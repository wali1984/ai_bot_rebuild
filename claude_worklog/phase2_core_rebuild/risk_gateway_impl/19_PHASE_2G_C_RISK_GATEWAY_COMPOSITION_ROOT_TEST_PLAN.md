# Phase 2G.C — Risk Gateway Composition Root Test Plan

All tests live under `v2/backend/tests/unit/composition/risk_gateway/`. Each test file contains exactly one test function whose name starts with `test_` and mirrors the file basename. No shared `conftest.py` is created or modified. Inline construction of the keyword arguments and `OrchestratorDecisionRecord` instances is required in each test that needs them; no helper module or fixture is added. Tests construct hand-written fakes inline.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 24)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of `v2.backend.app.composition.risk_gateway` equals `("build_risk_decision_evaluator", "RiskDecisionEvaluator", "RiskGatewayCompositionError")` exactly, including order; assert `build_risk_decision_evaluator` is callable; assert `RiskGatewayCompositionError` is a class and a subclass of `Exception` and is NOT a subclass of `ValueError`; assert `RiskDecisionEvaluator` is exported.

2. `test_errors_invariants.py` — instantiate `RiskGatewayCompositionError("some_code", field="some_field")`; assert `e.code == "some_code"`; assert `e.field == "some_field"`; assert `str(e) == "some_code (some_field)"`; assert calling without `field=` raises `TypeError` because `field` is required (no default).

Import-clean tests (each test must reconstruct the forbidden literal at runtime via string concatenation so the test source file does not contain the bare token; each test launches a child interpreter via `subprocess.run([sys.executable, "-c", ...])`):

3. `test_init_module_does_not_load_redis.py` — purge any literal `"red" + "is"` prefixed and `v2.backend.app.composition.risk_gateway*` entries from `sys.modules` in the child interpreter, re-import the package, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

4. `test_init_module_does_not_load_url_env.py` — purge any `v2.backend.app.adapters.redis_v2.url_env*` and `v2.backend.app.composition.risk_gateway*` entries from `sys.modules`, re-import the package, then assert no key containing the literal `"url" + "_env"` is present.

5. `test_init_module_does_not_register_fastapi_lifespan.py` — purge any `"fast" + "api"` prefixed and `v2.backend.app.composition.risk_gateway*` entries from `sys.modules`, re-import the package, then assert no `sys.modules` key starts with `"fast" + "api"`.

6. `test_runtime_module_does_not_load_redis_when_imported.py` — purge any `"red" + "is"` prefixed and `v2.backend.app.composition.risk_gateway.runtime` entries from `sys.modules`, then `import v2.backend.app.composition.risk_gateway.runtime`, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

Forbidden-token scan tests:

7. `test_composition_milestone_forbidden_tokens.py` — read the bytes of `__init__.py`, `errors.py`, `runtime.py`. For each forbidden literal listed in spec 18 'Forbidden tokens in source files', reconstruct the literal at runtime via string concatenation and assert the literal does not appear in any of the three source files. Apply NO exemption. Reconstruction MUST cover both `RISK_DECISION_REASON_DENY_DEFAULT` and the literal lowercase `deny_default`.

8. `test_composition_does_not_import_url_env_directly.py` — open `runtime.py` and `__init__.py`, read source, assert neither file source contains the literal `"url" + "_env"` reconstructed at runtime.

Build-time validation tests for `now_ms_clock`:

9. `test_validates_now_ms_clock_callable.py` — call `build_risk_decision_evaluator(now_ms_clock=42)` and assert it raises `RiskGatewayCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`. Also pass `None` and re-assert the same exception, code, and field. Also pass the string `"not_callable"` and re-assert.

10. `test_returns_callable_evaluator.py` — pass `now_ms_clock=lambda: 123` and assert the return value is callable. Assert the returned object is not the input clock (the binder MUST return a NEW callable, not pass the clock through).

Build-time non-invocation tests:

11. `test_assembler_not_invoked_at_build_time.py` — define a counter list `n=[0]` and a clock that increments it. Call `build_risk_decision_evaluator(now_ms_clock=...)`. Immediately after, assert `n == [0]` (the clock must NOT be called at build time). Also assert that no `RiskDecisionRecord` was constructed at build time by checking that no record-related side effect occurred (the test does not need to construct an OrchestratorDecisionRecord at build-time observation, only confirm the clock counter remains zero).

Evaluator forwarding tests (each constructs a counter-equipped clock, builds the evaluator, calls it once with an inline-constructed valid `OrchestratorDecisionRecord`, and asserts both behavior and forwarding):

12. `test_evaluator_invokes_assembler_exactly_once_per_call.py` — define a clock with a single-shot counter. Build the evaluator. Call the evaluator once with a valid `decision=OrchestratorDecisionRecord(...)` whose `decision_action` is `hold` and `decision_reason_code` is `hold_flat_direction`. Assert the clock counter incremented to exactly 1, demonstrating the assembler ran exactly once and called the clock exactly once.

13. `test_evaluator_returns_risk_decision_record.py` — call the evaluator with valid kwargs and assert `isinstance(result, RiskDecisionRecord)` is true (import `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway`).

14. `test_evaluator_records_clock_into_risk_decision_ts_ms.py` — pass `now_ms_clock=lambda: 1700000000000`, call the evaluator with a valid `decision`, assert `result.risk_decision_ts_ms == 1700000000000`.

Default-deny taxonomy mapping tests (one per orchestrator action; each constructs an inline-valid OrchestratorDecisionRecord whose action and reason match the 2F.A taxonomy and asserts the 2G.B service-layer mapping flows through the binder unchanged):

