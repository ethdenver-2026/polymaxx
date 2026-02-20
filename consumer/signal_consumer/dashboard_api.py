"""
FastAPI REST endpoints for the consumer dashboard.

Exposes balances, signal log, config, and health check.
Runs alongside the WebSocket server on port 8766.
"""

from __future__ import annotations

import json
import os
import queue

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from pydantic import BaseModel

from .balances import get_balances
from .config import get_settings, get_trading_mode, set_trading_mode
from .db import get_paper_positions, get_signals, log_signal, subscribe, unsubscribe
from .signal_generator import generate_signal

app = FastAPI(title="Signal Consumer Dashboard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/balances")
def balances():
    try:
        b = get_balances()
        return b.to_dict()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/signals")
def signals(limit: int = 100):
    return get_signals(limit=limit)


@app.get("/api/signals/stream")
def signals_stream():
    """SSE endpoint — pushes a JSON event each time a signal is logged."""
    def event_generator():
        q = subscribe()
        try:
            while True:
                try:
                    row = q.get(timeout=30)
                    yield f"data: {json.dumps(row)}\n\n"
                except queue.Empty:
                    # Send keep-alive comment to prevent proxy/browser timeout
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            unsubscribe(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/config")
def config():
    s = get_settings()
    mode = get_trading_mode()

    if mode == "live":
        try:
            b = get_balances()
            bankroll = b.polymarket_usdc
        except Exception:
            bankroll = 0.0
    else:
        bankroll = s.bankroll_usdc

    return {
        "trading_mode": mode,
        "bankroll_usdc": bankroll,
        "max_position_usd": s.max_position_usd,
        "kelly_fraction": s.kelly_fraction,
        "edge_threshold_pct": s.edge_threshold_pct,
        "wallet_address": os.environ.get("POLYMARKET_WALLET_ADDRESS", ""),
    }


class TradingModeRequest(BaseModel):
    mode: str


@app.post("/api/config/trading-mode")
def set_mode(body: TradingModeRequest):
    try:
        set_trading_mode(body.mode)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "trading_mode": body.mode}


@app.get("/api/paper-positions")
def paper_positions():
    return get_paper_positions()


@app.post("/api/generate-signal")
async def generate_signal_endpoint():
    """Generate a weather signal on demand from live APIs."""
    result = await generate_signal()
    signal_data = result["signal_data"]
    response = result["response"]

    if signal_data:
        log_signal(signal_data, response)

    return {
        "ok": response["action"] not in ("error",),
        "action": response["action"],
        "signal": signal_data or None,
        "errors": response.get("errors", []),
    }
