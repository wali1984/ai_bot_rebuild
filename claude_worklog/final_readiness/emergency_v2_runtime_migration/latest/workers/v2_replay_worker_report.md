# v2_replay_worker — Worker Report

worker_id: v2_replay_worker
classification: V2_RUNTIME_MIGRATION_PRIMARY_DISPATCH
generated_at: 2026-05-14
status: IMPLEMENTED_NON_LIVE
live_gate: blocked_human_only
gate_always_blocked_invariant: true
exchange_action_taken: false
exchange_call_invariant: NO_REAL_EXCHANGE_CALL_FROM_REPLAY_WORKER
codex_review_trigger: codex_review_v2_replay_worker

## Purpose

Lift the V2 composition runtime
`v2/backend/app/composition/replay_backtest_runner/runtime.py` into a
standalone CLI worker that:

1. Reads `PaperExecutionLedgerEntry` records from a JSON source
   (explicit `--source-file` or the V2 paper-execution worker public
   payload). No Redis stream reads.
2. Filters those entries by a replay window
   `[--window-start-ms, --window-end-ms]` and an optional
   `--paper-trade-id`.
3. Builds a `ReplayBacktestRun` and invokes the existing composition
   runtime to produce a tuple of `ReplayBacktestStep` records plus a
   `ReplayBacktestSummary`.
4. Writes the result to **replay-scoped** output paths only — never to
   `operator_runtime/paper_online/` (invariant
   `REPLAY_OUTPUT_NEVER_OVERWRITES_PAPER_ONLINE`).

## Files emitted in this dispatch

- `v2/backend/app/cli/v2_replay_worker.py`
- `v2/backend/tests/integration/cli/test_v2_replay_worker.py`
- `v2/frontend/public/operator_runtime/v2_replay_worker/latest/v2_replay_worker_status.json`
  (initial seed payload; fail_closed pending real run)
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_replay_worker_status.json`
  (mirror of the public seed payload)
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_replay_worker_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_replay_worker_legacy_behavior_mapping.json`
- this report

## Invariants asserted in source + tests

| Invariant | Where asserted |
|---|---|
| Replay output never overwrites `operator_runtime/paper_online/` | `v2_replay_worker.py::_assert_replay_output_paths_not_paper_online`, `v2_replay_worker.py::write_status`; tests `test_replay_output_paths_never_contain_paper_online`, `test_write_status_raises_when_target_is_paper_online` |
| Live gate permanently `blocked_human_only` | constant `LIVE_GATE_STATUS`; test `test_gate_always_blocked_invariant_in_payload` |
| No exchange-mutation method names in source | grep guarded by `test_no_exchange_mutation_method_names_in_source` |
| No Binance / ccxt / Redis imports | regex guarded by `test_no_binance_ccxt_or_redis_imports_in_source` |
| No legacy Redis writer keys reintroduced | `test_worker_source_does_not_introduce_legacy_redis_writers` |
| Symbol Universe contract on every payload | `build_symbol_scope` always included; test `test_symbol_universe_contract_in_payload` |
| 25-symbol legacy active subset is not the full universe | scope exposes `legacy_active_symbols`, `dynamic_discovered_symbols`, `training_symbols`, `paper_symbols`, `live_symbols`, `live_blocked_symbols` separately; public payload mismatch is ignored and canonical legacy 25 is preserved by `test_public_symbol_universe_payload_cannot_override_legacy_25` |
| Legacy execution-by-signal indexing preserved | `v2_replay_worker.py::_index_executions_by_signal_id`; test `test_execution_index_by_signal_id_is_preserved` |
| Fail-closed on missing/invalid input or empty window | tests 3, 4, 5, 8 |
| Required public payload fields present in payload AND on disk | `REQUIRED_PUBLIC_PAYLOAD_FIELDS`; test `test_required_public_payload_fields_present` |
| Steps chronologically sorted | test `test_steps_sorted_chronologically` |
| Service-level validators still enforced through composition runtime | test `test_invalid_ledger_reason_fails_closed` |

## CLI usage

```
python -m v2.backend.app.cli.v2_replay_worker \
  --replay-run-id rr_2026_05_14_btcusdt_01 \
  --symbol BTCUSDT \
  --window-start-ms 1715000000000 \
  --window-end-ms   1715086400000 \
  --run-mode replay \
  --source-file /tmp/paper_ledger_entries.json \
  --once
```

Exit codes:
- `0` → replay completed and at least one step was emitted
  (`fail_closed=False`)
- `2` → fail-closed (missing source, invalid JSON, empty window, invalid
  ledger entry, replay run rejected)

## Legacy alignment

See `v2_replay_worker_LEGACY_BASELINE_ANALYSIS.md` and
`v2_replay_worker_legacy_behavior_mapping.json` for the full legacy
reference set (`legacy_reference/scripts/replay_sanity_check.py`,
`legacy_reference/rl/scripts/replay_decision.py`,
`legacy_reference/rl/replay_store.py`,
`legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py`)
and the intentional changes (no Redis dependency; portfolio-policy
validation moved to the risk gateway; replay output write-path
invariant).

## SYMBOL_UNIVERSE_CONTRACT and SYMBOL_UNIVERSE_SELECTION_SCOPE_UPDATE

- `legacy_active_symbols` — the 25-symbol legacy active subset, sourced
  via the V2 Symbol Universe service from `legacy_config.py SYMBOLS`.
  Not the full universe. Public payload `legacy_active_symbols` cannot
  override the canonical legacy 25; mismatches are surfaced as
  `PUBLIC_PAYLOAD_MISMATCH_IGNORED_CANONICAL_LEGACY_25_PRESERVED`.
- `dynamic_discovered_symbols` — broader passive discovery from
  Binance Futures, CoinAnk, CoinAPI, KuCoin, and future ingestors.
- `training_symbols`, `paper_symbols` — evidence-selected subsets;
  empty in the seed payload until populated by the live workers.
- `live_symbols` — empty while live remains `blocked_human_only`.
- `live_blocked_symbols` — explicit; defaults to the discovered set.
- `binance_usdm_confirmed_symbols` — empty by default; CoinAnk-only
  symbols remain market-intelligence candidates until Binance USD-M
  tradability is confirmed.
- `passive_monitor_all_discovered_symbols: true`,
  `train_all_discovered_symbols: false`,
  `trade_all_discovered_symbols: false`.

## Operator note

The seed payload is `fail_closed=true` with reason
`no_paper_ledger_source_found`. That is the correct initial state: the
worker only emits a green payload after it has run with a real
`--source-file` or after the V2 paper-execution worker writes its first
real ledger entry. Operators triggering this worker must supply an
explicit replay-run id, symbol, and window.

## Codex review trigger

On emit, the supervisor should fire `codex_review_v2_replay_worker`
with this report as the entry point. Codex must verify:

1. The legacy baseline analysis cites concrete legacy files and line
   ranges.
2. No new Redis writer or exchange-mutation surface was introduced.
3. Replay output paths cannot collide with `paper_online/`.
4. The CLI faithfully delegates to the existing composition runtime.
5. The Symbol Universe contract is honoured in every code path.
I have emitted all seven required files: the V2 replay CLI worker that lifts the existing composition runtime, its integration test suite, the seed status payload at both the public-runtime and worker-status mirrors, the legacy baseline analysis with concrete legacy file/line citations, the JSON behavior mapping, and the worker report. Live remains `blocked_human_only`, no Redis/Binance/ccxt is introduced, and replay output is hard-walled against `operator_runtime/paper_online/`.
