"""Tests for MarketRegistry."""

import pytest
from datetime import date, datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signal_producer.models.models import Base
from signal_producer.data.polymarket_registry import MarketRegistry
from signal_producer.clients.polymarket.markets import WeatherEvent, WeatherMarket


@pytest.fixture
def engine():
    """Create in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def registry(engine):
    """Create MarketRegistry instance."""
    return MarketRegistry(engine)


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
        WeatherMarket(
            question="Will temp be 36-37°F?",
            low_temp=36.0,
            high_temp=38.0,
            yes_price=0.25,
            no_price=0.75,
            yes_token_id="yes_token_456",
            no_token_id="no_token_456",
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


class TestMarketRegistry:
    """Tests for MarketRegistry."""

    def test_register_event_returns_new_token_ids(self, registry, sample_weather_event):
        """register_event should return token IDs for new markets."""
        new_tokens = registry.register_event(sample_weather_event)

        # Should have 2 YES tokens and 2 NO tokens
        assert len(new_tokens) == 4
        assert "yes_token_123" in new_tokens
        assert "no_token_123" in new_tokens

    def test_register_event_idempotent(self, registry, sample_weather_event):
        """Registering same event twice should not duplicate."""
        registry.register_event(sample_weather_event)
        new_tokens = registry.register_event(sample_weather_event)

        # Second registration should return empty (already tracked)
        assert len(new_tokens) == 0

    def test_update_price(self, registry, sample_weather_event):
        """update_price should update in-memory cache."""
        registry.register_event(sample_weather_event)
        registry.update_price("yes_token_123", 0.42, datetime.now(UTC).isoformat())

        # Get price from cache
        price = registry.get_price("yes_token_123")
        assert price == 0.42

    def test_get_active_events(self, registry, sample_weather_event):
        """get_active_events should return only active events."""
        registry.register_event(sample_weather_event)
        active = registry.get_active_events()

        assert len(active) == 1
        assert active[0].event_id == "213978"

    def test_mark_resolved(self, registry, sample_weather_event):
        """mark_resolved should update status and return tokens to unsubscribe."""
        registry.register_event(sample_weather_event)
        tokens = registry.mark_resolved("213978", "yes")

        # Should return all token IDs to unsubscribe
        assert len(tokens) == 4

        # Event should no longer be active
        active = registry.get_active_events()
        assert len(active) == 0

    def test_get_active_token_ids(self, registry, sample_weather_event):
        """get_active_token_ids should return all tokens for active events."""
        registry.register_event(sample_weather_event)
        tokens = registry.get_active_token_ids()

        assert len(tokens) == 4
        assert "yes_token_123" in tokens
        assert "no_token_123" in tokens
