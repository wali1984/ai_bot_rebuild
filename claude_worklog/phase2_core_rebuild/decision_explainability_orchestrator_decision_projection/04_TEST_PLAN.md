# Phase 2U — Test Plan

## Test module location

`v2/backend/tests/unit/decision_explainability_orchestrator_decision_projection/test_decision_explainability_orchestrator_decision_projection.py`

## Required pytest functions (11 total)

### 1. `test_harness_returns_frozen_result_with_12_envelopes_and_12_decision_records`

- Invokes `run_orchestrator_decision_projection_harness()`.
- Asserts result is an instance of `OrchestratorDecisionProjectionHarnessResult`.
- Asserts `len(result.envelopes) == 12`.
- Asserts `len(result.decision_records) == 12`.
- Asserts both attributes are `tuple` instances (immutable).
- Asserts the result class is a frozen dataclass with `slots=True`.

### 2. `test_per_row_lineage_carry_over`

- For each `envelope` and corresponding `fixture_input`, the produced `decision_record`, and the constructed `TrainerPredictionRecord`:
  - `envelope.prediction_id == decision_record.prediction_id == trainer_prediction.prediction_id == fixture_input.prediction_id`.
  - `envelope.feature_snapshot_id == decision_record.feature_snapshot_id == trainer_prediction.feature_snapshot_id == fixture_input.feature_snapshot_id`.
  - `envelope.decision_id == decision_record.decision_id`.
  - `envelope.decision_id` is a non-empty `str` of length ≤ 128 with no whitespace.

### 3. `test_per_row_action_reason_mirror_per_scenario`

- BTC scenario rows: `decision_action == "open_long"`, `decision_reason_code == "proceed_long"`.
- ETH scenario rows: `decision_action == "open_short"`, `decision_reason_code == "proceed_short"`.
- LAB scenario rows: `decision_action == "open_short"`, `decision_reason_code == "proceed_short"`.
- SOL scenario rows: `decision_action == "abstain"`, `decision_reason_code == "abstain_low_confidence"`.

### 4. `test_per_row_symbol_mirror_per_scenario`

- BTC rows: `symbol == "BTCUSDT"`.
- ETH rows: `symbol == "ETHUSDT"`.
- LAB rows: `symbol == "LABUSDT"`.
- SOL rows: `symbol == "SOLUSDT"`.

### 5. `test_per_row_input_prediction_field_mirror_per_scenario`

- BTC rows: `input_prediction_direction == "long"`, `input_prediction_confidence_calibrated == 0.85`, `input_prediction_freshness_flag == "fresh"`, `input_worker_health_status == "HEALTHY"`.
- ETH rows: `input_prediction_direction == "short"`, `input_prediction_confidence_calibrated == 0.82`, `input_prediction_freshness_flag == "fresh"`, `input_worker_health_status == "HEALTHY"`.
- LAB rows: `input_prediction_direction == "short"`, `input_prediction_confidence_calibrated == 0.83`, `input_prediction_freshness_flag == "fresh"`, `input_worker_health_status == "HEALTHY"`.
- SOL rows: `input_prediction_direction == "long"`, `input_prediction_confidence_calibrated == 0.40`, `input_prediction_freshness_flag == "fresh"`, `input_worker_health_status == "HEALTHY"`.
- For every row: `isinstance(envelope.input_prediction_confidence_calibrated, float)` and `not isinstance(envelope.input_prediction_confidence_calibrated, bool)`.

### 6. `test_per_row_decision_ts_ms_strictly_monotonic_within_orchestrator_clock_window`

- All 12 `envelope.decision_ts_ms` values are strictly increasing across the harness invocation order.
- The first `decision_ts_ms` equals `ORCHESTRATOR_CLOCK_START_MS`.
- The last `decision_ts_ms` is at most `ORCHESTRATOR_CLOCK_START_MS + 17 * 11`.
- Every `decision_ts_ms` is a positive `int`, not `bool`.

### 7. `test_per_row_live_blocked_invariant_true`

- For every envelope and every decision_record: `live_blocked is True`.
- For every envelope: `isinstance(envelope.live_blocked, bool)`.

### 8. `test_lab_scenario_legacy_evidence_pointer_literal`

