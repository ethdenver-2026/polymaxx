"""Tests for signal-consumer webhook behavior."""

from __future__ import annotations

import asyncio
import threading
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from signal_schema import MarketType, Signal, SignalMetadata

from signal_consumer import config as config_module
from signal_consumer.api import create_app


def _build_signal(*, strategy: str = "weather", edge: float = 0.03) -> Signal:
    return Signal(
        strategy=strategy,
        market_type=MarketType.POLYMARKET,
        market_id="market-123",
        token_id="token-abc",
        description="Weather bucket signal",
        target_date=date.today(),
        model_probability=0.55,
        market_price=0.50,
        edge=edge,
        confidence=0.9,
        position_size_usd=5.0,
        expected_value=0.20,
        metadata=SignalMetadata(city="nyc", bucket_low=40, bucket_high=41),
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_webhook_rejects_non_weather_strategy():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/signal",
            json=_build_signal(strategy="esports").model_dump(mode="json"),
        )

    assert resp.status_code == 400
    assert "unsupported strategy" in resp.text


@pytest.mark.asyncio
async def test_webhook_skips_weather_signal_below_threshold():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/signal",
            json=_build_signal(edge=0.019).model_dump(mode="json"),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"


@pytest.mark.asyncio
async def test_webhook_simulates_weather_signal_in_paper_mode(monkeypatch):
    dispatched = {"count": 0}

    def _fake_exec(*, settings, signal, request_id):
        assert request_id
        assert signal.edge >= 0.02
        dispatched["count"] += 1
        return {"ok": True}

    monkeypatch.setattr("signal_consumer.api.execute_weather_signal_market_buy", _fake_exec)
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/signal",
            json=_build_signal(edge=0.02).model_dump(mode="json"),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "simulated"

    # Dispatch is synchronous in paper mode.
    assert dispatched["count"] == 0


@pytest.mark.asyncio
async def test_webhook_accepts_and_dispatches_in_live_mode(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("EXECUTION_WORKERS", "1")
    monkeypatch.setenv("EXECUTION_QUEUE_MAXSIZE", "10")

    dispatched = {"count": 0}

    def _fake_exec(*, settings, signal, request_id):
        assert request_id
        assert settings.trading_mode == "live"
        assert signal.edge >= 0.02
        dispatched["count"] += 1
        return {"ok": True}

    monkeypatch.setattr("signal_consumer.api.execute_weather_signal_market_buy", _fake_exec)
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/webhook/signal",
            json=_build_signal(edge=0.02).model_dump(mode="json"),
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accepted"

    # Poll briefly instead of fixed sleep to avoid flaky timing assumptions.
    for _ in range(50):
        if dispatched["count"] == 1:
            break
        await asyncio.sleep(0.01)

    assert dispatched["count"] == 1


@pytest.mark.asyncio
async def test_healthz_returns_ok():
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_payload_missing_required_field():
    app = create_app()
    payload = _build_signal().model_dump(mode="json")
    payload.pop("token_id")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhook/signal", json=payload)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_payload_wrong_type():
    app = create_app()
    payload = _build_signal().model_dump(mode="json")
    payload["edge"] = {"not": "a number"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/webhook/signal", json=payload)

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_webhook_returns_503_when_execution_queue_is_full(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("EXECUTION_WORKERS", "1")
    monkeypatch.setenv("EXECUTION_QUEUE_MAXSIZE", "1")

    release_worker = threading.Event()

    def _slow_exec(*, settings, signal, request_id):
        _ = settings, signal, request_id
        release_worker.wait(timeout=2)
        return {"ok": True}

    monkeypatch.setattr("signal_consumer.api.execute_weather_signal_market_buy", _slow_exec)
    app = create_app()

    statuses: list[int] = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(5):
            resp = await client.post(
                "/webhook/signal",
                json=_build_signal(edge=0.02).model_dump(mode="json"),
            )
            statuses.append(resp.status_code)
            if resp.status_code == 503:
                assert resp.json()["detail"] == "execution queue is full"
                break

    release_worker.set()
    await asyncio.sleep(0.05)

    assert 200 in statuses
    assert 503 in statuses


@pytest.mark.asyncio
async def test_worker_error_does_not_stop_subsequent_processing(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("EXECUTION_WORKERS", "1")
    monkeypatch.setenv("EXECUTION_QUEUE_MAXSIZE", "10")

    attempts = {"count": 0}

    def _flaky_exec(*, settings, signal, request_id):
        _ = settings, signal, request_id
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    monkeypatch.setattr("signal_consumer.api.execute_weather_signal_market_buy", _flaky_exec)
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp1 = await client.post(
            "/webhook/signal",
            json=_build_signal(edge=0.02).model_dump(mode="json"),
        )
        resp2 = await client.post(
            "/webhook/signal",
            json=_build_signal(edge=0.03).model_dump(mode="json"),
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    for _ in range(50):
        if attempts["count"] >= 2:
            break
        await asyncio.sleep(0.01)

    assert attempts["count"] >= 2


@pytest.mark.asyncio
async def test_webhook_dispatches_multiple_live_signals(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("EXECUTION_WORKERS", "2")
    monkeypatch.setenv("EXECUTION_QUEUE_MAXSIZE", "20")

    dispatched = {"count": 0}

    def _fake_exec(*, settings, signal, request_id):
        _ = settings, request_id
        assert signal.strategy == "weather"
        dispatched["count"] += 1
        return {"ok": True}

    monkeypatch.setattr("signal_consumer.api.execute_weather_signal_market_buy", _fake_exec)
    app = create_app()
    total = 8

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.post(
                    "/webhook/signal",
                    json=_build_signal(edge=0.02 + (i * 0.001)).model_dump(mode="json"),
                )
                for i in range(total)
            )
        )

    assert all(resp.status_code == 200 for resp in responses)
    assert all(resp.json()["status"] == "accepted" for resp in responses)

    for _ in range(100):
        if dispatched["count"] == total:
            break
        await asyncio.sleep(0.01)

    assert dispatched["count"] == total

