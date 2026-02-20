"""Backtesting module for historical strategy evaluation."""

from .engine import BacktestEngine, BacktestResult, TradeResult
from .error_analysis import (
    ErrorAnalyzer,
    ForecastErrorStats,
    build_all_error_stats,
)
from .price_history import PriceHistoryClient, PricePoint
from ..strategies.weather.open_meteo import OpenMeteoClient, EnsembleForecast

# Legacy GEFS client (not recommended - has systematic bias)
from .gefs import GEFSClient

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "TradeResult",
    "ErrorAnalyzer",
    "ForecastErrorStats",
    "build_all_error_stats",
    "PriceHistoryClient",
    "PricePoint",
    "OpenMeteoClient",
    "EnsembleForecast",
    "GEFSClient",  # Legacy
]
