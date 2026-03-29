"""Deepgram STT configuration for Pipecat."""

import os

from pipecat.services.deepgram.stt import DeepgramSTTService


def create_stt() -> DeepgramSTTService:
    return DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))
