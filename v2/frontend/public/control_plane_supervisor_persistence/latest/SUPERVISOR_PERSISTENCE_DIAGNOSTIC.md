# Supervisor Persistence Diagnostic

Generated: `2026-05-12T05:49:07.268576+00:00`

## Diagnosis

Before recovery, `agent_supervisor.py` was not persistent:

- Agent supervisor tmux session present: `False`
- Agent supervisor process alive: `False`
- Supervisor heartbeat age seconds: `1116`
- Queue status age seconds: `1289`
- Scheduler alive: `True`
- Codex watchdog alive: `True`

The scheduler and Codex watchdog were already persistent, but the queue supervisor was absent. The stale heartbeat/status files made the dashboard see an old supervisor state rather than a live process.

## Root Cause

The existing one-shot supervisor start path created a tmux session for `agent_supervisor.py`, but it did not wrap the process in a restart loop. If the supervisor exited, the session disappeared and no durable control-plane session recreated it. The autonomous supervisor path also uses the same `supervisor.lock` as the normal queue supervisor, so running both independent supervisor daemons creates lock contention instead of redundancy.

A second robustness gap was found in `agent_supervisor.py`: while a child `claude`, `codex`, `ollama`, or system-check subprocess was running, the supervisor waited in a blocking child wait and could stop refreshing heartbeat. That made a live supervisor look stale during long child work.

## Actions Required

- Add a rebuild-control-plane wrapper that restarts only non-live control-plane daemons.
- Preserve the single queue-supervisor lock model.
- Keep scheduler and Codex watchdog sessions persistent.
- Keep master planner status explicit but do not start Claude planner in this task unless separately allowed.
- Keep legacy trainer/trader/orchestrator/Redis/VPN outside wrapper scope.
