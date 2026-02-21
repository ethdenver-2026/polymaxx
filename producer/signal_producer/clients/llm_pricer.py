"""LLM-based signal pricing module.

Two modes:
- mock: Formula-based pricing for when 0G is unavailable.
- 0g: Calls 0G Compute Network chatbot endpoint with a pricing prompt.
"""

from __future__ import annotations

import json
import re
import subprocess

import httpx
import structlog

from ..signals.types.producer_signal_preview import ProducerSignalPreview

logger = structlog.get_logger()

# Price bounds
MIN_PRICE = 0.01
MAX_PRICE = 5.00
BASE_PRICE = 1.00


def _mock_price(preview: ProducerSignalPreview) -> float:
    """Formula-based pricing: abs(edge) * confidence * base_price."""
    max_edge = max(abs(ex["edge"]) for ex in preview.exchanges) if preview.exchanges else 0.0
    price = max_edge * preview.confidence * BASE_PRICE
    return round(max(MIN_PRICE, min(MAX_PRICE, price)), 4)


def _build_pricing_prompt(preview: ProducerSignalPreview) -> str:
    max_edge = max(abs(ex["edge"]) for ex in preview.exchanges) if preview.exchanges else 0.0

    return (
        "You are a pricing engine for a prediction-market signal marketplace.\n"
        "A producer is auctioning a trading signal. Consumers see a preview and bid to unlock it.\n\n"
        "Signal preview (what the consumer sees):\n"
        f"- Producer: {preview.producer_did}\n"
        f"- Signal type: {preview.signal_type}\n"
        f"- Edge (model vs market): {max_edge:.4f}\n"
        f"- Model confidence: {preview.confidence:.2f}\n"
        f"- Last price paid for a signal: ${preview.last_price_paid:.2f}\n"
        f"- Auction ends: {preview.auction_end_utc}\n\n"
        "Price factors:\n"
        "- Higher edge = more valuable signal (bigger mispricing found)\n"
        "- Higher confidence = more reliable (tighter ensemble spread)\n"
        "- Last price paid anchors consumer expectations\n"
        "- Producer reputation matters but is hard to quantify early on\n\n"
        f"Set a suggested starting price in USDC between {MIN_PRICE} and {MAX_PRICE}.\n"
        "Respond with ONLY a single number, nothing else."
    )


def _get_0g_service_info() -> dict:
    """Get endpoint, model, and auth headers from the 0G broker via Node.js helper.

    Returns: {"endpoint": "...", "model": "...", "headers": {...}}
    """
    result = subprocess.run(
        ["node", "scripts/0g-auth-helper.mjs"],
        capture_output=True,
        text=True,
        timeout=30,
        env={**__import__("os").environ, "ZG_NETWORK": "mainnet"},
    )
    if result.returncode != 0:
        raise RuntimeError(f"0g-auth-helper failed: {result.stderr}")
    # SDK may print debug lines before the JSON — grab the last line starting with '{'
    for line in reversed(result.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(f"No JSON found in 0g-auth-helper output: {result.stdout[:200]}")


async def _0g_price(preview: ProducerSignalPreview, endpoint: str, model: str, temperature: float) -> float:
    """Call 0G Compute Network chatbot for pricing.

    If endpoint/model are empty, auto-discovers them from the 0G helper script.
    """
    service = _get_0g_service_info()
    auth_headers = service.get("headers", {})
    # Use provided endpoint/model or fall back to discovered ones
    actual_endpoint = endpoint or service.get("endpoint", "")
    actual_model = model or service.get("model", "")

    if not actual_endpoint:
        raise RuntimeError("No 0G endpoint available")

    prompt = _build_pricing_prompt(preview)

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{actual_endpoint}/chat/completions",
            headers={"Content-Type": "application/json", **auth_headers},
            json={
                "model": actual_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": 4096,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    message = data["choices"][0]["message"]
    content = message.get("content") or ""
    # Some models (e.g. GLM) put reasoning in a separate field
    reasoning = message.get("reasoning_content") or ""
    raw = content.strip() or reasoning.strip()

    if not raw:
        logger.warning("LLM returned empty response, falling back to mock")
        return _mock_price(preview)

    # Extract the first number-like token from the response
    match = re.search(r"\d+\.?\d*", raw)
    if not match:
        logger.warning("LLM returned no numeric value, falling back to mock", raw=raw[:200])
        return _mock_price(preview)

    try:
        price = float(match.group())
    except ValueError:
        logger.warning("LLM returned non-numeric price, falling back to mock", raw=raw[:200])
        return _mock_price(preview)

    return round(max(MIN_PRICE, min(MAX_PRICE, price)), 4)


async def price_signal(
    preview: ProducerSignalPreview,
    mode: str = "mock",
    endpoint: str = "",
    model: str = "",
    temperature: float = 0.8,
) -> float:
    """Price a signal preview. Returns price in USDC."""
    if mode == "mock":
        return _mock_price(preview)

    try:
        return await _0g_price(preview, endpoint=endpoint, model=model, temperature=temperature)
    except Exception as e:
        logger.error("0G pricing failed, falling back to mock", error=str(e))
        return _mock_price(preview)
