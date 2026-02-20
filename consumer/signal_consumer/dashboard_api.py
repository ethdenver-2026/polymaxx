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

from .balances import get_balances
from .config import get_settings
from .db import get_signals, subscribe, unsubscribe

app = FastAPI(title="Signal Consumer Dashboard API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
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

    if s.trading_mode == "live":
        try:
            b = get_balances()
            bankroll = b.polymarket_usdc
        except Exception:
            bankroll = 0.0
    else:
        bankroll = s.bankroll_usdc

    return {
        "trading_mode": s.trading_mode,
        "bankroll_usdc": bankroll,
        "max_position_usd": s.max_position_usd,
        "kelly_fraction": s.kelly_fraction,
        "edge_threshold_pct": s.edge_threshold_pct,
        "wallet_address": os.environ.get("POLYMARKET_WALLET_ADDRESS", ""),
    }
