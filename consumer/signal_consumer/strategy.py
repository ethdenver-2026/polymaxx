"""
Strategy layer: abstract pipeline between signal receipt and order execution.

Two-question pipeline:
  1. can_process  — Do we have enough balance for the trade to go through?
  2. should_process — Does Kelly criterion say this is profitable?

The base `Strategy.process()` orchestrates: can -> should -> execute -> record.
Every decision (trade or skip) is recorded to the DB with reasoning.

Usage:
    from .strategy import WeatherStrategy
    strategy = WeatherStrategy()
    result = strategy.process(signal_data)
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .db import log_signal
from .execute_order import execute_order, MIN_ORDER_SIZE
from .polymarket import init_client, get_live_price, get_clob_balance

logger = logging.getLogger("signal_consumer.strategy")

# Polymarket minimum order size in USD
MIN_ORDER_SIZE_USD = 5.0


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
    # Execution fields (populated when should_trade=True and order is placed)
    order_id: str | None = None
    order_status: str | None = None
    order_errors: list[str] = field(default_factory=list)

    def checks_as_dicts(self) -> list[dict]:
        return [
            {"name": c.name, "passed": c.passed, "detail": c.detail, "data": c.data}
            for c in self.checks
        ]


def kelly_position(win_prob: float, price: float, bankroll: float, fraction: float = 0.25) -> float:
    """Quarter-Kelly position sizing.

    Returns the optimal position size in USD, capped at $5.
    """
    if win_prob <= price or price <= 0 or price >= 1:
        return 0.0
    b = (1 - price) / price  # Win payout multiplier
    kelly = (win_prob * b - (1 - win_prob)) / b
    return min(bankroll * kelly * fraction, 5.0)


class Strategy(ABC):
    """Abstract base class for trading strategies."""

    @abstractmethod
    def can_process(self, signal: dict) -> StrategyCheck:
        """Can I process? Checks balance is sufficient for tx to go through."""

    @abstractmethod
    def should_process(self, signal: dict, balance: float) -> tuple[StrategyCheck, float]:
        """Should I process? Uses Kelly criterion to determine profitability.

        Returns (check, position_size_usd). position_size_usd is 0 if check fails.
        """

    def process(self, signal: dict) -> StrategyResult:
        """Orchestrate: can -> should -> execute -> record to DB.

        Always records the decision (trade or skip with reason).
        """
        signal_price = signal["market_price"]
        model_prob = signal["model_probability"]
        signal_edge = signal.get("edge", model_prob - signal_price)

        checks: list[StrategyCheck] = []

        # --- Step 1: Can I? ---
        can_check = self.can_process(signal)
        checks.append(can_check)

        if not can_check.passed:
            result = StrategyResult(
                should_trade=False,
                adjusted_position_usd=0.0,
                adjusted_price=signal_price,
                skip_reason=can_check.detail,
                checks=checks,
                live_edge=None,
                signal_edge=signal_edge,
            )
            self._record(signal, result)
            return result

        balance = can_check.data.get("balance", 0.0)

        # --- Step 2: Should I? ---
        should_check, position_usd = self.should_process(signal, balance)
        checks.append(should_check)

        live_price = should_check.data.get("live_price", signal_price)
        live_edge = should_check.data.get("live_edge")

        if not should_check.passed:
            result = StrategyResult(
                should_trade=False,
                adjusted_position_usd=0.0,
                adjusted_price=live_price,
                skip_reason=should_check.detail,
                checks=checks,
                live_edge=live_edge,
                signal_edge=signal_edge,
            )
            self._record(signal, result)
            return result

        # --- Step 3: Execute ---
        side = signal.get("side", "buy")
        size = position_usd / live_price if live_price > 0 else 0
        if size < MIN_ORDER_SIZE:
            size = float(MIN_ORDER_SIZE)

        exec_result = execute_order(
            token_id=signal["token_id"],
            side=side,
            price=live_price,
            size=size,
        )

        result = StrategyResult(
            should_trade=True,
            adjusted_position_usd=position_usd,
            adjusted_price=live_price,
            skip_reason=None,
            checks=checks,
            live_edge=live_edge,
            signal_edge=signal_edge,
            order_id=exec_result.order_id,
            order_status=exec_result.status,
            order_errors=exec_result.errors,
        )
        self._record(signal, result)
        return result

    def _record(self, signal: dict, result: StrategyResult) -> None:
        """Record decision to DB (trade or skip with reason)."""
        if result.should_trade:
            action = "executed" if result.order_id else "error"
        else:
            action = "skipped"

        response = {
            "action": action,
            "signal_price": signal["market_price"],
            "live_price": result.adjusted_price,
            "signal_edge": result.signal_edge,
            "live_edge": result.live_edge,
            "order_id": result.order_id,
            "status": result.order_status,
            "errors": result.order_errors if result.should_trade else (
                [result.skip_reason] if result.skip_reason else []
            ),
            "strategy_checks": result.checks_as_dicts(),
        }

        try:
            log_signal(signal, response)
        except Exception:
            logger.exception("Failed to log signal to database")


class WeatherStrategy(Strategy):
    """Concrete strategy for weather prediction markets."""

    def can_process(self, signal: dict) -> StrategyCheck:
        """Check CLOB balance >= $5 minimum."""
        try:
            client = init_client()
        except Exception as e:
            logger.error("Failed to init CLOB client: %s", e)
            return StrategyCheck(
                name="can_process",
                passed=False,
                detail=f"CLOB client init failed: {e}",
                data={},
            )

        try:
            balance = get_clob_balance(client)
        except Exception as e:
            logger.error("Failed to fetch balance: %s", e)
            return StrategyCheck(
                name="can_process",
                passed=False,
                detail=f"Balance fetch failed: {e}",
                data={},
            )

        if balance < MIN_ORDER_SIZE_USD:
            return StrategyCheck(
                name="can_process",
                passed=False,
                detail=f"Insufficient balance: ${balance:.2f} < ${MIN_ORDER_SIZE_USD:.0f} minimum",
                data={"balance": balance, "minimum": MIN_ORDER_SIZE_USD},
            )

        return StrategyCheck(
            name="can_process",
            passed=True,
            detail=f"Balance ${balance:.2f} sufficient",
            data={"balance": balance},
        )

    def should_process(self, signal: dict, balance: float) -> tuple[StrategyCheck, float]:
        """Use live price + Kelly criterion to decide profitability."""
        token_id = signal["token_id"]
        side = signal.get("side", "buy")
        signal_price = signal["market_price"]
        model_prob = signal["model_probability"]
        edge_threshold = float(os.environ.get("EDGE_THRESHOLD_PCT", "8")) / 100
        kelly_frac = float(os.environ.get("KELLY_FRACTION", "0.25"))

        # Fetch live price
        try:
            client = init_client()
            live_price = get_live_price(client, token_id, side)
        except Exception:
            live_price = None

        if live_price is None:
            live_price = signal_price  # fallback

        live_edge = model_prob - live_price

        # Kelly position sizing
        position_usd = kelly_position(model_prob, live_price, balance, kelly_frac)

        # Check: Kelly says position > 0 AND edge > threshold
        if position_usd <= 0 or live_edge < edge_threshold:
            reason_parts = []
            if position_usd <= 0:
                reason_parts.append(f"Kelly position $0 (prob={model_prob:.3f}, price={live_price:.3f})")
            if live_edge < edge_threshold:
                reason_parts.append(
                    f"Edge {live_edge*100:.1f}% < threshold {edge_threshold*100:.1f}%"
                )
            detail = "; ".join(reason_parts)

            return (
                StrategyCheck(
                    name="should_process",
                    passed=False,
                    detail=detail,
                    data={
                        "live_price": live_price,
                        "live_edge": live_edge,
                        "model_prob": model_prob,
                        "kelly_position": position_usd,
                        "edge_threshold": edge_threshold,
                    },
                ),
                0.0,
            )

        # Cap at minimum order size
        if position_usd < MIN_ORDER_SIZE_USD:
            position_usd = MIN_ORDER_SIZE_USD

        return (
            StrategyCheck(
                name="should_process",
                passed=True,
                detail=(
                    f"Edge {live_edge*100:.1f}% >= {edge_threshold*100:.1f}%, "
                    f"Kelly ${position_usd:.2f}"
                ),
                data={
                    "live_price": live_price,
                    "live_edge": live_edge,
                    "model_prob": model_prob,
                    "kelly_position": position_usd,
                    "edge_threshold": edge_threshold,
                    "kelly_fraction": kelly_frac,
                    "balance": balance,
                },
            ),
            position_usd,
        )
