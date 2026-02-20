"""Forecast error distribution analysis for Option D backtesting.

Builds empirical error distributions by comparing Open-Meteo Previous Runs API
forecasts with actual NOAA observations. These distributions are used to
generate synthetic ensembles for backtesting.

IMPORTANT: Previous Runs API data only available from Jan 2024 onwards.
This gives us ~13 months of error data, not multi-year historical records.

See: docs/SYNTHETIC_ENSEMBLES.md for transition plan to real collected ensembles.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
import structlog

from ..clients.noaa_cdo import NOAACDOClient, CITY_STATIONS


logger = structlog.get_logger()

# Previous Runs API URL
# NOTE: Data only available from Jan 2024 onwards
PREVIOUS_RUNS_API_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"


@dataclass
class ForecastErrorStats:
    """Error statistics for a specific city and lead time.

    Used to generate synthetic ensembles from deterministic forecasts.
    """
    city: str
    lead_days: int  # 1, 2, or 3
    mean_error: float  # Bias (positive = forecast too warm)
    std_error: float   # Standard deviation of errors
    sample_count: int

    def __repr__(self) -> str:
        return (
            f"ForecastErrorStats(city={self.city!r}, lead_days={self.lead_days}, "
            f"mean_error={self.mean_error:.2f}°F, std_error={self.std_error:.2f}°F, "
            f"n={self.sample_count})"
        )


class ErrorAnalyzer:
    """Analyze historical forecast errors to build realistic error distributions.

    Uses Open-Meteo Previous Runs API for past forecasts and NOAA CDO API
    for actual observations.

    # TEMPORARY: Using Previous Runs API (deterministic) + error distributions
    # TODO(after-2w-collection): Replace with ForecastCollector.load_forecast()
    # See: docs/SYNTHETIC_ENSEMBLES.md "Phase 2: Real Ensemble Transition"
    """

    def __init__(
        self,
        noaa_client: NOAACDOClient | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize error analyzer.

        Args:
            noaa_client: NOAA CDO client. If None, will create one (requires NOAA_CDO_TOKEN).
            timeout: HTTP request timeout in seconds.
        """
        self.noaa_client = noaa_client
        self.timeout = timeout

    def _ensure_noaa_client(self) -> NOAACDOClient:
        """Ensure NOAA client is initialized."""
        if self.noaa_client is None:
            self.noaa_client = NOAACDOClient(timeout=self.timeout)
        return self.noaa_client

    async def fetch_previous_run_forecast(
        self,
        lat: float,
        lon: float,
        target_date: date,
        lead_days: int,
        timezone: str,
    ) -> float | None:
        """
        Get what the model predicted N days ago for target_date.

        Uses the Previous Runs API with temperature_2m_previous_dayN variables.

        NOTE: Data only available from Jan 2024 onwards.

        Args:
            lat: Latitude
            lon: Longitude
            target_date: Date we want the forecast for
            lead_days: How many days in advance (1-5)
            timezone: Timezone string (e.g., "America/New_York")

        Returns:
            Forecasted daily high temperature in Fahrenheit, or None if unavailable
        """
        if lead_days < 1 or lead_days > 5:
            logger.warning("lead_days must be 1-5", lead_days=lead_days)
            return None

        # Build the variable name for the historical forecast
        # previous_day1 = forecast from ~24 hours ago
        # previous_day2 = forecast from ~48 hours ago, etc.
        prev_var = f"temperature_2m_previous_day{lead_days}"

        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": f"temperature_2m,{prev_var}",
            "temperature_unit": "fahrenheit",
            "timezone": timezone,
            "start_date": str(target_date),
            "end_date": str(target_date),
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(PREVIOUS_RUNS_API_URL, params=params)

                if resp.status_code != 200:
                    logger.debug(
                        "Previous Runs API error",
                        status_code=resp.status_code,
                        target_date=str(target_date),
                        lead_days=lead_days,
                    )
                    return None

                data = resp.json()

            hourly = data.get("hourly", {})
            times = hourly.get("time", [])
            prev_temps = hourly.get(prev_var, [])

            if not times or not prev_temps:
                logger.debug(
                    "No previous run data",
                    target_date=str(target_date),
                    lead_days=lead_days,
                    available_keys=list(hourly.keys()),
                )
                return None

            # Filter out None values and get daily high
            valid_temps = [t for t in prev_temps if t is not None]
            if not valid_temps:
                return None

            return max(valid_temps)

        except Exception as e:
            logger.warning(
                "Failed to fetch previous run",
                error=str(e),
                target_date=str(target_date),
                lead_days=lead_days,
            )
            return None

    async def build_error_distribution(
        self,
        city: str,
        lat: float,
        lon: float,
        timezone: str,
        start_date: date,
        end_date: date,
        lead_days: int = 1,
    ) -> ForecastErrorStats:
        """
        Compute error statistics for a city/lead_time by comparing
        Previous Runs forecasts to NOAA observations.

        Args:
            city: City slug (e.g., "nyc")
            lat: Latitude
            lon: Longitude
            timezone: Timezone string
            start_date: Start of analysis period
            end_date: End of analysis period
            lead_days: Forecast lead time in days (1, 2, or 3)

        Returns:
            ForecastErrorStats with mean bias and spread
        """
        noaa = self._ensure_noaa_client()

        errors: list[float] = []
        current = start_date

        while current <= end_date:
            target_date = current

            # Get what the forecast predicted (N days ago for target_date)
            forecast_temp = await self.fetch_previous_run_forecast(
                lat=lat,
                lon=lon,
                target_date=target_date,
                lead_days=lead_days,
                timezone=timezone,
            )

            # Get actual observation
            actual_temp = await noaa.get_city_high(city, target_date)

            if forecast_temp is not None and actual_temp is not None:
                error = forecast_temp - actual_temp  # Positive = too warm
                errors.append(error)

            current += timedelta(days=1)

        if not errors:
            logger.warning(
                "No error data collected",
                city=city,
                lead_days=lead_days,
                start_date=str(start_date),
                end_date=str(end_date),
            )
            # Return default conservative error stats
            return ForecastErrorStats(
                city=city,
                lead_days=lead_days,
                mean_error=0.0,
                std_error=3.0,  # Conservative default
                sample_count=0,
            )

        # Calculate statistics
        mean_error = sum(errors) / len(errors)
        variance = sum((e - mean_error) ** 2 for e in errors) / len(errors)
        std_error = variance ** 0.5

        logger.info(
            "Built error distribution",
            city=city,
            lead_days=lead_days,
            mean_error=f"{mean_error:.2f}°F",
            std_error=f"{std_error:.2f}°F",
            sample_count=len(errors),
        )

        return ForecastErrorStats(
            city=city,
            lead_days=lead_days,
            mean_error=mean_error,
            std_error=std_error,
            sample_count=len(errors),
        )

    def generate_synthetic_ensemble(
        self,
        deterministic_forecast: float,
        error_stats: ForecastErrorStats,
        n_members: int = 31,
        seed: int | None = None,
    ) -> list[float]:
        """
        Generate synthetic ensemble from error distribution.

        Applies bias correction and uses learned spread instead of
        hardcoded σ=2°F.

        # TEMPORARY: Using synthetic ensemble from error distributions
        # TODO(after-2w-collection): Replace with ForecastCollector.load_forecast()
        # See: docs/SYNTHETIC_ENSEMBLES.md "Phase 2: Real Ensemble Transition"

        Args:
            deterministic_forecast: The deterministic GFS forecast temperature
            error_stats: Learned error statistics for this city/lead_time
            n_members: Number of ensemble members to generate (default 31)
            seed: Optional random seed for reproducibility

        Returns:
            List of synthetic ensemble member temperatures
        """
        if seed is not None:
            random.seed(seed)

        # Apply bias correction (subtract mean error since error = forecast - actual)
        bias_corrected = deterministic_forecast - error_stats.mean_error

        # Generate members using learned spread
        members = [
            bias_corrected + random.gauss(0, error_stats.std_error)
            for _ in range(n_members)
        ]

        return members


async def build_all_error_stats(
    cities: dict[str, dict],
    start_date: date,
    end_date: date,
    lead_days_list: list[int] = [1, 2, 3],
    noaa_client: NOAACDOClient | None = None,
) -> dict[str, dict[int, ForecastErrorStats]]:
    """
    Build error statistics for all cities and lead times.

    Args:
        cities: Dict of city configs with lat, lon, tz keys
        start_date: Start of analysis period
        end_date: End of analysis period
        lead_days_list: List of lead times to analyze
        noaa_client: Optional NOAA client

    Returns:
        Nested dict: error_stats[city][lead_days] = ForecastErrorStats
    """
    analyzer = ErrorAnalyzer(noaa_client=noaa_client)
    all_stats: dict[str, dict[int, ForecastErrorStats]] = {}

    for city, config in cities.items():
        all_stats[city] = {}

        for lead_days in lead_days_list:
            stats = await analyzer.build_error_distribution(
                city=city,
                lat=config["lat"],
                lon=config["lon"],
                timezone=config["tz"],
                start_date=start_date,
                end_date=end_date,
                lead_days=lead_days,
            )
            all_stats[city][lead_days] = stats

    return all_stats
