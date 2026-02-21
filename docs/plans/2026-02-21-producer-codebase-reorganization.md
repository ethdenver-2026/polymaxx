# Producer Codebase Reorganization Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clean up producer codebase structure by removing unused files, consolidating duplicates, unifying configuration, and reorganizing directories for clarity.

**Architecture:** Reorganize `producer/signal_producer/` with clearer naming, move shared wire protocol types to `shared/`, and consolidate configuration. No functional changes - pure refactoring.

**Tech Stack:** Python, dataclasses, Pydantic, SQLAlchemy

---

## Verification Strategy

Each task has specific verification commands. **Do not commit until all checks pass.**

**If any verification fails:** `git checkout .` to revert, then investigate.

---

### Task 1 Verification: signal_messages.py Deleted

```bash
cd producer

# 1. File should not exist
ls signal_producer/signals/types/signal_messages.py 2>&1 | grep -q "No such file" && echo "PASS: File deleted" || echo "FAIL: File still exists"

# 2. Types still importable (they come from producer_signal_preview.py)
uv run python -c "from signal_producer.signals.types import SignalPreviewMessage, ProducerSignalPreview; print('PASS: Types import OK')"

# 3. Quick test of signal types
uv run pytest tests/test_signal_types.py -v
```

---

### Task 2 Verification: Shared Types (MAJOR CORNERSTONE)

```bash
# FROM REPO ROOT (not producer/)
cd /Users/adoll/projects/prediction-market-known-outcomes

# 1. Shared package imports work
uv run python -c "
from signal_schema import ProducerSignal, WeatherMetadata, PolymarketInfo
from signal_schema import AuctionBidMessage, AuctionBidRejected, SignalPreviewMessage
print('PASS: All shared types import')
"

# 2. Producer can import from shared (via re-export)
cd producer && uv run python -c "
from signal_producer.signals.types import ProducerSignal, WeatherMetadata
print('PASS: Producer re-exports work')
"

# 3. Consumer can import from shared
cd ../consumer && uv run python -c "
from signal_schema import ProducerSignal
print('PASS: Consumer imports shared types')
"

# 4. FULL TEST SUITES - both producer and consumer
cd ../producer && uv run pytest tests/ -v --tb=short
cd ../consumer && uv run pytest tests/ -v --tb=short

# 5. Type checking
cd ../producer && uv run mypy signal_producer --ignore-missing-imports
```

---

### Task 3 Verification: websocket.py Deleted

```bash
cd producer

# 1. Old file should not exist
ls signal_producer/publishing/websocket.py 2>&1 | grep -q "No such file" && echo "PASS: File deleted" || echo "FAIL: File still exists"

# 2. Imports work via new path
uv run python -c "
from signal_producer.publishing.websocket_signal_broadcaster import SignalBroadcaster, broadcaster
from signal_producer.publishing import broadcaster
print('PASS: Broadcaster imports work')
"

# 3. Test broadcaster functionality
uv run pytest tests/test_websocket_broadcaster.py tests/test_ws_server.py -v
```

---

### Task 4 Verification: DEFAULT_CITIES Unified

```bash
cd producer

# 1. Only one DEFAULT_CITIES should exist (in config.py)
grep -rn "DEFAULT_CITIES\s*=" signal_producer/ | wc -l | xargs -I {} bash -c '[ {} -eq 1 ] && echo "PASS: Single definition" || echo "FAIL: Multiple definitions"'

# 2. event_discovery imports from config
uv run python -c "
from signal_producer.tasks.event_discovery import EventDiscoveryTask
from signal_producer.config import DEFAULT_CITIES
print(f'PASS: DEFAULT_CITIES = {DEFAULT_CITIES}')
"

# 3. Test event discovery
uv run pytest tests/test_event_discovery.py -v
```

---

### Task 5 Verification: Data Module Reorganization (MAJOR CORNERSTONE)

