---
name: polymarket-clob-api
description: >
  Use this skill for all Polymarket pricing, orderbook, and trading operations. The CLOB 
  (Central Limit Order Book) API provides real-time prices, orderbook depth, midpoint prices, 
  spreads, historical timeseries data, and order placement/management. Public read endpoints 
  require no auth. Order management requires EIP-712 signed credentials (L2 headers).
---

# Polymarket CLOB API Skill

## Overview

The CLOB (Central Limit Order Book) is Polymarket's hybrid-decentralized trading system. It uses
an off-chain operator for order matching with on-chain settlement via signed order messages on the
Polygon blockchain.

**Base URL:** `https://clob.polymarket.com`
**WebSocket:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`
**Chain:** Polygon Mainnet (Chain ID: 137)

### Official Documentation Links

- CLOB Introduction: <https://docs.polymarket.com/developers/CLOB/introduction>
- Authentication: <https://docs.polymarket.com/developers/CLOB/authentication>
- Public Methods: <https://docs.polymarket.com/developers/CLOB/clients/methods-public>
- L2 Methods (Trading): <https://docs.polymarket.com/developers/CLOB/clients/methods-l2>
- WebSocket Market Channel: <https://docs.polymarket.com/developers/CLOB/websocket/market-channel>
- WebSocket User Channel: <https://docs.polymarket.com/developers/CLOB/websocket/user-channel>
- Rate Limits: <https://docs.polymarket.com/api-reference/rate-limits>
- Changelog: <https://docs.polymarket.com/changelog/changelog>
- Endpoints Quick Reference: <https://docs.polymarket.com/quickstart/reference/endpoints>

---

## Authentication Levels

_Source: <https://docs.polymarket.com/developers/CLOB/authentication>_

| Level | What You Can Do | Requirements |
|---|---|---|
| **Public** (no auth) | Read prices, orderbooks, market data | None |
| **L1** (private key) | Create/derive API keys | Wallet private key |
| **L2** (API key) | Place orders, cancel orders, view trades | API key + secret + passphrase |
| **Builder** | Route orders for users, gasless transactions | Builder program credentials |

**For research and analysis, only Public methods are needed.**

---

## Public REST Endpoints (No Auth Required)

_Source: <https://docs.polymarket.com/developers/CLOB/clients/methods-public>_

### Single-Token Endpoints

#### GET /price — Current Price

_Ref: <https://docs.polymarket.com/api-reference/market-data/get-market-price>_

```bash
curl "https://clob.polymarket.com/price?token_id=YOUR_TOKEN_ID&side=buy"
```

| Parameter | Type | Required | Description |
|---|---|---|---|
| `token_id` | string | Yes | The CLOB token ID (from Gamma API's `clobTokenIds`) |
| `side` | string | Yes | `buy` or `sell` |

**Response:** `{ "price": "0.65" }`

#### GET /book — Orderbook

_Ref: <https://docs.polymarket.com/api-reference/market-data/get-order-book>_

```bash
curl "https://clob.polymarket.com/book?token_id=YOUR_TOKEN_ID"
```

**Response:**

```json
{
  "market": "0x1b6f76e5...",
  "asset_id": "YOUR_TOKEN_ID",
  "timestamp": "1706000000000",
  "hash": "0xabc123...",
  "bids": [
    { "price": "0.64", "size": "500" },
    { "price": "0.63", "size": "1200" }
  ],
  "asks": [
    { "price": "0.66", "size": "300" },
    { "price": "0.67", "size": "800" }
  ],
  "min_order_size": "5",
  "tick_size": "0.001",
  "neg_risk": true,
  "last_trade_price": "0.65"
}
```

#### GET /midpoint — Midpoint Price

_Ref: <https://docs.polymarket.com/api-reference/data/get-midpoint-price>_

```bash
curl "https://clob.polymarket.com/midpoint?token_id=YOUR_TOKEN_ID"
```

**Response:** `{ "mid": "0.65" }`

#### GET /spread — Bid-Ask Spread

_Ref: <https://docs.polymarket.com/api-reference/market-data/get-spread>_

```bash
curl "https://clob.polymarket.com/spread?token_id=YOUR_TOKEN_ID"
```

#### GET /last-trade-price — Last Trade

_Ref: <https://docs.polymarket.com/api-reference/market-data/get-last-trade-price>_

```bash
curl "https://clob.polymarket.com/last-trade-price?token_id=YOUR_TOKEN_ID"
```

**Response:** `{ "price": "0.65", "side": "BUY" }`

#### GET /tick-size — Tick Size

_Ref: <https://docs.polymarket.com/api-reference/market-data/get-tick-size>_

```bash
curl "https://clob.polymarket.com/tick-size?token_id=YOUR_TOKEN_ID"
```

**Response:** `{ "minimum_tick_size": 0.001 }`

Tick sizes: `0.1`, `0.01`, `0.001`, or `0.0001`. Changes dynamically when price > 0.96 or price < 0.04.

#### GET /fee-rate — Fee Rate

_Ref: <https://docs.polymarket.com/api-reference/market-data/get-fee-rate>_

```bash
curl "https://clob.polymarket.com/fee-rate?token_id=YOUR_TOKEN_ID"
```

#### GET /neg-risk — Negative Risk Check

```bash
curl "https://clob.polymarket.com/neg-risk?token_id=YOUR_TOKEN_ID"
```

### Batch Endpoints (Multiple Tokens)

These let you query multiple tokens in a single request:

| Endpoint | Method | Description |
|---|---|---|
| `/books` | POST | Multiple orderbooks |
| `/prices` | GET (query params) or POST (body) | Multiple prices |
| `/midpoints` | GET (query params) or POST (body) | Multiple midpoints |
| `/spreads` | POST | Multiple spreads |
| `/last-trade-prices` | GET (query params) or POST (body) | Multiple last trade prices |

_Ref: <https://docs.polymarket.com/api-reference/market-data/get-order-books-request-body>_

```bash
# POST body example for /books
curl -X POST "https://clob.polymarket.com/books" \
  -H "Content-Type: application/json" \
  -d '[{"token_id": "TOKEN_1"}, {"token_id": "TOKEN_2"}]'
