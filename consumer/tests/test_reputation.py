from __future__ import annotations

import pytest

from signal_consumer import db as db_module


def test_derive_consumer_did_pkh_normalizes_address():
    did = db_module.derive_consumer_did_pkh(
        chain_id=84532,
        wallet_address="0xAbCdefABCDEFabcdefABCDEFabcdefABCDEFabCD",
    )
    assert did == "did:pkh:eip155:84532:0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"


def test_validate_consumer_did_wallet_binding_rejects_mismatch():
    with pytest.raises(RuntimeError, match="does not match wallet-bound did:pkh"):
        db_module.validate_consumer_did_wallet_binding(
            consumer_did="did:pkh:eip155:84532:0x1111111111111111111111111111111111111111",
            wallet_address="0x2222222222222222222222222222222222222222",
            chain_id=84532,
        )


def test_consumer_negative_reputation_threshold(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "_DB_INITIALIZED", False)
    did = "did:pkh:eip155:84532:0xabcdefabcdefabcdefabcdefabcdefabcdefabcd"
    for idx in range(5):
        db_module.record_consumer_payment_failure(
            consumer_did=did,
            auction_id=f"auc-{idx}",
            reason="PAYMENT_FAILED",
        )
    score = db_module.get_consumer_reputation(did)
    assert score["negative_reputation"] == 5
    assert db_module.is_consumer_reputation_sufficient(did, threshold=5) is False
