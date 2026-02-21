---
name: polymarket-market-research
description: >
  Use this skill when performing deep-dive analysis on individual Polymarket markets.
  This skill guides LLM REASONING about resolution sources, competitive dynamics,
  and edge assessment. It is NOT a mechanical checklist - it's a framework for thinking.
---

# Polymarket Market Research Skill

## Philosophy

This skill guides REASONING, not box-checking. The research guide explicitly warns:
"Don't reduce that to regex and point scores."

Your value is in:
- READING market descriptions and understanding what they mean
- REASONING about whether resolution sources are accessible
- INTERPRETING trade patterns to assess competition
- JUDGING whether opportunities are worth pursuing

## Critical Methodology: Resolution-Source-First

**START with resolution sources, NOT categories.** Mining by category leads to shallow analysis.

### Why Resolution-Source-First?

Categories like "weather" or "finance" tell you WHAT markets are about.
Resolution sources tell you WHERE the data comes from and HOW to access it.

Two markets in the same category can have completely different edge profiles:
- "Fed rate decision" → data is PUBLIC and SIMULTANEOUS → no forecasting edge
- "NYC high temperature" → ensemble forecasts available DAYS ahead → forecasting edge

The resolution source determines whether you can build an edge, not the category.

### Data Resources

Market data is stored in `research_data/markets.db` (SQLite). Key fields:
- `resolution_source`: The URL/source used for resolution
- `description`: Contains detailed resolution rules (often more useful than resolution_source)
- `volume`, `liquidity`: Market size indicators
- `neg_risk`: Whether this is part of a multi-outcome event

Research findings are stored in `research_data/` as JSON files.

### How to Explore (Reasoning Framework)

When exploring markets, ask yourself:

1. **What resolution sources appear frequently?** Group by domain, not category.

2. **For each resolution source, ask:**
   - Is this a data feed I can access programmatically?
   - Does the data exist BEFORE the market resolves? (forecasting edge)
   - Or does the data appear SIMULTANEOUSLY with market resolution? (speed edge only)

3. **Look for patterns that suggest recurrence:**
   - Date patterns in slugs (february, march, weekly, monthly)
   - Bucket structures (0-19, 20-39, etc.)
   - Similar market titles with different dates

## Evaluating Edge Type

**This is the most important reasoning step.** Not all edges are equal.

### Forecasting Edge vs Speed Edge

| Edge Type | What It Means | Example | Our Advantage |
|-----------|---------------|---------|---------------|
| **Forecasting** | Data exists before resolution | Weather forecasts, tweet patterns | Model accuracy |
| **Speed** | Data appears at resolution time | Fed announcements, earnings | Infrastructure speed |
| **Information** | Private/expensive data | Custom polls, insider access | Capital/connections |

**Key question:** When does the resolution data become knowable?

- If knowable DAYS before → Forecasting edge (good for us)
- If knowable SECONDS before → Speed edge (need infrastructure)
- If knowable only to insiders → Information edge (not accessible)

### How to Evaluate a Category

Don't ask "is this category good?" Ask:

1. **When does resolution data become available relative to market close?**
   - Days before = forecasting opportunity
   - Seconds before = speed competition
   - At the same moment = pure reaction speed

2. **Is the resolution objective or subjective?**
   - Objective (number from API) = automatable
   - Subjective (consensus of reports) = resolution risk

3. **Who else is competing here?**
   - Low wallet concentration = retail-dominated, possibly inefficient
   - High wallet concentration = sophisticated players, efficient

4. **What infrastructure would a competitor need?**
   - Simple script = low barrier, expect competition
   - Complex modeling = higher barrier, less competition
   - Co-location/HFT = we can't compete

## API Validation Framework

Before recommending any opportunity, you must validate the resolution data source.

### What Makes a Good Resolution API?

| Criterion | Good | Bad |
|-----------|------|-----|
| **Accessibility** | Public, no auth required | Requires paid subscription or scraping |
| **Latency** | Updates frequently (hourly or better) | Updates daily or irregularly |
| **Reliability** | Official source, rarely wrong | Third-party aggregator, may have errors |
| **Format** | Structured JSON/API | HTML scraping required |
| **Rate limits** | Generous or none | Strict limits that prevent monitoring |

