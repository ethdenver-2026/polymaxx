from __future__ import annotations

import pytest

from signal_consumer.kite_payment import process_auction_payment


class _FakeResponse:
    def __init__(self, *, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, *, json: dict, headers: dict):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def test_process_auction_payment_success(monkeypatch):
    client = _FakeClient(
        [
            _FakeResponse(status_code=200, payload={"session_token": "token-1"}),
            _FakeResponse(status_code=200, payload={"ok": True}),
        ]
    )
    monkeypatch.setattr("signal_consumer.kite_payment.httpx.Client", lambda timeout: client)
    success = process_auction_payment(
        auction_id="auction-1",
        consumer_did="did:kite:consumer/default",
        x402_payment_url="https://x402.dev.gokite.ai/api/weather",
        bid_amount=2.0,
        kite_session_url="https://kite.example/session",
        kite_api_key="kite-key",
        timeout_seconds=5.0,
    )
    assert success is True
    assert len(client.calls) == 2


def test_process_auction_payment_fails_without_session_token(monkeypatch):
    client = _FakeClient([_FakeResponse(status_code=200, payload={"access_token": "not-accepted"})])
    monkeypatch.setattr("signal_consumer.kite_payment.httpx.Client", lambda timeout: client)
    with pytest.raises(RuntimeError, match="session_token"):
        process_auction_payment(
            auction_id="auction-1",
            consumer_did="did:kite:consumer/default",
            x402_payment_url="https://x402.dev.gokite.ai/api/weather",
            bid_amount=2.0,
            kite_session_url="https://kite.example/session",
            kite_api_key="kite-key",
            timeout_seconds=5.0,
        )
