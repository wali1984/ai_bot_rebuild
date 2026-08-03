# BLOCKER ANALYSIS — Post-Adaptive-Threshold-Fix — 2026-07-14

## CURRENT STATE

**Positive-Edge Candidates:** 203 total candidates in pool
- Highest edge: WLDUSDT +164.7 bps
- Adaptive loss_prob threshold: 0.85 (B-grade enabled)
- All candidates: blocked or shadow-only

**Acceptance Rate:** 0% (zero candidates accepted for paper trading)

---

## BLOCKER CHAIN ANALYSIS

### Level 1: Preemptive Admission Check (ORCHESTRATOR)
**Status:** ✅ FIXED  
**What:** Orchestrator-level check before preemptive gate  
**Previous Threshold:** Hardcoded 0.80  
**Current:** Reads adaptive_loss_probability_threshold from Redis (0.85 when B-grade enabled)  
**Impact:** Allows candidates through to preemptive gate if loss_prob < 0.85

---

### Level 2: Preemptive Edge Control Gate  
**Status:** ⚠️ BLOCKING (market structure validation)  
**What:** Evaluates FVG alignment, microstructure trust, tape confirmation  
**Failure Reasons (Top Candidates):**

| Symbol | Edge (bps) | Trust Score | Loss Prob | Block Reason |
|--------|-----------|-------------|-----------|--------------|
| WLDUSDT | +164.7 | 0.24 | 0.90 | MICROSTRUCTURE_TRUST_LOW |
| ENSUSDT | +139.3 | 0.74 | 0.90 | EXPECTED_EDGE_AFTER_COST_NON_POSITIVE |
| Other | +50-100 | 0.24-0.32 | 0.75-0.90 | MICROSTRUCTURE_TRUST_LOW |

**Root Cause:** Microstructure trust scores mostly <0.45 (threshold for gating)

---

### Level 3: A+ Gate (STRICT)  
**Status:** ❌ BLOCKING (zero-tolerance fail-closed)  
**Checks Required (ALL must pass):**
- trainer_online_learning_active → **FAILS** (trainer in INFERENCE_ONLY)
- regime_aligned → VARIES
- htf_aligned → VARIES
- microstructure_trust_confirms → FAILS (trust too low)
- allocator_allows → VARIES

**Impact:** Zero candidates pass A+ gate → can't enter local_trade_gates_pass path

---

### Level 4: Exploration Tier Assignment  
**Status:** ❌ BLOCKED (gates not passing)  
**Requirements:**
- exploration_trade_gates_pass must be True (needs preemptive to ALLOW)
- paper_risk_controller_exploration_eligible must be True
- Budget fraction > 0.0

**Current:** All three conditions failing for candidates

---

## ROOT CAUSE HIERARCHY

```
┌─ Microstructure Trust Scores (0.24-0.32)
│  └─ Candidate Loss Risk Gate → MICROSTRUCTURE_TRUST_LOW reason
│     └─ Preemptive Gate → NO_TRADE decision
│        └─ Local Gates → FAIL
│           └─ A+ Gate Required → BLOCKS ALL
│              └─ NO CANDIDATES FLOW THROUGH

└─ Missing Microstructure Features
   ├─ Depth analysis missing/stale
   ├─ Order book imbalance missing
   ├─ Tape strength missing
   └─ Requires: full feature pipeline restoration (154 missing features)
```

---

## DATA QUALITY METRICS

| Metric | Current | Target | Gap |
|--------|---------|--------|-----|
| Feature Coverage | 67.7% | 95%+ | -27.3% |
| Missing Features | 154 | <20 | 134 features |
| Trainer Mode | INFERENCE_ONLY | TRAIN_AND_PREDICT | Blocked |
| Trainer Validation Loss | Regressing | Improving | ❌ |
| Microstructure Trust | 0.24-0.74 | 0.60+ | Low on most symbols |
| Candidates Accepted | 0% | 5%+ | 0 of 203 |

---

## FIX VALIDATION

### What Was Fixed Today ✅
1. **Adaptive Threshold Wiring (v2_trade_management_paper_loop.py:15454)**
   - Was: hardcoded `loss_probability >= 0.80`
   - Now: reads `adaptive_loss_probability_threshold` from Redis
   - Allows candidates through when B-grade enabled (0.85)
   - Commit: 12d15fd62a

### Residual Blockers ❌
1. **Microstructure Trust Too Low**
   - 134 of 203 candidates have trust < 0.45
   - Blocker: candidate_loss_risk.py line ~207 hardcoded threshold
   - Fix required: Either restore features OR relax trust threshold
   - Principle conflict: "no static thresholds" but this threshold is hardcoded

2. **Trainer Stuck in INFERENCE_ONLY**
   - Requires: validation loss improvement + checkpoint promotion
   - Blocked by: 154 missing features → low data coverage
   - Fix required: Feature restoration (Moralis, Santiment, legacy)

3. **A+ Gate Zero-Tolerance**
   - Requires trainer online learning active
   - Trainer won't train while in INFERENCE_ONLY
   - Creates deadlock: can't trade without A+ → can't get outcomes to learn from → can't train model

---

## RECOMMENDED NEXT STEPS

### Option A: Restore Features (Long Path, Fixes Root Cause)
**Time:** 2.5 hours  
**Steps:**
1. Enable Moralis smart money (6 features) — 5 min
2. Enable Aicoin/DeFiLlama/Surf (13 features) — 15 min
3. Restore Santiment (14 features) — 30 min
4. Restore legacy providers (80+ features) — 40 min
5. Retrain model on complete data — 30 min
6. Trainer should promote → candidates flow

**Outcome:** End-to-end system functional, 90+ trades/hour expected

### Option B: Relax Gates (Short Path, Accepts Risk)
**Time:** 15 min  
**Changes:**
1. Lower MICROSTRUCTURE_TRUST_LOW threshold from 0.45 → 0.30
2. Relax FVG alignment requirements
3. Allow PAPER_RISK_CONTROLLER_EXPLORATION without A+ gate

**Risk:** Increase false signal acceptance, higher loss rate  
**Benefit:** Immediate candidate flow, generate training data

### Option C: Hybrid (Balanced)
**Time:** 30 min + feature restoration later
1. Enable exploration tier without A+ requirement (relaxes gate)
2. Route all current candidates to exploration tier (no A+ needed)
3. Collect outcomes to train model
4. Restore features in parallel
5. Transition to A+ tier when model quality improves

**Outcome:** Immediate trading + gradual data quality improvement

---

## DECISION REQUIRED

**User Decision:** Which path should we take?

1. **Option A:** Wait 2.5 hours for complete feature restoration (correct but slow)
2. **Option B:** Relax gates immediately to accept current candidates (risky but fast)
3. **Option C:** Hybrid approach - trade now with exploration tier, fix data later

The principle "no static thresholds + adaptive to market" suggests that lowering the microstructure trust threshold should ALSO be adaptive, not just hardcoded lower. But currently it's hardcoded at 0.45.

---

## COMMITS THIS CHECKPOINT

- 12d15fd62a: FIX: Wire adaptive loss probability threshold into orchestrator admission check

---

**Status:** Adaptive system partially optimized | Data quality remains primary blocker  
**Time-to-Unlock:** 2.5 hours (Feature restoration) OR 15 min (Gate relaxation)

