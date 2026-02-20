"""
Signal schema shared between producer and consumer.

This is the wire format: the producer emits Signal objects (as JSON),
and the consumer reads them to decide whether to execute trades.
"""

from datetime import UTC, date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class MarketType(str, Enum):
    """Supported prediction market platforms."""

    POLYMARKET = "polymarket"
    KALSHI = "kalshi"


class SignalMetadata(BaseModel):
    """Strategy-specific metadata attached to a signal."""

    city: str | None = None
    bucket_low: float | None = None
    bucket_high: float | None = None
    extra: dict | None = None


class Signal(BaseModel):
    """
    A trading signal produced by the signal producer.

    This is the contract between producer and consumer.
    The producer calculates edge and position sizing;
    the consumer decides whether/how to execute.
    """

    # Identity
    strategy: str = Field(description="Strategy name, e.g. 'weather', 'esports'")
    market_type: MarketType = Field(default=MarketType.POLYMARKET)
    market_id: str = Field(description="Platform event/market ID")
    token_id: str = Field(description="CLOB token ID to trade")

    # Signal data
    description: str = Field(description="Human-readable description of the market")
    target_date: date = Field(description="When the market resolves")
    model_probability: float = Field(ge=0, le=1, description="Model's estimated probability")
    market_price: float = Field(ge=0, le=1, description="Current market price")
    edge: float = Field(description="model_probability - market_price")
    confidence: float = Field(ge=0, le=1, description="Model confidence score")

    # Sizing recommendation
    position_size_usd: float = Field(gt=0, description="Recommended position in USD")
    expected_value: float = Field(description="Expected profit in USD")

    # Metadata
    metadata: SignalMetadata | None = None
    produced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
