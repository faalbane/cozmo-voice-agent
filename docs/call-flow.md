# Call Flow: Media & Control Plane

## Sequence Diagram

```
Customer       Twilio        SIP Bridge      LiveKit         Agent Worker       External APIs
(PSTN)        (SIP Trunk)    (livekit/sip)   (SFU)          (Python)           (Deepgram/OpenAI/Cartesia)
   │               │              │              │               │                    │
   │  Dial Phone # │              │              │               │                    │
   │──────────────>│              │              │               │                    │
   │               │  SIP INVITE  │              │               │                    │
   │               │─────────────>│              │               │                    │
   │               │              │  Create Room │               │                    │
   │               │              │─────────────>│               │                    │
   │               │              │              │  Dispatch Job │                    │
   │               │              │              │──────────────>│                    │
   │               │              │              │               │                    │
   │               │              │  200 OK      │  Accept Job   │                    │
   │               │  200 OK      │<─────────────│<──────────────│                    │
   │  Call Connected│<────────────│              │               │                    │
   │<──────────────│              │              │               │                    │
   │               │              │              │               │                    │
   │               │         RTP Audio           │  Subscribe    │                    │
   │  ═══════════════════════════════════════════>│  to caller    │                    │
   │               │              │              │  audio track  │                    │
   │               │              │              │               │                    │
   │               │              │              │  Agent joins  │                    │
   │               │              │              │<──────────────│                    │
   │               │              │              │               │                    │
   │               │              │              │  Greeting TTS │  TTS: "Hello..."   │
   │               │              │              │<──────────────│───────────────────>│
   │  ◄══════ Agent Audio ═══════════════════════│               │<───────────────────│
   │               │              │              │               │   (streaming audio)│
   │               │              │              │               │                    │
   ║  CONVERSATIONAL LOOP:        │              │               │                    │
   ║               │              │              │               │                    │
   │  Customer speaks             │              │               │                    │
   │  ═══════════════════════════════════════════>│               │                    │
   │               │              │              │  Audio frames │                    │
   │               │              │              │──────────────>│                    │
   │               │              │              │               │                    │
   │               │              │              │     ┌─────────┴────────────┐       │
   │               │              │              │     │ 1. VAD: Detect       │       │
   │               │              │              │     │    speech start/end  │       │
   │               │              │              │     │    (~50ms, local)    │       │
   │               │              │              │     └──────────┬───────────┘       │
   │               │              │              │               │                    │
   │               │              │              │               │  2. STT (streaming)│
   │               │              │              │               │───────────────────>│
   │               │              │              │               │  Transcript        │
   │               │              │              │               │<───────────────────│
   │               │              │              │               │  (~150ms)          │
   │               │              │              │               │                    │
   │               │              │              │     ┌─────────┴────────────┐       │
   │               │              │              │     │ 3. LLM: Generate     │       │
   │               │              │              │     │    response          │───────>│
   │               │              │              │     │    (may call KB tool)│       │
   │               │              │              │     │    (~200ms TTFT)     │<──────│
   │               │              │              │     └──────────┬───────────┘       │
   │               │              │              │               │                    │
   │               │              │              │               │  4. TTS (streaming)│
   │               │              │              │               │───────────────────>│
   │               │              │              │               │  Audio chunks      │
   │               │              │              │  Publish audio│<───────────────────│
   │  ◄══════ Agent Audio ═══════════════════════│<──────────────│  (~100ms TTFB)     │
   │               │              │              │               │                    │
   ║  BARGE-IN SCENARIO:          │              │               │                    │
   ║               │              │              │               │                    │
   │  Customer speaks during TTS  │              │               │                    │
   │  ═══════════════════════════════════════════>│               │                    │
   │               │              │              │──────────────>│                    │
   │               │              │              │     ┌─────────┴────────────┐       │
   │               │              │              │     │ VAD detects speech   │       │
   │               │              │              │     │ → Cancel TTS         │       │
   │               │              │              │     │ → Process new input  │       │
   │               │              │              │     └──────────┬───────────┘       │
   │               │              │              │               │                    │
   ║  CALL END:                   │              │               │                    │
   ║               │              │              │               │                    │
   │  Hang up      │              │              │               │                    │
   │──────────────>│  BYE         │              │               │                    │
   │               │─────────────>│  Remove      │               │                    │
   │               │              │  participant │  Disconnect   │                    │
   │               │              │─────────────>│──────────────>│                    │
   │               │              │              │               │  Cleanup           │
   │               │              │              │               │  (Redis, metrics)  │
```

## Latency Breakdown per Turn

```
Total E2E Target: < 600ms

│◄─────────── End-to-End Latency ────────────────────────────────────►│
│                                                                      │
│  VAD        │    STT         │      LLM          │    TTS     │ Net │
│  ~50ms      │    ~150ms      │      ~200ms       │    ~100ms  │~100ms│
│─────────────│────────────────│───────────────────│────────────│──────│
│  Speech     │  Streaming     │  Streaming        │  Streaming │ SFU │
│  endpoint   │  transcription │  TTFT             │  TTFB      │ hop │
│  detection  │  (Deepgram)    │  (GPT-4o-mini)    │  (Cartesia)│     │
```

## Control Plane vs Media Plane

| Plane | Protocol | Path | Latency Impact |
|---|---|---|---|
| **Control** | HTTP/WebSocket | LiveKit API → Agent Worker | Job dispatch: ~50ms (one-time) |
| **Media (inbound)** | RTP → WebRTC | Twilio → SIP Bridge → LiveKit SFU → Agent | ~20ms per hop |
| **Media (outbound)** | WebRTC → RTP | Agent → LiveKit SFU → SIP Bridge → Twilio | ~20ms per hop |
| **AI Pipeline** | HTTPS (streaming) | Agent → Deepgram/OpenAI/Cartesia | ~450ms total (streaming) |
