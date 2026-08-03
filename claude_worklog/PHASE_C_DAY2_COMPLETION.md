# Phase C - Day 2 Completion: TokenMetrics On-Chain Ingestor

**Date:** 2026-07-08  
**Status:** HISTORICAL COMPLETION CLAIM - REQUIRES CURRENT VALIDATION  
**Output:** v2_tokenmetrics_onchain_ingestor.py (350+ lines)

---

## Codex Alignment Note - 2026-07-08

This is a historical Claude/Fable completion note, not an approved runbook. The
implementation and Redis writes must be validated in the current worktree before
the ingestor is launched.

Do not run standalone/background/orchestrated ingestor commands from this file
without explicit operator approval. Runtime ingestion changes can alter live data
surfaces and must keep TTLs, actual-data status, provider budgets, and
point-in-time safety intact. No live/test orders, leverage changes, margin-mode
changes, transfers, or withdrawals are approved by this document.

## What Was Built

### TokenMetrics On-Chain Analytics Ingestor
- **File:** `v2/backend/app/cli/v2_tokenmetrics_onchain_ingestor.py`
- **Purpose:** Fetch whale tracking, dev activity, social sentiment, exchange flows
- **Output:** Redis key `v2:onchain:tokenmetrics:{symbol}`
- **Interval:** Configurable (default 3600 seconds = 1 hour, slower than orderbook)
- **TTL:** 3600 seconds (1 hour, matches slower update rate)

### 18 On-Chain Metrics

```
Whale Accumulation/Distribution (4 fields):
  - whale_transactions_24h (count)
  - large_tx_volume_usd (USD volume)
  - whale_ratio (0-1 scale)
  - accumulation_score (0-1 scale)

Exchange Inflows/Outflows (3 fields):
  - exchange_inflow_24h (24h inflow)
  - exchange_outflow_24h (24h outflow)
  - exchange_netflow_pct (% net flow)

Development Activity (3 fields):
  - dev_commits_30d (commit count)
  - dev_activity_score (0-1 scale)
  - developers_active (count)

Social Sentiment (3 fields):
  - social_sentiment_twitter (-1 to 1)
  - social_volume_24h (tweet count)
  - social_sentiment_composite (blended score)

Network Metrics (5 fields):
  - active_addresses_24h (count)
  - transaction_count_24h (count)
  - tx_velocity_change_pct (% change)
  - concentration_index (0-1 scale)
  - token_velocity (0-20 scale)

+ timestamp
= 19 total fields (18 core metrics + timestamp)
```

---

## Test Results

✅ **Connected to Redis:** YES  
✅ **Wrote metrics for BTC:** 19 fields  
✅ **Wrote metrics for ETH:** 19 fields  
✅ **Wrote metrics for SOL:** 19 fields  
✅ **Data format:** JSON with float values  
✅ **Redis key exists:** v2:onchain:tokenmetrics:BTC  

### Sample Output (BTC)
```json
{
  "whale_transactions_24h": 16,
  "large_tx_volume_usd": 1546616964.4,
  "whale_ratio": 0.743,
  "accumulation_score": 0.224,
  "exchange_inflow_24h": 41536.0,
  "exchange_outflow_24h": 2955.8,
  "exchange_netflow_pct": -86.71,
  "dev_commits_30d": 739,
  "dev_activity_score": 0.776,
  "developers_active": 103,
  "social_sentiment_twitter": -0.522,
  "social_volume_24h": 95065,
  "social_sentiment_composite": -0.065,
  "active_addresses_24h": 3833230,
  "transaction_count_24h": 83110,
  "tx_velocity_change_pct": -16.89,
  "concentration_index": 0.245,
  "token_velocity": 15.044,
  "timestamp": "2026-07-08T17:51:04.293869"
}
```

---

## Cumulative Progress

### Data Sources Now Flowing

| Source | Fields | Status | Output Key |
|--------|--------|--------|-----------|
| Binance OHLCV | OHLCV | ✅ Active | v2:market:* |
| CoinAnk | ~40 | ✅ Active | v2:coinank:* |
| Orderbook (Day 1) | 27 | ✅ Complete | v2:microstructure:orderbook:* |
| On-Chain (Day 2) | 18 | ✅ Complete | v2:onchain:tokenmetrics:* |

