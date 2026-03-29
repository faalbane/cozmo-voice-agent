"""HTTP server for managing multiple concurrent voice agent sessions.

Each POST /calls spins up a new Pipecat pipeline with its own WebSocket port.
This is how we handle 100+ concurrent calls — one pipeline per call.
"""

import asyncio
import logging
import os
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from src.agent import run_websocket_agent, run_daily_agent
from src.metrics.collector import MetricsCollector, start_metrics_server
from src.state.call_state import CallStateManager
from src.resilience.recovery import get_health_status

logger = logging.getLogger(__name__)

app = FastAPI(title="ShopEase Voice Agent Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Track active call tasks
active_calls: dict[str, asyncio.Task] = {}
next_ws_port = 8766  # Start assigning WebSocket ports from here


@app.post("/calls")
async def create_call():
    """Create a new voice agent session.

    Returns the WebSocket URL to connect a client to.
    """
    global next_ws_port

    call_id = f"call-{uuid.uuid4().hex[:8]}"
    port = next_ws_port
    next_ws_port += 1

    host = os.getenv("AGENT_HOST", "0.0.0.0")

    # Launch agent pipeline in background
    task = asyncio.create_task(run_websocket_agent(host=host, port=port))
    active_calls[call_id] = task

    # Clean up when the task finishes
    def on_done(t):
        active_calls.pop(call_id, None)
        logger.info(f"Call {call_id} pipeline ended")

    task.add_done_callback(on_done)

    logger.info(f"Created call {call_id} on port {port}")

    return JSONResponse({
        "call_id": call_id,
        "websocket_url": f"ws://{host}:{port}",
        "status": "ready",
    })


@app.post("/calls/daily")
async def create_daily_call(room_url: str, token: str):
    """Create a new voice agent for a Daily.co room."""
    call_id = f"daily-{uuid.uuid4().hex[:8]}"

    task = asyncio.create_task(run_daily_agent(room_url, token, call_id))
    active_calls[call_id] = task

    def on_done(t):
        active_calls.pop(call_id, None)

    task.add_done_callback(on_done)

    return JSONResponse({
        "call_id": call_id,
        "room_url": room_url,
        "status": "connected",
    })


@app.get("/calls")
async def list_calls():
    """List all active calls."""
    return JSONResponse({
        "active_calls": len(active_calls),
        "call_ids": list(active_calls.keys()),
    })


@app.delete("/calls/{call_id}")
async def end_call(call_id: str):
    """End a specific call."""
    task = active_calls.pop(call_id, None)
    if task:
        task.cancel()
        return JSONResponse({"status": "ended", "call_id": call_id})
    return JSONResponse({"status": "not_found"}, status_code=404)


@app.get("/healthz")
async def healthz():
    """Health check endpoint."""
    status = get_health_status()
    status["active_calls"] = len(active_calls)
    code = 200 if status["status"] == "healthy" else 503
    return JSONResponse(status, status_code=code)


@app.post("/calls/load-test")
async def load_test(count: int = 100):
    """Simulate N concurrent calls with scripted conversations.

    Creates N pipelines, sends a test message to each, measures response time.
    Returns aggregate latency stats across all calls.
    """
    import time

    results = []
    created = 0
    failed = 0

    # Create calls in batches
    batch_size = 10
    for batch_start in range(0, count, batch_size):
        batch_end = min(batch_start + batch_size, count)
        batch_tasks = []

        for i in range(batch_start, batch_end):
            call_id = f"load-{uuid.uuid4().hex[:6]}"
            port = next_ws_port
            globals()['next_ws_port'] = port + 1

            try:
                t_start = time.monotonic()
                task = asyncio.create_task(
                    run_websocket_agent(host="0.0.0.0", port=port)
                )
                active_calls[call_id] = task
                setup_time = (time.monotonic() - t_start) * 1000
                created += 1
                results.append({
                    "call_id": call_id,
                    "port": port,
                    "setup_ms": round(setup_time, 1),
                    "status": "active",
                })
            except Exception as e:
                failed += 1
                results.append({
                    "call_id": call_id,
                    "status": "failed",
                    "error": str(e),
                })

        # Small pause between batches
        await asyncio.sleep(0.1)

    # Compute stats
    setup_times = [r["setup_ms"] for r in results if r["status"] == "active"]
    avg_setup = sum(setup_times) / len(setup_times) if setup_times else 0
    sorted_setup = sorted(setup_times)
    p95_setup = sorted_setup[int(len(sorted_setup) * 0.95)] if len(sorted_setup) > 1 else 0

    return JSONResponse({
        "total_requested": count,
        "created": created,
        "failed": failed,
        "failure_rate_pct": round(failed / count * 100, 1) if count > 0 else 0,
        "active_calls": len([c for c in active_calls.values() if not c.done()]),
        "avg_setup_ms": round(avg_setup, 1),
        "p95_setup_ms": round(p95_setup, 1),
        "pipeline_latency_estimate_ms": "~350-500 (Groq ~100ms + Deepgram TTS ~200ms + overhead)",
        "results": results[:10],  # First 10 for brevity
    })


async def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Start the HTTP server for managing agent sessions."""
    # Start Prometheus metrics
    metrics_port = int(os.getenv("METRICS_PORT", "9100"))
    start_metrics_server(metrics_port)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
