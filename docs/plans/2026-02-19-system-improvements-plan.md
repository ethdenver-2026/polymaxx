# System Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add backtesting, trade resolution, dashboard, and DRY cleanup to the Polymarket weather trading bot.

**Architecture:** Async-first Python with FastAPI dashboard. SQLite with WAL mode for concurrent access. HTMX for real-time dashboard updates. NOAA GEFS data from AWS S3 for backtesting.

**Tech Stack:** Python 3.12, FastAPI, HTMX, SQLAlchemy, httpx, cfgrib, pytest-asyncio

**Design Doc:** `docs/plans/2026-02-19-system-improvements-design.md`

---

## Phase 1: DRY Cleanup (Async-First)

### Task 1.1: Refactor OpenMeteoClient to Async-Only

**Files:**
- Modify: `src/clients/open_meteo.py`
- Modify: `tests/test_open_meteo.py`

**Step 1: Update test to use async**

```python
# tests/test_open_meteo.py
import pytest
from datetime import date, timedelta

from src.clients.open_meteo import OpenMeteoClient


@pytest.mark.asyncio
async def test_get_ensemble_forecast_returns_31_members():
    client = OpenMeteoClient()
    target = date.today() + timedelta(days=1)

    forecast = await client.get_ensemble_forecast(
        lat=40.7128,
        lon=-74.0060,
        target_date=target,
        timezone="America/New_York",
        city="nyc",
    )

    assert len(forecast.member_highs) == 31
    assert forecast.city == "nyc"
    assert forecast.target_date == target


@pytest.mark.asyncio
async def test_get_ensemble_forecast_temps_in_reasonable_range():
    client = OpenMeteoClient()
    target = date.today() + timedelta(days=1)

    forecast = await client.get_ensemble_forecast(
        lat=40.7128,
        lon=-74.0060,
        target_date=target,
        timezone="America/New_York",
        city="nyc",
    )

    # Temps should be between -50°F and 150°F
    for temp in forecast.member_highs:
        assert -50 < temp < 150
```

**Step 2: Run test to verify current state**

Run: `pytest tests/test_open_meteo.py -v`

**Step 3: Remove sync method from OpenMeteoClient**

```python
# src/clients/open_meteo.py
"""Open-Meteo Ensemble API client."""

from datetime import date
from dataclasses import dataclass
import httpx


ENSEMBLE_API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


@dataclass
class EnsembleForecast:
    """Ensemble forecast result with 31 member daily highs."""

    city: str
    target_date: date
    member_highs: list[float]

    @property
    def mean(self) -> float:
        return sum(self.member_highs) / len(self.member_highs)

    @property
    def std(self) -> float:
        mean = self.mean
        variance = sum((t - mean) ** 2 for t in self.member_highs) / len(self.member_highs)
        return variance ** 0.5

    @property
    def min(self) -> float:
        return min(self.member_highs)

    @property
    def max(self) -> float:
        return max(self.member_highs)


class OpenMeteoClient:
    """Client for Open-Meteo Ensemble API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def get_ensemble_forecast(
        self,
        lat: float,
        lon: float,
        target_date: date,
        timezone: str,
        city: str = "unknown",
    ) -> EnsembleForecast:
        """
        Fetch 31-member ensemble forecast for a specific date.

        Args:
            lat: Latitude
            lon: Longitude
            target_date: Date to forecast
            timezone: Timezone string (e.g., "America/New_York")
            city: City identifier for logging

        Returns:
            EnsembleForecast with 31 daily high temperatures
        """
        days_out = (target_date - date.today()).days + 1

        params = {
            "latitude": lat,
            "longitude": lon,
            "models": "gfs_seamless",
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": timezone,
            "forecast_days": max(days_out, 1),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(ENSEMBLE_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        hourly = data["hourly"]
        times = hourly["time"]

        target_str = str(target_date)
        target_indices = [i for i, t in enumerate(times) if t.startswith(target_str)]

        if not target_indices:
            raise ValueError(f"No forecast data for {target_date}")

        member_keys = ["temperature_2m"] + [
            f"temperature_2m_member{i:02d}" for i in range(1, 31)
        ]

        member_highs = []
        for key in member_keys:
            if key not in hourly:
                raise ValueError(f"Missing ensemble member: {key}")
            temps_for_day = [hourly[key][i] for i in target_indices]
            daily_high = max(temps_for_day)
            member_highs.append(daily_high)

        return EnsembleForecast(
            city=city,
            target_date=target_date,
            member_highs=member_highs,
        )
```

