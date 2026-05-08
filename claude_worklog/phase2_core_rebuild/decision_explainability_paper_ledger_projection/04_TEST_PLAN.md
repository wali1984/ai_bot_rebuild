# Phase 2S — Test Plan

## Test module

The Phase 2S test module is authored at `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/test_decision_explainability_paper_ledger_projection.py`. The module imports:

- `PaperLedgerExplainabilityFixtureInput`, `build_paper_ledger_explainability_fixture_inputs`, `PAPER_LEDGER_CLOCK_START_MS`, `BASE_TS_MS`, scenario slug constants, and `build_paper_ledger_clock` from the Phase 2S fixture module;
- `PaperLedgerExplainabilityEnvelope`, `PaperLedgerExplainabilityHarnessResult`, and `decision_explainability_paper_ledger_projection_harness` from the Phase 2S harness module;
- `PaperExecutionLedgerEntry`, `PAPER_LEDGER_ACTION_RECORD_ALLOW`, `PAPER_LEDGER_ACTION_RECORD_DENY`, `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG`, `PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT`, `PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD` from `v2.backend.app.domain.paper_execution_ledger`;
- `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway`.

No other import is required.

## Required pytest cases

The test module asserts at least the following invariants. Every assertion compares typed surface values directly without normalization or transformation.

1. **Harness result shape**: `result = decision_explainability_paper_ledger_projection_harness(build_paper_ledger_explainability_fixture_inputs())` returns a `PaperLedgerExplainabilityHarnessResult` whose `envelopes` and `ledger_entries` tuples each have length 12 and matching positional order.

2. **Per-row lineage carry-over**: For each index `i`, `envelopes[i].paper_trade_id == ledger_entries[i].paper_trade_id`, `envelopes[i].risk_decision_id == ledger_entries[i].risk_decision_id`, `envelopes[i].decision_id == ledger_entries[i].decision_id`, `envelopes[i].prediction_id == ledger_entries[i].prediction_id`, `envelopes[i].feature_snapshot_id == ledger_entries[i].feature_snapshot_id`.

3. **Per-row symbol mirror**: For each index `i`, `envelopes[i].symbol == ledger_entries[i].symbol`.

4. **Per-row ledger-side action / reason mirror**: For each index `i`, `envelopes[i].ledger_action == ledger_entries[i].ledger_action`, `envelopes[i].ledger_reason_code == ledger_entries[i].ledger_reason_code`.

5. **Per-row input-side risk action / reason mirror**: For each index `i`, `envelopes[i].input_risk_action == ledger_entries[i].input_risk_action`, `envelopes[i].input_risk_reason_code == ledger_entries[i].input_risk_reason_code`.

6. **Per-row `live_blocked` invariant**: For each index `i`, `envelopes[i].live_blocked is True` and `ledger_entries[i].live_blocked is True`.

7. **`paper_trade_id` derivation invariant**: For each index `i`, `envelopes[i].paper_trade_id == "pt_" + envelopes[i].risk_decision_id`.

8. **Per-row `ledger_entry_ts_ms` mirror and strictly-increasing harness clock**: For each index `i`, `envelopes[i].ledger_entry_ts_ms == ledger_entries[i].ledger_entry_ts_ms == PAPER_LEDGER_CLOCK_START_MS + i * 19`. The 12 `ledger_entry_ts_ms` values are strictly increasing.

9. **Per-row `risk_decision_ts_ms` mirror on the input-side `RiskDecisionRecord`**: For each input row `inputs[i]`, `inputs[i].risk_decision_record.risk_decision_ts_ms == BASE_TS_MS + scenario_index * 60_000 + step_ordinal * 100` where `scenario_index = i // 3` and `step_ordinal = (i % 3) + 1`.

10. **Per-scenario ledger-side reason code**: For the BTC winner-long scenario steps (indices 0..2), `envelopes[i].ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_LONG` and `envelopes[i].ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW`. For the ETH winner-short scenario steps (indices 3..5), `envelopes[i].ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT` and `envelopes[i].ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW`. For the LAB loser-short scenario steps (indices 6..8), `envelopes[i].ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_ALLOW_PROCEED_SHORT` and `envelopes[i].ledger_action == PAPER_LEDGER_ACTION_RECORD_ALLOW`. For the SOL orchestrator-held scenario steps (indices 9..11), `envelopes[i].ledger_reason_code == PAPER_LEDGER_REASON_MIRROR_DENY_ORCHESTRATOR_HELD` and `envelopes[i].ledger_action == PAPER_LEDGER_ACTION_RECORD_DENY`.

