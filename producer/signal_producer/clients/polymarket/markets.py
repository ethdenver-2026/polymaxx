"""Weather market data structures and parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..weather.open_meteo import EnsembleForecast


@dataclass
class WeatherMarket:
    """A single temperature range market."""

    question: str
    low_temp: float | None  # None for "X or below"
    high_temp: float | None  # None for "X or above"
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    active: bool
    closed: bool

    def contains_temp(self, temp: float) -> bool:
        """Check if a temperature falls within this market range."""
        if self.low_temp is None:
            return temp < self.high_temp
        if self.high_temp is None:
            return temp >= self.low_temp
        return self.low_temp <= temp < self.high_temp


@dataclass
class WeatherEvent:
    """A weather prediction event with multiple temperature markets."""

    event_id: str
    title: str
    city: str
    target_date: date
    resolution_source: str
    markets: list[WeatherMarket]
    closed: bool

    @property
    def active_markets(self) -> list[WeatherMarket]:
        """Return only active, non-closed markets."""
        return [m for m in self.markets if m.active and not m.closed]

    # Backwards compatibility aliases
    @property
    def buckets(self) -> list[WeatherMarket]:
        """Deprecated: Use markets instead."""
        return self.markets

    @property
    def active_buckets(self) -> list[WeatherMarket]:
        """Deprecated: Use active_markets instead."""
        return self.active_markets


def _celsius_to_fahrenheit(c: float) -> float:
    """Convert Celsius to Fahrenheit."""
    return c * 9 / 5 + 32


def parse_temp_range(question: str) -> tuple[float | None, float | None]:
    """
    Extract temperature range from market question.

    Handles both Fahrenheit (US cities) and Celsius (international cities).
    Returns temperatures normalized to Fahrenheit for consistent comparison.

    Returns (low, high) where:
    - "between 34-35°F" → (34, 36)  # high is exclusive
    - "between 5-6°C" → (41.0, 44.6)  # converted to F, high exclusive
    - "31°F or below" → (None, 32)
    - "5°C or below" → (None, 42.8)  # 6°C in F
    - "46°F or higher" → (46, None)
    - "10°C or higher" → (50, None)
    """
    # Detect unit - check for °C first since some questions have both symbols
    is_celsius = "°C" in question

    # "between 34-35°F" or "between 5-6°C" → (low, high+1)
    match = re.search(r"between (\d+)-(\d+)", question)
    if match:
        low = float(match.group(1))
        high = float(match.group(2)) + 1
        if is_celsius:
            return _celsius_to_fahrenheit(low), _celsius_to_fahrenheit(high)
        return low, high

    # "31°F or below" or "5°C or below" → (None, val+1)
    match = re.search(r"(\d+)°[FC] or below", question)
    if match:
        val = float(match.group(1)) + 1
        if is_celsius:
            return None, _celsius_to_fahrenheit(val)
        return None, val

    # "46°F or higher" or "10°C or higher" or "or above"
    match = re.search(r"(\d+)°[FC] or (?:higher|above)", question)
    if match:
        val = float(match.group(1))
        if is_celsius:
            return _celsius_to_fahrenheit(val), None
        return val, None

    # Single-degree Celsius buckets: "be 6°C on" → (6, 7) in C → (42.8, 44.6) in F
    # This format is used for international cities
    match = re.search(r"be (\d+)°C on", question)
    if match:
        val = float(match.group(1))
        return _celsius_to_fahrenheit(val), _celsius_to_fahrenheit(val + 1)

    return None, None


def parse_weather_event(data: dict, city: str, target_date: date) -> WeatherEvent:
    """Parse Gamma API event JSON into WeatherEvent."""
    weather_markets = []

    for market_data in data.get("markets", []):
        question = market_data.get("question", "")
        low, high = parse_temp_range(question)

        # Parse JSON strings (CRITICAL: these are JSON strings, not arrays)
        try:
            prices = json.loads(market_data.get("outcomePrices", "[]"))
            tokens = json.loads(market_data.get("clobTokenIds", "[]"))
        except json.JSONDecodeError:
            continue

        if len(prices) < 2 or len(tokens) < 2:
            continue

        weather_markets.append(
            WeatherMarket(
                question=question,
                low_temp=low,
                high_temp=high,
                yes_price=float(prices[0]),
                no_price=float(prices[1]),
                yes_token_id=tokens[0],
                no_token_id=tokens[1],
                active=market_data.get("active", True),
                closed=market_data.get("closed", False),
            )
        )

    return WeatherEvent(
        event_id=data.get("id", ""),
        title=data.get("title", ""),
        city=city,
        target_date=target_date,
        resolution_source=data.get("resolutionSource", ""),
        markets=weather_markets,
        closed=data.get("closed", False),
    )


def calculate_market_probability(
    ensemble: EnsembleForecast,
    market: WeatherMarket,
) -> float:
    """
    Calculate probability that the actual temperature falls in this market range.

    Uses ensemble member counts: P = (members in range) / (total members)
    """
    count = sum(1 for temp in ensemble.member_highs if market.contains_temp(temp))
    return count / len(ensemble.member_highs)
