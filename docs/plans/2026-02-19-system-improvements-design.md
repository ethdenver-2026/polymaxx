# System Improvements Design

**Date:** 2026-02-19
**Status:** Approved
**Scope:** Backtesting, trade resolution, dashboard, DRY cleanup, orchestration

---

## Overview

This document captures design decisions for improving the Polymarket weather trading bot with:
- Proper backtesting using historical NOAA GEFS ensemble data
- Automated trade resolution using Polymarket's official outcomes
- Real-time dashboard for position tracking and P&L
- DRY cleanup (async-first architecture)
- Run orchestration and city management

All designs are extensible for future esports and other strategies.

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        STRATEGY LAYER                           │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ WeatherStrategy │  │ EsportsStrategy │  │ [Future]        │ │
│  │ - Open-Meteo    │  │ - GRID API      │  │                 │ │
│  │ - Ensemble prob │  │ - Win prob model│  │                 │ │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘ │
│           └──────────────┬─────┴───────────────────┘           │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              BaseStrategy (ABC)                          │   │
│  │  async def generate_signals() -> list[Signal]            │   │
│  │  async def get_resolution_data(trade) -> dict            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SHARED SERVICES                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ DataCollector│  │ TradeExecutor│  │ Resolver     │          │
│  │ (forecasts,  │  │ (paper/live) │  │ (Gamma API)  │          │
│  │  markets)    │  │              │  │              │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ RiskManager  │  │ Backtester   │  │ Dashboard    │          │
│  │ (Kelly,      │  │ (GEFS +      │  │ (FastAPI +   │          │
│  │  limits)     │  │  Polymarket) │  │  HTMX)       │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATA LAYER (SQLAlchemy)                    │
│  Signal | Position | Trade | Forecast | Observation            │
│                    SQLite (WAL mode) / Postgres                 │
└─────────────────────────────────────────────────────────────────┘
```

### Key Extensibility Points

- `BaseStrategy` interface allows new strategies without changing core
- `strategy` column on all tables enables filtering by market type
- Dashboard views are strategy-agnostic with pluggable detail renderers
- Same TradeExecutor, RiskManager for all strategies

---

## 2. Backtesting

### Data Sources (Validated)

| Data | Source | Availability |
|------|--------|--------------|
| Historical ensemble forecasts | NOAA GEFS on AWS S3 | 2017-01-01 to present |
| Ensemble members | 31 (gec00 + gep01-gep30) | All available |
| Temperature variable | TMAX (daily high) | Byte-range accessible |
| Historical market prices | Polymarket Timeseries API | Per-market history |
| Actual observations | NOAA/Weather Underground | Years of history |

### S3 Data Structure

```
s3://noaa-gefs-pds/
  gefs.YYYYMMDD/
    00/ 06/ 12/ 18/           # Model runs (UTC)
      atmos/
        pgrb2ap5/
          gec00.t00z.pgrb2a.0p50.f024      # Control, 24hr forecast
          gep01.t00z.pgrb2a.0p50.f024      # Perturbation 1
          ...
          gep30.t00z.pgrb2a.0p50.f024      # Perturbation 30
          *.idx                             # Index files for byte-range
```

### Backtest Flow

```
FOR each historical date in range:
  1. Download GEFS ensemble TMAX for target date
     - Use byte-range requests (~200KB per member)
     - Extract temperature at city lat/lon
     - Cache locally to avoid re-download

  2. Fetch historical Polymarket prices
     - Timeseries API for each bucket
     - Sample at signal generation time

  3. Simulate signal generation
     - Same code path as live trading
     - Calculate ensemble probability distribution
     - Compare to market prices
     - Apply edge threshold

  4. Record theoretical trade

  5. Compare to actual outcome
     - Fetch from Gamma API (official resolution)
     - Or compute from NOAA observation

  6. Calculate P&L
```

### New Dependencies

```toml
[project.optional-dependencies]
backtest = [
    "cfgrib>=0.9.10",      # GRIB2 file reading
    "xarray>=2024.1.0",    # Array handling
    "eccodes>=1.6.0",      # GRIB codec (cfgrib dependency)
]
```

### Storage Estimate

- Raw GRIB for 1 year, 8 cities: ~70GB
- Extracted city-specific data: ~500MB
- Recommended: Extract and cache only needed data

---

## 3. Trade Resolution

### Flow

```
Hourly (or on-demand):

1. Query trades WHERE status = 'filled' AND target_date < today

2. For each unresolved trade:

   a. CHECK GAMMA API (source of truth)
      - Fetch event by slug
      - If market.closed AND prices[0] in ['0','1']:
        → Use official resolution (YES won or NO won)
      - If not resolved yet:
        → Skip, retry later

   b. FETCH NOAA OBSERVATION (for validation)
      - Query observations for target_date in city timezone
      - Find max temperature
      - Store in observations table

   c. VALIDATE
      - If NOAA temp doesn't match winning bucket:
        → Log warning (possible data discrepancy)

   d. UPDATE TRADE
      - won = (our bucket resolved YES)
      - pnl = position * (1/fill_price - 1) if won, else -position
      - actual_temp = NOAA observation
      - resolved_at = now()
      - resolution_source = 'gamma_api'
