# Polymarket Opportunity Research Guide

## Philosophy

This guide is split into two layers:

- **Data collection** — Exact API calls to fetch structured data. These are mechanical and should be executed as written.
- **Analysis** — Questions to reason about using the fetched data. These require judgment and should NOT be hardcoded into scoring algorithms.

Claude's value is in the analysis layer: reading market descriptions, reasoning about resolution sources, assessing competitive dynamics, and spotting non-obvious patterns. Don't reduce that to regex and point scores.

Read all three skill files before starting:

- `gamma-api/SKILL.md` — Market discovery and metadata
- `clob-api/SKILL.md` — Pricing, orderbooks, and trading
- `data-api/SKILL.md` — Positions, activity, and intelligence

---

## Competitive Context

Before analyzing any data, understand what you're up against. The Polymarket ecosystem
has 170+ third-party tools, bots, and analytics products. Key facts:

- **Bot dominance in short-term markets:** In crypto 5-min and 15-min up/down markets,
  bots capture 73% of arbitrage profits. Average arbitrage opportunity duration is 2.7
  seconds (down from 12.3s in 2024). Pure arbitrage on liquid markets is effectively dead
  for new entrants.
  _Sources: BeInCrypto Jan 2026, Medium/Illumination Feb 2026_

- **Bot scarcity in niche markets:** When an open-source market-making bot was active,
  there were only 3-4 serious liquidity providers on the entire platform, and most
  operated manually. Niche, hard-to-price markets remain severely under-served.
  _Source: news.polymarket.com, May 2025 interview with poly-maker author_

- **Profitability is rare:** Only 7.6% of wallets on Polymarket are profitable (Dune data).
  _Source: CryptoNews, Feb 2026_

- **Whale/copy-trade infrastructure is mature:** Tools like Betmoar ($110M cumulative
  volume), Polywhaler, PolymarketScan (45 wallet filters), and multiple copy-trade bots
  mean that successful wallets get copied quickly.
  _Sources: DeFiPrime ecosystem guide Jan 2026, LaunchPoly Dec 2025_

- **Non-arbitrage strategies are the growth area:** 27% of bot-generated profits now
  come from non-arbitrage strategies: market making, news-driven momentum trading,
  and liquidity provision.
  _Source: Medium/Illumination Feb 2026_

This context matters for the analysis sections below. When assessing whether a market
category is "under-monitored," you're asking whether anyone in this large ecosystem has
built infrastructure for it — not just whether you personally haven't heard of bots there.

---

## Step 1: Fetch the Full Market Landscape

### 1.1 Get all tags

Polymarket has ~9,000 tags organized in a hierarchy. The main UI categories use
specific hardcoded tag IDs (Politics=2, Crypto=21, Sports=100639, etc.), but there
are thousands of subcategories and niche tags beneath them.

_Sources: TRMNL help center ("Polygon has ~9,000 possible tags"); Polymarket
safe-wallet-integration repo (hardcoded tag IDs)_

```python
import requests, json, time

# Tags endpoint — paginate to get all ~9,000
all_tags = []
offset = 0
while True:
    resp = requests.get(
        "https://gamma-api.polymarket.com/tags",
        params={"limit": 200, "offset": offset}
    )
    batch = resp.json()
    if not batch:
        break
    all_tags.extend(batch)
    offset += 200
    time.sleep(0.1)

print(f"Found {len(all_tags)} tags")

# Tags have hierarchical relationships — fetch them for top-level tags
# GET /tags/{id}/related-tags returns relationship objects (tagID, relatedTagID, rank)
# GET /tags/{id}/related-tags/tags returns full tag objects for related tags
# This helps understand the category tree
```

Save the full tag list. Tags have relational structure accessible via
`GET /tags/{id}/related-tags` (returns relationship objects with tagID, relatedTagID, rank)
and `GET /tags/{id}/related-tags/tags` (returns full tag objects for related tags).
Slug-based variants: `GET /tags/slug/{slug}/related-tags` and `GET /tags/slug/{slug}/related-tags/tags`.
_Source: docs.polymarket.com/api-reference/tags/get-related-tags-relationships-by-tag-id_

