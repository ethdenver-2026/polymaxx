"""Main entry point for the prediction market bot."""

import argparse
import asyncio
import os

import structlog

from .config import get_settings, DEFAULT_CITIES
from .strategies.weather import WeatherStrategy
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


async def run_once(cities: list[str] | None = None) -> list:
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
    """Main entry point with CLI argument parsing."""
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

    args = parser.parse_args()

    # Parse cities
    cities = None
    if args.cities:
        cities = [c.strip() for c in args.cities.split(",")]

    # Ensure data directory exists
    os.makedirs("data", exist_ok=True)

    # Run trading cycle
    signals = asyncio.run(run_once(cities=cities))

    if args.show_signals and signals:
        print("\n" + "=" * 60)
        print("SIGNALS FOUND")
        print("=" * 60)
        for s in signals:
            print(f"\n{s.city.upper()} - {s.target_date}")
            print(f"  {s.bucket_question}")
            print(f"  Model: {s.model_probability*100:.1f}% | Market: {s.market_price*100:.1f}%")
            print(f"  Edge: {s.edge_pct:.1f}% | Position: ${s.position_size_usd:.2f}")
            print(f"  EV: ${s.expected_value:.2f}")


if __name__ == "__main__":
    main()
