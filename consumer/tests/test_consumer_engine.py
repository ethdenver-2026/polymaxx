from __future__ import annotations

from dataclasses import dataclass

from signal_consumer.config import Settings
from signal_consumer.consumer_engine import get_available_balance_usdc, process_signal_payload


def _canonical_payload() -> dict:
    return {
        "signal_type": "weather",
        "model_probability": 0.61,
        "confidence": 0.88,
        "forecast_source": "open_meteo",
        "forecast_time": "2026-02-19T00:00:00+00:00",
        "metadata": {
            "city": "nyc",
            "target_date": "2026-02-20",
            "ensemble_mean": 44.2,
            "ensemble_std": 2.1,
            "members_in_range": 13,
        },
        "exchanges": [
            {
                "exchange": "polymarket",
                "event_id": "evt-3",
                "event_title": "Highest temperature in NYC on February 20?",
                "resolution_source": "https://example.com",
                "market_question": "Will NYC be 44-45F?",
                "market_group_item_title": "44-45°F",
                "token_id": "tok-3",
                "side": "yes",
                "market_price": 0.50,
                "edge": 0.11,
                "price_timestamp": "2026-02-19T00:01:00+00:00",
            }
        ],
        "published_at": "2026-02-19T00:02:00+00:00",
    }


@dataclass
class _FakeResult:
    success: bool
    signal_price: float | None
    live_price: float | None
    signal_edge: float | None
    live_edge: float | None
    order_id: str | None
    status: str | None
    errors: list[str]


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "trading_mode": "paper",
        "edge_threshold_pct": 8.0,
        "bankroll_usdc": 50.0,
        "max_position_usd": 5.0,
        "min_position_usd": 1.0,
        "x402_v2_chain_id": 8453,
        "trading_wallet_address": "0x0000000000000000000000000000000000000001",
        "trading_wallet_private_key": "0x" + "1" * 64,
        "payment_wallet_address": "0x0000000000000000000000000000000000000001",
        "payment_wallet_private_key": "0x" + "1" * 64,
    }
    base.update(overrides)
    return Settings(**base)


def test_process_signal_payload_skips_when_edge_evaporates(monkeypatch):
    monkeypatch.setattr("signal_consumer.consumer_engine.get_available_balance_usdc", lambda settings: 50.0)
    monkeypatch.setattr("signal_consumer.consumer_engine.get_live_price", lambda token_id, side: 0.60)

    response = process_signal_payload(_canonical_payload(), _settings())
    assert response["action"] == "skipped"
    assert "edge_below_threshold" in response["strategy_reasons"]


def test_process_signal_payload_simulates_in_paper_mode(monkeypatch):
    monkeypatch.setattr("signal_consumer.consumer_engine.get_available_balance_usdc", lambda settings: 50.0)
    monkeypatch.setattr("signal_consumer.consumer_engine.get_live_price", lambda token_id, side: 0.51)

    called = {"count": 0}

    def _fake_execute(payload: dict):
        called["count"] += 1
        return _FakeResult(
            success=True,
            signal_price=payload["market_price"],
            live_price=0.51,
            signal_edge=payload["model_probability"] - payload["market_price"],
            live_edge=payload["model_probability"] - 0.51,
            order_id="ord-1",
            status="live",
            errors=[],
        )

    monkeypatch.setattr("signal_consumer.consumer_engine.execute_trade", _fake_execute)

    response = process_signal_payload(_canonical_payload(), _settings(trading_mode="paper"))
    assert response["action"] == "simulated"
    assert called["count"] == 0


def test_process_signal_payload_executes_in_live_mode(monkeypatch):
    monkeypatch.setattr("signal_consumer.consumer_engine.get_available_balance_usdc", lambda settings: 50.0)
    monkeypatch.setattr("signal_consumer.consumer_engine.get_live_price", lambda token_id, side: 0.51)

    called = {"count": 0}

    def _fake_execute(payload: dict):
        called["count"] += 1
        return _FakeResult(
            success=True,
            signal_price=payload["market_price"],
            live_price=0.51,
            signal_edge=payload["model_probability"] - payload["market_price"],
            live_edge=payload["model_probability"] - 0.51,
            order_id="ord-2",
            status="live",
            errors=[],
        )

    monkeypatch.setattr("signal_consumer.consumer_engine.execute_trade", _fake_execute)

    response = process_signal_payload(_canonical_payload(), _settings(trading_mode="live"))
    assert response["action"] == "executed"
    assert response["order_id"] == "ord-2"
    assert called["count"] == 1


def test_process_signal_payload_accepts_canonical_producer_signal(monkeypatch):
    monkeypatch.setattr("signal_consumer.consumer_engine.get_available_balance_usdc", lambda settings: 50.0)
    monkeypatch.setattr("signal_consumer.consumer_engine.get_live_price", lambda token_id, side: 0.51)
    response = process_signal_payload(_canonical_payload(), _settings(trading_mode="paper"))
    assert response["action"] == "simulated"


def test_get_available_balance_live_mode_uses_consumer_polygon_balance(monkeypatch):
    class _FakeBalances:
        onchain_usdc = 3.5
        polymarket_usdc = 1.25

    captured: dict[str, str] = {}

    def _fake_get_balances(*, private_key: str | None = None, wallet_address: str | None = None):
        captured["private_key"] = private_key or ""
        captured["wallet_address"] = wallet_address or ""
        return _FakeBalances()

    monkeypatch.setattr("signal_consumer.consumer_engine.get_balances", _fake_get_balances)
    settings = _settings(
        trading_mode="live",
        trading_wallet_private_key="pk-test",
        trading_wallet_address="0xc11102FEeC9C44f8f5B74751427867dAC53d00d5",
    )

    available = get_available_balance_usdc(settings)
    assert available == 4.75
    assert captured["private_key"] == "pk-test"
    assert captured["wallet_address"] == "0xc11102FEeC9C44f8f5B74751427867dAC53d00d5"
