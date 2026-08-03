# Full-session self-review — all changes reassessed (2026-07-13 evening)

Operator asked for a complete reassessment of every change made today, fixing all
issues found, ensuring the A-grade path works end to end. Method: inventoried all
~17 commits + operational changes, re-derived correctness for each, ran a deep
evidence-flow audit of the halt-lift chain, fixed everything found.

## Issues FOUND and FIXED

### 1. CRITICAL — temporal prediction window reset every cycle (train/serve skew)
The Step 4c rolling window buffer lived on the V2HybridPolicyModel INSTANCE, but
runtime.run_hybrid_trainer_cycle constructs a FRESH model every cycle → the buffer
reset each cycle → at prediction time the GRU only ever saw a repeated single-frame
window while training on real 16-frame windows. Fixed: process-lifetime module
registries keyed by (input_dim, seq_len); reset_temporal_predict_registry() for
tests; new cross-instance persistence test. (commit d1411d4295)

### 2. CRITICAL — guardian rolling window could never fill (circular halt)
guardian.py admitted ONLY A_GRADE_EXECUTION_PAPER rows into the 100/300-trade
economic windows, but the halt forbids A-grade entries and probation eligibility
REQUIRES guardian_halted (decision.py:371) → the documented "runway via probation"
could not exist; A_GRADE_HALTED_PERFORMANCE was mathematically unliftable. Fixed:
POSITIVE_EDGE_PROBATION_PAPER added to GUARDIAN_ECONOMIC_EVIDENCE_TIERS across the
3 validators. Performance bars unchanged — losing probation trades still hold the
halt; exploration/bootstrap/shadow stay excluded. (commit 2573cac38b)

### 3. Dynamic-floor evidence input never populated
paper_exploration.policy low_evidence_penalty reads symbol_timeframe_evidence_count
off the candidate row; NO writer populated it → penalty pinned at +0.08 max forever;
closes could never lower the floor. Fixed: run_once() publishes per-(symbol,tf)
closed-outcome counts into a per-cycle registry injected into the exploration policy
row (tier-agnostic, matching bucket_health semantics). (commit 2573cac38b)

### 4. VRAM heuristic under-estimated temporal batches 16x
_auto_tuned_batch_size bytes_per_row now multiplied by seq_len when the temporal
encoder is on. (commit d1411d4295)

### 5. Queue-snapshot forgiveness missed the allocator confidence spelling
Both materialization-queue snapshot sites now recognize
ALLOCATOR_HARD_BLOCK:BLOCK_LOW_CONFIDENCE (kept in sync with
BOOTSTRAP_OVERRIDABLE_BLOCKERS). (commit d1411d4295)

### 6. Pretrain flywheel report accumulation
scheduled_pretrain now prunes reports to ~6 days (status API globs that dir per
request). (commit d1411d4295)

### 7. /ai/predictions calibration only on fallback branch
Now reads the prediction payload's confidence_calibration even when the trainer
summary supplied the action. (commit d1411d4295)

## Verified NON-issues (explicitly re-checked)
- Flywheel promotions ARE adopted: fresh model + load_latest_weights every cycle
  (runtime.py ~490) — no restart needed; today's improving live incumbent confirms.
- 6h cache-age refresh works: rebuild rewrites the pkl (mtime advances).
- Cross-epoch input cache is offline-only by design (trainer rebuilt per cycle
  online); fingerprint fail-safe prevents stale-data hits.
- Archive disk growth is self-bounded (DEFAULT_ROLLOVER_LIMIT_BYTES = 300GB,
  rollover called from runtime + bootstrap; 78G current, 554G free).
- TA expansion, archive feature-view merge, fast-path parity, GUI truth chain,
  unit env edits: all verified against live runtime earlier today.

## Corrected understanding of the A-grade chain (audit findings)
- Probation admission does NOT depend on the dynamic floor (fixed thresholds:
  loss-prob < 0.65, exit-feasibility >= 0.55, overstatement-risk < 0.75). The
  floor gates the exploration lane (and the P0 entry gate blocks fills broadly).
- The REAL chain now: bootstrap/exploration closes -> evidence counts (fix #3)
  lower the floor and mature buckets -> probation admits on its own bounds ->
  probation closes fill the guardian 100/300 windows (fix #2) with REAL
  performance -> halt lifts only if PF/expectancy/drawdown bars pass ->
  A_GRADE_EXECUTION entries resume -> A-grade rows.
- No step can be faked: every link is closed-trade outcomes measured by the
  unchanged performance bars.

## Test state
735 native_trainer+paper-loop+inventory, 452 guardian+paper-loop rerun, 78 API,
1 scheduled-pretrain, 4 temporal-window — all green.

## Services
trainer + paper loop + guardian + backend restarted on the fixed code; all active.
Gate env unchanged (blocked_human_only); paper-only throughout.
