# V2 Position History Source Probe Report

GO/NO-GO: `V2_POSITION_HISTORY_SOURCE_PROBE_READY`

Read-only probe. Does NOT modify `full_observation_builder.py`,
legacy, or any external feed. Does NOT approve live, canary,
leverage/margin, exchange mutation, legacy shutdown, or Redis trim.

## What was probed

Redis patterns scanned for any V2-native position-history time-series:

```
v2:paper:positions_history*   : 0 keys
v2:paper:ledger_history*      : 0 keys
v2:paper:intents_history*     : 0 keys
v2:paper:fills*               : 0 keys
v2:trade_history*             : 0 keys
```

V2 keys present today are all **snapshots**, not time-series:

- `v2:paper:positions` (latest snapshot only)
- `v2:paper:ledger` (latest snapshot only; held_by_paper_fill_gate snapshot inside)
- `v2:paper:intents` (latest snapshot only)
- `v2:risk:decisions` (latest snapshot only)
- `v2:orchestrator:decisions` (latest snapshot only)

## MFE/MAE/ROE/hold-time buildable today?

**No**. V2 publishes per-cycle snapshots only. MFE (Maximum Favorable
Excursion), MAE (Maximum Adverse Excursion), ROE-over-position, and
hold-time statistics all require continuous per-position trajectory
data captured over the lifetime of each position. V2 does not record
this today.

## Alternative V2-native sources (not Redis-queryable)

- `v2/runtime/paper_shadow_observation.log` — paper-shadow observation
  publisher writes a log line per cycle; contains time-series state but
  is file-based, not Redis-queryable.
- `claude_worklog/agent_supervisor/logs/control_plane/v2_trade_management_paper_loop.log`
  — per-cycle paper-loop log.
- `v2:paper:ledger.accepted / blocked` (snapshot lists; could be turned
  into a history by a new V2 service).

## Operator decision required

Options:

- **DEFER_POSITION_HISTORY**: keep MFE/MAE/ROE/hold-time slots
  explicit-missing (current default).
- **APPROVE_V2_POSITION_HISTORY_AGGREGATOR**: build
  `v2/backend/app/cli/v2_paper_position_history_aggregator_loop.py`
  reading paper snapshots into time-series; new Codex review pair
  required.

Current default state: **DEFER_POSITION_HISTORY**.

## Fields that would become buildable under Approve

- `position_mfe_bps`, `position_mae_bps`
- `position_roe_pct`, `position_hold_time_seconds`, `position_age_seconds`
- `drawdown_over_position`
- `max_favorable_excursion_since_entry`, `max_adverse_excursion_since_entry`
- `average_unrealized_bps_over_window`, `win_rate_over_window`

## Safety

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- `modifies_full_observation_builder = false`
- `modifies_legacy = false`
- `creates_external_feed = false`
- `creates_credentials = false`
- `loads_any_blob = false`
- `no_raw_credentials_in_packet = true`
