---
name: polymarket-data-api
description: >
  Use this skill for querying Polymarket user positions, trade history, on-chain activity,
  market holders, leaderboard data, and portfolio analysis. The Data API is the intelligence-
  gathering API — use it to see what whales hold, who's entering/exiting positions, smart
  money flows, and market participant behavior. No authentication required.
---

# Polymarket Data API Skill

## Overview

The Data API provides user-specific and market-participant data from Polymarket. It indexes
on-chain activity (trades, splits, merges, redemptions) and provides portfolio analysis
endpoints. This is your primary tool for **intelligence gathering** — understanding who
holds what, where money is flowing, and how the market's participants behave.

**Base URL:** `https://data-api.polymarket.com`
**Authentication:** None required for reading

### Official Documentation Links

- Positions: <https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user>
- Trades: <https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets>
- Activity: <https://docs.polymarket.com/api-reference/core/get-user-activity>
- Top Holders: <https://docs.polymarket.com/api-reference/core/get-top-holders-for-markets>
- Portfolio Value: <https://docs.polymarket.com/api-reference/core/get-total-value-of-a-users-positions>
- Closed Positions: <https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user>
- Leaderboard: <https://docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings>
- Open Interest: <https://docs.polymarket.com/api-reference/misc/get-open-interest>
- Live Volume: <https://docs.polymarket.com/api-reference/misc/get-live-volume-for-an-event>
- Rate Limits: <https://docs.polymarket.com/api-reference/rate-limits>
- Endpoints Quick Reference: <https://docs.polymarket.com/quickstart/reference/endpoints>

---

## Core Endpoints

### 1. GET /positions — User Positions

_Source: <https://docs.polymarket.com/api-reference/core/get-current-positions-for-a-user>_

Fetch current open positions for a given wallet address.

```bash
curl "https://data-api.polymarket.com/positions?user=0x56687bf447db6ffa42ffe2204a05edaa20f55839&sizeThreshold=50"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user` | string | **Yes** | User Profile Address (0x-prefixed, 40 hex chars) |
| `market` | string[] | No | Comma-separated condition IDs. **Mutually exclusive with `eventId`** |
| `eventId` | integer[] | No | Comma-separated event IDs. **Mutually exclusive with `market`** |
| `sizeThreshold` | number | No | Minimum position size (default: 1.0, min: 0) |
| `redeemable` | boolean | No | Only redeemable positions (default: false) |
| `mergeable` | boolean | No | Only mergeable positions (default: false) |
| `limit` | integer | No | Results per page (default: 100, max: 500) |
| `offset` | integer | No | Pagination offset (default: 0, max: 10000) |
| `sortBy` | enum | No | Sort field (default: `TOKENS`) |
| `sortDirection` | enum | No | `ASC` or `DESC` (default: `DESC`) |
| `title` | string | No | Filter by title (max 100 chars) |

**Sort options for `sortBy`:**

- `TOKENS` — position size (shares held)
- `CURRENT` — current value
- `INITIAL` — initial investment value
- `CASHPNL` — cash profit/loss
- `PERCENTPNL` — percentage profit/loss
- `TITLE` — market title
- `RESOLVING` — when the market resolves
- `PRICE` — current price
- `AVGPRICE` — average entry price

**Response:**

```json
[
  {
    "proxyWallet": "0x56687bf4...",
    "asset": "65396714035...",
    "conditionId": "0xdd22472e...",
    "size": 90548.087076,
    "avgPrice": 0.020628,
    "initialValue": 1867.83,
    "currentValue": 5840.35,
    "cashPnl": 3972.53,
    "percentPnl": 212.68,
    "totalBought": 109548.08,
    "realizedPnl": -894.40,
    "percentRealizedPnl": -12.5,
    "curPrice": 0.0645,
    "redeemable": false,
    "mergeable": false,
    "title": "Market question text",
    "slug": "market-slug",
    "icon": "https://polymarket-upload.s3...",
    "eventSlug": "event-slug",
    "outcome": "Yes",
    "outcomeIndex": 0,
    "oppositeOutcome": "No",
    "oppositeAsset": "52050340002...",
    "endDate": "2025-12-31T23:59:59Z",
    "negativeRisk": false
  }
]
```

