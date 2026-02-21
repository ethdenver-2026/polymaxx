from __future__ import annotations

import json

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
    assert events[0]["auction_id"] == "auc-1"
    assert events[0]["outcome"] == "payment_succeeds"  # latest outcome wins
    assert events[0]["winning_paid_amount"] == 3.25
    assert events[0]["bid_amount"] == 3.25  # merged from first event
