# Immutable Validation Frontier Review Checkpoint — 2026-07-23 16:06:12 UTC

## Resume coordinates

- Authoritative worktree: `/tmp/codex-strategy-receipt-promotion`
- Branch: `codex/strategy-receipt-promotion-20260723`
- Parent commit: `0726342c345bd410331767dcaa18cb14f1028ff0`
- Prior implementation: `a18c2a4c50e390eba226c605fcdabe4ac6732a5d`
- Prior checkpoint: `0726342c345bd410331767dcaa18cb14f1028ff0`
- Family outcome: unsafe proposal rejected before commit; production source restored exactly
- Live/PAPER services changed or restarted: `0`
- Exchange/order/risk/allocator authority changed: `0`

## Evidence counts

- Active agents at once: `2` maximum
- Source modules inspected for the admission boundary: `1`
- Direct calibration boundaries inspected: `7`
- Candidate-proposal functions/properties reviewed: `9`
- Candidate/model/source/authorization/status fields checked: `65`
- Existing admission structural fields checked: `51`
- Existing V2 policy fields checked: `15`
- Existing admission tests inspected: `19`
- Ordinary validation-split source/CLI files indexed: `12`
- Ordinary `validation_fraction` references indexed: `68`
- Ordinary split callable/config boundaries indexed: `27`
- Adjacent upstream partition files/boundaries indexed: `2/3`
- Split telemetry references/files indexed: `107/5`
- Directly affected test files/functions indexed: `18/61`
- Focused candidate-family tests passed before rejection: `22/22`
- Six-suite regression tests passed before rejection: `134/134`
- Compile targets passed: `2/2`
- Ruff targets passed: `2/2`
- `git diff --check`: passed
- HTTP routes/endpoints/screenshots inspected: `0/0/0` (backend receipt review)
- V1/V2 compatibility defects found: `0`
- Blocking candidate/frontier defect groups found: `4`
- Nonblocking candidate-test defect groups found: `2`
- Production source/test files retained from the rejected proposal: `0`
- Defects remaining in this family: `4` blocking, `2` test-coverage groups

## What was rejected

A CAS-backed calibration candidate proposal was implemented locally and reached
`134/134` passing tests. It was not committed because passing tests did not
establish the provenance claims needed by a validation-start receipt.

The rejected proposal had four blocking defects:

1. **No canonical candidate.** The same model could mint multiple candidate
   artifacts from different caller-selected training subsets and frontiers.
   There was no unique model/cycle key, conflict rule, append receipt, record
   chain, head anchor, or authoritative current pointer.
2. **No provable non-observation.** A caller-provided outcome list cannot prove
   that validation outcomes were not already observed or that omitted outcomes
   do not exist.
3. **No durable frontier clock.** The artifact stored a clock sampled before CAS
   publication. A later postwrite clock check was process-local and discarded,
   so a restart verifier could not prove publication occurred before the
   proposed validation frontier.
4. **No restart-safe full-lineage replay.** A process HMAC could not survive a
   restart, while the public bytes verifier could not replay the source ledger,
   head anchors, full model binding, all causal clocks, and receipt chain.

The rejected tests also exercised the private row sealer rather than the public
durable-outcome API, and did not cover conflicting frontiers, restart/open,
idempotence, mixed models, duplicates, or semantic source-field tampering.

## Proven compatibility boundary

The following existing behavior remains byte-for-byte untouched at this
checkpoint:

- V1 legacy admission schema, calibration verifier, and evidence policy;
- V2 adaptive admission schema, calibration verifier, and evidence policy;
- `_PARTITION_METHOD` and the historical latest-identifiable-suffix replay;
- calibration admission SQLite schema and metadata;
- all current runtime wiring and authority flags.

This checkpoint therefore does not claim that the latest-suffix defect is fixed.
It records why a superficially immutable CAS object is insufficient and prevents
that object from being promoted as evidence.

## Exact next implementation family

