"""Core voice agent: wires VoicePipelineAgent with STT/LLM/TTS and event hooks."""

import logging

from livekit.agents import JobContext, AgentSession, llm
from livekit.agents.voice import AgentTranscriptionOptions
from livekit.agents.voice import VoicePipelineAgent
from livekit import rtc

from src.pipeline.stt import create_stt
from src.pipeline.llm import create_llm
from src.pipeline.tts import create_tts
from src.pipeline.vad import create_vad
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.knowledge_lookup import AgentTools
from src.knowledge.vectordb import KnowledgeBase
from src.metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)


async def entrypoint(ctx: JobContext) -> None:
    """Main entrypoint for each voice agent session (one per call)."""
    logger.info(f"Agent session starting for room {ctx.room.name}")

    # Connect to the LiveKit room
    await ctx.connect()

    # Initialize knowledge base and tools
    kb = KnowledgeBase()
    tools = AgentTools(knowledge_base=kb)

    # Initialize metrics collector
    metrics = MetricsCollector()

    # Build the initial chat context with system prompt
    initial_ctx = llm.ChatContext()
    initial_ctx.append(role="system", text=SYSTEM_PROMPT)

    # Create the voice pipeline agent
    agent = VoicePipelineAgent(
        vad=create_vad(),
        stt=create_stt(),
        llm=create_llm(),
        tts=create_tts(),
        fnc_ctx=tools,
        chat_ctx=initial_ctx,
        # Barge-in: allow interruption after detecting 0.5s of user speech
        interrupt_speech_duration=0.5,
        interrupt_min_words=2,
        # Turn-taking: minimum silence before considering end of turn
        min_endpointing_delay=0.5,
        # Transcription options for observability
        transcription=AgentTranscriptionOptions(
            user_transcription=True,
            agent_transcription=True,
        ),
    )

    # Register metrics collection callback
    @agent.on("metrics_collected")
    def on_metrics(agent_metrics):
        metrics.record_pipeline_metrics(agent_metrics)

    # Track call state
    call_sid = ctx.room.name
    metrics.call_started(call_sid)

    @ctx.on("disconnect")
    def on_disconnect():
        metrics.call_ended(call_sid)
        logger.info(f"Call ended: {call_sid}")

    # Wait for a participant (the caller) to join
    participant = await ctx.wait_for_participant()
    logger.info(f"Caller joined: {participant.identity} in room {call_sid}")

    # Start the agent and greet the caller
    agent.start(ctx.room, participant)
    await agent.say(
        "Hello! Thank you for calling ShopEase. My name is Alex. How can I help you today?",
        allow_interruptions=True,
    )
