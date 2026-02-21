"""Signal generator task.

Generates ProducerSignals by combining ensemble forecasts with market prices.
Broadcasts signal preview messages for the marketplace auction protocol.
"""

import asyncio
import json
import uuid
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy.orm import Session

from ..models.models import SignalRecord
from ..signals.types import (
    ProducerSignal,
    ProducerSignalPreview,
    PreviewPolymarketInfo,
    WeatherMetadata,
    PolymarketInfo,
)
from ..clients.llm_pricer import price_signal
from ..config import CITIES

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from ..registry.market_registry import MarketRegistry, CachedEvent, CachedMarket
    from ..clients.open_meteo import OpenMeteoClient
    from ..publishing.websocket import SignalBroadcaster

logger = structlog.get_logger()

DEFAULT_FORECAST_INTERVAL = 6 * 60 * 60  # 6 hours in seconds
DEFAULT_EDGE_THRESHOLD = 0.08  # 8%


class SignalGeneratorTask:
    """
    Generates signals by comparing forecasts to market prices.

    On each cycle:
    1. Gets active events from registry
    2. Fetches ensemble forecast for each event
    3. Calculates model_probability per market
    4. Gets cached prices from registry
    5. Generates YES/NO ProducerSignals where edge exists
    6. Broadcasts signal preview messages via websocket
    """

    def __init__(
        self,
        registry: "MarketRegistry",
        open_meteo_client: "OpenMeteoClient",
        broadcaster: "SignalBroadcaster | None" = None,
        engine: "Engine | None" = None,
        edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
        forecast_interval: int = DEFAULT_FORECAST_INTERVAL,
        llm_pricing_mode: str = "mock",
        zg_endpoint: str = "",
        zg_model: str = "",
        llm_temperature: float = 0.8,
        signal_preview_ttl_minutes: int = 30,
        producer_id: str = "",
    ):
        self._registry = registry
        self._open_meteo = open_meteo_client
        self._broadcaster = broadcaster
        self._engine = engine
        self._edge_threshold = edge_threshold
        self._forecast_interval = forecast_interval
        self._running = False

        # Marketplace config
        self._llm_pricing_mode = llm_pricing_mode
        self._zg_endpoint = zg_endpoint
        self._zg_model = zg_model
        self._llm_temperature = llm_temperature
        self._preview_ttl_minutes = signal_preview_ttl_minutes
        self._producer_id = producer_id

        # Track last price paid (updated externally when auction settles)
        self._last_price_paid_usd: float = 0.0

    @property
    def last_price_paid_usd(self) -> float:
        return self._last_price_paid_usd

    @last_price_paid_usd.setter
    def last_price_paid_usd(self, value: float) -> None:
        self._last_price_paid_usd = value

    def _calculate_market_probability(
        self, member_highs: list[float], low_temp: float | None, high_temp: float | None
    ) -> float:
        """Calculate probability that temp falls in range."""
        count = 0
        for temp in member_highs:
            if low_temp is None:
                # "X or below" market
                if temp < high_temp:
                    count += 1
            elif high_temp is None:
                # "X or above" market
                if temp >= low_temp:
                    count += 1
            else:
                # Range market
                if low_temp <= temp < high_temp:
                    count += 1

        return count / len(member_highs) if member_highs else 0.0

    def _build_producer_signal(
        self,
        event: "CachedEvent",
        market: "CachedMarket",
        model_prob: float,
        market_price: float,
        side: str,
        edge: float,
        forecast: Any,
    ) -> ProducerSignal:
        """Build a ProducerSignal from event/market data."""
        # Calculate members in range for metadata
        members_in_range = int(model_prob * len(forecast.member_highs))

        metadata: WeatherMetadata = {
            "city": event.city,
            "target_date": event.target_date.isoformat(),
            "ensemble_mean": forecast.mean,
            "ensemble_std": forecast.std,
            "members_in_range": members_in_range,
        }

        exchange_info: PolymarketInfo = {
            "exchange": "polymarket",
            "event_id": event.event_id,
            "token_id": market.yes_token_id if side == "yes" else market.no_token_id,
            "side": side,
            "market_description": market.question,
            "resolution_source": "",  # Could be fetched from DB
            "market_price": market_price,
            "edge": edge,
            "price_timestamp": market.price_timestamp or datetime.now(UTC).isoformat(),
        }

        return ProducerSignal(
            signal_type="weather",
            model_probability=model_prob if side == "yes" else (1 - model_prob),
            confidence=self._calculate_confidence(forecast),
            forecast_source="open_meteo",
            forecast_time=datetime.now(UTC).isoformat(),
            metadata=metadata,
            exchanges=[exchange_info],
        )

    def _calculate_confidence(self, forecast: Any) -> float:
        """Calculate confidence based on ensemble spread."""
        spread = forecast.max - forecast.min

        if spread <= 5:
            return 1.0
        elif spread >= 20:
            return 0.3
        else:
            return 1.0 - (spread - 5) / 15 * 0.7

    async def _generate_for_event(self, event: "CachedEvent") -> list[ProducerSignal]:
        """Generate signals for a single event."""
        signals = []

        # Get city config for coordinates
        city_config = CITIES.get(event.city)
        if not city_config:
            logger.warning("Unknown city", city=event.city)
            return signals

        # Fetch ensemble forecast
        try:
            forecast = await self._open_meteo.get_ensemble_forecast(
                lat=city_config.lat,
                lon=city_config.lon,
                target_date=event.target_date,
                timezone=city_config.tz,
                city=event.city,
            )
        except Exception as e:
            logger.critical(
                "FORECAST_FETCH_FAILED",
                event_id=event.event_id,
                city=event.city,
                target_date=str(event.target_date),
                error=str(e),
                impact="Signal generation skipped - potential missed opportunity",
            )
            return signals

        # Process each unique market (dedupe by yes_token_id)
        seen_tokens = set()
        for token_id, market in event.markets.items():
            if market.yes_token_id in seen_tokens:
                continue
            seen_tokens.add(market.yes_token_id)

            # Skip invalid markets
            if market.low_temp is None and market.high_temp is None:
                continue

            # Get cached price
            yes_price = self._registry.get_price(market.yes_token_id)
            if yes_price is None:
                logger.debug("No price for market", token_id=market.yes_token_id)
                continue

            # Calculate model probability
            model_prob = self._calculate_market_probability(
                forecast.member_highs,
                market.low_temp,
                market.high_temp,
            )

            # Check for YES edge
            yes_edge = model_prob - yes_price
            if yes_edge >= self._edge_threshold:
                signal = self._build_producer_signal(
                    event=event,
                    market=market,
                    model_prob=model_prob,
                    market_price=yes_price,
                    side="yes",
                    edge=yes_edge,
                    forecast=forecast,
                )
                signals.append(signal)

            # Check for NO edge
            no_price = 1 - yes_price  # Assuming complementary prices
            no_prob = 1 - model_prob
            no_edge = no_prob - no_price
            if no_edge >= self._edge_threshold:
                signal = self._build_producer_signal(
                    event=event,
                    market=market,
                    model_prob=model_prob,
                    market_price=no_price,
                    side="no",
                    edge=no_edge,
                    forecast=forecast,
                )
                signals.append(signal)

        return signals

    def _persist_signal(self, signal: ProducerSignal) -> None:
        """Persist a ProducerSignal to the database."""
        if not self._engine:
            return

        exchange = signal.exchanges[0] if signal.exchanges else {}

        record = SignalRecord(
            strategy="weather",
            market_id=exchange.get("event_id", ""),
            token_id=exchange.get("token_id", ""),
            model_probability=signal.model_probability,
            market_price=exchange.get("market_price", 0.0),
            edge=exchange.get("edge", 0.0),
            confidence=signal.confidence,
            decision="signal",  # Generated signal, not yet traded
            skip_reason=None,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            metadata_json=json.dumps(signal.metadata),
        )

        session = Session(self._engine)
        try:
            session.add(record)
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to persist signal", error=str(e))
        finally:
            session.close()

    def _build_preview(self, signal: ProducerSignal) -> ProducerSignalPreview:
        """Build a ProducerSignalPreview from a full ProducerSignal.

        Strips market details (token_id, side, market_price, market_description,
        resolution_source) — only includes event_id and edge.
        """
        preview_exchanges: list[PreviewPolymarketInfo] = []
        for ex in signal.exchanges:
            preview_exchanges.append(
                PreviewPolymarketInfo(
                    exchange=ex["exchange"],
                    event_id=ex["event_id"],
                    edge=ex["edge"],
                    price_timestamp=ex["price_timestamp"],
                )
            )

        auction_ends = datetime.now(UTC) + timedelta(minutes=self._preview_ttl_minutes)

        return ProducerSignalPreview(
            signal_type=signal.signal_type,
            producer_did=self._producer_id,
            auction_id=str(uuid.uuid4()),
            auction_end_utc=auction_ends.isoformat(),
            last_price_paid=self._last_price_paid_usd,
            model_probability=signal.model_probability,
            confidence=signal.confidence,
            exchanges=preview_exchanges,
        )

    async def _generate_once(self) -> list[ProducerSignal]:
        """Run one signal generation cycle.

        Generates full signals, persists them for audit, then broadcasts
        stripped-down preview messages for the marketplace.
        """
        all_signals = []

        events = self._registry.get_active_events()

        for event in events:
            signals = await self._generate_for_event(event)
            all_signals.extend(signals)

            for signal in signals:
                # Persist full signal to database for audit
                self._persist_signal(signal)

                # Price the signal via LLM (logged for analytics)
                preview = self._build_preview(signal)
                suggested_price = await price_signal(
                    preview,
                    mode=self._llm_pricing_mode,
                    endpoint=self._zg_endpoint,
                    model=self._zg_model,
                    temperature=self._llm_temperature,
                )

                logger.info(
                    "LLM signal pricing",
                    auction_id=preview.auction_id,
                    producer_did=preview.producer_did,
                    suggested_price_usd=suggested_price,
                    last_paid=self._last_price_paid_usd,
                    edge=signal.exchanges[0].get("edge") if signal.exchanges else None,
                )

                # Broadcast preview and start auction via broadcaster
                if self._broadcaster:
                    await self._broadcaster.broadcast_producer_signal(signal)

        if all_signals:
            logger.info(
                "Signals generated",
                count=len(all_signals),
                events=len(events),
            )

        return all_signals

    async def run(self) -> None:
        """Run the signal generator (runs periodically)."""
        self._running = True
        logger.info(
            "Signal generator starting",
            interval_hours=self._forecast_interval / 3600,
            edge_threshold=f"{self._edge_threshold:.0%}",
        )

        while self._running:
            await self._generate_once()
            await asyncio.sleep(self._forecast_interval)

    def stop(self) -> None:
        """Stop the signal generator."""
        self._running = False
        logger.info("Signal generator stopping")
