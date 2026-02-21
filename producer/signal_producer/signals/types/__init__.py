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
    PreviewPolymarketInfo,
    ProducerSignalPreview,
    SignalPreviewMessage,
)

__all__ = [
    "AuctionBidMessage",
    "AuctionBidRejected",
    "ForecastSource",
    "PolymarketInfo",
    "PreviewPolymarketInfo",
    "ProducerSignal",
    "ProducerSignalPreview",
    "SignalPreviewMessage",
    "SignalType",
    "WeatherMetadata",
]
