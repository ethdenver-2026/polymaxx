from dataclasses import dataclass, asdict
from typing import Literal, TypedDict


# Type aliases for clarity
SignalType = Literal["weather"]


class PreviewPolymarketInfo(TypedDict):
    """Limited PolyMarket data to tell consumers what you have without revealing the content."""

    exchange: Literal["polymarket"]
    event_id: str
    edge: float  # model_prob - market_price (adjusted for side)
    price_timestamp: str  # ISO timestamp


# SignalPreview message (inform clients of what you have to let them auction on a price)


@dataclass
class ProducerSignalPreview:
    """
    Signal preview the producer sends to consumers to inform them of a signal it has.
    Should only contain enough info for them to bid on the data, not enough for them to know what the data is.

     Exchange-agnostic core prediction with typed metadata
     and exchange-specific market info.
    """

    # Type discriminator
    signal_type: SignalType

    # Core prediction (exchange-agnostic)
    model_probability: float
    confidence: float

    # Exchange-specific (one signal can map to multiple exchanges)
    exchanges: list[PreviewPolymarketInfo]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)
