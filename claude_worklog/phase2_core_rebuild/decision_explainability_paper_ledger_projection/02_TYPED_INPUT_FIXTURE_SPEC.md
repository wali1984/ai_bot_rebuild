# Phase 2S — Typed Input Fixture Spec

## Determinism rules

- All identifier strings are deterministic literals namespaced by scenario slug and step ordinal.
- All timestamps are integers expressed as offsets from a deterministic anchor `BASE_TS_MS = 1_700_000_000_000` (no wall-clock helpers, no `datetime.now()`, no `time.time()`, no `time.monotonic()`).
- All clocks are deterministic monotonic counters built via `build_test_clock(start_ms, step_ms)` returning `Callable[[], int]`. One `paper_ledger_clock` is required at the harness level for the single `PaperExecutionLedgerRecorder` composition-root build (the recorder is then invoked per-row, and each invocation advances the harness-level clock by the deterministic `step_ms` value). No other composition root is built or invoked by the Phase 2S harness.
- All `live_blocked` flags on the typed `RiskDecisionRecord` input rows are `True`. The typed `PaperExecutionLedgerEntry` rows produced by the recorder also carry `live_blocked = True` (per the recorder service invariant).
- All symbols are uppercase Binance USD-M tradable symbols (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LABUSDT`).
- No fixture invocation invokes `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open`, `pathlib.Path.read_text`, `pathlib.Path.write_text`, or any network client.
- No fixture invocation calls any Binance read-only account-history endpoint.
- No fixture imports any test module from `v2/backend/tests/unit/decision_explainability_data_contract/`, `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`. The Phase 2S fixture pack is self-contained and re-states the deterministic typed-row structure mirrored from those prior milestones.

## Scenario set

The Phase 2S evidence pack defines exactly four deterministic scenarios. Each scenario is a triplet of typed `PaperLedgerExplainabilityFixtureInput` rows. The fixture module exposes one factory function per scenario plus an aggregator `build_paper_ledger_explainability_fixture_inputs()` returning the ordered tuple of all twelve input rows.

| Scenario slug | Symbol | Step count | `input_decision_action` | `input_decision_reason_code` | `risk_action` | `risk_reason_code` | `has_lab_pointer` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `paper_ledger_explainability_pack_btc_winner_long` | `BTCUSDT` | 3 | `open_long` | `proceed_long` | `allow` | `allow_proceed_long` | `False` |
| `paper_ledger_explainability_pack_eth_winner_short` | `ETHUSDT` | 3 | `open_short` | `proceed_short` | `allow` | `allow_proceed_short` | `False` |
| `paper_ledger_explainability_pack_lab_loser_short` | `LABUSDT` | 3 | `open_short` | `proceed_short` | `allow` | `allow_proceed_short` | `True` |
| `paper_ledger_explainability_pack_sol_orchestrator_held` | `SOLUSDT` | 3 | `hold` | `hold_flat_direction` | `deny` | `deny_orchestrator_held` | `False` |

Total scenarios: 4. Total typed `PaperLedgerExplainabilityFixtureInput` rows: 12.

The four scenario `risk_reason_code` values (`allow_proceed_long`, `allow_proceed_short`, `allow_proceed_short`, `deny_orchestrator_held`) are all valid inputs to `assemble_paper_execution_ledger_entry` per `v2/backend/app/services/paper_execution_ledger/service.py` lines 59 through 78. The recorder produces, in each case, a typed `PaperExecutionLedgerEntry` with the corresponding mirrored ledger-side action / reason code (`record_allow` / `mirror_allow_proceed_long`, `record_allow` / `mirror_allow_proceed_short`, `record_allow` / `mirror_allow_proceed_short`, `record_deny` / `mirror_deny_orchestrator_held`).

The `paper_ledger_explainability_pack_lab_loser_short` scenario carries a deterministic `legacy_evidence_pointer` literal pointing into `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md` (LAB hedge-unwind / squeeze legacy-failure evidence). Phase 2S does NOT model PnL, hedge state, residual exposure, or squeeze risk; the LAB scenario contributes only the deterministic pointer literal carried by the per-row envelope.

## Identifier conventions

For scenario slug `S` and 1-based step ordinal `N` (e.g., `001`):

- `risk_decision_id` = `risk_decision_phase2s_S_N`.
- `decision_id` = `decision_phase2s_S_N`.
- `prediction_id` = `prediction_phase2s_S_N`.
- `feature_snapshot_id` = `feature_snapshot_phase2s_S_N`.
- `paper_trade_id` (auto-derived by recorder) = `pt_risk_decision_phase2s_S_N`.

All identifiers fit the existing 128-character constraint per the typed surface validations in `v2/backend/app/domain/risk_gateway/record.py` and `v2/backend/app/domain/paper_execution_ledger/record.py`. The `risk_decision_id` length stays within the 125-character cap required for `paper_trade_id` derivation per `v2/backend/app/services/paper_execution_ledger/service.py` line 53.

## Legacy evidence pointer convention

For 1-based step ordinal `N`:

- `legacy_evidence_pointer` = `legacy_evidence__paper_ledger_explainability__pack_btc_winner_long__step_N` for `paper_ledger_explainability_pack_btc_winner_long`.
- `legacy_evidence_pointer` = `legacy_evidence__paper_ledger_explainability__pack_eth_winner_short__step_N` for `paper_ledger_explainability_pack_eth_winner_short`.
- `legacy_evidence_pointer` = `legacy_evidence__paper_ledger_explainability__lab_hedge_unwind_squeeze__step_N` for `paper_ledger_explainability_pack_lab_loser_short`.
- `legacy_evidence_pointer` = `legacy_evidence__paper_ledger_explainability__pack_sol_orchestrator_held__step_N` for `paper_ledger_explainability_pack_sol_orchestrator_held`.

The pointer is a deterministic string identifier; the harness does NOT resolve it as a filesystem path, does NOT open it as a file, and does NOT read its target. The `forbidden_actions` list of the supervisor task explicitly forbids opening, reading, or writing the pointer string as a filesystem path.

## Typed input record shape

The fixture module defines test-only frozen `dataclass(slots=True)` value classes under `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/fixtures.py`:

```
@dataclass(frozen=True, slots=True)
class PaperLedgerExplainabilityFixtureInput:
    scenario_slug: str
    step_index: int
    legacy_evidence_pointer: str
    has_lab_pointer: bool
    risk_decision_record: RiskDecisionRecord
```

`PaperLedgerExplainabilityFixtureInput` is a test-only value class. It is NOT a V2 `app/domain` type, service, adapter, persistence model, API surface, scheduler, paper-mode trader process, or live-readiness gate. It is authored entirely inside the unit-test package under `v2/backend/tests/unit/decision_explainability_paper_ledger_projection/`.

`RiskDecisionRecord` is the existing typed surface from `v2/backend/app/domain/risk_gateway/record.py`. The fixture module imports `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway` only; no other domain symbol is imported by the fixture module.

The fixture module constructs each `RiskDecisionRecord` via the existing direct constructor with deterministic inputs. The fixture module does NOT mock, patch, or monkeypatch `assemble_paper_execution_ledger_entry`, `build_paper_execution_ledger_recorder`, `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_mode_runtime`, `assemble_paper_mode_flag`, or any of their dependencies.

## Run timestamp invariants

Per typed input row, the `risk_decision_record.risk_decision_ts_ms` field is computed as:

- `risk_decision_record.risk_decision_ts_ms = BASE_TS_MS + scenario_index * 60_000 + step_ordinal * 100`.

Where `scenario_index` is the zero-based ordinal of the scenario in the fixture pack (0 for `paper_ledger_explainability_pack_btc_winner_long`, 1 for `paper_ledger_explainability_pack_eth_winner_short`, 2 for `paper_ledger_explainability_pack_lab_loser_short`, 3 for `paper_ledger_explainability_pack_sol_orchestrator_held`), and `step_ordinal` is the 1-based ordinal of the step. All timestamps are `int`. No `bool` is used for any timestamp field.

The harness-level `paper_ledger_clock` advances on each per-row `PaperExecutionLedgerRecorder` invocation, producing a strictly increasing sequence of `ledger_entry_ts_ms` values across the 12 produced typed `PaperExecutionLedgerEntry` rows. The clock anchor is `PAPER_LEDGER_CLOCK_START_MS = BASE_TS_MS + 7_000_000`, with deterministic per-step advance `19` ms. The harness invokes the recorder exactly 12 times (once per fixture row, in the deterministic order returned by `build_paper_ledger_explainability_fixture_inputs()`), so the recorded `ledger_entry_ts_ms` for the i-th row (zero-based) is `PAPER_LEDGER_CLOCK_START_MS + i * 19`.

## Forbidden in fixtures

Fixtures must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics / ML import;
- any new V2 `app/domain` type, service, composition root, adapter, FastAPI surface, scheduler, background-loop adapter, Redis adapter, GPU runner, model-loading subsystem, or strategy library;
- any `shadow_decision_id` or `execution_intent_id` lineage row beyond the existing fields carried by `PaperExecutionLedgerEntry`;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation;
- any persistence (SQL, SQLite, JSON file, Parquet, CSV, Redis, in-memory dict acting as a ledger) of the typed envelope rows;
- any flip of the live-readiness gate or any substitute for `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`;
- any open / read / write of `legacy_evidence_pointer` strings as filesystem paths;
- any `mock`, `patch`, or `monkeypatch` of `build_paper_execution_ledger_recorder`, `assemble_paper_execution_ledger_entry`, `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_mode_runtime`, or `assemble_paper_mode_flag`;
- any import of a test module from `v2/backend/tests/unit/decision_explainability_data_contract/`, `v2/backend/tests/unit/paper_mode_evidence_collection_harness/`, `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, `v2/backend/tests/unit/historical_pnl_replay_wiring/`, or `v2/backend/tests/unit/aggregate_evidence_rollup_harness/`;
- any standalone harness framing-token marker line (the literal string `BEGIN` followed by `_FILE` or the literal string `END` followed by `_FILE`) as a line in any authored file body.

PHASE2S_DECISION_EXPLAINABILITY_PAPER_LEDGER_PROJECTION_TYPED_INPUT_FIXTURE_SPEC_READY
