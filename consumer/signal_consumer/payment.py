"""Kite session + x402 payment execution."""

from __future__ import annotations

import httpx
import structlog
from eth_account import Account
from eth_utils import to_checksum_address

from .siwx_auth import fetch_siwx_access_token

logger = structlog.get_logger()


def process_auction_payment(
    *,
    auction_id: str,
    consumer_did: str,
    wallet_address: str,
    producer_wallet_address: str,
    x402_payment_url: str,
    bid_amount: float,
    x402_mode: str,
    kite_session_url: str,
    kite_api_key: str,
    x402_v2_network: str,
    x402_v2_asset: str,
    x402_v2_chain_id: int,
    x402_v2_rpc_url: str,
    x402_v2_token_address: str,
    x402_v2_token_decimals: int,
    siwx_challenge_url: str = "",
    siwx_auth_url: str = "",
    siwx_app_id: str = "",
    siwx_wallet_private_key: str = "",
    timeout_seconds: float,
) -> bool:
    if x402_mode == "kite":
        return _process_kite_payment(
            auction_id=auction_id,
            consumer_did=consumer_did,
            x402_payment_url=x402_payment_url,
            bid_amount=bid_amount,
            kite_session_url=kite_session_url,
            kite_api_key=kite_api_key,
            timeout_seconds=timeout_seconds,
        )
    if x402_mode == "x402_v2":
        return _process_x402_v2_payment(
            auction_id=auction_id,
            consumer_did=consumer_did,
            wallet_address=wallet_address,
            x402_payment_url=x402_payment_url,
            bid_amount=bid_amount,
            x402_v2_network=x402_v2_network,
            x402_v2_asset=x402_v2_asset,
            x402_v2_chain_id=x402_v2_chain_id,
            x402_v2_rpc_url=x402_v2_rpc_url,
            x402_v2_token_address=x402_v2_token_address,
            x402_v2_token_decimals=x402_v2_token_decimals,
            siwx_challenge_url=siwx_challenge_url,
            siwx_auth_url=siwx_auth_url,
            siwx_app_id=siwx_app_id,
            siwx_wallet_private_key=siwx_wallet_private_key,
            producer_wallet_address=producer_wallet_address,
            timeout_seconds=timeout_seconds,
        )
    raise RuntimeError(f"Unsupported x402 mode: {x402_mode}")