### 2. GET /closed-positions — Closed Positions

_Source: <https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user>_

Get historical closed positions for a user.

```bash
curl "https://data-api.polymarket.com/closed-positions?user=0x..."
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user` | string | **Yes** | User Profile Address (0x-prefixed, 40 hex chars) |
| `market` | string[] | No | Comma-separated condition IDs. **Mutually exclusive with `eventId`** |
| `eventId` | integer[] | No | Comma-separated event IDs. **Mutually exclusive with `market`** |
| `title` | string | No | Filter by title (max 100 chars) |
| `limit` | integer | No | Results per page (default: **10**, max: **50**) |
| `offset` | integer | No | Pagination offset (default: 0, max: **100,000**) |
| `sortBy` | enum | No | Sort field (default: `REALIZEDPNL`) |
| `sortDirection` | enum | No | `ASC` or `DESC` (default: `DESC`) |

**Sort options for `sortBy`:**

- `REALIZEDPNL` — realized profit/loss
- `TITLE` — market title
- `PRICE` — final price
- `AVGPRICE` — average entry price
- `TIMESTAMP` — when position was closed

### 3. GET /trades — Trade History (Public)

_Source: <https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets>_

Fetch trades for a user or for specific markets. **No authentication required** (unlike the CLOB `/data/trades` endpoint which requires L2 auth).

```bash
# Trades for a specific user
curl "https://data-api.polymarket.com/trades?user=0x..."

# Trades for a specific market
curl "https://data-api.polymarket.com/trades?market=CONDITION_ID"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user` | string | No | Wallet address |
| `market` | string[] | No | Condition ID (comma-separated). **Mutually exclusive with `eventId`** |
| `eventId` | integer[] | No | Event IDs (comma-separated). **Mutually exclusive with `market`** |
| `limit` | integer | No | Results per page (default: 100, max: 10,000) |
| `offset` | integer | No | Pagination offset (default: 0, max: 10,000) |
| `takerOnly` | boolean | No | Return only taker orders (default: true) |
| `filterType` | string | No | `CASH` or `TOKENS` (requires `filterAmount`) |
| `filterAmount` | number | No | Amount threshold (requires `filterType`) |
| `side` | string | No | `BUY` or `SELL` |
| `sortBy` | string | No | `TIMESTAMP`, `TOKENS`, or `CASH` |
| `sortDirection` | string | No | `ASC` or `DESC` |

### 4. GET /activity — On-Chain Activity

_Source: <https://docs.polymarket.com/api-reference/core/get-user-activity>_

Returns all on-chain activity for a user, including trades, splits, merges, redemptions, rewards, conversions, and maker rebates.

```bash
curl "https://data-api.polymarket.com/activity?user=0x..."
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user` | string | **Yes** | Wallet address |
| `market` | string[] | No | Condition ID filter (comma-separated). **Mutually exclusive with `eventId`** |
| `eventId` | integer[] | No | Event ID filter (comma-separated). **Mutually exclusive with `market`** |
| `type` | string | No | Activity type filter (comma-separated) |
| `start` | integer | No | Start timestamp (seconds) |
| `end` | integer | No | End timestamp (seconds) |
| `side` | string | No | `BUY` or `SELL` (trades only) |
| `limit` | integer | No | Results per page (default: 100, max: 500) |
| `offset` | integer | No | Pagination offset (default: 0, max: 10,000) |
| `sortBy` | string | No | `TIMESTAMP`, `TOKENS`, or `CASH` (default: `TIMESTAMP`) |
| `sortDirection` | string | No | `ASC` or `DESC` (default: `DESC`) |

**Activity type values:** `TRADE`, `SPLIT`, `MERGE`, `REDEEM`, `REWARD`, `CONVERSION`, `MAKER_REBATE`

