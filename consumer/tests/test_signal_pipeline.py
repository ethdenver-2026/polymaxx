from __future__ import annotations

from datetime import UTC, datetime

import pytest

from signal_consumer.config import Settings
from signal_consumer.signal_pipeline import (
    ProducerSignalRecord,
    StrategyDecision,
    evaluate_strategy,
    parse_producer_signal_record,
)


def _legacy_payload() -> dict:
    return {
        "id": 11,
        "strategy": "weather",
        "market_id": "mkt-1",
        "token_id": "tok-1",
        "model_probability": 0.62,
        "market_price": 0.50,
        "edge": 0.12,
        "confidence": 0.9,
        "decision": "trade",
        "skip_reason": None,
        "trade_id": None,
        "created_at": "2026-02-19T12:00:00+00:00",
        "published_at": "2026-02-19T12:00:05+00:00",
        "metadata_json": '{"city":"nyc","forecast_horizon_hours":12}',
    }


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "trading_mode": "paper",
        "weather_edge_threshold": 0.08,
        "max_position_usd": 5.0,
        "bankroll_usdc": 50.0,
        "min_position_usd": 1.0,
    }
    base.update(overrides)
    return Settings(**base)


def _canonical_payload() -> dict:
    return {
        "signal_type": "weather",
        "model_probability": 0.62,
        "confidence": 0.9,
        "forecast_source": "open_meteo",
        "forecast_time": "2026-02-19T00:00:00+00:00",
        "metadata": {
            "city": "nyc",
            "target_date": "2026-02-20",
            "ensemble_mean": 44.1,
            "ensemble_std": 2.0,
            "members_in_range": 14,
        },
        "exchanges": [
            {
                "exchange": "polymarket",
                "event_id": "evt-1",
                "token_id": "tok-yes-1",
                "side": "yes",
                "market_description": "Will NYC be 44-45F?",
                "resolution_source": "https://example.com",
                "market_price": 0.50,
                "edge": 0.12,
                "price_timestamp": "2026-02-19T00:01:00+00:00",
            }
        ],
        "published_at": "2026-02-19T00:01:30+00:00",
    }


def test_parse_producer_signal_record_accepts_canonical_schema():
    record = parse_producer_signal_record(_canonical_payload())
    assert isinstance(record, ProducerSignalRecord)
    assert record.strategy == "weather"
    assert record.market_id == "evt-1"
    assert record.token_id == "tok-yes-1"
    assert record.metadata["target_date"] == "2026-02-20"


def test_parse_producer_signal_record_rejects_legacy_schema():
    with pytest.raises(ValueError, match="Legacy SignalRecord payloads are not accepted"):
        parse_producer_signal_record(_legacy_payload())


def test_parse_producer_signal_record_rejects_invalid_canonical_schema():
    payload = _canonical_payload()
    payload["exchanges"] = []
    with pytest.raises(ValueError, match="at least one exchange"):
        parse_producer_signal_record(payload)

def test_strategy_skips_when_live_edge_too_small():
    record = parse_producer_signal_record(_canonical_payload())
    decision = evaluate_strategy(
        record=record,
        settings=_settings(),
        available_balance_usdc=40.0,
        live_price=0.60,
        now=datetime(2026, 2, 19, tzinfo=UTC),
    )
    assert isinstance(decision, StrategyDecision)
    assert decision.should_trade is False
    assert "edge_below_threshold" in decision.reasons


def test_strategy_sizes_trade_with_balance_and_horizon():
    record = parse_producer_signal_record(_canonical_payload())
    decision = evaluate_strategy(
        record=record,
        settings=_settings(max_position_usd=10.0, bankroll_usdc=200.0),
        available_balance_usdc=80.0,
        live_price=0.45,
        now=datetime(2026, 2, 19, tzinfo=UTC),
    )
    assert decision.should_trade is True
    assert decision.position_size_usd is not None
    assert decision.position_size_usd > 0
    assert decision.position_size_usd <= 10.0


def test_strategy_derives_horizon_from_canonical_metadata_target_date():
    record = parse_producer_signal_record(_canonical_payload())
    decision = evaluate_strategy(
        record=record,
        settings=_settings(max_position_usd=10.0, bankroll_usdc=200.0),
        available_balance_usdc=80.0,
        live_price=0.45,
        now=datetime(2026, 2, 19, tzinfo=UTC),
    )
    assert decision.should_trade is True
    assert decision.horizon_hours is not None
    assert 20 <= decision.horizon_hours <= 30
