"""Main entry point for the prediction market bot."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime

import structlog

from .config import get_settings, DEFAULT_CITIES
from .models.models import SignalRecord, get_session
from .publishing.websocket import broadcaster
from .signals.types import ProducerSignal, WeatherMetadata, PolymarketInfo
from .strategies.weather import WeatherStrategy
from .strategies.base import Signal
from .trading.executor import TradeExecutor


# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


def _build_signal_record(signal: Signal) -> SignalRecord:
    """Build a SignalRecord payload from a strategy Signal."""
    metadata_json = json.dumps(signal.metadata) if signal.metadata else None
    return SignalRecord(
        strategy=signal.strategy,
        market_id=signal.market_id,
        token_id=signal.token_id,
        model_probability=signal.model_probability,
        market_price=signal.market_price,
        edge=signal.edge,
        confidence=signal.confidence,
        decision="trade",
        skip_reason=None,
        trade_id=None,
        created_at=datetime.now(UTC).replace(tzinfo=None),
        metadata_json=metadata_json,
    )


def _persist_signal_record_sync(executor: TradeExecutor, record: SignalRecord) -> None:
    """Persist a signal record using the producer DB engine."""
    session = get_session(executor.engine)
    try:
        session.add(record)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _build_producer_signal(signal: Signal) -> ProducerSignal:
    """Build canonical ProducerSignal payload from strategy Signal."""
    metadata = signal.metadata or {}
    weather_metadata: WeatherMetadata = {
        "city": str(metadata.get("city", "")),
        "target_date": signal.target_date.isoformat(),
        "ensemble_mean": float(metadata.get("ensemble_mean", 0.0)),
        "ensemble_std": float(metadata.get("ensemble_std", metadata.get("ensemble_std_dev", 0.0))),
        "members_in_range": int(metadata.get("members_in_range", round(signal.model_probability * 31))),
    }

    exchange: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": signal.market_id,
        "token_id": signal.token_id,
        "side": "yes",
        "market_description": signal.description,
        "resolution_source": str(metadata.get("resolution_source", "")),
        "market_price": signal.market_price,
        "edge": signal.edge,
        "price_timestamp": datetime.now(UTC).isoformat(),
    }

    return ProducerSignal(
        signal_type="weather",
        model_probability=signal.model_probability,
        confidence=signal.confidence,
        forecast_source="open_meteo",
        forecast_time=datetime.now(UTC).isoformat(),
        metadata=weather_metadata,
        exchanges=[exchange],
    )


async def run_once(cities: list[str] | None = None, broadcast_signals: bool = False) -> list:
    """Run a single trading cycle."""
    settings = get_settings()
    city_list = cities or DEFAULT_CITIES

    logger.info(
        "Starting trading cycle",
        mode=settings.trading_mode,
        cities=city_list,
        bankroll=f"${settings.bankroll_usdc:.2f}",
        edge_threshold=f"{settings.edge_threshold_pct:.1f}%",
    )

    # Initialize components
    strategy = WeatherStrategy(settings, cities=city_list)
    executor = TradeExecutor(settings)

    # Generate signals (async)
    result = await strategy.generate_signals()

    logger.info(
        "Strategy complete",
        events_checked=result.events_checked,
        signals_found=len(result.signals),
        errors=len(result.errors),
    )

    if result.errors:
        for error in result.errors:
            logger.warning("Strategy error", error=error)

    # Publish signals only when explicitly enabled (e.g., websocket server context).
    for signal in result.signals:
        producer_signal = _build_producer_signal(signal)
        signal_record = _build_signal_record(signal)
        persist_task = asyncio.create_task(asyncio.to_thread(_persist_signal_record_sync, executor, signal_record))
        publish_task: asyncio.Task[None] | None = None
        if broadcast_signals:
            publish_task = asyncio.create_task(broadcaster.broadcast_producer_signal(producer_signal))

        # Prioritize websocket delivery completion first when enabled.
        if publish_task is not None:
            await publish_task

        # DB write remains concurrent, but should not block signal delivery on failure.
        try:
            await persist_task
        except Exception as exc:
            logger.error(
                "Failed to persist SignalRecord",
                error=str(exc),
                market_id=signal_record.market_id,
                token_id=signal_record.token_id,
            )

    # Execute trades
    trades_executed = 0
    for signal in result.signals:
        exec_result = executor.execute(signal)
        if exec_result.success:
            trades_executed += 1

    logger.info(
        "Cycle complete",
        signals=len(result.signals),
        trades_executed=trades_executed,
    )

    return result.signals


def main():
    """Main entry point with CLI argument parsing.

    Default behavior runs a single trading cycle. Use --serve to run websocket server.
    """
    parser = argparse.ArgumentParser(description="Polymarket Weather Prediction Bot")

    parser.add_argument(
        "--cities",
        type=str,
        help="Comma-separated list of cities (e.g., nyc,chicago,miami)",
    )
    parser.add_argument(
        "--show-signals",
        action="store_true",
        help="Show detailed signal information",
    )
    parser.add_argument("--serve", action="store_true", help="Run websocket server instead of a single cycle")
    parser.add_argument("--producer", action="store_true", help="Run continuous producer (event discovery + signal generation)")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind websocket server",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind websocket server",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/producer.db",
        help="Database path for producer mode",
    )

    args = parser.parse_args()

    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)

    if args.producer:
        from .tasks import run_producer

        cities = None
        if args.cities:
            cities = [c.strip() for c in args.cities.split(",")]

        logger.info(
            "Starting producer",
            cities=cities or "all",
            db_path=args.db_path,
        )
        asyncio.run(run_producer(db_path=args.db_path, cities=cities))
        return

    if args.serve:
        from .ws_server import run_signal_server

        run_signal_server(host=args.host, port=args.port)
        return

    # Parse cities
    cities = None
    if args.cities:
        cities = [c.strip() for c in args.cities.split(",")]

    # Run trading cycle
    signals = asyncio.run(run_once(cities=cities))

    if args.show_signals and signals:
        print("\n" + "=" * 60)
        print("SIGNALS FOUND")
        print("=" * 60)
        for s in signals:
            city = s.metadata.get("city", "unknown").upper() if s.metadata else "UNKNOWN"
            print(f"\n{city} - {s.target_date}")
            print(f"  {s.description}")
            print(f"  Model: {s.model_probability*100:.1f}% | Market: {s.market_price*100:.1f}%")
            print(f"  Edge: {s.edge_pct:.1f}% | Position: ${s.position_size_usd:.2f}")
            print(f"  EV: ${s.expected_value:.2f}")


if __name__ == "__main__":
    main()
