"""Smoke tests for websocket signal delivery."""

from datetime import date

from fastapi.testclient import TestClient

import signal_producer.ws_server as ws_server
from signal_producer.strategies.base import Signal


def test_consumer_can_connect_and_receive_signal(monkeypatch):
    """Consumer websocket receives a signal after /run-once trigger."""

    async def fake_run_once(cities=None):
        signal = Signal(
            strategy="weather",
            market_id="event-123",
            token_id="token-abc",
            description="Will NYC be 46-47F?",
            target_date=date(2026, 2, 20),
            model_probability=0.7,
            market_price=0.55,
            edge=0.15,
            position_size_usd=5.0,
            expected_value=0.75,
            confidence=0.8,
            metadata={"city": "nyc"},
        )
        await ws_server.broadcaster.broadcast_signal(signal)
        return [signal]

    monkeypatch.setattr(ws_server, "run_once", fake_run_once)

    with TestClient(ws_server.app) as client:
        with client.websocket_connect("/ws/signals") as websocket:
            response = client.post("/run-once")
            assert response.status_code == 200
            assert response.json()["signals_found"] == 1

            payload = websocket.receive_json()
            assert payload["market_id"] == "event-123"
            assert payload["token_id"] == "token-abc"
            assert payload["metadata"]["city"] == "nyc"
            assert "published_at" in payload
"""Smoke tests for websocket signal delivery."""

from datetime import date

from fastapi.testclient import TestClient

import signal_producer.ws_server as ws_server
from signal_producer.strategies.base import Signal


def test_consumer_can_connect_and_receive_signal(monkeypatch):
    """Consumer websocket receives a signal after /run-once trigger."""

    async def fake_run_once(cities=None):
        signal = Signal(
            strategy="weather",
            market_id="event-123",
            token_id="token-abc",
            description="Will NYC be 46-47F?",
            target_date=date(2026, 2, 20),
            model_probability=0.7,
            market_price=0.55,
            edge=0.15,
            position_size_usd=5.0,
            expected_value=0.75,
            confidence=0.8,
            metadata={"city": "nyc"},
        )
        await ws_server.broadcaster.broadcast_signal(signal)
        return [signal]

    monkeypatch.setattr(ws_server, "run_once", fake_run_once)

    with TestClient(ws_server.app) as client:
        with client.websocket_connect("/ws/signals") as websocket:
            response = client.post("/run-once")
            assert response.status_code == 200
            assert response.json()["signals_found"] == 1

            payload = websocket.receive_json()
            assert payload["market_id"] == "event-123"
            assert payload["token_id"] == "token-abc"
            assert payload["metadata"]["city"] == "nyc"
            assert "published_at" in payload
