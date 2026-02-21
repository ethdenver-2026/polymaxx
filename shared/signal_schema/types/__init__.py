"""Shared signal types for producer-consumer wire protocol."""

from .producer_signal import (
    ForecastSource,
    PolymarketInfo,
    ProducerSignal,
    SignalType,
    TSAMetadata,
    WeatherMetadata,
)
from .auction_messages import (
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
    "TSAMetadata",
    "WeatherMetadata",
]