- Asserts that all 3 LAB row envelopes carry `legacy_evidence_pointer` matching the regex `^legacy_evidence__orchestrator_decision_explainability__lab_hedge_unwind_squeeze__step_[0-2]$`.
- Asserts that the LAB-scenario `step_index` values are `{0, 1, 2}` (set equality).
- Asserts that LAB envelopes carry `symbol == "LABUSDT"` and `decision_action == "open_short"`.

### 9. `test_envelope_allowed_fields_only`

- Asserts `dataclasses.fields(OrchestratorDecisionExplainabilityEnvelope)` returns exactly 15 fields with the names listed in `02_TYPED_INPUT_FIXTURE_SPEC.md`.
- Asserts the dataclass is `frozen=True` and uses `slots=True` (`__slots__` is set on the class).
- Asserts the dataclass does not declare any field named `risk_decision_id`, `paper_trade_id`, `replay_step_id`, `replay_run_id`, `replay_summary_id`, `shadow_decision_id`, `execution_intent_id`, `pnl`, `quantity`, `price`, `fee`, `funding`, `oi`, `liquidation_distance`, `orderbook_depth`, `hedge_state`, `residual_exposure`, `squeeze_score`, `top_positive_feature_codes`, `top_negative_feature_codes`, `feature_freshness_flags`, `regime_context`, `model_version`, `checkpoint_id`, `confidence_raw`, `previous_confidence`, `confidence_delta`, `confidence_calibration`, `position_sizing_reason`, `risk_check_list`, `blocked_trade_reason`, `paper_shadow_legacy_comparison`, or `audit_timeline`.

### 10. `test_evaluator_build_once_factory_determinism`

- Invokes `run_orchestrator_decision_projection_harness()` twice.
- Asserts both invocations return result objects whose `envelopes` and `decision_records` tuples are equal (field-by-field, all 12 rows).
- Confirms factory closures isolate state between invocations (no global counter leakage; each invocation builds its own evaluator).

### 11. `test_forbidden_token_and_forbidden_import_scan`

- Reads `harness.py` and `fixtures.py` source files (via `inspect.getsource(...)` only; no `open()`, no `pathlib.Path.read_text(...)`).
- Asserts no occurrence of any of the following tokens (case-sensitive substring match on the rendered source string):
  - `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`.
  - `os.environ`, `os.getenv`, `os.path`, `pathlib`, `Path(`.
  - `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`.
  - `socket`, `requests`, `httpx`, `urllib`.
  - `torch`, `numpy`, `pandas`, `scikit-learn`, `sklearn`.
  - `mock(`, `Mock(`, `MagicMock(`, `patch(`, `monkeypatch`, `mocker`.
  - `pnl`, `quantity`, `price`, `fee`, `funding`, `oi_`, `liquidation`, `orderbook`, `hedge_state`, `residual_exposure`, `squeeze`.
  - `previous_confidence`, `confidence_delta`, `confidence_calibration`, `top_positive`, `top_negative_feature_contributors`, `feature_freshness`, `regime_context`, `model_version_change`, `checkpoint_version`, `position_sizing`, `risk_check_list`, `blocked_trade_reason`, `paper_shadow_legacy_comparison`, `audit_timeline`, `shadow_decision_id`, `execution_intent_id`, `risk_decision_id`, `paper_trade_id`, `replay_step_id`, `replay_run_id`, `replay_summary_id`.
  - `assemble_orchestrator_decision_record(`, `assemble_paper_mode_flag(`, `assemble_risk_decision_record(`, `assemble_paper_execution_ledger_entry(`, `assemble_replay_backtest_step(`, `assemble_replay_backtest_summary(` (must invoke evaluator closures, not direct service callables).
  - `build_paper_mode_runtime`, `build_risk_decision_evaluator`, `build_paper_execution_ledger_recorder`, `build_replay_backtest_runner`, `build_shadow_mode_readiness_runtime`.
- Asserts no `import` line names any test module from `v2/backend/tests/unit/decision_explainability_data_contract/`, `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/`, `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/`, `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`.

## Acceptance

All 11 pytest functions must pass under `.venv/bin/python -m pytest v2/backend/tests/unit/decision_explainability_orchestrator_decision_projection/test_decision_explainability_orchestrator_decision_projection.py -v --no-header`.

PHASE2U_TEST_PLAN_READY
