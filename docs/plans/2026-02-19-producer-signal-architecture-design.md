# Producer Signal Architecture Design

**Date:** 2026-02-19
**Status:** Approved

## Overview

Redesign the producer to support real-time event discovery, live price tracking via CLOB websocket, and a typed signal structure that supports multiple exchanges and signal types.

## Goals

1. Real-time event discovery (poll Gamma API every 10s)
2. Live price tracking via CLOB websocket
3. Typed signal structure supporting multiple exchanges (Polymarket, Kalshi) and signal types (weather, esports)
4. Signal both YES and NO opportunities
5. Persist state to SQLite for restart recovery

## Non-Goals

- Position sizing (consumer's responsibility)
- Expected value calculation (consumer's responsibility)
- Kalshi implementation (design for it, don't build yet)
- Esports signals (design for it, don't build yet)

---

## Signal Structure

### Typed Metadata (per signal_type)

```python
from typing import Literal, TypedDict

class WeatherMetadata(TypedDict):
    city: str
    target_date: str                 # "2026-02-20"
    ensemble_mean: float
    ensemble_std: float
    members_in_range: int            # e.g., 12 of 31

class EsportsMetadata(TypedDict):
    match_id: str
    team_a: str
    team_b: str
    target_date: str
```

### Exchange-Specific Market Info

```python
class PolymarketInfo(TypedDict):
    exchange: Literal["polymarket"]
    event_id: str
    token_id: str
    side: Literal["yes", "no"]
    market_description: str
    resolution_source: str           # wunderground URL
    market_price: float              # 0-1
    edge: float                      # Calculated per-exchange
    price_timestamp: str

class KalshiInfo(TypedDict):
    exchange: Literal["kalshi"]
    event_ticker: str
    ticker: str
    side: Literal["yes", "no"]
    rules_primary: str
    yes_ask_dollars: float
    no_ask_dollars: float
    edge: float
    price_timestamp: str
```

### Canonical Producer Signal

```python
@dataclass
class ProducerSignal:
    # Type discriminator
    signal_type: Literal["weather", "esports"]

    # Core prediction (exchange-agnostic)
    model_probability: float
    confidence: float

    # Source info
    forecast_source: Literal["open_meteo", "noaa"]
    forecast_time: str               # ISO timestamp

    # Typed metadata (based on signal_type)
    metadata: WeatherMetadata | EsportsMetadata

    # Exchange-specific (one signal can map to multiple exchanges)
    exchanges: list[PolymarketInfo | KalshiInfo]
```

### Key Changes from Current Signal

| Field | Old | New |
|-------|-----|-----|
| `position_size_usd` | In signal | Removed (consumer's job) |
| `expected_value` | In signal | Removed (consumer's job) |
| `edge` | Top-level | Per-exchange (prices differ) |
| `market_price` | Top-level | Per-exchange |
| `metadata` | `dict \| None` | Typed per `signal_type` |
| `token_id`, `market_id` | Top-level | Nested in `exchanges` |

---

## Architecture

Single process with multiple async tasks and shared in-memory state backed by SQLite.

```
┌─────────────────────────────────────────────────────────────────┐
│ PRODUCER (single process, async tasks)                          │
│                                                                  │
│  ┌────────────────┐                                             │
│  │ Event Discovery│  Gamma API poll (10s)                       │
│  │ Task           │  → Discover weather events                  │
│  │                │  → Register markets in MarketRegistry       │
│  │                │  → Trigger CLOB subscription for new tokens │
│  └───────┬────────┘                                             │
│          │                                                       │
│          ▼                                                       │
│  ┌────────────────┐                                             │
│  │ MarketRegistry │  SQLite-backed, in-memory cache             │
│  │                │  - Known events + markets                   │
│  │                │  - Live prices (from CLOB WS)               │
│  │                │  - Latest forecasts                         │
│  └───────┬────────┘                                             │
│          │                                                       │
│          ▼                                                       │
│  ┌────────────────┐                                             │
│  │ Price Tracker  │  CLOB websocket (persistent)                │
│  │ Task           │  → Subscribe to token IDs                   │
│  │                │  → Update price cache on price_change       │
│  │                │  → Mark resolved on market_resolved         │
│  └───────┬────────┘                                             │
│          │                                                       │
│          ▼                                                       │
│  ┌────────────────┐                                             │
│  │ Signal         │  Open-Meteo poll (6h)                       │
│  │ Generator Task │  → Fetch ensemble forecasts                 │
│  │                │  → Calculate model_probability per market   │
│  │                │  → Generate YES/NO signals where edge exists│
│  │                │  → Publish to WebSocket server              │
│  └───────┬────────┘                                             │
│          │                                                       │
│          ▼                                                       │
│  ┌────────────────┐                                             │
│  │ WebSocket      │  Consumers connect here (already exists)    │
│  │ Server         │  → Broadcast signals                        │
│  └────────────────┘                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Components

### MarketRegistry

SQLite-backed with in-memory cache for fast lookups.

```python
class MarketRegistry:
    """Central store for tracked events, markets, and prices."""

    def __init__(self, engine: Engine):
        self._engine = engine
        self._cache = self._load_from_db()

    def register_event(self, event: WeatherEvent) -> list[str]:
        """Register event, persist to DB, return new token_ids to subscribe."""

    def update_price(self, token_id: str, price: float, timestamp: str) -> None:
        """Update cached price (in-memory only, prices are ephemeral)."""

    def update_forecast(self, event_id: str, forecast: EnsembleForecast) -> None:
        """Update forecast, persist to DB, mark for signal generation."""

    def mark_resolved(self, event_id: str, resolution: str) -> list[str]:
        """Mark event resolved (soft delete), return token_ids to unsubscribe."""

    def get_active_events(self) -> list[TrackedEvent]:
        """Return only status='active' events."""

    def get_active_token_ids(self) -> list[str]:
        """Return all token_ids for active events (used on startup to resubscribe)."""
```

### TrackedEvent Status

```python
class TrackedEvent:
    event_id: str
    status: Literal["active", "resolved", "expired"]  # Never delete, just mark
    resolved_at: datetime | None
```

| Status | Meaning |
|--------|---------|
| `active` | Currently tracking, subscribed to CLOB |
| `resolved` | Market resolved normally |
| `expired` | Cleaned up via fallback (target_date passed) |

### Persistence Strategy

| Data | Storage | Why |
|------|---------|-----|
| Events + markets | SQLite | Survive restart, know what to resubscribe |
| Forecasts | SQLite | Don't re-fetch if recent enough |
| Prices | In-memory only | Stale on restart, CLOB WS will repopulate |

---

## Data Flow

### Startup

1. Load TrackedEvents from SQLite (status='active')
2. For each event → check Gamma API
   - If closed → mark_resolved(), skip
   - If active → collect token_ids
3. Subscribe to CLOB websocket with all active token_ids
4. Start async tasks

### Event Discovery (every 10s)

1. Poll Gamma API for weather events (next 4 days, all cities)
2. For each event:
   - Already tracked? → skip
   - New? → register_event() → returns new token_ids
3. Subscribe new token_ids to CLOB websocket

### Price Tracking (persistent websocket)

CLOB websocket events:
- `price_change` → registry.update_price(token_id, price, timestamp)
- `market_resolved` → registry.mark_resolved(event_id) → unsubscribe

### Forecast Update (every 6h)

1. For each active event:
   - Fetch ensemble forecast from Open-Meteo
   - registry.update_forecast(event_id, forecast)
2. Trigger signal generation

### Signal Generation (after forecast update)

For each event with updated forecast:
  For each market in event:
    1. model_prob = count_in_range / 31
    2. Get cached price from registry
    3. If model_prob > price → signal YES
       If model_prob < price → signal NO
    4. Build ProducerSignal with typed metadata + exchange info
    5. Broadcast via websocket server

### Event Cleanup

| Trigger | Action |
|---------|--------|
| Startup | Check all tracked events against Gamma API, mark resolved ones |
| CLOB `market_resolved` | Immediate mark_resolved() + unsubscribe |
| Daily task | Sweep events where `target_date < today - 1` as safety net |

---

## Error Handling

| Severity | Scenario | Handling |
|----------|----------|----------|
| **CRITICAL** | Open-Meteo down | Retry 3x with backoff → if still failing, log CRITICAL + skip signal generation |
| WARN | Gamma API down | Retry with backoff, continue with cached events |
| WARN | CLOB websocket disconnects | Auto-reconnect, resubscribe all active token_ids |
| WARN | Price cache miss | Skip signal for that market, log warning |
| INFO | Broadcast fails | Log error, don't block other signals |
| WARN | SQLite write fails | Log error, continue with in-memory state |

### Critical Logging for Open-Meteo Failure

```python
logger.critical(
    "FORECAST_FETCH_FAILED",
    event_id=event_id,
    city=city,
    target_date=target_date,
    retry_count=3,
    error=str(exc),
    impact="Signal generation skipped - potential missed opportunity",
)
```

### CLOB Websocket Reconnection

```python
async def maintain_connection():
    while True:
        try:
            async with connect_clob_websocket() as ws:
                token_ids = registry.get_active_token_ids()
                await subscribe(ws, token_ids)
                await handle_messages(ws)
        except ConnectionClosed:
            logger.warning("CLOB websocket disconnected, reconnecting...")
            await asyncio.sleep(5)  # backoff
```

---

## Testing

| Layer | What to Test |
|-------|--------------|
| Unit | `MarketRegistry` CRUD, price cache, status transitions |
| Unit | Signal generation logic (YES/NO signals, edge calculation) |
| Unit | Typed metadata serialization |
| Integration | Gamma API polling → registry updates |
| Integration | CLOB websocket → price cache updates |
| Integration | Forecast update → signal broadcast |
| E2E | Full flow: discovery → tracking → forecast → signal → broadcast |

### Mocking Strategy

- Mock Gamma API responses (use recorded fixtures)
- Mock CLOB websocket with fake price events
- Mock Open-Meteo with ensemble fixtures
- Test websocket server with test client

### Key Test Cases

1. New event discovered → tokens subscribed
2. Price update → cache updated
3. Forecast update → correct YES/NO signals generated
4. Market resolved → status marked, unsubscribed
5. Restart recovery → resubscribes active events only

---

## Naming Changes

| Old | New |
|-----|-----|
| `WeatherBucket` | `WeatherMarket` |
| `bucket` (variable names) | `market` |

---

## Out of Scope (Future)

- Kalshi exchange integration (designed for, not implemented)
- Esports signal type (designed for, not implemented)
- Alerting for CRITICAL errors (webhook, PagerDuty)
- NOAA as forecast source (enum exists, not implemented)
