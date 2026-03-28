"""Redis-backed call state tracking for active calls."""

import json
import logging
import os
import time

import redis

logger = logging.getLogger(__name__)

_ACTIVE_CALLS_KEY = "voice_agent:active_calls"
_CALL_PREFIX = "voice_agent:call:"
_CALL_TTL = 3600  # 1 hour max call duration


class CallStateManager:
    """Track active calls in Redis for cross-worker visibility and recovery."""

    def __init__(self) -> None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._worker_id = os.getenv("HOSTNAME", f"worker-{os.getpid()}")

    def register_call(self, call_sid: str, caller_id: str = "") -> None:
        """Register a new active call."""
        call_data = {
            "call_sid": call_sid,
            "caller_id": caller_id,
            "worker_id": self._worker_id,
            "started_at": time.time(),
            "status": "active",
        }
        pipe = self._redis.pipeline()
        pipe.hset(f"{_CALL_PREFIX}{call_sid}", mapping=call_data)
        pipe.expire(f"{_CALL_PREFIX}{call_sid}", _CALL_TTL)
        pipe.sadd(_ACTIVE_CALLS_KEY, call_sid)
        pipe.execute()
        logger.info(f"Registered call {call_sid} on worker {self._worker_id}")

    def end_call(self, call_sid: str) -> None:
        """Mark a call as ended and remove from active set."""
        pipe = self._redis.pipeline()
        pipe.hset(f"{_CALL_PREFIX}{call_sid}", "status", "completed")
        pipe.hset(f"{_CALL_PREFIX}{call_sid}", "ended_at", str(time.time()))
        pipe.srem(_ACTIVE_CALLS_KEY, call_sid)
        pipe.expire(f"{_CALL_PREFIX}{call_sid}", 300)  # Keep metadata 5 min after end
        pipe.execute()
        logger.info(f"Ended call {call_sid}")

    def fail_call(self, call_sid: str, reason: str = "") -> None:
        """Mark a call as failed."""
        pipe = self._redis.pipeline()
        pipe.hset(f"{_CALL_PREFIX}{call_sid}", mapping={
            "status": "failed",
            "ended_at": str(time.time()),
            "failure_reason": reason,
        })
        pipe.srem(_ACTIVE_CALLS_KEY, call_sid)
        pipe.expire(f"{_CALL_PREFIX}{call_sid}", 300)
        pipe.execute()
        logger.warning(f"Call {call_sid} failed: {reason}")

    def get_active_calls(self) -> list[dict]:
        """Get all currently active calls across all workers."""
        call_sids = self._redis.smembers(_ACTIVE_CALLS_KEY)
        calls = []
        for sid in call_sids:
            data = self._redis.hgetall(f"{_CALL_PREFIX}{sid}")
            if data:
                calls.append(data)
        return calls

    def get_active_count(self) -> int:
        """Get the number of currently active calls."""
        return self._redis.scard(_ACTIVE_CALLS_KEY)

    def get_call(self, call_sid: str) -> dict | None:
        """Get details for a specific call."""
        data = self._redis.hgetall(f"{_CALL_PREFIX}{call_sid}")
        return data if data else None

    def cleanup_orphaned_calls(self, max_age_seconds: int = 7200) -> int:
        """Clean up calls that may have been orphaned by crashed workers."""
        call_sids = self._redis.smembers(_ACTIVE_CALLS_KEY)
        cleaned = 0
        now = time.time()

        for sid in call_sids:
            data = self._redis.hgetall(f"{_CALL_PREFIX}{sid}")
            if not data:
                self._redis.srem(_ACTIVE_CALLS_KEY, sid)
                cleaned += 1
                continue

            started_at = float(data.get("started_at", 0))
            if now - started_at > max_age_seconds:
                self.fail_call(sid, reason="orphaned_cleanup")
                cleaned += 1

        if cleaned:
            logger.info(f"Cleaned up {cleaned} orphaned calls")
        return cleaned
