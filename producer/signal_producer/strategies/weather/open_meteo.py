"""Open-Meteo Ensemble API client for weather forecasts."""

from datetime import date
from dataclasses import dataclass
import httpx


ENSEMBLE_API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
HISTORICAL_FORECAST_API_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"


@dataclass
class EnsembleForecast:
    """Ensemble forecast result with 31 member daily highs and full raw API response."""

    city: str
    target_date: date
    member_highs: list[float]  # 31 values (control + 30 members)
    # Complete raw API response - no data discarded
    raw_response: dict | None = None

    @property
    def mean(self) -> float:
        """Mean of all ensemble members."""
        return sum(self.member_highs) / len(self.member_highs)

    @property
    def std(self) -> float:
        """Standard deviation of ensemble members."""
        mean = self.mean
        variance = sum((t - mean) ** 2 for t in self.member_highs) / len(self.member_highs)
        return variance ** 0.5

    @property
    def min(self) -> float:
        """Minimum ensemble member forecast."""
        return min(self.member_highs)

    @property
    def max(self) -> float:
        """Maximum ensemble member forecast."""
        return max(self.member_highs)


class OpenMeteoClient:
    """Client for Open-Meteo Ensemble API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def get_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        target_date: date,
        timezone: str,
        city: str = "unknown",
    ) -> EnsembleForecast:
        """
        Fetch 31-member ensemble forecast for a specific date.

        Args:
            lat: Latitude
            lon: Longitude
            target_date: Date to forecast
            timezone: Timezone string (e.g., "America/New_York")
            city: City identifier for logging

        Returns:
            EnsembleForecast with 31 daily high temperatures
        """
        # Calculate forecast days needed
        days_out = (target_date - date.today()).days + 1

        params = {
            "latitude": lat,
            "longitude": lon,
            "models": "gfs_seamless",
            # Collect all potentially useful weather variables
            "hourly": ",".join([
                "temperature_2m",
                "apparent_temperature",
                "precipitation",
                "rain",
                "snowfall",
                "wind_speed_10m",
                "relative_humidity_2m",
                "cloud_cover",
            ]),
            "temperature_unit": "fahrenheit",
            "precipitation_unit": "inch",
            "wind_speed_unit": "mph",
            "timezone": timezone,
            "forecast_days": max(days_out, 1),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(ENSEMBLE_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        hourly = data["hourly"]
        times = hourly["time"]

        # Find indices for target date
        target_str = str(target_date)
        target_indices = [i for i, t in enumerate(times) if t.startswith(target_str)]

        if not target_indices:
            raise ValueError(f"No forecast data for {target_date}")

        # Collect all 31 member keys
        # Control run is "temperature_2m", members are "temperature_2m_member01" through "temperature_2m_member30"
        member_keys = ["temperature_2m"] + [
            f"temperature_2m_member{i:02d}" for i in range(1, 31)
        ]

        # Get daily max for each member
        member_highs = []
        for key in member_keys:
            if key not in hourly:
                raise ValueError(f"Missing ensemble member: {key}")
            temps_for_day = [hourly[key][i] for i in target_indices]
            daily_high = max(temps_for_day)
            member_highs.append(daily_high)

        return EnsembleForecast(
            city=city,
            target_date=target_date,
            member_highs=member_highs,
            raw_response=data,  # Keep entire API response
        )

    async def get_historical_forecast(
        self,
        lat: float,
        lon: float,
        forecast_date: date,
        target_date: date,
        timezone: str,
        city: str = "unknown",
    ) -> EnsembleForecast | None:
        """
        Fetch historical forecast from a past date.

        Uses Open-Meteo Historical Forecast API. Since ensemble data isn't
        available for past dates, we use the deterministic forecast and
        generate a synthetic ensemble based on typical forecast uncertainty.

        Args:
            lat: Latitude
            lon: Longitude
            forecast_date: Date when the forecast was made
            target_date: Date being forecasted
            timezone: Timezone string (e.g., "America/New_York")
            city: City identifier for logging

        Returns:
            EnsembleForecast with synthetic member temperatures, or None if unavailable
        """
        import random

        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": str(forecast_date),
            "end_date": str(target_date),
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": timezone,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(HISTORICAL_FORECAST_API_URL, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()

        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])

        if not times or not temps:
            return None

        # Find temperatures for target date
        target_str = str(target_date)
        target_temps = [
            temps[i] for i, t in enumerate(times)
            if t.startswith(target_str) and i < len(temps) and temps[i] is not None
        ]

        if not target_temps:
            return None

        # Get the best forecast daily high
        daily_high = max(target_temps)

        # Generate synthetic ensemble based on typical 24-hour forecast uncertainty
        # Research shows ~2°F MAE for 24-hour temperature forecasts
        # We use a normal distribution with std=2°F to simulate ensemble spread
        random.seed(int(forecast_date.toordinal() + lat * 100 + lon * 100))
        std_dev = 2.0  # Typical 24-hour forecast uncertainty

        member_highs = [
            daily_high + random.gauss(0, std_dev)
            for _ in range(31)
        ]

        return EnsembleForecast(
            city=city,
            target_date=target_date,
            member_highs=member_highs,
        )
