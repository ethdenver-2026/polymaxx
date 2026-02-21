"""Tests for auction smoke DB event utilities."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from signal_producer.auction_smoke import (
    _count_auction_rows,
    _get_recent_auction_events,
    _print_recent_auction_events,
)


def _seed_consumer_auction_log(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE consumer_auction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at REAL NOT NULL,
            auction_id TEXT NOT NULL,
            consumer_did TEXT NOT NULL,
            outcome TEXT NOT NULL,
            winner_did TEXT,
            winning_paid_amount REAL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO consumer_auction_log
            (received_at, auction_id, consumer_did, outcome, winner_did, winning_paid_amount)
        VALUES
            (10.0, 'auction-1', 'did:kite:test/a', 'bid_submitted', NULL, NULL),
            (11.0, 'auction-1', 'did:kite:test/a', 'won_offer', NULL, NULL),
            (12.0, 'auction-1', 'did:kite:test/a', 'payment_failed', NULL, NULL),
            (13.0, 'auction-1', 'did:kite:test/b', 'payment_succeeds', 'did:kite:test/b', 6.0)
        """
    )
    conn.commit()
    conn.close()


def test_get_recent_auction_events_returns_descending_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "consumer_signals.db"
    _seed_consumer_auction_log(db_path)

    events = _get_recent_auction_events(db_path, limit=2)

    assert len(events) == 2
    assert events[0]["outcome"] == "payment_succeeds"
    assert events[1]["outcome"] == "payment_failed"


def test_get_recent_auction_events_missing_table_returns_empty(tmp_path: Path) -> None:
    db_path = tmp_path / "consumer_signals.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE placeholder (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    assert _get_recent_auction_events(db_path, limit=5) == []
    assert _count_auction_rows(db_path) == 0


def test_print_recent_auction_events_outputs_rows(tmp_path: Path, capsys) -> None:
    db_path = tmp_path / "consumer_signals.db"
    _seed_consumer_auction_log(db_path)

    _print_recent_auction_events(db_path, limit=1)
    out = capsys.readouterr().out

    assert "Recent consumer_auction_log events (limit=1):" in out
    assert "outcome=payment_succeeds" in out
