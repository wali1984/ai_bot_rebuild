# PLANNER TURN — Phase 2R Consolidated END_FILE Marker Leakage Discovery (Lane C `codex_watchdog`; underlying milestone Lane B `explainability_ui` Phase 2R)

## Active requirement

REQ_0006 (Phase 2 trainer-parity rebuild) under concurrent enforcement of REQ_0009 (full decision explainability and under-the-hood UI), REQ_0017 (force paper/backtest MVP track), REQ_0018 (planner lane lock), REQ_0020 (full autonomous legacy-mapped paper/backtest performance target), REQ_0014 / REQ_0015 / REQ_0016 (Codex non-live human-replacement watchdog and planner-level human-attention autorecovery), REQ_0011 / REQ_0021 (parallel Codex review and capacity scheduler), REQ_0007 (Codex autofix authority for non-live blockers), REQ_0010 (safe path remap autorecovery).

## Active milestone

Phase 2R — Decision Explainability Data Contract — first post-consolidation Lane B `explainability_ui` milestone after `V2_BACKTEST_AND_PAPER_MVP_READY`. Implementation marker `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_IMPLEMENTATION_READY` is materialized at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/07_GO_NO_GO.md` body line one.

## Trigger

A wider scan against the dirty worktree at HEAD `1e05026` extends the prior `PLANNER_TURN_2R_PYTHON_SOURCE_END_FILE_LEAKAGE_RECOVERY.md` finding. Two additional standalone module-level `END_FILE: <path>` framing-token lines have leaked beyond the four authored Python files in `v2/backend/tests/unit/decision_explainability_data_contract/`. Verified by `Grep -n '^END_FILE:' claude_worklog/agent_supervisor/tasks/` filtered to `*phase2r*`:

- `claude_worklog/agent_supervisor/tasks/codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup.json:218:END_FILE: claude_worklog/agent_supervisor/tasks/codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup.json`
- `claude_worklog/agent_supervisor/tasks/174_phase2r_decision_explainability_data_contract_codex_review.json:303:END_FILE: claude_worklog/agent_supervisor/tasks/174_phase2r_decision_explainability_data_contract_codex_review.json`

In each case the leaked line follows the JSON object's closing `}`, making the file invalid JSON. `python -m json.tool` rejects both files with `Extra data: line 218 column 1 (char ...)` and `Extra data: line 303 column 1 (char ...)` respectively. The supervisor's task loader cannot parse either file; consequently the Phase 2R Python-source cleanup recovery task cannot be dispatched, and the downstream `174_phase2r_decision_explainability_data_contract_codex_review` Codex review task cannot be dispatched after recovery.

The leaked lines are byte-narrow tail lines: every other byte of every other line in both task JSONs matches the planner's authored intent (allowed_output_prefixes, required_output_files, forbidden_actions, prompt, validation_commands, success/failure markers). Cleanup is a strict one-line strip per file matching `^END_FILE: claude_worklog/agent_supervisor/tasks/.+\.json$`.

The four authored Python files under `v2/backend/tests/unit/decision_explainability_data_contract/` retain the original four leaked tail lines verified by `Grep -n '^END_FILE:' v2/backend/tests/unit/decision_explainability_data_contract/`:

- `__init__.py:2:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/__init__.py`
- `fixtures.py:187:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/fixtures.py`
- `harness.py:82:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/harness.py`
- `test_decision_explainability_data_contract.py:276:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/test_decision_explainability_data_contract.py`

Total leaked-tail-line cleanup scope is six files: four authored Python source files plus two supervisor task JSONs.

## Classification

Lane C `codex_watchdog` autorecovery for an L1 non-live test-only Python source-byte leakage and an L1 non-live supervisor-task-JSON byte leakage. No new lineage IDs, no new typed surfaces, no new V2 `app/` adapter / domain / service / API / scheduler / FastAPI surface, no Redis access, no `/home/wali/Desktop/AI BOT` mutation, no exchange action, no live-readiness gate flip, no Binance read-only account-history endpoint invocation, no secret read or print, no master planner prompt mutation. Cleanup scope is the six leaked files plus this planner-turn note plus the new consolidated recovery task JSON plus the recovery report and GO/NO-GO marker.

## Decision

Author and queue Codex consolidated recovery task `codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup` in this same planner turn. The new task supersedes the broken predecessor `codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup` in scope and dispatch authority because the predecessor is itself invalid JSON and cannot be loaded by the supervisor. The supervisor reclassifies the broken predecessor as `superseded_by_evidence` per REQ_0014 / REQ_0015 / REQ_0016 once the consolidated recovery completes; the broken predecessor's untracked-file body is rewritten in-place by this consolidated recovery's byte-narrow cleanup pass.

Recovery scope:

- Strip exactly one trailing standalone line matching `^END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/.+$` from each of the four authored Python files. Preserve every other byte of every other line, including the docstring on `__init__.py` line 1, the `return tuple(rows)` on `fixtures.py` line 186, the closing brace of the per-row `DecisionExplainabilityEnvelope` projection construction on `harness.py` line 81, and the `return decision_explainability_data_contract_harness(inputs)` on `test_decision_explainability_data_contract.py` line 275.
- Strip exactly one trailing standalone line matching `^END_FILE: claude_worklog/agent_supervisor/tasks/.+\.json$` from each of the two supervisor task JSON files (`codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup.json` and `174_phase2r_decision_explainability_data_contract_codex_review.json`). Preserve every other byte of every other line, including each JSON object's closing `}` on the line preceding the leaked tail.
- Validate that both cleaned task JSON files now parse: `python3 -c 'import json; [json.load(open(p)) for p in ["claude_worklog/agent_supervisor/tasks/codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup.json","claude_worklog/agent_supervisor/tasks/174_phase2r_decision_explainability_data_contract_codex_review.json"]]'` must exit 0.
- Validate that the test package now collects: `python -m pytest v2/backend/tests/unit/decision_explainability_data_contract/ --collect-only -q` returns a non-zero collected count and exit 0.
- Validate that the implementation-report-claimed 16 passing tests run cleanly: `python -m pytest v2/backend/tests/unit/decision_explainability_data_contract/test_decision_explainability_data_contract.py -v --no-header` exits 0 and reports exactly `16 passed`.
- Forbidden-token grep over the six cleaned files plus this planner-turn note must exit 1 (no matches): `rg -n '^[[:space:]]*(END_FILE|BEGIN_FILE):' v2/backend/tests/unit/decision_explainability_data_contract/ claude_worklog/agent_supervisor/tasks/codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup.json claude_worklog/agent_supervisor/tasks/174_phase2r_decision_explainability_data_contract_codex_review.json`.
- High-confidence secret scan over the six cleaned files plus the recovery report and GO/NO-GO marker must exit 1.
- `git status --porcelain` must show only the six cleaned files plus this planner-turn note plus the consolidated recovery task JSON plus the recovery report and GO/NO-GO marker (and the standing worktree-excluded paths) as dirty.
- Two-commit pattern: first commit stages the six cleaned files plus this planner-turn note plus the consolidated recovery task JSON; second commit stages the recovery report and GO/NO-GO marker. Push after each.
- Do NOT modify the parallel-readonly-review report or GO/NO-GO file at `parallel_capacity_readonly_review_phase2r_decision_explainability_data_contract_implementation_ready_*.md` (frozen evidence-of-trigger).
- Do NOT modify the Phase 2R packet's six markdown planning files (`01_LEGACY_FAILURE_EVIDENCE.md` through `05_GO_NO_GO_REQUEST.md` plus `PLANNER_TURN_2R_OPEN_IMPLEMENTATION.md`), the implementation report (`06_IMPLEMENTATION_REPORT.md`), the implementation GO/NO-GO marker (`07_GO_NO_GO.md`), the prior reconciliation / residual-leakage planner-turn notes, the open-Codex-review planner-turn note, the prior Python-source recovery planner-turn note, the supervisor task 173 JSON, the parallel-capacity readonly review supervisor task JSON, the prior `codex_recover_173_phase2r_*` task JSONs, the prior `codex_recover_173_phase2r_*` recovery reports, or the master planner prompt.

The two markdown planner-turn notes (`PLANNER_TURN_2R_PYTHON_SOURCE_END_FILE_LEAKAGE_RECOVERY.md` line 80 and `PLANNER_TURN_2R_OPEN_CODEX_REVIEW.md` line 96) also carry trailing standalone `END_FILE: <path>` lines but are explicitly out of scope for this cleanup: markdown parses cleanly with the trailing line and the consolidated recovery does not block the dispatch path on visual noise. Future watchdog turns may sweep them in a separate cleanup pass without blocking Phase 2R Codex review dispatch.

## Recovery success markers

- PASS body line one at `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup_GO_NO_GO.md`: `CODEX_NON_LIVE_RECOVERY_READY`.
- FAIL body line one at the same file (with explicit blocker description in the recovery report): `CODEX_NON_LIVE_RECOVERY_BLOCKED`.
- Recovery report final non-blank body line at `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_173_phase2r_consolidated_python_source_and_task_json_end_file_leakage_cleanup_REPORT.md`: `CODEX_RECOVER_173_PHASE2R_CONSOLIDATED_PYTHON_SOURCE_AND_TASK_JSON_END_FILE_LEAKAGE_CLEANUP_REPORT_READY`.

## Next steps after recovery PASS

On `CODEX_NON_LIVE_RECOVERY_READY`, the supervisor:

1. Reclassifies the parallel-readonly-review supervisor task `parallel_capacity_readonly_review_phase2r_decision_explainability_data_contract_implementation_ready` as `superseded_by_evidence` per REQ_0014 / REQ_0015 / REQ_0016 (the BLOCKED finding is now resolved by the source-byte cleanup; the parallel-readonly-review GO/NO-GO file remains a frozen evidence-of-trigger artifact).
2. Reclassifies the broken predecessor recovery task `codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup` as `superseded_by_evidence` (its body has been byte-narrow-cleaned in place by this consolidated recovery and its scope is fully covered).
3. Dispatches supervisor task `174_phase2r_decision_explainability_data_contract_codex_review` against the now-clean worktree. The task carries `requires_clean_worktree=true` with `worktree_excluded_paths` covering the master planner prompt, the parallel-capacity readonly review supervisor task JSON, and the parallel-readonly-review report and GO/NO-GO file.
4. On Codex PASS at `09_CODEX_GO_NO_GO.md` with body line one `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_CODEX_PASS`, the planner opens the next post-consolidation Lane B `explainability_ui` milestone per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` — either a per-row paper-execution-ledger explainability envelope projection harness, or a per-row replay-backtest-runner explainability envelope projection harness, or the 30-day Binance read-only account-history pull (REQ_0024) wiring as a separate non-live milestone (the `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` posture remains in effect until secret-handling and 30-day-Binance-pull preconditions are independently approved). Live trading remains blocked.
5. On Codex FAIL with concrete documentation blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the Phase 2R packet only.
6. On Codex FAIL that is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A through 2Q reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/` and rewrites `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent.

