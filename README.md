# ShopEase Voice Agent

Production-ready voice AI agent system handling **100 concurrent PSTN calls** with **<600ms average round-trip latency**.

Built with LiveKit Agents SDK, Deepgram STT, OpenAI GPT-4o-mini, and Cartesia TTS.

## Architecture

```
PSTN Caller → Twilio SIP → LiveKit SIP Bridge → LiveKit SFU → Agent Worker Pool
                                                                    │
                                                    ┌───────────────┼───────────────┐
                                                    ▼               ▼               ▼
                                                Deepgram        GPT-4o-mini     Cartesia
                                                (STT)           (LLM)           (TTS)
                                                                    │
                                                                ChromaDB
                                                            (Knowledge Base)
```

**Key design decisions:**
- **LiveKit over Pipecat**: Native SIP bridge, built-in worker scaling, subprocess isolation per call
- **Streaming everything**: STT, LLM, and TTS all stream to minimize time-to-first-byte
- **Pre-warmed workers**: 3 idle processes ready for instant call pickup (zero cold-start)

See [docs/architecture.md](docs/architecture.md) for the full system diagram.

## Latency Budget

| Stage | Target | Provider |
|---|---|---|
| VAD (speech detection) | ~50ms | Silero (local) |
| STT (transcription) | ~150ms | Deepgram Nova-2 |
| LLM (response generation) | ~200ms | GPT-4o-mini |
| TTS (speech synthesis) | ~100ms | Cartesia Sonic |
| Network overhead | ~100ms | LiveKit SFU |
| **Total** | **~600ms** | |

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- API keys (see below)

### 1. Clone & Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

**Required API keys:**

| Service | Key | Get it at |
|---|---|---|
| LiveKit | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | [livekit.io](https://livekit.io) |
| Twilio | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | [twilio.com](https://twilio.com) |
| Deepgram | `DEEPGRAM_API_KEY` | [deepgram.com](https://deepgram.com) |
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| Cartesia | `CARTESIA_API_KEY` | [cartesia.ai](https://cartesia.ai) |

### 2. Setup

```bash
# One-command setup (installs deps, starts infra, seeds knowledge base)
bash scripts/setup.sh
```

Or manually:

```bash
pip install -e ".[dev]"
docker compose up -d redis chromadb prometheus grafana
python scripts/seed_knowledge.py
```

### 3. Configure Twilio SIP Trunk

```bash
# Set your LiveKit SIP endpoint
export LIVEKIT_SIP_URI=sip:your-project.sip.livekit.cloud
bash infra/twilio-setup.sh

# Create LiveKit SIP trunk and dispatch rules
lk sip trunk create infra/sip-trunk-config.json
lk sip dispatch create infra/sip-trunk-config.json
```

### 4. Run the Agent

```bash
# Development mode (connects to LiveKit, hot reloads)
python src/main.py dev

# Production mode
docker compose up -d
```

### 5. Start the Dashboard

```bash
make dashboard
# Open http://localhost:8080
```

### 6. Test It

Call your Twilio phone number. The agent will greet you:

> "Hello! Thank you for calling ShopEase. My name is Alex. How can I help you today?"

Try asking:
- "What's your refund policy?"
- "I want to cancel my order" (objection handling)
- "How long does shipping take?"

## Monitoring

- **Live Dashboard**: http://localhost:8080 — real-time active calls, worker health
- **Grafana**: http://localhost:3000 (admin/admin) — latency percentiles, MOS scores, call volume
- **Prometheus**: http://localhost:9090 — raw metrics

### Key Metrics

| Metric | Description |
|---|---|
| `voice_agent_e2e_latency_seconds` | End-to-end response latency (histogram) |
| `voice_agent_concurrent_calls` | Active calls (gauge) |
| `voice_agent_mos_score` | Estimated Mean Opinion Score (histogram) |
| `voice_agent_call_setup_failures_total` | Failed call setups (counter) |
| `voice_agent_llm_ttft_seconds` | LLM time to first token (histogram) |

## Load Testing

```bash
# Run progressive load test (10 → 25 → 50 → 75 → 100 concurrent calls)
bash scripts/run_load_test.sh

# Results saved to tests/load/results/load_test_report.json
```

## Scaling

Scale agent workers to handle more concurrent calls:

```bash
# Scale to 5 workers (handles ~75-100 calls)
AGENT_REPLICAS=5 docker compose up -d --scale agent=5

# Scale to 7 workers (handles 100+ calls)
AGENT_REPLICAS=7 docker compose up -d --scale agent=7
```

See [docs/scaling-plan.md](docs/scaling-plan.md) for the full scaling architecture.

## Project Structure

```
├── src/
│   ├── main.py              # Worker entrypoint
│   ├── agent.py             # VoicePipelineAgent setup
│   ├── dashboard.py         # Live monitoring UI
│   ├── pipeline/            # STT, LLM, TTS, VAD configs
│   ├── knowledge/           # ChromaDB vector search + documents
│   ├── tools/               # LLM function tools
│   ├── metrics/             # Prometheus instrumentation
│   ├── state/               # Redis call tracking
│   └── resilience/          # Health checks, circuit breaker
├── infra/                   # LiveKit, Twilio, Prometheus, Grafana configs
├── docs/                    # Architecture diagrams & write-ups
├── tests/                   # Unit, integration, and load tests
└── scripts/                 # Setup, seeding, and load test scripts
```

## Tests

```bash
# Unit tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=src
```

## Documentation

- [System Architecture](docs/architecture.md) — high-level component diagram
- [Call Flow](docs/call-flow.md) — media & control plane sequence diagram
- [Scaling Plan](docs/scaling-plan.md) — tier-based scaling strategy
- [LiveKit vs Pipecat](docs/livekit-vs-pipecat.md) — framework comparison
- [Scaling to 1,000 Calls](docs/scaling-to-1000.md) — bottlenecks and mitigations

## Features Checklist

- [x] **Telephony Integration**: Twilio SIP trunk → LiveKit SIP Bridge → Agent
- [x] **Conversational AI**: GPT-4o-mini with function calling, natural turn-taking
- [x] **Barge-in**: Interruptible TTS with configurable speech detection threshold
- [x] **Knowledge Base**: ChromaDB vector search over company documents
- [x] **Objection Handling**: Cancellation scenario with empathetic de-escalation
- [x] **Latency Instrumentation**: Per-turn STT/LLM/TTS breakdown via Prometheus
- [x] **Call Quality Metrics**: MOS estimation, jitter, packet loss tracking
- [x] **Scalability**: Load-aware worker dispatch, horizontal scaling to 100+ calls
- [x] **Failure Recovery**: LLM timeout fallback, circuit breaker, health checks
- [x] **Live Dashboard**: Real-time WebSocket-powered call monitoring UI
- [x] **Load Testing**: Progressive 10→100 concurrent call test harness
- [x] **Architecture Docs**: 3 diagrams + LiveKit vs Pipecat + scaling 1-pager
