"""Failure recovery mechanisms for the voice agent system."""

import asyncio
import logging
import os

import psutil

logger = logging.getLogger(__name__)

# Thresholds for health checks
_CPU_CRITICAL = 90.0
_MEMORY_CRITICAL = 90.0
_MAX_CONCURRENT_CALLS = int(os.getenv("AGENT_MAX_CONCURRENT_CALLS", "20"))


def check_worker_health() -> bool:
    """Check if the worker is healthy enough to accept new calls.

    Returns True if the worker can handle more work, False if it should
    stop accepting calls.
    """
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory().percent

        if cpu > _CPU_CRITICAL:
            logger.warning(f"CPU critical: {cpu}%")
            return False

        if memory > _MEMORY_CRITICAL:
            logger.warning(f"Memory critical: {memory}%")
            return False

        return True

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return False


async def llm_with_timeout(
    coro,
    timeout_seconds: float = 4.0,
    fallback_response: str = "I'm sorry, let me take a moment. Could you repeat that?",
) -> str:
    """Wrap an LLM call with a timeout and fallback response.

    If the LLM doesn't respond within the timeout, returns a canned
    response to maintain conversational flow rather than leaving silence.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        logger.warning(f"LLM timeout after {timeout_seconds}s, using fallback")
        return fallback_response
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return fallback_response


class CircuitBreaker:
    """Simple circuit breaker for external service calls.

    Opens the circuit (stops calling) after consecutive failures,
    then periodically allows a test call to check recovery.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._state = "closed"  # closed = normal, open = blocking, half_open = testing
        self._last_failure_time = 0.0

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            import time
            if time.monotonic() - self._last_failure_time > self.recovery_timeout:
                self._state = "half_open"
                return False
            return True
        return False

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        import time
        self._failures += 1
        self._last_failure_time = time.monotonic()
        if self._failures >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                f"Circuit breaker opened after {self._failures} consecutive failures"
            )


def get_health_status() -> dict:
    """Return a health status dict suitable for a /healthz endpoint."""
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()

        healthy = cpu < _CPU_CRITICAL and memory.percent < _MEMORY_CRITICAL

        return {
            "status": "healthy" if healthy else "unhealthy",
            "cpu_percent": cpu,
            "memory_percent": memory.percent,
            "memory_available_mb": round(memory.available / 1024 / 1024),
            "pid": os.getpid(),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