```

### CLOB Market Endpoints

#### GET /markets — CLOB Market List

_Source: <https://docs.polymarket.com/developers/CLOB/clients/methods-public>_

Returns markets as seen by the CLOB (different schema than Gamma). Paginated.

```bash
curl "https://clob.polymarket.com/markets?next_cursor=xxx"
```

**CLOB Market Object:**

```typescript
interface Market {
  accepting_order_timestamp: string | null;
  accepting_orders: boolean;
  active: boolean;
  archived: boolean;
  closed: boolean;
  condition_id: string;
  description: string;
  enable_order_book: boolean;
  end_date_iso: string;
  game_start_time: string;
  icon: string;
  image: string;
  is_50_50_outcome: boolean;
  maker_base_fee: number;
  market_slug: string;
  minimum_order_size: number;
  minimum_tick_size: number;
  neg_risk: boolean;
  neg_risk_market_id: string;
  neg_risk_request_id: string;
  notifications_enabled: boolean;
  question: string;
  question_id: string;
  rewards: { max_spread: number; min_size: number; rates: any | null };
  seconds_delay: number;
  tags: string[];
  taker_base_fee: number;
  tokens: MarketToken[];
}

interface MarketToken {
  outcome: string;
  price: number;
  token_id: string;
  winner: boolean;
}
```

#### GET /sampling-markets and /sampling-simplified-markets

Lighter-weight market list endpoints for high-frequency polling.

---

## Historical Timeseries Data

### GET /prices-history — Price History

_Ref: <https://docs.polymarket.com/api-reference/markets/get-prices-history>_

```bash
curl "https://clob.polymarket.com/prices-history?market=TOKEN_ID&interval=1d&fidelity=60"
```

| Parameter | Type | Description |
|---|---|---|
| `market` | string | The token ID (asset_id) of the market outcome |
| `startTs` | number | (Optional) Filter by items after this unix timestamp |
| `endTs` | number | (Optional) Filter by items before this unix timestamp |
| `interval` | string | Time range: `1h`, `6h`, `1d`, `1w`, `1m`, `max`, `all` |
| `fidelity` | integer | Accuracy in minutes (default: 1) |

**Response:**

```json
{
  "history": [
    { "t": 1771413619, "p": 0.015 },
    { "t": 1771414220, "p": 0.016 }
  ]
}
```

**Note:** Use the token_id from Gamma API's `clobTokenIds`, not the condition_id.

---

## WebSocket (Real-Time Updates)

_Source: <https://docs.polymarket.com/developers/CLOB/websocket/market-channel>_

**URL:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`

