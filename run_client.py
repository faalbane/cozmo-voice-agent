#!/usr/bin/env python3
"""Start the voice agent AND server AND web client.

Usage:
    python run_client.py

Then open http://localhost:3001 in your browser.
"""

import asyncio
import http.server
import os
import sys
import threading
import webbrowser

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

from dotenv import load_dotenv
load_dotenv()

CLIENT_PORT = 3001
AGENT_WS_PORT = 8765
SERVER_PORT = 8080


def start_http_server():
    """Serve the client HTML."""
    client_dir = os.path.join(PROJECT_DIR, "public", "client")
    os.chdir(client_dir)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

    server = http.server.HTTPServer(("0.0.0.0", CLIENT_PORT), Handler)
    server.serve_forever()


def start_api_server():
    """Run the FastAPI server for concurrent calls in its own event loop."""
    os.chdir(PROJECT_DIR)
    import uvicorn
    from src.server import app
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="info")


async def main():
    # Start HTTP file server (thread)
    t1 = threading.Thread(target=start_http_server, daemon=True)
    t1.start()

    # Start FastAPI server (thread with its own event loop)
    t2 = threading.Thread(target=start_api_server, daemon=True)
    t2.start()

    print()
    print("=" * 50)
    print("  ShopEase Voice Agent")
    print("=" * 50)
    print(f"  Single call:      http://localhost:{CLIENT_PORT}")
    print(f"  Concurrent demo:  http://localhost:{CLIENT_PORT}/multi.html")
    print(f"  Server API:       http://localhost:{SERVER_PORT}/calls")
    print(f"  Agent WebSocket:  ws://localhost:{AGENT_WS_PORT}")
    print()
    print("  Opening browser...")
    print("=" * 50)
    print()

    webbrowser.open(f"http://localhost:{CLIENT_PORT}")

    # Start the single-call Pipecat agent (main event loop)
    from src.agent import run_websocket_agent
    await run_websocket_agent(host="0.0.0.0", port=AGENT_WS_PORT)


if __name__ == "__main__":
    asyncio.run(main())
