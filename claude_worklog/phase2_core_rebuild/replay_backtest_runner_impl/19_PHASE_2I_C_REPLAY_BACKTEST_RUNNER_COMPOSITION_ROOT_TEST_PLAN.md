# Phase 2I.C — Replay/Backtest Runner Composition Root Test Plan

All tests live under `v2/backend/tests/unit/composition/replay_backtest_runner/`. Each test file contains exactly one test function whose name starts with `test_` and mirrors the file basename. No shared `conftest.py` is created or modified. Inline construction of the keyword arguments and `PaperExecutionLedgerEntry` / `ReplayBacktestRun` / `ReplayBacktestStep` instances is required in each test that needs them; no helper module or fixture is added. Tests construct hand-written fakes inline using only the public 2I.A and 2H.A constructors imported directly from their domain modules. Tests MUST NOT import any 2G.A / 2F.A / 2E1 / 2E2 / 2E3 domain symbol; the 2I.C composition layer is decoupled from the upstream record types.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 35)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of `v2.backend.app.composition.replay_backtest_runner` equals `("build_replay_backtest_runner", "ReplayBacktestRunner", "ReplayBacktestRunnerCompositionError")` exactly, including order; assert `build_replay_backtest_runner` is callable; assert `ReplayBacktestRunnerCompositionError` is a class and a subclass of `Exception` and is NOT a subclass of `ValueError`; assert `ReplayBacktestRunner` is exported.

2. `test_errors_invariants.py` — instantiate `ReplayBacktestRunnerCompositionError("some_code", field="some_field")`; assert `e.code == "some_code"`; assert `e.field == "some_field"`; assert `str(e) == "some_code (some_field)"`; assert calling without `field=` raises `TypeError` because `field` is required (no default).

3. `test_replay_backtest_runner_class_invariants.py` — assert `ReplayBacktestRunner.__slots__ == ("assemble_step", "assemble_summary")` exactly, including order; assert `not hasattr(ReplayBacktestRunner, "__dict__")` is False at class scope but `hasattr(instance, "__dict__")` returns False on a constructed instance (confirming slotted-instance discipline); assert attaching a foreign attribute to a constructed instance raises `AttributeError`; assert the class has no class methods or static methods beyond `__init__` (compare against the public method introspection set).

Import-clean tests (each test must reconstruct the forbidden literal at runtime via string concatenation so the test source file does not contain the bare token; each test launches a child interpreter via `subprocess.run([sys.executable, "-c", ...])`):

4. `test_init_module_does_not_load_redis.py` — purge any literal `"red" + "is"` prefixed and `v2.backend.app.composition.replay_backtest_runner*` entries from `sys.modules` in the child interpreter, re-import the package, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

5. `test_init_module_does_not_load_url_env.py` — purge any `v2.backend.app.adapters.redis_v2.url_env*` and `v2.backend.app.composition.replay_backtest_runner*` entries from `sys.modules`, re-import the package, then assert no key containing the literal `"url" + "_env"` is present.

6. `test_init_module_does_not_register_fastapi_lifespan.py` — purge any `"fast" + "api"` prefixed and `v2.backend.app.composition.replay_backtest_runner*` entries from `sys.modules`, re-import the package, then assert no `sys.modules` key starts with `"fast" + "api"`.

7. `test_runtime_module_does_not_load_redis_when_imported.py` — purge any `"red" + "is"` prefixed and `v2.backend.app.composition.replay_backtest_runner.runtime` entries from `sys.modules`, then `import v2.backend.app.composition.replay_backtest_runner.runtime`, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

Forbidden-token scan tests:

