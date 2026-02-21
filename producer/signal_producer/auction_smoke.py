"""Reproducible end-to-end auction smoke test harness."""

from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from .signals.types import PolymarketInfo, ProducerSignal, WeatherMetadata
from .ws_server import app, broadcaster


def _build_sample_signal(event_id: str) -> ProducerSignal:
    return ProducerSignal(
        signal_type="weather",
        model_probability=0.70,
        confidence=0.85,
        forecast_source="open_meteo",
        forecast_time=datetime.now(UTC).isoformat(),
        metadata=WeatherMetadata(
            city="nyc",
            target_date="2026-02-22",
            ensemble_mean=45.2,
            ensemble_std=2.1,
            members_in_range=12,
        ),
        exchanges=[
            PolymarketInfo(
                exchange="polymarket",
                event_id=event_id,
                token_id="token-secret",
                side="yes",
                market_description="Will NYC be 44-45F?",
                resolution_source="https://example.com",
                market_price=0.52,
                edge=0.18,
                price_timestamp=datetime.now(UTC).isoformat(),
            )
        ],
    )


def _count_auction_rows(db_path: Path) -> int:
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM consumer_auction_log").fetchone()
        return int(row[0] if row else 0)
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _get_recent_auction_events(db_path: Path, limit: int = 20) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                received_at,
                auction_id,
                consumer_did,
                outcome,
                winner_did,
                winning_paid_amount
            FROM consumer_auction_log
            ORDER BY received_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def _print_recent_auction_events(db_path: Path, limit: int) -> None:
    events = _get_recent_auction_events(db_path, limit=limit)
    if not events:
        print("No consumer_auction_log events found.")
        return
    print(f"Recent consumer_auction_log events (limit={limit}):")
    for event in events:
        print(
            "  id={id} auction_id={auction_id} consumer={consumer_did} outcome={outcome} "
            "winner={winner_did} paid={winning_paid_amount}".format(**event)
        )


def _start_consumer_process(
    *,
    repo_root: Path,
    host: str,
    port: int,
    did: str,
    bid_amount: float,
    payment_success: bool,
    api_port: int,
    log_path: Path,
) -> tuple[subprocess.Popen, object]:
    consumer_dir = repo_root / "consumer"
    env = os.environ.copy()
    env.update(
        {
            "CONSUMER_DID": did,
            "CONSUMER_WALLET_ADDRESS": "0x0000000000000000000000000000000000000abc",
            "CONSUMER_DEFAULT_BID_AMOUNT": str(bid_amount),
            "CONSUMER_PAYMENT_AUTO_SUCCEEDS": "true" if payment_success else "false",
            "BID_LLM_PROVIDER": "mock",
            "PRODUCER_WS_URL": f"ws://{host}:{port}/ws/signals",
            "PRODUCER_BID_WS_URL": f"ws://{host}:{port}/ws/bids",
        }
    )
    log_file = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "python",
            "-m",
            "signal_consumer.run",
            "--host",
            host,
            "--api-port",
            str(api_port),
            "--verbose",
        ],
        cwd=str(consumer_dir),
        env=env,
        stdout=log_file,
        stderr=log_file,
    )
    return proc, log_file


async def _run_smoke(
    *,
    repo_root: Path,
    host: str,
    port: int,
    top_bid: float,
    second_bid: float,
    top_payment_success: bool,
    second_payment_success: bool,
    consumer_a_api_port: int,
    consumer_b_api_port: int,
    consumer_startup_seconds: float,
    print_db_events: bool,
    print_db_events_limit: int,
) -> None:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
    server_task = asyncio.create_task(server.serve())
    await asyncio.sleep(0.8)

    log_dir = repo_root / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_a = log_dir / "consumer-a-smoke.log"
    log_b = log_dir / "consumer-b-smoke.log"
    proc_a, file_a = _start_consumer_process(
        repo_root=repo_root,
        host=host,
        port=port,
        did="did:kite:paper/consumer-a",
        bid_amount=top_bid,
        payment_success=top_payment_success,
        api_port=consumer_a_api_port,
        log_path=log_a,
    )
    proc_b, file_b = _start_consumer_process(
        repo_root=repo_root,
        host=host,
        port=port,
        did="did:kite:paper/consumer-b",
        bid_amount=second_bid,
        payment_success=second_payment_success,
        api_port=consumer_b_api_port,
        log_path=log_b,
    )
    db_path = repo_root / "data" / "consumer_signals.db"
    before = _count_auction_rows(db_path)
    print(f"consumer_auction_log rows before: {before}")
    print(f"consumer logs: {log_a}, {log_b}")

    try:
        await asyncio.sleep(consumer_startup_seconds)
        await broadcaster.broadcast_producer_signal(
            _build_sample_signal(event_id="event-paper-live-1")
        )
        await asyncio.sleep(8.0)

        after = _count_auction_rows(db_path)
        print(f"consumer_auction_log rows after: {after}")
        if after <= before:
            raise RuntimeError(
                "Real-consumer smoke test failed: consumer_auction_log did not increase. "
                f"Check logs at {log_a} and {log_b}."
            )
        print("Real-consumer smoke test passed: auction rows were persisted.")
        if print_db_events:
            _print_recent_auction_events(db_path, limit=print_db_events_limit)
    finally:
        for proc, file_handle in ((proc_a, file_a), (proc_b, file_b)):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            file_handle.close()
        server.should_exit = True
        await asyncio.sleep(0.5)
        server_task.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run reproducible producer auction smoke test")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8012)
    parser.add_argument("--top-bid", type=float, default=10.0)
    parser.add_argument("--second-bid", type=float, default=6.0)
    parser.add_argument("--top-payment-success", action="store_true")
    parser.add_argument("--second-payment-success", action="store_true")
    parser.add_argument("--consumer-a-api-port", type=int, default=8766)
    parser.add_argument("--consumer-b-api-port", type=int, default=8767)
    parser.add_argument("--consumer-startup-seconds", type=float, default=3.0)
    parser.add_argument(
        "--print-db-events",
        action="store_true",
        help="Print recent consumer_auction_log events after real-consumer run",
    )
    parser.add_argument("--print-db-events-limit", type=int, default=20)
    args = parser.parse_args()

    # Defaults mirror the fallback scenario: top fails, second succeeds.
    top_success = args.top_payment_success
    second_success = args.second_payment_success or not top_success
    repo_root = Path(__file__).resolve().parents[2]

    asyncio.run(
        _run_smoke(
            repo_root=repo_root,
            host=args.host,
            port=args.port,
            top_bid=args.top_bid,
            second_bid=args.second_bid,
            top_payment_success=top_success,
            second_payment_success=second_success,
            consumer_a_api_port=args.consumer_a_api_port,
            consumer_b_api_port=args.consumer_b_api_port,
            consumer_startup_seconds=args.consumer_startup_seconds,
            print_db_events=args.print_db_events,
            print_db_events_limit=args.print_db_events_limit,
        )
    )


if __name__ == "__main__":
    main()
