"""Base strategy interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass
class Signal:
    """A trading signal - generic across all strategies."""

    strategy: str  # 'weather', 'esports', etc.
    market_id: str  # Polymarket event/market ID
    token_id: str  # CLOB token ID
    description: str  # Human-readable description
    target_date: date  # Resolution date
    model_probability: float  # Our model's probability (0-1)
    market_price: float  # Current market price (0-1)
    edge: float  # model_probability - market_price
    position_size_usd: float  # Recommended position
    expected_value: float  # Expected profit
    confidence: float  # Model confidence (0-1)
    metadata: dict | None = None  # Strategy-specific data

    @property
    def edge_pct(self) -> float:
        """Edge as percentage."""
        return self.edge * 100


@dataclass
class StrategyResult:
    """Result of running a strategy."""

    signals: list[Signal]
    events_checked: int
    errors: list[str]


class BaseStrategy(ABC):
    """Abstract base class for trading strategies."""

    @abstractmethod
    async def generate_signals(self) -> StrategyResult:
        """Generate trading signals."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Return strategy name for logging."""
        pass
