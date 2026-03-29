"""Cartesia TTS configuration for Pipecat."""

import os

from pipecat.services.cartesia import CartesiaTTSService


def create_tts() -> CartesiaTTSService:
    return CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",
    )
