"""Real load test: 100 concurrent calls with actual LLM + TTS responses.

Each call creates a full Pipecat pipeline, injects a test transcript,
runs it through Groq LLM + Deepgram TTS, and measures real E2E latency.
No mocking — every call hits real APIs.
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
    TextFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.deepgram.tts import DeepgramTTSService
from pipecat.services.groq import GroqLLMService

from src.prompts.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Test prompts to simulate different callers
TEST_PROMPTS = [
    "What is your refund policy?",
    "How much does shipping cost?",
    "I want to cancel my subscription.",
    "Do you have a loyalty program?",
    "What happens if my item arrives damaged?",
    "Can I return a gift card?",
    "How long does express shipping take?",
    "What is your price match policy?",
    "I was charged twice for my order.",
    "Can I cancel an order that already shipped?",
]


async def run_single_load_call(call_id: int, prompt: str) -> dict:
    """Run a single test call: send prompt through LLM → TTS and measure latency."""
    result = {
        "call_id": call_id,
        "prompt": prompt,
        "status": "pending",
        "latency_ms": 0,
        "response": "",
    }

    try:
        # Create minimal pipeline: just LLM + TTS (no transport needed)
        llm = GroqLLMService(
            api_key=os.getenv("GROQ_API_KEY"),
            model="llama-3.1-8b-instant",
        )

        tts = DeepgramTTSService(
            api_key=os.getenv("DEEPGRAM_API_KEY"),
            voice="aura-asteria-en",
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        context = OpenAILLMContext(messages=messages)
        context_aggregator = llm.create_context_aggregator(context)

        # Collector to capture response and measure latency
        class ResponseCollector(FrameProcessor):
            def __init__(self):
                super().__init__(name=f"collector-{call_id}")
                self.response_text = ""
                self.first_token_time = 0
                self.start_time = 0
                self.done = asyncio.Event()

            async def process_frame(self, frame: Frame, direction: FrameDirection):
                await super().process_frame(frame, direction)

                if isinstance(frame, TextFrame) and frame.text:
                    if not self.first_token_time:
                        self.first_token_time = time.monotonic()
                    self.response_text += frame.text

                if isinstance(frame, TTSStartedFrame):
                    if not self.first_token_time:
                        self.first_token_time = time.monotonic()

                if isinstance(frame, EndFrame):
                    self.done.set()

                await self.push_frame(frame, direction)

        collector = ResponseCollector()
        collector.start_time = time.monotonic()

        pipeline = Pipeline([
            context_aggregator.user(),
            llm,
            collector,
            tts,
            context_aggregator.assistant(),
        ])

        task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True))

        runner = PipelineRunner()

        # Run pipeline with the test prompt
        async def run():
            await task.queue_frames([
                TranscriptionFrame(text=prompt, user_id="load-test", timestamp=str(time.time())),
            ])
            # Wait for first response or timeout
            try:
                await asyncio.wait_for(collector.done.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass
            await task.queue_frame(EndFrame())

        # Start pipeline and run test
        pipeline_task = asyncio.create_task(runner.run(task))
        await asyncio.sleep(0.5)  # Let pipeline initialize
        await run()

        # Calculate latency
        if collector.first_token_time:
            latency = (collector.first_token_time - collector.start_time) * 1000
        else:
            latency = -1

        pipeline_task.cancel()
        try:
            await pipeline_task
        except (asyncio.CancelledError, Exception):
            pass

        result["status"] = "completed" if latency > 0 else "timeout"
        result["latency_ms"] = round(latency, 1)
        result["response"] = collector.response_text[:100]

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        logger.error(f"Call {call_id} failed: {e}")

    return result


async def run_load_test(count: int = 100, concurrency: int = 20) -> dict:
    """Run N concurrent calls in batches and return aggregate results."""
    logger.info(f"Starting load test: {count} calls, {concurrency} concurrent")

    all_results = []
    start_time = time.monotonic()

    # Run in batches to avoid overwhelming APIs
    for batch_start in range(0, count, concurrency):
        batch_end = min(batch_start + concurrency, count)
        batch_tasks = []

        for i in range(batch_start, batch_end):
            prompt = TEST_PROMPTS[i % len(TEST_PROMPTS)]
            batch_tasks.append(run_single_load_call(i, prompt))

        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

        for r in batch_results:
            if isinstance(r, Exception):
                all_results.append({"call_id": -1, "status": "error", "error": str(r), "latency_ms": -1})
            else:
                all_results.append(r)

        completed = len(all_results)
        logger.info(f"Load test progress: {completed}/{count}")

    total_time = (time.monotonic() - start_time) * 1000

    # Aggregate stats
    successful = [r for r in all_results if r["status"] == "completed"]
    failed = [r for r in all_results if r["status"] != "completed"]
    latencies = sorted([r["latency_ms"] for r in successful if r["latency_ms"] > 0])

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    p95_latency = latencies[int(len(latencies) * 0.95)] if len(latencies) > 1 else (latencies[0] if latencies else 0)
    min_latency = latencies[0] if latencies else 0
    max_latency = latencies[-1] if latencies else 0

    return {
        "total_calls": count,
        "successful": len(successful),
        "failed": len(failed),
        "failure_rate_pct": round(len(failed) / count * 100, 1),
        "avg_latency_ms": round(avg_latency, 1),
        "p95_latency_ms": round(p95_latency, 1),
        "min_latency_ms": round(min_latency, 1),
        "max_latency_ms": round(max_latency, 1),
        "total_time_ms": round(total_time, 1),
        "target_600ms": avg_latency < 600,
        "calls": all_results[:20],  # First 20 for display
    }
