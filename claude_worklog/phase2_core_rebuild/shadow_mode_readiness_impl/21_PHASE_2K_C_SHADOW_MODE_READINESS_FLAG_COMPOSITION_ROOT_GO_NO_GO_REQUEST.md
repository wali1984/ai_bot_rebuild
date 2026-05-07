# Phase 2K.C — Shadow-Mode-Readiness Flag Composition Root GO/NO-GO Request

This document is the consolidated GO/NO-GO request that the supervisor uses to gate dispatch of the 2K.C composition-root implementation task and the subsequent 2K.C composition-root Codex review task. It also enumerates the Codex review rubric used by the review task.

## Predecessor markers (must all be present)

- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/15_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_GO_NO_GO.md` contains exactly `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/17_2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` contains exactly `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/07_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_GO_NO_GO.md` contains exactly `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/09_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_GO_NO_GO.md` contains exactly `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` contains exactly `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `v2/backend/app/services/shadow_mode_readiness/__init__.py`, `errors.py`, and `service.py` exist and pass their service test suite.
- `v2/backend/app/domain/shadow_mode_readiness/__init__.py`, `errors.py`, and `flag.py` exist and pass their domain test suite.
- `v2/backend/app/services/replay_runner.py` placeholder still exists at exactly one tracked path and has zero modification (`git ls-files v2/backend/app/services/replay_runner.py` returns exactly one line; `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` returns zero lines).
- `v2/backend/app/services/paper_loop.py` placeholder still exists at exactly one tracked path and has zero modification.
- `v2/backend/app/composition/shadow_mode_readiness.py` flat-file placeholder does NOT exist (`git ls-files v2/backend/app/composition/shadow_mode_readiness.py` returns zero lines).
- `v2/backend/app/domain/replay/` is unchanged from its 015A docstring-only placeholder state (exactly two tracked files, zero diff vs HEAD).
- `v2/backend/app/domain/execution/` is unchanged from its 015A docstring-only placeholder state (exactly three tracked files, zero diff vs HEAD).

If any precondition is missing or different, the supervisor MUST NOT dispatch the 2K.C composition-root implementation task.

## Implementation task GO/NO-GO checks

The 2K.C implementation PASSes only if all of the following hold:

