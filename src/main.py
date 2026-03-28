"""Entrypoint for the voice agent worker process."""

import logging
import os

from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    JobRequest,
    WorkerOptions,
    WorkerType,
    cli,
)

from src.agent import entrypoint
from src.knowledge.vectordb import KnowledgeBase
from src.metrics.collector import MetricsCollector, start_metrics_server
from src.resilience.recovery import check_worker_health

load_dotenv()

logger = logging.getLogger(__name__)


async def request_fnc(req: JobRequest) -> AutoSubscribe:
    """Decide whether to accept an incoming call job.

    Rejects if the worker is overloaded based on health checks.
    """
    if not check_worker_health():
        logger.warning("Worker unhealthy, rejecting job")
        await req.reject()
        MetricsCollector().call_setup_failed()
        return AutoSubscribe.AUDIO_ONLY

    logger.info(f"Accepting job for room {req.room.name}")
    await req.accept(entrypoint, auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    return AutoSubscribe.AUDIO_ONLY


def prewarm_fnc(proc: JobProcess) -> None:
    """Pre-initialize heavy resources before accepting calls.

    This runs once per subprocess and ensures the first call
    doesn't pay cold-start latency for model loading.
    """
    logger.info("Pre-warming worker process...")

    # Pre-load Silero VAD model (downloads on first use)
    from livekit.plugins import silero
    silero.VAD.load()

    # Initialize knowledge base connection
    try:
        kb = KnowledgeBase()
        logger.info(f"Knowledge base ready with {kb.collection_count()} documents")
    except Exception as e:
        logger.warning(f"Knowledge base not available during prewarm: {e}")

    # Start Prometheus metrics server
    metrics_port = int(os.getenv("METRICS_PORT", "9100"))
    start_metrics_server(metrics_port)

    logger.info("Worker pre-warm complete")


def load_fnc() -> float:
    """Report current worker load as a normalized 0-1 value.

    LiveKit uses this to decide whether to dispatch new jobs to this worker.
    When load exceeds the threshold, the worker stops receiving new calls.
    """
    import psutil

    cpu = psutil.cpu_percent(interval=0.1) / 100.0
    memory = psutil.virtual_memory().percent / 100.0

    # Weighted: CPU matters more for real-time audio processing
    load = (cpu * 0.6) + (memory * 0.4)
    return min(load, 1.0)


if __name__ == "__main__":
    load_threshold = float(os.getenv("AGENT_WORKER_LOAD_THRESHOLD", "0.65"))

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            request_fnc=request_fnc,
            prewarm_fnc=prewarm_fnc,
            load_fnc=load_fnc,
            load_threshold=load_threshold,
            worker_type=WorkerType.ROOM,
            # Pre-fork 3 idle processes for instant call pickup
            num_idle_processes=3,
        ),
    )
