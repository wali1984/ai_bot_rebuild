# UPSTREAM DATA QUALITY ANALYSIS — 2026-07-14

## Problem Statement
Candidates are being blocked with "EXPECTED_EDGE_AFTER_COST_NON_POSITIVE" (loss_prob=0.90).
Investigation shows this is NOT a gate tuning issue—it's a **DATA COMPLETENESS issue**.

## Evidence: Blocked Candidate Analysis

**Candidate:** VIRTUALUSDT (blocked)

| Field | Status | Value | Required For |
|-------|--------|-------|-------------|
| raw_confidence | ❌ NULL | - | Trainer output (prediction) |
| expected_move_bps | ❌ NULL | - | Price target/model prediction |
| actual_observed_spread_entry_bps | ❌ NULL | - | Market microstructure |
| expected_slippage_bps | ❌ NULL | - | Order execution |
| pre_trade_fee_bps | ❌ NULL | - | Exchange/protocol costs |
| funding_bps | ❌ NULL | - | Perpetuals funding cost |
| microstructure_trust_score | ✅ 0.418 | 41.8% | Orderbook quality |

**Result:**
- No price prediction (raw_confidence=NULL)
- No cost data (all costs NULL)
- Cost validator: net_edge = NULL → loss_prob = 0.90 (default high) → BLOCK

## Root Cause Hierarchy

1. **LEVEL 0: Trainer Not Producing Predictions**
   - raw_confidence = NULL means no model output
   - Possible reasons:
     - Trainer model not ready (still training)
     - Trainer crashed or halted
     - Prediction batching failed
     - Feature pipeline incomplete so trainer won't run

2. **LEVEL 1: Market Data Pipeline Incomplete**
   - actual_observed_spread_entry_bps = NULL (should be real-time from orderbook)
   - expected_slippage_bps = NULL (should be from market simulation)
   - pre_trade_fee_bps = NULL (should be from exchange config)
   - Indicates: Market microstructure data not being populated

3. **LEVEL 2: Moralis Features Missing**
   - 15 Moralis features: aicoin, defillama, surf, etc.
   - Last update: 10+ days ago (1783531031560)
   - Indicates: Moralis provider not running or API key not set

## Successful Trades vs Failed Candidates

**8 Successful Trades (62.5% win rate):**
- Executed when?  ~July 4-7 (before feature pipeline issues began)
- Key difference: May have followed different code path that didn't pre-compute all fields
- Or: May have had data that's no longer available in current pipeline

**Current Failed Candidates:**
- Generated after recent code changes
- Strict validation requires ALL fields populated
- Fields missing = automatic block via loss_probability

## What Needs to Happen

### URGENT (To unlock trade flow):
1. **Verify trainer is producing predictions**
   - Check v2:trainer:hybrid_cuda:status
   - Verify raw_confidence field is populated on new candidates
   - If not: Fix trainer or unblock its pipeline

2. **Verify market data pipeline**
   - Check if orderbook spread data is being written
   - Check if fee configuration is accessible
   - Check if slippage models are running
   - Populate these fields in candidate generation

3. **Moralis features**
   - If MORALIS_API_KEY is not set: Set it (or disable Moralis-required features)
   - If set: Restart v2_moralis_provider_loop (data is 10+ days stale)

### MEDIUM (To improve candidate quality):
1. Restore feature pipeline completeness (15 missing features)
2. Verify feature freshness (current pipeline may be stale)
3. Retrain trainer if it's been collecting new data

### Diagnostic Commands:
```bash
# Check trainer status
redis-cli GET "v2:trainer:hybrid_cuda:status" | jq .

# Check if predictions are being written
redis-cli LLEN "v2:trainer:predictions:queue" 2>/dev/null

# Check Moralis age
redis-cli GET "meta:moralis:last_update" | echo "Updated $(date -d @$(cat)/1000 2>/dev/null) UTC" || echo "No Moralis data"

# Check market data pipeline
redis-cli KEYS "v2:market:*:latest" | head -5
```

## Summary

**Gate is working correctly by rejecting low-confidence, negative-edge candidates.**
**The real problem: Upstream data pipelines are not populating required fields.**

