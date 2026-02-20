"""Tests for ProducerSignal types."""

import pytest
from datetime import datetime

from signal_producer.signals.types import (
    WeatherMetadata,
    PolymarketInfo,
    ProducerSignal,
)


def test_weather_metadata_has_required_fields():
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 34.8,
        "ensemble_std": 2.1,
        "members_in_range": 12,
    }
    assert metadata["city"] == "nyc"
    assert metadata["members_in_range"] == 12


def test_polymarket_info_has_required_fields():
    info: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "abc123",
        "side": "yes",
        "market_description": "Will temp be 34-35F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.35,
        "edge": 0.05,
        "price_timestamp": "2026-02-19T12:00:00Z",
    }
    assert info["exchange"] == "polymarket"
    assert info["side"] == "yes"


def test_producer_signal_creation():
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 34.8,
        "ensemble_std": 2.1,
        "members_in_range": 12,
    }
    exchange: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "abc123",
        "side": "yes",
        "market_description": "Will temp be 34-35F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.35,
        "edge": 0.05,
        "price_timestamp": "2026-02-19T12:00:00Z",
    }
    signal = ProducerSignal(
        signal_type="weather",
        model_probability=0.40,
        confidence=0.85,
        forecast_source="open_meteo",
        forecast_time="2026-02-19T08:00:00Z",
        metadata=metadata,
        exchanges=[exchange],
    )
    assert signal.signal_type == "weather"
    assert signal.model_probability == 0.40
    assert len(signal.exchanges) == 1


def test_producer_signal_to_dict():
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 34.8,
        "ensemble_std": 2.1,
        "members_in_range": 12,
    }
    exchange: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "abc123",
        "side": "yes",
        "market_description": "Will temp be 34-35F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.35,
        "edge": 0.05,
        "price_timestamp": "2026-02-19T12:00:00Z",
    }
    signal = ProducerSignal(
        signal_type="weather",
        model_probability=0.40,
        confidence=0.85,
        forecast_source="open_meteo",
        forecast_time="2026-02-19T08:00:00Z",
        metadata=metadata,
        exchanges=[exchange],
    )
    d = signal.to_dict()
    assert d["signal_type"] == "weather"
    assert d["metadata"]["city"] == "nyc"
    assert d["exchanges"][0]["exchange"] == "polymarket"
