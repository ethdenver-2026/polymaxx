"""
SQLite persistence for consumer signal log.

Stores every signal received by the consumer along with the action taken
(executed, skipped, error) and price/edge details at execution time.
"""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "consumer_signals.db"

# Thread-safe pub/sub for live signal updates.
# Subscribers are queue.Queue instances — one per SSE connection.
_subscribers: list[queue.Queue[dict]] = []
_subscribers_lock = threading.Lock()
_SCHEMA_COLUMNS: dict[str, str] = {
    "source_created_at": "TEXT",
    "source_published_at": "TEXT",
    "decision_status": "TEXT",
    "strategy_reasons_json": "TEXT",
    "balance_available_usdc": "REAL",
    "chosen_position_usd": "REAL",
    "horizon_hours": "REAL",
    "metadata_json": "TEXT",
    "strategy_checks": "TEXT",
}


def subscribe() -> queue.Queue[dict]:
    """Add a subscriber queue. Returns the queue to read from."""
    q: queue.Queue[dict] = queue.Queue(maxsize=64)
    with _subscribers_lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: queue.Queue[dict]) -> None:
    """Remove a subscriber queue."""
    with _subscribers_lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass


def _notify(signal_row: dict) -> None:
    """Push to all subscriber queues (non-blocking, drops if full)."""
    with _subscribers_lock:
        for q in _subscribers:
            try:
                q.put_nowait(signal_row)
            except queue.Full:
                pass


def init_db() -> None:
    """Create the consumer_signal_log table if it doesn't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS consumer_signal_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at REAL    NOT NULL,
            signal_json TEXT    NOT NULL,
            action      TEXT    NOT NULL,
            signal_price REAL,
            live_price   REAL,
            signal_edge  REAL,
            live_edge    REAL,
            order_id    TEXT,
            errors      TEXT
        )
    """)
    # Idempotent migration: add columns that don't exist yet
    existing_cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(consumer_signal_log)").fetchall()
    }
    for name, sql_type in _SCHEMA_COLUMNS.items():
        if name not in existing_cols:
            conn.execute(
                f"ALTER TABLE consumer_signal_log ADD COLUMN {name} {sql_type}"
            )
    conn.commit()
    conn.close()


def log_signal(signal_data: dict, response: dict) -> None:
    """Persist a signal and its processing result, then notify subscribers."""
    now = time.time()
    init_db()
    strategy_checks = response.get("strategy_checks")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        """
        INSERT INTO consumer_signal_log
            (received_at, signal_json, action, signal_price, live_price,
             signal_edge, live_edge, order_id, errors, strategy_checks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            json.dumps(signal_data),
            response.get("action", "unknown"),
            response.get("signal_price"),
            response.get("live_price"),
            response.get("signal_edge"),
            response.get("live_edge"),
            response.get("order_id"),
            json.dumps(response.get("errors", [])),
            json.dumps(strategy_checks) if strategy_checks else None,
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()

    # Notify SSE subscribers
    _notify({
        "id": row_id,
        "received_at": now,
        "action": response.get("action", "unknown"),
        "status": response.get("status"),
        "token_id": signal_data.get("token_id", ""),
    })


def get_signals(limit: int = 100) -> list[dict]:
    """Retrieve recent signals from the log."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM consumer_signal_log ORDER BY received_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        signal = json.loads(row["signal_json"])
        raw_checks = row["strategy_checks"] if "strategy_checks" in row.keys() else None
        results.append({
            "id": row["id"],
            "received_at": row["received_at"],
            "description": signal.get("description", ""),
            "token_id": signal.get("token_id", ""),
            "side": signal.get("side", "buy"),
            "model_probability": signal.get("model_probability"),
            "position_size_usd": signal.get("position_size_usd"),
            "action": row["action"],
            "signal_price": row["signal_price"],
            "live_price": row["live_price"],
            "signal_edge": row["signal_edge"],
            "live_edge": row["live_edge"],
            "order_id": row["order_id"],
            "errors": json.loads(row["errors"]) if row["errors"] else [],
            "strategy_checks": json.loads(raw_checks) if raw_checks else None,
        })
    return results


def get_executed_notional_usd() -> float:
    """Return cumulative notional for executed trades in consumer log."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        """
        SELECT COALESCE(SUM(signal_json_extract.position_size_usd), 0.0)
        FROM (
            SELECT
                json_extract(signal_json, '$.position_size_usd') AS position_size_usd
            FROM consumer_signal_log
            WHERE action IN ('executed', 'simulated')
        ) AS signal_json_extract
        """
    ).fetchone()
    conn.close()
    return float(row[0] or 0.0)
