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

1. **If I had the resolution data 10 minutes early...**
   - How much could I realistically trade given the orderbook?
   - What price would I get after slippage?
   - What's my expected profit per occurrence?

2. **How often does this opportunity occur?**
   - Daily (weather markets) = high frequency
   - Weekly (Fed meetings) = medium frequency
   - Annual (elections) = low frequency, big events

3. **Is it worth building?**
   - $20/day × 30 days = $600/month — maybe worth a simple script
   - $5/week × 4 weeks = $20/month — probably not worth it
   - $500 once per year — not worth dedicated infrastructure

4. **What are the risks?**
   - Data source could be wrong or delayed
   - Market could become more efficient
   - Liquidity could disappear
   - Resolution rules could be ambiguous

## Output Format

After your analysis, provide structured output:

```json
{
  "market_slug": "string",

  "resolution_analysis": {
    "trigger": "What exactly causes resolution (your understanding)",
    "data_source": "The authoritative source",
    "oracle_type": "Chainlink|UMA|Markets Team",
    "programmatic_access": {
      "available": true|false,
      "api_or_method": "How to get the data",
      "update_frequency": "How often it updates",
      "delay_estimate_minutes": 0
    }
  },

  "competitive_assessment": {
    "unique_wallets": 0,
    "concentration_interpretation": "What the wallet distribution means",
    "bot_presence": "None|Some|Heavy",
    "bot_evidence": "What signals suggest automation",
    "monitoring_infrastructure": "What competitors likely have"
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
2. **REASON about patterns** - What do the numbers mean?
3. **THINK about timing** - Where in the information flow can we act?
4. **JUDGE realistically** - Be honest about edge and risks
5. **USE web search** - Validate your assumptions about data access
6. **REPORT uncertainty** - If you're not sure, say so
