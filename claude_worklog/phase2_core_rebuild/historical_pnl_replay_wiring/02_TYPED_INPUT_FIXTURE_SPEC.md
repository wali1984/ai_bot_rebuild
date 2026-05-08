# Phase 2P — Typed Input Fixture Spec

## Determinism rules

- All identifier strings are deterministic literals namespaced by scenario slug and step ordinal.
- All timestamps are integers expressed as offsets from a deterministic anchor `BASE_TS_MS = 1_700_000_000_000` (no wall-clock helpers, no `datetime.now()`, no `time.time()`, no `time.monotonic()`).
- All clocks are deterministic monotonic counters built via `build_test_clock(start_ms, step_ms)` returning `Callable[[], int]`. Two independent test clocks are required: one for `PaperModeRuntime` (`paper_mode_clock`) and one for `PaperExecutionLedgerRecorder` (`ledger_clock`). Both clocks are pure-function counter objects authored entirely under the test package.
- All `live_blocked` flags are `True`.
- All symbols are uppercase Binance USD-M tradable symbols (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LABUSDT`).
- No fixture invocation invokes `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open`, `pathlib.Path.read_text`, `pathlib.Path.write_text`, or any network client.
- No fixture invocation calls any Binance read-only account-history endpoint.

## Evidence pack scenarios

The Phase 2P evidence pack defines exactly four deterministic scenarios. Each scenario is a typed pair `(HistoricalPnLEvidenceRun, tuple[HistoricalPnLReplayInput, ...])`. The fixture module exposes one factory function per scenario plus an aggregator `build_historical_pnl_replay_evidence_pack()` returning the ordered tuple of all four scenarios.

| Scenario slug | Symbol | Step count | Input-risk-action | Input-risk-reason | Mirror reason |
| --- | --- | --- | --- | --- | --- |
| `historical_pnl_pack_btc_winner_long` | `BTCUSDT` | 3 | `allow` | `allow_proceed_long` | `mirror_allow_proceed_long` |
| `historical_pnl_pack_eth_winner_short` | `ETHUSDT` | 3 | `allow` | `allow_proceed_short` | `mirror_allow_proceed_short` |
| `historical_pnl_pack_lab_loser_short` | `LABUSDT` | 3 | `allow` | `allow_proceed_short` | `mirror_allow_proceed_short` |
| `historical_pnl_pack_sol_orchestrator_held` | `SOLUSDT` | 3 | `deny` | `deny_orchestrator_held` | `mirror_deny_orchestrator_held` |

Total scenarios: 4. Total `HistoricalPnLReplayInput` rows across the pack: 12. Total expected `PaperExecutionLedgerEntry` records produced by the harness across the pack: 12. Total expected `HistoricalPnLReplayComparisonRecord` records: 12. Total expected `HistoricalPnLReplayEvidenceTrio` records: 4 (one per scenario). Total expected `PaperModeFlag` records emitted by the harness: 1 (at the harness level, not per scenario).

The `historical_pnl_pack_lab_loser_short` scenario uses a deterministic `legacy_realized_trade_evidence_pointer` literal pointing into `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md` (LAB hedge-unwind / squeeze legacy-failure evidence). Phase 2P does NOT model PnL, hedge state, residual exposure, or squeeze risk; the LAB scenario is a deterministic pointer-only typed mirror.

## Identifier conventions

For scenario slug `S` (e.g., `historical_pnl_pack_btc_winner_long`) and 1-based step ordinal `N` (e.g., `001`):

- `risk_decision_id` = `risk_decision_S_N`
- `decision_id` = `decision_S_N`
- `prediction_id` = `prediction_S_N`
- `feature_snapshot_id` = `feature_snapshot_S_N`

All identifiers fit the existing 128-character constraint with no whitespace per the typed surface validations in `v2/backend/app/domain/risk_gateway/record.py` and `v2/backend/app/domain/paper_execution_ledger/record.py`.

## Legacy realized-trade evidence pointer convention

For scenario slug `S` and 1-based step ordinal `N`:

- `legacy_realized_trade_evidence_pointer` = `legacy_realized_trade_evidence__S__step_N` for `historical_pnl_pack_btc_winner_long`, `historical_pnl_pack_eth_winner_short`, and `historical_pnl_pack_sol_orchestrator_held`.
- `legacy_realized_trade_evidence_pointer` = `legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_N` for `historical_pnl_pack_lab_loser_short`.

The pointer is a deterministic string identifier; the harness does NOT resolve it as a filesystem path, does NOT open it as a file, and does NOT read its target. The `forbidden_actions` list of the supervisor task explicitly forbids opening, reading, or writing the pointer string as a filesystem path.

## Typed input record shape

The fixture module defines test-only frozen `dataclass(slots=True)` value classes under `v2/backend/tests/unit/historical_pnl_replay_wiring/fixtures.py`:

```
@dataclass(frozen=True, slots=True)
class HistoricalPnLEvidenceRun:
    scenario_slug: str
    symbol: str
    run_started_ts_ms: int
    run_ended_ts_ms: int

@dataclass(frozen=True, slots=True)
class HistoricalPnLReplayInput:
    legacy_realized_trade_evidence_pointer: str
    risk_decision_record: RiskDecisionRecord
```

`HistoricalPnLEvidenceRun` and `HistoricalPnLReplayInput` are test-only value classes. They are NOT V2 `app/domain` types, services, adapters, persistence models, API surfaces, schedulers, paper-mode trader processes, or live-readiness gates. They are authored entirely inside the unit-test package under `v2/backend/tests/unit/historical_pnl_replay_wiring/`.

`RiskDecisionRecord` is the existing typed surface from `v2/backend/app/domain/risk_gateway/record.py`. The fixture module imports `RiskDecisionRecord` from `v2.backend.app.domain.risk_gateway` only; no other domain symbol is imported by the fixture module.

The fixture module constructs each `RiskDecisionRecord` via the existing `assemble_risk_decision_record(decision=..., now_ms_clock=...)` service or via the existing `RiskDecisionRecord` direct constructor with deterministic inputs. The fixture module does NOT mock, patch, or monkeypatch `assemble_risk_decision_record`, `build_risk_decision_evaluator`, `build_paper_execution_ledger_recorder`, `build_paper_mode_runtime`, `assemble_paper_execution_ledger_entry`, `assemble_paper_mode_flag`, or any of their dependencies.

## Mirror reason → input-risk-reason mapping (read-only restatement)

Per `v2/backend/app/domain/paper_execution_ledger/record.py` constants:

| `ledger_reason_code` | `input_risk_action` | `input_risk_reason_code` |
| --- | --- | --- |
| `mirror_allow_proceed_long` | `allow` | `allow_proceed_long` |
| `mirror_allow_proceed_short` | `allow` | `allow_proceed_short` |
| `mirror_deny_orchestrator_held` | `deny` | `deny_orchestrator_held` |

The fixture module restates this mapping as a `_REASON_TO_INPUT_RISK` mapping local to the test package; it does not import any new constant from `v2/backend/app/`.

## Run timestamp invariants

For each scenario:

- `run_started_ts_ms` = `BASE_TS_MS + scenario_index * 60_000`.
- `run_ended_ts_ms` = `run_started_ts_ms + step_count * 1_000`.
- Per-step `risk_decision_record.decision_ts_ms` = `run_started_ts_ms + N * 100` (1-based ordinal).

`scenario_index` is the zero-based ordinal of the scenario in the evidence pack (0 for `historical_pnl_pack_btc_winner_long`, 1 for `historical_pnl_pack_eth_winner_short`, 2 for `historical_pnl_pack_lab_loser_short`, 3 for `historical_pnl_pack_sol_orchestrator_held`). All timestamps are `int`. No `bool` is used for any timestamp field.

## Forbidden in fixtures

Fixtures must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics import;
- any new domain type, service, composition root, adapter, or test-harness adapter beyond the test-only value classes `HistoricalPnLEvidenceRun`, `HistoricalPnLReplayInput`, `HistoricalPnLReplayComparisonRecord`, and `HistoricalPnLReplayEvidenceTrio`;
- any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk field;
- any `live_blocked = False` value;
- any Binance read-only account-history client invocation;
- any standalone harness framing token marker (`BEGIN_FILE` or `END_FILE`) line.

PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_TYPED_INPUT_FIXTURE_SPEC_READY
