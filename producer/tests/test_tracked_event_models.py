"""Tests for TrackedEvent SQLAlchemy models."""

import pytest
from datetime import date, datetime, UTC
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from signal_producer.models.models import (
    Base,
    TrackedEvent,
    TrackedMarket,
    TrackedForecast,
)


@pytest.fixture
def db_session():
    """Create in-memory SQLite database with session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestTrackedEvent:
    """Tests for TrackedEvent model."""

    def test_create_tracked_event(self, db_session):
        """Test creating a TrackedEvent."""
        event = TrackedEvent(
            event_id="213978",
            title="Highest temperature in NYC on February 20?",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA",
            status="active",
        )
        db_session.add(event)
        db_session.commit()

        assert event.id is not None
        assert event.status == "active"

    def test_status_transitions(self, db_session):
        """Test event status transitions."""
        event = TrackedEvent(
            event_id="213978",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            status="active",
        )
        db_session.add(event)
        db_session.commit()

        # Transition to resolved
        event.status = "resolved"
        event.resolved_at = datetime.now(UTC)
        db_session.commit()

        assert event.status == "resolved"
        assert event.resolved_at is not None


class TestTrackedMarket:
    """Tests for TrackedMarket model."""

    def test_create_tracked_market(self, db_session):
        """Test creating a TrackedMarket."""
        event = TrackedEvent(
            event_id="213978",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            status="active",
        )
        db_session.add(event)
        db_session.flush()

        market = TrackedMarket(
            event_id=event.id,
            question="Will temp be 34-35°F?",
            low_temp=34.0,
            high_temp=36.0,
            yes_token_id="yes123",
            no_token_id="no123",
            active=True,
        )
        db_session.add(market)
        db_session.commit()

        assert market.id is not None
        assert market.event_id == event.id


class TestTrackedForecast:
    """Tests for TrackedForecast model."""

    def test_create_tracked_forecast(self, db_session):
        """Test creating a TrackedForecast."""
        event = TrackedEvent(
            event_id="213978",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            status="active",
        )
        db_session.add(event)
        db_session.flush()

        forecast = TrackedForecast(
            event_id=event.id,
            forecast_source="open_meteo",
            forecast_time=datetime.now(UTC),
            ensemble_mean=34.5,
            ensemble_std=2.1,
        )
        db_session.add(forecast)
        db_session.commit()

        assert forecast.id is not None
        assert forecast.forecast_source == "open_meteo"
