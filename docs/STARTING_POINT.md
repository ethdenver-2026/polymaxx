# Prediction Market Bot — Complete Project Brief for Claude Code (v2)

**Date**: February 18, 2026
**Status**: Pre-build research complete. Ready for implementation.

---

## TABLE OF CONTENTS

1. Project Overview & Strategy
2. Architecture & Design Principles
3. Key Technical Decisions (Resolved)
4. Data Provider Details (CORRECTED)
5. Platform Integration Details
6. Weather Strategy — Implementation Path (FASTEST TO PROFIT)
7. Esports Strategy — Implementation Path
8. Future Extensibility (Kalshi, Mentions, Other Markets)
9. Human Pre-Work Checklist
10. Implementation Plan — Weather-First
11. Open Questions & Risks
12. Reference Materials

---

## 1. PROJECT OVERVIEW & STRATEGY

### What We're Building

A multi-strategy automated trading bot for Polymarket prediction markets, starting with **weather markets** (fastest to profit, simplest data pipeline) then expanding to **esports markets** (higher ceiling, more complex data requirements).

The system must be built with a **Strategy Pattern** so new market types can be added without rewriting core infrastructure.

### Strategic Ordering (Changed from v1)

**Phase 1 — Weather (START HERE)**: Exploit mispricing between NOAA/ECMWF weather forecasts and Polymarket crowd-sourced temperature markets. All data sources are free, public APIs. No approval wait. No proprietary data feeds. Documented profits: $1K→$24K, $65K across cities.

**Phase 2 — Esports**: Exploit broadcast delay (15-60s) between GRID's game-server data and what viewers/traders see. Higher potential ceiling but blocked on GRID data access approval and uncertain data granularity on free tier.

**Phase 3 — Future market types**: Kalshi cross-platform arbitrage, mentions markets (Deepgram), other categories. System should support these via the Strategy Pattern but we are NOT detailing or building these now. Just ensure the architecture doesn't prevent them.

### Why Weather First

| Factor | Weather | Esports |
|--------|---------|---------|
| Data source | NOAA/Open-Meteo (free, public, no auth for forecast data) | GRID (requires application, 48hr wait, uncertain live data on free tier) |
| Edge type | Model vs. crowd mispricing (NOAA 85-90% accurate vs market ~15-40% implied) | Latency (game server data arrives before broadcast) |
| Model needed | None — NOAA forecasts ARE the model. Just compare to market prices. | Win probability model from game state features (kills, gold, objectives) |
| Resolution | Deterministic (NOAA Central Park thermometer for NYC, 0.01°F precision) | UMA Oracle (2hr challenge period, edge cases with remakes/DQs) |
| LLM needed | Minimal (market matching, edge case filtering) | Heavy (resolution rule interpretation, ambiguous scenarios) |
| Open-source reference | `suislanchez/polymarket-kalshi-weather-bot` (complete, working) | `Polymarket/agents` (framework only, no strategy logic) |
| Time to first trade | ~1-2 weeks | ~5-7 weeks |
| Markets available | 8+ cities × daily resolution = high throughput | Varies by tournament schedule, some days zero markets |
| Infrastructure shared | 100% of Polymarket execution, monitoring, risk management | Same |

### Documented Weather Bot Earnings (treat with skepticism)

- Hans323: $1,000 → $24,000+ via automated NOAA-referenced micro-bets (London markets)
- meropi: ~$30,000 profit from automated $1-$3 bets, some at $0.01/share producing 500x payoffs
- 1pixel: ~$18,500 from $2,300 deposits, NYC/London markets only
- Various: ~$65,000 profit trading weather across NYC, London, and Seoul

### Documented Esports Bot Earnings (treat with skepticism)

- TeemuTeemuTeemu: $208K in 3 months (esports speed advantages)
- xdd07070: $118K in 1 month (esports)

---

## 2. ARCHITECTURE & DESIGN PRINCIPLES

### Core Architecture — Strategy Pattern

