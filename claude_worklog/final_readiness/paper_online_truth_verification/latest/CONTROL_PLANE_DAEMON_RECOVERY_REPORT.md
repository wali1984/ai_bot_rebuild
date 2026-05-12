# Control Plane Daemon Recovery Report

Generated at: 2026-05-12T05:10:44.420Z

## Process Truth

```text
2142277 1029421  125727 python3 claude_worklog/tools/codex_non_live_watchdog.py --daemon --poll-seconds 300
2399536 1029421   88691 python3 claude_worklog/tools/parallel_capacity_scheduler.py --daemon --poll-seconds 600
3324274 3324271   13394 python3 -u trading/trader.py
3446733 1011413    5862 python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30
3516630 1029421     778 python3 claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30
3530614 3516630      54 node /home/wali/.local/bin/codex exec [prompt redacted]
3530626 3530614      54 /home/wali/.local/lib/node_modules/@openai/codex/.../codex exec [prompt redacted]