"""Backtest engine for historical strategy evaluation.

Simulates trading by:
1. Loading historical GEFS ensemble forecasts
2. Fetching historical Polymarket prices
3. Determining actual outcomes from resolved markets
4. Calculating theoretical P&L
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import NamedTuple
import json

import httpx
import structlog

from ..config import CITIES, CityConfig
from ..strategies.weather.markets import WeatherBucket
from ..strategies.weather.open_meteo import OpenMeteoClient, EnsembleForecast
from ..trading.kelly import calculate_kelly_position, calculate_edge

logger = structlog.get_logger()

# Polymarket APIs
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CLOB_API_URL = "https://clob.polymarket.com"


class TradeResult(NamedTuple):
    """Result of a simulated trade."""
    city: str
    target_date: date
    bucket_question: str
    forecast_temp: float  # Ensemble mean
    actual_temp: float | None
    model_prob: float
    market_price: float
    edge: float
    position_usd: float
    won: bool | None  # None if not yet resolved
    pnl: float | None


@dataclass
class BacktestResult:
    """Complete backtest results."""
    start_date: date
    end_date: date
    cities: list[str]
    trades: list[TradeResult] = field(default_factory=list)
    total_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0
    unresolved_count: int = 0

    @property
    def win_rate(self) -> float:
        resolved = self.win_count + self.loss_count
        return self.win_count / resolved if resolved > 0 else 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            f"Backtest: {self.start_date} to {self.end_date}",
            f"Cities: {', '.join(self.cities)}",
            f"Total trades: {self.total_trades}",
            f"Resolved: {self.win_count + self.loss_count}",
            f"Win rate: {self.win_rate*100:.1f}%",
            f"Total P&L: ${self.total_pnl:.2f}",
        ]
        return "\n".join(lines)


class BacktestEngine:
    """Engine for running historical backtests.

    Args:
        open_meteo_client: Open-Meteo client for fetching historical forecasts
        bankroll: Starting capital in USD
        kelly_fraction: Fraction of Kelly criterion to use
        max_position: Maximum position size per trade
        edge_threshold: Minimum edge to trade (e.g., 0.08 = 8%)
    """

    def __init__(
        self,
        open_meteo_client: OpenMeteoClient | None = None,
        bankroll: float = 50.0,
        kelly_fraction: float = 0.25,
        max_position: float = 5.0,
        edge_threshold: float = 0.08,
        timeout: float = 30.0,
    ):
        self.open_meteo = open_meteo_client or OpenMeteoClient()
        self.bankroll = bankroll
        self.kelly_fraction = kelly_fraction
        self.max_position = max_position
        self.edge_threshold = edge_threshold
        self.timeout = timeout

    def _build_slug(self, city: str, target_date: date) -> str:
        """Build Polymarket event slug."""
        month = target_date.strftime("%B").lower()
        day = target_date.day
        year = target_date.year
        return f"highest-temperature-in-{city}-on-{month}-{day}-{year}"

    async def _fetch_event_data(self, city: str, target_date: date) -> dict | None:
        """Fetch event data from Gamma API."""
        slug = self._build_slug(city, target_date)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{GAMMA_API_URL}/events/slug/{slug}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def _get_historical_price(
        self,
        token_id: str,
        target_timestamp: int,
    ) -> float | None:
        """Get market price at a specific time.

        Uses the timeseries API to find price near the target time.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Fetch price history around target time
            start_ts = target_timestamp - 86400  # 1 day before
            end_ts = target_timestamp

            try:
                resp = await client.get(
                    f"{CLOB_API_URL}/prices-history",
                    params={
                        "market": token_id,
                        "startTs": start_ts,
                        "endTs": end_ts,
                    },
                )

                if resp.status_code != 200:
                    return None

                data = resp.json()
                history = data.get("history", [])

                if not history:
                    return None

                # Find price closest to target time (but before it)
                valid_prices = [h for h in history if h["t"] <= target_timestamp]
                if not valid_prices:
                    return None

                closest = max(valid_prices, key=lambda x: x["t"])
                return float(closest["p"])
            except Exception as e:
                logger.debug("Failed to fetch historical price", token=token_id, error=str(e))
                return None

    async def _get_bucket_historical_prices(
        self,
        buckets: list[WeatherBucket],
        forecast_timestamp: int,
    ) -> dict[str, float]:
        """Get historical prices for all buckets at forecast time.

        Returns:
            Dict mapping yes_token_id to historical price
        """
        prices = {}
        for bucket in buckets:
            price = await self._get_historical_price(bucket.yes_token_id, forecast_timestamp)
            if price is not None:
                prices[bucket.yes_token_id] = price
        return prices

    def _parse_buckets(self, event_data: dict) -> list[WeatherBucket]:
        """Parse bucket markets from event data."""
        from ..strategies.weather.markets import parse_temp_range

        buckets = []
        for market in event_data.get("markets", []):
            try:
                prices = json.loads(market.get("outcomePrices", "[]"))
                tokens = json.loads(market.get("clobTokenIds", "[]"))
            except json.JSONDecodeError:
                continue

            if len(prices) < 2 or len(tokens) < 2:
                continue

            question = market.get("question", "")
            low, high = parse_temp_range(question)

            buckets.append(WeatherBucket(
                question=question,
                low_temp=low,
                high_temp=high,
                yes_price=float(prices[0]),
                no_price=float(prices[1]),
                yes_token_id=tokens[0],
                no_token_id=tokens[1],
                active=market.get("active", True),
                closed=market.get("closed", False),
            ))

        return buckets

    def _find_winning_bucket(self, event_data: dict) -> str | None:
        """Find which bucket won (for resolved events)."""
        for market in event_data.get("markets", []):
            if not market.get("closed"):
                continue

            try:
                prices = json.loads(market.get("outcomePrices", "[]"))
            except json.JSONDecodeError:
                continue

            if len(prices) >= 2 and prices[0] == "1":
                return market.get("question", "")

        return None

    def _bucket_contains_temp(self, bucket: WeatherBucket, temp: float) -> bool:
        """Check if temperature falls in bucket range."""
        return bucket.contains_temp(temp)

    def _calculate_model_prob(
        self,
        ensemble: EnsembleForecast,
        bucket: WeatherBucket,
    ) -> float:
        """Calculate model probability for a bucket."""
        count = sum(
            1 for temp in ensemble.member_highs
            if self._bucket_contains_temp(bucket, temp)
        )
        return count / len(ensemble.member_highs)

    async def run_single_day(
        self,
        city: str,
        city_config: CityConfig,
        target_date: date,
    ) -> list[TradeResult]:
        """Run backtest for a single city/date.

        Args:
            city: City slug
            city_config: City configuration
            target_date: Date of the weather market

        Returns:
            List of trade results for this day
        """
        from datetime import datetime, timezone

        results = []

        # Forecast is made day before target
        forecast_date = target_date - timedelta(days=1)

        # Fetch ensemble forecast using Open-Meteo historical API
        ensemble = await self.open_meteo.get_historical_forecast(
            lat=city_config.lat,
            lon=city_config.lon,
            forecast_date=forecast_date,
            target_date=target_date,
            timezone=city_config.tz,
            city=city,
        )

        if ensemble is None:
            logger.warning("No forecast data", city=city, forecast_date=str(forecast_date))
            return results

        # Fetch market data (for resolution)
        event_data = await self._fetch_event_data(city, target_date)
        if event_data is None:
            logger.debug("No market data", city=city, target_date=str(target_date))
            return results

        # Parse buckets
        buckets = self._parse_buckets(event_data)
        if not buckets:
            logger.debug("No buckets found", city=city, target_date=str(target_date))
            return results

        # Find winning bucket (actual outcome)
        winning_question = self._find_winning_bucket(event_data)
        is_resolved = event_data.get("closed", False)

        # Infer actual temperature from winning bucket
        actual_temp = None
        if winning_question:
            for b in buckets:
                if b.question == winning_question:
                    if b.low_temp is not None and b.high_temp is not None:
                        actual_temp = (b.low_temp + b.high_temp) / 2
                    elif b.high_temp is not None:
                        actual_temp = b.high_temp - 1  # "X or below"
                    elif b.low_temp is not None:
                        actual_temp = b.low_temp + 1  # "X or above"
                    break

        # Get historical prices at forecast time (noon on forecast day)
        forecast_dt = datetime(
            forecast_date.year, forecast_date.month, forecast_date.day,
            12, 0, 0, tzinfo=timezone.utc
        )
        forecast_timestamp = int(forecast_dt.timestamp())

        historical_prices = await self._get_bucket_historical_prices(buckets, forecast_timestamp)

        if not historical_prices:
            logger.debug("No historical prices", city=city, target_date=str(target_date))
            return results

        # Evaluate each bucket
        for bucket in buckets:
            if bucket.low_temp is None and bucket.high_temp is None:
                continue

            # Use historical price, not resolved price
            market_price = historical_prices.get(bucket.yes_token_id)
            if market_price is None:
                continue

            # Skip invalid prices
            if market_price <= 0 or market_price >= 1:
                continue

            model_prob = self._calculate_model_prob(ensemble, bucket)
            edge = calculate_edge(model_prob, market_price)

            # Only trade with sufficient edge
            if edge < self.edge_threshold:
                continue

            position = calculate_kelly_position(
                win_prob=model_prob,
                price=market_price,
                bankroll=self.bankroll,
                kelly_fraction=self.kelly_fraction,
                max_position=self.max_position,
            )

            if position <= 0:
                continue

            # Determine outcome
            won = None
            pnl = None

            if is_resolved and winning_question:
                won = bucket.question == winning_question
                if won:
                    # Win payout
                    pnl = position * (1 - market_price) / market_price
                else:
                    pnl = -position

            results.append(TradeResult(
                city=city,
                target_date=target_date,
                bucket_question=bucket.question,
                forecast_temp=ensemble.mean,
                actual_temp=actual_temp,
                model_prob=model_prob,
                market_price=market_price,
                edge=edge,
                position_usd=position,
                won=won,
                pnl=pnl,
            ))

        return results

    async def run(
        self,
        start_date: date,
        end_date: date,
        cities: list[str] | None = None,
    ) -> BacktestResult:
        """Run full backtest over date range.

        Args:
            start_date: First date to backtest
            end_date: Last date to backtest (inclusive)
            cities: List of city slugs (defaults to all)

        Returns:
            BacktestResult with all trades and statistics
        """
        city_slugs = cities or list(CITIES.keys())
        result = BacktestResult(
            start_date=start_date,
            end_date=end_date,
            cities=city_slugs,
        )

        current = start_date
        while current <= end_date:
            logger.info("Backtesting date", date=str(current))

            for city in city_slugs:
                city_config = CITIES.get(city)
                if not city_config:
                    continue

                try:
                    trades = await self.run_single_day(city, city_config, current)
                    result.trades.extend(trades)
                except Exception as e:
                    logger.warning(
                        "Backtest error",
                        city=city,
                        date=str(current),
                        error=str(e),
                    )

            current += timedelta(days=1)

        # Calculate totals
        for trade in result.trades:
            if trade.pnl is not None:
                result.total_pnl += trade.pnl
                if trade.won:
                    result.win_count += 1
                else:
                    result.loss_count += 1
            else:
                result.unresolved_count += 1

        return result
