"""Trade resolution service using Gamma API."""

import json
from datetime import date, datetime
from typing import TYPE_CHECKING
import httpx
import structlog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from ..models.models import Trade


logger = structlog.get_logger()


class ResolutionService:
    """Service to check trade resolution status from Polymarket."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.base_url = "https://gamma-api.polymarket.com"

    def _build_slug(self, city: str, target_date: date) -> str:
        """Build the weather event slug."""
        month = target_date.strftime("%B").lower()
        day = target_date.day
        year = target_date.year
        return f"highest-temperature-in-{city}-on-{month}-{day}-{year}"

    async def _fetch_event(self, city: str, target_date: date) -> dict | None:
        """Fetch event data from Gamma API."""
        slug = self._build_slug(city, target_date)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/events/slug/{slug}")

            if resp.status_code == 404:
                return None

            resp.raise_for_status()
            return resp.json()

    async def check_resolution(
        self, city: str, target_date: date
    ) -> dict | None:
        """
        Check if a weather market has been resolved.

        Args:
            city: City slug (e.g., "nyc")
            target_date: Target date of the market

        Returns:
            dict with winning_bucket, winning_token, etc. if resolved
            None if not yet resolved
        """
        event = await self._fetch_event(city, target_date)

        if not event or not event.get("closed"):
            return None

        for market in event.get("markets", []):
            if not market.get("closed"):
                continue

            try:
                prices = json.loads(market.get("outcomePrices", "[]"))
                tokens = json.loads(market.get("clobTokenIds", "[]"))
            except json.JSONDecodeError:
                continue

            if len(prices) >= 2 and prices[0] == "1":
                # YES won for this bucket
                return {
                    "winning_bucket": market.get("question", ""),
                    "winning_token": tokens[0] if tokens else None,
                    "resolution": "yes",
                }

        return None

    async def resolve_trade(
        self, trade: "Trade", session: "Session"
    ) -> bool:
        """
        Resolve a trade by checking Polymarket outcome.

        Args:
            trade: Trade record to resolve
            session: Database session

        Returns:
            True if resolved, False if not yet resolved
        """
        result = await self.check_resolution(trade.city, trade.target_date)

        if not result:
            return False

        # Check if our trade won
        won = trade.token_id == result["winning_token"]

        # Calculate P&L
        if won:
            # Win: we get position / fill_price back, minus what we paid
            pnl = trade.position_usd * (1 - trade.fill_price) / trade.fill_price
        else:
            # Lose: we lose the position
            pnl = -trade.position_usd

        # Update trade
        trade.status = "resolved"
        trade.pnl = pnl
        trade.resolution_source = "gamma_api"
        trade.resolved_at = datetime.utcnow()

        session.commit()

        logger.info(
            "Trade resolved",
            trade_id=trade.id,
            city=trade.city,
            won=won,
            pnl=f"${pnl:.2f}",
        )

        return True

    async def resolve_pending_trades(
        self, session: "Session"
    ) -> tuple[int, int]:
        """
        Resolve all pending trades that can be resolved.

        Args:
            session: Database session

        Returns:
            Tuple of (resolved_count, pending_count)
        """
        from ..models.models import Trade

        # Get trades that need resolution
        pending_trades = session.query(Trade).filter(
            Trade.status.in_(["filled"]),
            Trade.target_date < date.today(),
        ).all()

        resolved = 0
        still_pending = 0

        for trade in pending_trades:
            try:
                if await self.resolve_trade(trade, session):
                    resolved += 1
                else:
                    still_pending += 1
            except Exception as e:
                logger.warning(
                    "Failed to resolve trade",
                    trade_id=trade.id,
                    error=str(e),
                )
                still_pending += 1

        return resolved, still_pending
