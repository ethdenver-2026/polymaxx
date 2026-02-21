"""SQLite persistence for consumer signal and auction logs."""

from __future__ import annotations

import json
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path
from threading import Lock

# Regexes for deriving event title / bucket from legacy market_description
# e.g. "Will the highest temperature in New York City be between 52-53°F on February 21?"
_RE_EVENT_TITLE = re.compile(
    r"highest temperature in (.+?) (?:be .+? )?on (.+?)\?", re.IGNORECASE
)
_RE_BUCKET = re.compile(
    r"be ((?:between )?\d+.+?)(?:\s+on\s)", re.IGNORECASE
)

from signal_schema.addressing import normalize_evm_address

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "consumer_signals.db"

# Thread-safe pub/sub for live signal updates.
# Subscribers are queue.Queue instances — one per SSE connection.
_subscribers: list[queue.Queue[dict]] = []
_subscribers_lock = threading.Lock()
_SCHEMA_COLUMNS: dict[str, str] = {
    "signal_id": "TEXT",
    "state": "TEXT",
    "consumer_did": "TEXT",
    "source_created_at": "TEXT",
    "source_published_at": "TEXT",
    "decision_status": "TEXT",
    "strategy_reasons_json": "TEXT",
    "balance_available_usdc": "REAL",
    "chosen_position_usd": "REAL",
    "horizon_hours": "REAL",
    "metadata_json": "TEXT",
    "strategy_checks": "TEXT",
    "auction_id": "TEXT",
    "producer_did": "TEXT",
    "event_id": "TEXT",
    "winner_did": "TEXT",
    "winning_paid_amount": "REAL",
    "bid_amount": "REAL",
    "decision_rationale": "TEXT",
    "preview_received_at": "REAL",
    "bid_submitted_at": "REAL",
    "signal_received_at": "REAL",
    "auction_result_received_at": "REAL",
    "updated_at": "REAL",
}
_AUCTION_SCHEMA_COLUMNS: dict[str, str] = {
    "event_title": "TEXT",
    "market_group_item_title": "TEXT",
}
_TRADES_SCHEMA_COLUMNS: dict[str, str] = {}  # future migrations
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
    with _DB_INIT_LOCK:
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
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at             REAL    NOT NULL,
            auction_id              TEXT    NOT NULL,
            consumer_did            TEXT    NOT NULL,
            producer_did            TEXT,
            event_id                TEXT,
            event_title             TEXT,
            market_group_item_title TEXT,
            bid_amount              REAL,
            auction_end_utc         TEXT,
            outcome                 TEXT    NOT NULL,
            rejection_reason        TEXT,
            winner_did              TEXT,
            winning_paid_amount     REAL,
            payment_url             TEXT,
            x402_network            TEXT,
            x402_asset              TEXT,
            metadata_json           TEXT,
            raw_message_json        TEXT    NOT NULL
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
        conn.execute("""
        CREATE TABLE IF NOT EXISTS consumer_trades (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_log_id      INTEGER,
            trade_type         TEXT NOT NULL,
            token_id           TEXT NOT NULL,
            side               TEXT NOT NULL DEFAULT 'buy',
            entry_price        REAL,
            size_usd           REAL,
            model_probability  REAL,
            signal_edge        REAL,
            live_edge          REAL,
            order_id           TEXT,
            status             TEXT NOT NULL DEFAULT 'open',
            event_id           TEXT,
            event_title        TEXT,
            market_description TEXT,
            city               TEXT,
            target_date        TEXT,
            created_at         REAL NOT NULL,
            closed_at          REAL,
            exit_price         REAL,
            pnl_usd            REAL
        )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_trades_status "
            "ON consumer_trades (status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_trades_trade_type "
            "ON consumer_trades (trade_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_trades_created_at "
            "ON consumer_trades (created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_trades_token_id "
            "ON consumer_trades (token_id)"
        )
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
        # Idempotent migration: add columns that don't exist yet (signal log)
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(consumer_signal_log)").fetchall()
        }
        for name, sql_type in _SCHEMA_COLUMNS.items():
            if name not in existing_cols:
                conn.execute(
                    f"ALTER TABLE consumer_signal_log ADD COLUMN {name} {sql_type}"
                )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_signal_log_auction_id "
            "ON consumer_signal_log (auction_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_consumer_signal_log_auction_consumer "
            "ON consumer_signal_log (auction_id, consumer_did)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_consumer_signal_log_signal_id_unique "
            "ON consumer_signal_log (signal_id) "
            "WHERE signal_id IS NOT NULL"
        )
        # Idempotent migration: add columns that don't exist yet (auction log)
        existing_auction_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(consumer_auction_log)").fetchall()
        }
        for name, sql_type in _AUCTION_SCHEMA_COLUMNS.items():
            if name not in existing_auction_cols:
                conn.execute(
                    f"ALTER TABLE consumer_auction_log ADD COLUMN {name} {sql_type}"
                )
        # Idempotent migration: add columns that don't exist yet (trades)
        existing_trade_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(consumer_trades)").fetchall()
        }
        for name, sql_type in _TRADES_SCHEMA_COLUMNS.items():
            if name not in existing_trade_cols:
                conn.execute(
                    f"ALTER TABLE consumer_trades ADD COLUMN {name} {sql_type}"
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
    # Accept the default placeholder — just derive from wallet
    if candidate in ("", "did:kite:consumer/default"):
        return expected
    if candidate != expected:
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
    event_title: str | None = None,
    market_group_item_title: str | None = None,
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
                event_title, market_group_item_title,
                bid_amount, auction_end_utc, outcome, rejection_reason, winner_did,
                winning_paid_amount, payment_url, x402_network, x402_asset,
                metadata_json, raw_message_json
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            auction_id,
            consumer_did,
            producer_did,
            event_id,
            event_title,
            market_group_item_title,
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
    """Return recent auctions, collapsed to one row per auction_id.

    Each row merges all lifecycle events (bid_submitted → won_offer →
    payment_succeeds etc.) into a single summary with the final outcome.
    Smoke/seeded data is always excluded.
    """
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM consumer_auction_log ORDER BY received_at ASC",
    ).fetchall()
    conn.close()

    # Group events by auction_id, merging into a single row per auction.
    auctions: dict[str, dict] = {}
    for row in rows:
        raw = json.loads(row["raw_message_json"])
        if raw.get("smoke"):
            continue  # always skip seeded data

        aid = row["auction_id"]
        if aid not in auctions:
            auctions[aid] = {
                "id": row["id"],
                "received_at": row["received_at"],
                "auction_id": aid,
                "consumer_did": row["consumer_did"],
                "producer_did": None,
                "event_id": None,
                "event_title": None,
                "market_group_item_title": None,
                "bid_amount": None,
                "auction_end_utc": None,
                "outcome": row["outcome"],
                "rejection_reason": None,
                "winner_did": None,
                "winning_paid_amount": None,
                "payment_url": None,
            }

        entry = auctions[aid]
        # Always update to the latest outcome
        entry["outcome"] = row["outcome"]
        # Merge non-null fields from later events
        if row["producer_did"]:
            entry["producer_did"] = row["producer_did"]
        if row["event_id"]:
            entry["event_id"] = row["event_id"]
        if row["event_title"]:
            entry["event_title"] = row["event_title"]
        if row["market_group_item_title"]:
            entry["market_group_item_title"] = row["market_group_item_title"]
        if row["bid_amount"]:
            entry["bid_amount"] = row["bid_amount"]
        if row["auction_end_utc"]:
            entry["auction_end_utc"] = row["auction_end_utc"]
        if row["rejection_reason"]:
            entry["rejection_reason"] = row["rejection_reason"]
        if row["winner_did"]:
            entry["winner_did"] = row["winner_did"]
        if row["winning_paid_amount"]:
            entry["winning_paid_amount"] = row["winning_paid_amount"]
        if row["payment_url"]:
            entry["payment_url"] = row["payment_url"]

    # Return most-recent-first, limited
    result = sorted(auctions.values(), key=lambda a: a["received_at"], reverse=True)
    return result[:limit]


def log_signal(signal_data: dict, response: dict, *, auction_id: str | None = None) -> None:
    """Persist a signal and its processing result, then notify subscribers."""
    now = time.time()
    init_db()
    strategy_checks = response.get("strategy_checks")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        """
        INSERT INTO consumer_signal_log
            (received_at, signal_json, action, signal_price, live_price,
             signal_edge, live_edge, order_id, errors, strategy_checks,
             auction_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            auction_id,
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


def _require_non_empty(value: str | None, field: str) -> str:
    if value is None:
        raise RuntimeError(f"{field} is required")
    cleaned = value.strip()
    if not cleaned:
        raise RuntimeError(f"{field} must be non-empty")
    return cleaned


def get_signal_id_for_auction_id(auction_id: str, *, consumer_did: str | None = None) -> str | None:
    """Return the latest signal_id for an auction_id (optionally scoped by consumer_did)."""
    aid = _require_non_empty(auction_id, "auction_id")
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    if consumer_did is not None:
        did = _require_non_empty(consumer_did, "consumer_did")
        row = conn.execute(
            """
            SELECT signal_id
            FROM consumer_signal_log
            WHERE auction_id = ?
              AND consumer_did = ?
              AND signal_id IS NOT NULL
            ORDER BY received_at DESC
            LIMIT 1
            """,
            (aid, did),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT signal_id
            FROM consumer_signal_log
            WHERE auction_id = ?
              AND signal_id IS NOT NULL
            ORDER BY received_at DESC
            LIMIT 1
            """,
            (aid,),
        ).fetchone()
    conn.close()
    if not row:
        return None
    return str(row[0])


def create_signal_lifecycle(
    *,
    signal_id: str,
    auction_id: str,
    consumer_did: str,
    preview_payload: dict,
    producer_did: str | None = None,
    event_id: str | None = None,
) -> int:
    """Create a lifecycle row as soon as SignalPreviewMessage is received."""
    sid = _require_non_empty(signal_id, "signal_id")
    aid = _require_non_empty(auction_id, "auction_id")
    did = _require_non_empty(consumer_did, "consumer_did")
    if not isinstance(preview_payload, dict) or not preview_payload:
        raise RuntimeError("preview_payload must be a non-empty dict")

    now = time.time()
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        """
        INSERT INTO consumer_signal_log
            (
                received_at, updated_at, preview_received_at,
                consumer_did,
                signal_id, auction_id, state, action,
                signal_json, errors,
                producer_did, event_id
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            now,
            now,
            did,
            sid,
            aid,
            "preview_received",
            "pending",
            json.dumps(preview_payload),
            json.dumps([]),
            producer_did,
            event_id,
        ),
    )
    conn.commit()
    row_id = int(cur.lastrowid)
    conn.close()

    _notify(
        {
            "id": row_id,
            "signal_id": sid,
            "auction_id": aid,
            "received_at": now,
            "action": "pending",
            "state": "preview_received",
            "token_id": "",
        }
    )
    return row_id


def update_signal_lifecycle(
    *,
    signal_id: str | None = None,
    auction_id: str | None = None,
    consumer_did: str | None = None,
    state: str | None = None,
    action: str | None = None,
    signal_payload: dict | None = None,
    signal_price: float | None = None,
    live_price: float | None = None,
    signal_edge: float | None = None,
    live_edge: float | None = None,
    order_id: str | None = None,
    errors: list[str] | None = None,
    producer_did: str | None = None,
    event_id: str | None = None,
    winner_did: str | None = None,
    winning_paid_amount: float | None = None,
    bid_amount: float | None = None,
    decision_rationale: str | None = None,
) -> None:
    """
    Update a lifecycle row identified by signal_id or auction_id.

    Raises RuntimeError when identifier is missing, no fields are supplied,
    or the target row does not exist.
    """
    where_sql = ""
    where_params: list[str] = []
    if signal_id:
        where_sql = "signal_id = ?"
        where_params.append(_require_non_empty(signal_id, "signal_id"))
        if consumer_did is not None:
            where_sql += " AND consumer_did = ?"
            where_params.append(_require_non_empty(consumer_did, "consumer_did"))
    elif auction_id:
        where_sql = "auction_id = ? AND consumer_did = ?"
        where_params.append(_require_non_empty(auction_id, "auction_id"))
        where_params.append(_require_non_empty(consumer_did, "consumer_did"))
    else:
        raise RuntimeError("Either signal_id or auction_id is required for update_signal_lifecycle")

    if signal_payload is not None and not isinstance(signal_payload, dict):
        raise RuntimeError("signal_payload must be a dict when provided")
    if errors is not None and not isinstance(errors, list):
        raise RuntimeError("errors must be a list[str] when provided")

    now = time.time()
    updates: list[str] = []
    params: list[object] = []

    def _set(name: str, value: object) -> None:
        updates.append(f"{name} = ?")
        params.append(value)

    if state is not None:
        _set("state", state)
        if state == "preview_received":
            _set("preview_received_at", now)
        if state == "bid_submitted":
            _set("bid_submitted_at", now)
        if state in {"signal_received", "executed", "simulated", "skipped", "error"}:
            _set("signal_received_at", now)
        if state.startswith("auction_") or state in {
            "AuctionBidRejected",
            "AuctionLossNotice",
            "AuctionNoWinner",
            "auction_result",
            "payment_succeeds",
            "payment_failed",
        }:
            _set("auction_result_received_at", now)
    if action is not None:
        _set("action", action)
    if signal_payload is not None:
        _set("signal_json", json.dumps(signal_payload))
    if signal_price is not None:
        _set("signal_price", signal_price)
    if live_price is not None:
        _set("live_price", live_price)
    if signal_edge is not None:
        _set("signal_edge", signal_edge)
    if live_edge is not None:
        _set("live_edge", live_edge)
    if order_id is not None:
        _set("order_id", order_id)
    if errors is not None:
        _set("errors", json.dumps(errors))
    if producer_did is not None:
        _set("producer_did", producer_did)
    if event_id is not None:
        _set("event_id", event_id)
    if winner_did is not None:
        _set("winner_did", winner_did)
    if winning_paid_amount is not None:
        _set("winning_paid_amount", winning_paid_amount)
    if bid_amount is not None:
        _set("bid_amount", bid_amount)
    if decision_rationale is not None:
        _set("decision_rationale", decision_rationale)

    if not updates:
        raise RuntimeError("No update fields provided to update_signal_lifecycle")

    _set("updated_at", now)

    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        f"UPDATE consumer_signal_log SET {', '.join(updates)} WHERE {where_sql}",
        (*params, *where_params),
    )
    if cur.rowcount == 0:
        conn.close()
        ident = f"signal_id={where_params[0]}" if signal_id else f"auction_id={where_params[0]} consumer_did={where_params[1]}"
        raise RuntimeError(
            f"No consumer_signal_log row found for {ident}"
        )

    row = conn.execute(
        f"""
        SELECT id, signal_id, auction_id, action, state, signal_json
        FROM consumer_signal_log
        WHERE {where_sql}
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        tuple(where_params),
    ).fetchone()
    conn.commit()
    conn.close()

    token_id = ""
    if row and row[5]:
        try:
            payload = json.loads(row[5])
            if isinstance(payload, dict):
                exchanges = payload.get("exchanges")
                if isinstance(exchanges, list) and exchanges and isinstance(exchanges[0], dict):
                    token_id = str(exchanges[0].get("token_id") or "")
                if not token_id:
                    token_id = str(payload.get("token_id") or "")
        except Exception:
            token_id = ""

    if row:
        _notify(
            {
                "id": row[0],
                "signal_id": row[1],
                "auction_id": row[2],
                "received_at": now,
                "action": row[3],
                "state": row[4],
                "token_id": token_id,
            }
        )


def get_signals(limit: int = 100) -> list[dict]:
    """Retrieve recent signals with joined auction metadata."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT s.*,
               a.bid_amount  AS auction_bid_amount,
               a.outcome     AS auction_outcome,
               a.winning_paid_amount AS auction_paid_amount,
               a.winner_did AS auction_winner_did
        FROM consumer_signal_log s
        LEFT JOIN (
            SELECT auction_id, bid_amount, outcome, winning_paid_amount, winner_did,
                   ROW_NUMBER() OVER (PARTITION BY auction_id ORDER BY received_at DESC) AS rn
            FROM consumer_auction_log
            WHERE outcome IN ('payment_succeeds', 'AuctionBidRejected',
                              'AuctionLossNotice', 'AuctionNoWinner', 'bid_skipped', 'auction_result')
        ) a ON s.auction_id = a.auction_id AND a.rn = 1
        ORDER BY s.received_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    results = []
    for row in rows:
        signal = json.loads(row["signal_json"])
        raw_checks = row["strategy_checks"] if "strategy_checks" in row.keys() else None

        # Extract from canonical ProducerSignal format
        exchange = signal.get("exchanges", [{}])[0] if signal.get("exchanges") else {}
        metadata = signal.get("metadata", {})

        # Build description from market_question/event_title or legacy description field
        description = (
            exchange.get("market_question")
            or exchange.get("market_description")
            or exchange.get("event_title")
            or signal.get("description", "")
        )

        # event_title: use field directly, or derive from market_description
        event_title = exchange.get("event_title") or ""
        if not event_title:
            md = exchange.get("market_description") or ""
            m = _RE_EVENT_TITLE.search(md)
            if m:
                event_title = f"Highest temperature in {m.group(1)} on {m.group(2)}?"

        # market_group_item_title: use field directly, or derive from market_description
        market_label = exchange.get("market_group_item_title") or ""
        if not market_label:
            md = exchange.get("market_description") or ""
            m = _RE_BUCKET.search(md)
            if m:
                market_label = m.group(1)

        merged_bid_amount = row["bid_amount"] if "bid_amount" in row.keys() and row["bid_amount"] is not None else row["auction_bid_amount"]
        merged_outcome = row["state"] if "state" in row.keys() and row["state"] else row["auction_outcome"]
        merged_paid_amount = (
            row["winning_paid_amount"]
            if "winning_paid_amount" in row.keys() and row["winning_paid_amount"] is not None
            else row["auction_paid_amount"]
        )
        merged_winner_did = (
            row["winner_did"]
            if "winner_did" in row.keys() and row["winner_did"]
            else row["auction_winner_did"]
        )

        results.append({
            "id": row["id"],
            "signal_id": row["signal_id"] if "signal_id" in row.keys() and row["signal_id"] else f"signal-{row['id']}",
            "received_at": row["received_at"],
            "description": description,
            "event_title": event_title,
            "market_group_item_title": market_label,
            "token_id": exchange.get("token_id") or signal.get("token_id", ""),
            "side": exchange.get("side") or signal.get("side", "buy"),
            "model_probability": signal.get("model_probability"),
            "position_size_usd": signal.get("position_size_usd"),
            "action": row["action"],
            "state": row["state"] if "state" in row.keys() else None,
            "signal_price": row["signal_price"],
            "live_price": row["live_price"],
            "signal_edge": row["signal_edge"],
            "live_edge": row["live_edge"],
            "order_id": row["order_id"],
            "errors": json.loads(row["errors"]) if row["errors"] else [],
            "strategy_checks": json.loads(raw_checks) if raw_checks else None,
            "city": metadata.get("city"),
            "event_id": exchange.get("event_id"),
            "edge": exchange.get("edge"),
            "auction_id": row["auction_id"],
            "bid_amount": merged_bid_amount,
            "auction_outcome": merged_outcome,
            "paid_amount": merged_paid_amount,
            "winner_did": merged_winner_did,
        })
    return results


def log_trade(
    *,
    trade_type: str,
    token_id: str,
    side: str = "buy",
    entry_price: float | None = None,
    size_usd: float | None = None,
    model_probability: float | None = None,
    signal_edge: float | None = None,
    live_edge: float | None = None,
    order_id: str | None = None,
    status: str = "open",
    event_id: str | None = None,
    event_title: str | None = None,
    market_description: str | None = None,
    city: str | None = None,
    target_date: str | None = None,
    signal_log_id: int | None = None,
) -> int:
    """Insert a trade record and notify subscribers. Returns trade_id."""
    now = time.time()
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        """
        INSERT INTO consumer_trades
            (signal_log_id, trade_type, token_id, side, entry_price, size_usd,
             model_probability, signal_edge, live_edge, order_id, status,
             event_id, event_title, market_description, city, target_date, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_log_id, trade_type, token_id, side, entry_price, size_usd,
            model_probability, signal_edge, live_edge, order_id, status,
            event_id, event_title, market_description, city, target_date, now,
        ),
    )
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()

    _notify({
        "type": "trade",
        "id": trade_id,
        "trade_type": trade_type,
        "token_id": token_id,
        "status": status,
        "created_at": now,
    })
    return trade_id


def get_trades(
    limit: int = 100,
    status: str | None = None,
    trade_type: str | None = None,
) -> list[dict]:
    """Return trades with optional filters."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    clauses: list[str] = []
    params: list = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if trade_type:
        clauses.append("trade_type = ?")
        params.append(trade_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM consumer_trades {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_paper_positions() -> list[dict]:
    """Return paper positions from the trades table (backward-compatible shape)."""
    trades = get_trades(status="open", trade_type="paper")
    results = []
    for t in trades:
        results.append({
            "token_id": t.get("token_id", ""),
            "description": t.get("market_description") or t.get("event_title") or "",
            "side": t.get("side", "buy"),
            "entry_price": t.get("entry_price", 0),
            "size_usd": t.get("size_usd", 0),
            "model_probability": t.get("model_probability", 0),
            "edge": t.get("signal_edge") or t.get("live_edge") or 0,
            "received_at": t.get("created_at", 0),
        })
    return results


def get_executed_notional_usd() -> float:
    """Return cumulative notional for open trades."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        "SELECT COALESCE(SUM(size_usd), 0.0) FROM consumer_trades WHERE status = 'open'"
    ).fetchone()
    conn.close()
    return float(row[0] or 0.0)


def get_auction_spend_usd() -> float:
    """Return total USDC spent on successful auction payments."""
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute(
        """
        SELECT COALESCE(SUM(bid_amount), 0.0)
        FROM consumer_auction_log
        WHERE outcome = 'payment_succeeds'
        """
    ).fetchone()
    conn.close()
    return float(row[0] or 0.0)
