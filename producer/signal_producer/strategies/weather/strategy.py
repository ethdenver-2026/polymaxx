"""Weather prediction strategy using ensemble forecasts."""

from datetime import date
import structlog

from ...config import Settings, CITIES
from ...clients.gamma import GammaClient
from ..base import BaseStrategy, StrategyResult, Signal
from .open_meteo import OpenMeteoClient
from .signals import calculate_weather_signals


logger = structlog.get_logger()


class WeatherStrategy(BaseStrategy):
    """
    Strategy that compares ensemble weather forecasts to Polymarket prices.

    Uses 31-member GFS ensemble to estimate temperature probability distribution,
    then compares to market-implied probabilities to find mispriced buckets.
    """

    def __init__(
        self,
        settings: Settings,
        cities: list[str] | None = None,
    ):
        self.settings = settings
        self.city_slugs = cities or ["nyc", "chicago", "miami"]
        self.open_meteo = OpenMeteoClient()
        self.gamma = GammaClient()

    def get_name(self) -> str:
        return "weather"

    async def generate_signals(self) -> StrategyResult:
        """Generate signals for all active weather markets."""
        all_signals: list[Signal] = []
        events_checked = 0
        errors: list[str] = []

        # Discover active events
        try:
            events = await self.gamma.discover_weather_events(
                cities=self.city_slugs,
                days_ahead=self.settings.max_forecast_days,
            )
        except Exception as e:
            logger.error("Failed to discover events", error=str(e))
            return StrategyResult(signals=[], events_checked=0, errors=[str(e)])

        for event in events:
            events_checked += 1

            # Get city config
            city_config = CITIES.get(event.city)
            if not city_config:
                errors.append(f"Unknown city: {event.city}")
                continue

            # Skip if too far out (forecasts less reliable)
            days_out = (event.target_date - date.today()).days
            if days_out > self.settings.max_forecast_days:
                continue

            # Get ensemble forecast
            try:
                forecast = await self.open_meteo.get_ensemble_forecast(
                    lat=city_config.lat,
                    lon=city_config.lon,
                    target_date=event.target_date,
                    timezone=city_config.tz,
                    city=event.city,
                )
            except Exception as e:
                logger.warning(
                    "Failed to get forecast",
                    city=event.city,
                    date=str(event.target_date),
                    error=str(e),
                )
                errors.append(f"Forecast error for {event.city}: {e}")
                continue

            # Calculate signals
            signals = calculate_weather_signals(
                ensemble=forecast,
                event=event,
                bankroll=self.settings.bankroll_usdc,
                kelly_fraction=self.settings.kelly_fraction,
                max_position=self.settings.max_position_usd,
                edge_threshold=self.settings.edge_threshold_pct / 100,
            )

            for signal in signals:
                logger.info(
                    "Signal found",
                    city=signal.metadata.get("city"),
                    date=str(signal.target_date),
                    bucket=signal.description[:50],
                    edge_pct=f"{signal.edge_pct:.1f}%",
                    position=f"${signal.position_size_usd:.2f}",
                )

            all_signals.extend(signals)

        # Sort all signals by edge
        all_signals.sort(key=lambda s: s.edge, reverse=True)

        return StrategyResult(
            signals=all_signals,
            events_checked=events_checked,
            errors=errors,
        )
