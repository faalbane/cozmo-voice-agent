#!/usr/bin/env python3
"""Start the voice agent AND a local HTTP server for the web client.

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


def start_http_server():
    """Serve the client HTML on a local HTTP server."""
    client_dir = os.path.join(os.path.dirname(__file__), "public", "client")
    os.chdir(client_dir)

    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Suppress logs

        def end_headers(self):
            # Allow ES module imports
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

    server = http.server.HTTPServer(("0.0.0.0", CLIENT_PORT), Handler)
    server.serve_forever()


async def main():
    # Start HTTP server for the web client in a thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    print()
    print("=" * 50)
    print("  ShopEase Voice Agent")
    print("=" * 50)
    print(f"  Agent WebSocket:  ws://localhost:{AGENT_WS_PORT}")
    print(f"  Web Client:       http://localhost:{CLIENT_PORT}")
    print()
    print("  Opening browser...")
    print("  Click the green button and start talking!")
    print("=" * 50)
    print()

    # Open browser
    webbrowser.open(f"http://localhost:{CLIENT_PORT}")

    # Start the Pipecat agent
    from src.agent import run_websocket_agent
    await run_websocket_agent(host="0.0.0.0", port=AGENT_WS_PORT)


if __name__ == "__main__":
    asyncio.run(main())
