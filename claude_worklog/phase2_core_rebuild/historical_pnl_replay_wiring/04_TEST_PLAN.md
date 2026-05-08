# Phase 2P — Test Plan

## Pytest module

The pytest module `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py` exercises the `replay_historical_pnl_evidence_pack` harness end-to-end against the deterministic four-scenario evidence pack defined in `02_TYPED_INPUT_FIXTURE_SPEC.md`.

## Required test cases

The pytest module declares (at minimum) the following test functions:

1. `test_harness_emits_paper_mode_flag_with_live_blocked_true_and_mode_in_allowed_set` — asserts the `PaperModeFlag` returned by the harness has `live_blocked is True` and `mode in {"paper", "live_blocked"}`.
2. `test_harness_emits_one_trio_per_scenario_in_input_order` — asserts `len(trios) == 4` and `[trio.scenario_slug for trio in trios] == ["historical_pnl_pack_btc_winner_long", "historical_pnl_pack_eth_winner_short", "historical_pnl_pack_lab_loser_short", "historical_pnl_pack_sol_orchestrator_held"]`.
3. `test_each_trio_has_three_comparison_records` — asserts `all(len(trio.comparisons) == 3 for trio in trios)` and total comparison-record count is 12.
4. `test_each_comparison_carries_lineage_from_input_risk_decision_record` — asserts every produced `PaperExecutionLedgerEntry` carries the `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol` of the corresponding input `RiskDecisionRecord`.
5. `test_each_comparison_pointer_matches_input_pointer` — asserts every produced `HistoricalPnLReplayComparisonRecord.legacy_realized_trade_evidence_pointer == input.legacy_realized_trade_evidence_pointer`.
6. `test_lab_loser_scenario_uses_lab_hedge_unwind_pointer_literal` — asserts the LAB scenario's per-step pointer matches the literal `"legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_N"` for `N in {1, 2, 3}`.
7. `test_live_blocked_is_true_on_every_paper_execution_ledger_entry` — asserts `comparison.v2_paper_execution_ledger_entry.live_blocked is True` for every produced comparison record.
8. `test_input_risk_action_and_reason_carry_into_paper_execution_ledger_entry` — asserts `comparison.v2_paper_execution_ledger_entry.input_risk_action == input.risk_decision_record.action` and `comparison.v2_paper_execution_ledger_entry.input_risk_reason_code == input.risk_decision_record.reason_code` for every produced comparison record.
9. `test_evidence_run_symbol_matches_per_step_risk_decision_record_symbol` — asserts every input `risk_decision_record.symbol` matches its scenario's `evidence_run.symbol`.
10. `test_harness_does_not_emit_shadow_decision_id_or_execution_intent_id_or_paper_trade_id_lineage_row` — asserts no field on any produced typed record is named `shadow_decision_id` or `execution_intent_id`, and the only `paper_trade_id` field present is the existing one on `PaperExecutionLedgerEntry` (carried by the existing composition root, not introduced by Phase 2P).
11. `test_harness_does_not_introduce_pnl_or_size_or_price_or_fees_or_funding_field` — asserts no field on any produced typed record is named `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, `funding`, `oi`, `liquidation`, `orderbook`, `hedge_state`, `residual_exposure`, or `squeeze_risk`.
12. `test_harness_propagates_paper_mode_runtime_composition_error_unchanged` — asserts that injecting a non-callable clock into `paper_mode_clock` raises `PaperModeRuntimeCompositionError` propagated unchanged from `build_paper_mode_runtime`.
13. `test_harness_propagates_paper_execution_ledger_composition_error_unchanged` — asserts that injecting a non-callable clock into `ledger_clock` raises `PaperExecutionLedgerCompositionError` propagated unchanged from `build_paper_execution_ledger_recorder`.

Additional invariant assertions may be added by the implementer; no assertion may rely on `mock`, `patch`, or `monkeypatch` against any of `build_paper_mode_runtime`, `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `assemble_paper_mode_flag`, or any of their dependencies.

## Forbidden in tests

- No wall-clock helper invocation (`time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`).
- No file I/O (`open`, `pathlib.Path.read_text`, `pathlib.Path.write_text`).
- No environment-variable reader (`os.environ`, `os.getenv`).
- No network client (`socket`, `requests`, `httpx`, `urllib`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`).
- No heavyweight numerics / ML library (`torch`, `numpy`, `pandas`, `scikit-learn`).
- No Binance read-only account-history endpoint invocation.
- No `mock`, `patch`, or `monkeypatch` use against `build_paper_mode_runtime`, `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `assemble_paper_mode_flag`, `build_risk_decision_evaluator`, or `assemble_risk_decision_record`.
- No flip of the live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- No standalone harness framing token marker (`BEGIN_FILE` or `END_FILE`) line in any test file body.

## Pytest invocation

Validation runs:

```
python -m pytest v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py -v --no-header
```

All declared test cases must pass. No skipped tests are allowed.

PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_TEST_PLAN_READY
