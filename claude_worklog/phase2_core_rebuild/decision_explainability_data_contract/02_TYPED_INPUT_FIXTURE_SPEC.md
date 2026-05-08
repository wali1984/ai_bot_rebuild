# Phase 2R — Typed Input Fixture Spec

## Determinism rules

- All identifier strings are deterministic literals namespaced by scenario slug and step ordinal.
- All timestamps are integers expressed as offsets from a deterministic anchor `BASE_TS_MS = 1_700_000_000_000` (no wall-clock helpers, no `datetime.now()`, no `time.time()`, no `time.monotonic()`).
- All clocks are deterministic monotonic counters built via `build_test_clock(start_ms, step_ms)` returning `Callable[[], int]`. One `paper_mode_clock` is required at the harness level for the single `PaperModeRuntime` invocation. No other composition root is invoked by the Phase 2R harness.
- All `live_blocked` flags are `True`.
- All symbols are uppercase Binance USD-M tradable symbols (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LABUSDT`).
- No fixture invocation invokes `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open`, `pathlib.Path.read_text`, `pathlib.Path.write_text`, or any network client.
- No fixture invocation calls any Binance read-only account-history endpoint.
- No fixture imports any test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`. The Phase 2R fixture pack is self-contained and re-states the deterministic typed-row structure mirrored from those prior milestones.

## Scenario set

The Phase 2R evidence pack defines exactly four deterministic scenarios. Each scenario is a triplet of typed `DecisionExplainabilityFixtureInput` rows. The fixture module exposes one factory function per scenario plus an aggregator `build_decision_explainability_fixture_inputs()` returning the ordered tuple of all twelve input rows.

| Scenario slug | Symbol | Step count | `input_decision_action` | `input_decision_reason_code` | `risk_action` | `risk_reason_code` | `has_lab_pointer` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `decision_explainability_pack_btc_winner_long` | `BTCUSDT` | 3 | `open_long` | `proceed_long` | `allow` | `allow_proceed_long` | `False` |
| `decision_explainability_pack_eth_winner_short` | `ETHUSDT` | 3 | `open_short` | `proceed_short` | `allow` | `allow_proceed_short` | `False` |
| `decision_explainability_pack_lab_loser_short` | `LABUSDT` | 3 | `open_short` | `proceed_short` | `allow` | `allow_proceed_short` | `True` |
| `decision_explainability_pack_sol_orchestrator_held` | `SOLUSDT` | 3 | `hold` | `hold_flat_direction` | `deny` | `deny_orchestrator_held` | `False` |

Total scenarios: 4. Total typed `DecisionExplainabilityFixtureInput` rows: 12.

The `decision_explainability_pack_lab_loser_short` scenario carries a deterministic `legacy_evidence_pointer` literal pointing into `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md` (LAB hedge-unwind / squeeze legacy-failure evidence). Phase 2R does NOT model PnL, hedge state, residual exposure, or squeeze risk; the LAB scenario contributes only the deterministic pointer literal carried by the per-row envelope.

## Identifier conventions

For scenario slug `S` and 1-based step ordinal `N` (e.g., `001`):

- `risk_decision_id` = `risk_decision_phase2r_S_N`.
- `decision_id` = `decision_phase2r_S_N`.
- `prediction_id` = `prediction_phase2r_S_N`.
- `feature_snapshot_id` = `feature_snapshot_phase2r_S_N`.

All identifiers fit the existing 128-character constraint with no whitespace per the typed surface validations in `v2/backend/app/domain/risk_gateway/record.py`.

## Legacy evidence pointer convention

For scenario slug `S` and 1-based step ordinal `N`:

- `legacy_evidence_pointer` = `legacy_evidence__decision_explainability__pack_btc_winner_long__step_N` for `decision_explainability_pack_btc_winner_long`.
- `legacy_evidence_pointer` = `legacy_evidence__decision_explainability__pack_eth_winner_short__step_N` for `decision_explainability_pack_eth_winner_short`.
- `legacy_evidence_pointer` = `legacy_evidence__decision_explainability__lab_hedge_unwind_squeeze__step_N` for `decision_explainability_pack_lab_loser_short`.
- `legacy_evidence_pointer` = `legacy_evidence__decision_explainability__pack_sol_orchestrator_held__step_N` for `decision_explainability_pack_sol_orchestrator_held`.

The pointer is a deterministic string identifier; the harness does NOT resolve it as a filesystem path, does NOT open it as a file, and does NOT read its target. The `forbidden_actions` list of the supervisor task explicitly forbids opening, reading, or writing the pointer string as a filesystem path.

## Typed input record shape

The fixture module defines test-only frozen `dataclass(slots=True)` value classes under `v2/backend/tests/unit/decision_explainability_data_contract/fixtures.py`:

```
@dataclass(frozen=True, slots=True)
class DecisionExplainabilityFixtureInput:
    scenario_slug: str
    step_index: int
    legacy_evidence_pointer: str
    has_lab_pointer: bool
    risk_decision_record: RiskDecisionRecord
```

`DecisionExplainabilityFixtureInput` is a test-only value class. It is NOT a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, paper-mode trader process, or live-readiness gate. It is authored entirely inside the unit-test package under `v2/backend/tests/unit/decision_explainability_data_contract/`.

`RiskDecisionRecord` is the existing typed surface from `v2/backend/app/domain/risk_gateway/record.py`. The fixture module imports `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway` only; no other domain symbol is imported by the fixture module.

The fixture module constructs each `RiskDecisionRecord` via the existing direct constructor with deterministic inputs. The fixture module does NOT mock, patch, or monkeypatch `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_execution_ledger_recorder`, `build_paper_mode_runtime`, `assemble_paper_execution_ledger_entry`, `assemble_paper_mode_flag`, or any of their dependencies.

## Run timestamp invariants

Per typed input row, the `risk_decision_record.risk_decision_ts_ms` field is computed as:

- `risk_decision_record.risk_decision_ts_ms = BASE_TS_MS + scenario_index * 60_000 + step_ordinal * 100`.

Where `scenario_index` is the zero-based ordinal of the scenario in the fixture pack (0 for `decision_explainability_pack_btc_winner_long`, 1 for `decision_explainability_pack_eth_winner_short`, 2 for `decision_explainability_pack_lab_loser_short`, 3 for `decision_explainability_pack_sol_orchestrator_held`), and `step_ordinal` is the 1-based ordinal of the step. All timestamps are `int`. No `bool` is used for any timestamp field.

## Forbidden in fixtures

Fixtures must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics / ML import;
- any new V2 `app/domain` type, service, composition root, adapter, FastAPI surface, scheduler, background-loop adapter, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row beyond the existing fields carried by `RiskDecisionRecord`;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation;
- any persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger) of the typed envelope rows;
- any flip of the live-readiness gate or any substitute for `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`;
- any open / read / write of `legacy_evidence_pointer` strings as filesystem paths;
- any `mock`, `patch`, or `monkeypatch` of `build_paper_mode_runtime`, `assemble_paper_mode_flag`, `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_execution_ledger_recorder`, or `assemble_paper_execution_ledger_entry`;
- any import of a test module from `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`;
- any standalone harness framing token marker line (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body.

PHASE2R_DECISION_EXPLAINABILITY_DATA_CONTRACT_TYPED_INPUT_FIXTURE_SPEC_READY