**Step 4: Run tests**

Run: `pytest tests/test_open_meteo.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clients/open_meteo.py tests/test_open_meteo.py
git commit -m "refactor: make OpenMeteoClient async-only"
```

---

### Task 1.2: Refactor GammaClient to Async-Only

**Files:**
- Modify: `src/clients/gamma.py`
- Create: `tests/test_gamma.py`

**Step 1: Write async test**

```python
# tests/test_gamma.py
import pytest
from datetime import date, timedelta

from src.clients.gamma import GammaClient, parse_temp_range


def test_parse_temp_range_between():
    low, high = parse_temp_range("between 34-35°F")
    assert low == 34
    assert high == 36  # Exclusive upper bound


def test_parse_temp_range_or_below():
    low, high = parse_temp_range("31°F or below")
    assert low is None
    assert high == 32


def test_parse_temp_range_or_higher():
    low, high = parse_temp_range("46°F or higher")
    assert low == 46
    assert high is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_weather_event_returns_buckets():
    client = GammaClient()
    tomorrow = date.today() + timedelta(days=1)

    event = await client.fetch_weather_event("nyc", tomorrow)

    # May be None if no market exists
    if event:
        assert event.city == "nyc"
        assert event.target_date == tomorrow
        assert len(event.buckets) > 0
```

**Step 2: Run tests**

Run: `pytest tests/test_gamma.py -v`

**Step 3: Refactor GammaClient to async-only**

```python
# src/clients/gamma.py
"""Polymarket Gamma API client for weather events."""

import json
import re
from datetime import date, timedelta
from dataclasses import dataclass
import httpx


GAMMA_API_URL = "https://gamma-api.polymarket.com"


@dataclass
class WeatherBucket:
    """A single temperature bucket market."""

    question: str
    low_temp: float | None
    high_temp: float | None
    yes_price: float
    no_price: float
    yes_token_id: str
    no_token_id: str
    active: bool
    closed: bool

    def contains_temp(self, temp: float) -> bool:
        if self.low_temp is None:
            return temp < self.high_temp
        if self.high_temp is None:
            return temp >= self.low_temp
        return self.low_temp <= temp < self.high_temp


@dataclass
class WeatherEvent:
    """A weather prediction event with multiple temperature buckets."""

    event_id: str
    title: str
    city: str
    target_date: date
    resolution_source: str
    buckets: list[WeatherBucket]
    closed: bool

    @property
    def active_buckets(self) -> list[WeatherBucket]:
        return [b for b in self.buckets if b.active and not b.closed]


def parse_temp_range(question: str) -> tuple[float | None, float | None]:
    """Extract temperature range from market question."""
    match = re.search(r"between (\d+)-(\d+)", question)
    if match:
        return float(match.group(1)), float(match.group(2)) + 1

    match = re.search(r"(\d+)°F or below", question)
    if match:
        return None, float(match.group(1)) + 1

    match = re.search(r"(\d+)°F or (?:higher|above)", question)
    if match:
        return float(match.group(1)), None

    return None, None


class GammaClient:
    """Client for Polymarket Gamma API."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.base_url = GAMMA_API_URL

    def _build_slug(self, city: str, target_date: date) -> str:
        month = target_date.strftime("%B").lower()
        day = target_date.day
        year = target_date.year
        return f"highest-temperature-in-{city}-on-{month}-{day}-{year}"

    async def fetch_weather_event(
        self, city: str, target_date: date
    ) -> WeatherEvent | None:
        """Fetch a weather event for a specific city and date."""
        slug = self._build_slug(city, target_date)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}/events/slug/{slug}")

            if resp.status_code == 404:
                return None

            resp.raise_for_status()
            data = resp.json()

        return self._parse_event(data, city, target_date)

    def _parse_event(
        self, data: dict, city: str, target_date: date
    ) -> WeatherEvent:
        """Parse event JSON into WeatherEvent."""
        buckets = []

        for market in data.get("markets", []):
            question = market.get("question", "")
            low, high = parse_temp_range(question)

            try:
                prices = json.loads(market.get("outcomePrices", "[]"))
                tokens = json.loads(market.get("clobTokenIds", "[]"))
            except json.JSONDecodeError:
                continue

            if len(prices) < 2 or len(tokens) < 2:
                continue

            buckets.append(
                WeatherBucket(
                    question=question,
                    low_temp=low,
                    high_temp=high,
                    yes_price=float(prices[0]),
                    no_price=float(prices[1]),
                    yes_token_id=tokens[0],
                    no_token_id=tokens[1],
                    active=market.get("active", True),
                    closed=market.get("closed", False),
                )
            )

        return WeatherEvent(
            event_id=data.get("id", ""),
            title=data.get("title", ""),
            city=city,
            target_date=target_date,
            resolution_source=data.get("resolutionSource", ""),
            buckets=buckets,
            closed=data.get("closed", False),
        )

    async def discover_weather_events(
        self, cities: list[str], days_ahead: int = 7
    ) -> list[WeatherEvent]:
        """Discover all active weather events for given cities."""
        events = []
        today = date.today()

        for city in cities:
            for day_offset in range(1, days_ahead + 1):
                target = today + timedelta(days=day_offset)
                event = await self.fetch_weather_event(city, target)

                if event and not event.closed and event.active_buckets:
                    events.append(event)

        return events
```

