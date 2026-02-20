"""
Combined runner: starts the FastAPI REST server and WebSocket server together.

Usage:
    python -m signal_consumer.run
    python -m signal_consumer.run --ws-port 8765 --api-port 8766
"""

from __future__ import annotations

import asyncio
import logging
import threading

import uvicorn
from dotenv import load_dotenv

from .db import init_db
from .server import start_server

logger = logging.getLogger("signal_consumer.run")


def _run_api(host: str, port: int) -> None:
    """Run the FastAPI server in a background thread."""
    uvicorn.run(
        "signal_consumer.api:app",
        host=host,
        port=port,
        log_level="info",
    )


def main():
    load_dotenv()

    import argparse

    parser = argparse.ArgumentParser(description="Signal consumer (WebSocket + REST API)")
    parser.add_argument("--host", default="localhost", help="Bind address (default: localhost)")
    parser.add_argument("--ws-port", type=int, default=8765, help="WebSocket port (default: 8765)")
    parser.add_argument("--api-port", type=int, default=8766, help="REST API port (default: 8766)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Initialize signal log database
    init_db()
    logger.info("Signal database initialized")

    # Start FastAPI in a background thread
    api_thread = threading.Thread(
        target=_run_api,
        args=(args.host, args.api_port),
        daemon=True,
    )
    api_thread.start()
    logger.info("REST API started on http://%s:%d", args.host, args.api_port)

    # Run WebSocket server in the main async loop
    logger.info("Starting WebSocket server on ws://%s:%d", args.host, args.ws_port)
    asyncio.run(start_server(host=args.host, port=args.ws_port))


if __name__ == "__main__":
    main()
