# Phase 2R — Test Plan

## Test module

A single pytest module is authored at `v2/backend/tests/unit/decision_explainability_data_contract/test_decision_explainability_data_contract.py`. The module imports the fixture pack and the harness from the sibling `fixtures` and `harness` modules. The module does NOT import any test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`.

## Required pytest cases (16 total)

1. `test_harness_paper_mode_flag_live_blocked_invariant`. The single `PaperModeFlag` returned at the harness level has `live_blocked is True` and `mode in {"paper", "live_blocked"}`.

2. `test_fixture_input_count_equals_twelve`. The fixture pack returns exactly 12 typed `DecisionExplainabilityFixtureInput` rows in the scenario / step order specified by `02_TYPED_INPUT_FIXTURE_SPEC.md`.

3. `test_envelope_count_equals_twelve`. The harness result `envelopes` tuple has exactly 12 typed `DecisionExplainabilityEnvelope` rows.

4. `test_envelope_lineage_carry_over`. For each `(input_row, envelope)` pair, the envelope's `feature_snapshot_id`, `prediction_id`, `decision_id`, and `risk_decision_id` equal the corresponding fields on `input_row.risk_decision_record`.

5. `test_envelope_action_reason_mirror`. For each `(input_row, envelope)` pair, the envelope's `input_decision_action`, `input_decision_reason_code`, `risk_action`, and `risk_reason_code` equal the corresponding fields on `input_row.risk_decision_record`.

6. `test_envelope_per_row_paper_mode_flag_mirror`. For each envelope, `paper_mode_live_blocked is True` and `paper_mode_mode == harness_result.paper_mode_flag.mode`.

7. `test_envelope_decision_ts_ms_mirror`. For each `(input_row, envelope)` pair, the envelope's `risk_decision_ts_ms` equals `input_row.risk_decision_record.risk_decision_ts_ms`.

8. `test_envelope_risk_live_blocked_mirror`. For each `(input_row, envelope)` pair, the envelope's `risk_live_blocked` equals `input_row.risk_decision_record.live_blocked`, which equals `True`.

9. `test_envelope_legacy_evidence_pointer_is_string_not_path`. For each envelope, `legacy_evidence_pointer` is an instance of `str` and the test does NOT call `pathlib.Path(...)` on the value, does NOT call `open(...)` on the value, and does NOT call any read helper. Verified by absence of `pathlib`, `open`, and `Path` references in the test module body via the forbidden-token AST scan helper.

10. `test_envelope_lab_scenario_pointer_literal_match`. For each envelope whose `source_scenario_slug == "decision_explainability_pack_lab_loser_short"`, `legacy_evidence_pointer == f"legacy_evidence__decision_explainability__lab_hedge_unwind_squeeze__step_{envelope.step_index}"`.

11. `test_envelope_source_scenario_slug_namespacing`. For each envelope, `source_scenario_slug` starts with the literal prefix `decision_explainability_` and equals one of the four scenario slugs declared in `02_TYPED_INPUT_FIXTURE_SPEC.md`.

12. `test_envelope_step_index_one_based`. For each envelope, `step_index in {1, 2, 3}`.

13. `test_envelope_symbols_are_uppercase_binance_usdm`. For each envelope, `symbol in {"BTCUSDT", "ETHUSDT", "LABUSDT", "SOLUSDT"}` and `symbol == symbol.upper()`.

14. `test_no_forbidden_lineage_or_market_fields`. None of the typed records (`DecisionExplainabilityFixtureInput`, `DecisionExplainabilityEnvelope`, `DecisionExplainabilityHarnessResult`) carries a `shadow_decision_id`, `execution_intent_id`, `paper_trade_id` (beyond fields carried by `RiskDecisionRecord` itself), or any of `pnl`, `quantity`, `price`, `fees`, `slippage`, `funding_rate`, `open_interest`, `liquidation_cluster`, `orderbook_depth`, `hedge_state`, `residual_exposure`, `squeeze_risk`, `top_positive_feature_contributors`, `top_negative_feature_contributors`, `feature_freshness_flags`, `stale_missing_unused_feature_flags`, `confidence`, `previous_confidence`, `confidence_delta`, `confidence_calibration`, `model_version`, `checkpoint_version`, `regime_context`, `position_sizing_reason`, `risk_check_list`, `blocked_trade_reason`, `paper_shadow_legacy_comparison`, or `audit_timeline` field. Verified by introspecting the `__dataclass_fields__` of each typed record class.

15. `test_harness_paper_mode_flag_is_singleton_identity`. The `harness_result.paper_mode_flag` is the same `PaperModeFlag` instance carried (by mirror, not by reference) into each envelope's `paper_mode_live_blocked` and `paper_mode_mode` fields. Identity is asserted at the `PaperModeFlag` level (the harness produces exactly one `PaperModeFlag` instance and reuses its `live_blocked` / `mode` attributes for every envelope mirror).

16. `test_no_forbidden_tokens_in_authored_files`. A forbidden-token scan returns zero matches for: `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open(`, `pathlib.Path`, `requests`, `httpx`, `urllib`, `socket`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`, `torch`, `numpy`, `pandas`, `scikit-learn`, `mock(`, `patch(`, `monkeypatch`, `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`, the literal string `BEGIN` followed by `_FILE`, and the literal string `END` followed by `_FILE`. The scan is implemented by reading the dunder `__file__` attribute of each module and using `inspect.getsource(module)` to obtain the source text deterministically. The scan does NOT call `open`, `pathlib`, or any external file-system helper. (`inspect.getsource` is the only allowed source-introspection helper for the forbidden-token scan; `linecache`, `pkgutil.get_data`, and any other source-fetch helper are forbidden.)

## Validation command

`python -m pytest v2/backend/tests/unit/decision_explainability_data_contract/test_decision_explainability_data_contract.py -v --no-header`. Expected outcome: 16 passed in under 1.0 seconds.

## Forbidden-import scan

The pytest module additionally asserts via an `import` AST walk that the harness module's import set is restricted to:

- `dataclasses` (stdlib).
- `typing` / `collections.abc` (stdlib).
- `inspect` (stdlib, only inside the forbidden-token-scan helper).
- `v2.backend.app.domain.risk_gateway` (typed surface).
- `v2.backend.app.domain.paper_mode.flag` (typed surface).
- `v2.backend.app.composition.paper_mode.runtime` (composition root).
- the sibling test-package modules (`fixtures`).

Any other top-level module import is a test failure.

PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_TEST_PLAN_READY
