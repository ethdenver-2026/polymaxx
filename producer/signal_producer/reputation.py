"""In-memory consumer reputation tracking. Will move onchain later."""

from __future__ import annotations

import os

import structlog

logger = structlog.get_logger()

try:
    BLACKLIST_THRESHOLD = int(os.getenv("REPUTATION_BLACKLIST_THRESHOLD", "3"))
except (ValueError, TypeError):
    logger.warning(
        "Invalid REPUTATION_BLACKLIST_THRESHOLD, using default=3",
        raw_value=os.getenv("REPUTATION_BLACKLIST_THRESHOLD"),
    )
    BLACKLIST_THRESHOLD = 3


class ReputationStore:
    """Tracks payment failure counts in-memory. Blacklists after threshold."""

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}

    def record_payment_failure(self, consumer_did: str) -> int:
        count = self._failures.get(consumer_did, 0) + 1
        self._failures[consumer_did] = count
        logger.info("Payment failure recorded", consumer_did=consumer_did, failures=count, blacklisted=count >= BLACKLIST_THRESHOLD)
        return count

    def record_payment_success(self, consumer_did: str) -> None:
        """Decay failure count on successful payment (floor at 0)."""
        current = self._failures.get(consumer_did, 0)
        if current > 0:
            self._failures[consumer_did] = current - 1
            logger.info("Payment success recorded, failure count decayed", consumer_did=consumer_did, failures=current - 1)

    def is_blacklisted(self, consumer_did: str) -> bool:
        return self._failures.get(consumer_did, 0) >= BLACKLIST_THRESHOLD
