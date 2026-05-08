# Phase 2O — Typed Input Fixture Spec

## Determinism rules

- All identifier strings are deterministic literals namespaced by scenario slug and step ordinal.
- All timestamps are integers expressed as offsets from a deterministic anchor `BASE_TS_MS = 1_700_000_000_000` (no wall-clock helpers, no `datetime.now()`, no `time.time()`, no `time.monotonic()`).
- All clocks are deterministic monotonic counters built via `build_test_clock(start_ms, step_ms)` returning `Callable[[], int]`. Two independent test clocks are required: one for `ShadowModeReadinessRuntime` (`shadow_mode_clock`) and one for `RiskDecisionEvaluator` (`risk_decision_clock`). Both clocks are pure-function counter objects authored entirely under the test package.
- All `live_blocked` flags are `True`.
- All symbols are uppercase Binance USD-M tradable symbols (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LABUSDT`).
- No fixture invocation invokes `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open`, `pathlib.Path.read_text`, `pathlib.Path.write_text`, or any network client.

## Evidence pack scenarios

The Phase 2O shadow-comparison pack defines exactly four deterministic scenarios. Each scenario is a typed pair `(scenario_slug, tuple[ShadowModeComparisonInput, ...])` where `ShadowModeComparisonInput` is a test-only frozen value class wrapping `(orchestrator_decision: OrchestratorDecisionRecord, legacy_action_evidence_pointer: str)`. The fixture module exposes one factory function per scenario plus an aggregator `build_shadow_mode_evidence_pack()` returning the ordered tuple of all four scenarios.

| Scenario slug | Symbol | Decision action | Decision reason | Step count | Risk reason produced |
| --- | --- | --- | --- | --- | --- |
| `shadow_mode_evidence_pack_btc_long` | `BTCUSDT` | `open_long` | `proceed_long` | 3 | three `allow_proceed_long` |
| `shadow_mode_evidence_pack_eth_short` | `ETHUSDT` | `open_short` | `proceed_short` | 3 | three `allow_proceed_short` |
| `shadow_mode_evidence_pack_sol_held` | `SOLUSDT` | `hold` | `hold_flat_direction` | 3 | three `deny_orchestrator_held` |
| `shadow_mode_evidence_pack_lab_abstained` | `LABUSDT` | `abstain` | `abstain_low_confidence` | 3 | three `deny_orchestrator_abstained` |

Total scenarios: 4. Total `OrchestratorDecisionRecord` typed input rows across the pack: 12. Total expected `RiskDecisionRecord` rows produced by the harness across the pack: 12. Total expected per-step `ShadowModeComparisonRecord` rows produced by the harness across the pack: 12. Total expected `ShadowModeReadinessFlag` rows: 1 (one harness-level readiness flag, state `ready`).

## Identifier conventions

For scenario slug `S` (e.g., `shadow_mode_evidence_pack_btc_long`) and 1-based step ordinal `N` (e.g., `001`):

- `decision_id` = `decision_S_N`
- `prediction_id` = `prediction_S_N`
- `feature_snapshot_id` = `feature_snapshot_S_N`
- `risk_decision_id` (auto-derived by the existing risk-gateway service) = `rd_decision_S_N`
- `legacy_action_evidence_pointer` = `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md#shadow_S_N`

All identifiers fit the existing 128-character constraint with no whitespace per the typed surface validations in `v2/backend/app/domain/orchestrator_decision/record.py` and `v2/backend/app/domain/risk_gateway/record.py`. The `decision_id` must be at most 125 characters to satisfy the existing risk-gateway service `risk_decision_id` derivation prefix `rd_`; all Phase 2O `decision_id` values are well under that bound.

The `legacy_action_evidence_pointer` is a deterministic string; the harness never opens the file. The pointer references existing read-only legacy-runtime-audit / legacy-readonly-audit Markdown files; the suffix anchor is purely a typed string convention and does not require the underlying file to define the anchor.

## Decision-action / decision-reason / direction / freshness / worker-health invariants

For each scenario the typed `OrchestratorDecisionRecord` is constructed with the following invariants per the existing `OrchestratorDecisionRecord` cross-field validations:

| Decision action | Decision reason | Input direction | Confidence calibrated | Freshness flag | Worker health |
| --- | --- | --- | --- | --- | --- |
| `open_long` | `proceed_long` | `long` | 0.75 | `fresh` | `HEALTHY` |
| `open_short` | `proceed_short` | `short` | 0.75 | `fresh` | `HEALTHY` |
| `hold` | `hold_flat_direction` | `flat` | 0.50 | `fresh` | `HEALTHY` |
| `abstain` | `abstain_low_confidence` | `long` | 0.10 | `fresh` | `HEALTHY` |

The `live_blocked` flag is `True` on every typed record.

## Run timestamp invariants

For each scenario:

- `decision_ts_ms[N]` = `BASE_TS_MS + scenario_index * 60_000 + N * 100` (1-based ordinal).

`scenario_index` is the zero-based ordinal of the scenario in the evidence pack (0 for `shadow_mode_evidence_pack_btc_long`, 1 for `shadow_mode_evidence_pack_eth_short`, etc.). All timestamps are `int`. No `bool` is used for any timestamp field.

## Forbidden in fixtures

Fixtures must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics import;
- any new domain type, service, composition root, adapter, or test-harness adapter beyond the existing typed surfaces;
- any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk field;
- any `live_blocked = False` value;
- any standalone harness framing token marker line in any authored file body;
- any actual file open / read / write of the legacy-action evidence pointer (the pointer is a deterministic typed string and is never dereferenced by the harness).

PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_TYPED_INPUT_FIXTURE_SPEC_READY