```bash
cd producer

# 1. Old directories should not exist
ls -d signal_producer/registry 2>&1 | grep -q "No such file" && echo "PASS: registry/ deleted" || echo "FAIL: registry/ still exists"
ls -d signal_producer/tracker 2>&1 | grep -q "No such file" && echo "PASS: tracker/ deleted" || echo "FAIL: tracker/ still exists"

# 2. New data/ module works
uv run python -c "
from signal_producer.data import MarketRegistry, CachedEvent, CachedMarket
from signal_producer.data import PriceTracker, CLOB_WS_URL
from signal_producer.data import ForecastCollector, StoredForecast
print('PASS: All data module imports work')
"

# 3. Old import paths should fail
uv run python -c "from signal_producer.registry import MarketRegistry" 2>&1 | grep -q "ModuleNotFoundError" && echo "PASS: Old path fails" || echo "FAIL: Old path still works"

# 4. FULL TEST SUITE
uv run pytest tests/ -v --tb=short

# 5. Specific tests for moved modules
uv run pytest tests/test_market_registry.py tests/test_price_tracker.py tests/test_models.py -v
```

---

### Task 6 Verification: Clients Reorganized (MAJOR CORNERSTONE)

```bash
cd producer

# 1. New submodules exist
uv run python -c "
from signal_producer.clients.polymarket import GammaClient, WeatherEvent, WeatherMarket
from signal_producer.clients.weather import OpenMeteoClient, EnsembleForecast, NOAACDOClient
from signal_producer.clients import GammaClient, OpenMeteoClient  # re-exports
print('PASS: All client imports work')
"

# 2. FULL TEST SUITE
uv run pytest tests/ -v --tb=short

# 3. Specific client tests
uv run pytest tests/test_gamma_api.py tests/test_open_meteo.py -v -k "not live"
```

---

### Task 7 Verification: auction_smoke.py Deleted

```bash
cd producer

# 1. Files should not exist
ls signal_producer/auction_smoke.py 2>&1 | grep -q "No such file" && echo "PASS: auction_smoke.py deleted" || echo "FAIL"
ls tests/test_auction_smoke.py 2>&1 | grep -q "No such file" && echo "PASS: test_auction_smoke.py deleted" || echo "FAIL"

# 2. Entry point should be removed (command should fail)
uv run signal-auction-smoke --help 2>&1 | grep -q "No such command" && echo "PASS: Entry point removed" || echo "FAIL: Command still exists"

# 3. Other tests still pass
uv run pytest tests/ -v --tb=short
```

---

### Task 8 Verification: Final (FULL VERIFICATION)

```bash
cd /Users/adoll/projects/prediction-market-known-outcomes

# 1. Producer full test suite
cd producer && uv run pytest tests/ -v

# 2. Producer type checking
uv run mypy signal_producer --ignore-missing-imports

# 3. Consumer full test suite
cd ../consumer && uv run pytest tests/ -v

# 4. CLI works
cd ../producer && uv run signal-producer --help

# 5. Import smoke test - all major modules
uv run python -c "
from signal_producer.clients.polymarket import GammaClient
from signal_producer.clients.weather import OpenMeteoClient
from signal_producer.data import MarketRegistry, PriceTracker, ForecastCollector
from signal_producer.publishing import broadcaster
from signal_producer.tasks import ProducerOrchestrator
from signal_producer.signals.types import ProducerSignal
print('PASS: All major imports work')
"

# 6. No circular imports (this would fail on import)
uv run python -c "import signal_producer; print('PASS: No circular imports')"
```

---

## Summary of Changes

| Current | Action | New Location |
|---------|--------|--------------|
| `signals/types/signal_messages.py` | DELETE | - |
| `signals/types/producer_signal.py` | MOVE | `shared/signal_schema/types/producer_signal.py` |
| `signals/types/producer_signal_preview.py` | MOVE | `shared/signal_schema/types/auction_messages.py` |
| `publishing/websocket.py` | DELETE | - |
| `tasks/event_discovery.py` DEFAULT_CITIES | DELETE | Use `config.py` |
| `models/collector.py` | MOVE+RENAME | `data/ensemble_collector.py` |
| `registry/` | RENAME | `data/` |
| `registry/market_registry.py` | RENAME | `data/polymarket_registry.py` |
| `tracker/price_tracker.py` | MOVE+RENAME | `data/polymarket_price_tracker.py` |
| `tracker/` | DELETE (empty) | - |
| `clients/` | REORGANIZE | `clients/polymarket/`, `clients/weather/` |
| `shared/signal_schema/signal.py` | DELETE (unused) | - |
| `auction_smoke.py` | DELETE | (one-shot artifact, unused) |
| `tests/test_auction_smoke.py` | DELETE | (tests deleted file) |

