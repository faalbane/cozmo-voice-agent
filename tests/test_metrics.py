"""Tests for metrics and call quality calculations."""

import pytest

from src.metrics.call_quality import estimate_mos, assess_quality
from src.metrics.latency import LatencyTrace, LatencyTracker


class TestMOSEstimation:
    def test_excellent_conditions(self):
        mos = estimate_mos(latency_ms=50, jitter_ms=1, packet_loss_pct=0)
        assert mos >= 4.0
        assert assess_quality(mos) == "Excellent"

    def test_good_conditions(self):
        mos = estimate_mos(latency_ms=100, jitter_ms=10, packet_loss_pct=0.5)
        assert mos >= 3.5

    def test_poor_conditions(self):
        mos = estimate_mos(latency_ms=300, jitter_ms=50, packet_loss_pct=5)
        assert mos < 3.5

    def test_terrible_conditions(self):
        mos = estimate_mos(latency_ms=500, jitter_ms=100, packet_loss_pct=20)
        assert mos < 2.5

    def test_mos_range(self):
        """MOS should always be between 1.0 and 4.5."""
        for latency in [0, 50, 100, 200, 500, 1000]:
            for jitter in [0, 5, 20, 50, 100]:
                for loss in [0, 1, 5, 10, 30]:
                    mos = estimate_mos(latency, jitter, loss)
                    assert 1.0 <= mos <= 4.5, f"MOS {mos} out of range for ({latency}, {jitter}, {loss})"


class TestLatencyTracker:
    def test_single_turn(self):
        tracker = LatencyTracker("test-call")
        trace = tracker.start_turn()
        trace.user_speech_end = 1000.0
        trace.stt_result = 1000.15
        trace.llm_first_token = 1000.35
        trace.tts_first_byte = 1000.45
        trace.tts_playout_start = 1000.50

        assert abs(trace.stt_duration - 0.15) < 0.001
        assert abs(trace.llm_ttft - 0.20) < 0.001
        assert abs(trace.tts_ttfb - 0.10) < 0.001
        assert abs(trace.e2e_latency - 0.50) < 0.001

    def test_summary(self):
        trace = LatencyTrace(turn_id=1)
        trace.user_speech_end = 0.0
        trace.stt_result = 0.15
        trace.llm_first_token = 0.35
        trace.tts_first_byte = 0.45
        trace.tts_playout_start = 0.50

        summary = trace.summary()
        assert summary["stt_ms"] == 150.0
        assert summary["llm_ttft_ms"] == 200.0
        assert summary["tts_ttfb_ms"] == 100.0
        assert summary["e2e_ms"] == 500.0

    def test_stats_aggregation(self):
        tracker = LatencyTracker("test-call")

        for i in range(10):
            trace = tracker.start_turn()
            trace.user_speech_end = float(i * 10)
            trace.tts_playout_start = float(i * 10) + 0.5
            tracker.traces.append(trace)

        stats = tracker.get_stats()
        assert stats["turns"] == 10
        assert stats["avg_e2e_ms"] == 500.0

    def test_empty_stats(self):
        tracker = LatencyTracker("test-call")
        stats = tracker.get_stats()
        assert stats["turns"] == 0


class TestAssessQuality:
    def test_quality_levels(self):
        assert assess_quality(4.5) == "Excellent"
        assert assess_quality(4.0) == "Excellent"
        assert assess_quality(3.8) == "Good"
        assert assess_quality(3.3) == "Fair"
        assert assess_quality(2.8) == "Poor"
        assert assess_quality(2.0) == "Bad"
