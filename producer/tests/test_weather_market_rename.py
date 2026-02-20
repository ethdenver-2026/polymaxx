"""Test that WeatherMarket exists and WeatherBucket is removed."""

import pytest


def test_weather_market_import():
    from signal_producer.clients.markets import WeatherMarket, WeatherEvent
    assert WeatherMarket is not None
    assert WeatherEvent is not None


def test_weather_bucket_removed():
    with pytest.raises(ImportError):
        from signal_producer.clients.markets import WeatherBucket
