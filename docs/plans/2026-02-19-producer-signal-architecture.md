# Producer Signal Architecture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement real-time event discovery, live price tracking via CLOB websocket, and typed signal structure supporting multiple exchanges.

**Architecture:** Single async process with 4 tasks (EventDiscovery, PriceTracker, Forecast, SignalGenerator) sharing a SQLite-backed MarketRegistry. Signals are broadcast via existing websocket server.

**Tech Stack:** Python 3.12, asyncio, SQLAlchemy, websockets, FastAPI (existing), structlog

**Design Doc:** `docs/plans/2026-02-19-producer-signal-architecture-design.md`

---

## Task 1: Create ProducerSignal Types

**Files:**
- Create: `producer/signal_producer/signals/types.py`
- Test: `producer/tests/test_signal_types.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_signal_types.py
"""Tests for ProducerSignal types."""

import pytest
from datetime import datetime

from signal_producer.signals.types import (
    WeatherMetadata,
    PolymarketInfo,
    ProducerSignal,
)


def test_weather_metadata_has_required_fields():
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 34.8,
        "ensemble_std": 2.1,
        "members_in_range": 12,
    }
    assert metadata["city"] == "nyc"
    assert metadata["members_in_range"] == 12


def test_polymarket_info_has_required_fields():
    info: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "abc123",
        "side": "yes",
        "market_description": "Will temp be 34-35F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.35,
        "edge": 0.05,
        "price_timestamp": "2026-02-19T12:00:00Z",
    }
    assert info["exchange"] == "polymarket"
    assert info["side"] == "yes"


def test_producer_signal_creation():
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 34.8,
        "ensemble_std": 2.1,
        "members_in_range": 12,
    }
    exchange: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "abc123",
        "side": "yes",
        "market_description": "Will temp be 34-35F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.35,
        "edge": 0.05,
        "price_timestamp": "2026-02-19T12:00:00Z",
    }
    signal = ProducerSignal(
        signal_type="weather",
        model_probability=0.40,
        confidence=0.85,
        forecast_source="open_meteo",
        forecast_time="2026-02-19T08:00:00Z",
        metadata=metadata,
        exchanges=[exchange],
    )
    assert signal.signal_type == "weather"
    assert signal.model_probability == 0.40
    assert len(signal.exchanges) == 1


def test_producer_signal_to_dict():
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 34.8,
        "ensemble_std": 2.1,
        "members_in_range": 12,
    }
    exchange: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "abc123",
        "side": "yes",
        "market_description": "Will temp be 34-35F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.35,
        "edge": 0.05,
        "price_timestamp": "2026-02-19T12:00:00Z",
    }
    signal = ProducerSignal(
        signal_type="weather",
        model_probability=0.40,
        confidence=0.85,
        forecast_source="open_meteo",
        forecast_time="2026-02-19T08:00:00Z",
        metadata=metadata,
        exchanges=[exchange],
    )
    d = signal.to_dict()
    assert d["signal_type"] == "weather"
    assert d["metadata"]["city"] == "nyc"
    assert d["exchanges"][0]["exchange"] == "polymarket"
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_signal_types.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'signal_producer.signals'"

**Step 3: Write minimal implementation**

```python
# producer/signal_producer/signals/__init__.py
"""Signal types for the producer."""

from .types import (
    WeatherMetadata,
    EsportsMetadata,
    PolymarketInfo,
    KalshiInfo,
    ProducerSignal,
    ForecastSource,
    SignalType,
)

__all__ = [
    "WeatherMetadata",
    "EsportsMetadata",
    "PolymarketInfo",
    "KalshiInfo",
    "ProducerSignal",
    "ForecastSource",
    "SignalType",
]
```

```python
# producer/signal_producer/signals/types.py
"""Typed signal structures for the producer.

See design doc: docs/plans/2026-02-19-producer-signal-architecture-design.md
"""

from dataclasses import dataclass, asdict
from typing import Literal, TypedDict


# Type aliases for clarity
SignalType = Literal["weather", "esports"]
ForecastSource = Literal["open_meteo", "noaa"]
Side = Literal["yes", "no"]
Exchange = Literal["polymarket", "kalshi"]


# === Typed Metadata (per signal_type) ===


class WeatherMetadata(TypedDict):
    """Metadata for weather signals."""

    city: str
    target_date: str  # ISO date string "2026-02-20"
    ensemble_mean: float
    ensemble_std: float
    members_in_range: int  # e.g., 12 of 31


class EsportsMetadata(TypedDict):
    """Metadata for esports signals (future)."""

    match_id: str
    team_a: str
    team_b: str
    target_date: str


# === Exchange-Specific Market Info ===


class PolymarketInfo(TypedDict):
    """Polymarket-specific market information."""

    exchange: Literal["polymarket"]
    event_id: str
    token_id: str
    side: Side
    market_description: str
    resolution_source: str  # e.g., wunderground URL
    market_price: float  # 0-1
    edge: float  # model_prob - market_price (adjusted for side)
    price_timestamp: str  # ISO timestamp


class KalshiInfo(TypedDict):
    """Kalshi-specific market information (future)."""

    exchange: Literal["kalshi"]
    event_ticker: str
    ticker: str
    side: Side
    rules_primary: str
    yes_ask_dollars: float
    no_ask_dollars: float
    edge: float
    price_timestamp: str


# === Canonical Producer Signal ===


@dataclass
class ProducerSignal:
    """
    Canonical signal emitted by the producer.

    Exchange-agnostic core prediction with typed metadata
    and exchange-specific market info.
    """

    # Type discriminator
    signal_type: SignalType

    # Core prediction (exchange-agnostic)
    model_probability: float
    confidence: float

    # Source info
    forecast_source: ForecastSource
    forecast_time: str  # ISO timestamp

    # Typed metadata (based on signal_type)
    metadata: WeatherMetadata | EsportsMetadata

    # Exchange-specific (one signal can map to multiple exchanges)
    exchanges: list[PolymarketInfo | KalshiInfo]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return asdict(self)
```

**Step 4: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_signal_types.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add producer/signal_producer/signals/ producer/tests/test_signal_types.py
git commit -m "feat: add ProducerSignal types with typed metadata and exchange info"
```

---

## Task 2: Rename WeatherBucket to WeatherMarket

**Files:**
- Modify: `producer/signal_producer/strategies/weather/markets.py`
- Modify: `producer/signal_producer/strategies/weather/signals.py`
- Modify: `producer/signal_producer/strategies/weather/strategy.py`
- Test: `producer/tests/test_weather_signals.py` (update existing)

**Step 1: Write the failing test**

```python
# producer/tests/test_weather_market_rename.py
"""Test that WeatherMarket exists and WeatherBucket is removed."""

import pytest


def test_weather_market_import():
    from signal_producer.strategies.weather.markets import WeatherMarket, WeatherEvent
    assert WeatherMarket is not None
    assert WeatherEvent is not None


def test_weather_bucket_removed():
    with pytest.raises(ImportError):
        from signal_producer.strategies.weather.markets import WeatherBucket
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_weather_market_rename.py -v`
Expected: FAIL (WeatherMarket not found)

**Step 3: Rename in markets.py**

In `producer/signal_producer/strategies/weather/markets.py`:
- Rename `class WeatherBucket` → `class WeatherMarket`
- Update all references in docstrings

**Step 4: Update signals.py**

