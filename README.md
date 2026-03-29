# ShopEase Voice Agent

Production-ready voice AI agent system handling **100 concurrent calls** with **<600ms average round-trip latency**.

Built with **Pipecat**, Deepgram STT/TTS, Groq Llama 3.1 8B, and SQLite.

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure API keys
cp .env.example .env
# Edit .env with: DEEPGRAM_API_KEY, GROQ_API_KEY

# 3. Run everything
source .venv/bin/activate
python run_client.py
```

This starts the voice agent, HTTP server, and web client. Open **http://localhost:3001** and click the phone button to talk.

## What It Does

- **Voice conversation**: Talk to an AI customer support agent in real-time
- **Barge-in**: Interrupt the agent mid-sentence — it stops and responds to your new input
- **Knowledge base**: Keyword search (RAG) over refund policies, shipping, cancellations, etc. with term-frequency scoring
- **SQLite database**: Real order CRUD — cancel, return, update status via natural language
- **<600ms latency**: Groq LLM (~100ms TTFT) + Deepgram TTS (~200ms TTFB)
- **100 concurrent calls**: Load test runs 100 real API calls simultaneously
- **Objection handling**: Try saying "I want to cancel my subscription"
- **Live metrics**: MOS (E-model), jitter, packet loss, P95/avg response time

## Architecture

```
                    ┌─ WebSocket ──┐      ┌─ Daily.co WebRTC ──┐
 Browser Client ───>│  Transport   │      │    Transport        │<─── PSTN (Twilio SIP)
                    └──────┬───────┘      └────────┬────────────┘
                           │                       │
                           ▼                       ▼
                    ┌──────────────────────────────────────┐
                    │         Pipecat Pipeline              │
                    │                                      │
                    │  Silero VAD → Deepgram STT           │
                    │       → Groq Llama 3.1 8B            │
                    │            → Deepgram Aura TTS       │
                    │                 │                     │
                    │    Keyword Search KB (RAG)            │
                    │    SQLite Order Database              │
                    └──────────────────────────────────────┘
                           │              │
                     SQLite (Orders)  Prometheus → Grafana
```

**Data flow per turn:**
```
User speech → Silero VAD (50ms) → Deepgram STT (150ms)
  → KB Lookup (term-frequency scoring, <1ms)
  → Groq Llama 3.1 8B (TTFT ~100ms)
  → Deepgram Aura TTS (TTFB ~200ms)
  → Audio to caller
  Total: ~500ms (under 600ms target)
