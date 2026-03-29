# Call Flow: Media & Control Plane

## Sequence Diagram

```
Customer       Twilio        Daily.co        Pipecat           Agent Server       External APIs
(PSTN)        (SIP Trunk)   (WebRTC)        Pipeline          (FastAPI)          (Deepgram/Groq/Cartesia)
   │               │              │              │               │                    │
   │  Dial Phone # │              │              │               │                    │
   │──────────────>│              │              │               │                    │
   │               │  SIP INVITE  │              │               │                    │
   │               │─────────────>│              │               │                    │
   │               │              │  POST /calls │               │                    │
   │               │              │─────────────────────────────>│                    │
   │               │              │              │  Create       │                    │
   │               │              │              │  Pipeline     │                    │
   │               │              │              │<──────────────│                    │
   │               │  200 OK      │              │               │                    │
   │  Call Connected│<────────────│              │               │                    │
   │<──────────────│              │              │               │                    │
   │               │              │              │               │                    │
   │               │         Audio Stream        │               │                    │
   │  ═══════════════════════════>│══════════════>│              │                    │
   │               │              │              │  Pipeline     │                    │
   │               │              │              │  starts       │                    │
   │               │              │              │               │                    │
   │               │              │              │  Greeting TTS │  TTS: "Hello..."   │
   │               │              │◄═════════════│──────────────────────────────────>│
   │  ◄══════ Agent Audio ════════│              │               │<──────────────────│
   │               │              │              │               │   (streaming audio)│
   │               │              │              │               │                    │
   ║  CONVERSATIONAL LOOP:        │              │               │                    │
   ║               │              │              │               │                    │
   │  Customer speaks             │              │               │                    │
   │  ═══════════════════════════>│══════════════>│              │                    │
   │               │              │              │  Audio frames │                    │
   │               │              │              │  into pipeline│                    │
   │               │              │              │               │                    │
   │               │              │     ┌────────┴─────────────┐ │                    │
   │               │              │     │ 1. Silero VAD:       │ │                    │
   │               │              │     │    Detect speech     │ │                    │
   │               │              │     │    start/end         │ │                    │
   │               │              │     │    (~50ms, local)    │ │                    │
   │               │              │     └─────────┬────────────┘ │                    │
   │               │              │               │              │                    │
   │               │              │               │  2. STT (streaming)               │
   │               │              │               │──────────────────────────────────>│
   │               │              │               │  Transcript (Deepgram Nova-2)     │
   │               │              │               │<──────────────────────────────────│
   │               │              │               │  (~150ms)    │                    │
   │               │              │               │              │                    │
   │               │              │     ┌─────────┴────────────┐ │                    │
   │               │              │     │ 3. LLM: Generate     │ │                    │
   │               │              │     │    response          │─────────────────────>│
   │               │              │     │    (Groq Llama 3.1   │ │                    │
   │               │              │     │     8B, ~50ms TTFT)  │<────────────────────│
   │               │              │     └──────────┬───────────┘ │                    │
   │               │              │               │              │                    │
   │               │              │               │  4. TTS (streaming)               │
   │               │              │               │──────────────────────────────────>│
   │               │              │               │  Audio chunks (Cartesia Sonic)    │
   │               │              │  Publish audio│<──────────────────────────────────│
   │  ◄══════ Agent Audio ════════│◄═════════════│               │  (~100ms TTFB)    │
   │               │              │              │               │                    │
   ║  BARGE-IN SCENARIO:          │              │               │                    │
   ║               │              │              │               │                    │
   │  Customer speaks during TTS  │              │               │                    │
   │  ═══════════════════════════>│══════════════>│              │                    │
   │               │              │     ┌─────────┴────────────┐ │                    │
   │               │              │     │ Silero VAD detects   │ │                    │
   │               │              │     │ → Cancel TTS output  │ │                    │
   │               │              │     │ → Process new input  │ │                    │
   │               │              │     └──────────┬───────────┘ │                    │
   │               │              │               │              │                    │
   ║  CALL END:                   │              │               │                    │
   ║               │              │              │               │                    │
   │  Hang up      │              │              │               │                    │
   │──────────────>│  BYE         │              │               │                    │
   │               │─────────────>│  Disconnect  │               │                    │
   │               │              │─────────────>│  Pipeline     │                    │
   │               │              │              │  cleanup      │                    │
   │               │              │              │  (async task  │                    │
   │               │              │              │   cancelled)  │                    │
```

## Latency Breakdown per Turn

```
Total E2E Target: < 400ms

│◄─────────── End-to-End Latency ────────────────────────────────────►│
│                                                                      │
│  VAD        │    STT         │      LLM       │    TTS     │  Net   │
│  ~50ms      │    ~150ms      │      ~50ms     │    ~100ms  │ ~50ms  │
│─────────────│────────────────│────────────────│────────────│────────│
│  Speech     │  Streaming     │  Streaming     │  Streaming │  WS /  │
│  endpoint   │  transcription │  TTFT          │  TTFB      │ WebRTC │
│  detection  │  (Deepgram     │  (Groq Llama   │  (Cartesia │  hop   │
│  (Silero)   │   Nova-2)      │   3.1 8B)      │   Sonic)   │        │
```

## Control Plane vs Media Plane

| Plane | Protocol | Path | Latency Impact |
|---|---|---|---|
| **Control** | HTTP | POST /calls → creates Pipecat pipeline (async task) | Pipeline creation: ~10ms (one-time) |
| **Media (dev)** | WebSocket | Browser ↔ Pipecat pipeline directly | ~50ms round-trip |
| **Media (prod)** | WebRTC | Twilio → Daily.co → Pipecat pipeline | ~30ms per hop |
| **AI Pipeline** | HTTPS (streaming) | Pipeline → Deepgram/Groq/Cartesia | ~350ms total (streaming) |
