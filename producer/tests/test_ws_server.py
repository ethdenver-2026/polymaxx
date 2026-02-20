"""Smoke tests for websocket signal delivery."""

from datetime import datetime

from fastapi.testclient import TestClient

import signal_producer.ws_server as ws_server
from signal_producer.models.models import SignalRecord


def test_consumer_receives_full_signal_record_payload(monkeypatch):
    """Consumer websocket receives the full SignalRecord payload."""

    async def fake_run_once(cities=None):
        record = SignalRecord(
            id=42,
            strategy="weather",
            market_id="event-123",
            token_id="token-abc",
            model_probability=0.7,
            market_price=0.55,
            edge=0.15,
            confidence=0.8,
            decision="trade",
            skip_reason=None,
            trade_id=None,
            created_at=datetime(2026, 2, 20, 1, 2, 3),
            metadata_json='{"city":"nyc","bucket":"46-47"}',
        )
        await ws_server.broadcaster.broadcast_signal_record(record)
        return [record]

    monkeypatch.setattr(ws_server, "run_once", fake_run_once)

    with TestClient(ws_server.app) as client:
        with client.websocket_connect("/ws/signals") as websocket:
            response = client.post("/run-once")
            assert response.status_code == 200
            assert response.json()["signals_found"] == 1

            payload = websocket.receive_json()
            assert "published_at" in payload
            payload.pop("published_at")
            assert payload == {
                "id": 42,
                "strategy": "weather",
                "market_id": "event-123",
                "token_id": "token-abc",
                "model_probability": 0.7,
                "market_price": 0.55,
                "edge": 0.15,
                "confidence": 0.8,
                "decision": "trade",
                "skip_reason": None,
                "trade_id": None,
                "created_at": "2026-02-20T01:02:03",
                "metadata_json": '{"city":"nyc","bucket":"46-47"}',
            }
