"""WebSocket ingestion from producer signal stream."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode

import structlog
import websockets

from .config import Settings
from .consumer_engine import process_signal_payload
from .db import log_auction_event, log_signal

logger = structlog.get_logger()


def handle_raw_ws_message(message: str, settings: Settings) -> dict:
    """Decode raw websocket JSON, process signal, and persist result."""
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as exc:
        response = {"action": "error", "errors": [f"invalid_json: {exc}"]}
        logger.error("Invalid websocket JSON payload", error=str(exc))
        return response

    try:
        response = process_signal_payload(payload, settings)
    except Exception as exc:
        logger.exception("Signal processing failed", error=str(exc))
        response = {"action": "error", "errors": [f"processing_failed: {exc}"]}

    try:
        log_signal(payload, response)
    except Exception as exc:
        logger.exception("Failed to persist consumer signal log", error=str(exc))

    return response


async def _submit_bid_for_preview(payload: dict, settings: Settings) -> dict:
    auction_id = payload.get("auction_id")
    if not auction_id:
        raise RuntimeError("SignalPreviewMessage missing auction_id")
    producer_did = payload.get("producer_did")
    event_id = None
    exchanges = payload.get("exchanges")
    if isinstance(exchanges, list) and exchanges:
        event_id = exchanges[0].get("event_id")
    bid_url = f"{settings.producer_bid_ws_url}?{urlencode({'consumer_did': settings.consumer_did})}"
    bid_message = {
        "type": "AuctionBidMessage",
        "version": 1,
        "auction_id": auction_id,
        "consumer_did": settings.consumer_did,
        "wallet_address": settings.consumer_wallet_address,
        "bid_amount": settings.consumer_default_bid_amount,
    }
    log_auction_event(
        auction_id=auction_id,
        consumer_did=settings.consumer_did,
        producer_did=producer_did,
        event_id=event_id,
        bid_amount=settings.consumer_default_bid_amount,
        auction_end_utc=payload.get("auction_end_utc"),
        outcome="bid_submitted",
        raw_message=bid_message,
    )
    logger.info(
        "Submitting auction bid",
        auction_id=auction_id,
        consumer_did=settings.consumer_did,
        bid_amount=settings.consumer_default_bid_amount,
    )
    async with websockets.connect(bid_url) as bid_ws:
        await bid_ws.send(json.dumps(bid_message))
        while True:
            raw = await asyncio.wait_for(bid_ws.recv(), timeout=settings.consumer_bid_timeout_seconds)
            bid_response = json.loads(raw)
            response_type = bid_response.get("type")

            if response_type in {"AuctionBidRejected", "AuctionLossNotice", "AuctionNoWinner"}:
                log_auction_event(
                    auction_id=auction_id,
                    consumer_did=settings.consumer_did,
                    producer_did=producer_did,
                    event_id=event_id,
                    bid_amount=settings.consumer_default_bid_amount,
                    outcome=response_type,
                    rejection_reason=bid_response.get("reason"),
                    winner_did=bid_response.get("winner_did"),
                    winning_paid_amount=bid_response.get("paid_amount"),
                    raw_message=bid_response,
                )
                logger.info(
                    "Auction ended without win",
                    auction_id=auction_id,
                    response_type=response_type,
                )
                return {"action": response_type, "errors": []}

            if response_type == "AuctionWinNotice":
                log_auction_event(
                    auction_id=auction_id,
                    consumer_did=settings.consumer_did,
                    producer_did=producer_did,
                    event_id=event_id,
                    bid_amount=bid_response.get("bid_amount"),
                    outcome="won_offer",
                    payment_url=bid_response.get("x402_payment_url"),
                    raw_message=bid_response,
                )
                payment_result = {
                    "type": "AuctionPaymentResult",
                    "version": 1,
                    "auction_id": auction_id,
                    "consumer_did": settings.consumer_did,
                    "payment_success": settings.consumer_payment_auto_succeeds,
                }
                await bid_ws.send(json.dumps(payment_result))
                continue

            if response_type == "AuctionPaymentStatus":
                log_auction_event(
                    auction_id=auction_id,
                    consumer_did=settings.consumer_did,
                    producer_did=producer_did,
                    event_id=event_id,
                    bid_amount=settings.consumer_default_bid_amount,
                    outcome=str(bid_response.get("status", "PAYMENT_UNKNOWN")).lower(),
                    raw_message=bid_response,
                )
                continue

            if response_type == "SignalMessage":
                signal_payload = bid_response.get("signal")
                if not isinstance(signal_payload, dict):
                    raise RuntimeError("SignalMessage missing signal payload")
                response = process_signal_payload(signal_payload, settings)
                log_signal(signal_payload, response)
                return response


async def consume_producer_signals(settings: Settings) -> None:
    """Reconnect loop that consumes producer websocket signals forever."""
    ws_url = settings.producer_ws_url
    reconnect_delay = settings.producer_ws_reconnect_seconds
    logger.info("Starting producer websocket ingestion", ws_url=ws_url)

    while True:
        try:
            signal_url = f"{ws_url}?{urlencode({'consumer_did': settings.consumer_did})}"
            async with websockets.connect(signal_url) as ws:
                logger.info("Connected to producer websocket", ws_url=ws_url)
                async for message in ws:
                    payload = json.loads(message)
                    message_type = payload.get("type")
                    if message_type == "SignalPreviewMessage":
                        await _submit_bid_for_preview(payload, settings)
                        continue
                    if message_type == "SignalMessage":
                        signal_payload = payload.get("signal", {})
                        handle_raw_ws_message(json.dumps(signal_payload), settings)
                        continue
                    handle_raw_ws_message(message, settings)
        except Exception as exc:
            logger.error(
                "Producer websocket disconnected",
                ws_url=ws_url,
                reconnect_seconds=reconnect_delay,
                error=str(exc),
            )
            await asyncio.sleep(reconnect_delay)
