"""Tests for database models."""

import pytest
from datetime import date, datetime

from signal_producer.data.models import SignalRecord, Trade, Position, init_db, get_session


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


class TestPosition:
    """Tests for Position model."""

    def test_create_position(self, db_session):
        position = Position(
            strategy="weather",
            market_id="123",
            token_id="abc",
            shares=100.0,
            cost_basis=0.15,
            total_cost=15.0,
            status="open",
            opened_at=datetime.utcnow(),
        )
        db_session.add(position)
        db_session.commit()

        assert position.id is not None
        assert position.status == "open"

    def test_close_position(self, db_session):
        position = Position(
            strategy="weather",
            market_id="123",
            token_id="abc",
            shares=100.0,
            cost_basis=0.15,
            total_cost=15.0,
            status="open",
            opened_at=datetime.utcnow(),
        )
        db_session.add(position)
        db_session.commit()

        # Close the position
        position.status = "closed"
        position.closed_at = datetime.utcnow()
        position.realized_pnl = 5.50
        db_session.commit()

        assert position.status == "closed"
        assert position.realized_pnl == 5.50


class TestTradeWithStrategy:
    """Tests for Trade model with strategy field."""

    def test_trade_has_strategy_field(self, db_session):
        trade = Trade(
            mode="paper",
            strategy="weather",
            city="nyc",
            target_date=date.today(),
            bucket_question="Will temp be 46-47?",
            token_id="abc",
            side="buy",
            model_prob=0.75,
            market_price=0.60,
            edge=0.15,
            position_usd=5.0,
            status="filled",
            created_at=datetime.utcnow(),
        )
        db_session.add(trade)
        db_session.commit()

        assert trade.strategy == "weather"

    def test_trade_default_strategy(self, db_session):
        """Test that strategy defaults to 'weather' for backwards compatibility."""
        trade = Trade(
            mode="paper",
            city="nyc",
            target_date=date.today(),
            bucket_question="Will temp be 46-47?",
            token_id="abc",
            side="buy",
            model_prob=0.75,
            market_price=0.60,
            edge=0.15,
            position_usd=5.0,
            status="filled",
            created_at=datetime.utcnow(),
        )
        db_session.add(trade)
        db_session.commit()

        assert trade.strategy == "weather"

    def test_trade_has_resolution_fields(self, db_session):
        trade = Trade(
            mode="paper",
            strategy="weather",
            city="nyc",
            target_date=date.today(),
            bucket_question="Will temp be 46-47?",
            token_id="abc",
            side="buy",
            model_prob=0.75,
            market_price=0.60,
            edge=0.15,
            position_usd=5.0,
            status="resolved",
            actual_temp=46.5,
            resolution_source="gamma_api",
            created_at=datetime.utcnow(),
        )
        db_session.add(trade)
        db_session.commit()

        assert trade.actual_temp == 46.5
        assert trade.resolution_source == "gamma_api"
