"""Polymarket Gamma API client."""

from datetime import date, timedelta
from typing import TYPE_CHECKING
import httpx

if TYPE_CHECKING:
    from .markets import WeatherEvent
    from .tsa_markets import TSAEvent


GAMMA_API_URL = "https://gamma-api.polymarket.com"


class GammaClient:
    """Client for Polymarket Gamma API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.base_url = GAMMA_API_URL

    async def fetch_event_by_slug(self, slug: str) -> dict | None:
        """
        Fetch any event by its slug.

        Args:
            slug: Event slug

        Returns:
            Event data dict or None if not found
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/events/slug/{slug}")

            if resp.status_code == 404:
                return None

            resp.raise_for_status()
            return resp.json()

    async def fetch_event_by_id(self, event_id: str) -> dict | None:
        """
        Fetch any event by its ID.

        Args:
            event_id: Event ID

        Returns:
            Event data dict or None if not found
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/events/{event_id}")

            if resp.status_code == 404:
                return None

            resp.raise_for_status()
            return resp.json()

    # Weather-specific convenience methods
    # These could move to a weather-specific client, but kept here for now

    def _build_weather_slug(self, city: str, target_date: date) -> str:
        """Build the weather event slug."""
        month = target_date.strftime("%B").lower()
        day = target_date.day
        year = target_date.year
        return f"highest-temperature-in-{city}-on-{month}-{day}-{year}"

    async def fetch_weather_event(
        self, city: str, target_date: date
    ) -> "WeatherEvent | None":
        """
        Fetch a weather event for a specific city and date.

        Args:
            city: City slug (e.g., "nyc", "chicago")
            target_date: Target date for the forecast

        Returns:
            WeatherEvent or None if not found
        """
        # Lazy import to avoid circular dependency
        from .markets import parse_weather_event

        slug = self._build_weather_slug(city, target_date)
        data = await self.fetch_event_by_slug(slug)

        if data is None:
            return None

        return parse_weather_event(data, city, target_date)

    async def discover_weather_events(
        self, cities: list[str], days_ahead: int = 7
    ) -> list["WeatherEvent"]:
        """
        Discover all active weather events for given cities.

        Args:
            cities: List of city slugs to check
            days_ahead: How many days ahead to look

        Returns:
            List of active WeatherEvents
        """
        events = []
        today = date.today()

        for city in cities:
            for day_offset in range(1, days_ahead + 1):
                target = today + timedelta(days=day_offset)
                event = await self.fetch_weather_event(city, target)

                if event and not event.closed and event.active_buckets:
                    events.append(event)

        return events

    # TSA-specific methods

    def _build_tsa_slug(self, target_date: date) -> str:
        """Build the TSA event slug."""
        month = target_date.strftime("%B").lower()
        day = target_date.day
        return f"number-of-tsa-passengers-{month}-{day}"

    async def fetch_tsa_event(self, target_date: date) -> "TSAEvent | None":
        """
        Fetch a TSA event for a specific date.

        Args:
            target_date: Target date for the passenger count

        Returns:
            TSAEvent or None if not found
        """
        # Lazy import to avoid circular dependency
        from .tsa_markets import parse_tsa_event

        slug = self._build_tsa_slug(target_date)
        data = await self.fetch_event_by_slug(slug)

        if data is None:
            return None

        return parse_tsa_event(data, target_date)

    async def discover_tsa_events(self, days_ahead: int = 3) -> list["TSAEvent"]:
        """
        Discover all active TSA events for the next N days.

        Args:
            days_ahead: How many days ahead to look

        Returns:
            List of active TSAEvents
        """
        events = []
        today = date.today()

        for day_offset in range(1, days_ahead + 1):
            target = today + timedelta(days=day_offset)
            event = await self.fetch_tsa_event(target)

            if event and not event.closed and event.active_markets:
                events.append(event)

        return events
