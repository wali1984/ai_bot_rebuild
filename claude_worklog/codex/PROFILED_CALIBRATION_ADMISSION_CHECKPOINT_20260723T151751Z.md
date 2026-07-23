# Profiled Calibration Admission Checkpoint — 2026-07-23 15:17:51Z

## Resume point

- Branch: `codex/strategy-receipt-promotion-20260723`
- Implementation commit: `3037d0085db63892f41b55d6306b42c6f805a963`
- Implementation remote parity: verified against `origin/codex/strategy-receipt-promotion-20260723`
- Worktree at implementation commit: clean
- Family completed: durable, model-bound, purged-forward calibration admission
- Runtime wiring changed: no
- Services restarted or mutated: 0
- Exchange/order/live-execution paths changed: 0

This is a component-family checkpoint, not a regenerated system atlas.

## Delivered boundary

The family consumes exact factory-built finalized outcome results and:

1. revalidates their canonical finalized-outcome artifacts;
2. enforces one exact checkpoint, generation, model-parameter fingerprint, and
   model-binding digest per admission;
3. selects the latest structurally identifiable chronological validation suffix
   without reading validation outcomes;
4. keeps identical `decision_time` cohorts together;
5. requires every purged-train label to be available strictly before the first
   forward-validation decision;
6. assigns every row exactly once to purged train, purge gap, or untouched
   forward validation;
7. fits temperature only on purged-train rows;
8. recomputes fit, partition, Brier uncertainty, delete-one ECE uncertainty,
   and global/per-action non-regression from sealed inventory during every
   artifact reopen;
9. copies admitted source artifacts and the admission artifact into immutable
   content-addressed storage;
10. records the admission in an append-only SQLite chain with receipts,
    externally published head anchors, source replay uniqueness, strict schema
    validation, immutable-row triggers, reader/writer inode leases, durable
    pragmas, bounded database/source/CAS resources, and explicit suffix-only
    recovery;
11. returns a factory-sealed result that reopens the ledger, CAS, source
    artifacts, receipts, and external head catalog before exposing authority;
12. authorizes calibration input and calibration-only checkpoint writing while
    denying optimizer execution, model-weight mutation, serving, paper/live
    trading, exchange, allocator, risk, deployment, and order authority.

An exact-byte downstream validator was also added to the finalized-outcome
ledger. No existing finalized-outcome authority was broadened.

## Evidence counts

### Routes and contracts

- Public Python routes inspected/implemented: 8
- HTTP routes: 0
- CLI routes: 0
- Runtime/service routes: 0
- Admission artifact top-level fields: 11
- Model-binding fields: 7
- Source-inventory fields per row: 19
- Partition-proof fields: 14
- Evidence-policy fields: 11
- Authorization fields: 19
  - true: 3 (`consumer_eligible`, `calibration_input_authorized`,
    `calibration_only_checkpoint_write_authorized`)
  - false: 16
- SQLite tables: 5
- SQLite indexes: 2
- SQLite immutability triggers: 10
- Exported symbols: 14
- PIT/durability clocks reviewed: 12
- HTTP endpoints compared: 0
- Screenshots captured: 0

### Verification

- Focused tests: 17/17 passed in 15.87 seconds
- Adjacent confidence/finalized-outcome tests: 51/51 passed in 137.55 seconds
- Total executed final regression cases: 68/68 passed
- Python syntax checks: 2/2 source files passed
- Ruff checks: 3/3 changed source/test files passed
- Mypy checks: 2/2 source files passed
- Diff whitespace checks: passed
- Frontend/mobile builds: 0 (not in this component family)
- Service/runtime smoke tests: 0 (family intentionally remains unwired)

The adjacent regression covered the existing confidence-calibration semantics,
directional profitability semantics, finalized outcome maturation, source-free
artifact contradiction rejection, and both binary directional calibration
classes. Previously proven system-wide audits were not rerun.

## Tests cover

