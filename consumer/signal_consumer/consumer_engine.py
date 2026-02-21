"""Signal processing engine for producer websocket payloads."""

from __future__ import annotations

import structlog

from .balances import get_balances
from .config import Settings
from .db import get_executed_notional_usd
from .execute_order import ExecutionResult, execute_order
from .polymarket import init_client, get_live_price as _get_live_price
from .signal_pipeline import evaluate_strategy, parse_producer_signal_record

logger = structlog.get_logger()


def get_available_balance_usdc(settings: Settings) -> float:
    """Return currently available USDC for new trades."""
    if settings.trading_mode == "live":
        balances = get_balances(
            private_key=settings.trading_wallet_private_key,
            wallet_address=settings.trading_wallet_address,
        )
        # Trading capacity is wallet USDC on Polygon plus any USDC already deposited in Polymarket.
        return float(balances.onchain_usdc + balances.polymarket_usdc)
    executed_notional = get_executed_notional_usd()
    available = settings.bankroll_usdc - executed_notional
    return max(0.0, float(available))


def get_live_price(token_id: str, side: str = "buy") -> float:
    """Fetch live price from CLOB orderbook and fail loudly when missing."""
    client = init_client()
    price = _get_live_price(client, token_id, side)
    if price is None:
        raise RuntimeError(f"No {'asks' if side.lower() == 'buy' else 'bids'} available in orderbook for token_id={token_id}")
    return price


def execute_trade(payload: dict) -> ExecutionResult:
    """Execute strategy-approved signal via canonical execution path."""
    live_price = payload["live_price"]
    position_usd = payload["position_size_usd"]
    size = position_usd / live_price if live_price > 0 else 0
    return execute_order(
        token_id=payload["token_id"],
        side=payload.get("side", "buy"),
        price=live_price,
        size=size,
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
