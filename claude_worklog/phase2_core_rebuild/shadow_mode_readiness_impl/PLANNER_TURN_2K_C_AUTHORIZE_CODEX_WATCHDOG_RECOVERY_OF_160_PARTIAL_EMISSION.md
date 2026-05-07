# Planner Turn — Phase 2K.C Shadow-Mode-Readiness Flag Composition Root — Authorize Codex Watchdog Recovery of Task 160 Partial Emission

## Active milestone

REQ_0017 milestone 7 / REQ_0020 sequence step 7: `SHADOW_MODE_READINESS`, sub-phase 2K.C (Shadow-Mode-Readiness Flag Composition Root).

Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` after 2K.C closes: 0 milestones (the consolidation evidence packet under `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/` is the closing artifact, not a new milestone).

## Predecessor markers (verified present)

- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/07_2K_A_..._GO_NO_GO.md` carries `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/09_2K_A_..._CODEX_GO_NO_GO.md` carries `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/15_2K_B_..._GO_NO_GO.md` carries `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/17_2K_B_..._CODEX_GO_NO_GO.md` carries `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_..._CODEX_GO_NO_GO.md` carries `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `21_PHASE_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md` is on disk and ends with `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY`.

## Observed runtime state at this planner turn

`git status --porcelain` returns:

```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
?? v2/backend/app/composition/shadow_mode_readiness/
?? v2/backend/tests/unit/composition/shadow_mode_readiness/
```

Per the standing supervisor worktree-isolation contract (item 1 of `21`), the planner-prompt dirty entry is excluded from the dispatch worktree. The two untracked directories are the partial output of task `160_shadow_mode_readiness_2kc_flag_composition_root_implementation`:

- `v2/backend/app/composition/shadow_mode_readiness/__init__.py`
- `v2/backend/app/composition/shadow_mode_readiness/errors.py`
- `v2/backend/app/composition/shadow_mode_readiness/runtime.py`
- `v2/backend/tests/unit/composition/shadow_mode_readiness/__init__.py`

This is incomplete against the `21` rubric: rubric item 5 requires `.venv/bin/python -m pytest v2/backend/tests/unit/composition/shadow_mode_readiness/ -q` to report `22 passed`; only the test-package `__init__.py` is present, so pytest would discover zero tests. Rubric item 3 requires 23 files (22 test files plus the empty `__init__.py`) at the test-plan paths in `19`. The 22 test files are missing.

The 160 task has therefore landed source-side artifacts but has not satisfied the test-side rubric. The implementation report `22_2K_C_..._IMPLEMENTATION_REPORT.md` and the GO/NO-GO marker `23_2K_C_..._GO_NO_GO.md` are not yet on disk.

## Standing recovery task already enqueued

`claude_worklog/agent_supervisor/tasks/codex_recover_160_shadow_mode_readiness_2kc_flag_composition_root_implementation.json` is `pending`, lane `codex_watchdog`, risk `L1`, with `mvp_relevance` set to recover the non-live blocker on the paper/backtest MVP path and `next_gate` `CODEX_NON_LIVE_RECOVERY_READY`. Its `allowed_output_prefixes` cover the recovery surface (`v2/`, `claude_worklog/phase2_core_rebuild/`, `claude_worklog/agent_supervisor/`, `claude_worklog/tools/`, `claude_worklog/security/`, `claude_worklog/agent_supervisor_reliability/`) and its `required_output_files` are the recovery report and GO/NO-GO under `claude_worklog/phase2_core_rebuild/automation_reliability/`.

No new planner task JSON is required. The supervisor's existing dispatch path for the codex_watchdog lane is sufficient.

## Authorization for this turn

Per REQ_0007, REQ_0011, REQ_0014, REQ_0015, REQ_0016, REQ_0018, REQ_0021:

1. The supervisor / watchdog SHOULD dispatch `codex_recover_160_shadow_mode_readiness_2kc_flag_composition_root_implementation` next, treating the standing planner-prompt dirty line and the durable Lane C parallel-capacity readonly-review markers under `claude_worklog/agent_supervisor/tasks/` as the supervisor's worktree-isolation exclusions per `21` item 1.
2. The recovery task MAY:
   - inspect the three source files already on disk and the empty test-package `__init__.py`;
   - emit the 22 missing test files at the exact paths enumerated in `19_PHASE_2K_C_..._TEST_PLAN.md` under the one-test-function-per-file inline-fake rule;
   - run `.venv/bin/python -m py_compile` on the three source files and `.venv/bin/python -m pytest v2/backend/tests/unit/composition/shadow_mode_readiness/ -q`;
   - run the `21` cross-isolation diff and forbidden-token scan;
   - emit `22_2K_C_..._IMPLEMENTATION_REPORT.md` and `23_2K_C_..._GO_NO_GO.md` only if all `21` rubric items hold; otherwise leave the marker FAILED with concrete blockers and emit the recovery report and GO/NO-GO under `claude_worklog/phase2_core_rebuild/automation_reliability/` with `CODEX_NON_LIVE_RECOVERY_BLOCKED`.
3. The recovery task MUST NOT:
   - modify any 2K.A or 2K.B file (`v2/backend/app/{domain,services}/shadow_mode_readiness/`);
   - modify any 2J.A / 2J.B / 2J.C / 2I.A / 2I.B / 2I.C / 2H.A / 2H.B / 2H.C / 2G.A / 2G.B / 2G.C / 2F.A / 2F.B / 2F.C / 2E1 / 2E2 / 2E3 file;
   - modify the `v2/backend/app/services/replay_runner.py` and `v2/backend/app/services/paper_loop.py` placeholders;
   - populate `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/` beyond their 015A docstring-only state;
   - reintroduce a flat-file placeholder at `v2/backend/app/composition/shadow_mode_readiness.py`;
   - introduce any of the forbidden tokens listed in spec `18` (e.g., `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, `deny_default`, `mirror_deny_default`, `PaperExecutionLedgerEntry`, `ReplayBacktestStep`, `ReplayBacktestSummary`, `ReplayBacktestRun`, `PaperModeFlag`, `ShadowModeReadinessFlag(`, `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, `live_enabled`, `enable_live`, `shadow_decision_id`, harness framing tokens).
4. After the recovery task closes:
   - if `23_2K_C_..._GO_NO_GO.md` carries `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`, the supervisor SHOULD dispatch the already-enqueued `161_shadow_mode_readiness_2kc_flag_composition_root_codex_review.json`;
   - if `25_2K_C_..._CODEX_GO_NO_GO.md` then carries `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`, the planner WILL open the `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation turn under `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/` (NEW directory) summarizing the seven satisfied REQ_0017 milestones and the typed surfaces they produced;
   - if `25_2K_C_..._CODEX_GO_NO_GO.md` carries the FAIL marker, the supervisor SHOULD enqueue a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 22 new test files only, then re-run Codex review.

