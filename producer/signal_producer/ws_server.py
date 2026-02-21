"""FastAPI server exposing websocket signal stream."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from .main import run_once
from .publishing.websocket_signal_broadcaster import broadcaster

logger = structlog.get_logger()
app = FastAPI(title="Signal Producer WebSocket Server", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run-once")
async def run_cycle(cities: str | None = None) -> dict:
    try:
        city_list = [c.strip() for c in cities.split(",")] if cities else None
        signals = await run_once(cities=city_list, broadcast_signals=True)
        return {"signals_found": len(signals)}
    except Exception as exc:
        logger.exception("run-once failed", error=str(exc), cities=cities)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.websocket("/ws/signals")
async def signals_websocket(websocket: WebSocket) -> None:
    consumer_did = websocket.query_params.get("consumer_did") or f"anon-signal-{id(websocket)}"
    await broadcaster.connect(websocket, consumer_did=consumer_did)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(consumer_did=consumer_did)
    except Exception as exc:
        logger.exception("websocket connection error", error=str(exc))
        await broadcaster.disconnect(consumer_did=consumer_did)


@app.websocket("/ws/bids")
async def bids_websocket(websocket: WebSocket) -> None:
    consumer_did = websocket.query_params.get("consumer_did") or f"anon-bid-{id(websocket)}"
    await broadcaster.connect_bid(websocket, consumer_did=consumer_did)
    try:
        while True:
            payload = await websocket.receive_json()
            await broadcaster.handle_bid_payload(payload, consumer_did=consumer_did)
    except WebSocketDisconnect:
        await broadcaster.disconnect_bid(consumer_did=consumer_did)
    except Exception as exc:
        logger.exception("bid websocket connection error", error=str(exc), consumer_did=consumer_did)
        await broadcaster.disconnect_bid(consumer_did=consumer_did)


def run_signal_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the producer websocket FastAPI server."""
    import uvicorn

    logger.info("Starting websocket server", host=host, port=port)
    uvicorn.run("signal_producer.ws_server:app", host=host, port=port, log_level="info")
