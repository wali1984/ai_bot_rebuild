# Master Rebuild Planner — Phase 2E1.B END_FILE Marker Discovery

## Decision

The Phase 2E1.B implementation files emitted by task 056 are **structurally broken** at the materialization layer. Every one of the 19 Python files (8 source modules under `v2/backend/app/domain/trainer_parity/` and 11 test files under `v2/backend/tests/unit/domain/trainer_parity/`) contains a trailing literal line of the form


at module top level. That line is bare unquoted text, not a comment, not a docstring, and not inside any block. Any Python interpreter attempting to compile or import these files will raise `SyntaxError`. Therefore:

- `pytest v2/backend/tests/unit/domain/trainer_parity/ -q` cannot succeed;
- task 058 (local validation) would record `PHASE2E1B_LOCAL_VALIDATION_FAILED` if dispatched as-is;
- task 057 (Codex review) cannot be reached;
- the Phase 2E1.B marker `PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW` currently in `32_2E1B_GO_NO_GO.md` is **not honest evidence** and must be downgraded.

The next safest non-live milestone is a Claude L1 remediation task (059) that strips the trailing `END_FILE:` line from each of the 19 files **using the Edit tool**, not via BEGIN_FILE/END_FILE blocks (the harness re-materializes those blocks with the same trailing marker, which is exactly how this bug was introduced).

## Raw evidence

`rg "^END_FILE:" v2/backend/app/domain/trainer_parity/` (planner turn, this session) — eight hits, one per source file, each on the file's last content line:

- `__init__.py:33`
- `errors.py:15`
- `feature_status_flags.py:111`
- `freshness_metadata.py:110`
- `stage_a_record.py:111`
- `stage_b_record.py:63`
- `lineage_validator.py:43`
- `explainability_validator.py:79`

`rg "^END_FILE:" v2/backend/tests/unit/domain/trainer_parity/` — eleven hits, one per test file, each on the file's last content line:

- `__init__.py:1` (the test package `__init__.py` is a single line: `END_FILE: v2/backend/tests/unit/domain/trainer_parity/__init__.py`; pytest collection imports this and will SyntaxError before any test runs)
- `conftest.py:111`
- `test_stage_a_record_invariants.py:92`
- `test_stage_b_record_invariants.py:93`
- `test_feature_status_flags.py:58`
- `test_feature_freshness_envelope.py:86`
- `test_freshness_metadata.py:101`
- `test_lineage_validator_stage_a.py:49`
- `test_lineage_validator_stage_b.py:84`
- `test_explainability_validator.py:133`
- `test_public_surface.py:48`

Spot-check of `v2/backend/app/domain/trainer_parity/errors.py` (full read this turn): the file ends on line 15 with `END_FILE: v2/backend/app/domain/trainer_parity/errors.py`, immediately following the closing line of `class TrainerParityLineageError`. No surrounding quotes, no `#`, no triple-string. Same shape across the other 18 files.

This is raw evidence; the failure mode is proved without invoking pytest.

## Why this is the safest action in this turn

- The remediation is a one-line deletion per file (the literal trailing `END_FILE: <path>` line). No logic change. No spec interpretation. No test rewrite.
- The fix must be applied via the Edit tool because BEGIN_FILE/END_FILE re-emission is what produced the bug. The remediation task explicitly forbids BEGIN_FILE/END_FILE blocks for the 19 Python files.
- Downgrading `32_2E1B_GO_NO_GO.md` to `PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED` immediately removes the predecessor marker for task 058 and task 057, preventing either from dispatching against broken sources.
- No legacy file is touched, no Redis traffic, no subprocess outside `python -m py_compile` and `grep`, no network, no GPU, no live trader, no live trainer.
- Risk class is L1, the lowest non-trivial level, matching tasks 056 and 058.

## Predecessors satisfied for this remediation

- `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS` — Phase 2E1.A is closed.
- Task 056 emitted the 19 source/test files (presence verified).
- Task 058 has not run; no validation marker exists; Codex 057 has not dispatched.

## What this turn does NOT do

- Does not run `pytest`. The failure mode is established by direct read; the planner does not need to burn a pytest run to confirm a top-level SyntaxError that is visible in the source.
- Does not advance Phase 2E1.C (prediction worker liveness). Phase 2E1.C remains gated on `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`.
- Does not advance REQ_0008 (enterprise website / animation system). The frontend track stays parked while the backend domain layer is broken.
- Does not invoke REQ_0007 Codex autofix scope. This bug is a pre-Codex materialization defect inside REQ_0006 implementation scope; Codex has not yet reviewed Phase 2E1.B and has not surfaced a blocker. Codex autofix is reserved for blockers Codex itself flags.
- Does not commit or push. Commit/push happens in the supervisor cycle after the remediation passes its own checks and after task 058 reports `PHASE2E1B_LOCAL_VALIDATION_PASSED`.
- Does not modify the eight V2 source files or eleven V2 test files in this planner turn. The remediation runs under task 059.
- Does not amend the spec, test plan, or safety-boundary documents. The defect is materialization, not specification.

## Hard stops respected

- No legacy file modified.
- No file under `/home/wali/Desktop/AI BOT/` read or modified.
- No `.env` read.
- No Redis access.
- No subprocess started by the planner this turn (only Read and Grep against the repo working tree).
- No exchange action.
- No leverage or margin change.
- No live trading flag changed.
- No deployment.
- No production migration.
- No secret value emitted.

## Artifacts dispatched in this turn

Planner control-plane note (this file):

- `claude_worklog/autonomous_control_plane/PLANNER_PHASE2E1B_END_FILE_MARKER_DISCOVERY.md`

Implementation worklog request:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/39_PHASE_2E1B_END_FILE_MARKER_REMEDIATION_REQUEST.md`

Supervisor task:

- `claude_worklog/agent_supervisor/tasks/059_trainer_parity_2e1b_endfile_marker_remediation.json` (new, Claude, L1)

Marker downgrade:

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/32_2E1B_GO_NO_GO.md` → `PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED`

## Predecessor chain after this turn

- 056 (impl): files emitted but materialized broken; marker downgraded to BLOCKED.
- 059 (END_FILE marker remediation): pending, predecessor `056` only; on PASS, re-emits `32_2E1B_GO_NO_GO.md` as `PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`.
- 058 (local validation): unchanged JSON; remains naturally gated because its required marker file is now BLOCKED, so the supervisor cannot dispatch 058 until 059 restores READY.
- 057 (Codex review): unchanged; remains gated on 058 PASS.

No update to the 058 or 057 task JSONs is required — the marker downgrade is sufficient to hold the chain.

## Markers

- Active requirement: `REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE`
- Active slice: 2E1.B (remediation sub-step)
- Slice status: implementation materialization defect detected; remediation dispatched; validation re-gated.

PLANNER_PHASE2E1B_END_FILE_MARKER_DISCOVERY_RECORDED
