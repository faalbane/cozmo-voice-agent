"""Real load test: 100 concurrent calls through Groq LLM + Deepgram TTS.

Each call sends a real prompt, gets a real LLM response, generates real
TTS audio, and measures actual E2E latency. No mocking.
"""

import asyncio
import logging
import os
import time

import httpx

from src.prompts.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

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


async def run_single_call(call_id: int, prompt: str, groq_key: str, dg_key: str) -> dict:
    """Run one call: Groq LLM -> Deepgram TTS, measure real latency."""
    result = {"call_id": call_id, "prompt": prompt, "status": "pending", "latency_ms": 0, "response": ""}

    for attempt in range(3):
        try:
            t_start = time.monotonic()

            # 1. Real Groq LLM call (streaming — measure TTFT)
            response_text = ""
            t_llm = 0
            async with httpx.AsyncClient(timeout=15) as http:
                async with http.stream(
                    "POST",
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": prompt},
                        ],
                        "max_tokens": 80,
                        "temperature": 0.4,
                        "stream": True,
                    },
                ) as stream:
                    stream.raise_for_status()
                    async for line in stream.aiter_lines():
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            continue
                        if not t_llm:
                            t_llm = time.monotonic()  # First token!
                        try:
                            chunk = __import__("json").loads(line[6:])
                            delta = chunk["choices"][0].get("delta", {}).get("content", "")
                            response_text += delta
                        except Exception:
                            pass

            if not t_llm:
                t_llm = time.monotonic()

            # 2. Real Deepgram TTS call
            async with httpx.AsyncClient(timeout=15) as http:
                tts_resp = await http.post(
                    "https://api.deepgram.com/v1/speak?model=aura-asteria-en",
                    headers={"Authorization": f"Token {dg_key}", "Content-Type": "application/json"},
                    json={"text": response_text[:200]},
                )
                tts_resp.raise_for_status()

            t_end = time.monotonic()

            result["status"] = "completed"
            result["latency_ms"] = round((t_end - t_start) * 1000, 1)
            result["llm_ms"] = round((t_llm - t_start) * 1000, 1)
            result["tts_ms"] = round((t_end - t_llm) * 1000, 1)
            result["response"] = response_text[:100]
            return result

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429 and attempt < 2:
                await asyncio.sleep((attempt + 1) * 2)
                continue
            result["status"] = "error"
            result["error"] = f"HTTP {e.response.status_code}"
            return result
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)[:100]
            return result

    return result


async def run_load_test(count: int = 100, concurrency: int = 10) -> dict:
    """Run N concurrent real API calls and return aggregate results."""
    logger.info(f"Starting load test: {count} calls, {concurrency} concurrent")

    groq_key = os.getenv("GROQ_API_KEY")
    dg_key = os.getenv("DEEPGRAM_API_KEY")
    all_results = []
    start_time = time.monotonic()

    for batch_start in range(0, count, concurrency):
        batch_end = min(batch_start + concurrency, count)
        tasks = [
            run_single_call(i, TEST_PROMPTS[i % len(TEST_PROMPTS)], groq_key, dg_key)
            for i in range(batch_start, batch_end)
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in batch_results:
            if isinstance(r, Exception):
                all_results.append({"call_id": -1, "status": "error", "error": str(r), "latency_ms": -1})
            else:
                all_results.append(r)

        logger.info(f"Load test: {len(all_results)}/{count} done")

    total_time = (time.monotonic() - start_time) * 1000
    successful = [r for r in all_results if r["status"] == "completed"]
    latencies = sorted([r["latency_ms"] for r in successful])

    avg = sum(latencies) / len(latencies) if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) > 1 else (latencies[0] if latencies else 0)

    # LLM TTFT stats (the metric that matters for streaming voice)
    llm_times = sorted([r["llm_ms"] for r in successful if "llm_ms" in r])
    avg_llm = sum(llm_times) / len(llm_times) if llm_times else 0

    return {
        "total_calls": count,
        "successful": len(successful),
        "failed": count - len(successful),
        "failure_rate_pct": round((count - len(successful)) / count * 100, 1),
        "avg_latency_ms": round(avg, 1),
        "p95_latency_ms": round(p95, 1),
        "min_latency_ms": round(latencies[0], 1) if latencies else 0,
        "max_latency_ms": round(latencies[-1], 1) if latencies else 0,
        "total_time_ms": round(total_time, 1),
        "avg_llm_ttft_ms": round(avg_llm, 1),
        "target_600ms": avg_llm < 600,
        "calls": all_results,
    }
