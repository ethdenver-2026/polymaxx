"""Weather-specific signal calculation."""

from ..base import Signal
from .markets import WeatherBucket, WeatherEvent
from .open_meteo import EnsembleForecast
from ...trading.kelly import calculate_kelly_position, calculate_edge, calculate_expected_value


def calculate_bucket_probability(
    ensemble: EnsembleForecast,
    bucket: WeatherBucket,
) -> float:
    """
    Calculate probability that the actual temperature falls in this bucket.

    Uses ensemble member counts: P = (members in bucket) / (total members)
    """
    count = sum(
        1 for temp in ensemble.member_highs
        if bucket.contains_temp(temp)
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


def calculate_weather_signals(
    ensemble: EnsembleForecast,
    event: WeatherEvent,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_position: float = 5.0,
    edge_threshold: float = 0.08,
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

    Returns:
        List of Signal objects, sorted by edge (highest first)
    """
    signals = []
    confidence = calculate_confidence(ensemble)

    for bucket in event.active_buckets:
        # Skip if bucket range couldn't be parsed
        if bucket.low_temp is None and bucket.high_temp is None:
            continue

        model_prob = calculate_bucket_probability(ensemble, bucket)
        market_price = bucket.yes_price
        edge = calculate_edge(model_prob, market_price)

        # Only consider positive edge above threshold
        if edge < edge_threshold:
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
            continue

        ev = calculate_expected_value(model_prob, market_price, position_size)

        signals.append(Signal(
            strategy="weather",
            market_id=event.event_id,
            token_id=bucket.yes_token_id,
            description=bucket.question,
            target_date=ensemble.target_date,
            model_probability=model_prob,
            market_price=market_price,
            edge=edge,
            position_size_usd=position_size,
            expected_value=ev,
            confidence=confidence,
            metadata={
                "city": ensemble.city,
                "bucket_low": bucket.low_temp,
                "bucket_high": bucket.high_temp,
            },
        ))

    # Sort by edge, highest first
    return sorted(signals, key=lambda s: s.edge, reverse=True)