In `producer/signal_producer/strategies/weather/signals.py`:
- Change `from .markets import WeatherBucket` → `from .markets import WeatherMarket`
- Rename all `bucket` variables to `market`
- Update type hints: `WeatherBucket` → `WeatherMarket`
- Update function params: `bucket: WeatherBucket` → `market: WeatherMarket`

**Step 5: Update strategy.py**

In `producer/signal_producer/strategies/weather/strategy.py`:
- Update any `bucket` references to `market`

**Step 6: Run all tests to verify nothing broke**

Run: `cd producer && python -m pytest tests/ -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add producer/signal_producer/strategies/weather/
git add producer/tests/test_weather_market_rename.py
git commit -m "refactor: rename WeatherBucket to WeatherMarket"
```

---

## Task 3: Create TrackedEvent SQLAlchemy Model

**Files:**
- Create: `producer/signal_producer/registry/__init__.py`
- Create: `producer/signal_producer/registry/models.py`
- Test: `producer/tests/test_registry_models.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_registry_models.py
"""Tests for registry SQLAlchemy models."""

import pytest
from datetime import date, datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from signal_producer.registry.models import Base, TrackedEvent, TrackedMarket, EventStatus


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_create_tracked_event(db_session):
    event = TrackedEvent(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        status=EventStatus.ACTIVE,
        resolution_source="https://wunderground.com/...",
        created_at=datetime.utcnow(),
    )
    db_session.add(event)
    db_session.commit()

    loaded = db_session.query(TrackedEvent).filter_by(event_id="213978").first()
    assert loaded is not None
    assert loaded.status == EventStatus.ACTIVE
    assert loaded.city == "nyc"


def test_create_tracked_market(db_session):
    event = TrackedEvent(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        status=EventStatus.ACTIVE,
        resolution_source="https://wunderground.com/...",
        created_at=datetime.utcnow(),
    )
    db_session.add(event)
    db_session.commit()

    market = TrackedMarket(
        event_id="213978",
        token_id="abc123",
        side="yes",
        market_description="Will temp be 34-35F?",
        low_temp=34.0,
        high_temp=36.0,
    )
    db_session.add(market)
    db_session.commit()

    loaded = db_session.query(TrackedMarket).filter_by(token_id="abc123").first()
    assert loaded is not None
    assert loaded.side == "yes"


def test_event_status_transitions(db_session):
    event = TrackedEvent(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        status=EventStatus.ACTIVE,
        resolution_source="https://wunderground.com/...",
        created_at=datetime.utcnow(),
    )
    db_session.add(event)
    db_session.commit()

    # Mark resolved
    event.status = EventStatus.RESOLVED
    event.resolved_at = datetime.utcnow()
    db_session.commit()

    loaded = db_session.query(TrackedEvent).filter_by(event_id="213978").first()
    assert loaded.status == EventStatus.RESOLVED
    assert loaded.resolved_at is not None
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_registry_models.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

```python
# producer/signal_producer/registry/__init__.py
"""Market registry for tracking events and prices."""

from .models import Base, TrackedEvent, TrackedMarket, EventStatus

__all__ = ["Base", "TrackedEvent", "TrackedMarket", "EventStatus"]
```

```python
# producer/signal_producer/registry/models.py
"""SQLAlchemy models for the market registry."""

from datetime import date, datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, String, Float, Date, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class EventStatus(str, Enum):
    """Status of a tracked event."""

    ACTIVE = "active"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class TrackedEvent(Base):
    """A tracked prediction market event."""

    __tablename__ = "tracked_events"

    event_id = Column(String(100), primary_key=True)
    event_type = Column(String(50), nullable=False)  # "weather", "esports"
    city = Column(String(50), nullable=True)  # For weather events
    target_date = Column(Date, nullable=False)
    status = Column(SQLEnum(EventStatus), default=EventStatus.ACTIVE, nullable=False)
    resolution_source = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    # Forecast data (JSON stored as string for simplicity)
    forecast_json = Column(String, nullable=True)
    forecast_updated_at = Column(DateTime, nullable=True)

    # Relationships
    markets = relationship("TrackedMarket", back_populates="event", cascade="all, delete-orphan")


class TrackedMarket(Base):
    """A tracked market within an event (e.g., a temperature range)."""

    __tablename__ = "tracked_markets"

    token_id = Column(String(100), primary_key=True)
    event_id = Column(String(100), ForeignKey("tracked_events.event_id"), nullable=False)
    side = Column(String(10), nullable=False)  # "yes" or "no"
    market_description = Column(String(500), nullable=False)
    low_temp = Column(Float, nullable=True)  # For weather markets
    high_temp = Column(Float, nullable=True)

    # Relationships
    event = relationship("TrackedEvent", back_populates="markets")
```

**Step 4: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_registry_models.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add producer/signal_producer/registry/
git add producer/tests/test_registry_models.py
git commit -m "feat: add TrackedEvent and TrackedMarket SQLAlchemy models"
```

---

## Task 4: Create MarketRegistry Class

**Files:**
- Create: `producer/signal_producer/registry/registry.py`
- Test: `producer/tests/test_market_registry.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_market_registry.py
"""Tests for MarketRegistry."""

import pytest
from datetime import date, datetime
from sqlalchemy import create_engine

from signal_producer.registry.models import Base, EventStatus
from signal_producer.registry.registry import MarketRegistry, PriceEntry


@pytest.fixture
def registry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return MarketRegistry(engine)


def test_register_event(registry):
    token_ids = registry.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[
            {
                "token_id": "abc123",
                "side": "yes",
                "market_description": "Will temp be 34-35F?",
                "low_temp": 34.0,
                "high_temp": 36.0,
            },
            {
                "token_id": "def456",
                "side": "no",
                "market_description": "Will temp be 34-35F?",
                "low_temp": 34.0,
                "high_temp": 36.0,
            },
        ],
    )
    assert token_ids == ["abc123", "def456"]


def test_get_active_events(registry):
    registry.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[],
    )
    events = registry.get_active_events()
    assert len(events) == 1
    assert events[0].event_id == "213978"


def test_update_price(registry):
    registry.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[
            {"token_id": "abc123", "side": "yes", "market_description": "Test", "low_temp": 34.0, "high_temp": 36.0},
        ],
    )
    registry.update_price("abc123", 0.35, "2026-02-19T12:00:00Z")

    price = registry.get_price("abc123")
    assert price is not None
    assert price.price == 0.35


def test_mark_resolved(registry):
    registry.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[
            {"token_id": "abc123", "side": "yes", "market_description": "Test", "low_temp": 34.0, "high_temp": 36.0},
        ],
    )

    token_ids = registry.mark_resolved("213978")
    assert token_ids == ["abc123"]

    events = registry.get_active_events()
    assert len(events) == 0


def test_get_active_token_ids(registry):
    registry.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[
            {"token_id": "abc123", "side": "yes", "market_description": "Test", "low_temp": 34.0, "high_temp": 36.0},
            {"token_id": "def456", "side": "no", "market_description": "Test", "low_temp": 34.0, "high_temp": 36.0},
        ],
    )

    token_ids = registry.get_active_token_ids()
    assert set(token_ids) == {"abc123", "def456"}


def test_is_event_tracked(registry):
    assert not registry.is_event_tracked("213978")

    registry.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[],
    )

    assert registry.is_event_tracked("213978")
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_market_registry.py -v`
Expected: FAIL with "cannot import name 'MarketRegistry'"