### 1.2 Paginate all active events with their markets

```python
all_events = []
offset = 0

while True:
    resp = requests.get(
        "https://gamma-api.polymarket.com/events",
        params={"active": "true", "closed": "false", "limit": 100, "offset": offset}
    )
    events = resp.json()
    if not events:
        break
    all_events.extend(events)
    offset += 100
    time.sleep(0.1)

print(f"Total active events: {len(all_events)}")

# Flatten to markets
all_markets = []
for event in all_events:
    for market in event.get("markets", []):
        all_markets.append({
            "event": event,
            "market": market
        })
print(f"Total active markets: {len(all_markets)}")
```

### 1.3 Save raw data

```python
with open("raw_events.json", "w") as f:
    json.dump(all_events, f, indent=2)
```

---

## Step 2: Categorize and Understand the Landscape

### Data to extract per market (mechanical)

For each market, pull these fields into a summary table:

```python
summaries = []
for item in all_markets:
    event = item["event"]
    market = item["market"]

    summary = {
        # Identity
        "event_title": event.get("title"),
        "event_slug": event.get("slug"),
        "question": market.get("question"),
        "tags": [t["label"] for t in event.get("tags", [])],

        # Resolution
        "resolution_source_field": market.get("resolutionSource") or event.get("resolutionSource"),
        "description": market.get("description", "")[:1500],
        "automatically_resolved": market.get("automaticallyResolved"),
        "end_date": market.get("endDate"),

        # Pricing — fields confirmed in official schema
        "liquidity": market.get("liquidity"),       # official docs
        "volume": market.get("volume"),             # official docs
        "volume24hr": market.get("volume24hr"),     # official docs
        "liquidity_clob": market.get("liquidityClob"),  # official docs
        "liquidity_amm": market.get("liquidityAmm"),    # official docs
        # The following pricing fields are returned by the API but not in the
        # official schema. Confirmed by the Go SDK (ivanzzeth/polymarket-go-gamma-client)
        # and a Jan 2026 Medium article with example JSON. They may be absent on
        # some markets, so always use .get().
        "spread": market.get("spread"),
        "best_bid": market.get("bestBid"),
        "best_ask": market.get("bestAsk"),
        "last_trade_price": market.get("lastTradePrice"),
        "one_day_price_change": market.get("oneDayPriceChange"),

        # Structure — all confirmed in official schema
        "accepting_orders": market.get("acceptingOrders"),
        "seconds_delay": market.get("secondsDelay"),
        "neg_risk": event.get("negRisk"),
        "competitive": event.get("competitive"),  # Polymarket's own competitiveness metric
        "enable_order_book": market.get("enableOrderBook"),

        # Outcomes — THESE ARE JSON-ENCODED STRINGS, must json.loads() them
        "outcomes": market.get("outcomes"),          # official docs
        "outcome_prices": market.get("outcomePrices"),  # official docs

        # IDs needed for deeper API calls — all confirmed in official schema
        "condition_id": market.get("conditionId"),       # identifies the market (both outcomes)
        "clob_token_ids": market.get("clobTokenIds"),     # identifies specific YES/NO tokens
        # ^^^ CRITICAL DISTINCTION: condition_id groups outcomes; clobTokenIds are per-token.
        # CLOB endpoints (orderbook, price history) require token IDs, not condition IDs.
        # Data API endpoints (trades, holders) use condition IDs.

        # Fee structure — confirmed in official schema
        "maker_fee": market.get("makerBaseFee"),
        "taker_fee": market.get("takerBaseFee"),

        # Rewards — check clobRewards array if present (nested structure)
        "clob_rewards": market.get("clobRewards"),  # array of reward config objects
    }
    summaries.append(summary)

with open("market_summaries.json", "w") as f:
    json.dump(summaries, f, indent=2)
```

### Analysis questions for Claude (judgment)

