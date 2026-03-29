# LiveKit Agents vs Pipecat: Comparison

## Overview

Both LiveKit Agents and Pipecat are frameworks for building real-time voice AI agents. They take fundamentally different approaches: LiveKit provides a vertically integrated platform (media server + agent SDK), while Pipecat is a transport-agnostic pipeline framework.

## Feature Comparison

| Dimension | LiveKit Agents | Pipecat |
|---|---|---|
| **Architecture** | Platform: SFU + Agent SDK + SIP Bridge | Framework: pipeline of frame processors |
| **SIP/Telephony** | Native SIP bridge, first-class Twilio integration | Requires external gateway (Daily SIP, Jambonz) |
| **Media Transport** | Built-in SFU (WebRTC), handles all routing | Pluggable transports (Daily, WebSocket, local) |
| **Voice Pipeline** | `VoicePipelineAgent` with built-in VAD, barge-in, turn-taking | Frame processor chain, composable and transparent |
| **Scaling** | Worker pool with load-based dispatch (`load_fnc`) | One pipeline per async task; external orchestration for multi-host |
| **Process Isolation** | Each call in its own subprocess automatically | Each call in its own async task; lightweight but shared process |
| **Observability** | `on_metrics_collected` gives per-turn STT/LLM/TTS breakdown | Must instrument manually at each processor stage |
| **Function Calling** | Native `@ai_callable` decorator, automatic tool execution | Supported via LLM service function calling |
| **Code Verbosity** | ~50 lines for a complete voice agent | ~80-120 lines for equivalent functionality |
| **Flexibility** | Opinionated pipeline (good defaults, less control) | Highly flexible frame processors (full control) |
| **Language Support** | Python (primary), Node.js (community) | Python only |
| **Community** | Large (LiveKit ecosystem), enterprise backing | Growing, strong open-source community |
| **Hosting** | LiveKit Cloud available (managed) | Self-hosted; Daily.co for managed WebRTC layer |
| **Local Dev** | Requires LiveKit server + SIP bridge + cloud account | `python server.py` with 3 API keys |

## When to Use LiveKit Agents

**Choose LiveKit when:**
- You need a fully managed platform with built-in scaling
- You want subprocess isolation per call out of the box
- You need built-in observability (per-turn latency metrics)
- You prefer convention over configuration
- You're building a large-scale telephony product and want a managed SFU

**Example use cases:**
- Large call center deployments (1000+ concurrent)
- Enterprise telephony products needing managed infrastructure
- Teams that want turnkey scaling without custom orchestration

## When to Use Pipecat

**Choose Pipecat when:**
- You want a simple, transparent pipeline you can understand end-to-end
- You need to run locally for development without cloud accounts
- You want full control over the processing pipeline
- You want to mix and match transports (WebSocket for dev, WebRTC for prod)
- You're building with speed and simplicity as priorities
- You want to avoid platform lock-in

**Example use cases:**
- Voice AI agents with rapid development cycles
- Projects where local development experience matters
- Custom audio processing pipelines
- Multi-modal (voice + vision) agents
- Teams that prefer framework over platform

## Why We Chose Pipecat for This Project

For this project, Pipecat is the better fit. Here is why:

1. **Simplicity**: A complete voice agent runs with `python server.py` and 3 API keys (Deepgram, Groq, Cartesia). No LiveKit server to deploy, no SIP bridge to configure, no cloud account to create. The entire stack is transparent and debuggable.

2. **Local development**: With WebSocket transport, you can develop and test the full pipeline on localhost. LiveKit requires running their server, SIP bridge, and configuring room routing even for local testing.

3. **Transport flexibility**: The same pipeline code works with `WebSocketServerTransport` for development and `DailyTransport` for production WebRTC/PSTN. Switching transports is a one-line change, not an architectural shift.

4. **Pipeline transparency**: Every frame processor in the chain is visible and inspectable. When debugging latency, you can log timestamps at every stage. LiveKit's `VoicePipelineAgent` is a black box by comparison.

5. **Cost efficiency**: No SFU server costs during development. In production, Daily.co provides managed WebRTC only when needed for PSTN/WebRTC bridging. For WebSocket-only deployments, there are zero infrastructure costs beyond the AI API keys.

6. **Fast iteration**: The one-pipeline-per-call model via `server.py`'s HTTP API (`POST /calls`) is simple to reason about. Each call is an async task — no subprocess overhead, no worker dispatch complexity.

## Trade-offs We Accepted

- **No built-in scaling**: Pipecat does not have LiveKit's `load_fnc` / `load_threshold` for automatic worker dispatch. At scale, we need Nginx + Kubernetes HPA to distribute calls across server instances. This is more work, but it is standard infrastructure.

- **No built-in observability**: LiveKit's `on_metrics_collected` gives per-turn latency breakdowns for free. With Pipecat, we instrument this ourselves by adding timing to frame processors. More work upfront, but we get exactly the metrics we want.

- **Shared process per call**: LiveKit isolates each call in its own subprocess. Pipecat runs all calls as async tasks in a shared process. A truly pathological error could affect other calls. In practice, Python's async error handling and Pipecat's pipeline isolation make this a minor concern.

- **PSTN requires Daily.co**: LiveKit has native SIP trunking. With Pipecat, PSTN calls require Daily.co as a WebRTC/SIP bridge. This adds a dependency, but Daily.co is a well-supported integration that Pipecat maintains as a first-class transport.
