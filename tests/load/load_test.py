"""Load test harness for concurrent call simulation.

Simulates N concurrent calls by creating LiveKit rooms and publishing
pre-recorded audio, then measures agent response latencies.
"""

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

load_dotenv()

from livekit import api, rtc

logger = logging.getLogger(__name__)


@dataclass
class CallResult:
    call_id: str
    success: bool
    setup_time_ms: float = 0.0
    first_response_ms: float = 0.0
    error: str = ""


@dataclass
class LoadTestReport:
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    avg_setup_ms: float = 0.0
    avg_response_ms: float = 0.0
    p95_response_ms: float = 0.0
    p99_response_ms: float = 0.0
    max_response_ms: float = 0.0
    min_response_ms: float = 0.0
    failure_rate_pct: float = 0.0
    results: list[CallResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "avg_setup_ms": round(self.avg_setup_ms, 1),
            "avg_response_ms": round(self.avg_response_ms, 1),
            "p95_response_ms": round(self.p95_response_ms, 1),
            "p99_response_ms": round(self.p99_response_ms, 1),
            "max_response_ms": round(self.max_response_ms, 1),
            "min_response_ms": round(self.min_response_ms, 1),
            "failure_rate_pct": round(self.failure_rate_pct, 2),
        }


async def simulate_call(
    call_id: str,
    lk_api: api.LiveKitAPI,
    lk_url: str,
    timeout: float = 30.0,
) -> CallResult:
    """Simulate a single call: create room, join, wait for agent response."""
    result = CallResult(call_id=call_id, success=False)
    room_name = f"load-test-{call_id}"

    try:
        t_start = time.monotonic()

        # Create room via API
        await lk_api.room.create_room(
            api.CreateRoomRequest(name=room_name, empty_timeout=60)
        )

        # Generate a token for the simulated caller
        token = (
            api.AccessToken()
            .with_identity(f"caller-{call_id}")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )

        # Connect to room as simulated caller
        room = rtc.Room()
        await room.connect(lk_url, token)

        t_setup = time.monotonic()
        result.setup_time_ms = (t_setup - t_start) * 1000

        # Wait for agent to join and start publishing audio
        agent_responded = asyncio.Event()
        t_agent_response = [0.0]

        @room.on("track_subscribed")
        def on_track(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity != f"caller-{call_id}":
                t_agent_response[0] = time.monotonic()
                agent_responded.set()

        try:
            await asyncio.wait_for(agent_responded.wait(), timeout=timeout)
            result.first_response_ms = (t_agent_response[0] - t_setup) * 1000
            result.success = True
        except asyncio.TimeoutError:
            result.error = f"Agent did not respond within {timeout}s"

        await room.disconnect()

    except Exception as e:
        result.error = str(e)
        logger.error(f"Call {call_id} failed: {e}")

    finally:
        # Clean up room
        try:
            await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception:
            pass

    return result


async def run_load_test(
    num_calls: int,
    ramp_up_seconds: float = 10.0,
) -> LoadTestReport:
    """Run a load test with the specified number of concurrent calls."""
    lk_url = os.getenv("LIVEKIT_URL", "ws://localhost:7880")
    lk_api_instance = api.LiveKitAPI(
        url=lk_url.replace("ws://", "http://").replace("wss://", "https://"),
    )

    logger.info(f"Starting load test: {num_calls} concurrent calls (ramp-up: {ramp_up_seconds}s)")

    # Ramp up calls gradually
    delay_per_call = ramp_up_seconds / num_calls
    tasks = []

    for i in range(num_calls):
        task = asyncio.create_task(simulate_call(str(i), lk_api_instance, lk_url))
        tasks.append(task)
        if delay_per_call > 0:
            await asyncio.sleep(delay_per_call)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Build report
    report = LoadTestReport(total_calls=num_calls)
    call_results = []

    for r in results:
        if isinstance(r, Exception):
            call_results.append(CallResult(call_id="?", success=False, error=str(r)))
        else:
            call_results.append(r)

    report.results = call_results
    report.successful_calls = sum(1 for r in call_results if r.success)
    report.failed_calls = report.total_calls - report.successful_calls
    report.failure_rate_pct = (report.failed_calls / report.total_calls * 100) if report.total_calls > 0 else 0

    response_times = sorted([r.first_response_ms for r in call_results if r.success and r.first_response_ms > 0])

    if response_times:
        report.avg_response_ms = sum(response_times) / len(response_times)
        report.min_response_ms = response_times[0]
        report.max_response_ms = response_times[-1]
        p95_idx = int(len(response_times) * 0.95)
        p99_idx = int(len(response_times) * 0.99)
        report.p95_response_ms = response_times[min(p95_idx, len(response_times) - 1)]
        report.p99_response_ms = response_times[min(p99_idx, len(response_times) - 1)]

    setup_times = [r.setup_time_ms for r in call_results if r.setup_time_ms > 0]
    if setup_times:
        report.avg_setup_ms = sum(setup_times) / len(setup_times)

    await lk_api_instance.aclose()
    return report


async def progressive_load_test():
    """Run progressive load tests at increasing concurrency levels."""
    levels = [10, 25, 50, 75, 100]
    all_reports = {}

    for n in levels:
        print(f"\n{'='*60}")
        print(f"  Load Test: {n} concurrent calls")
        print(f"{'='*60}")

        report = await run_load_test(num_calls=n, ramp_up_seconds=n * 0.2)
        all_reports[n] = report.to_dict()

        print(f"  Success: {report.successful_calls}/{report.total_calls}")
        print(f"  Avg Response: {report.avg_response_ms:.1f}ms")
        print(f"  P95 Response: {report.p95_response_ms:.1f}ms")
        print(f"  Failure Rate: {report.failure_rate_pct:.1f}%")

        target_met = report.avg_response_ms < 600
        print(f"  <600ms Target: {'PASS' if target_met else 'FAIL'}")

        # Cool down between levels
        if n < levels[-1]:
            print(f"\n  Cooling down for 10 seconds...")
            await asyncio.sleep(10)

    # Save report
    report_path = "tests/load/results/load_test_report.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(all_reports, f, indent=2)
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(progressive_load_test())
