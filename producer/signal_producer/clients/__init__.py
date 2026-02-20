"""External API clients."""
from .gamma import GammaClient
from .noaa_cdo import NOAACDOClient, CITY_STATIONS
from .markets import WeatherEvent, WeatherMarket, parse_weather_event, parse_temp_range, calculate_market_probability
from .open_meteo import OpenMeteoClient, EnsembleForecast

__all__ = [
    "GammaClient",
    "NOAACDOClient",
    "CITY_STATIONS",
    "WeatherEvent",
    "WeatherMarket",
    "parse_weather_event",
    "parse_temp_range",
    "calculate_market_probability",
    "OpenMeteoClient",
    "EnsembleForecast",
]
