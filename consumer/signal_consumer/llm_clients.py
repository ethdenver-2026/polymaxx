"""LLM clients used to price incoming signal bids."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Protocol

from .bid_pricing import BidDecision, BidPricingInput


class BidLlmClient(Protocol):
    async def decide_bid(self, context: BidPricingInput) -> BidDecision: ...


def parse_bid_decision_json(raw_text: str) -> BidDecision:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"LLM response must be a JSON object, got {type(parsed).__name__}")
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


class MockBidClient:
    """Formula-based bid pricing — no LLM needed."""

    async def decide_bid(self, context: BidPricingInput) -> BidDecision:
        bid = abs(context.edge) * context.confidence * 1.0
        bid = round(max(0.01, min(5.0, bid)), 4)
        return BidDecision(
            should_bid=True,
            bid_amount=bid,
            rationale="mock: edge * confidence",
        )


class AnthropicBidClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        temperature: float,
        timeout_seconds: float,
    ) -> None:
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for anthropic bid provider")
        if not model:
            raise RuntimeError("ANTHROPIC_BID_MODEL is required for anthropic bid provider")
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)
        self._model = model
        self._temperature = temperature

    async def decide_bid(self, context: BidPricingInput) -> BidDecision:
        prompt = _prompt_for_context(context)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=300,
            temperature=self._temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        blocks = getattr(response, "content", [])
        if not blocks:
            raise RuntimeError("Anthropic returned empty content for bid decision")
        first_text = getattr(blocks[0], "text", "")
        if not first_text:
            raise RuntimeError("Anthropic returned non-text content for bid decision")
        return parse_bid_decision_json(first_text)


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
        anthropic_api_key: str,
        anthropic_model: str,
        anthropic_temperature: float = 0.8,
        g0_api_key: str = "",
        g0_base_url: str = "",
        g0_model: str = "",
        request_timeout_seconds: float = 15.0,
        anthropic_client: BidLlmClient | None = None,
        g0_client: BidLlmClient | None = None,
    ) -> None:
        self._provider = provider
        if provider == "mock":
            self._client = MockBidClient()
            return
        if provider == "anthropic":
            self._client = anthropic_client or AnthropicBidClient(
                api_key=anthropic_api_key,
                model=anthropic_model,
                temperature=anthropic_temperature,
                timeout_seconds=request_timeout_seconds,
            )
            return
        if provider == "g0":
            self._client = g0_client or ZeroGBidClient(
                api_key=g0_api_key,
                base_url=g0_base_url,
                model=g0_model,
                temperature=anthropic_temperature,
                timeout_seconds=request_timeout_seconds,
            )
            return
        raise RuntimeError(f"Unsupported bid LLM provider: {provider}")

    async def decide_bid(self, context: BidPricingInput) -> BidDecision:
        return await self._client.decide_bid(context)
