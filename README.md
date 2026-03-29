# ShopEase Voice Agent

Production-ready voice AI agent system handling **100 concurrent PSTN calls** with **<600ms average round-trip latency**.

Built with **Pipecat**, Deepgram STT, OpenAI GPT-4o-mini, and Cartesia TTS.

## Quick Start (3 minutes)

### 1. Install & configure

```bash
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with your API keys (Deepgram, OpenAI, Cartesia)
```

### 2. Run the agent

```bash
python src/main.py
```

### 3. Talk to it

Open `public/client/index.html` in your browser, click the phone button, and speak.

That's it. No cloud accounts, no Docker, no SIP trunks needed for the basic demo.

---

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
                    │       → OpenAI GPT-4o-mini           │
                    │            → Cartesia TTS            │
                    │                 │                     │
                    │           ChromaDB                    │
                    │        (Knowledge Base)               │
                    └──────────────────────────────────────┘
                           │              │
                     Redis (State)   Prometheus → Grafana
```

## Three Run Modes

| Mode | Command | Use Case |
|---|---|---|
| **WebSocket** | `python src/main.py` | Local dev, browser demo. No cloud needed. |
| **Server** | `python src/main.py --mode server` | Production. HTTP API creates per-call pipelines. |
| **Daily** | `python src/main.py --mode daily --room-url URL --token TOKEN` | WebRTC with PSTN via Twilio. |

## API Keys

| Service | Key | Get it at |
|---|---|---|
| Deepgram | `DEEPGRAM_API_KEY` | [deepgram.com](https://deepgram.com) (free tier) |
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| Cartesia | `CARTESIA_API_KEY` | [cartesia.ai](https://cartesia.ai) (free tier) |
| Daily.co | `DAILY_API_KEY` | [daily.co](https://daily.co) (optional, for WebRTC/PSTN) |

## Scaling to 100 Concurrent Calls

The server mode (`--mode server`) handles concurrency:

```bash
# Start the agent server
python src/main.py --mode server --port 8080

# Create a new call (returns a WebSocket URL)
curl -X POST http://localhost:8080/calls
# → {"call_id": "call-a1b2c3d4", "websocket_url": "ws://0.0.0.0:8766"}

# List active calls
curl http://localhost:8080/calls

# End a call
curl -X DELETE http://localhost:8080/calls/call-a1b2c3d4
```

Each call gets its own Pipecat pipeline in an async task — full isolation.

For Docker-based scaling:

```bash
docker compose up -d
# Agent server on :8080, Grafana on :3000, Prometheus on :9090
```

## Latency Budget

| Stage | Target | Provider |
|---|---|---|
| VAD | ~50ms | Silero (local) |
| STT | ~150ms | Deepgram Nova-2 |
| LLM TTFT | ~200ms | GPT-4o-mini |
| TTS TTFB | ~100ms | Cartesia Sonic |
| Network | ~100ms | WebSocket/WebRTC |
| **Total** | **~600ms** | |

## Knowledge Base

The agent has a ChromaDB-backed knowledge base with e-commerce documents:
- Refund policy, shipping info, product details
- Objection handling (cancellation scenarios)

Seed it: `python scripts/seed_knowledge.py`

Try asking: *"What's your refund policy?"* or *"I want to cancel my subscription"*

## Monitoring

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Health check**: `curl http://localhost:8080/healthz`

## Project Structure

```
├── src/
│   ├── main.py              # Entrypoint (websocket/server/daily modes)
│   ├── agent.py             # Pipecat pipeline (STT→LLM→TTS)
│   ├── server.py            # HTTP server for concurrent calls
│   ├── dashboard.py         # Live monitoring dashboard
│   ├── pipeline/            # STT, LLM, TTS, VAD configs
│   ├── knowledge/           # ChromaDB vector search + documents
│   ├── tools/               # LLM function tools (knowledge lookup)
│   ├── metrics/             # Prometheus instrumentation
│   ├── state/               # Redis call tracking
│   └── resilience/          # Health checks, circuit breaker
├── public/
│   ├── index.html           # Project overview site
│   ├── client/index.html    # Browser voice client
│   └── demo/index.html      # Live monitoring dashboard
├── infra/                   # Prometheus, Grafana, Redis configs
├── docs/                    # Architecture diagrams & write-ups
├── tests/                   # Unit, integration, and load tests
└── scripts/                 # Setup, seeding, load test scripts
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

## Live Demo

- **Project overview**: https://cozmo-voice-agent.web.app
- **Interactive dashboard**: https://cozmo-voice-agent.web.app/demo