Given the full landscape, reason about:

1. **What categories exist?** Group events by tag. Which categories have many markets?
   Which have few? Don't use a hardcoded list — look at the actual tag data. Pay
   attention to the tag hierarchy: a market might be tagged "Sports > NBA > Player Props"
   which tells you more than just "Sports."

2. **Which categories are likely under-monitored?** Consider the competitive context
   above. Crypto and sports markets have sophisticated bot infrastructure. But remember
   that even "niche" categories might have dedicated analytics tools you don't know about
   (PolymarketScan's "Rules Arb" does AI-powered resolution rule analysis across all
   markets). The question is not "has anyone ever looked at this" but "is the monitoring
   infrastructure so thin that a few-minute information advantage is still possible?"

3. **Where do you see resolution sources you can identify?** Read the `resolutionSource`
   field and `description` text. The `resolutionSource` field is sometimes a clean label
   (e.g., "Official electoral commission results") but is often empty or generic. The
   `description` field has the detailed resolution rules and usually names specific data
   sources. If you need the canonical on-chain resolution rules, those are in the UMA
   `ancillaryData` field, but the description is usually sufficient.

4. **What's the market structure look like?** For each category: what's the typical
   liquidity, spread, volume? Note that markets with active `clobRewards` have subsidized
   liquidity — market makers earn rewards for keeping orders on the book. This means the
   apparent liquidity may evaporate when rewards end. Markets without rewards that still
   have tight spreads are genuinely liquid.

---

## Step 3: Deep Dive on Promising Markets

For markets that look interesting from Step 2, fetch detailed trading data.

**Important ID distinction:** The Gamma API market object has two different identifiers
you'll use downstream:

- `conditionId` — Identifies the market (both outcomes together). Used by the **Data API**
  for trades, holders, positions, and activity.
- `clobTokenIds` — JSON-encoded string containing token IDs for each outcome (e.g.,
  `["12345...", "67890..."]`). The first is typically YES, second is NO. Used by the
  **CLOB API** for orderbooks, prices, and price history.

Always `json.loads()` the `clobTokenIds` before using them.

### 3.1 Orderbook depth

```python
def get_orderbook(token_id):
    """Fetch orderbook for a specific outcome token.
    token_id comes from json.loads(market['clobTokenIds'])[0] for YES, [1] for NO."""
    return requests.get(
        "https://clob.polymarket.com/book",
        params={"token_id": token_id}
    ).json()
```

### 3.2 Recent trades

```python
def get_recent_trades(condition_id, limit=500, taker_only=False):
    """Fetch recent trades for a market.
    Uses condition_id (NOT token_id).
    IMPORTANT: takerOnly defaults to true in the API — meaning by default you
    only see the taker side of each trade, not the maker. Set taker_only=False
    to see all trades for competitive analysis.
    Official params: limit (max 10000), offset, takerOnly, market, eventId,
    user, side, filterType, filterAmount.
    NOTE: The GitHub Gist (shaunlebron) also documents start, end, sortBy,
    sortDirection params, but these are NOT in the official API reference.
    They may work but are not guaranteed."""
    return requests.get(
        "https://data-api.polymarket.com/trades",
        params={
            "market": condition_id,
            "limit": limit,
            "takerOnly": str(taker_only).lower(),
        }
    ).json()
```

_Source: docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets
(takerOnly: boolean, default: true)_

Response fields: `proxyWallet`, `side`, `asset`, `conditionId`, `size`, `price`,
`timestamp`, `title`, `slug`, `icon`, `eventSlug`, `outcome`, `outcomeIndex`,
`name`, `pseudonym`, `bio`, `profileImage`, `transactionHash`.

### 3.3 User activity (requires a wallet address)