### 5. GET /holders — Top Holders

_Source: <https://docs.polymarket.com/api-reference/core/get-top-holders-for-markets>_

Get the top holders for a specific market.

```bash
curl "https://data-api.polymarket.com/holders?market=CONDITION_ID"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `market` | string[] | **Yes** | Comma-separated condition IDs (Hash64 format) |
| `limit` | integer | No | Max holders per token (default: 20, **max: 20**) |
| `minBalance` | integer | No | Minimum balance threshold (default: 1, max: 999,999) |

**Response:**

```json
[
  {
    "token": "asset_id",
    "holders": [
      {
        "proxyWallet": "0x...",
        "amount": 50000.0,
        "pseudonym": "Ironclad-Tenement",
        "name": "Trader123",
        "bio": "...",
        "profileImage": "https://...",
        "asset": "...",
        "outcomeIndex": 0,
        "displayUsernamePublic": true
      }
    ]
  }
]
```

### 6. GET /value — Total Position Value

_Source: <https://docs.polymarket.com/api-reference/core/get-total-value-of-a-users-positions>_

Get the total value of a user's positions across all markets.

```bash
curl "https://data-api.polymarket.com/value?user=0x..."
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `user` | string | **Yes** | Wallet address |
| `market` | string[] | No | Filter to specific condition IDs |

**Response:**

```json
[
  {
    "user": "0x...",
    "value": 12345.67
  }
]
```

### 7. GET /v1/leaderboard — Trader Leaderboard

_Source: <https://docs.polymarket.com/api-reference/core/get-trader-leaderboard-rankings>_

Get top traders ranked by profit or volume.

```bash
curl "https://data-api.polymarket.com/v1/leaderboard?category=WEATHER&timePeriod=WEEK&limit=10"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `category` | string | No | Category filter (default: `OVERALL`) |
| `timePeriod` | string | No | Time period (default: `DAY`) |
| `orderBy` | string | No | `PNL` or `VOL` (default: `PNL`) |
| `limit` | integer | No | Results per page (default: 25, max: 50) |
| `offset` | integer | No | Pagination offset (default: 0, max: 1000) |
| `user` | string | No | Filter by specific user address |
| `userName` | string | No | Filter by username |

**Category options:** `OVERALL`, `POLITICS`, `SPORTS`, `CRYPTO`, `CULTURE`, `MENTIONS`, `WEATHER`, `ECONOMICS`, `TECH`, `FINANCE`

**Time period options:** `DAY`, `WEEK`, `MONTH`, `ALL`

**Response:**

```json
[
  {
    "rank": "1",
    "proxyWallet": "0x...",
    "userName": "TopTrader",
    "vol": 1214895.14,
    "pnl": 545434.52,
    "profileImage": "https://...",
    "xUsername": "trader_x",
    "verifiedBadge": true
  }
]
```

### 8. GET /traded — Markets Traded Count

_Source: <https://docs.polymarket.com/api-reference/misc/get-total-markets-a-user-has-traded>_

Get the total number of markets a user has traded.

```bash
curl "https://data-api.polymarket.com/traded?user=0x..."
```

**Response:**

```json
{
  "user": "0x...",
  "traded": 42
}
```

### 9. GET /v1/market-positions — Market Positions by Condition ID

Get all positions for a specific market (by condition ID). Useful for analyzing who holds positions in a market.

```bash
curl "https://data-api.polymarket.com/v1/market-positions?market=CONDITION_ID"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `market` | string | **Yes** | Condition ID (Hash64 format) |
| `limit` | integer | No | Results per page |
| `offset` | integer | No | Pagination offset |

**Response:**

Returns an array of position objects showing all holders in the market.

---

## Misc Endpoints

### GET /oi — Open Interest

_Source: <https://docs.polymarket.com/api-reference/misc/get-open-interest>_

