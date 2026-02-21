"""SQLite persistence for consumer signal and auction logs."""

from __future__ import annotations

import json
import queue
import sqlite3
import threading
import time
from pathlib import Path
from threading import Lock

from signal_schema.addressing import normalize_evm_address

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
_DB_INITIALIZED = False
_DB_INIT_LOCK = Lock()


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
    """Create consumer tables if they don't exist."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    with _DB_INIT_LOCK:
        if _DB_INITIALIZED:
            return
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
        conn.execute("""
        CREATE TABLE IF NOT EXISTS consumer_auction_log (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at         REAL    NOT NULL,
            auction_id          TEXT    NOT NULL,
            consumer_did        TEXT    NOT NULL,
            producer_did        TEXT,
            event_id            TEXT,
            bid_amount          REAL,
            auction_end_utc     TEXT,
            outcome             TEXT    NOT NULL,
            rejection_reason    TEXT,
            winner_did          TEXT,
            winning_paid_amount REAL,
            payment_url         TEXT,
            x402_network        TEXT,
            x402_asset          TEXT,
            metadata_json       TEXT,
            raw_message_json    TEXT    NOT NULL
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS consumer_reputation_events (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at         REAL    NOT NULL,
            consumer_did        TEXT    NOT NULL,
            auction_id          TEXT,
            reason              TEXT    NOT NULL,
            negative_delta      INTEGER NOT NULL
        )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_auction_log_auction_id "
            "ON consumer_auction_log (auction_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_auction_log_received_at "
            "ON consumer_auction_log (received_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_auction_log_outcome "
            "ON consumer_auction_log (outcome)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_rep_events_consumer_did "
            "ON consumer_reputation_events (consumer_did)"
        )
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
        _DB_INITIALIZED = True


def _normalize_wallet_address(wallet_address: str) -> str:
    try:
        return normalize_evm_address(wallet_address)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def derive_consumer_did_pkh(*, chain_id: int, wallet_address: str) -> str:
    normalized_address = _normalize_wallet_address(wallet_address)
    return f"did:pkh:eip155:{chain_id}:{normalized_address}"


def validate_consumer_did_wallet_binding(
    *,
    consumer_did: str,
    wallet_address: str,
    chain_id: int,
) -> str:
    expected = derive_consumer_did_pkh(chain_id=chain_id, wallet_address=wallet_address)
    candidate = consumer_did.strip().lower()
    if candidate and candidate != expected:
        raise RuntimeError(
            "Configured consumer_did does not match wallet-bound did:pkh. "
            f"expected={expected} got={consumer_did}"
        )
    return expected


def record_consumer_payment_failure(*, consumer_did: str, auction_id: str, reason: str) -> None:
    now = time.time()
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        INSERT INTO consumer_reputation_events
            (received_at, consumer_did, auction_id, reason, negative_delta)
        VALUES (?, ?, ?, ?, ?)
        """,
        (now, consumer_did, auction_id, reason, 1),
    )
    conn.commit()
    conn.close()


def get_consumer_reputation(consumer_did: str) -> dict:
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        """
        SELECT COALESCE(SUM(negative_delta), 0)
        FROM consumer_reputation_events
        WHERE consumer_did = ?
        """,
        (consumer_did,),
    ).fetchone()
    conn.close()
    negative_reputation = int(row[0] or 0)
    return {"consumer_did": consumer_did, "negative_reputation": negative_reputation}


def is_consumer_reputation_sufficient(consumer_did: str, threshold: int = 5) -> bool:
    if threshold <= 0:
        raise RuntimeError(f"Invalid reputation threshold: {threshold}")
    rep = get_consumer_reputation(consumer_did)
    return int(rep["negative_reputation"]) < threshold


def log_auction_event(
    *,
    auction_id: str,
    consumer_did: str,
    outcome: str,
    raw_message: dict,
    producer_did: str | None = None,
    event_id: str | None = None,
    bid_amount: float | None = None,
    auction_end_utc: str | None = None,
    rejection_reason: str | None = None,
    winner_did: str | None = None,
    winning_paid_amount: float | None = None,
    payment_url: str | None = None,
    x402_network: str | None = None,
    x402_asset: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Persist a single auction lifecycle event."""
    now = time.time()
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        INSERT INTO consumer_auction_log
            (
                received_at, auction_id, consumer_did, producer_did, event_id,
                bid_amount, auction_end_utc, outcome, rejection_reason, winner_did,
                winning_paid_amount, payment_url, x402_network, x402_asset,
                metadata_json, raw_message_json
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            auction_id,
            consumer_did,
            producer_did,
            event_id,
            bid_amount,
            auction_end_utc,
            outcome,
            rejection_reason,
            winner_did,
            winning_paid_amount,
            payment_url,
            x402_network,
            x402_asset,
            json.dumps(metadata) if metadata else None,
            json.dumps(raw_message),
        ),
    )
    conn.commit()
    conn.close()


def get_auction_events(limit: int = 100) -> list[dict]:
    """Return recent auction events from consumer_auction_log."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM consumer_auction_log ORDER BY received_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": row["id"],
            "received_at": row["received_at"],
            "auction_id": row["auction_id"],
            "consumer_did": row["consumer_did"],
            "producer_did": row["producer_did"],
            "event_id": row["event_id"],
            "bid_amount": row["bid_amount"],
            "auction_end_utc": row["auction_end_utc"],
            "outcome": row["outcome"],
            "rejection_reason": row["rejection_reason"],
            "winner_did": row["winner_did"],
            "winning_paid_amount": row["winning_paid_amount"],
            "payment_url": row["payment_url"],
            "x402_network": row["x402_network"],
            "x402_asset": row["x402_asset"],
            "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else None,
            "raw_message": json.loads(row["raw_message_json"]),
        }
        for row in rows
    ]


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


def get_paper_positions() -> list[dict]:
    """Return paper (simulated) positions from the signal log."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            id,
            received_at,
            signal_json,
            signal_price,
            signal_edge
        FROM consumer_signal_log
        WHERE action = 'simulated'
        ORDER BY received_at DESC
        """
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        signal = json.loads(row["signal_json"])
        results.append({
            "token_id": signal.get("token_id", ""),
            "description": signal.get("description", ""),
            "side": signal.get("side", "buy"),
            "entry_price": row["signal_price"] or signal.get("market_price", 0),
            "size_usd": signal.get("position_size_usd", 0),
            "model_probability": signal.get("model_probability", 0),
            "edge": row["signal_edge"] or signal.get("edge", 0),
            "received_at": row["received_at"],
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
