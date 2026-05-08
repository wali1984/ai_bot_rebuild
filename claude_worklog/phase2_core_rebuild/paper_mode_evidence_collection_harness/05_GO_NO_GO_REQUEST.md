# Phase 2N — GO/NO-GO Request

## Acceptance criteria

The supervisor task `165_phase2n_paper_mode_evidence_collection_harness_implementation` MUST satisfy all of the following before writing the success marker `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY` to `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/07_GO_NO_GO.md`:

1. Exactly four authored Python files exist under `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`:
   - `__init__.py` — empty package shim.
   - `fixtures.py` — deterministic evidence-pack factory per `02_TYPED_INPUT_FIXTURE_SPEC.md`.
   - `harness.py` — pure-function harness `replay_paper_mode_evidence_pack` + test-only `PaperModeEvidenceTrio` per `03_HARNESS_PIPELINE_SPEC.md`.
   - `test_paper_mode_evidence_collection_harness.py` — pytest module per `04_TEST_PLAN.md`.
2. The 13 required pytest functions defined in `04_TEST_PLAN.md` § "Required test functions" all pass under `python -m pytest v2/backend/tests/unit/paper_mode_evidence_collection_harness/test_paper_mode_evidence_collection_harness.py -v --no-header`.
3. `git diff --stat HEAD -- v2/backend/app/` reports no change.
4. `git diff --stat HEAD --` against every Phase 2 prior-milestone directory under `claude_worklog/phase2_core_rebuild/` reports no change.
5. `git diff --stat HEAD -- /home/wali/Desktop/AI\ BOT` reports no change.
6. `06_IMPLEMENTATION_REPORT.md` exists with body containing per-scenario typed step counts, lineage carry-over coverage, paper-mode flag invariants asserted, the read-only legacy evidence pointers per `01_LEGACY_FAILURE_EVIDENCE.md`, and any Phase 2N-layer typing limitation. The report ends with the marker `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_REPORT_READY`.
7. `07_GO_NO_GO.md` exists with body exactly `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY`.
8. No file under `v2/backend/app/`, no file under `claude_worklog/phase2_core_rebuild/` other than the two implementation artifacts (06–07), no file under `claude_worklog/agent_supervisor/tasks/`, no file under `claude_worklog/autonomous_control_plane/`, no file under `/home/wali/Desktop/AI BOT`, and no Redis key is modified.

## Hard safety boundaries (restated)

- No `/home/wali/Desktop/AI BOT` mutation.
- No Redis read or write.
- No live service restart.
- No exchange order placement, cancellation, leverage change, margin change, or position-mode change.
- No live trading enablement.
- No deployment.
- No production migration.
- No secret read, print, or commit.
- No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- No standalone harness `BEGIN_FILE` / `END_FILE` framing token marker line in any authored file body.

## Success / failure markers

- Success marker: `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY` in `07_GO_NO_GO.md`.
- Failure marker: `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_FAIL` in `07_GO_NO_GO.md`.
- Implementation report marker (in `06_IMPLEMENTATION_REPORT.md`): `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_REPORT_READY`.

## Codex review gate (subsequent task)

On local PASS, the planner authors `166_phase2n_paper_mode_evidence_collection_harness_codex_review` scoped to the Phase 2N packet (00–07) and the four test-only files under `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`. The Codex review verifies the typed mirror projection per `03_HARNESS_PIPELINE_SPEC.md`, the fixture invariants per `02_TYPED_INPUT_FIXTURE_SPEC.md`, the test plan per `04_TEST_PLAN.md`, and that no file under `v2/backend/app/` is modified, no `/home/wali/Desktop/AI BOT` mutation, no Redis access, no live action, no secret exposure, and no live-readiness gate flip. Codex review marker: `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` or `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_FAIL`.

PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_GO_NO_GO_REQUEST_READY
