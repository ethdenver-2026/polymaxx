from __future__ import annotations

import json

from signal_consumer import db as db_module


def test_log_signal_persists_extended_metadata(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    signal_data = {
        "token_id": "tok-1",
        "created_at": "2026-02-19T12:00:00+00:00",
        "published_at": "2026-02-19T12:00:05+00:00",
        "metadata_json": '{"forecast_horizon_hours":12}',
    }
    response = {
        "action": "executed",
        "status": "live",
        "signal_price": 0.5,
        "live_price": 0.52,
        "signal_edge": 0.1,
        "live_edge": 0.08,
        "order_id": "ord-1",
        "errors": [],
        "strategy_reasons": ["ok"],
        "balance_available_usdc": 30.0,
        "position_size_usd": 3.5,
        "horizon_hours": 12.0,
    }

    db_module.log_signal(signal_data, response)
    rows = db_module.get_signals(limit=10)
    assert len(rows) == 1
    row = rows[0]
    assert row["decision_status"] == "live"
    assert row["strategy_reasons"] == ["ok"]
    assert row["balance_available_usdc"] == 30.0
    assert row["chosen_position_usd"] == 3.5
    assert row["horizon_hours"] == 12.0
    assert row["source_created_at"] == "2026-02-19T12:00:00+00:00"
    assert row["source_published_at"] == "2026-02-19T12:00:05+00:00"
    assert json.loads(row["metadata_json"])["forecast_horizon_hours"] == 12


def test_log_signal_notifies_sse_subscribers(tmp_path, monkeypatch):
    db_path = tmp_path / "consumer_signals.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    q = db_module.subscribe()
    try:
        db_module.log_signal({"token_id": "tok-2"}, {"action": "skipped", "status": "paper"})
        event = q.get(timeout=1)
        assert event["action"] == "skipped"
        assert event["token_id"] == "tok-2"
        assert event["status"] == "paper"
    finally:
        db_module.unsubscribe(q)
