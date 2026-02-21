"""Signal type contracts for producer messaging."""

from .producer_signal import (
    ForecastSource,
    PolymarketInfo,
    ProducerSignal,
    SignalType,
    WeatherMetadata,
)
from .producer_signal_preview import (
    AuctionBidMessage,
    AuctionBidRejected,
    ProducerSignalPreview,
    PreviewPolymarketInfo,
    SignalPreviewMessage,
)

__all__ = [
    "SignalType",
    "ForecastSource",
    "WeatherMetadata",
    "PolymarketInfo",
    "ProducerSignal",
    "PreviewPolymarketInfo",
    "ProducerSignalPreview",
    "SignalPreviewMessage",
    "AuctionBidMessage",
    "AuctionBidRejected",
]
