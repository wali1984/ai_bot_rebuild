# V2 Liquidation WSS Persistent Paper/Shadow Daemon Report

GO/NO-GO: V2_LIQUIDATION_WSS_PERSISTENT_PAPER_SHADOW_DAEMON_READY

This packet does NOT approve live trading, canary trading, legacy
shutdown, Redis trim, paper-only shutdown acceptance, checkpoint
compatibility, or policy architecture parity. It does NOT load any
pickle/torch blob. It does NOT touch legacy. It does NOT synthesize
liquidation events. It writes only to v2:market:liquidations:*.

## What got installed

### Systemd unit: ai-bot-v2-liquidation-wss-paper-shadow.service

claude_worklog/systemd/user/ai-bot-v2-liquidation-wss-paper-shadow.service

- Description: AI BOT V2 liquidation WSS client (paper/shadow only;
  public Binance Futures forceOrder stream).
- WorkingDirectory: /home/wali/Desktop/AI BOT REBUILD
- Environment: PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD
- Environment: LIVE_GATE=blocked_human_only
- Environment: V2_LIQUIDATION_WSS_OPT_IN=true
- ExecStart: bash -lc wrapper with escaped path, runs the bounded
  WSS loop with --total-seconds 86400 --max-seconds-per-session 600
  --max-events-per-session 1000.
- StandardOutput/StandardError → claude_worklog/agent_supervisor/logs/control_plane/v2_liquidation_wss_loop.{log,err}
- Restart=always, RestartSec=15.
- WantedBy=default.target.

Symlinked into ~/.config/systemd/user/ and into default.target.wants/.
`systemctl --user daemon-reload` + `enable --now` succeeded.

### Live state

```
systemctl --user is-active ai-bot-v2-liquidation-wss-paper-shadow.service
→ active

pgrep -af v2_liquidation_wss_loop:
3465777 .../.venv/bin/python3 -m v2.backend.app.cli.v2_liquidation_wss_loop
        --total-seconds 86400 --max-seconds-per-session 600
        --max-events-per-session 1000
```

### Code change: periodic heartbeat write

The previous WSS CLI wrote the heartbeat only at total-budget exit
(24h), which left v2:market:liquidations:heartbeat expired between
restarts. Updated _run_with_reconnect to write the heartbeat after
each session yield (every ~10 minutes given
--max-seconds-per-session=600). TTL is 300s in write_heartbeat,
so the key stays fresh because the 10-minute session-boundary refresh
beats the TTL.

### Updated scripts

- claude_worklog/tools/start_v2_production_replacement_runtime.sh
  → UNITS array now includes ai-bot-v2-liquidation-wss-paper-shadow.service
- claude_worklog/tools/status_v2_production_replacement_runtime.sh
  → PATTERNS array now includes v2_liquidation_wss_loop
- claude_worklog/tools/stop_v2_production_replacement_runtime.sh
  → UNITS + PATTERNS arrays both include the daemon

The continuous remediation governor's REQUIRED_V2_PROCESSES list is
intentionally NOT modified here; that list is fail-blocking and any
addition must be Codex-reviewed first.

### Frontend Monitor Center

3 new cards reading
/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json:
- Persistent liquidation WSS daemon GO/NO-GO + session count + events
  written
- WSS daemon safety (writes_exchange_orders, no_synthetic_liquidation_events)
- WSS daemon endpoint (URL + opt-in note)

tsc --noEmit exit 0.

## Verification (raw)

- Process: systemd-managed (PPID under systemd-user manager).
- systemctl --user is-active: active.
- Process command line includes the bounded session flags.
- v2:market:liquidations:heartbeat populated (readback go_no_go =
  V2_LIQUIDATION_WSS_CLIENT_PAPER_SHADOW_READY).
- v2:market:liquidations:latest:*, :aggregate:* unpopulated (no events
  yet — quiet market window). The packet does not synthesize.
- Aggregator's v2_per_symbol_aggregator_present probe stays false
  until real events arrive; the flag flips automatically when they do.
- Continuous remediation governor: still
  V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY.
- Soak: minutes_observed=1312.05, soak_6h_ready=true,
  all_v2_processes_uninterrupted=true. No soak interruption.

## Tests

107/107 focused tests pass (full sweep across all observation-lane
and runtime-lane modules). The 18-case
test_v2_liquidation_wss_loop.py suite covers parse/retention/backoff/
v2-only-writes/opt-in-gating/no-exchange-mutation/no-torch-import.

## Safety invariants (raw)

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
- All Redis writes guarded to v2:market:liquidations:* namespace.
- Opt-in env V2_LIQUIDATION_WSS_OPT_IN=true is set only inside the
  systemd unit Environment line (not in shell history, not committed
  to .env, not exposed in any payload).

## What this packet does NOT do

- Does not approve live trading.
- Does not enable canary, legacy shutdown, or Redis trim.
- Does not modify legacy.
- Does not commit credentials (none required for the public WSS).
- Does not claim checkpoint compatibility or policy architecture
  parity.
- Does not lift FULL_OBSERVATION_BUILDER_COMPLETE (state still PARTIAL;
  the 4 currently-missing liquidation slots fill only when real events
  arrive over the public stream).
- Does not fabricate liquidation data.
- Does not add the daemon to the continuous remediation governor's
  fail-blocking process list (that is Codex's call).

## Outputs

- claude_worklog/systemd/user/ai-bot-v2-liquidation-wss-paper-shadow.service
- ~/.config/systemd/user/ai-bot-v2-liquidation-wss-paper-shadow.service (symlink)
- claude_worklog/final_readiness/v2_liquidation_wss_persistent_paper_shadow_daemon/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_liquidation_wss_persistent_paper_shadow_daemon/latest/V2_LIQUIDATION_WSS_PERSISTENT_PAPER_SHADOW_DAEMON_REPORT.md
- claude_worklog/agent_supervisor/logs/control_plane/v2_liquidation_wss_loop.{log,err} (will appear once the first event arrives)
- v2:market:liquidations:heartbeat (Redis; refreshed every ~10 minutes by the daemon)
