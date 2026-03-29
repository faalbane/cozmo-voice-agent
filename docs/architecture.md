# System Architecture

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Clients                                     │
│                                                                      │
│   Browser (WebSocket)          PSTN Phone (Twilio → Daily.co)       │
└──────────┬─────────────────────────────┬────────────────────────────┘
           │                             │
           ▼                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Agent Server (FastAPI)                             │
│              POST /calls → creates a new pipeline                    │
│              GET /calls → lists active calls                         │
│              GET /healthz → worker health                            │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Pipecat Pipeline (one per call, async task)                   │  │
│  │                                                                │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐  │  │
│  │  │ Silero   │→ │ Deepgram │→ │  Groq    │→ │  Cartesia    │  │  │
│  │  │ VAD      │  │ STT      │  │ Llama 3.1│  │  TTS         │  │  │
│  │  │ (local)  │  │ (stream) │  │ 8B       │  │  (stream)    │  │  │
│  │  └──────────┘  └──────────┘  └────┬─────┘  └──────────────┘  │  │
│  │                                    │                           │  │
│  │                              ┌─────▼──────┐                   │  │
│  │                              │ Knowledge  │                   │  │
│  │                              │ (System    │                   │  │
│  │                              │  Prompt)   │                   │  │
│  │                              └─────┬──────┘                   │  │
│  └────────────────────────────────────┼───────────────────────────┘  │
│                                       │                              │
└───────────────────────────────────────┼──────────────────────────────┘
                                        │
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────┐
│     ChromaDB      │  │      Redis        │  │  Prometheus + Grafana │
│  (available, not  │  │  (Call State)     │  │  (Observability)      │
│   required)       │  └───────────────────┘  └───────────────────────┘
└───────────────────┘
```

## Why Pipecat

| Property | Benefit |
|---|---|
| **Transport-agnostic** | WebSocket for dev, Daily.co for production, Twilio for PSTN — same pipeline code |
| **Frame-based pipeline** | Each stage (VAD→STT→LLM→TTS) is a composable processor |
| **Built-in interruption** | `allow_interruptions=True` handles barge-in natively |
| **Function calling** | LLM can call knowledge base tools mid-conversation |
| **Simple scaling** | One async task per call, no subprocess overhead |
| **Zero cloud lock-in** | Runs locally with just 3 API keys (Deepgram, Groq, Cartesia) |
| **Simple local dev** | No cloud account needed — `python server.py` and go |

## Scaling Model

Each call is an independent `asyncio.Task` running its own Pipecat pipeline. The server creates a new task per `POST /calls`. This gives us:

- **Isolation**: One call crashing doesn't affect others
- **Horizontal scaling**: Run multiple server instances behind a load balancer
- **Resource efficiency**: Async I/O means 100 calls share CPU efficiently (the work is I/O-bound — waiting for API responses)

## Transport Modes

| Mode | Transport | Client | PSTN Support |
|---|---|---|---|
| WebSocket | `WebSocketServerTransport` | Browser / any WS client | No (web only) |
| Daily.co | `DailyTransport` | Daily.co rooms / WebRTC | Yes (via Twilio SIP) |
| Server | HTTP API + per-call WebSocket | Any client via API | Both supported |