```

### Why Gamma API Over Computing Ourselves

- Gamma API shows official Polymarket resolution
- Matches exactly what we get paid out
- Avoids edge cases (rounding, timezone, data discrepancies)
- NOAA observation stored for validation and backtesting

### Timezone Handling

```python
# NYC calendar day in UTC
# Feb 17 00:00 EST = Feb 17 05:00 UTC
# Feb 17 23:59 EST = Feb 18 04:59 UTC

def get_utc_range_for_local_date(target_date: date, timezone: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone)
    local_start = datetime.combine(target_date, time.min, tzinfo=tz)
    local_end = datetime.combine(target_date, time.max, tzinfo=tz)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)
```

---

## 4. Data Model Changes

### New: Signal Table

```python
class Signal(Base):
    """Every signal generated, whether traded or not."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    strategy = Column(String(50), nullable=False, index=True)
    market_id = Column(String(100), nullable=False)
    token_id = Column(String(100), nullable=False)

    # Signal data
    model_probability = Column(Float, nullable=False)
    market_price = Column(Float, nullable=False)
    edge = Column(Float, nullable=False)
    confidence = Column(Float)

    # Decision
    decision = Column(String(20), nullable=False)  # 'trade', 'skip'
    skip_reason = Column(String(100))  # 'below_threshold', 'no_liquidity', etc.

    # Link to trade if acted on
    trade_id = Column(Integer, ForeignKey('trades.id'), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    metadata_json = Column(Text)  # Strategy-specific data as JSON
```

### New: Position Table

```python
class Position(Base):
    """Open position in a market."""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True)
    strategy = Column(String(50), nullable=False, index=True)
    market_id = Column(String(100), nullable=False)
    token_id = Column(String(100), nullable=False)

    # Position state
    shares = Column(Float, nullable=False)
    cost_basis = Column(Float, nullable=False)  # Avg cost per share
    total_cost = Column(Float, nullable=False)

    # Lifecycle
    status = Column(String(20), nullable=False)  # 'open', 'closed'
    opened_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime)
    realized_pnl = Column(Float)
```

### Updated: Trade Table

```python
class Trade(Base):
    __tablename__ = "trades"

    # Existing fields...

    # New fields
    strategy = Column(String(50), nullable=False, index=True)
    position_id = Column(Integer, ForeignKey('positions.id'))
    signal_id = Column(Integer, ForeignKey('signals.id'))
    actual_temp = Column(Float)  # For weather trades
    resolution_source = Column(String(50))  # 'gamma_api', 'manual'
```

---

## 5. Dashboard

### Stack

- **Backend:** FastAPI (Python)
- **Frontend:** HTMX + Jinja2 templates
- **Charts:** Chart.js via CDN
- **CSS:** Pico CSS or Tailwind CDN
- **Real-time:** 5-second polling via `hx-trigger="every 5s"`
- **Push (optional):** SSE for instant signal notifications

### Process Isolation

```
┌──────────────┐      ┌──────────────┐
│  Trading Bot │      │  Dashboard   │
│  (cron job)  │      │  (daemon)    │
│              │      │              │
│  Writes to   │      │  Reads from  │
│  SQLite      │◄────►│  SQLite      │
│  (WAL mode)  │      │  (read-only) │
└──────────────┘      └──────────────┘
```

Dashboard crash does not affect trading.

### Views

| Route | Purpose |
|-------|---------|
| `/` | Portfolio overview, recent signals, P&L summary |
| `/positions` | Open positions with live values (5s refresh) |
| `/trades` | Trade history, filterable by strategy/city/date |
| `/signals` | All signals including skipped, with reasons |
| `/analytics` | P&L charts, win rate by strategy/city |
| `/backtest` | Run and view backtests |
| `/settings` | View config, city list |

### Data Refresh Strategy

| Data | Source | Frequency |
|------|--------|-----------|
| Position prices | Polymarket CLOB API | Every 5s |
| Wallet balance | Polymarket API | Every 60s |
| Signals/Trades | SQLite | Every 5s |
| Portfolio totals | Computed | Every 5s |

### Filtering by Strategy

All views support `?strategy=weather` or `?strategy=esports` query param.

Summary tables show breakdown by strategy:

```
Strategy   │ Trades │ Win Rate │ Realized  │ Unrealized
───────────┼────────┼──────────┼───────────┼───────────
All        │ 127    │ 68%      │ +$234.50  │ +$45.20
Weather    │ 98     │ 71%      │ +$187.30  │ +$32.10
Esports    │ 29     │ 58%      │ +$47.20   │ +$13.10
```

---

## 6. DRY Cleanup

### Problem

Current code has sync/async duplication in every client (~50% repeated code).

### Solution

Async-only implementation. Single `asyncio.run()` at entry point.

### Before

```python
class OpenMeteoClient:
    async def get_ensemble_forecast(self, ...):
        # 40 lines

    def get_ensemble_forecast_sync(self, ...):
        # Same 40 lines, copy-pasted
```

### After

```python
class OpenMeteoClient:
    async def get_ensemble_forecast(self, ...):
        # 40 lines - single implementation

# Entry point
def main():
    asyncio.run(async_main())
```

### Files Affected

| File | Before | After |
|------|--------|-------|
| `clients/open_meteo.py` | 174 lines | ~90 lines |
| `clients/gamma.py` | 224 lines | ~120 lines |
| `strategy/weather.py` | 174 lines | ~100 lines |

---

## 7. Run Orchestration

### CLI Commands

```bash
# Full trading cycle (cron calls this)
python -m src.cli run --all-cities

# Specific cities
python -m src.cli run --cities nyc,chicago,miami

# Just collect data (no trading)
python -m src.cli collect

# Just resolve trades
python -m src.cli resolve

# Run backtest
python -m src.cli backtest --start 2025-01-01 --end 2026-02-01

# Scan for new cities
python -m src.cli scan-cities

# Start dashboard
python -m src.cli dashboard --port 8000
```

### Cron Setup

```cron
# Run trading cycle hourly
0 * * * * cd /path/to/bot && python -m src.cli run --all-cities >> /var/log/bot.log 2>&1
```

### Systemd Service for Dashboard

```ini
[Unit]
Description=Trading Bot Dashboard
After=network.target

[Service]
Type=simple
User=bot
WorkingDirectory=/path/to/bot
ExecStart=/path/to/venv/bin/python -m src.cli dashboard --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 8. City Management

### Add Seoul (Missing)

```python
CITIES["seoul"] = CityConfig(
    name="Seoul",
    slug="seoul",
    lat=37.5665,
    lon=126.9780,
    tz="Asia/Seoul",
    station="RKSS",
)
```

### City Scanner

```python
@cli.command()
def scan_cities():
    """Check for new weather markets on Polymarket."""
    potential = ["la", "denver", "phoenix", "tokyo", "paris", "sydney", ...]
    tomorrow = date.today() + timedelta(days=1)

    for slug in potential:
        event = gamma.fetch_weather_event(slug, tomorrow)
        if event and not event.closed:
            print(f"Found new city: {slug}")
```

### Verified Cities (Feb 2026)

| City | Slug | In Config |
|------|------|-----------|
| New York | nyc | Yes |
| Chicago | chicago | Yes |
| Miami | miami | Yes |
| London | london | Yes |
| Dallas | dallas | Yes |
| Seattle | seattle | Yes |
| Atlanta | atlanta | Yes |
| Seoul | seoul | **Add** |

---

## 9. Summary of Decisions

| Topic | Decision |
|-------|----------|
| Async/Sync | Async-only, sync wrapper at entry point |
| Dashboard stack | FastAPI + HTMX, not React |
| Dashboard refresh | 5-second polling, SSE optional |
| Dashboard process | Separate from trading bot |
| Database | SQLite (WAL mode), Postgres-ready via SQLAlchemy |
| Backtesting data | NOAA GEFS from AWS S3 (2017-present) |
| Resolution source | Gamma API official outcome |
| Validation data | NOAA observations |
| Run frequency | Hourly cron |
| City discovery | Curated list + scanner command |

---

## 10. Market Detection Strategy

### Current: Hourly Cron (Weather)

For weather markets, hourly polling is sufficient:
- Markets publish 24-48 hours before resolution
- Signal value decays slowly over hours
- Catches new markets within 1 hour of creation
- Simple, reliable, no daemon management

### Future: WebSocket (Esports)

Polymarket has WebSocket support (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) with `new_market` events. However:
- Requires `custom_feature_enabled: true` subscription
- Global subscription (all new markets) needs deeper research
- More valuable for esports where odds shift faster

**TODO**: Research Polymarket WebSocket global subscription for new market detection when implementing esports strategy.

| Strategy | Detection Method | Rationale |
|----------|------------------|-----------|
| Weather | Hourly cron | Sufficient lead time, simple |
| Esports | WebSocket daemon | Real-time odds matter more |

---

## 11. Non-Goals (Explicitly Excluded)

- Esports implementation (future phase)
- x402 payment protocol (future phase)
- Live trading execution (blocked on wallet setup)
- Multi-tenant signal publisher/consumer (future phase)
- Prometheus/Grafana operational monitoring (can add later)
- WebSocket market detection for weather (research for esports)
