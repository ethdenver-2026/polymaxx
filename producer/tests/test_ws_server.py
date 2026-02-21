"""Smoke tests for websocket signal preview delivery."""

from fastapi.testclient import TestClient
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
import time

import signal_producer.ws_server as ws_server
from signal_schema import ProducerSignal, WeatherMetadata, PolymarketInfo


def test_consumer_receives_canonical_producer_signal_payload(monkeypatch):
    """Consumer websocket receives SignalPreviewMessage payload."""

    async def fake_run_once(cities=None, broadcast_signals=False):
        signal = ProducerSignal(
            signal_type="weather",
            model_probability=0.7,
            confidence=0.8,
            forecast_source="open_meteo",
            forecast_time="2026-02-20T00:00:00",
            metadata=WeatherMetadata(
                city="nyc",
                target_date="2026-02-20",
                ensemble_mean=45.5,
                ensemble_std=2.3,
                members_in_range=12,
            ),
            exchanges=[
                PolymarketInfo(
                    exchange="polymarket",
                    event_id="event-123",
                    event_title="Highest temperature in NYC on February 20?",
                    resolution_source="https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA",
                    market_question="Will the highest temperature be 46-47°F?",
                    market_group_item_title="46-47°F",
                    token_id="token-abc",
                    side="yes",
                    market_price=0.55,
                    edge=0.15,
                    price_timestamp="2026-02-20T01:02:03",
                ),
            ],
        )
        await ws_server._active_broadcaster.broadcast_producer_signal(signal)
        return [signal]

    monkeypatch.setattr(ws_server, "run_once", fake_run_once)

    with TestClient(ws_server.app) as client:
        with client.websocket_connect("/ws/signals?consumer_did=did:kite:test/consumer-a") as websocket:
            response = client.post("/run-once")
            assert response.status_code == 200
            assert response.json()["signals_found"] == 1

            payload = websocket.receive_json()
            assert payload["type"] == "SignalPreviewMessage"
            assert payload["signal_type"] == "weather"
            assert payload["producer_did"].startswith("did:")
            assert payload["auction_id"]
            assert payload["auction_end_utc"]
            assert payload["last_price_paid"] == 0.55
            assert payload["exchanges"][0]["exchange"] == "polymarket"
            assert payload["exchanges"][0]["event_id"] == "event-123"


