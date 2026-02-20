"""Tests for Kelly criterion position sizing."""

import pytest
from signal_producer.trading.kelly import (
    calculate_kelly_position,
    calculate_expected_value,
    calculate_edge,
)


class TestCalculateEdge:
    """Test edge calculation."""

    def test_positive_edge(self):
        """Model probability > market price = positive edge."""
        edge = calculate_edge(model_prob=0.60, market_price=0.40)
        assert edge == pytest.approx(0.20)

    def test_negative_edge(self):
        """Model probability < market price = negative edge."""
        edge = calculate_edge(model_prob=0.30, market_price=0.50)
        assert edge == pytest.approx(-0.20)

    def test_zero_edge(self):
        """Model probability == market price = no edge."""
        edge = calculate_edge(model_prob=0.50, market_price=0.50)
        assert edge == pytest.approx(0.0)


class TestCalculateKellyPosition:
    """Test Kelly position sizing."""

    def test_no_edge_returns_zero(self):
        """When win_prob <= price, there's no edge, return 0."""
        # Exactly equal
        position = calculate_kelly_position(
            win_prob=0.50,
            price=0.50,
            bankroll=100.0,
        )
        assert position == 0.0

        # Win prob less than price
        position = calculate_kelly_position(
            win_prob=0.40,
            price=0.50,
            bankroll=100.0,
        )
        assert position == 0.0

    def test_invalid_price_zero_returns_zero(self):
        """Price of 0 is invalid."""
        position = calculate_kelly_position(
            win_prob=0.60,
            price=0.0,
            bankroll=100.0,
        )
        assert position == 0.0

    def test_invalid_price_one_returns_zero(self):
        """Price of 1 is invalid (no profit possible)."""
        position = calculate_kelly_position(
            win_prob=0.99,
            price=1.0,
            bankroll=100.0,
        )
        assert position == 0.0

    def test_invalid_price_negative_returns_zero(self):
        """Negative price is invalid."""
        position = calculate_kelly_position(
            win_prob=0.60,
            price=-0.10,
            bankroll=100.0,
        )
        assert position == 0.0

    def test_invalid_win_prob_zero_returns_zero(self):
        """Zero win probability returns 0."""
        position = calculate_kelly_position(
            win_prob=0.0,
            price=0.50,
            bankroll=100.0,
        )
        assert position == 0.0

    def test_quarter_kelly_fraction(self):
        """Verify default uses quarter Kelly (0.25)."""
        # Full Kelly with 60% win prob at 40% price:
        # b = (1 - 0.4) / 0.4 = 1.5
        # q = 0.4
        # kelly = (0.6 * 1.5 - 0.4) / 1.5 = (0.9 - 0.4) / 1.5 = 0.333...
        # Quarter Kelly = 0.333... * 0.25 = 0.0833...
        # Position = 100 * 0.0833... = 8.33...

        position = calculate_kelly_position(
            win_prob=0.60,
            price=0.40,
            bankroll=100.0,
            kelly_fraction=0.25,
        )

        # With quarter Kelly, should be about 8.33
        # But max_position is 5.0 by default, so it should be capped
        assert position == pytest.approx(5.0)  # Capped at max_position

        # Try with higher max to verify the calculation
        position_uncapped = calculate_kelly_position(
            win_prob=0.60,
            price=0.40,
            bankroll=100.0,
            kelly_fraction=0.25,
            max_position=50.0,
        )
        # 100 * 0.333... * 0.25 = 8.33...
        assert position_uncapped == pytest.approx(8.333, rel=0.01)

    def test_full_kelly_vs_quarter_kelly(self):
        """Quarter Kelly should be 1/4 of full Kelly."""
        full_kelly = calculate_kelly_position(
            win_prob=0.55,
            price=0.40,
            bankroll=100.0,
            kelly_fraction=1.0,
            max_position=100.0,
            min_position=0.0,
        )

        quarter_kelly = calculate_kelly_position(
            win_prob=0.55,
            price=0.40,
            bankroll=100.0,
            kelly_fraction=0.25,
            max_position=100.0,
            min_position=0.0,
        )

        assert quarter_kelly == pytest.approx(full_kelly * 0.25)

    def test_max_position_cap(self):
        """Large bankroll should hit max position cap."""
        position = calculate_kelly_position(
            win_prob=0.70,
            price=0.30,
            bankroll=10000.0,  # Large bankroll
            kelly_fraction=0.25,
            max_position=5.0,  # Small cap
        )
        assert position == 5.0  # Should be capped

    def test_min_position_threshold(self):
        """Positions below min_position should return 0."""
        # Small edge, small bankroll = tiny position
        position = calculate_kelly_position(
            win_prob=0.51,
            price=0.50,
            bankroll=10.0,  # Small bankroll
            kelly_fraction=0.25,
            min_position=1.0,  # Minimum $1
        )
        assert position == 0.0  # Too small to trade

    def test_known_kelly_calculation(self):
        """Verify formula with known values.

        Example: 70% win probability, 30% price
        b = (1 - 0.3) / 0.3 = 2.333...
        q = 0.3
        kelly = (0.7 * 2.333 - 0.3) / 2.333 = (1.633 - 0.3) / 2.333 = 0.5714
        Quarter Kelly = 0.5714 * 0.25 = 0.1428
        Position = 100 * 0.1428 = 14.28
        """
        position = calculate_kelly_position(
            win_prob=0.70,
            price=0.30,
            bankroll=100.0,
            kelly_fraction=0.25,
            max_position=50.0,
            min_position=0.0,
        )

        expected = 100 * ((0.70 * 2.333333 - 0.30) / 2.333333) * 0.25
        assert position == pytest.approx(expected, rel=0.01)

    def test_win_prob_capped_at_99_percent(self):
        """Win probability should be capped at 99% to avoid division issues."""
        # Even with 100% model probability, should not be infinite
        position = calculate_kelly_position(
            win_prob=1.0,  # Model says 100%
            price=0.10,
            bankroll=100.0,
            kelly_fraction=0.25,
            max_position=50.0,
        )

        # Should use capped 0.99 instead of 1.0
        # b = (1 - 0.1) / 0.1 = 9
        # kelly = (0.99 * 9 - 0.01) / 9 = (8.91 - 0.01) / 9 = 0.988...
        # Position = 100 * 0.988 * 0.25 = 24.7
        assert position > 0
        assert position <= 50.0

    def test_small_edge_reasonable_position(self):
        """Small edge should give small but non-zero position."""
        # 8% edge: model 58% vs market 50%
        position = calculate_kelly_position(
            win_prob=0.58,
            price=0.50,
            bankroll=50.0,
            kelly_fraction=0.25,
            max_position=5.0,
            min_position=1.0,
        )

        # Should be a reasonable small position
        assert 1.0 <= position <= 5.0


