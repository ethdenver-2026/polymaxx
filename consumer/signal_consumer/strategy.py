"""
Strategy layer that sits between signal receipt and order execution.

Runs a pipeline of checks to determine whether and how much to trade:
  1. Balance check — can we afford a trade?
  2. Live edge check — is the market still mispriced?
  3. Forecast horizon risk — adjust threshold for distant forecasts
  4. Position sizing — balance-aware capping

Usage:
    from .strategy import run_strategy
    result = run_strategy(signal_data)
    if result.should_trade:
        execute_order(...)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

logger = logging.getLogger("signal_consumer.strategy")

# Polymarket minimum order size in USD
MIN_ORDER_SIZE_USD = 5.0

# Reserve buffer to keep in account for gas/fees
BALANCE_RESERVE_USD = 2.0

# USDC.e decimals on Polygon
USDC_E_DECIMALS = 6


@dataclass
class StrategyCheck:
    """Result of a single strategy check."""

    name: str
    passed: bool
    detail: str
    data: dict = field(default_factory=dict)


@dataclass
class StrategyResult:
    """Aggregated result of the strategy pipeline."""

    should_trade: bool
    adjusted_position_usd: float
    adjusted_price: float
    skip_reason: str | None
    checks: list[StrategyCheck]
    live_edge: float | None
    signal_edge: float | None

    def checks_as_dicts(self) -> list[dict]:
        return [
            {"name": c.name, "passed": c.passed, "detail": c.detail, "data": c.data}
            for c in self.checks
        ]


def _init_client() -> ClobClient:
    """Initialize a ClobClient from environment variables."""
    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("POLYMARKET_PRIVATE_KEY not set")

    wallet_address = os.environ.get("POLYMARKET_WALLET_ADDRESS", "")
    host = os.environ.get("CLOB_API_URL", "https://clob.polymarket.com")
    chain_id = int(os.environ.get("CHAIN_ID", "137"))
    sig_type = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "2"))

    temp_client = ClobClient(host, key=private_key, chain_id=chain_id)
    creds = temp_client.create_or_derive_api_creds()

    return ClobClient(
        host,
        key=private_key,
        chain_id=chain_id,
        creds=creds,
        signature_type=sig_type,
        funder=wallet_address or None,
    )


def _get_clob_balance(client: ClobClient) -> float:
    """Fetch USDC.e balance from the Polymarket CLOB."""
    sig_type = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "2"))
    result = client.get_balance_allowance(
        BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=sig_type)
    )
    return int(result.get("balance", "0")) / 10**USDC_E_DECIMALS


def _get_live_price(client: ClobClient, token_id: str, side: str) -> float | None:
    """Fetch the current best price from the orderbook."""
    try:
        book = client.get_order_book(token_id)
        if side.lower() == "buy":
            asks = book.asks if book.asks else []
            return float(asks[0].price) if asks else None
        else:
            bids = book.bids if book.bids else []
            return float(bids[0].price) if bids else None
    except Exception:
        return None


def _get_horizon_multiplier(days_out: float) -> float:
    """
    Return an edge threshold multiplier based on forecast horizon.

    Longer horizons require higher edge because ensemble spread grows with lead time.
    """
    if days_out <= 0.5:
        return 1.0
    elif days_out <= 1.0:
        return 1.5
    elif days_out <= 2.0:
        return 2.0
    else:
        return 2.5


def _check_balance(balance: float, requested_size: float) -> StrategyCheck:
    """Check if we have enough CLOB balance to trade."""
    if balance < MIN_ORDER_SIZE_USD:
        return StrategyCheck(
            name="balance",
            passed=False,
            detail=f"Insufficient balance: ${balance:.2f} < ${MIN_ORDER_SIZE_USD:.0f} minimum",
            data={"balance": balance, "minimum": MIN_ORDER_SIZE_USD},
        )

    if balance < requested_size:
        return StrategyCheck(
            name="balance",
            passed=True,
            detail=f"Balance ${balance:.2f} < requested ${requested_size:.2f}, will reduce position",
            data={"balance": balance, "requested": requested_size, "reduced": True},
        )

    return StrategyCheck(
        name="balance",
        passed=True,
        detail=f"Balance ${balance:.2f} sufficient",
        data={"balance": balance},
    )


def _check_live_edge(
    model_prob: float,
    live_price: float,
    signal_price: float,
    base_threshold: float,
    horizon_multiplier: float,
) -> StrategyCheck:
    """Check if live edge still exceeds the horizon-adjusted threshold."""
    live_edge = model_prob - live_price
    adjusted_threshold = base_threshold * horizon_multiplier

    if live_edge < adjusted_threshold:
        return StrategyCheck(
            name="live_edge",
            passed=False,
            detail=(
                f"Edge {live_edge*100:.1f}% below threshold "
                f"{adjusted_threshold*100:.1f}% "
                f"(base {base_threshold*100:.0f}% x {horizon_multiplier:.1f}x horizon)"
            ),
            data={
                "live_edge": live_edge,
                "adjusted_threshold": adjusted_threshold,
                "base_threshold": base_threshold,
                "horizon_multiplier": horizon_multiplier,
                "model_prob": model_prob,
                "live_price": live_price,
            },
        )

    return StrategyCheck(
        name="live_edge",
        passed=True,
        detail=f"Edge {live_edge*100:.1f}% >= threshold {adjusted_threshold*100:.1f}%",
        data={
            "live_edge": live_edge,
            "adjusted_threshold": adjusted_threshold,
            "base_threshold": base_threshold,
            "horizon_multiplier": horizon_multiplier,
        },
    )


def _check_forecast_horizon(days_out: float) -> StrategyCheck:
    """Report the forecast horizon and its risk multiplier."""
    multiplier = _get_horizon_multiplier(days_out)

    if days_out <= 0.5:
        label = "same day"
    elif days_out <= 1.0:
        label = "1 day"
    elif days_out <= 2.0:
        label = "2 days"
    else:
        label = f"{days_out:.0f} days"

    return StrategyCheck(
        name="horizon_risk",
        passed=True,  # informational — the edge check enforces the multiplier
        detail=f"Horizon: {label}, multiplier: {multiplier:.1f}x",
        data={"days_out": days_out, "multiplier": multiplier, "label": label},
    )


def _calculate_position(
    requested_usd: float,
    balance: float,
    max_position_usd: float,
    max_balance_pct: float,
) -> StrategyCheck:
    """Determine final position size with all caps applied."""
    size = requested_usd

    # Cap at max position
    size = min(size, max_position_usd)

    # Cap at percentage of balance
    balance_cap = balance * max_balance_pct
    size = min(size, balance_cap)

    # Cap at balance minus reserve
    available = max(0.0, balance - BALANCE_RESERVE_USD)
    size = min(size, available)

    if size < MIN_ORDER_SIZE_USD:
        return StrategyCheck(
            name="position_size",
            passed=False,
            detail=f"Position ${size:.2f} below ${MIN_ORDER_SIZE_USD:.0f} minimum after caps",
            data={
                "final_size": size,
                "requested": requested_usd,
                "balance_cap": balance_cap,
                "available": available,
                "max_position": max_position_usd,
            },
        )

    return StrategyCheck(
        name="position_size",
        passed=True,
        detail=f"Position: ${size:.2f} (requested ${requested_usd:.2f})",
        data={
            "final_size": size,
            "requested": requested_usd,
            "balance_cap": balance_cap,
            "available": available,
            "max_position": max_position_usd,
        },
    )


def _parse_days_out(signal_data: dict) -> float:
    """Calculate days until the target date from signal data."""
    target_date_str = signal_data.get("target_date")
    if not target_date_str:
        # Check inside metadata
        metadata = signal_data.get("metadata", {})
        target_date_str = metadata.get("target_date")

    if not target_date_str:
        return 0.0  # Unknown horizon → treat as same-day (conservative: no multiplier)

    try:
        target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        days = (target - date.today()).days
        return max(0.0, float(days))
    except (ValueError, TypeError):
        return 0.0


def run_strategy(signal_data: dict) -> StrategyResult:
    """
    Run the full strategy pipeline on a signal.

    Returns a StrategyResult indicating whether to trade and at what size/price.
    """
    token_id = signal_data["token_id"]
    side = signal_data.get("side", "buy")
    signal_price = signal_data["market_price"]
    model_prob = signal_data["model_probability"]
    signal_edge = signal_data.get("edge", model_prob - signal_price)
    requested_size = signal_data["position_size_usd"]

    # Config from env
    base_threshold = float(os.environ.get("EDGE_THRESHOLD_PCT", "8")) / 100
    max_position_usd = float(os.environ.get("MAX_POSITION_USD", "5"))
    max_balance_pct = float(os.environ.get("MAX_BALANCE_PCT", "20")) / 100

    checks: list[StrategyCheck] = []

    # --- Init client ---
    try:
        client = _init_client()
    except Exception as e:
        logger.error("Failed to init CLOB client: %s", e)
        checks.append(StrategyCheck(
            name="client_init", passed=False,
            detail=f"CLOB client init failed: {e}", data={},
        ))
        return StrategyResult(
            should_trade=False,
            adjusted_position_usd=0.0,
            adjusted_price=signal_price,
            skip_reason=f"Client init failed: {e}",
            checks=checks,
            live_edge=None,
            signal_edge=signal_edge,
        )

    # --- 1. Balance check ---
    try:
        balance = _get_clob_balance(client)
    except Exception as e:
        logger.error("Failed to fetch balance: %s", e)
        balance = 0.0
        checks.append(StrategyCheck(
            name="balance", passed=False,
            detail=f"Balance fetch failed: {e}", data={},
        ))
        return StrategyResult(
            should_trade=False,
            adjusted_position_usd=0.0,
            adjusted_price=signal_price,
            skip_reason=f"Balance fetch failed: {e}",
            checks=checks,
            live_edge=None,
            signal_edge=signal_edge,
        )

    balance_check = _check_balance(balance, requested_size)
    checks.append(balance_check)
    if not balance_check.passed:
        return StrategyResult(
            should_trade=False,
            adjusted_position_usd=0.0,
            adjusted_price=signal_price,
            skip_reason=balance_check.detail,
            checks=checks,
            live_edge=None,
            signal_edge=signal_edge,
        )

    # --- 2. Fetch live price ---
    live_price = _get_live_price(client, token_id, side)
    if live_price is None:
        live_price = signal_price  # fallback

    # --- 3. Forecast horizon ---
    days_out = _parse_days_out(signal_data)
    horizon_check = _check_forecast_horizon(days_out)
    checks.append(horizon_check)
    horizon_multiplier = _get_horizon_multiplier(days_out)

    # --- 4. Live edge check (with horizon-adjusted threshold) ---
    edge_check = _check_live_edge(
        model_prob, live_price, signal_price, base_threshold, horizon_multiplier
    )
    checks.append(edge_check)
    live_edge = model_prob - live_price

    if not edge_check.passed:
        return StrategyResult(
            should_trade=False,
            adjusted_position_usd=0.0,
            adjusted_price=live_price,
            skip_reason=edge_check.detail,
            checks=checks,
            live_edge=live_edge,
            signal_edge=signal_edge,
        )

    # --- 5. Position sizing ---
    position_check = _calculate_position(
        requested_size, balance, max_position_usd, max_balance_pct
    )
    checks.append(position_check)

    if not position_check.passed:
        return StrategyResult(
            should_trade=False,
            adjusted_position_usd=0.0,
            adjusted_price=live_price,
            skip_reason=position_check.detail,
            checks=checks,
            live_edge=live_edge,
            signal_edge=signal_edge,
        )

    final_size = position_check.data["final_size"]

    return StrategyResult(
        should_trade=True,
        adjusted_position_usd=final_size,
        adjusted_price=live_price,
        skip_reason=None,
        checks=checks,
        live_edge=live_edge,
        signal_edge=signal_edge,
    )
