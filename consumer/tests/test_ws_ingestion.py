from __future__ import annotations

import asyncio
import json
from collections import deque

from signal_consumer.bid_pricing import BidDecision
from signal_consumer.config import Settings
from signal_consumer.ws_ingestion import _submit_bid_for_preview, handle_raw_ws_message


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"trading_mode": "paper", "bankroll_usdc": 50.0}
    base.update(overrides)
    return Settings(**base)


def test_handle_raw_ws_message_logs_success(monkeypatch):
    payload = {
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
                "token_id": "tok-3",
                "side": "yes",
                "market_description": "Will NYC be 44-45F?",
                "resolution_source": "https://example.com",
                "market_price": 0.50,
                "edge": 0.11,
                "price_timestamp": "2026-02-19T00:01:00+00:00",
            }
        ],
        "published_at": "2026-02-19T00:02:00+00:00",
    }
    captured: dict = {}

    def _fake_process(payload_dict: dict, settings: Settings):
        assert payload_dict["signal_type"] == "weather"
        assert settings.trading_mode == "paper"
        return {"action": "simulated", "errors": []}

    def _fake_log(signal_data: dict, response: dict):
        captured["signal"] = signal_data
        captured["response"] = response

    monkeypatch.setattr("signal_consumer.ws_ingestion.process_signal_payload", _fake_process)
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_signal", _fake_log)
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", lambda **_: None)

    response = handle_raw_ws_message(json.dumps(payload), _settings())
    assert response["action"] == "simulated"
    assert captured["signal"]["signal_type"] == "weather"
    assert captured["response"]["action"] == "simulated"


def test_handle_raw_ws_message_returns_error_for_invalid_json():
    response = handle_raw_ws_message("{bad-json", _settings())
    assert response["action"] == "error"
    assert response["errors"]


def test_submit_bid_preview_handles_rejection(monkeypatch):
    preview_payload = {
        "type": "SignalPreviewMessage",
        "auction_id": "auction-1",
    }
    outbound_messages: list[dict] = []

    class _FakeBidSocket:
        def __init__(self):
            self._responses = deque(
                [
                    json.dumps({"type": "AuctionBidAccepted", "auction_id": "auction-1"}),
                    json.dumps(
                        {
                            "type": "AuctionBidRejected",
                            "auction_id": "auction-1",
                            "reason": "auction_elapsed",
                        }
                    ),
                ]
            )

        async def send(self, message: str):
            outbound_messages.append(json.loads(message))

        async def recv(self) -> str:
            return self._responses.popleft()

    class _FakeConnectContext:
        async def __aenter__(self):
            return _FakeBidSocket()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.websockets.connect",
        lambda _: _FakeConnectContext(),
    )
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", lambda **_: None)
    settings = _settings(
        consumer_did="did:kite:test/consumer-a",
        consumer_wallet_address="0xabc",
        consumer_default_bid_amount=2.5,
    )
    async def _fake_bid_decision(*_args, **_kwargs):
        return BidDecision(should_bid=True, bid_amount=2.5, rationale="ok")

    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.determine_bid_for_preview",
        _fake_bid_decision,
    )
    result = asyncio.run(_submit_bid_for_preview(preview_payload, settings))
    assert result["action"] == "AuctionBidRejected"
    assert outbound_messages[0]["type"] == "AuctionBidMessage"


def test_submit_bid_preview_skips_when_llm_says_do_not_bid(monkeypatch):
    preview_payload = {
        "type": "SignalPreviewMessage",
        "auction_id": "auction-1",
        "producer_did": "did:kite:producer/default/weather-v1",
        "exchanges": [{"event_id": "evt-1", "edge": 0.1}],
        "last_price_paid": 1.2,
        "model_probability": 0.6,
        "confidence": 0.7,
    }
    captured_events: list[dict] = []

    def _fake_log_auction_event(**kwargs):
        captured_events.append(kwargs)

    async def _fake_no_bid(*_args, **_kwargs):
        return BidDecision(should_bid=False, bid_amount=0.0, rationale="insufficient edge")

    monkeypatch.setattr("signal_consumer.ws_ingestion.determine_bid_for_preview", _fake_no_bid)
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", _fake_log_auction_event)

    result = asyncio.run(
        _submit_bid_for_preview(
            preview_payload,
            _settings(consumer_did="did:kite:test/consumer-a", consumer_wallet_address="0xabc"),
        )
    )

    assert result["action"] == "bid_skipped"
    assert any(event.get("outcome") == "bid_skipped" for event in captured_events)


def test_submit_bid_preview_sends_payment_failure_when_x402_fails(monkeypatch):
    preview_payload = {
        "type": "SignalPreviewMessage",
        "auction_id": "auction-1",
        "producer_did": "did:kite:producer/default/weather-v1",
        "exchanges": [{"event_id": "evt-1", "edge": 0.11}],
        "last_price_paid": 1.2,
        "model_probability": 0.6,
        "confidence": 0.7,
    }
    outbound_messages: list[dict] = []

    class _FakeBidSocket:
        def __init__(self):
            self._responses = deque(
                [
                    json.dumps({"type": "AuctionBidAccepted", "auction_id": "auction-1"}),
                    json.dumps(
                        {
                            "type": "AuctionWinNotice",
                            "auction_id": "auction-1",
                            "bid_amount": 2.0,
                            "x402_payment_url": "https://x402.dev.gokite.ai/api/weather",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "AuctionPaymentStatus",
                            "auction_id": "auction-1",
                            "status": "PAYMENT_FAILED",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "AuctionNoWinner",
                            "auction_id": "auction-1",
                            "reason": "bidder_list_exhausted",
                        }
                    ),
                ]
            )

        async def send(self, message: str):
            outbound_messages.append(json.loads(message))

        async def recv(self) -> str:
            return self._responses.popleft()

    class _FakeConnectContext:
        async def __aenter__(self):
            return _FakeBidSocket()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.websockets.connect",
        lambda _: _FakeConnectContext(),
    )
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", lambda **_: None)
    async def _fake_bid(*_args, **_kwargs):
        return BidDecision(should_bid=True, bid_amount=2.0, rationale="ok")

    monkeypatch.setattr("signal_consumer.ws_ingestion.determine_bid_for_preview", _fake_bid)
    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.process_auction_payment",
        lambda **_kwargs: False,
    )
    result = asyncio.run(
        _submit_bid_for_preview(
            preview_payload,
            _settings(consumer_did="did:kite:test/consumer-a", consumer_wallet_address="0xabc"),
        )
    )
    assert result["action"] == "AuctionNoWinner"
    payment_messages = [m for m in outbound_messages if m.get("type") == "AuctionPaymentResult"]
    assert payment_messages
    assert payment_messages[-1]["payment_success"] is False
