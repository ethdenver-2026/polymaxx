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

from .execute_order import execute_order, MIN_ORDER_SIZE
from .strategy import run_strategy
from .db import log_signal

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

            # Run strategy checks in a thread (py-clob-client is synchronous)
            loop = asyncio.get_event_loop()
            strategy_result = await loop.run_in_executor(
                None, lambda: run_strategy(data)
            )

            strategy_checks = strategy_result.checks_as_dicts()

            if strategy_result.should_trade:
                # Strategy passed — execute the order
                side = data.get("side", "buy")
                size = strategy_result.adjusted_position_usd / strategy_result.adjusted_price
                if size < MIN_ORDER_SIZE:
                    size = float(MIN_ORDER_SIZE)

                exec_result = await loop.run_in_executor(
                    None,
                    lambda: execute_order(
                        token_id=data["token_id"],
                        side=side,
                        price=strategy_result.adjusted_price,
                        size=size,
                    ),
                )

                action = "executed" if exec_result.success else "error"
                response = {
                    "action": action,
                    "signal_price": data["market_price"],
                    "live_price": strategy_result.adjusted_price,
                    "signal_edge": strategy_result.signal_edge,
                    "live_edge": strategy_result.live_edge,
                    "order_id": exec_result.order_id,
                    "status": exec_result.status,
                    "errors": exec_result.errors,
                    "strategy_checks": strategy_checks,
                }
            else:
                # Strategy rejected the signal
                action = "skipped"
                response = {
                    "action": action,
                    "signal_price": data["market_price"],
                    "live_price": strategy_result.adjusted_price,
                    "signal_edge": strategy_result.signal_edge,
                    "live_edge": strategy_result.live_edge,
                    "order_id": None,
                    "status": None,
                    "errors": [strategy_result.skip_reason] if strategy_result.skip_reason else [],
                    "strategy_checks": strategy_checks,
                }

            logger.info(
                "Signal processed: action=%s, live_edge=%s, order_id=%s, skip=%s",
                action,
                f"{strategy_result.live_edge*100:.1f}%" if strategy_result.live_edge is not None else "N/A",
                response.get("order_id") or "none",
                strategy_result.skip_reason or "n/a",
            )

            # Persist signal + response to SQLite
            try:
                log_signal(data, response)
            except Exception:
                logger.exception("Failed to log signal to database")

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
