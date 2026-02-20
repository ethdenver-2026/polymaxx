# Data Collection Research for Weather Prediction Markets

Research conducted: February 2026

## Executive Summary

This document covers what data should be collected for weather prediction market trading, how Polymarket resolves temperature markets, and the relationship between different data sources.

---

## Resolution Source Analysis

### What Polymarket Uses

From actual market data (Gamma API):

> "The resolution source for this market will be information from **Wunderground**, specifically the highest temperature recorded for all times on this day by the **LaGuardia Airport Station** once information is finalized"

Resolution URL: `https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA`

Key points from market description:
- Measures to "whole degrees Fahrenheit"
- Cannot resolve until "all data for this date has been finalized"
- Revisions after finalization are not considered

### The Data Chain

```
ASOS Sensor (at KLGA airport)
         │
         ▼
   METAR Report (every ~20 min)
         │
         ├──────────────────────────────────┐
         ▼                                  ▼
  Weather Underground                 NOAA CDO (GHCN-Daily)
  (Polymarket resolution)             (what we collect)
         │                                  │
         │  Source: MADIS/ASOS feed         │  Source: Same ASOS sensors
         │  Format: Web display             │  Format: TMAX in °F via API
         │                                  │
         └──────────────────────────────────┘
                    SAME DATA
```

### Why They Match

Both Weather Underground and NOAA CDO pull from the **same ASOS sensors**:

- Weather Underground: "Almost 2,000 Automated Surface Observation System (ASOS) stations located at airports throughout the country" and "over 26,000 weather stations that are part of MADIS which is managed by NOAA"
- NOAA CDO: Provides the official GHCN-Daily dataset that includes ASOS TMAX observations

**Verified alignment:**
- Feb 16, 2026: NOAA CDO = 39°F, Polymarket resolved to "38-39°F" bucket ✅
- Feb 17, 2026: NOAA CDO = 47°F, matched Polymarket resolution ✅

### Potential 1°F Rounding Discrepancies

ASOS temperature processing has a known issue:

1. Sensors store temperatures in whole °F internally
2. Data is transmitted as whole °C
3. °F → °C → °F conversion can cause 1°F rounding errors

Example: 78°F → 25.6°C → rounds to 26°C → converts back to 78.8°F → rounds to 79°F

This is rare but possible. The official "CLI" (Climatological Report) from NWS is the gold standard that avoids this, but Polymarket uses Weather Underground which may have the rounding issue.

**Mitigation**: These edge cases are rare. If a temperature is on a bucket boundary, manually verify Weather Underground before resolution.

---

## Data Collection Recommendations

### Currently Collected ✅

The `ForecastCollector` stores:
- 31-member GFS ensemble highs from Open-Meteo
- Raw API response (preserves all data)
- Forecast date → target date mapping
- Mean, std, min, max statistics

### Missing Data (Priority Order)

#### P0: Market Prices at Forecast Time

**Why critical**: Without knowing market prices when signals were generated, you cannot calculate true P&L or edge.

```python
@dataclass
class MarketSnapshot:
    city: str
    target_date: str
    snapshot_time: str  # ISO timestamp
    buckets: list[dict]  # [{question, yes_price, no_price, yes_token, no_token}]
    event_id: str
```

**Note**: User mentioned Polymarket has historical price API and trades will be captured in consumer via websocket.

#### P0: Actual Temperature Observations

**Why critical**: Cannot verify forecast accuracy without ground truth.

```python
@dataclass
class ActualObservation:
    city: str
    date: str
    tmax_fahrenheit: float
    source: str  # "noaa_cdo"
    station_id: str  # e.g., "GHCND:USW00014732"
    collected_at: str
```

**Implementation**: NOAA CDO client already exists (`signal_producer/clients/noaa_cdo.py`). Add daily collection job.

#### P1: Multiple Lead Times

Currently collecting 1-day ahead only. Should collect 1, 2, and 3 days ahead.

**Why**: Ensemble underdispersion increases with lead time. Different lead times have different error characteristics.

**Change**: Modify crontab to run collector for `days_ahead=1,2,3`

#### P1: Trading Signals and Decisions

Record what signals were generated and trading decisions made.

```python
@dataclass
class TradingSignal:
    city: str
    target_date: str
    generated_at: str
    bucket_question: str
    ensemble_prob: float
    market_price: float
    edge: float
    kelly_position: float
    decision: str  # "trade", "skip_low_edge", "skip_no_liquidity"
```

#### P2: Resolution Data

Capture when and how markets resolved.

