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
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    LLMMessagesFrame,
    OutputTransportMessageFrame,
    TTSSpeakFrame,
    TranscriptionFrame,
    TTSStartedFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.deepgram.tts import DeepgramTTSService
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

    # --- TTS (Deepgram Aura — ~200ms TTFB vs Cartesia ~850ms) ---
    tts = DeepgramTTSService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        voice="aura-asteria-en",
        name="deepgram-tts",
    )

    # --- Conversation context ---
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    context = OpenAILLMContext(messages=messages)
    context_aggregator = llm.create_context_aggregator(context)

    # --- Knowledge base (keyword search) ---
    # Augments the system prompt with relevant KB results per turn.
    from src.knowledge.search import search_knowledge

    class KBLookupProcessor(FrameProcessor):
        """Searches knowledge base on each user transcript and injects context."""

        def __init__(self):
            super().__init__(name="kb-lookup")

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)

            if isinstance(frame, TranscriptionFrame) and frame.text.strip():
                kb_result = search_knowledge(frame.text)
                if kb_result:
                    logger.info(f"[KB] Found results for: {frame.text[:50]}")
                    # Update system message with KB context
                    if context.messages and context.messages[0]["role"] == "system":
                        base_prompt = SYSTEM_PROMPT
                        context.messages[0]["content"] = (
                            base_prompt + "\n\n## Relevant Knowledge for This Query:\n" + kb_result
                        )

            await self.push_frame(frame, direction)

    kb_processor = KBLookupProcessor()

    # --- Server-side latency measurement processor ---
    class LatencyMeasurer(FrameProcessor):
        """Measures actual pipeline latency: transcription → first TTS output."""

        def __init__(self):
            super().__init__(name="latency-measurer")
            self._turn_start = 0.0
            self._waiting = False
            self.latencies = []

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)

            if isinstance(frame, TranscriptionFrame) and frame.text.strip():
                self._turn_start = time.monotonic()
                self._waiting = True

            if isinstance(frame, TTSStartedFrame) and self._waiting and self._turn_start > 0:
                latency_ms = (time.monotonic() - self._turn_start) * 1000
                self._waiting = False
                self.latencies.append(latency_ms)
                logger.info(f"[LATENCY] Pipeline E2E: {latency_ms:.0f}ms (turn {len(self.latencies)})")

                # Send latency to client via transport message
                avg = sum(self.latencies) / len(self.latencies)
                sorted_l = sorted(self.latencies)
                p95 = sorted_l[int(len(sorted_l) * 0.95)] if len(sorted_l) > 1 else sorted_l[0]
                await self.push_frame(OutputTransportMessageFrame(
                    message={
                        "type": "latency",
                        "data": {
                            "last": round(latency_ms),
                            "avg": round(avg),
                            "p95": round(p95),
                            "min": round(sorted_l[0]),
                            "max": round(sorted_l[-1]),
                            "turns": len(self.latencies),
                            "history": [round(l) for l in self.latencies[-10:]],
                        },
                    }
                ), direction)

            await self.push_frame(frame, direction)

    latency_measurer = LatencyMeasurer()

    # --- Build pipeline ---
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            latency_measurer,
            kb_processor,
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
