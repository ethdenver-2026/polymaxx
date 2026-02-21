"""LLM clients used to price incoming signal bids."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Protocol

import structlog

from .bid_pricing import BidDecision, BidPricingInput

logger = structlog.get_logger()


class BidLlmClient(Protocol):
    async def decide_bid(self, context: BidPricingInput) -> BidDecision: ...


def _extract_json_object(raw_text: str) -> dict:
    decoder = json.JSONDecoder()
    stripped = raw_text.strip()
    try:
        parsed, _ = decoder.raw_decode(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    if start == -1:
        raise RuntimeError("LLM response does not contain JSON object")
    try:
        parsed, _ = decoder.raw_decode(stripped[start:])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"LLM response must be a JSON object, got {type(parsed).__name__}")
    return parsed


def parse_bid_decision_json(raw_text: str) -> BidDecision:
    parsed = _extract_json_object(raw_text)
    missing = [field for field in ("should_bid", "bid_amount", "rationale") if field not in parsed]
    if missing:
        raise RuntimeError(f"LLM response missing required fields: {', '.join(missing)}")
    return BidDecision(
        should_bid=bool(parsed["should_bid"]),
        bid_amount=float(parsed["bid_amount"]),
        rationale=str(parsed["rationale"]),
    )


def _prompt_for_context(context: BidPricingInput) -> str:
    return (
        "You are a market-signal buyer. Return JSON only with keys "
        "should_bid (boolean), bid_amount (number), rationale (string). "
        f"Context: {json.dumps(asdict(context))}"
    )


class ZeroGBidClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float,
        timeout_seconds: float,
    ) -> None:
        if not api_key:
            raise RuntimeError("G0_API_KEY is required for g0 bid provider")
        if not base_url:
            raise RuntimeError("G0_BASE_URL is required for g0 bid provider")
        if not model:
            raise RuntimeError("G0_BID_MODEL is required for g0 bid provider")
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout_seconds)
        self._model = model
        self._temperature = temperature

    async def decide_bid(self, context: BidPricingInput) -> BidDecision:
        prompt = _prompt_for_context(context)
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        if not response.choices:
            raise RuntimeError("0G returned empty choices for bid decision")
        message = response.choices[0].message
        content = message.content if message else None
        if not content:
            raise RuntimeError("0G returned empty content for bid decision")
        return parse_bid_decision_json(content)


class BidLlmRouter:
    def __init__(
        self,
        *,
        provider: str,
        temperature: float = 0.8,
        g0_api_key: str = "",
        g0_base_url: str = "",
        g0_model: str = "",
        request_timeout_seconds: float = 15.0,
        g0_client: BidLlmClient | None = None,
    ) -> None:
        if provider != "g0":
            raise RuntimeError(f"Unsupported bid LLM provider: {provider}. Only 'g0' is supported")
        self._client = g0_client or ZeroGBidClient(
            api_key=g0_api_key,
            base_url=g0_base_url,
            model=g0_model,
            temperature=temperature,
            timeout_seconds=request_timeout_seconds,
        )

    async def decide_bid(self, context: BidPricingInput) -> BidDecision:
        return await self._client.decide_bid(context)
