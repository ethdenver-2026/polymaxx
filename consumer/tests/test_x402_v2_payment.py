from __future__ import annotations

from signal_consumer.payment import AuctionPaymentRequest, KiteConfig, X402V2Config, process_auction_payment

from .fakes import FakeClient, FakeResponse


def test_x402_v2_payment_includes_network_asset(monkeypatch):
    client = FakeClient([FakeResponse(status_code=200, payload={"ok": True})])
    monkeypatch.setattr("signal_consumer.payment.httpx.Client", lambda timeout: client)
    monkeypatch.setattr(
        "signal_consumer.payment.fetch_siwx_access_token",
        lambda **_: "tok-v2",
    )
    monkeypatch.setattr(
        "signal_consumer.payment._send_erc20_payment_transaction",
        lambda **_: ("0xtxhash", 1_000_000),
    )
    monkeypatch.setattr(
        "signal_consumer.payment._wait_for_transaction_receipt",
        lambda **_: None,
    )

    success = process_auction_payment(
        request=AuctionPaymentRequest(
            auction_id="auc-1",
            consumer_did="did:pkh:eip155:84532:0x0000000000000000000000000000000000000001",
            wallet_address="0x0000000000000000000000000000000000000001",
            producer_wallet_address="0x0000000000000000000000000000000000000002",
            x402_payment_url="https://x402.example/pay",
            bid_amount=1.0,
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
    assert client.calls[0]["json"]["network"] == "base-sepolia"
    assert client.calls[0]["json"]["asset"] == "usdc"
    assert client.calls[0]["json"]["tx_hash"] == "0xtxhash"
    assert client.calls[0]["json"]["token_address"] == "0x036cbd53842c5426634e7929541ec2318f3dcf7e"
    assert client.calls[0]["json"]["token_amount_units"] == 1_000_000
