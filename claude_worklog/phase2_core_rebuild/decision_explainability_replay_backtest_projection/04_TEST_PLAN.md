# Phase 2T — Test Plan

## Test module location

`v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py`

## Required pytest functions (10 total)

### 1. `test_harness_returns_frozen_result_with_12_steps_and_4_summaries`

- Invokes `run_replay_backtest_projection_harness()`.
- Asserts result is an instance of `ReplayBacktestProjectionHarnessResult`.
- Asserts `len(result.step_envelopes) == 12`.
- Asserts `len(result.summary_envelopes) == 4`.
- Asserts both tuples are immutable (`tuple` type).

### 2. `test_per_row_lineage_carry_over`

- For each `step_envelope` and corresponding fixture input row:
  - `step_envelope.risk_decision_id == fixture_input.risk_decision_id`.
  - `step_envelope.decision_id == fixture_input.decision_id`.
  - `step_envelope.prediction_id == fixture_input.prediction_id`.
  - `step_envelope.feature_snapshot_id == fixture_input.feature_snapshot_id`.
- Asserts `step_envelope.paper_trade_id` starts with `pt_` and equals `pt_` + `risk_decision_id`.
- Asserts `step_envelope.replay_step_id` and `step_envelope.replay_run_id` are non-empty strings.

### 3. `test_per_row_action_reason_mirror_per_scenario`

- BTC scenario steps: `step_action == "ALLOW"`, `step_reason_code == "PROCEED_LONG"`, `input_paper_action == "ALLOW"`, `input_paper_reason_code == "RISK_OK"`.
- ETH scenario steps: `step_action == "ALLOW"`, `step_reason_code == "PROCEED_SHORT"`, `input_paper_action == "ALLOW"`, `input_paper_reason_code == "RISK_OK"`.
- LAB scenario steps: `step_action == "ALLOW"`, `step_reason_code == "PROCEED_SHORT"`, `input_paper_action == "ALLOW"`, `input_paper_reason_code == "RISK_OK"`.
- SOL scenario steps: `step_action == "DENY"`, `step_reason_code == "ORCHESTRATOR_HELD"`, `input_paper_action == "DENY"`, `input_paper_reason_code == "ORCHESTRATOR_HELD"`.

### 4. `test_per_row_symbol_mirror_per_scenario`

- BTC scenario steps: `symbol == "BTCUSDT"`.
- ETH scenario steps: `symbol == "ETHUSDT"`.
- LAB scenario steps: `symbol == "LABUSDT"`.
- SOL scenario steps: `symbol == "SOLUSDT"`.

### 5. `test_per_row_step_ts_ms_strictly_monotonic_and_within_replay_clock_window`

- All 12 `step_envelope.step_ts_ms` values are strictly increasing across the harness invocation order.
- The first `step_ts_ms` equals `REPLAY_CLOCK_START_MS`.
- The last `step_ts_ms` is at most `REPLAY_CLOCK_START_MS + 15 * 23` (12 step + 4 summary clock calls bound).
- Every `step_ts_ms` is a positive `int`, not `bool`.

### 6. `test_summary_partition_counts_match_per_scenario_action_reason_distribution`

- For each summary envelope:
  - `total_steps_count == 3`.
  - `live_blocked is True`.
- BTC summary: `record_allow_steps_count == 3`, `mirror_allow_proceed_long_steps_count == 3`, all other partition counts == 0.
- ETH summary: `record_allow_steps_count == 3`, `mirror_allow_proceed_short_steps_count == 3`, all other partition counts == 0.
- LAB summary: `record_allow_steps_count == 3`, `mirror_allow_proceed_short_steps_count == 3`, all other partition counts == 0.
- SOL summary: `record_deny_steps_count == 3`, `mirror_deny_orchestrator_held_steps_count == 3`, all other partition counts == 0.

### 7. `test_lab_scenario_legacy_evidence_pointer_literal`

