"""SIWx challenge/auth helpers for wallet-bound x402 v2 sessions."""

from __future__ import annotations

import httpx
import structlog
from eth_account import Account
from eth_account.messages import encode_defunct

logger = structlog.get_logger()


def fetch_siwx_access_token(
    *,
    consumer_did: str,
    wallet_address: str,
    siwx_challenge_url: str,
    siwx_auth_url: str,
    siwx_app_id: str,
    siwx_wallet_private_key: str,
    timeout_seconds: float,
) -> str:
    if not siwx_challenge_url:
        raise RuntimeError("SIWX_CHALLENGE_URL is required for x402_v2 mode")
    if not siwx_auth_url:
        raise RuntimeError("SIWX_AUTH_URL is required for x402_v2 mode")
    if not siwx_app_id:
        raise RuntimeError("SIWX_APP_ID is required for x402_v2 mode")
    if not siwx_wallet_private_key:
        raise RuntimeError("SIWX_WALLET_PRIVATE_KEY is required for x402_v2 mode")

    with httpx.Client(timeout=timeout_seconds) as client:
        challenge_resp = client.post(
            siwx_challenge_url,
            json={
                "consumer_did": consumer_did,
                "wallet_address": wallet_address,
                "app_id": siwx_app_id,
            },
        )
        if challenge_resp.status_code >= 400:
            raise RuntimeError(
                "SIWx challenge request failed: "
                f"status={challenge_resp.status_code} body={challenge_resp.text}"
            )
        challenge_payload = challenge_resp.json()
        challenge = challenge_payload.get("challenge")
        if not challenge:
            raise RuntimeError(
                "SIWx challenge response missing required challenge field: "
                f"{challenge_payload}"
            )

        challenge_message = encode_defunct(text=str(challenge))
        signed = Account.sign_message(challenge_message, private_key=siwx_wallet_private_key)
        signature = signed.signature.hex()
        auth_resp = client.post(
            siwx_auth_url,
            json={
                "consumer_did": consumer_did,
                "wallet_address": wallet_address,
                "app_id": siwx_app_id,
                "challenge": challenge,
                "signature": signature,
            },
        )
        if auth_resp.status_code >= 400:
            raise RuntimeError(
                "SIWx auth request failed: "
                f"status={auth_resp.status_code} body={auth_resp.text}"
            )
        auth_payload = auth_resp.json()
        access_token = auth_payload.get("access_token")
        if not access_token:
            raise RuntimeError(
                "SIWx auth response missing required access_token field: "
                f"{auth_payload}"
            )
        logger.info("Obtained SIWx access token", consumer_did=consumer_did)
        return str(access_token)
