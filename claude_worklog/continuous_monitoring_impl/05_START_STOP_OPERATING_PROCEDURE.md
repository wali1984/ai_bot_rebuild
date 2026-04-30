# 05 Start/Stop Operating Procedure (For Later Use)

This procedure defines exact commands for later execution. Do not execute now.

## Start continuous read-only monitor (later)

1. Open workspace:
- `cd "$HOME/Desktop/AI BOT REBUILD"`

2. Start in tmux (recommended):
- `tmux new-session -d -s ai_bot_continuous_read_only 'cd "$HOME/Desktop/AI BOT REBUILD"; python3 claude_worklog/tools/read_only_monitor.py --continuous --interval-seconds 60 --output-dir ./claude_worklog/monitoring --packet-output-dir ./claude_worklog/continuous_monitoring/packets'`

3. Start dashboard (optional, detached):
- `./claude_worklog/tools/launch_runtime_monitor_dashboard.sh`

## Health checks (later)

- `cd "$HOME/Desktop/AI BOT REBUILD"`
- `tmux ls | grep ai_bot_continuous_read_only`
- `pgrep -af "read_only_monitor.py"`
- `ls -lh claude_worklog/continuous_monitoring/packets/hourly | tail`
- `ls -lh claude_worklog/continuous_monitoring/packets/alerts | tail`
- `python3 claude_worklog/tools/runtime_monitor_dashboard.py --once`

## Stop procedure (later, graceful)

- `cd "$HOME/Desktop/AI BOT REBUILD"`
- `tmux send-keys -t ai_bot_continuous_read_only C-c`
- `sleep 2`
- `tmux ls | grep ai_bot_continuous_read_only || echo "stopped"`

## Safety reminders
- Monitor must remain read-only.
- Never execute Redis write/delete commands in monitoring procedure.
