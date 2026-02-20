"""Unit tests for polymarket execution helpers."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from signal_consumer.config import Settings
from signal_consumer import polymarket as polymarket_module
from signal_schema import MarketType, Signal, SignalMetadata


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "trading_mode": "live",
        "chain_id": 137,
        "clob_api_url": "https://clob.polymarket.com",
        "polymarket_private_key": "pk",
        "polymarket_api_key": "ak",
        "polymarket_api_secret": "as",
        "polymarket_api_passphrase": "ap",
        "max_slippage_abs": 0.05,
    }
    base.update(overrides)
    return Settings(**base)


def _signal(*, position_size_usd: float = 5.0, market_price: float = 0.5) -> Signal:
    return Signal(
        strategy="weather",
        market_type=MarketType.POLYMARKET,
        market_id="market-123",
        token_id="token-abc",
        description="Weather bucket signal",
        target_date=date.today(),
        model_probability=0.55,
        market_price=market_price,
        edge=0.05,
        confidence=0.9,
        position_size_usd=position_size_usd,
        expected_value=0.2,
        metadata=SignalMetadata(city="nyc", bucket_low=40, bucket_high=41),
    )


def test_build_clob_client_rejects_non_polygon_chain():
    with pytest.raises(RuntimeError, match="requires 137"):
        polymarket_module.build_clob_client(_settings(chain_id=80002))


@pytest.mark.parametrize(
    ("field_name", "value", "expected_name"),
    [
        ("polymarket_private_key", "", "POLYMARKET_PRIVATE_KEY"),
        ("polymarket_api_key", "   ", "POLYMARKET_API_KEY"),
        ("polymarket_api_secret", "", "POLYMARKET_API_SECRET"),
        ("polymarket_api_passphrase", "   ", "POLYMARKET_API_PASSPHRASE"),
    ],
)
def test_build_clob_client_requires_nonempty_credentials(
    field_name: str,
    value: str,
    expected_name: str,
):
    with pytest.raises(RuntimeError, match=expected_name):
        polymarket_module.build_clob_client(_settings(**{field_name: value}))


def test_get_cached_clob_client_reuses_same_instance(monkeypatch):
    polymarket_module._client_cache.clear()
    created = {"count": 0}

    class DummyClient:
        pass

    def _fake_build(settings: Settings):
        _ = settings
        created["count"] += 1
        return DummyClient()

    monkeypatch.setattr(polymarket_module, "build_clob_client", _fake_build)

    settings = _settings()
    c1 = polymarket_module.get_cached_clob_client(settings)
    c2 = polymarket_module.get_cached_clob_client(settings)

    assert c1 is c2
    assert created["count"] == 1


def test_execute_weather_signal_market_buy_rejects_non_live_mode():
    with pytest.raises(RuntimeError, match="refusing to place real order"):
        polymarket_module.execute_weather_signal_market_buy(
            settings=_settings(trading_mode="paper"),
            signal=_signal(),
            request_id="req-1",
        )


def test_execute_weather_signal_market_buy_rejects_non_positive_amount(monkeypatch):
    class DummyClient:
        pass

    monkeypatch.setattr(
        polymarket_module,
        "get_cached_clob_client",
        lambda settings: DummyClient(),
    )

    signal = SimpleNamespace(token_id="token-abc", position_size_usd=0, market_price=0.5)

    with pytest.raises(RuntimeError, match="must be > 0"):
        polymarket_module.execute_weather_signal_market_buy(
            settings=_settings(),
            signal=signal,
            request_id="req-2",
        )


def test_execute_weather_signal_market_buy_posts_expected_order(monkeypatch):
    polymarket_module._market_options_cache.clear()

    class DummyClient:
        def __init__(self):
            self.market_order_args = None
            self.market_order_options = None
            self.posted_order = None
            self.post_order_type = None

        def get_order_book(self, token_id: str):
            assert token_id == "token-abc"
            return SimpleNamespace(tick_size="0.01", neg_risk=False)

        def create_market_order(self, order_args, options=None):
            self.market_order_args = order_args
            self.market_order_options = options
            return {"signed": "order"}

        def post_order(self, order, orderType=None):
            self.posted_order = order
            self.post_order_type = orderType
            return {"order_id": "ord-1"}

    client = DummyClient()
    monkeypatch.setattr(polymarket_module, "get_cached_clob_client", lambda settings: client)

    resp = polymarket_module.execute_weather_signal_market_buy(
        settings=_settings(max_slippage_abs=0.1),
        signal=_signal(position_size_usd=5.0, market_price=0.95),
        request_id="req-3",
    )

    assert resp == {"order_id": "ord-1"}
    assert client.market_order_args is not None
    assert client.market_order_args.token_id == "token-abc"
    assert client.market_order_args.amount == 5.0
    assert client.market_order_args.price == 0.99
    assert client.market_order_options is not None
    assert client.market_order_options.tick_size == "0.01"
    assert client.market_order_options.neg_risk is False
    assert client.posted_order == {"signed": "order"}
    assert client.post_order_type == polymarket_module.OrderType.FOK


def test_get_market_options_is_cached_by_token():
    polymarket_module._market_options_cache.clear()
    calls = {"book": 0}

    class DummyClient:
        def get_order_book(self, token_id: str):
            assert token_id == "token-abc"
            calls["book"] += 1
            return SimpleNamespace(tick_size="0.01", neg_risk=False)

    client = DummyClient()

    first = polymarket_module.get_market_options(client, "token-abc")
    second = polymarket_module.get_market_options(client, "token-abc")

    assert first == second == ("0.01", False)
    assert calls == {"book": 1}
