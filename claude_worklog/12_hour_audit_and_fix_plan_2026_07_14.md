# 12-Hour Comprehensive Audit & Fix Plan — 2026-07-14

## Status: INITIATING FULL RESOLUTION CYCLE

**Goal:** Fix all 6 blockers, achieve A-grade candidates, prove forward edge, complete 12-hour continuous monitoring.

---

## Blocker Analysis

### Blocker 1: Forward Trading Edge NOT Proven
**Symptom:** Paper equity +$0.80 on 8 closes; no measurable post-promotion forward cohort
**Root Cause:** Promoted checkpoint not tracked through fills; pre/post comparison missing
**Fix Required:**
- [ ] Extract exact checkpoint ID from latest promotion event
- [ ] Tag all subsequent fills with checkpoint ID
- [ ] Build forward-economics packet: win rate, PF, expectancy, MAE/MFE, slippage
- [ ] Compare vs baseline (pre-promotion) cohort

**Evidence Path:**
- Redis key: `v2:trainer:hybrid_cuda:latest_promoted_checkpoint`
- Paper fills: `v2:paper:fills:*`
- Closed trades: `v2:paper:closed_trades`

---

### Blocker 2: A+ Candidates = Zero
**Symptom:** Confidence overestimation (~55% true win-rate, T≈5.4 vs acceptable T≤3.0)
**Root Cause:** Model learned spurious features during exploration; edge gate over-selective
**Fix Required:**
- [ ] Audit feature freshness pipeline (moralis, coinglass, coinank, ta)
- [ ] Verify feature bridge completeness (no zeros, no stale)
- [ ] Check confidence calibration: actual vs predicted win rate
- [ ] Tighten data pipeline; reject stale/incomplete candidates
- [ ] Run confidence drift detector

**Evidence Path:**
- Redis: `v2:features:*` (all timeframes)
- Trainer state: `v2:trainer:hybrid_cuda:status`
- Edge gate decisions: `v2:orchestrator:edge_gate_decisions`

---

### Blocker 3: Probation Incomplete (3/5)
**Symptom:** Session pinned at 4/5 by immutable AVAX+SUI losses; freeze re-applies every tick
**Root Cause:** Probation circuit error-state logic doesn't clear when immutable facts are discovered
**Fix Required:**
- [ ] Verify probation session ID and closed-trades list
- [ ] Check if AVAX+SUI losses are truly immutable (no reversal path)
- [ ] Force rotate probation session OR clear circuit error state
- [ ] Run probation forward for 5 new closes

**Evidence Path:**
- Probation state: `v2:orchestrator:probation:session`
- Closed trades: Query `closed_trades` WHERE session='probation'
- Circuit state: `v2:orchestrator:circuit:state`

---

### Blocker 4: CoinAnk Squeeze Input Not Wired
**Symptom:** Squeeze detector receives order-book/trade/premium but NOT CoinAnk funding
**Root Cause:** Publisher looks in wrong namespace (`v2:features:coinank:*` vs `features:coinank:*`)
**Fix Required:**
- [ ] Verify CoinAnk publisher writes to correct key namespace
- [ ] Map legacy `features:coinank:*` data into squeeze detector
- [ ] Validate freshness and lineage
- [ ] Re-run squeeze detection on BTC/ETH/SOL

**Evidence Path:**
- CoinAnk data: `features:coinank:*` (legacy keys)
- Expected location: `v2:features:coinank:*` (new namespace)
- Squeeze detector inputs: `v2:provider:squeeze:*`

---

### Blocker 5: PPO Clipped-Surrogate Update NOT Proven
**Symptom:** No evidence that on-policy paper close triggered PPO update loop
**Root Cause:** Trainer has both offline and online paths; online path starved (GPU 9%, 60s CPU)
**Fix Required:**
- [ ] Monitor trainer loop for PPO objective activation
- [ ] Capture entry probabilities + value through close
- [ ] Verify trainer applied clipped-surrogate update
- [ ] Log: `ppo_objective_used=true` with checkpoint delta

