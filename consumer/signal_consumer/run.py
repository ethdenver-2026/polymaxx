"""Combined runner: dashboard API + producer websocket ingestion loop."""

from __future__ import annotations

import asyncio
import logging
import threading

import uvicorn
from dotenv import load_dotenv

from .config import get_settings
from .db import init_db
from .ws_ingestion import consume_producer_signals

logger = logging.getLogger("signal_consumer.run")


def _run_api(host: str, port: int) -> None:
    """Run the FastAPI server in a background thread."""
    uvicorn.run(
        "signal_consumer.dashboard_api:app",
        host=host,
        port=port,
        log_level="info",
    )


def main():
    load_dotenv()
    settings = get_settings()

    import argparse

    parser = argparse.ArgumentParser(description="Signal consumer (producer websocket + dashboard API)")
    parser.add_argument("--host", default="localhost", help="Bind address (default: localhost)")
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

    logger.info("Starting producer websocket ingestion loop: %s", settings.producer_ws_url)
    asyncio.run(consume_producer_signals(settings))


if __name__ == "__main__":
    main()