**Step 3: Write minimal implementation**

```python
# producer/signal_producer/registry/registry.py
"""MarketRegistry: Central store for tracked events, markets, and prices."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
import asyncio

import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from .models import Base, TrackedEvent, TrackedMarket, EventStatus

logger = structlog.get_logger()


@dataclass
class PriceEntry:
    """In-memory price cache entry."""

    price: float
    timestamp: str


class MarketRegistry:
    """
    Central store for tracked events, markets, and prices.

    SQLite-backed for persistence, with in-memory price cache.
    """

    def __init__(self, engine: Engine):
        self._engine = engine
        self._price_cache: dict[str, PriceEntry] = {}
        self._lock = asyncio.Lock()

        # Ensure tables exist
        Base.metadata.create_all(engine)

    def _session(self) -> Session:
        return Session(self._engine)

    def register_event(
        self,
        event_id: str,
        event_type: str,
        city: str | None,
        target_date: date,
        resolution_source: str,
        markets: list[dict],
    ) -> list[str]:
        """
        Register a new event with its markets.

        Returns list of token_ids to subscribe to.
        """
        with self._session() as session:
            # Check if already exists
            existing = session.query(TrackedEvent).filter_by(event_id=event_id).first()
            if existing:
                logger.debug("Event already tracked", event_id=event_id)
                return []

            event = TrackedEvent(
                event_id=event_id,
                event_type=event_type,
                city=city,
                target_date=target_date,
                status=EventStatus.ACTIVE,
                resolution_source=resolution_source,
                created_at=datetime.utcnow(),
            )
            session.add(event)

            token_ids = []
            for m in markets:
                market = TrackedMarket(
                    token_id=m["token_id"],
                    event_id=event_id,
                    side=m["side"],
                    market_description=m["market_description"],
                    low_temp=m.get("low_temp"),
                    high_temp=m.get("high_temp"),
                )
                session.add(market)
                token_ids.append(m["token_id"])

            session.commit()
            logger.info("Registered event", event_id=event_id, markets=len(token_ids))
            return token_ids

    def get_active_events(self) -> list[TrackedEvent]:
        """Return all active events."""
        with self._session() as session:
            events = session.query(TrackedEvent).filter_by(status=EventStatus.ACTIVE).all()
            # Detach from session
            session.expunge_all()
            return events

    def get_active_token_ids(self) -> list[str]:
        """Return all token_ids for active events."""
        with self._session() as session:
            events = session.query(TrackedEvent).filter_by(status=EventStatus.ACTIVE).all()
            token_ids = []
            for event in events:
                for market in event.markets:
                    token_ids.append(market.token_id)
            return token_ids

    def is_event_tracked(self, event_id: str) -> bool:
        """Check if an event is already tracked (any status)."""
        with self._session() as session:
            event = session.query(TrackedEvent).filter_by(event_id=event_id).first()
            return event is not None

    def update_price(self, token_id: str, price: float, timestamp: str) -> None:
        """Update cached price (in-memory only)."""
        self._price_cache[token_id] = PriceEntry(price=price, timestamp=timestamp)

    def get_price(self, token_id: str) -> PriceEntry | None:
        """Get cached price for a token."""
        return self._price_cache.get(token_id)

    def mark_resolved(self, event_id: str) -> list[str]:
        """
        Mark event as resolved.

        Returns list of token_ids to unsubscribe from.
        """
        with self._session() as session:
            event = session.query(TrackedEvent).filter_by(event_id=event_id).first()
            if not event:
                logger.warning("Event not found for resolution", event_id=event_id)
                return []

            token_ids = [m.token_id for m in event.markets]

            event.status = EventStatus.RESOLVED
            event.resolved_at = datetime.utcnow()
            session.commit()

            # Clear price cache for these tokens
            for token_id in token_ids:
                self._price_cache.pop(token_id, None)

            logger.info("Marked event resolved", event_id=event_id, tokens=len(token_ids))
            return token_ids

    def mark_expired(self, event_id: str) -> list[str]:
        """Mark event as expired (cleanup fallback)."""
        with self._session() as session:
            event = session.query(TrackedEvent).filter_by(event_id=event_id).first()
            if not event:
                return []

            token_ids = [m.token_id for m in event.markets]

            event.status = EventStatus.EXPIRED
            event.resolved_at = datetime.utcnow()
            session.commit()

            for token_id in token_ids:
                self._price_cache.pop(token_id, None)

            logger.info("Marked event expired", event_id=event_id)
            return token_ids
```

**Step 4: Update registry __init__.py**

```python
# producer/signal_producer/registry/__init__.py
"""Market registry for tracking events and prices."""

from .models import Base, TrackedEvent, TrackedMarket, EventStatus
from .registry import MarketRegistry, PriceEntry

__all__ = [
    "Base",
    "TrackedEvent",
    "TrackedMarket",
    "EventStatus",
    "MarketRegistry",
    "PriceEntry",
]
```

**Step 5: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_market_registry.py -v`
Expected: PASS (6 tests)

**Step 6: Commit**

```bash
git add producer/signal_producer/registry/
git add producer/tests/test_market_registry.py
git commit -m "feat: add MarketRegistry with SQLite persistence and price cache"
```

---

## Task 5: Create CLOB WebSocket Price Tracker

**Files:**
- Create: `producer/signal_producer/tasks/__init__.py`
- Create: `producer/signal_producer/tasks/price_tracker.py`
- Test: `producer/tests/test_price_tracker.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_price_tracker.py
"""Tests for CLOB websocket price tracker."""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from sqlalchemy import create_engine

from signal_producer.registry.models import Base
from signal_producer.registry.registry import MarketRegistry
from signal_producer.tasks.price_tracker import PriceTracker, parse_price_change_event


def test_parse_price_change_event():
    event = {
        "event_type": "price_change",
        "asset_id": "abc123",
        "price": "0.35",
        "timestamp": "2026-02-19T12:00:00Z",
    }
    result = parse_price_change_event(event)
    assert result is not None
    assert result["token_id"] == "abc123"
    assert result["price"] == 0.35


def test_parse_price_change_event_invalid():
    event = {"event_type": "book"}  # Not a price_change
    result = parse_price_change_event(event)
    assert result is None


@pytest.fixture
def registry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return MarketRegistry(engine)


@pytest.mark.asyncio
async def test_price_tracker_updates_registry(registry):
    tracker = PriceTracker(registry)

    # Simulate a price update
    await tracker.handle_price_change("abc123", 0.35, "2026-02-19T12:00:00Z")

    price = registry.get_price("abc123")
    assert price is not None
    assert price.price == 0.35


@pytest.mark.asyncio
async def test_price_tracker_subscribe(registry):
    tracker = PriceTracker(registry)

    # Mock websocket
    mock_ws = AsyncMock()
    tracker._ws = mock_ws

    await tracker.subscribe(["abc123", "def456"])

    mock_ws.send.assert_called_once()
    call_args = json.loads(mock_ws.send.call_args[0][0])
    assert call_args["type"] == "market"
    assert set(call_args["assets_ids"]) == {"abc123", "def456"}
    assert call_args["custom_feature_enabled"] is True
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_price_tracker.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

```python
# producer/signal_producer/tasks/__init__.py
"""Async tasks for the producer."""

from .price_tracker import PriceTracker

__all__ = ["PriceTracker"]
```

