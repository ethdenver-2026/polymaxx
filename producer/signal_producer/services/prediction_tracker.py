"""Prediction tracking service for calibration analysis."""

from datetime import date, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..strategies.weather.markets import WeatherMarket, WeatherEvent
    from ..strategies.weather.open_meteo import EnsembleForecast


logger = structlog.get_logger()


class PredictionTracker:
    """Track market predictions and their outcomes for calibration analysis.

    Records ALL market probabilities for each event, not just traded ones.
    This enables calibration analysis to detect model bias and improve forecasts.
    """

    def record_predictions(
        self,
        ensemble: "EnsembleForecast",
        event: "WeatherEvent",
        session: "Session",
    ) -> int:
        """
        Record predictions for ALL markets in an event.

        Args:
            ensemble: The ensemble forecast used for prediction
            event: Weather event with temperature markets
            session: Database session

        Returns:
            Number of predictions recorded
        """
        from ..models.models import PredictionRecord
        from ..strategies.weather.signals import calculate_market_probability

        recorded = 0

        for weather_market in event.markets:
            # Calculate model probability for this market
            model_prob = calculate_market_probability(ensemble, weather_market)

            # Check if prediction already exists (avoid duplicates)
            existing = session.query(PredictionRecord).filter(
                PredictionRecord.city == ensemble.city,
                PredictionRecord.target_date == ensemble.target_date,
                PredictionRecord.bucket_question == weather_market.question,
                PredictionRecord.forecast_date == date.today(),
            ).first()

            if existing:
                continue

            prediction = PredictionRecord(
                forecast_date=date.today(),
                target_date=ensemble.target_date,
                city=ensemble.city,
                bucket_question=weather_market.question,
                bucket_low=weather_market.low_temp,
                bucket_high=weather_market.high_temp,
                raw_ensemble_prob=model_prob,
                ensemble_mean=ensemble.mean,
                ensemble_spread=ensemble.max - ensemble.min,
                market_price=weather_market.yes_price,
            )

            session.add(prediction)
            recorded += 1

        if recorded > 0:
            session.commit()
            logger.debug(
                "Recorded predictions",
                city=ensemble.city,
                target_date=str(ensemble.target_date),
                count=recorded,
            )

        return recorded

    def resolve_predictions(
        self,
        city: str,
        target_date: date,
        actual_temp: float,
        session: "Session",
    ) -> int:
        """
        Mark predictions as resolved with actual outcome.

        Args:
            city: City slug (e.g., "nyc")
            target_date: The date that was forecasted
            actual_temp: Observed high temperature
            session: Database session

        Returns:
            Number of predictions resolved
        """
        from ..models.models import PredictionRecord

        predictions = session.query(PredictionRecord).filter(
            PredictionRecord.city == city,
            PredictionRecord.target_date == target_date,
            PredictionRecord.outcome.is_(None),  # Not yet resolved
        ).all()

        resolved = 0

        for pred in predictions:
            # Determine if actual temp fell in this bucket
            if pred.bucket_low is None:
                # "X or below" bucket
                outcome = actual_temp < pred.bucket_high
            elif pred.bucket_high is None:
                # "X or above" bucket
                outcome = actual_temp >= pred.bucket_low
            else:
                # Range bucket [low, high)
                outcome = pred.bucket_low <= actual_temp < pred.bucket_high

            pred.actual_temp = actual_temp
            pred.outcome = outcome
            pred.resolved_at = datetime.utcnow()
            resolved += 1

        if resolved > 0:
            session.commit()
            logger.info(
                "Resolved predictions",
                city=city,
                target_date=str(target_date),
                actual_temp=f"{actual_temp:.1f}°F",
                count=resolved,
            )

        return resolved

    def get_calibration_data(
        self,
        session: "Session",
        city: str | None = None,
        min_date: date | None = None,
    ) -> list[tuple[float, bool]]:
        """
        Return (model_prob, outcome) pairs for calibration analysis.

        Args:
            session: Database session
            city: Optional city filter
            min_date: Optional minimum target date filter

        Returns:
            List of (probability, outcome) tuples for resolved predictions
        """
        from ..models.models import PredictionRecord

        query = session.query(
            PredictionRecord.raw_ensemble_prob,
            PredictionRecord.outcome,
        ).filter(
            PredictionRecord.outcome.isnot(None),  # Only resolved
        )

        if city:
            query = query.filter(PredictionRecord.city == city)

        if min_date:
            query = query.filter(PredictionRecord.target_date >= min_date)

        return [(prob, bool(outcome)) for prob, outcome in query.all()]

    def get_calibration_summary(
        self,
        session: "Session",
        city: str | None = None,
        n_bins: int = 10,
    ) -> dict:
        """
        Get calibration statistics binned by probability.

        Args:
            session: Database session
            city: Optional city filter
            n_bins: Number of probability bins

        Returns:
            Dict with bins, counts, and observed frequencies
        """
        data = self.get_calibration_data(session, city=city)

        if not data:
            return {"bins": [], "counts": [], "observed": [], "total": 0}

        # Create bins
        bins = [i / n_bins for i in range(n_bins + 1)]
        bin_counts = [0] * n_bins
        bin_hits = [0] * n_bins

        for prob, outcome in data:
            # Find which bin this probability falls into
            bin_idx = min(int(prob * n_bins), n_bins - 1)
            bin_counts[bin_idx] += 1
            if outcome:
                bin_hits[bin_idx] += 1

        # Calculate observed frequency per bin
        observed = []
        for count, hits in zip(bin_counts, bin_hits):
            if count > 0:
                observed.append(hits / count)
            else:
                observed.append(None)

        return {
            "bins": bins,
            "counts": bin_counts,
            "observed": observed,
            "total": len(data),
        }
