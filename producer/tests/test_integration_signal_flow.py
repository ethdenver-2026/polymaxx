"""Integration tests for the full producer signal flow.

Tests the complete pipeline:
Event Discovery → Registry → Price Tracker → Signal Generator → Broadcaster
"""

import pytest
import asyncio
import tempfile
import os
from datetime import date, datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine

from signal_producer.clients.gamma import GammaClient
from signal_producer.models.models import Base
from signal_producer.publishing.websocket import SignalBroadcaster
from signal_producer.registry.market_registry import MarketRegistry
from signal_producer.strategies.weather.markets import WeatherEvent, WeatherMarket
from signal_producer.strategies.weather.open_meteo import EnsembleForecast, OpenMeteoClient
from signal_producer.tasks.event_discovery import EventDiscoveryTask
from signal_producer.tasks.signal_generator import SignalGeneratorTask
from signal_producer.tracker.price_tracker import PriceTracker


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)

    yield engine

    # Cleanup
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def registry(temp_db):
    """Create MarketRegistry with temp database."""
    return MarketRegistry(temp_db)


@pytest.fixture
def sample_weather_event():
    """Sample WeatherEvent for testing."""
    markets = [
        WeatherMarket(
            question="Will temp be 42-44°F?",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.30,
            no_price=0.70,
            yes_token_id="yes_token_42_44",
            no_token_id="no_token_42_44",
            active=True,
            closed=False,
        ),
        WeatherMarket(
            question="Will temp be 44-46°F?",
            low_temp=44.0,
            high_temp=46.0,
            yes_price=0.25,
            no_price=0.75,
            yes_token_id="yes_token_44_46",
            no_token_id="no_token_44_46",
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


@pytest.fixture
def ensemble_forecast():
    """Ensemble forecast with all members at 43°F."""
    return EnsembleForecast(
        city="nyc",
        target_date=date(2026, 2, 20),
        member_highs=[43.0] * 31,  # 100% in 42-44 range
    )


class TestSignalFlowIntegration:
    """Integration tests for complete signal flow."""

    @pytest.mark.asyncio
    async def test_event_discovery_to_registry(self, registry, sample_weather_event):
        """Test event discovery registers events in registry."""
        # Setup mock gamma client
        mock_gamma = AsyncMock(spec=GammaClient)
        mock_gamma.discover_weather_events.return_value = [sample_weather_event]

        # Setup mock price tracker
        mock_price_tracker = AsyncMock()

        # Create discovery task
        discovery = EventDiscoveryTask(
            gamma_client=mock_gamma,
            registry=registry,
            price_tracker=mock_price_tracker,
            cities=["nyc"],
        )

        # Run discovery
        new_count = await discovery._discover_once()

        # Verify event was registered
        assert new_count == 1
        events = registry.get_active_events()
        assert len(events) == 1
        assert events[0].event_id == "213978"
        assert events[0].city == "nyc"

        # Verify tokens were subscribed
        mock_price_tracker.subscribe_tokens.assert_called_once()
        subscribed_tokens = mock_price_tracker.subscribe_tokens.call_args[0][0]
        assert "yes_token_42_44" in subscribed_tokens
        assert "no_token_42_44" in subscribed_tokens

    @pytest.mark.asyncio
    async def test_price_update_to_registry(self, registry, sample_weather_event):
        """Test price updates are stored in registry."""
        # First register the event
        registry.register_event(sample_weather_event)

        # Update price
        registry.update_price("yes_token_42_44", 0.45, datetime.now(UTC).isoformat())

        # Verify price was stored
        price = registry.get_price("yes_token_42_44")
        assert price == 0.45

    @pytest.mark.asyncio
    async def test_signal_generation_with_edge(
        self, registry, sample_weather_event, ensemble_forecast
    ):
        """Test signal generation when model has edge over market."""
        # Register event and set price
        registry.register_event(sample_weather_event)
        ts = datetime.now(UTC).isoformat()
        registry.update_price("yes_token_42_44", 0.30, ts)  # Market price 30%
        registry.update_price("yes_token_44_46", 0.25, ts)

        # Setup mock OpenMeteo
        mock_open_meteo = AsyncMock(spec=OpenMeteoClient)
        mock_open_meteo.get_ensemble_forecast.return_value = ensemble_forecast

        # Setup mock broadcaster
        mock_broadcaster = AsyncMock()

        # Create signal generator with low threshold
        generator = SignalGeneratorTask(
            registry=registry,
            open_meteo_client=mock_open_meteo,
            broadcaster=mock_broadcaster,
            edge_threshold=0.05,  # 5% threshold
        )

        # Generate signals
        signals = await generator._generate_once()

        # Should generate YES signal for 42-44 range (100% model prob vs 30% market)
        assert len(signals) >= 1

        yes_signals = [s for s in signals if s.exchanges[0]["side"] == "yes"]
        assert len(yes_signals) >= 1

        signal = yes_signals[0]
        assert signal.signal_type == "weather"
        assert signal.model_probability == 1.0  # All members in 42-44 range
        assert signal.exchanges[0]["edge"] >= 0.05

        # Verify broadcaster was called
        mock_broadcaster.broadcast_producer_signal.assert_called()

    @pytest.mark.asyncio
    async def test_full_flow_with_no_edge(
        self, registry, sample_weather_event, ensemble_forecast
    ):
        """Test no signals when market price matches model probability."""
        # Register event and set price equal to model probability
        registry.register_event(sample_weather_event)
        ts = datetime.now(UTC).isoformat()
        registry.update_price("yes_token_42_44", 1.0, ts)  # Market matches model (100%)
        registry.update_price("yes_token_44_46", 0.0, ts)

        # Setup mock OpenMeteo
        mock_open_meteo = AsyncMock(spec=OpenMeteoClient)
        mock_open_meteo.get_ensemble_forecast.return_value = ensemble_forecast

        # Setup mock broadcaster
        mock_broadcaster = AsyncMock()

        # Create signal generator
        generator = SignalGeneratorTask(
            registry=registry,
            open_meteo_client=mock_open_meteo,
            broadcaster=mock_broadcaster,
            edge_threshold=0.05,
        )

        # Generate signals
        signals = await generator._generate_once()

        # No edge = no signals
        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_rediscovery_no_duplicates(self, registry, sample_weather_event):
        """Test that rediscovering same event doesn't create duplicates."""
        mock_gamma = AsyncMock(spec=GammaClient)
        mock_gamma.discover_weather_events.return_value = [sample_weather_event]
        mock_price_tracker = AsyncMock()

        discovery = EventDiscoveryTask(
            gamma_client=mock_gamma,
            registry=registry,
            price_tracker=mock_price_tracker,
            cities=["nyc"],
        )

        # First discovery
        count1 = await discovery._discover_once()
        assert count1 == 1

        # Second discovery of same event
        count2 = await discovery._discover_once()
        assert count2 == 0  # No new events

        # Still only one event in registry
        events = registry.get_active_events()
        assert len(events) == 1
