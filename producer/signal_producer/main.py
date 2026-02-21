"""Main entry point for the prediction market bot."""

import argparse
import asyncio
import os
import warnings
from typing import Any

import structlog

from .config import DEFAULT_CITIES
from signal_schema import ProducerSignal


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


async def run_once(cities: list[str] | None = None, broadcast_signals: bool = False) -> list[Any]:
    """Run a single signal generation cycle.

    DEPRECATED: Use `--producer` mode for continuous signal generation.
    This function now returns an empty list. Use the producer orchestrator
    for the full signal generation pipeline.
    """
    warnings.warn(
        "run_once() is deprecated. Use --producer mode for signal generation.",
        DeprecationWarning,
        stacklevel=2,
    )
    city_list = cities or DEFAULT_CITIES
    logger.warning(
        "run_once is deprecated - use --producer mode",
        cities=city_list,
        broadcast_signals=broadcast_signals,
    )
    return []


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
        from .tasks.orchestrator import ProducerOrchestrator
        from .ws_server import app, set_broadcaster

        import uvicorn

        cities = None
        if args.cities:
            cities = [c.strip() for c in args.cities.split(",")]

        logger.info(
            "Starting producer with WebSocket server",
            cities=cities or "all",
            db_path=args.db_path,
            host=args.host,
            port=args.port,
        )

        async def _run_producer_and_server() -> None:
            orchestrator = ProducerOrchestrator(db_path=args.db_path, cities=cities)
            orchestrator._init_components()
            set_broadcaster(orchestrator.broadcaster)

            server = uvicorn.Server(
                uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
            )
            server_task = asyncio.create_task(server.serve())
            orchestrator._setup_signal_handlers()
            try:
                await orchestrator._run_tasks()
            finally:
                server.should_exit = True
                await server_task

        asyncio.run(_run_producer_and_server())
        return

    if args.serve:
        from .ws_server import run_signal_server

        run_signal_server(host=args.host, port=args.port)
        return

    # Default: show deprecation message and recommend --producer mode
    print("No mode specified. Available modes:")
    print("  --producer  Run continuous signal generation (recommended)")
    print("  --serve     Run websocket server")
    print("\nExample: python -m signal_producer --producer")


if __name__ == "__main__":
    main()
