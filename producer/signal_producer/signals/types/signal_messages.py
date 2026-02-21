"""WebSocket message types for the signal marketplace."""

from dataclasses import dataclass, asdict
from typing import Literal

from .producer_signal_preview import PreviewPolymarketInfo


@dataclass
class SignalPreviewMessage:
    """Broadcast to all consumers: a signal is available for auction.

    Contains enough info for consumers to decide how much to bid,
    but NOT enough to act on the signal directly (no token_id, side, market_price).

    Fields that impact consumer pricing decisions:
    - producer_id: identity/reputation of the producer
    - edge: magnitude of the opportunity
    - last_price_paid_usd: what the last buyer paid
    - auction_ends_at: urgency / time pressure
    """

    msg_type: Literal["signal_preview"] = "signal_preview"
    signal_id: str = ""                     # UUID to reference this signal
    producer_id: str = ""                   # Producer identity (wallet address or alias)
    signal_type: str = "weather"            # Signal type discriminator
    model_probability: float = 0.0          # Model's predicted probability
    confidence: float = 0.0                 # Ensemble confidence (0-1)
    exchanges: list[PreviewPolymarketInfo] = None  # type: ignore[assignment]
    suggested_price_usd: float = 0.0        # LLM-determined starting price
    last_price_paid_usd: float = 0.0        # What the last buyer paid for a signal
    auction_ends_at: str = ""               # ISO timestamp — when the auction closes

    def __post_init__(self) -> None:
        if self.exchanges is None:
            self.exchanges = []

    def to_dict(self) -> dict:
        return asdict(self)
