# Profiled Finalized Outcome Ledger Checkpoint

Timestamp: `2026-07-23T14:12:05Z`
Branch: `codex/strategy-receipt-promotion-20260723`
Implementation commit: `c4868f9abfefd8b2bf3cafcd48b590e201cd6f7c`
Family status: implementation complete, committed, pushed, and regression-clean

## Outcome

An exact, durably committed ex-ante profiled-research hypothesis can now mature
against the canonical finalized Binance 5-minute label archive without caller-
supplied clocks, prices, returns, labels, or outcomes. The ledger waits for the
actual label-availability boundary, verifies the archive receipt cutoff, copies
the exact finalized path into immutable content-addressed storage, recomputes
the archive range and label-path digest preimages, and binds every candle
identity and canonical payload to the stored outcome.

The selected action is preserved exactly as it existed at decision time. Long,
short, and hold counterfactual economics use the portable decision-time cost
closure; funding is signed oppositely for long and short; a directional
calibration observation is positive only when selected-action net PnL is
strictly greater than zero. Hindsight-best action remains a separate diagnostic
and cannot replace the selected action. Directional MFE/MAE excludes the
pre-decision part of an overlapping candle.

Outcome rows, append receipts, post-commit readback receipts, and independently
enumerable head anchors are append-only and hash chained. Reopen verifies the
SQLite schema, resource bounds, CAS membership, exact canonical JSON, source
commitment, source-free label/economics semantics, head catalog, and archive-
tail stability. Missing evidence, suffix truncation, broken symlinks, non-hex
catalog shards, clock ties/rollback, late archive receipts, and semantic
contradictions fail closed without self-healing.

The archive range proof now includes its exact `range_material` digest preimage,
making the durable proof independently recomputable. This is a compatible
additive proof field; all 93 adjacent archive/hypothesis/commitment regression
cases pass.

This family remains an unwired research primitive. It grants no trainer,
calibration, publisher, serving, PAPER, live, exchange, order, deployment, or
execution authority.

## Evidence counts

- Production files changed: 2
- Test files changed: 1
- Public ledger routes inspected and covered: 4 / 4
- HTTP/API endpoints compared or changed: 0 / 0
- Screenshots captured: 0
- Application builds applicable: 0
- Python byte-compile checks passed: 3 / 3 files
- Ruff checks passed: 3 / 3 files
- Strict mypy checks passed: 1 / 1 production module
- Commit whitespace checks passed: 1 / 1 commit
- Focused test functions: 30
- Focused parametrized test cases passed: 44 / 44
- Proof/catalog/microsecond boundary cases passed: 10 / 10
- Adjacent final-regression cases passed: 93 / 93
- Total final pytest cases passed: 137 / 137
- Exact contract fields checked: 108 / 108
- False downstream-authority fields checked: 18 / 18
- Outcome status fields checked: 8 / 8
- SQLite tables checked: 5 / 5
- SQLite persisted columns checked: 59 / 59
- SQLite indexes checked: 2 / 2
- SQLite immutability triggers checked: 10 / 10
- CAS families checked: 3 / 3 (outcome, candle, head anchor)
- Raw/logical outcome clocks distinguished: 5 / 5
- Source/runtime imports of the new ledger outside its test: 0
- Services restarted or activated: 0
- Redis reads/writes: 0 / 0
- Exchange/PAPER/live/order paths changed: 0
- Reviewer defects found in final proof/catalog pass: 3
- Reviewer defects fixed: 3 / 3
- Defects remaining in this family: 0
- Downstream family now queued: 1
- Implementation diff: 4,908 insertions, 0 deletions

## Four public ledger routes

1. `recover_pending_postcommit_readbacks`
2. `mature_hypothesis`
3. `open_matured_outcome`
4. `verify_integrity`

## Exact field coverage

- Outcome artifact: 15 fields
- Hypothesis binding: 23 fields
- Label-source binding: 15 fields
- Candle inventory row: 8 fields
- Economics: 34 fields
- Calibration row: 13 fields
- Total: 108 fields

## Five outcome clocks

1. `maturation_observed_at` — raw internal label-maturation observation
2. `commit_observed_at` — raw internal outcome-commit observation
3. `commit_prepared_at` — canonical logical append ordering clock
4. `postcommit_observed_at` — raw internal post-commit observation
5. `postcommit_readback_at` — canonical logical readback ordering clock

The source commitment additionally preserves `decision_time`,
`hypothesis_generated_at`, `label_earliest_available_at`, and its own commit and
post-commit clocks. Raw observations establish causality; logical clocks never
manufacture provenance.

## Retained invariants

- Only an exactly verified committed hypothesis may mature.
- No public maturation argument accepts a clock, price, return, label, or
  outcome.
- `decision_time` and the exact 900-second horizon determine the complete
  finalized 5-minute label path.
- Every candle must be final and its archive receipt committed no later than
  the internal maturation observation.
- `feature available_at > decision_time` remains forbidden upstream; label
  candles are used only after the decision and only for outcome maturation.
- A candle overlapping `decision_time` contributes the exit path but its
  pre-decision interval cannot contribute MFE/MAE.
- Selected action is never replaced by the hindsight-best action.
- Exact zero selected-action net PnL is not profitable.
- Every stored range digest, label-path digest, candle content digest, outcome
  digest, receipt digest, chain link, and head anchor is recomputed on reopen.
- A reader lease spans the SQLite database, commitment CAS, label archive,
  outcome/candle CAS, and external head catalog.
- All 18 downstream-authority values remain exact booleans set to `false`.

## Validation commands

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py v2/backend/app/services/native_trainer/durable_canonical_5m_label_archive.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m ruff check v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py v2/backend/app/services/native_trainer/durable_canonical_5m_label_archive.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m mypy --strict v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py -k 'source_free or head_catalog or decision_one'
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_durable_canonical_5m_label_archive.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_shadow_hypothesis_commitment_v1.py
git diff --check
git diff --cached --check
git show --check --oneline c4868f9abfefd8b2bf3cafcd48b590e201cd6f7c
```

Focused result: `44 passed in 513.45s`.

Proof/catalog/microsecond boundary result: `10 passed, 34 deselected in
120.84s`.

Adjacent final-regression result: `93 passed in 248.02s`.

## Honest downstream state

The finalized-label outcome-maturation blocker is closed. The durable result
is calibration evidence only; it is intentionally not yet admitted to trainer
calibration or publisher activation. The next family is the calibration-
admission/publisher boundary: consume only fully verified directional rows,
retain PIT/finality lineage, establish adaptive evidence sufficiency without a
static market threshold, and keep runtime activation fail-closed until its own
commit, checkpoint, and final regression are complete.

Publisher activation remains blocked on that next family. This checkpoint does
not claim that trainer publishing or any trading service is online.

## Files in the implementation commit

- `v2/backend/app/services/native_trainer/durable_canonical_5m_label_archive.py`
- `v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py`
