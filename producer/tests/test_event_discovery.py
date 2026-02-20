"""Tests for Event Discovery task."""

import pytest
import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from signal_producer.tasks.event_discovery import EventDiscoveryTask
from signal_producer.strategies.weather.markets import WeatherEvent, WeatherMarket


@pytest.fixture
def sample_weather_event():
    """Sample WeatherEvent for testing."""
    markets = [
        WeatherMarket(
            question="Will temp be 34-35°F?",
            low_temp=34.0,
            high_temp=36.0,
            yes_price=0.35,
            no_price=0.65,
            yes_token_id="yes_token_123",
            no_token_id="no_token_123",
            active=True,
            closed=False,
        ),
    ]
    return WeatherEvent(
        event_id="213978",
        title="Highest temperature in NYC on February 20?",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=markets,
        closed=False,
    )


class TestEventDiscoveryTask:
    """Tests for EventDiscoveryTask."""

    @pytest.fixture
    def mock_gamma(self):
        """Create mock GammaClient."""
        return AsyncMock()

    @pytest.fixture
    def mock_registry(self):
        """Create mock MarketRegistry."""
        return MagicMock()

    @pytest.fixture
    def mock_price_tracker(self):
        """Create mock PriceTracker."""
        return AsyncMock()

    @pytest.fixture
    def discovery_task(self, mock_gamma, mock_registry, mock_price_tracker):
        """Create EventDiscoveryTask instance."""
        return EventDiscoveryTask(
            gamma_client=mock_gamma,
            registry=mock_registry,
            price_tracker=mock_price_tracker,
            cities=["nyc", "chicago"],
            poll_interval=10,
        )

    @pytest.mark.asyncio
    async def test_discover_registers_new_events(
        self, discovery_task, mock_gamma, mock_registry, sample_weather_event
    ):
        """Test that new events are registered with the registry."""
        mock_gamma.discover_weather_events.return_value = [sample_weather_event]
        mock_registry.register_event.return_value = ["yes_token_123", "no_token_123"]

        await discovery_task._discover_once()

        mock_registry.register_event.assert_called_once_with(sample_weather_event)

    @pytest.mark.asyncio
    async def test_discover_subscribes_new_tokens(
        self, discovery_task, mock_gamma, mock_registry, mock_price_tracker, sample_weather_event
    ):
        """Test that new tokens are subscribed via price tracker."""
        mock_gamma.discover_weather_events.return_value = [sample_weather_event]
        mock_registry.register_event.return_value = ["yes_token_123", "no_token_123"]

        await discovery_task._discover_once()

        mock_price_tracker.subscribe_tokens.assert_called_once_with(
            ["yes_token_123", "no_token_123"]
        )

    @pytest.mark.asyncio
    async def test_discover_skips_already_registered(
        self, discovery_task, mock_gamma, mock_registry, mock_price_tracker, sample_weather_event
    ):
        """Test that already-registered events don't trigger new subscriptions."""
        mock_gamma.discover_weather_events.return_value = [sample_weather_event]
        mock_registry.register_event.return_value = []  # No new tokens

        await discovery_task._discover_once()

        mock_price_tracker.subscribe_tokens.assert_not_called()

    @pytest.mark.asyncio
    async def test_discover_handles_empty_response(
        self, discovery_task, mock_gamma, mock_registry
    ):
        """Test handling of no events found."""
        mock_gamma.discover_weather_events.return_value = []

        await discovery_task._discover_once()

        mock_registry.register_event.assert_not_called()
