# Paste into Claude Code — 12h read-only monitor (or run script directly)

Create and run a read-only 12-hour monitor.

It must:
- read old Redis streams read-only
- sample relevant keys
- scan logs if available
- detect missing signal_id
- detect missing confidence
- detect duplicate exchange_order_id
- detect stale signal timestamps
- detect CROSS margin in position snapshots
- detect high leverage
- detect ADJUST_LEVERAGE signals
- detect risk-add actions
- detect risk rejects/skips
- detect execution latency
- detect trader/trainer heartbeats

It must write only to:
./claude_worklog/monitoring/*.jsonl
./claude_worklog/monitoring_summary.md

Do not write to old Redis.
Do not modify old bot.
Do not execute trades.
Do not change configs.

Implementation: `./claude_worklog/tools/read_only_monitor.py` (installed by Cursor Agent).

## Run command

```bash
cd "$HOME/Desktop/AI BOT REBUILD"
export PATH="$HOME/.local/bin:$PATH"
python3 ./claude_worklog/tools/read_only_monitor.py \
  --duration-hours 12 \
  --interval-seconds 60 \
  --output-dir ./claude_worklog/monitoring
```

Optional: run in background:

```bash
nohup python3 ./claude_worklog/tools/read_only_monitor.py \
  --duration-hours 12 \
  --interval-seconds 60 \
  --output-dir ./claude_worklog/monitoring \
  >> ./claude_worklog/monitoring/nohup.out 2>&1 &
```
