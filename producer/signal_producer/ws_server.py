"""FastAPI server exposing websocket signal stream."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect

from .main import run_once
from .publishing.websocket import broadcaster

logger = structlog.get_logger()
app = FastAPI(title="Signal Producer WebSocket Server", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run-once")
async def run_cycle(cities: str | None = None) -> dict:
    try:
        city_list = [c.strip() for c in cities.split(",")] if cities else None
        signals = await run_once(cities=city_list)
        return {"signals_found": len(signals)}
    except Exception as exc:
        logger.exception("run-once failed", error=str(exc), cities=cities)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.websocket("/ws/signals")
async def signals_websocket(websocket: WebSocket) -> None:
    await broadcaster.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await broadcaster.disconnect(websocket)
    except Exception as exc:
        logger.exception("websocket connection error", error=str(exc))
        await broadcaster.disconnect(websocket)
