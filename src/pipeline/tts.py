from livekit.plugins import cartesia


def create_tts() -> cartesia.TTS:
    """Create Cartesia TTS with streaming for minimal TTFB."""
    return cartesia.TTS(
        model="sonic-2",
        voice="71a7ad14-091c-4e8e-a314-022ece01c121",  # "British Reading Lady"
        language="en",
        speed=1.0,
        emotion=["positivity:high", "curiosity"],
    )