---

## Task 1: Delete Unused signal_messages.py

**Files:**
- Delete: `producer/signal_producer/signals/types/signal_messages.py`

**Step 1: Verify no imports exist**

Run: `grep -rn "signal_messages" producer/`
Expected: No matches (already confirmed in research)

**Step 2: Delete the file**

```bash
rm producer/signal_producer/signals/types/signal_messages.py
```

**Step 3: Commit**

```bash
git add -A && git commit -m "chore: remove unused signal_messages.py

SignalPreviewMessage is defined in producer_signal_preview.py.
The signal_messages.py version was never imported anywhere."
```

---

## Task 2: Move Producer Signal Types to Shared

**Files:**
- Move: `producer/signal_producer/signals/types/producer_signal.py` → `shared/signal_schema/types/producer_signal.py`
- Move: `producer/signal_producer/signals/types/producer_signal_preview.py` → `shared/signal_schema/types/auction_messages.py`
- Delete: `shared/signal_schema/signal.py` (unused legacy)
- Update: `shared/signal_schema/__init__.py`
- Update: `producer/signal_producer/signals/types/__init__.py`
- Update: `producer/signal_producer/signals/__init__.py`
- Update: All importing files in producer/
- Update: `consumer/signal_consumer/signal_pipeline.py` (remove duplicate)

**Step 1: Create shared/signal_schema/types/ directory**

```bash
mkdir -p shared/signal_schema/types
```

**Step 2: Move producer_signal.py to shared**

```bash
cp producer/signal_producer/signals/types/producer_signal.py shared/signal_schema/types/producer_signal.py
```

**Step 3: Move producer_signal_preview.py to shared as auction_messages.py**

```bash
cp producer/signal_producer/signals/types/producer_signal_preview.py shared/signal_schema/types/auction_messages.py
```

**Step 4: Create shared/signal_schema/types/__init__.py**

```python
"""Shared signal types for producer-consumer wire protocol."""

from .producer_signal import (
    ForecastSource,
    PolymarketInfo,
    ProducerSignal,
    SignalType,
    WeatherMetadata,
)
from .auction_messages import (
    AuctionBidMessage,
    AuctionBidRejected,
    PreviewPolymarketInfo,
    ProducerSignalPreview,
    SignalPreviewMessage,
)

__all__ = [
    "AuctionBidMessage",
    "AuctionBidRejected",
    "ForecastSource",
    "PolymarketInfo",
    "PreviewPolymarketInfo",
    "ProducerSignal",
    "ProducerSignalPreview",
    "SignalPreviewMessage",
    "SignalType",
    "WeatherMetadata",
]
```

**Step 5: Update shared/signal_schema/__init__.py**

```python
"""Shared signal schema for producer-consumer communication."""

from .types import (
    AuctionBidMessage,
    AuctionBidRejected,
    ForecastSource,
    PolymarketInfo,
    PreviewPolymarketInfo,
    ProducerSignal,
    ProducerSignalPreview,
    SignalPreviewMessage,
    SignalType,
    WeatherMetadata,
)

__all__ = [
    "AuctionBidMessage",
    "AuctionBidRejected",
    "ForecastSource",
    "PolymarketInfo",
    "PreviewPolymarketInfo",
    "ProducerSignal",
    "ProducerSignalPreview",
    "SignalPreviewMessage",
    "SignalType",
    "WeatherMetadata",
]
```

**Step 6: Delete unused shared/signal_schema/signal.py**

```bash
rm shared/signal_schema/signal.py
```

**Step 7: Update producer imports**

Update `producer/signal_producer/signals/types/__init__.py`:
```python
"""Signal type contracts - re-exported from shared schema."""

from signal_schema import (
    AuctionBidMessage,
    AuctionBidRejected,
    ForecastSource,
    PolymarketInfo,
    PreviewPolymarketInfo,
    ProducerSignal,
    ProducerSignalPreview,
    SignalPreviewMessage,
    SignalType,
    WeatherMetadata,
)

__all__ = [
    "AuctionBidMessage",
    "AuctionBidRejected",
    "ForecastSource",
    "PolymarketInfo",
    "PreviewPolymarketInfo",
    "ProducerSignal",
    "ProducerSignalPreview",
    "SignalPreviewMessage",
    "SignalType",
    "WeatherMetadata",
]
```

