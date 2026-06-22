# V2 8h War-Room Automation Daemon Report

GO/NO-GO: V2_8H_WAR_ROOM_AUTOMATION_DAEMON_READY

This packet does NOT approve real trading, canary trading, exchange
mutation, leverage/margin changes, legacy shutdown, Redis trim, or
paper-only shutdown acceptance. It does NOT modify legacy. It does
NOT pause the V2 runtime. It does NOT write old Redis keys. It does
NOT enable provider one-shots under 403. It does NOT start the
policy architecture port. It does NOT claim checkpoint compatibility
or policy architecture parity.

## Files installed

- claude_worklog/tools/v2_8h_war_room_daemon.py
- claude_worklog/systemd/user/ai-bot-v2-8h-war-room.service
- claude_worklog/systemd/user/ai-bot-v2-8h-war-room.timer
- claude_worklog/tools/start_v2_8h_war_room.sh
- claude_worklog/tools/status_v2_8h_war_room.sh
- claude_worklog/tools/stop_v2_8h_war_room.sh
- v2/backend/tests/integration/cli/test_v2_8h_war_room_daemon.py

Symlinks created:

- ~/.config/systemd/user/ai-bot-v2-8h-war-room.service
- ~/.config/systemd/user/ai-bot-v2-8h-war-room.timer
- ~/.config/systemd/user/timers.target.wants/ai-bot-v2-8h-war-room.timer

## Daemon design

- Modes: --once (default; preferred for systemd timer), --loop with
  --deadline-hours (default 8) and --cycle-seconds (default 300).
- State file persists across runs at
  claude_worklog/final_readiness/v2_8h_war_room/latest/war_room_state.json
  so relaunch resumes rather than duplicating task spam.
- Per-cycle outputs:
  - cycle_id, started_at, finished_at
  - tier_5m_executed / tier_15m_executed / tier_30m_executed /
    tier_60m_executed flags
  - runtime_checks (Lane A snapshot)
  - gaps (Lane B classifications)
  - fixes_applied (Lane G; empty when NO_ACTION_REQUIRED_WITH_EVIDENCE)
  - codex_reviews_queued (Lane G summary)
- Append-only cycle history at
  claude_worklog/final_readiness/v2_8h_war_room/latest/cycle_history.jsonl

## Cycle tiers

Every 5 minutes (Lane A):

- continuous remediation governor go_no_go + fail_blockers
- V2 process count vs required
- soak health + minutes_observed
- liquidation WSS heartbeat TTL + payload presence
- systemd service states (9 watched services)
- v2:* namespace counts (8 namespaces)
- full observation builder state + per-symbol generated dim
- live_gate and live_symbols invariants

Every 15 minutes (Lane B):

- gap matrix for BTCUSDT, ETHUSDT, SOLUSDT
- per-symbol classifications across the 10-class taxonomy
  (CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED,
  FULL_OBSERVATION_PARTIAL, FEATURE_FRESHNESS_NOT_CURRENT,
  PAPER_FILL_GATE_STRICT_BLOCK, MISSING_LEGACY_LOG_ACTION_EVIDENCE,
  V2_POSITION_HISTORY_MISSING,
  ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING,
  ORCHESTRATOR_DECISION_MISMATCH, RISK_GATE_MISMATCH,
  UNKNOWN_REQUIRES_CODEX_REVIEW)
- aggregated counts surface where the work is

Every 30 minutes (Lane C/D/E):

- full observation builder status refresh via existing CLI
- Binance top-10 dashboard feed refresh when heartbeat is older than
  30 minutes (otherwise skipped to respect public-endpoint budget)
- Nansen / LunarCrush one-shots NOT triggered by the daemon under 403
- frontend / public payloads kept in sync via the same CLI

Every 60 minutes (Lane G):

- narrow-fix evaluation against the gap matrix
- Codex review queue refresh
- explicit NO_ACTION_REQUIRED_WITH_EVIDENCE emission when every
  observed blocker is owned by the operator, the burndown lanes, or
  already tracked under its own packet
- ZERO broad audit tasks, ZERO duplicate checkpoint tasks, ZERO
  policy architecture port, ZERO checkpoint compatibility claim

