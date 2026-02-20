"""
SQLite persistence for consumer signal log.

Stores every signal received by the consumer along with the action taken
(executed, skipped, error) and price/edge details at execution time.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "consumer_signals.db"


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
    conn.commit()
    conn.close()


def log_signal(signal_data: dict, response: dict) -> None:
    """Persist a signal and its processing result."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        INSERT INTO consumer_signal_log
            (received_at, signal_json, action, signal_price, live_price,
             signal_edge, live_edge, order_id, errors)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            time.time(),
            json.dumps(signal_data),
            response.get("action", "unknown"),
            response.get("signal_price"),
            response.get("live_price"),
            response.get("signal_edge"),
            response.get("live_edge"),
            response.get("order_id"),
            json.dumps(response.get("errors", [])),
        ),
    )
    conn.commit()
    conn.close()


def get_signals(limit: int = 100) -> list[dict]:
    """Retrieve recent signals from the log."""
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
        })
    return results
