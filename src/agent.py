"""Core voice agent built with Pipecat.

Supports two transport modes:
  - WebSocket: for local dev and web-based demo (no external accounts needed)
  - Daily: for production WebRTC with PSTN via Twilio SIP
"""

import asyncio
import logging
import os
import time

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndFrame, LLMMessagesFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.groq import GroqLLMService

from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.knowledge_lookup import register_knowledge_tools
from src.metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)


async def create_agent_pipeline(transport, call_id: str = "local"):
    """Build the Pipecat voice pipeline with STT → LLM → TTS.

    Args:
        transport: A Pipecat transport (WebSocket, Daily, or local).
        call_id: Identifier for this call session.
    """
    metrics = MetricsCollector()
    metrics.call_started(call_id)

    # --- STT ---
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        name="deepgram-stt",
    )

    # --- LLM ---
    llm = GroqLLMService(
        api_key=os.getenv("GROQ_API_KEY"),
        model="llama-3.1-8b-instant",
        name="groq-llm",
    )

    # --- TTS ---
    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"),
        voice_id="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Lady
        name="cartesia-tts",
    )

    # --- Conversation context ---
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    context = OpenAILLMContext(messages=messages)
    context_aggregator = llm.create_context_aggregator(context)

    # Knowledge is embedded in system prompt — no tool calling needed
    # (Groq/Llama doesn't reliably support function calling)

    # --- Timing hooks for latency instrumentation ---
    turn_start = [0.0]

    @stt.event_handler("on_transcript")
    async def on_transcript(transcript):
        if transcript.strip():
            turn_start[0] = time.monotonic()

    # --- Build pipeline ---
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            enable_metrics=True,
        ),
    )

    # --- Metrics callback ---
    @task.event_handler("on_metrics")
    async def on_metrics(metrics_data):
        try:
            if hasattr(metrics_data, "ttfb") and turn_start[0] > 0:
                e2e = time.monotonic() - turn_start[0]
                metrics.record_e2e_latency(e2e)
        except Exception as e:
            logger.debug(f"Metrics recording error: {e}")

    # --- Send initial greeting directly via TTS (skips LLM for instant response) ---
    GREETING = "Hello! Thank you for calling ShopEase. My name is Alex. How can I help you today?"

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant(transport, participant):
        logger.info(f"Participant joined call {call_id}")
        # Send directly to TTS — no LLM round-trip needed for the greeting
        await task.queue_frames([TTSSpeakFrame(text=GREETING)])
        # Also add to context so LLM knows what it said
        context.add_message({"role": "assistant", "content": GREETING})

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.info(f"Participant left call {call_id}: {reason}")
        metrics.call_ended(call_id)
        await task.queue_frame(EndFrame())

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info(f"Client connected to call {call_id}")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info(f"Client disconnected from call {call_id}")
        metrics.call_ended(call_id)
        await task.queue_frame(EndFrame())

    return task


async def run_websocket_agent(host: str = "0.0.0.0", port: int = 8765):
    """Run the agent with a WebSocket transport (local dev / web demo)."""
    from pipecat.transports.websocket.server import (
        WebsocketServerParams,
        WebsocketServerTransport,
    )
    from pipecat.serializers.protobuf import ProtobufFrameSerializer

    transport = WebsocketServerTransport(
        params=WebsocketServerParams(
            host=host,
            port=port,
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=ProtobufFrameSerializer(),
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    min_volume=0.3,
                    start_secs=0.1,
                    stop_secs=0.15,
                    confidence=0.6,
                )
            ),
            vad_audio_passthrough=True,
        )
    )

    logger.info(f"Starting WebSocket voice agent on ws://{host}:{port}")
    task = await create_agent_pipeline(transport, call_id=f"ws-{port}")

    runner = PipelineRunner()
    await runner.run(task)


async def run_daily_agent(room_url: str, token: str, call_id: str = "daily"):
    """Run the agent with Daily.co WebRTC transport (production / PSTN)."""
    from pipecat.transports.services.daily import DailyParams, DailyTransport

    transport = DailyTransport(
        room_url=room_url,
        token=token,
        bot_name="ShopEase Agent",
        params=DailyParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(
                params=VADParams(
                    min_volume=0.3,
                    start_secs=0.1,
                    stop_secs=0.15,
                    confidence=0.6,
                )
            ),
            vad_audio_passthrough=True,
        ),
    )

    logger.info(f"Starting Daily.co voice agent for room: {room_url}")
    task = await create_agent_pipeline(transport, call_id=call_id)

    runner = PipelineRunner()
    await runner.run(task)
