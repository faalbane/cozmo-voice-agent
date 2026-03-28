# Scaling to 1,000 Calls: What Breaks and How to Fix It

## What Breaks at 1,000 Concurrent Calls

### 1. LiveKit Server (Media Routing)
A single LiveKit server instance handling 1,000 simultaneous rooms with audio routing will hit CPU limits. Each room requires RTP packet forwarding, DTLS encryption, and RTCP processing. At ~500 rooms, a well-provisioned single node starts to degrade.

### 2. LLM API Rate Limits
GPT-4o-mini allows ~10,000 RPM on Tier 5. With 1,000 concurrent calls averaging one turn every 10 seconds, that's 6,000 RPM — feasible but with no headroom. Bursty traffic (many callers speaking simultaneously) could hit rate limits, causing latency spikes as requests queue.

### 3. STT/TTS Connection Concurrency
Deepgram and Cartesia enterprise plans support hundreds of concurrent WebSocket connections, but 1,000 simultaneous streams approaches the upper bound. Connection establishment overhead also increases, impacting time-to-first-result.

### 4. Agent Worker Memory
Each agent subprocess consumes ~200MB (VAD model, WebSocket connections, audio buffers). At 1,000 calls across 70 workers (~15 calls each), total memory footprint is ~200GB cluster-wide. Worker garbage collection pauses can cause audio dropouts.

### 5. ChromaDB Query Throughput
A single ChromaDB instance handles ~500 QPS with sub-50ms latency. At 1,000 calls with frequent knowledge lookups, query latency degrades and becomes a bottleneck in the LLM function calling path.

## How to Fix It

### LiveKit: Go Multi-Node or Managed
- **LiveKit Cloud**: Auto-scales SFU infrastructure across regions. Eliminates the single-server bottleneck entirely.
- **Self-hosted multi-node**: Deploy 3-5 LiveKit server instances behind a load balancer. LiveKit supports multi-node via Redis-backed room routing.

### LLM: Diversify and Self-Host
- **Multiple API keys**: Spread requests across 3-4 API keys from different organizations to multiply rate limits.
- **Self-hosted inference**: Deploy Llama 3.1 70B on vLLM with 4x A100 GPUs. Eliminates rate limits entirely and provides predictable ~150ms TTFT. Cost-effective at >500 concurrent calls.
- **Prompt caching**: OpenAI and Anthropic both support prompt caching. Since all calls share the same system prompt, cache hit rate would be near 100%, reducing TTFT by ~30%.

### STT/TTS: Enterprise + Fallback
- **Enterprise tiers**: Deepgram Enterprise supports 1,000+ concurrent connections with dedicated infrastructure.
- **Provider fallback**: Primary: Deepgram. Secondary: AssemblyAI or Whisper (self-hosted). If primary fails, circuit breaker routes to secondary.
- **TTS caching**: Cache synthesized audio for common phrases ("Hello, how can I help you?", "Is there anything else?"). At 1,000 calls, cache hit rates for greetings alone save ~2,000 TTS calls per hour.

### Workers: Kubernetes HPA with Custom Metrics
```
voice_agent_concurrent_calls / max_calls_per_worker → target: 0.75
```
- Scale up: Add 5 workers when utilization exceeds 75%
- Scale down: Remove 2 workers when utilization drops below 30% (5-minute stabilization window)
- Use spot/preemptible instances for non-critical workers (70% cost savings), with graceful drain on termination

### Knowledge Base: Cache + Cluster
- **Redis cache**: Cache top-100 most frequent queries (refund policy, shipping info). TTL: 1 hour. Expected cache hit rate: 60-80%.
- **Qdrant cluster**: Replace ChromaDB with Qdrant, which supports sharded collections and horizontal scaling.

## Where Is the Latency Bottleneck Today?

**The LLM time-to-first-token (TTFT) is the dominant bottleneck**, consuming ~200ms or 33% of our 600ms budget.

```
Current latency breakdown (single call):
  VAD:  ████░░░░░░░░░░░░░░░░  50ms  (8%)
  STT:  ████████░░░░░░░░░░░░ 150ms (25%)
  LLM:  ████████████░░░░░░░░ 200ms (33%)  ◄── BOTTLENECK
  TTS:  ██████░░░░░░░░░░░░░░ 100ms (17%)
  Net:  ██████░░░░░░░░░░░░░░ 100ms (17%)
```

At 1,000 calls, LLM API queuing pushes TTFT to 300-500ms under load, breaking the 600ms target. The fixes:

1. **Self-hosted LLM** (vLLM + Llama 3.1 70B): Predictable ~150ms TTFT regardless of concurrent load
2. **Shorter system prompts**: Reduce from ~400 tokens to ~200 tokens (saves ~20ms on TTFT)
3. **Speculative decoding**: Pre-generate likely responses for common queries, verify with LLM
4. **Regional deployment**: Place agent workers in the same region as the LLM endpoint to minimize network hops

**Secondary bottleneck**: STT streaming latency (150ms) is largely fixed by Deepgram's architecture and difficult to reduce further. Switching to a self-hosted Whisper model would increase this to ~300ms. Deepgram is the right choice.
