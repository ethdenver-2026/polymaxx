"""TSA signal generator task.

Generates ProducerSignals for TSA passenger volume markets using external TSA predictor.
"""

import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy.orm import Session

from ..models.models import SignalRecord
from signal_schema import (
    ProducerSignal,
    ProducerSignalPreview,
    PreviewPolymarketInfo,
    TSAMetadata,
    PolymarketInfo,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from ..data.polymarket_registry import MarketRegistry, CachedTSAEvent, CachedTSAMarket
    from ..publishing.websocket_signal_broadcaster import SignalBroadcaster

logger = structlog.get_logger()

DEFAULT_SIGNAL_INTERVAL = 60  # 1 minute in seconds
DEFAULT_EDGE_THRESHOLD = 0.01  # 1%


class TSASignalGeneratorTask:
    """
    Generates TSA signals using external predictor model.

    On each cycle:
    1. Gets active TSA events from registry
    2. Calls external TSA predictor for each event's target date
    3. Gets cached prices from registry (CLOB WebSocket)
    4. Generates YES/NO ProducerSignals where edge exists
    5. Broadcasts via SignalBroadcaster
    """

    def __init__(
        self,
        registry: "MarketRegistry",
        broadcaster: "SignalBroadcaster | None" = None,
        engine: "Engine | None" = None,
        tsa_project_path: str | None = None,
        edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
        signal_interval: int = DEFAULT_SIGNAL_INTERVAL,
        signal_preview_ttl_minutes: int = 5,
        producer_id: str = "",
    ):
        self._registry = registry
        self._broadcaster = broadcaster
        self._engine = engine
        self._edge_threshold = edge_threshold
        self._signal_interval = signal_interval
        self._running = False

        self._preview_ttl_minutes = signal_preview_ttl_minutes
        self._producer_id = producer_id

        # Track last price paid (updated externally when auction settles)
        self._last_price_paid_usd: float = 0.0

        # Setup TSA project path for importing predictor
        self._tsa_project_path = tsa_project_path
        self._predictor = None

        if tsa_project_path:
            self._setup_tsa_predictor(tsa_project_path)

    def _setup_tsa_predictor(self, tsa_project_path: str) -> None:
        """Setup import path for TSA predictor."""
        path = Path(tsa_project_path)
        logger.info(
            "Setting up TSA predictor",
            path=tsa_project_path,
            path_exists=path.exists(),
            src_exists=(path / "src").exists() if path.exists() else False,
            predict_exists=(path / "src" / "predict.py").exists() if path.exists() else False,
        )
        if path.exists():
            sys.path.insert(0, str(path))
            try:
                # TSA project has get_prediction in src/predict.py
                # and prediction_to_signal in src/signal.py
                from src.predict import get_prediction
                from src.signal import prediction_to_signal
                self._predictor = {
                    "get_prediction": get_prediction,
                    "prediction_to_signal": prediction_to_signal,
                }
                logger.info("TSA predictor loaded successfully", path=tsa_project_path)
            except ImportError as e:
                logger.error(
                    "TSA predictor import failed",
                    path=tsa_project_path,
                    error=str(e),
                    error_type=type(e).__name__,
                )
        else:
            logger.error("TSA project path does not exist", path=tsa_project_path)

    @property
    def last_price_paid_usd(self) -> float:
        return self._last_price_paid_usd

    @last_price_paid_usd.setter
    def last_price_paid_usd(self, value: float) -> None:
        self._last_price_paid_usd = value

    def _calculate_bracket_probability(
        self,
        predicted_passengers: int,
        error_std_pct: float,
        bracket_lower: int | None,
        bracket_upper: int | None,
    ) -> float:
        """
        Calculate probability that actual passengers falls in bracket.

        Uses normal distribution with given std error.
        """
        import math
        from statistics import NormalDist

        if predicted_passengers <= 0:
            return 0.0

        # Standard deviation in passengers
        std = predicted_passengers * error_std_pct

        if std <= 0:
            # Point estimate - either in bracket or not
            if bracket_lower is None:
                return 1.0 if predicted_passengers < bracket_upper else 0.0
            elif bracket_upper is None:
                return 1.0 if predicted_passengers >= bracket_lower else 0.0
            else:
                return 1.0 if bracket_lower <= predicted_passengers < bracket_upper else 0.0

        # Use normal distribution CDF
        dist = NormalDist(mu=predicted_passengers, sigma=std)

        if bracket_lower is None:
            # "Below X" market
            return dist.cdf(bracket_upper)
        elif bracket_upper is None:
            # "Above X" market
            return 1 - dist.cdf(bracket_lower)
        else:
            # Range market
            return dist.cdf(bracket_upper) - dist.cdf(bracket_lower)

    def _get_tsa_prediction(self, target_date: Any) -> dict | None:
        """Get prediction from external TSA predictor."""
        if not self._predictor:
            logger.debug(
                "TSA predictor not available - was setup called?",
                tsa_project_path=self._tsa_project_path,
                predictor_is_none=self._predictor is None,
            )
            return None

        try:
            get_prediction = self._predictor["get_prediction"]
            prediction = get_prediction(target_date)
            return prediction
        except Exception as e:
            logger.warning(
                "TSA prediction failed",
                target_date=str(target_date),
                error=str(e),
            )
            return None

    def _build_producer_signal(
        self,
        event: "CachedTSAEvent",
        market: "CachedTSAMarket",
        model_prob: float,
        market_price: float,
        side: str,
        edge: float,
        prediction: dict,
    ) -> ProducerSignal:
        """Build a ProducerSignal from TSA event/market data."""
        metadata: TSAMetadata = {
            "target_date": event.target_date.isoformat(),
            "predicted_passengers": prediction.get("predicted_passengers", 0),
            "confidence_p5": prediction.get("confidence_p5", 0),
            "confidence_p95": prediction.get("confidence_p95", 0),
            "error_std_pct": prediction.get("error_std_pct", 0.035),
            "bracket_label": market.group_item_title or "",
            "bracket_lower": market.bracket_lower,
            "bracket_upper": market.bracket_upper,
        }

        exchange_info: PolymarketInfo = {
            "exchange": "polymarket",
            # Event level
            "event_id": event.event_id,
            "event_title": event.title,
            "resolution_source": event.resolution_source or "",
            # Market level
            "market_question": market.question,
            "market_group_item_title": market.group_item_title or "",
            # Trading info
            "token_id": market.yes_token_id if side == "yes" else market.no_token_id,
            "side": side,
            "market_price": market_price,
            "edge": edge,
            "price_timestamp": market.price_timestamp or datetime.now(UTC).isoformat(),
        }

        return ProducerSignal(
            signal_type="tsa",
            model_probability=model_prob if side == "yes" else (1 - model_prob),
            confidence=self._calculate_confidence(prediction),
            forecast_source="tsa_xgboost",
            forecast_time=datetime.now(UTC).isoformat(),
            metadata=metadata,
            exchanges=[exchange_info],
        )

    def _calculate_confidence(self, prediction: dict) -> float:
        """Calculate confidence based on prediction interval width."""
        p5 = prediction.get("confidence_p5", 0)
        p95 = prediction.get("confidence_p95", 0)
        predicted = prediction.get("predicted_passengers", 1)

        if predicted <= 0:
            return 0.5

        # Relative interval width
        interval_width = (p95 - p5) / predicted

        # Narrow interval = high confidence
        if interval_width <= 0.05:
            return 1.0
        elif interval_width >= 0.20:
            return 0.3
        else:
            return 1.0 - (interval_width - 0.05) / 0.15 * 0.7

    async def _generate_for_event(
        self, event: "CachedTSAEvent"
    ) -> list[ProducerSignal]:
        """Generate signals for a single TSA event."""
        signals = []

        # Get prediction from external TSA project
        prediction = self._get_tsa_prediction(event.target_date)
        if not prediction:
            logger.debug("No TSA prediction available", target_date=str(event.target_date))
            return signals

        predicted_passengers = prediction.get("predicted_passengers", 0)
        error_std_pct = prediction.get("error_std_pct", 0.035)

        if predicted_passengers <= 0:
            logger.warning("Invalid prediction", predicted_passengers=predicted_passengers)
            return signals

        # Process each unique market (dedupe by yes_token_id)
        seen_tokens = set()
        for token_id, market in event.markets.items():
            if market.yes_token_id in seen_tokens:
                continue
            seen_tokens.add(market.yes_token_id)

            # Skip invalid markets
            if market.bracket_lower is None and market.bracket_upper is None:
                continue

            # Get cached price
            yes_price = self._registry.get_price(market.yes_token_id)
            if yes_price is None:
                logger.debug("No price for market", token_id=market.yes_token_id)
                continue

            # Calculate model probability
            model_prob = self._calculate_bracket_probability(
                predicted_passengers=predicted_passengers,
                error_std_pct=error_std_pct,
                bracket_lower=market.bracket_lower,
                bracket_upper=market.bracket_upper,
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
                    prediction=prediction,
                )
                signals.append(signal)

            # Check for NO edge
            no_price = 1 - yes_price
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
                    prediction=prediction,
                )
                signals.append(signal)

        return signals

    def _persist_signal(self, signal: ProducerSignal) -> None:
        """Persist a ProducerSignal to the database."""
        if not self._engine:
            return

        exchange = signal.exchanges[0] if signal.exchanges else {}

        record = SignalRecord(
            strategy="tsa",
            market_id=exchange.get("event_id", ""),
            token_id=exchange.get("token_id", ""),
            model_probability=signal.model_probability,
            market_price=exchange.get("market_price", 0.0),
            edge=exchange.get("edge", 0.0),
            confidence=signal.confidence,
            decision="signal",
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
            logger.error("Failed to persist TSA signal", error=str(e))
        finally:
            session.close()

    async def _generate_once(self) -> list[ProducerSignal]:
        """Run one signal generation cycle."""
        all_signals = []

        events = self._registry.get_active_tsa_events()

        for event in events:
            signals = await self._generate_for_event(event)
            all_signals.extend(signals)

            for signal in signals:
                # Persist full signal to database for audit
                self._persist_signal(signal)

                # Broadcast via broadcaster
                if self._broadcaster:
                    await self._broadcaster.broadcast_producer_signal(signal)

        if all_signals:
            logger.info(
                "TSA signals generated",
                count=len(all_signals),
                events=len(events),
            )

        return all_signals

    async def run(self) -> None:
        """Run the TSA signal generator (runs every minute)."""
        self._running = True
        logger.info(
            "TSA signal generator starting",
            interval_seconds=self._signal_interval,
            edge_threshold=f"{self._edge_threshold:.0%}",
        )

        # Wait for price tracker to populate initial prices
        await asyncio.sleep(5)

        while self._running:
            await self._generate_once()
            jitter = random.uniform(0, self._signal_interval * 0.2)
            await asyncio.sleep(self._signal_interval + jitter)

    def stop(self) -> None:
        """Stop the TSA signal generator."""
        self._running = False
        logger.info("TSA signal generator stopping")
