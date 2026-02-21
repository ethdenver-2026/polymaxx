"""Main orchestrator for the producer signal pipeline.

Coordinates all async tasks:
- Event Discovery: Polls Gamma API for new weather events
- Price Tracker: WebSocket connection for real-time prices
- Signal Generator: Generates ProducerSignals from forecasts
"""

import asyncio
import signal
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import create_engine

from ..clients.polymarket.gamma import GammaClient
from ..models.models import Base
from ..config import get_settings, CITIES
from ..publishing.websocket_signal_broadcaster import SignalBroadcaster
from ..reputation import ReputationStore
from ..data.polymarket_registry import MarketRegistry
from ..clients.weather.open_meteo import OpenMeteoClient
from ..data.polymarket_price_tracker import PriceTracker

from .event_discovery import EventDiscoveryTask
from .signal_generator import SignalGeneratorTask

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

logger = structlog.get_logger()

DEFAULT_DB_PATH = "data/producer.db"


class ProducerOrchestrator:
    """
    Orchestrates all producer tasks.

    Manages lifecycle of:
    - MarketRegistry (SQLite-backed)
    - GammaClient (Polymarket API)
    - OpenMeteoClient (weather forecasts)
    - PriceTracker (WebSocket prices)
    - EventDiscoveryTask
    - SignalGeneratorTask
    - SignalBroadcaster (WebSocket output)
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        cities: list[str] | None = None,
        poll_interval: int = 10,
        forecast_interval: int | None = None,
        edge_threshold: float | None = None,
    ):
        self._db_path = db_path
        self._cities = cities or list(CITIES.keys())
        self._poll_interval = poll_interval

        # Pick defaults from settings based on trading mode
        settings = get_settings()
        self._forecast_interval = forecast_interval or settings.forecast_interval_seconds
        if edge_threshold is not None:
            self._edge_threshold = edge_threshold
        elif settings.trading_mode == "paper":
            self._edge_threshold = settings.paper_edge_threshold_pct / 100
        else:
            self._edge_threshold = settings.edge_threshold_pct / 100

        # Components (initialized in start())
        self._engine: "Engine | None" = None
        self._registry: MarketRegistry | None = None
        self._gamma: GammaClient | None = None
        self._open_meteo: OpenMeteoClient | None = None
        self._price_tracker: PriceTracker | None = None
        self._broadcaster: SignalBroadcaster | None = None
        self._event_discovery: EventDiscoveryTask | None = None
        self._signal_generator: SignalGeneratorTask | None = None

        self._running = False
        self._shutdown_event = asyncio.Event()

    def _init_components(self) -> None:
        """Initialize all components."""
        # Database
        self._engine = create_engine(f"sqlite:///{self._db_path}", echo=False)
        Base.metadata.create_all(self._engine)

        # Registry
        self._registry = MarketRegistry(self._engine)

        # Clients
        self._gamma = GammaClient()
        self._open_meteo = OpenMeteoClient()

        # Broadcaster
        self._broadcaster = SignalBroadcaster(reputation_store=ReputationStore())

        # Price tracker
        self._price_tracker = PriceTracker(registry=self._registry)

        # Tasks
        self._event_discovery = EventDiscoveryTask(
            gamma_client=self._gamma,
            registry=self._registry,
            price_tracker=self._price_tracker,
            cities=self._cities,
            poll_interval=self._poll_interval,
        )

        settings = get_settings()
        self._signal_generator = SignalGeneratorTask(
            registry=self._registry,
            open_meteo_client=self._open_meteo,
            broadcaster=self._broadcaster,
            engine=self._engine,
            edge_threshold=self._edge_threshold,
            forecast_interval=self._forecast_interval,
            signal_preview_ttl_minutes=settings.signal_preview_ttl_minutes,
            producer_id=settings.polymarket_wallet_address or "anonymous",
        )

        logger.info(
            "Components initialized",
            cities=self._cities,
            db_path=self._db_path,
            edge_threshold=f"{self._edge_threshold:.0%}",
        )

    def _setup_signal_handlers(self) -> None:
        """Setup graceful shutdown handlers."""
        loop = asyncio.get_running_loop()

        def handle_signal() -> None:
            logger.info("Shutdown signal received")
            self._shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

    async def _wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()

    async def _run_tasks(self) -> None:
        """Run all tasks concurrently."""
        tasks = [
            asyncio.create_task(self._event_discovery.run(), name="event_discovery"),
            asyncio.create_task(self._price_tracker.run(), name="price_tracker"),
            asyncio.create_task(self._signal_generator.run(), name="signal_generator"),
            asyncio.create_task(self._wait_for_shutdown(), name="shutdown_monitor"),
        ]

        try:
            # Wait for shutdown or any task to fail
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Check if a task failed (not shutdown)
            for task in done:
                if task.get_name() != "shutdown_monitor":
                    exc = task.exception()
                    if exc:
                        logger.error(
                            "Task failed",
                            task=task.get_name(),
                            error=str(exc),
                        )

        finally:
            # Stop all tasks
            self._event_discovery.stop()
            self._signal_generator.stop()
            self._price_tracker.stop()

            # Cancel remaining tasks
            for task in pending:
                task.cancel()

            # Wait for cleanup
            await asyncio.gather(*pending, return_exceptions=True)

    async def run(self) -> None:
        """Run the orchestrator (main entry point)."""
        self._running = True
        logger.info("Producer orchestrator starting")

        try:
            self._init_components()
            self._setup_signal_handlers()
            await self._run_tasks()
        except Exception as e:
            logger.error("Orchestrator error", error=str(e))
            raise
        finally:
            self._running = False
            logger.info("Producer orchestrator stopped")

    @property
    def registry(self) -> MarketRegistry | None:
        """Get the market registry (for testing/inspection)."""
        return self._registry

    @property
    def broadcaster(self) -> SignalBroadcaster | None:
        """Get the broadcaster (for WebSocket server integration)."""
        return self._broadcaster


async def run_producer(
    db_path: str = DEFAULT_DB_PATH,
    cities: list[str] | None = None,
) -> None:
    """Convenience function to run the producer."""
    orchestrator = ProducerOrchestrator(db_path=db_path, cities=cities)
    await orchestrator.run()