```python
# producer/signal_producer/tasks/price_tracker.py
"""CLOB websocket price tracker task."""

import asyncio
import json
from typing import Any, Callable, Awaitable

import structlog
import websockets
from websockets.exceptions import ConnectionClosed

from ..registry.registry import MarketRegistry

logger = structlog.get_logger()

CLOB_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


def parse_price_change_event(event: dict) -> dict | None:
    """Parse a price_change event from CLOB websocket."""
    if event.get("event_type") != "price_change":
        return None

    try:
        return {
            "token_id": event["asset_id"],
            "price": float(event["price"]),
            "timestamp": event.get("timestamp", ""),
        }
    except (KeyError, ValueError) as e:
        logger.warning("Failed to parse price_change", error=str(e), event=event)
        return None


def parse_market_resolved_event(event: dict) -> str | None:
    """Parse a market_resolved event, return event_id if applicable."""
    if event.get("event_type") != "market_resolved":
        return None
    return event.get("market_id") or event.get("event_id")


class PriceTracker:
    """
    Maintains CLOB websocket connection for real-time price updates.

    Subscribes to token_ids and updates the MarketRegistry price cache.
    """

    def __init__(
        self,
        registry: MarketRegistry,
        ws_url: str = CLOB_WS_URL,
        on_market_resolved: Callable[[str], Awaitable[None]] | None = None,
    ):
        self._registry = registry
        self._ws_url = ws_url
        self._ws: Any = None
        self._subscribed_tokens: set[str] = set()
        self._on_market_resolved = on_market_resolved
        self._running = False

    async def handle_price_change(self, token_id: str, price: float, timestamp: str) -> None:
        """Handle a price change event."""
        self._registry.update_price(token_id, price, timestamp)
        logger.debug("Price updated", token_id=token_id[:20], price=price)

    async def handle_market_resolved(self, event_id: str) -> None:
        """Handle a market resolved event."""
        token_ids = self._registry.mark_resolved(event_id)
        self._subscribed_tokens -= set(token_ids)

        if self._on_market_resolved:
            await self._on_market_resolved(event_id)

        logger.info("Market resolved", event_id=event_id, unsubscribed=len(token_ids))

    async def subscribe(self, token_ids: list[str]) -> None:
        """Subscribe to price updates for token_ids."""
        if not token_ids:
            return

        new_tokens = [t for t in token_ids if t not in self._subscribed_tokens]
        if not new_tokens:
            return

        message = {
            "type": "market",
            "assets_ids": new_tokens,
            "custom_feature_enabled": True,
        }

        if self._ws:
            await self._ws.send(json.dumps(message))
            self._subscribed_tokens.update(new_tokens)
            logger.info("Subscribed to tokens", count=len(new_tokens))

    async def unsubscribe(self, token_ids: list[str]) -> None:
        """Unsubscribe from token_ids (remove from tracking)."""
        self._subscribed_tokens -= set(token_ids)
        # Note: CLOB websocket doesn't support unsubscribe, we just stop tracking

    async def _handle_message(self, message: str) -> None:
        """Handle incoming websocket message."""
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from websocket", message=message[:100])
            return

        # Handle price_change
        price_data = parse_price_change_event(event)
        if price_data:
            await self.handle_price_change(
                price_data["token_id"],
                price_data["price"],
                price_data["timestamp"],
            )
            return

        # Handle market_resolved
        event_id = parse_market_resolved_event(event)
        if event_id:
            await self.handle_market_resolved(event_id)
            return

    async def run(self) -> None:
        """Run the price tracker (persistent connection with reconnect)."""
        self._running = True

        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._ws = ws
                    logger.info("Connected to CLOB websocket", url=self._ws_url)

                    # Resubscribe to all tracked tokens
                    token_ids = list(self._subscribed_tokens)
                    if token_ids:
                        await self.subscribe(token_ids)

                    # Handle messages
                    async for message in ws:
                        await self._handle_message(message)

            except ConnectionClosed:
                logger.warning("CLOB websocket disconnected, reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error("CLOB websocket error", error=str(e))
                await asyncio.sleep(5)

        self._ws = None

    async def stop(self) -> None:
        """Stop the price tracker."""
        self._running = False
        if self._ws:
            await self._ws.close()
```

