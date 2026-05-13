# v2_feature_snapshot_builder — worker report

## Status

**MIGRATED_AND_RUNNABLE** as of 2026-05-13. Single-shot run completed; public payload fresh; all 9 integration tests pass.

## What this worker does

Standalone CLI worker that lifts `v2/backend/app/services/feature_snapshots/service.py` out of the `paper_online_runtime` loop. Independently produces feature snapshots from a V2-owned input (either a payload file, the `paper_online` runtime's payload, or a fresh Binance public REST fetch) and writes:

- `v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json`
- `v2/runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_status.json`

## Runnable command

```text
python3 -m v2.backend.app.cli.v2_feature_snapshot_builder --once --read-from-paper-runtime
python3 -m v2.backend.app.cli.v2_feature_snapshot_builder --loop --interval 30
```

Flags:
- `--once` / `--loop` (default `--once`)
- `--interval N` (loop interval, default 30s)
- `--symbol SYMBOL` (read-only public feed, default BTCUSDT)
- `--payload-file PATH` (override input — used by tests and replay)
- `--read-from-paper-runtime` (prefer existing `paper_online` payload when present)
- `--no-write` (dry run; useful for diagnostics)

## Public payload fields (all required fields populated)

`worker_id`, `last_run_ts`, `last_snapshot_id`, `last_snapshot_ts`, `feature_categories_present`, `stale_features`, `missing_features`, `trainer_readiness`, `source_payload_path`, `freshness_seconds`, plus safety fields `live_gate` and `current_gate_state` (both always `blocked_human_only`).

## trainer_readiness state machine

| condition | trainer_readiness |
|---|---|
| missing required features | `BLOCKED_MISSING_REQUIRED` (worker exits code 2 in single-shot mode) |
| no missing, some stale | `DEGRADED_STALE_INPUTS` |
| no missing, no stale, library confidence_input_ready | `READY` |
| otherwise | `NOT_READY` |

## Test coverage (all passing)

| # | test | what it proves |
|---|---|---|
| 1 | `test_build_snapshot_produces_expected_categories` | Required public payload fields present; price + liquidity categories present from sample input |
| 2 | `test_stale_input_marked_explicitly_as_stale` | When source freshness exceeds `max_age_ms`, the `stale_features` list is non-empty and readiness is `DEGRADED_STALE_INPUTS` or `BLOCKED_MISSING_REQUIRED` |
| 3 | `test_fail_closed_when_required_feature_category_missing` | CLI exits code 2 and emits `BLOCKED_MISSING_REQUIRED` when required price features are stripped |
| 4 | `test_snapshot_id_is_deterministic_given_inputs` | Two runs with the same payload-file produce the same `last_snapshot_id` |
| 5 | `test_trainer_readiness_signal_propagates_correctly` | `confidence_input_ready` from the library maps to `READY` in status output when no missing/stale |
| 6 | `test_live_gate_is_always_blocked_human_only` | `live_gate` and `current_gate_state` are both `blocked_human_only` in the status payload |
| 7 | `test_worker_module_has_no_real_exchange_codepath` | Contract test: the worker source contains no exchange order/leverage/margin-mutation method names |
| 8 | `test_freshness_seconds_is_non_negative_for_present_ts` | Freshness helper returns ≥ 0 for a present-or-past timestamp |
| 9 | `test_freshness_seconds_returns_minus_one_for_garbage` | Freshness helper returns -1 for malformed input rather than crashing |

Run via `.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_feature_snapshot_builder.py` (or `.venv/bin/python3 -m pytest …`). Result this turn: **9 passed in 0.07s**.

## First runtime run (this turn)

```text
last_snapshot_id: feature_snapshot_93fded25d918e395b102fca1
last_snapshot_ts: 2026-05-13T21:41:03Z
trainer_readiness: READY
feature_categories_present: [price, liquidity]
source_payload_path: binance_public_rest:BTCUSDT
live_gate: blocked_human_only
```

## Hard-constraint compliance

- No legacy mutation: yes (worker reads only V2 paths or Binance public read-only REST).
- No old Redis writes: yes (worker contains no `redis` import; verifiable by `grep -n "redis" v2/backend/app/cli/v2_feature_snapshot_builder.py`).
- No exchange order / leverage / margin codepath: yes (test #7 enforces).
- No key activation: yes (worker uses only public REST endpoints with no auth header).
- No approval token creation: yes.
- Live gate always `blocked_human_only`: yes (constants + test #6 enforce).
- Legacy `frozen_reference_only`: yes.

## Codex review

Triggers `codex_review_v2_feature_snapshot_builder` (task descriptor already queued at `claude_worklog/agent_supervisor/tasks/codex_review_v2_feature_snapshot_builder.json`). Codex must produce `V2_FEATURE_SNAPSHOT_BUILDER_CODEX_PASS` or `_FAIL` after reviewing this report and the artifacts listed above.

## Files emitted by this worker port

- `v2/backend/app/cli/v2_feature_snapshot_builder.py` — CLI worker (~280 lines)
- `v2/backend/tests/integration/cli/__init__.py` — empty package marker
- `v2/backend/tests/integration/cli/test_v2_feature_snapshot_builder.py` — 9 tests, all passing
- `v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json` — public payload (seeded by first run)
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_report.md` (this file)
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_feature_snapshot_builder_status.json` — mirror

## Outcome for the aggregate

This port moves the V2 independence score in the [gap matrix](../V2_RUNTIME_WORKER_GAP_MATRIX.md) from `MIGRATED_LIBRARY_ONLY` to `MIGRATED_AND_RUNNABLE` for the feature pipeline. Remaining P0 lifts: risk_gateway_runtime, paper_execution, execution_ledger, signal_lineage, account/position monitor.

The aggregate emergency-migration GO/NO-GO remains `EMERGENCY_V2_RUNTIME_MIGRATION_AND_ONLINE_BOOTSTRAP_BLOCKED` until the remaining five P0 workers ship.
