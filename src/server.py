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


@app.get("/kb/search")
async def kb_search(q: str = ""):
    """Search the knowledge base and return results."""
    from src.knowledge.search import _kb
    results = _kb.search(q, top_k=2)
    return JSONResponse({
        "query": q,
        "results": [{"title": r.title, "doc_id": r.doc_id, "score": round(r.score, 1), "content": r.content[:120]} for r in results],
    })


@app.get("/db/orders")
async def db_list_orders():
    """Return all orders from SQLite DB."""
    from src.db.orders import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders ORDER BY order_id")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return JSONResponse({"orders": rows})


def _spoken_to_digits(text: str) -> str:
    """Convert spoken numbers to digits: 'one two three four five' → '12345'."""
    word_map = {
        'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
        'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
    }
    import re
    words = re.findall(r'\b(?:' + '|'.join(word_map.keys()) + r')\b', text.lower())
    if len(words) >= 3:
        return ''.join(word_map[w] for w in words)
    return ''


@app.get("/db/action")
async def db_action(query: str = ""):
    """Detect order actions from user query and update real SQLite DB."""
    import re
    import datetime
    from src.db.orders import lookup_order, update_order_status

    query_lower = query.lower()

    # Try numeric order ID first, then spoken digits
    order_match = re.search(r'order\s*#?\s*(\d+)', query_lower)
    order_id = order_match.group(1) if order_match else None
    if not order_id:
        spoken = _spoken_to_digits(query_lower)
        if spoken:
            order_id = spoken

    has_action = order_id or any(w in query_lower for w in ['cancel', 'status', 'track', 'return'])
    if not has_action:
        return JSONResponse({"action": None})

    if not order_id:
        order_id = "12345"

    # Detect action from natural language — flexible status updates for any order
    action = "lookup"
    new_status = None

    # Known statuses that can be set via voice
    all_statuses = [
        'cancelled', 'canceled', 'cancel_requested', 'cancel',
        'shipped', 'shipping', 'delivered', 'processing',
        'completed', 'on hold', 'pending', 'returned',
        'return_initiated', 'refund_processing', 'refunded',
    ]
    # Normalize map
    status_normalize = {
        'cancelled': 'cancelled', 'canceled': 'cancelled', 'cancel': 'cancelled',
        'cancel_requested': 'cancel_requested',
        'shipped': 'shipped', 'shipping': 'shipped',
        'delivered': 'delivered', 'completed': 'completed',
        'processing': 'processing', 'pending': 'pending',
        'on hold': 'on_hold', 'returned': 'returned',
        'return_initiated': 'return_initiated',
        'refund_processing': 'refund_processing', 'refunded': 'refunded',
    }

    # Check for status update keywords
    is_update = any(w in query_lower for w in ['update', 'change', 'set', 'mark', 'make'])
    for s in all_statuses:
        if s in query_lower:
            new_status = status_normalize.get(s, s)
            action = f"update_to_{new_status}"
            break

    # Fallback action detection
    if not new_status:
        if 'cancel' in query_lower:
            action = "cancel_requested"
            new_status = "cancel_requested"
        elif 'return' in query_lower:
            action = "return_initiated"
            new_status = "return_initiated"
        elif 'refund' in query_lower:
            action = "refund_requested"
            new_status = "refund_processing"
        elif 'track' in query_lower:
            action = "tracking_lookup"

    order_data = lookup_order(order_id)
    if not order_data:
        order_data = {"status": "not_found", "item": "Unknown", "total": "$0.00"}

    if new_status and order_data.get("status") != "not_found":
        order_data = update_order_status(order_id, new_status) or order_data

    return JSONResponse({
        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
        "order_id": order_id,
        "action": action,
        "order": {
            "item": order_data.get("item", "Unknown"),
            "total": order_data.get("total", "$0.00"),
            "status": order_data.get("status", "unknown"),
            "tracking": order_data.get("tracking"),
            "customer_name": order_data.get("customer_name"),
        },
        "db": "SQLite (shopease.db)",
    })


@app.get("/calls/load-test")
async def load_test_stream(count: int = 100):
    """Stream real load test results via SSE as each batch completes."""
    import json as _json
    from starlette.responses import StreamingResponse
    from src.load_test import run_single_call, TEST_PROMPTS

    groq_key = os.getenv("GROQ_API_KEY")
    dg_key = os.getenv("DEEPGRAM_API_KEY")

    async def generate():
        all_results = []
        concurrency = 5

        for batch_start in range(0, count, concurrency):
            batch_end = min(batch_start + concurrency, count)
            tasks = [
                run_single_call(i, TEST_PROMPTS[i % len(TEST_PROMPTS)], groq_key, dg_key)
                for i in range(batch_start, batch_end)
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in batch_results:
                if isinstance(r, Exception):
                    all_results.append({"call_id": -1, "status": "error", "error": str(r), "latency_ms": -1})
                else:
                    all_results.append(r)

            # Compute running stats
            successful = [r for r in all_results if r.get("status") == "completed"]
            latencies = sorted([r["latency_ms"] for r in successful])
            avg = sum(latencies) / len(latencies) if latencies else 0
            p95 = latencies[int(len(latencies) * 0.95)] if len(latencies) > 1 else (latencies[0] if latencies else 0)

            update = {
                "progress": len(all_results),
                "total": count,
                "successful": len(successful),
                "failed": len(all_results) - len(successful),
                "avg_latency_ms": round(avg, 1),
                "p95_latency_ms": round(p95, 1),
                "min_latency_ms": round(latencies[0], 1) if latencies else 0,
                "max_latency_ms": round(latencies[-1], 1) if latencies else 0,
                "target_600ms": avg < 600,
                "batch": [r for r in batch_results if not isinstance(r, Exception)],
                "done": len(all_results) >= count,
            }
            yield f"data: {_json.dumps(update)}\n\n"
            await asyncio.sleep(0.5)  # Pace batches to avoid rate limits

    return StreamingResponse(generate(), media_type="text/event-stream")


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
