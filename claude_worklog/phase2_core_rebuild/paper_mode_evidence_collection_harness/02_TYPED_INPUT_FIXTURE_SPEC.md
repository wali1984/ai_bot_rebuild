# Phase 2N — Typed Input Fixture Spec

## Determinism rules

- All identifier strings are deterministic literals namespaced by scenario slug and step ordinal.
- All timestamps are integers expressed as offsets from a deterministic anchor `BASE_TS_MS = 1_700_000_000_000` (no wall-clock helpers, no `datetime.now()`, no `time.time()`, no `time.monotonic()`).
- All clocks are deterministic monotonic counters built via `build_test_clock(start_ms, step_ms)` returning `Callable[[], int]`. Two independent test clocks are required: one for `PaperModeRuntime` (`paper_mode_clock`) and one for `ReplayBacktestRunner` (`replay_clock`). Both clocks are pure-function counter objects authored entirely under the test package.
- All `live_blocked` flags are `True`.
- All symbols are uppercase Binance USD-M tradable symbols (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `LABUSDT`).
- No fixture invocation invokes `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow`, `os.environ`, `os.getenv`, `open`, `pathlib.Path.read_text`, `pathlib.Path.write_text`, or any network client.

## Evidence pack scenarios

The Phase 2N evidence pack defines exactly five deterministic scenarios. Each scenario is a typed pair `(ReplayBacktestRun, tuple[PaperExecutionLedgerEntry, ...])`. The fixture module exposes one factory function per scenario plus an aggregator `build_paper_mode_evidence_pack()` returning the ordered tuple of all five scenarios.

| Scenario slug | Symbol | Run mode | Step count | Mirror reason mix |
| --- | --- | --- | --- | --- |
| `paper_mode_evidence_pack_btc_long` | `BTCUSDT` | `replay` | 3 | three `mirror_allow_proceed_long` mirror rows |
| `paper_mode_evidence_pack_eth_short` | `ETHUSDT` | `replay` | 3 | three `mirror_allow_proceed_short` mirror rows |
| `paper_mode_evidence_pack_sol_held` | `SOLUSDT` | `replay` | 2 | two `mirror_deny_orchestrator_held` mirror rows |
| `paper_mode_evidence_pack_lab_abstained` | `LABUSDT` | `replay` | 2 | two `mirror_deny_orchestrator_abstained` mirror rows |
| `paper_mode_evidence_pack_btc_default_deny` | `BTCUSDT` | `replay` | 2 | two `mirror_deny_default` mirror rows |

Total scenarios: 5. Total `PaperExecutionLedgerEntry` mirror rows across the pack: 12. Total expected `ReplayBacktestStep` records produced by the harness across the pack: 12. Total expected `ReplayBacktestSummary` records: 5 (one per scenario).

## Identifier conventions

For scenario slug `S` (e.g., `paper_mode_evidence_pack_btc_long`) and 1-based step ordinal `N` (e.g., `001`):

- `replay_run_id` = `replay_run_S`
- `paper_trade_id` = `paper_trade_S_N`
- `risk_decision_id` = `risk_decision_S_N`
- `decision_id` = `decision_S_N`
- `prediction_id` = `prediction_S_N`
- `feature_snapshot_id` = `feature_snapshot_S_N`

All identifiers fit the existing 128-character constraint with no whitespace per the typed surface validations in `v2/backend/app/domain/paper_execution_ledger/record.py` and `v2/backend/app/domain/replay_backtest_runner/step.py` and `v2/backend/app/domain/replay_backtest_runner/run.py`.

## Mirror reason → input-risk-reason mapping (read-only restatement)

Per `v2/backend/app/domain/paper_execution_ledger/record.py` constants:

| `ledger_reason_code` | `input_risk_action` | `input_risk_reason_code` |
| --- | --- | --- |
| `mirror_allow_proceed_long` | `allow` | `allow_proceed_long` |
| `mirror_allow_proceed_short` | `allow` | `allow_proceed_short` |
| `mirror_deny_orchestrator_abstained` | `deny` | `deny_orchestrator_abstained` |
| `mirror_deny_orchestrator_held` | `deny` | `deny_orchestrator_held` |
| `mirror_deny_default` | `deny` | `deny_default` |

The fixture module restates this mapping as a `_REASON_TO_INPUT_RISK` mapping local to the test package; it does not import any new constant from `v2/backend/app/`.

## Run timestamp invariants

For each scenario:

- `run_started_ts_ms` = `BASE_TS_MS + scenario_index * 60_000`.
- `run_ended_ts_ms` = `run_started_ts_ms + max(1, step_count) * 1_000`.
- `ledger_entry_ts_ms[N]` = `run_started_ts_ms + N * 100` (1-based ordinal).

`scenario_index` is the zero-based ordinal of the scenario in the evidence pack (0 for `paper_mode_evidence_pack_btc_long`, 1 for `paper_mode_evidence_pack_eth_short`, etc.). All timestamps are `int`. No `bool` is used for any timestamp field.

## Forbidden in fixtures

Fixtures must NOT introduce:

- any wall-clock helper invocation;
- any file I/O, network client, environment-variable reader, or heavyweight numerics import;
- any new domain type, service, composition root, adapter, or test-harness adapter beyond the existing typed surfaces;
- any `shadow_decision_id`, `execution_intent_id`, or new standalone `paper_trade_id` lineage row;
- any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk field;
- any `live_blocked = False` value;
- any standalone harness framing token marker (`BEGIN_FILE` or `END_FILE`) line.

PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_TYPED_INPUT_FIXTURE_SPEC_READY