```python
def get_user_activity(proxy_wallet, condition_id=None, activity_type=None):
    """Fetch on-chain activity for a SPECIFIC USER.
    IMPORTANT: The /activity endpoint REQUIRES a user address — you cannot
    query all activity for a market. Workflow: get trades → extract wallets →
    query activity for wallets of interest.
    type options: TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION, MAKER_REBATE
    Official params: user (required), market, eventId, type, start, end,
    sortBy (TIMESTAMP/TOKENS/CASH), sortDirection (ASC/DESC), side, limit, offset."""
    params = {"user": proxy_wallet}
    if condition_id:
        params["market"] = condition_id
    if activity_type:
        params["type"] = activity_type  # e.g. "SPLIT,MERGE" for bot detection
    return requests.get(
        "https://data-api.polymarket.com/activity",
        params=params
    ).json()

# Bot detection workflow:
# 1. Get trades for a market
# 2. Extract unique proxyWallet addresses
# 3. For top wallets by volume, query their activity to check for SPLIT/MERGE patterns
def detect_bot_wallets(condition_id, limit=500):
    """Find wallets with bot-like activity on a market."""
    trades = get_recent_trades(condition_id, limit=limit, taker_only=False)
    
    # Count trades per wallet
    wallet_trades = {}
    for t in trades:
        w = t["proxyWallet"]
        wallet_trades.setdefault(w, []).append(t)
    
    # For top wallets by trade count, check for splits/merges
    bot_signals = []
    for wallet, wtrades in sorted(wallet_trades.items(), key=lambda x: -len(x[1]))[:10]:
        activity = get_user_activity(wallet, condition_id, "SPLIT,MERGE")
        bot_signals.append({
            "wallet": wallet,
            "name": wtrades[0].get("name") or wtrades[0].get("pseudonym"),
            "trade_count": len(wtrades),
            "split_merge_count": len(activity),
            "likely_bot": len(activity) > 5,  # heuristic — Claude should reason about this
        })
        time.sleep(0.2)  # respect rate limits
    
    return bot_signals
```

_Source: docs.polymarket.com/api-reference/core/get-user-activity
(user: string, **required**; type enum includes MAKER\_REBATE)_

The `/activity` endpoint is more revealing than `/trades` for competitive analysis because
it shows splits (creating new YES+NO pairs from USDC) and merges (recombining), which
are signatures of active market making. A wallet that frequently splits and merges is
likely running a bot.

### 3.4 Market positions (richer than holders)

```python
def get_market_positions(condition_id):
    """Get ALL positions for a market with PnL data.
    Unlike /holders (capped at 20), this returns full position data grouped
    by outcome token, including avgPrice, currentValue, cashPnl, totalPnl.
    This is the best endpoint for understanding who's positioned how."""
    return requests.get(
        "https://data-api.polymarket.com/v1/market-positions",
        params={"market": condition_id}
    ).json()
```

