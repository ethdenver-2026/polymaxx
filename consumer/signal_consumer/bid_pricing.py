"""Bid-pricing domain model and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class BidPricingInput:
    auction_id: str
    producer_did: str
    last_price_paid: float
    edge: float
    model_probability: float
    confidence: float
    balance_usdc: float
    reputation_score: float | None


@dataclass(slots=True)
class BidDecision:
    should_bid: bool
    bid_amount: float
    rationale: str


def build_bid_pricing_input(
    *,
    preview_payload: dict[str, Any],
    balance_usdc: float,
    reputation_score: float | None,
) -> BidPricingInput:
    auction_id = str(preview_payload.get("auction_id", "")).strip()
    producer_did = str(preview_payload.get("producer_did", "")).strip()
    if not auction_id:
        raise RuntimeError("SignalPreviewMessage missing auction_id for bid pricing")
    if not producer_did:
        raise RuntimeError("SignalPreviewMessage missing producer_did for bid pricing")

    exchanges = preview_payload.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise RuntimeError("SignalPreviewMessage missing exchanges for bid pricing")
    first_exchange = exchanges[0]
    edge = first_exchange.get("edge")
    if edge is None:
        raise RuntimeError("SignalPreviewMessage exchanges[0].edge is required for bid pricing")

    return BidPricingInput(
        auction_id=auction_id,
        producer_did=producer_did,
        last_price_paid=float(preview_payload.get("last_price_paid")),
        edge=float(edge),
        model_probability=float(preview_payload.get("model_probability")),
        confidence=float(preview_payload.get("confidence")),
        balance_usdc=float(balance_usdc),
        reputation_score=None if reputation_score is None else float(reputation_score),
    )


def normalize_bid_decision(
    *,
    decision: BidDecision,
    available_balance_usdc: float,
    max_bid_amount_usdc: float,
) -> BidDecision:
    if available_balance_usdc <= 0:
        return BidDecision(should_bid=False, bid_amount=0.0, rationale=decision.rationale)
    if max_bid_amount_usdc <= 0:
        raise RuntimeError("max_bid_amount_usdc must be > 0")

    if not decision.should_bid:
        return BidDecision(should_bid=False, bid_amount=0.0, rationale=decision.rationale)

    bounded = min(
        float(decision.bid_amount),
        float(available_balance_usdc),
        float(max_bid_amount_usdc),
    )
    if bounded <= 0:
        return BidDecision(should_bid=False, bid_amount=0.0, rationale=decision.rationale)
    return BidDecision(should_bid=True, bid_amount=bounded, rationale=decision.rationale)