## Hard safety boundaries (restated)

- No `/home/wali/Desktop/AI BOT` mutation.
- No Redis read or write; no Redis adapter.
- No live service restart; no live-trader / live-orchestrator / live-trainer process modification.
- No exchange order placement or cancellation; no leverage / margin change; no live trading enablement.
- No deployment; no production migration.
- No secret read, print, or commit.
- No Binance read-only account-history endpoint invocation.
- No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- No file under `v2/backend/app/` modified.
- No file under `v2/frontend/` modified.
- No file under `v2/backend/tests/unit/` modified outside the four named files in `v2/backend/tests/unit/decision_explainability_data_contract/`.
- No file under `claude_worklog/agent_supervisor/tasks/` modified outside the two named broken supervisor task JSONs and this consolidated recovery task JSON.
- No prior-milestone Phase 2 artifact byte content modified.
- No Phase 2R planning artifact (01–05), implementation report (06), implementation GO/NO-GO marker (07), prior reconciliation / residual-leakage / open-Codex-review / Python-source recovery planner-turn notes, parallel-readonly-review report, parallel-readonly-review GO/NO-GO, supervisor task 173 JSON, prior `codex_recover_173_phase2r_*` task JSONs, prior `codex_recover_173_phase2r_*` recovery reports, or master planner prompt modified by the recovery.

PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_PLANNER_TURN_CONSOLIDATED_END_FILE_LEAKAGE_DISCOVERY_READY
