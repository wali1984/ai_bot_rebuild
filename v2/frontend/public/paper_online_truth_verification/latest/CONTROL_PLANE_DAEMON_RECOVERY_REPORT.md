# Control Plane Daemon Recovery Report

Generated at: 2026-05-12T05:24:43.685Z

## Process Truth

```text
2142277 1029421  126547 python3 claude_worklog/tools/codex_non_live_watchdog.py --daemon --poll-seconds 300
2399536 1029421   89511 python3 claude_worklog/tools/parallel_capacity_scheduler.py --daemon --poll-seconds 600
3324274 3324271   14214 python3 -u trading/trader.py
3446733 1011413    6682 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30
```

## Tmux State

```text
--- ai_bot_agent_supervisor
MISSING
--- ai_bot_autonomous_agent_supervisor
MISSING
--- ai_bot_parallel_capacity_scheduler
2399536 python3 0
--- ai_bot_codex_non_live_watchdog
2142277 python3 0
```

## Status Payloads

- Supervisor heartbeat last_loop_ts: `2026-05-12T05:23:34.643549+00:00`
- Queue generated_at: `2026-05-12T05:20:41.266105+00:00`
- Current task: `none`
- Next task: `codex_recover_fail_marker_2ic_replay_backtest_runner_composition_root_codex_go_no_go`

## Recovery Result

- Agent supervisor daemon: NOT_RUNNING_FINAL_CHECK
- Parallel capacity scheduler: RUNNING
- Codex watchdog: RUNNING
- Autonomous supervisor tmux: NOT_RUNNING_FINAL_CHECK

Final control-plane blocker: Agent supervisor daemon is not persistent at final verification; scheduler and Codex watchdog remain running.

No live trainer/trader/orchestrator/Redis/VPN restart was performed. No exchange order, leverage change, margin change, live enablement, or old Redis write was performed.
