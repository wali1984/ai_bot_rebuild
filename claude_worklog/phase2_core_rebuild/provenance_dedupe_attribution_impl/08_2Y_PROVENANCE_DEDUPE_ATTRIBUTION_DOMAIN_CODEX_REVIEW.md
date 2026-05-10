# Phase 2Y Provenance Dedupe Attribution Domain Codex Review

## Files reviewed

- Phase 2Y documentation: `00_PHASE_2Y_SCOPE.md`, `01_PHASE_2Y_LEGACY_EVIDENCE_REVIEW.md`, `02_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SPEC.md`, `03_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TEST_PLAN.md`, `04_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SAFETY_BOUNDARIES.md`, `05_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_GO_NO_GO_REQUEST.md`, `06_IMPLEMENTATION_REPORT.md`, `07_GO_NO_GO.md`.
- Planner-turn notes: `PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_OPEN_AND_2X_RECONCILIATION_AT_HEAD_BDB268B.md`, `PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TASK_193_AUTHORED.md`, `PLANNER_TURN_2Y_TASK_193_EVIDENCE_FIRST_RECONCILED_AND_TASK_194_AUTHORED.md`.
- Prior evidence: Phase 2W recommendation and Codex review, Phase 2X.B reconciliation marker, LAB hedge-unwind evidence, Phase 2G risk gateway evidence and Codex marker, legacy build impact map line 31, Phase 2V trainer-parity spec line 19 and Codex marker, V2 lineage chain, legacy failure register, and final readiness marker.
- V2 source: 11 files under `v2/backend/app/{domain,services,composition}/provenance_dedupe_attribution/`.
- V2 unit tests: 43 Python test/fixture/package files under `v2/backend/tests/unit/{domain,services,composition}/provenance_dedupe_attribution/`.

## Step 1 - predecessor markers

