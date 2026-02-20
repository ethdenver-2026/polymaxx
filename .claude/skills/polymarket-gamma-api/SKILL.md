---
name: polymarket-gamma-api
description: >
  Use this skill for all Polymarket market discovery, metadata retrieval, categorization,
  and event/market browsing tasks. The Gamma API is the primary read-only API for finding
  what's tradeable on Polymarket. Use it to list events, markets, tags, sports, and series.
  No authentication required for any Gamma endpoint.
---

# Polymarket Gamma API Skill

## Overview

The Gamma API is Polymarket's hosted service that indexes on-chain market data and provides
enriched metadata including categorization, volume stats, and resolution information. It is
**read-only** and requires **no authentication**.

**Base URL:** `https://gamma-api.polymarket.com`

### Official Documentation Links
- Overview: https://docs.polymarket.com/developers/gamma-markets-api/overview
- Gamma Structure: https://docs.polymarket.com/developers/gamma-markets-api/gamma-structure
- Fetching Markets Guide: https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide
- API Reference (Events): https://docs.polymarket.com/api-reference/events/list-events
- API Reference (Markets): https://docs.polymarket.com/api-reference/markets/list-markets
- API Reference (Search): https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles
- API Reference (Tags): https://docs.polymarket.com/api-reference/tags/list-tags
- Rate Limits: https://docs.polymarket.com/api-reference/rate-limits
- Endpoints Quick Reference: https://docs.polymarket.com/quickstart/reference/endpoints

---

## Data Model

Polymarket structures data hierarchically:

```
Series (optional grouping, e.g. "NBA 2025")
  └── Event (a question, e.g. "Will Bitcoin reach $100k?")
       └── Market(s) (tradable binary outcomes within the event)
            └── Outcomes & Prices (Yes/No with implied probabilities)
```

### Key Identifiers
- **Event ID** — numeric ID for an event
- **Event Slug** — human-readable URL identifier (found in Polymarket URLs after `/event/`)
- **Market ID** — numeric ID for a specific market
- **Condition ID** (`conditionId`) — on-chain identifier linking to the CTF (Conditional Token Framework)
- **Token IDs** (`clobTokenIds`) — the YES and NO token IDs needed for CLOB API price/order operations
- **Tag ID** — numeric category identifier

### Event Object (key fields)
_Source: https://docs.polymarket.com/api-reference/events/list-events_

```json
{
  "id": "123456",
  "slug": "will-bitcoin-reach-100k-by-2025",
  "title": "Will Bitcoin reach $100k by 2025?",
  "description": "...",
  "resolutionSource": "CoinGecko",
  "active": true,
  "closed": false,
  "negRisk": false,
  "negRiskMarketID": "",
  "volume": 1500000,
  "volume24hr": 50000,
  "volume1wk": 200000,
  "volume1mo": 800000,
  "liquidity": 250000,
  "liquidityClob": 250000,
  "openInterest": 180000,
  "commentCount": 42,
  "startDate": "2025-01-01T00:00:00Z",
  "endDate": "2025-12-31T23:59:59Z",
  "tags": [{ "id": "21", "label": "Crypto", "slug": "crypto" }],
  "markets": [ /* array of Market objects */ ],
  "series": [ /* array of Series objects if applicable */ ]
}
```

**IMPORTANT:** Events have a top-level `resolutionSource` field. This is the primary way to identify what data source resolves the market — much easier than parsing the description text.

### Market Object (key fields)
_Source: https://docs.polymarket.com/api-reference/markets/get-market-by-id_

