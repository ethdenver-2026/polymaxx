"""Backtesting module for historical strategy evaluation."""

from .engine import BacktestEngine, BacktestResult, TradeResult
from ..strategies.weather.open_meteo import OpenMeteoClient, EnsembleForecast

# Legacy GEFS client (not recommended - has systematic bias)
from .gefs import GEFSClient

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "TradeResult",
    "OpenMeteoClient",
    "EnsembleForecast",
    "GEFSClient",  # Legacy
]
