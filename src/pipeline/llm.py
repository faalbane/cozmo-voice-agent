from livekit.plugins import openai


def create_llm() -> openai.LLM:
    """Create OpenAI LLM optimized for low TTFT in voice conversations."""
    return openai.LLM(
        model="gpt-4o-mini",
        temperature=0.7,
    )
