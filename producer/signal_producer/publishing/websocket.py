"""In-memory WebSocket signal publisher."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any

import structlog
from fastapi import WebSocket

from ..models.models import SignalRecord
from ..signals.types import ProducerSignal
from ..strategies.base import Signal

logger = structlog.get_logger()


def _json_safe(value: Any) -> Any:
    """Convert dataclass payload values into JSON-serializable values."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


class SignalBroadcaster:
    """Tracks active WebSocket clients and broadcasts signals."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket client connected", clients=len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WebSocket client disconnected", clients=len(self._connections))

    async def _broadcast_payload(self, payload: dict[str, Any], market_id: str, token_id: str) -> None:
        payload["published_at"] = datetime.now(UTC).isoformat()

        async with self._lock:
            connections = list(self._connections)

        if not connections:
            logger.info(
                "No websocket clients connected; signal not delivered",
                market_id=market_id,
                token_id=token_id,
            )
            return

        async def _send(websocket: WebSocket) -> Exception | None:
            try:
                await websocket.send_json(payload)
                return None
            except Exception as exc:
                logger.error(
                    "WebSocket send failed",
                    error=str(exc),
                    market_id=market_id,
                    token_id=token_id,
                )
                return exc

        send_results = await asyncio.gather(*[_send(websocket) for websocket in connections], return_exceptions=False)
        failed = [websocket for websocket, result in zip(connections, send_results, strict=False) if result is not None]

        if failed:
            async with self._lock:
                for websocket in failed:
                    self._connections.discard(websocket)

        logger.info(
            "Signal broadcast complete",
            recipients=len(connections) - len(failed),
            failed=len(failed),
            market_id=market_id,
            token_id=token_id,
        )

    async def broadcast_signal(self, signal: Signal) -> None:
        payload = _json_safe(asdict(signal))
        await self._broadcast_payload(payload, market_id=signal.market_id, token_id=signal.token_id)

    async def broadcast_signal_record(self, record: SignalRecord) -> None:
        payload = {
            "id": record.id,
            "strategy": record.strategy,
            "market_id": record.market_id,
            "token_id": record.token_id,
            "model_probability": record.model_probability,
            "market_price": record.market_price,
            "edge": record.edge,
            "confidence": record.confidence,
            "decision": record.decision,
            "skip_reason": record.skip_reason,
            "created_at": record.created_at,
            "metadata_json": record.metadata_json,
        }
        await self._broadcast_payload(_json_safe(payload), market_id=record.market_id, token_id=record.token_id)

    async def broadcast_producer_signal(self, signal: ProducerSignal) -> None:
        """Broadcast a ProducerSignal to all connected clients."""
        payload = _json_safe(asdict(signal))

        # Extract identifiers from first exchange for logging
        market_id = ""
        token_id = ""
        if signal.exchanges:
            first_exchange = signal.exchanges[0]
            market_id = first_exchange.get("event_id", "")
            token_id = first_exchange.get("token_id", "")

        await self._broadcast_payload(payload, market_id=market_id, token_id=token_id)


broadcaster = SignalBroadcaster()
