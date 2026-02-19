"""Weather market data structures and parsing."""

import json
import re
from dataclasses import dataclass
from datetime import date


@dataclass
class WeatherBucket:
    """A single temperature bucket market."""

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
        """Check if a temperature falls within this bucket."""
        if self.low_temp is None:
            return temp < self.high_temp
        if self.high_temp is None:
            return temp >= self.low_temp
        return self.low_temp <= temp < self.high_temp


@dataclass
class WeatherEvent:
    """A weather prediction event with multiple temperature buckets."""

    event_id: str
    title: str
    city: str
    target_date: date
    resolution_source: str
    buckets: list[WeatherBucket]
    closed: bool

    @property
    def active_buckets(self) -> list[WeatherBucket]:
        """Return only active, non-closed buckets."""
        return [b for b in self.buckets if b.active and not b.closed]


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
    buckets = []

    for market in data.get("markets", []):
        question = market.get("question", "")
        low, high = parse_temp_range(question)

        # Parse JSON strings (CRITICAL: these are JSON strings, not arrays)
        try:
            prices = json.loads(market.get("outcomePrices", "[]"))
            tokens = json.loads(market.get("clobTokenIds", "[]"))
        except json.JSONDecodeError:
            continue

        if len(prices) < 2 or len(tokens) < 2:
            continue

        buckets.append(
            WeatherBucket(
                question=question,
                low_temp=low,
                high_temp=high,
                yes_price=float(prices[0]),
                no_price=float(prices[1]),
                yes_token_id=tokens[0],
                no_token_id=tokens[1],
                active=market.get("active", True),
                closed=market.get("closed", False),
            )
        )

    return WeatherEvent(
        event_id=data.get("id", ""),
        title=data.get("title", ""),
        city=city,
        target_date=target_date,
        resolution_source=data.get("resolutionSource", ""),
        buckets=buckets,
        closed=data.get("closed", False),
    )