**Step 4: Run tests**

Run: `pytest tests/test_gamma.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/clients/gamma.py tests/test_gamma.py
git commit -m "refactor: make GammaClient async-only"
```

---

### Task 1.3: Refactor WeatherStrategy to Async-Only

**Files:**
- Modify: `src/strategy/weather.py`
- Modify: `src/strategy/base.py`

**Step 1: Update BaseStrategy to async-only**

```python
# src/strategy/base.py
"""Base strategy interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..trading.edge import Signal


@dataclass
class StrategyResult:
    """Result from signal generation."""

    signals: list[Signal]
    events_checked: int
    errors: list[str]


class BaseStrategy(ABC):
    """Abstract base class for trading strategies."""

    @abstractmethod
    def get_name(self) -> str:
        """Return strategy name (e.g., 'weather', 'esports')."""
        ...

    @abstractmethod
    async def generate_signals(self) -> StrategyResult:
        """Generate trading signals."""
        ...
```

**Step 2: Update WeatherStrategy**

```python
# src/strategy/weather.py
"""Weather prediction strategy using ensemble forecasts."""

from datetime import date
import structlog

from ..config import Settings, CITIES
from ..clients.open_meteo import OpenMeteoClient
from ..clients.gamma import GammaClient
from ..trading.edge import calculate_signals, Signal
from .base import BaseStrategy, StrategyResult


logger = structlog.get_logger()


class WeatherStrategy(BaseStrategy):
    """
    Strategy that compares ensemble weather forecasts to Polymarket prices.
    """

    def __init__(
        self,
        settings: Settings,
        cities: list[str] | None = None,
    ):
        self.settings = settings
        self.city_slugs = cities or ["nyc", "chicago", "miami"]
        self.open_meteo = OpenMeteoClient()
        self.gamma = GammaClient()

    def get_name(self) -> str:
        return "weather"

    async def generate_signals(self) -> StrategyResult:
        """Generate signals for all active weather markets."""
        all_signals: list[Signal] = []
        events_checked = 0
        errors: list[str] = []

        try:
            events = await self.gamma.discover_weather_events(
                cities=self.city_slugs,
                days_ahead=self.settings.max_forecast_days,
            )
        except Exception as e:
            logger.error("Failed to discover events", error=str(e))
            return StrategyResult(signals=[], events_checked=0, errors=[str(e)])

        for event in events:
            events_checked += 1

            city_config = CITIES.get(event.city)
            if not city_config:
                errors.append(f"Unknown city: {event.city}")
                continue

            days_out = (event.target_date - date.today()).days
            if days_out > self.settings.max_forecast_days:
                continue

            try:
                forecast = await self.open_meteo.get_ensemble_forecast(
                    lat=city_config.lat,
                    lon=city_config.lon,
                    target_date=event.target_date,
                    timezone=city_config.tz,
                    city=event.city,
                )
            except Exception as e:
                logger.warning(
                    "Failed to get forecast",
                    city=event.city,
                    date=str(event.target_date),
                    error=str(e),
                )
                errors.append(f"Forecast error for {event.city}: {e}")
                continue

            signals = calculate_signals(
                ensemble=forecast,
                event=event,
                bankroll=self.settings.bankroll_usdc,
                kelly_fraction=self.settings.kelly_fraction,
                max_position=self.settings.max_position_usd,
                edge_threshold=self.settings.edge_threshold_pct / 100,
            )

            for signal in signals:
                logger.info(
                    "Signal found",
                    city=signal.city,
                    date=str(signal.target_date),
                    bucket=signal.bucket_question[:50],
                    edge_pct=f"{signal.edge_pct:.1f}%",
                    position=f"${signal.position_size_usd:.2f}",
                )

            all_signals.extend(signals)

        all_signals.sort(key=lambda s: s.edge, reverse=True)

        return StrategyResult(
            signals=all_signals,
            events_checked=events_checked,
            errors=errors,
        )
```

