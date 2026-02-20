# Synthetic Ensembles: Current State and Transition Plan

This document describes the current synthetic ensemble approach used for backtesting and the plan to transition to real collected ensembles.

## Background: Why Synthetic Ensembles?

Open-Meteo does **not** provide historical ensemble data. When backtesting, we need ensembles for past dates, but we can only get:

1. **Previous Runs API:** Deterministic forecasts from past dates (Jan 2024+)
2. **Historical Weather API:** ERA5 reanalysis data (NOT observations)

To backtest with ensembles, we must generate **synthetic ensembles** based on learned forecast error distributions.

## Current State: Hardcoded σ=2°F

The original `get_historical_forecast()` in `open_meteo.py` used a hardcoded approach:

```python
# UNRELIABLE - hardcoded spread
std_dev = 2.0  # Arbitrary "typical 24-hour forecast uncertainty"
member_highs = [daily_high + random.gauss(0, std_dev) for _ in range(31)]
```

### Problems with Hardcoded Approach

| Issue | Impact |
|-------|--------|
| σ=2°F is arbitrary | Not empirically derived from actual errors |
| Same spread for all lead times | 1-day vs 3-day forecasts have different uncertainty |
| Same spread for all cities | Coastal vs mountain terrain affects accuracy |
| No bias correction | GFS has systematic warm/cold biases per region |
| Doesn't capture underdispersion | GFS ensemble is already overconfident |

## Phase 1: Option D Improvement (Current)

Replaced hardcoded approach with **empirically-derived error distributions**.

### New Implementation

Location: `producer/signal_producer/backtest/error_analysis.py`

```python
# TEMPORARY: Using synthetic ensemble from error distributions
# TODO(after-2w-collection): Replace with ForecastCollector.load_forecast()

class ErrorAnalyzer:
    async def build_error_distribution(
        self,
        city: str,
        lat: float,
        lon: float,
        timezone: str,
        start_date: date,
        end_date: date,
        lead_days: int = 1,
    ) -> ForecastErrorStats:
        """Compare Previous Runs forecasts to NOAA observations."""

    def generate_synthetic_ensemble(
        self,
        deterministic_forecast: float,
        error_stats: ForecastErrorStats,
        n_members: int = 31,
    ) -> list[float]:
        """Generate ensemble using learned spread and bias correction."""
        # Apply bias correction
        bias_corrected = deterministic_forecast - error_stats.mean_error

        # Generate members with learned spread
        members = [
            bias_corrected + random.gauss(0, error_stats.std_error)
            for _ in range(n_members)
        ]
        return members
```

### Improvements Over Hardcoded

| Feature | Before | After |
|---------|--------|-------|
| Error distribution | Hardcoded σ=2°F | Learned from 13+ months of data |
| City-specific | No | Yes, separate stats per city |
| Lead-time specific | No | Yes, 1-day / 2-day / 3-day |
| Bias correction | No | Yes, mean error subtracted |
| Data source | None | NOAA CDO API + Previous Runs API |

### Limitations of Phase 1

1. **Still synthetic:** Generated from Gaussian distribution, not real ensemble spread
2. **Limited history:** Only ~13 months from Previous Runs API (Jan 2024+)
3. **Gaussian assumption:** Real errors may not be normally distributed
4. **Independent members:** Each member drawn independently, unlike correlated ensemble

## Phase 2: Real Ensemble Transition

**Trigger:** When `ForecastCollector` has accumulated ~14 days of real Open-Meteo ensemble forecasts.

### Data Collection (Already Running)

The crontab collector stores real ensemble forecasts daily:

```json
{
  "city": "nyc",
  "forecast_date": "2026-02-19",
  "target_date": "2026-02-20",
  "member_highs": [41.2, 42.1, 40.8, ...],  // Real 31 members
  "mean": 41.5,
  "std": 1.8,
  "min_temp": 39.2,
  "max_temp": 44.1
}
```

### Transition Implementation

Add hybrid approach to BacktestEngine:

```python
class BacktestEngine:
    def __init__(
        self,
        ...,
        use_collected_ensembles: bool = True,
        min_collection_days: int = 14,
    ):
        self.collected_forecasts = self._load_collected_forecasts()

    async def get_ensemble_for_backtest(
        self, city, forecast_date, target_date
    ):
        # Try real collected data first
        if self.use_collected_ensembles:
            stored = self.collector.load_forecast(
                city, target_date, forecast_date
            )
            if stored:
                return EnsembleForecast(
                    city=city,
                    target_date=target_date,
                    member_highs=stored.member_highs,
                    source="open_meteo_collected",
                )

        # Fall back to Option D synthetic
        return self._generate_synthetic_ensemble(
            city, forecast_date, target_date
        )
```

### CLI Status Command

```bash
$ python -m signal_producer backtest-status

City        Collected  Status
----------  ---------  ----------------------
nyc         18 days    ✅ Using real ensembles
chicago     12 days    ⚠️ Using synthetic (need 14)
miami       5 days     ⚠️ Using synthetic (need 14)
```

## Timeline

| Week | Action |
|------|--------|
| Now | Option D implemented (empirically-derived synthetic) |
| +1 week | Verify crontab collector running daily |
| +2 weeks | Enable real ensemble backtesting for cities with ≥14 days |
| +4 weeks | Most cities should have real data |
| +8 weeks | Consider deprecating synthetic fallback |

## Validation Before Trusting Collected Data

1. Compare collected ensemble spread vs synthetic spread
2. Check for data gaps (missed collection days)
3. Verify ensemble mean tracks deterministic forecast
4. Confirm 31 members present in each record

## Code Markers

All temporary compromises are marked in code:

```python
# TEMPORARY: Using synthetic ensemble from error distributions
# TODO(after-2w-collection): Replace with ForecastCollector.load_forecast()
# See: docs/SYNTHETIC_ENSEMBLES.md "Phase 2: Real Ensemble Transition"
```

## Temporary Compromises Summary

| Compromise | Current Workaround | Change When Data Available |
|------------|-------------------|---------------------------|
| No historical ensembles | Synthetic from error distributions | Use real collected ensembles |
| Error distributions from ~13 months | Previous Runs API (Jan 2024+) | Can validate against real spread |
| Gaussian assumption | `random.gauss(0, std_error)` | Real ensembles have actual spread |
| No multi-day tracking | Each day's ensemble independent | Real data tracks forecast evolution |
| 12hr price granularity | Approximate CLOB prices | Collect live prices at signal time |

## File Locations

- Error analysis: `producer/signal_producer/backtest/error_analysis.py`
- NOAA client: `producer/signal_producer/clients/noaa_cdo.py`
- Price history: `producer/signal_producer/backtest/price_history.py`
- Prediction tracking: `producer/signal_producer/services/prediction_tracker.py`

## Data Sources

| Source | API | Data Range | Purpose |
|--------|-----|------------|---------|
| Previous Runs | Open-Meteo | Jan 2024+ | Past deterministic forecasts |
| Actual temps | NOAA CDO | 1940+ | Ground truth observations |
| Live ensembles | Open-Meteo Ensemble | Current | Real-time 31-member forecasts |
| Market prices | CLOB prices-history | Varies | Historical Polymarket prices |

## Credentials Required

| Credential | Purpose | How to Get |
|------------|---------|------------|
| NOAA_CDO_TOKEN | Historical observations | https://www.ncei.noaa.gov/cdo-web/token (free) |
