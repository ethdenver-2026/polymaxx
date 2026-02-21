"""Shared signal schema for producer-consumer communication."""

from .types import (
    AuctionBidMessage,
    AuctionBidRejected,
    ForecastSource,
    PolymarketInfo,
    PreviewPolymarketInfo,
    ProducerSignal,
    ProducerSignalPreview,
    SignalPreviewMessage,
    SignalType,
    WeatherMetadata,
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