def test_siwx_challenge_auth_and_payment_endpoint(monkeypatch):
    ws_server._SIWX_CHALLENGES.clear()
    ws_server._SIWX_TOKENS.clear()
    ws_server._CONSUMED_TX_HASHES.clear()
    acct = Account.create()
    consumer_did = f"did:pkh:eip155:137:{acct.address.lower()}"
    app_id = "demo-app"
    auction_id = "auc-123"
    monkeypatch.setattr(
        ws_server._active_broadcaster,
        "notify_payment_result",
        lambda *, auction_id, consumer_did, success: True,
    )
    monkeypatch.setenv("PRODUCER_WALLET_ADDRESS", "0x2222222222222222222222222222222222222222")
    monkeypatch.setenv("PRODUCER_X402_TOKEN_ADDRESS", "0x3333333333333333333333333333333333333333")
    monkeypatch.setattr(ws_server, "_verify_onchain_payment", lambda **_: None)
    with TestClient(ws_server.app) as client:
        challenge_resp = client.post(
            "/x402/v2/siwx/challenge",
            json={
                "consumer_did": consumer_did,
                "wallet_address": acct.address.lower(),
                "app_id": app_id,
            },
        )
        assert challenge_resp.status_code == 200
        challenge = challenge_resp.json()["challenge"]
        signature = Account.sign_message(
            encode_defunct(text=challenge),
            private_key=acct.key.hex(),
        ).signature.hex()
        auth_resp = client.post(
            "/x402/v2/siwx/auth",
            json={
                "consumer_did": consumer_did,
                "wallet_address": acct.address.lower(),
                "app_id": app_id,
                "challenge": challenge,
                "signature": signature,
            },
        )
        assert auth_resp.status_code == 200
        access_token = auth_resp.json()["access_token"]

        payment_resp = client.post(
            "/x402/v2/payment",
            json={
                "auction_id": auction_id,
                "consumer_did": consumer_did,
                "amount_usdc": 1.5,
                "network": "base-sepolia",
                "asset": "usdc",
                "tx_hash": "0x" + "a" * 64,
                "from_wallet_address": acct.address.lower(),
                "token_address": "0x3333333333333333333333333333333333333333",
                "token_amount_units": 1_500_000,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert payment_resp.status_code == 200
        assert payment_resp.json() == {"accepted": True, "tx_hash": "0x" + "a" * 64}
        payment_resp_reuse = client.post(
            "/x402/v2/payment",
            json={
                "auction_id": auction_id,
                "consumer_did": consumer_did,
                "amount_usdc": 1.5,
                "network": "base-sepolia",
                "asset": "usdc",
                "tx_hash": "0x" + "a" * 64,
                "from_wallet_address": acct.address.lower(),
                "token_address": "0x3333333333333333333333333333333333333333",
                "token_amount_units": 1_500_000,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert payment_resp_reuse.status_code == 401


def test_x402_payment_rejects_invalid_token(monkeypatch):
    ws_server._SIWX_CHALLENGES.clear()
    ws_server._SIWX_TOKENS.clear()
    ws_server._CONSUMED_TX_HASHES.clear()
    monkeypatch.setattr(
        ws_server._active_broadcaster,
        "notify_payment_result",
        lambda *, auction_id, consumer_did, success: True,
    )
    monkeypatch.setenv("PRODUCER_WALLET_ADDRESS", "0x2222222222222222222222222222222222222222")
    monkeypatch.setenv("PRODUCER_X402_TOKEN_ADDRESS", "0x3333333333333333333333333333333333333333")
    monkeypatch.setattr(ws_server, "_verify_onchain_payment", lambda **_: None)
    with TestClient(ws_server.app) as client:
        resp = client.post(
            "/x402/v2/payment",
            json={
                "auction_id": "auc-1",
                "consumer_did": "did:pkh:eip155:137:0x1111111111111111111111111111111111111111",
                "amount_usdc": 1.0,
                "network": "base-sepolia",
                "asset": "usdc",
                "tx_hash": "0xdeadbeef",
                "from_wallet_address": "0x1111111111111111111111111111111111111111",
                "token_address": "0x3333333333333333333333333333333333333333",
                "token_amount_units": 1_000_000,
            },
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401


def test_x402_payment_rejects_replayed_tx_hash(monkeypatch):
    ws_server._SIWX_CHALLENGES.clear()
    ws_server._SIWX_TOKENS.clear()
    ws_server._CONSUMED_TX_HASHES.clear()
    now = time.time()
    did1 = "did:pkh:eip155:137:0x1111111111111111111111111111111111111111"
    did2 = "did:pkh:eip155:137:0x2222222222222222222222222222222222222222"
    ws_server._SIWX_TOKENS["token-1"] = {
        "consumer_did": did1,
        "wallet_address": "0x1111111111111111111111111111111111111111",
        "app_id": "app",
        "expires_at": now + 600,
    }
    ws_server._SIWX_TOKENS["token-2"] = {
        "consumer_did": did2,
        "wallet_address": "0x2222222222222222222222222222222222222222",
        "app_id": "app",
        "expires_at": now + 600,
    }
    monkeypatch.setenv("PRODUCER_WALLET_ADDRESS", "0x9999999999999999999999999999999999999999")
    monkeypatch.setenv("PRODUCER_X402_TOKEN_ADDRESS", "0x3333333333333333333333333333333333333333")
    monkeypatch.setattr(ws_server, "_verify_onchain_payment", lambda **_: None)
    monkeypatch.setattr(
        ws_server._active_broadcaster,
        "notify_payment_result",
        lambda *, auction_id, consumer_did, success: True,
    )
    tx_hash = "0x" + "a" * 64
    with TestClient(ws_server.app) as client:
        first = client.post(
            "/x402/v2/payment",
            json={
                "auction_id": "auc-1",
                "consumer_did": did1,
                "amount_usdc": 1.0,
                "network": "base-sepolia",
                "asset": "usdc",
                "tx_hash": tx_hash,
                "from_wallet_address": "0x1111111111111111111111111111111111111111",
                "token_address": "0x3333333333333333333333333333333333333333",
                "token_amount_units": 1_000_000,
            },
            headers={"Authorization": "Bearer token-1"},
        )
        assert first.status_code == 200
        second = client.post(
            "/x402/v2/payment",
            json={
                "auction_id": "auc-2",
                "consumer_did": did2,
                "amount_usdc": 1.0,
                "network": "base-sepolia",
                "asset": "usdc",
                "tx_hash": tx_hash,
                "from_wallet_address": "0x2222222222222222222222222222222222222222",
                "token_address": "0x3333333333333333333333333333333333333333",
                "token_amount_units": 1_000_000,
            },
            headers={"Authorization": "Bearer token-2"},
        )
        assert second.status_code == 409
        assert "Replay detected" in second.text


def test_verify_onchain_payment_accepts_matching_transfer_log(monkeypatch):
    tx_hash = "0xabc123"
    token_address = "0x3333333333333333333333333333333333333333"
    from_addr = "0x1111111111111111111111111111111111111111"
    to_addr = "0x2222222222222222222222222222222222222222"
    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    from_topic = f"0x{from_addr.replace('0x', '').rjust(64, '0')}"
    to_topic = f"0x{to_addr.replace('0x', '').rjust(64, '0')}"
    amount_units = 1_500_000

    def fake_rpc_call(*, rpc_url, method, params):
        if method == "eth_getTransactionByHash":
            return {"from": from_addr, "to": token_address, "value": "0x0"}
        if method == "eth_getTransactionReceipt":
            return {
                "status": "0x1",
                "logs": [
                    {
                        "address": token_address,
                        "topics": [transfer_topic, from_topic, to_topic],
                        "data": hex(amount_units),
                    }
                ],
            }
        raise AssertionError(f"unexpected method: {method}")

    monkeypatch.setattr(ws_server, "_rpc_call", fake_rpc_call)
    ws_server._verify_onchain_payment(
        tx_hash=tx_hash,
        from_address=from_addr,
        to_address=to_addr,
        token_address=token_address,
        min_token_amount_units=amount_units,
    )


def test_verify_onchain_payment_rejects_low_transfer_amount(monkeypatch):
    token_address = "0x3333333333333333333333333333333333333333"
    from_addr = "0x1111111111111111111111111111111111111111"
    to_addr = "0x2222222222222222222222222222222222222222"
    transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    from_topic = f"0x{from_addr.replace('0x', '').rjust(64, '0')}"
    to_topic = f"0x{to_addr.replace('0x', '').rjust(64, '0')}"

    def fake_rpc_call(*, rpc_url, method, params):
        if method == "eth_getTransactionByHash":
            return {"from": from_addr, "to": token_address, "value": "0x0"}
        if method == "eth_getTransactionReceipt":
            return {
                "status": "0x1",
                "logs": [
                    {
                        "address": token_address,
                        "topics": [transfer_topic, from_topic, to_topic],
                        "data": hex(10),
                    }
                ],
            }
        raise AssertionError(f"unexpected method: {method}")

    monkeypatch.setattr(ws_server, "_rpc_call", fake_rpc_call)
    with pytest.raises(Exception):
        ws_server._verify_onchain_payment(
            tx_hash="0xabc123",
            from_address=from_addr,
            to_address=to_addr,
            token_address=token_address,
            min_token_amount_units=1_000_000,
        )
