# Control Plane Supervisor Persistence Recovery Report

Generated: `2026-05-12T05:49:07.268576+00:00`

## Result

`CONTROL_PLANE_SUPERVISOR_PERSISTENCE_RECOVERY_READY`

## What Changed

- Added/repaired rebuild-control-plane wrapper scripts for start, stop, and status.
- Recovered `agent_supervisor.py` persistence in tmux.
- Kept existing scheduler and Codex watchdog persistent.
- Patched supervisor heartbeat behavior so long child tasks no longer make a live supervisor look stale.
- Captured immediate and 190-second status snapshots.
- Refreshed dashboard payload for control-plane persistence.

## Current State

- Agent supervisor persistent: `True`
- Current heartbeat age seconds: `5`
- Scheduler running: `True`
- Codex watchdog running: `True`
- Governor selection file present: `True`
- Master planner running: `False`
- Paper runtime fresh: `True`
- Legacy trader visible/classified: `True`
- Live gate: `blocked_human_only`
- Redis trim: `deferred_non_blocking`

## Safety Outcome

No legacy bot code was modified. No old Redis write/delete/trim command was run. No Redis trim approval file was created. No live trainer/trader/orchestrator/Redis/VPN restart was performed. No exchange order, leverage change, margin change, or live trading enablement was performed.

## Next Milestone

`LEGACY_TRAINER_GPU_PARITY_AND_V2_WRAPPER_VALIDATION_READY`

## Watchdog Compatibility

Post-proof validation found that Codex watchdog recovery could still stop `agent_supervisor.py`. This was repaired by scoping `codex_non_live_watchdog.py::stop_planner()` away from the persistent queue supervisor. Final status after the repair shows supervisor alive with heartbeat age `5` seconds.
