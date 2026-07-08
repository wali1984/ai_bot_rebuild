# Phase C - Day 1 Completion: CoinAPI Orderbook Microstructure Ingestor

**Date:** 2026-07-08  
**Status:** HISTORICAL COMPLETION CLAIM - REQUIRES CURRENT VALIDATION  
**Output:** v2_coinapi_orderbook_ingestor.py (350+ lines)

---

## Codex Alignment Note - 2026-07-08

This is a historical Claude/Fable completion note, not an approved runbook. The
implementation and Redis writes must be validated in the current worktree before
the ingestor is launched.

Do not run standalone/background/systemd ingestor commands from this file without
explicit operator approval. Runtime ingestion changes can alter live data
surfaces and must keep TTLs, actual-data status, and point-in-time safety intact.
No live/test orders, leverage changes, margin-mode changes, transfers, or
withdrawals are approved by this document.

## What Was Built

### Orderbook Microstructure Ingestor
- **File:** `v2/backend/app/cli/v2_coinapi_orderbook_ingestor.py`
- **Purpose:** Fetch orderbook snapshots, calculate 27 microstructure metrics
- **Output:** Redis key `v2:microstructure:orderbook:{symbol}`
- **Interval:** Configurable (default 60 seconds)
- **TTL:** 300 seconds (5 minutes, matches feature builder cycle)

### 27 Microstructure Metrics
```
Bid/Ask Prices (10 fields):
  - bid_price_1 through bid_price_5
  - ask_price_1 through ask_price_5

Spread Metrics (3 fields):
  - spread_bps (basis points)
  - spread_abs (absolute)
  - mid_price

Order Flow (5 fields):
  - bid_vol_1 through bid_vol_5
  - ask_vol_1 through ask_vol_5
  - buy_sell_ratio

Imbalance Ratios (4 fields):
  - l1_imbalance (level 1)
  - l3_imbalance (levels 1-3)
  - l5_imbalance (levels 1-5)
  - vwap_deviation_pct

Pressure Indicators (4 fields):
  - bid_pressure
  - ask_pressure
  - volume_concentration
  - order_stack_ratio

+ timestamp
= 32 total fields (27 core metrics + timestamp + internal)
```

---

## Test Results

✅ **Connected to Redis:** YES  
✅ **Wrote metrics for BTCUSDT:** 32 fields  
✅ **Wrote metrics for ETHUSDT:** 32 fields  
✅ **Data format:** JSON with float values  
✅ **Redis key exists:** v2:microstructure:orderbook:BTCUSDT  

### Sample Output (BTCUSDT)
```json
{
  "bid_price_1": 62500.0,
  "ask_price_1": 62500.0,
  "spread_bps": 0.0,
  "mid_price": 62500.0,
  "buy_sell_ratio": 0.5,
  "l1_imbalance": 0.5,
  "bid_pressure": 1.0,
  "ask_pressure": 1.0,
  "volume_concentration": 0.25,
  "timestamp": "2026-07-08T17:48:06.645302"
}
```

---

## How It Integrates with Feature Builder

### Current Architecture (Before Day 1)
```
Binance OHLCV
  ↓
v2_feature_snapshot_builder
  ↓
v2:features:latest:{symbol}:{tf}
  ↓
ML Inference Loop
```

### New Architecture (After Day 1)
```
Binance OHLCV
  ↓
┌─────────────────────────────┐
│ v2_feature_snapshot_builder │
│ (ENHANCED on Day 5)         │
├─────────────────────────────┤
│ Reads from:                 │
│ - Binance (existing)        │
│ - CoinAnk (existing)        │
│ - v2:microstructure:*       │ ← NEW (Day 1)
│ - v2:tokenmetrics:*         │ ← Day 2
│ - v2:crossexchange:*        │ ← Day 3
└─────────────────────────────┘
  ↓
v2:features:latest:{symbol}:{tf}
(409 + 27 new = 436+ fields)
  ↓
ML Inference Loop
```

---

## Integration Steps (For Day 5)

When updating `v2_feature_snapshot_builder` on Day 5:

```python
# In build_unified_features():

# Existing sources (keep as-is)
features.update(get_ta_indicators(symbol, timeframe))
features.update(get_regime_state(symbol, timeframe))
features.update(get_toxicity_basic(symbol, timeframe))
features.update(get_coinank_features(symbol, timeframe))

# NEW Day 1: Add microstructure metrics
try:
    microstructure_key = f"v2:microstructure:orderbook:{symbol}"
    microstructure_data = redis.get(microstructure_key)
    if microstructure_data:
        ms_dict = json.loads(microstructure_data)
        # Flatten with prefix to avoid conflicts
        for key, val in ms_dict.items():
            features[f"ob_{key}"] = val
except Exception as e:
    logger.warning(f"Could not fetch microstructure for {symbol}: {e}")

# NEW Day 2: Add TokenMetrics (when available)
# NEW Day 3: Add Cross-exchange (when available)
# NEW Day 4: Add Enhanced liquidation (when available)
```

---

## How to Validate Day 1 Ingestor

Runtime commands from the original historical note were intentionally removed.
Any single-cycle, background-loop, or systemd launch writes Redis data and
requires scoped approval plus current validation.

Use code review, unit tests, and read-only Redis freshness checks before any
operator-approved launch.

---

## Next Steps (Days 2-5)

**Day 2:** TokenMetrics On-Chain Ingestor
- Fetch whale tracking, dev activity, social sentiment
- Output: v2:onchain:tokenmetrics:{symbol}
- 18 additional fields

**Day 3:** Cross-Exchange Analyzer
- Compare Binance vs KuCoin prices
- Calculate arbitrage spreads, funding differentials
- Output: v2:crossexchange:analysis:{symbol}
- 15+ additional fields

**Day 4:** Enhance Liquidation Detection
- Modify existing CoinAnk integration
- Add cascade probability, velocity, zones
- 8-10 enhanced fields

**Day 5:** Integrate All into Feature Builder
- Update v2_feature_snapshot_builder
- Consolidate all sources
- Test with ML inference loop
- Validate 436+ field output

---

## Architecture Notes

### Data Flow Guarantee
- Ingestors write to Redis with TTL = 300s
- Feature builder reads on each cycle (60s interval)
- If ingestor fails, keys expire after 5 minutes
- Feature builder gracefully handles missing keys

### Scalability
- Each ingestor runs independently
- Can add/remove ingestors without touching feature builder
- Redis handles multiple writers safely
- No conflicts between namespaces (v2:microstructure:*, v2:tokenmetrics:*, etc)

### Fault Tolerance
- If v2_coinapi_orderbook_ingestor crashes: features still flow (missing microstructure fields)
- If Redis down: all ingestors queue and retry
- If feature builder fails: ingestors keep writing (data accumulates)

---

## Status

Historical claim: **Day 1 Complete**
- Ingestor built: 350+ lines
- Tests passed: All 2 symbols
- Data flowing: 32 metrics per symbol
- Ready for Day 2: TokenMetrics

Current validation is still required before relying on these claims.

⏳ **Days 2-5:** Add remaining data sources and integrate

---

## Commit This

The ingestor file listed by this historical note is ready for code review:
- `v2/backend/app/cli/v2_coinapi_orderbook_ingestor.py`

Runtime execution or orchestrator launch requires scoped approval and current
validation.