**Step 3: Run tests**

Run: `pytest tests/ -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/strategy/base.py src/strategy/weather.py
git commit -m "refactor: make WeatherStrategy async-only"
```

---

### Task 1.4: Update Main Entry Point to Async

**Files:**
- Modify: `src/main.py`

**Step 1: Refactor main.py**

```python
# src/main.py
"""Main entry point for the prediction market bot."""

import argparse
import asyncio
import os

import structlog

from .config import get_settings, DEFAULT_CITIES
from .strategy.weather import WeatherStrategy
from .trading.executor import TradeExecutor


structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def run_once(cities: list[str] | None = None) -> list:
    """Run a single trading cycle."""
    settings = get_settings()
    city_list = cities or DEFAULT_CITIES

    logger.info(
        "Starting trading cycle",
        mode=settings.trading_mode,
        cities=city_list,
        bankroll=f"${settings.bankroll_usdc:.2f}",
        edge_threshold=f"{settings.edge_threshold_pct:.1f}%",
    )

    strategy = WeatherStrategy(settings, cities=city_list)
    executor = TradeExecutor(settings)

    result = await strategy.generate_signals()

    logger.info(
        "Strategy complete",
        events_checked=result.events_checked,
        signals_found=len(result.signals),
        errors=len(result.errors),
    )

    if result.errors:
        for error in result.errors:
            logger.warning("Strategy error", error=error)

    trades_executed = 0
    for signal in result.signals:
        exec_result = executor.execute(signal)
        if exec_result.success:
            trades_executed += 1

    logger.info(
        "Cycle complete",
        signals=len(result.signals),
        trades_executed=trades_executed,
    )

    return result.signals


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(description="Polymarket Weather Prediction Bot")

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single trading cycle and exit",
    )
    parser.add_argument(
        "--cities",
        type=str,
        help="Comma-separated list of cities (e.g., nyc,chicago,miami)",
    )
    parser.add_argument(
        "--show-signals",
        action="store_true",
        help="Show detailed signal information",
    )

    args = parser.parse_args()

    cities = None
    if args.cities:
        cities = [c.strip() for c in args.cities.split(",")]

    os.makedirs("data", exist_ok=True)

    signals = asyncio.run(run_once(cities=cities))

    if args.show_signals and signals:
        print("\n" + "=" * 60)
        print("SIGNALS FOUND")
        print("=" * 60)
        for s in signals:
            print(f"\n{s.city.upper()} - {s.target_date}")
            print(f"  {s.bucket_question}")
            print(f"  Model: {s.model_probability*100:.1f}% | Market: {s.market_price*100:.1f}%")
            print(f"  Edge: {s.edge_pct:.1f}% | Position: ${s.position_size_usd:.2f}")
            print(f"  EV: ${s.expected_value:.2f}")


if __name__ == "__main__":
    main()
```

**Step 2: Test manually**

Run: `python -m src.main --once --cities nyc --show-signals`
Expected: Should run and show any signals found

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "refactor: make main entry point async"
```

---

## Phase 2: Data Model Updates

### Task 2.1: Add Signal Table

**Files:**
- Modify: `src/data/models.py`
- Create: `tests/test_models.py`

**Step 1: Write test**

```python
# tests/test_models.py
import pytest
from datetime import date, datetime

from src.data.models import Signal, Trade, Position, init_db, get_session


@pytest.fixture
def db_session(tmp_path):
    db_path = str(tmp_path / "test.db")
    engine = init_db(db_path)
    session = get_session(engine)
    yield session
    session.close()


def test_create_signal(db_session):
    signal = Signal(
        strategy="weather",
        market_id="123",
        token_id="abc",
        model_probability=0.75,
        market_price=0.60,
        edge=0.15,
        confidence=0.9,
        decision="trade",
        created_at=datetime.utcnow(),
    )
    db_session.add(signal)
    db_session.commit()

    assert signal.id is not None


