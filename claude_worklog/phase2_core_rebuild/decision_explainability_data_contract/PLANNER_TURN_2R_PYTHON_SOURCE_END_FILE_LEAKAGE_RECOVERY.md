# PLANNER TURN — Phase 2R Python-Source END_FILE Marker Leakage Autorecovery (Lane C `codex_watchdog`; underlying milestone Lane B `explainability_ui` Phase 2R)

## Active requirement

REQ_0006 (Phase 2 trainer-parity rebuild) under concurrent enforcement of REQ_0009 (full decision explainability and under-the-hood UI), REQ_0017 (force paper/backtest MVP track), REQ_0018 (planner lane lock), REQ_0020 (full autonomous legacy-mapped paper/backtest performance target), REQ_0014 / REQ_0015 / REQ_0016 (Codex non-live human-replacement watchdog and planner-level human-attention autorecovery), REQ_0011 / REQ_0021 (parallel Codex review and capacity scheduler), REQ_0007 (Codex autofix authority for non-live blockers), REQ_0010 (safe path remap autorecovery), REQ_0019 / REQ_0023 (legacy monitor / read-only audit evidence consulted during V2 build).

## Active milestone

Phase 2R — Decision Explainability Data Contract — first post-consolidation Lane B `explainability_ui` milestone after `V2_BACKTEST_AND_PAPER_MVP_READY`. Implementation marker `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_IMPLEMENTATION_READY` is materialized at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/07_GO_NO_GO.md` body line one. Codex review supervisor task `174_phase2r_decision_explainability_data_contract_codex_review` is authored under `claude_worklog/agent_supervisor/tasks/`.

## Trigger

Lane C parallel-capacity read-only review per REQ_0021 ran against the committed `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_IMPLEMENTATION_READY` marker and returned `CODEX_PARALLEL_READONLY_REVIEW_BLOCKED` at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/parallel_capacity_readonly_review_phase2r_decision_explainability_data_contract_implementation_ready_GO_NO_GO.md`. The reviewer report at `parallel_capacity_readonly_review_phase2r_decision_explainability_data_contract_implementation_ready_REPORT.md` lists three concrete blockers, all reducible to one root cause:

The four authored Python files under `v2/backend/tests/unit/decision_explainability_data_contract/` each carry one trailing standalone module-level `END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/<basename>` line as bare Python source rather than as the harness framing token. The leak is byte-narrow and identical in shape to the prior reconciliation-tail leakage on the markdown documentation outputs (cleaned by `codex_recover_173_phase2r_reconciliation_residual_end_file_marker_leakage_cleanup`), but this round leaked into authored test-package source under `v2/`. The four leaked lines are (verified by `Grep '^[[:space:]]*END_FILE' v2/backend/tests/unit/decision_explainability_data_contract/`):

- `v2/backend/tests/unit/decision_explainability_data_contract/__init__.py:2:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/__init__.py`
- `v2/backend/tests/unit/decision_explainability_data_contract/fixtures.py:187:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/fixtures.py`
- `v2/backend/tests/unit/decision_explainability_data_contract/harness.py:82:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/harness.py`
- `v2/backend/tests/unit/decision_explainability_data_contract/test_decision_explainability_data_contract.py:276:END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/test_decision_explainability_data_contract.py`

Python parses each leaked line as a module-level annotated-assignment statement of the form `END_FILE: <annotation_expr>`. The annotation expression `v2/backend/tests/unit/decision_explainability_data_contract/<basename>` is evaluated at import time as a chain of `truediv` operations starting from the bare name `v2`. Because no module-level binding `v2` exists inside the test package, evaluation raises `NameError: name 'v2' is not defined` the first time the package initializer is imported. The package initializer is imported by `pytest` collection before any test function runs; collection fails with the `NameError`, no test is exercised, and the implementation report's claim of "16 passing tests" is unreachable on the committed tree.

The same root cause re-surfaces inside `fixtures.py`, `harness.py`, and `test_decision_explainability_data_contract.py` as trailing dedented annotated-expression lines after the final function body. Even where the package initializer's import-time error is patched, those three lines violate the standing forbidden-token rule (no standalone harness framing-token marker line in any authored body) and would be caught by an authored forbidden-token scan if collection ever reached the test module.