1. Worktree is clean at dispatch (`git status --porcelain` returns zero lines, with the supervisor's worktree-isolation contract excluding the planner-prompt dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` and any durable Lane C parallel-capacity readonly-review marker files under `claude_worklog/agent_supervisor/tasks/` from the dispatch worktree).
2. The three authored source files exist exactly at the spec'd paths and contain exactly the public surface and import set documented in `18`.
3. The 22 test files (plus the empty `__init__.py`, totaling 23 files in the test directory) exist exactly at the test-plan paths in `19` and follow the one-test-function-per-file inline-fake rule.
4. `.venv/bin/python -m py_compile` of the three source files exits 0.
5. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/shadow_mode_readiness/ -q` reports `22 passed` and exits 0.
6. The 2K.B service suite, the 2K.A domain suite, the 2J.C composition suite, the 2J.B service suite, the 2J.A domain suite, the 2I.C composition suite, the 2I.B service suite, the 2I.A domain suite, the 2H.C composition suite, the 2H.B service suite, the 2H.A domain suite, the 2G.C composition suite, the 2G.B service suite, the 2G.A domain suite, the 2F.C composition suite, the 2F.B service suite, the 2F.A domain suite, and every 2E1/2E2/2E3 suite enumerated in `19` 'Test runner expectations' pass with zero regressions when run individually.
7. The forbidden-token scan returns zero matches per token across the three authored source files (including `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, the lowercase `deny_default`, the literal `mirror_deny_default`, `PaperExecutionLedgerEntry`, `ReplayBacktestStep`, `ReplayBacktestSummary`, `ReplayBacktestRun`, `PaperModeFlag`, the call-form token `ShadowModeReadinessFlag(`, the bare tokens `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, `live_enabled`, `enable_live`, `shadow_decision_id`, and the harness framing tokens `BEGIN_FILE` / `END_FILE`).
8. The cross-isolation diff (`git status -s` over the safety-boundary path set in `20`) returns zero lines outside the additive 2K.C scope.
9. The implementation report (`22`) cites function/line-range evidence for each of the four behavior-contract steps in `18` and reports each safety-boundary item as `none observed` or `observed: <evidence>`, including explicit rows for the `RiskDecisionRecord` / `OrchestratorDecisionRecord` / `PaperModeFlag` forbidden-emission, the `ShadowModeReadinessFlag(` direct-construction forbidden-introduction, the flat-file placeholder forbidden-introduction, the `replay_runner.py` / `paper_loop.py` forbidden-modification, the `v2/backend/app/domain/replay/` / `v2/backend/app/domain/execution/` forbidden-population, the replay/ledger persistence forbidden-introduction, the PnL / position sizing / quantity / price / fees / slippage forbidden-introduction, the `live` / `live_enabled` / `enable_live` requested-state forbidden-introduction, and the `SHADOW_MODE_LIVE_ENABLED` / `SHADOW_MODE_LIVE` / `shadow_decision_id` constant forbidden-introduction.
10. No FastAPI lifespan, dependency, router, module-level singleton, cache, lock, wall-clock helper, `os.environ`, `subprocess` (outside test files), `socket`, secret-shaped string, URL string, or background task is present in the three authored source files.
11. `git ls-files v2/backend/app/composition/shadow_mode_readiness.py` returns zero lines (no flat-file placeholder reintroduced).
12. `git ls-files v2/backend/app/services/replay_runner.py` returns exactly one line and `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` returns zero lines (placeholder untouched).
13. `git ls-files v2/backend/app/services/paper_loop.py` returns exactly one line and `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` returns zero lines (placeholder untouched).
14. `git diff --stat HEAD -- v2/backend/app/domain/replay/` returns zero lines (015A placeholder untouched).
15. `git diff --stat HEAD -- v2/backend/app/domain/execution/` returns zero lines (015A placeholder untouched).
16. `git diff --stat HEAD -- v2/backend/app/domain/shadow_mode_readiness/` returns zero lines (2K.A surface untouched).
17. `git diff --stat HEAD -- v2/backend/app/services/shadow_mode_readiness/` returns zero lines (2K.B surface untouched).
18. `git diff --stat HEAD -- v2/backend/app/composition/paper_mode/` returns zero lines (2J.C surface untouched).
19. The slotted `ShadowModeReadinessRuntime` class exposes `__slots__ == ("shadow_mode_readiness_now",)` exactly; constructed instances reject foreign attribute attachment.

If the implementation PASSes, the implementation report ends with `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_IMPLEMENTATION_REPORT_READY` and the GO/NO-GO file (`23`) contains exactly `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`. If the implementation FAILs with concrete blockers and no safety violation, the GO/NO-GO file contains exactly `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_IMPL_AND_VALIDATION_FAILED` and the supervisor enqueues a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 22 new test files only.

## Codex review task rubric

The 2K.C Codex review PASSes only if all of the following review items hold:

1. `__init__.py` re-exports exactly `(build_shadow_mode_readiness_runtime, ShadowModeReadinessRuntime, ShadowModeReadinessRuntimeCompositionError)` and `__all__` is exactly that 3-tuple in that order.
2. `errors.py` defines `ShadowModeReadinessRuntimeCompositionError(Exception)` with `__init__(self, code: str, *, field: str) -> None` and a `__repr__` consistent with spec `18`, importing only `from __future__ import annotations`.
3. `ShadowModeReadinessRuntimeCompositionError` is NOT a subclass of `ValueError` (kept distinct from the 2K.B service error and the 2K.A domain error to allow callers to discriminate build-time misconfiguration from call-time service-layer rejection and from value-object rejection).
4. `runtime.py` defines `ShadowModeReadinessRuntime` with `__slots__ == ("shadow_mode_readiness_now",)` exactly and with `__init__(self, *, shadow_mode_readiness_now) -> None` per spec `18`. The class defines no other method, classmethod, staticmethod, or property. The class does not declare `__weakref__` in `__slots__`. Constructed instances reject foreign attribute attachment.
5. `runtime.py` defines `build_shadow_mode_readiness_runtime` with the keyword-only signature declared in spec `18`; the parameter set is exactly `{now_ms_clock}`; the function returns `ShadowModeReadinessRuntime`.
6. `runtime.py` imports are exactly the five entries listed in spec `18` 'Imports allowed in runtime.py'. No third-party import. No `typing` import. No factory import. No `url`+`_env` import. No literal `red`+`is` import. No `fast`+`api` import. No `asyncio` import. No `threading` import. No `multiprocessing` import. No `subprocess` import. No `socket` import. No `selectors` import. No `pathlib` import. No `logging` import. No `datetime` import. No `time` import. No `os` import. No `math` import. No `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, `orchestrator_decision`, `risk_gateway`, `paper_execution_ledger`, `replay_backtest_runner`, or `paper_mode` composition or service or domain import. The only stdlib imports beyond `__future__` are `from collections.abc import Callable`.
7. `runtime.py` does NOT contain any literal substring listed in spec `18` 'Forbidden tokens in source files'.
8. The behavior contract in `runtime.py` for `build_shadow_mode_readiness_runtime` matches the four-step ordering in spec `18` exactly. The clock callable check uses the builtin `callable(...)` test. The clock is NOT invoked at build time. The 2K.B service function is NOT invoked at build time.
9. The inner closure `_shadow_mode_readiness_now` declares `requested_state: str` keyword-only and returns `assemble_shadow_mode_readiness_flag(requested_state=requested_state, now_ms_clock=_now_ms_clock)` exactly.
10. The closure does not catch or wrap `ShadowModeReadinessServiceError` or `ShadowModeReadinessDomainError`.
11. The 22 test files at the spec'd paths each contain exactly one test function whose name starts with `test_`. No shared `conftest.py` is created or modified. Each test reconstructs forbidden literals at runtime via string concatenation.
12. The forbidden-token scan test reconstructs every literal listed in spec `18` 'Forbidden tokens in source files' and asserts zero matches in any of the three source files.
13. The import-clean tests use `subprocess.run([sys.executable, "-c", ...])` to launch fresh child interpreters, purge `sys.modules`, and re-import the package and the runtime module to verify no transitive load of literal `red`+`is`, `url`+`_env`, or `fast`+`api`.
14. The cross-isolation diff at the path set in `20` 'Cross-isolation paths' returns zero lines outside the additive 2K.C scope.
15. No 2K.A or 2K.B file is modified.
16. No 2J.A / 2J.B / 2J.C / 2I.A / 2I.B / 2I.C / 2H.A / 2H.B / 2H.C / 2G.A / 2G.B / 2G.C / 2F.A / 2F.B / 2F.C / 2E1 / 2E2 / 2E3 file is modified.
17. No legacy file under `/home/wali/Desktop/AI BOT` is modified.
18. No literal `red`+`is`, `aio`+`red`+`is`, `hi`+`red`+`is`, `httpx`, `requests`, `fast`+`api`, `uvicorn`, `starlette`, or `urllib` import or transitive load is present.
19. The slotted `ShadowModeReadinessRuntime` class exposes the captured-clock closure via the `shadow_mode_readiness_now` attribute. Both invocations of `runtime.shadow_mode_readiness_now(...)` observe the same captured-clock identity.
20. The implementation report (`22`) cites function/line-range evidence for each behavior-contract step and reports each safety-boundary item as `none observed` or `observed: <evidence>`.
21. The Codex reviewer does NOT introduce a `live` / `live_enabled` / `enable_live` state branch when re-reading the source; the only accepted requested states are `not_ready` and `ready`, both with `live_blocked == True`.
22. The Codex reviewer adjudicates the pre-existing `v2/backend/app/domain/replay/` and `v2/backend/app/domain/execution/` 015A docstring-only placeholders as out-of-scope per the 2J.A / 2J.B / 2J.C / 2H.C / 2I.C reconciliation precedent; row remains FAIL only at the placeholder cross-isolation gate when the rubric command is `git ls-files v2/backend/app/domain/replay/` or `git ls-files v2/backend/app/domain/execution/`, but that row is reconciled by addendum if the supervisor records `26_2K_C_..._CODEX_RECONCILIATION_ADDENDUM.md` per the 2H.C / 2I.C / 2J.C pattern.

If the Codex review PASSes, the marker file `25_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` contains exactly `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`. If the Codex review FAILs, the supervisor enqueues a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 22 test files only, then re-runs Codex review.

## Phase exit

Phase 2K closes when `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS` is materialized. At that point REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`) is satisfied. The planner then opens the consolidation turn that authors the `V2_BACKTEST_AND_PAPER_MVP_READY` evidence packet under `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/` (NEW directory) summarizing the seven satisfied REQ_0017 milestones and the typed surfaces they produced. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` after 2K.C closes: 0 milestones remaining (the consolidation turn is the closing artifact, not a new milestone).

PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY
