"""Entrypoint for the voice agent.

Usage:
  # WebSocket mode (local dev, no cloud accounts needed):
  python src/main.py

  # Daily.co mode (production WebRTC / PSTN):
  python src/main.py --mode daily --room-url https://your.daily.co/room --token TOKEN

  # HTTP server mode (handles multiple concurrent calls via API):
  python src/main.py --mode server --port 8080
"""

import argparse
import asyncio
import logging
import os
import sys

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="ShopEase Voice Agent (Pipecat)")
    parser.add_argument(
        "--mode",
        choices=["websocket", "daily", "server"],
        default="websocket",
        help="Transport mode (default: websocket)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="WebSocket/server host")
    parser.add_argument("--port", type=int, default=8765, help="WebSocket/server port")
    parser.add_argument("--room-url", help="Daily.co room URL (daily mode)")
    parser.add_argument("--token", help="Daily.co token (daily mode)")
    args = parser.parse_args()

    # Validate required API keys
    required_keys = ["DEEPGRAM_API_KEY", "OPENAI_API_KEY", "CARTESIA_API_KEY"]
    missing = [k for k in required_keys if not os.getenv(k)]
    if missing:
        logger.error(f"Missing required API keys: {', '.join(missing)}")
        logger.error("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    if args.mode == "websocket":
        logger.info("Starting in WebSocket mode (local dev)")
        logger.info(f"Agent will listen on ws://{args.host}:{args.port}")
        logger.info("Connect a web client to start a conversation.")

        from src.agent import run_websocket_agent

        asyncio.run(run_websocket_agent(host=args.host, port=args.port))

    elif args.mode == "daily":
        if not args.room_url or not args.token:
            logger.error("Daily mode requires --room-url and --token")
            sys.exit(1)

        logger.info(f"Starting in Daily.co mode: {args.room_url}")

        from src.agent import run_daily_agent

        asyncio.run(run_daily_agent(args.room_url, args.token))

    elif args.mode == "server":
        logger.info(f"Starting HTTP server on {args.host}:{args.port}")
        logger.info("POST /calls to create new agent sessions")

        from src.server import run_server

        asyncio.run(run_server(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