### Validation Process

1. **Find the actual endpoint** - Read the market description, find the resolution source URL
2. **Test accessibility** - Can you fetch it with curl? Does it require auth?
3. **Check update frequency** - How often does the data change? Is there a timestamp?
4. **Verify it matches resolution** - Does the API data format match what the market resolves to?
5. **Assess reliability** - Is this the authoritative source or a proxy?

**Document what you find.** If you can't access the data programmatically, the opportunity is not viable for automation.

## Part 1: Resolution Source Analysis (LLM Reasoning)

### Step 1: Read and Understand the Market

From the Gamma API, you have:
- `resolutionSource` field (often generic or empty)
- `description` field (contains detailed resolution rules)
- `automaticallyResolved` boolean

**Your task: READ the description carefully and ANSWER these questions:**

1. **What EXACTLY triggers resolution?**
   - Is it a specific number (temperature > 32°F)?
   - Is it an event occurrence (Fed announces rate)?
   - Is it subjective (consensus of news reports)?

2. **What is the authoritative data source?**
   - Named source (Weather Underground, USGS, official scoreboard)?
   - Consensus reporting (NYT, BBC, WSJ agreement)?
   - No clear source (subjective judgment)?

3. **Which oracle will resolve this?**
   - **Chainlink** = automated, real-time (crypto prices)
   - **UMA** = optimistic oracle, 2hr challenge period (most markets)
   - **Markets Team** = manual verification

### Step 2: Evaluate Data Access

**REASON about whether you can access the resolution data:**

| Question | Think About |
|----------|-------------|
| Is there a public API? | Search for "{source} API documentation" |
| How fast does it update? | Real-time? Hourly? Daily? |
| What's the delay chain? | Event → Source updates → Market reacts |
| Can we beat the market? | Do we have faster access than typical traders? |

**Web search required:**
- `"{resolution_source}" API documentation`
- `"{resolution_source}" data feed real-time`

### Step 3: Assess Timing Advantage

**THINK through the information flow:**

```
Real-world event occurs
    ↓ (delay 1: event → data source)
Data source updates
    ↓ (delay 2: source → traders notice)
Traders react
    ↓ (delay 3: reaction → price moves)
Market price adjusts
```

**Key question:** At which point can WE act, and is there enough time before others?

## Part 2: Competitive Dynamics (LLM Reasoning)

### Fetch the Data (Mechanical)

```bash
# Trades (use takerOnly=false for full picture)
curl "https://data-api.polymarket.com/trades?market={CONDITION_ID}&takerOnly=false&limit=500"

# Bot detection (for each top wallet)
curl "https://data-api.polymarket.com/activity?user={WALLET}&type=SPLIT,MERGE"

# Positions
curl "https://data-api.polymarket.com/v1/market-positions?market={CONDITION_ID}"
```

### Interpret the Data (LLM Reasoning)

**Don't just count - THINK about what the numbers mean:**

| Observation | What It MEANS |
|-------------|---------------|
| 5 unique wallets trading | Market is controlled by few players, likely sophisticated |
| 200 unique wallets | Retail-dominated, possibly less efficient |
| Top 3 wallets = 80% volume | Someone has infrastructure here already |
| Trades every 30 seconds | Automated trading, bots present |
| High SPLIT/MERGE activity | Market maker bot, creates YES+NO from USDC |
| `clobRewards` active | Liquidity is subsidized, may disappear when rewards end |

**Key questions to ANSWER:**
1. Who is trading this market? Retail or sophisticated?
2. Are there signs of automated trading?
3. What infrastructure would someone need to compete here?
4. Is this market being actively monitored by bots?

## Part 3: Practical Execution (LLM Reasoning)

### Fetch Orderbook (Mechanical)

```bash
curl "https://clob.polymarket.com/book?token_id={TOKEN_ID}"
```

### Think About Execution (LLM Reasoning)

**REASON about whether you can actually trade:**

