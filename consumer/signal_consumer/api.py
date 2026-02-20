"""
FastAPI REST endpoints for the consumer dashboard.

Exposes balances, signal log, config, and health check.
Runs alongside the WebSocket server on port 8766.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .balances import get_balances
from .db import get_signals

app = FastAPI(title="Signal Consumer API", version="0.1.0")

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


@app.get("/api/config")
def config():
    return {
        "trading_mode": os.environ.get("TRADING_MODE", "paper"),
        "bankroll_usdc": float(os.environ.get("BANKROLL_USDC", "50")),
        "max_position_usd": float(os.environ.get("MAX_POSITION_USD", "5")),
        "kelly_fraction": float(os.environ.get("KELLY_FRACTION", "0.25")),
        "edge_threshold_pct": float(os.environ.get("EDGE_THRESHOLD_PCT", "8")),
        "daily_loss_limit_pct": float(os.environ.get("DAILY_LOSS_LIMIT_PCT", "5")),
        "wallet_address": os.environ.get("POLYMARKET_WALLET_ADDRESS", ""),
    }
