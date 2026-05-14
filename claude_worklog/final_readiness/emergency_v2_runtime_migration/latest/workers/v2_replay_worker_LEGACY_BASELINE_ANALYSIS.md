# v2_replay_worker — Legacy Baseline Analysis

worker_id: v2_replay_worker
generated_at: 2026-05-14
classification: LEGACY_REVIEWED_BEFORE_V2_BUILD
live_gate: blocked_human_only
exchange_action_taken: false
exchange_call_invariant: NO_REAL_EXCHANGE_CALL_FROM_REPLAY_WORKER

## Scope

This worker lifts the existing V2 composition runtime
`v2/backend/app/composition/replay_backtest_runner/runtime.py` into a
standalone CLI worker. The CLI consumes paper-execution ledger entries
(emitted by `v2_paper_execution_worker`) and produces a windowed
`ReplayBacktestRun`, a tuple of `ReplayBacktestStep` records, and a
`ReplayBacktestSummary`. Output is written to a replay-scoped public
runtime path. The replay worker MUST NEVER overwrite
`operator_runtime/paper_online/`.

## legacy_source_paths

The legacy bot's replay/backtest behaviour is spread across several
small scripts and an RL experience buffer. The full set reviewed:

- `legacy_reference/scripts/replay_sanity_check.py`
  - Replays the last N entries of the `signals:trading` Redis stream
    plus the `executed_signals` stream and verifies portfolio policy
    constraints (max long/short slots, total positions, margin %).
- `legacy_reference/rl/scripts/replay_decision.py`
  - Replays a single decision by stream id from `signals:trading`.
- `legacy_reference/rl/replay_store.py`
  - Regime-stratified experience replay buffer used inside the RL
    trainer (state, action, reward, next_state, regime_label tuples).
- `legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py`
  - The legacy paper trader whose simulated executions provide the
    fill records that the V2 paper-execution worker now records and
    that this V2 replay worker consumes.
- `legacy_reference/rl/historical_data_loader.py`
  - Historical data loader used by the legacy trainer for offline
    replay over recorded market data.

## legacy_functions_preserved

| Legacy function/symbol | Responsibility | V2 location |
|---|---|---|
| `replay_sanity_check.fetch_signals` | Read recent decisions from a stream-like store | `v2_replay_worker._load_paper_ledger_entries_from_source` (reads JSON, not Redis) |
| `replay_sanity_check.fetch_executions` | Index executions by signal id | `v2_replay_worker._index_executions_by_signal_id` preserves an in-window execution index without old Redis reads/writes |
| `replay_sanity_check.replay_and_validate` | Walk decisions chronologically and produce a per-step + summary report | `assemble_replay_backtest_step` + `assemble_replay_backtest_summary` (existing V2 services, invoked through the composition runtime) |
| `replay_decision.main` | Replay a single decision | Inline filter on paper ledger entries by `paper_trade_id` (optional `--paper-trade-id` arg) |
| `paper_trader` simulated execution | Stamp simulated fill ledger | Already owned by `v2_paper_execution_worker`; this replay worker only consumes its ledger output |

## legacy_inputs

- Redis streams (`signals:trading`, `executed_signals`) consumed via
  `xrevrange` / `xrange`.
- Environment variables (`REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`,
  `PORTFOLIO_MAX_*`, `PORTFOLIO_MARGIN_*`).
- CLI args (`-n COUNT`, `--id <stream-id>`, `--verbose`).

## legacy_outputs

- Console log of policy violations, allow/deny counts, max positions
  observed, max margin percentage observed.
- No persisted artefact (the legacy scripts print to stdout only).

## legacy_redis_keys (read-only references)

The legacy scripts read these streams. The V2 replay worker MUST NOT
re-create writers for any of them; they are listed only so the audit
trail shows which legacy keys the legacy behaviour depended on.

- `signals:trading` (Redis stream, read-only legacy reference)
- `executed_signals` (Redis stream, read-only legacy reference)

The V2 replay worker reads NEITHER stream. It only reads V2 file-based
payloads (a JSON ledger entries file, or the V2 paper-execution worker
status payload at `v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`).

## legacy_config_dependencies