```bash
curl "https://data-api.polymarket.com/oi?market=CONDITION_ID"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `market` | string[] | No | Comma-separated condition IDs (Hash64 format) |

**Response:**

```json
[
  {
    "market": "0xdd22472e...",
    "value": 158026.20
  }
]
```

### GET /live-volume — Live Volume for Event

_Source: <https://docs.polymarket.com/api-reference/misc/get-live-volume-for-an-event>_

```bash
curl "https://data-api.polymarket.com/live-volume?id=12345"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `id` | integer | **Yes** | Event ID (must be >= 1) |

**Response:**

```json
{
  "total": 50000.0,
  "markets": [
    {
      "market": "0x...",
      "value": 25000.0
    }
  ]
}
```

---

## Builder Endpoints

For developers in the Polymarket Builders Program:

### GET /v1/builders/leaderboard — Builder Leaderboard

```bash
curl "https://data-api.polymarket.com/v1/builders/leaderboard?timePeriod=WEEK&limit=10"
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `timePeriod` | string | No | `DAY`, `WEEK`, `MONTH`, `ALL` (default: `DAY`) |
| `limit` | integer | No | Max results (default: 25, max: 50) |
| `offset` | integer | No | Pagination offset (default: 0, max: 1000) |

**Response:**

```json
[
  {
    "rank": "1",
    "builder": "betmoar",
    "volume": 3822015.04,
    "activeUsers": 113,
    "verified": true,
    "builderLogo": "https://..."
  }
]
```

### GET /v1/builders/volume — Builder Volume Time Series

```bash
curl "https://data-api.polymarket.com/v1/builders/volume"
```

Returns daily volume time series data for builders.

---

## Profile Endpoint (Gamma API)

**NOTE:** User profiles are on the **Gamma API**, not the Data API.

### GET /public-profile — Public Profile

_Source: <https://docs.polymarket.com/api-reference/profiles/get-public-profile-by-wallet-address>_

**Base URL:** `https://gamma-api.polymarket.com`

```bash
curl "https://gamma-api.polymarket.com/public-profile?address=0x..."
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `address` | string | **Yes** | Wallet address (0x-prefixed, 40 hex chars) |

**Response:**

```json
{
  "createdAt": "2024-10-14T04:57:11.603626Z",
  "proxyWallet": "0x...",
  "displayUsernamePublic": true,
  "pseudonym": "Ironclad-Tenement",
  "name": "Theo4",
  "bio": "...",
  "profileImage": "https://...",
  "xUsername": "trader_x",
  "verifiedBadge": false,
  "users": [
    {"id": "902314", "creator": false, "mod": false}
  ]
}
```

---

## Rate Limits

_Source: <https://docs.polymarket.com/api-reference/rate-limits>_

Rate limits use Cloudflare throttling (delayed/queued, not rejected).

| Endpoint | Limit |
|---|---|
| General (all Data API) | **1,000 req / 10s** |
| `/trades` | **200 req / 10s** |
| `/positions` | **150 req / 10s** |
| `/closed-positions` | **150 req / 10s** |
| Health check (`/ok`) | **100 req / 10s** |

---

## Intelligence Gathering Workflows

### Workflow 1: Smart Money Tracking

Identify what top traders are doing in a specific market:

```python
import requests
import time

# Step 1: Get top holders of a market
holders = requests.get(
    "https://data-api.polymarket.com/holders",
    params={"market": CONDITION_ID, "limit": 20}
).json()

# Step 2: For each top holder, check their full portfolio
for holder_group in holders:
    for holder in holder_group.get("holders", []):
        positions = requests.get(
            "https://data-api.polymarket.com/positions",
            params={"user": holder["proxyWallet"], "sizeThreshold": 100}
        ).json()
        time.sleep(0.1)  # be respectful of 150 req/10s limit on /positions
```

### Workflow 2: Market Activity Analysis

Monitor trading activity in a specific market to detect unusual volume:

```python
import time

# Get recent trades for a market
trades = requests.get(
    "https://data-api.polymarket.com/trades",
    params={
        "market": CONDITION_ID,
        "start": int(time.time()) - 3600,  # last hour
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC"
    }
).json()

