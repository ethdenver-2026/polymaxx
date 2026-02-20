"""WebSocket ingestion from producer signal stream."""

from __future__ import annotations

import asyncio
import json

import structlog
import websockets

from .config import Settings
from .consumer_engine import process_signal_payload
from .db import log_signal

logger = structlog.get_logger()


def handle_raw_ws_message(message: str, settings: Settings) -> dict:
    """Decode raw websocket JSON, process signal, and persist result."""
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as exc:
        response = {"action": "error", "errors": [f"invalid_json: {exc}"]}
        logger.error("Invalid websocket JSON payload", error=str(exc))
        return response

    try:
        response = process_signal_payload(payload, settings)
    except Exception as exc:
        logger.exception("Signal processing failed", error=str(exc))
        response = {"action": "error", "errors": [f"processing_failed: {exc}"]}

    try:
        log_signal(payload, response)
    except Exception as exc:
        logger.exception("Failed to persist consumer signal log", error=str(exc))

    return response


async def consume_producer_signals(settings: Settings) -> None:
    """Reconnect loop that consumes producer websocket signals forever."""
    ws_url = settings.producer_ws_url
    reconnect_delay = settings.producer_ws_reconnect_seconds
    logger.info("Starting producer websocket ingestion", ws_url=ws_url)

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                logger.info("Connected to producer websocket", ws_url=ws_url)
                async for message in ws:
                    handle_raw_ws_message(message, settings)
        except Exception as exc:
            logger.error(
                "Producer websocket disconnected",
                ws_url=ws_url,
                reconnect_seconds=reconnect_delay,
                error=str(exc),
            )
            await asyncio.sleep(reconnect_delay)