**Step 8: Delete old producer signal type files**

```bash
rm producer/signal_producer/signals/types/producer_signal.py
rm producer/signal_producer/signals/types/producer_signal_preview.py
```

**Step 9: Update consumer to use shared types**

In `consumer/signal_consumer/signal_pipeline.py`, replace local `CanonicalProducerSignal` and `ProducerSignalExchange` with imports from shared:

```python
from signal_schema import ProducerSignal, PolymarketInfo
```

Remove the duplicate class definitions (lines ~15-39).

**Step 10: Run tests to verify**

```bash
cd producer && uv run pytest tests/ -v
cd ../consumer && uv run pytest tests/ -v
```

**Step 11: Commit**

```bash
git add -A && git commit -m "refactor: move signal types to shared/signal_schema

- Move ProducerSignal, WeatherMetadata, PolymarketInfo to shared
- Move AuctionBidMessage, AuctionBidRejected to shared
- Delete unused Signal class from shared
- Update producer to re-export from shared
- Update consumer to import from shared (removes duplication)"
```

---

## Task 3: Delete websocket.py Compatibility Module

**Files:**
- Delete: `producer/signal_producer/publishing/websocket.py`
- Update: `producer/signal_producer/publishing/__init__.py`
- Update: All files importing from `publishing.websocket`

**Step 1: Find all imports of publishing.websocket**

Files to update:
- `producer/signal_producer/tasks/orchestrator.py` (line 19)
- `producer/signal_producer/tasks/signal_generator.py` (line 31)
- `producer/tests/test_websocket_broadcaster.py` (line 8)
- `producer/tests/test_integration_signal_flow.py` (line 18)

**Step 2: Update orchestrator.py**

Change line 19 from:
```python
from ..publishing.websocket import SignalBroadcaster
```
To:
```python
from ..publishing.websocket_signal_broadcaster import SignalBroadcaster
```

**Step 3: Update signal_generator.py**

Change line 31 from:
```python
from ..publishing.websocket import SignalBroadcaster
```
To:
```python
from ..publishing.websocket_signal_broadcaster import SignalBroadcaster
```

**Step 4: Update test_websocket_broadcaster.py**

Change line 8 from:
```python
from signal_producer.publishing.websocket import SignalBroadcaster
```
To:
```python
from signal_producer.publishing.websocket_signal_broadcaster import SignalBroadcaster
```

**Step 5: Update test_integration_signal_flow.py**

Change line 18 from:
```python
from signal_producer.publishing.websocket import SignalBroadcaster
```
To:
```python
from signal_producer.publishing.websocket_signal_broadcaster import SignalBroadcaster
```

**Step 6: Update publishing/__init__.py**

```python
"""Publishers for outbound signal delivery."""

from .websocket_signal_broadcaster import broadcaster, SignalBroadcaster

__all__ = ["broadcaster", "SignalBroadcaster"]
```

**Step 7: Delete websocket.py**

```bash
rm producer/signal_producer/publishing/websocket.py
```

**Step 8: Run tests**

```bash
cd producer && uv run pytest tests/test_websocket_broadcaster.py tests/test_integration_signal_flow.py -v
```

**Step 9: Commit**

```bash
git add -A && git commit -m "chore: remove websocket.py compatibility layer

Import directly from websocket_signal_broadcaster.py instead."
```

---

## Task 4: Unify DEFAULT_CITIES Configuration

**Files:**
- Modify: `producer/signal_producer/tasks/event_discovery.py`
- Reference: `producer/signal_producer/config.py` (no changes needed)

**Step 1: Update event_discovery.py**

Remove local DEFAULT_CITIES definition (line 19) and import from config:

Change from:
```python
DEFAULT_POLL_INTERVAL = 10  # seconds
DEFAULT_CITIES = ["nyc", "chicago", "miami"]
DEFAULT_DAYS_AHEAD = 4
```

