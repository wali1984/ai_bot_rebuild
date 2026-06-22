# V2 Liquidation WSS Daemon Heartbeat Freshness Remediation Report

GO/NO-GO: V2_LIQUIDATION_WSS_DAEMON_HEARTBEAT_FRESHNESS_REMEDIATION_READY

This packet does NOT approve live trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT load any pickle or torch blob. It does NOT synthesize liquidation
events. It writes only to v2:market:liquidations:*. live_gate stays
blocked_human_only. live_symbols stays [].

## Codex fail blockers addressed

- LIQUIDATION_WSS_HEARTBEAT_NOT_FRESH — fixed.
- STATUS_PAYLOAD_NOT_DAEMON_FRESH — fixed.
- HEARTBEAT_TTL_SHORTER_THAN_SESSION_BOUNDARY — fixed.
- systemd PYTHONPATH parsed as /home/wali/Desktop/AI due to unquoted
  path with spaces — fixed.

## Source changes

### v2/backend/app/services/native_ingestors/liquidations_wss.py

- Added module constants.
- write_heartbeat now accepts ttl_seconds (keyword-only, default 180).
- Strictly TTL > interval (180 > 60).

### v2/backend/app/cli/v2_liquidation_wss_loop.py

- New _build_daemon_status_payload builds a status payload with the
  daemon-fresh fields required by the operator dashboard contract.
- New _heartbeat_writer async coroutine refreshes the heartbeat +
  status JSON files every heartbeat_interval_seconds (default 60s).
- New _refresh_freshness writes the heartbeat + status JSON files in
  one atomic step, used at startup, every interval tick, and at
  shutdown.
- New _run_daemon composes the WSS reconnect loop with the heartbeat
  writer task and guarantees three writes: initial (at startup),
  periodic (every interval), and final (after the reconnect loop
  exits).
- _run_with_reconnect now mutates a shared live_state dict in place.
- New CLI flags --heartbeat-interval-seconds and --heartbeat-ttl-seconds.
- main() refuses to run with interval >= ttl and exits with rc=2.
- Status payload schema bumped to v2_liquidation_wss_client_status_v2.

### claude_worklog/systemd/user/ai-bot-v2-liquidation-wss-paper-shadow.service

- Environment lines for PYTHONPATH, LIVE_GATE, and
  V2_LIQUIDATION_WSS_OPT_IN are now double-quoted using systemd
  Environment KEY=value syntax. PYTHONPATH is no longer split on
  the space inside the path component AI BOT REBUILD.

## Tests

Focused WSS test suite added cases:

- test_write_heartbeat_default_ttl_is_180_seconds
- test_write_heartbeat_accepts_custom_ttl
- test_heartbeat_ttl_strictly_greater_than_default_interval
- test_build_daemon_status_payload_has_required_freshness_fields
- test_heartbeat_writer_refreshes_status_and_redis_during_quiet_session
- test_systemd_unit_pythonpath_quoted_for_path_with_spaces
- test_cli_main_blocks_when_interval_not_strictly_below_ttl

Existing safety-invariant test was updated to read the daemon-fresh
fields. Full suite: 25 of 25 pass.

## Daemon restart audit

```
systemctl --user daemon-reload
systemctl --user restart ai-bot-v2-liquidation-wss-paper-shadow.service
systemctl --user is-active -> active
systemctl --user show MainPID -> 3548989
systemctl --user show ActiveState -> active
systemctl --user show SubState -> running
```

Only the V2 liquidation WSS daemon was restarted. No legacy unit
was restarted. No other V2 runtime loop was restarted.

Live process environment raw values:

```
PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD
LIVE_GATE=blocked_human_only
V2_LIQUIDATION_WSS_OPT_IN=true
```

Live process command line raw values:

```
.venv/bin/python3 -m v2.backend.app.cli.v2_liquidation_wss_loop
--total-seconds 86400 --max-seconds-per-session 600
--max-events-per-session 1000
```

## Redis verification

```
redis-cli TTL v2:market:liquidations:heartbeat -> 155 (positive)
redis-cli GET v2:market:liquidations:heartbeat -> daemon-fresh payload
redis-cli scan pattern v2:market:liquidations:latest:*    -> 0 keys
redis-cli scan pattern v2:market:liquidations:aggregate:* -> 0 keys
```

Heartbeat TTL stayed positive across at least one refresh window:
TTL transitioned from 148 to 133 across a 75-second observation
(consistent with one refresh at the 60s tick resetting TTL to 180,
followed by ~47s of decay). No per-symbol latest or aggregate keys
were created, consistent with the no-synthesis invariant during a
quiet-market interval.

## Status payload verification

```
claude_worklog/final_readiness/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json -> refreshed
v2/frontend/public/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json -> refreshed
v2/frontend/public/v2_liquidation_wss_client/latest/operator_dashboard_payload.json -> refreshed
```

Payload contains daemon-fresh fields:
process_mode=persistent_daemon, service_active=true,
opt_in_enabled=true, heartbeat_at, sessions, reconnect_count,
events_received, events_written, last_event_utc, live_gate,
live_symbols, writes_legacy_redis, writes_exchange_orders,
no_synthetic_liquidation_events.

## Runtime continuity

After the restart, the following V2 governors and runtime loops remain
active and unaffected:

- ai-bot-v2-liquidation-wss-paper-shadow.service
- ai-bot-v2-continuous-legacy-log-remediation.service
- ai-bot-v2-legacy-log-intelligence-observer.service
- ai-bot-v2-paper-online-runtime.service
- ai-bot-v2-paper-shadow-observation.service
- ai-bot-v2-feature-snapshot-builder.service
- ai-bot-v2-symbol-universe-publisher.service
- ai-bot-v2-codex-watchdog.service
- ai-bot-v2-agent-supervisor.service

No legacy unit was restarted. No unrelated V2 runtime loop was
restarted. Soak was not interrupted.

## What this packet does NOT do

- Does not approve live trading.
- Does not enable canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not add the daemon to the continuous remediation governor
  fail-blocking process list. That decision waits for Codex re-review.
- Does not modify legacy.
- Does not synthesize liquidation events.
- Does not claim checkpoint compatibility or policy architecture
  parity.
- Does not change leverage or margin.
- Does not place, modify, or cancel exchange entries.
- Does not create approval tokens.

## Safety invariants

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- writes_legacy_redis = false
- writes_exchange_orders = false
- no_synthetic_liquidation_events = true
- no_torch_imported = true
- no_pickle_loaded = true
- no_legacy_filesystem_modified = true

## Outputs

- claude_worklog/final_readiness/v2_liquidation_wss_persistent_daemon_remediation/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_liquidation_wss_persistent_daemon_remediation/latest/V2_LIQUIDATION_WSS_DAEMON_HEARTBEAT_FRESHNESS_REMEDIATION_REPORT.md
- claude_worklog/final_readiness/v2_liquidation_wss_persistent_daemon_remediation/latest/daemon_heartbeat_freshness_status.json
- v2/frontend/public/operator_runtime/v2_liquidation_wss_persistent_daemon_remediation/latest/operator_dashboard_payload.json
- v2/backend/app/services/native_ingestors/liquidations_wss.py (modified)
- v2/backend/app/cli/v2_liquidation_wss_loop.py (modified)
- claude_worklog/systemd/user/ai-bot-v2-liquidation-wss-paper-shadow.service (modified)
- v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py (modified; 25 of 25 pass)