Cannot unlock trade flow by tuning gates. Must fix:
1. Trainer predictions (raw_confidence)
2. Market data (spread, slippage, fees)
3. Feature pipeline (15 missing Moralis features)


---

# DEEP DIVE: TRAINER STATUS & ROOT CAUSE

## Trainer Is Deliberately Frozen (NOT A BUG)

The trainer is running but in **"INFERENCE_ONLY"** mode. This is CORRECT behavior, not a failure.

**Why INFERENCE_ONLY?**

```
checkpoint_promotion_reason: "VALIDATION_LOSS_REGRESSED"
checkpoint_promotion_allowed: false
validation_improved: false
validation_loss_delta: 3.028205  (WORSE, not better)
overfit_gap_warning: true
train_val_generalization_gap: 4.412461
```

**Translation:** The trainer trained a cycle, but the validation loss got WORSE (regressed +3.03), meaning the model overfitted. It correctly refuses to promote a degraded model.

## Feature Data Quality Breakdown

**Missing 154 features** (67.7% coverage, 32.3% missing):

```json
{
  "missing_feature_count": 154,
  "stale_feature_count": 0,
  "data_coverage_percent": 67.71488469601677,
  "feature_dim": 477,
  "expected_input_dim": 1908
}
```

**Feature sources with issues:**
- aicoin (8 features)
- defillama (3 features)  
- surf (2 features)
- moralis (6 features)
- santiment (14 features)
- + 117 others missing from various providers

## Model Performance Breakdown

**Backtest on 16,384 rows:**
```json
{
  "win_rate": 0.482535,      // 48.2% - barely better than random
  "profit_factor_proxy": 1.119368,  // Only 1.12 profit-loss ratio
  "expectancy_after_cost_bps": 3.726344,  // Only 3.7 bps edge
  "evidence_class": "BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE"
}
```

**Training metrics:**
```
loss_before: 8.679579734802246
loss_after: 8.63144302368164  (Tiny improvement)
validation_supervised_loss_before: 10.01569938659668
validation_supervised_loss_after: 13.043904304504395  (REGRESSED by 3.03)
```

**Overfitting detected:**
```
overfit_gap_warning: true
training_steps_per_minute: 134.8
max_promotion_rejection_streak: 9  (9 consecutive rejections)
```

## Why This Happened

1. **Feature pipeline degradation:**
   - 154 features missing = 32% of input data missing
   - Trainer tries to train with incomplete data
   - Model fits poorly to partial data
   - Validation loss regresses

2. **Data coverage collapse:**
   - 67.7% coverage means 1 out of every 3 feature values is NULL/missing
   - Model can't learn effective patterns with that much missing data
   - Overfitting to available data, underfitting to reality

3. **Feedback loop:**
   - Poor model → generates poor candidates → gates block them all
   - Gates correctly identify model is unreliable
   - Trainer refused to promote → stays in INFERENCE_ONLY
   - System is SELF-PROTECTING against bad model

## The Solution Path

### IMMEDIATE (Get model capable again):
1. **Restore 154 missing features** - Primary bottleneck
   - Focus on high-impact providers: Moralis, Santiment, Aicoin, DeFiLlama, Surf
   - Update feature pipeline to populate these fields
   - Verify feature freshness (some are 10+ days old)

2. **Retrain with complete data:**
   - Once features are 95%+ available, restart training
   - Monitor validation loss (should decrease)
   - Promotion should be allowed once validation improves

3. **Verify candidate quality:**
   - With trained model, candidates should have raw_confidence values
   - Edge calculations should work (non-null costs)
   - Gates will accept candidates instead of blocking

### TIMELINE ESTIMATE:
- Feature restoration: 2-4 hours (depending on provider APIs)
- Model retraining cycle: 30-60 minutes (gain performance feedback)
- Trade accumulation: Next 2-6 hours (once model is production-quality)

## Current System State: SELF-PROTECTIVE

The system is NOT broken. It's CORRECTLY:
1. Identifying degraded model (validation regressed)
2. Refusing to use degraded model for live/A+ trades
3. Freezing training until data quality improves
4. Blocking candidates because model lacks confidence
5. Gates correctly rejecting NULL-confidence + NULL-cost trades

**This is proper defensive behavior.**

The FIX is upstream data restoration, not gate tuning.