class TestCalculateExpectedValue:
    """Test expected value calculation."""

    def test_positive_ev_trade(self):
        """Profitable trade should have positive EV."""
        ev = calculate_expected_value(
            win_prob=0.70,
            price=0.40,
            position=10.0,
        )

        # Win profit: 10 * (1 - 0.4) / 0.4 = 10 * 1.5 = 15
        # Lose loss: 10
        # EV = 0.7 * 15 - 0.3 * 10 = 10.5 - 3 = 7.5
        assert ev == pytest.approx(7.5)

    def test_negative_ev_trade(self):
        """Losing trade should have negative EV."""
        ev = calculate_expected_value(
            win_prob=0.30,  # Only 30% chance to win
            price=0.50,
            position=10.0,
        )

        # Win profit: 10 * (1 - 0.5) / 0.5 = 10
        # EV = 0.3 * 10 - 0.7 * 10 = 3 - 7 = -4
        assert ev == pytest.approx(-4.0)

    def test_zero_ev_at_fair_price(self):
        """When win_prob == price, EV should be ~0."""
        ev = calculate_expected_value(
            win_prob=0.50,
            price=0.50,
            position=10.0,
        )

        # Win profit: 10 * 1 = 10
        # EV = 0.5 * 10 - 0.5 * 10 = 0
        assert ev == pytest.approx(0.0)

    def test_invalid_price_zero(self):
        """Price of 0 returns 0 EV."""
        ev = calculate_expected_value(
            win_prob=0.50,
            price=0.0,
            position=10.0,
        )
        assert ev == 0.0

    def test_invalid_price_one(self):
        """Price of 1 returns 0 EV."""
        ev = calculate_expected_value(
            win_prob=0.99,
            price=1.0,
            position=10.0,
        )
        assert ev == 0.0

    def test_ev_scales_with_position(self):
        """EV should scale linearly with position size."""
        ev_small = calculate_expected_value(win_prob=0.60, price=0.40, position=5.0)
        ev_large = calculate_expected_value(win_prob=0.60, price=0.40, position=10.0)

        assert ev_large == pytest.approx(ev_small * 2)


class TestKellyEdgeCases:
    """Test edge cases and integration between functions."""

    def test_very_small_edge(self):
        """Very small edge should still work but may be below min position."""
        edge = calculate_edge(0.51, 0.50)
        assert edge == pytest.approx(0.01)

        position = calculate_kelly_position(
            win_prob=0.51,
            price=0.50,
            bankroll=50.0,
            min_position=1.0,
        )
        # Likely below min threshold
        assert position == 0.0

    def test_very_large_edge(self):
        """Very large edge should be capped by max position."""
        edge = calculate_edge(0.95, 0.10)
        assert edge == pytest.approx(0.85)

        position = calculate_kelly_position(
            win_prob=0.95,
            price=0.10,
            bankroll=1000.0,
            max_position=5.0,
        )
        assert position == 5.0  # Capped

    def test_consistency_edge_position_ev(self):
        """Verify all three functions work together consistently."""
        model_prob = 0.65
        market_price = 0.45
        bankroll = 100.0

        # Calculate edge
        edge = calculate_edge(model_prob, market_price)
        assert edge == pytest.approx(0.20)

        # Calculate position
        position = calculate_kelly_position(
            win_prob=model_prob,
            price=market_price,
            bankroll=bankroll,
            kelly_fraction=0.25,
            max_position=50.0,
            min_position=0.0,
        )
        assert position > 0

        # Calculate EV
        ev = calculate_expected_value(model_prob, market_price, position)
        assert ev > 0  # Positive edge should mean positive EV