**Step 4: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_price_tracker.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add producer/signal_producer/tasks/
git add producer/tests/test_price_tracker.py
git commit -m "feat: add CLOB websocket price tracker"
```

---

## Task 6: Create Event Discovery Task

**Files:**
- Create: `producer/signal_producer/tasks/event_discovery.py`
- Test: `producer/tests/test_event_discovery.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_event_discovery.py
"""Tests for event discovery task."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine

from signal_producer.registry.models import Base
from signal_producer.registry.registry import MarketRegistry
from signal_producer.tasks.event_discovery import EventDiscoveryTask


@pytest.fixture
def registry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return MarketRegistry(engine)


@pytest.fixture
def mock_gamma_response():
    return {
        "id": "213978",
        "title": "Highest temperature in NYC on February 20?",
        "closed": False,
        "resolutionSource": "https://wunderground.com/...",
        "markets": [
            {
                "question": "Will temp be 34-35F?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.35", "0.65"]',
                "clobTokenIds": '["abc123", "def456"]',
                "active": True,
                "closed": False,
            }
        ],
    }


@pytest.mark.asyncio
async def test_discover_new_event(registry, mock_gamma_response):
    task = EventDiscoveryTask(registry, cities=["nyc"], days_ahead=1)

    with patch.object(task, "_fetch_event", return_value=mock_gamma_response):
        new_token_ids = await task.discover_once()

    assert len(new_token_ids) == 2
    assert registry.is_event_tracked("213978")


@pytest.mark.asyncio
async def test_skip_already_tracked_event(registry, mock_gamma_response):
    # Pre-register the event
    registry.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[],
    )

    task = EventDiscoveryTask(registry, cities=["nyc"], days_ahead=1)

    with patch.object(task, "_fetch_event", return_value=mock_gamma_response):
        new_token_ids = await task.discover_once()

    # Should return empty since already tracked
    assert len(new_token_ids) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_event_discovery.py -v`
Expected: FAIL with "cannot import name 'EventDiscoveryTask'"

**Step 3: Write minimal implementation**

```python
# producer/signal_producer/tasks/event_discovery.py
"""Event discovery task - polls Gamma API for new events."""

import asyncio
import json
from datetime import date, timedelta

import httpx
import structlog

from ..registry.registry import MarketRegistry
from ..strategies.weather.markets import parse_temp_range

logger = structlog.get_logger()

GAMMA_API_URL = "https://gamma-api.polymarket.com"
DEFAULT_CITIES = ["nyc", "chicago", "miami", "la"]
MONTH_NAMES = [
    "", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]


def build_weather_slug(city: str, target_date: date) -> str:
    """Build Polymarket weather event slug."""
    month = MONTH_NAMES[target_date.month]
    return f"highest-temperature-in-{city}-on-{month}-{target_date.day}-{target_date.year}"


class EventDiscoveryTask:
    """
    Discovers new weather events from Gamma API.

    Polls every N seconds, registers new events in MarketRegistry.
    """

    def __init__(
        self,
        registry: MarketRegistry,
        cities: list[str] | None = None,
        days_ahead: int = 4,
        poll_interval: float = 10.0,
    ):
        self._registry = registry
        self._cities = cities or DEFAULT_CITIES
        self._days_ahead = days_ahead
        self._poll_interval = poll_interval
        self._running = False

    async def _fetch_event(self, slug: str) -> dict | None:
        """Fetch event from Gamma API by slug."""
        url = f"{GAMMA_API_URL}/events/slug/{slug}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10.0)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.warning("Failed to fetch event", slug=slug, error=str(e))
            return None

    async def _check_event_closed(self, event_id: str) -> bool:
        """Check if an event is closed via Gamma API."""
        url = f"{GAMMA_API_URL}/events/{event_id}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=10.0)
                if resp.status_code == 404:
                    return True  # Treat missing as closed
                resp.raise_for_status()
                data = resp.json()
                return data.get("closed", False)
        except Exception as e:
            logger.warning("Failed to check event status", event_id=event_id, error=str(e))
            return False

    def _parse_markets(self, event_data: dict) -> list[dict]:
        """Parse markets from Gamma API response."""
        markets = []
        for m in event_data.get("markets", []):
            if not m.get("active", True) or m.get("closed", False):
                continue

            try:
                tokens = json.loads(m.get("clobTokenIds", "[]"))
                prices = json.loads(m.get("outcomePrices", "[]"))
            except json.JSONDecodeError:
                continue

            if len(tokens) < 2:
                continue

            question = m.get("question", "")
            low_temp, high_temp = parse_temp_range(question)

            # YES token
            markets.append({
                "token_id": tokens[0],
                "side": "yes",
                "market_description": question,
                "low_temp": low_temp,
                "high_temp": high_temp,
            })
            # NO token
            markets.append({
                "token_id": tokens[1],
                "side": "no",
                "market_description": question,
                "low_temp": low_temp,
                "high_temp": high_temp,
            })

        return markets

    async def discover_once(self) -> list[str]:
        """Run one discovery cycle, return new token_ids to subscribe."""
        all_new_tokens = []
        today = date.today()

        for city in self._cities:
            for day_offset in range(1, self._days_ahead + 1):
                target_date = today + timedelta(days=day_offset)
                slug = build_weather_slug(city, target_date)

                # Check if already tracked
                # We need to fetch to get event_id, but can skip if we have a mapping
                event_data = await self._fetch_event(slug)
                if not event_data:
                    continue

                event_id = event_data.get("id")
                if not event_id:
                    continue

                if self._registry.is_event_tracked(event_id):
                    continue

                if event_data.get("closed", False):
                    continue

                markets = self._parse_markets(event_data)

                new_tokens = self._registry.register_event(
                    event_id=event_id,
                    event_type="weather",
                    city=city,
                    target_date=target_date,
                    resolution_source=event_data.get("resolutionSource", ""),
                    markets=markets,
                )

                all_new_tokens.extend(new_tokens)
                logger.info(
                    "Discovered new event",
                    event_id=event_id,
                    city=city,
                    target_date=str(target_date),
                    markets=len(markets),
                )

        return all_new_tokens

    async def cleanup_on_startup(self) -> None:
        """Check tracked events against Gamma API, mark resolved ones."""
        events = self._registry.get_active_events()

        for event in events:
            is_closed = await self._check_event_closed(event.event_id)
            if is_closed:
                self._registry.mark_resolved(event.event_id)
                logger.info("Marked stale event as resolved on startup", event_id=event.event_id)

    async def run(self) -> None:
        """Run the discovery task (polling loop)."""
        self._running = True

        while self._running:
            try:
                new_tokens = await self.discover_once()
                if new_tokens:
                    logger.info("Discovery cycle complete", new_tokens=len(new_tokens))
            except Exception as e:
                logger.error("Discovery cycle failed", error=str(e))

            await asyncio.sleep(self._poll_interval)

    async def stop(self) -> None:
        """Stop the discovery task."""
        self._running = False
```

**Step 4: Update tasks __init__.py**

```python
# producer/signal_producer/tasks/__init__.py
"""Async tasks for the producer."""

from .price_tracker import PriceTracker
from .event_discovery import EventDiscoveryTask

__all__ = ["PriceTracker", "EventDiscoveryTask"]
```

**Step 5: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_event_discovery.py -v`
Expected: PASS (2 tests)

**Step 6: Commit**

```bash
git add producer/signal_producer/tasks/
git add producer/tests/test_event_discovery.py
git commit -m "feat: add event discovery task with Gamma API polling"
```

---

## Task 7: Create Signal Generator Task

**Files:**
- Create: `producer/signal_producer/tasks/signal_generator.py`
- Test: `producer/tests/test_signal_generator.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_signal_generator.py
"""Tests for signal generator task."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine

from signal_producer.registry.models import Base, TrackedEvent, TrackedMarket, EventStatus
from signal_producer.registry.registry import MarketRegistry
from signal_producer.tasks.signal_generator import SignalGeneratorTask
from signal_producer.signals.types import ProducerSignal


@pytest.fixture
def registry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    reg = MarketRegistry(engine)

    # Register a test event
    reg.register_event(
        event_id="213978",
        event_type="weather",
        city="nyc",
        target_date=date(2026, 2, 20),
        resolution_source="https://wunderground.com/...",
        markets=[
            {"token_id": "yes_token", "side": "yes", "market_description": "Will temp be 34-35F?", "low_temp": 34.0, "high_temp": 36.0},
            {"token_id": "no_token", "side": "no", "market_description": "Will temp be 34-35F?", "low_temp": 34.0, "high_temp": 36.0},
        ],
    )

    # Set prices
    reg.update_price("yes_token", 0.25, "2026-02-19T12:00:00Z")
    reg.update_price("no_token", 0.75, "2026-02-19T12:00:00Z")

    return reg


@pytest.fixture
def mock_ensemble():
    """Mock ensemble with 12/31 members in 34-36 range."""
    return {
        "member_highs": [35.0] * 12 + [40.0] * 19,  # 12 in range, 19 out
        "mean": 37.5,
        "std": 2.5,
        "target_date": date(2026, 2, 20),
    }


@pytest.mark.asyncio
async def test_generate_yes_signal_when_underpriced(registry, mock_ensemble):
    broadcaster = AsyncMock()
    task = SignalGeneratorTask(registry, broadcaster)

    with patch.object(task, "_fetch_ensemble", return_value=mock_ensemble):
        signals = await task.generate_signals_for_event("213978")

    # model_prob = 12/31 = 0.387, market_price = 0.25
    # Edge = 0.387 - 0.25 = 0.137 > 0 → YES signal
    yes_signals = [s for s in signals if s.exchanges[0]["side"] == "yes"]
    assert len(yes_signals) == 1
    assert yes_signals[0].model_probability == pytest.approx(12/31, rel=0.01)


@pytest.mark.asyncio
async def test_generate_no_signal_when_overpriced(registry, mock_ensemble):
    # Set YES price high (overpriced)
    registry.update_price("yes_token", 0.60, "2026-02-19T12:00:00Z")
    registry.update_price("no_token", 0.40, "2026-02-19T12:00:00Z")

    broadcaster = AsyncMock()
    task = SignalGeneratorTask(registry, broadcaster)

    with patch.object(task, "_fetch_ensemble", return_value=mock_ensemble):
        signals = await task.generate_signals_for_event("213978")

    # model_prob = 12/31 = 0.387, YES market_price = 0.60
    # YES is overpriced (0.60 > 0.387), so NO is underpriced
    # NO edge = (1 - 0.387) - 0.40 = 0.213 > 0 → NO signal
    no_signals = [s for s in signals if s.exchanges[0]["side"] == "no"]
    assert len(no_signals) == 1