## Lane / MVP relevance

- Lane: `paper_backtest_mvp` for the underlying 2K.C milestone; Lane: `codex_watchdog` for the recovery task itself.
- MVP relevance: 2K.C closure satisfies REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`) and produces the slotted `ShadowModeReadinessRuntime` composition surface that the `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation packet enumerates.
- `blocked_by`: `160_shadow_mode_readiness_2kc_flag_composition_root_implementation` (partial) and the standing planner-prompt dirty entry (standing exclusion).
- `next_gate`: `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`, then `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`, then `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `legacy_evidence_consulted`: predecessor markers 07/09/15/17 of 2K.A/2K.B and 25 of 2J.C; 2K.C spec/test-plan/safety-boundary docs `18`/`19`/`20`/`21`; the partial output of task 160; the `21` GO/NO-GO request rubric.
- `legacy_failure_addressed`: incomplete 2K.C composition-root emission (3 of 25 spec'd files on disk; 22 test files missing) preventing the paper/backtest MVP closure path from advancing.

## Hard stops reaffirmed

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write or delete Redis keys.
- Do not restart live trainer / trader / orchestrator / Redis / VPN.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy.
- Do not run production migrations.
- Do not expose or commit secrets.
- Final live approval remains human-only.

## Planner directive

No new task JSON is emitted this turn. The watchdog/supervisor is authorized to dispatch the standing `codex_recover_160_shadow_mode_readiness_2kc_flag_composition_root_implementation` task next, then `161_shadow_mode_readiness_2kc_flag_composition_root_codex_review`, then open the `V2_BACKTEST_AND_PAPER_MVP_READY` consolidation turn.

PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_PLANNER_TURN_AUTHORIZE_CODEX_WATCHDOG_RECOVERY_OF_160_PARTIAL_EMISSION_READY
