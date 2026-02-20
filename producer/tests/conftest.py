"""Shared test fixtures for signal_producer tests."""

import pytest
from datetime import date
from dataclasses import dataclass


@dataclass
class MockEnsembleForecast:
    """Mock ensemble forecast for testing without API calls."""

    city: str
    target_date: date
    member_highs: list[float]
    raw_response: dict | None = None

    @property
    def mean(self) -> float:
        return sum(self.member_highs) / len(self.member_highs)

    @property
    def std(self) -> float:
        mean = self.mean
        variance = sum((t - mean) ** 2 for t in self.member_highs) / len(self.member_highs)
        return variance ** 0.5

    @property
    def min(self) -> float:
        return min(self.member_highs)

    @property
    def max(self) -> float:
        return max(self.member_highs)


@dataclass
class MockWeatherMarket:
    """Mock weather market for testing."""

    question: str
    low_temp: float | None
    high_temp: float | None
    yes_price: float
    no_price: float
    yes_token_id: str = "mock_yes_token"
    no_token_id: str = "mock_no_token"
    active: bool = True
    closed: bool = False

    def contains_temp(self, temp: float) -> bool:
        """Check if a temperature falls within this market range."""
        if self.low_temp is None:
            return temp < self.high_temp
        if self.high_temp is None:
            return temp >= self.low_temp
        return self.low_temp <= temp < self.high_temp


# Backwards compatibility alias
MockWeatherBucket = MockWeatherMarket


@dataclass
class MockWeatherEvent:
    """Mock weather event for testing."""

    event_id: str
    title: str
    city: str
    target_date: date
    resolution_source: str
    markets: list[MockWeatherMarket]
    closed: bool = False

    @property
    def active_markets(self) -> list[MockWeatherMarket]:
        return [m for m in self.markets if m.active and not m.closed]

    # Backwards compatibility aliases
    @property
    def buckets(self) -> list[MockWeatherMarket]:
        return self.markets

    @property
    def active_buckets(self) -> list[MockWeatherMarket]:
        return self.active_markets


@pytest.fixture
def sample_ensemble() -> MockEnsembleForecast:
    """
    Standard 31-member ensemble forecast.

    Distribution centered at 42°F with realistic spread.
    Members range from ~38°F to ~46°F.
    """
    # Create a distribution that looks like a real ensemble
    # Center: 42°F, roughly normal distribution
    member_highs = [
        38.5, 39.2, 39.8, 40.1, 40.5,  # Cold tail
        40.8, 41.0, 41.2, 41.4, 41.6,  # Below mean
        41.8, 41.9, 42.0, 42.1, 42.2,  # Around mean
        42.3, 42.4, 42.5, 42.7, 42.9,  # Around mean
        43.1, 43.4, 43.7, 44.0, 44.3,  # Above mean
        44.6, 45.0, 45.4, 45.8, 46.2, 46.5,  # Warm tail
    ]

    return MockEnsembleForecast(
        city="nyc",
        target_date=date(2026, 2, 20),
        member_highs=member_highs,
    )


@pytest.fixture
def tight_ensemble() -> MockEnsembleForecast:
    """Ensemble with very low spread (high confidence)."""
    member_highs = [42.0 + i * 0.1 for i in range(31)]  # 42.0 to 45.0
    return MockEnsembleForecast(
        city="nyc",
        target_date=date(2026, 2, 20),
        member_highs=member_highs,
    )


@pytest.fixture
def wide_ensemble() -> MockEnsembleForecast:
    """Ensemble with high spread (low confidence)."""
    member_highs = [35.0 + i * 0.8 for i in range(31)]  # 35.0 to 59.0
    return MockEnsembleForecast(
        city="nyc",
        target_date=date(2026, 2, 20),
        member_highs=member_highs,
    )


@pytest.fixture
def sample_bucket() -> MockWeatherMarket:
    """Standard weather market for testing."""
    return MockWeatherMarket(
        question="Will the highest temperature be between 42-43°F?",
        low_temp=42.0,
        high_temp=44.0,  # Exclusive upper bound
        yes_price=0.20,
        no_price=0.80,
    )


@pytest.fixture
def below_bucket() -> MockWeatherMarket:
    """'X or below' market."""
    return MockWeatherMarket(
        question="Will the highest temperature be 39°F or below?",
        low_temp=None,
        high_temp=40.0,  # 39 or below means < 40
        yes_price=0.10,
        no_price=0.90,
    )


@pytest.fixture
def above_bucket() -> MockWeatherMarket:
    """'X or above' market."""
    return MockWeatherMarket(
        question="Will the highest temperature be 46°F or higher?",
        low_temp=46.0,
        high_temp=None,
        yes_price=0.15,
        no_price=0.85,
    )


@pytest.fixture
def sample_event(sample_bucket, below_bucket, above_bucket) -> MockWeatherEvent:
    """Standard weather event with multiple markets."""
    return MockWeatherEvent(
        event_id="mock_event_123",
        title="Highest temperature in NYC on February 20?",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA",
        markets=[below_bucket, sample_bucket, above_bucket],
    )
