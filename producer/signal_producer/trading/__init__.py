"""Trading logic - position sizing, execution."""
from .kelly import calculate_kelly_position

__all__ = ["calculate_kelly_position"]