```json
{
  "id": "789",
  "question": "Will Bitcoin reach $100k by 2025?",
  "conditionId": "0x...",
  "slug": "will-bitcoin-reach-100k-by-2025",
  "resolutionSource": "CoinGecko",
  "clobTokenIds": "[\"TOKEN_YES_ID\", \"TOKEN_NO_ID\"]",
  "outcomes": "[\"Yes\", \"No\"]",
  "outcomePrices": "[\"0.65\", \"0.35\"]",
  "volume": "1500000",
  "volume24hr": 50000,
  "volume1wk": 200000,
  "volume1mo": 800000,
  "liquidity": "250000",
  "description": "This market resolves to Yes if...",
  "active": true,
  "closed": false,
  "acceptingOrders": true,
  "secondsDelay": 0,
  "bestBid": 0.64,
  "bestAsk": 0.66,
  "lastTradePrice": 0.65,
  "spread": 0.02,
  "oneDayPriceChange": -0.02,
  "oneHourPriceChange": 0.01,
  "oneWeekPriceChange": 0.05,
  "negRisk": false,
  "negRiskOther": false,
  "startDate": "2025-01-01T00:00:00Z",
  "endDate": "2025-12-31T23:59:59Z",
  "makerBaseFee": 0,
  "takerBaseFee": 0,
  "orderPriceMinTickSize": 0.01,
  "orderMinSize": 5,
  "automaticallyResolved": false,
  "competitive": 50,
  "rewardsMinSize": 20,
  "rewardsMaxSpread": 0.03,
  "tags": [{ "id": "21", "label": "Crypto", "slug": "crypto" }]
}
```

**IMPORTANT:** `outcomes`, `outcomePrices`, and `clobTokenIds` are JSON-encoded strings (not arrays). Parse them:
```python
import json
outcomes = json.loads(market["outcomes"])           # ["Yes", "No"]
prices = json.loads(market["outcomePrices"])        # ["0.65", "0.35"]
token_ids = json.loads(market["clobTokenIds"])      # ["TOKEN_YES_ID", "TOKEN_NO_ID"]
```

**For opportunity scanning:** The `bestBid`, `bestAsk`, `lastTradePrice`, `spread`, and `oneDayPriceChange` fields on market objects give you immediate pricing data without needing to call the CLOB API separately.

---

## Core Endpoints

### 1. GET /events — List Events
_Source: https://docs.polymarket.com/api-reference/events/list-events_

The primary endpoint for market discovery. Events contain their associated markets.

**Query Parameters:**
| Parameter | Type | Description |
|---|---|---|
| `active` | boolean | Filter for active events |
| `closed` | boolean | Filter for closed/open events |
| `tag_id` | integer | Filter by category tag ID |
| `series_id` | integer | Filter by series (e.g. a sports league) |
| `slug` | string | Get a specific event by slug |
| `order` | string | Sort field (e.g. `id`, `volume24hr`, `startTime`) |
| `ascending` | boolean | Sort direction |
| `limit` | integer | Results per page |
| `offset` | integer | Pagination offset (0-based) |
| `related_tags` | boolean | Include related tag markets |

**Example — All active events, newest first:**
```bash
curl "https://gamma-api.polymarket.com/events?active=true&closed=false&order=id&ascending=false&limit=100"
```

**Example — Get a specific event by slug (two methods):**
_Source: https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide_
```bash
# Query parameter method
curl "https://gamma-api.polymarket.com/events?slug=fed-decision-in-october"

# Path endpoint method (recommended)
curl "https://gamma-api.polymarket.com/events/slug/fed-decision-in-october"
```

**Example — Events filtered by tag:**
```bash
curl "https://gamma-api.polymarket.com/events?tag_id=21&active=true&closed=false&limit=50"
```

### 2. GET /events/{id} — Get Event by ID
_Source: https://docs.polymarket.com/api-reference/events/get-event-by-id_

```bash
curl "https://gamma-api.polymarket.com/events/123456"
```

### 3. GET /events/{id}/tags — Get Event Tags
_Source: https://docs.polymarket.com/api-reference/events/get-event-tags_

```bash
curl "https://gamma-api.polymarket.com/events/123456/tags"
```

### 4. GET /markets — List Markets
_Source: https://docs.polymarket.com/api-reference/markets/list-markets_

Returns individual markets (not grouped by event). Supports same filtering as `/events` plus:
| Parameter | Type | Description |
|---|---|---|
| `condition_id` | string | Filter by on-chain condition ID |

### 5. GET /markets/{id} and /markets/slug/{slug} — Get Market
_Source: https://docs.polymarket.com/api-reference/markets/get-market-by-id_

### 6. GET /tags — List Tags (Categories)
_Source: https://docs.polymarket.com/api-reference/tags/list-tags_

Additional tag endpoints:
- `GET /tags/{id}` — Get tag by ID
- `GET /tags/slug/{slug}` — Get tag by slug

```bash
curl "https://gamma-api.polymarket.com/tags?limit=100"
```

