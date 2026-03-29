"""Silero VAD configuration for Pipecat."""

from pipecat.audio.vad.silero import SileroVADAnalyzer


def create_vad() -> SileroVADAnalyzer:
    return SileroVADAnalyzer(
        params=SileroVADAnalyzer.VADParams(
            min_volume=0.4,
            stop_secs=0.5,
        )
    )
