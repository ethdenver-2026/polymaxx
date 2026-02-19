"""Kelly criterion position sizing."""


def calculate_kelly_position(
    win_prob: float,
    price: float,
    bankroll: float,
    kelly_fraction: float = 0.25,
    max_position: float = 5.0,
    min_position: float = 1.0,
) -> float:
    """
    Calculate position size using fractional Kelly criterion.

    Args:
        win_prob: Estimated probability of winning (0-1)
        price: Current market price (0-1)
        bankroll: Total available capital
        kelly_fraction: Fraction of Kelly to use (default 0.25 = quarter Kelly)
        max_position: Maximum position size in USD
        min_position: Minimum position size in USD (below this, don't trade)

    Returns:
        Position size in USD, or 0 if not worth trading
    """
    # Sanity checks
    if win_prob <= price:
        return 0.0  # No edge

    if price <= 0 or price >= 1:
        return 0.0  # Invalid price

    if win_prob <= 0:
        return 0.0  # Invalid probability

    # Cap probability at 0.99 to avoid division issues
    # (even if model says 100%, we should assume some small error)
    win_prob = min(win_prob, 0.99)

    # Win payout ratio: if you buy at price p and win, you get (1-p)/p return
    # For binary outcomes, b = (1 - price) / price
    b = (1 - price) / price

    # Kelly formula: f* = (p * b - q) / b
    # where p = win_prob, q = 1 - p, b = payout ratio
    q = 1 - win_prob
    kelly = (win_prob * b - q) / b

    # Apply Kelly fraction (quarter Kelly is safer)
    position = bankroll * kelly * kelly_fraction

    # Apply limits
    if position < min_position:
        return 0.0  # Too small to bother

    return min(position, max_position)


def calculate_expected_value(
    win_prob: float,
    price: float,
    position: float,
) -> float:
    """
    Calculate expected value of a trade.

    Args:
        win_prob: Probability of winning
        price: Purchase price
        position: Position size in USD

    Returns:
        Expected profit in USD
    """
    if price <= 0 or price >= 1:
        return 0.0

    # If we win: we get (1/price) * position back, so profit = position * (1-price)/price
    # If we lose: we lose the full position
    win_profit = position * (1 - price) / price
    lose_loss = position

    ev = win_prob * win_profit - (1 - win_prob) * lose_loss
    return ev


def calculate_edge(model_prob: float, market_price: float) -> float:
    """
    Calculate edge as the difference between model probability and market price.

    Args:
        model_prob: Model's estimated probability (0-1)
        market_price: Current market price (0-1)

    Returns:
        Edge as a fraction (e.g., 0.10 = 10% edge)
    """
    return model_prob - market_price