11. **LAB-scenario pointer literal**: For each index `i` in the LAB-scenario range (6..8), `envelopes[i].legacy_evidence_pointer.startswith("legacy_evidence__paper_ledger_explainability__lab_hedge_unwind_squeeze__step_")` and `envelopes[i].source_scenario_slug == "paper_ledger_explainability_pack_lab_loser_short"`. The pointer is asserted only as a string literal; the test never opens, reads, or writes it as a filesystem path.

12. **Slug namespacing**: For each index `i`, `envelopes[i].source_scenario_slug` is one of the four scenario slug constants exposed by the fixture module, with `i // 3` selecting the slug. No other slug appears.

13. **Step-index range**: For each index `i`, `envelopes[i].step_index` is in `{1, 2, 3}` and equals `(i % 3) + 1`.

14. **Symbol-set restriction**: The set of distinct symbols across all 12 envelopes equals exactly `{"BTCUSDT", "ETHUSDT", "LABUSDT", "SOLUSDT"}`.

15. **Forbidden-field absence**: The set of `dataclasses.fields(PaperLedgerExplainabilityEnvelope)` field names equals exactly the 15-name set listed in `03_HARNESS_PIPELINE_SPEC.md`. No `top_positive_feature_contributors`, `top_negative_feature_contributors`, `feature_freshness_flags`, `stale_missing_unused_feature_flags`, `confidence`, `previous_confidence`, `confidence_delta`, `confidence_calibration`, `model_version`, `checkpoint_version`, `regime_context`, `position_sizing_reason`, `risk_check_list`, `blocked_trade_reason`, `paper_shadow_legacy_comparison`, `audit_timeline`, `shadow_decision_id`, or `execution_intent_id` field appears.

16. **Persistence absence**: The harness module source text contains no occurrence of `open(`, `pathlib`, `sqlite3`, `redis`, `requests`, `httpx`, `socket`, `urllib`, `json.dump`, `json.load`, `pickle`, `csv.writer`, or `csv.reader`.

17. **Recorder-build-once invariant**: The harness module source text contains exactly one call to `build_paper_execution_ledger_recorder`. The harness invokes the recorder closure exactly 12 times (once per fixture row).

18. **Forbidden-token scan**: The harness, fixture, and test module source text contain no standalone framing-token marker line (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line.

19. **Forbidden-import scan**: The harness, fixture, and test module source text contain no `import` of `time`, `datetime`, `os.environ`, `os.getenv`, `socket`, `requests`, `httpx`, `urllib`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`, `torch`, `numpy`, `pandas`, or `scikit-learn`.

20. **Other-test-module-import absence**: The harness, fixture, and test module source text contain no `from v2.backend.tests.unit.decision_explainability_data_contract`, `from v2.backend.tests.unit.paper_mode_evidence_collection_harness`, `from v2.backend.tests.unit.shadow_mode_evidence_collection_harness`, `from v2.backend.tests.unit.historical_pnl_replay_wiring`, or `from v2.backend.tests.unit.aggregate_evidence_rollup_harness` import.

21. **Composition-root-import restriction**: The harness module source text imports exactly one composition-root symbol, `build_paper_execution_ledger_recorder`, from `v2.backend.app.composition.paper_execution_ledger.runtime`. No other composition-root symbol is imported.

## Forbidden in tests

The test module must NOT:

- introduce any wall-clock helper, file I/O helper, network client, environment-variable reader, or heavyweight numerics / ML import;
- mock, patch, or monkeypatch `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_mode_runtime`, or `assemble_paper_mode_flag`;
- introduce any new V2 `app/domain` type, service, composition root, adapter, FastAPI surface, scheduler, background-loop adapter, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- introduce any `shadow_decision_id` or `execution_intent_id` lineage assertion;
- introduce any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk assertion;
- introduce any persistence assertion;
- flip the live-readiness gate or substitute for `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`;
- open, read, or write any `legacy_evidence_pointer` string as a filesystem path;
- import any test module from `v2/backend/tests/unit/decision_explainability_data_contract/`, `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`;
- emit a standalone harness framing-token marker line (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body.

PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_TEST_PLAN_READY
