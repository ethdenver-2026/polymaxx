"""LLM-based signal pricing via WebSocket connection to 0G pricer service.

Two modes:
- mock: Formula-based pricing for when 0G is unavailable.
- 0g: Connects to the 0G WS pricer (scripts/0g-ws-pricer.mjs) over WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid

import structlog
import websockets
from websockets.asyncio.client import ClientConnection

from ..signals.types.producer_signal_preview import ProducerSignalPreview

logger = structlog.get_logger()

# Price bounds
MIN_PRICE = 0.01
MAX_PRICE = 5.00
BASE_PRICE = 1.00

# Default WebSocket URI for the 0G pricer sidecar
DEFAULT_ZG_WS_URI = "ws://localhost:8089"


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


class ZgWsPricer:
    """Persistent WebSocket client to the 0G pricer sidecar."""

    def __init__(self, ws_uri: str = DEFAULT_ZG_WS_URI) -> None:
        self._ws_uri = ws_uri
        self._ws: ClientConnection | None = None
        self._model: str = ""
        self._connected = False

    async def connect(self) -> None:
        """Connect to the 0G WS pricer and wait for the ready message."""
        self._ws = await websockets.connect(self._ws_uri)
        # Wait for ready handshake
        raw = await asyncio.wait_for(self._ws.recv(), timeout=10)
        msg = json.loads(raw)
        if msg.get("type") == "ready":
            self._model = msg.get("model", "")
            self._connected = True
            logger.info(
                "Connected to 0G WS pricer",
                uri=self._ws_uri,
                model=self._model,
            )
        else:
            raise RuntimeError(f"Unexpected handshake message: {msg}")

    async def close(self) -> None:
        if self._ws:
            await self._ws.close()
            self._connected = False

    async def price(self, preview: ProducerSignalPreview, temperature: float) -> float:
        """Send a pricing request over WebSocket and return the price."""
        if not self._connected or not self._ws:
            await self.connect()

        request_id = str(uuid.uuid4())
        prompt = _build_pricing_prompt(preview)

        await self._ws.send(json.dumps({
            "type": "price_request",
            "request_id": request_id,
            "prompt": prompt,
            "temperature": temperature,
        }))

        # Wait for the matching response (120s for reasoning models)
        raw = await asyncio.wait_for(self._ws.recv(), timeout=120)
        resp = json.loads(raw)

        if resp.get("error"):
            raise RuntimeError(f"0G pricer error: {resp['error']}")

        price = resp.get("price")
        if price is None:
            raise RuntimeError(f"No price in response: {resp.get('raw', '')[:200]}")

        return round(max(MIN_PRICE, min(MAX_PRICE, float(price))), 4)


# Module-level singleton — reused across pricing calls
_pricer: ZgWsPricer | None = None


async def _0g_price(preview: ProducerSignalPreview, ws_uri: str, temperature: float) -> float:
    """Price a signal via the 0G WebSocket pricer."""
    global _pricer
    if _pricer is None:
        _pricer = ZgWsPricer(ws_uri=ws_uri)

    try:
        return await _pricer.price(preview, temperature)
    except (websockets.ConnectionClosed, OSError):
        # Connection dropped — reconnect once and retry
        logger.warning("0G WS connection lost, reconnecting")
        _pricer = ZgWsPricer(ws_uri=ws_uri)
        return await _pricer.price(preview, temperature)


async def price_signal(
    preview: ProducerSignalPreview,
    mode: str = "mock",
    ws_uri: str = DEFAULT_ZG_WS_URI,
    temperature: float = 0.8,
) -> float:
    """Price a signal preview. Returns price in USDC.

    Args:
        preview: The signal preview to price.
        mode: "mock" for formula-based, "0g" for 0G LLM via WebSocket.
        ws_uri: WebSocket URI of the 0G pricer sidecar.
        temperature: LLM temperature (0.7-0.9 for natural variation).
    """
    if mode == "mock":
        return _mock_price(preview)

    try:
        return await _0g_price(preview, ws_uri=ws_uri, temperature=temperature)
    except Exception as e:
        logger.error("0G WS pricing failed, falling back to mock", error=str(e))
        return _mock_price(preview)
