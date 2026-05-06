# Phase 2G.C — Risk Gateway Composition Root GO/NO-GO Request

This document is the consolidated GO/NO-GO request that the supervisor uses to gate dispatch of `131_risk_gateway_2gc_composition_root_implementation.json` and the subsequent `132_risk_gateway_2gc_composition_root_codex_review.json`. It also enumerates the Codex review rubric used by `132`.

## Predecessor markers (must all be present)

- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/15_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_GO_NO_GO.md` contains exactly `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/17_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md` contains exactly `PHASE2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_CODEX_PASS`.
- `v2/backend/app/services/risk_gateway/__init__.py`, `errors.py`, and `service.py` exist and pass their domain/service/composition-import-clean test suites.
- `v2/backend/app/services/risk_gateway.py` placeholder is deleted (verified by `git ls-files v2/backend/app/services/risk_gateway.py` returning zero output lines).

If any precondition is missing or different, the supervisor MUST NOT dispatch `131`.

## Implementation task `131` GO/NO-GO checks

`131` PASSes only if all of the following hold:

1. Worktree is clean at dispatch (`git status --porcelain` returns zero lines).
2. The three authored source files exist exactly at the spec'd paths and contain exactly the public surface and import set documented in `18`.
3. The 24 test files exist exactly at the test-plan paths in `19` and follow the one-test-function-per-file inline-fake rule.
4. `.venv/bin/python -m py_compile` of the three source files exits 0.
5. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/risk_gateway/ -q` reports `24 passed` and exits 0.
6. The 2G.B service suite, the 2G.A domain suite, the 2F.C composition suite, the 2F.B service suite, the 2F.A domain suite, and every 2E1/2E2/2E3 suite enumerated in `19` 'Test runner expectations' pass with zero regressions when run individually.
7. The forbidden-token scan returns zero matches per token across the three authored source files (including `RISK_DECISION_REASON_DENY_DEFAULT` and the literal `deny_default`).
8. The cross-isolation diff (`git status -s` over the safety-boundary path set in `20`) returns zero lines outside the additive 2G.C scope.
9. The implementation report (`22`) cites function/line-range evidence for each of the four behavior-contract steps in `18` and reports each safety-boundary item as `none observed` or `observed: <evidence>`.
10. No FastAPI lifespan, dependency, router, module-level singleton, cache, lock, wall-clock helper, `os.environ`, `subprocess` (outside test files), `socket`, secret-shaped string, URL string, or background task is present in the three authored source files.

If `131` PASSes, the implementation report ends with `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_IMPLEMENTATION_REPORT_READY` and the GO/NO-GO file (`23`) contains exactly `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`. If `131` FAILs with concrete blockers and no safety violation, the GO/NO-GO file contains exactly `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_FAILED` and the supervisor enqueues a REQ_0007 / REQ_0014 autofix task scoped to the three authored source files plus the 24 new test files only.

## Codex review task `132` rubric

`132` PASSes only if all of the following review items hold:

1. `__init__.py` re-exports exactly `(build_risk_decision_evaluator, RiskDecisionEvaluator, RiskGatewayCompositionError)` and `__all__` is exactly that 3-tuple in that order.
2. `errors.py` defines `RiskGatewayCompositionError(Exception)` with `__init__(self, code: str, *, field: str) -> None` and a `__repr__` consistent with spec `18`, importing only `from __future__ import annotations`.
3. `RiskGatewayCompositionError` is NOT a subclass of `ValueError` (kept distinct from the 2G.B service error and the 2G.A domain error to allow callers to discriminate build-time misconfiguration from call-time service-layer rejection and from value-object rejection).
4. `runtime.py` defines `RiskDecisionEvaluator` type alias as `Callable[..., RiskDecisionRecord]`.
5. `runtime.py` defines `build_risk_decision_evaluator` with the keyword-only signature declared in spec `18`; the parameter set is exactly `{now_ms_clock}`; the function returns `RiskDecisionEvaluator`.
6. `runtime.py` imports are exactly the six entries listed in spec `18` 'Imports allowed in runtime.py'. No third-party import. No `typing` import. No factory import. No `url` + `_env` import. No literal `red` + `is` import. No `fast` + `api` import. No `asyncio` import. No `threading` import. No `multiprocessing` import. No `subprocess` import. No `socket` import. No `selectors` import. No `pathlib` import. No `logging` import. No `datetime` import. No `time` import. No `os` import. No `math` import. No `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, or `orchestrator_decision` composition or service import (the only allowed orchestrator-decision import is the 2F.A `OrchestratorDecisionRecord` from the domain layer). The only stdlib imports beyond `__future__` are `from collections.abc import Callable`.
7. `runtime.py` contains zero occurrences of every literal in spec `18` 'Forbidden tokens in source files'. Verified via `rg --fixed-strings --case-sensitive` for each token. NO exemption applies.
8. The same forbidden-token set is absent from `__init__.py` and `errors.py`.
9. `runtime.py` implements the four behavior steps in this exact order: callable check on `now_ms_clock`, bind closure variable, define inner `_evaluator` with `decision` keyword-only parameter, return `_evaluator`. The inner `_evaluator` body is exactly a single `return assemble_risk_decision_record(decision=decision, now_ms_clock=_now_ms_clock)` statement with the closure variable forwarded.
10. `runtime.py` does NOT call `now_ms_clock` at build time. `runtime.py` does NOT call `assemble_risk_decision_record` at build time. `runtime.py` does NOT cache any value derived from the clock beyond binding the closure variable at build time.
11. `runtime.py` does NOT catch, wrap, or rewrap `RiskGatewayServiceError` raised from `assemble_risk_decision_record`. `runtime.py` does NOT catch, wrap, or rewrap `RiskGatewayDomainError` raised from `RiskDecisionRecord.__post_init__`. Service and domain errors propagate unchanged.
12. `runtime.py` does NOT mutate any caller-supplied input. The `decision` parameter is passed through unchanged.
13. Every test file under `v2/backend/tests/unit/composition/risk_gateway/` contains exactly one test function whose name starts with `test_` and uses inline hand-written fakes; no shared `conftest` is created or modified.
14. `test_composition_milestone_forbidden_tokens.py` constructs every forbidden literal at runtime via string concatenation, scans the three authored source files, and applies NO exemption (covers `RISK_DECISION_REASON_DENY_DEFAULT` and the lowercase `deny_default`).
15. `test_init_module_does_not_load_redis.py`, `test_init_module_does_not_load_url_env.py`, `test_init_module_does_not_register_fastapi_lifespan.py`, and `test_runtime_module_does_not_load_redis_when_imported.py` each launch a child interpreter via `subprocess.run([sys.executable, '-c', ...])` (allowed in test files only) to ensure a clean module table after re-import.
16. `test_public_surface.py` asserts the exact `(name, ordering)` of `__all__` and asserts `RiskGatewayCompositionError` is NOT a subclass of `ValueError`.
17. `test_validates_now_ms_clock_callable.py` asserts non-callable input raises `RiskGatewayCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`, covering at least integer, `None`, and string inputs.
18. `test_returns_callable_evaluator.py` asserts the returned evaluator is callable and is not the input clock (binder returns a NEW callable).
19. `test_assembler_not_invoked_at_build_time.py` asserts the clock counter is zero immediately after `build_risk_decision_evaluator` returns.
20. `test_evaluator_invokes_assembler_exactly_once_per_call.py` asserts the clock counter increments by exactly 1 per evaluator call.
21. `test_evaluator_returns_risk_decision_record.py` asserts `isinstance` check against the 2G.A domain `RiskDecisionRecord` type.
22. `test_evaluator_records_clock_into_risk_decision_ts_ms.py` asserts the returned record's `risk_decision_ts_ms` equals the clock return value.
23. `test_evaluator_propagates_open_long_to_allow_proceed_long.py` asserts the open_long mapping forwards through the binder.
24. `test_evaluator_propagates_open_short_to_allow_proceed_short.py` asserts the open_short mapping forwards through the binder.
25. `test_evaluator_propagates_hold_to_deny_orchestrator_held.py` asserts the hold mapping forwards through the binder.
26. `test_evaluator_propagates_abstain_to_deny_orchestrator_abstained.py` asserts the abstain mapping forwards through the binder.
27. `test_evaluator_keyword_only_params.py` asserts positional-arg calling raises `TypeError`.
28. `test_evaluator_propagates_service_error_for_non_int_clock.py` asserts a clock returning float raises `RiskGatewayServiceError` with `code == "must_be_int"` and `field == "now_ms_clock"`.
29. `test_evaluator_propagates_service_error_for_negative_clock.py` asserts a clock returning negative int raises `RiskGatewayServiceError` with `code == "must_be_nonnegative"` and `field == "now_ms_clock"`.
30. `test_evaluator_propagates_service_error_for_non_record_decision.py` asserts non-record `decision` raises `RiskGatewayServiceError` with `code == "must_be_orchestrator_decision_record"` and `field == "decision"`.
31. `test_evaluator_propagates_service_error_for_long_decision_id.py` asserts a 126-character `decision_id` raises `RiskGatewayServiceError` with `code == "decision_id_too_long_for_risk_decision_id_derivation"` and `field == "decision.decision_id"`.
32. `test_evaluator_does_not_mutate_supplied_inputs.py` asserts the original `OrchestratorDecisionRecord` field values remain byte-identical after the call.
33. `test_errors_invariants.py` asserts `code`, `field`, `__str__`, and that omitting `field` raises `TypeError`.
34. `test_composition_does_not_import_url_env_directly.py` asserts neither `runtime.py` nor `__init__.py` source contains the literal `"url" + "_env"` reconstructed at runtime.
35. The 24 composition test files in `v2/backend/tests/unit/composition/risk_gateway/` pass with zero failures and zero errors.
36. The existing 2G.B service suite (`v2/backend/tests/unit/services/risk_gateway/`), 2G.A domain suite (`v2/backend/tests/unit/domain/risk_gateway/`), 2F.C composition suite (`v2/backend/tests/unit/composition/orchestrator_decision/`), 2F.B service suite (`v2/backend/tests/unit/services/orchestrator_decision/`), 2F.A domain suite (`v2/backend/tests/unit/domain/orchestrator_decision/`), 2E3.C composition suite (`v2/backend/tests/unit/composition/trainer_prediction_output/`), 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), 2E2.C composition suite (`v2/backend/tests/unit/composition/trainer_worker_health/`), 2E2.B service suite (`v2/backend/tests/unit/services/trainer_worker_health/`), 2E2.A domain suite (`v2/backend/tests/unit/domain/trainer_worker_health/`), 2E1.E composition suite (`v2/backend/tests/unit/composition/trainer_parity/`), 2E1.D service suite (`v2/backend/tests/unit/services/trainer_parity/`), and 2E1 trainer_liveness domain suite (`v2/backend/tests/unit/domain/trainer_liveness/`) all pass with zero failures and zero errors.
37. `py_compile` passes for the three authored source files.
38. `git status -s` over the cross-isolation paths in `20` returns zero lines.
39. No FastAPI startup hook, lifespan handler, dependency, router registration, module-level singleton, module-level cache, module-level lock, or background task anywhere in the three authored source files.
40. No write to any cross-isolation path in `20`.
41. No secret-shaped string in the diff (per the canonical secret list).
42. No `trainer_worker_health`, `trainer_parity`, `trainer_prediction_output`, or `orchestrator_decision` service or composition import in any of the three authored source files (the only allowed orchestrator-decision import is the 2F.A `OrchestratorDecisionRecord` from the domain layer).
43. No REQ_0017 scope-cap violation: no execution-side surface, no paper executor, no shadow executor, no replay runner, no paper ledger, no model-loading, no GPU, no checkpoint subsystem expansion; no FastAPI surface; no adapter expansion; no expansion of the binder beyond the one build-time `now_ms_clock` parameter and the one call-time `decision` parameter; no new lineage ID at the composition layer beyond the `risk_decision_id` already derived inside the 2G.B service.
44. No `decision` mutation at runtime; the parameter is forwarded by reference unchanged.
45. No import or emission of `RISK_DECISION_REASON_DENY_DEFAULT` or the literal `deny_default` in any authored 2G.C source file.
46. `git ls-files v2/backend/app/services/risk_gateway.py` returns zero output lines (the placeholder deleted by 2G.B has not been reintroduced).
47. No successful construction of a `RiskDecisionRecord` with `live_blocked == False` is observed in the test corpus or the source files (the 2G.B service hard-codes `live_blocked=True`; 2G.C only forwards).

If all 47 rows PASS, the Codex review report (`24`) ends with `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_REVIEW_READY` and the Codex GO/NO-GO file (`25`) contains exactly `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS`. On any FAIL with concrete blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the three authored 2G.C source files plus the 24 new test files only. On any safety violation, surface to human attention; no autofix is permitted.

## Phase exit (closing Phase 2G → opening REQ_0017 milestone 4)

Phase 2G closes when the 2G.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 3 (`RISK_GATEWAY_DEFAULT_DENY_MVP`) is satisfied and the planner opens REQ_0017 milestone 4 (`PAPER_EXECUTION_LEDGER_MVP`) under a fresh consolidated milestone turn. No execution-side behavior, no paper executor, and no strategy library is opened in 2G.C.

PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY
