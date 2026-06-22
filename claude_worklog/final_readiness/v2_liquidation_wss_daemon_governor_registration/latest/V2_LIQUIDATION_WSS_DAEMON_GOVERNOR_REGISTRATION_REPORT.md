# V2 Liquidation WSS Daemon Governor Registration

Generated: `2026-05-21T03:30:30Z`

GO/NO-GO: `V2_LIQUIDATION_WSS_DAEMON_GOVERNOR_REGISTRATION_READY`

## Scope

Following the Codex PASS on the persistent liquidation WSS daemon
heartbeat/status freshness remediation, this packet ensures both
governor surfaces (continuous remediation review governor and 8h
war-room review governor) treat the persistent liquidation WSS
daemon as a first-class expected dependency. Future cycles must
fail if:

- the `v2_liquidation_wss_loop` process is missing
- the `ai-bot-v2-liquidation-wss-paper-shadow.service` systemd unit
  is not active
- the `v2:market:liquidations:heartbeat` Redis key is missing,
  TTL ≤ 0, or stale
- the heartbeat payload reports `process_mode` other than
  `persistent_daemon`
- `live_gate` is not `blocked_human_only`
- `live_symbols` is not `[]`
- `writes_legacy_redis`, `writes_exchange_orders`, or synthetic-event
  drift is reported

No legacy code, runtime, or Redis namespace is modified. No live
trading, canary, leverage, margin, or approval drift is introduced.
`live_gate=blocked_human_only` and `live_symbols=[]` are unchanged.

## Pre-Existing Registration (Confirmed By Direct Read)

Both governors already register the process and (where applicable)
the systemd unit. This packet did NOT introduce that registration —
it confirmed it and tightened the drift checks.

### Continuous Remediation Review Governor

[claude_worklog/tools/codex_continuous_remediation_review_governor.py](claude_worklog/tools/codex_continuous_remediation_review_governor.py)

- `REQUIRED_V2_PROCESSES["liquidation_wss_paper_shadow_daemon"] = "v2_liquidation_wss_loop"`
  ([line 64](claude_worklog/tools/codex_continuous_remediation_review_governor.py#L64))
- `LIQUIDATION_WSS_HEARTBEAT_KEY = "v2:market:liquidations:heartbeat"`
  ([line 67](claude_worklog/tools/codex_continuous_remediation_review_governor.py#L67))
- `LIQUIDATION_WSS_HEARTBEAT_MAX_AGE_SECONDS = 180`
  ([line 68](claude_worklog/tools/codex_continuous_remediation_review_governor.py#L68))
- `liquidation_wss_heartbeat_probe()` ([line 280](claude_worklog/tools/codex_continuous_remediation_review_governor.py#L280))
  reads the heartbeat payload and exposes `process_mode`,
  `service_active`, `opt_in_enabled`, `no_synthetic_liquidation_events`,
  `writes_legacy_redis`, `writes_exchange_orders`, `live_gate`,
  `live_symbols`.

### 8h War-Room Review Governor

[claude_worklog/tools/codex_8h_war_room_review_governor.py](claude_worklog/tools/codex_8h_war_room_review_governor.py)

- `REQUIRED_PROCESSES["liquidation_wss_daemon"] = "v2_liquidation_wss_loop"`
  ([line 81](claude_worklog/tools/codex_8h_war_room_review_governor.py#L81))
- `SYSTEMD_SERVICES` includes `"ai-bot-v2-liquidation-wss-paper-shadow.service"`
  ([line 93](claude_worklog/tools/codex_8h_war_room_review_governor.py#L93))
- `LIQUIDATION_HEARTBEAT_KEY = "v2:market:liquidations:heartbeat"`
  ([line 74](claude_worklog/tools/codex_8h_war_room_review_governor.py#L74))

## Source Patch

Both governors were extended to emit additional fail blockers when
the heartbeat payload diverges from the persistent-daemon contract.
All additions are additive: they cannot make an existing PASS
become BLOCKED for a payload that already matches the contract
(observed values are `persistent_daemon` / `blocked_human_only` /
`[]`).

### Continuous Remediation Review Governor

Added (after the existing `writes_legacy_redis` / `writes_exchange_orders`
/ `no_synthetic_liquidation_events` drift checks):

```python
if liquidation_wss_heartbeat["present"]:
    observed_mode = liquidation_wss_heartbeat.get("process_mode")
    if observed_mode not in (None, "persistent_daemon"):
        fail_blockers.append(
            f"LIQUIDATION_WSS_DAEMON_PROCESS_MODE_NOT_PERSISTENT_DAEMON:{observed_mode}"
        )
    observed_gate = liquidation_wss_heartbeat.get("live_gate")
    if observed_gate not in (None, LIVE_GATE):
        fail_blockers.append(
            f"LIQUIDATION_WSS_DAEMON_LIVE_GATE_DRIFT:{observed_gate}"
        )
    observed_symbols = liquidation_wss_heartbeat.get("live_symbols")
    if observed_symbols not in (None, []):
        fail_blockers.append(
            f"LIQUIDATION_WSS_DAEMON_LIVE_SYMBOLS_DRIFT:{observed_symbols}"
        )
```

`None` is treated as "field not yet emitted by older payloads" and
is informational, not a fail. This is intentional: payloads emitted
before the persistent-daemon remediation lacked these fields, and we
do not want to spuriously block on legacy heartbeat shape. Drift is
only flagged when the field is *present* and *wrong*.

### 8h War-Room Review Governor

Added the same three drift checks against `heartbeat_payload`,
guarded by `if heartbeat_payload:` so they only fire when there is a
payload to inspect. Also added `process_mode`, `live_gate`,
`live_symbols`, `service_active`, `opt_in_enabled`, and matching
`expected_*` fields to the `liquidation_wss_heartbeat` block in the
governor status, so the operator dashboard surfaces the contract
even on a passing cycle.

## Per-Symbol Liquidation Keys Policy

Per-symbol keys remain OPTIONAL:

- `v2:market:liquidations:latest:{symbol}`
- `v2:market:liquidations:aggregate:{symbol}`
- `v2:market:liquidations:{symbol}`

No events means no keys. Readiness must NOT require any per-symbol
liquidation key; only the heartbeat is required. The Codex review
that preceded this packet observed:

> total liquidation keys: `1`
> latest per-symbol keys: `0`
> aggregate per-symbol keys: `0`
> per-symbol liquidation keys: `0`

and still returned `CODEX_PASS`. This packet preserves that policy:
no fail blocker depends on per-symbol key presence.

## Validation

| Check                                                            | Result |
| ---------------------------------------------------------------- | ------ |
| `py_compile` of continuous remediation governor                  | PASS   |
| `py_compile` of 8h war-room governor                             | PASS   |
| Focused liquidation/WSS test selection (`-k "liquidation or wss"`) | PASS (55 of 55) |
| Existing governor passing state preserved (additive checks only) | PASS   |
| JSON validation of new packet outputs                            | PASS   |

## Safety Posture

All safety state is unchanged:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`
- Legacy bot mutation: none
- Exchange mutation: none
- Old Redis writes: none
- Codex PASS marker creation: none

## Final Decision

`V2_LIQUIDATION_WSS_DAEMON_GOVERNOR_REGISTRATION_READY`
