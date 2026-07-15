# Adaptive Leverage Strategy for 1000x Growth Goal — 2026-07-15

## Strategic Objective

**System Goal:** Achieve 1000x equity growth in 90 days through intelligent, adaptive risk-taking

**Philosophy:** Paper and replay trading are LEARNING MECHANISMS, not just error-prevention systems. The system must:
- Take CONTROLLED RISKS to discover what works
- Learn from MISTAKES and losses
- Build trading BRAIN (model calibration) through real outcomes
- Progressively increase leverage as confidence grows

## Problem: Conservative Gates Blocking 100% of Candidates

Current state:
- 588 evaluated candidates
- 0 accepted for trading
- All blocked by: `BLOCK_INSUFFICIENT_LIQUIDITY`, `BLOCK_REGIME_NOT_ALIGNED`, missing trade tape evidence

**Root cause:** Gates were designed for LIVE TRADING SAFETY, not paper learning.
In paper mode, we should prioritize LEARNING SIGNALS over rigid safety requirements.

---

## Solution 1: Adaptive Risk Envelope (DEPLOYED ✅)

**Status:** Implemented and deployed in commit 67bf8e9966

**How it works:**
```python
# Leverage scales dynamically based on:
- Win rate: 60% WR → 1.5x, 80% WR → 3.0x, 85%+ WR → up to 10x
- Profit factor: PF>1.5 → additional 1.3x multiplier
- Model confidence: Higher confidence → higher leverage allowed
- Drawdown: Current losses reduce risk budget proportionally

# Risk budget scales similarly:
- Per-trade loss: 1% baseline → 15% max (paper mode)
- Per-symbol exposure: 8% baseline → 50% max
- Portfolio risk: 60% baseline → 250% max

# NO STATIC THRESHOLDS — all scaling is smooth and continuous
```

**Result:** Once candidates PASS gate checks, they'll receive appropriate leverage sizing based on real performance.

---

## Solution 2: Make Paper Gates More Permissive (NEXT STEP)

We need to adjust the GATE LOGIC for paper mode to allow more candidates through:

### Gate 1: Liquidity Requirement (BLOCK_INSUFFICIENT_LIQUIDITY)

**Current (Live-safe, paper-restrictive):**
- Requires high liquidity scores
- Liquidity score measured against strict thresholds

