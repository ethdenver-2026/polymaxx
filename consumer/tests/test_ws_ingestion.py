from __future__ import annotations

import asyncio
import json
from collections import deque

from signal_consumer.bid_pricing import BidDecision
from signal_consumer.config import Settings
from signal_consumer.ws_ingestion import (
    _submit_bid_for_preview,
    determine_bid_for_preview,
    handle_raw_ws_message,
)


def _settings(**overrides: object) -> Settings:
    wallet = "0x0000000000000000000000000000000000000001"
    base: dict[str, object] = {
        "trading_mode": "paper",
        "bankroll_usdc": 50.0,
        "consumer_wallet_address": wallet,
        "payment_wallet_address": wallet,
        "trading_wallet_address": wallet,
        "payment_wallet_private_key": "0x" + "1" * 64,
        "trading_wallet_private_key": "0x" + "1" * 64,
        "consumer_did": f"did:pkh:eip155:137:{wallet}",
    }
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
    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.is_consumer_reputation_sufficient",
        lambda _did, threshold=5: True,
    )
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", lambda **_: None)
    settings = _settings(
        consumer_did="did:pkh:eip155:137:0x0000000000000000000000000000000000000001",
        consumer_wallet_address="0x0000000000000000000000000000000000000001",
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

    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.is_consumer_reputation_sufficient",
        lambda _did, threshold=5: True,
    )
    monkeypatch.setattr("signal_consumer.ws_ingestion.determine_bid_for_preview", _fake_no_bid)
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", _fake_log_auction_event)

    result = asyncio.run(
        _submit_bid_for_preview(
            preview_payload,
            _settings(
                consumer_did="did:pkh:eip155:137:0x0000000000000000000000000000000000000001",
                consumer_wallet_address="0x0000000000000000000000000000000000000001",
            ),
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
    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.is_consumer_reputation_sufficient",
        lambda _did, threshold=5: True,
    )
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", lambda **_: None)
    monkeypatch.setattr("signal_consumer.ws_ingestion.record_consumer_payment_failure", lambda **_: None)
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
            _settings(
                consumer_did="did:pkh:eip155:137:0x0000000000000000000000000000000000000001",
                consumer_wallet_address="0x0000000000000000000000000000000000000001",
                consumer_payment_auto_succeeds=False,
            ),
        )
    )
    assert result["action"] == "AuctionNoWinner"
    payment_messages = [m for m in outbound_messages if m.get("type") == "AuctionPaymentResult"]
    assert payment_messages
    assert payment_messages[-1]["payment_success"] is False


def test_submit_bid_preview_rejects_when_reputation_insufficient(monkeypatch):
    preview_payload = {
        "type": "SignalPreviewMessage",
        "auction_id": "auction-1",
        "producer_did": "did:kite:producer/default/weather-v1",
        "exchanges": [{"event_id": "evt-1", "edge": 0.11}],
        "last_price_paid": 1.2,
        "model_probability": 0.6,
        "confidence": 0.7,
    }
    events: list[dict] = []

    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.is_consumer_reputation_sufficient",
        lambda _did, threshold=5: False,
    )
    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.log_auction_event",
        lambda **kwargs: events.append(kwargs),
    )
    result = asyncio.run(
        _submit_bid_for_preview(
            preview_payload,
            _settings(
                consumer_did="did:pkh:eip155:137:0x0000000000000000000000000000000000000001",
                consumer_wallet_address="0x0000000000000000000000000000000000000001",
                chain_id=137,
            ),
        )
    )
    assert result["action"] == "InsufficientReputation"
    assert any(event.get("outcome") == "insufficient_reputation" for event in events)


def test_submit_bid_preview_uses_llm_decision_amount_end_to_end(monkeypatch):
    preview_payload = {
        "type": "SignalPreviewMessage",
        "auction_id": "auction-llm",
        "producer_did": "did:kite:producer/default/weather-v1",
        "exchanges": [{"event_id": "evt-llm", "edge": 0.21}],
        "last_price_paid": 1.2,
        "model_probability": 0.75,
        "confidence": 0.83,
    }
    outbound_messages: list[dict] = []

    class _FakeBidSocket:
        def __init__(self):
            self._responses = deque(
                [
                    json.dumps(
                        {
                            "type": "AuctionBidRejected",
                            "auction_id": "auction-llm",
                            "reason": "auction_elapsed",
                        }
                    )
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

    class _FakeBalances:
        polymarket_usdc = 0.0
        onchain_usdc = 0.0
        onchain_pol = 1.0

    class _FakeRouter:
        def __init__(self, **_kwargs):
            pass

        async def decide_bid(self, _context):
            # Deliberately over max bid to verify normalization path.
            return BidDecision(should_bid=True, bid_amount=9.5, rationale="strong edge")

    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.websockets.connect",
        lambda _: _FakeConnectContext(),
    )
    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.is_consumer_reputation_sufficient",
        lambda _did, threshold=5: True,
    )
    monkeypatch.setattr("signal_consumer.ws_ingestion.get_balances", lambda **_kwargs: _FakeBalances())
    monkeypatch.setattr(
        "signal_consumer.ws_ingestion.get_payment_usdc_balance",
        lambda **_kwargs: 100.0,
    )
    monkeypatch.setattr("signal_consumer.ws_ingestion.BidLlmRouter", _FakeRouter)
    monkeypatch.setattr("signal_consumer.ws_ingestion.log_auction_event", lambda **_: None)

    result = asyncio.run(
        _submit_bid_for_preview(
            preview_payload,
            _settings(
                consumer_did="did:pkh:eip155:137:0x0000000000000000000000000000000000000001",
                consumer_wallet_address="0x0000000000000000000000000000000000000001",
                bid_llm_max_bid_amount_usdc=5.0,
            ),
        )
    )
    assert result["action"] == "AuctionBidRejected"
    assert outbound_messages
    assert outbound_messages[0]["type"] == "AuctionBidMessage"
    # Bid amount should be produced by LLM path then normalized to max.
    assert outbound_messages[0]["bid_amount"] == 5.0


def test_determine_bid_for_preview_skips_when_polygon_pol_below_threshold(monkeypatch):
    preview_payload = {
        "type": "SignalPreviewMessage",
        "auction_id": "auction-pol-gate",
        "producer_did": "did:kite:producer/default/weather-v1",
        "exchanges": [{"event_id": "evt-pol", "edge": 0.25}],
        "last_price_paid": 1.0,
        "model_probability": 0.8,
        "confidence": 0.9,
    }

    class _LowPolBalances:
        polymarket_usdc = 0.0
        onchain_usdc = 0.0
        onchain_pol = 0.0

    class _FailIfCalledRouter:
        def __init__(self, **_kwargs):
            pass

        async def decide_bid(self, _context):
            raise AssertionError("LLM should not be called when POL gate fails")

    monkeypatch.setattr("signal_consumer.ws_ingestion.get_balances", lambda **_kwargs: _LowPolBalances())
    monkeypatch.setattr("signal_consumer.ws_ingestion.BidLlmRouter", _FailIfCalledRouter)

    decision = asyncio.run(
        determine_bid_for_preview(
            preview_payload,
            _settings(min_polygon_pol_for_bidding=0.01),
        )
    )
    assert decision.should_bid is False
    assert decision.bid_amount == 0.0
    assert "insufficient_polygon_pol" in decision.rationale
