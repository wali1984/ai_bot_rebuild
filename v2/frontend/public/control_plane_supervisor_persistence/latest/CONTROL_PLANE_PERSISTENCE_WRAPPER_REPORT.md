# Control Plane Persistence Wrapper Report

Generated: `2026-05-12T05:49:07.268576+00:00`

## Scripts Added/Repaired

- `claude_worklog/tools/start_rebuild_control_plane.sh`
- `claude_worklog/tools/stop_rebuild_control_plane.sh`
- `claude_worklog/tools/status_rebuild_control_plane.sh`

## Managed Scope

The wrapper manages only rebuild-control-plane daemons:

- `agent_supervisor.py`
- `parallel_capacity_scheduler.py`
- `codex_non_live_watchdog.py`

## Explicitly Not Managed

- legacy trainer
- legacy trader
- legacy orchestrator
- Redis
- VPN
- exchange services

## Persistence Behavior

`start_rebuild_control_plane.sh` creates tmux-backed restart loops, avoids duplicate sessions, clears `supervisor.lock` only when the recorded PID is verified dead, writes runtime start/status records under ignored supervisor runtime paths, and appends control-plane events to ignored `events.jsonl`.

`stop_rebuild_control_plane.sh` stops only the rebuild control-plane tmux sessions and does not kill legacy/live process patterns.

`status_rebuild_control_plane.sh` emits human-readable status and JSON with PID/process lines, tmux state, heartbeat age, status freshness, scheduler/watchdog/planner state, paper runtime age, live gate, Redis trim state, and legacy trader visibility.

## Supervisor Heartbeat Patch

`agent_supervisor.py` now refreshes heartbeat while waiting on child subprocesses. This prevents long safe non-live `codex exec`, `claude --print`, `ollama run`, or system-check tasks from making a live supervisor look stale.

## Current Wrapper State

- Agent supervisor tmux: `True`
- Agent supervisor alive: `True`
- Agent supervisor args: `--daemon --dry-run --poll-seconds 30`
- Scheduler alive: `True`
- Codex watchdog alive: `True`
- Master planner alive: `False`
- Master planner policy: `not started by rebuild control-plane wrapper unless separately allowed`
