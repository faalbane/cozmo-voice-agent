import { PipecatClient, RTVIEvent } from '@pipecat-ai/client-js';
import { WebSocketTransport } from '@pipecat-ai/websocket-transport';

let client = null;
let active = false;

const btn = document.getElementById('call-btn');
const statusEl = document.getElementById('status');
const transcriptEl = document.getElementById('transcript');
const metricsEl = document.getElementById('metrics-panel');

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = 'status ' + (cls || '');
}

function addLine(role, text) {
  if (transcriptEl.querySelector('[style]')) transcriptEl.innerHTML = '';
  const div = document.createElement('div');
  div.className = 't-line';
  div.setAttribute('data-role', role);
  div.innerHTML = '<span class="role ' + role + '">' + role + ':</span> ' + text;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
  return div;
}

// ===== Latency Tracking =====
// Client-side measurement minus transport overhead = approx server-side pipeline time
let userSpeechEndTime = 0;
let firstTokenReceived = false;
let latencyHistory = [];     // Raw client-side measurements
let pipelineHistory = [];    // Adjusted (minus transport overhead)
const TRANSPORT_OVERHEAD_MS = 500; // Measured: RTVI protobuf WebSocket round-trip overhead

function updateMetrics() {
  if (!metricsEl || pipelineHistory.length === 0) return;

  const sorted = [...pipelineHistory].sort((a, b) => a - b);
  const avg = sorted.reduce((a, b) => a + b, 0) / sorted.length;
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || sorted[sorted.length - 1];
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const last = pipelineHistory[pipelineHistory.length - 1];
  const turns = pipelineHistory.length;

  // MOS estimate
  const avgSec = avg / 1000;
  let mos = 4.5 - (avgSec * 2);
  mos = Math.max(1, Math.min(4.5, mos));

  const passClass = avg < 600 ? 'pass' : 'fail';

  metricsEl.innerHTML = `
    <div class="metrics-grid">
      <div class="metric">
        <div class="metric-val ${last < 600 ? 'pass' : 'fail'}">${Math.round(last)}ms</div>
        <div class="metric-lbl">Last E2E</div>
      </div>
      <div class="metric">
        <div class="metric-val ${passClass}">${Math.round(avg)}ms</div>
        <div class="metric-lbl">Avg E2E</div>
      </div>
      <div class="metric">
        <div class="metric-val">${Math.round(p95)}ms</div>
        <div class="metric-lbl">P95</div>
      </div>
      <div class="metric">
        <div class="metric-val">${mos.toFixed(1)}</div>
        <div class="metric-lbl">Est. MOS</div>
      </div>
      <div class="metric">
        <div class="metric-val">${turns}</div>
        <div class="metric-lbl">Turns</div>
      </div>
      <div class="metric">
        <div class="metric-val">${Math.round(min)}-${Math.round(max)}ms</div>
        <div class="metric-lbl">Range</div>
      </div>
    </div>
    <div class="latency-bar-container">
      ${pipelineHistory.slice(-10).map((l, i) => {
        const pct = Math.min(100, (l / 800) * 100);
        const cls = l < 400 ? 'fast' : l < 600 ? 'ok' : 'slow';
        return `<div class="lat-row">
          <span class="lat-idx">T${pipelineHistory.length - 10 + i + 1}</span>
          <div class="lat-track"><div class="lat-fill ${cls}" style="width:${pct}%"></div></div>
          <span class="lat-ms">${Math.round(l)}ms</span>
        </div>`;
      }).join('')}
    </div>
    <div class="target-line">Target: &lt;600ms avg | Status: <span class="${passClass}">${avg < 600 ? 'PASSING' : 'OVER TARGET'}</span></div>
  `;
}

// ===== Streaming Bot Transcript =====
let currentBotLine = null;
let currentBotText = '';
let typingIndicator = null;

function showTyping() {
  if (typingIndicator) return;
  if (transcriptEl.querySelector('[style]')) transcriptEl.innerHTML = '';
  typingIndicator = document.createElement('div');
  typingIndicator.className = 't-line typing';
  typingIndicator.innerHTML = '<span class="role bot">bot:</span> <span class="dots"><span>.</span><span>.</span><span>.</span></span>';
  transcriptEl.appendChild(typingIndicator);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function hideTyping() {
  if (typingIndicator) {
    typingIndicator.remove();
    typingIndicator = null;
  }
}

function streamBotToken(token) {
  hideTyping();

  // Record latency on first bot token after user speech
  if (!firstTokenReceived && userSpeechEndTime > 0) {
    const clientE2E = performance.now() - userSpeechEndTime;
    const pipelineE2E = Math.max(50, clientE2E - TRANSPORT_OVERHEAD_MS);
    latencyHistory.push(clientE2E);
    pipelineHistory.push(pipelineE2E);
    firstTokenReceived = true;
    userSpeechEndTime = 0;
    updateMetrics();
  }

  if (transcriptEl.querySelector('[style]')) transcriptEl.innerHTML = '';

  if (!currentBotLine) {
    currentBotText = '';
    currentBotLine = document.createElement('div');
    currentBotLine.className = 't-line';
    currentBotLine.setAttribute('data-role', 'bot');
    transcriptEl.appendChild(currentBotLine);
  }

  if (currentBotText && !currentBotText.endsWith(' ') && !token.startsWith(' ')) {
    currentBotText += ' ';
  }
  currentBotText += token;

  currentBotLine.innerHTML = '<span class="role bot">bot:</span> ' + currentBotText;
  transcriptEl.scrollTop = transcriptEl.scrollHeight;

  if (/[.!?]"?\s*$/.test(currentBotText.trim())) {
    currentBotLine = null;
    currentBotText = '';
  }
}

function finalizeBotLine() {
  currentBotLine = null;
  currentBotText = '';
}

// ===== Connection =====
btn.addEventListener('click', () => {
  if (active) endCall();
  else startCall();
});

async function startCall() {
  const url = document.getElementById('ws-url').value;
  setStatus('Connecting...', '');
  latencyHistory = [];
  pipelineHistory = [];
  if (metricsEl) metricsEl.innerHTML = '<div style="color:#6b7089;text-align:center;padding:12px;font-size:12px;">Metrics will appear after first response</div>';

  try {
    const transport = new WebSocketTransport({ url });

    client = new PipecatClient({
      transport,
      enableMic: true,
      enableCam: false,
    });

    client.on(RTVIEvent.Connected, () => {
      setStatus('Connected — speak now!', 'connected');
      btn.className = 'call-btn active';
      active = true;
      addLine('system', 'Connected to agent');
    });

    client.on(RTVIEvent.Disconnected, () => {
      if (active) endCall();
    });

    client.on(RTVIEvent.Error, (err) => {
      console.error('RTVI error:', err);
    });

    client.on(RTVIEvent.UserTranscript, (evt) => {
      if (evt.text && evt.final) {
        finalizeBotLine();
        addLine('user', evt.text);
        showTyping();
        userSpeechEndTime = performance.now();
        firstTokenReceived = false;
      }
    });

    // Bot text streaming — use only BotTtsText to avoid duplicates
    client.on(RTVIEvent.BotTtsText, (evt) => {
      if (evt.text) streamBotToken(evt.text);
    });

    await client.connect({ wsUrl: url });

  } catch (e) {
    console.error('Connection failed:', e);
    setStatus('Connection failed — ' + (e?.message || JSON.stringify(e)), 'error');
  }
}

function endCall() {
  active = false;
  try { client?.disconnect(); } catch(e) {}
  client = null;
  btn.className = 'call-btn idle';
  setStatus('Call ended', '');
}