```
┌─────────────────────────────────────────────────────┐
│ STRATEGY LAYER (pluggable per market type)           │
│                                                      │
│ WeatherStrategy    EsportsStrategy   [FutureStrategy]│
│ ├─ NOAA/ECMWF     ├─ GRID API       ├─ ...          │
│ ├─ Ensemble prob   ├─ Game state     │               │
│ └─ Temp ranges     └─ Win prob model │               │
├─────────────────────────────────────────────────────┤
│ SHARED DECISION ENGINE                               │
│ Edge Calculator (strategy prob vs market price)       │
│ LLM Validator (via Venice.ai — resolution edge cases) │
│ Risk Manager (Kelly criterion, position sizing)       │
├─────────────────────────────────────────────────────┤
│ SHARED EXECUTION LAYER (from Polymarket/agents)      │
│ Polymarket.py → Order Builder → CLOB API             │
│ Gamma.py → Market Discovery → Token IDs              │
│ Objects.py → Trade/Market/Event Models                │
├─────────────────────────────────────────────────────┤
│ SHARED MONITORING                                    │
│ SQLite Logger → Telegram Bot → Grafana               │
│ Kill Switch → Circuit Breakers                       │
└─────────────────────────────────────────────────────┘
```

### BaseStrategy Interface

```python
class BaseStrategy(ABC):
    @abstractmethod
    def get_signal(self) -> Signal: ...
    @abstractmethod
    def calculate_edge(self, signal, market_price) -> float: ...
    @abstractmethod
    def should_trade(self, edge, confidence) -> bool: ...
    @abstractmethod
    def get_market_filter(self) -> dict: ...  # Gamma API filter params

class WeatherStrategy(BaseStrategy): ...   # Phase 1
class EsportsStrategy(BaseStrategy): ...   # Phase 2
# Future strategies just implement this interface
```

### What's Shared vs Strategy-Specific

**Shared (~60% of codebase, build once)**:

- Polymarket execution layer (py-clob-client, order management)
- Market discovery pipeline (Gamma API)
- Risk management framework (Kelly criterion, position sizing, exposure limits)
- Monitoring stack (SQLite, Telegram, Grafana)
- Kill switch / circuit breakers
- Backtesting infrastructure
- Database schema (with strategy_type column)
- LLM client (Venice.ai integration)

**Weather-specific (~20%)**:

- NOAA/Open-Meteo API client
- GFS ensemble probability distribution calculator
- Temperature range → Polymarket market matching
- Weather-specific market discovery rules (filter by "weather" tag)

**Esports-specific (~20%, built in Phase 2)**:

- GRID API integration + game state parsing
- Win probability model (kills/objectives/gold → P(win))
- Game-specific logic (CS2 vs Dota 2 different state spaces)
- Broadcast delay estimation

---

## 3. KEY TECHNICAL DECISIONS (RESOLVED)

### LLM Provider: Venice.ai

