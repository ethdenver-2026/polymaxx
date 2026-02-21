"""FastAPI server exposing websocket signal stream."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .publishing.websocket_signal_broadcaster import broadcaster as _default_broadcaster

if TYPE_CHECKING:
    from .publishing.websocket_signal_broadcaster import SignalBroadcaster

logger = structlog.get_logger()
app = FastAPI(title="Signal Producer WebSocket Server", version="0.1.0")

# The active broadcaster — defaults to the module-level singleton but can be
# replaced by the orchestrator's broadcaster (which has reputation tracking).
_active_broadcaster: SignalBroadcaster = _default_broadcaster


def set_broadcaster(b: SignalBroadcaster) -> None:
    """Replace the active broadcaster (called by orchestrator on startup)."""
    global _active_broadcaster
    _active_broadcaster = b
    logger.info("WebSocket server broadcaster replaced by orchestrator instance")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/signals")
async def signals_websocket(websocket: WebSocket) -> None:
    consumer_did = websocket.query_params.get("consumer_did") or f"anon-signal-{id(websocket)}"
    await _active_broadcaster.connect(websocket, consumer_did=consumer_did)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await _active_broadcaster.disconnect(consumer_did=consumer_did)
    except Exception as exc:
        logger.exception("websocket connection error", error=str(exc))
        await _active_broadcaster.disconnect(consumer_did=consumer_did)


@app.websocket("/ws/bids")
async def bids_websocket(websocket: WebSocket) -> None:
    consumer_did = websocket.query_params.get("consumer_did") or f"anon-bid-{id(websocket)}"
    await _active_broadcaster.connect_bid(websocket, consumer_did=consumer_did)
    try:
        while True:
            payload = await websocket.receive_json()
            await _active_broadcaster.handle_bid_payload(payload, consumer_did=consumer_did)
    except WebSocketDisconnect:
        await _active_broadcaster.disconnect_bid(consumer_did=consumer_did)
    except Exception as exc:
        logger.exception("bid websocket connection error", error=str(exc), consumer_did=consumer_did)
        await _active_broadcaster.disconnect_bid(consumer_did=consumer_did)


def run_signal_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the producer websocket FastAPI server."""
    import uvicorn

    logger.info("Starting websocket server", host=host, port=port)
    uvicorn.run("signal_producer.ws_server:app", host=host, port=port, log_level="info")