- chronological purged partition and strict label availability;
- validation-label independence of partition selection;
- tied decision-time cohort integrity;
- exact recomputation of partition, fit, and validation proofs;
- paired Brier endpoint identity and uncertainty digest method binding;
- held forward-validation regression;
- idempotent durable append and restart-style reopen;
- factory-result mutation rejection;
- same-model/different-evidence conflict;
- schema and immutable CAS tamper detection;
- suffix head recovery and interior-gap rejection;
- unknown external head rejection;
- source-outcome CAS tamper detection;
- read-only missing-state behavior;
- reader/writer lease contention;
- aggregate source-CAS resource rejection before any write;
- exact real finalized-outcome waiting path with zero ledger/CAS-object writes;
- mixed-model, duplicate-row, non-sequence, non-byte, and duplicate-key input
  rejection.

## Files changed by implementation commit

- `v2/backend/app/services/native_trainer/profiled_research_calibration_admission_v1.py`
  (created; 3,024 lines before this checkpoint)
- `v2/backend/tests/unit/services/native_trainer/test_profiled_research_calibration_admission_v1.py`
  (created; 686 lines before this checkpoint)
- `v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py`
  (21 inserted lines: public exact-byte artifact validator/export)

## Defects remaining

Six tracked defects remain after this family:

1. No unchanged-weight calibration-only checkpoint promoter consumes this
   admission yet.
2. Publisher, ordinary PAPER lineage, and risk consumers still need exact
   equality binding between calibration fingerprint and the served
   checkpoint/model rather than shape-only validation.
3. No finalized-outcome admission/calibration-only CLI or runtime route is
   wired; this family deliberately grants no runtime authority.
4. Existing confidence fitting/evidence still uses fixed ECE bins and fixed
   temperature search bounds/grid/iteration heuristics. These must be replaced
   or derived adaptively before runtime release to satisfy the no-static-market-
   threshold objective.
5. Public preparation can be approximately quadratic when many supplied
   finalized outcomes share one source ledger because each factory result
   reopens and verifies that source ledger. A batch-verified source cursor is
   needed for large evidence sets.
6. Finalized-outcome record-chain/append/postcommit receipt digests are
   notarized by the admission after validating the factory result, but their
   receipt bodies are not copied. They are trust-on-admit references rather
   than independently portable source-ledger provenance.

The aggregate source-CAS byte-cap defect found during final review was fixed
and covered before the implementation commit.

## Next component family

Do not wire serving, PAPER, risk, live execution, or an ordinary optimizer
promotion path from this checkpoint.

Resume with one scoped family at a time:

1. remove/derive the fixed calibration evidence heuristics adaptively and add
   exact regression proofs;
2. add the unchanged-weight calibration-only checkpoint promoter without
   weakening ordinary optimizer promotion;
3. enforce calibration/checkpoint fingerprint equality at publisher, PAPER
   lineage, and risk read boundaries;
4. add the explicit finalized-outcome admission/calibration-only runtime route;
5. address batch source verification and portable source receipt bodies before
   treating very large admission sets as operationally scalable.

Commit and push each family, then write its own checkpoint. Do not regenerate a
full system atlas.

## Shell commands executed for this family

The family used these command groups (including iterative failing runs before
the final green run):

- `git status --short`, branch/HEAD/remote parity, `git diff --stat`,
  `git diff --numstat`, `git diff --check`, and scoped `git diff` inspections.
- `wc -l`, `sed -n`, `tail`, and `rg -n/-c/-l` inspections of the new admission
  module, finalized-outcome module, immutable CAS, confidence implementation,
  existing ledger hardening patterns, and relevant tests.
- `python -m py_compile` on both changed source modules.
- `python -m ruff check` on the two source files and new test file.
- `python -m mypy --follow-imports=skip` on the two changed source files.
- Synthetic Python admission/append/reopen/integrity smoke execution against a
  temporary SQLite ledger and immutable CAS.
- Focused pytest iterations on
  `test_profiled_research_calibration_admission_v1.py` (initial failures were
  corrected; final result 17/17).
- Adjacent pytest regression on `test_confidence_calibration.py`,
  `test_hybrid_confidence_profitability_semantics.py`, and three exact
  finalized-outcome cases (51/51).
- Contract-count Python inspection for artifact/model/source/partition/policy/
  authorization/schema/export counts.
- `git add`, cached diff check, implementation commit, and branch push.