Build a new append-only candidate/frontier ledger; do not mutate the existing
admission ledger schema. The new ledger must provide all of the following in one
reader-lease/single-transaction source snapshot and one durable write chain:

1. **Authoritative source snapshot**
   - ordered finalized-outcome inventory;
   - total source sequence;
   - finalized-outcome record-chain head;
   - terminal finalized-outcome head-anchor SHA-256;
   - exact source CAS byte addresses and replay verification;
   - same-model calibration projection digest;
   - source snapshot observed/readback clocks.
2. **Hypothesis terminal accounting**
   - complete committed-hypothesis cohort through a sealed commitment head;
   - one terminal disposition for every member: finalized eligible, finalized
     ineligible with reason, or durably pending with a causally valid reason;
   - no silent omission between the hypothesis head and outcome head.
3. **Canonical candidate uniqueness**
   - one immutable key per checkpoint/model fingerprint and calibration cycle;
   - idempotent replay for identical material;
   - conflict on a different train inventory, fit, or frontier for that key;
   - append receipt, record chain, postcommit readback receipt, and head anchor;
   - published head catalog that survives restart.
4. **Durably anchored frontier**
   - `latest_source_postcommit_readback_at < candidate_anchored_at`;
   - `candidate_anchored_at < first_forward_validation_decision_time`;
   - clock rollback fails closed;
   - the head-anchor time, not a caller assertion, is the lower-bound receipt.
5. **No authority before completeness**
   - candidate/frontier artifacts remain consumer-ineligible;
   - missing hypothesis accounting, source snapshot, CAS replay, or head anchor
     yields `WAITING_FOR_FORWARD_COHORT_COMPLETENESS` and zero optimizer rows;
   - no V3 admission is minted in this family.

## Required tests for the next family

- exact public API with real durable finalized outcomes;
- idempotent same-material sealing;
- conflicting frontier/train inventory for the same canonical key;
- mixed-model, duplicate, incomplete, and ineligible inventories;
- missing hypothesis terminal disposition;
- source ledger append during snapshot attempt;
- source CAS and every bound semantic field tamper;
- append/postcommit/head-anchor tamper and catalog gaps;
- clock equality, rollback, and `source_readback < anchor < validation decision`;
- restart/open and full replay from durable bytes without process secrets;
- V1 and V2 historical artifact verification unchanged;
- no candidate receipt can authorize optimizer, checkpoint, serving, paper, or
  live execution.

Only after this ledger passes should a separate family mint V3 receipt-bound
append-only validation admission. Removal of active `validation_fraction` comes
after role assignment is sealed over the authenticated corpus and before batch
truncation or optimizer-claim retries.

## Commands executed in this family

Read-only inspection used `git status`, `git diff`, `git rev-parse`, `rg`,
`sed`, `tail`, `find`, and `date`. Verification commands were:

```bash
python -m py_compile \
  v2/backend/app/services/native_trainer/profiled_research_calibration_admission_v1.py \
  v2/backend/tests/unit/services/native_trainer/test_profiled_research_calibration_admission_v1.py

PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/native_trainer/test_profiled_research_calibration_admission_v1.py

PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py \
  v2/backend/tests/unit/services/native_trainer/test_profiled_research_calibration_admission_v1.py \
  v2/backend/tests/unit/services/native_trainer/test_training_state.py \
  v2/backend/tests/unit/services/native_trainer/test_checkpoint_lifecycle.py \
  v2/backend/tests/unit/services/native_trainer/test_confidence_proportional_calibration.py \
  v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py

/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check \
  v2/backend/app/services/native_trainer/profiled_research_calibration_admission_v1.py \
  v2/backend/tests/unit/services/native_trainer/test_profiled_research_calibration_admission_v1.py

git diff --check
```

The first `python -m pytest` attempt used `/usr/bin/python` and failed before
collection because that interpreter has no `pytest`; it made no changes. The
repository virtual environment commands then passed as counted above.