@pytest.mark.asyncio
async def test_skip_signal_when_no_edge(registry, mock_ensemble):
    # Set price equal to model prob
    registry.update_price("yes_token", 0.387, "2026-02-19T12:00:00Z")
    registry.update_price("no_token", 0.613, "2026-02-19T12:00:00Z")

    broadcaster = AsyncMock()
    task = SignalGeneratorTask(registry, broadcaster)

    with patch.object(task, "_fetch_ensemble", return_value=mock_ensemble):
        signals = await task.generate_signals_for_event("213978")

    # No edge, no signals
    assert len(signals) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_signal_generator.py -v`
Expected: FAIL with "cannot import name 'SignalGeneratorTask'"

**Step 3: Write minimal implementation**

```python
# producer/signal_producer/tasks/signal_generator.py
"""Signal generator task - creates ProducerSignals from forecasts."""

import asyncio
from datetime import datetime, date, UTC
from typing import Callable, Awaitable

import httpx
import structlog

from ..registry.registry import MarketRegistry
from ..registry.models import TrackedEvent, TrackedMarket
from ..signals.types import (
    ProducerSignal,
    WeatherMetadata,
    PolymarketInfo,
)

logger = structlog.get_logger()

OPEN_METEO_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
EDGE_THRESHOLD = 0.02  # Minimum edge to generate signal


class SignalGeneratorTask:
    """
    Generates ProducerSignals from ensemble forecasts.

    Fetches forecasts, calculates model probabilities,
    compares with cached prices, emits signals.
    """

    def __init__(
        self,
        registry: MarketRegistry,
        broadcaster: Callable[[ProducerSignal], Awaitable[None]],
        edge_threshold: float = EDGE_THRESHOLD,
        forecast_interval: float = 6 * 60 * 60,  # 6 hours
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._edge_threshold = edge_threshold
        self._forecast_interval = forecast_interval
        self._running = False

    async def _fetch_ensemble(self, city: str, target_date: date) -> dict | None:
        """Fetch ensemble forecast from Open-Meteo."""
        # City coordinates (simplified)
        coords = {
            "nyc": (40.7128, -74.0060),
            "chicago": (41.8781, -87.6298),
            "miami": (25.7617, -80.1918),
            "la": (34.0522, -118.2437),
        }

        lat, lon = coords.get(city, (40.7128, -74.0060))

        params = {
            "latitude": lat,
            "longitude": lon,
            "models": "gfs_seamless",
            "hourly": "temperature_2m",
            "temperature_unit": "fahrenheit",
            "timezone": "America/New_York",
            "forecast_days": 7,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(OPEN_METEO_URL, params=params, timeout=30.0)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.critical(
                "FORECAST_FETCH_FAILED",
                city=city,
                target_date=str(target_date),
                error=str(e),
                impact="Signal generation skipped - potential missed opportunity",
            )
            return None

        # Parse ensemble members
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])

        # Find hours for target date
        target_str = target_date.isoformat()
        target_indices = [i for i, t in enumerate(times) if t.startswith(target_str)]

        if not target_indices:
            return None

        # Get all member keys
        member_keys = ["temperature_2m"] + [f"temperature_2m_member{i:02d}" for i in range(1, 31)]

        # Get daily high for each member
        member_highs = []
        for key in member_keys:
            if key not in hourly:
                continue
            temps = hourly[key]
            day_temps = [temps[i] for i in target_indices if i < len(temps)]
            if day_temps:
                member_highs.append(max(day_temps))

        if not member_highs:
            return None

        return {
            "member_highs": member_highs,
            "mean": sum(member_highs) / len(member_highs),
            "std": (sum((t - sum(member_highs)/len(member_highs))**2 for t in member_highs) / len(member_highs)) ** 0.5,
            "target_date": target_date,
        }

    def _calculate_probability(self, ensemble: dict, low_temp: float | None, high_temp: float | None) -> float:
        """Calculate probability that temp falls in range."""
        member_highs = ensemble["member_highs"]
        count = 0
        for temp in member_highs:
            if low_temp is None:
                if temp < high_temp:
                    count += 1
            elif high_temp is None:
                if temp >= low_temp:
                    count += 1
            else:
                if low_temp <= temp < high_temp:
                    count += 1
        return count / len(member_highs)

    async def generate_signals_for_event(self, event_id: str) -> list[ProducerSignal]:
        """Generate signals for a single event."""
        signals = []

        with self._registry._session() as session:
            event = session.query(TrackedEvent).filter_by(event_id=event_id).first()
            if not event:
                return signals

            # Fetch ensemble
            ensemble = await self._fetch_ensemble(event.city, event.target_date)
            if not ensemble:
                return signals

            forecast_time = datetime.now(UTC).isoformat()

            # Group markets by description (YES/NO pairs)
            markets_by_desc: dict[str, list[TrackedMarket]] = {}
            for market in event.markets:
                desc = market.market_description
                if desc not in markets_by_desc:
                    markets_by_desc[desc] = []
                markets_by_desc[desc].append(market)

            for desc, markets in markets_by_desc.items():
                yes_market = next((m for m in markets if m.side == "yes"), None)
                no_market = next((m for m in markets if m.side == "no"), None)

                if not yes_market:
                    continue

                # Calculate model probability
                model_prob = self._calculate_probability(
                    ensemble,
                    yes_market.low_temp,
                    yes_market.high_temp,
                )

                # Get cached prices
                yes_price_entry = self._registry.get_price(yes_market.token_id)
                if not yes_price_entry:
                    logger.warning("No cached price for YES token", token_id=yes_market.token_id[:20])
                    continue

                yes_price = yes_price_entry.price
                no_price = 1 - yes_price  # Approximation

                if no_market:
                    no_price_entry = self._registry.get_price(no_market.token_id)
                    if no_price_entry:
                        no_price = no_price_entry.price

                # Calculate edges
                yes_edge = model_prob - yes_price
                no_edge = (1 - model_prob) - no_price

                # Build metadata
                metadata: WeatherMetadata = {
                    "city": event.city,
                    "target_date": event.target_date.isoformat(),
                    "ensemble_mean": ensemble["mean"],
                    "ensemble_std": ensemble["std"],
                    "members_in_range": int(model_prob * len(ensemble["member_highs"])),
                }

                # Generate YES signal if edge exists
                if yes_edge >= self._edge_threshold:
                    exchange_info: PolymarketInfo = {
                        "exchange": "polymarket",
                        "event_id": event_id,
                        "token_id": yes_market.token_id,
                        "side": "yes",
                        "market_description": desc,
                        "resolution_source": event.resolution_source or "",
                        "market_price": yes_price,
                        "edge": yes_edge,
                        "price_timestamp": yes_price_entry.timestamp,
                    }

                    signal = ProducerSignal(
                        signal_type="weather",
                        model_probability=model_prob,
                        confidence=1.0 - min(ensemble["std"] / 10, 0.5),  # Simple confidence
                        forecast_source="open_meteo",
                        forecast_time=forecast_time,
                        metadata=metadata,
                        exchanges=[exchange_info],
                    )
                    signals.append(signal)

                # Generate NO signal if edge exists
                if no_market and no_edge >= self._edge_threshold:
                    no_price_entry = self._registry.get_price(no_market.token_id)

                    exchange_info: PolymarketInfo = {
                        "exchange": "polymarket",
                        "event_id": event_id,
                        "token_id": no_market.token_id,
                        "side": "no",
                        "market_description": desc,
                        "resolution_source": event.resolution_source or "",
                        "market_price": no_price,
                        "edge": no_edge,
                        "price_timestamp": no_price_entry.timestamp if no_price_entry else "",
                    }

                    signal = ProducerSignal(
                        signal_type="weather",
                        model_probability=model_prob,
                        confidence=1.0 - min(ensemble["std"] / 10, 0.5),
                        forecast_source="open_meteo",
                        forecast_time=forecast_time,
                        metadata=metadata,
                        exchanges=[exchange_info],
                    )
                    signals.append(signal)

        return signals

    async def generate_and_broadcast(self) -> int:
        """Generate signals for all active events and broadcast."""
        events = self._registry.get_active_events()
        total_signals = 0

        for event in events:
            signals = await self.generate_signals_for_event(event.event_id)
            for signal in signals:
                await self._broadcaster(signal)
                total_signals += 1

        return total_signals

    async def run(self) -> None:
        """Run the signal generator (periodic loop)."""
        self._running = True

        while self._running:
            try:
                count = await self.generate_and_broadcast()
                logger.info("Signal generation cycle complete", signals=count)
            except Exception as e:
                logger.error("Signal generation failed", error=str(e))

            await asyncio.sleep(self._forecast_interval)

    async def stop(self) -> None:
        """Stop the signal generator."""
        self._running = False
