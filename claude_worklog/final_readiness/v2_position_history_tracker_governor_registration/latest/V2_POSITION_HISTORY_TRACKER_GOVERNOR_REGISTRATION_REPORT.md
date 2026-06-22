# V2 Position-History Tracker Governor Registration

Generated: `2026-05-21T06:00:00Z`

GO/NO-GO: `V2_POSITION_HISTORY_TRACKER_GOVERNOR_REGISTRATION_READY`

## Scope

Following the Codex PASS on
`V2_POSITION_HISTORY_TRACKER_DAEMON_REMEDIATION_CODEX_PASS`, this
packet registers the persistent position-history tracker daemon
as a first-class expected dependency in both governor surfaces.
Future cycles will fail if:

- the `v2_position_history_persistent_tracker` process is missing
- the `ai-bot-v2-position-history-persistent-tracker.service`
  systemd unit is not active
- the `v2:paper:position_history:heartbeat` Redis key is missing,
  TTL ≤ 0, or stale
- the heartbeat payload reports `process_mode` other than
  `persistent_daemon`
- `service_active=false`
- `live_gate` is not `blocked_human_only`
- `live_symbols` is not `[]`
- `writes_legacy_redis`, `writes_exchange_orders`,
  `no_synthesized_accepted_positions=false`,
  `no_fabricated_excursion_metrics=false`,
  `no_shadow_observations_counted_as_accepted=false`, or
  `full_observation_consumption_allowed=true` drift

The user constraints are preserved:

- open positions are NOT required for PASS
- MFE/MAE/ROE are NOT required to be populated; they may be `null`
  when there is no V2-owned open-position evidence
- per-symbol `NO_OPEN_POSITION` is the legitimate steady state

`live_gate=blocked_human_only` and `live_symbols=[]` are unchanged.
No legacy code, runtime, or Redis namespace is touched. No live,
canary, leverage, margin, or approval drift introduced.

## Source Patches

### Continuous Remediation Review Governor

[claude_worklog/tools/codex_continuous_remediation_review_governor.py](claude_worklog/tools/codex_continuous_remediation_review_governor.py)

- `REQUIRED_V2_PROCESSES` gains
  `"position_history_persistent_tracker": "v2_position_history_persistent_tracker"`.
- New constants
  `POSITION_HISTORY_HEARTBEAT_KEY = "v2:paper:position_history:heartbeat"` and
  `POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS = 180`.
- New probe `position_history_heartbeat_probe()` mirroring the
  liquidation-WSS probe shape; reads TTL + payload, derives
  open/no-open counts from `open_position_symbols` /
  `no_open_position_symbols` lists if direct count fields are
  absent.
- `evaluate()` invokes the probe and adds drift checks. All checks
  use `is not None` / `is True` / `is False` guards so absent fields
  remain informational and never spuriously block.
- `summary.position_history_daemon` exposes the probe in the
  governor status payload.

### 8h War-Room Review Governor

[claude_worklog/tools/codex_8h_war_room_review_governor.py](claude_worklog/tools/codex_8h_war_room_review_governor.py)

- `REQUIRED_PROCESSES` gains the same process entry.
- `SYSTEMD_SERVICES` gains
  `"ai-bot-v2-position-history-persistent-tracker.service"`.
- New constants `POSITION_HISTORY_HEARTBEAT_KEY` and
  `POSITION_HISTORY_HEARTBEAT_MAX_AGE_SECONDS = 240`.
- `evaluate()` reads the heartbeat via the existing
  `redis_get_json` helper, applies freshness + drift checks, and
  surfaces a `position_history_heartbeat` block alongside the
  existing `liquidation_wss_heartbeat` block.

All additions are additive: they cannot make a currently-passing
governor cycle become BLOCKED for a payload that already matches
the contract.

## Live Probe Evidence

Running the new probe directly against the live daemon:

| Field | Value |
| ----- | ----- |
| `present` | True |
| `fresh` | True |
| `ttl_seconds` | 891 |
| `process_mode` | `persistent_daemon` |
| `service_active` | True |
| `live_gate` | `blocked_human_only` |
| `live_symbols` | `[]` |
| `writes_legacy_redis` | False |
| `writes_exchange_orders` | False |
| `no_synthesized_accepted_positions` | True |
| `no_fabricated_excursion_metrics` | True |
| `no_shadow_observations_counted_as_accepted` | True |
| `full_observation_consumption_allowed` | False |
| `open_position_symbol_count` | 0 |
| `no_open_position_symbol_count` | 3 |
| `no_open_position_symbols` | `["BTCUSDT","ETHUSDT","SOLUSDT"]` |
| `new_fail_blockers_triggered_against_live_state` | `[]` |

Zero new fail blockers trip against the running daemon. The
governor registration is consistent with the current passing state.

## Validation

| Check | Result |
| ----- | ------ |
| `py_compile` of continuous remediation governor | PASS |
| `py_compile` of 8h war-room governor | PASS |
| Focused tracker + recorder + tools test sweep | PASS (76 of 76) |
| JSON validation of packet outputs | PASS |
| Old-Redis-write scan on patched governors | PASS (0 hits) |
| Approval-token scan on patched governors | PASS (only detection regex; no creation) |
| Live probe vs running daemon: all new checks pass | PASS |

## Safety Posture

All safety state is unchanged:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `places_real_order=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- legacy code: unmodified
- legacy runtime: not stopped, not touched
- old Redis namespaces: not written
- exchange mutation surface: none introduced
- approvals: none created

## Final Decision

`V2_POSITION_HISTORY_TRACKER_GOVERNOR_REGISTRATION_READY`