To:
```python
from ..config import DEFAULT_CITIES

DEFAULT_POLL_INTERVAL = 10  # seconds
DEFAULT_DAYS_AHEAD = 4
```

**Step 2: Run tests**

```bash
cd producer && uv run pytest tests/test_event_discovery.py -v
```

**Step 3: Commit**

```bash
git add -A && git commit -m "refactor: unify DEFAULT_CITIES from config.py

Remove duplicate definition in event_discovery.py."
```

---

## Task 5: Reorganize Data Collection Modules

**Goal:** Rename `registry/` to `data/`, move `models/collector.py` and `tracker/price_tracker.py` there with clearer names.

**Files:**
- Rename: `registry/` → `data/`
- Rename: `registry/market_registry.py` → `data/polymarket_registry.py`
- Move: `models/collector.py` → `data/ensemble_collector.py`
- Move: `tracker/price_tracker.py` → `data/polymarket_price_tracker.py`
- Delete: `tracker/` (will be empty)
- Update: `models/__init__.py`
- Update: All importing files

**Step 1: Create data/ directory and move files**

```bash
mv producer/signal_producer/registry producer/signal_producer/data
mv producer/signal_producer/data/market_registry.py producer/signal_producer/data/polymarket_registry.py
mv producer/signal_producer/models/collector.py producer/signal_producer/data/ensemble_collector.py
mv producer/signal_producer/tracker/price_tracker.py producer/signal_producer/data/polymarket_price_tracker.py
```

**Step 2: Update data/__init__.py**

```python
"""Data collection and registry modules."""

from .polymarket_registry import MarketRegistry, CachedEvent, CachedMarket, CachedPrice
from .ensemble_collector import ForecastCollector, StoredForecast
from .polymarket_price_tracker import PriceTracker, CLOB_WS_URL

__all__ = [
    "MarketRegistry",
    "CachedEvent",
    "CachedMarket",
    "CachedPrice",
    "ForecastCollector",
    "StoredForecast",
    "PriceTracker",
    "CLOB_WS_URL",
]
```

**Step 3: Update imports in polymarket_registry.py**

Change line 15 from:
```python
from ..clients.markets import WeatherEvent, WeatherMarket
```
To:
```python
from ..clients.polymarket.markets import WeatherEvent, WeatherMarket
```
(This will be valid after Task 6)

**Step 4: Update imports in polymarket_price_tracker.py**

Change line 23 from:
```python
from ..registry.market_registry import MarketRegistry
```
To:
```python
from .polymarket_registry import MarketRegistry
```

**Step 5: Update models/__init__.py**

Remove collector imports:
```python
"""Data storage models."""

from .models import (
    Base,
    Observation,
    SignalRecord,
    TrackedEvent,
    TrackedMarket,
    TrackedForecast,
    get_engine,
    init_db,
    get_session,
)

__all__ = [
    "Base",
    "Observation",
    "SignalRecord",
    "TrackedEvent",
    "TrackedMarket",
    "TrackedForecast",
    "get_engine",
    "init_db",
    "get_session",
]
```

**Step 6: Delete empty tracker/ directory**

```bash
rm -rf producer/signal_producer/tracker
```

**Step 7: Update all importing files**

Files referencing `registry.market_registry`:
- `tasks/orchestrator.py`: `from ..registry.market_registry import MarketRegistry` → `from ..data.polymarket_registry import MarketRegistry`
- `tasks/event_discovery.py`: TYPE_CHECKING import → `from ..data.polymarket_registry import MarketRegistry`

Files referencing `tracker.price_tracker`:
- `tasks/orchestrator.py`: `from ..tracker.price_tracker import PriceTracker` → `from ..data.polymarket_price_tracker import PriceTracker`

Files referencing `models.collector`:
- `cli.py`: `from .models import ForecastCollector` → `from .data import ForecastCollector`

Test files:
- `test_market_registry.py`: Update imports
- `test_price_tracker.py`: Update imports
- `test_integration_signal_flow.py`: Update imports

**Step 8: Run tests**

```bash
cd producer && uv run pytest tests/ -v
```

**Step 9: Commit**