def test_create_signal_with_skip_reason(db_session):
    signal = Signal(
        strategy="weather",
        market_id="123",
        token_id="abc",
        model_probability=0.65,
        market_price=0.60,
        edge=0.05,
        decision="skip",
        skip_reason="below_threshold",
        created_at=datetime.utcnow(),
    )
    db_session.add(signal)
    db_session.commit()

    assert signal.skip_reason == "below_threshold"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL (Signal class doesn't exist)

**Step 3: Add Signal model**

```python
# Add to src/data/models.py after existing imports

class Signal(Base):
    """Every signal generated, whether traded or not."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    strategy = Column(String(50), nullable=False, index=True)
    market_id = Column(String(100), nullable=False)
    token_id = Column(String(100), nullable=False)

    model_probability = Column(Float, nullable=False)
    market_price = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    confidence = Column(Float)

    decision = Column(String(20), nullable=False)  # 'trade', 'skip'
    skip_reason = Column(String(100))

    trade_id = Column(Integer, ForeignKey('trades.id'), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    metadata_json = Column(Text)
```

**Step 4: Run tests**

Run: `pytest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/data/models.py tests/test_models.py
git commit -m "feat: add Signal model for tracking all generated signals"
```

---

### Task 2.2: Add Position Table

**Files:**
- Modify: `src/data/models.py`
- Modify: `tests/test_models.py`

**Step 1: Add test**

```python
# Add to tests/test_models.py

def test_create_position(db_session):
    position = Position(
        strategy="weather",
        market_id="123",
        token_id="abc",
        shares=100.0,
        cost_basis=0.15,
        total_cost=15.0,
        status="open",
        opened_at=datetime.utcnow(),
    )
    db_session.add(position)
    db_session.commit()

    assert position.id is not None
    assert position.status == "open"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_create_position -v`
Expected: FAIL

**Step 3: Add Position model**

```python
# Add to src/data/models.py

class Position(Base):
    """Open position in a market."""

    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    strategy = Column(String(50), nullable=False, index=True)
    market_id = Column(String(100), nullable=False)
    token_id = Column(String(100), nullable=False)

    shares = Column(Float, nullable=False)
    cost_basis = Column(Float, nullable=False)
    total_cost = Column(Float, nullable=False)

    status = Column(String(20), nullable=False)  # 'open', 'closed'
    opened_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime)
    realized_pnl = Column(Float)
```

**Step 4: Run tests**

Run: `pytest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/data/models.py tests/test_models.py
git commit -m "feat: add Position model for tracking open positions"
```

---

### Task 2.3: Add Strategy Column to Trade

**Files:**
- Modify: `src/data/models.py`
- Modify: `tests/test_models.py`

**Step 1: Add test**

```python
# Add to tests/test_models.py

def test_trade_has_strategy_field(db_session):
    trade = Trade(
        mode="paper",
        strategy="weather",
        city="nyc",
        target_date=date.today(),
        bucket_question="Will temp be 46-47?",
        token_id="abc",
        side="buy",
        model_prob=0.75,
        market_price=0.60,
        edge=0.15,
        position_usd=5.0,
        status="filled",
        created_at=datetime.utcnow(),
    )
    db_session.add(trade)
    db_session.commit()

    assert trade.strategy == "weather"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py::test_trade_has_strategy_field -v`
Expected: FAIL

**Step 3: Add strategy column to Trade**

```python
# Modify Trade class in src/data/models.py
# Add these columns:

    strategy = Column(String(50), nullable=False, index=True, default="weather")
    position_id = Column(Integer, ForeignKey('positions.id'), nullable=True)
    signal_id = Column(Integer, ForeignKey('signals.id'), nullable=True)
    actual_temp = Column(Float)
    resolution_source = Column(String(50))
```

**Step 4: Run tests**

Run: `pytest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/data/models.py tests/test_models.py
git commit -m "feat: add strategy column and FKs to Trade model"
```

---

### Task 2.4: Add Seoul to Cities Config

**Files:**
- Modify: `src/config.py`
- Create: `tests/test_config.py`

**Step 1: Write test**

```python
# tests/test_config.py
from src.config import CITIES


def test_seoul_in_cities():
    assert "seoul" in CITIES
    seoul = CITIES["seoul"]
    assert seoul.name == "Seoul"
    assert seoul.tz == "Asia/Seoul"
    assert seoul.lat == 37.5665
    assert seoul.lon == 126.9780


def test_all_cities_have_required_fields():
    for slug, city in CITIES.items():
        assert city.name, f"{slug} missing name"
        assert city.lat, f"{slug} missing lat"
        assert city.lon, f"{slug} missing lon"
        assert city.tz, f"{slug} missing tz"
        assert city.station, f"{slug} missing station"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (seoul not in CITIES)

**Step 3: Add Seoul**

```python
# Add to CITIES dict in src/config.py

    "seoul": CityConfig(
        name="Seoul",
        slug="seoul",
        lat=37.5665,
        lon=126.9780,
        tz="Asia/Seoul",
        station="RKSS",
    ),
```

**Step 4: Run tests**

Run: `pytest tests/test_config.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add Seoul to supported cities"
```

---

## Phase 3: Trade Resolution

### Task 3.1: Create Resolution Service

**Files:**
- Create: `src/services/__init__.py`
- Create: `src/services/resolver.py`
- Create: `tests/test_resolver.py`

**Step 1: Write test**

```python
# tests/test_resolver.py
import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from src.services.resolver import ResolutionService


@pytest.mark.asyncio
async def test_check_resolution_returns_winning_bucket():
    service = ResolutionService()

    # Mock the Gamma API response
    mock_event = {
        "closed": True,
        "markets": [
            {
                "question": "between 46-47°F",
                "outcomePrices": '["1", "0"]',  # YES won
                "clobTokenIds": '["token1", "token2"]',
                "closed": True,
            },
            {
                "question": "between 44-45°F",
                "outcomePrices": '["0", "1"]',  # NO won
                "clobTokenIds": '["token3", "token4"]',
                "closed": True,
            },
        ],
    }

    with patch.object(service, '_fetch_event', return_value=mock_event):
        result = await service.check_resolution("nyc", date(2026, 2, 17))

    assert result is not None
    assert result["winning_bucket"] == "between 46-47°F"
    assert result["winning_token"] == "token1"


@pytest.mark.asyncio
async def test_check_resolution_returns_none_if_not_resolved():
    service = ResolutionService()

    mock_event = {
        "closed": False,
        "markets": [],
    }

    with patch.object(service, '_fetch_event', return_value=mock_event):
        result = await service.check_resolution("nyc", date(2026, 2, 20))

    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_resolver.py -v`
Expected: FAIL

**Step 3: Create resolver service**

```python
# src/services/__init__.py
"""Services module."""

# src/services/resolver.py
"""Trade resolution service using Gamma API."""

import json
from datetime import date
import httpx


class ResolutionService:
    """Service to check trade resolution status from Polymarket."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.base_url = "https://gamma-api.polymarket.com"

    async def _fetch_event(self, city: str, target_date: date) -> dict | None:
        """Fetch event data from Gamma API."""
        month = target_date.strftime("%B").lower()
        day = target_date.day
        year = target_date.year
        slug = f"highest-temperature-in-{city}-on-{month}-{day}-{year}"

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
                # YES won
                return {
                    "winning_bucket": market.get("question", ""),
                    "winning_token": tokens[0] if tokens else None,
                    "resolution": "yes",
                }

        return None

    async def resolve_trade(
        self, trade, db_session
    ) -> bool:
        """
        Resolve a trade by checking Polymarket outcome.

        Returns:
            True if resolved, False if not yet resolved
        """
        from datetime import datetime

        result = await self.check_resolution(trade.city, trade.target_date)

        if not result:
            return False

        # Check if our trade won
        won = trade.token_id == result["winning_token"]

        # Calculate P&L
        if won:
            pnl = trade.position_usd * (1 - trade.fill_price) / trade.fill_price
        else:
            pnl = -trade.position_usd

        # Update trade
        trade.status = "resolved"
        trade.pnl = pnl
        trade.resolution_source = "gamma_api"
        trade.resolved_at = datetime.utcnow()

        db_session.commit()

        return True
```

**Step 4: Run tests**

Run: `pytest tests/test_resolver.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/services/__init__.py src/services/resolver.py tests/test_resolver.py
git commit -m "feat: add ResolutionService for checking trade outcomes"
```

---

## Phase 4: Dashboard (Abbreviated)

Due to length, dashboard tasks are outlined rather than fully specified:

### Task 4.1: Create FastAPI App Structure

**Files:**
- Create: `src/dashboard/__init__.py`
- Create: `src/dashboard/app.py`
- Create: `src/dashboard/routes.py`
- Create: `src/dashboard/templates/base.html`

### Task 4.2: Add Portfolio Endpoint

**Endpoint:** `GET /api/portfolio`
**Returns:** Free cash, positions value, total P&L

### Task 4.3: Add Positions Endpoint

**Endpoint:** `GET /api/positions`
**Returns:** List of open positions with current prices

### Task 4.4: Add Trades Endpoint

**Endpoint:** `GET /api/trades?strategy=weather`
**Returns:** Filterable trade history

### Task 4.5: Add Signals Endpoint

**Endpoint:** `GET /api/signals`
**Returns:** All signals with decision and skip_reason

### Task 4.6: Add Analytics Endpoint

**Endpoint:** `GET /api/analytics?strategy=weather`
**Returns:** P&L over time, win rate by strategy

### Task 4.7: Create HTMX Templates

**Files:**
- `templates/home.html`
- `templates/positions.html`
- `templates/trades.html`
- `templates/analytics.html`

### Task 4.8: Add 5-Second Polling

Use `hx-trigger="every 5s"` on position and signal elements.

---

## Phase 5: Backtesting (Abbreviated)

> **Note:** This backtesting implementation is specific to **weather markets** using NOAA GEFS ensemble data. Esports backtesting will require a different approach (GRID historical data, different model). The backtest engine interface should be generic, but the data fetching is weather-specific.

### Task 5.1: Add GRIB Dependencies

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
backtest = ["cfgrib>=0.9.10", "xarray>=2024.1.0"]
```

### Task 5.2: Create GEFS Client

**Files:**
- Create: `src/clients/gefs.py`
- Create: `tests/test_gefs.py`

Download ensemble data from S3 using byte-range requests.

### Task 5.3: Create Backtest Engine

**Files:**
- Create: `src/backtest/__init__.py`
- Create: `src/backtest/engine.py`
- Create: `tests/test_backtest.py`

### Task 5.4: Add Backtest CLI Command

**Command:** `python -m src.cli backtest --start 2025-01-01 --end 2026-02-01`

---

## Phase 6: CLI Improvements

### Task 6.1: Create CLI Module with Typer

**Files:**
- Create: `src/cli.py`

```python
# src/cli.py
import asyncio
import typer
from datetime import date

app = typer.Typer()


@app.command()
def run(
    cities: str = typer.Option(None, help="Comma-separated cities"),
    all_cities: bool = typer.Option(False, help="Run all configured cities"),
):
    """Run a trading cycle."""
    from .main import run_once
    from .config import CITIES

    city_list = list(CITIES.keys()) if all_cities else cities.split(",") if cities else None
    asyncio.run(run_once(city_list))


@app.command()
def resolve():
    """Check and resolve pending trades."""
    # Implementation
    pass


@app.command()
def dashboard(port: int = 8000):
    """Start the dashboard server."""
    import uvicorn
    uvicorn.run("src.dashboard.app:app", host="0.0.0.0", port=port, reload=True)


@app.command()
def scan_cities():
    """Scan for new weather markets on Polymarket."""
    # Implementation
    pass


if __name__ == "__main__":
    app()
```

---

## Verification Checklist

After completing all tasks:

1. [ ] `pytest tests/ -v` — All tests pass
2. [ ] `python -m src.cli run --cities nyc` — Trading cycle runs
3. [ ] `python -m src.cli resolve` — Resolution checks work
4. [ ] `python -m src.cli dashboard` — Dashboard starts on port 8000
5. [ ] Dashboard shows positions with 5s refresh
6. [ ] Dashboard filters by strategy

---

## Commit Summary

After all tasks, you should have approximately these commits:

1. `refactor: make OpenMeteoClient async-only`
2. `refactor: make GammaClient async-only`
3. `refactor: make WeatherStrategy async-only`
4. `refactor: make main entry point async`
5. `feat: add Signal model`
6. `feat: add Position model`
7. `feat: add strategy column to Trade`
8. `feat: add Seoul to cities`
9. `feat: add ResolutionService`
10. `feat: add dashboard FastAPI app`
11. `feat: add portfolio endpoint`
12. `feat: add positions endpoint`
13. `feat: add trades endpoint`
14. `feat: add HTMX templates`
15. `feat: add CLI with typer`
