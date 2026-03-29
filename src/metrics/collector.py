"""Prometheus metrics for the voice agent system."""

import logging
import time

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

logger = logging.getLogger(__name__)

# --- Histograms (latency) ---

VOICE_LATENCY_BUCKETS = (0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0, 5.0)

e2e_latency = Histogram(
    "voice_agent_e2e_latency_seconds",
    "End-to-end latency from user speech end to first TTS audio byte",
    buckets=VOICE_LATENCY_BUCKETS,
)

stt_latency = Histogram(
    "voice_agent_stt_duration_seconds",
    "Time for speech-to-text transcription",
    buckets=VOICE_LATENCY_BUCKETS,
)

llm_ttft = Histogram(
    "voice_agent_llm_ttft_seconds",
    "LLM time to first token",
    buckets=VOICE_LATENCY_BUCKETS,
)

tts_ttfb = Histogram(
    "voice_agent_tts_ttfb_seconds",
    "TTS time to first audio byte",
    buckets=VOICE_LATENCY_BUCKETS,
)

agent_response_time = Histogram(
    "voice_agent_response_time_seconds",
    "Total agent response time (STT + LLM + TTS)",
    buckets=VOICE_LATENCY_BUCKETS,
)

# --- Counters ---

calls_total = Counter(
    "voice_agent_calls_total",
    "Total number of calls handled",
    ["status"],  # completed, failed, dropped
)

call_setup_failures = Counter(
    "voice_agent_call_setup_failures_total",
    "Number of failed call setups",
)

tool_calls_total = Counter(
    "voice_agent_tool_calls_total",
    "Number of knowledge base tool calls",
    ["tool_name"],
)

# --- Gauges ---

concurrent_calls = Gauge(
    "voice_agent_concurrent_calls",
    "Number of currently active calls",
)

# --- Call Quality ---

mos_score = Histogram(
    "voice_agent_mos_score",
    "Estimated Mean Opinion Score",
    buckets=(1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0),
)

jitter_ms = Histogram(
    "voice_agent_jitter_ms",
    "Audio jitter in milliseconds",
    buckets=(1, 2, 5, 10, 20, 30, 50, 100),
)

packet_loss_pct = Histogram(
    "voice_agent_packet_loss_percent",
    "Packet loss percentage",
    buckets=(0, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0),
)


class MetricsCollector:
    """Convenience wrapper for recording voice agent metrics."""

    def record_e2e_latency(self, seconds: float) -> None:
        """Record end-to-end latency for a single conversational turn."""
        e2e_latency.observe(seconds)
        agent_response_time.observe(seconds)

    def record_pipeline_metrics(self, metrics) -> None:
        """Record metrics from pipeline callbacks.

        The metrics object contains per-turn timing breakdowns.
        """
        try:
            if hasattr(metrics, "stt_duration"):
                stt_latency.observe(metrics.stt_duration)

            if hasattr(metrics, "llm_ttft"):
                llm_ttft.observe(metrics.llm_ttft)

            if hasattr(metrics, "tts_ttfb"):
                tts_ttfb.observe(metrics.tts_ttfb)

            # End-to-end: sum of all pipeline stages
            if hasattr(metrics, "stt_duration") and hasattr(metrics, "llm_ttft") and hasattr(metrics, "tts_ttfb"):
                total = metrics.stt_duration + metrics.llm_ttft + metrics.tts_ttfb
                e2e_latency.observe(total)
                agent_response_time.observe(total)

        except Exception as e:
            logger.error(f"Failed to record pipeline metrics: {e}")

    def record_call_quality(self, jitter: float, loss: float, estimated_mos: float) -> None:
        """Record call quality metrics from RTC stats."""
        jitter_ms.observe(jitter)
        packet_loss_pct.observe(loss)
        mos_score.observe(estimated_mos)

    def call_started(self, call_sid: str) -> None:
        concurrent_calls.inc()
        logger.info(f"Call started: {call_sid} (concurrent: {concurrent_calls._value.get()})")

    def call_ended(self, call_sid: str) -> None:
        concurrent_calls.dec()
        calls_total.labels(status="completed").inc()

    def call_failed(self, call_sid: str) -> None:
        concurrent_calls.dec()
        calls_total.labels(status="failed").inc()

    def call_setup_failed(self) -> None:
        call_setup_failures.inc()
        calls_total.labels(status="failed").inc()


def start_metrics_server(port: int = 9100) -> None:
    """Start Prometheus metrics HTTP server."""
    try:
        start_http_server(port)
        logger.info(f"Prometheus metrics server started on port {port}")
    except OSError as e:
        logger.warning(f"Metrics server already running or port {port} in use: {e}")