- `PORTFOLIO_MAX_LONG_SLOTS`, `PORTFOLIO_MAX_SHORT_SLOTS`,
  `PORTFOLIO_MAX_TOTAL_POSITIONS` (sanity-check thresholds).
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` (stream connectivity).

These are intentionally NOT carried into V2: the V2 replay worker is a
deterministic windowed re-walk of already-recorded paper ledger
entries; portfolio-policy validation belongs to the V2 risk gateway
(`v2_risk_gateway_runtime_worker`) and is verified separately.

## legacy_edge_cases

- Empty `signals:trading` stream → legacy prints "no signals", exits 0.
  → V2: replay run still emits a fail-closed status with reason
  `no_paper_ledger_entries_in_window` and rc 2.
- JSON decode failure on stream payload → legacy logs and skips.
  → V2: classified as `INVALID_PAPER_LEDGER_ENTRY` and fail-closes.
- Stream entries unordered → legacy reverses to chronological.
  → V2: explicitly sorts paper ledger entries by `ledger_entry_ts_ms`
  ascending before assembling steps.
- Very old entries kept by stream pruning → legacy still replays them.
  → V2: applies a `--window-start-ms`/`--window-end-ms` window and
  refuses entries outside the window.
- `--id` not found → legacy prints "not found" rc 1.
  → V2: `--paper-trade-id` not found → fail-closed,
  `paper_trade_id_not_in_window`, rc 2.

## legacy_failure_modes

- Redis connection refused → unrecoverable, legacy aborts. V2 has no
  Redis dependency, so this failure mode does not exist.
- Malformed payload → legacy skips silently; V2 fail-closes.
- Stream pruning had removed the requested id → legacy "not found"; V2
  reports `paper_trade_id_not_in_window`.

## legacy_tests_or_expected_behavior

The legacy scripts ship without unit tests. Expected behaviour is
documented inline (docstrings + headers) and validated only by the
ad-hoc operator running `python3 scripts/replay_sanity_check.py` and
reading the console output. The V2 worker preserves the spirit
(deterministic re-walk of recorded decisions) and adds a structured,
machine-readable status payload plus integration tests.

## V2_mapping

- Reads ledger entries from a JSON file (`--source-file`) OR from the
  V2 paper-execution worker public payload (single entry). NEVER from
  Redis.
- Constructs domain dataclasses
  (`PaperExecutionLedgerEntry`, `ReplayBacktestRun`) and invokes
  `v2.backend.app.composition.replay_backtest_runner.build_replay_backtest_runner(now_ms_clock=...)`
  to obtain `assemble_step` and `assemble_summary` callables.
- Writes:
  - `v2/frontend/public/operator_runtime/v2_replay_worker/latest/v2_replay_worker_status.json`
  - `v2/runtime/v2_replay_worker/latest/v2_replay_worker_status.json`
  - `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_replay_worker_status.json`
- Refuses to write any path that resolves to
  `operator_runtime/paper_online/` (invariant `REPLAY_OUTPUT_NEVER_OVERWRITES_PAPER_ONLINE`).

## intentional_changes

- No Redis read or write (legacy `signals:trading`, `executed_signals`
  are no longer queried). All ledger entries arrive via filesystem.
- No portfolio-constraint validation here (that responsibility belongs
  to `v2_risk_gateway_runtime_worker`).
- Adds a hard write-path invariant: replay outputs are scoped to
  `v2_replay_worker/` and must not collide with `paper_online/`.
- Symbol Universe contract is required on every payload (legacy
  scripts hardcoded the live symbol set).
- Live gate is permanently `blocked_human_only`; legacy scripts had no
  notion of a gate.

## removed_or_deprecated_behavior_with_reason

- Direct Redis stream access — removed because V2 is local-first and
  reads file-based public payloads. Reason: dependency reduction and
  audit safety (V2 must never re-create writers for legacy keys).
- Hardcoded portfolio policy thresholds — removed because they are now
  evaluated by the V2 risk gateway and are not part of replay/backtest
  bookkeeping. Reason: separation of concerns.
- `redis.Redis(...)`, `xrevrange`, `xrange` imports — removed.
  Reason: V2 paper/replay path must not introduce a new Redis client.
- Telegram alerts (present in legacy paper trader) — explicitly
  excluded from the replay worker. Reason: replay is a deterministic
  re-walk; it does not emit live alerts.

## evidence_pointers

- `legacy_reference/scripts/replay_sanity_check.py:1-120` —
  legacy replay-sanity script source (read-only).
- `legacy_reference/rl/scripts/replay_decision.py:1-42` —
  legacy replay-decision script source (read-only).
- `legacy_reference/rl/replay_store.py:1-60` — RL replay buffer
  context (read-only).
- `legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py:1-60`
  — legacy paper trader (read-only context for ledger entry
  shape).
- `v2/backend/app/composition/replay_backtest_runner/runtime.py:1-55`
  — V2 composition runtime that this CLI worker wraps.
- `v2/backend/app/services/replay_backtest_runner/service.py:30-226` —
  the `assemble_replay_backtest_step` and
  `assemble_replay_backtest_summary` functions invoked.
- `v2/backend/app/domain/replay_backtest_runner/run.py:1-83` —
  `ReplayBacktestRun` invariants used by the worker.
- `v2/backend/app/domain/paper_execution_ledger/record.py:1-100` —
  `PaperExecutionLedgerEntry` shape that the worker constructs from
  JSON.
- `v2/backend/app/cli/v2_paper_execution_worker.py:560-620` —
  upstream paper-execution worker status payload shape used as a
  single-entry source.

## blocked_human_only_acknowledgement

- live_gate: blocked_human_only
- gate_always_blocked_invariant: true
- exchange_action_taken: false
- exchange_call_invariant: NO_REAL_EXCHANGE_CALL_FROM_REPLAY_WORKER
- legacy_redis_writers_introduced: false
