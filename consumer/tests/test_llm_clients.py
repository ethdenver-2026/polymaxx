from __future__ import annotations

import asyncio

import pytest

from signal_consumer.bid_pricing import BidDecision, BidPricingInput
from signal_consumer.llm_clients import BidLlmRouter, parse_bid_decision_json


def test_parse_bid_decision_json_validates_shape():
    raw = '{"should_bid": true, "bid_amount": 2.75, "rationale": "edge and confidence"}'
    parsed = parse_bid_decision_json(raw)
    assert parsed == BidDecision(should_bid=True, bid_amount=2.75, rationale="edge and confidence")


def test_parse_bid_decision_json_rejects_missing_fields():
    with pytest.raises(RuntimeError, match="bid_amount"):
        parse_bid_decision_json('{"should_bid": true, "rationale": "missing amount"}')


def test_parse_bid_decision_json_accepts_fenced_output():
    raw = (
        "Here is my decision:\\n"
        "```json\\n"
        '{"should_bid": true, "bid_amount": 2.0, "rationale": "good edge"}\\n'
        "```"
    )
    parsed = parse_bid_decision_json(raw)
    assert parsed == BidDecision(should_bid=True, bid_amount=2.0, rationale="good edge")


def test_bid_llm_router_rejects_unknown_provider():
    with pytest.raises(RuntimeError, match="Unsupported bid LLM provider"):
        BidLlmRouter(provider="bad-provider")


def test_bid_llm_router_uses_injected_client():
    context = BidPricingInput(
        auction_id="a1",
        producer_did="did:kite:producer/default/weather-v1",
        last_price_paid=1.1,
        edge=0.2,
        model_probability=0.62,
        confidence=0.8,
        balance_usdc=17.0,
        reputation_score=None,
    )

    class _FakeClient:
        async def decide_bid(self, _: BidPricingInput) -> BidDecision:
            return BidDecision(should_bid=True, bid_amount=1.75, rationale="ok")

    router = BidLlmRouter(
        provider="g0",
        g0_client=_FakeClient(),
    )
    decision = asyncio.run(router.decide_bid(context))
    assert decision.bid_amount == 1.75