Venice.ai is a privacy-focused AI inference platform with OpenAI-compatible API endpoints. It provides access to both open-source models ("Private" — run on Venice's GPUs, zero logging) and commercial models ("Anonymized" — proxied through Venice with no user data linked to the provider).

**Why Venice.ai**:

- OpenAI-compatible `/v1/chat/completions` endpoint — works with any OpenAI SDK
- Access to Gemini, Claude, GPT models through single API
- Privacy-focused (important for trading strategy IP)
- Credit-based, no subscription required
- Founded by Erik Voorhees (ShapeShift founder) — legitimate crypto/privacy project

**Relevant models and pricing (per 1M tokens)**:

| Model | Privacy | Input | Output | Use Case |
|-------|---------|-------|--------|----------|
| Qwen3 235B A22B | Private | $0.15 | $0.75 | 90% of decisions — fast, cheap, capable |
| DeepSeek V3.2 | Private | $0.40 | $1.00 | Alternative to Qwen3 for variety |
| Gemini 3 Flash Preview | Anonymized | $0.70 | $3.75 | Medium complexity — borderline edge cases |
| Claude Sonnet 4.5 | Anonymized | $3.75 | $18.75 | Truly ambiguous resolution interpretation |
| Claude Opus 4.5 | Anonymized | $6.00 | $30.00 | Only if Sonnet fails on critical edge case |

**Tiered architecture**:

- **90% of decisions** → Qwen3 235B ($0.15/$0.75 per 1M tokens) or DeepSeek V3.2
- **Borderline cases** → Gemini 3 Flash Preview
- **Truly ambiguous** → Claude Sonnet 4.5

**Integration**:

```python
# Venice.ai is OpenAI-compatible
from openai import OpenAI

client = OpenAI(
    api_key="your-venice-api-key",
    base_url="https://api.venice.ai/api/v1"
)

response = client.chat.completions.create(
    model="qwen3-235b-a22b-instruct-2507",  # or "gemini-3-flash-preview", etc.
    messages=[{"role": "user", "content": "..."}]
)
```

No need for LiteLLM — Venice.ai itself is the unified routing layer. Just change the `model` parameter.

**Human setup**: Generate API key at venice.ai/settings/api. Keys prefixed with `VENICE-INFERENCE-KEY-`. Credits purchased with credit card or crypto. Credits never expire.

### Why LLMs Are Still Needed (Even for Weather)

Weather markets are simpler but edge cases exist:

- Market wording ambiguity: "high temperature" — is that the daily max or the forecast high?
- Resolution source disputes: market says "per weather.gov" but what if weather.gov is down?
- Multi-range markets: bucket boundaries, rounding rules
- Esports (Phase 2) needs LLMs heavily for: remakes, DQs, forfeit wins, format changes

### Execution Framework: Polymarket/agents

Use Polymarket's official repo (2,200 stars, 522 forks, MIT license):

- **Take**: `Polymarket.py` (order execution), `Gamma.py` (market discovery), `Objects.py` (data models)
- **Build ourselves**: Everything else

### Open-Source References (Vetted)

| Repo | Stars | Use |
|------|-------|-----|
| `Polymarket/agents` | 2,200 | Official framework — take execution layer |
| `suislanchez/polymarket-kalshi-weather-bot` | — | Weather bot reference (FastAPI, 31-member GFS ensemble, Kelly criterion) |
| `warproxxx/poly-maker` | 633 | Production patterns, market-making logic |
| `Jon-Becker/prediction-market-analysis` | 1,800 | Backtesting dataset (7.68M markets, 72.1M trades) |
| `ent0n29/polybot` | 103 | Monitoring patterns (Grafana/Prometheus) |
| **AVOID**: terauss repos, Mist-kail, BlackSky-Jose | — | SEO spam, inflated stars |

---

## 4. DATA PROVIDER DETAILS (CORRECTED)

### Weather Data Sources (All Free, No Auth Required for Forecast Data)

**Open-Meteo (PRIMARY for weather strategy)**:

- Free, open-source weather API
- Provides 31-member GFS ensemble forecasts (critical for probability distributions)
- No API key required for non-commercial use
- Endpoint: `https://ensemble-api.open-meteo.com/v1/ensemble`
- Returns temperature forecasts with uncertainty ranges from all 31 ensemble members
- Calculate probability of each temperature range by counting how many of 31 members fall in each bucket

**NOAA/NWS API (SECONDARY/VALIDATION)**:

- Official US government weather data
- Free, no auth required
- `https://api.weather.gov/` — forecasts, observations, alerts
- Used for: US city forecasts, validation against Open-Meteo
- GFS model updates: 00, 06, 12, 18 UTC

**ECMWF (TERTIARY — for European cities)**:

- Accessed via Open-Meteo (they include ECMWF data)
- Updates: 00, 12 UTC
- Generally considered more accurate than GFS for European cities

**Resolution verification**:

- NYC: NOAA Central Park weather station (0.01°F precision)
- London: Met Office Heathrow observations
- Other cities: Check specific Polymarket market resolution sources

### GRID Esports (For Phase 2)

**What it is**: Official esports data platform with direct game-server partnerships (Riot Games, Ubisoft, KRAFTON, 70+ tournament organizers). Data comes directly from game servers — sub-second latency.

**Open Access (Free)**: CS2 and Dota 2 only. Apply at grid.gg/open-access-application-form/. Up to 48hr approval.

**CRITICAL — FAST TRACK OPPORTUNITY: Cloud9 × JetBrains Hackathon**

The "Sky's the Limit" hackathon provides GRID data access for **League of Legends AND VALORANT** — titles normally locked behind GRID's paid commercial tier. Key details:

- **Hackathon submission deadline**: February 3, 2026 (ALREADY PASSED)
- **Data access window**: December 9, 2025 through **March 9, 2026** (still active for ~3 weeks)
- **Data application form**: grid.gg/hackathon-application-form/ (returned 404 when tested Feb 18, but Google's index still shows the form content)
- **What's included**: LoL and VALORANT data via GRID Open Access — Central Data API, Series State API, File Download API, Series Events JSONL files
- **Judging period**: Feb 10 – Feb 24, 2026 (happening now)

**Recommended action**:

1. Try the hackathon application form immediately — it may still work even though submissions are closed, since data access runs until March 9
2. If the form is truly dead, email GRID support (<support@grid.gg>) explaining you want to participate in the hackathon and requesting data access for the remaining window
3. Simultaneously apply for regular Open Access (CS2/Dota 2) — this is guaranteed to work
4. If you get hackathon access: you have ~3 weeks of free LoL + VALORANT data to explore, test, and determine if the data granularity supports live trading

**Paid tiers**: Pricing not public. Enterprise sales only. GRID's primary customers are major sportsbooks. Expect $10K-$100K+/year — likely prohibitive for individual use.

### ⚠️ PandaScore — CORRECTED ASSESSMENT

**Previous assessment was WRONG.** PandaScore is NOT a reliable alternative for live trading.

**What PandaScore actually is**: A data aggregator that **scrapes** esports data from publicly available broadcast streams. They do NOT have direct game-server access for most titles.

**Court ruling**: A Berlin court ruled PandaScore cannot advertise their data as "live" or "real-time" when it is scraped from streams. Bayes Esports (GRID's predecessor entity) won this case and pursued additional legal action.

**Latency problem**: PandaScore claims "300ms latency from stream" — but that's 300ms from the **broadcast stream**, which itself is already 15-60+ seconds delayed from the game server. This means PandaScore data arrives at roughly the same time viewers see it. **This completely destroys the speed edge.**

**PandaScore's own CEO acknowledged** the delay problem: even a 2-second advantage is significant, and current 5-10 minute broadcast delays are problematic for betting.

**Live data pricing**: Starts at €1,000/videogame/month for basic live API. Full play-by-play (Pro Live plan) requires contacting sales.

**What PandaScore IS useful for** (but not for live trading):

- Historical match data for backtesting
- Match schedules and fixtures (free tier)
- Post-game statistics
- Validating GRID data accuracy

**Bottom line**: For the live trading edge, GRID is the ONLY viable path. PandaScore cannot beat the broadcast delay.

---

## 5. PLATFORM INTEGRATION DETAILS

### Polymarket

**Blockchain**: Polygon (Chain ID 137)
**Currency**: USDC.e (bridged USDC on Polygon)
**Gas**: MATIC/POL (Polymarket covers most via relayer)

**APIs**:

- **Gamma API** (read-only, no auth): market discovery, metadata, events
- **CLOB API** (auth required): order placement, order book, positions
- **Python SDK**: `py-clob-client` — EIP-712 signing, order building, API key derivation

**Authentication**: Wallet private key → py-clob-client derives API key, secret, passphrase

**Fees**: Most markets fee-free for makers and takers. Exception: 15-min crypto markets have dynamic taker fees.

**Key addresses**:

```
USDCe: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
CTF: 0x4d97dcd97ec945f40cf65f87097ace5ea0476045
CTF_EXCHANGE: 0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
NEG_RISK_CTF_EXCHANGE: 0xC5d563A36AE78145C45a50134d48A1215220f80a
```

---

## 6. WEATHER STRATEGY — IMPLEMENTATION PATH

### How the Edge Works

1. **NOAA GFS/ECMWF** forecasts 24-hour temperatures with 85-90% accuracy
2. **Polymarket** crowd-sources temperature predictions, often with significant mispricing
3. **The gap**: NOAA says 43°F with high confidence. Market prices the 40-45°F range at $0.15 (15% implied). True probability: ~70%+. Edge: 55%+.
4. **Resolution is deterministic**: official weather station reading, 0.01°F precision. No UMA oracle, no challenge period, no ambiguity.

### Four Compounding Edges

1. **Model vs. Crowd Mispricing**: NOAA ensemble says 70% chance of 40-45°F range, market prices it at 15%. Buy at $0.15, collect $1.00.

2. **Forecast Latency Arbitrage**: GFS updates at 00/06/12/18 UTC, ECMWF at 00/12 UTC. When a new model run shifts the forecast by 2°F+, there's a window (minutes to hours) before market participants reprice. Bot monitors Tropical Tidbits/Windy, enters before crowd catches up.

3. **Probabilistic Distribution Errors**: Retail traders cluster on round numbers. They don't think in probability distributions. Bot uses 31-member GFS ensemble from Open-Meteo to calculate actual probability per bucket.

4. **Multi-City Diversification**: NYC, London, LA, Chicago, Seattle, Atlanta, Dallas, Miami all have active markets. Same strategy across 8+ cities = higher throughput + risk diversification.

### Weather Bot Architecture

```python
class WeatherStrategy(BaseStrategy):
    def get_signal(self) -> Signal:
        # 1. Fetch 31-member GFS ensemble from Open-Meteo
        # 2. For each temperature bucket (e.g., 40-45°F):
        #    count members in range / 31 = probability
        # 3. Return probability distribution over all buckets
        
    def calculate_edge(self, signal, market_price) -> float:
        # edge = model_probability - market_implied_probability
        # Only trade if edge > threshold (e.g., 8%)
        
    def should_trade(self, edge, confidence) -> bool:
        # Trade if: edge > 8%, liquidity > $5K, forecast < 48hrs out
        # Don't trade: forecast > 48hrs, low liquidity, low ensemble agreement
        
    def get_market_filter(self) -> dict:
        # Gamma API filter: tag="weather", active=True
```

### Reference Implementation

`suislanchez/polymarket-kalshi-weather-bot`:

- FastAPI backend
- 31-member GFS ensemble from Open-Meteo
- Kelly criterion position sizing (quarter-Kelly for safety)
- Supports both Kalshi and Polymarket
- 3D globe dashboard visualization
- Edge detection threshold: 8%

---

## 7. ESPORTS STRATEGY — IMPLEMENTATION PATH (PHASE 2)

### How the Edge Works

Esports broadcasts have a **structural 15-60 second delay** from game server to Twitch/YouTube. GRID receives data directly from game servers with sub-second latency.

```
Game server event (T=0)
  → GRID data feed (T=0.5-2s)
  → Our bot trades (T=2-5s)
  → Broadcast viewers see it (T=15-60s)
  → Market prices update (T=20-90s)
```

### Market Resolution — How It Actually Works

1. **GRID** = data provider to **Sportstensor** (Polymarket's AI market maker)
2. **Sportstensor** uses GRID data for **pricing/liquidity**, not settlement
3. **UMA Optimistic Oracle** resolves markets: proposer submits outcome + $750 bond → 2hr challenge → if undisputed (98.5% of cases), resolves
4. Our edge is in **live in-match trading**, not post-match resolution

### Data Access Paths (in order of preference)

1. **GRID Hackathon access** (if still available): LoL + VALORANT + CS2 + Dota 2, free until March 9
2. **GRID Open Access** (guaranteed): CS2 + Dota 2 only, free, 48hr approval
3. **GRID Paid tier**: All titles including LoL, but likely $10K+/year — evaluate only after proving profitability with weather + free GRID data
4. **PandaScore**: NOT viable for live trading speed edge. Only useful for historical data and backtesting.

### Open Question

Does GRID Open Access provide sufficient **live** data granularity and latency for trading? Or does it only provide historical/post-game data, with the ultra-low-latency live feed reserved for paid "Series Events" customers? This is the biggest unknown and must be tested once access is granted.

---

## 8. FUTURE EXTENSIBILITY

The system MUST be architected to support additional market types later without rewriting core infrastructure. However, we are NOT detailing, designing, or building any of the following now:

**Kalshi cross-platform support** (~1-2 weeks to add later):

- Different exchange connector (REST API, RSA auth vs Polymarket's EIP-712)
- Official Python SDK: `kalshi-python` on PyPI
- Same signal layer reusable — game/weather data is exchange-agnostic
- Cross-platform arbitrage is the big unlock (same event, different prices)
- US-legal (CFTC regulated), KYC required

**Mentions/speech markets** (future):

- Deepgram for speech-to-text with confidence scores
- $200 free credit, no credit card
- Complex resolution rules (Sanders/Greensboro case study)

**Other market types**: Crypto (NOT recommended — Polymarket added dynamic fees), politics, custom categories.

**Architecture requirement**: The `BaseStrategy` interface must be clean enough that adding a new strategy is purely additive — new files implementing the interface, no changes to shared infrastructure.

---

## 9. HUMAN PRE-WORK CHECKLIST

### PRIORITY 1 — BLOCKING (nothing works without these)

**1. Polymarket Wallet + Funding** (30-60 min, $55-105)

- Install MetaMask, create wallet, write seed phrase on paper
- Export private key (for bot's py-clob-client config)
- Add Polygon network (Chain ID 137, RPC `https://polygon-rpc.com`)
- Buy USDC on exchange (Coinbase, Kraken), withdraw on Polygon network
- Send ~$2-5 MATIC/POL for gas
- Deposit USDC on polymarket.com, make one manual trade to verify
- Starting: $50-100 USDC for testing
- **CRITICAL**: Private key in `.env`, never committed to git
- **JURISDICTIONAL WARNING**: Polymarket ToS prohibits US persons from API trading

**2. Polymarket API Credentials** (5 min, free)

- Derived programmatically from wallet signature via py-clob-client
- Claude Code writes the derivation script
- Env vars: `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, `POLYMARKET_API_PASSPHRASE`

**3. Venice.ai API Key** (5 min, $10-20 initial credit)

- Sign up at venice.ai
- Generate API key in Settings → API
- Buy initial credits ($10-20, credit card or crypto)
- Keys prefixed with `VENICE-INFERENCE-KEY-`
- Env var: `VENICE_API_KEY`

**4. Hetzner VPS** (15 min, ~$14/mo)

- hetzner.com/cloud → create account
- CCX13 (2 dedicated vCPU, 8GB RAM), Ashburn VA, Ubuntu 24.04
- Add SSH public key, note IP
- Alternative (cheaper dev): CX23 ~$4/mo

### PRIORITY 2 — NEEDED FOR DEVELOPMENT

**5. GRID Esports Access** (5 min to apply, up to 48hr wait)

- **FIRST**: Try hackathon form at grid.gg/hackathon-application-form/ (may still work — data access runs until March 9, 2026)
- **IF 404**: Email <support@grid.gg> requesting hackathon data access for remaining window
- **SIMULTANEOUSLY**: Apply for regular Open Access at grid.gg/open-access-application-form/ (CS2/Dota 2, guaranteed)
- Env var: `GRID_API_KEY`

**6. Telegram Bot** (5 min, free)

- @BotFather → /newbot → save token + chat ID
- Env vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

**7. GitHub Repo** (5 min, free)

- Private repo, .gitignore: `.env`, `*.key`, `credentials/`, `__pycache__/`

### PRIORITY 3 — NICE TO HAVE (later)

**8. Grafana Cloud** (10 min, free tier)

- grafana.com/products/cloud/ → free account
- 10K metrics, 50GB logs sufficient for our scale

**9. Deepgram** (5 min, free $200 credit) — only for future speech/mentions markets

### Environment Variables Summary

```bash
# Polymarket
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_API_KEY=...
POLYMARKET_API_SECRET=...
POLYMARKET_API_PASSPHRASE=...

# LLM (Venice.ai — OpenAI-compatible)
VENICE_API_KEY=VENICE-INFERENCE-KEY-...

# Esports Data (Phase 2)
GRID_API_KEY=...

# Monitoring
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### Monthly Cost Summary

| Item | Cost |
|------|------|
| Hetzner CCX13 | ~$14 |
| Venice.ai (est. 10K evals/day) | ~$1-5 (Qwen3 is very cheap) |
| Polymarket trading capital | $50-500 (capital, not cost) |
| Everything else | Free |
| **Total operating** | **~$15-19/month** |

---

## 10. IMPLEMENTATION PLAN — WEATHER-FIRST

### Phase 1: Foundation + Weather MVP (Week 1-2)

**Milestone 1.1: Dev Environment** (Day 1)

- Set up Hetzner VPS
- Python 3.11 venv, install dependencies
- Clone Polymarket/agents, explore codebase
- Clone suislanchez/polymarket-kalshi-weather-bot for reference
- Set up project structure with Strategy Pattern

**Milestone 1.2: Market Discovery** (Day 2-3)

- Gamma API client → fetch active weather markets
- Parse market structure (city, date, temperature ranges, resolution source)
- Test: list all active weather markets with prices

**Milestone 1.3: Weather Signal** (Day 3-5)

- Open-Meteo API client → fetch 31-member GFS ensemble
- NWS API client → fetch NOAA point forecasts
- Probability distribution calculator (ensemble members per bucket)
- Test: for NYC tomorrow, calculate probability of each temperature range

**Milestone 1.4: Edge Detection** (Day 5-7)

- Compare model probabilities to market prices
- Calculate edge per market per bucket
- Filter: edge > 8%, liquidity > $5K, forecast < 48hrs
- Venice.ai LLM validation for market wording edge cases
- Test: generate ranked list of trading opportunities with edge %

**Milestone 1.5: Paper Trading** (Day 7-10)

- Polymarket order execution (paper mode via py-clob-client)
- SQLite logging of all signals, decisions, (paper) trades
- Telegram alerts for detected opportunities
- Test: full pipeline — weather data → edge detection → paper trade → alert

**Milestone 1.6: Monitoring** (Day 10-14)

- Kill switch (daily loss limit, API error threshold)
- Performance dashboard (P&L, win rate, edge realization)
- Telegram controls (pause/resume, status check)
- Test: trigger kill switch, verify pause

### Phase 2: Weather Live Trading (Week 3-4)

**Milestone 2.1: Micro-Stakes** (Week 3)

- $50 bankroll, $5 max position
- Quarter-Kelly sizing
- Trade 1-3 opportunities per day
- 24/7 monitoring first week
- Success: 20+ real trades, verify execution matches paper

**Milestone 2.2: Scale Assessment** (Week 4)

- Compare realized edge vs expected edge
- Adjust thresholds if needed
- If profitable: increase to $250 bankroll, $10 positions
- If not: diagnose why (latency? mispricing gone? model error?)

### Phase 3: Esports Signal Layer (Week 5-7, parallel with weather)

**Milestone 3.1: GRID Integration**

- GRID API client (once access granted)
- Parse CS2/Dota 2 match data
- Evaluate: does Open Access provide live in-match data, or only historical?
- If live: build game state parser
- If not: evaluate whether hackathon access or paid tier is needed

**Milestone 3.2: Win Probability Model**

- Features: gold lead, kills, objectives, towers, time elapsed
- Historical data → logistic regression or gradient boosted model
- Backtest against historical matches + Polymarket price data

**Milestone 3.3: Esports Paper Trading**

- Match GRID events to Polymarket markets
- Full pipeline: game state → win prob → edge detection → paper trade
- Measure detection→order latency (target: <30s)

### Phase 4: Esports Live + Optimization (Week 8+)

- Micro-stakes esports trading alongside weather
- Cross-strategy portfolio management
- Continuous optimization of both strategies

### Timeline Summary

| Milestone | Timeline | Dependency |
|-----------|----------|------------|
| Weather paper trading | Week 2 | Wallet + VPS only |
| Weather live (micro) | Week 3 | Wallet funded |
| GRID access granted | Week 1-3 | Application submitted |
| Esports paper trading | Week 5-7 | GRID access + model |
| Esports live (micro) | Week 8+ | Proven edge |

---

## 11. OPEN QUESTIONS & RISKS

### GRID Data Granularity (Phase 2 blocker)

Does GRID Open Access provide live in-match data with sub-second latency, or only historical/post-game data? The paid "Series Events" feed is their premium live product. If Open Access doesn't include live data, the esports strategy may require paid GRID access ($10K+/year) to be viable.

**Mitigation**: Start with weather (no GRID dependency). Test GRID Open Access when approved. If live data isn't available on free tier, evaluate whether proven weather profits justify GRID paid tier investment.

### Weather Edge Degradation

Weather bot articles are proliferating rapidly (multiple Medium/Substack guides in Feb 2026). More competition = less mispricing. However: new casual bettors enter daily recreating inefficiencies, 8+ cities × daily markets = high throughput, and deterministic resolution means guaranteed payouts when right.

### Regulatory Risk

- Polymarket ToS prohibits US persons from API trading
- User must assess their own jurisdictional situation independently
- Kalshi (future Phase 3) is US-legal alternative

### AI-Generated Code Risk

- Must have human review of ALL order execution logic
- Paper trade extensively before live capital
- Kill switches and circuit breakers are non-negotiable

### Competition

- Weather: growing but still profitable per documented results
- Esports: moderate competition, Sportstensor is the major bot
- Polymarket has NO anti-bot measures for weather or esports markets (unlike crypto which has dynamic fees)

---

## 12. REFERENCE MATERIALS

### API Documentation

| API | URL | Auth Required |
|-----|-----|---------------|
| Polymarket CLOB | docs.polymarket.com | Yes (wallet-derived) |
| Polymarket Gamma | gamma-api.polymarket.com | No |
| Open-Meteo Ensemble | open-meteo.com/en/docs/ensemble-api | No |
| NOAA/NWS | api.weather.gov | No |
| Venice.ai | docs.venice.ai | Yes (API key) |
| GRID | grid.gg/knowledge-hub/ | Yes (API key) |
| py-clob-client | pypi.org/project/py-clob-client/ | — |
| kalshi-python (future) | pypi.org/project/kalshi-python/ | — |

### Previous Research Transcripts

Full deep-dive research behind every decision:

| File | Contents |
|------|----------|
| `/mnt/transcripts/2026-02-18-15-12-25-prediction-market-bot-planning.txt` | Initial architecture |
| `/mnt/transcripts/2026-02-18-15-54-36-prediction-market-bot-deep-research.txt` | Providers, hosting, monitoring |
| `/mnt/transcripts/2026-02-18-16-02-01-polymarket-oracle-mechanics-deep-dive.txt` | UMA resolution mechanics |
| `/mnt/transcripts/2026-02-18-16-06-29-polymarket-bot-deep-research-nine-questions.txt` | 9 deep questions: GRID/UMA, data, Deepgram, LLMs, bots, extensibility |

### Key Learnings That Shaped the Plan

1. **Weather before esports**: No approval wait, free data, simpler model, same execution layer, documented profits. De-risks the project.

2. **PandaScore is NOT viable for live trading**: Scrapes broadcast streams (court-confirmed). 300ms latency "from stream" means it arrives at the same time as viewers. Only GRID has game-server-direct data.

3. **GRID hackathon = potential LoL/VALORANT fast track**: Data access runs until March 9, 2026. Worth trying even though submissions closed Feb 3.

4. **Venice.ai replaces direct LLM API keys**: Single provider, OpenAI-compatible, supports Gemini/Claude/GPT through one API. Qwen3 235B at $0.15/1M input tokens handles 90% of decisions.

5. **Strategy Pattern is non-negotiable**: Weather and esports share 60% of code. Future market types (Kalshi, mentions) must be additive, not require rewrites.

6. **Polymarket fights crypto arb but NOT weather/esports**: Dynamic fees only on 15-min crypto markets. Weather and esports remain fee-free.

7. **Resolution is the hidden complexity**: NOAA thermometer (weather) vs UMA oracle (esports). Weather's deterministic resolution is a major advantage.

---

## FIRST SESSION INSTRUCTIONS FOR CLAUDE CODE

1. **Set up Hetzner VPS** (user provides IP + SSH key)
2. **Install Python 3.11, Node.js, git, pip dependencies**
3. **Clone Polymarket/agents** and **suislanchez/polymarket-kalshi-weather-bot**
4. **Build minimal Gamma API client** — fetch active weather markets (zero auth needed)
5. **Build Open-Meteo ensemble client** — fetch 31-member GFS data for NYC
6. **Set up project structure** with BaseStrategy interface and WeatherStrategy skeleton
7. **Implement edge detection** — compare ensemble probabilities to market prices
8. **Paper trading mode** with CLOB client (once user provides wallet credentials)

Weather strategy can reach paper-trading state in ~1 week. GRID integration (esports) starts whenever access is approved, running in parallel.
