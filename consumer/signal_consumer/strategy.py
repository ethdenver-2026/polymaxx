"""
Strategy layer: abstract pipeline between signal receipt and order execution.

Three-stage pipeline:
  1. can_process    — Do we have enough balance?
  2. should_process — Is the live edge above our threshold?
  3. size_position  — How much to bet? (Kelly criterion)

The base `Strategy.process()` orchestrates: can -> should -> size -> execute -> record.
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

from py_clob_client.client import ClobClient

from .db import log_signal
from .execute_order import execute_order, MIN_ORDER_USD
from .polymarket import init_client, get_live_price, get_clob_balance

logger = logging.getLogger("signal_consumer.strategy")

# Polymarket minimum order value in USD
MIN_ORDER_SIZE_USD = MIN_ORDER_USD


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
    def can_process(self, signal: dict, client: ClobClient) -> StrategyCheck:
        """Stage 1: Can I trade? (e.g. balance check)"""

    @abstractmethod
    def should_process(self, signal: dict, client: ClobClient) -> StrategyCheck:
        """Stage 2: Should I trade? (live edge vs threshold)"""

    @abstractmethod
    def size_position(self, signal: dict, balance: float, live_price: float) -> tuple[StrategyCheck, float]:
        """Stage 3: How much to trade? (Kelly criterion / position sizing)

        Returns (check, position_size_usd). position_size_usd is 0 if check fails.
        """

    def process(self, signal: dict) -> StrategyResult:
        """Orchestrate: can -> should -> size -> execute -> record.

        Always records the decision (trade or skip with reason).
        If an unexpected error occurs, records an error result before re-raising.
        """
        signal_price = signal.get("market_price", 0)
        model_prob = signal.get("model_probability", 0)
        signal_edge = signal.get("edge", model_prob - signal_price)

        try:
            return self._run_pipeline(signal, signal_price, model_prob, signal_edge)
        except Exception:
            logger.exception("Unexpected error in strategy pipeline")
            result = StrategyResult(
                should_trade=False,
                adjusted_position_usd=0.0,
                adjusted_price=signal_price,
                skip_reason="Internal strategy error",
                checks=[],
                live_edge=None,
                signal_edge=signal_edge,
                order_errors=["Unexpected error in strategy pipeline"],
            )
            self._record(signal, result)
            return result

    def _run_pipeline(
        self, signal: dict, signal_price: float, model_prob: float, signal_edge: float,
    ) -> StrategyResult:
        """Inner pipeline: can -> should -> size -> execute -> record."""
        checks: list[StrategyCheck] = []

        # --- Step 0: Init client once for the whole pipeline ---
        try:
            client = self._get_client()
        except Exception as e:
            logger.error("Failed to init CLOB client: %s", e)
            result = StrategyResult(
                should_trade=False,
                adjusted_position_usd=0.0,
                adjusted_price=signal_price,
                skip_reason=f"CLOB client init failed: {e}",
                checks=[StrategyCheck(
                    name="init_client", passed=False,
                    detail=f"CLOB client init failed: {e}", data={},
                )],
                live_edge=None,
                signal_edge=signal_edge,
            )
            self._record(signal, result)
            return result

        # --- Step 1: Can I? (balance check) ---
        can_check = self.can_process(signal, client)
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

        # --- Step 2: Should I? (edge check) ---
        should_check = self.should_process(signal, client)
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

        # --- Step 3: How much? (position sizing) ---
        size_check, position_usd = self.size_position(signal, balance, live_price)
        checks.append(size_check)

        if not size_check.passed:
            result = StrategyResult(
                should_trade=False,
                adjusted_position_usd=0.0,
                adjusted_price=live_price,
                skip_reason=size_check.detail,
                checks=checks,
                live_edge=live_edge,
                signal_edge=signal_edge,
            )
            self._record(signal, result)
            return result

        # --- Step 4: Execute ---
        side = signal.get("side", "buy")
        size = position_usd / live_price if live_price > 0 else 0
        min_size = MIN_ORDER_USD / live_price if live_price > 0 else 0
        if size < min_size:
            size = min_size

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

    def _get_client(self) -> ClobClient:
        """Get or create the CLOB client. Subclasses may override for caching."""
        return init_client()

    def _record(self, signal: dict, result: StrategyResult) -> None:
        """Record decision to DB (trade or skip with reason)."""
        if result.should_trade:
            action = "executed" if result.order_id else "error"
        else:
            action = "skipped"

        response = {
            "action": action,
            "signal_price": signal.get("market_price"),
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
    """Concrete strategy for weather prediction markets.

    Caches the CLOB client across signals to avoid redundant credential
    derivation (one network round-trip per init_client call).
    """

    def __init__(self) -> None:
        self._client: ClobClient | None = None

    def _get_client(self) -> ClobClient:
        """Return cached client, creating on first call."""
        if self._client is None:
            self._client = init_client()
        return self._client

    def can_process(self, signal: dict, client: ClobClient) -> StrategyCheck:
        """Check CLOB balance >= minimum order value."""
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

    def should_process(self, signal: dict, client: ClobClient) -> StrategyCheck:
        """Check live edge is above the configured threshold."""
        token_id = signal["token_id"]
        side = signal.get("side", "buy")
        signal_price = signal["market_price"]
        model_prob = signal["model_probability"]
        edge_threshold = float(os.environ.get("EDGE_THRESHOLD_PCT", "8")) / 100

        # Fetch live price
        try:
            live_price = get_live_price(client, token_id, side)
        except Exception:
            logger.warning("Failed to fetch live price for %s, falling back to signal price", token_id, exc_info=True)
            live_price = None

        if live_price is None:
            logger.info("No live price available for %s, using signal price %.4f", token_id, signal_price)
            live_price = signal_price

        live_edge = model_prob - live_price

        if live_edge < edge_threshold:
            return StrategyCheck(
                name="should_process",
                passed=False,
                detail=f"Edge {live_edge*100:.1f}% < threshold {edge_threshold*100:.1f}%",
                data={
                    "live_price": live_price,
                    "live_edge": live_edge,
                    "model_prob": model_prob,
                    "edge_threshold": edge_threshold,
                },
            )

        return StrategyCheck(
            name="should_process",
            passed=True,
            detail=f"Edge {live_edge*100:.1f}% >= {edge_threshold*100:.1f}%",
            data={
                "live_price": live_price,
                "live_edge": live_edge,
                "model_prob": model_prob,
                "edge_threshold": edge_threshold,
            },
        )

    def size_position(self, signal: dict, balance: float, live_price: float) -> tuple[StrategyCheck, float]:
        """Use Kelly criterion to determine position size."""
        model_prob = signal["model_probability"]
        kelly_frac = float(os.environ.get("KELLY_FRACTION", "0.25"))

        position_usd = kelly_position(model_prob, live_price, balance, kelly_frac)

        if position_usd <= 0:
            return (
                StrategyCheck(
                    name="size_position",
                    passed=False,
                    detail=f"Kelly position $0 (prob={model_prob:.3f}, price={live_price:.3f})",
                    data={
                        "model_prob": model_prob,
                        "live_price": live_price,
                        "kelly_fraction": kelly_frac,
                        "balance": balance,
                        "position_usd": 0.0,
                    },
                ),
                0.0,
            )

        # Floor at minimum order size
        if position_usd < MIN_ORDER_SIZE_USD:
            position_usd = MIN_ORDER_SIZE_USD

        return (
            StrategyCheck(
                name="size_position",
                passed=True,
                detail=f"Kelly ${position_usd:.2f} (frac={kelly_frac}, bal=${balance:.2f})",
                data={
                    "model_prob": model_prob,
                    "live_price": live_price,
                    "kelly_fraction": kelly_frac,
                    "balance": balance,
                    "position_usd": position_usd,
                },
            ),
            position_usd,
        )
