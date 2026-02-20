"""Smoke tests for websocket signal delivery."""

from fastapi.testclient import TestClient

import signal_producer.ws_server as ws_server
from signal_producer.signals.types import ProducerSignal, WeatherMetadata, PolymarketInfo


def test_consumer_receives_canonical_producer_signal_payload(monkeypatch):
    """Consumer websocket receives canonical ProducerSignal payload."""

    async def fake_run_once(cities=None, broadcast_signals=False):
        signal = ProducerSignal(
            signal_type="weather",
            model_probability=0.7,
            confidence=0.8,
            forecast_source="open_meteo",
            forecast_time="2026-02-20T00:00:00",
            metadata=WeatherMetadata(
                city="nyc",
                target_date="2026-02-20",
                ensemble_mean=45.5,
                ensemble_std=2.3,
                members_in_range=12,
            ),
            exchanges=[
                PolymarketInfo(
                    exchange="polymarket",
                    event_id="event-123",
                    token_id="token-abc",
                    side="yes",
                    market_description="Will the highest temperature be 46-47°F?",
                    resolution_source="https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA",
                    market_price=0.55,
                    edge=0.15,
                    price_timestamp="2026-02-20T01:02:03",
                ),
            ],
        )
        await ws_server.broadcaster.broadcast_producer_signal(signal)
        return [signal]

    monkeypatch.setattr(ws_server, "run_once", fake_run_once)

    with TestClient(ws_server.app) as client:
        with client.websocket_connect("/ws/signals") as websocket:
            response = client.post("/run-once")
            assert response.status_code == 200
            assert response.json()["signals_found"] == 1

            payload = websocket.receive_json()
            assert "published_at" in payload
            payload.pop("published_at")
            assert payload["signal_type"] == "weather"
            assert payload["model_probability"] == 0.7
            assert payload["forecast_source"] == "open_meteo"
            assert payload["metadata"]["city"] == "nyc"
            assert payload["metadata"]["target_date"] == "2026-02-20"
            assert payload["exchanges"][0]["exchange"] == "polymarket"
            assert payload["exchanges"][0]["event_id"] == "event-123"
            assert payload["exchanges"][0]["token_id"] == "token-abc"
            assert payload["exchanges"][0]["side"] == "yes"
