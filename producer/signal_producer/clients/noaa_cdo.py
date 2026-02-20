"""NOAA Climate Data Online (CDO) API client for historical observations.

Uses the NCEI CDO API to fetch actual temperature observations from GHCN-Daily.
These observations match what Weather Underground uses for Polymarket resolution.

API Documentation: https://www.ncdc.noaa.gov/cdo-web/webservices/v2
Token required: https://www.ncei.noaa.gov/cdo-web/token (free)
"""

import os
from datetime import date

import httpx
import structlog


logger = structlog.get_logger()

NCEI_API_URL = "https://www.ncei.noaa.gov/cdo-web/api/v2"

# Station IDs for each city (GHCND format)
# These are the airport stations that match Polymarket resolution sources
CITY_STATIONS = {
    "nyc": "GHCND:USW00014732",  # KLGA - LaGuardia Airport
    "chicago": "GHCND:USW00094846",  # KORD - O'Hare
    "la": "GHCND:USW00023174",  # KLAX - Los Angeles International
    "miami": "GHCND:USW00012839",  # KMIA - Miami International
    "denver": "GHCND:USW00023062",  # KDEN - Denver International
    "seattle": "GHCND:USW00024233",  # KSEA - Seattle-Tacoma
    "atlanta": "GHCND:USW00013874",  # KATL - Hartsfield-Jackson
    "boston": "GHCND:USW00014739",  # KBOS - Logan International
    "phoenix": "GHCND:USW00023183",  # KPHX - Phoenix Sky Harbor
    "houston": "GHCND:USW00012960",  # KIAH - George Bush Intercontinental
    # International cities (Celsius, but we convert to Fahrenheit)
    "london": "GHCND:UKE00105723",  # Heathrow
    "paris": "GHCND:FRE00104388",  # Paris-Orly
    "tokyo": "GHCND:JA000047662",  # Tokyo (Haneda area)
}


def celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return c * 9 / 5 + 32


class NOAACDOClient:
    """Client for NOAA Climate Data Online API (historical observations).

    Fetches actual temperature observations from GHCN-Daily dataset.
    This is the authoritative source that matches Polymarket resolution.

    Requires NOAA_CDO_TOKEN environment variable.
    Get a free token at: https://www.ncei.noaa.gov/cdo-web/token
    """

    def __init__(self, token: str | None = None, timeout: float = 30.0):
        """
        Initialize NOAA CDO client.

        Args:
            token: NOAA CDO API token. If not provided, reads from NOAA_CDO_TOKEN env var.
            timeout: HTTP request timeout in seconds.
        """
        self.token = token or os.environ.get("NOAA_CDO_TOKEN")
        if not self.token:
            raise ValueError(
                "NOAA CDO API token required. "
                "Set NOAA_CDO_TOKEN environment variable or pass token parameter. "
                "Get a free token at: https://www.ncei.noaa.gov/cdo-web/token"
            )
        self.timeout = timeout
        self.base_url = NCEI_API_URL

    def _get_headers(self) -> dict[str, str]:
        """Get request headers with API token."""
        return {"token": self.token}

    async def get_daily_high(
        self, station_id: str, target_date: date
    ) -> float | None:
        """
        Get TMAX observation from GHCN-Daily dataset.

        Args:
            station_id: GHCND station ID (e.g., "GHCND:USW00014732")
            target_date: Date to fetch observation for

        Returns:
            High temperature in Fahrenheit, or None if not available
        """
        params = {
            "datasetid": "GHCND",
            "stationid": station_id,
            "datatypeid": "TMAX",
            "startdate": str(target_date),
            "enddate": str(target_date),
            "units": "standard",  # Request Fahrenheit
            "limit": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/data",
                    params=params,
                    headers=self._get_headers(),
                )

                if resp.status_code == 404:
                    return None

                resp.raise_for_status()
                data = resp.json()

                results = data.get("results", [])
                if not results:
                    logger.debug(
                        "No TMAX observation found",
                        station_id=station_id,
                        date=str(target_date),
                    )
                    return None

                # When units=standard is specified, NOAA returns temperature
                # already converted to Fahrenheit (not in tenths).
                # Native storage is tenths of °C, but the API does the conversion.
                tmax = results[0].get("value")
                if tmax is None:
                    return None

                return float(tmax)

        except httpx.HTTPStatusError as e:
            logger.warning(
                "NOAA CDO API error",
                status_code=e.response.status_code,
                station_id=station_id,
                date=str(target_date),
            )
            return None
        except Exception as e:
            logger.warning(
                "Failed to fetch NOAA observation",
                error=str(e),
                station_id=station_id,
                date=str(target_date),
            )
            return None

    async def get_city_high(self, city: str, target_date: date) -> float | None:
        """
        Get high temperature for a city on a specific date.

        Args:
            city: City slug (e.g., "nyc", "chicago")
            target_date: Date to fetch observation for

        Returns:
            High temperature in Fahrenheit, or None if not available
        """
        station_id = CITY_STATIONS.get(city)
        if not station_id:
            logger.warning(
                "Unknown city for NOAA lookup",
                city=city,
                known_cities=list(CITY_STATIONS.keys()),
            )
            return None

        return await self.get_daily_high(station_id, target_date)

    async def get_date_range(
        self, station_id: str, start_date: date, end_date: date
    ) -> list[tuple[date, float]]:
        """
        Get TMAX observations for a date range.

        Args:
            station_id: GHCND station ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            List of (date, temp_fahrenheit) tuples
        """
        params = {
            "datasetid": "GHCND",
            "stationid": station_id,
            "datatypeid": "TMAX",
            "startdate": str(start_date),
            "enddate": str(end_date),
            "units": "standard",
            "limit": 1000,  # Max allowed by API
        }

        results = []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/data",
                    params=params,
                    headers=self._get_headers(),
                )

                if resp.status_code == 404:
                    return results

                resp.raise_for_status()
                data = resp.json()

                for record in data.get("results", []):
                    obs_date = date.fromisoformat(record["date"][:10])
                    tmax = record.get("value")
                    if tmax is not None:
                        # units=standard returns Fahrenheit directly
                        results.append((obs_date, float(tmax)))

        except Exception as e:
            logger.warning(
                "Failed to fetch NOAA date range",
                error=str(e),
                station_id=station_id,
            )

        return results

    async def check_station_availability(self, station_id: str) -> bool:
        """
        Check if a station is available in GHCN-Daily.

        Args:
            station_id: GHCND station ID to check

        Returns:
            True if station exists and has data
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/stations/{station_id}",
                    headers=self._get_headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False
