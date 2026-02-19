# Claude Project Context - Polymarket Weather Bot

## Project Overview

Prediction market trading bot exploiting weather forecast accuracy vs market mispricing. Uses NOAA/Open-Meteo ensemble forecasts to calculate probability distributions, compares against Polymarket prices, and trades when edge exceeds threshold.

---

## API Documentation Links

### Polymarket
- **CLOB Overview**: https://docs.polymarket.com/developers/CLOB/overview
- **CLOB Methods**: https://docs.polymarket.com/developers/CLOB/clients/methods-overview
- **Timeseries API**: https://docs.polymarket.com/developers/CLOB/timeseries
- **Gamma API (Markets)**: https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide
- **py-clob-client GitHub**: https://github.com/Polymarket/py-clob-client (791 stars, actively maintained)
- **py-clob-client Examples**: https://github.com/Polymarket/py-clob-client/tree/main/examples

### Weather Data
- **Open-Meteo Ensemble API**: https://open-meteo.com/en/docs/ensemble-api
- **Open-Meteo Historical Forecast API**: https://open-meteo.com/en/docs/historical-forecast-api
- **Open-Meteo Previous Runs API**: https://open-meteo.com/en/docs/previous-runs-api
- **NOAA Weather API**: https://www.weather.gov/documentation/services-web-api
- **NOAA KLGA Station**: https://api.weather.gov/stations/KLGA

### LLM
- **Venice.ai API**: https://docs.venice.ai/api-reference/api-spec
- Venice is OpenAI-compatible, use `openai` Python library with custom base_url

---

## Critical API Details (Verified via Testing)

### Gamma API - Weather Events

**Endpoint**: `GET https://gamma-api.polymarket.com/events/slug/{slug}`

**Slug Pattern**: `highest-temperature-in-{city}-on-{month}-{day}-{year}`
- Example: `highest-temperature-in-nyc-on-february-20-2026`
- Cities use short names: `nyc`, `la`, etc.

**Response Structure** (verified Feb 18, 2026):
```json
{
  "id": "213978",
  "title": "Highest temperature in NYC on February 20?",
  "closed": false,
  "resolutionSource": "https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA",
  "markets": [
    {
      "question": "Will the highest temperature in New York City be 31°F or below on February 20?",
      "outcomes": "[\"Yes\", \"No\"]",           // JSON STRING - must parse
      "outcomePrices": "[\"0.007\", \"0.993\"]", // JSON STRING - must parse
      "clobTokenIds": "[\"token1\", \"token2\"]", // JSON STRING - [YES_token, NO_token]
      "active": true,
      "closed": false
    }
  ]
}
```

**IMPORTANT**: `outcomes`, `outcomePrices`, and `clobTokenIds` are JSON STRINGS, not arrays. Must use `json.loads()`.

### Open-Meteo Ensemble API

**Endpoint**: `GET https://ensemble-api.open-meteo.com/v1/ensemble`

**Parameters**:
```
latitude=40.7128
longitude=-74.0060
models=gfs_seamless
hourly=temperature_2m
temperature_unit=fahrenheit
timezone=America/New_York
forecast_days=7
```

**Response Structure** (verified Feb 18, 2026):
```json
{
  "hourly": {
    "time": ["2026-02-18T00:00", "2026-02-18T01:00", ...],
    "temperature_2m": [35.6, 35.2, ...],           // Control run (member 0)
    "temperature_2m_member01": [35.8, 35.4, ...],  // Ensemble member 1
    "temperature_2m_member02": [35.4, 35.0, ...],  // Ensemble member 2
    // ... up to temperature_2m_member30
  }
}
```

**IMPORTANT**: Members are SEPARATE KEYS, not a nested array. Total 31 members (control + 30 perturbations).

### Polymarket Timeseries API

**Endpoint**: `GET https://clob.polymarket.com/prices-history`

**Parameters**:
- `market`: CLOB token ID (required)
- `interval`: `1m`, `1h`, `6h`, `1d`, `1w`, `max`
- OR `startTs`/`endTs`: Unix timestamps

**Response**:
```json
{
  "history": [
    {"t": 1771413619, "p": 0.015},
    {"t": 1771437797, "p": 0.0065}
  ]
}
```

### NOAA Observations API

**Endpoint**: `GET https://api.weather.gov/stations/KLGA/observations/latest`

