# V2 Position-History Persistent Tracker — Paper/Shadow Readiness Report

Generated: `2026-05-21T04:00:00Z`

GO/NO-GO: `V2_POSITION_HISTORY_PERSISTENT_TRACKER_PAPER_SHADOW_READY`

## Scope

V2-only paper/shadow persistent tracker that keeps the existing
`v2:paper:position_price_track:*`, `v2:paper:position_history:*`,
and `v2:paper:position_history:heartbeat` keys persistently fresh,
and surfaces the additional observation fields the full-observation
builder will need (first/last seen, accepted/held/shadow/blocked
intent counts, explicit `NO_OPEN_POSITION` state).

This packet does NOT:

- modify legacy code, legacy runtime, or any legacy Redis namespace
- enable live trading, canary trading, or operator approvals
- place exchange orders, cancel orders, or modify them
- change leverage or margin mode
- override the strict paper fill gate
- count shadow or held intents as accepted
- synthesize accepted positions
- fabricate MFE/MAE/ROE values
- unblock the full-observation builder's consumption of these keys
  (that remains gated behind a separate Codex review)

`live_gate=blocked_human_only`, `live_symbols=[]`, and
`live_enabled=false` are preserved.

## Relationship To Existing Recorder

The existing one-shot recorder at
[v2/backend/app/services/rl_core/position_price_tracking_recorder.py](v2/backend/app/services/rl_core/position_price_tracking_recorder.py)
already implements the MFE/MAE/ROE/hold-time math, the entry-price
recovery search, and the realized-exit recovery search. The
existing one-shot CLI
[v2/backend/app/cli/v2_position_price_tracking_recorder.py](v2/backend/app/cli/v2_position_price_tracking_recorder.py)
exposes those tracks via the same per-symbol keys but runs once
per invocation, which left the per-symbol histories not
persistently refreshed.

This packet adds:

- a new persistent-daemon CLI at
  [v2/backend/app/cli/v2_position_history_persistent_tracker.py](v2/backend/app/cli/v2_position_history_persistent_tracker.py)
- a new service module at
  [v2/backend/app/services/rl_core/position_history_persistent_tracker.py](v2/backend/app/services/rl_core/position_history_persistent_tracker.py)

The new service module reuses the recorder's math and its allowlist
helper (`safe_redis_set`) verbatim, then layers on:

- `first_seen_utc` and `last_seen_utc` per symbol, carried over only
  when the recorder still reports an `OPEN_*` state
- `accepted_intent_count`, `held_intent_count`,
  `shadow_observation_count`, `block_reason_count`, `block_reasons`
  per symbol from V2 paper inputs only
- `unrealized_bps` (alias of ROE, null on closed/flat)
- `max_favorable_bps`, `max_adverse_bps` (aliases of MFE/MAE)
- `entry_price_proxy` and `entry_price_proxy_source` to satisfy the
  TA-burndown's "entry price proxy if available" requirement
