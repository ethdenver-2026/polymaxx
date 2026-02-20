"""Signal processing engine for producer websocket payloads."""

from __future__ import annotations

import structlog

from .balances import get_balances
from .config import Settings
from .db import get_executed_notional_usd
from .execute_order import ExecutionResult, execute_signal_data
from .signal_pipeline import evaluate_strategy, parse_producer_signal_record

logger = structlog.get_logger()


def get_available_balance_usdc(settings: Settings) -> float:
    """Return currently available USDC for new trades."""
    if settings.trading_mode == "live":
        balances = get_balances()
        return float(balances.polymarket_usdc)
    executed_notional = get_executed_notional_usd()
    available = settings.bankroll_usdc - executed_notional
    return max(0.0, float(available))


def get_live_price(token_id: str, side: str = "buy") -> float:
    """Fetch live price from CLOB orderbook and fail loudly when missing."""
    from .execute_order import _init_client  # noqa: PLC0415

    client = _init_client()
    book = client.get_order_book(token_id)
    if side.lower() == "buy":
        asks = book.asks if book.asks else []
        if not asks:
            raise RuntimeError(f"No asks available in orderbook for token_id={token_id}")
        return float(asks[0].price)

    bids = book.bids if book.bids else []
    if not bids:
        raise RuntimeError(f"No bids available in orderbook for token_id={token_id}")
    return float(bids[0].price)


def execute_trade(payload: dict) -> ExecutionResult:
    """Execute strategy-approved signal via canonical execution path."""
    return execute_signal_data(
        payload,
        prevalidated_live_price=payload["live_price"],
        prevalidated_position_size_usd=payload["position_size_usd"],
        enforce_edge_check=False,
    )


def process_signal_payload(payload: dict, settings: Settings) -> dict:
    """Parse, evaluate, and optionally execute one producer signal payload."""
    record = parse_producer_signal_record(payload)
    available_balance = get_available_balance_usdc(settings)
    live_price = get_live_price(record.token_id, side="buy")

    decision = evaluate_strategy(
        record=record,
        settings=settings,
        available_balance_usdc=available_balance,
        live_price=live_price,
    )

    response: dict = {
        "action": "skipped",
        "signal_price": record.market_price,
        "live_price": live_price,
        "signal_edge": record.edge,
        "live_edge": decision.live_edge,
        "order_id": None,
        "status": None,
        "errors": [],
        "strategy_reasons": decision.reasons,
        "balance_available_usdc": available_balance,
        "position_size_usd": decision.position_size_usd,
        "horizon_hours": decision.horizon_hours,
    }

    if not decision.should_trade:
        return response

    if settings.trading_mode != "live":
        response["action"] = "simulated"
        response["status"] = "paper"
        return response

    execution_payload = {
        "token_id": record.token_id,
        "side": "buy",
        "market_price": record.market_price,
        "model_probability": record.model_probability,
        "edge": record.edge,
        "position_size_usd": decision.position_size_usd,
        "live_price": live_price,
        "strategy": record.strategy,
        "market_id": record.market_id,
    }
    result = execute_trade(execution_payload)
    response.update(
        {
            "action": "executed" if result.success else "error",
            "order_id": result.order_id,
            "status": result.status,
            "errors": result.errors,
            "signal_price": result.signal_price,
            "live_price": result.live_price,
            "signal_edge": result.signal_edge,
            "live_edge": result.live_edge,
        }
    )
    logger.info(
        "Signal processed",
        action=response["action"],
        token_id=record.token_id,
        market_id=record.market_id,
        balance_available_usdc=available_balance,
        position_size_usd=decision.position_size_usd,
    )
    return response