8. `test_composition_milestone_forbidden_tokens.py` — read the bytes of `__init__.py`, `errors.py`, `runtime.py`. For each forbidden literal listed in spec 18 'Forbidden tokens in source files', reconstruct the literal at runtime via string concatenation and assert the literal does not appear in any of the three source files. Apply NO exemption. Reconstruction MUST cover `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `sqlite`, `sqlalchemy`, `parquet`, `RISK_DECISION_REASON_DENY_DEFAULT`, the lowercase `deny_default`, the literal `mirror_deny_default`, the four call-form tokens `ReplayBacktestStep(`, `ReplayBacktestSummary(`, `PaperExecutionLedgerEntry(`, `ReplayBacktestRun(`, and the harness framing tokens `BEGIN_FILE` and `END_FILE`.

9. `test_composition_does_not_import_url_env_directly.py` — open `runtime.py` and `__init__.py`, read source, assert neither file source contains the literal `"url" + "_env"` reconstructed at runtime.

Build-time validation tests for `now_ms_clock`:

10. `test_validates_now_ms_clock_callable.py` — call `build_replay_backtest_runner(now_ms_clock=42)` and assert it raises `ReplayBacktestRunnerCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`. Also pass `None` and re-assert the same exception, code, and field. Also pass the string `"not_callable"` and re-assert.

11. `test_returns_replay_backtest_runner_instance.py` — pass `now_ms_clock=lambda: 123` and assert the return value is an instance of `ReplayBacktestRunner`. Assert the returned object's `assemble_step` attribute is callable. Assert the returned object's `assemble_summary` attribute is callable. Assert the returned object's `assemble_step` is not the input clock and `assemble_summary` is not the input clock.

Build-time non-invocation tests:

12. `test_assemble_step_not_invoked_at_build_time.py` — define a counter list `n=[0]` and a clock that increments it. Call `build_replay_backtest_runner(now_ms_clock=...)`. Immediately after, assert `n == [0]` (the clock must NOT be called at build time). Also assert that no `ReplayBacktestStep` was constructed at build time by checking that no step-related side effect occurred.

13. `test_assemble_summary_not_invoked_at_build_time.py` — define a counter list `m=[0]` and a clock that increments it. Call `build_replay_backtest_runner(now_ms_clock=...)`. Immediately after, assert `m == [0]`. Also assert that no `ReplayBacktestSummary` was constructed at build time.

Clock-identity sharing tests:

14. `test_both_closures_share_captured_clock.py` — define a counter clock; build the runner with that clock. Call `runner.assemble_step(...)` once with valid kwargs (inline-constructed `PaperExecutionLedgerEntry` and `ReplayBacktestRun`) and observe the counter increments by exactly 1. Then call `runner.assemble_summary(...)` once with valid kwargs (the inline-constructed `ReplayBacktestRun` and the tuple containing the just-returned `ReplayBacktestStep`); observe the counter increments by exactly 1 more (cumulative 2). Both calls must observe the same captured clock identity.

15. `test_runner_returns_new_callables_not_input_clock.py` — pass `now_ms_clock=lambda x=[0]: x[0]` (a uniquely identifiable lambda); build the runner; assert `runner.assemble_step is not now_ms_clock_lambda` and `runner.assemble_summary is not now_ms_clock_lambda` (the binder MUST return NEW callables, not pass the clock through). Also assert `runner.assemble_step is not runner.assemble_summary` (the two attributes are distinct closures).

Step-assembler forwarding tests (each constructs a counter-equipped clock, builds the runner, calls `runner.assemble_step` once with inline-constructed valid `PaperExecutionLedgerEntry` and `ReplayBacktestRun`, and asserts both behavior and forwarding):

16. `test_assemble_step_invokes_clock_exactly_once_per_call.py` — define a clock with a single-shot counter. Build the runner. Call `runner.assemble_step` once with valid kwargs whose `paper_ledger_entry.ledger_reason_code` is `mirror_allow_proceed_long` (constructed via 2H.A constructor and the `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG` constant). Assert the clock counter incremented to exactly 1, demonstrating the assembler ran exactly once and called the clock exactly once.

17. `test_assemble_step_returns_replay_backtest_step.py` — call `runner.assemble_step` with valid kwargs and assert `isinstance(result, ReplayBacktestStep)` is true (import `ReplayBacktestStep` from `v2.backend.app.domain.replay_backtest_runner`).

18. `test_assemble_step_records_clock_into_step_ts_ms.py` — pass `now_ms_clock=lambda: 1700000000000` (greater than the inline `replay_run.run_started_ts_ms`), call `runner.assemble_step` with valid kwargs, assert `result.step_ts_ms == 1700000000000`.

19. `test_assemble_step_keyword_only_params.py` — call `runner.assemble_step` with one positional argument and assert `TypeError` is raised, demonstrating the inner closure declares both parameters keyword-only.

20. `test_assemble_step_does_not_mutate_supplied_inputs.py` — build with valid build args. Construct a valid `PaperExecutionLedgerEntry` and a valid `ReplayBacktestRun` and snapshot every input lineage field on both records before the call. Call `runner.assemble_step`. After the call, assert each field on both original records is byte-identical to its pre-call value (records are frozen, but the test asserts equality via attribute access on the same object). Also assert the original references are unchanged.

Step mirror-taxonomy mapping tests (one per step-reason branch authored in 2I.B; each constructs an inline-valid `PaperExecutionLedgerEntry` whose `ledger_action` and `ledger_reason_code` match the 2H.A taxonomy and asserts the 2I.B service-layer mirror flows through the runner unchanged):

21. `test_assemble_step_propagates_allow_proceed_long.py` — build the runner with `now_ms_clock=lambda: 2`. Call with a `PaperExecutionLedgerEntry` whose `ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW` and `ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG`. Assert `result.step_action == STEP_ACTION_RECORD_ALLOW` and `result.step_reason_code == STEP_REASON_MIRROR_ALLOW_PROCEED_LONG` and `result.input_paper_action == PAPER_LEDGER_ACTION_RECORD_ALLOW` and `result.input_paper_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG` and `result.live_blocked is True`.

22. `test_assemble_step_propagates_allow_proceed_short.py` — analogous to test 21, with `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT` and `STEP_REASON_MIRROR_ALLOW_PROCEED_SHORT`.

23. `test_assemble_step_propagates_deny_orchestrator_held.py` — analogous, with `PAPER_LEDGER_ACTION_RECORD_DENY` and `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD` mapping to `STEP_ACTION_RECORD_DENY` and `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_HELD`.

24. `test_assemble_step_propagates_deny_orchestrator_abstained.py` — analogous, with `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED` mapping to `STEP_REASON_MIRROR_DENY_ORCHESTRATOR_ABSTAINED`.

25. `test_assemble_step_propagates_deny_default.py` — build the runner with `now_ms_clock=lambda: 3`. Construct an inline `PaperExecutionLedgerEntry` whose `ledger_action == PAPER_LEDGER_ACTION_RECORD_DENY` and whose `ledger_reason_code` is the 2H.A constant `PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT` imported directly from `v2.backend.app.domain.paper_execution_ledger`. The literal lowercase `deny_default` and the literal `mirror_deny_default` MUST be reconstructed at runtime via string concatenation if needed for any assertion message, so the test source file does not contain the bare token. Call `runner.assemble_step` with that entry. Assert `result.step_action == STEP_ACTION_RECORD_DENY` and `result.step_reason_code` equals the 2I.A constant `STEP_REASON_MIRROR_DENY_DEFAULT` imported from `v2.backend.app.domain.replay_backtest_runner` and `result.input_paper_action == PAPER_LEDGER_ACTION_RECORD_DENY` and `result.input_paper_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_DEFAULT` and `result.live_blocked is True`.

Step error propagation tests:

26. `test_assemble_step_propagates_service_error_for_non_paper_entry.py` — build the runner with valid build args; call `runner.assemble_step(paper_ledger_entry="not an entry", replay_run=valid_run)`; assert `ReplayBacktestRunnerServiceError` is raised with `code == "must_be_paper_execution_ledger_entry"` and `field == "paper_ledger_entry"`. Import `ReplayBacktestRunnerServiceError` from `v2.backend.app.services.replay_backtest_runner`. The composition root MUST NOT catch or wrap the service error; the assertion verifies the service error class propagates unchanged.

27. `test_assemble_step_propagates_service_error_for_non_run.py` — build with valid build args; call with `replay_run="not a run"` and a valid `paper_ledger_entry`; assert `ReplayBacktestRunnerServiceError` is raised with `code == "must_be_replay_backtest_run"` and `field == "replay_run"`.

28. `test_assemble_step_propagates_service_error_for_symbol_mismatch.py` — build with `now_ms_clock=lambda: 100`. Construct a `ReplayBacktestRun` whose `symbol == "BTCUSDT"`. Construct a `PaperExecutionLedgerEntry` whose `symbol == "ETHUSDT"`. Call `runner.assemble_step` with the two records; assert `ReplayBacktestRunnerServiceError` is raised with `code == "paper_ledger_entry_symbol_must_match_replay_run_symbol"` and `field == "paper_ledger_entry.symbol"`.

Summary-assembler forwarding tests:

29. `test_assemble_summary_invokes_clock_exactly_once_per_call.py` — define a clock with a single-shot counter. Build the runner. Call `runner.assemble_summary` once with valid kwargs (an inline `ReplayBacktestRun` and an empty `tuple` of steps). Assert the clock counter incremented to exactly 1.

30. `test_assemble_summary_returns_replay_backtest_summary.py` — call `runner.assemble_summary` with valid kwargs and assert `isinstance(result, ReplayBacktestSummary)` is true (import `ReplayBacktestSummary` from `v2.backend.app.domain.replay_backtest_runner`).

31. `test_assemble_summary_records_clock_into_summary_emitted_ts_ms.py` — pass `now_ms_clock=lambda: 1700000000001` (greater than the inline `replay_run.run_started_ts_ms`), call `runner.assemble_summary` with the run and an empty step tuple, assert `result.summary_emitted_ts_ms == 1700000000001`.

32. `test_assemble_summary_keyword_only_params.py` — call `runner.assemble_summary` with one positional argument and assert `TypeError` is raised, demonstrating the inner closure declares both parameters keyword-only.

33. `test_assemble_summary_propagates_service_error_for_non_tuple_steps.py` — build with valid build args; call with `steps=[step]` (a list, not a tuple) and a valid `replay_run`; assert `ReplayBacktestRunnerServiceError` is raised with `code == "must_be_tuple"` and `field == "steps"`.

Cross-closure error/mutation tests:

34. `test_assemble_summary_propagates_service_error_for_step_replay_run_id_mismatch.py` — build with `now_ms_clock=lambda: 100`. Construct a `ReplayBacktestRun` `r1` with `replay_run_id == "rrun_a"`. Construct a `PaperExecutionLedgerEntry` whose `symbol` matches `r1.symbol`. Call `runner.assemble_step` to obtain a `ReplayBacktestStep` `s1` whose `replay_run_id == "rrun_a"`. Construct a SECOND `ReplayBacktestRun` `r2` with `replay_run_id == "rrun_b"` and the SAME symbol. Call `runner.assemble_summary(replay_run=r2, steps=(s1,))`; assert `ReplayBacktestRunnerServiceError` is raised with `code == "step_replay_run_id_must_match_replay_run_id"` and `field == "steps[0].replay_run_id"`.

35. `test_assemble_summary_does_not_mutate_supplied_inputs.py` — build with valid build args. Construct a valid `ReplayBacktestRun` and a valid step tuple (single inline-constructed step). Snapshot every input lineage field before the call. Call `runner.assemble_summary`. After the call, assert each field on the original run and step is byte-identical to its pre-call value. Also assert the original `replay_run` and `steps` references are unchanged. Also assert the `steps` tuple object identity is preserved.

## Inline fakes

Test files MUST construct hand-written fakes inline (a tiny callable returning a fixed int or sequence of ints; a hand-built `PaperExecutionLedgerEntry`, `ReplayBacktestRun`, and `ReplayBacktestStep` per the 2H.A and 2I.A constructor surfaces). No `unittest.mock`. No third-party fakes. No shared helper module. No conftest. Tests MUST NOT import any 2G.A `RiskDecisionRecord` or 2F.A `OrchestratorDecisionRecord` or any 2E1 / 2E2 / 2E3 record symbol; the 2I.C composition tests are decoupled from upstream domain types and only depend on the 2H.A `PaperExecutionLedgerEntry`, the 2I.A run / step / summary value objects, and the 2I.A / 2H.A constant exports.

## Test runner expectations

`.venv/bin/python -m pytest v2/backend/tests/unit/composition/replay_backtest_runner/ -q` must report `35 passed` with zero failures and zero errors. The 2I.B service suite (`v2/backend/tests/unit/services/replay_backtest_runner/`), the 2I.A domain suite (`v2/backend/tests/unit/domain/replay_backtest_runner/`), the 2H.C composition suite (`v2/backend/tests/unit/composition/paper_execution_ledger/`), the 2H.B service suite (`v2/backend/tests/unit/services/paper_execution_ledger/`), the 2H.A domain suite (`v2/backend/tests/unit/domain/paper_execution_ledger/`), the 2G.C composition suite (`v2/backend/tests/unit/composition/risk_gateway/`), the 2G.B service suite (`v2/backend/tests/unit/services/risk_gateway/`), the 2G.A domain suite (`v2/backend/tests/unit/domain/risk_gateway/`), the 2F.C composition suite (`v2/backend/tests/unit/composition/orchestrator_decision/`), the 2F.B service suite (`v2/backend/tests/unit/services/orchestrator_decision/`), the 2F.A domain suite (`v2/backend/tests/unit/domain/orchestrator_decision/`), the 2E3.C composition suite (`v2/backend/tests/unit/composition/trainer_prediction_output/`), the 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), the 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), the 2E2.C composition suite (`v2/backend/tests/unit/composition/trainer_worker_health/`), the 2E2.B service suite (`v2/backend/tests/unit/services/trainer_worker_health/`), the 2E2.A domain suite (`v2/backend/tests/unit/domain/trainer_worker_health/`), the 2E1.E composition suite (`v2/backend/tests/unit/composition/trainer_parity/`), the 2E1.D service suite (`v2/backend/tests/unit/services/trainer_parity/`), and the 2E1 trainer_liveness domain suite (`v2/backend/tests/unit/domain/trainer_liveness/`) must continue to pass with zero regressions when run individually.

PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_TEST_PLAN_READY
