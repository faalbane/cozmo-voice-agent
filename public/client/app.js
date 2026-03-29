import { PipecatClient, RTVIEvent } from '@pipecat-ai/client-js';
import { WebSocketTransport } from '@pipecat-ai/websocket-transport';

let client = null;
let active = false;

const btn = document.getElementById('call-btn');
const statusEl = document.getElementById('status');
const transcriptEl = document.getElementById('transcript');

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

// Get or create the current streaming bot line
let currentBotLine = null;
let currentBotText = '';

function streamBotToken(token) {
  if (transcriptEl.querySelector('[style]')) transcriptEl.innerHTML = '';

  if (!currentBotLine) {
    currentBotText = '';
    currentBotLine = document.createElement('div');
    currentBotLine.className = 't-line';
    currentBotLine.setAttribute('data-role', 'bot');
    transcriptEl.appendChild(currentBotLine);
  }

  // Add space between tokens if needed
  if (currentBotText && !currentBotText.endsWith(' ') && !token.startsWith(' ')) {
    currentBotText += ' ';
  }
  currentBotText += token;

  currentBotLine.innerHTML = '<span class="role bot">bot:</span> ' + currentBotText;
  transcriptEl.scrollTop = transcriptEl.scrollHeight;

  // Finalize on sentence-ending punctuation
  if (/[.!?]"?\s*$/.test(currentBotText.trim())) {
    currentBotLine = null;
    currentBotText = '';
  }
}

function finalizeBotLine() {
  currentBotLine = null;
  currentBotText = '';
}

btn.addEventListener('click', () => {
  if (active) endCall();
  else startCall();
});

async function startCall() {
  const url = document.getElementById('ws-url').value;
  setStatus('Connecting...', '');

  try {
    const transport = new WebSocketTransport({
      url: url,
    });

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
      setStatus('Error: ' + (err.message || err), 'error');
    });

    client.on(RTVIEvent.UserTranscript, (evt) => {
      if (evt.text && evt.final) {
        addLine('user', evt.text);
      }
    });

    // Stream bot tokens into the transcript in real-time
    client.on(RTVIEvent.BotTtsText, (evt) => {
      if (evt.text) {
        streamBotToken(evt.text);
      }
    });

    await client.connect({ wsUrl: url });

  } catch (e) {
    console.error('Connection failed:', e);
    setStatus('Connection failed — ' + e.message, 'error');
  }
}

function endCall() {
  active = false;
  try { client?.disconnect(); } catch(e) {}
  client = null;
  btn.className = 'call-btn idle';
  setStatus('Call ended', '');
}
