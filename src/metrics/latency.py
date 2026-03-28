"""End-to-end latency instrumentation for the voice pipeline.

Hooks into VoicePipelineAgent events to measure per-segment latencies
and compute the full speech-to-speech round-trip time.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LatencyTrace:
    """Tracks timing for a single conversational turn."""

    turn_id: int = 0
    user_speech_end: float = 0.0
    stt_result: float = 0.0
    llm_first_token: float = 0.0
    tts_first_byte: float = 0.0
    tts_playout_start: float = 0.0

    @property
    def stt_duration(self) -> float:
        if self.stt_result and self.user_speech_end:
            return self.stt_result - self.user_speech_end
        return 0.0

    @property
    def llm_ttft(self) -> float:
        if self.llm_first_token and self.stt_result:
            return self.llm_first_token - self.stt_result
        return 0.0

    @property
    def tts_ttfb(self) -> float:
        if self.tts_first_byte and self.llm_first_token:
            return self.tts_first_byte - self.llm_first_token
        return 0.0

    @property
    def e2e_latency(self) -> float:
        if self.tts_playout_start and self.user_speech_end:
            return self.tts_playout_start - self.user_speech_end
        return 0.0

    def summary(self) -> dict:
        return {
            "turn_id": self.turn_id,
            "stt_ms": round(self.stt_duration * 1000, 1),
            "llm_ttft_ms": round(self.llm_ttft * 1000, 1),
            "tts_ttfb_ms": round(self.tts_ttfb * 1000, 1),
            "e2e_ms": round(self.e2e_latency * 1000, 1),
        }


class LatencyTracker:
    """Tracks latency across multiple conversational turns in a call."""

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.traces: list[LatencyTrace] = []
        self._current: LatencyTrace | None = None
        self._turn_counter = 0

    def start_turn(self) -> LatencyTrace:
        self._turn_counter += 1
        self._current = LatencyTrace(turn_id=self._turn_counter)
        return self._current

    def mark_user_speech_end(self) -> None:
        if self._current is None:
            self.start_turn()
        self._current.user_speech_end = time.monotonic()

    def mark_stt_result(self) -> None:
        if self._current:
            self._current.stt_result = time.monotonic()

    def mark_llm_first_token(self) -> None:
        if self._current:
            self._current.llm_first_token = time.monotonic()

    def mark_tts_first_byte(self) -> None:
        if self._current:
            self._current.tts_first_byte = time.monotonic()

    def mark_tts_playout_start(self) -> None:
        if self._current:
            self._current.tts_playout_start = time.monotonic()
            self.traces.append(self._current)
            logger.info(
                f"[{self.call_id}] Turn {self._current.turn_id} latency: "
                f"{self._current.summary()}"
            )
            self._current = None

    def get_stats(self) -> dict:
        """Compute aggregate stats across all turns."""
        if not self.traces:
            return {"turns": 0}

        e2e_values = [t.e2e_latency for t in self.traces if t.e2e_latency > 0]
        if not e2e_values:
            return {"turns": len(self.traces)}

        sorted_e2e = sorted(e2e_values)
        p95_idx = int(len(sorted_e2e) * 0.95)

        return {
            "turns": len(self.traces),
            "avg_e2e_ms": round(sum(e2e_values) / len(e2e_values) * 1000, 1),
            "p95_e2e_ms": round(sorted_e2e[min(p95_idx, len(sorted_e2e) - 1)] * 1000, 1),
            "min_e2e_ms": round(sorted_e2e[0] * 1000, 1),
            "max_e2e_ms": round(sorted_e2e[-1] * 1000, 1),
        }
