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

import httpx
import structlog

from .balances import get_balances
from .config import get_settings, get_trading_mode, set_trading_mode
from .db import get_auction_events, log_auction_event, get_paper_positions, get_signals, log_signal, subscribe, unsubscribe
from .signal_generator import generate_signal

logger = structlog.get_logger()

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


@app.get("/api/auctions")
def auctions(limit: int = 100):
    events = get_auction_events(limit=limit)
    if get_trading_mode() != "paper":
        events = [e for e in events if not (e.get("raw_message") or {}).get("smoke")]
    return events


@app.post("/api/auctions/smoke")
def auctions_smoke():
    """Seed sample auction lifecycle events for UI testing (paper mode only)."""
    if get_trading_mode() != "paper":
        return {"ok": False, "error": "Smoke test only available in paper mode"}

    import uuid
    import time

    auction_id = f"auction-smoke-{uuid.uuid4().hex[:8]}"
    consumer = "did:kite:paper/consumer-a"
    producer = "did:kite:paper/producer-1"
    event_id = f"event-smoke-{uuid.uuid4().hex[:6]}"
    now = time.time()

    # Simulate a full auction lifecycle
    events = [
        {"outcome": "bid_submitted", "bid_amount": 8.50},
        {"outcome": "won_offer", "winner_did": consumer, "winning_paid_amount": 8.50},
        {"outcome": "payment_succeeds", "winner_did": consumer, "winning_paid_amount": 8.50,
         "payment_url": "https://example.com/pay/mock"},
    ]
    for i, ev in enumerate(events):
        log_auction_event(
            auction_id=auction_id,
            consumer_did=consumer,
            producer_did=producer,
            event_id=event_id,
            bid_amount=ev.get("bid_amount"),
            outcome=ev["outcome"],
            winner_did=ev.get("winner_did"),
            winning_paid_amount=ev.get("winning_paid_amount"),
            payment_url=ev.get("payment_url"),
            raw_message={"smoke": True, "step": i},
        )

    # Also add a second auction that was lost
    auction_id_2 = f"auction-smoke-{uuid.uuid4().hex[:8]}"
    event_id_2 = f"event-smoke-{uuid.uuid4().hex[:6]}"
    for i, ev in enumerate([
        {"outcome": "bid_submitted", "bid_amount": 5.00},
        {"outcome": "auction_loss", "winner_did": "did:kite:paper/consumer-b"},
    ]):
        log_auction_event(
            auction_id=auction_id_2,
            consumer_did=consumer,
            producer_did=producer,
            event_id=event_id_2,
            bid_amount=ev.get("bid_amount"),
            outcome=ev["outcome"],
            winner_did=ev.get("winner_did"),
            raw_message={"smoke": True, "step": i},
        )

    return {"ok": True, "auctions_created": 2, "events_created": 5}


@app.get("/api/paper-positions")
def paper_positions():
    return get_paper_positions()


class GenerateSignalRequest(BaseModel):
    cities: list[str] | None = None


@app.post("/api/generate-signal")
async def generate_signal_endpoint(body: GenerateSignalRequest | None = None):
    """Generate signals — tries producer first, falls back to local generator."""
    cities = body.cities if body and body.cities else ["nyc", "chicago"]

    # --- Try producer first ---
    s = get_settings()
    producer_http = s.producer_ws_url.replace("ws://", "http://").replace("wss://", "https://")
    producer_http = producer_http.split("/ws/")[0]

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{producer_http}/run-once",
                params={"cities": ",".join(cities)},
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "ok": True,
            "signals_found": data.get("signals_found", 0),
            "source": "producer",
            "errors": [],
        }
    except (httpx.ConnectError, httpx.HTTPStatusError):
        logger.info("Producer unreachable, falling back to local generator", cities=cities)

    # --- Fallback: local signal generator per city ---
    total_logged = 0
    all_errors: list[str] = []

    for city in cities:
        try:
            result = await generate_signal(city_slug=city)
        except Exception as exc:
            all_errors.append(f"{city}:{exc}")
            continue

        signal_data = result["signal_data"]
        response = result["response"]

        # Always log so every attempt shows in the signal feed
        log_signal(signal_data, response)
        total_logged += 1

        if response.get("errors"):
            all_errors.extend(f"{city}:{e}" for e in response["errors"])

    return {
        "ok": total_logged > 0,
        "signals_found": total_logged,
        "source": "local",
        "errors": all_errors,
    }