```bash
git add -A && git commit -m "refactor: reorganize data collection modules

- Rename registry/ to data/
- Rename market_registry.py to polymarket_registry.py
- Move collector.py to data/ensemble_collector.py
- Move price_tracker.py to data/polymarket_price_tracker.py
- Delete empty tracker/ directory"
```

---

## Task 6: Reorganize Clients Directory

**Goal:** Create subdirectories for polymarket and weather clients.

**Files:**
- Create: `clients/polymarket/`
- Create: `clients/weather/`
- Move: `clients/gamma.py` → `clients/polymarket/gamma.py`
- Move: `clients/markets.py` → `clients/polymarket/markets.py`
- Move: `clients/open_meteo.py` → `clients/weather/open_meteo.py`
- Move: `clients/noaa_cdo.py` → `clients/weather/noaa_cdo.py`
- Keep: `clients/llm_pricer.py` (not polymarket or weather specific)
- Update: `clients/__init__.py`

**Step 1: Create subdirectories**

```bash
mkdir -p producer/signal_producer/clients/polymarket
mkdir -p producer/signal_producer/clients/weather
```

**Step 2: Move files**

```bash
mv producer/signal_producer/clients/gamma.py producer/signal_producer/clients/polymarket/
mv producer/signal_producer/clients/markets.py producer/signal_producer/clients/polymarket/
mv producer/signal_producer/clients/open_meteo.py producer/signal_producer/clients/weather/
mv producer/signal_producer/clients/noaa_cdo.py producer/signal_producer/clients/weather/
```

**Step 3: Create clients/polymarket/__init__.py**

```python
"""Polymarket API clients and data structures."""

from .gamma import GammaClient
from .markets import (
    WeatherEvent,
    WeatherMarket,
    parse_weather_event,
    parse_temp_range,
    calculate_market_probability,
)

__all__ = [
    "GammaClient",
    "WeatherEvent",
    "WeatherMarket",
    "parse_weather_event",
    "parse_temp_range",
    "calculate_market_probability",
]
```

**Step 4: Create clients/weather/__init__.py**

```python
"""Weather data API clients."""

from .open_meteo import OpenMeteoClient, EnsembleForecast
from .noaa_cdo import NOAACDOClient, CITY_STATIONS

__all__ = [
    "OpenMeteoClient",
    "EnsembleForecast",
    "NOAACDOClient",
    "CITY_STATIONS",
]
```

**Step 5: Update clients/__init__.py**

```python
"""External API clients."""

from .polymarket import (
    GammaClient,
    WeatherEvent,
    WeatherMarket,
    parse_weather_event,
    parse_temp_range,
    calculate_market_probability,
)
from .weather import (
    OpenMeteoClient,
    EnsembleForecast,
    NOAACDOClient,
    CITY_STATIONS,
)
from .llm_pricer import LLMPricer

__all__ = [
    "GammaClient",
    "WeatherEvent",
    "WeatherMarket",
    "parse_weather_event",
    "parse_temp_range",
    "calculate_market_probability",
    "OpenMeteoClient",
    "EnsembleForecast",
    "NOAACDOClient",
    "CITY_STATIONS",
    "LLMPricer",
]
```

**Step 6: Update internal imports in moved files**

In `clients/polymarket/markets.py`, update TYPE_CHECKING import (line 12):
```python
if TYPE_CHECKING:
    from ..weather.open_meteo import EnsembleForecast
```

In `clients/weather/open_meteo.py`, no changes needed (no internal imports).

In `clients/weather/noaa_cdo.py`, no changes needed.

In `clients/polymarket/gamma.py`, no changes needed.

**Step 7: Update all importing files**

Most imports go through `clients/__init__.py` so they won't need changes. Direct imports need updating:

- `data/polymarket_registry.py`: `from ..clients.markets import` → `from ..clients.polymarket.markets import`
- `data/ensemble_collector.py`: `from ..clients.open_meteo import` → `from ..clients.weather.open_meteo import`
- `tasks/orchestrator.py`: Imports through `clients` package, no change needed
- `cli.py`: Imports through `clients` package, no change needed

**Step 8: Run tests**

```bash
cd producer && uv run pytest tests/ -v
```

**Step 9: Commit**