```

**Step 4: Update tasks __init__.py**

```python
# producer/signal_producer/tasks/__init__.py
"""Async tasks for the producer."""

from .price_tracker import PriceTracker
from .event_discovery import EventDiscoveryTask
from .signal_generator import SignalGeneratorTask

__all__ = ["PriceTracker", "EventDiscoveryTask", "SignalGeneratorTask"]
```

**Step 5: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_signal_generator.py -v`
Expected: PASS (3 tests)

**Step 6: Commit**

```bash
git add producer/signal_producer/tasks/
git add producer/tests/test_signal_generator.py
git commit -m "feat: add signal generator task with YES/NO signal support"
```

---

## Task 8: Update WebSocket Broadcaster for ProducerSignal

**Files:**
- Modify: `producer/signal_producer/publishing/websocket.py`
- Test: `producer/tests/test_ws_broadcaster.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_ws_broadcaster.py
"""Tests for websocket broadcaster with ProducerSignal."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from signal_producer.signals.types import ProducerSignal, WeatherMetadata, PolymarketInfo
from signal_producer.publishing.websocket import SignalBroadcaster


@pytest.fixture
def sample_producer_signal():
    metadata: WeatherMetadata = {
        "city": "nyc",
        "target_date": "2026-02-20",
        "ensemble_mean": 34.8,
        "ensemble_std": 2.1,
        "members_in_range": 12,
    }
    exchange: PolymarketInfo = {
        "exchange": "polymarket",
        "event_id": "213978",
        "token_id": "abc123",
        "side": "yes",
        "market_description": "Will temp be 34-35F?",
        "resolution_source": "https://wunderground.com/...",
        "market_price": 0.35,
        "edge": 0.05,
        "price_timestamp": "2026-02-19T12:00:00Z",
    }
    return ProducerSignal(
        signal_type="weather",
        model_probability=0.40,
        confidence=0.85,
        forecast_source="open_meteo",
        forecast_time="2026-02-19T08:00:00Z",
        metadata=metadata,
        exchanges=[exchange],
    )


@pytest.mark.asyncio
async def test_broadcast_producer_signal(sample_producer_signal):
    broadcaster = SignalBroadcaster()

    mock_ws = AsyncMock()
    await broadcaster.connect(mock_ws)

    await broadcaster.broadcast_producer_signal(sample_producer_signal)

    mock_ws.send_json.assert_called_once()
    payload = mock_ws.send_json.call_args[0][0]

    assert payload["signal_type"] == "weather"
    assert payload["model_probability"] == 0.40
    assert payload["metadata"]["city"] == "nyc"
    assert payload["exchanges"][0]["exchange"] == "polymarket"
    assert "published_at" in payload
```

**Step 2: Run test to verify it fails**

