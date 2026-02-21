from __future__ import annotations

import json
import sqlite3

from signal_consumer import db as db_module


def test_log_signal_persists_strategy_checks(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    signal_data = {
        "token_id": "tok-1",
        "model_probability": 0.6,
        "market_price": 0.5,
    }
    strategy_checks = [
        {"name": "can_process", "passed": True, "detail": "Balance $14.20 sufficient", "data": {"balance": 14.2}},
        {"name": "should_process", "passed": True, "detail": "Edge 10.0% >= 8.0%", "data": {"live_edge": 0.10}},
    ]
    response = {
        "action": "executed",
        "status": "live",
        "signal_price": 0.5,
        "live_price": 0.52,
        "signal_edge": 0.1,
        "live_edge": 0.08,
        "order_id": "ord-1",
        "errors": [],
        "strategy_checks": strategy_checks,
    }

    db_module.log_signal(signal_data, response)
    rows = db_module.get_signals(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "executed"
    assert row["signal_price"] == 0.5
    assert row["live_price"] == 0.52
    assert row["signal_edge"] == 0.1
    assert row["live_edge"] == 0.08
    assert row["order_id"] == "ord-1"
    assert row["strategy_checks"] is not None
    assert len(row["strategy_checks"]) == 2
    assert row["strategy_checks"][0]["name"] == "can_process"
    assert row["strategy_checks"][0]["passed"] is True
    assert row["strategy_checks"][1]["name"] == "should_process"


def test_log_signal_notifies_sse_subscribers(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "_DB_INITIALIZED", False)
    q = db_module.subscribe()
    try:
        db_module.log_signal({"token_id": "tok-2"}, {"action": "skipped", "status": "paper"})
        event = q.get(timeout=1)
        assert event["action"] == "skipped"
        assert event["token_id"] == "tok-2"
        assert event["status"] == "paper"
    finally:
        db_module.unsubscribe(q)


def test_log_and_fetch_auction_events(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "_DB_INITIALIZED", False)

    db_module.log_auction_event(
        auction_id="auc-1",
        consumer_did="did:kite:test/consumer-a",
        producer_did="did:kite:test/producer",
        event_id="evt-1",
        bid_amount=3.25,
        auction_end_utc="2026-02-20T10:00:00+00:00",
        outcome="bid_submitted",
        raw_message={"type": "AuctionBidMessage"},
    )
    db_module.log_auction_event(
        auction_id="auc-1",
        consumer_did="did:kite:test/consumer-a",
        outcome="payment_succeeds",
        winner_did="did:kite:test/consumer-a",
        winning_paid_amount=3.25,
        raw_message={"type": "AuctionPaymentStatus", "status": "PAYMENT_SUCCEEDS"},
    )

    events = db_module.get_auction_events(limit=10)
    # get_auction_events collapses multiple events for the same auction_id into one row
    assert len(events) == 1
    assert events[0]["outcome"] == "payment_succeeds"  # Latest outcome
    assert events[0]["winning_paid_amount"] == 3.25
    assert events[0]["auction_id"] == "auc-1"


def test_get_signal_id_for_auction_scoped_by_consumer(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "_DB_INITIALIZED", False)

    aid = "auction-shared"
    sid_a = "sig-consumer-a"
    sid_b = "sig-consumer-b"
    db_module.create_signal_lifecycle(
        signal_id=sid_a,
        auction_id=aid,
        consumer_did="did:pkh:eip155:137:0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        preview_payload={"type": "SignalPreviewMessage", "auction_id": aid},
    )
    db_module.create_signal_lifecycle(
        signal_id=sid_b,
        auction_id=aid,
        consumer_did="did:pkh:eip155:137:0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        preview_payload={"type": "SignalPreviewMessage", "auction_id": aid},
    )

    resolved_a = db_module.get_signal_id_for_auction_id(
        aid,
        consumer_did="did:pkh:eip155:137:0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    resolved_b = db_module.get_signal_id_for_auction_id(
        aid,
        consumer_did="did:pkh:eip155:137:0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )

    assert resolved_a == sid_a
    assert resolved_b == sid_b


def test_update_signal_lifecycle_scoped_by_consumer(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "_DB_INITIALIZED", False)

    aid = "auction-same"
    did_a = "did:pkh:eip155:137:0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    did_b = "did:pkh:eip155:137:0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    db_module.create_signal_lifecycle(
        signal_id="sig-a",
        auction_id=aid,
        consumer_did=did_a,
        preview_payload={"type": "SignalPreviewMessage", "auction_id": aid},
    )
    db_module.create_signal_lifecycle(
        signal_id="sig-b",
        auction_id=aid,
        consumer_did=did_b,
        preview_payload={"type": "SignalPreviewMessage", "auction_id": aid},
    )

    db_module.update_signal_lifecycle(
        auction_id=aid,
        consumer_did=did_a,
        state="bid_submitted",
        action="pending",
        bid_amount=1.23,
    )

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        """
        SELECT signal_id, consumer_did, state, bid_amount
        FROM consumer_signal_log
        WHERE auction_id = ?
        ORDER BY signal_id ASC
        """,
        (aid,),
    ).fetchall()
    conn.close()

    assert len(rows) == 2
    row_a = [r for r in rows if r[0] == "sig-a"][0]
    row_b = [r for r in rows if r[0] == "sig-b"][0]
    assert row_a[1] == did_a
    assert row_a[2] == "bid_submitted"
    assert row_a[3] == 1.23
    assert row_b[1] == did_b
    assert row_b[2] == "preview_received"
    assert row_b[3] is None