**Response** (verified):
```json
{
  "properties": {
    "temperature": {
      "value": 2,  // Celsius
      "unitCode": "wmoUnit:degC"
    },
    "timestamp": "2026-02-18T17:45:00+00:00"
  }
}
```

Convert to Fahrenheit: `value * 9/5 + 32`

---

## py-clob-client Usage

### Installation
```bash
pip install py-clob-client>=0.34.5
```

### Chain IDs
```python
from py_clob_client.constants import POLYGON, AMOY
# POLYGON = 137  (mainnet - USE THIS)
# AMOY = 80002   (testnet - Polymarket doesn't run on this)
```

### Credential Derivation (one-time)
```python
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

client = ClobClient(
    host="https://clob.polymarket.com",
    key=os.environ["POLYMARKET_PRIVATE_KEY"],
    chain_id=POLYGON,
)
creds = client.derive_api_key()
# Save these to .env:
# POLYMARKET_API_KEY=creds.api_key
# POLYMARKET_API_SECRET=creds.api_secret
# POLYMARKET_API_PASSPHRASE=creds.api_passphrase
```

### Order Creation
```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL
from py_clob_client.constants import POLYGON

creds = ApiCreds(
    api_key=os.environ["POLYMARKET_API_KEY"],
    api_secret=os.environ["POLYMARKET_API_SECRET"],
    api_passphrase=os.environ["POLYMARKET_API_PASSPHRASE"],
)

client = ClobClient(
    host="https://clob.polymarket.com",
    key=os.environ["POLYMARKET_PRIVATE_KEY"],
    chain_id=POLYGON,
    creds=creds,
)

# Market order
order_args = MarketOrderArgs(
    token_id="<token_id>",
    amount=100,  # Amount in smallest unit
    side=BUY,    # or SELL
)
signed_order = client.create_market_order(order_args)
resp = client.post_order(signed_order, orderType=OrderType.FOK)
```

### Order Types
- `OrderType.GTC` - Good Till Cancelled
- `OrderType.FOK` - Fill or Kill
- `OrderType.GTD` - Good Till Date

---

## Environment Variables

```bash
# Wallet (user provides)
POLYMARKET_PRIVATE_KEY=0x<64-hex-chars>
POLYMARKET_WALLET_ADDRESS=0x<40-hex-chars>

# Derived credentials (script generates)
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=

# API Keys (already have)
VENICE_API_KEY=k8gn2BSeJyzwlzsgeUdmSiy1McfYbZx4TMUF3ftVD1
GRID_API_KEY=fGCOHQkP0DA5POehxWo3zst232XwiaoaFHjk2jvN

# Trading Config
TRADING_MODE=paper  # or "live"
BANKROLL_USDC=50
MAX_POSITION_USD=5
KELLY_FRACTION=0.25
DAILY_LOSS_LIMIT_PCT=5
EDGE_THRESHOLD_PCT=8

# Chain (CRITICAL)
CHAIN_ID=137
CLOB_API_URL=https://clob.polymarket.com

# Profit Extraction
PROFIT_EXTRACTION_PCT=0
SAFE_WALLET_ADDRESS=
```

---

## Key Verified Facts

### Resolution Source
- Polymarket weather markets resolve using **Weather Underground** data
- Specifically: LaGuardia Airport Station (KLGA)
- URL: https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA
- Resolution to whole degrees Fahrenheit

### NOAA/Weather Underground Alignment
- **Verified Feb 17, 2026**: NOAA reported 46.9°F max, Polymarket resolved to 46-47°F bucket
- Both use same ASOS station data - values match
- Safe to use NOAA/Open-Meteo for forecasting

### Weather Market Structure
- Organized as EVENTS, not individual markets
- Each event has ~9 temperature buckets (2°F each)
- Buckets: "31°F or below", "32-33°F", "34-35°F", ..., "46°F or higher"
- Each bucket is a Yes/No market with own token IDs

### Python Version
- py-clob-client requires Python >=3.9.10
- We're using Python 3.12

### Paper Trading
- Polymarket has NO native paper trading/testnet
- We implement it: read real data, skip order execution, log simulated trades

---

## City Coordinates

