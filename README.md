# ShopEase Voice Agent

Production-ready voice AI agent system handling **100 concurrent calls** with **<600ms average round-trip latency**.

Built with **Pipecat**, Deepgram STT, Groq Llama 3.1 8B, and Deepgram Aura TTS.

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure API keys
cp .env.example .env
# Edit .env with: DEEPGRAM_API_KEY, GROQ_API_KEY, OPENAI_API_KEY

# 3. Run everything
python run_client.py
```

This starts the voice agent, HTTP server, and web client. Open **http://localhost:3001** and click the phone button to talk.

## What It Does

- **Voice conversation**: Talk to an AI customer support agent in real-time
- **Barge-in**: Interrupt the agent mid-sentence — it stops and responds to your new input
- **Knowledge base**: Keyword search over refund policies, shipping, cancellations, etc.
- **<600ms latency**: Groq LLM (~100ms TTFT) + Deepgram TTS (~200ms TTFB)
- **100 concurrent calls**: Load test runs 100 real API calls simultaneously
- **Objection handling**: Try saying "I want to cancel my subscription"

## Architecture

```
                    ┌─ WebSocket ──┐      ┌─ Daily.co WebRTC ──┐
 Browser Client ───►│  Transport   │      │    Transport        │◄─── PSTN (Twilio)
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
                    │        Keyword Search KB              │
                    └──────────────────────────────────────┘
                           │              │
                     Redis (State)   Prometheus → Grafana
```

## API Keys

| Service | Key | Purpose | Get it at |
|---|---|---|---|
| Deepgram | `DEEPGRAM_API_KEY` | STT + TTS | [deepgram.com](https://deepgram.com) (free tier) |
| Groq | `GROQ_API_KEY` | LLM (Llama 3.1 8B) | [console.groq.com](https://console.groq.com) (free tier) |
| OpenAI | `OPENAI_API_KEY` | Embeddings (optional) | [platform.openai.com](https://platform.openai.com) |

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
1. Sends a **real prompt** to Groq Llama 3.1 8B (e.g., "What is your refund policy?")
2. Gets a **real LLM response**
3. Generates **real TTS audio** via Deepgram Aura
4. **Measures actual E2E latency**

No mocking — every call hits real APIs. Results show avg/p95/min/max latency and individual call details.

You can also create calls via the API:

```bash
# Create a call
curl -X POST http://localhost:8080/calls

# Run 100-call load test
curl -X POST "http://localhost:8080/calls/load-test?count=100"

# List active calls
curl http://localhost:8080/calls

# Health check
curl http://localhost:8080/healthz
```

## Latency Budget

| Stage | Target | Provider |
|---|---|---|
| VAD | ~50ms | Silero (local) |
| STT | ~150ms | Deepgram Nova-2 |
| LLM TTFT | ~100ms | Groq Llama 3.1 8B |
| TTS TTFB | ~200ms | Deepgram Aura |
| Network | ~50ms | WebSocket |
| **Total** | **~550ms** | |

## Knowledge Base

In-memory keyword search over e-commerce documents:
- Refund policy, shipping rates, product info
- Cancellation policies, complaint handling
- Loyalty program, gift cards

The `KBLookupProcessor` in the pipeline automatically searches relevant docs for each user turn and injects context into the LLM prompt.

Try asking: *"What's your refund policy?"* or *"I want to cancel my subscription"*

## Project Structure

```
├── src/
│   ├── main.py              # Entrypoint (websocket/server/daily modes)
│   ├── agent.py             # Pipecat pipeline (VAD→STT→LLM→TTS)
│   ├── server.py            # HTTP server for concurrent calls
│   ├── load_test.py         # Real 100-call load test
│   ├── knowledge/
│   │   └── search.py        # Keyword search knowledge base
│   ├── metrics/             # Prometheus instrumentation, MOS estimation
│   ├── state/               # Redis call tracking
│   └── resilience/          # Circuit breaker, health checks
├── public/client/
│   ├── index.html           # Voice client (single call + metrics)
│   └── multi.html           # 100-call load test UI
├── run_client.py            # One-command startup (agent + server + client)
├── infra/                   # Prometheus, Grafana, Redis, Twilio configs
├── docs/                    # Architecture diagrams & write-ups
├── docker-compose.yml       # Docker orchestration
├── Dockerfile               # Container image
└── tests/                   # Unit and load tests
```

## Monitoring

```bash
# Health check
curl http://localhost:8080/healthz

# With Docker (Grafana + Prometheus)
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