15. `test_evaluator_propagates_open_long_to_allow_proceed_long.py` — build the evaluator with `now_ms_clock=lambda: 1`. Call with an OrchestratorDecisionRecord whose `decision_action == "open_long"` and `decision_reason_code == "proceed_long"`. Assert `result.risk_action == "allow"` and `result.risk_reason_code == "allow_proceed_long"` and `result.input_decision_action == "open_long"` and `result.input_decision_reason_code == "proceed_long"` and `result.live_blocked is True`.

16. `test_evaluator_propagates_open_short_to_allow_proceed_short.py` — build the evaluator with `now_ms_clock=lambda: 1`. Call with an OrchestratorDecisionRecord whose `decision_action == "open_short"` and `decision_reason_code == "proceed_short"`. Assert `result.risk_action == "allow"` and `result.risk_reason_code == "allow_proceed_short"` and `result.input_decision_action == "open_short"` and `result.input_decision_reason_code == "proceed_short"` and `result.live_blocked is True`.

17. `test_evaluator_propagates_hold_to_deny_orchestrator_held.py` — build the evaluator with `now_ms_clock=lambda: 1`. Call with an OrchestratorDecisionRecord whose `decision_action == "hold"` and `decision_reason_code == "hold_flat_direction"`. Assert `result.risk_action == "deny"` and `result.risk_reason_code == "deny_orchestrator_held"` and `result.input_decision_action == "hold"` and `result.input_decision_reason_code == "hold_flat_direction"` and `result.live_blocked is True`.

18. `test_evaluator_propagates_abstain_to_deny_orchestrator_abstained.py` — build the evaluator with `now_ms_clock=lambda: 1`. Call with an OrchestratorDecisionRecord whose `decision_action == "abstain"` and `decision_reason_code == "abstain_low_confidence"`. Assert `result.risk_action == "deny"` and `result.risk_reason_code == "deny_orchestrator_abstained"` and `result.input_decision_action == "abstain"` and `result.input_decision_reason_code == "abstain_low_confidence"` and `result.live_blocked is True`.

Keyword-only enforcement test:

19. `test_evaluator_keyword_only_params.py` — call the evaluator with one positional argument and assert `TypeError` is raised, demonstrating the inner function declares the `decision` parameter keyword-only.

Error propagation tests:

20. `test_evaluator_propagates_service_error_for_non_int_clock.py` — pass `now_ms_clock=lambda: 1.5`, build the evaluator, call it with a valid `decision`, assert `RiskGatewayServiceError` is raised with `code == "must_be_int"` and `field == "now_ms_clock"`. The composition root MUST NOT catch or wrap the service error; the assertion verifies the service error class propagates unchanged. Import `RiskGatewayServiceError` from `v2.backend.app.services.risk_gateway`.

21. `test_evaluator_propagates_service_error_for_negative_clock.py` — pass `now_ms_clock=lambda: -1`, build the evaluator, call it with a valid `decision`, assert `RiskGatewayServiceError` is raised with `code == "must_be_nonnegative"` and `field == "now_ms_clock"`.

22. `test_evaluator_propagates_service_error_for_non_record_decision.py` — build the evaluator with valid build args, call the evaluator with `decision="not a record"`, assert `RiskGatewayServiceError` is raised with `code == "must_be_orchestrator_decision_record"` and `field == "decision"`.

23. `test_evaluator_propagates_service_error_for_long_decision_id.py` — construct an `OrchestratorDecisionRecord` whose `decision_id` is 126 characters long (one past the 125 limit enforced by the 2G.B service). Build the evaluator with valid build args, call the evaluator with the long-id decision, assert `RiskGatewayServiceError` is raised with `code == "decision_id_too_long_for_risk_decision_id_derivation"` and `field == "decision.decision_id"`.

24. `test_evaluator_does_not_mutate_supplied_inputs.py` — build with valid build args. Construct a valid `OrchestratorDecisionRecord` and snapshot every input lineage field on the record before the call. Call the evaluator. After the call, assert each field on the original record is byte-identical to its pre-call value (records are frozen, but the test asserts equality via attribute access on the same object). Also assert the original `decision` reference is unchanged.

## Inline fakes

Test files MUST construct hand-written fakes inline (a tiny callable returning a fixed int or sequence of ints; a hand-built `OrchestratorDecisionRecord` per the 2F.A constructor surface). No `unittest.mock`. No third-party fakes. No shared helper module. No conftest.

## Test runner expectations

`.venv/bin/python -m pytest v2/backend/tests/unit/composition/risk_gateway/ -q` must report `24 passed` with zero failures and zero errors. The 2G.B service suite (`v2/backend/tests/unit/services/risk_gateway/`), the 2G.A domain suite (`v2/backend/tests/unit/domain/risk_gateway/`), the 2F.C composition suite (`v2/backend/tests/unit/composition/orchestrator_decision/`), the 2F.B service suite (`v2/backend/tests/unit/services/orchestrator_decision/`), the 2F.A domain suite (`v2/backend/tests/unit/domain/orchestrator_decision/`), the 2E3.C composition suite (`v2/backend/tests/unit/composition/trainer_prediction_output/`), the 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), the 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), the 2E2.C composition suite (`v2/backend/tests/unit/composition/trainer_worker_health/`), the 2E2.B service suite (`v2/backend/tests/unit/services/trainer_worker_health/`), the 2E2.A domain suite (`v2/backend/tests/unit/domain/trainer_worker_health/`), the 2E1.E composition suite (`v2/backend/tests/unit/composition/trainer_parity/`), the 2E1.D service suite (`v2/backend/tests/unit/services/trainer_parity/`), and the 2E1 trainer_liveness domain suite (`v2/backend/tests/unit/domain/trainer_liveness/`) must continue to pass with zero regressions when run individually.

PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_TEST_PLAN_READY
