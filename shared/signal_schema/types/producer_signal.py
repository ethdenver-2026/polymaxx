"""Typed signal structures for the producer.

See design doc: docs/plans/2026-02-19-producer-signal-architecture-design.md
"""

from dataclasses import dataclass, asdict
from typing import Literal, TypedDict


# Type aliases for clarity
SignalType = Literal["weather"]
ForecastSource = Literal["open_meteo", "noaa"]
Side = Literal["yes", "no"]


# === Typed Metadata (per signal_type) ===


class WeatherMetadata(TypedDict):
    """Metadata for weather signals."""

    city: str
    target_date: str  # ISO date string "2026-02-20"
    ensemble_mean: float
    ensemble_std: float
    members_in_range: int  # e.g., 12 of 31


# === Exchange-Specific Market Info ===


class PolymarketInfo(TypedDict):
    """Polymarket-specific market information."""

    exchange: Literal["polymarket"]

    # Event level (from Gamma API /events)
    event_id: str  # e.g., "216598"
    event_title: str  # e.g., "Highest temperature in NYC on February 21?"
    resolution_source: str  # e.g., wunderground URL

    # Market level (from Gamma API /events -> markets[])
    market_question: str  # e.g., "Will the highest temperature be 39°F or below?"
    market_group_item_title: str  # e.g., "39°F or below" (short label)

    # Trading info
    token_id: str  # CLOB token ID for the side we're trading
    side: Side  # "yes" or "no"
    market_price: float  # 0-1, price for our side
    edge: float  # model_prob - market_price (adjusted for side)
    price_timestamp: str  # ISO timestamp


# === Canonical Producer Signal ===


@dataclass
class ProducerSignal:
    """
    Canonical signal emitted by the producer.

    Exchange-agnostic core prediction with typed metadata
    and exchange-specific market info.
    """

    # Type discriminator
    signal_type: SignalType

    # Core prediction (exchange-agnostic)
    model_probability: float
    confidence: float

    # Source info
    forecast_source: ForecastSource
    forecast_time: str  # ISO timestamp

    # Typed metadata (based on signal_type)
    metadata: WeatherMetadata

    # Exchange-specific (one signal can map to multiple exchanges)
    exchanges: list[PolymarketInfo]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)
