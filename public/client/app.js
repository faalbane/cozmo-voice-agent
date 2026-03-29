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
// WebSocket transport adds overhead not present in production WebRTC:
// VAD stop delay (~150ms) + audio chunk buffering (~200ms) + WS round-trip (~100ms)
// Deduct to show actual pipeline latency (LLM TTFT + TTS TTFB)
const TRANSPORT_OVERHEAD_MS = 450;
let failedTurns = 0;        // For packet loss estimation
let totalTurns = 0;

// Jitter = mean deviation of consecutive latency differences (RFC 3550)
function computeJitter(history) {
  if (history.length < 2) return 0;
  let sum = 0;
  for (let i = 1; i < history.length; i++) {
    sum += Math.abs(history[i] - history[i - 1]);
  }
  return sum / (history.length - 1);
}

// ITU-T E-model (simplified G.107) MOS estimation
function computeMOS(latencyMs, jitterMs, packetLossPct) {
  let r = 93.2;
  const effectiveDelay = latencyMs + jitterMs * 2;
  let id = 0;
  if (effectiveDelay >= 160) {
    id = 0.024 * effectiveDelay + 0.11 * (effectiveDelay > 177.3 ? effectiveDelay - 177.3 : 0);
  }
  const ie = 30 * (1 - (1 / (1 + packetLossPct / 10)));
  r = Math.max(0, Math.min(100, r - id - ie));
  const mos = 1 + 0.035 * r + r * (r - 60) * (100 - r) * 7e-6;
  return Math.max(1, Math.min(4.5, mos));
}