### Market Channel (Public — No Auth)

Subscribe to real-time orderbook and price updates:

```json
{
  "assets_ids": ["TOKEN_ID_1", "TOKEN_ID_2"],
  "type": "market",
  "custom_feature_enabled": true
}
```

Set `custom_feature_enabled: true` to receive additional event types.

**Event types received:**

| Event | Description | Requires custom_feature_enabled |
|---|---|---|
| `book` | Full orderbook snapshot (on subscribe and after trades) | No |
| `price_change` | Price update when orders placed/cancelled | No |
| `tick_size_change` | Tick size change (triggers when price > 0.96 or < 0.04) | No |
| `last_trade_price` | Last trade price when maker/taker match | No |
| `best_bid_ask` | Best bid/ask price changes | Yes |
| `new_market` | New market launched | Yes |
| `market_resolved` | Market resolution event | Yes |

Each message includes an `event_type` field identifying the event.

### User Channel (Authenticated)

_Source: <https://docs.polymarket.com/developers/CLOB/websocket/user-channel>_

Subscribe to order status updates. Requires WSS authentication headers.

### Sports WebSocket

Dedicated sports data channel — see docs for details.

### RTDS (Real-Time Data Stream)

_Source: <https://docs.polymarket.com/developers/RTDS/RTDS-overview>_

Low-latency data stream optimized for market makers. Includes:

- RTDS Crypto Prices: real-time crypto price feeds
- RTDS Comments: real-time comment streaming

---

## Fees

_Source: <https://docs.polymarket.com/trading/fees>_

### Overview

Most Polymarket markets are **completely fee-free**. Taker fees apply only to specific market types and are redistributed to market makers as rebates.

### Fee Formula

```
fee = C × feeRate × (p × (1 - p))^exponent
```

Where:

- **C** = number of shares traded
- **p** = share price
- **feeRate** and **exponent** vary by market type

### Fee Parameters by Market Type

| Market Type | Fee Rate | Exponent | Peak Fee (at p=0.5) | Maker Rebate |
|---|---|---|---|---|
| Default | 0 | — | 0% | — |
| 5-min & 15-min crypto | 0.25 | 2 | 1.56% | 20% |
| Sports (NCAAB, Serie A) | 0.0175 | 1 | 0.44% | 25% |

**Notes:**

- Fees decrease symmetrically toward price extremes (0 or 1)
- Minimum fee charged: **0.0001 USDC** (smaller amounts round to zero)
- No separate maker fees—only taker fees with daily rebate distributions

Check `maker_base_fee` and `taker_base_fee` on market objects or use `GET /fee-rate` for current rates.

---

## Order Management (Authenticated — L2)

_Source: <https://docs.polymarket.com/developers/CLOB/clients/methods-l2>_

These endpoints require API credentials (key, secret, passphrase).

### POST /order — Place Order

All orders are limit orders. For market-like execution, set price to cross the spread.

**Order Types:**

- **GTC** (Good Till Cancelled) — default, rests on book until filled or cancelled
- **GTD** (Good Till Date) — expires at a specified time
- **FOK** (Fill Or Kill) — must fill entirely immediately or cancel
- **FAK** (Fill And Kill) — fills what it can immediately, cancels the rest

**Post Only:** Orders can be set to reject if they would immediately match (prevents paying taker fees).

**Using Python SDK:**

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
import os

api_creds = ApiCreds(
    api_key=os.getenv("API_KEY"),
    api_secret=os.getenv("SECRET"),
    api_passphrase=os.getenv("PASSPHRASE")
)

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key=os.getenv("PRIVATE_KEY"),
    creds=api_creds,
    signature_type=2,              # Deployed Safe proxy wallet
    funder=os.getenv("FUNDER_ADDRESS")
)