# Analyze trade patterns
total_volume = sum(t.get("usdcSize", 0) for t in trades)
buy_volume = sum(t.get("usdcSize", 0) for t in trades if t.get("side") == "BUY")
sell_volume = sum(t.get("usdcSize", 0) for t in trades if t.get("side") == "SELL")
```

### Workflow 3: Whale Alert System

Track large position changes by monitoring top leaderboard wallets:

```python
# Get leaderboard (note: /v1/leaderboard path)
leaders = requests.get(
    "https://data-api.polymarket.com/v1/leaderboard",
    params={"timePeriod": "WEEK", "limit": 20}
).json()

# For each top trader, check recent activity
for trader in leaders[:20]:
    activity = requests.get(
        "https://data-api.polymarket.com/activity",
        params={
            "user": trader["proxyWallet"],
            "type": "TRADE",
            "start": int(time.time()) - 86400,  # last 24h
            "sortBy": "CASH",
            "sortDirection": "DESC"
        }
    ).json()
    time.sleep(0.1)
```

### Workflow 4: Bot Detection

Identify likely bot traders by analyzing activity patterns:

```python
activity = requests.get(
    "https://data-api.polymarket.com/activity",
    params={
        "user": SUSPECT_ADDRESS,
        "type": "TRADE",
        "sortBy": "TIMESTAMP"
    }
).json()

# Analyze patterns
timestamps = [a["timestamp"] for a in activity]
intervals = [timestamps[i] - timestamps[i+1] for i in range(len(timestamps)-1)]
# Bots tend to have very consistent intervals and trade sizes
if intervals:
    avg_interval = sum(intervals) / len(intervals)
    std_interval = (sum((x - avg_interval)**2 for x in intervals) / len(intervals)) ** 0.5
    # Low std relative to avg = likely bot
```

---

## Key Fields Reference

### Position Fields

| Field | Description |
|---|---|
| `size` | Number of tokens/shares held |
| `avgPrice` | Average entry price |
| `initialValue` | Total invested (USDC) |
| `currentValue` | Current position value |
| `cashPnl` | Unrealized P&L in USDC |
| `percentPnl` | Unrealized P&L as percentage |
| `realizedPnl` | Realized P&L from closed portions |
| `percentRealizedPnl` | Realized P&L as percentage |
| `curPrice` | Current market price |
| `redeemable` | Whether position can be redeemed |
| `mergeable` | Whether position can be merged |
| `outcomeIndex` | 0 for Yes, 1 for No |
| `negativeRisk` | Whether this is a negative risk market |

### Activity Types

| Type | Description |
|---|---|
| `TRADE` | Buy or sell on the CLOB |
| `SPLIT` | Split 1 USDC → 1 YES + 1 NO |
| `MERGE` | Merge 1 YES + 1 NO → 1 USDC |
| `REDEEM` | Redeem winning tokens after resolution |
| `REWARD` | Liquidity reward claim |
| `CONVERSION` | Negative risk conversion (NO → YES across markets) |
| `MAKER_REBATE` | Rebate for providing liquidity as a maker |

---

## Best Practices

1. **Use `sizeThreshold`** to filter out dust positions
2. **Combine with Gamma API** — Data API gives user/holder data, Gamma gives market metadata and profiles
3. **Respect rate limits** — `/positions` is 150 req/10s, add small delays when scanning many wallets
4. **Monitor CONVERSION activity** — signals sophisticated traders exploiting negative risk inefficiencies
5. **Track SPLIT and MERGE activity** — high split/merge activity indicates market making or arbitrage bots
6. **Use condition IDs consistently** — the `market` parameter takes condition IDs (same as CLOB API)
7. **`market` and `eventId` are mutually exclusive** — use one or the other, not both
8. **Leaderboard uses `/v1/` prefix** — don't forget the version prefix for leaderboard endpoints
9. **Profiles are on Gamma API** — use `gamma-api.polymarket.com` for profile lookups, not `data-api`
10. **Holders limit capped at 20** — you can only get top 20 holders per request
