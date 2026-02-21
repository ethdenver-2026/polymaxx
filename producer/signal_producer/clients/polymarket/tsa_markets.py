"""TSA passenger volume market data structures and parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date


@dataclass
class TSAMarket:
    """A single TSA passenger volume bracket market."""

    question: str
    group_item_title: str | None  # Short label like "2.2M-2.4M" or "below 2M"
    bracket_lower: int | None  # None for "below X"
    bracket_upper: int | None  # None for "above X"
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    active: bool
    closed: bool

    def contains_passengers(self, passengers: int) -> bool:
        """Check if a passenger count falls within this bracket."""
        if self.bracket_lower is None:
            return passengers < self.bracket_upper
        if self.bracket_upper is None:
            return passengers >= self.bracket_lower
        return self.bracket_lower <= passengers < self.bracket_upper


@dataclass
class TSAEvent:
    """A TSA passenger volume prediction event with multiple bracket markets."""

    event_id: str
    title: str
    target_date: date
    resolution_source: str
    markets: list[TSAMarket]
    closed: bool

    @property
    def active_markets(self) -> list[TSAMarket]:
        """Return only active, non-closed markets."""
        return [m for m in self.markets if m.active and not m.closed]


def _parse_millions(s: str) -> int:
    """Parse '2.2M' or '2,200,000' to integer."""
    s = s.strip()
    if s.endswith("M"):
        return int(float(s[:-1]) * 1_000_000)
    return int(s.replace(",", ""))


def parse_tsa_bracket(text: str, group_item_title: str | None = None) -> tuple[int | None, int | None]:
    """
    Extract passenger bracket from groupItemTitle or market question.

    Returns (lower, upper) where:
    - "<1.8M" → (None, 1_800_000)
    - "1.8M-2.0M" → (1_800_000, 2_000_000)
    - ">2.6M" → (2_600_000, None)

    Also handles question text formats:
    - "between 2.2M-2.4M" → (2_200_000, 2_400_000)
    - "below 2M" → (None, 2_000_000)
    - "greater than 2.6M" → (2_600_000, None)
    """
    # Prefer groupItemTitle if available (cleaner format)
    if group_item_title:
        # "<1.8M" format
        match = re.match(r"<(\d+\.?\d*M)", group_item_title)
        if match:
            return None, _parse_millions(match.group(1))

        # ">2.6M" format
        match = re.match(r">(\d+\.?\d*M)", group_item_title)
        if match:
            return _parse_millions(match.group(1)), None

        # "1.8M-2.0M" format
        match = re.match(r"(\d+\.?\d*M)\s*[-–]\s*(\d+\.?\d*M)", group_item_title)
        if match:
            return _parse_millions(match.group(1)), _parse_millions(match.group(2))

    # Fall back to parsing from question text
    question = text

    # "between 2.2M-2.4M" or "2.2M-2.4M" or "between 1.8 million and 2.0 million"
    match = re.search(r"between\s+(\d+\.?\d*)\s*(?:M|million)?\s*(?:and|-|–)\s*(\d+\.?\d*)\s*(?:M|million)", question, re.IGNORECASE)
    if match:
        val1, val2 = match.group(1), match.group(2)
        # Add M suffix if not present (assume millions)
        if not val1.endswith("M"):
            val1 += "M"
        if not val2.endswith("M"):
            val2 += "M"
        return _parse_millions(val1), _parse_millions(val2)

    # "below 2M" or "under 2M" or "less than 1.8 million"
    match = re.search(r"(?:below|under|less\s+than)\s+(\d+\.?\d*)\s*(?:M|million)?", question, re.IGNORECASE)
    if match:
        val = match.group(1)
        if not val.endswith("M"):
            val += "M"
        return None, _parse_millions(val)

    # "greater than 2.6M" or "2.6M or more" or "above 2.6M"
    match = re.search(r"(?:greater\s+than|above|over)\s+(\d+\.?\d*)\s*(?:M|million)?", question, re.IGNORECASE)
    if match:
        val = match.group(1)
        if not val.endswith("M"):
            val += "M"
        return _parse_millions(val), None

    match = re.search(r"(\d+\.?\d*)\s*(?:M|million)?\s+or\s+(?:more|above)", question, re.IGNORECASE)
    if match:
        val = match.group(1)
        if not val.endswith("M"):
            val += "M"
        return _parse_millions(val), None

    return None, None


def parse_tsa_event(data: dict, target_date: date) -> TSAEvent:
    """Parse Gamma API event JSON into TSAEvent."""
    tsa_markets = []

    for market_data in data.get("markets", []):
        question = market_data.get("question", "")
        group_item_title = market_data.get("groupItemTitle")
        lower, upper = parse_tsa_bracket(question, group_item_title)

        # Parse JSON strings (CRITICAL: these are JSON strings, not arrays)
        try:
            prices = json.loads(market_data.get("outcomePrices", "[]"))
            tokens = json.loads(market_data.get("clobTokenIds", "[]"))
        except json.JSONDecodeError:
            continue

        if len(prices) < 2 or len(tokens) < 2:
            continue

        tsa_markets.append(
            TSAMarket(
                question=question,
                group_item_title=market_data.get("groupItemTitle"),
                bracket_lower=lower,
                bracket_upper=upper,
                yes_price=float(prices[0]),
                no_price=float(prices[1]),
                yes_token_id=tokens[0],
                no_token_id=tokens[1],
                active=market_data.get("active", True),
                closed=market_data.get("closed", False),
            )
        )

    return TSAEvent(
        event_id=data.get("id", ""),
        title=data.get("title", ""),
        target_date=target_date,
        resolution_source=data.get("resolutionSource", ""),
        markets=tsa_markets,
        closed=data.get("closed", False),
    )
