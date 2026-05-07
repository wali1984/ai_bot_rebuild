# Phase 2I.C — Replay/Backtest Runner Composition Root GO/NO-GO Request

This document is the consolidated GO/NO-GO request that the supervisor uses to gate dispatch of the 2I.C composition-root implementation task and the subsequent 2I.C composition-root Codex review task. It also enumerates the Codex review rubric used by the review task.

## Predecessor markers (must all be present)

- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/15_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_GO_NO_GO.md` contains exactly `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/17_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` contains exactly `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/07_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_GO_NO_GO.md` contains exactly `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/09_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_GO_NO_GO.md` contains exactly `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_CODEX_PASS`.
- `v2/backend/app/services/replay_backtest_runner/__init__.py`, `errors.py`, and `service.py` exist and pass their domain/service/composition-import-clean test suites.
- `v2/backend/app/services/replay_runner.py` placeholder still exists at exactly one tracked path and has zero modification (`git ls-files v2/backend/app/services/replay_runner.py` returns exactly one line; `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` returns zero lines).
- `v2/backend/app/services/paper_loop.py` placeholder still exists at exactly one tracked path and has zero modification.
- `v2/backend/app/composition/replay_backtest_runner.py` flat-file placeholder does NOT exist (`git ls-files v2/backend/app/composition/replay_backtest_runner.py` returns zero lines).
- `v2/backend/app/domain/execution/` is unpopulated (`git ls-files v2/backend/app/domain/execution/` returns zero lines).

If any precondition is missing or different, the supervisor MUST NOT dispatch the 2I.C composition-root implementation task.

## Implementation task GO/NO-GO checks

The 2I.C implementation PASSes only if all of the following hold:

1. Worktree is clean at dispatch (`git status --porcelain` returns zero lines, with the supervisor's worktree-isolation contract excluding the planner-prompt dirty entry at `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` and any durable Lane C parallel-capacity readonly-review marker files under `claude_worklog/agent_supervisor/tasks/` from the dispatch worktree).
2. The three authored source files exist exactly at the spec'd paths and contain exactly the public surface and import set documented in `18`.
3. The 35 test files exist exactly at the test-plan paths in `19` and follow the one-test-function-per-file inline-fake rule.
4. `.venv/bin/python -m py_compile` of the three source files exits 0.
5. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/replay_backtest_runner/ -q` reports `35 passed` and exits 0.
6. The 2I.B service suite, the 2I.A domain suite, the 2H.C composition suite, the 2H.B service suite, the 2H.A domain suite, the 2G.C composition suite, the 2G.B service suite, the 2G.A domain suite, the 2F.C composition suite, the 2F.B service suite, the 2F.A domain suite, and every 2E1/2E2/2E3 suite enumerated in `19` 'Test runner expectations' pass with zero regressions when run individually.
7. The forbidden-token scan returns zero matches per token across the three authored source files (including `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, the lowercase `deny_default`, the literal `mirror_deny_default`, and the four call-form tokens `ReplayBacktestStep(`, `ReplayBacktestSummary(`, `PaperExecutionLedgerEntry(`, `ReplayBacktestRun(`).
8. The cross-isolation diff (`git status -s` over the safety-boundary path set in `20`) returns zero lines outside the additive 2I.C scope.
9. The implementation report (`22`) cites function/line-range evidence for each of the five behavior-contract steps in `18` and reports each safety-boundary item as `none observed` or `observed: <evidence>`, including explicit rows for the `RiskDecisionRecord` / `OrchestratorDecisionRecord` forbidden-emission, the `live_blocked == False` forbidden-construction, the flat-file placeholder forbidden-introduction, the `replay_runner.py` / `paper_loop.py` forbidden-modification, the `v2/backend/app/domain/execution/` forbidden-population, the replay/ledger persistence forbidden-introduction, and the PnL / position sizing / quantity / price / fees / slippage forbidden-introduction.
10. No FastAPI lifespan, dependency, router, module-level singleton, cache, lock, wall-clock helper, `os.environ`, `subprocess` (outside test files), `socket`, secret-shaped string, URL string, or background task is present in the three authored source files.
11. `git ls-files v2/backend/app/composition/replay_backtest_runner.py` returns zero lines (no flat-file placeholder reintroduced).
12. `git ls-files v2/backend/app/services/replay_runner.py` returns exactly one line and `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` returns zero lines (placeholder untouched).
13. `git ls-files v2/backend/app/services/paper_loop.py` returns exactly one line and `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` returns zero lines (placeholder untouched).
14. `git ls-files v2/backend/app/domain/execution/` returns zero lines (directory unpopulated).
15. The slotted `ReplayBacktestRunner` class exposes `__slots__ == ("assemble_step", "assemble_summary")` exactly; constructed instances reject foreign attribute attachment.

If the implementation PASSes, the implementation report ends with `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_IMPLEMENTATION_REPORT_READY` and the GO/NO-GO file (`23`) contains exactly `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`. If the implementation FAILs with concrete blockers and no safety violation, the GO/NO-GO file contains exactly `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_FAILED` and the supervisor enqueues a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 35 new test files only.

## Codex review task rubric

The 2I.C Codex review PASSes only if all of the following review items hold:

1. `__init__.py` re-exports exactly `(build_replay_backtest_runner, ReplayBacktestRunner, ReplayBacktestRunnerCompositionError)` and `__all__` is exactly that 3-tuple in that order.
2. `errors.py` defines `ReplayBacktestRunnerCompositionError(Exception)` with `__init__(self, code: str, *, field: str) -> None` and a `__repr__` consistent with spec `18`, importing only `from __future__ import annotations`.
3. `ReplayBacktestRunnerCompositionError` is NOT a subclass of `ValueError` (kept distinct from the 2I.B service error and the 2I.A domain error to allow callers to discriminate build-time misconfiguration from call-time service-layer rejection and from value-object rejection).
4. `runtime.py` defines `ReplayBacktestRunner` with `__slots__ == ("assemble_step", "assemble_summary")` exactly and with `__init__(self, *, assemble_step, assemble_summary) -> None` per spec `18`. The class defines no other method, classmethod, staticmethod, or property. The class does not declare `__weakref__` in `__slots__`. Constructed instances reject foreign attribute attachment.
5. `runtime.py` defines `build_replay_backtest_runner` with the keyword-only signature declared in spec `18`; the parameter set is exactly `{now_ms_clock}`; the function returns `ReplayBacktestRunner`.
6. `runtime.py` imports are exactly the six entries listed in spec `18` 'Imports allowed in runtime.py'. No third-party import. No `typing` import. No factory import. No `url`+`_env` import. No literal `red`+`is` import. No `fast`+`api` import. No `asyncio` import. No `threading` import. No `multiprocessing` import. No `subprocess` import. No `socket` import. No `selectors` import. No `pathlib` import. No `logging` import. No `datetime` import. No `time` import. No `os` import. No `math` import. No `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, `orchestrator_decision`, `risk_gateway`, or `paper_execution_ledger` composition or service import. No import of `v2.backend.app.domain.orchestrator_decision` or `v2.backend.app.domain.risk_gateway`. The only stdlib imports beyond `__future__` are `from collections.abc import Callable`.
7. `runtime.py` contains zero occurrences of every literal in spec `18` 'Forbidden tokens in source files'. Verified via `rg --fixed-strings --case-sensitive` for each token. NO exemption applies.
8. The same forbidden-token set is absent from `__init__.py` and `errors.py`.
9. `runtime.py` implements the five behavior steps in this exact order: callable check on `now_ms_clock`, bind closure variable, define inner `_assemble_step` with `paper_ledger_entry` and `replay_run` keyword-only parameters, define inner `_assemble_summary` with `replay_run` and `steps` keyword-only parameters, return `ReplayBacktestRunner(assemble_step=_assemble_step, assemble_summary=_assemble_summary)`. The inner `_assemble_step` body is exactly a single `return assemble_replay_backtest_step(paper_ledger_entry=paper_ledger_entry, replay_run=replay_run, now_ms_clock=_now_ms_clock)` statement. The inner `_assemble_summary` body is exactly a single `return assemble_replay_backtest_summary(replay_run=replay_run, steps=steps, now_ms_clock=_now_ms_clock)` statement. Both closures forward the same `_now_ms_clock` closure variable.
10. `runtime.py` does NOT call `now_ms_clock` at build time. `runtime.py` does NOT call either assembler service function at build time. `runtime.py` does NOT cache any value derived from the clock beyond binding the closure variable at build time.
11. `runtime.py` does NOT catch, wrap, or rewrap `ReplayBacktestRunnerServiceError` raised from either assembler. `runtime.py` does NOT catch, wrap, or rewrap `ReplayBacktestRunnerDomainError` raised from any value-object `__post_init__`. Service and domain errors propagate unchanged.
12. `runtime.py` does NOT mutate any caller-supplied input. The `paper_ledger_entry`, `replay_run`, and `steps` parameters are passed through unchanged.
13. `runtime.py` does NOT directly construct any `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun`; value-object construction is delegated entirely to the 2I.B service.
14. Every test file under `v2/backend/tests/unit/composition/replay_backtest_runner/` contains exactly one test function whose name starts with `test_` and uses inline hand-written fakes; no shared `conftest` is created or modified.
15. `test_composition_milestone_forbidden_tokens.py` constructs every forbidden literal at runtime via string concatenation, scans the three authored source files, and applies NO exemption (covers `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, the lowercase `deny_default`, the literal `mirror_deny_default`, the four call-form tokens, and the harness framing tokens `BEGIN_FILE` / `END_FILE`).
16. `test_init_module_does_not_load_redis.py`, `test_init_module_does_not_load_url_env.py`, `test_init_module_does_not_register_fastapi_lifespan.py`, and `test_runtime_module_does_not_load_redis_when_imported.py` each launch a child interpreter via `subprocess.run([sys.executable, '-c', ...])` (allowed in test files only) to ensure a clean module table after re-import.
17. `test_public_surface.py` asserts the exact `(name, ordering)` of `__all__` and asserts `ReplayBacktestRunnerCompositionError` is NOT a subclass of `ValueError`.
18. `test_replay_backtest_runner_class_invariants.py` asserts `__slots__` exact 2-tuple, slotted-instance discipline (no `__dict__` on instance, foreign-attribute attachment raises `AttributeError`), and absence of foreign methods.
19. `test_validates_now_ms_clock_callable.py` asserts non-callable input raises `ReplayBacktestRunnerCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`, covering at least integer, `None`, and string inputs.
20. `test_returns_replay_backtest_runner_instance.py` asserts the returned object is a `ReplayBacktestRunner` instance with two callable attributes; both attributes are NOT identity-equal to the input clock; the two attributes are NOT identity-equal to each other.
21. `test_assemble_step_not_invoked_at_build_time.py` and `test_assemble_summary_not_invoked_at_build_time.py` each assert the corresponding clock counter is zero immediately after `build_replay_backtest_runner` returns.
22. `test_both_closures_share_captured_clock.py` asserts that calling `runner.assemble_step` once and then `runner.assemble_summary` once both increment the same shared counter, demonstrating clock-identity sharing.
23. `test_runner_returns_new_callables_not_input_clock.py` asserts the two attribute callables are distinct from each other and distinct from the input clock.
24. `test_assemble_step_invokes_clock_exactly_once_per_call.py` asserts the clock counter increments by exactly 1 per `runner.assemble_step` call.
25. `test_assemble_step_returns_replay_backtest_step.py` asserts `isinstance` check against the 2I.A `ReplayBacktestStep` type.
26. `test_assemble_step_records_clock_into_step_ts_ms.py` asserts the returned step's `step_ts_ms` equals the clock return value.
27. `test_assemble_step_keyword_only_params.py` asserts positional-arg calling raises `TypeError`.
28. `test_assemble_step_does_not_mutate_supplied_inputs.py` asserts the original `PaperExecutionLedgerEntry` and `ReplayBacktestRun` field values remain byte-identical after the call.
29. `test_assemble_step_propagates_allow_proceed_long.py` asserts the `allow_proceed_long` mirror flows through the runner.
30. `test_assemble_step_propagates_allow_proceed_short.py` asserts the `allow_proceed_short` mirror flows through the runner.
31. `test_assemble_step_propagates_deny_orchestrator_held.py` asserts the `deny_orchestrator_held` mirror flows through the runner.
32. `test_assemble_step_propagates_deny_orchestrator_abstained.py` asserts the `deny_orchestrator_abstained` mirror flows through the runner.
33. `test_assemble_step_propagates_deny_default.py` asserts the `deny_default` mirror flows through the runner using runtime-reconstructed literals so the test source file does not contain the bare `deny_default` token; the test imports the constants `PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT` and `STEP_REASON_MIRROR_DENY_DEFAULT` from their canonical 2H.A and 2I.A modules instead of using the bare string literals.
34. `test_assemble_step_propagates_service_error_for_non_paper_entry.py` asserts non-`PaperExecutionLedgerEntry` `paper_ledger_entry` raises `ReplayBacktestRunnerServiceError` with `code == "must_be_paper_execution_ledger_entry"` and `field == "paper_ledger_entry"`.
35. `test_assemble_step_propagates_service_error_for_non_run.py` asserts non-`ReplayBacktestRun` `replay_run` raises `ReplayBacktestRunnerServiceError` with `code == "must_be_replay_backtest_run"` and `field == "replay_run"`.
36. `test_assemble_step_propagates_service_error_for_symbol_mismatch.py` asserts symbol mismatch between paper-ledger entry and replay run raises `ReplayBacktestRunnerServiceError` with `code == "paper_ledger_entry_symbol_must_match_replay_run_symbol"` and `field == "paper_ledger_entry.symbol"`.
37. `test_assemble_summary_invokes_clock_exactly_once_per_call.py` asserts the clock counter increments by exactly 1 per `runner.assemble_summary` call.
38. `test_assemble_summary_returns_replay_backtest_summary.py` asserts `isinstance` check against the 2I.A `ReplayBacktestSummary` type.
39. `test_assemble_summary_records_clock_into_summary_emitted_ts_ms.py` asserts the returned summary's `summary_emitted_ts_ms` equals the clock return value.
40. `test_assemble_summary_keyword_only_params.py` asserts positional-arg calling raises `TypeError`.
41. `test_assemble_summary_propagates_service_error_for_non_tuple_steps.py` asserts list-typed `steps` raises `ReplayBacktestRunnerServiceError` with `code == "must_be_tuple"` and `field == "steps"`.
42. `test_assemble_summary_propagates_service_error_for_step_replay_run_id_mismatch.py` asserts step-vs-run replay_run_id mismatch raises `ReplayBacktestRunnerServiceError` with `code == "step_replay_run_id_must_match_replay_run_id"` and `field == "steps[0].replay_run_id"`.
43. `test_assemble_summary_does_not_mutate_supplied_inputs.py` asserts the original `ReplayBacktestRun` and step tuple remain byte-identical after the call.
44. `test_errors_invariants.py` asserts `code`, `field`, `__str__`, and that omitting `field` raises `TypeError`.
45. `test_composition_does_not_import_url_env_directly.py` asserts neither `runtime.py` nor `__init__.py` source contains the literal `"url" + "_env"` reconstructed at runtime.
46. The 35 composition test files in `v2/backend/tests/unit/composition/replay_backtest_runner/` pass with zero failures and zero errors.
47. The existing 2I.B service suite, 2I.A domain suite, 2H.C composition suite, 2H.B service suite, 2H.A domain suite, 2G.C composition suite, 2G.B service suite, 2G.A domain suite, 2F.C composition suite, 2F.B service suite, 2F.A domain suite, 2E3.C composition suite, 2E3.B service suite, 2E3.A domain suite, 2E2.C composition suite, 2E2.B service suite, 2E2.A domain suite, 2E1.E composition suite, 2E1.D service suite, and 2E1 trainer_liveness domain suite all pass with zero failures and zero errors.
48. `py_compile` passes for the three authored source files.
49. `git status -s` over the cross-isolation paths in `20` returns zero lines.
50. No FastAPI startup hook, lifespan handler, dependency, router registration, module-level singleton, module-level cache, module-level lock, or background task anywhere in the three authored source files.
51. No write to any cross-isolation path in `20`.
52. No secret-shaped string in the diff (per the canonical secret list).
53. No `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, `orchestrator_decision`, `risk_gateway`, or `paper_execution_ledger` service or composition import in any of the three authored source files. No import of `v2.backend.app.domain.orchestrator_decision` or `v2.backend.app.domain.risk_gateway`.
54. No REQ_0017 scope-cap violation: no execution-side surface beyond the existing 2H ledger boundary plus the existing 2I replay/backtest runner boundary, no paper executor, no shadow executor, no replay engine, no scheduler, no background loop, no paper trader process, no strategy library, no model-loading, no GPU, no checkpoint subsystem expansion; no FastAPI surface; no adapter expansion; no expansion of the binder beyond the one build-time `now_ms_clock` parameter and the slotted runner's two attribute closures; no new lineage ID at the composition layer beyond the `replay_step_id` and `replay_summary_id` already derived inside the 2I.B service; no replay/ledger persistence; no PnL/position-sizing/quantity/price/fees/slippage/risk-adjusted-return computation.
55. No `paper_ledger_entry`, `replay_run`, or `steps` mutation at runtime; the parameters are forwarded by reference unchanged.
56. No import or emission of `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `RISK_DECISION_REASON_DENY_DEFAULT`, the literal lowercase `deny_default`, or the literal `mirror_deny_default` in any authored 2I.C source file.
57. `git ls-files v2/backend/app/composition/replay_backtest_runner.py` returns zero output lines (no flat-file placeholder introduced).
58. `git ls-files v2/backend/app/services/replay_runner.py` returns exactly one output line and `git diff --stat HEAD -- v2/backend/app/services/replay_runner.py` returns zero output lines (placeholder untouched).
59. `git ls-files v2/backend/app/services/paper_loop.py` returns exactly one output line and `git diff --stat HEAD -- v2/backend/app/services/paper_loop.py` returns zero output lines (placeholder untouched).
60. `git ls-files v2/backend/app/domain/execution/` returns zero output lines (directory remains unpopulated).
61. No successful construction of a `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` with `live_blocked == False` is observed in the test corpus or the source files (the 2H.B and 2I.B services hard-code `live_blocked=True`; 2I.C only forwards).
62. No direct construction of `ReplayBacktestStep`, `ReplayBacktestSummary`, `PaperExecutionLedgerEntry`, or `ReplayBacktestRun` in any authored 2I.C source file (value-object construction is the responsibility of the 2I.B assembler service alone).

If all 62 rows PASS, the Codex review report (`24`) ends with `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_REVIEW_READY` and the Codex GO/NO-GO file (`25`) contains exactly `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`. On any FAIL with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2I.C source files plus the 35 new test files only. On any safety violation, surface to human attention; no autofix is permitted.

## Phase exit (closing Phase 2I → opening REQ_0017 milestone 6)

Phase 2I closes when the 2I.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 5 (`REPLAY_BACKTEST_RUNNER_MVP`) is satisfied and the planner opens REQ_0017 milestone 6 (`PAPER_MODE_MVP`) under a fresh consolidated milestone turn. No execution-side behavior beyond the existing ledger and replay/backtest runner boundary, no paper executor, no shadow executor, no replay engine, no scheduler, no background loop, no paper trader process, and no strategy library is opened in 2I.C.

PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY
