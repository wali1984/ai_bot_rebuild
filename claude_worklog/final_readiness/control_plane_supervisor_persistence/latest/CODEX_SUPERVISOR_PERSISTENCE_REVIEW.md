# Codex Supervisor Persistence Review

Generated: `2026-05-12T05:49:07.268576+00:00`

## Review Result

`CONTROL_PLANE_SUPERVISOR_PERSISTENCE_CODEX_PASS`

## Challenges Applied

- Supervisor one-shot risk: checked. A tmux restart loop now wraps `agent_supervisor.py`.
- Heartbeat freshness after waiting: checked. The 190-second proof shows heartbeat age `3` seconds.
- Long child task heartbeat: checked. `agent_supervisor.py` now refreshes heartbeat while waiting on child subprocesses.
- Dead lock/PID handling: checked. The start wrapper clears `supervisor.lock` only when the recorded PID is not alive.
- Duplicate daemons: checked. The 190-second snapshot showed one supervisor Python process.
- Live/legacy service scope: checked. Wrapper managed only rebuild-control-plane sessions; legacy trader remained visible/classified and was not stopped.
- Old Redis mutation: no evidence of Redis write commands in this task.
- Exchange mutation: no evidence of order, leverage, margin, position-mode, or live-enable actions.
- Paper-online truth: paper runtime remained fresh in the after-start and after-190-second snapshots.
- Dashboard reporting: operator dashboard payload reports persistence, heartbeat freshness, scheduler/watchdog state, live gate, Redis trim status, and legacy trader visibility.

## Residual Notes

The master planner status file is still stale and the planner process is not running. This task did not restart the Claude master planner because the requested recovery was supervisor persistence only and live services were out of scope. The wrapper status reports that state explicitly instead of hiding it.

## Additional Watchdog Challenge

Codex also challenged whether another rebuild-control-plane daemon could kill the supervisor after the proof. That check found and fixed the watchdog `stop_planner()` call that previously stopped `agent_supervisor.py`. With that patch, watchdog recovery preserves the supervisor daemon.
