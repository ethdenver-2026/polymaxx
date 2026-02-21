"""LLM-based signal pricing via WebSocket connection to 0G pricer service.

Two modes:
- mock: Formula-based pricing for when 0G is unavailable.
- 0g: Connects to the 0G WS pricer (scripts/0g-ws-pricer.mjs) over WebSocket.

Returns structured AuctionBidMessage dicts ready to send to the producer.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import structlog
import websockets
from websockets.asyncio.client import ClientConnection

from ..signals.types import (
    ProducerSignalPreview,
    AuctionBidMessage,
)

logger = structlog.get_logger()

# Bid bounds
MIN_BID = 0.01
MAX_BID = 5.00
BASE_PRICE = 1.00

# Default WebSocket URI for the 0G pricer sidecar
DEFAULT_ZG_WS_URI = "ws://localhost:8089"


def _mock_bid(
    preview: ProducerSignalPreview,
    auction_id: str,
    consumer_did: str,
    wallet_address: str,
) -> AuctionBidMessage:
    """Formula-based bid: abs(edge) * confidence * base_price."""
    max_edge = max(abs(ex["edge"]) for ex in preview.exchanges) if preview.exchanges else 0.0
    bid_amount = max_edge * preview.confidence * BASE_PRICE
    bid_amount = round(max(MIN_BID, min(MAX_BID, bid_amount)), 4)

    return AuctionBidMessage(
        auction_id=auction_id,
        consumer_did=consumer_did,
        bid_amount=bid_amount,
        wallet_address=wallet_address,
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

    async def get_bid(
        self,
        preview: ProducerSignalPreview,
        auction_id: str,
        consumer_did: str,
        wallet_address: str,
        temperature: float,
    ) -> AuctionBidMessage:
        """Send a pricing request and return a structured AuctionBidMessage."""
        if not self._connected or not self._ws:
            await self.connect()

        request_id = str(uuid.uuid4())
        max_edge = max(abs(ex["edge"]) for ex in preview.exchanges) if preview.exchanges else 0.0

        await self._ws.send(json.dumps({
            "type": "price_request",
            "request_id": request_id,
            "auction_id": auction_id,
            "consumer_did": consumer_did,
            "wallet_address": wallet_address,
            "preview": {
                "signal_type": preview.signal_type,
                "producer_did": preview.producer_did,
                "edge": max_edge,
                "confidence": preview.confidence,
                "last_price_paid": preview.last_price_paid,
                "auction_end_utc": preview.auction_end_utc,
            },
            "temperature": temperature,
        }))

        raw = await asyncio.wait_for(self._ws.recv(), timeout=120)
        resp = json.loads(raw)

        if resp.get("error"):
            raise RuntimeError(f"0G pricer error: {resp['error']}")

        bid_data = resp.get("bid")
        if not bid_data or bid_data.get("bid_amount") is None:
            raise RuntimeError(f"No bid in response: {resp}")

        return AuctionBidMessage(
            auction_id=bid_data["auction_id"],
            consumer_did=bid_data["consumer_did"],
            bid_amount=float(bid_data["bid_amount"]),
            wallet_address=bid_data["wallet_address"],
        )


# Module-level singleton
_pricer: ZgWsPricer | None = None


async def _0g_bid(
    preview: ProducerSignalPreview,
    auction_id: str,
    consumer_did: str,
    wallet_address: str,
    ws_uri: str,
    temperature: float,
) -> AuctionBidMessage:
    """Get a bid via the 0G WebSocket pricer."""
    global _pricer
    if _pricer is None:
        _pricer = ZgWsPricer(ws_uri=ws_uri)

    try:
        return await _pricer.get_bid(preview, auction_id, consumer_did, wallet_address, temperature)
    except (websockets.ConnectionClosed, OSError):
        logger.warning("0G WS connection lost, reconnecting")
        _pricer = ZgWsPricer(ws_uri=ws_uri)
        return await _pricer.get_bid(preview, auction_id, consumer_did, wallet_address, temperature)


async def price_signal(
    preview: ProducerSignalPreview,
    auction_id: str = "",
    consumer_did: str = "",
    wallet_address: str = "",
    mode: str = "mock",
    ws_uri: str = DEFAULT_ZG_WS_URI,
    temperature: float = 0.8,
) -> AuctionBidMessage:
    """Price a signal preview. Returns a structured AuctionBidMessage.

    Args:
        preview: The signal preview to price.
        auction_id: Auction to bid on.
        consumer_did: Identity of the bidding consumer.
        wallet_address: Consumer's wallet address.
        mode: "mock" for formula-based, "0g" for 0G LLM via WebSocket.
        ws_uri: WebSocket URI of the 0G pricer sidecar.
        temperature: LLM temperature (0.7-0.9 for natural variation).
    """
    if mode == "mock":
        return _mock_bid(preview, auction_id, consumer_did, wallet_address)

    try:
        return await _0g_bid(
            preview,
            auction_id=auction_id,
            consumer_did=consumer_did,
            wallet_address=wallet_address,
            ws_uri=ws_uri,
            temperature=temperature,
        )
    except Exception as e:
        logger.error("0G WS pricing failed, falling back to mock", error=str(e))
        return _mock_bid(preview, auction_id, consumer_did, wallet_address)