**Known Major Tag IDs:**
| Category | tag_id |
|---|---|
| Politics | 2 |
| Finance | 120 |
| Crypto | 21 |
| Games (Sports) | 100639 |
| Tech | 1401 |
| Culture | 596 |
| Geopolitics | 100265 |

### 7. GET /sports — Sports Metadata
_Source: https://docs.polymarket.com/api-reference/sports/get-sports-metadata-information_

Returns metadata for automated sports leagues. Additional endpoints:
- `GET /sports/market-types` — Valid market types (spreads, totals, moneyline, etc.)
- `GET /sports/teams?sport={sport}` — List teams (requires `sport` param, e.g. `nba`, `nfl`, `epl`)

### 8. GET /series — List Series
_Source: https://docs.polymarket.com/api-reference/series/list-series_

Series group related events (e.g. all NBA games, all Fed meetings).
- `GET /series/{id}` — Get series by ID

### 9. GET /public-search — Search Markets
_Source: https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles_

Full-text search across markets, events, and profiles. Returns structured results.

```bash
curl "https://gamma-api.polymarket.com/public-search?q=earthquake"
```

**NOTE:** The endpoint is `/public-search`, NOT `/search`. The query parameter is `q`, NOT `query`.

### 10. Health Check

The root endpoint `GET /` returns 200 OK. There is no `/ok`, `/health`, or `/healthz` endpoint.

```bash
curl -o /dev/null -w "%{http_code}" "https://gamma-api.polymarket.com/"
# Returns: 200
```

---

## Pagination

All list endpoints support `limit` and `offset`:

```bash
# Page 1
curl "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=50&offset=0"
# Page 2
curl "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=50&offset=50"
```

Loop with increasing offset until you receive an empty array to paginate all results.

---

## Rate Limits
_Source: https://docs.polymarket.com/api-reference/rate-limits_

Rate limits use Cloudflare throttling — requests over the limit are **delayed/queued**, not rejected.

| Endpoint | Limit |
|---|---|
| General (all Gamma) | **4,000 req / 10s** |
| `/events` | **500 req / 10s** |
| `/markets` | **300 req / 10s** |
| `/markets` + `/events` combined | **900 req / 10s** |
| `/comments` | **200 req / 10s** |
| `/tags` | **200 req / 10s** |
| `/public-search` | **350 req / 10s** |

These limits are generous. For typical scanning, you won't hit them.

---

## Negative Risk Events
_Source: https://docs.polymarket.com/developers/neg-risk/overview_

Events with `negRisk: true` are "winner-take-all" multi-outcome events where:
- Only one outcome can win
- All outcomes are mutually exclusive and exhaustive
- A NO share in any market can be converted to 1 YES share in all other markets
- The sum of all YES prices should theoretically equal $1.00

Markets with `negRiskOther: true` have an "Other" catch-all outcome.

**For arbitrage scanning:** If the sum of YES prices across all markets in a negRisk event is significantly != $1.00, there may be a Dutch Book opportunity.

---

## Resolution Source Extraction
_Source: https://docs.polymarket.com/developers/resolution/UMA_

Both Event and Market objects have a top-level `resolutionSource` field — the easiest way to identify the authoritative data source.

For detailed resolution criteria, parse the market `description` field which contains:
- What oracle resolves the market (UMA, or automated)
- The specific resolution source and URL
- The resolution criteria (threshold, date, condition)

Markets with `automaticallyResolved: true` use automated resolution (faster). Others use the UMA oracle system (human-proposed, slower — typically hours).

---

## Best Practices
_Source: https://docs.polymarket.com/developers/gamma-markets-api/fetch-markets-guide_

1. **Use `active=true&closed=false`** for discovery (recommended by official docs)
2. **Use the events endpoint for discovery** — events contain nested markets, reducing API calls
3. **Use slug for specific lookups** — `GET /events/slug/{slug}` is most direct
4. **Use tag filtering** to reduce API calls for category browsing
5. **Check `resolutionSource`** on both events and markets for data source identification
6. **Extract `clobTokenIds`** from market objects — needed for CLOB API operations
7. **Use `bestBid`, `bestAsk`, `spread`** on market objects for quick pricing
8. **Cache tag data** — tags change infrequently
