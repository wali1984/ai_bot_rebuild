# Phase 2H.C — Paper Execution Ledger Composition Root Test Plan

All tests live under `v2/backend/tests/unit/composition/paper_execution_ledger/`. Each test file contains exactly one test function whose name starts with `test_` and mirrors the file basename. No shared `conftest.py` is created or modified. Inline construction of the keyword arguments and `RiskDecisionRecord` instances is required in each test that needs them; no helper module or fixture is added. Tests construct hand-written fakes inline.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 25)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of `v2.backend.app.composition.paper_execution_ledger` equals `("build_paper_execution_ledger_recorder", "PaperExecutionLedgerRecorder", "PaperExecutionLedgerCompositionError")` exactly, including order; assert `build_paper_execution_ledger_recorder` is callable; assert `PaperExecutionLedgerCompositionError` is a class and a subclass of `Exception` and is NOT a subclass of `ValueError`; assert `PaperExecutionLedgerRecorder` is exported.

2. `test_errors_invariants.py` — instantiate `PaperExecutionLedgerCompositionError("some_code", field="some_field")`; assert `e.code == "some_code"`; assert `e.field == "some_field"`; assert `str(e) == "some_code (some_field)"`; assert calling without `field=` raises `TypeError` because `field` is required (no default).

Import-clean tests (each test must reconstruct the forbidden literal at runtime via string concatenation so the test source file does not contain the bare token; each test launches a child interpreter via `subprocess.run([sys.executable, "-c", ...])`):

3. `test_init_module_does_not_load_redis.py` — purge any literal `"red" + "is"` prefixed and `v2.backend.app.composition.paper_execution_ledger*` entries from `sys.modules` in the child interpreter, re-import the package, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

4. `test_init_module_does_not_load_url_env.py` — purge any `v2.backend.app.adapters.redis_v2.url_env*` and `v2.backend.app.composition.paper_execution_ledger*` entries from `sys.modules`, re-import the package, then assert no key containing the literal `"url" + "_env"` is present.

5. `test_init_module_does_not_register_fastapi_lifespan.py` — purge any `"fast" + "api"` prefixed and `v2.backend.app.composition.paper_execution_ledger*` entries from `sys.modules`, re-import the package, then assert no `sys.modules` key starts with `"fast" + "api"`.

6. `test_runtime_module_does_not_load_redis_when_imported.py` — purge any `"red" + "is"` prefixed and `v2.backend.app.composition.paper_execution_ledger.runtime` entries from `sys.modules`, then `import v2.backend.app.composition.paper_execution_ledger.runtime`, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

Forbidden-token scan tests:

