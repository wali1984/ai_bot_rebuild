# Phase 2F.C — Orchestrator Decision Composition Root GO/NO-GO Request

This document is the consolidated GO/NO-GO request that the supervisor uses to gate dispatch of `124_orchestrator_decision_2fc_composition_root_implementation.json` and the subsequent `125_orchestrator_decision_2fc_composition_root_codex_review.json`. It also enumerates the Codex review rubric used by `125`.

## Predecessor markers (must all be present)

- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/15_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_GO_NO_GO.md` contains exactly `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/17_2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` contains exactly `PHASE2F_B_ORCHESTRATOR_DECISION_ASSEMBLER_SERVICE_CODEX_PASS`.
- `v2/backend/app/services/orchestrator_decision/__init__.py`, `errors.py`, and `service.py` exist and pass their domain/service/composition-import-clean test suites.

If any precondition is missing or different, the supervisor MUST NOT dispatch `124`.

## Implementation task `124` GO/NO-GO checks

`124` PASSes only if all of the following hold:

1. Worktree is clean at dispatch (`git status --porcelain` returns zero lines).
2. The three authored source files exist exactly at the spec'd paths and contain exactly the public surface and import set documented in `18`.
3. The 28 test files exist exactly at the test-plan paths in `19` and follow the one-test-function-per-file inline-fake rule.
4. `.venv/bin/python -m py_compile` of the three source files exits 0.
5. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/orchestrator_decision/ -q` reports `28 passed` and exits 0.
6. The 2F.B service suite, the 2F.A domain suite, and every 2E1/2E2/2E3 suite enumerated below pass with zero regressions when run individually.
7. The forbidden-token scan returns zero matches per token across the three authored source files.
8. The cross-isolation diff (`git status -s` over the safety-boundary path set in `20`) returns zero lines outside the additive 2F.C scope.
9. The implementation report (`22`) cites function/line-range evidence for each of the seven behavior contract steps in `18` and reports each safety-boundary item as `none observed` or `observed: <evidence>`.
10. No FastAPI lifespan, dependency, router, module-level singleton, cache, lock, wall-clock helper, `os.environ`, `subprocess` (outside test files), `socket`, secret-shaped string, URL string, or background task is present in the three authored source files.

If `124` PASSes, the implementation report ends with `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_IMPLEMENTATION_REPORT_READY` and the GO/NO-GO file (`23`) contains exactly `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`. If `124` FAILs with concrete blockers and no safety violation, the GO/NO-GO file contains exactly `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_IMPL_AND_VALIDATION_FAILED` and the supervisor enqueues a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 28 new test files only.

## Codex review task `125` rubric

`125` PASSes only if all of the following review items hold:

