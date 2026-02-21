"""Tests for Signal Generator task."""

import pytest
from datetime import date, datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

from signal_producer.tasks.signal_generator import SignalGeneratorTask
from signal_schema import ProducerSignal, WeatherMetadata, PolymarketInfo
from signal_producer.data.polymarket_registry import CachedEvent, CachedMarket


@pytest.fixture
def mock_registry():
    """Create mock MarketRegistry with cached events."""
    registry = MagicMock()

    # Create cached market
    cached_market = CachedMarket(
        db_id=1,
        question="Will temp be 42-44°F?",
        group_item_title="42-44°F",
        low_temp=42.0,
        high_temp=44.0,
        yes_token_id="yes_token_123",
        no_token_id="no_token_123",
        yes_price=0.30,
        no_price=0.70,
        price_timestamp=datetime.now(UTC).isoformat(),
    )

    # Create cached event
    cached_event = CachedEvent(
        event_id="213978",
        db_id=1,
        title="Highest temperature in NYC on February 20?",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        status="active",
        markets={
            "yes_token_123": cached_market,
            "no_token_123": cached_market,
        },
    )

    registry.get_active_events.return_value = [cached_event]
    registry.get_price.side_effect = lambda t: 0.30 if "yes" in t else 0.70

    return registry


@pytest.fixture
def mock_open_meteo():
    """Create mock OpenMeteoClient."""
    client = AsyncMock()

    # Mock ensemble forecast - all members at 43°F (in the 42-44 range)
    from signal_producer.clients.weather.open_meteo import EnsembleForecast

    forecast = MagicMock(spec=EnsembleForecast)
    forecast.city = "nyc"
    forecast.target_date = date(2026, 2, 20)
    forecast.member_highs = [43.0] * 31  # 100% in 42-44 range
    forecast.mean = 43.0
    forecast.std = 0.0
    forecast.min = 43.0
    forecast.max = 43.0

    client.get_ensemble_forecast.return_value = forecast

    return client


@pytest.fixture
def mock_broadcaster():
    """Create mock SignalBroadcaster."""
    return AsyncMock()


class TestSignalGeneratorTask:
    """Tests for SignalGeneratorTask."""

    @pytest.fixture
    def generator(self, mock_registry, mock_open_meteo, mock_broadcaster):
        """Create SignalGeneratorTask instance."""
        return SignalGeneratorTask(
            registry=mock_registry,
            open_meteo_client=mock_open_meteo,
            broadcaster=mock_broadcaster,
            edge_threshold=0.05,
        )

    @pytest.mark.asyncio
    async def test_generates_signal_for_positive_edge(
        self, generator, mock_broadcaster
    ):
        """Test signal generation when model_prob > market_price."""
        signals = await generator._generate_once()

        # Should generate at least one signal
        assert len(signals) >= 1

        # Should broadcast the signal
        assert mock_broadcaster.broadcast_producer_signal.called

    @pytest.mark.asyncio
    async def test_signal_has_correct_structure(self, generator):
        """Test that generated signals have correct ProducerSignal structure."""
        signals = await generator._generate_once()

        assert len(signals) >= 1
        signal = signals[0]

        assert isinstance(signal, ProducerSignal)
        assert signal.signal_type == "weather"
        assert signal.forecast_source == "open_meteo"
        assert isinstance(signal.metadata, dict)
        assert "city" in signal.metadata
        assert len(signal.exchanges) >= 1

    @pytest.mark.asyncio
    async def test_generates_yes_signal(self, generator):
        """Test YES signal when model_prob > yes_price."""
        signals = await generator._generate_once()

        # With 100% model prob and 30% market price, should generate YES signal
        yes_signals = [s for s in signals if s.exchanges[0]["side"] == "yes"]
        assert len(yes_signals) >= 1

    @pytest.mark.asyncio
    async def test_no_signal_when_no_edge(self, generator, mock_registry):
        """Test no signal generated when edge below threshold."""
        # Set market price equal to model probability (no edge)
        # Must clear side_effect to use return_value
        mock_registry.get_price.side_effect = None
        mock_registry.get_price.return_value = 1.0  # 100% price

        signals = await generator._generate_once()

        # No signals should be generated (no edge)
        assert len(signals) == 0

    @pytest.mark.asyncio
    async def test_skips_market_without_price(self, generator, mock_registry):
        """Test that markets without cached prices are skipped."""
        # Must clear side_effect to use return_value
        mock_registry.get_price.side_effect = None
        mock_registry.get_price.return_value = None

        signals = await generator._generate_once()

        # Should skip (no price available)
        assert len(signals) == 0