7. `test_composition_milestone_forbidden_tokens.py` — read the bytes of `__init__.py`, `errors.py`, `runtime.py`. For each forbidden literal listed in spec 19 'Forbidden tokens in source files', reconstruct the literal at runtime via string concatenation and assert the literal does not appear in any of the three source files. Apply NO exemption. Reconstruction MUST cover `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, and the lowercase `deny_default`.

8. `test_composition_does_not_import_url_env_directly.py` — open `runtime.py` and `__init__.py`, read source, assert neither file source contains the literal `"url" + "_env"` reconstructed at runtime.

Build-time validation tests for `now_ms_clock`:

9. `test_validates_now_ms_clock_callable.py` — call `build_paper_execution_ledger_recorder(now_ms_clock=42)` and assert it raises `PaperExecutionLedgerCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`. Also pass `None` and re-assert the same exception, code, and field. Also pass the string `"not_callable"` and re-assert.

10. `test_returns_callable_recorder.py` — pass `now_ms_clock=lambda: 123` and assert the return value is callable. Assert the returned object is not the input clock (the binder MUST return a NEW callable, not pass the clock through).

Build-time non-invocation tests:

11. `test_assembler_not_invoked_at_build_time.py` — define a counter list `n=[0]` and a clock that increments it. Call `build_paper_execution_ledger_recorder(now_ms_clock=...)`. Immediately after, assert `n == [0]` (the clock must NOT be called at build time). Also assert that no `PaperExecutionLedgerEntry` was constructed at build time by checking that no entry-related side effect occurred (the test does not need to construct a `RiskDecisionRecord` at build-time observation, only confirm the clock counter remains zero).

Recorder forwarding tests (each constructs a counter-equipped clock, builds the recorder, calls it once with an inline-constructed valid `RiskDecisionRecord`, and asserts both behavior and forwarding):

12. `test_recorder_invokes_assembler_exactly_once_per_call.py` — define a clock with a single-shot counter. Build the recorder. Call the recorder once with a valid `decision=RiskDecisionRecord(...)` whose `risk_action` is `allow` and `risk_reason_code` is `allow_proceed_long`. Assert the clock counter incremented to exactly 1, demonstrating the assembler ran exactly once and called the clock exactly once.

13. `test_recorder_returns_paper_execution_ledger_entry.py` — call the recorder with valid kwargs and assert `isinstance(result, PaperExecutionLedgerEntry)` is true (import `PaperExecutionLedgerEntry` from `v2.backend.app.domain.paper_execution_ledger`).

14. `test_recorder_records_clock_into_ledger_entry_ts_ms.py` — pass `now_ms_clock=lambda: 1700000000000`, call the recorder with a valid `decision`, assert `result.ledger_entry_ts_ms == 1700000000000`.

Mirror-taxonomy mapping tests (one per risk-reason branch authored in 2H.B; each constructs an inline-valid `RiskDecisionRecord` whose action and reason match the 2G.A taxonomy and asserts the 2H.B service-layer mirror flows through the binder unchanged):

15. `test_recorder_propagates_allow_proceed_long_to_mirror_allow_proceed_long.py` — build the recorder with `now_ms_clock=lambda: 1`. Call with a `RiskDecisionRecord` whose `risk_action == "allow"` and `risk_reason_code == "allow_proceed_long"`. Assert `result.ledger_action == "record_allow"` and `result.ledger_reason_code == "mirror_allow_proceed_long"` and `result.input_risk_action == "allow"` and `result.input_risk_reason_code == "allow_proceed_long"` and `result.live_blocked is True`.

16. `test_recorder_propagates_allow_proceed_short_to_mirror_allow_proceed_short.py` — build the recorder with `now_ms_clock=lambda: 1`. Call with a `RiskDecisionRecord` whose `risk_action == "allow"` and `risk_reason_code == "allow_proceed_short"`. Assert `result.ledger_action == "record_allow"` and `result.ledger_reason_code == "mirror_allow_proceed_short"` and `result.input_risk_action == "allow"` and `result.input_risk_reason_code == "allow_proceed_short"` and `result.live_blocked is True`.

17. `test_recorder_propagates_deny_orchestrator_held_to_mirror_deny_orchestrator_held.py` — build the recorder with `now_ms_clock=lambda: 1`. Call with a `RiskDecisionRecord` whose `risk_action == "deny"` and `risk_reason_code == "deny_orchestrator_held"`. Assert `result.ledger_action == "record_deny"` and `result.ledger_reason_code == "mirror_deny_orchestrator_held"` and `result.input_risk_action == "deny"` and `result.input_risk_reason_code == "deny_orchestrator_held"` and `result.live_blocked is True`.

18. `test_recorder_propagates_deny_orchestrator_abstained_to_mirror_deny_orchestrator_abstained.py` — build the recorder with `now_ms_clock=lambda: 1`. Call with a `RiskDecisionRecord` whose `risk_action == "deny"` and `risk_reason_code == "deny_orchestrator_abstained"`. Assert `result.ledger_action == "record_deny"` and `result.ledger_reason_code == "mirror_deny_orchestrator_abstained"` and `result.input_risk_action == "deny"` and `result.input_risk_reason_code == "deny_orchestrator_abstained"` and `result.live_blocked is True`.

19. `test_recorder_propagates_deny_default_to_mirror_deny_default.py` — build the recorder with `now_ms_clock=lambda: 1`. Construct an inline `RiskDecisionRecord` whose `risk_action == "deny"` and `risk_reason_code` is the literal lowercase `"deny_default"` reconstructed at runtime via string concatenation so the test source file does not contain the bare token. Call the recorder with that record. Assert `result.ledger_action == "record_deny"` and `result.ledger_reason_code == "mirror_deny_default"` (also reconstructed at runtime) and `result.input_risk_action == "deny"` and `result.input_risk_reason_code == "deny_default"` (reconstructed) and `result.live_blocked is True`.

Keyword-only enforcement test:

20. `test_recorder_keyword_only_params.py` — call the recorder with one positional argument and assert `TypeError` is raised, demonstrating the inner function declares the `decision` parameter keyword-only.

Error propagation tests:

21. `test_recorder_propagates_service_error_for_non_int_clock.py` — pass `now_ms_clock=lambda: 1.5`, build the recorder, call it with a valid `decision`, assert `PaperExecutionLedgerServiceError` is raised with `code == "must_be_int"` and `field == "now_ms_clock"`. The composition root MUST NOT catch or wrap the service error; the assertion verifies the service error class propagates unchanged. Import `PaperExecutionLedgerServiceError` from `v2.backend.app.services.paper_execution_ledger`.

22. `test_recorder_propagates_service_error_for_negative_clock.py` — pass `now_ms_clock=lambda: -1`, build the recorder, call it with a valid `decision`, assert `PaperExecutionLedgerServiceError` is raised with `code == "must_be_nonnegative"` and `field == "now_ms_clock"`.

23. `test_recorder_propagates_service_error_for_non_record_decision.py` — build the recorder with valid build args, call the recorder with `decision="not a record"`, assert `PaperExecutionLedgerServiceError` is raised with `code == "must_be_risk_decision_record"` and `field == "decision"`.

24. `test_recorder_propagates_service_error_for_long_risk_decision_id.py` — construct a `RiskDecisionRecord` whose `risk_decision_id` is 126 characters long (one past the 125 limit enforced by the 2H.B service). Build the recorder with valid build args, call the recorder with the long-id decision, assert `PaperExecutionLedgerServiceError` is raised with `code == "risk_decision_id_too_long_for_paper_trade_id_derivation"` and `field == "decision.risk_decision_id"`.

25. `test_recorder_does_not_mutate_supplied_inputs.py` — build with valid build args. Construct a valid `RiskDecisionRecord` and snapshot every input lineage field on the record before the call. Call the recorder. After the call, assert each field on the original record is byte-identical to its pre-call value (records are frozen, but the test asserts equality via attribute access on the same object). Also assert the original `decision` reference is unchanged.

## Inline fakes

Test files MUST construct hand-written fakes inline (a tiny callable returning a fixed int or sequence of ints; a hand-built `RiskDecisionRecord` per the 2G.A constructor surface). No `unittest.mock`. No third-party fakes. No shared helper module. No conftest.

## Test runner expectations

`.venv/bin/python -m pytest v2/backend/tests/unit/composition/paper_execution_ledger/ -q` must report `25 passed` with zero failures and zero errors. The 2H.B service suite (`v2/backend/tests/unit/services/paper_execution_ledger/`), the 2H.A domain suite (`v2/backend/tests/unit/domain/paper_execution_ledger/`), the 2G.C composition suite (`v2/backend/tests/unit/composition/risk_gateway/`), the 2G.B service suite (`v2/backend/tests/unit/services/risk_gateway/`), the 2G.A domain suite (`v2/backend/tests/unit/domain/risk_gateway/`), the 2F.C composition suite (`v2/backend/tests/unit/composition/orchestrator_decision/`), the 2F.B service suite (`v2/backend/tests/unit/services/orchestrator_decision/`), the 2F.A domain suite (`v2/backend/tests/unit/domain/orchestrator_decision/`), the 2E3.C composition suite (`v2/backend/tests/unit/composition/trainer_prediction_output/`), the 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), the 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), the 2E2.C composition suite (`v2/backend/tests/unit/composition/trainer_worker_health/`), the 2E2.B service suite (`v2/backend/tests/unit/services/trainer_worker_health/`), the 2E2.A domain suite (`v2/backend/tests/unit/domain/trainer_worker_health/`), the 2E1.E composition suite (`v2/backend/tests/unit/composition/trainer_parity/`), the 2E1.D service suite (`v2/backend/tests/unit/services/trainer_parity/`), and the 2E1 trainer_liveness domain suite (`v2/backend/tests/unit/domain/trainer_liveness/`) must continue to pass with zero regressions when run individually.

PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_TEST_PLAN_READY
