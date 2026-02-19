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


def parse_temp_range(question: str) -> tuple[float | None, float | None]:
    """
    Extract temperature range from market question.

    Returns (low, high) where:
    - "between 34-35°F" → (34, 36)  # high is exclusive
    - "31°F or below" → (None, 32)
    - "46°F or higher" → (46, None)
    """
    # "between 34-35°F" → (34, 36)
    match = re.search(r"between (\d+)-(\d+)", question)
    if match:
        return float(match.group(1)), float(match.group(2)) + 1

    # "31°F or below" → (None, 32)
    match = re.search(r"(\d+)°F or below", question)
    if match:
        return None, float(match.group(1)) + 1

    # "46°F or higher" or "46°F or above"
    match = re.search(r"(\d+)°F or (?:higher|above)", question)
    if match:
        return float(match.group(1)), None

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