The leaked lines do not modify the substantive content of any authored module: the `__init__.py` docstring, the `fixtures.py` four-scenario × three-step deterministic fixture builders and the typed `DecisionExplainabilityFixtureInput` carrier, the `harness.py` pure-function projection driving `build_paper_mode_runtime` once at harness level, and the `test_decision_explainability_data_contract.py` 16 required pytest functions per `04_TEST_PLAN.md` § "Required test cases" all conform byte-for-byte to the planning artifacts (01–05) and to `06_IMPLEMENTATION_REPORT.md` § "Test Mapping". The cleanup is therefore a strict one-line strip per authored Python file with no other byte-content change.

## Classification

Lane C `codex_watchdog` autorecovery for an L1 non-live test-only Python source-byte leakage that breaks pytest collection of a Lane B test-only package. No new lineage IDs, no new typed surfaces, no new V2 `app/` adapter / domain / service / API / scheduler / FastAPI surface, no Redis access, no `/home/wali/Desktop/AI BOT` mutation, no exchange action, no live-readiness gate flip, no Binance read-only account-history endpoint invocation, no secret read or print, no master planner prompt mutation. Cleanup scope is the four authored `.py` files plus this planner-turn note plus the new recovery task JSON plus the recovery report and GO/NO-GO marker; the parallel-readonly-review report and GO/NO-GO at `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/parallel_capacity_readonly_review_phase2r_decision_explainability_data_contract_implementation_ready_*.md` and the parallel-readonly-review supervisor task JSON at `claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_phase2r_decision_explainability_data_contract_implementation_ready.json` are evidence-of-trigger artifacts and remain byte-frozen by the recovery scope (the supervisor's standing `worktree_excluded_paths` already covers the parallel-capacity readonly review task JSONs).

## Decision

Author and queue Codex recovery task `codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup` in this same planner turn. Recovery scope:

- Strip exactly one trailing standalone line that exactly matches the regex `^END_FILE: v2/backend/tests/unit/decision_explainability_data_contract/.+$` from each of the four authored Python files. Preserve every other byte. For `__init__.py`, the resulting body must be exactly the single line of docstring `"""Phase 2R decision explainability data contract harness tests."""` followed by a single trailing newline.
- Validate that the test package now collects: `python -m pytest v2/backend/tests/unit/decision_explainability_data_contract/ --collect-only -q` returns a non-zero collected count and exit 0. Then run the implementation-report-claimed validation `python -m pytest v2/backend/tests/unit/decision_explainability_data_contract/test_decision_explainability_data_contract.py -v --no-header` and confirm 16 passing tests, matching `06_IMPLEMENTATION_REPORT.md` § "Test Mapping" exactly.
- Add a forbidden-token grep that flags any `^(END_FILE|BEGIN_FILE):` line in the four authored Python files; the command must exit 1 (no matches) post-cleanup. The grep is invoked as a validation command on every recovery-task run; future watchdog turns may promote it into the standing supervisor-side preflight if the leakage recurs.
- Run a high-confidence secret scan over the four cleaned `.py` files plus the planner-turn note plus the recovery task JSON plus the recovery report and GO/NO-GO marker; the scan must exit 1 (no matches). The scan rubric matches the prior reconciliation recovery's standing rubric.
- Run `git status --porcelain` and confirm only the four cleaned `.py` files plus this planner-turn note plus the recovery task JSON plus the recovery report and the GO/NO-GO marker (and the standing worktree-excluded paths) are dirty.
- Stage and commit the four cleaned `.py` files plus this planner-turn note plus the recovery task JSON in a single commit with the message `Codex watchdog recover Phase 2R Python source END_FILE marker leakage breaking pytest collection`, push, then author the recovery report and GO/NO-GO marker and commit / push them in a second commit with the message `Codex watchdog author Phase 2R Python source END_FILE leakage cleanup recovery report and GO/NO-GO`.
- Do NOT modify the parallel-capacity readonly review report or GO/NO-GO file (they are evidence of trigger; the supervisor reconciles them by writing the formal Codex review GO/NO-GO PASS at `09_CODEX_GO_NO_GO.md` after task 174 dispatches and passes).
- Do NOT modify the Phase 2R packet's six markdown files (`01_LEGACY_FAILURE_EVIDENCE.md`, `02_TYPED_INPUT_FIXTURE_SPEC.md`, `03_HARNESS_PIPELINE_SPEC.md`, `04_TEST_PLAN.md`, `05_GO_NO_GO_REQUEST.md`, `PLANNER_TURN_2R_OPEN_IMPLEMENTATION.md`), the implementation report (`06_IMPLEMENTATION_REPORT.md`), the implementation GO/NO-GO marker (`07_GO_NO_GO.md`), the prior reconciliation / residual-leakage planner-turn notes (`PLANNER_TURN_2R_RECONCILIATION_173_RECOVERY.md`, `PLANNER_TURN_2R_RESIDUAL_LEAKAGE_AND_173_DISPATCH_HOLD_RECOVERY.md`), the open-Codex-review planner-turn note (`PLANNER_TURN_2R_OPEN_CODEX_REVIEW.md`), the supervisor task 173 JSON, the supervisor task 174 JSON, the prior `codex_recover_173_phase2r_*` task JSONs, the prior `codex_recover_173_phase2r_*` recovery reports, or the master planner prompt.

The four `.py` files live under `v2/backend/tests/unit/decision_explainability_data_contract/`. The recovery task therefore widens the prior `codex_recover_173_phase2r_reconciliation_residual_end_file_marker_leakage_cleanup` allowed-output-prefix set (which excluded all of `v2/`) to allow exactly the four file paths as authored test-package outputs. All other `v2/` paths remain forbidden — the recovery touches only the four leaked files inside the named test package directory and the recovery's own report and GO/NO-GO marker under `claude_worklog/phase2_core_rebuild/automation_reliability/`. The widening is the smallest change consistent with REQ_0007 / REQ_0014 / REQ_0016 (Codex autofix authority for non-live blockers) and REQ_0010 (safe path remap autorecovery for an emitted-path layout that happens to leak inside the canonical authored test package path itself).

## Recovery success markers

- PASS body line one at `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup_GO_NO_GO.md`: `CODEX_NON_LIVE_RECOVERY_READY`.
- FAIL body line one at the same file (with explicit blocker description in the recovery report): `CODEX_NON_LIVE_RECOVERY_BLOCKED`.
- Recovery report final non-blank body line at `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_173_phase2r_decision_explainability_data_contract_python_source_end_file_marker_leakage_cleanup_REPORT.md`: `CODEX_RECOVER_173_PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_PYTHON_SOURCE_END_FILE_MARKER_LEAKAGE_CLEANUP_REPORT_READY`.

## Next steps after recovery PASS

On `CODEX_NON_LIVE_RECOVERY_READY`, the supervisor:

1. Reclassifies the parallel-readonly-review supervisor task `parallel_capacity_readonly_review_phase2r_decision_explainability_data_contract_implementation_ready` as `superseded_by_evidence` per REQ_0014 / REQ_0015 / REQ_0016 (the BLOCKED finding is now resolved by the source-byte cleanup; the parallel-readonly-review GO/NO-GO file remains a frozen evidence-of-trigger artifact and the supervisor does not rewrite its body).
2. Dispatches supervisor task `174_phase2r_decision_explainability_data_contract_codex_review` against the now-clean worktree. The task carries `requires_clean_worktree=true` with `worktree_excluded_paths` covering the master planner prompt and the parallel-capacity readonly review task JSONs.
3. On Codex PASS at `09_CODEX_GO_NO_GO.md` with body line one `PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_CODEX_PASS`, the planner opens the next post-consolidation Lane B `explainability_ui` milestone per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` — either the per-row paper-execution-ledger explainability envelope projection harness consuming the existing typed `PaperExecutionLedgerEntry` mirror rows surfaced by the existing `PaperExecutionLedgerRecorder` composition root, or the per-row replay-backtest-runner explainability envelope projection harness consuming the existing typed `ReplayBacktestRunner` mirror rows, or the 30-day Binance read-only account-history pull (REQ_0024) wiring as a separate non-live milestone (the `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` posture remains in effect until secret-handling and 30-day-Binance-pull preconditions are independently approved). Live trading remains blocked.
4. On Codex FAIL with concrete documentation blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the Phase 2R packet only.
5. On Codex FAIL that is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H.A / 2H.B / 2H.C / 2I.A / 2I.B / 2I.C / 2J.C / 2L / 2M / 2N / 2O / 2P / 2Q reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/decision_explainability_data_contract/` and rewrites `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent.

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
- No prior-milestone Phase 2 artifact byte content modified.
- No Phase 2R planning artifact (01–05), implementation report (06), implementation GO/NO-GO marker (07), open-Codex-review planner-turn note, prior reconciliation / residual-leakage planner-turn notes, parallel-readonly-review report, parallel-readonly-review GO/NO-GO, supervisor task 173 JSON, supervisor task 174 JSON, prior `codex_recover_173_phase2r_*` task JSONs, prior `codex_recover_173_phase2r_*` recovery reports, or master planner prompt modified by the recovery.

PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_PLANNER_TURN_PYTHON_SOURCE_END_FILE_LEAKAGE_RECOVERY_READY
