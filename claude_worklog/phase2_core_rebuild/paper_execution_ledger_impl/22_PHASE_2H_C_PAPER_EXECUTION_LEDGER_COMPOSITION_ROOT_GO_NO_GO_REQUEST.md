# Phase 2H.C — Paper Execution Ledger Composition Root GO/NO-GO Request

This document is the consolidated GO/NO-GO request that the supervisor uses to gate dispatch of the 2H.C composition-root implementation task and the subsequent 2H.C composition-root Codex review task. It also enumerates the Codex review rubric used by the review task.

## Predecessor markers (must all be present)

- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md` contains exactly `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/18_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` contains exactly `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS`.
- `v2/backend/app/services/paper_execution_ledger/__init__.py`, `errors.py`, and `service.py` exist and pass their domain/service/composition-import-clean test suites.
- `v2/backend/app/services/paper_loop.py` placeholder still exists at exactly one tracked path and has zero modification (`git ls-files v2/backend/app/services/paper_loop.py` returns exactly one line; `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` returns zero lines).
- `v2/backend/app/composition/paper_execution_ledger.py` flat-file placeholder does NOT exist (`git ls-files v2/backend/app/composition/paper_execution_ledger.py` returns zero lines).
- `v2/backend/app/domain/execution/` is unpopulated (`git ls-files v2/backend/app/domain/execution/` returns zero lines).

If any precondition is missing or different, the supervisor MUST NOT dispatch the 2H.C composition-root implementation task.

## Implementation task GO/NO-GO checks

The 2H.C implementation PASSes only if all of the following hold:

1. Worktree is clean at dispatch (`git status --porcelain` returns zero lines, with the supervisor's worktree-isolation contract excluding the planner-prompt dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` and any durable Lane C parallel-capacity readonly-review marker files under `claude_worklog/agent_supervisor/tasks/` from the dispatch worktree).
2. The three authored source files exist exactly at the spec'd paths and contain exactly the public surface and import set documented in `19`.
3. The 25 test files exist exactly at the test-plan paths in `20` and follow the one-test-function-per-file inline-fake rule.
4. `.venv/bin/python -m py_compile` of the three source files exits 0.
5. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/paper_execution_ledger/ -q` reports `25 passed` and exits 0.
6. The 2H.B service suite, the 2H.A domain suite, the 2G.C composition suite, the 2G.B service suite, the 2G.A domain suite, the 2F.C composition suite, the 2F.B service suite, the 2F.A domain suite, and every 2E1/2E2/2E3 suite enumerated in `20` 'Test runner expectations' pass with zero regressions when run individually.
7. The forbidden-token scan returns zero matches per token across the three authored source files (including `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, and the literal lowercase `deny_default`).
8. The cross-isolation diff (`git status -s` over the safety-boundary path set in `21`) returns zero lines outside the additive 2H.C scope.
9. The implementation report (`23`) cites function/line-range evidence for each of the four behavior-contract steps in `19` and reports each safety-boundary item as `none observed` or `observed: <evidence>`, including explicit rows for the OrchestratorDecisionRecord forbidden-emission, the live_blocked == False forbidden-construction, the flat-file placeholder forbidden-introduction, the paper_loop.py forbidden-modification, the v2/backend/app/domain/execution/ forbidden-population, the ledger-persistence forbidden-introduction, and the PnL / position sizing / quantity / price / fees / slippage forbidden-introduction.
10. No FastAPI lifespan, dependency, router, module-level singleton, cache, lock, wall-clock helper, `os.environ`, `subprocess` (outside test files), `socket`, secret-shaped string, URL string, or background task is present in the three authored source files.
11. `git ls-files v2/backend/app/composition/paper_execution_ledger.py` returns zero lines (no flat-file placeholder reintroduced).
12. `git ls-files v2/backend/app/services/paper_loop.py` returns exactly one line and `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` returns zero lines (placeholder untouched).
13. `git ls-files v2/backend/app/domain/execution/` returns zero lines (directory unpopulated).