1. `__init__.py` re-exports exactly `(build_orchestrator_decision_evaluator, OrchestratorDecisionEvaluator, OrchestratorDecisionCompositionError)` and `__all__` is exactly that 3-tuple in that order.
2. `errors.py` defines `OrchestratorDecisionCompositionError(Exception)` with `__init__(self, code: str, *, field: str) -> None` and a `__repr__` consistent with spec `18`, importing only `from __future__ import annotations`.
3. `OrchestratorDecisionCompositionError` is NOT a subclass of `ValueError` (kept distinct from the 2F.B service error to allow callers to discriminate build-time misconfiguration from call-time service-layer rejection).
4. `runtime.py` defines `OrchestratorDecisionEvaluator` type alias as `Callable[..., OrchestratorDecisionRecord]`.
5. `runtime.py` defines `build_orchestrator_decision_evaluator` with the keyword-only signature declared in spec `18`; the parameter set is exactly `{low_confidence_threshold, now_ms_clock}`; the function returns `OrchestratorDecisionEvaluator`.
6. `runtime.py` imports are exactly the seven entries listed in spec `18` 'Imports allowed in runtime.py'. No third-party import. No `typing` import. No factory import. No `url` + `_env` import. No literal `red` + `is` import. No `fast` + `api` import. No `asyncio` import. No `threading` import. No `multiprocessing` import. No `subprocess` import. No `socket` import. No `selectors` import. No `pathlib` import. No `logging` import. No `datetime` import. No `time` import. No `os` import. No `trainer_worker_health`, `trainer_parity`, or `trainer_prediction_output` composition or service import. The only stdlib imports beyond `__future__` are `import math` and `from collections.abc import Callable`.
7. `runtime.py` contains zero occurrences of every literal in spec `18` 'Forbidden tokens in source files'. Verified via `rg --fixed-strings --case-sensitive` for each token. NO exemption applies.
8. The same forbidden-token set is absent from `__init__.py` and `errors.py`.
9. `runtime.py` implements the seven behavior steps in this exact order: float-and-not-bool check on `low_confidence_threshold`, finite check, range `[0.0, 1.0]` check, callable check on `now_ms_clock`, bind closure variables, define inner `_evaluator` with `prediction` keyword-only parameter, return `_evaluator`. The inner `_evaluator` body is exactly a single `return assemble_orchestrator_decision_record(prediction=prediction, low_confidence_threshold=_low_confidence_threshold, now_ms_clock=_now_ms_clock)` statement with the closure variables forwarded.
10. `runtime.py` does NOT call `now_ms_clock` at build time. `runtime.py` does NOT call `assemble_orchestrator_decision_record` at build time. `runtime.py` does NOT cache any value derived from the clock or the threshold beyond binding the closure variables at build time.
11. `runtime.py` does NOT catch, wrap, or rewrap `OrchestratorDecisionServiceError` raised from `assemble_orchestrator_decision_record`. `runtime.py` does NOT catch, wrap, or rewrap `OrchestratorDecisionDomainError` raised from `OrchestratorDecisionRecord.__post_init__`. Service and domain errors propagate unchanged.
12. `runtime.py` does NOT mutate any caller-supplied input. The `prediction` parameter is passed through unchanged.
13. Every test file under `v2/backend/tests/unit/composition/orchestrator_decision/` contains exactly one test function whose name starts with `test_` and uses inline hand-written fakes; no shared `conftest` is created or modified.
14. `test_composition_milestone_forbidden_tokens.py` constructs every forbidden literal at runtime via string concatenation, scans the three authored source files, and applies NO exemption.
15. `test_init_module_does_not_load_redis.py`, `test_init_module_does_not_load_url_env.py`, `test_init_module_does_not_register_fastapi_lifespan.py`, and `test_runtime_module_does_not_load_redis_when_imported.py` each launch a child interpreter via `subprocess.run([sys.executable, '-c', ...])` (allowed in test files only) to ensure a clean module table after re-import.
16. `test_public_surface.py` asserts the exact `(name, ordering)` of `__all__` and asserts `OrchestratorDecisionCompositionError` is NOT a subclass of `ValueError`.
17. `test_validates_now_ms_clock_callable.py` asserts non-callable input raises `OrchestratorDecisionCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`, covering at least integer and `None` inputs.
18. `test_validates_low_confidence_threshold_not_float.py`, `test_validates_low_confidence_threshold_not_bool.py`, `test_validates_low_confidence_threshold_not_finite.py`, `test_validates_low_confidence_threshold_below_zero.py`, and `test_validates_low_confidence_threshold_above_one.py` each assert the documented `OrchestratorDecisionCompositionError` `code` and `field` for the corresponding invalid input.
19. `test_threshold_zero_accepted_at_build.py` and `test_threshold_one_accepted_at_build.py` confirm boundary acceptance at `0.0` and `1.0`.
20. `test_returns_callable_evaluator.py` asserts the returned evaluator is callable and is not the input clock (binder returns a NEW callable).
21. `test_assembler_not_invoked_at_build_time.py` asserts the clock counter is zero immediately after `build_orchestrator_decision_evaluator` returns.
22. `test_evaluator_invokes_assembler_exactly_once_per_call.py` asserts the clock counter increments by exactly 1 per evaluator call.
23. `test_evaluator_returns_orchestrator_decision_record.py` asserts `isinstance` check against the 2F.A domain `OrchestratorDecisionRecord` type.
24. `test_evaluator_records_clock_into_decision_ts_ms.py` asserts the returned record's `decision_ts_ms` equals the clock return value.
25. `test_evaluator_uses_captured_threshold.py` asserts that two binders with different thresholds produce different abstain/proceed verdicts for the same `prediction`, demonstrating per-binder threshold capture.
26. `test_evaluator_keyword_only_params.py` asserts positional-arg calling raises `TypeError`.
27. `test_evaluator_propagates_service_error_for_non_int_clock.py` asserts a clock returning float raises `OrchestratorDecisionServiceError` with `code == "must_be_int"` and `field == "now_ms_clock"`.
28. `test_evaluator_propagates_service_error_for_negative_clock.py` asserts a clock returning negative int raises `OrchestratorDecisionServiceError` with `code == "must_be_nonnegative"` and `field == "now_ms_clock"`.
29. `test_evaluator_propagates_service_error_for_non_record_prediction.py` asserts non-record `prediction` raises `OrchestratorDecisionServiceError` with `code == "must_be_trainer_prediction_record"` and `field == "prediction"`.
30. `test_evaluator_propagates_service_error_for_long_prediction_id.py` asserts a 125-character `prediction_id` raises `OrchestratorDecisionServiceError` with `code == "prediction_id_too_long_for_decision_id_derivation"` and `field == "prediction.prediction_id"`.
31. `test_evaluator_does_not_mutate_supplied_inputs.py` asserts the original `TrainerPredictionRecord` field values remain byte-identical after the call.
32. `test_errors_invariants.py` asserts `code`, `field`, `__str__`, and that omitting `field` raises `TypeError`.
33. `test_composition_does_not_import_url_env_directly.py` asserts neither `runtime.py` nor `__init__.py` source contains the literal `"url" + "_env"` reconstructed at runtime.
34. The 28 composition test files in `v2/backend/tests/unit/composition/orchestrator_decision/` pass with zero failures and zero errors.
35. The existing 2F.B service suite (`v2/backend/tests/unit/services/orchestrator_decision/`), 2F.A domain suite (`v2/backend/tests/unit/domain/orchestrator_decision/`), 2E3.C composition suite (`v2/backend/tests/unit/composition/trainer_prediction_output/`), 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), 2E2.C composition suite (`v2/backend/tests/unit/composition/trainer_worker_health/`), 2E2.B service suite (`v2/backend/tests/unit/services/trainer_worker_health/`), 2E2.A domain suite (`v2/backend/tests/unit/domain/trainer_worker_health/`), 2E1.E composition suite (`v2/backend/tests/unit/composition/trainer_parity/`), 2E1.D service suite (`v2/backend/tests/unit/services/trainer_parity/`), and 2E1 trainer_liveness domain suite (`v2/backend/tests/unit/domain/trainer_liveness/`) all pass with zero failures and zero errors.
36. `py_compile` passes for the three authored source files.
37. `git status -s` over the cross-isolation paths in `20` returns zero lines.
38. No FastAPI startup hook, lifespan handler, dependency, router registration, module-level singleton, module-level cache, module-level lock, or background task anywhere in the three authored source files.
39. No write to any cross-isolation path in `20`.
40. No secret-shaped string in the diff (per the canonical secret list).
41. No `trainer_worker_health`, `trainer_parity`, or `trainer_prediction_output` service or composition import in any of the three authored source files.
42. No REQ_0017 scope-cap violation: no risk-gateway, no execution-side, no model-loading, no GPU, no checkpoint subsystem expansion; no FastAPI surface; no adapter expansion; no expansion of the binder beyond the two build-time parameters and the one call-time `prediction` parameter.
43. No threshold mutation at runtime; the closure variable is the sole reference forwarded to the assembler.
44. No `prediction` mutation at runtime; the parameter is forwarded by reference unchanged.

If all 44 rows PASS, the Codex review report (`24`) ends with `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_REVIEW_READY` and the Codex GO/NO-GO file (`25`) contains exactly `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS`. On any FAIL with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2F.C source files plus the 28 new test files only. On any safety violation, surface to human attention; no autofix is permitted.

## Phase exit (closing Phase 2F → opening REQ_0017 milestone 3)

Phase 2F closes when the 2F.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 2 (`ORCHESTRATOR_DECISION_MVP`) is satisfied and the planner opens REQ_0017 milestone 3 (`RISK_GATEWAY_DEFAULT_DENY_MVP`) under a fresh consolidated milestone turn. No risk-gateway behavior, no execution-side surface, and no strategy library is opened in 2F.C.

PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY
