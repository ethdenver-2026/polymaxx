"""Kite session + x402 payment execution."""

from __future__ import annotations

import httpx
import structlog

logger = structlog.get_logger()


def process_auction_payment(
    *,
    auction_id: str,
    consumer_did: str,
    x402_payment_url: str,
    bid_amount: float,
    kite_session_url: str,
    kite_api_key: str,
    timeout_seconds: float,
) -> bool:
    if not kite_session_url:
        raise RuntimeError("KITE_SESSION_URL is required for x402 payment execution")
    if not kite_api_key:
        raise RuntimeError("KITE_API_KEY is required for x402 payment execution")
    if not x402_payment_url:
        raise RuntimeError("AuctionWinNotice missing x402_payment_url")
    if bid_amount <= 0:
        raise RuntimeError(f"Invalid bid amount for payment execution: {bid_amount}")

    logger.info(
        "Starting Kite x402 payment flow",
        auction_id=auction_id,
        consumer_did=consumer_did,
        payment_url=x402_payment_url,
        bid_amount=bid_amount,
    )
    with httpx.Client(timeout=timeout_seconds) as client:
        session_resp = client.post(
            kite_session_url,
            json={
                "auction_id": auction_id,
                "consumer_did": consumer_did,
                "amount_usdc": bid_amount,
            },
            headers={"Authorization": f"Bearer {kite_api_key}"},
        )
        if session_resp.status_code >= 400:
            raise RuntimeError(
                "Kite session creation failed: "
                f"status={session_resp.status_code} body={session_resp.text}"
            )
        session_payload = session_resp.json()
        session_token = session_payload.get("session_token")
        if not session_token:
            raise RuntimeError(
                "Kite session response missing required session_token field: "
                f"{session_payload}"
            )

        payment_resp = client.post(
            x402_payment_url,
            json={
                "auction_id": auction_id,
                "consumer_did": consumer_did,
                "amount_usdc": bid_amount,
            },
            headers={"Authorization": f"Bearer {session_token}"},
        )
        if payment_resp.status_code >= 400:
            logger.error(
                "x402 payment request failed",
                auction_id=auction_id,
                consumer_did=consumer_did,
                status_code=payment_resp.status_code,
                body=payment_resp.text,
            )
            return False
        logger.info(
            "x402 payment completed",
            auction_id=auction_id,
            consumer_did=consumer_did,
            status_code=payment_resp.status_code,
        )
        return True