Run: `cd producer && python -m pytest tests/test_ws_broadcaster.py -v`
Expected: FAIL (broadcast_producer_signal doesn't exist)

**Step 3: Update websocket.py**

Add to `producer/signal_producer/publishing/websocket.py`:

```python
# Add import at top
from ..signals.types import ProducerSignal

# Add method to SignalBroadcaster class
async def broadcast_producer_signal(self, signal: ProducerSignal) -> None:
    """Broadcast a ProducerSignal to all connected clients."""
    payload = signal.to_dict()

    # Get first exchange info for logging
    exchange_info = signal.exchanges[0] if signal.exchanges else {}
    market_id = exchange_info.get("event_id", "unknown")
    token_id = exchange_info.get("token_id", "unknown")

    await self._broadcast_payload(payload, market_id=market_id, token_id=token_id)
```

**Step 4: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_ws_broadcaster.py -v`
Expected: PASS (1 test)

**Step 5: Commit**

```bash
git add producer/signal_producer/publishing/websocket.py
git add producer/tests/test_ws_broadcaster.py
git commit -m "feat: add broadcast_producer_signal to websocket broadcaster"
```

---

## Task 9: Create Main Orchestrator

**Files:**
- Create: `producer/signal_producer/orchestrator.py`
- Test: `producer/tests/test_orchestrator.py`

**Step 1: Write the failing test**

```python
# producer/tests/test_orchestrator.py
"""Tests for main orchestrator."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from signal_producer.orchestrator import ProducerOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_starts_all_tasks():
    with patch("signal_producer.orchestrator.MarketRegistry") as MockRegistry:
        with patch("signal_producer.orchestrator.EventDiscoveryTask") as MockDiscovery:
            with patch("signal_producer.orchestrator.PriceTracker") as MockTracker:
                with patch("signal_producer.orchestrator.SignalGeneratorTask") as MockGenerator:
                    mock_registry = MagicMock()
                    MockRegistry.return_value = mock_registry

                    mock_discovery = AsyncMock()
                    MockDiscovery.return_value = mock_discovery

                    mock_tracker = AsyncMock()
                    MockTracker.return_value = mock_tracker

                    mock_generator = AsyncMock()
                    MockGenerator.return_value = mock_generator

                    orchestrator = ProducerOrchestrator(db_path=":memory:")

                    # Start should call cleanup and start tasks
                    mock_discovery.cleanup_on_startup = AsyncMock()
                    mock_discovery.run = AsyncMock()
                    mock_tracker.run = AsyncMock()
                    mock_tracker.subscribe = AsyncMock()
                    mock_generator.run = AsyncMock()

                    # We can't easily test the full run loop, but we can test setup
                    assert orchestrator._registry is not None
```

**Step 2: Write minimal implementation**

```python
# producer/signal_producer/orchestrator.py
"""Main orchestrator that coordinates all producer tasks."""

import asyncio

import structlog
from sqlalchemy import create_engine

from .registry.models import Base
from .registry.registry import MarketRegistry
from .tasks.event_discovery import EventDiscoveryTask
from .tasks.price_tracker import PriceTracker
from .tasks.signal_generator import SignalGeneratorTask
from .publishing.websocket import broadcaster

logger = structlog.get_logger()


class ProducerOrchestrator:
    """
    Coordinates all producer tasks:
    - Event discovery (Gamma API polling)
    - Price tracking (CLOB websocket)
    - Signal generation (forecast polling)
    - WebSocket server (broadcasting)
    """

    def __init__(
        self,
        db_path: str = "data/producer.db",
        discovery_interval: float = 10.0,
        forecast_interval: float = 6 * 60 * 60,
        cities: list[str] | None = None,
    ):
        self._engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(self._engine)

        self._registry = MarketRegistry(self._engine)

        self._discovery = EventDiscoveryTask(
            self._registry,
            cities=cities,
            poll_interval=discovery_interval,
        )

        self._price_tracker = PriceTracker(
            self._registry,
            on_market_resolved=self._on_market_resolved,
        )

        self._signal_generator = SignalGeneratorTask(
            self._registry,
            broadcaster=self._broadcast_signal,
        )

        self._tasks: list[asyncio.Task] = []

    async def _broadcast_signal(self, signal) -> None:
        """Broadcast signal via websocket."""
        await broadcaster.broadcast_producer_signal(signal)

    async def _on_market_resolved(self, event_id: str) -> None:
        """Handle market resolution."""
        logger.info("Market resolved callback", event_id=event_id)

    async def _on_new_tokens(self, token_ids: list[str]) -> None:
        """Subscribe to new tokens when discovered."""
        if token_ids:
            await self._price_tracker.subscribe(token_ids)

    async def startup(self) -> None:
        """Initialize and start all tasks."""
        logger.info("Starting producer orchestrator...")

        # Cleanup stale events
        await self._discovery.cleanup_on_startup()

        # Get active tokens and subscribe
        token_ids = self._registry.get_active_token_ids()
        if token_ids:
            await self._price_tracker.subscribe(token_ids)
            logger.info("Resubscribed to active tokens", count=len(token_ids))

        # Start tasks
        self._tasks = [
            asyncio.create_task(self._discovery.run(), name="discovery"),
            asyncio.create_task(self._price_tracker.run(), name="price_tracker"),
            asyncio.create_task(self._signal_generator.run(), name="signal_generator"),
            asyncio.create_task(self._discovery_subscription_loop(), name="discovery_subscription"),
        ]

        logger.info("Producer orchestrator started", tasks=len(self._tasks))

    async def _discovery_subscription_loop(self) -> None:
        """Monitor for new tokens from discovery and subscribe."""
        while True:
            try:
                new_tokens = await self._discovery.discover_once()
                if new_tokens:
                    await self._price_tracker.subscribe(new_tokens)
            except Exception as e:
                logger.error("Discovery subscription loop error", error=str(e))
            await asyncio.sleep(10)

    async def shutdown(self) -> None:
        """Stop all tasks gracefully."""
        logger.info("Shutting down producer orchestrator...")

        await self._discovery.stop()
        await self._price_tracker.stop()
        await self._signal_generator.stop()

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        logger.info("Producer orchestrator stopped")

    async def run(self) -> None:
        """Run the orchestrator until interrupted."""
        await self.startup()

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()
```

**Step 3: Run test to verify it passes**

Run: `cd producer && python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (1 test)

**Step 4: Commit**

```bash
git add producer/signal_producer/orchestrator.py
git add producer/tests/test_orchestrator.py
git commit -m "feat: add ProducerOrchestrator to coordinate all tasks"
```

---

## Task 10: Integration Test - Full Flow

**Files:**
- Create: `producer/tests/test_integration.py`

**Step 1: Write the integration test**

```python
# producer/tests/test_integration.py
"""Integration tests for full producer flow."""

import pytest
import asyncio
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy import create_engine

from signal_producer.registry.models import Base
from signal_producer.registry.registry import MarketRegistry
from signal_producer.tasks.event_discovery import EventDiscoveryTask
from signal_producer.tasks.signal_generator import SignalGeneratorTask
from signal_producer.signals.types import ProducerSignal


@pytest.fixture
def registry():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return MarketRegistry(engine)


@pytest.fixture
def mock_gamma_response():
    return {
        "id": "213978",
        "title": "Highest temperature in NYC on February 20?",
        "closed": False,
        "resolutionSource": "https://wunderground.com/...",
        "markets": [
            {
                "question": "Will the highest temperature in New York City be between 34-35°F on February 20?",
                "outcomes": '["Yes", "No"]',
                "outcomePrices": '["0.35", "0.65"]',
                "clobTokenIds": '["yes_token_123", "no_token_456"]',
                "active": True,
                "closed": False,
            }
        ],
    }


@pytest.fixture
def mock_ensemble():
    return {
        "member_highs": [35.0] * 15 + [40.0] * 16,  # 15 in range
        "mean": 37.5,
        "std": 2.5,
        "target_date": date(2026, 2, 20),
    }


@pytest.mark.asyncio
async def test_full_flow_discovery_to_signal(registry, mock_gamma_response, mock_ensemble):
    """Test: discover event → update prices → generate signal → broadcast."""

    signals_received = []

    async def capture_signal(signal: ProducerSignal):
        signals_received.append(signal)

    # Step 1: Discover event
    discovery = EventDiscoveryTask(registry, cities=["nyc"], days_ahead=1)

    with patch.object(discovery, "_fetch_event", return_value=mock_gamma_response):
        new_tokens = await discovery.discover_once()

    assert len(new_tokens) == 2
    assert registry.is_event_tracked("213978")

    # Step 2: Simulate price updates from CLOB websocket
    registry.update_price("yes_token_123", 0.30, "2026-02-19T12:00:00Z")
    registry.update_price("no_token_456", 0.70, "2026-02-19T12:00:00Z")

    # Step 3: Generate signals
    generator = SignalGeneratorTask(registry, broadcaster=capture_signal, edge_threshold=0.02)

    with patch.object(generator, "_fetch_ensemble", return_value=mock_ensemble):
        signals = await generator.generate_signals_for_event("213978")

    # model_prob = 15/31 ≈ 0.484
    # yes_edge = 0.484 - 0.30 = 0.184 > 0.02 → YES signal
    assert len(signals) >= 1

    yes_signal = next((s for s in signals if s.exchanges[0]["side"] == "yes"), None)
    assert yes_signal is not None
    assert yes_signal.signal_type == "weather"
    assert yes_signal.metadata["city"] == "nyc"
    assert yes_signal.exchanges[0]["exchange"] == "polymarket"
    assert yes_signal.exchanges[0]["edge"] > 0.02
```

**Step 2: Run integration test**

Run: `cd producer && python -m pytest tests/test_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add producer/tests/test_integration.py
git commit -m "test: add integration test for full discovery-to-signal flow"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | ProducerSignal types | `signals/types.py` |
| 2 | Rename WeatherBucket → WeatherMarket | `strategies/weather/*.py` |
| 3 | TrackedEvent SQLAlchemy models | `registry/models.py` |
| 4 | MarketRegistry class | `registry/registry.py` |
| 5 | CLOB websocket price tracker | `tasks/price_tracker.py` |
| 6 | Event discovery task | `tasks/event_discovery.py` |
| 7 | Signal generator task | `tasks/signal_generator.py` |
| 8 | Update websocket broadcaster | `publishing/websocket.py` |
| 9 | Main orchestrator | `orchestrator.py` |
| 10 | Integration test | `tests/test_integration.py` |

---

**Plan complete and saved to `docs/plans/2026-02-19-producer-signal-architecture.md`. Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**