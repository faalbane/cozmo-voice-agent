from livekit.plugins import silero


def create_vad() -> silero.VAD:
    """Create Silero VAD tuned for telephony turn-taking.

    Parameters are tuned to balance responsiveness with avoiding
    false interrupts from background noise on phone lines.
    """
    return silero.VAD.load(
        min_speech_duration=0.1,
        min_silence_duration=0.5,
        padding_duration=0.1,
        max_buffered_speech=60.0,
        activation_threshold=0.5,
    )