- explicit `position_state=NO_OPEN_POSITION` (replaces the
  recorder's `FLAT` label) so the full-observation consumer can
  branch unambiguously
- `full_observation_consumption_allowed=false` and
  `full_observation_consumption_unblocked_after=V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS`
  on every payload

The new CLI offers `--once` and `--loop` modes. In `--loop` mode it
refuses to start unless `heartbeat_ttl_seconds` exceeds
`cycle_interval_seconds` by at least 30 seconds — this is the same
contract the liquidation WSS daemon enforces and ensures the
heartbeat key never expires between cycles.

## Inputs

The tracker reads only the V2-owned Redis keys listed in the task:

- `v2:paper:positions`
- `v2:paper:ledger`
- `v2:market:prices:{symbol}`
- `v2:prediction:{symbol}:1m`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`

The prediction key is accepted for shape-compatibility with the
recorder; the tracker does not use it for accepted-position
synthesis (the recorder's `build_position_track` explicitly
discards it with `del prediction`).

## Outputs

Three Redis keys, all under the existing
`position_price_tracking_recorder` allowlist:

- `v2:paper:position_history:{symbol}` — extended per-symbol payload
  (superset of the recorder's history schema)
- `v2:paper:position_price_track:{symbol}` — recorder's track
  payload, refreshed every cycle
- `v2:paper:position_history:heartbeat` — extended heartbeat
  (superset of the recorder's heartbeat schema)

Status mirrors:

- `claude_worklog/final_readiness/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json`
- `v2/frontend/public/operator_runtime/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json`
- `v2/frontend/public/v2_position_history_persistent_tracker/latest/operator_dashboard_payload.json`

## Tracked Fields

Per the task contract:

| Field | Source / Computation |
| ----- | -------------------- |
| `first_seen_utc` | carried over from previous history payload while position remains OPEN; reset on close / no-open |
| `last_seen_utc` | current generated timestamp every cycle |
| `entry_price_proxy` / `entry_price_proxy_source` | recorder's `entry_price` + `entry_price_source` |
| `latest_price` | from `v2:market:prices:{symbol}` via recorder |
| `max_favorable_bps` | recorder's `mfe_bps` (carries forward min/max across cycles) |
| `max_adverse_bps` | recorder's `mae_bps` |
| `unrealized_bps` | recorder's `roe_bps`, null on closed/flat |
| `hold_time_seconds` | recorder's `hold_time_seconds` (null on no-open) |
| `accepted_intent_count` | V2 paper ledger `accepted` list, excluding rows tagged shadow / held / blocked |
| `held_intent_count` | ledger `held_by_paper_fill_gate` plus ledger-accepted-but-tagged-held plus `v2:paper:intents_held_by_paper_fill_gate` |
| `shadow_observation_count` | ledger `shadow_observations` plus ledger-accepted-but-tagged-shadow plus intents tagged shadow |
| `block_reason_count` | ledger `blocked` list plus ledger-accepted-but-tagged-blocked |
| `block_reasons` | deduped sorted reason strings |

## Safety Rules (Pinned in Tests)

1. **No synthesized accepted positions.** When `v2:paper:positions`
   has no row for the symbol, `position_state=NO_OPEN_POSITION`,
   `side=None`, and MFE/MAE/unrealized are all `null`.
2. **No shadow/held intents counted as accepted.** Ledger rows
   tagged `SHADOW*` / `HELD*` / `BLOCKED*` are routed to the
   matching distinct count, not `accepted_intent_count`. Verified
   by `test_shadow_and_held_intents_are_not_counted_as_accepted`.
3. **No fabricated MFE/MAE/ROE.** When entry price cannot be
   recovered or latest price is missing, the recorder returns
   `OPEN_MISSING_PRICE_INPUTS` with null excursions and the
   tracker propagates that. Verified by
   `test_no_open_position_does_not_synthesize_accepted_or_excursion_metrics`.
4. **Redis allowlist.** Writes are restricted to the recorder's
   existing `_allowed_key` set. Verified by
   `test_only_allowed_v2_paper_keys_are_written` and
   `test_safe_redis_set_refuses_non_allowlisted_keys`.
5. **Heartbeat-TTL > cycle-interval contract.** The daemon refuses
   to start if heartbeat TTL is not at least 30s greater than the
   cycle interval. Verified by
   `test_persistent_loop_refuses_when_heartbeat_ttl_too_short`.
6. **`V2_LIVE_GATE_OVERRIDE` refusal.** Setting that env var to any
   value other than `blocked_human_only` exits non-zero before any
   work happens. Verified by `test_main_refuses_live_gate_override`.
7. **Full-observation consumption explicitly blocked.** Every
   payload carries `full_observation_consumption_allowed=false` and
   names the Codex marker that would unblock it.

## Validation

| Check | Result |
| ----- | ------ |
| Focused persistent-tracker tests | PASS (12/12) |
| Existing recorder plus TA burndown tests | PASS (43/43) |
| `py_compile` of new service plus CLI | PASS |
| JSON validation of packet status JSONs | PASS |
| Legacy-Redis-write scan on new files | NONE (0 hits) |
| Exchange-mutation scan on new files | NONE (0 hits) |
| Direct `redis_client.set(` calls outside `safe_redis_set` | NONE (0 hits) |
| Raw credential scan on new files | NONE (0 hits) |

## New / Modified Files

| File | sha256 | bytes | lines |
| ---- | ------ | ----: | ----: |
| `v2/backend/app/services/rl_core/position_history_persistent_tracker.py` | `79c9655bbbf8afd1e09c9e9b199c71da51b89f8d5c1370bd5dfb5e9563da58bf` | 17709 | 472 |
| `v2/backend/app/cli/v2_position_history_persistent_tracker.py` | `8da0b844212eca2eef697e2ff1cc3659159b24d73cf0830eb519fa343a8159c1` | 12007 | 331 |
| `v2/backend/tests/integration/cli/test_v2_position_history_persistent_tracker.py` | `44a8e25f2386fef7ea87eb7a4ad4aa32cb298d45ed4ae7cb6b14de47d9d91701` | 18970 | 519 |

No legacy file, no `legacy_reference/`, no protected legacy worktree,
no `.env` file, and no secrets file was modified.

## Safety Posture

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=false`
- `places_real_order=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `full_observation_consumption_allowed=false`
- `full_observation_consumption_unblocked_after=V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS`

## Final Decision

`V2_POSITION_HISTORY_PERSISTENT_TRACKER_PAPER_SHADOW_READY`
