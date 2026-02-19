"""NOAA Weather API client for observations."""

from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
import httpx


NOAA_API_URL = "https://api.weather.gov"


@dataclass
class Observation:
    """A single weather observation."""

    station: str
    timestamp: datetime
    temperature_c: float | None
    temperature_f: float | None

    @classmethod
    def from_celsius(cls, station: str, timestamp: datetime, temp_c: float | None):
        """Create observation from Celsius temperature."""
        temp_f = None
        if temp_c is not None:
            temp_f = temp_c * 9 / 5 + 32
        return cls(
            station=station,
            timestamp=timestamp,
            temperature_c=temp_c,
            temperature_f=temp_f,
        )


@dataclass
class DailyObservation:
    """Aggregated daily observation with high/low."""

    station: str
    date: date
    high_f: float
    low_f: float
    observation_count: int


class NOAAClient:
    """Client for NOAA Weather API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "(prediction-market-bot, contact@example.com)",
            "Accept": "application/geo+json",
        }

    async def get_latest_observation(self, station: str) -> Observation | None:
        """
        Get the latest observation from a weather station.

        Args:
            station: Station ID (e.g., "KLGA")

        Returns:
            Observation or None if unavailable
        """
        url = f"{NOAA_API_URL}/stations/{station}/observations/latest"

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.headers
        ) as client:
            resp = await client.get(url)

            if resp.status_code != 200:
                return None

            data = resp.json()

        return self._parse_observation(station, data)

    def _parse_observation(self, station: str, data: dict) -> Observation | None:
        """Parse observation JSON."""
        props = data.get("properties", {})
        temp_data = props.get("temperature", {})
        temp_c = temp_data.get("value")

        timestamp_str = props.get("timestamp")
        if not timestamp_str:
            return None

        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except ValueError:
            return None

        return Observation.from_celsius(station, timestamp, temp_c)

    async def get_observations_range(
        self, station: str, start: datetime, end: datetime
    ) -> list[Observation]:
        """
        Get observations for a time range.

        Args:
            station: Station ID
            start: Start time (UTC)
            end: End time (UTC)

        Returns:
            List of observations
        """
        url = f"{NOAA_API_URL}/stations/{station}/observations"
        params = {
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self.headers
        ) as client:
            resp = await client.get(url, params=params)

            if resp.status_code != 200:
                return []

            data = resp.json()

        observations = []
        for feature in data.get("features", []):
            obs = self._parse_observation(station, feature)
            if obs:
                observations.append(obs)

        return observations

    async def get_daily_high(
        self, station: str, target_date: date
    ) -> DailyObservation | None:
        """
        Get daily high/low for a specific date.

        Args:
            station: Station ID
            target_date: Date to get observations for

        Returns:
            DailyObservation or None
        """
        # Get observations for the full day (UTC)
        start = datetime(
            target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc
        )
        end = start + timedelta(days=1)

        observations = await self.get_observations_range(station, start, end)

        # Filter to only valid temperature readings
        temps_f = [obs.temperature_f for obs in observations if obs.temperature_f is not None]

        if not temps_f:
            return None

        return DailyObservation(
            station=station,
            date=target_date,
            high_f=max(temps_f),
            low_f=min(temps_f),
            observation_count=len(temps_f),
        )
