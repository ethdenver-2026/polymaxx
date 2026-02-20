"""
WebSocket server that receives signal JSON payloads and executes trades.

The consumer listens for incoming signals, validates edge against the live
CLOB orderbook price, and executes if the edge still holds.

Usage:
    python -m signal_consumer.server
    python -m signal_consumer.server --port 8765 --host 0.0.0.0

Signal payload (JSON over WebSocket):
    {
        "token_id": "9049613919983...",
        "side": "buy",
        "model_probability": 0.42,
        "market_price": 0.35,
        "edge": 0.07,
        "position_size_usd": 3.50,
        "description": "Will temp be 44-45F in NYC on Feb 21?",
        "metadata": { ... }
    }

Response payload (JSON):
    {
        "action": "executed" | "skipped" | "error",
        "signal_price": 0.35,
        "live_price": 0.36,
        "signal_edge": 0.07,
        "live_edge": 0.06,
        "order_id": "0xabc...",
        "status": "live",
        "errors": []
    }
"""

from __future__ import annotations

import asyncio
import json
import os
import logging

import websockets
from dotenv import load_dotenv

from .execute_order import execute_signal_data

logger = logging.getLogger("signal_consumer.server")

# Required fields in a signal payload
REQUIRED_FIELDS = {"token_id", "model_probability", "market_price", "position_size_usd"}


def _validate_signal(data: dict) -> list[str]:
    """Validate that a signal payload has all required fields."""
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        return [f"Missing required fields: {', '.join(sorted(missing))}"]

    errors = []
    if not (0 <= data["model_probability"] <= 1):
        errors.append("model_probability must be between 0 and 1")
    if not (0 < data["market_price"] < 1):
        errors.append("market_price must be between 0 and 1 (exclusive)")
    if data["position_size_usd"] <= 0:
        errors.append("position_size_usd must be positive")
    return errors


async def _handle_signal(websocket):
    """Handle incoming WebSocket connections and process signals."""
    remote = websocket.remote_address
    logger.info("Client connected: %s:%s", remote[0], remote[1])

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except json.JSONDecodeError as e:
                response = {"action": "error", "errors": [f"Invalid JSON: {e}"]}
                await websocket.send(json.dumps(response))
                continue

            logger.info(
                "Signal received: %s (token=%s...)",
                data.get("description", "unknown")[:60],
                data.get("token_id", "?")[:20],
            )

            # Validate payload
            validation_errors = _validate_signal(data)
            if validation_errors:
                response = {"action": "error", "errors": validation_errors}
                await websocket.send(json.dumps(response))
                continue

            # Execute in a thread to avoid blocking the event loop
            # (py-clob-client uses synchronous requests internally)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: execute_signal_data(data)
            )

            if result.success:
                action = "executed"
            elif result.live_edge is not None and not result.success:
                action = "skipped"
            else:
                action = "error"

            response = {
                "action": action,
                "signal_price": result.signal_price,
                "live_price": result.live_price,
                "signal_edge": result.signal_edge,
                "live_edge": result.live_edge,
                "order_id": result.order_id,
                "status": result.status,
                "errors": result.errors,
            }

            logger.info(
                "Signal processed: action=%s, live_edge=%s, order_id=%s",
                action,
                f"{result.live_edge*100:.1f}%" if result.live_edge is not None else "N/A",
                result.order_id or "none",
            )

            await websocket.send(json.dumps(response))

    except websockets.exceptions.ConnectionClosed:
        logger.info("Client disconnected: %s:%s", remote[0], remote[1])


async def start_server(host: str = "localhost", port: int = 8765):
    """Start the WebSocket signal consumer server."""
    logger.info("Starting signal consumer on ws://%s:%d", host, port)

    async with websockets.serve(_handle_signal, host, port):
        await asyncio.Future()  # Run forever


def main():
    load_dotenv()

    import argparse

    parser = argparse.ArgumentParser(description="Signal consumer WebSocket server")
    parser.add_argument("--host", default="localhost", help="Bind address (default: localhost)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    asyncio.run(start_server(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
