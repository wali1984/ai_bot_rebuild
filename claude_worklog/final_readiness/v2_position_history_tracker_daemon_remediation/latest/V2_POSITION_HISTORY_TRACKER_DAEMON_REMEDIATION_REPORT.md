# V2 Position-History Tracker — Persistent Daemon Remediation Report

Generated: `2026-05-21T05:53:30Z`

GO/NO-GO: `V2_POSITION_HISTORY_TRACKER_PERSISTENT_DAEMON_REMEDIATION_READY`

## Scope

The prior packet `v2_position_history_persistent_tracker` shipped the
service module, CLI, tests, and packet artifacts, but did NOT install
the systemd unit or start the daemon. Codex correctly failed it with
`POSITION_HISTORY_HEARTBEAT_ABSENT_OR_EXPIRED`: at review time the
heartbeat key did not exist in Redis, TTL was `-2`, and no tracker
process was running.

This remediation packet:

- creates the systemd user unit
  `ai-bot-v2-position-history-persistent-tracker.service`
- symlinks it into `~/.config/systemd/user/`
- runs `systemctl --user daemon-reload`, `enable --now`
- proves the daemon is `active/running`, the heartbeat key exists
  with positive TTL, and the cycle counter advances across cycles
- preserves all paper/shadow safety invariants
- does NOT add the daemon to fail-blocking governors (deferred until
  Codex passes this remediation review)

`live_gate=blocked_human_only`, `live_symbols=[]`, and
`live_enabled=false` remain unchanged.

## Codex Fail Blocker Addressed

> `POSITION_HISTORY_HEARTBEAT_ABSENT_OR_EXPIRED`
>
> Runtime Redis evidence:
> - `EXISTS v2:paper:position_history:heartbeat` returned `0`
> - `TTL v2:paper:position_history:heartbeat` returned `-2`
> - `v2:paper:position_history*` key count: `0`
> - `v2:paper:position_price_track*` key count: `0`
> - no `v2_position_history_persistent_tracker` process was running

## Systemd Unit

File:
[claude_worklog/systemd/user/ai-bot-v2-position-history-persistent-tracker.service](claude_worklog/systemd/user/ai-bot-v2-position-history-persistent-tracker.service)

Sha256: `aa8cd019a201c9e479ba7b230d85a2912f6c6e266536b15cbcbec5823fe93594`

Key fields:

- `Type=simple`
- `WorkingDirectory=/home/wali/Desktop/AI BOT REBUILD`
- `Environment="PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD"`
- `Environment="LIVE_GATE=blocked_human_only"`
- `Environment="V2_LIVE_GATE_OVERRIDE=blocked_human_only"`
- `ExecStart=/usr/bin/env bash -lc 'exec .venv/bin/python3 -m v2.backend.app.cli.v2_position_history_persistent_tracker --loop --symbols BTCUSDT,ETHUSDT,SOLUSDT --total-seconds 86400 --max-seconds-per-session 600 --cycle-interval-seconds 60 --heartbeat-ttl-seconds 300 --track-ttl-seconds 900'`
- `Restart=always`, `RestartSec=15`
- `WantedBy=default.target`

The CLI itself refuses to start if `V2_LIVE_GATE_OVERRIDE` is set
to anything other than `blocked_human_only`, and refuses to start
the loop if `heartbeat_ttl_seconds <= cycle_interval_seconds + 29`
— both guards verified in the test suite.

Cycle/TTL satisfies the constraint:

- cycle interval = 60s (≤ 60s constraint)
- heartbeat TTL = 300s
- TTL minus cycle interval = 240s (≥ 30s constraint)

## Live Evidence

Captured immediately after enabling the service:

| Field | Value |
| ----- | ----- |
| `systemctl --user is-active ai-bot-v2-position-history-persistent-tracker.service` | `active` |
| `SubState` | `running` |
| `MainPID` | `2222389` |
| `NRestarts` | `0` |
| `ExecMainStatus` | `0` |
| `ps` includes the tracker CLI | YES |
| `EXISTS v2:paper:position_history:heartbeat` | `1` |
| `TTL v2:paper:position_history:heartbeat` | `844` (positive, refreshing) |
| heartbeat `generated_utc` at sample 1 | `2026-05-21T05:50:16Z` (cycle 1) |
| heartbeat `generated_utc` at sample 2 (after 75s) | `2026-05-21T05:51:16Z` (cycle 2) |
| heartbeat `generated_utc` at sample 3 (after another 60s) | `2026-05-21T05:53:16Z` (cycle 4) |
| per-symbol `v2:paper:position_price_track:*` keys | 3 (BTCUSDT, ETHUSDT, SOLUSDT) |
| per-symbol `v2:paper:position_history:*` keys | 3 (BTCUSDT, ETHUSDT, SOLUSDT) |
| `open_position_symbol_count` | 0 |
| `no_open_position_symbol_count` | 3 |
| `no_open_position_state_token` | `NO_OPEN_POSITION` |

