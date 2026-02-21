"""External API clients."""

from .polymarket import (
    GammaClient,
    WeatherEvent,
    WeatherMarket,
    parse_weather_event,
    parse_temp_range,
    calculate_market_probability,
)
from .weather import (
    OpenMeteoClient,
    EnsembleForecast,
    NOAACDOClient,
    CITY_STATIONS,
)

__all__ = [
    "GammaClient",
    "WeatherEvent",
    "WeatherMarket",
    "parse_weather_event",
    "parse_temp_range",
    "calculate_market_probability",
    "OpenMeteoClient",
    "EnsembleForecast",
    "NOAACDOClient",
    "CITY_STATIONS",
]
