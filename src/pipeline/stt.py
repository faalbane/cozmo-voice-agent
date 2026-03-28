from livekit.plugins import deepgram


def create_stt() -> deepgram.STT:
    """Create Deepgram STT with streaming optimized for low latency."""
    return deepgram.STT(
        model="nova-2",
        language="en",
        smart_format=True,
        no_delay=True,
        interim_results=True,
        endpointing=300,
    )
