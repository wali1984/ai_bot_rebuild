# Persistence Proof

Generated: `2026-05-12T05:49:07.268576+00:00`

## Immediate Check

- Agent supervisor alive: `True`
- Agent supervisor heartbeat age seconds: `2`
- Queue status age seconds: `12`
- Scheduler alive: `True`
- Codex watchdog alive: `True`
- Paper runtime fresh: `True`

## 180 Second Check

The control plane was checked again after a 190-second wait.

- Agent supervisor alive: `True`
- Agent supervisor heartbeat age seconds: `3`
- Queue status age seconds: `13`
- Agent supervisor Python process count: `2`
- Scheduler alive: `True`
- Codex watchdog alive: `True`
- Paper runtime fresh: `True`
- Paper runtime age seconds: `31`

## Duplicate Process Check

The 180-second snapshot contained one supervisor wrapper shell and one `python3 claude_worklog/tools/agent_supervisor.py --daemon` process. No duplicate runaway `agent_supervisor.py` daemons were observed.

## Post-Proof Guard

After the active persistence proof, the agent supervisor tmux session was restarted in `--daemon --dry-run --poll-seconds 30` mode so this control-plane-only task would not keep launching unrelated queued work while validation and commit were performed. The wrapper remains active and can be restarted in active mode by running `start_rebuild_control_plane.sh` without overriding `AGENT_SUPERVISOR_ARGS`.

## Safety

No live trainer/trader/orchestrator/Redis/VPN restart was performed. No old Redis write was performed. No exchange action, leverage change, margin change, or live enablement was performed.

## Final Watchdog-Compatible State

After patching the watchdog not to stop the persistent supervisor, the agent supervisor was restarted in dry-run persistence mode and rechecked:

- Agent supervisor alive: `True`
- Agent supervisor heartbeat age seconds: `5`
- Agent supervisor tmux session: `True`
- Scheduler alive: `True`
- Codex watchdog alive: `True`
