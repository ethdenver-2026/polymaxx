"""Parsing and strategy evaluation for producer websocket signals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .config import Settings


class ProducerSignalExchange(BaseModel):
    """Exchange-specific signal section from canonical ProducerSignal."""

    exchange: str
    event_id: str
    event_title: str
    resolution_source: str
    market_question: str
    market_group_item_title: str
    token_id: str
    side: str
    market_price: float = Field(gt=0, lt=1)
    edge: float
    price_timestamp: datetime


class CanonicalProducerSignal(BaseModel):
    """Canonical producer websocket payload."""

    signal_type: str
    model_probability: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    forecast_source: str
    forecast_time: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    exchanges: list[ProducerSignalExchange]
    published_at: datetime | None = None


class ProducerSignalRecord(BaseModel):
    """Wire contract received from producer websocket."""

    id: int | None = None
    strategy: str
    market_id: str
    token_id: str
    model_probability: float = Field(ge=0, le=1)
    market_price: float = Field(gt=0, lt=1)
    edge: float
    confidence: float | None = Field(default=None, ge=0, le=1)
    decision: str
    skip_reason: str | None = None
    trade_id: int | None = None
    created_at: datetime
    published_at: datetime
    metadata_json: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class StrategyDecision:
    """Result of evaluating whether a signal should be traded."""

    should_trade: bool
    reasons: list[str]
    live_price: float
    live_edge: float
    available_balance_usdc: float
    position_size_usd: float | None = None
    horizon_hours: float | None = None


def parse_producer_signal_record(payload: dict[str, Any]) -> ProducerSignalRecord:
    """Parse only canonical ProducerSignal payloads into internal shape."""
    if "signal_type" not in payload:
        raise ValueError("Legacy SignalRecord payloads are not accepted; expected canonical ProducerSignal")

    try:
        canonical = CanonicalProducerSignal.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid canonical producer signal payload: {exc}") from exc
    if not canonical.exchanges:
        raise ValueError("Canonical producer signal must include at least one exchange")
    exchange = canonical.exchanges[0]
    normalized_metadata = dict(canonical.metadata)
    normalized_metadata.update(
        {
            "exchange": exchange.exchange,
            "side": exchange.side,
            "resolution_source": exchange.resolution_source,
            "event_title": exchange.event_title,
            "market_question": exchange.market_question,
            "market_group_item_title": exchange.market_group_item_title,
            "price_timestamp": exchange.price_timestamp.isoformat(),
        }
    )
    normalized_payload: dict[str, Any] = {
        "id": None,
        "strategy": canonical.signal_type,
        "market_id": exchange.event_id,
        "token_id": exchange.token_id,
        "model_probability": canonical.model_probability,
        "market_price": exchange.market_price,
        "edge": exchange.edge,
        "confidence": canonical.confidence,
        "decision": "trade",
        "skip_reason": None,
        "trade_id": None,
        "created_at": canonical.forecast_time,
        "published_at": canonical.published_at or datetime.now(UTC),
        "metadata_json": json.dumps(normalized_metadata),
        "metadata": normalized_metadata,
    }
    try:
        return ProducerSignalRecord.model_validate(normalized_payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid normalized producer signal payload: {exc}") from exc


def _extract_horizon_hours(record: ProducerSignalRecord) -> float | None:
    raw = record.metadata.get("forecast_horizon_hours")
    if raw is None:
        raw_days = record.metadata.get("forecast_horizon_days")
        if raw_days is not None:
            return float(raw_days) * 24.0

        target_date_raw = record.metadata.get("target_date")
        if target_date_raw:
            try:
                target_date_dt = datetime.fromisoformat(f"{target_date_raw}T00:00:00+00:00")
                created_at_utc = (
                    record.created_at
                    if record.created_at.tzinfo is not None
                    else record.created_at.replace(tzinfo=UTC)
                )
                delta_hours = (target_date_dt - created_at_utc.astimezone(UTC)).total_seconds() / 3600.0
                return max(0.0, delta_hours)
            except ValueError:
                return None
        return None
    return float(raw)


def _horizon_multiplier(horizon_hours: float | None) -> tuple[float, str | None]:
    if horizon_hours is None:
        return 0.8, "horizon_missing_using_conservative_sizing"
    if horizon_hours <= 6:
        return 1.0, None
    if horizon_hours <= 12:
        return 0.9, None
    if horizon_hours <= 24:
        return 0.75, None
    if horizon_hours <= 48:
        return 0.6, None
    return 0.0, "horizon_too_far_out"


def evaluate_strategy(
    *,
    record: ProducerSignalRecord,
    settings: Settings,
    available_balance_usdc: float,
    live_price: float,
    now: datetime | None = None,
) -> StrategyDecision:
    """Apply strategy/risk checks and produce a deterministic trade decision."""
    _ = now or datetime.now(UTC)
    reasons: list[str] = []

    if record.strategy != "weather":
        return StrategyDecision(
            should_trade=False,
            reasons=["unsupported_strategy"],
            live_price=live_price,
            live_edge=record.model_probability - live_price,
            available_balance_usdc=available_balance_usdc,
        )

    if record.decision != "trade":
        return StrategyDecision(
            should_trade=False,
            reasons=["producer_decision_not_trade"],
            live_price=live_price,
            live_edge=record.model_probability - live_price,
            available_balance_usdc=available_balance_usdc,
        )

    live_edge = record.model_probability - live_price
    effective_threshold = (
        settings.paper_edge_threshold_pct if settings.trading_mode == "paper"
        else settings.edge_threshold_pct
    )
    if live_edge < effective_threshold / 100:
        return StrategyDecision(
            should_trade=False,
            reasons=["edge_below_threshold"],
            live_price=live_price,
            live_edge=live_edge,
            available_balance_usdc=available_balance_usdc,
        )

    if available_balance_usdc <= 0:
        return StrategyDecision(
            should_trade=False,
            reasons=["insufficient_balance"],
            live_price=live_price,
            live_edge=live_edge,
            available_balance_usdc=available_balance_usdc,
        )

    horizon_hours = _extract_horizon_hours(record)
    horizon_mult, horizon_reason = _horizon_multiplier(horizon_hours)
    if horizon_reason:
        reasons.append(horizon_reason)
    if horizon_mult == 0:
        return StrategyDecision(
            should_trade=False,
            reasons=reasons,
            live_price=live_price,
            live_edge=live_edge,
            available_balance_usdc=available_balance_usdc,
            horizon_hours=horizon_hours,
        )

    edge_scaled_fraction = min(max(live_edge, 0.0), 0.20)
    desired_position = available_balance_usdc * edge_scaled_fraction * horizon_mult
    capped_position = min(desired_position, settings.max_position_usd, available_balance_usdc)
    if capped_position < settings.min_position_usd:
        reasons.append("position_below_minimum")
        return StrategyDecision(
            should_trade=False,
            reasons=reasons,
            live_price=live_price,
            live_edge=live_edge,
            available_balance_usdc=available_balance_usdc,
            position_size_usd=capped_position,
            horizon_hours=horizon_hours,
        )

    return StrategyDecision(
        should_trade=True,
        reasons=reasons,
        live_price=live_price,
        live_edge=live_edge,
        available_balance_usdc=available_balance_usdc,
        position_size_usd=capped_position,
        horizon_hours=horizon_hours,
    )
