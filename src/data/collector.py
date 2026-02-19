"""Ensemble forecast data collector.

Collects and stores Open-Meteo ensemble forecasts for backtesting.
Run daily to build up historical ensemble data.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from dataclasses import dataclass, asdict

import structlog

from ..config import CITIES, CityConfig
from ..strategies.weather.open_meteo import OpenMeteoClient, EnsembleForecast

logger = structlog.get_logger()

# Default storage location
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "ensemble_forecasts"


@dataclass
class StoredForecast:
    """Forecast record for storage."""

    city: str
    forecast_date: str  # ISO format
    target_date: str    # ISO format
    member_highs: list[float]  # 31 daily high temps
    mean: float
    std: float
    min_temp: float
    max_temp: float

    @classmethod
    def from_ensemble(cls, forecast: EnsembleForecast, forecast_date: date) -> "StoredForecast":
        """Create storage record from EnsembleForecast."""
        return cls(
            city=forecast.city,
            forecast_date=forecast_date.isoformat(),
            target_date=forecast.target_date.isoformat(),
            member_highs=forecast.member_highs,
            mean=forecast.mean,
            std=forecast.std,
            min_temp=forecast.min,
            max_temp=forecast.max,
        )


class ForecastCollector:
    """Collects and stores ensemble forecasts."""

    def __init__(
        self,
        data_dir: Path | None = None,
        client: OpenMeteoClient | None = None,
    ):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.client = client or OpenMeteoClient()

    def _get_file_path(self, city: str, target_date: date) -> Path:
        """Get storage path for a forecast."""
        return self.data_dir / f"{city}_{target_date.isoformat()}.json"

    def _forecast_exists(self, city: str, target_date: date) -> bool:
        """Check if forecast already exists."""
        return self._get_file_path(city, target_date).exists()

    def _save_forecast(self, forecast: StoredForecast) -> None:
        """Save forecast to JSON file."""
        path = self._get_file_path(
            forecast.city,
            date.fromisoformat(forecast.target_date),
        )
        with open(path, "w") as f:
            json.dump(asdict(forecast), f, indent=2)
        logger.info(
            "Saved forecast",
            city=forecast.city,
            target_date=forecast.target_date,
            path=str(path),
        )

    def load_forecast(self, city: str, target_date: date) -> StoredForecast | None:
        """Load a stored forecast."""
        path = self._get_file_path(city, target_date)
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        return StoredForecast(**data)

    async def collect_forecast(
        self,
        city: str,
        city_config: CityConfig,
        target_date: date,
        force: bool = False,
    ) -> StoredForecast | None:
        """Collect and store ensemble forecast for a city/date.

        Args:
            city: City slug
            city_config: City configuration
            target_date: Date to forecast
            force: Overwrite existing data

        Returns:
            StoredForecast if successful, None otherwise
        """
        if not force and self._forecast_exists(city, target_date):
            logger.debug("Forecast already exists", city=city, target_date=str(target_date))
            return self.load_forecast(city, target_date)

        forecast_date = date.today()

        try:
            ensemble = await self.client.get_ensemble_forecast(
                lat=city_config.lat,
                lon=city_config.lon,
                target_date=target_date,
                timezone=city_config.tz,
                city=city,
            )
        except Exception as e:
            logger.error(
                "Failed to fetch forecast",
                city=city,
                target_date=str(target_date),
                error=str(e),
            )
            return None

        stored = StoredForecast.from_ensemble(ensemble, forecast_date)
        self._save_forecast(stored)
        return stored

    async def collect_all(
        self,
        cities: list[str] | None = None,
        days_ahead: int = 1,
        force: bool = False,
    ) -> dict[str, StoredForecast]:
        """Collect forecasts for all cities.

        Args:
            cities: List of city slugs (defaults to all)
            days_ahead: How many days ahead to forecast (default 1 = tomorrow)
            force: Overwrite existing data

        Returns:
            Dict mapping city to StoredForecast
        """
        city_slugs = cities or list(CITIES.keys())
        target_date = date.today() + timedelta(days=days_ahead)

        logger.info(
            "Collecting forecasts",
            cities=city_slugs,
            target_date=str(target_date),
        )

        results = {}
        for city in city_slugs:
            config = CITIES.get(city)
            if not config:
                logger.warning("Unknown city", city=city)
                continue

            forecast = await self.collect_forecast(city, config, target_date, force)
            if forecast:
                results[city] = forecast

        logger.info(
            "Collection complete",
            collected=len(results),
            total=len(city_slugs),
        )
        return results

    def list_forecasts(self) -> list[tuple[str, date]]:
        """List all stored forecasts."""
        forecasts = []
        for path in self.data_dir.glob("*.json"):
            parts = path.stem.split("_")
            if len(parts) >= 2:
                city = "_".join(parts[:-1])
                try:
                    target_date = date.fromisoformat(parts[-1])
                    forecasts.append((city, target_date))
                except ValueError:
                    continue
        return sorted(forecasts, key=lambda x: (x[1], x[0]))
