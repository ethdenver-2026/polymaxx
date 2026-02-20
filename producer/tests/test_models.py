"""Tests for database models."""

import pytest
from datetime import date, datetime

from signal_producer.models.models import SignalRecord, init_db, get_session


@pytest.fixture
def db_session(tmp_path):
    """Create a test database session."""
    db_path = str(tmp_path / "test.db")
    engine = init_db(db_path)
    session = get_session(engine)
    yield session
    session.close()


class TestSignalRecord:
    """Tests for SignalRecord model."""

    def test_create_signal(self, db_session):
        signal = SignalRecord(
            strategy="weather",
            market_id="123",
            token_id="abc",
            model_probability=0.75,
            market_price=0.60,
            edge=0.15,
            confidence=0.9,
            decision="trade",
            created_at=datetime.utcnow(),
        )
        db_session.add(signal)
        db_session.commit()

        assert signal.id is not None

    def test_create_signal_with_skip_reason(self, db_session):
        signal = SignalRecord(
            strategy="weather",
            market_id="123",
            token_id="abc",
            model_probability=0.65,
            market_price=0.60,
            edge=0.05,
            decision="skip",
            skip_reason="below_threshold",
            created_at=datetime.utcnow(),
        )
        db_session.add(signal)
        db_session.commit()

        assert signal.skip_reason == "below_threshold"

    def test_signal_with_metadata(self, db_session):
        signal = SignalRecord(
            strategy="weather",
            market_id="123",
            token_id="abc",
            model_probability=0.75,
            market_price=0.60,
            edge=0.15,
            decision="trade",
            metadata_json='{"city": "nyc", "bucket": "46-47"}',
            created_at=datetime.utcnow(),
        )
        db_session.add(signal)
        db_session.commit()

        assert signal.metadata_json is not None
