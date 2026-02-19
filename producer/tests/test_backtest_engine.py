"""Tests for the backtest engine."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

from signal_producer.backtest.engine import (
    BacktestEngine,
    BacktestResult,
    TradeResult,
)
from signal_producer.backtest.gefs import EnsembleForecast


class TestTradeResult:
    """Tests for TradeResult."""

    def test_trade_result_basic(self):
        """Test basic TradeResult creation."""
        result = TradeResult(
            city="nyc",
            target_date=date(2025, 8, 16),
            bucket_question="Will the temp be 80-82°F?",
            forecast_temp=81.5,
            actual_temp=81.0,
            model_prob=0.35,
            market_price=0.20,
            edge=0.15,
            position_usd=3.50,
            won=True,
            pnl=14.0,
        )
        assert result.city == "nyc"
        assert result.edge == 0.15
        assert result.won is True


class TestBacktestResult:
    """Tests for BacktestResult."""

    def test_win_rate_calculation(self):
        """Test win rate calculation."""
        result = BacktestResult(
            start_date=date(2025, 8, 1),
            end_date=date(2025, 8, 31),
            cities=["nyc"],
            win_count=3,
            loss_count=2,
        )
        assert result.win_rate == 0.6

    def test_win_rate_no_trades(self):
        """Test win rate with no resolved trades."""
        result = BacktestResult(
            start_date=date(2025, 8, 1),
            end_date=date(2025, 8, 31),
            cities=["nyc"],
        )
        assert result.win_rate == 0.0

    def test_summary(self):
        """Test summary generation."""
        result = BacktestResult(
            start_date=date(2025, 8, 1),
            end_date=date(2025, 8, 31),
            cities=["nyc", "chicago"],
            total_pnl=25.50,
            win_count=5,
            loss_count=3,
        )
        summary = result.summary()
        assert "2025-08-01" in summary
        assert "2025-08-31" in summary
        assert "nyc, chicago" in summary
        assert "$25.50" in summary
        assert "62.5%" in summary


class TestBacktestEngine:
    """Tests for BacktestEngine."""

    def test_build_slug(self):
        """Test slug building."""
        engine = BacktestEngine()
        slug = engine._build_slug("nyc", date(2025, 8, 16))
        assert slug == "highest-temperature-in-nyc-on-august-16-2025"

    def test_bucket_contains_temp_range(self):
        """Test temperature containment for range bucket."""
        from signal_producer.strategies.weather.markets import WeatherBucket

        engine = BacktestEngine()
        bucket = WeatherBucket(
            question="80-82°F",
            yes_price=0.2,
            no_price=0.8,
            yes_token_id="t1",
            no_token_id="t2",
            low_temp=80,
            high_temp=82,
            active=True,
            closed=False,
        )

        assert engine._bucket_contains_temp(bucket, 80.0) is True
        assert engine._bucket_contains_temp(bucket, 81.5) is True
        assert engine._bucket_contains_temp(bucket, 82.0) is False  # Exclusive upper
        assert engine._bucket_contains_temp(bucket, 79.9) is False

    def test_bucket_contains_temp_or_below(self):
        """Test 'X or below' bucket."""
        from signal_producer.strategies.weather.markets import WeatherBucket

        engine = BacktestEngine()
        bucket = WeatherBucket(
            question="31°F or below",
            yes_price=0.1,
            no_price=0.9,
            yes_token_id="t1",
            no_token_id="t2",
            low_temp=None,
            high_temp=32,  # parse_temp_range returns high+1, so 32 for "31 or below"
            active=True,
            closed=False,
        )

        assert engine._bucket_contains_temp(bucket, 30.0) is True
        assert engine._bucket_contains_temp(bucket, 31.0) is True
        assert engine._bucket_contains_temp(bucket, 32.0) is False

    def test_bucket_contains_temp_or_above(self):
        """Test 'X or above' bucket."""
        from signal_producer.strategies.weather.markets import WeatherBucket

        engine = BacktestEngine()
        bucket = WeatherBucket(
            question="46°F or above",
            yes_price=0.1,
            no_price=0.9,
            yes_token_id="t1",
            no_token_id="t2",
            low_temp=46,
            high_temp=None,
            active=True,
            closed=False,
        )

        assert engine._bucket_contains_temp(bucket, 46.0) is True
        assert engine._bucket_contains_temp(bucket, 50.0) is True
        assert engine._bucket_contains_temp(bucket, 45.0) is False

    def test_calculate_model_prob(self):
        """Test model probability calculation."""
        from signal_producer.strategies.weather.markets import WeatherBucket

        engine = BacktestEngine()

        ensemble = EnsembleForecast(
            forecast_date=date(2025, 8, 15),
            target_date=date(2025, 8, 16),
            latitude=40.7128,
            longitude=-74.0060,
            member_temps=[80.0, 80.5, 81.0, 81.5, 82.0, 82.5, 83.0, 84.0, 85.0, 86.0],
        )

        bucket = WeatherBucket(
            question="80-82°F",
            yes_price=0.2,
            no_price=0.8,
            yes_token_id="t1",
            no_token_id="t2",
            low_temp=80,
            high_temp=82,
            active=True,
            closed=False,
        )

        # Members in bucket: 80.0, 80.5, 81.0, 81.5 = 4 out of 10
        prob = engine._calculate_model_prob(ensemble, bucket)
        assert prob == 0.4

    @pytest.mark.asyncio
    async def test_run_single_day_no_gefs_data(self):
        """Test handling when GEFS data is unavailable."""
        from signal_producer.config import CITIES

        engine = BacktestEngine()

        # Mock GEFS client to return None
        engine.gefs = MagicMock()
        engine.gefs.fetch_ensemble = AsyncMock(return_value=None)

        results = await engine.run_single_day(
            "nyc",
            CITIES["nyc"],
            date(2025, 8, 16),
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_run_single_day_no_market_data(self):
        """Test handling when market data is unavailable."""
        from signal_producer.config import CITIES

        engine = BacktestEngine()

        # Mock GEFS client
        engine.gefs = MagicMock()
        engine.gefs.fetch_ensemble = AsyncMock(return_value=EnsembleForecast(
            forecast_date=date(2025, 8, 15),
            target_date=date(2025, 8, 16),
            latitude=40.7128,
            longitude=-74.0060,
            member_temps=[80.0] * 31,
        ))

        # Mock event fetch to return None
        with patch.object(engine, '_fetch_event_data', return_value=None):
            results = await engine.run_single_day(
                "nyc",
                CITIES["nyc"],
                date(2025, 8, 16),
            )

        assert results == []


@pytest.mark.integration
class TestBacktestEngineIntegration:
    """Integration tests for backtest engine."""

    @pytest.mark.asyncio
    async def test_run_single_historical_day(self):
        """Test backtesting a single historical day."""
        from signal_producer.config import CITIES

        engine = BacktestEngine()

        # Use a historical date that should have GEFS data and market data
        results = await engine.run_single_day(
            "nyc",
            CITIES["nyc"],
            date(2025, 8, 16),
        )

        # Results may or may not exist depending on market availability
        # Just ensure no errors
        assert isinstance(results, list)
