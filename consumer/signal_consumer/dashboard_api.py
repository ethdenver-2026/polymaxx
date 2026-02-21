"""
FastAPI REST endpoints for the consumer dashboard.

Exposes balances, signal log, config, and health check.
Runs alongside the WebSocket server on port 8766.
"""

from __future__ import annotations

import json
import os
import queue

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import StreamingResponse

from pydantic import BaseModel

import structlog

from .balances import get_balances
from .config import get_settings, get_trading_mode, set_trading_mode
from .db import get_auction_events, get_trades, log_auction_event, log_trade, get_paper_positions, get_signals, log_signal, subscribe, unsubscribe
from .polymarket import init_client, get_live_price as _get_live_price
try:
    from .signal_generator import generate_signal
except ImportError:
    generate_signal = None

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

    wallet_address = (
        s.trading_wallet_address
        or os.environ.get("TRADING_WALLET_ADDRESS", "")
        or os.environ.get("POLYMARKET_WALLET_ADDRESS", "")
    )

    return {
        "trading_mode": mode,
        "bankroll_usdc": bankroll,
        "max_position_usd": s.max_position_usd,
        "kelly_fraction": s.kelly_fraction,
        "edge_threshold_pct": s.edge_threshold_pct,
        "wallet_address": wallet_address,
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
    return get_auction_events(limit=limit)



@app.get("/api/paper-positions")
def paper_positions():
    return get_paper_positions()


def _enrich_trades_with_prices(trades: list[dict]) -> list[dict]:
    """Attach current_price and unrealized_pnl to open trades using CLOB orderbook."""
    open_trades = [t for t in trades if t.get("status") == "open" and t.get("token_id")]
    if not open_trades:
        for t in trades:
            t["current_price"] = None
            t["unrealized_pnl"] = None
        return trades

    try:
        client = init_client()
    except Exception:
        logger.warning("Failed to init CLOB client for price enrichment")
        for t in trades:
            t["current_price"] = None
            t["unrealized_pnl"] = None
        return trades

    # Dedupe by (token_id, side) since get_live_price needs side
    price_cache: dict[tuple[str, str], float | None] = {}
    for t in open_trades:
        key = (t["token_id"], t.get("side", "buy"))
        if key not in price_cache:
            try:
                price_cache[key] = _get_live_price(client, t["token_id"], t.get("side", "buy"))
            except Exception:
                price_cache[key] = None

    for t in trades:
        if t.get("status") != "open":
            t["current_price"] = None
            t["unrealized_pnl"] = None
            continue
        key = (t.get("token_id", ""), t.get("side", "buy"))
        cur = price_cache.get(key)
        t["current_price"] = cur
        entry = t.get("entry_price")
        size = t.get("size_usd")
        if cur is not None and entry and entry > 0 and size:
            shares = size / entry
            t["unrealized_pnl"] = round(shares * cur - size, 4)
        else:
            t["unrealized_pnl"] = None

    return trades


@app.get("/api/trades")
def trades(limit: int = 100, status: str | None = None, trade_type: str | None = None):
    raw = get_trades(limit=limit, status=status, trade_type=trade_type)
    return _enrich_trades_with_prices(raw)


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

    if generate_signal is None:
        return {
            "ok": False,
            "signals_found": 0,
            "source": "local",
            "errors": ["Local signal generator unavailable: missing signal_consumer.signal_generator"],
        }

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

        # Record trade for simulated signals
        if response.get("action") == "simulated":
            exchange = signal_data.get("exchanges", [{}])[0] if signal_data.get("exchanges") else {}
            metadata = signal_data.get("metadata", {})
            try:
                log_trade(
                    trade_type="paper",
                    token_id=exchange.get("token_id") or signal_data.get("token_id", ""),
                    side=exchange.get("side", "buy"),
                    entry_price=response.get("live_price") or response.get("signal_price"),
                    size_usd=signal_data.get("position_size_usd"),
                    model_probability=signal_data.get("model_probability"),
                    signal_edge=response.get("signal_edge"),
                    live_edge=response.get("live_edge"),
                    event_id=exchange.get("event_id"),
                    event_title=exchange.get("event_title"),
                    market_description=exchange.get("market_question") or exchange.get("market_description"),
                    city=metadata.get("city"),
                    target_date=metadata.get("target_date"),
                )
            except Exception:
                logger.exception("Failed to log paper trade from local generator")

        if response.get("errors"):
            all_errors.extend(f"{city}:{e}" for e in response["errors"])

    return {
        "ok": total_logged > 0,
        "signals_found": total_logged,
        "source": "local",
        "errors": all_errors,
    }
