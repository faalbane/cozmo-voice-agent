# System Architecture

## High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          PSTN Network                               │
│                     (Customer Phone Calls)                          │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ SIP/RTP
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      Twilio SIP Trunk                                │
│              (Inbound call routing, phone numbers)                    │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ SIP INVITE + RTP
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    LiveKit SIP Bridge                                 │
│          (SIP termination → WebRTC media bridging)                   │
│                                                                      │
│  • Converts SIP/RTP to WebRTC media tracks                          │
│  • Creates a LiveKit Room per call                                   │
│  • Publishes caller audio as a room track                           │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ WebRTC (audio tracks)
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    LiveKit Server (SFU)                               │
│            (Real-time media routing & signaling)                     │
│                                                                      │
│  • Routes audio between SIP Bridge and Agent Workers                │
│  • Dispatches incoming calls to available agent workers             │
│  • Handles room lifecycle (create, close, participant tracking)     │
│  • Provides RTC stats (jitter, packet loss, bitrate)                │
└────────┬─────────────────────────────┬───────────────────────────────┘
         │ Job Dispatch                │ RTC Stats
         ▼                            ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    Agent Worker Pool                                  │
│          (N workers, each handling ~15-20 concurrent calls)          │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Agent Worker Process                                           │ │
│  │                                                                 │ │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────────┐  │ │
│  │  │ Silero   │→ │ Deepgram │→ │  OpenAI  │→ │   Cartesia    │  │ │
│  │  │ VAD      │  │ STT      │  │ GPT-4o-  │  │   TTS         │  │ │
│  │  │ (local)  │  │ (stream) │  │ mini     │  │   (stream)    │  │ │
│  │  └──────────┘  └──────────┘  └────┬─────┘  └───────────────┘  │ │
│  │                                    │                            │ │
│  │                              ┌─────▼──────┐                    │ │
│  │                              │ Knowledge  │                    │ │
│  │                              │ Lookup     │                    │ │
│  │                              │ (LLM Tool) │                    │ │
│  │                              └─────┬──────┘                    │ │
│  │                                    │                            │ │
│  └────────────────────────────────────┼────────────────────────────┘ │
│                                       │                              │
└───────────────────────────────────────┼──────────────────────────────┘
                                        │ Vector Query
                                        ▼
┌───────────────────┐  ┌───────────────────┐  ┌───────────────────────┐
│     ChromaDB      │  │      Redis        │  │  Prometheus + Grafana │
│  (Knowledge Base) │  │  (Call State)     │  │  (Observability)      │
│                   │  │                   │  │                       │
│ • Company docs    │  │ • Active calls    │  │ • E2E latency         │
│ • Policy chunks   │  │ • Worker registry │  │ • Pipeline breakdown  │
│ • Embeddings      │  │ • Health state    │  │ • MOS / jitter        │
│ • Cosine search   │  │ • Call metadata   │  │ • Call volume         │
└───────────────────┘  └───────────────────┘  └───────────────────────┘
```

## Component Responsibilities

| Component | Role | Scale Characteristics |
|---|---|---|
| **Twilio SIP Trunk** | PSTN ingress, phone number management | Managed service, unlimited capacity |
| **LiveKit SIP Bridge** | SIP→WebRTC protocol translation | 1 instance handles 200+ calls |
| **LiveKit Server** | Media routing (SFU), room management, job dispatch | Vertically scales to ~500 rooms |
| **Agent Workers** | Voice AI pipeline (VAD→STT→LLM→TTS) | Horizontally scalable, ~15-20 calls each |
| **ChromaDB** | Vector similarity search for knowledge retrieval | Single instance sufficient to 1000+ queries/s |
| **Redis** | Call state, inter-worker coordination, health tracking | Single instance to 100k+ ops/s |
| **Prometheus** | Metrics aggregation and storage | Scrapes all workers every 5s |
| **Grafana** | Real-time dashboards and alerting | Pre-provisioned with voice agent dashboards |

## Design Principles

1. **Separation of concerns**: Media routing (LiveKit), AI processing (Agent Workers), and state (Redis) are independent and independently scalable.
2. **Subprocess isolation**: Each call runs in its own Python subprocess. A crash in one call doesn't affect others.
3. **Streaming pipeline**: Every stage (STT, LLM, TTS) uses streaming to minimize time-to-first-byte, keeping total E2E latency under 600ms.
4. **Load-aware dispatch**: Workers report CPU/memory load to LiveKit, which stops dispatching to overloaded workers automatically.
5. **Pre-warmed processes**: Workers pre-fork idle processes and pre-load ML models (VAD) so call pickup is instant.