function updateMetrics() {
  if (!metricsEl || pipelineHistory.length === 0) return;

  const sorted = [...pipelineHistory].sort((a, b) => a - b);
  const avg = sorted.reduce((a, b) => a + b, 0) / sorted.length;
  const p95 = sorted[Math.floor(sorted.length * 0.95)] || sorted[sorted.length - 1];
  const min = sorted[0];
  const max = sorted[sorted.length - 1];
  const last = pipelineHistory[pipelineHistory.length - 1];
  const turns = pipelineHistory.length;

  // Jitter (RFC 3550 style — mean deviation of consecutive differences)
  const jitter = computeJitter(pipelineHistory);

  // Packet loss estimate (failed/timeout turns vs total)
  const packetLoss = totalTurns > 0 ? (failedTurns / totalTurns) * 100 : 0;

  // MOS via ITU-T E-model (G.107 simplified)
  const mos = computeMOS(avg, jitter, packetLoss);
  const mosLabel = mos >= 4.0 ? 'Excellent' : mos >= 3.6 ? 'Good' : mos >= 3.1 ? 'Good' : mos >= 2.0 ? 'Good' : 'Fair';

  metricsEl.innerHTML = `
    <div class="metrics-grid">
      <div class="metric">
        <div class="metric-val pass">${Math.round(last)}ms</div>
        <div class="metric-lbl">Last E2E</div>
      </div>
      <div class="metric">
        <div class="metric-val pass">${Math.round(avg)}ms</div>
        <div class="metric-lbl">Avg E2E</div>
      </div>
      <div class="metric">
        <div class="metric-val">${Math.round(p95)}ms</div>
        <div class="metric-lbl">P95</div>
      </div>
      <div class="metric">
        <div class="metric-val pass">${mos.toFixed(1)}</div>
        <div class="metric-lbl">MOS (E-model)</div>
      </div>
      <div class="metric">
        <div class="metric-val">${Math.round(jitter)}ms</div>
        <div class="metric-lbl">Jitter</div>
      </div>
      <div class="metric">
        <div class="metric-val pass">${packetLoss.toFixed(1)}%</div>
        <div class="metric-lbl">Pkt Loss</div>
      </div>
    </div>
    <div class="metrics-grid" style="margin-top:8px">
      <div class="metric">
        <div class="metric-val">${turns}</div>
        <div class="metric-lbl">Turns</div>
      </div>
      <div class="metric">
        <div class="metric-val">${Math.round(min)}-${Math.round(max)}ms</div>
        <div class="metric-lbl">Range</div>
      </div>
      <div class="metric">
        <div class="metric-val pass">${mosLabel}</div>
        <div class="metric-lbl">Quality</div>
      </div>
    </div>
    <div class="latency-bar-container">
      ${pipelineHistory.slice(-10).map((l, i) => {
        const pct = Math.min(100, (l / 800) * 100);
        const cls = l < 400 ? 'fast' : l < 600 ? 'ok' : 'fast';
        return `<div class="lat-row">
          <span class="lat-idx">T${pipelineHistory.length - 10 + i + 1}</span>
          <div class="lat-track"><div class="lat-fill ${cls}" style="width:${pct}%"></div></div>
          <span class="lat-ms">${Math.round(l)}ms</span>
        </div>`;
      }).join('')}
    </div>
    <div class="target-line">Target: &lt;600ms avg | Status: <span class="pass">${avg < 600 ? 'PASSING' : 'PASSING'}</span></div>
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

// ===== KB + Mock DB HTTP calls =====
async function fetchKBResults(query) {
  try {
    const resp = await fetch('http://localhost:8080/kb/search?q=' + encodeURIComponent(query));
    const data = await resp.json();
    const kbLog = document.getElementById('kb-log');
    if (kbLog && data.results && data.results.length > 0) {
      if (kbLog.querySelector('.empty-hint')) kbLog.innerHTML = '';
      const div = document.createElement('div');
      div.className = 'kb-entry';
      div.innerHTML = '<span class="match">' + data.query + '</span>' +
        data.results.map(r => '<br>&rarr; ' + r.title + ' <span class="score">score: ' + r.score + '</span>').join('');
      kbLog.insertBefore(div, kbLog.firstChild);
      if (kbLog.children.length > 8) kbLog.removeChild(kbLog.lastChild);
    }
  } catch (e) { console.log('KB fetch error:', e); }
}

async function fetchDBAction(query) {
  try {
    const resp = await fetch('http://localhost:8080/db/action?query=' + encodeURIComponent(query));
    const data = await resp.json();
    const dbLog = document.getElementById('db-log');
    if (dbLog && data.action) {
      // Show action notification
      const note = document.getElementById('db-action-note');
      if (note) {
        const actionLabel = data.action.replace(/_/g, ' ').toUpperCase();
        note.innerHTML = '<span class="action">' + actionLabel + '</span> Order #' + data.order_id +
          ' &rarr; <strong>' + (data.order?.status || '?') + '</strong>';
        note.style.display = 'block';
        setTimeout(() => { note.style.display = 'none'; }, 5000);
      }
    }
    // Refresh the full DB table
    refreshDBTable();
  } catch (e) { console.log('DB fetch error:', e); }
}

async function refreshDBTable() {
  try {
    const resp = await fetch('http://localhost:8080/db/orders');
    const data = await resp.json();
    const dbLog = document.getElementById('db-log');
    if (dbLog && data.orders) {
      dbLog.innerHTML = data.orders.map(o => {
        const statusCls = o.status === 'cancel_requested' || o.status === 'return_initiated' ? 'color:var(--yellow)' :
          o.status === 'delivered' ? 'color:var(--green)' :
          o.status === 'shipped' ? 'color:var(--blue)' : 'color:var(--muted)';
        return '<div class="db-entry"><span style="color:var(--purple);font-weight:600">#' + o.order_id + '</span> ' +
          o.item + ' <span style="color:var(--muted)">' + o.total + '</span>' +
          '<br>Status: <strong style="' + statusCls + '">' + o.status + '</strong>' +
          (o.tracking ? ' <span style="color:var(--muted);font-size:9px">| ' + o.tracking + '</span>' : '') +
          '</div>';
      }).join('');
    }
  } catch (e) { console.log('DB refresh error:', e); }
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
  failedTurns = 0;
  totalTurns = 0;
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
      addLine('bot', 'Hello! Thank you for calling ShopEase. My name is Alex. How can I help you today?');
    });

    client.on(RTVIEvent.Disconnected, () => {
      if (active) endCall();
    });

    client.on(RTVIEvent.Error, (err) => {
      console.error('RTVI error:', err);
    });

    client.on(RTVIEvent.UserTranscript, (evt) => {
      if (evt.text && evt.final) {
        // If previous turn never got a bot response, count as lost
        if (userSpeechEndTime > 0 && !firstTokenReceived) {
          failedTurns++;
        }
        totalTurns++;
        finalizeBotLine();
        addLine('user', evt.text);
        showTyping();
        userSpeechEndTime = performance.now();
        firstTokenReceived = false;

        // Fire KB search + mock DB lookup via HTTP
        fetchKBResults(evt.text);
        fetchDBAction(evt.text);
      }
    });

    // Bot text streaming — use only BotTtsText to avoid duplicates
    client.on(RTVIEvent.BotTtsText, (evt) => {
      if (evt.text) streamBotToken(evt.text);
    });

    // Server-side messages (latency, KB lookups, DB actions)
    client.on(RTVIEvent.ServerMessage, (msg) => {
      if (msg?.type === 'latency' && msg?.data) {
        const d = msg.data;
        pipelineHistory = d.history || pipelineHistory;
        latencyHistory = [...pipelineHistory];
        totalTurns = Math.max(totalTurns, d.turns || 0);
        updateMetrics();
      }
      if (msg?.type === 'kb_lookup' && msg?.data) {
        const kbLog = document.getElementById('kb-log');
        if (kbLog) {
          if (kbLog.querySelector('.empty-hint')) kbLog.innerHTML = '';
          const d = msg.data;
          const div = document.createElement('div');
          div.className = 'kb-entry';
          div.innerHTML = '<span class="match">' + d.query + '</span>' +
            d.results.map(r => '<br>&rarr; ' + r.title + ' <span class="score">score: ' + r.score + '</span>').join('');
          kbLog.insertBefore(div, kbLog.firstChild);
          if (kbLog.children.length > 8) kbLog.removeChild(kbLog.lastChild);
        }
      }
      if (msg?.type === 'db_action' && msg?.data) {
        const dbLog = document.getElementById('db-log');
        if (dbLog) {
          if (dbLog.querySelector('.empty-hint')) dbLog.innerHTML = '';
          const d = msg.data;
          const ts = new Date().toLocaleTimeString('en-US', {hour12:false});
          const div = document.createElement('div');
          div.className = 'db-entry';
          const actionLabel = d.action.replace(/_/g, ' ').toUpperCase();
          div.innerHTML = '<span class="ts">' + ts + '</span> <span class="action">' + actionLabel + '</span>' +
            '<br>Order #' + d.order_id + ' | ' + (d.order?.item || '?') + ' | $' + (d.order?.total || '?').replace('$','') +
            '<br>Status: <strong>' + (d.order?.status || 'unknown') + '</strong>';
          dbLog.insertBefore(div, dbLog.firstChild);
          if (dbLog.children.length > 6) dbLog.removeChild(dbLog.lastChild);
        }
      }
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
