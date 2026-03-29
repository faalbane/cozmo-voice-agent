"""HTTP server for managing multiple concurrent voice agent sessions.

Each POST /calls spins up a new Pipecat pipeline with its own WebSocket port.
This is how we handle 100+ concurrent calls — one pipeline per call.
"""

import asyncio
import logging
import os
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from src.agent import run_websocket_agent, run_daily_agent
from src.metrics.collector import MetricsCollector, start_metrics_server
from src.state.call_state import CallStateManager
from src.resilience.recovery import get_health_status

logger = logging.getLogger(__name__)

app = FastAPI(title="ShopEase Voice Agent Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Track active call tasks
active_calls: dict[str, asyncio.Task] = {}
next_ws_port = 8766  # Start assigning WebSocket ports from here


@app.post("/calls")
async def create_call():
    """Create a new voice agent session.

    Returns the WebSocket URL to connect a client to.
    """
    global next_ws_port

    call_id = f"call-{uuid.uuid4().hex[:8]}"
    port = next_ws_port
    next_ws_port += 1

    host = os.getenv("AGENT_HOST", "0.0.0.0")

    # Launch agent pipeline in background
    task = asyncio.create_task(run_websocket_agent(host=host, port=port))
    active_calls[call_id] = task

    # Clean up when the task finishes
    def on_done(t):
        active_calls.pop(call_id, None)
        logger.info(f"Call {call_id} pipeline ended")

    task.add_done_callback(on_done)

    logger.info(f"Created call {call_id} on port {port}")

    return JSONResponse({
        "call_id": call_id,
        "websocket_url": f"ws://{host}:{port}",
        "status": "ready",
    })


@app.post("/calls/daily")
async def create_daily_call(room_url: str, token: str):
    """Create a new voice agent for a Daily.co room."""
    call_id = f"daily-{uuid.uuid4().hex[:8]}"

    task = asyncio.create_task(run_daily_agent(room_url, token, call_id))
    active_calls[call_id] = task

    def on_done(t):
        active_calls.pop(call_id, None)

    task.add_done_callback(on_done)

    return JSONResponse({
        "call_id": call_id,
        "room_url": room_url,
        "status": "connected",
    })


@app.get("/calls")
async def list_calls():
    """List all active calls."""
    return JSONResponse({
        "active_calls": len(active_calls),
        "call_ids": list(active_calls.keys()),
    })


@app.delete("/calls/{call_id}")
async def end_call(call_id: str):
    """End a specific call."""
    task = active_calls.pop(call_id, None)
    if task:
        task.cancel()
        return JSONResponse({"status": "ended", "call_id": call_id})
    return JSONResponse({"status": "not_found"}, status_code=404)


@app.get("/healthz")
async def healthz():
    """Health check endpoint."""
    status = get_health_status()
    status["active_calls"] = len(active_calls)
    code = 200 if status["status"] == "healthy" else 503
    return JSONResponse(status, status_code=code)


async def run_server(host: str = "0.0.0.0", port: int = 8080):
    """Start the HTTP server for managing agent sessions."""
    # Start Prometheus metrics
    metrics_port = int(os.getenv("METRICS_PORT", "9100"))
    start_metrics_server(metrics_port)

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()