def _process_kite_payment(
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


def _process_x402_v2_payment(
    *,
    auction_id: str,
    consumer_did: str,
    wallet_address: str,
    x402_payment_url: str,
    bid_amount: float,
    x402_v2_network: str,
    x402_v2_asset: str,
    x402_v2_chain_id: int,
    x402_v2_rpc_url: str,
    x402_v2_token_address: str,
    x402_v2_token_decimals: int,
    siwx_challenge_url: str,
    siwx_auth_url: str,
    siwx_app_id: str,
    siwx_wallet_private_key: str,
    producer_wallet_address: str,
    timeout_seconds: float,
) -> bool:
    if not x402_payment_url:
        raise RuntimeError("AuctionWinNotice missing x402_payment_url")
    if bid_amount <= 0:
        raise RuntimeError(f"Invalid bid amount for payment execution: {bid_amount}")
    if not producer_wallet_address:
        raise RuntimeError("AuctionWinNotice missing producer_wallet_address")
    token = fetch_siwx_access_token(
        consumer_did=consumer_did,
        wallet_address=wallet_address,
        siwx_challenge_url=siwx_challenge_url,
        siwx_auth_url=siwx_auth_url,
        siwx_app_id=siwx_app_id,
        siwx_wallet_private_key=siwx_wallet_private_key,
        timeout_seconds=timeout_seconds,
    )
    tx_hash, token_amount_units = _send_erc20_payment_transaction(
        chain_id=x402_v2_chain_id,
        rpc_url=x402_v2_rpc_url,
        private_key=siwx_wallet_private_key,
        from_address=wallet_address,
        to_address=producer_wallet_address,
        bid_amount_usdc=bid_amount,
        token_address=x402_v2_token_address,
        token_decimals=x402_v2_token_decimals,
        timeout_seconds=timeout_seconds,
    )
    logger.info(
        "Starting x402 v2 payment flow",
        auction_id=auction_id,
        consumer_did=consumer_did,
        payment_url=x402_payment_url,
        bid_amount=bid_amount,
        network=x402_v2_network,
        asset=x402_v2_asset,
        tx_hash=tx_hash,
        token_amount_units=token_amount_units,
    )
    with httpx.Client(timeout=timeout_seconds) as client:
        payment_resp = client.post(
            x402_payment_url,
            json={
                "auction_id": auction_id,
                "consumer_did": consumer_did,
                "amount_usdc": bid_amount,
                "network": x402_v2_network,
                "asset": x402_v2_asset,
                "tx_hash": tx_hash,
                "from_wallet_address": wallet_address,
                "token_address": x402_v2_token_address,
                "token_amount_units": token_amount_units,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if payment_resp.status_code >= 400:
            logger.error(
                "x402 v2 payment request failed",
                auction_id=auction_id,
                consumer_did=consumer_did,
                status_code=payment_resp.status_code,
                body=payment_resp.text,
            )
            return False
        logger.info(
            "x402 v2 payment completed",
            auction_id=auction_id,
            consumer_did=consumer_did,
            status_code=payment_resp.status_code,
            tx_hash=tx_hash,
        )
        return True


def _normalize_address(address: str) -> str:
    normalized = address.strip().lower()
    if not normalized.startswith("0x") or len(normalized) != 42:
        raise RuntimeError(f"Invalid address: {address}")
    return normalized


def _rpc_call(*, rpc_url: str, method: str, params: list, timeout_seconds: float) -> object:
    resp = httpx.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=timeout_seconds,
    )
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"RPC {method} failed: {payload['error']}")
    return payload.get("result")


def _send_erc20_payment_transaction(
    *,
    chain_id: int,
    rpc_url: str,
    private_key: str,
    from_address: str,
    to_address: str,
    bid_amount_usdc: float,
    token_address: str,
    token_decimals: int,
    timeout_seconds: float,
) -> tuple[str, int]:
    if chain_id <= 0:
        raise RuntimeError(f"Invalid chain id for x402_v2: {chain_id}")
    if not rpc_url:
        raise RuntimeError("X402_V2_RPC_URL is required for on-chain x402_v2 settlement")
    if token_decimals < 0:
        raise RuntimeError(f"Invalid X402_V2_TOKEN_DECIMALS: {token_decimals}")
    if not token_address:
        raise RuntimeError("X402_V2_TOKEN_ADDRESS is required for on-chain x402_v2 settlement")
    from_addr = _normalize_address(from_address)
    to_addr = _normalize_address(to_address)
    token_addr = _normalize_address(token_address)

    nonce_hex = _rpc_call(
        rpc_url=rpc_url,
        method="eth_getTransactionCount",
        params=[from_addr, "pending"],
        timeout_seconds=timeout_seconds,
    )
    gas_price_hex = _rpc_call(
        rpc_url=rpc_url,
        method="eth_gasPrice",
        params=[],
        timeout_seconds=timeout_seconds,
    )
    nonce = int(str(nonce_hex), 16)
    gas_price = int(str(gas_price_hex), 16)
    token_amount_units = max(1, int(round(bid_amount_usdc * (10**token_decimals))))
    selector = "a9059cbb"
    to_arg = to_addr.replace("0x", "").rjust(64, "0")
    amount_arg = hex(token_amount_units)[2:].rjust(64, "0")
    data = f"0x{selector}{to_arg}{amount_arg}"
    tx = {
        "nonce": nonce,
        "to": to_checksum_address(token_addr),
        "value": 0,
        "data": data,
        "gas": 80_000,
        "gasPrice": gas_price,
        "chainId": chain_id,
    }
    signed = Account.sign_transaction(tx, private_key=private_key)
    tx_hash = _rpc_call(
        rpc_url=rpc_url,
        method="eth_sendRawTransaction",
        params=[f"0x{signed.raw_transaction.hex()}"],
        timeout_seconds=timeout_seconds,
    )
    tx_hash_str = str(tx_hash)
    logger.info(
        "Submitted on-chain x402_v2 token transfer",
        from_address=from_addr,
        to_address=to_addr,
        token_address=token_addr,
        token_amount_units=token_amount_units,
        chain_id=chain_id,
        tx_hash=tx_hash_str,
    )
    return tx_hash_str, token_amount_units
