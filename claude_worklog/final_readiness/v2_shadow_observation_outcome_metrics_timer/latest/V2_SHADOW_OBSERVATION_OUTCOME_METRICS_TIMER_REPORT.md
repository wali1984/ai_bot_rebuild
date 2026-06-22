# V2 Shadow Observation Outcome Metrics Timer Report

GO/NO-GO: V2_SHADOW_OBSERVATION_OUTCOME_METRICS_TIMER_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT loosen the strict paper-fill gate. It does NOT open the gate or
introduce any new accepted fill. It does NOT touch accepted-position
MFE/MAE/ROE. It does NOT claim checkpoint compatibility or policy
architecture parity.

## What was installed

Two systemd user units that fire the existing
`v2_paper_shadow_outcome_metrics --once` CLI on a 60-second cadence,
so shadow / no-trade outcome metrics refresh continuously without
relying on a Claude session staying open.

### claude_worklog/systemd/user/ai-bot-v2-shadow-outcome-metrics.service

- `Type=oneshot` (timer-driven, no long-running process)
- `WorkingDirectory=/home/wali/Desktop/AI BOT REBUILD`
- `Environment="PYTHONPATH=/home/wali/Desktop/AI BOT REBUILD"`
- `Environment="LIVE_GATE=blocked_human_only"`
- `ExecStart=/usr/bin/env bash -lc 'exec /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python3 -m v2.backend.app.cli.v2_paper_shadow_outcome_metrics --once'`
  - Uses the proven `bash -lc` wrapper + backslash-escaped spaces (same
    pattern as the liquidation-WSS daemon + 8h war-room timer + paper
    trade management loop), so the path that contains spaces never
    triggers a `203/EXEC` failure on restart.
- After: `ai-bot-v2-trade-management-paper-loop.service` (so the
  shadow-outcome tick fires after the paper writer has refreshed its
  shadow / held rows).
- stdout / stderr append to
  `claude_worklog/agent_supervisor/logs/control_plane/v2_paper_shadow_outcome_metrics.{log,err}`.

### claude_worklog/systemd/user/ai-bot-v2-shadow-outcome-metrics.timer

- `OnBootSec=30s`, `OnUnitActiveSec=60s`
- `Persistent=true` (missed ticks replay)
- `AccuracySec=10s`
- Drives the `.service` above.

### Helper script (none added)

The shadow-outcome timer reuses the existing CLI; no new
start/status/stop shell helpers were added. The existing
`status_v2_8h_war_room.sh` pattern is sufficient guidance for
operator use of `systemctl --user`.

## Install + first tick (raw)

```
systemctl --user daemon-reload
systemctl --user enable --now ai-bot-v2-shadow-outcome-metrics.timer
  -> symlink /home/wali/.config/systemd/user/timers.target.wants/...
     -> /home/wali/Desktop/AI BOT REBUILD/claude_worklog/systemd/user/ai-bot-v2-shadow-outcome-metrics.timer
systemctl --user is-active   ai-bot-v2-shadow-outcome-metrics.timer  -> active
systemctl --user is-enabled  ai-bot-v2-shadow-outcome-metrics.timer  -> enabled
```

The first tick fired immediately after `enable --now`, producing:

```
redis-cli TTL v2:paper:shadow_outcome:heartbeat   -> 587
redis-cli TTL v2:paper:shadow_outcome:BTCUSDT     -> 587
redis-cli TTL v2:paper:shadow_outcome:ETHUSDT     -> 587
redis-cli TTL v2:paper:shadow_outcome:SOLUSDT     -> 587
```

Heartbeat payload (excerpted, raw):

```
label_counts = {SHADOW_OUTCOME_ONLY: 2, HELD_OUTCOME_ONLY: 1}
outcome_count = 3
allowed_redis_writes = [
  v2:paper:shadow_outcome:{symbol},
  v2:paper:shadow_outcome:heartbeat
]
counted_as_accepted_position = false
counted_as_fill = false
affects_pnl_ledger = false
opens_paper_fill_gate = false
approves_live / canary / legacy_shutdown / redis_trim = false (all)
writes_legacy_redis / writes_exchange_orders = false
live_gate = blocked_human_only
live_symbols = []
```

Worklog + public status JSON were refreshed by the same tick (ages
under 60s).

## Continuous remediation governor enrollment

NOT done in this packet. Per the operator's instruction:

> Do not add to fail-blocking continuous remediation governor until
> Codex reviews this timer.

The continuous-remediation governor's `REQUIRED_V2_PROCESSES` list
was not modified. Enrollment is a separate operator/Codex decision.

## Safety boundary

The shadow-outcome service module's `_safe_redis_set` allowlist (from
the prior packet) refuses every Redis key except
`v2:paper:shadow_outcome:*` and the heartbeat. The timer-driven CLI
inherits that boundary; it CANNOT write to accepted-position keys,
the paper ledger, the paper heartbeat, or any legacy namespace.
Tests in the prior packet prove this directly. The timer cannot
loosen any safety property because it just invokes the CLI on a
schedule.

## Frontend / Monitor Center / /market / /admin/war-room

The CLI writes:

- `v2/frontend/public/v2_shadow_observation_outcome_metrics/latest/operator_dashboard_payload.json`
- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics/latest/shadow_outcome_metrics_status.json`

Both are now refreshed continuously by the timer. The realtime user
website's existing `MISSING/STALE` render contract automatically
picks up the timer-refreshed payload — no frontend code changes
needed in this packet to surface live shadow-outcome data.

## What this packet does NOT do

- Does not approve real trading.
- Does not approve canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy.
- Does not pause V2 runtime.
- Does not change leverage or margin.
- Does not loosen the strict paper-fill gate.
- Does not open the gate.
- Does not introduce any new accepted fill.
- Does not touch accepted-position MFE/MAE/ROE.
- Does not affect the PnL ledger.
- Does not add the shadow-outcome service to the continuous
  remediation governor's fail-blocking process list.
- Does not place, modify, or cancel exchange entries.
- Does not synthesize prices.
- Does not claim checkpoint compatibility.
- Does not claim policy architecture parity.

## Outputs

- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics_timer/latest/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics_timer/latest/V2_SHADOW_OBSERVATION_OUTCOME_METRICS_TIMER_REPORT.md`
- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics_timer/latest/shadow_outcome_metrics_timer_status.json`
- `v2/frontend/public/v2_shadow_observation_outcome_metrics_timer/latest/operator_dashboard_payload.json`
- `claude_worklog/systemd/user/ai-bot-v2-shadow-outcome-metrics.service` (new)
- `claude_worklog/systemd/user/ai-bot-v2-shadow-outcome-metrics.timer` (new)
- `~/.config/systemd/user/ai-bot-v2-shadow-outcome-metrics.service` (symlink)
- `~/.config/systemd/user/ai-bot-v2-shadow-outcome-metrics.timer` (symlink)
- `~/.config/systemd/user/timers.target.wants/ai-bot-v2-shadow-outcome-metrics.timer` (symlink)