Command: `head -1` over the nine requested marker files.
Stdout:
- `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED`
- `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED`
- `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY`
- `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_CODEX_PASS`
- `V2_BACKTEST_AND_PAPER_MVP_READY`
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`
- `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS`
- `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS`
- `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`
Result: PASS.

## Step 2 - focused pytest

Command: `PYTHONPATH=. ./.venv/bin/python -m pytest v2/backend/tests/unit/domain/provenance_dedupe_attribution/ v2/backend/tests/unit/services/provenance_dedupe_attribution/ v2/backend/tests/unit/composition/provenance_dedupe_attribution/ -x -q`
Stdout: `43 passed in 0.06s`.
Result: PASS.

## Step 3 - smoke import

Command: `PYTHONPATH=. python3 -c "from ...; print('ok')"`
Stdout: `ok`
Result: PASS.

## Step 4 - no Redis / FastAPI / Starlette source grep

Command: `grep -nR "redis\|aioredis\|redis.asyncio\|fastapi\|starlette" v2/backend/app/domain/provenance_dedupe_attribution/ v2/backend/app/services/provenance_dedupe_attribution/ v2/backend/app/composition/provenance_dedupe_attribution/ 2>/dev/null`
Stdout: empty.
Result: PASS.

## Step 5 - no lifespan or router registration in package init files

Command: `grep -nR "add_event_handler\|lifespan\|FastAPI\|APIRouter" .../__init__.py 2>/dev/null`
Stdout: empty.
Result: PASS.

## Step 6 - runtime clock policy

Files read: `runtime.py`, `test_runtime_provenance_now_invokes_clock_zero_times_per_call.py`, `test_runtime_dedupe_decision_now_invokes_clock_zero_times_per_call.py`, `test_runtime_does_not_invoke_clock_at_build_time.py`, `test_runtime_validates_now_ms_clock.py`.
Findings:
- `build_provenance_dedupe_attribution_runtime` validates `now_ms_clock` with `callable`.
- The supplied clock is captured and never invoked at build time.
- `provenance_now` delegates to `assemble_provenance_record` without invoking the clock.
- `dedupe_decision_now` delegates to `assemble_dedupe_decision_record` without invoking the clock.
Result: PASS.

## Step 7 - live_blocked invariant

Files read: `provenance_record.py`, `dedupe_decision_record.py`.
Findings:
- `ProvenanceRecord.__post_init__` calls `_validate_live_blocked`, which raises `ProvenanceDedupeAttributionDomainError` unless `live_blocked is True`.
- `DedupeDecisionRecord.__post_init__` calls the same validator and rejects `live_blocked=False`.
Result: PASS.

## Step 8 - duplicate_of_decision_id invariant

Files read: `dedupe_decision_record.py` and the five requested dedupe-state tests.
Findings:
- `DEDUPE_DUPLICATE_OF_PRIOR` requires non-`None` `duplicate_of_decision_id` and validates it as a non-empty, no-whitespace ID at most 128 chars.
- `DEDUPE_NEW` and `DEDUPE_STALE_OUT_OF_ORDER` reject any non-`None` `duplicate_of_decision_id`.
- The requested construction/rejection tests cover those state transitions.
Result: PASS.

## Step 9 - deterministic ID derivation

Files read: `provenance_service.py`, `dedupe_service.py`, spec file `02`, deterministic service tests, and public-surface tests.
Findings:
- `provenance_id` is derived as `f"prov:{decision_id}:{source_id}:{ingestor_id}"[:128]`.
- `dedupe_decision_id` is derived as `f"dedupe:{decision_id}:{dedupe_state}"[:128]`.
- These are deterministic derivations from existing decision context, not new lineage IDs.
- Public surfaces expose only the specified domain records/constants/errors, assemblers/errors, and runtime/factory/error.
Result: PASS.

## Step 10 - duplicate_signal_blocked trainer-parity regression fixture

Files read: Phase 2V trainer-parity spec line 19, `_fixtures.py`, and the four requested propagation tests.
Findings:
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` line 19 records `duplicate_signal_blocked` as `model_version=hybrid_trainer_v2026_05`, `checkpoint_id=ckpt_duplicate_signal_blocked_2026_05`, `confidence_raw=0.77`, `confidence_calibrated=0.74`, `trainer_worker_liveness=alive`.
- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/_fixtures.py` uses the matching model version, checkpoint ID, and liveness, but uses `confidence_raw=0.71` and `confidence_calibrated=0.68`.
- The four requested tests propagate the fixture values successfully, but they do not match the actual Phase 2V line 19 row on disk.
Result: FAIL.

Per-test result:
- `test_provenance_record_carries_phase_2v_trainer_parity_fields.py`: FAIL - carries fixture values `0.71` / `0.68`, not the Phase 2V line 19 row values `0.77` / `0.74`.
- `test_dedupe_decision_record_carries_phase_2v_trainer_parity_fields.py`: FAIL - carries fixture values `0.71` / `0.68`, not the Phase 2V line 19 row values `0.77` / `0.74`.
- `test_provenance_service_propagates_phase_2v_trainer_parity_fields.py`: FAIL - propagates fixture values `0.71` / `0.68`, not the Phase 2V line 19 row values `0.77` / `0.74`.
- `test_dedupe_service_propagates_phase_2v_trainer_parity_fields.py`: FAIL - propagates fixture values `0.71` / `0.68`, not the Phase 2V line 19 row values `0.77` / `0.74`.

## Step 11 - typed-contract-only scope

Files read: domain, services, and composition `__init__.py` files.
Scope checks:
- No paper trader, shadow trader, live trader, replay engine, scheduler, background loop, FastAPI surface, Redis adapter, GPU runner, model-loading subsystem, or strategy library: PASS.
- No new lineage ID beyond mirrored `decision_id`, `prediction_id`, `feature_snapshot_id`, `risk_decision_id`, and the five Phase 2V trainer-parity fields; `provenance_id` and `dedupe_decision_id` are deterministic derivations: PASS.
- `ProvenanceRecord` and `DedupeDecisionRecord` public surfaces match spec `02`: PASS.
Result: PASS.

## Step 12 - no prior-milestone byte mutation

Command: `git diff --stat HEAD~1..HEAD -- :(exclude)v2/backend/app/domain/provenance_dedupe_attribution/ :(exclude)v2/backend/app/services/provenance_dedupe_attribution/ :(exclude)v2/backend/app/composition/provenance_dedupe_attribution/ :(exclude)v2/backend/tests/unit/domain/provenance_dedupe_attribution/ :(exclude)v2/backend/tests/unit/services/provenance_dedupe_attribution/ :(exclude)v2/backend/tests/unit/composition/provenance_dedupe_attribution/ :(exclude)claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/ :(exclude)claude_worklog/agent_supervisor/tasks/193_phase2y_provenance_dedupe_attribution_domain_implementation.json :(exclude)claude_worklog/agent_supervisor/tasks/codex_recover_193_phase2y_provenance_dedupe_attribution_domain_implementation.json :(exclude)claude_worklog/agent_supervisor/`
Stdout: empty.
Result: PASS.

## Step 13 - eight-doc byte-clean marker check

Commands: `tail -1`, `wc -l`, and grep for markdown fence wrappers or standalone `END_FILE` markers across docs `00` through `07`.
Results:
- `00_PHASE_2Y_SCOPE.md`: tail `PHASE_2Y_SCOPE_READY`, `17` lines, no fence or standalone `END_FILE`: PASS.
- `01_PHASE_2Y_LEGACY_EVIDENCE_REVIEW.md`: tail `PHASE_2Y_LEGACY_EVIDENCE_REVIEW_READY`, `11` lines, no fence or standalone `END_FILE`: PASS.
- `02_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SPEC.md`: tail `PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SPEC_READY`, `15` lines, no fence or standalone `END_FILE`: PASS.
- `03_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TEST_PLAN.md`: tail `PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TEST_PLAN_READY`, `11` lines, no fence or standalone `END_FILE`: PASS.
- `04_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SAFETY_BOUNDARIES.md`: tail `PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_SAFETY_BOUNDARIES_READY`, `14` lines, no fence or standalone `END_FILE`: PASS.
- `05_PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_GO_NO_GO_REQUEST.md`: tail `PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_GO_NO_GO_REQUEST_READY`, `15` lines, no fence or standalone `END_FILE`: PASS.
- `06_IMPLEMENTATION_REPORT.md`: tail `PHASE_2Y_IMPLEMENTATION_REPORT_READY`, `23` lines, no fence or standalone `END_FILE`: PASS.
- `07_GO_NO_GO.md`: exactly one line `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED`, no fence or standalone `END_FILE`: PASS.
Result: PASS.

## Hard-boundary verification

- No `/home/wali/Desktop/AI BOT` modification: PASS.
- No Redis key read/write and no Redis command invocation: PASS.
- No live exchange API or Binance HTTP API call: PASS.
- No leverage or margin change: PASS.
- No live service restart: PASS.
- No deployment and no production migration: PASS.
- No secret exposure or credential commit: PASS.
- No execution-side surface introduction: PASS.
- No new lineage ID introduction; `provenance_id` and `dedupe_decision_id` are deterministic derivations of existing IDs and not new lineage IDs: PASS.
- No live-gate flip: PASS.
- No V2 source/test mutation by this Codex review: PASS.
- No prior-milestone byte mutation by this Codex review, including the now-prior 2X `external_manual_position_quarantine_impl/` directory: PASS.

## Final determination

Overall result: FAIL.

Blocker:
- Phase 2Y trainer-parity fixture values for the `duplicate_signal_blocked` regression do not match the actual Phase 2V spec row at `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` line 19. The Phase 2Y fixture and propagation tests use `confidence_raw=0.71` and `confidence_calibrated=0.68`; the cited Phase 2V row uses `confidence_raw=0.77` and `confidence_calibrated=0.74`.

PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REVIEW_READY
