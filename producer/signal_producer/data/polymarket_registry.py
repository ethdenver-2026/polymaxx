"""Market registry for tracking events, markets, and prices.

SQLite-backed with in-memory cache for fast lookups.
"""

from dataclasses import dataclass
from datetime import datetime, UTC
from typing import Any

import structlog
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..models.models import TrackedEvent, TrackedMarket, TrackedForecast
from ..clients.polymarket.markets import WeatherEvent, WeatherMarket

logger = structlog.get_logger()


@dataclass
class CachedPrice:
    """In-memory cached price for a token."""

    price: float
    timestamp: str


@dataclass
class CachedEvent:
    """In-memory cached event data."""

    event_id: str
    db_id: int
    city: str
    target_date: Any  # date
    status: str
    markets: dict[str, "CachedMarket"]  # token_id -> CachedMarket


@dataclass
class CachedMarket:
    """In-memory cached market data."""

    db_id: int
    question: str
    low_temp: float | None
    high_temp: float | None
    yes_token_id: str
    no_token_id: str
    yes_price: float | None = None
    no_price: float | None = None
    price_timestamp: str | None = None


class MarketRegistry:
    """
    Central store for tracked events, markets, and prices.

    SQLite-backed for persistence, with in-memory cache for fast lookups.
    Prices are ephemeral (in-memory only) as they're repopulated via CLOB websocket.
    """

    def __init__(self, engine: Engine):
        self._engine = engine
        self._session_factory = sessionmaker(bind=engine)
        self._events: dict[str, CachedEvent] = {}  # event_id -> CachedEvent
        self._token_to_event: dict[str, str] = {}  # token_id -> event_id
        self._prices: dict[str, CachedPrice] = {}  # token_id -> CachedPrice
        self._load_from_db()

    def _get_session(self) -> Session:
        return self._session_factory()

    def _load_from_db(self) -> None:
        """Load active events from database into cache."""
        session = self._get_session()
        try:
            db_events = session.query(TrackedEvent).filter(
                TrackedEvent.status == "active"
            ).all()

            for db_event in db_events:
                markets = session.query(TrackedMarket).filter(
                    TrackedMarket.event_id == db_event.id
                ).all()

                cached_markets = {}
                for m in markets:
                    cached_market = CachedMarket(
                        db_id=m.id,
                        question=m.question,
                        low_temp=m.low_temp,
                        high_temp=m.high_temp,
                        yes_token_id=m.yes_token_id,
                        no_token_id=m.no_token_id,
                        yes_price=m.yes_price,
                        no_price=m.no_price,
                    )
                    cached_markets[m.yes_token_id] = cached_market
                    cached_markets[m.no_token_id] = cached_market
                    self._token_to_event[m.yes_token_id] = db_event.event_id
                    self._token_to_event[m.no_token_id] = db_event.event_id

                    # Seed in-memory price cache from DB
                    if m.yes_price is not None:
                        self._prices[m.yes_token_id] = CachedPrice(
                            price=m.yes_price, timestamp="db_seed",
                        )
                    if m.no_price is not None:
                        self._prices[m.no_token_id] = CachedPrice(
                            price=m.no_price, timestamp="db_seed",
                        )

                self._events[db_event.event_id] = CachedEvent(
                    event_id=db_event.event_id,
                    db_id=db_event.id,
                    city=db_event.city,
                    target_date=db_event.target_date,
                    status=db_event.status,
                    markets=cached_markets,
                )

            logger.info("Loaded events from DB", count=len(self._events))
        finally:
            session.close()

    def register_event(self, event: WeatherEvent) -> list[str]:
        """
        Register event, persist to DB, return new token_ids to subscribe.

        If event already exists, returns empty list.
        """
        # Check if already tracked
        if event.event_id in self._events:
            logger.debug("Event already tracked", event_id=event.event_id)
            return []

        session = self._get_session()
        try:
            # Create DB records
            db_event = TrackedEvent(
                event_id=event.event_id,
                title=event.title,
                city=event.city,
                target_date=event.target_date,
                resolution_source=event.resolution_source,
                status="active",
            )
            session.add(db_event)
            session.flush()  # Get the ID

            new_tokens = []
            cached_markets = {}

            for market in event.markets:
                db_market = TrackedMarket(
                    event_id=db_event.id,
                    question=market.question,
                    low_temp=market.low_temp,
                    high_temp=market.high_temp,
                    yes_token_id=market.yes_token_id,
                    no_token_id=market.no_token_id,
                    yes_price=market.yes_price,
                    no_price=market.no_price,
                    active=market.active,
                )
                session.add(db_market)
                session.flush()

                new_tokens.extend([market.yes_token_id, market.no_token_id])

                cached_market = CachedMarket(
                    db_id=db_market.id,
                    question=market.question,
                    low_temp=market.low_temp,
                    high_temp=market.high_temp,
                    yes_token_id=market.yes_token_id,
                    no_token_id=market.no_token_id,
                    yes_price=market.yes_price,
                    no_price=market.no_price,
                )
                cached_markets[market.yes_token_id] = cached_market
                cached_markets[market.no_token_id] = cached_market
                self._token_to_event[market.yes_token_id] = event.event_id
                self._token_to_event[market.no_token_id] = event.event_id

                # Seed in-memory price cache from Gamma API prices so signal
                # generator can work even before CLOB websocket delivers updates
                now_ts = datetime.now(UTC).isoformat()
                if market.yes_price is not None:
                    self._prices[market.yes_token_id] = CachedPrice(
                        price=market.yes_price, timestamp=now_ts,
                    )
                if market.no_price is not None:
                    self._prices[market.no_token_id] = CachedPrice(
                        price=market.no_price, timestamp=now_ts,
                    )

            session.commit()

            # Update cache
            self._events[event.event_id] = CachedEvent(
                event_id=event.event_id,
                db_id=db_event.id,
                city=event.city,
                target_date=event.target_date,
                status="active",
                markets=cached_markets,
            )

            logger.info(
                "Registered event",
                event_id=event.event_id,
                city=event.city,
                markets=len(event.markets),
                tokens=len(new_tokens),
            )

            return new_tokens

        except Exception as e:
            session.rollback()
            logger.error("Failed to register event", event_id=event.event_id, error=str(e))
            raise
        finally:
            session.close()

    def update_price(self, token_id: str, price: float, timestamp: str) -> None:
        """Update cached price (in-memory only, prices are ephemeral)."""
        self._prices[token_id] = CachedPrice(price=price, timestamp=timestamp)

        # Also update the cached market
        event_id = self._token_to_event.get(token_id)
        if event_id and event_id in self._events:
            cached_event = self._events[event_id]
            if token_id in cached_event.markets:
                market = cached_event.markets[token_id]
                if token_id == market.yes_token_id:
                    market.yes_price = price
                else:
                    market.no_price = price
                market.price_timestamp = timestamp

    def get_price(self, token_id: str) -> float | None:
        """Get cached price for a token."""
        cached = self._prices.get(token_id)
        return cached.price if cached else None

    def update_forecast(self, event_id: str, forecast: Any) -> None:
        """Update forecast, persist to DB, mark for signal generation."""
        # TODO: Implement forecast caching
        pass

    def mark_resolved(self, event_id: str, resolution: str) -> list[str]:
        """Mark event resolved (soft delete), return token_ids to unsubscribe."""
        if event_id not in self._events:
            logger.warning("Event not found", event_id=event_id)
            return []

        cached_event = self._events[event_id]
        tokens_to_unsubscribe = list(cached_event.markets.keys())

        session = self._get_session()
        try:
            db_event = session.query(TrackedEvent).filter(
                TrackedEvent.event_id == event_id
            ).first()

            if db_event:
                db_event.status = "resolved"
                db_event.resolved_at = datetime.now(UTC)
                session.commit()

            # Update cache
            cached_event.status = "resolved"

            # Clean up token mapping
            for token_id in tokens_to_unsubscribe:
                self._token_to_event.pop(token_id, None)
                self._prices.pop(token_id, None)

            logger.info(
                "Marked event resolved",
                event_id=event_id,
                tokens_unsubscribed=len(tokens_to_unsubscribe),
            )

            return tokens_to_unsubscribe

        except Exception as e:
            session.rollback()
            logger.error("Failed to mark resolved", event_id=event_id, error=str(e))
            raise
        finally:
            session.close()

    def get_active_events(self) -> list[CachedEvent]:
        """Return only status='active' events."""
        return [e for e in self._events.values() if e.status == "active"]

    def get_active_token_ids(self) -> list[str]:
        """Return all token_ids for active events (used on startup to resubscribe)."""
        tokens = []
        for event in self.get_active_events():
            tokens.extend(event.markets.keys())
        return list(set(tokens))  # Deduplicate
