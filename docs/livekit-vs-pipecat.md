# LiveKit Agents vs Pipecat: Comparison

## Overview

Both LiveKit Agents and Pipecat are frameworks for building real-time voice AI agents. They take fundamentally different approaches: LiveKit provides a vertically integrated platform (media server + agent SDK), while Pipecat is a transport-agnostic pipeline framework.

## Feature Comparison

| Dimension | LiveKit Agents | Pipecat |
|---|---|---|
| **Architecture** | Platform: SFU + Agent SDK + SIP Bridge | Framework: pipeline of frame processors |
| **SIP/Telephony** | Native SIP bridge, first-class Twilio integration | Requires external gateway (Jambonz, Daily SIP) |
| **Media Transport** | Built-in SFU (WebRTC), handles all routing | Pluggable transports (Daily, WebSocket, local) |
| **Voice Pipeline** | `VoicePipelineAgent` with built-in VAD, barge-in, turn-taking | Manual frame processor chain, more assembly needed |
| **Scaling** | Worker pool with load-based dispatch (`load_fnc`) | No built-in scaling; external orchestration required |
| **Process Isolation** | Each call in its own subprocess automatically | Single process by default; must implement isolation |
| **Observability** | `on_metrics_collected` gives per-turn STT/LLM/TTS breakdown | Must instrument manually at each processor stage |
| **Function Calling** | Native `@ai_callable` decorator, automatic tool execution | Supported but requires more wiring |
| **Code Verbosity** | ~50 lines for a complete voice agent | ~100-150 lines for equivalent functionality |
| **Flexibility** | Opinionated pipeline (good defaults, less control) | Highly flexible frame processors (full control) |
| **Language Support** | Python (primary), Node.js (community) | Python only |
| **Community** | Large (LiveKit ecosystem), enterprise backing | Growing, strong open-source community |
| **Hosting** | LiveKit Cloud available (managed) | Self-hosted only |

## When to Use LiveKit Agents

**Choose LiveKit when:**
- You need PSTN/SIP telephony integration (the SIP bridge is a massive time-saver)
- You need to handle 50+ concurrent calls (built-in worker scaling)
- You want production-ready observability out of the box
- You prefer convention over configuration
- You're building a telephony product (call centers, IVR replacement, voice bots)

**Example use cases:**
- Customer support phone agents
- Appointment scheduling bots
- Outbound sales dialers
- Interactive voice response (IVR) systems

## When to Use Pipecat

**Choose Pipecat when:**
- You need custom media processing (audio effects, real-time translation, multi-modal)
- You're not using telephony (browser-based, in-app voice, IoT devices)
- You need fine-grained control over the processing pipeline
- You want to mix and match transports (WebSocket today, WebRTC tomorrow)
- You're building experimental or research-oriented voice applications

**Example use cases:**
- In-browser voice assistants
- Real-time translation systems
- Custom audio processing pipelines
- Voice-controlled IoT applications
- Multi-modal (voice + vision) agents

## Why We Chose LiveKit for This Project

For this assignment (100 concurrent PSTN calls with <600ms latency), LiveKit is the clear winner:

1. **Native SIP trunk support** eliminates an entire integration layer. With Pipecat, we'd need to set up and maintain Jambonz or a similar SIP gateway, adding ~2 days of work and another failure point.

2. **Built-in worker scaling** with `load_fnc` and `load_threshold` directly solves the 100-call concurrency requirement. Pipecat would require building a custom orchestration layer from scratch.

3. **`on_metrics_collected` callback** provides exactly the per-turn latency breakdown (STT duration, LLM TTFT, TTS TTFB) the assignment demands, without any custom timing instrumentation.

4. **Subprocess isolation** means one crashing call doesn't take down others — critical for a 100-call demo.

5. **Pre-warmed processes** (`num_idle_processes`) ensure calls are picked up instantly, which is crucial for meeting the <600ms latency target on the first turn.

## Trade-offs We Accepted

- **Less control over the media pipeline**: LiveKit's `VoicePipelineAgent` is opinionated. We can't easily insert custom audio processing stages between STT and LLM. For this use case, we don't need to.

- **Platform lock-in**: Choosing LiveKit ties us to their SFU for media routing. The AI pipeline (STT/LLM/TTS providers) is still pluggable, but switching away from LiveKit for media would be a significant rewrite.

- **Cost at scale**: LiveKit Cloud pricing adds per-participant costs on top of API costs for STT/LLM/TTS. At 1000+ calls, self-hosting or optimizing the deployment becomes important.
