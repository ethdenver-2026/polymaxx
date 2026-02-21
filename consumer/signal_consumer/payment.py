"""Kite session + x402 payment execution."""

from __future__ import annotations

import httpx
import time
from dataclasses import dataclass
import structlog
from eth_account import Account
from eth_utils import to_checksum_address

from signal_schema.addressing import normalize_evm_address

from .siwx_auth import fetch_siwx_access_token

logger = structlog.get_logger()


@dataclass(frozen=True)
class AuctionPaymentRequest:
    auction_id: str
    consumer_did: str
    wallet_address: str
    producer_wallet_address: str
    x402_payment_url: str
    bid_amount: float
    x402_mode: str


@dataclass(frozen=True)
class KiteConfig:
    session_url: str
    api_key: str


@dataclass(frozen=True)
class X402V2Config:
    network: str
    asset: str
    chain_id: int
    rpc_url: str
    token_address: str
    token_decimals: int
    siwx_challenge_url: str = ""
    siwx_auth_url: str = ""
    siwx_app_id: str = ""
    siwx_wallet_private_key: str = ""


def process_auction_payment(
    *,
    request: AuctionPaymentRequest,
    kite_config: KiteConfig,
    x402_v2_config: X402V2Config,
    timeout_seconds: float,
) -> bool:
    if request.x402_mode == "kite":
        return _process_kite_payment(
            auction_id=request.auction_id,
            consumer_did=request.consumer_did,
            x402_payment_url=request.x402_payment_url,
            bid_amount=request.bid_amount,
            kite_session_url=kite_config.session_url,
            kite_api_key=kite_config.api_key,
            timeout_seconds=timeout_seconds,
        )
    if request.x402_mode == "x402_v2":
        return _process_x402_v2_payment(
            request=request,
            x402_v2_config=x402_v2_config,
            timeout_seconds=timeout_seconds,
        )
    raise RuntimeError(f"Unsupported x402 mode: {request.x402_mode}")


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
    request: AuctionPaymentRequest,
    x402_v2_config: X402V2Config,
    timeout_seconds: float,
) -> bool:
    if not request.x402_payment_url:
        raise RuntimeError("AuctionWinNotice missing x402_payment_url")
    if request.bid_amount <= 0:
        raise RuntimeError(f"Invalid bid amount for payment execution: {request.bid_amount}")
    if not request.producer_wallet_address:
        raise RuntimeError("AuctionWinNotice missing producer_wallet_address")
    token = fetch_siwx_access_token(
        consumer_did=request.consumer_did,
        wallet_address=request.wallet_address,
        siwx_challenge_url=x402_v2_config.siwx_challenge_url,
        siwx_auth_url=x402_v2_config.siwx_auth_url,
        siwx_app_id=x402_v2_config.siwx_app_id,
        siwx_wallet_private_key=x402_v2_config.siwx_wallet_private_key,
        timeout_seconds=timeout_seconds,
    )
    logger.info(
        "Starting x402 v2 payment flow",
        auction_id=request.auction_id,
        consumer_did=request.consumer_did,
        payment_url=request.x402_payment_url,
        bid_amount=request.bid_amount,
        network=x402_v2_config.network,
        asset=x402_v2_config.asset,
    )
    tx_hash, token_amount_units = _send_erc20_payment_transaction(
        chain_id=x402_v2_config.chain_id,
        rpc_url=x402_v2_config.rpc_url,
        private_key=x402_v2_config.siwx_wallet_private_key,
        from_address=request.wallet_address,
        to_address=request.producer_wallet_address,
        bid_amount_usdc=request.bid_amount,
        token_address=x402_v2_config.token_address,
        token_decimals=x402_v2_config.token_decimals,
        timeout_seconds=timeout_seconds,
    )
    _wait_for_transaction_receipt(
        tx_hash=tx_hash,
        rpc_url=x402_v2_config.rpc_url,
        timeout_seconds=timeout_seconds,
    )
    logger.info(
        "x402 v2 transaction confirmed",
        auction_id=request.auction_id,
        consumer_did=request.consumer_did,
        tx_hash=tx_hash,
        token_amount_units=token_amount_units,
    )
    with httpx.Client(timeout=timeout_seconds) as client:
        payment_resp = client.post(
            request.x402_payment_url,
            json={
                "auction_id": request.auction_id,
                "consumer_did": request.consumer_did,
                "amount_usdc": request.bid_amount,
                "network": x402_v2_config.network,
                "asset": x402_v2_config.asset,
                "tx_hash": tx_hash,
                "from_wallet_address": request.wallet_address,
                "token_address": x402_v2_config.token_address,
                "token_amount_units": token_amount_units,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if payment_resp.status_code >= 400:
            logger.error(
                "x402 v2 payment request failed",
                auction_id=request.auction_id,
                consumer_did=request.consumer_did,
                status_code=payment_resp.status_code,
                body=payment_resp.text,
            )
            return False
        logger.info(
            "x402 v2 payment completed",
            auction_id=request.auction_id,
            consumer_did=request.consumer_did,
            status_code=payment_resp.status_code,
            tx_hash=tx_hash,
        )
        return True


def _normalize_address(address: str) -> str:
    try:
        return normalize_evm_address(address)
    except ValueError as exc:
        raise RuntimeError(f"Invalid address: {address}") from exc


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


def _wait_for_transaction_receipt(
    *,
    tx_hash: str,
    rpc_url: str,
    timeout_seconds: float,
) -> None:
    if timeout_seconds <= 0:
        raise RuntimeError(f"Invalid timeout_seconds for receipt wait: {timeout_seconds}")
    deadline = timeout_seconds
    elapsed = 0.0
    poll_seconds = min(1.0, max(0.2, timeout_seconds / 10))
    while elapsed < deadline:
        receipt = _rpc_call(
            rpc_url=rpc_url,
            method="eth_getTransactionReceipt",
            params=[tx_hash],
            timeout_seconds=timeout_seconds,
        )
        if receipt:
            status = int(str(receipt.get("status", "0x0")), 16)
            if status != 1:
                raise RuntimeError(
                    f"On-chain transaction failed while waiting for receipt: tx_hash={tx_hash} status={status}"
                )
            return
        time.sleep(poll_seconds)
        elapsed += poll_seconds
    raise RuntimeError(
        f"Timed out waiting for transaction receipt: tx_hash={tx_hash} timeout_seconds={timeout_seconds}"
    )