- Asserts that all 3 LAB step envelopes carry `legacy_evidence_pointer` matching the regex `^legacy_evidence__replay_step_explainability__lab_hedge_unwind_squeeze__step_[0-2]$`.
- Asserts that the LAB summary envelope carries `legacy_evidence_pointer == "legacy_evidence__replay_step_explainability__lab_hedge_unwind_squeeze__summary"`.
- Asserts that the LAB-scenario `step_index` values are `{0, 1, 2}` (set equality).

### 8. `test_envelope_allowed_fields_only`

- For `ReplayBacktestStepExplainabilityEnvelope`, asserts `dataclasses.fields(...)` returns exactly 17 fields with the names listed in `02_TYPED_INPUT_FIXTURE_SPEC.md`.
- For `ReplayBacktestSummaryExplainabilityEnvelope`, asserts `dataclasses.fields(...)` returns exactly 14 fields with the names listed in `02_TYPED_INPUT_FIXTURE_SPEC.md`.
- Asserts `__slots__` is not set (frozen dataclass) and `frozen=True` is set.
- Asserts the dataclasses do not declare any field named `pnl`, `quantity`, `price`, `fee`, `funding`, `oi`, `liquidation_distance`, `orderbook_depth`, `hedge_state`, `residual_exposure`, `squeeze_score`, `confidence`, `top_positive_feature_contributors`, `top_negative_feature_contributors`, `feature_freshness_flags`, `regime_context`, `model_version`, `checkpoint_version`, `position_sizing_reason`, `risk_check_list`, `blocked_trade_reason`, `paper_shadow_legacy_comparison`, `audit_timeline`, `shadow_decision_id`, or `execution_intent_id`.

### 9. `test_replay_clock_and_paper_ledger_clock_factory_determinism`

- Invokes `run_replay_backtest_projection_harness()` twice.
- Asserts both invocations return result objects whose `step_envelopes` and `summary_envelopes` tuples are equal (field-by-field, all 12+4 rows).
- Confirms factory closures isolate state between invocations (no global counter leakage).

### 10. `test_forbidden_token_and_forbidden_import_scan`

- Reads `harness.py` and `fixtures.py` source files (via `inspect.getsource(...)` only; no `open()`).
- Asserts no occurrence of any of the following tokens (case-sensitive substring match on the rendered source string):
  - `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`.
  - `os.environ`, `os.getenv`, `os.path`, `pathlib`, `Path(`.
  - `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`.
  - `socket`, `requests`, `httpx`, `urllib`.
  - `torch`, `numpy`, `pandas`, `scikit-learn`, `sklearn`.
  - `mock(`, `Mock(`, `MagicMock(`, `patch(`, `monkeypatch`, `mocker`.
  - `pnl`, `quantity`, `price`, `fee`, `funding`, `oi_`, `liquidation`, `orderbook`, `hedge_state`, `residual_exposure`, `squeeze`.
  - `confidence`, `top_positive`, `top_negative`, `feature_freshness`, `regime_context`, `model_version`, `checkpoint_version`, `position_sizing`, `risk_check_list`, `blocked_trade_reason`, `paper_shadow_legacy_comparison`, `audit_timeline`, `shadow_decision_id`, `execution_intent_id`.
  - `assemble_paper_execution_ledger_entry(`, `assemble_replay_backtest_step(`, `assemble_replay_backtest_summary(` (must invoke closures, not direct service callables).
  - `build_paper_mode_runtime`, `assemble_paper_mode_flag`, `build_risk_decision_evaluator`, `assemble_risk_decision_record`, `build_orchestrator_decision_router`.
- Asserts no `import` line names any test module from `v2/backend/tests/unit/decision_explainability_data_contract/`, `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/`, `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`.

## Acceptance

All 10 pytest functions must pass under `.venv/bin/python -m pytest v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py -v --no-header`.

PHASE2T_TEST_PLAN_READY
