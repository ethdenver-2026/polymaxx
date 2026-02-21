from __future__ import annotations

import pytest

from signal_consumer.payment import AuctionPaymentRequest, KiteConfig, X402V2Config, process_auction_payment

from .fakes import FakeClient, FakeResponse


def test_process_auction_payment_success(monkeypatch):
    client = FakeClient(
        [
            FakeResponse(status_code=200, payload={"session_token": "token-1"}),
            FakeResponse(status_code=200, payload={"ok": True}),
        ]
    )
    monkeypatch.setattr("signal_consumer.payment.httpx.Client", lambda timeout: client)
    success = process_auction_payment(
        request=AuctionPaymentRequest(
            auction_id="auction-1",
            consumer_did="did:kite:consumer/default",
            wallet_address="0xabc",
            producer_wallet_address="0xdef",
            x402_payment_url="https://x402.dev.gokite.ai/api/weather",
            bid_amount=2.0,
            x402_mode="kite",
        ),
        kite_config=KiteConfig(
            session_url="https://kite.example/session",
            api_key="kite-key",
        ),
        x402_v2_config=X402V2Config(
            network="base-sepolia",
            asset="usdc",
            chain_id=84532,
            rpc_url="https://base-sepolia-rpc.publicnode.com",
            token_address="0x036cbd53842c5426634e7929541ec2318f3dcf7e",
            token_decimals=6,
        ),
        timeout_seconds=5.0,
    )
    assert success is True
    assert len(client.calls) == 2


def test_process_auction_payment_fails_without_session_token(monkeypatch):
    client = FakeClient([FakeResponse(status_code=200, payload={"access_token": "not-accepted"})])
    monkeypatch.setattr("signal_consumer.payment.httpx.Client", lambda timeout: client)
    with pytest.raises(RuntimeError, match="session_token"):
        process_auction_payment(
            request=AuctionPaymentRequest(
                auction_id="auction-1",
                consumer_did="did:kite:consumer/default",
                wallet_address="0xabc",
                producer_wallet_address="0xdef",
                x402_payment_url="https://x402.dev.gokite.ai/api/weather",
                bid_amount=2.0,
                x402_mode="kite",
            ),
            kite_config=KiteConfig(
                session_url="https://kite.example/session",
                api_key="kite-key",
            ),
            x402_v2_config=X402V2Config(
                network="base-sepolia",
                asset="usdc",
                chain_id=84532,
                rpc_url="https://base-sepolia-rpc.publicnode.com",
                token_address="0x036cbd53842c5426634e7929541ec2318f3dcf7e",
                token_decimals=6,
            ),
            timeout_seconds=5.0,
        )


def test_process_auction_payment_x402_v2_success(monkeypatch):
    client = FakeClient([FakeResponse(status_code=200, payload={"ok": True})])
    monkeypatch.setattr("signal_consumer.payment.httpx.Client", lambda timeout: client)
    monkeypatch.setattr(
        "signal_consumer.payment.fetch_siwx_access_token",
        lambda **_: "siwx-token-1",
    )
    monkeypatch.setattr(
        "signal_consumer.payment._send_erc20_payment_transaction",
        lambda **_: ("0xtest", 1_250_000),
    )
    monkeypatch.setattr(
        "signal_consumer.payment._wait_for_transaction_receipt",
        lambda **_: None,
    )
    success = process_auction_payment(
        request=AuctionPaymentRequest(
            auction_id="auction-2",
            consumer_did="did:pkh:eip155:84532:0xabc",
            wallet_address="0xabc",
            producer_wallet_address="0xdef",
            x402_payment_url="https://x402.example/pay",
            bid_amount=1.25,
            x402_mode="x402_v2",
        ),
        kite_config=KiteConfig(session_url="", api_key=""),
        x402_v2_config=X402V2Config(
            network="base-sepolia",
            asset="usdc",
            chain_id=84532,
            rpc_url="https://base-sepolia-rpc.publicnode.com",
            token_address="0x036cbd53842c5426634e7929541ec2318f3dcf7e",
            token_decimals=6,
            siwx_challenge_url="https://siwx.example/challenge",
            siwx_auth_url="https://siwx.example/auth",
            siwx_app_id="app-1",
            siwx_wallet_private_key="0x123",
        ),
        timeout_seconds=5.0,
    )
    assert success is True
    assert len(client.calls) == 1
    assert client.calls[0]["headers"]["Authorization"] == "Bearer siwx-token-1"


def test_process_auction_payment_rejects_unknown_mode():
    with pytest.raises(RuntimeError, match="Unsupported x402 mode"):
        process_auction_payment(
            request=AuctionPaymentRequest(
                auction_id="auction-3",
                consumer_did="did:pkh:eip155:84532:0xabc",
                wallet_address="0xabc",
                producer_wallet_address="0xdef",
                x402_payment_url="https://x402.example/pay",
                bid_amount=1.25,
                x402_mode="bad-mode",
            ),
            kite_config=KiteConfig(session_url="", api_key=""),
            x402_v2_config=X402V2Config(
                network="base-sepolia",
                asset="usdc",
                chain_id=84532,
                rpc_url="https://base-sepolia-rpc.publicnode.com",
                token_address="0x036cbd53842c5426634e7929541ec2318f3dcf7e",
                token_decimals=6,
            ),
            timeout_seconds=5.0,
        )