The heartbeat advanced across two consecutive observations and the
TTL was re-extended — proof the daemon is refreshing every cycle,
not just at start.

## Safety Pinned In Live Payload

The current heartbeat payload (read directly from Redis at
`2026-05-21T05:53:16Z`) reports:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- `full_observation_consumption_allowed=false`
- `full_observation_consumption_unblocked_after=V2_POSITION_HISTORY_PERSISTENT_TRACKER_CODEX_PASS`
- `no_synthesized_accepted_positions=true`
- `no_fabricated_excursion_metrics=true`
- `no_shadow_observations_counted_as_accepted=true`
- `accepted_intent_count_by_symbol={BTCUSDT:0, ETHUSDT:0, SOLUSDT:0}`
- `shadow_observation_count_by_symbol={BTCUSDT:1, ETHUSDT:1, SOLUSDT:0}`
- `held_intent_count_by_symbol={BTCUSDT:0, ETHUSDT:0, SOLUSDT:2}`
- `block_reason_count_by_symbol={BTCUSDT:0, ETHUSDT:0, SOLUSDT:0}`

Note the runtime distinction the prior Codex review asked for:
shadow and held intents are present in the V2 paper ledger but are
NOT counted as accepted (accepted stays at 0). The tracker is
honestly surfacing them in their own separate counters.

For all three symbols, `position_state=NO_OPEN_POSITION` and
MFE/MAE/ROE/unrealized_bps are `null`. The recorder did not invent
an entry price; `entry_price_source` records
`MISSING_ENTRY_PRICE_FROM_V2_PAPER_INPUTS`.

## Redis Write Boundary

Live scan of the V2 paper namespace returned exactly the three
allowed keyspaces:

- `v2:paper:position_history:heartbeat`
- `v2:paper:position_history:{BTCUSDT,ETHUSDT,SOLUSDT}`
- `v2:paper:position_price_track:{BTCUSDT,ETHUSDT,SOLUSDT}`

Zero writes outside the allowlist. Zero old-Redis writes. Zero
exchange-mutation surface from the new code. All `approves_*`
fields are `false` everywhere.

## Refreshed Status Mirrors

The daemon writes status mirrors on every cycle. All three are
current (within one cycle of `now`):

- [claude_worklog/final_readiness/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json](claude_worklog/final_readiness/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json)
- [v2/frontend/public/operator_runtime/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json](v2/frontend/public/operator_runtime/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json)
- [v2/frontend/public/v2_position_history_persistent_tracker/latest/operator_dashboard_payload.json](v2/frontend/public/v2_position_history_persistent_tracker/latest/operator_dashboard_payload.json)

All three report `process_mode=persistent_daemon`,
`cycle_count>=4`, `service_active=true` (heartbeat-side flag),
`live_gate=blocked_human_only`, `live_symbols=[]`,
`full_observation_consumption_allowed=false`.

## Validation

| Check | Result |
| ----- | ------ |
| `py_compile` of service module | PASS |
| `py_compile` of CLI module | PASS |
| Focused persistent-tracker tests | PASS (12 of 12) |
| Focused recorder + TA-burndown tests | PASS (43 of 43) |
| Combined tracker-related test sweep | PASS (55 of 55) |
| `systemctl --user is-active` | `active` |
| Daemon process running | PASS (PID 2222389) |
| Redis heartbeat exists | PASS (`EXISTS=1`) |
| Redis heartbeat TTL positive | PASS (`TTL=844`) |
| Heartbeat freshness across two samples | PASS (cycle 1 -> 4; generated_utc advancing) |
| TTL exceeds cycle interval by ≥ 30s | PASS (240s headroom) |
| Per-symbol track keys present | PASS (3 of 3) |
| Per-symbol history keys present | PASS (3 of 3) |
| Redis write boundary scan | PASS (only allowed keys observed) |
| Old Redis write scan | PASS (0 hits in new code) |
| Exchange mutation scan | PASS (0 hits in new code) |
| Approval-token scan | PASS (all `approves_*` false) |
| JSON validation | PASS |

## Governor Registration Policy

Per the task spec, this daemon is intentionally NOT added to:

- `claude_worklog/tools/codex_continuous_remediation_review_governor.py`
- `claude_worklog/tools/codex_8h_war_room_review_governor.py`

It will be registered as an expected process / heartbeat in those
governors only AFTER Codex passes this daemon-remediation review.
That registration is the natural follow-up packet
(`v2_position_history_tracker_governor_registration`), mirroring
the liquidation-WSS daemon registration pattern that just landed.

## Safety Posture

- `live_gate=blocked_human_only` (CLI refuses to start otherwise)
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
- legacy code: unmodified
- legacy runtime: not stopped, not touched
- old Redis namespaces: not written
- exchange mutation surface: none introduced
- approvals: none created

## Final Decision

`V2_POSITION_HISTORY_TRACKER_PERSISTENT_DAEMON_REMEDIATION_READY`