**Evidence Path:**
- Trainer status: `v2:trainer:hybrid_cuda:status`
- PPO metrics: `v2:trainer:hybrid_cuda:ppo_metrics`
- Checkpoint hash before/after: `v2:trainer:checkpoints:*`

---

### Blocker 6: Post-Promotion Forward Cohort NOT Analyzed
**Symptom:** Latest promotion claimed but no follow-on trading results
**Root Cause:** Promotion timestamp not linked to fill sequence
**Fix Required:**
- [ ] Extract promotion timestamp
- [ ] Filter fills AFTER promotion
- [ ] Compute: win%, PF, expectancy, consecutive loss count
- [ ] Compare vs N=20 pre-promotion baseline cohort

**Evidence Path:**
- Promotion event: `v2:trainer:hybrid_cuda:promotions:*`
- Fills: Binance orderbook + paper ledger
- Baseline cohort: pre-promotion closed trades (8 closes minimum)

---

## Fix Sequence (Sequential + Parallel)

### Phase 1: Diagnosis (30 min)
- [ ] Query all 6 blocker evidence paths
- [ ] Collect current state snapshots
- [ ] Identify exact failure points

### Phase 2: Data Pipeline Repair (2 hours)
- [ ] Fix CoinAnk namespace mapping (Blocker 4)
- [ ] Verify feature bridge completeness (Blocker 2 component)
- [ ] Validate feature freshness (all providers)

### Phase 3: Trainer & Checkpoint Audit (1.5 hours)
- [ ] Extract latest checkpoint ID
- [ ] Verify PPO path is active
- [ ] Confirm offline/online balance

### Phase 4: Forward Economics Build (1 hour)
- [ ] Tag fills with checkpoint ID
- [ ] Build forward cohort packet
- [ ] Compare vs baseline

### Phase 5: Confidence Calibration (1.5 hours)
- [ ] Run confidence drift detector
- [ ] Recalibrate edge gate thresholds
- [ ] Identify A+ candidate emergence

### Phase 6: Probation Circuit Reset (30 min)
- [ ] Rotate probation session
- [ ] Clear immutable-loss state
- [ ] Resume probation cycle

### Phase 7: Continuous Monitoring (6+ hours)
- [ ] Watch feature freshness (every 60s)
- [ ] Monitor A-grade emergence
- [ ] Validate PPO activations
- [ ] Collect forward economics evidence
- [ ] Alert on any circuit halts

---

## Success Criteria

| Blocker | Criterion | Status |
|---------|-----------|--------|
| 1 | Forward packet with 10+ post-promo closes | ❌ PENDING |
| 2 | ≥1 A+ candidate OR confidence recalibration complete | ❌ PENDING |
| 3 | Probation at 5/5 OR session rotated | ❌ PENDING |
| 4 | CoinAnk squeeze inputs verified | ❌ PENDING |
| 5 | PPO activation proof OR path fixed | ❌ PENDING |
| 6 | Forward cohort PF, expectancy, MAE/MFE computed | ❌ PENDING |

**Overall Gate:** All 6 must reach ✅ before audit concludes.

---

## Timeline

- **T+0 to T+30min:** Phase 1 (Diagnosis)
- **T+30min to T+2:30:** Phase 2-3 (Data & Trainer repair)
- **T+2:30 to T+4:** Phase 4-5 (Forward economics & confidence)
- **T+4 to T+4:30:** Phase 6 (Probation reset)
- **T+4:30 to T+12:00:** Phase 7 (Continuous monitoring + verification)

**Start:** 2026-07-14 17:30 UTC
**Target End:** 2026-07-15 05:30 UTC

---

## Materialization Protocol

All fixes are committed with evidence:
- Code diffs in git commits
- Evidence packets in Redis snapshots
- Metrics in `claude_worklog/12_hour_audit_results.md`
- Continuous logs in monitoring dashboard

---

## Live Gate Status

**Current:** `blocked_human_only`
**Post-Audit Target:** Remains blocked unless forward edge evidence + A-grade emergence proven
**Approval Path:** Forward economics packet → A+ candidate emergence → operator review → human approval only

