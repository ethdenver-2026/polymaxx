"""FastAPI server exposing websocket signal stream."""

from __future__ import annotations

import hashlib
import os
import secrets
import time
import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from eth_account import Account
from eth_account.messages import encode_defunct
from signal_schema.addressing import normalize_evm_address

from .main import run_once
from .publishing.websocket_signal_broadcaster import broadcaster as _default_broadcaster
from signal_schema import ProducerSignal

if TYPE_CHECKING:
    from .publishing.websocket_signal_broadcaster import SignalBroadcaster

logger = structlog.get_logger()
app = FastAPI(title="Signal Producer WebSocket Server", version="0.1.0")

# The active broadcaster — defaults to the module-level singleton but can be
# replaced by the orchestrator's broadcaster (which has reputation tracking).
_active_broadcaster: SignalBroadcaster = _default_broadcaster


def set_broadcaster(b: SignalBroadcaster) -> None:
    """Replace the active broadcaster (called by orchestrator on startup)."""
    global _active_broadcaster
    _active_broadcaster = b
    logger.info("WebSocket server broadcaster replaced by orchestrator instance")


_SIWX_CHALLENGES: dict[str, dict[str, str | float]] = {}
_SIWX_TOKENS: dict[str, dict[str, str | float]] = {}
_CONSUMED_TX_HASHES: dict[str, float] = {}
_PAYMENT_REPLAY_LOCK = asyncio.Lock()
_SIWX_CHALLENGE_TTL_SECONDS = float(os.getenv("PRODUCER_SIWX_CHALLENGE_TTL_SECONDS", "120"))
_SIWX_TOKEN_TTL_SECONDS = float(os.getenv("PRODUCER_SIWX_TOKEN_TTL_SECONDS", "600"))
_DEBUG_ENDPOINTS_ENABLED = os.getenv("DEBUG_ENDPOINTS_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class SiwxChallengeRequest(BaseModel):
    consumer_did: str
    wallet_address: str
    app_id: str


class SiwxChallengeResponse(BaseModel):
    challenge: str


class SiwxAuthRequest(BaseModel):
    consumer_did: str
    wallet_address: str
    app_id: str
    challenge: str
    signature: str


class SiwxAuthResponse(BaseModel):
    access_token: str
    expires_in_seconds: int


class X402PaymentRequest(BaseModel):
    auction_id: str
    consumer_did: str
    amount_usdc: float = Field(gt=0)
    network: str
    asset: str
    tx_hash: str
    from_wallet_address: str
    token_address: str
    token_amount_units: int = Field(gt=0)


def _normalize_address(value: str) -> str:
    try:
        return normalize_evm_address(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid wallet address: {value}")


def _purge_expired_state() -> None:
    now = time.time()
    for store in (_SIWX_CHALLENGES, _SIWX_TOKENS):
        expired = [key for key, data in store.items() if float(data.get("expires_at", 0.0)) <= now]
        for key in expired:
            store.pop(key, None)


def _challenge_key(*, consumer_did: str, wallet_address: str, app_id: str) -> str:
    return hashlib.sha256(f"{consumer_did}|{wallet_address}|{app_id}".encode("utf-8")).hexdigest()


def _extract_bearer_token(header_value: str | None) -> str:
    if not header_value:
        raise HTTPException(status_code=401, detail="Authorization header is required")
    prefix = "bearer "
    if not header_value.lower().startswith(prefix):
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    token = header_value[len(prefix):].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token is empty")
    return token


def _normalize_tx_hash(tx_hash: str) -> str:
    tx = tx_hash.strip().lower()
    if not tx.startswith("0x") or len(tx) != 66:
        raise HTTPException(status_code=400, detail=f"Invalid tx_hash format: {tx_hash}")
    return tx


def _rpc_call(*, rpc_url: str, method: str, params: list) -> object:
    resp = httpx.post(
        rpc_url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=15,
    )
    payload = resp.json()
    if "error" in payload:
        raise HTTPException(status_code=400, detail=f"RPC {method} failed: {payload['error']}")
    return payload.get("result")


def _verify_onchain_payment(
    *,
    tx_hash: str,
    from_address: str,
    to_address: str,
    token_address: str,
    min_token_amount_units: int,
) -> None:
    rpc_url = os.getenv("PRODUCER_X402_RPC_URL", "https://base-sepolia-rpc.publicnode.com")
    tx = _rpc_call(rpc_url=rpc_url, method="eth_getTransactionByHash", params=[tx_hash])
    if not tx:
        raise HTTPException(status_code=400, detail=f"Transaction not found: {tx_hash}")
    receipt = _rpc_call(rpc_url=rpc_url, method="eth_getTransactionReceipt", params=[tx_hash])
    if not receipt:
        raise HTTPException(status_code=400, detail=f"Transaction not mined yet: {tx_hash}")
    status = int(str(receipt.get("status", "0x0")), 16)
    if status != 1:
        raise HTTPException(status_code=400, detail=f"Transaction failed on-chain: {tx_hash}")
    tx_from = str(tx.get("from", "")).lower()
    tx_to = str(tx.get("to", "")).lower()
    expected_from = _normalize_address(from_address)
    expected_to = _normalize_address(to_address)
    expected_token = _normalize_address(token_address)
    if tx_from != expected_from:
        raise HTTPException(status_code=400, detail="On-chain from address mismatch")
    if tx_to != expected_token:
        raise HTTPException(status_code=400, detail="On-chain token contract mismatch")
    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    expected_from_topic = f"0x{expected_from.replace('0x', '').rjust(64, '0')}"
    expected_to_topic = f"0x{expected_to.replace('0x', '').rjust(64, '0')}"
    logs = receipt.get("logs") or []
    for log in logs:
        if str(log.get("address", "")).lower() != expected_token:
            continue
        topics = log.get("topics") or []
        if len(topics) < 3:
            continue
        if str(topics[0]).lower() != transfer_topic:
            continue
        if str(topics[1]).lower() != expected_from_topic:
            continue
        if str(topics[2]).lower() != expected_to_topic:
            continue
        value_units = int(str(log.get("data", "0x0")), 16)
        if value_units < min_token_amount_units:
            raise HTTPException(status_code=400, detail="On-chain transfer amount below required amount")
        return
    raise HTTPException(status_code=400, detail="Required ERC20 transfer log not found")


@app.post("/x402/v2/siwx/challenge", response_model=SiwxChallengeResponse)
async def create_siwx_challenge(payload: SiwxChallengeRequest) -> SiwxChallengeResponse:
    _purge_expired_state()
    wallet_address = _normalize_address(payload.wallet_address)
    expected_did = f"did:pkh:eip155:137:{wallet_address}"
    if payload.consumer_did.strip().lower() != expected_did:
        raise HTTPException(
            status_code=400,
            detail=f"consumer_did does not match wallet-bound did:pkh; expected={expected_did}",
        )
    challenge = f"siwx:{secrets.token_urlsafe(24)}"
    key = _challenge_key(
        consumer_did=payload.consumer_did.strip().lower(),
        wallet_address=wallet_address,
        app_id=payload.app_id.strip(),
    )
    _SIWX_CHALLENGES[key] = {
        "challenge": challenge,
        "expires_at": time.time() + _SIWX_CHALLENGE_TTL_SECONDS,
    }
    return SiwxChallengeResponse(challenge=challenge)


@app.post("/x402/v2/siwx/auth", response_model=SiwxAuthResponse)
async def issue_siwx_token(payload: SiwxAuthRequest) -> SiwxAuthResponse:
    _purge_expired_state()
    wallet_address = _normalize_address(payload.wallet_address)
    key = _challenge_key(
        consumer_did=payload.consumer_did.strip().lower(),
        wallet_address=wallet_address,
        app_id=payload.app_id.strip(),
    )
    challenge_state = _SIWX_CHALLENGES.get(key)
    if not challenge_state:
        raise HTTPException(status_code=401, detail="No challenge found for consumer/app")
    expected_challenge = str(challenge_state.get("challenge", ""))
    if payload.challenge != expected_challenge:
        raise HTTPException(status_code=401, detail="Challenge mismatch")
    try:
        recovered = Account.recover_message(
            encode_defunct(text=payload.challenge),
            signature=payload.signature,
        ).lower()
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid signature: {exc}") from exc
    if recovered != wallet_address:
        raise HTTPException(status_code=401, detail="Signature does not match wallet address")
    _SIWX_CHALLENGES.pop(key, None)
    token = secrets.token_urlsafe(32)
    _SIWX_TOKENS[token] = {
        "consumer_did": payload.consumer_did.strip().lower(),
        "wallet_address": wallet_address,
        "app_id": payload.app_id.strip(),
        "expires_at": time.time() + _SIWX_TOKEN_TTL_SECONDS,
    }
    return SiwxAuthResponse(access_token=token, expires_in_seconds=int(_SIWX_TOKEN_TTL_SECONDS))


@app.post("/x402/v2/payment")
async def process_x402_v2_payment(
    payload: X402PaymentRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, str | bool]:
    _purge_expired_state()
    token = _extract_bearer_token(authorization)
    token_state = _SIWX_TOKENS.get(token)
    if not token_state:
        raise HTTPException(status_code=401, detail="Invalid or expired SIWx token")
    if str(token_state.get("consumer_did", "")) != payload.consumer_did.strip().lower():
        raise HTTPException(status_code=403, detail="Token consumer mismatch")
    token_wallet = str(token_state.get("wallet_address", ""))
    producer_wallet = (
        os.getenv("PRODUCER_WALLET_ADDRESS", "") or os.getenv("POLYMARKET_WALLET_ADDRESS", "")
    ).strip()
    if not producer_wallet:
        raise HTTPException(status_code=500, detail="Producer wallet address is not configured")
    expected_token_address = os.getenv(
        "PRODUCER_X402_TOKEN_ADDRESS",
        "0x036cbd53842c5426634e7929541ec2318f3dcf7e",
    )
    if _normalize_address(payload.token_address) != _normalize_address(expected_token_address):
        raise HTTPException(status_code=400, detail="Token contract does not match producer configuration")
    normalized_tx_hash = _normalize_tx_hash(payload.tx_hash)
    async with _PAYMENT_REPLAY_LOCK:
        if normalized_tx_hash in _CONSUMED_TX_HASHES:
            raise HTTPException(status_code=409, detail=f"Replay detected: tx_hash already consumed {normalized_tx_hash}")
        _verify_onchain_payment(
            tx_hash=normalized_tx_hash,
            from_address=payload.from_wallet_address or token_wallet,
            to_address=producer_wallet,
            token_address=payload.token_address,
            min_token_amount_units=payload.token_amount_units,
        )
        accepted = _active_broadcaster.notify_payment_result(
            auction_id=payload.auction_id,
            consumer_did=payload.consumer_did,
            success=True,
        )
        if not accepted:
            raise HTTPException(status_code=409, detail="No pending payment waiter for consumer/auction")
        _CONSUMED_TX_HASHES[normalized_tx_hash] = time.time()
        _SIWX_TOKENS.pop(token, None)
    logger.info(
        "Producer x402_v2 payment accepted",
        auction_id=payload.auction_id,
        consumer_did=payload.consumer_did,
        amount_usdc=payload.amount_usdc,
        network=payload.network,
        asset=payload.asset,
        tx_hash=normalized_tx_hash,
    )
    return {"accepted": True, "tx_hash": normalized_tx_hash}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/run-once")
async def run_cycle(cities: str | None = None) -> dict:
    try:
        city_list = [c.strip() for c in cities.split(",")] if cities else None
        signals = await run_once(cities=city_list, broadcast_signals=True)
        return {"signals_found": len(signals)}
    except Exception as exc:
        logger.exception("run-once failed", error=str(exc), cities=cities)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/debug/broadcast-test-signal")
async def broadcast_test_signal() -> dict[str, str]:
    """Broadcast a deterministic signal to exercise auction/payment E2E locally."""
    if not _DEBUG_ENDPOINTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")
    now = datetime.now(UTC)
    signal = ProducerSignal(
        signal_type="weather",
        model_probability=0.96,
        confidence=0.95,
        forecast_source="open_meteo",
        forecast_time=now.isoformat(),
        metadata={
            "city": "nyc",
            "target_date": now.date().isoformat(),
            "ensemble_mean": 47.0,
            "ensemble_std": 1.8,
            "members_in_range": 20,
        },
        exchanges=[
            {
                "exchange": "polymarket",
                "event_id": "debug-event",
                "token_id": "debug-token",
                "side": "yes",
                "market_description": "Debug market for x402_v2 payment E2E",
                "resolution_source": "https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA",
                "market_price": 0.06,
                "edge": 0.90,
                "price_timestamp": now.isoformat(),
            }
        ],
    )
    await _active_broadcaster.broadcast_producer_signal(signal)
    return {"status": "broadcasted"}
@app.websocket("/ws/signals")
async def signals_websocket(websocket: WebSocket) -> None:
    consumer_did = websocket.query_params.get("consumer_did") or f"anon-signal-{id(websocket)}"
    await _active_broadcaster.connect(websocket, consumer_did=consumer_did)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await _active_broadcaster.disconnect(consumer_did=consumer_did)
    except Exception as exc:
        logger.exception("websocket connection error", error=str(exc))
        await _active_broadcaster.disconnect(consumer_did=consumer_did)


@app.websocket("/ws/bids")
async def bids_websocket(websocket: WebSocket) -> None:
    consumer_did = websocket.query_params.get("consumer_did") or f"anon-bid-{id(websocket)}"
    await _active_broadcaster.connect_bid(websocket, consumer_did=consumer_did)
    try:
        while True:
            payload = await websocket.receive_json()
            await _active_broadcaster.handle_bid_payload(payload, consumer_did=consumer_did)
    except WebSocketDisconnect:
        await _active_broadcaster.disconnect_bid(consumer_did=consumer_did)
    except Exception as exc:
        logger.exception("bid websocket connection error", error=str(exc), consumer_did=consumer_did)
        await _active_broadcaster.disconnect_bid(consumer_did=consumer_did)


def run_signal_server(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Run the producer websocket FastAPI server."""
    import uvicorn

    logger.info("Starting websocket server", host=host, port=port)
    uvicorn.run("signal_producer.ws_server:app", host=host, port=port, log_level="info")