```

## 4-Pane Demo UI

The web client at `localhost:3001` features a 4-pane layout:

| Pane | Position | Shows |
|---|---|---|
| **Knowledge Base** | Left | Live keyword search results with relevance scores |
| **Conversation** | Center (tallest) | Real-time transcript with streaming bot responses |
| **Latency & Quality** | Right | MOS, jitter, packet loss, P95, avg E2E, per-turn bars |
| **Order Database** | Bottom | SQLite orders with live CRUD updates |

## API Keys

| Service | Key | Purpose |
|---|---|---|
| Deepgram | `DEEPGRAM_API_KEY` | STT + TTS |
| Groq | `GROQ_API_KEY` | LLM (Llama 3.1 8B) |

Both have free tiers. No other external services required.

## Run Modes

| Mode | Command | Use Case |
|---|---|---|
| **All-in-one** | `python run_client.py` | Single call + server + web client. Best for demo. |
| **WebSocket** | `python src/main.py` | Single agent on ws://localhost:8765 |
| **Server** | `python src/main.py --mode server` | HTTP API for concurrent calls on :8080 |
| **Daily** | `python src/main.py --mode daily --room-url URL --token TOKEN` | WebRTC with PSTN via Twilio |

## 100 Concurrent Calls Load Test

Open **http://localhost:3001/multi.html** and click "Run 100-Call Load Test".

Each of the 100 calls:
1. Sends a **real prompt** to Groq Llama 3.1 8B
2. Gets a **real LLM response** (streaming, measures TTFT)
3. Generates **real TTS audio** via Deepgram Aura
4. **Measures actual pipeline latency** (LLM TTFT + TTS TTFB)

No mocking — every call hits real APIs. Results stream via SSE showing avg/p95/min/max latency.

API endpoints:
```bash
curl -X POST http://localhost:8080/calls              # Create a call
curl http://localhost:8080/calls/load-test?count=100   # Run load test (SSE)
curl http://localhost:8080/calls                       # List active calls
curl http://localhost:8080/healthz                     # Health check
curl http://localhost:8080/kb/search?q=refund          # KB search
curl http://localhost:8080/db/orders                   # List all orders
```

## Latency Budget

| Stage | Target | Provider |
|---|---|---|
| VAD | ~50ms | Silero (local) |
| STT | ~150ms | Deepgram Nova-2 |
| LLM TTFT | ~100ms | Groq Llama 3.1 8B |
| TTS TTFB | ~200ms | Deepgram Aura |
| **Total** | **~500ms** | **Under 600ms target** |

## Knowledge Base (RAG)

Keyword search with term-frequency scoring over 6 domain documents:
- Refund policy, shipping rates, order cancellation
- Products & pricing, loyalty/rewards program, complaint handling

The `KBLookupProcessor` in the pipeline searches on each user turn and injects top-K results into the LLM context. Visible in the UI with relevance scores.

Try asking: *"What's your refund policy?"* or *"How much does shipping cost?"*

## Order Database (SQLite)

Real SQLite database (`src/db/shopease.db`) with 5 pre-seeded orders. Supports CRUD via natural language:
- *"Cancel order 12345"* → status updates to `cancel_requested`
- *"Update order 67890 to shipped"* → status updates to `shipped`
- Spoken digits converted automatically ("one two three four five" → 12345)

Updates visible in real-time in the bottom DB pane.

## Observability & Metrics

**Client-side (live in UI):**
- E2E latency (last, avg, P95)
- MOS score (ITU-T E-model G.107)
- Jitter (RFC 3550)
- Packet loss estimation
- Per-turn latency bars

**Server-side (Prometheus):**
- `voice_agent_e2e_latency_seconds` — histogram
- `voice_agent_llm_ttft_seconds` — LLM time to first token
- `voice_agent_tts_ttfb_seconds` — TTS time to first byte
- `voice_agent_mos_score` — MOS histogram
- `voice_agent_concurrent_calls` — gauge
- `voice_agent_calls_total` — counter by status

## Project Structure

```
├── src/
│   ├── main.py              # Entrypoint (websocket/server/daily modes)
│   ├── agent.py             # Pipecat pipeline (VAD→STT→LLM→TTS)
│   ├── server.py            # FastAPI server for concurrent calls + KB/DB APIs
│   ├── load_test.py         # Real 100-call load test
│   ├── knowledge/
│   │   └── search.py        # Keyword search KB (term-frequency scoring)
│   ├── db/
│   │   └── orders.py        # SQLite order database
│   ├── prompts/
│   │   └── system_prompt.py # Agent system prompt
│   ├── metrics/             # Prometheus instrumentation, MOS estimation
│   ├── state/               # Redis call tracking
│   └── resilience/          # Circuit breaker, health checks, retry policies
├── public/client/
│   ├── index.html           # 4-pane voice client (KB + chat + metrics + DB)
│   └── multi.html           # 100-call load test UI
├── run_client.py            # One-command startup (agent + server + client)
├── infra/                   # Prometheus, Grafana, Redis configs
├── docs/                    # Architecture diagrams & write-ups
├── docker-compose.yml       # Docker orchestration
├── Dockerfile               # Container image
└── tests/                   # Unit and load tests
```

## Monitoring (Docker)

```bash
docker compose up -d
# Grafana: http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
```

## Tests

```bash
pytest tests/ -v --cov=src
```

## Documentation

- [System Architecture](docs/architecture.md)
- [Call Flow](docs/call-flow.md)
- [Scaling Plan](docs/scaling-plan.md)
- [LiveKit vs Pipecat](docs/livekit-vs-pipecat.md)
- [Scaling to 1,000 Calls](docs/scaling-to-1000.md)