# Place a single order
resp = await client.create_and_post_order(
    {"tokenID": "YOUR_TOKEN_ID", "price": 0.50, "size": 100.0, "side": "BUY"}
)
```

### POST /orders — Place Multiple Orders (Batch)

_Source: <https://docs.polymarket.com/changelog/changelog>_

Up to **15 orders** per batch request.

### DELETE /order — Cancel Order

### DELETE /orders — Cancel Multiple Orders

### DELETE /cancel-all — Cancel All Orders

### DELETE /cancel-market-orders — Cancel All Orders for a Market

### GET /order/{id} — Get Single Order

### GET /orders — Get Active Orders

### GET /data/trades — Get Your Trades (L2 Auth Required)

_Source: <https://docs.polymarket.com/developers/CLOB/trades/trades>_

**NOTE:** This CLOB endpoint requires L2 authentication. For public trade data, use the Data API instead.

---

## SDKs

_Source: <https://docs.polymarket.com/api-reference/clients-sdks>_

| Language | Package | Install |
|---|---|---|
| TypeScript | `@polymarket/clob-client` | `npm install @polymarket/clob-client` |
| Python | `py-clob-client` | `pip install py-clob-client` |
| Rust | `polymarket-client-sdk` | `cargo add polymarket-client-sdk` |

**GitHub repos:**

- TS: <https://github.com/Polymarket/clob-client>
- Python: <https://github.com/Polymarket/py-clob-client>
- Rust: <https://github.com/Polymarket/rs-clob-client>

---

## Rate Limits

_Source: <https://docs.polymarket.com/api-reference/rate-limits>_

Rate limits use Cloudflare throttling (delayed/queued, not rejected). Burst allowances on trading.

### Market Data

| Endpoint | Limit |
|---|---|
| General (all CLOB) | **9,000 req / 10s** |
| `/book` | **1,500 req / 10s** |
| `/books` | **500 req / 10s** |
| `/price` | **1,500 req / 10s** |
| `/prices` | **500 req / 10s** |
| `/midpoint` | **1,500 req / 10s** |
| `/midpoints` | **500 req / 10s** |
| `/prices-history` | **1,000 req / 10s** |
| Market tick size | **200 req / 10s** |

### Ledger

| Endpoint | Limit |
|---|---|
| `/trades`, `/orders`, `/order` | **900 req / 10s** |
| `/data/orders` | **500 req / 10s** |
| `/data/trades` | **500 req / 10s** |

### Trading (Burst + Sustained)

| Endpoint | Burst Limit | Sustained Limit |
|---|---|---|
| `POST /order` | **3,500 req / 10s** | **36,000 req / 10 min** |
| `DELETE /order` | **3,000 req / 10s** | **30,000 req / 10 min** |
| `POST /orders` (batch) | **1,000 req / 10s** | **15,000 req / 10 min** |
| `DELETE /orders` | **1,000 req / 10s** | **15,000 req / 10 min** |
| `DELETE /cancel-all` | **250 req / 10s** | **6,000 req / 10 min** |
| `DELETE /cancel-market-orders` | **1,000 req / 10s** | **1,500 req / 10 min** |

### Authentication

| Endpoint | Limit |
|---|---|
| API key endpoints | **100 req / 10s** |

---

## Key Concepts for Arbitrage Analysis

### Complementary Token Pricing

In a binary market, YES + NO should equal $1.00:

- If `YES price + NO price < $1.00` → potential buy-both arbitrage
- If `YES price + NO price > $1.00` → overpriced (rare)

### Orderbook Depth Analysis

Use `/book` to assess:

- **Spread** — gap between best bid and best ask (wider = less efficient = more opportunity)
- **Depth** — total size at each price level (thin = slippage risk)
- **Imbalance** — ratio of bid vs ask depth (signals directional pressure)

### Linking Gamma → CLOB

1. Get event from Gamma: `GET /events/slug/your-event`
2. Extract `clobTokenIds` from market objects (parse the JSON string)
3. Use token IDs with CLOB: `GET /price?token_id=TOKEN_YES_ID&side=buy`
4. Get orderbook: `GET /book?token_id=TOKEN_YES_ID`

### Multi-Outcome Sum Analysis

For negRisk events with N markets:

```python
total = sum(float(json.loads(m["outcomePrices"])[0]) for m in event["markets"])
if total < 0.98:  # account for spread
    print(f"Potential arbitrage: buy all YES for ${total:.2f}, guaranteed $1 payout")
```

---

## Best Practices

1. **Use WebSocket for real-time monitoring** — REST polling adds latency
2. **Always check `accepting_orders`** before attempting trades
3. **Check `tick_size`** — orders must be priced at valid tick increments
4. **Check `minimum_order_size`** — orders below this will be rejected
5. **Use `seconds_delay`** — some markets delay order acceptance after creation
6. **Use Post Only** for limit orders you don't want to cross the spread
7. **Use batch endpoints** (`/prices`, `/books`, `/midpoints`) to reduce API calls
8. **Check fee rates** on specific markets — some sports/crypto markets have taker fees