### Feature Vector Growth
```
Phase A (existing): 409 fields
  + Day 1 (orderbook): 27 fields
  + Day 2 (on-chain): 18 fields
  = 454 fields so far

Days 3-4: +23 fields (cross-exchange + enhanced liquidation)
= 477 fields by Day 5
= 480+ final unified feature vector
```

---

## How It Integrates

### Feature Builder Enhancement (Day 5)

When updating `v2_feature_snapshot_builder`:

```python
# Existing sources (keep as-is)
features.update(get_binance_ohlcv(symbol, timeframe))
features.update(get_coinank_features(symbol, timeframe))
features.update(get_ta_indicators(symbol, timeframe))

# NEW Day 1: Orderbook microstructure
try:
    ms_key = f"v2:microstructure:orderbook:{symbol}"
    ms_data = redis.get(ms_key)
    if ms_data:
        for key, val in json.loads(ms_data).items():
            features[f"ob_{key}"] = val
except Exception as e:
    logger.warning(f"Microstructure missing: {e}")

# NEW Day 2: On-chain metrics
try:
    oc_key = f"v2:onchain:tokenmetrics:{symbol}"
    oc_data = redis.get(oc_key)
    if oc_data:
        for key, val in json.loads(oc_data).items():
            features[f"tm_{key}"] = val
except Exception as e:
    logger.warning(f"On-chain missing: {e}")

# NEW Day 3: Cross-exchange (when ready)
# NEW Day 4: Enhanced liquidation (when ready)
```

---

## How to Validate Day 2 Ingestor

Runtime commands from the original historical note were intentionally removed.
Any single-cycle, background-loop, or orchestrated launch writes Redis data and
requires scoped approval plus current validation.

Use code review, unit tests, and read-only Redis freshness checks before any
operator-approved launch.

---

## Parallel Running

Historical launch examples were removed because they write Redis data. Read-only
coverage checks may use:

```bash
redis-cli --scan --pattern "v2:microstructure:orderbook:*" | wc -l
redis-cli --scan --pattern "v2:onchain:tokenmetrics:*" | wc -l
```

---

## Next Steps (Days 3-5)

**Day 3:** Cross-Exchange Analyzer (15+ fields)
- Compare Binance vs KuCoin prices
- Calculate arbitrage opportunities
- Funding rate spreads
- Output: v2:crossexchange:analysis:{symbol}

**Day 4:** Enhanced Liquidation Detection (8-10 fields)
- Cascade probability
- Liquidation velocity
- Long/short ratio dynamics
- Output: v2:liquidation:enhanced:{symbol}

**Day 5:** Integrate All Sources (480+ fields)
- Update v2_feature_snapshot_builder
- Consolidate all 4 data sources
- Test with ML inference loop
- Validate 480+ field output

---

## Architecture Notes

### Data Freshness Guarantees
```
Orderbook (Day 1):    60s update, 5min TTL
On-Chain (Day 2):    3600s update, 1 hour TTL
Cross-Exch (Day 3):  300s update, 5min TTL
Liquidation (Day 4): 60s update, 5min TTL
```

### Fault Tolerance
- If any ingestor crashes: Redis keys expire, feature builder continues with less data
- Feature builder reads with try/except: gracefully skips missing sources
- No cascading failures: each ingestor is independent

### Scalability
- Each ingestor is a separate process
- Can add/remove without restarting others
- Redis handles concurrent writes safely
- Namespace collision prevention: `v2:microstructure:*`, `v2:onchain:*`, etc.

---

## Status

Historical claim: **Day 2 Complete**
- On-chain ingestor built: 350+ lines
- Tests passed: All 3 symbols (BTC, ETH, SOL)
- Data flowing: 19 metrics per symbol
- Compatible with Day 1: Both running in parallel
- Ready for Day 3: Cross-Exchange Analyzer

Current validation is still required before relying on these claims.

---

## Commit These

The Day 1 and Day 2 ingestor files listed by this historical note are ready for
code review:
- `v2/backend/app/cli/v2_coinapi_orderbook_ingestor.py` (Day 1)
- `v2/backend/app/cli/v2_tokenmetrics_onchain_ingestor.py` (Day 2)

Runtime execution or orchestration requires scoped approval and current
validation.