**Needed for Paper Learning:**
- In PAPER MODE: Accept lower liquidity thresholds (we're not executing real orders)
- In PAPER MODE: Allow small-cap symbols to generate training data
- In PAPER MODE: Measure liquidity risk but not as hard blocker

**Change:**
```python
# Current: if liquidity_score < 0.7, block
# New (paper mode): if liquidity_score < 0.3, block (allow higher tail-risk learning)

# Current: if spread_bps > 10, block
# New (paper mode): if spread_bps > 30, block (simulate realistic slippage)
```

### Gate 2: Regime Alignment (BLOCK_REGIME_NOT_ALIGNED)

**Current (Live-safe):**
- Regime must align with market macro state

**Needed for Paper Learning:**
- In PAPER MODE: Allow regime-misaligned trades to test model robustness
- Regime checks are CAUTIONARY in paper, not blocking
- Let model learn what works in different regimes

**Change:**
```python
# Current: regime_score < 0.6 = BLOCK
# New (paper mode): regime_score < 0.2 = BLOCK (but allow learning in 0.2-0.6 range)
```

### Gate 3: Trade Tape Confirmation (missing_evidence)

**Current (Live-safe):**
- Requires trade tape to confirm market moves
- Missing evidence = block

**Needed for Paper Learning:**
- In PAPER MODE: Missing evidence is WARNING, not blocker
- Allow system to trade without real-time confirmation
- Learn which predictions are robust to missing evidence

**Change:**
```python
# Current: if missing_evidence checks > 2, block
# New (paper mode): if missing_evidence checks > 4, block (only block if mostly missing)
```

---

## Solution 3: A+ Gate Flexibility for Paper (NEXT STEP)

Currently A+ gate requires:
- regime_aligned ✓
- trade_tape_confirms ✗ (missing)
- microstructure_trust_confirms ✗ (missing)
- allocator_allows ✗ (blocked by liquidity)

**For Paper Learning:**
- A+ should be LEARNING-focused, not LIVE-ready-focused
- Require only: high confidence, positive edge, good allocator health
- Trade tape / microstructure can be learned LIVE

**Change:**
Allow A-grade (not A+) candidates to trade in paper when:
- confidence_calibrated > 0.70
- expected_edge_bps > 20
- allocator says OK

---

## Solution 4: Leverage Recommendation Multiplier (NEXT STEP)

Currently leverage is capped at 3x hard limit in paper.

**For Aggressive Paper Learning:**
```python
# Current hard cap: PAPER_MAX_LEVERAGE = 3
# New (with dynamic envelope): effectively 10x max (scaled by performance)

# For example:
# - Fresh model (0 closed trades): leverage 1-2x
# - After 10+ trades at 60% WR: leverage 3-5x
# - After 50+ trades at 75% WR: leverage 6-10x
```

---

## Implementation Roadmap

### Phase 1: ✅ DEPLOYED
- Adaptive risk envelope (dynamic_envelope.py)
- Leverage scales with real performance
- Passes dynamic envelope to allocator

### Phase 2: IN PROGRESS (This Session)
- Make liquidity gates mode-aware (paper vs live)
- Relax regime alignment in paper
- Allow trade tape missing as warning, not blocker
- Adjust A+ gate for paper learning

### Phase 3: MONITORING
- Watch model performance as gates open
- Scale leverage as win rate improves
- Monitor drawdown and adjust risk dynamically
- Collect training data on edge detection

---

## Key Principle: No Static Caps

The system must NEVER hardcode:
- "max leverage = 3x" 
- "max risk = 1%"
- "max liquidity threshold = 0.7"

Instead:
- All limits scale CONTINUOUSLY with performance
- Limits are FLOORS (minimum safety), not CEILINGS (maximum ambition)
- System grows leverage as it proves itself

---

## Expected Outcome

**Current State:**
- 588 candidates evaluated
- 0 accepted (100% blocked)
- 66.67% paper win rate (from 8 closed trades)
- Net PnL: $0.83 (proof of concept)

**After Phase 2 (Gate Relaxation):**
- ~100-200 candidates per cycle accepted (estimated)
- ~5-15 closed per cycle (leverage will scale)
- Win rate should hold 60-70% (market dependent)
- PnL should compound as position size increases

**After Phase 3 (Leverage Scaling):**
- As win rate improves → leverage compounds → capital compounds
- 1000x growth emerges from 70%+ sustained win rate + 5-10x leverage
- Timeline: 60-90 days (subject to market conditions)

---

## Files Modified This Session

1. ✅ `/v2/backend/app/services/adaptive_capital_allocator/dynamic_envelope.py` (NEW)
   - Calculates risk envelope based on real performance
   
2. ✅ `/v2/backend/app/cli/v2_trade_management_paper_loop.py`
   - Imports and uses dynamic_envelope
   - Passes dynamic envelope to allocate_paper_candidate

## Files to Modify Next

1. `/v2/backend/app/services/adaptive_capital_allocator/allocator.py`
   - Make liquidity gate mode-aware
   - Relax regime requirements in paper mode

2. `/v2/backend/app/services/paper_trade_management/leverage_recommendation.py`
   - Remove hardcoded 3x cap (let dynamic envelope handle it)
   - Scale recommendations with performance

3. `/v2/backend/app/cli/v2_trade_management_paper_loop.py` (a_plus_gate)
   - Make A+ gate learning-focused in paper
   - Reduce evidence requirements for paper trading

---

## Safety Guardrails (Never Removed)

Even with aggressive paper settings, these ALWAYS apply:
- Paper only (never touches live)
- Liquidation buffer always maintained (500 bps minimum)
- Daily drawdown caps (start 5%, scale to 20% max)
- Emergency absolute cap (if set)
- Single trade max loss (start 1%, scale to 15% max)

The system learns by FAILING SAFELY, not failing catastrophically.

---

**Session Status:** Adaptive envelope deployed. Next: Gate relaxation for paper learning.
**Last Update:** 2026-07-15T15:16:47Z
