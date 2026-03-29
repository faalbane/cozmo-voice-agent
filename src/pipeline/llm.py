"""OpenAI LLM configuration for Pipecat."""

import os

from pipecat.services.openai import OpenAILLMService


def create_llm() -> OpenAILLMService:
    return OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o-mini",
    )