## Safety boundary (raw)

`safe_redis_set` refuses any key other than
`v2:war_room:heartbeat`. Tests prove this directly. A cycle bug
cannot leak writes into other v2:* namespaces, let alone legacy
namespaces. The daemon's only Redis surface is the heartbeat key.

Tested forbidden write attempts (all refused):

- v2:market:liquidations:heartbeat
- v2:paper:positions
- v2:altdata:nansen:status
- prediction:BTCUSDT (legacy namespace)
- signals:trading:primary (legacy namespace)

## Verification (raw)

```
systemctl --user is-active   ai-bot-v2-8h-war-room.timer   -> active
systemctl --user is-enabled  ai-bot-v2-8h-war-room.timer   -> enabled
systemctl --user list-timers --all                          -> shows next/last run
redis-cli TTL v2:war_room:heartbeat                         -> 525 (positive)
redis-cli GET v2:war_room:heartbeat                         -> live daemon payload
```

A foreground `--once` run with all tiers forced succeeded:

```
{"cycle_id": "wr_<id>",
 "go_no_go": "V2_8H_CONTINUOUS_WAR_ROOM_READY_PROGRESS_MADE",
 "tier_15m_executed": true,
 "tier_30m_executed": true,
 "tier_60m_executed": true}
```

The systemd timer fired its own tick immediately after install
(cycle_count incremented to 2 after the manual cycle), confirming
the timer-driven execution path is live.

## Tests

9/9 pass in `test_v2_8h_war_room_daemon.py`:

- module loads without torch / pickle import
- safe_redis_set boundary refuses every key except the heartbeat
- tier_15m / tier_30m / tier_60m due-time logic
- deadline_exceeded(8h) crossing
- tier_60m emits NO_ACTION_REQUIRED_WITH_EVIDENCE when every
  observed blocker is owned externally
- daemon source contains no exchange-mutation verbs (piecewise
  composition check)
- status payload carries every safety invariant
- run_one_cycle end-to-end with FakeRedis writes status JSON +
  heartbeat (heartbeat is the only Redis key written)
- run_one_cycle never invokes the Nansen / LunarCrush provider
  one-shot CLIs

## What this packet does NOT do

- Does not approve real trading.
- Does not enable canary, legacy shutdown, Redis trim, or paper-only
  shutdown acceptance.
- Does not modify legacy. Does not stop or restart legacy. Does not
  execute legacy scripts.
- Does not call provider APIs under 403.
- Does not write old Redis keys; the daemon's only Redis write is the
  war-room heartbeat.
- Does not place, modify, or cancel exchange entries.
- Does not adjust leverage or margin.
- Does not start the policy architecture port.
- Does not claim checkpoint compatibility.
- Does not claim policy architecture parity.

## Outputs

- claude_worklog/final_readiness/v2_8h_war_room_automation_daemon/latest/GO_NO_GO.md
- claude_worklog/final_readiness/v2_8h_war_room_automation_daemon/latest/V2_8H_WAR_ROOM_AUTOMATION_DAEMON_REPORT.md
- claude_worklog/final_readiness/v2_8h_war_room_automation_daemon/latest/automation_daemon_status.json
- v2/frontend/public/operator_runtime/v2_8h_war_room_automation_daemon/latest/operator_dashboard_payload.json
- claude_worklog/tools/v2_8h_war_room_daemon.py (new)
- claude_worklog/systemd/user/ai-bot-v2-8h-war-room.service (new)
- claude_worklog/systemd/user/ai-bot-v2-8h-war-room.timer (new)
- claude_worklog/tools/start_v2_8h_war_room.sh (new)
- claude_worklog/tools/status_v2_8h_war_room.sh (new)
- claude_worklog/tools/stop_v2_8h_war_room.sh (new)
- v2/backend/tests/integration/cli/test_v2_8h_war_room_daemon.py (new; 9/9 pass)
- ~/.config/systemd/user/ai-bot-v2-8h-war-room.service (symlink)
- ~/.config/systemd/user/ai-bot-v2-8h-war-room.timer (symlink)
