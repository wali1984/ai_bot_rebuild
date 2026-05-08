# Phase 2O — Test Plan

## Test module

The test module is `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py`.

The test module imports only from:

- `v2.backend.app.domain.orchestrator_decision`,
- `v2.backend.app.domain.risk_gateway`,
- `v2.backend.app.domain.shadow_mode_readiness`,
- `v2.backend.app.composition.shadow_mode_readiness.runtime`,
- `v2.backend.app.composition.risk_gateway.runtime`,
- the local fixtures and harness modules under `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`,
- the standard library (`pytest`, `dataclasses` only as needed).

The test module does NOT import `time`, `datetime`, `os`, `pathlib`, `subprocess`, `socket`, `requests`, `httpx`, `urllib`, `redis`, `aioredis`, `ccxt`, `fastapi`, `starlette`, `pydantic`, `torch`, `numpy`, `pandas`, or `scikit-learn`.

## Required test functions

Exactly the following 13 pytest functions must be authored, all under `test_shadow_mode_evidence_collection_harness.py`:

1. `test_evidence_pack_scenario_count_is_four` — asserts `len(build_shadow_mode_evidence_pack()) == 4`.
2. `test_evidence_pack_total_input_step_count_is_twelve` — asserts the total `OrchestratorDecisionRecord` count across the pack is 12 (3 + 3 + 3 + 3).
3. `test_evidence_pack_per_scenario_step_counts` — asserts the per-scenario step counts `(3, 3, 3, 3)` for the four scenarios in declared order.
4. `test_evidence_pack_lineage_id_namespacing` — asserts every `decision_id`, `prediction_id`, `feature_snapshot_id` carries the scenario slug and a 3-digit ordinal `001`/`002`/`003`.
5. `test_evidence_pack_legacy_action_evidence_pointer_namespacing` — asserts every `legacy_action_evidence_pointer` matches the deterministic anchor convention `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md#shadow_<slug>_<ordinal>`.
6. `test_evidence_pack_uniform_live_blocked` — asserts every `OrchestratorDecisionRecord.live_blocked is True`.
7. `test_harness_returns_ready_flag_when_requested_ready` — drives the harness with `requested_state=SHADOW_MODE_READY` and asserts `state == SHADOW_MODE_READY`, `live_blocked is True`, and `flag_emitted_ts_ms` matches the deterministic test clock.
8. `test_harness_returns_not_ready_flag_when_requested_not_ready` — drives the harness with `requested_state=SHADOW_MODE_NOT_READY` and asserts `state == SHADOW_MODE_NOT_READY`, `live_blocked is True`.
9. `test_harness_produces_one_trio_per_scenario_with_twelve_total_comparisons` — asserts the returned trio tuple has length 4 and the total comparison-record count summed across trios is 12.
10. `test_harness_lineage_carry_over` — asserts each produced `RiskDecisionRecord` carries the input `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol` from the corresponding `OrchestratorDecisionRecord`, and that `risk_decision_id == "rd_" + decision_id`.
11. `test_harness_risk_action_and_reason_per_decision_action` — asserts the produced `risk_action` and `risk_reason_code` match the existing service mapping for `open_long`, `open_short`, `hold`, `abstain`.
12. `test_harness_comparison_record_pairs_legacy_pointer_with_v2_risk_decision_record` — asserts each `ShadowModeComparisonRecord.legacy_action_evidence_pointer` equals the corresponding input pointer and `ShadowModeComparisonRecord.v2_risk_decision_record` is the produced `RiskDecisionRecord` for that step.
13. `test_harness_no_shadow_decision_id_field_introduced` — asserts the test-only `ShadowModeComparisonRecord` dataclass field set is exactly `{"legacy_action_evidence_pointer", "v2_risk_decision_record"}`, and asserts no `shadow_decision_id`, `execution_intent_id`, or `paper_trade_id` attribute exists on `ShadowModeComparisonRecord`, `ShadowModeComparisonInput`, or `ShadowModeEvidenceTrio`.

## Validation command

```
python -m pytest v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py -v --no-header
```

All 13 tests must pass. No tests are skipped. No tests are marked `xfail`. No tests use `mock.patch`, `monkeypatch`, or `unittest.mock`.

## Forbidden test behavior

Tests must NOT:

- mock, patch, or monkeypatch `build_shadow_mode_readiness_runtime`, `assemble_shadow_mode_readiness_flag`, `build_risk_decision_evaluator`, `assemble_risk_decision_record`, or any of their dependencies;
- introduce any I/O, network call, persistence, scheduler, FastAPI surface, Redis adapter, GPU runner, or model-loading subsystem;
- introduce any new lineage ID beyond `feature_snapshot_id`, `prediction_id`, `decision_id`, and the auto-derived `risk_decision_id`;
- assert or imply the existence of `shadow_decision_id`, `execution_intent_id`, or a new standalone `paper_trade_id` lineage row;
- introduce PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation;
- open, read, or write any file referenced by `legacy_action_evidence_pointer`;
- emit a standalone harness framing token marker line in any authored file body.

PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_TEST_PLAN_READY