| Question | How to Assess |
|----------|---------------|
| How much can I trade? | Sum depth until price moves 5% |
| What's my cost to enter? | Spread × position size |
| Will my order move the market? | Compare my size to total depth |
| Are there fees? | Check `takerBaseFee` (0% for most, up to 1.56% for some) |

## Part 4: Edge Assessment (LLM Reasoning)

**This is the final judgment. THINK through:**

1. **If I had the resolution data early...**
   - How much could I realistically trade given the orderbook?
   - What price would I get after slippage?
   - What's my expected profit per occurrence?

2. **How often does this opportunity occur?**
   - Consider: daily, weekly, monthly, quarterly, annual
   - Higher frequency = more chances to profit, worth more infrastructure investment
   - Lower frequency = must have larger edge per occurrence to be worthwhile

3. **Is it worth building?**

   Think about the RATIO of expected monthly profit to build effort:
   - High profit, low effort → definitely build
   - Low profit, low effort → maybe build if it's a stepping stone
   - High profit, high effort → worth it if sustainable
   - Low profit, high effort → skip

   Don't use fixed thresholds. A $50/month opportunity might be worth it if it takes 2 hours to build and runs forever. A $500/month opportunity might not be worth it if it requires constant maintenance.

4. **What are the risks?**
   - Data source could be wrong or delayed
   - Market could become more efficient (other bots enter)
   - Liquidity could disappear
   - Resolution rules could be ambiguous
   - Platform could change rules or fees

## Output Format

After your analysis, provide structured output:

```json
{
  "market_slug": "string",

  "resolution_analysis": {
    "trigger": "What exactly causes resolution (your understanding)",
    "data_source": "The authoritative source",
    "oracle_type": "Chainlink|UMA|Markets Team",
    "edge_type": "Forecasting|Speed|Information|None",
    "programmatic_access": {
      "available": true|false,
      "api_or_method": "How to get the data",
      "update_frequency": "How often it updates",
      "lead_time": "How far in advance is data available"
    }
  },

  "competitive_assessment": {
    "unique_wallets": 0,
    "concentration_interpretation": "What the wallet distribution means",
    "bot_presence": "None|Some|Heavy",
    "bot_evidence": "What signals suggest automation",
    "barrier_to_entry": "What infrastructure competitors likely need"
  },

  "execution_assessment": {
    "safe_trade_size_usd": 0,
    "spread_cost_pct": 0,
    "fees_pct": 0,
    "liquidity_sustainable": true|false
  },

  "edge_assessment": {
    "profit_per_occurrence_usd": 0,
    "occurrence_frequency": "Daily|Weekly|Monthly|Annual",
    "expected_monthly_value_usd": 0,
    "build_effort": "Low|Medium|High",
    "effort_justified": true|false,
    "confidence": "High|Medium|Low",
    "reasoning": "Your thinking about the opportunity"
  },

  "recommendation": {
    "pursue": true|false,
    "priority": "High|Medium|Low",
    "build_requirements": "What infrastructure is needed",
    "key_risks": ["Risk 1", "Risk 2"],
    "reasoning": "Why you recommend this"
  }
}
```

## Key Reminders

1. **READ descriptions** - Don't just extract fields, understand them
2. **REASON about edge type** - Forecasting vs speed vs information
3. **THINK about timing** - When does data become knowable?
4. **VALIDATE APIs** - Test that you can actually access the data
5. **ASSESS competition** - What infrastructure do competitors have?
6. **JUDGE effort vs reward** - Is the build effort justified?
7. **REPORT uncertainty** - If you're not sure, say so

## Anti-Patterns to Avoid

1. **Category-first thinking**: "Weather is good" → Wrong. Ask WHY weather works (forecasting edge).

2. **Hardcoded conclusions**: "Avoid sports" → Wrong. Ask what PROPERTY of sports makes it hard (speed competition, no forecasting edge).

3. **Copy-paste queries**: Running the same SQL without thinking → Wrong. Each market requires fresh reasoning.

4. **Skipping API validation**: "This should work" → Wrong. Curl it or don't recommend it.

5. **Ignoring competition**: "There's edge here" → Incomplete. Ask who else sees this edge.
