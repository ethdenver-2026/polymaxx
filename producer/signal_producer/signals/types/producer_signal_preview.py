from dataclasses import asdict, dataclass
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

    # Identity and auction envelope
    producer_did: str
    auction_id: str
    auction_end_utc: str  # ISO timestamp
    last_price_paid: float

    # Core prediction (exchange-agnostic)
    model_probability: float
    confidence: float

    # Exchange-specific (one signal can map to multiple exchanges)
    exchanges: list[PreviewPolymarketInfo]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)


SignalPreviewMessage = ProducerSignalPreview


@dataclass
class AuctionBidMessage:
    """Bid message sent by a consumer for a previewed auction."""

    auction_id: str
    consumer_did: str
    bid_amount: float
    wallet_address: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["type"] = "AuctionBidMessage"
        payload["version"] = 1
        return payload


@dataclass
class AuctionBidRejected:
    """Rejected bid response emitted by producer."""

    auction_id: str
    consumer_did: str
    reason: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["type"] = "AuctionBidRejected"
        payload["version"] = 1
        return payload
