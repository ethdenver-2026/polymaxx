"""Event discovery task.

Polls Gamma API for new weather events and registers them with the registry.
"""

import asyncio
from typing import TYPE_CHECKING

import structlog

from ..config import DEFAULT_CITIES

if TYPE_CHECKING:
    from ..clients.gamma import GammaClient
    from ..registry.market_registry import MarketRegistry
    from ..tracker.price_tracker import PriceTracker

logger = structlog.get_logger()

DEFAULT_POLL_INTERVAL = 10  # seconds
DEFAULT_DAYS_AHEAD = 4


class EventDiscoveryTask:
    """
    Discovers new weather events by polling Gamma API.

    When new events are found:
    1. Registers them with MarketRegistry
    2. Subscribes to new tokens via PriceTracker
    """

    def __init__(
        self,
        gamma_client: "GammaClient",
        registry: "MarketRegistry",
        price_tracker: "PriceTracker | None" = None,
        cities: list[str] | None = None,
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
    ):
        self._gamma = gamma_client
        self._registry = registry
        self._price_tracker = price_tracker
        self._cities = cities or DEFAULT_CITIES
        self._days_ahead = days_ahead
        self._poll_interval = poll_interval
        self._running = False

    async def _discover_once(self) -> int:
        """
        Run one discovery cycle.

        Returns:
            Number of new events discovered
        """
        try:
            events = await self._gamma.discover_weather_events(
                cities=self._cities,
                days_ahead=self._days_ahead,
            )
        except Exception as e:
            logger.warning("Failed to discover events", error=str(e))
            return 0

        new_events = 0

        for event in events:
            # Register with registry (returns new token IDs if new)
            new_tokens = self._registry.register_event(event)

            if new_tokens:
                new_events += 1

                # Subscribe to new tokens for price updates
                if self._price_tracker:
                    await self._price_tracker.subscribe_tokens(new_tokens)

                logger.info(
                    "Discovered new event",
                    event_id=event.event_id,
                    city=event.city,
                    target_date=str(event.target_date),
                    tokens=len(new_tokens),
                )

        return new_events

    async def run(self) -> None:
        """Run the discovery task (polls continuously)."""
        self._running = True
        logger.info(
            "Event discovery starting",
            cities=self._cities,
            poll_interval=self._poll_interval,
        )

        while self._running:
            await self._discover_once()
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        """Stop the discovery task."""
        self._running = False
        logger.info("Event discovery stopping")