```python
CITY_COORDINATES = {
    "new_york": {"lat": 40.7128, "lon": -74.0060, "tz": "America/New_York", "slug": "nyc", "station": "KLGA"},
    "los_angeles": {"lat": 34.0522, "lon": -118.2437, "tz": "America/Los_Angeles", "slug": "la", "station": "KLAX"},
    "chicago": {"lat": 41.8781, "lon": -87.6298, "tz": "America/Chicago", "slug": "chicago", "station": "KORD"},
    "london": {"lat": 51.5074, "lon": -0.1278, "tz": "Europe/London", "slug": "london", "station": "EGLL"},
}
```

---

## Common Patterns

### Parse Weather Event
```python
import json
import httpx

async def fetch_weather_event(city_slug: str, month: str, day: int, year: int):
    slug = f"highest-temperature-in-{city_slug}-on-{month}-{day}-{year}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://gamma-api.polymarket.com/events/slug/{slug}")
        if resp.status_code == 404:
            return None
        data = resp.json()

    buckets = []
    for market in data.get("markets", []):
        prices = json.loads(market["outcomePrices"])  # MUST parse JSON string
        tokens = json.loads(market["clobTokenIds"])   # MUST parse JSON string
        buckets.append({
            "question": market["question"],
            "yes_price": float(prices[0]),
            "no_price": float(prices[1]),
            "yes_token": tokens[0],
            "no_token": tokens[1],
        })
    return {"event_id": data["id"], "buckets": buckets}
```

### Get Ensemble Forecast
```python
async def get_ensemble_temps(lat: float, lon: float) -> list[float]:
    """Get 31 daily high temperatures from ensemble."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "models": "gfs_seamless",
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "forecast_days": 7,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://ensemble-api.open-meteo.com/v1/ensemble", params=params)
        data = resp.json()

    hourly = data["hourly"]
    # Collect all member keys
    member_keys = ["temperature_2m"] + [f"temperature_2m_member{i:02d}" for i in range(1, 31)]

    # Get max temp for each member (daily high)
    return [max(hourly[key]) for key in member_keys]
```

### Calculate Edge
```python
def calculate_edge(ensemble_temps: list[float], bucket_low: float, bucket_high: float, market_price: float) -> float:
    """Calculate edge: model probability - market probability."""
    count = sum(1 for t in ensemble_temps if bucket_low <= t < bucket_high)
    model_prob = count / len(ensemble_temps)
    return model_prob - market_price
```

### Kelly Position Sizing
```python
def kelly_position(win_prob: float, price: float, bankroll: float, fraction: float = 0.25) -> float:
    """Quarter-Kelly position sizing."""
    if win_prob <= price or price <= 0 or price >= 1:
        return 0
    b = (1 - price) / price  # Win payout multiplier
    kelly = (win_prob * b - (1 - win_prob)) / b
    return min(bankroll * kelly * fraction, 5.0)  # Max $5
```

---

## DO NOT USE

- **suislanchez/polymarket-kalshi-weather-bot**: Only 6 stars, created Feb 10 2026 (8 days old), simulation-only, not production-ready
- **AMOY testnet for Polymarket**: Polymarket doesn't run on Amoy, use POLYGON (137)
- **Hardcoded chain IDs**: Always use `from py_clob_client.constants import POLYGON`

---

## Backtesting Data Sources

| Source | URL | Data |
|--------|-----|------|
| Open-Meteo Historical Forecast | https://open-meteo.com/en/docs/historical-forecast-api | Past forecasts (2-5 years) |
| Open-Meteo Previous Runs | https://open-meteo.com/en/docs/previous-runs-api | Forecasts with lead time (Jan 2024+) |
| Polymarket Timeseries | `GET /prices-history` | Historical market prices |
| NOAA Climate Data | https://api.weather.gov/stations/KLGA/observations | Historical observations |

---

## Quick Test Commands

```bash
# Test Open-Meteo ensemble
curl "https://ensemble-api.open-meteo.com/v1/ensemble?latitude=40.7128&longitude=-74.0060&models=gfs_seamless&hourly=temperature_2m&temperature_unit=fahrenheit"

# Test Gamma API weather event
curl "https://gamma-api.polymarket.com/events/slug/highest-temperature-in-nyc-on-february-20-2026"

# Test NOAA current observation
curl "https://api.weather.gov/stations/KLGA/observations/latest"

# Test Polymarket timeseries
curl "https://clob.polymarket.com/prices-history?market=<token_id>&interval=max"
```
