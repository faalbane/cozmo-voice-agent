"""Live call monitoring dashboard - FastAPI + WebSocket + SSE."""

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.state.call_state import CallStateManager
from src.resilience.recovery import get_health_status
from src.metrics.call_quality import estimate_mos, assess_quality

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.call_manager = CallStateManager()
    app.state.ws_clients: set[WebSocket] = set()
    # Start background task to push updates
    task = asyncio.create_task(broadcast_loop(app))
    yield
    task.cancel()


app = FastAPI(title="Voice Agent Dashboard", lifespan=lifespan)


async def broadcast_loop(app: FastAPI):
    """Push call state updates to all connected WebSocket clients every second."""
    while True:
        try:
            await asyncio.sleep(1)
            if not app.state.ws_clients:
                continue

            data = get_dashboard_data(app.state.call_manager)
            message = json.dumps(data)

            disconnected = set()
            for ws in app.state.ws_clients:
                try:
                    await ws.send_text(message)
                except Exception:
                    disconnected.add(ws)

            app.state.ws_clients -= disconnected
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Broadcast error: {e}")


def get_dashboard_data(cm: CallStateManager) -> dict:
    """Gather all dashboard data."""
    active_calls = cm.get_active_calls()
    health = get_health_status()

    return {
        "timestamp": time.time(),
        "active_calls": len(active_calls),
        "calls": [
            {
                "call_sid": c.get("call_sid", ""),
                "caller_id": c.get("caller_id", "Unknown"),
                "worker_id": c.get("worker_id", ""),
                "duration_s": round(time.time() - float(c.get("started_at", time.time()))),
                "status": c.get("status", "unknown"),
            }
            for c in active_calls
        ],
        "health": health,
    }


@app.get("/", response_class=HTMLResponse)
async def index():
    return DASHBOARD_HTML


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    app.state.ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        app.state.ws_clients.discard(ws)


@app.get("/api/calls")
async def get_calls():
    data = get_dashboard_data(app.state.call_manager)
    return JSONResponse(data)


@app.get("/healthz")
async def healthz():
    status = get_health_status()
    code = 200 if status["status"] == "healthy" else 503
    return JSONResponse(status, status_code=code)


DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Voice Agent - Live Dashboard</title>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d29;
    --border: #2a2d3a;
    --text: #e1e4ed;
    --muted: #8b8fa3;
    --green: #22c55e;
    --yellow: #eab308;
    --red: #ef4444;
    --blue: #3b82f6;
    --purple: #a855f7;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    background: var(--bg);
    color: var(--text);
    padding: 24px;
    min-height: 100vh;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
  }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header .status {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--muted);
  }
  .status-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--green);
    animation: pulse 2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
  }
  .stat-card .label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    margin-bottom: 8px;
  }
  .stat-card .value {
    font-size: 32px;
    font-weight: 700;
  }
  .stat-card .sub {
    font-size: 12px;
    color: var(--muted);
    margin-top: 4px;
  }
  .calls-section {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }
  .calls-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    font-size: 14px;
    font-weight: 600;
    display: flex;
    justify-content: space-between;
  }
  .calls-table {
    width: 100%;
    border-collapse: collapse;
  }
  .calls-table th {
    text-align: left;
    padding: 12px 20px;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
  }
  .calls-table td {
    padding: 12px 20px;
    font-size: 13px;
    border-bottom: 1px solid var(--border);
  }
  .calls-table tr:last-child td { border-bottom: none; }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }
  .badge.active { background: rgba(34,197,94,0.15); color: var(--green); }
  .badge.completed { background: rgba(59,130,246,0.15); color: var(--blue); }
  .badge.failed { background: rgba(239,68,68,0.15); color: var(--red); }
  .empty-state {
    padding: 48px;
    text-align: center;
    color: var(--muted);
    font-size: 14px;
  }
  .green { color: var(--green); }
  .yellow { color: var(--yellow); }
  .red { color: var(--red); }
</style>
</head>
<body>

<div class="header">
  <h1>ShopEase Voice Agent</h1>
  <div class="status">
    <div class="status-dot" id="ws-dot"></div>
    <span id="ws-status">Connecting...</span>
  </div>
</div>

<div class="stats-grid">
  <div class="stat-card">
    <div class="label">Active Calls</div>
    <div class="value green" id="active-calls">0</div>
    <div class="sub">concurrent sessions</div>
  </div>
  <div class="stat-card">
    <div class="label">Worker CPU</div>
    <div class="value" id="cpu">--</div>
    <div class="sub" id="cpu-sub">system load</div>
  </div>
  <div class="stat-card">
    <div class="label">Memory</div>
    <div class="value" id="memory">--</div>
    <div class="sub" id="memory-sub">utilization</div>
  </div>
  <div class="stat-card">
    <div class="label">Health</div>
    <div class="value green" id="health">--</div>
    <div class="sub">worker status</div>
  </div>
</div>

<div class="calls-section">
  <div class="calls-header">
    <span>Live Calls</span>
    <span id="call-count" style="color: var(--muted);">0 calls</span>
  </div>
  <table class="calls-table" id="calls-table">
    <thead>
      <tr>
        <th>Call ID</th>
        <th>Caller</th>
        <th>Worker</th>
        <th>Duration</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody id="calls-body">
      <tr><td colspan="5" class="empty-state">No active calls</td></tr>
    </tbody>
  </table>
</div>

<script>
let ws;
function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    document.getElementById('ws-status').textContent = 'Live';
    document.getElementById('ws-dot').style.background = '#22c55e';
  };

  ws.onclose = () => {
    document.getElementById('ws-status').textContent = 'Reconnecting...';
    document.getElementById('ws-dot').style.background = '#ef4444';
    setTimeout(connect, 2000);
  };

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    update(data);
  };
}

function formatDuration(s) {
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, '0')}`;
}

function update(data) {
  document.getElementById('active-calls').textContent = data.active_calls;
  document.getElementById('call-count').textContent = `${data.active_calls} calls`;

  const h = data.health || {};
  const cpu = h.cpu_percent ?? '--';
  const mem = h.memory_percent ?? '--';
  document.getElementById('cpu').textContent = typeof cpu === 'number' ? cpu.toFixed(1) + '%' : cpu;
  document.getElementById('memory').textContent = typeof mem === 'number' ? mem.toFixed(1) + '%' : mem;
  document.getElementById('memory-sub').textContent = h.memory_available_mb ? `${h.memory_available_mb} MB free` : 'utilization';

  const cpuEl = document.getElementById('cpu');
  cpuEl.className = 'value ' + (cpu > 90 ? 'red' : cpu > 70 ? 'yellow' : 'green');

  const healthEl = document.getElementById('health');
  healthEl.textContent = h.status || '--';
  healthEl.className = 'value ' + (h.status === 'healthy' ? 'green' : 'red');

  const tbody = document.getElementById('calls-body');
  if (!data.calls || data.calls.length === 0) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No active calls</td></tr>';
    return;
  }

  tbody.innerHTML = data.calls.map(c => `
    <tr>
      <td style="font-family: monospace;">${c.call_sid.substring(0, 20)}</td>
      <td>${c.caller_id || 'Unknown'}</td>
      <td style="color: var(--muted);">${c.worker_id}</td>
      <td>${formatDuration(c.duration_s)}</td>
      <td><span class="badge ${c.status}">${c.status}</span></td>
    </tr>
  `).join('');
}

connect();
</script>
</body>
</html>
"""
