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
    event_id: str
    token_id: str
    side: Side
    market_description: str
    resolution_source: str  # e.g., wunderground URL
    market_price: float  # 0-1
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