_Source: docs.polymarket.com/api-reference/core/get-positions-for-a-market
("Returns positions for a given market (condition\_id), grouped by outcome token,
with profile data, PnL breakdown, and current pricing.")_

### 3.5 Top holders (simpler, capped at 20)

```python
def get_holders(condition_id):
    """Get top holders for a market.
    Capped at 20 holders per token. For full position data use
    get_market_positions() above instead."""
    return requests.get(
        "https://data-api.polymarket.com/holders",
        params={"market": condition_id}
    ).json()
```

_Source: docs.polymarket.com/developers/misc-endpoints/data-api-holders
("Maximum number of holders to return per token. Capped at 20.")_

### 3.6 Price history

```python
def get_price_history(token_id, interval="1w", fidelity=60):
    """Get historical prices for backtesting.
    IMPORTANT: Uses token_id (from clobTokenIds), NOT condition_id.
    interval options: 1h, 6h, 1d, 1w, 1m, max, all
    fidelity: resolution in minutes (default 1 min, but use 60 for weekly+ intervals)
    KNOWN ISSUE: Resolved markets only return data at 12+ hour granularity."""
    return requests.get(
        "https://clob.polymarket.com/prices-history",
        params={"market": token_id, "interval": interval, "fidelity": fidelity}
    ).json()
```

_Source: docs.polymarket.com/api-reference/markets/get-prices-history
("market: The market (asset id) to query"; interval options: max, all, 1m, 1w, 1d, 6h, 1h);
Known 12h granularity issue: github.com/Polymarket/py-clob-client/issues/216_

### Analysis questions for Claude (judgment)

For each promising market, reason about:

1. **Resolution source analysis:**
   - Read the full market description. What exactly triggers resolution?
   - Is the resolution source a single authoritative data point (like USGS earthquake
     magnitude) or a subjective judgment?
   - Can you access this data source programmatically? If so, how fast does it update?
   - What's the likely delay between the real-world event and the data source reflecting it?
   - What's the likely delay between the data source updating and Polymarket traders reacting?

2. **Competitive dynamics (from Data API):**
   - Look at the trade data. Count unique `proxyWallet` addresses. If 3 wallets are
     doing 90% of volume, that's very different from 200 retail traders.
   - **Note:** `/trades` defaults to `takerOnly=true`. Set `takerOnly=false` to see
     both sides. With takerOnly=true you only see who's taking liquidity, not who's
     making it.
   - Look at trade timing. Are there trades happening within seconds of each other in
     consistent patterns? That suggests automation.
   - **For suspicious wallets, query their activity for splits and merges.** Use
     `get_user_activity(wallet, condition_id, "SPLIT,MERGE")`. Frequent SPLIT and MERGE
     activity is a strong bot/market-maker signal — retail users almost never do manual
     splits. (The `/activity` endpoint requires a user address; see the
     `detect_bot_wallets()` helper above.)
   - Use `get_market_positions(condition_id)` to see ALL positions with PnL data.
     This is more useful than `/holders` (which caps at 20) because it shows average
     entry prices and realized PnL — you can see who bought in early vs. who's chasing.
   - Check if the market has liquidity rewards active (look at the `clobRewards` array
     on the market object — if present and non-empty, market makers are being paid to
     keep orders on the book). Some of the orderbook depth may be reward-seeking, not
     genuine position-taking.

   **What you CAN'T see from the Data API:** The trades endpoint shows `proxyWallet` but
   does not reveal maker vs. taker roles. To see who was maker vs. taker on a specific
   trade, you need on-chain OrderFilled event logs from the CTF Exchange contract
   (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`) or NegRisk CTF Exchange on Polygon.
   This is a separate data layer beyond what these API calls provide.
   _Source: yzc.me/x01Crypto/decoding-polymarket (Zichao Yang, Nov 2025)_

3. **Practical execution:**
   - Look at the orderbook. How much can you buy/sell before moving the price significantly?
   - What's the spread? A 5-cent spread on a $0.50 market means you start 10% underwater.
   - Is the market accepting orders? What's the `secondsDelay`?
   - Are there taker fees? Check `takerBaseFee`. Most markets are 0 bps, but some crypto
     and sports markets have taker fees up to 1.56%.

4. **Edge assessment:**
   - If you had the resolution data 10 minutes before the market reacted, how much could
     you realistically profit given the orderbook depth (not just the displayed liquidity)?
   - Is that profit worth the effort of building and maintaining the data pipeline?
   - How often does this type of event occur? A $200 edge on an earthquake market that
     triggers once a year is very different from a $20 edge on daily temperature markets
     that trigger every day.

---

## Step 4: Cross-Market Analysis

### Negative risk sum check (mechanical)

For events with `negRisk: true`, check if YES prices across all outcomes sum to ~$1.00:

```python
for event in all_events:
    if not event.get("negRisk"):
        continue

    markets = event.get("markets", [])
    if len(markets) < 2:
        continue

    yes_sum = 0
    for m in markets:
        prices = json.loads(m.get("outcomePrices", "[]"))
        if prices:
            yes_sum += float(prices[0])

    deviation = abs(yes_sum - 1.0)
    if deviation > 0.03:  # more than 3 cents off
        print(f"SUM DEVIATION: {event['title']}")
        print(f"  YES sum: ${yes_sum:.4f} (off by ${deviation:.4f})")
        print(f"  Markets: {len(markets)}, Liquidity: {event.get('liquidity')}")
        for m in markets:
            prices = json.loads(m.get("outcomePrices", "[]"))
            print(f"    {m['question'][:60]}: YES={prices[0] if prices else '?'}")
        print()
```

### Analysis questions for Claude (judgment)

1. **Logical dependencies:** Are there markets where the outcome of one logically implies
   the outcome of another? For example, "Will X happen before Y?" and "Will X happen at
   all?" — if the first resolves Yes, the second must also. Look for these relationships
   across events, not just within negRisk groups.

2. **Stale pricing:** Are there markets where the price hasn't moved in days but the
   underlying situation has changed? Compare `lastTradePrice` timestamps to recent news.

3. **Category-level patterns:** When you look at all weather markets together, or all
   government action markets together — do you see systematic patterns? For instance, do
   temperature markets consistently misprice in one direction?

---

## Step 5: Generate Report

Produce a structured report with:

1. **Landscape summary** — How many total markets, breakdown by category, overall
   liquidity distribution
2. **Opportunity categories ranked by potential** — Your assessment of which categories
   offer the best risk-adjusted opportunities, with reasoning (not just a score)
3. **Specific market candidates** — For each promising market, include:
   - What the market is, what resolves it
   - The resolution data source and how to access it
   - Liquidity, spread, and volume data
   - Competitive assessment (how botted, how many traders)
   - Estimated edge and frequency of opportunity
   - What you'd need to build to exploit it
4. **Cross-market opportunities** — Any negRisk sum deviations, logical dependencies,
   or stale pricing found
5. **Recommended next steps** — Prioritized list of what to build first, based on
   effort-to-reward ratio

---

## Important Notes

### Rate Limiting

_Source: <https://docs.polymarket.com/api-reference/rate-limits>_

Limits use Cloudflare throttling (delayed, not rejected). Actual limits are generous:

- **Gamma API:** 4,000 req/10s general, 500/10s for /events, 300/10s for /markets
- **Data API:** 1,000 req/10s general, 200/10s for /trades, 150/10s for /positions
- **CLOB API:** 9,000 req/10s general, 1,500/10s for /book and /price

A `time.sleep(0.1)` between requests is conservative and safe for all scanning.

### Data Gotchas

- `outcomePrices`, `outcomes`, and `clobTokenIds` are **JSON-encoded strings**, not
  arrays. Always `json.loads()` them.
- **condition_id vs token_id**: CLOB endpoints use token IDs (from `clobTokenIds`).
  Data API endpoints use condition IDs (from `conditionId`). Mixing these up returns
  empty results with no error.
- **`/trades` defaults to `takerOnly=true`**. You only see taker-side trades unless
  you explicitly pass `takerOnly=false`. This significantly affects competitive analysis.
- **`/activity` requires a `user` address**. You cannot query all activity for a market.
  Get trades first → extract wallets → query activity per wallet.
- APIs return empty arrays `[]` for no results — not an error.
- Some events have no markets (resolved/removed). Skip gracefully.
- The `resolutionSource` field on events/markets is the quickest way to identify data
  sources, but it's often empty or generic. The `description` field has the detailed rules.
- Price history for **resolved markets** only returns data at 12+ hour granularity, even
  if finer data existed while the market was active. Plan backtesting accordingly.
- The holders endpoint returns a **maximum of 20 holders per token**. Use
  `/v1/market-positions` instead for the full picture.

### Network Access

- Requires access to: `gamma-api.polymarket.com`, `clob.polymarket.com`, `data-api.polymarket.com`
- If running in Claude Code, ensure these domains are in your network config.
- If blocked, suggest the user run the data collection locally and feed results back.

### What to Save

- `raw_events.json` — Full event dump for offline analysis
- `all_tags.json` — Full tag list with IDs for category mapping
- `market_summaries.json` — Extracted summary table from Step 2
- `deep_dives/` — Detailed orderbook, trade, activity, and holder data for top candidates
- `report.md` — Final analysis report