```python
@dataclass
class MarketResolution:
    city: str
    target_date: str
    event_id: str
    resolved_at: str
    winning_bucket: str
    actual_temp: float
    resolution_source_url: str
```

#### P2: Order Book Depth/Liquidity

Polymarket provides order book depth showing bid/ask at various price levels.

**Why**: Liquidity affects slippage and whether positions can actually be filled.

#### P3: MOS (Model Output Statistics)

NWS produces station-specific bias-corrected forecasts.

**Why helpful**: Could compare Open-Meteo bias to official NWS bias correction.

**Access**: IEM MOS Archive at mesonet.agron.iastate.edu/mos/

---

## Data Sources NOT to Collect

### Weather Underground (Don't Scrape)

**Reasons:**
1. No public API - requires scraping JavaScript-rendered pages
2. Same underlying data as NOAA CDO (both use ASOS)
3. NOAA CDO is more authoritative and has proper API

### Historical Weather API (ERA5 Reanalysis)

Open-Meteo Historical Weather API uses ERA5 reanalysis data, NOT observations.

**Problem**: Reanalysis is model-interpolated data, not actual station readings. Won't match Weather Underground resolution values.

---

## Signal Generation vs Verification

| Purpose | Data Source | Reason |
|---------|-------------|--------|
| **Forecasting (signals)** | Open-Meteo GFS ensemble | Provides probability distribution for trading |
| **Verification** | NOAA CDO observations | Measures forecast accuracy |
| **Resolution** | Weather Underground | What Polymarket uses (same as NOAA) |

**Do NOT base signals on NOAA/Weather Underground** - those are observations (what happened), not forecasts (what will happen). Open-Meteo ensemble forecasts are what give you edge.

---

## Historical Data Availability

| Source | Historical Range | Access | Notes |
|--------|-----------------|--------|-------|
| **NOAA CDO (GHCN-Daily)** | 1940+ | Free API (token required) | Best for verification |
| **Open-Meteo Previous Runs** | Jan 2024+ | Free API | Historical forecasts |
| **IEM ASOS Archive** | 2000+ | Free download | Alternative to NOAA CDO |
| **Weather Underground** | Years | Scraping only | No API, avoid |
| **Polymarket prices** | Market history | CLOB API | Historical prices available |

### NOAA CDO Token

Get free token at: https://www.ncei.noaa.gov/cdo-web/token

Current token in `.env`: `NOAA_CDO_TOKEN=CLOronYiAZZDWvtkdijQyOlieLZCkRTp`

---

## Station IDs for Each City

From `signal_producer/clients/noaa_cdo.py`:

```python
CITY_STATIONS = {
    "nyc": "GHCND:USW00014732",      # KLGA (LaGuardia)
    "chicago": "GHCND:USW00094846",  # KORD (O'Hare)
    "miami": "GHCND:USW00012839",    # KMIA
    "denver": "GHCND:USW00003017",   # KDEN
    "la": "GHCND:USW00023174",       # KLAX
}
```

---

## References

- [Weather Underground Data Sources](https://www.wunderground.com/about/data)
- [IEM: Wagering on ASOS Temperatures](https://mesonet.agron.iastate.edu/onsite/news.phtml?id=1469)
- [Wethr.net: Weather Market Basics](https://wethr.net/edu/the-temperature)
- [Wethr.net: NWS Data Guide](https://wethr.net/edu/nws-data-guide)
- [Wethr.net: City Resources](https://wethr.net/edu/city-resources)
- [NCEI ASOS/AWOS Documentation](https://www.ncei.noaa.gov/products/land-based-station/automated-surface-weather-observing-systems)
- [FAA ASOS Program](https://www.faa.gov/air_traffic/weather/asos)
- [Polymarket CLOB API Docs](https://docs.polymarket.com/developers/CLOB/overview)
- [GFS Ensemble Bias Correction Study](https://journals.ametsoc.org/view/journals/wefo/26/3/waf-d-10-05028_1.xml)
- [Forecast Calibration Methods](https://www.worldclimateservice.com/2021/09/06/forecast-calibration/)

---

## Action Items

1. ✅ Continue collecting Open-Meteo ensemble forecasts (already doing)
2. ⬜ Add daily NOAA CDO observation collection job
3. ⬜ Expand forecast collection to 2-day and 3-day lead times
4. ⬜ Consumer will capture trades via websocket (per user)
5. ⬜ Historical prices available via Polymarket API (per user)
6. ❌ Don't scrape Weather Underground - NOAA CDO is equivalent
