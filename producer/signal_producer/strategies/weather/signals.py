"""Weather-specific signal calculation."""

from dataclasses import dataclass
from enum import Enum, auto
import structlog

from ..base import Signal
from .markets import WeatherMarket, WeatherEvent
from .open_meteo import EnsembleForecast
from ...trading.kelly import calculate_kelly_position, calculate_edge, calculate_expected_value

logger = structlog.get_logger()


class FilterReason(Enum):
    """Reasons a bucket was filtered out."""
    INVALID_BUCKET = auto()      # Could not parse temperature range
    LOW_PROBABILITY = auto()     # Model prob below min_bucket_probability
    INSUFFICIENT_EDGE = auto()   # Edge below threshold
    SMALL_POSITION = auto()      # Position size too small


@dataclass
class FilteredBucket:
    """Record of a bucket that was filtered out."""
    bucket_question: str
    reason: FilterReason
    model_prob: float | None = None
    market_price: float | None = None
    edge: float | None = None
    detail: str = ""


@dataclass
class ConfidenceFilter:
    """
    Filter configuration for weather strategy signal generation.

    Filters based on statistically defensible criteria:
    - min_bucket_probability: Requires enough ensemble members to agree
      for a reliable probability estimate. With n=31 members, at p=0.40
      the standard error is ~8.8%. Lower probabilities have higher
      estimation uncertainty.

    Note: Spread-based filters (std, min/max range) were removed after
    research showed they are "necessary but insufficient" for reliability
    and can be actively harmful. See: arxiv.org/html/2512.02160v1
    """
    min_bucket_probability: float = 0.35  # ~11 of 31 members must agree

    @classmethod
    def conservative(cls) -> "ConfidenceFilter":
        """Require strong consensus - 50%+ of members agree."""
        return cls(min_bucket_probability=0.50)  # 15+ members

    @classmethod
    def moderate(cls) -> "ConfidenceFilter":
        """Balanced - ~35% of members agree."""
        return cls(min_bucket_probability=0.35)  # 11+ members

    @classmethod
    def aggressive(cls) -> "ConfidenceFilter":
        """Lower threshold - ~25% of members."""
        return cls(min_bucket_probability=0.25)  # 8+ members

    @classmethod
    def disabled(cls) -> "ConfidenceFilter":
        """No filtering - only edge threshold matters."""
        return cls(min_bucket_probability=0.0)


def calculate_market_probability(
    ensemble: EnsembleForecast,
    market: WeatherMarket,
) -> float:
    """
    Calculate probability that the actual temperature falls in this market range.

    Uses ensemble member counts: P = (members in range) / (total members)
    """
    count = sum(
        1 for temp in ensemble.member_highs
        if market.contains_temp(temp)
    )
    return count / len(ensemble.member_highs)


def calculate_confidence(ensemble: EnsembleForecast) -> float:
    """
    Calculate confidence score based on ensemble spread.

    Lower spread = higher confidence.
    Returns value 0-1 where 1 = very confident.
    """
    spread = ensemble.max - ensemble.min

    # Typical spreads: 5-15°F for 1-2 day forecasts
    # Narrow spread (<5°F) = high confidence
    # Wide spread (>15°F) = low confidence
    if spread <= 5:
        return 1.0
    elif spread >= 20:
        return 0.3
    else:
        # Linear interpolation
        return 1.0 - (spread - 5) / 15 * 0.7


@dataclass
class SignalResult:
    """Result of signal calculation with filtering info."""
    signals: list[Signal]
    filtered: list[FilteredBucket]


def calculate_weather_signals(
    ensemble: EnsembleForecast,
    event: WeatherEvent,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_position: float = 5.0,
    edge_threshold: float = 0.08,
    confidence_filter: ConfidenceFilter | None = None,
) -> list[Signal]:
    """
    Calculate trading signals from ensemble forecast vs market prices.

    Args:
        ensemble: Ensemble forecast with 31 member highs
        event: Weather event with bucket markets
        bankroll: Available capital in USD
        kelly_fraction: Fraction of Kelly to use
        max_position: Maximum position per trade
        edge_threshold: Minimum edge to generate signal (e.g., 0.08 = 8%)
        confidence_filter: High confidence filter config (None = disabled)

    Returns:
        List of Signal objects, sorted by edge (highest first)
    """
    if confidence_filter is None:
        confidence_filter = ConfidenceFilter.disabled()

    signals = []
    filtered = []
    confidence = calculate_confidence(ensemble)

    for weather_market in event.active_markets:
        # Skip if market range couldn't be parsed
        if weather_market.low_temp is None and weather_market.high_temp is None:
            filtered.append(FilteredBucket(
                bucket_question=weather_market.question,
                reason=FilterReason.INVALID_BUCKET,
            ))
            continue

        model_prob = calculate_market_probability(ensemble, weather_market)
        market_price = weather_market.yes_price
        edge = calculate_edge(model_prob, market_price)

        # HIGH CONFIDENCE FILTER #3: Minimum bucket probability (consensus)
        if model_prob < confidence_filter.min_bucket_probability:
            filtered.append(FilteredBucket(
                bucket_question=weather_market.question,
                reason=FilterReason.LOW_PROBABILITY,
                model_prob=model_prob,
                market_price=market_price,
                edge=edge,
                detail=f"prob={model_prob:.0%} < min={confidence_filter.min_bucket_probability:.0%}",
            ))
            continue

        # Only consider positive edge above threshold
        if edge < edge_threshold:
            filtered.append(FilteredBucket(
                bucket_question=weather_market.question,
                reason=FilterReason.INSUFFICIENT_EDGE,
                model_prob=model_prob,
                market_price=market_price,
                edge=edge,
                detail=f"edge={edge:.1%} < threshold={edge_threshold:.1%}",
            ))
            continue

        position_size = calculate_kelly_position(
            win_prob=model_prob,
            price=market_price,
            bankroll=bankroll,
            kelly_fraction=kelly_fraction,
            max_position=max_position,
        )

        # Skip if position too small
        if position_size <= 0:
            filtered.append(FilteredBucket(
                bucket_question=weather_market.question,
                reason=FilterReason.SMALL_POSITION,
                model_prob=model_prob,
                market_price=market_price,
                edge=edge,
            ))
            continue

        ev = calculate_expected_value(model_prob, market_price, position_size)

        signals.append(Signal(
            strategy="weather",
            market_id=event.event_id,
            token_id=weather_market.yes_token_id,
            description=weather_market.question,
            target_date=ensemble.target_date,
            model_probability=model_prob,
            market_price=market_price,
            edge=edge,
            position_size_usd=position_size,
            expected_value=ev,
            confidence=confidence,
            metadata={
                "city": ensemble.city,
                "market_low": weather_market.low_temp,
                "market_high": weather_market.high_temp,
                "ensemble_std": ensemble.std,
            },
        ))

    # Log filter summary
    if filtered:
        filter_counts = {}
        for f in filtered:
            filter_counts[f.reason.name] = filter_counts.get(f.reason.name, 0) + 1
        logger.debug(
            "Buckets filtered",
            city=ensemble.city,
            target_date=str(ensemble.target_date),
            **filter_counts,
        )

    # Sort by edge, highest first
    return sorted(signals, key=lambda s: s.edge, reverse=True)