If the implementation PASSes, the implementation report ends with `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPLEMENTATION_REPORT_READY` and the GO/NO-GO file (`24`) contains exactly `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`. If the implementation FAILs with concrete blockers and no safety violation, the GO/NO-GO file contains exactly `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_FAILED` and the supervisor enqueues a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 25 new test files only.

## Codex review task rubric

The 2H.C Codex review PASSes only if all of the following review items hold:

1. `__init__.py` re-exports exactly `(build_paper_execution_ledger_recorder, PaperExecutionLedgerRecorder, PaperExecutionLedgerCompositionError)` and `__all__` is exactly that 3-tuple in that order.
2. `errors.py` defines `PaperExecutionLedgerCompositionError(Exception)` with `__init__(self, code: str, *, field: str) -> None` and a `__repr__` consistent with spec `19`, importing only `from __future__ import annotations`.
3. `PaperExecutionLedgerCompositionError` is NOT a subclass of `ValueError` (kept distinct from the 2H.B service error and the 2H.A domain error to allow callers to discriminate build-time misconfiguration from call-time service-layer rejection and from value-object rejection).
4. `runtime.py` defines `PaperExecutionLedgerRecorder` type alias as `Callable[..., PaperExecutionLedgerEntry]`.
5. `runtime.py` defines `build_paper_execution_ledger_recorder` with the keyword-only signature declared in spec `19`; the parameter set is exactly `{now_ms_clock}`; the function returns `PaperExecutionLedgerRecorder`.
6. `runtime.py` imports are exactly the six entries listed in spec `19` 'Imports allowed in runtime.py'. No third-party import. No `typing` import. No factory import. No `url`+`_env` import. No literal `red`+`is` import. No `fast`+`api` import. No `asyncio` import. No `threading` import. No `multiprocessing` import. No `subprocess` import. No `socket` import. No `selectors` import. No `pathlib` import. No `logging` import. No `datetime` import. No `time` import. No `os` import. No `math` import. No `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, `orchestrator_decision`, or `risk_gateway` composition or service import. No import of `v2.backend.app.domain.orchestrator_decision`. The only stdlib imports beyond `__future__` are `from collections.abc import Callable`.
7. `runtime.py` contains zero occurrences of every literal in spec `19` 'Forbidden tokens in source files'. Verified via `rg --fixed-strings --case-sensitive` for each token. NO exemption applies.
8. The same forbidden-token set is absent from `__init__.py` and `errors.py`.
9. `runtime.py` implements the four behavior steps in this exact order: callable check on `now_ms_clock`, bind closure variable, define inner `_recorder` with `decision` keyword-only parameter, return `_recorder`. The inner `_recorder` body is exactly a single `return assemble_paper_execution_ledger_entry(decision=decision, now_ms_clock=_now_ms_clock)` statement with the closure variable forwarded.
10. `runtime.py` does NOT call `now_ms_clock` at build time. `runtime.py` does NOT call `assemble_paper_execution_ledger_entry` at build time. `runtime.py` does NOT cache any value derived from the clock beyond binding the closure variable at build time.
11. `runtime.py` does NOT catch, wrap, or rewrap `PaperExecutionLedgerServiceError` raised from `assemble_paper_execution_ledger_entry`. `runtime.py` does NOT catch, wrap, or rewrap `PaperExecutionLedgerDomainError` raised from `PaperExecutionLedgerEntry.__post_init__`. Service and domain errors propagate unchanged.
12. `runtime.py` does NOT mutate any caller-supplied input. The `decision` parameter is passed through unchanged.
13. `runtime.py` does NOT directly construct any `PaperExecutionLedgerEntry`; entry construction is delegated entirely to the 2H.B service.
14. Every test file under `v2/backend/tests/unit/composition/paper_execution_ledger/` contains exactly one test function whose name starts with `test_` and uses inline hand-written fakes; no shared `conftest` is created or modified.
15. `test_composition_milestone_forbidden_tokens.py` constructs every forbidden literal at runtime via string concatenation, scans the three authored source files, and applies NO exemption (covers `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, and the lowercase `deny_default`).
16. `test_init_module_does_not_load_redis.py`, `test_init_module_does_not_load_url_env.py`, `test_init_module_does_not_register_fastapi_lifespan.py`, and `test_runtime_module_does_not_load_redis_when_imported.py` each launch a child interpreter via `subprocess.run([sys.executable, '-c', ...])` (allowed in test files only) to ensure a clean module table after re-import.
17. `test_public_surface.py` asserts the exact `(name, ordering)` of `__all__` and asserts `PaperExecutionLedgerCompositionError` is NOT a subclass of `ValueError`.
18. `test_validates_now_ms_clock_callable.py` asserts non-callable input raises `PaperExecutionLedgerCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`, covering at least integer, `None`, and string inputs.
19. `test_returns_callable_recorder.py` asserts the returned recorder is callable and is not the input clock (binder returns a NEW callable).
20. `test_assembler_not_invoked_at_build_time.py` asserts the clock counter is zero immediately after `build_paper_execution_ledger_recorder` returns.
21. `test_recorder_invokes_assembler_exactly_once_per_call.py` asserts the clock counter increments by exactly 1 per recorder call.
22. `test_recorder_returns_paper_execution_ledger_entry.py` asserts `isinstance` check against the 2H.A domain `PaperExecutionLedgerEntry` type.
23. `test_recorder_records_clock_into_ledger_entry_ts_ms.py` asserts the returned entry's `ledger_entry_ts_ms` equals the clock return value.
24. `test_recorder_propagates_allow_proceed_long_to_mirror_allow_proceed_long.py` asserts the `allow_proceed_long` mirror flows through the binder.
25. `test_recorder_propagates_allow_proceed_short_to_mirror_allow_proceed_short.py` asserts the `allow_proceed_short` mirror flows through the binder.
26. `test_recorder_propagates_deny_orchestrator_held_to_mirror_deny_orchestrator_held.py` asserts the `deny_orchestrator_held` mirror flows through the binder.
27. `test_recorder_propagates_deny_orchestrator_abstained_to_mirror_deny_orchestrator_abstained.py` asserts the `deny_orchestrator_abstained` mirror flows through the binder.
28. `test_recorder_propagates_deny_default_to_mirror_deny_default.py` asserts the `deny_default` mirror flows through the binder using runtime-reconstructed literals so the test source file does not contain the bare `deny_default` token.
29. `test_recorder_keyword_only_params.py` asserts positional-arg calling raises `TypeError`.
30. `test_recorder_propagates_service_error_for_non_int_clock.py` asserts a clock returning float raises `PaperExecutionLedgerServiceError` with `code == "must_be_int"` and `field == "now_ms_clock"`.
31. `test_recorder_propagates_service_error_for_negative_clock.py` asserts a clock returning negative int raises `PaperExecutionLedgerServiceError` with `code == "must_be_nonnegative"` and `field == "now_ms_clock"`.
32. `test_recorder_propagates_service_error_for_non_record_decision.py` asserts non-record `decision` raises `PaperExecutionLedgerServiceError` with `code == "must_be_risk_decision_record"` and `field == "decision"`.
33. `test_recorder_propagates_service_error_for_long_risk_decision_id.py` asserts a 126-character `risk_decision_id` raises `PaperExecutionLedgerServiceError` with `code == "risk_decision_id_too_long_for_paper_trade_id_derivation"` and `field == "decision.risk_decision_id"`.
34. `test_recorder_does_not_mutate_supplied_inputs.py` asserts the original `RiskDecisionRecord` field values remain byte-identical after the call.
35. `test_errors_invariants.py` asserts `code`, `field`, `__str__`, and that omitting `field` raises `TypeError`.
36. `test_composition_does_not_import_url_env_directly.py` asserts neither `runtime.py` nor `__init__.py` source contains the literal `"url" + "_env"` reconstructed at runtime.
37. The 25 composition test files in `v2/backend/tests/unit/composition/paper_execution_ledger/` pass with zero failures and zero errors.
38. The existing 2H.B service suite (`v2/backend/tests/unit/services/paper_execution_ledger/`), 2H.A domain suite (`v2/backend/tests/unit/domain/paper_execution_ledger/`), 2G.C composition suite (`v2/backend/tests/unit/composition/risk_gateway/`), 2G.B service suite (`v2/backend/tests/unit/services/risk_gateway/`), 2G.A domain suite (`v2/backend/tests/unit/domain/risk_gateway/`), 2F.C composition suite (`v2/backend/tests/unit/composition/orchestrator_decision/`), 2F.B service suite (`v2/backend/tests/unit/services/orchestrator_decision/`), 2F.A domain suite (`v2/backend/tests/unit/domain/orchestrator_decision/`), 2E3.C composition suite (`v2/backend/tests/unit/composition/trainer_prediction_output/`), 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), 2E2.C composition suite (`v2/backend/tests/unit/composition/trainer_worker_health/`), 2E2.B service suite (`v2/backend/tests/unit/services/trainer_worker_health/`), 2E2.A domain suite (`v2/backend/tests/unit/domain/trainer_worker_health/`), 2E1.E composition suite (`v2/backend/tests/unit/composition/trainer_parity/`), 2E1.D service suite (`v2/backend/tests/unit/services/trainer_parity/`), and 2E1 trainer_liveness domain suite (`v2/backend/tests/unit/domain/trainer_liveness/`) all pass with zero failures and zero errors.
39. `py_compile` passes for the three authored source files.
40. `git status -s` over the cross-isolation paths in `21` returns zero lines.
41. No FastAPI startup hook, lifespan handler, dependency, router registration, module-level singleton, module-level cache, module-level lock, or background task anywhere in the three authored source files.
42. No write to any cross-isolation path in `21`.
43. No secret-shaped string in the diff (per the canonical secret list).
44. No `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, `orchestrator_decision`, or `risk_gateway` service or composition import in any of the three authored source files. No import of `v2.backend.app.domain.orchestrator_decision`.
45. No REQ_0017 scope-cap violation: no execution-side surface beyond the ledger boundary, no paper executor, no shadow executor, no replay runner, no model-loading, no GPU, no checkpoint subsystem expansion; no FastAPI surface; no adapter expansion; no expansion of the binder beyond the one build-time `now_ms_clock` parameter and the one call-time `decision` parameter; no new lineage ID at the composition layer beyond the `paper_trade_id` already derived inside the 2H.B service; no ledger persistence; no PnL/position-sizing/quantity/price/fees/slippage/risk-adjusted-return computation.
46. No `decision` mutation at runtime; the parameter is forwarded by reference unchanged.
47. No import or emission of `OrchestratorDecisionRecord`, `RISK_DECISION_REASON_DENY_DEFAULT`, or the literal lowercase `deny_default` in any authored 2H.C source file.
48. `git ls-files v2/backend/app/composition/paper_execution_ledger.py` returns zero output lines (no flat-file placeholder introduced).
49. `git ls-files v2/backend/app/services/paper_loop.py` returns exactly one output line and `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` returns zero output lines (placeholder untouched).
50. `git ls-files v2/backend/app/domain/execution/` returns zero output lines (directory remains unpopulated).
51. No successful construction of a `PaperExecutionLedgerEntry` with `live_blocked == False` is observed in the test corpus or the source files (the 2H.B service hard-codes `live_blocked=True`; 2H.C only forwards).
52. No direct construction of `PaperExecutionLedgerEntry` in any authored 2H.C source file (entry construction is the responsibility of the 2H.B assembler service alone).

If all 52 rows PASS, the Codex review report (`25`) ends with `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_REVIEW_READY` and the Codex GO/NO-GO file (`26`) contains exactly `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`. On any FAIL with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2H.C source files plus the 25 new test files only. On any safety violation, surface to human attention; no autofix is permitted.

## Phase exit (closing Phase 2H → opening REQ_0017 milestone 5)

Phase 2H closes when the 2H.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 4 (`PAPER_EXECUTION_LEDGER_MVP`) is satisfied and the planner opens REQ_0017 milestone 5 (`REPLAY_BACKTEST_RUNNER_MVP`) under a fresh consolidated milestone turn. No execution-side behavior beyond the existing ledger boundary, no paper executor, and no strategy library is opened in 2H.C.

PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY
