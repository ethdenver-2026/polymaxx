"""Tests for weather signal calculation."""

import pytest
from datetime import date

from signal_producer.strategies.weather.signals import (
    calculate_bucket_probability,
    calculate_confidence,
    calculate_weather_signals,
    ConfidenceFilter,
    FilterReason,
)
from tests.conftest import (
    MockEnsembleForecast,
    MockWeatherBucket,
    MockWeatherEvent,
)


class TestCalculateBucketProbability:
    """Test bucket probability calculation from ensemble members."""

    def test_probability_counts_correctly(self, sample_ensemble):
        """Verify correct counting of members in bucket."""
        # Bucket 42-44°F
        bucket = MockWeatherBucket(
            question="42-43°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.20,
            no_price=0.80,
        )

        prob = calculate_bucket_probability(sample_ensemble, bucket)

        # Manually count: members in [42, 44) from sample_ensemble
        # 41.8, 41.9, 42.0, 42.1, 42.2, 42.3, 42.4, 42.5, 42.7, 42.9, 43.1, 43.4, 43.7
        # In range [42, 44): 42.0, 42.1, 42.2, 42.3, 42.4, 42.5, 42.7, 42.9, 43.1, 43.4, 43.7 = 11 members
        count = sum(1 for t in sample_ensemble.member_highs if 42.0 <= t < 44.0)
        expected_prob = count / 31

        assert prob == pytest.approx(expected_prob)

    def test_empty_bucket_returns_zero(self, sample_ensemble):
        """Bucket with no members should return 0 probability."""
        # Bucket way outside the range
        bucket = MockWeatherBucket(
            question="60-62°F",
            low_temp=60.0,
            high_temp=62.0,
            yes_price=0.05,
            no_price=0.95,
        )

        prob = calculate_bucket_probability(sample_ensemble, bucket)
        assert prob == 0.0

    def test_all_members_in_bucket(self, tight_ensemble):
        """Bucket containing all members should return 1.0."""
        # Wide bucket that contains all members
        bucket = MockWeatherBucket(
            question="40-50°F",
            low_temp=40.0,
            high_temp=50.0,
            yes_price=0.90,
            no_price=0.10,
        )

        prob = calculate_bucket_probability(tight_ensemble, bucket)
        assert prob == pytest.approx(1.0)

    def test_or_below_bucket(self, sample_ensemble):
        """Test 'X or below' bucket (low_temp=None)."""
        bucket = MockWeatherBucket(
            question="39°F or below",
            low_temp=None,
            high_temp=40.0,  # < 40°F
            yes_price=0.10,
            no_price=0.90,
        )

        prob = calculate_bucket_probability(sample_ensemble, bucket)

        # Count members < 40°F: 38.5, 39.2, 39.8 = 3 members
        count = sum(1 for t in sample_ensemble.member_highs if t < 40.0)
        expected = count / 31

        assert prob == pytest.approx(expected)

    def test_or_above_bucket(self, sample_ensemble):
        """Test 'X or above' bucket (high_temp=None)."""
        bucket = MockWeatherBucket(
            question="46°F or higher",
            low_temp=46.0,
            high_temp=None,
            yes_price=0.15,
            no_price=0.85,
        )

        prob = calculate_bucket_probability(sample_ensemble, bucket)

        # Count members >= 46°F: 46.2, 46.5 = 2 members
        count = sum(1 for t in sample_ensemble.member_highs if t >= 46.0)
        expected = count / 31

        assert prob == pytest.approx(expected)


class TestCalculateConfidence:
    """Test confidence calculation from ensemble spread."""

    def test_narrow_spread_high_confidence(self, tight_ensemble):
        """Narrow spread should give high confidence."""
        confidence = calculate_confidence(tight_ensemble)
        # Spread is 3°F (42.0 to 45.0), should be high confidence
        assert confidence >= 0.8

    def test_wide_spread_low_confidence(self, wide_ensemble):
        """Wide spread should give low confidence."""
        confidence = calculate_confidence(wide_ensemble)
        # Spread is 24°F (35.0 to 59.0), should be low confidence
        assert confidence <= 0.5

    def test_very_narrow_spread_max_confidence(self):
        """Very narrow spread (<=5°F) should give max confidence."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            member_highs=[42.0 + i * 0.1 for i in range(31)],  # 42.0 to 45.0, 3°F spread
        )
        confidence = calculate_confidence(ensemble)
        assert confidence == pytest.approx(1.0)

    def test_very_wide_spread_min_confidence(self):
        """Very wide spread (>=20°F) should give minimum confidence."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            member_highs=[30.0 + i for i in range(31)],  # 30 to 60°F, 30°F spread
        )
        confidence = calculate_confidence(ensemble)
        assert confidence == pytest.approx(0.3)


class TestConfidenceFilter:
    """Test ConfidenceFilter presets."""

    def test_conservative_preset(self):
        """Conservative filter requires 50%+ consensus."""
        filter_config = ConfidenceFilter.conservative()
        assert filter_config.min_bucket_probability == 0.50

    def test_moderate_preset(self):
        """Moderate filter requires 35%+ consensus."""
        filter_config = ConfidenceFilter.moderate()
        assert filter_config.min_bucket_probability == 0.35

    def test_aggressive_preset(self):
        """Aggressive filter requires 25%+ consensus."""
        filter_config = ConfidenceFilter.aggressive()
        assert filter_config.min_bucket_probability == 0.25

    def test_disabled_preset(self):
        """Disabled filter allows any probability."""
        filter_config = ConfidenceFilter.disabled()
        assert filter_config.min_bucket_probability == 0.0


class TestCalculateWeatherSignals:
    """Test the main signal calculation function."""

    def test_signals_sorted_by_edge(self):
        """Returned signals should be sorted by edge, highest first."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            member_highs=[42.0] * 31,  # All members at exactly 42°F
        )

        # Create buckets with different edges
        buckets = [
            MockWeatherBucket(
                question="42-44°F",  # 100% probability
                low_temp=42.0,
                high_temp=44.0,
                yes_price=0.50,  # 50% edge (1.0 - 0.5)
                no_price=0.50,
            ),
            MockWeatherBucket(
                question="40-42°F",  # 0% probability
                low_temp=40.0,
                high_temp=42.0,
                yes_price=0.10,  # Negative edge
                no_price=0.90,
            ),
        ]

        event = MockWeatherEvent(
            event_id="test_123",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            buckets=buckets,
        )

        signals = calculate_weather_signals(
            ensemble=ensemble,
            event=event,
            bankroll=100.0,
            edge_threshold=0.01,  # Low threshold to get signals
        )

        # Should only get the positive edge bucket
        assert len(signals) >= 1
        # First signal should have highest edge
        if len(signals) > 1:
            assert signals[0].edge >= signals[1].edge

    def test_filters_invalid_bucket(self):
        """Buckets with unparseable temps should be filtered."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            member_highs=[42.0] * 31,
        )

        bucket = MockWeatherBucket(
            question="Invalid bucket",
            low_temp=None,  # Both None = invalid
            high_temp=None,
            yes_price=0.50,
            no_price=0.50,
        )

        event = MockWeatherEvent(
            event_id="test_123",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            buckets=[bucket],
        )

        signals = calculate_weather_signals(
            ensemble=ensemble,
            event=event,
            bankroll=100.0,
        )

        assert len(signals) == 0

    def test_filters_low_probability(self):
        """Buckets below min_bucket_probability should be filtered."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            # Only 3 members in target range = ~10% probability
            member_highs=[42.0, 42.5, 43.0] + [50.0] * 28,
        )

        bucket = MockWeatherBucket(
            question="42-44°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.05,  # High edge, but low model probability
            no_price=0.95,
        )

        event = MockWeatherEvent(
            event_id="test_123",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            buckets=[bucket],
        )

        # With conservative filter (50% min), should filter
        signals = calculate_weather_signals(
            ensemble=ensemble,
            event=event,
            bankroll=100.0,
            confidence_filter=ConfidenceFilter.conservative(),
        )

        assert len(signals) == 0

    def test_filters_insufficient_edge(self):
        """Buckets below edge threshold should be filtered."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            member_highs=[42.0] * 31,  # 100% in 42-44 bucket
        )

        bucket = MockWeatherBucket(
            question="42-44°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.98,  # Only 2% edge
            no_price=0.02,
        )

        event = MockWeatherEvent(
            event_id="test_123",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            buckets=[bucket],
        )

        signals = calculate_weather_signals(
            ensemble=ensemble,
            event=event,
            bankroll=100.0,
            edge_threshold=0.08,  # 8% threshold
        )

        assert len(signals) == 0

    def test_generates_valid_signal(self):
        """Should generate valid signal for good opportunity."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            member_highs=[42.0] * 31,  # 100% in 42-44 bucket
        )

        bucket = MockWeatherBucket(
            question="42-44°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.50,  # 50% edge
            no_price=0.50,
        )

        event = MockWeatherEvent(
            event_id="test_123",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            buckets=[bucket],
        )

        signals = calculate_weather_signals(
            ensemble=ensemble,
            event=event,
            bankroll=100.0,
            edge_threshold=0.08,
            confidence_filter=ConfidenceFilter.disabled(),
        )

        assert len(signals) == 1
        signal = signals[0]
        assert signal.strategy == "weather"
        assert signal.market_id == "test_123"
        assert signal.model_probability == pytest.approx(1.0)
        assert signal.market_price == pytest.approx(0.50)
        assert signal.edge == pytest.approx(0.50)
        assert signal.position_size_usd > 0

    def test_signal_metadata(self):
        """Signal should include relevant metadata."""
        ensemble = MockEnsembleForecast(
            city="nyc",
            target_date=date(2026, 2, 20),
            member_highs=[42.0] * 31,
        )

        bucket = MockWeatherBucket(
            question="42-44°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.30,
            no_price=0.70,
        )

        event = MockWeatherEvent(
            event_id="test_123",
            title="Test Event",
            city="nyc",
            target_date=date(2026, 2, 20),
            resolution_source="test",
            buckets=[bucket],
        )

        signals = calculate_weather_signals(
            ensemble=ensemble,
            event=event,
            bankroll=100.0,
            confidence_filter=ConfidenceFilter.disabled(),
        )

        assert len(signals) == 1
        signal = signals[0]
        assert signal.metadata is not None
        assert signal.metadata["city"] == "nyc"
        assert signal.metadata["bucket_low"] == 42.0
        assert signal.metadata["bucket_high"] == 44.0
        assert "ensemble_std" in signal.metadata


class TestBucketContainsTemp:
    """Test bucket temperature containment logic."""

    def test_contains_in_range(self):
        """Temperature in range should return True."""
        bucket = MockWeatherBucket(
            question="42-44°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.20,
            no_price=0.80,
        )
        assert bucket.contains_temp(42.0) is True
        assert bucket.contains_temp(43.0) is True
        assert bucket.contains_temp(43.9) is True

    def test_excludes_upper_bound(self):
        """Upper bound should be exclusive."""
        bucket = MockWeatherBucket(
            question="42-44°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.20,
            no_price=0.80,
        )
        assert bucket.contains_temp(44.0) is False

    def test_includes_lower_bound(self):
        """Lower bound should be inclusive."""
        bucket = MockWeatherBucket(
            question="42-44°F",
            low_temp=42.0,
            high_temp=44.0,
            yes_price=0.20,
            no_price=0.80,
        )
        assert bucket.contains_temp(42.0) is True

    def test_or_below_bucket_contains(self):
        """'X or below' should contain temps below threshold."""
        bucket = MockWeatherBucket(
            question="39°F or below",
            low_temp=None,
            high_temp=40.0,
            yes_price=0.10,
            no_price=0.90,
        )
        assert bucket.contains_temp(39.0) is True
        assert bucket.contains_temp(35.0) is True
        assert bucket.contains_temp(40.0) is False

    def test_or_above_bucket_contains(self):
        """'X or above' should contain temps at or above threshold."""
        bucket = MockWeatherBucket(
            question="46°F or higher",
            low_temp=46.0,
            high_temp=None,
            yes_price=0.15,
            no_price=0.85,
        )
        assert bucket.contains_temp(46.0) is True
        assert bucket.contains_temp(50.0) is True
        assert bucket.contains_temp(45.9) is False
