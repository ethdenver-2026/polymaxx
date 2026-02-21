from __future__ import annotations

import pytest

from signal_consumer.bid_pricing import (
    BidDecision,
    build_bid_pricing_input,
    normalize_bid_decision,
)


def test_build_bid_pricing_input_uses_preview_fields():
    preview_payload = {
        "auction_id": "auction-1",
        "producer_did": "did:kite:producer/default/weather-v1",
        "last_price_paid": 2.2,
        "model_probability": 0.72,
        "confidence": 0.88,
        "exchanges": [{"event_id": "evt-1", "edge": 0.14}],
    }

    context = build_bid_pricing_input(
        preview_payload=preview_payload,
        balance_usdc=25.0,
        reputation_score=None,
    )

    assert context.auction_id == "auction-1"
    assert context.producer_did == "did:kite:producer/default/weather-v1"
    assert context.last_price_paid == 2.2
    assert context.edge == 0.14
    assert context.balance_usdc == 25.0
    assert context.reputation_score is None


def test_build_bid_pricing_input_rejects_missing_exchange_edge():
    preview_payload = {
        "auction_id": "auction-1",
        "producer_did": "did:kite:producer/default/weather-v1",
        "last_price_paid": 2.2,
        "model_probability": 0.72,
        "confidence": 0.88,
        "exchanges": [{"event_id": "evt-1"}],
    }

    with pytest.raises(RuntimeError, match="edge"):
        build_bid_pricing_input(
            preview_payload=preview_payload,
            balance_usdc=25.0,
            reputation_score=None,
        )


def test_normalize_bid_decision_clamps_to_bounds():
    decision = BidDecision(should_bid=True, bid_amount=100.0, rationale="high conviction")
    normalized = normalize_bid_decision(
        decision=decision,
        available_balance_usdc=9.0,
        max_bid_amount_usdc=5.0,
    )

    assert normalized.should_bid is True
    assert normalized.bid_amount == 5.0


def test_normalize_bid_decision_zeroes_amount_when_should_not_bid():
    decision = BidDecision(should_bid=False, bid_amount=3.5, rationale="skip")
    normalized = normalize_bid_decision(
        decision=decision,
        available_balance_usdc=12.0,
        max_bid_amount_usdc=5.0,
    )

    assert normalized.should_bid is False
    assert normalized.bid_amount == 0.0
