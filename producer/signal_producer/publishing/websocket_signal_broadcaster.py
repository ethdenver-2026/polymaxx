"""In-memory WebSocket signal publisher."""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import structlog
from fastapi import WebSocket

from ..models.models import SignalRecord
from ..reputation import ReputationStore
from signal_schema import (
    AuctionBidRejected,
    ProducerSignal,
    SignalPreviewMessage,
)

logger = structlog.get_logger()


def _json_safe(value: Any) -> Any:
    """Convert dataclass payload values into JSON-serializable values."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


class SignalBroadcaster:
    """Tracks active websocket clients and runs preview/bid auctions."""

    def __init__(self, reputation_store: ReputationStore | None = None) -> None:
        self._signal_connections: dict[str, WebSocket] = {}
        self._bid_connections: dict[str, WebSocket] = {}
        self._connection_lock = asyncio.Lock()
        self._auction_lock = asyncio.Lock()
        self._auctions: dict[str, AuctionState] = {}
        self._payment_waiters: dict[tuple[str, str], asyncio.Future[bool]] = {}
        self._auction_timeout_seconds = float(os.getenv("SIGNAL_AUCTION_TIMEOUT_SECONDS", "15"))
        self._payment_timeout_seconds = float(
            os.getenv("SIGNAL_AUCTION_PAYMENT_TIMEOUT_SECONDS", "20")
        )
        self._producer_did = os.getenv("PRODUCER_DID", "did:kite:producer/default/weather-v1")
        self._producer_wallet_address = (
            os.getenv("PRODUCER_WALLET_ADDRESS", "") or os.getenv("POLYMARKET_WALLET_ADDRESS", "")
        ).strip().lower()
        self._kite_x402_url = os.getenv("PRODUCER_KITE_X402_URL", "https://x402.dev.gokite.ai/api/weather")
        self._x402_mode = os.getenv("PRODUCER_X402_MODE", "x402_v2").strip().lower()
        self._public_base_url = os.getenv("PRODUCER_PUBLIC_BASE_URL", "http://127.0.0.1:8000").strip()
        self._x402_v2_url = os.getenv("PRODUCER_X402_V2_URL", "").strip()
        if self._x402_mode not in {"kite", "x402_v2"}:
            raise RuntimeError(f"Unsupported PRODUCER_X402_MODE: {self._x402_mode}")
        if self._x402_mode == "x402_v2" and not self._x402_v2_url:
            # Self-hosted default endpoint for producer-owned x402_v2 flow.
            self._x402_v2_url = f"{self._public_base_url.rstrip('/')}/x402/v2/payment"
        self._reputation = reputation_store

    async def connect(self, websocket: WebSocket, consumer_did: str) -> None:
        await websocket.accept()
        async with self._connection_lock:
            self._signal_connections[consumer_did] = websocket
        logger.info(
            "Signal websocket client connected",
            consumer_did=consumer_did,
            clients=len(self._signal_connections),
        )

    async def disconnect(self, consumer_did: str) -> None:
        async with self._connection_lock:
            self._signal_connections.pop(consumer_did, None)
        logger.info(
            "Signal websocket client disconnected",
            consumer_did=consumer_did,
            clients=len(self._signal_connections),
        )

    async def connect_bid(self, websocket: WebSocket, consumer_did: str) -> None:
        await websocket.accept()
        async with self._connection_lock:
            self._bid_connections[consumer_did] = websocket
        logger.info(
            "Bid websocket client connected",
            consumer_did=consumer_did,
            clients=len(self._bid_connections),
        )

    async def disconnect_bid(self, consumer_did: str) -> None:
        async with self._connection_lock:
            self._bid_connections.pop(consumer_did, None)
        logger.info(
            "Bid websocket client disconnected",
            consumer_did=consumer_did,
            clients=len(self._bid_connections),
        )

    async def _broadcast_payload(
        self,
        payload: dict[str, Any],
        market_id: str,
        token_id: str,
    ) -> None:
        payload["published_at"] = datetime.now(UTC).isoformat()

        async with self._connection_lock:
            connections = list(self._signal_connections.items())

        if not connections:
            logger.info(
                "No websocket clients connected; signal not delivered",
                market_id=market_id,
                token_id=token_id,
            )
            return

        async def _send(consumer_did: str, websocket: WebSocket) -> Exception | None:
            try:
                await websocket.send_json(payload)
                return None
            except Exception as exc:
                logger.error(
                    "WebSocket send failed",
                    error=str(exc),
                    consumer_did=consumer_did,
                    market_id=market_id,
                    token_id=token_id,
                )
                return exc

        send_results = await asyncio.gather(
            *[_send(consumer_did, websocket) for consumer_did, websocket in connections],
            return_exceptions=False,
        )
        failed = [
            consumer_did
            for (consumer_did, _), result in zip(connections, send_results, strict=False)
            if result is not None
        ]

        if failed:
            async with self._connection_lock:
                for consumer_did in failed:
                    self._signal_connections.pop(consumer_did, None)

        logger.info(
            "Signal broadcast complete",
            recipients=len(connections) - len(failed),
            failed=len(failed),
            market_id=market_id,
            token_id=token_id,
        )

    async def broadcast_signal_record(self, record: SignalRecord) -> None:
        payload = {
            "id": record.id,
            "strategy": record.strategy,
            "market_id": record.market_id,
            "token_id": record.token_id,
            "model_probability": record.model_probability,
            "market_price": record.market_price,
            "edge": record.edge,
            "confidence": record.confidence,
            "decision": record.decision,
            "skip_reason": record.skip_reason,
            "created_at": record.created_at,
            "metadata_json": record.metadata_json,
        }
        await self._broadcast_payload(
            _json_safe(payload),
            market_id=str(record.market_id),
            token_id=str(record.token_id),
        )

    async def broadcast_producer_signal(self, signal: ProducerSignal) -> None:
        """Broadcast a signal preview and start auction lifecycle."""
        if not signal.exchanges:
            raise RuntimeError("Cannot preview signal without exchange payload")

        first_exchange = signal.exchanges[0]
        auction_id = str(uuid4())
        end_time = datetime.now(UTC).timestamp() + self._auction_timeout_seconds
        auction_end_utc = datetime.fromtimestamp(end_time, tz=UTC)

        preview = SignalPreviewMessage(
            signal_type=signal.signal_type,
            producer_did=self._producer_did,
            auction_id=auction_id,
            auction_end_utc=auction_end_utc.isoformat(),
            last_price_paid=float(first_exchange["market_price"]),
            model_probability=signal.model_probability,
            confidence=signal.confidence,
            exchanges=[
                {
                    "exchange": "polymarket",
                    "event_id": first_exchange["event_id"],
                    "edge": float(first_exchange["edge"]),
                    "price_timestamp": str(first_exchange["price_timestamp"]),
                }
            ],
        )
        payload = preview.to_dict()
        payload["type"] = "SignalPreviewMessage"
        payload["version"] = 1
        payload["sent_at"] = datetime.now(UTC).isoformat()

        async with self._connection_lock:
            expected_consumers = set(self._signal_connections.keys())
        async with self._auction_lock:
            self._auctions[auction_id] = AuctionState(
                auction_id=auction_id,
                signal=signal,
                expected_consumers=expected_consumers,
                auction_end_utc=auction_end_utc,
            )

        logger.info(
            "Auction created for signal preview",
            auction_id=auction_id,
            expected_consumers=len(expected_consumers),
            auction_end_utc=auction_end_utc.isoformat(),
            event_id=first_exchange["event_id"],
        )

        await self._broadcast_payload(
            payload,
            market_id=str(first_exchange.get("event_id", "")),
            token_id=str(first_exchange.get("token_id", "")),
        )
        asyncio.create_task(self._close_auction_when_elapsed(auction_id))

    async def handle_bid_payload(self, payload: dict[str, Any], consumer_did: str) -> None:
        """Handle inbound bid/payment websocket payload from a consumer."""
        message_type = payload.get("type")
        if message_type == "AuctionBidMessage":
            await self._handle_auction_bid(payload, consumer_did)
            return
        if message_type == "AuctionPaymentResult":
            await self._handle_payment_result(payload, consumer_did)
            return
        raise RuntimeError(f"Unsupported bid message type: {message_type}")

    async def _handle_auction_bid(self, payload: dict[str, Any], consumer_did: str) -> None:
        auction_id = payload.get("auction_id")
        bid_amount = payload.get("bid_amount")
        if not auction_id or bid_amount is None:
            raise RuntimeError("AuctionBidMessage requires auction_id and bid_amount")

        async with self._auction_lock:
            auction = self._auctions.get(auction_id)
            if auction is None:
                await self._notify_bid_rejected(auction_id, consumer_did, "auction_not_found")
                return
            if auction.closed:
                await self._notify_bid_rejected(auction_id, consumer_did, "auction_already_closed")
                return
            if datetime.now(UTC) > auction.auction_end_utc:
                await self._notify_bid_rejected(auction_id, consumer_did, "auction_elapsed")
                return
            if consumer_did not in auction.expected_consumers:
                await self._notify_bid_rejected(auction_id, consumer_did, "unknown_consumer")
                return
            if self._reputation and self._reputation.is_blacklisted(consumer_did):
                await self._notify_bid_rejected(auction_id, consumer_did, "blacklisted")
                return
            auction.bids[consumer_did] = float(bid_amount)
            auction.responded_consumers.add(consumer_did)
            all_responded = auction.responded_consumers >= auction.expected_consumers

        await self._send_to_bidder(
            consumer_did,
            {
                "type": "AuctionBidAccepted",
                "version": 1,
                "auction_id": auction_id,
                "consumer_did": consumer_did,
                "bid_amount": float(bid_amount),
                "sent_at": datetime.now(UTC).isoformat(),
            },
        )
        logger.info(
            "Auction bid accepted",
            auction_id=auction_id,
            consumer_did=consumer_did,
            bid_amount=float(bid_amount),
            responded=len(auction.responded_consumers),
            expected=len(auction.expected_consumers),
        )

        if all_responded:
            await self._close_auction(auction_id, "all_snapshot_responded")

    async def _handle_payment_result(self, payload: dict[str, Any], consumer_did: str) -> None:
        auction_id = payload.get("auction_id")
        success = payload.get("payment_success")
        if not auction_id or success is None:
            raise RuntimeError("AuctionPaymentResult requires auction_id and payment_success")
        future = self._payment_waiters.get((auction_id, consumer_did))
        if future is None:
            logger.info(
                "Received payment result with no waiter; likely already resolved by HTTP payment endpoint",
                auction_id=auction_id,
                consumer_did=consumer_did,
            )
            return
        if not future.done():
            future.set_result(bool(success))

    def notify_payment_result(self, *, auction_id: str, consumer_did: str, success: bool) -> bool:
        """Resolve an outstanding payment waiter from an internal HTTP endpoint."""
        future = self._payment_waiters.get((auction_id, consumer_did))
        if future is None:
            logger.warning(
                "No payment waiter to resolve",
                auction_id=auction_id,
                consumer_did=consumer_did,
            )
            return False
        if not future.done():
            future.set_result(bool(success))
        return True

    async def _close_auction_when_elapsed(self, auction_id: str) -> None:
        async with self._auction_lock:
            auction = self._auctions.get(auction_id)
            if auction is None or auction.closed:
                return
            wait_seconds = (auction.auction_end_utc - datetime.now(UTC)).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        await self._close_auction(auction_id, "auction_elapsed")

    async def _close_auction(self, auction_id: str, reason: str) -> None:
        async with self._auction_lock:
            auction = self._auctions.get(auction_id)
            if auction is None or auction.closed:
                return
            auction.closed = True
            auction.close_reason = reason

        logger.info(
            "Auction closed",
            auction_id=auction_id,
            reason=reason,
            bids=len(auction.bids),
        )
        asyncio.create_task(self._run_payment_cascade(auction_id))

    async def _run_payment_cascade(self, auction_id: str) -> None:
        async with self._auction_lock:
            auction = self._auctions.get(auction_id)
            if auction is None:
                return
            ordered_bidders = sorted(auction.bids.items(), key=lambda item: item[1], reverse=True)

        for consumer_did, bid_amount in ordered_bidders:
            await self._send_to_bidder(
                consumer_did,
                {
                    "type": "AuctionWinNotice",
                    "version": 1,
                    "auction_id": auction_id,
                    "consumer_did": consumer_did,
                    "bid_amount": bid_amount,
                    "producer_wallet_address": self._producer_wallet_address,
                    "x402_mode": self._x402_mode,
                    "x402_payment_url": (
                        self._x402_v2_url if self._x402_mode == "x402_v2" else self._kite_x402_url
                    ),
                    "payment_timeout_seconds": self._payment_timeout_seconds,
                    "sent_at": datetime.now(UTC).isoformat(),
                },
            )
            success = await self._await_payment_result(auction_id, consumer_did)
            if not success:
                if self._reputation:
                    self._reputation.record_payment_failure(consumer_did)
                await self._send_to_bidder(
                    consumer_did,
                    {
                        "type": "AuctionPaymentStatus",
                        "version": 1,
                        "auction_id": auction_id,
                        "consumer_did": consumer_did,
                        "status": "PAYMENT_FAILED",
                        "sent_at": datetime.now(UTC).isoformat(),
                    },
                )
                continue

            if self._reputation:
                self._reputation.record_payment_success(consumer_did)
            await self._send_to_bidder(
                consumer_did,
                {
                    "type": "AuctionPaymentStatus",
                    "version": 1,
                    "auction_id": auction_id,
                    "consumer_did": consumer_did,
                    "status": "PAYMENT_SUCCEEDS",
                    "sent_at": datetime.now(UTC).isoformat(),
                },
            )
            await self._send_to_bidder(
                consumer_did,
                {
                    "type": "SignalMessage",
                    "version": 1,
                    "auction_id": auction_id,
                    "signal": _json_safe(asdict(auction.signal)),
                    "sent_at": datetime.now(UTC).isoformat(),
                },
            )
            await self._notify_losers(auction_id, winner_did=consumer_did, paid_amount=bid_amount)
            await self._broadcast_auction_result(auction_id, winner_did=consumer_did, paid_amount=bid_amount)
            logger.info(
                "Auction payment succeeded",
                auction_id=auction_id,
                winner_did=consumer_did,
                paid_amount=bid_amount,
            )
            return

        await self._notify_all_no_winner(auction_id)
        await self._broadcast_auction_result(auction_id, winner_did=None, paid_amount=None)
        logger.warning("Auction exhausted without payment success", auction_id=auction_id)

    async def _await_payment_result(self, auction_id: str, consumer_did: str) -> bool:
        key = (auction_id, consumer_did)
        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
        self._payment_waiters[key] = future
        try:
            return await asyncio.wait_for(future, timeout=self._payment_timeout_seconds)
        except TimeoutError:
            logger.error(
                "Timed out waiting for payment result",
                auction_id=auction_id,
                consumer_did=consumer_did,
                timeout_seconds=self._payment_timeout_seconds,
            )
            return False
        finally:
            self._payment_waiters.pop(key, None)

    async def _notify_bid_rejected(self, auction_id: str, consumer_did: str, reason: str) -> None:
        payload = AuctionBidRejected(
            auction_id=auction_id,
            consumer_did=consumer_did,
            reason=reason,
        ).to_dict()
        payload["sent_at"] = datetime.now(UTC).isoformat()
        await self._send_to_bidder(consumer_did, payload)

    async def _notify_losers(self, auction_id: str, winner_did: str, paid_amount: float) -> None:
        async with self._auction_lock:
            auction = self._auctions.get(auction_id)
            if auction is None:
                return
            losers = [consumer_did for consumer_did in auction.bids if consumer_did != winner_did]
        for consumer_did in losers:
            await self._send_to_bidder(
                consumer_did,
                {
                    "type": "AuctionLossNotice",
                    "version": 1,
                    "auction_id": auction_id,
                    "winner_did": winner_did,
                    "paid_amount": paid_amount,
                    "sent_at": datetime.now(UTC).isoformat(),
                },
            )

    async def _notify_all_no_winner(self, auction_id: str) -> None:
        async with self._auction_lock:
            auction = self._auctions.get(auction_id)
            if auction is None:
                return
            consumers = list(auction.bids.keys())
        for consumer_did in consumers:
            await self._send_to_bidder(
                consumer_did,
                {
                    "type": "AuctionNoWinner",
                    "version": 1,
                    "auction_id": auction_id,
                    "reason": "bidder_list_exhausted",
                    "sent_at": datetime.now(UTC).isoformat(),
                },
            )

    async def _broadcast_auction_result(
        self, auction_id: str, winner_did: str | None, paid_amount: float | None
    ) -> None:
        """Broadcast auction outcome to ALL signal-connected clients."""
        payload = {
            "type": "AuctionResultBroadcast",
            "version": 1,
            "auction_id": auction_id,
            "winner_did": winner_did,
            "paid_amount": paid_amount,
            "sent_at": datetime.now(UTC).isoformat(),
        }
        await self._broadcast_payload(payload, market_id=auction_id, token_id="")

    async def _send_to_bidder(self, consumer_did: str, payload: dict[str, Any]) -> None:
        async with self._connection_lock:
            websocket = self._bid_connections.get(consumer_did)
        if websocket is None:
            logger.error(
                "No bid websocket for consumer",
                consumer_did=consumer_did,
                payload_type=payload.get("type"),
            )
            return
        try:
            await websocket.send_json(payload)
        except Exception as exc:
            logger.error(
                "Failed to send bid websocket payload",
                consumer_did=consumer_did,
                payload_type=payload.get("type"),
                error=str(exc),
            )


@dataclass
class AuctionState:
    auction_id: str
    signal: ProducerSignal
    expected_consumers: set[str]
    auction_end_utc: datetime
    bids: dict[str, float] = field(default_factory=dict)
    responded_consumers: set[str] = field(default_factory=set)
    closed: bool = False
    close_reason: str | None = None


broadcaster = SignalBroadcaster()  # Default instance; orchestrator creates its own with reputation
