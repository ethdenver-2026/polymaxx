"""Historical Polymarket price fetching for backtesting.

Uses the CLOB prices-history API to fetch historical market prices.

KNOWN LIMITATION: For resolved markets, prices-history has ~12hr granularity.
This means we can only get approximate prices at forecast time, not exact prices.

See: https://docs.polymarket.com/developers/CLOB/timeseries
"""

from datetime import date, datetime
from typing import NamedTuple

import httpx
import structlog

from ..clients.gamma import GammaClient


logger = structlog.get_logger()

CLOB_API_URL = "https://clob.polymarket.com"


class PricePoint(NamedTuple):
    """A single price observation."""
    timestamp: int  # Unix timestamp
    price: float


class PriceHistoryClient:
    """Fetch historical Polymarket prices for backtesting.

    KNOWN LIMITATION: For resolved markets, the prices-history endpoint
    has approximately 12-hour granularity. This means we cannot get
    exact entry prices for backtesting - only approximate values.

    For future dates (live trading), prices should be captured at
    signal generation time instead.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.base_url = CLOB_API_URL
        self.gamma_client = GammaClient(timeout=timeout)

    async def get_price_history(
        self,
        token_id: str,
        interval: str = "max",
    ) -> list[PricePoint]:
        """
        Get price history for a token.

        Args:
            token_id: CLOB token ID
            interval: Time interval ("1m", "1h", "6h", "1d", "1w", "max")

        Returns:
            List of PricePoint tuples sorted by timestamp
        """
        params = {
            "market": token_id,
            "interval": interval,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(
                    f"{self.base_url}/prices-history",
                    params=params,
                )

                if resp.status_code == 404:
                    return []

                resp.raise_for_status()
                data = resp.json()

            history = data.get("history", [])
            return [
                PricePoint(timestamp=point["t"], price=point["p"])
                for point in history
            ]

        except Exception as e:
            logger.warning(
                "Failed to fetch price history",
                error=str(e),
                token_id=token_id,
            )
            return []

    async def get_price_at_time(
        self,
        token_id: str,
        timestamp: int,
    ) -> float | None:
        """
        Get market price at or near a specific time.

        NOTE: Due to 12hr granularity limitation, this returns the
        nearest available price point, which may not be exact.

        Args:
            token_id: CLOB token ID
            timestamp: Unix timestamp

        Returns:
            Price at or near the timestamp, or None if unavailable
        """
        history = await self.get_price_history(token_id)

        if not history:
            return None

        # Find closest price point to requested timestamp
        closest = min(history, key=lambda p: abs(p.timestamp - timestamp))

        # Warn if the closest point is more than 12 hours away
        time_diff = abs(closest.timestamp - timestamp)
        if time_diff > 43200:  # 12 hours in seconds
            logger.debug(
                "Price point distant from requested time",
                token_id=token_id,
                requested_time=datetime.fromtimestamp(timestamp).isoformat(),
                closest_time=datetime.fromtimestamp(closest.timestamp).isoformat(),
                hours_diff=time_diff / 3600,
            )

        return closest.price

    async def get_bucket_prices_at_forecast_time(
        self,
        city: str,
        target_date: date,
        forecast_datetime: datetime,
    ) -> dict[str, float]:
        """
        Get all bucket prices at the time a forecast was made.

        Args:
            city: City slug (e.g., "nyc")
            target_date: Target date of the weather event
            forecast_datetime: When the forecast was made

        Returns:
            Dict mapping bucket question -> price at forecast time
        """
        # Fetch the event to get token IDs
        event = await self.gamma_client.fetch_weather_event(city, target_date)

        if event is None:
            logger.warning(
                "Weather event not found",
                city=city,
                target_date=str(target_date),
            )
            return {}

        forecast_ts = int(forecast_datetime.timestamp())
        prices = {}

        for bucket in event.buckets:
            price = await self.get_price_at_time(bucket.yes_token_id, forecast_ts)
            if price is not None:
                prices[bucket.question] = price
            else:
                # Fall back to current price if historical not available
                prices[bucket.question] = bucket.yes_price
                logger.debug(
                    "Using current price (no historical data)",
                    bucket=bucket.question,
                )

        return prices

    async def get_entry_prices_for_backtest(
        self,
        city: str,
        target_date: date,
        forecast_date: date,
        forecast_hour: int = 12,  # Noon local time
    ) -> dict[str, float]:
        """
        Get entry prices for backtesting a specific date.

        Convenience method that constructs the forecast datetime
        and fetches bucket prices.

        Args:
            city: City slug
            target_date: Target date of the weather event
            forecast_date: Date when forecast was made
            forecast_hour: Hour of day for forecast (default noon)

        Returns:
            Dict mapping bucket question -> price
        """
        forecast_dt = datetime(
            forecast_date.year,
            forecast_date.month,
            forecast_date.day,
            forecast_hour,
            0,
        )

        return await self.get_bucket_prices_at_forecast_time(
            city, target_date, forecast_dt
        )