```bash
git add -A && git commit -m "refactor: organize clients into polymarket/ and weather/ subdirs

- Move gamma.py and markets.py to clients/polymarket/
- Move open_meteo.py and noaa_cdo.py to clients/weather/
- Keep llm_pricer.py at clients/ level (cross-cutting)"
```

---

## Task 7: Delete auction_smoke.py (One-Shot Artifact)

**Files:**
- Delete: `producer/signal_producer/auction_smoke.py`
- Delete: `producer/tests/test_auction_smoke.py`
- Update: `producer/pyproject.toml` (remove entry point)

**Step 1: Remove entry point from pyproject.toml**

In `producer/pyproject.toml`, remove line 57:
```toml
signal-auction-smoke = "signal_producer.auction_smoke:main"
```

**Step 2: Delete the files**

```bash
rm producer/signal_producer/auction_smoke.py
rm producer/tests/test_auction_smoke.py
```

**Step 3: Run tests to verify nothing depends on it**

```bash
cd producer && uv run pytest tests/ -v --tb=short
```

**Step 4: Commit**

```bash
git add -A && git commit -m "chore: remove unused auction_smoke.py

One-shot artifact from initial E2E validation.
Never used in CI or regular development workflow."
```

---

## Task 8: Final Cleanup and Verification

**Step 1: Remove any empty __pycache__ directories**

```bash
find producer/signal_producer -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
```

**Step 2: Run full test suite**

```bash
cd producer && uv run pytest tests/ -v
```

**Step 3: Run type checking**

```bash
cd producer && uv run mypy signal_producer
```

**Step 4: Verify imports work**

```bash
cd producer && uv run python -c "from signal_producer.clients import GammaClient, OpenMeteoClient; from signal_producer.data import MarketRegistry, PriceTracker, ForecastCollector; print('All imports OK')"
```

**Step 5: Commit final state**

```bash
git add -A && git commit -m "chore: final cleanup after reorganization"
```

---

## Final Directory Structure

```
producer/signal_producer/
├── __init__.py
├── cli.py
├── config.py                    # Unified DEFAULT_CITIES
├── main.py
├── ws_server.py
│
├── clients/
│   ├── __init__.py              # Re-exports all clients
│   ├── llm_pricer.py            # Cross-cutting LLM client
│   ├── polymarket/
│   │   ├── __init__.py
│   │   ├── gamma.py             # Polymarket Gamma API
│   │   └── markets.py           # WeatherEvent, WeatherMarket
│   └── weather/
│       ├── __init__.py
│       ├── open_meteo.py        # Open-Meteo ensemble API
│       └── noaa_cdo.py          # NOAA CDO API
│
├── data/                        # (was registry/ + tracker/ + models/collector.py)
│   ├── __init__.py
│   ├── polymarket_registry.py   # Market tracking (was market_registry.py)
│   ├── polymarket_price_tracker.py  # CLOB WebSocket (was price_tracker.py)
│   └── ensemble_collector.py    # Forecast collection (was collector.py)
│
├── models/
│   ├── __init__.py
│   └── models.py                # SQLAlchemy ORM only
│
├── publishing/
│   ├── __init__.py
│   └── websocket_signal_broadcaster.py  # (websocket.py deleted)
│
├── signals/
│   ├── __init__.py
│   └── types/
│       └── __init__.py          # Re-exports from shared/signal_schema
│
└── tasks/
    ├── __init__.py
    ├── orchestrator.py
    ├── event_discovery.py       # Uses config.DEFAULT_CITIES
    └── signal_generator.py

shared/signal_schema/
├── __init__.py
└── types/
    ├── __init__.py
    ├── producer_signal.py       # ProducerSignal, WeatherMetadata, PolymarketInfo
    └── auction_messages.py      # AuctionBidMessage, AuctionBidRejected, etc.
```

---

## Verification Checklist

- [ ] All tests pass: `uv run pytest tests/ -v`
- [ ] Type checking passes: `uv run mypy signal_producer`
- [ ] CLI works: `uv run signal-producer --help`
- [ ] Entry point removed: `uv run signal-auction-smoke` should fail (command not found)
- [ ] No circular imports
- [ ] Consumer tests pass: `cd ../consumer && uv run pytest tests/ -v`
