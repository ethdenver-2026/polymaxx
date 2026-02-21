from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct

from signal_consumer.siwx_auth import fetch_siwx_access_token

from .fakes import FakeClient, FakeResponse


def test_fetch_siwx_access_token_signs_challenge(monkeypatch):
    acct = Account.create()
    challenge = "sign-this"
    client = FakeClient(
        [
            FakeResponse(status_code=200, payload={"challenge": challenge}),
            FakeResponse(status_code=200, payload={"access_token": "tok-1"}),
        ]
    )
    monkeypatch.setattr("signal_consumer.siwx_auth.httpx.Client", lambda timeout: client)

    token = fetch_siwx_access_token(
        consumer_did=f"did:pkh:eip155:84532:{acct.address.lower()}",
        wallet_address=acct.address.lower(),
        siwx_challenge_url="https://siwx.example/challenge",
        siwx_auth_url="https://siwx.example/auth",
        siwx_app_id="app-1",
        siwx_wallet_private_key=acct.key.hex(),
        timeout_seconds=5.0,
    )
    assert token == "tok-1"
    assert len(client.calls) == 2

    signature_hex = client.calls[1]["json"]["signature"]
    recovered = Account.recover_message(encode_defunct(text=challenge), signature=signature_hex)
    assert recovered.lower() == acct.address.lower()
