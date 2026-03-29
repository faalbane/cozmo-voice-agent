# Scaling to 1,000 Calls: What Breaks and How to Fix It

## What Breaks at 1,000 Concurrent Calls

### 1. Pipecat Server Processes (Pipeline Capacity)
Each Pipecat server process runs pipelines as async tasks. A single process can handle ~50 concurrent pipelines before event loop contention causes audio dropouts. At 1,000 calls, you need ~20-70 server processes distributed across multiple hosts, each managing 15-50 pipelines.

### 2. Groq API Rate Limits
Groq's rate limits vary by tier but are generous for Llama 3.1 8B. With 1,000 concurrent calls averaging one turn every 10 seconds, that's 6,000 RPM. Groq's infrastructure handles this well, but bursty traffic could still cause queuing. The ~100ms TTFT advantage over GPT-4o-mini (~200ms) means the LLM is no longer the primary latency bottleneck.

### 3. TTS Connection Concurrency (New Primary Bottleneck)
With LLM TTFT reduced from ~200ms to ~100ms via Groq, **TTS is now the dominant bottleneck**. Deepgram Aura delivers ~200ms TTFB per stream, but at 1,000 simultaneous streams, connection establishment overhead and server-side queuing can push TTFB to 300-400ms. This eats into the latency budget significantly.

### 4. STT Connection Concurrency
Deepgram enterprise plans support hundreds of concurrent WebSocket connections, but 1,000 simultaneous streams approaches the upper bound. Connection establishment overhead also increases, impacting time-to-first-result.

### 5. Server Instance Memory
Each pipeline consumes ~50-100MB (Silero VAD model loaded once per process, plus WebSocket connections and audio buffers per pipeline). At 1,000 calls across 70 instances (~15 calls each), total memory footprint is ~70-100GB cluster-wide. Async task scheduling overhead can cause audio dropouts if the event loop is overloaded.

### 6. Knowledge Base & Order Database
The keyword search KB uses in-memory term-frequency scoring with no external service, so it scales trivially with each server process. The SQLite order database handles lookups for order status and history. At 1,000 calls, SQLite's single-writer limitation can cause contention if many calls write simultaneously — use WAL mode and consider moving to PostgreSQL at scale.

## How to Fix It

### Pipecat: Scale Server Instances Horizontally
- **Multiple processes per host**: Run 3-5 `server.py` processes per host behind Nginx, each on a different port.
- **Kubernetes deployment**: Deploy as a Deployment with HPA scaling on `voice_agent_concurrent_calls`. Each pod runs one server process handling ~15 pipelines.
- **Daily.co for WebRTC**: Use Daily.co as the managed WebRTC layer for production/PSTN. Daily handles the media routing complexity, and Pipecat connects via `DailyTransport`.

### LLM: Already Fast, Keep It That Way
- **Groq Llama 3.1 8B Instant** at ~100ms TTFT is no longer the primary bottleneck. Focus optimization efforts elsewhere.
- **Multiple API keys**: Spread requests across 2-3 Groq API keys for rate limit headroom.
- **Self-hosted fallback**: Deploy Llama 3.1 8B on vLLM with a single A100 GPU as a fallback if Groq has an outage. The 8B model is small enough that self-hosting is practical and cost-effective.
- **Prompt caching**: Since all calls share the same system prompt, Groq's built-in KV caching provides near-100% cache hit rate, keeping TTFT consistently low.

### TTS: The New Bottleneck — Enterprise + Caching
- **Enterprise tier**: Deepgram Enterprise supports 1,000+ concurrent connections with dedicated infrastructure for Aura TTS.
- **Audio caching**: Cache synthesized audio for common phrases ("Hello, how can I help you?", "Is there anything else?"). At 1,000 calls, cache hit rates for greetings alone save ~2,000 TTS calls per hour.
- **Provider fallback**: Primary: Deepgram Aura. Secondary: ElevenLabs or a self-hosted XTTS model. Circuit breaker routes to secondary on failure.
- **Streaming optimization**: Start TTS streaming as soon as the first LLM tokens arrive (Pipecat does this natively). With Groq's ~100ms TTFT, TTS synthesis begins quickly.

### STT: Enterprise + Fallback
- **Enterprise tiers**: Deepgram Enterprise supports 1,000+ concurrent connections with dedicated infrastructure.
- **Provider fallback**: Primary: Deepgram. Secondary: AssemblyAI. If primary fails, circuit breaker routes to secondary.

### Server Instances: Kubernetes HPA with Custom Metrics
```
voice_agent_concurrent_calls / max_calls_per_instance → target: 0.75
```
- Scale up: Add 5 instances when utilization exceeds 75%
- Scale down: Remove 2 instances when utilization drops below 30% (5-minute stabilization window)
- Use spot/preemptible instances for non-critical servers (70% cost savings), with graceful drain on termination

### Knowledge Base & Order Database: In-Memory KB + SQLite
- **Default**: Knowledge is served via in-memory keyword search with term-frequency scoring. No external service needed. This is the fastest path.
- **SQLite order DB**: Handles order lookups (status, history). Enable WAL mode for concurrent read access during calls.
- **At scale**: Migrate SQLite to PostgreSQL for multi-writer support and connection pooling. Redis cache for top-100 most frequent KB queries (TTL: 1 hour, expected cache hit rate: 60-80%).

## Where Is the Latency Bottleneck Today?

**TTS time-to-first-byte (TTFB) is the dominant bottleneck**, consuming ~200ms or ~36% of our 550ms budget. With Groq's ~100ms TTFT, the LLM is no longer the primary constraint — TTS is.

```
Current latency breakdown (single call):
  VAD:  ███░░░░░░░░░░░░░░░░░  50ms ( 9.1%)
  STT:  ████████████░░░░░░░░ 150ms (27.3%)
  LLM:  ████████░░░░░░░░░░░░ 100ms (18.2%)  ◄── Was 200ms with GPT-4o-mini!
  TTS:  ████████████████░░░░ 200ms (36.4%)  ◄── DOMINANT BOTTLENECK
  Net:  ███░░░░░░░░░░░░░░░░░  50ms ( 9.1%)
  ─────────────────────────────────
  Total:                      550ms
```

At 1,000 calls, TTS connection queuing pushes TTFB to 300-400ms under load, which significantly impacts responsiveness. The fixes:

1. **Deepgram Enterprise**: Dedicated infrastructure eliminates connection queuing for Aura TTS
2. **TTS audio caching**: Pre-synthesize common phrases, serve from cache (~5ms instead of ~200ms)
3. **Regional deployment**: Place server instances in the same region as Deepgram's endpoints
4. **Parallel warm-up**: Pre-establish TTS connections during call setup, before the first turn

**Why STT is not the bottleneck**: Deepgram Nova-2 at 150ms is already near-optimal for streaming STT. Switching providers would likely increase this. The 150ms is a fixed cost that cannot be meaningfully reduced. TTS, on the other hand, has clear optimization paths (caching, enterprise tier) that can bring it well below 200ms.

**The big win**: Switching from GPT-4o-mini (~200ms TTFT) to Groq Llama 3.1 8B Instant (~100ms TTFT) saved 100ms per turn. Using Deepgram Aura TTS (~200ms TTFB) consolidates the STT and TTS provider into a single vendor, simplifying operations.
