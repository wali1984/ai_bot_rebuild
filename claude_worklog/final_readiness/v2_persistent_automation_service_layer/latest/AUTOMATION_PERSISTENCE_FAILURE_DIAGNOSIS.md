# Automation Persistence Failure Diagnosis

Generated: 2026-05-13T23:38:09Z

## Classification

- ORCHESTRATOR_SELECTION_VALID
- SUPERVISOR_DAEMON_NOT_PERSISTENT
- TMUX_FROM_CHAT_HARNESS_NOT_PERSISTENT
- SYSTEMD_USER_PERSISTENCE_REQUIRED
- LIVE_GATE_BLOCKED_HUMAN_ONLY

## Finding

The V2 worker-porting orchestrator selected the correct next worker:

- next worker: `v2_market_ingestor_from_legacy_baseline`
- next action: `dispatch_legacy_baseline_analysis`
- required descriptor: `claude_worklog/agent_supervisor/tasks/claude_port_v2_market_ingestor_from_legacy_baseline.json`

Before this service-layer change, no persistent control-plane process was available to execute the selection. The system had no durable `agent_supervisor.py`, `v2_worker_porting_orchestrator`, parallel scheduler, or Codex watchdog process, and no tmux session survived as a reliable persistence layer.

## Root Cause

Selection was correct. Dispatch was missing because persistence depended on manual shell/tmux startup. A chat-harness-launched shell is not a durable daemon host.

Two additional dispatcher defects were found and fixed while proving autodispatch:

- `dispatch_legacy_baseline_analysis` did not select the Claude task descriptor.
- the supervisor treated existing file-path dependencies as task ids, which blocked the selected V2 task even though the baseline files existed.

## Current Result

Systemd user services are now installed and active. The supervisor has dispatched:

`claude_port_v2_market_ingestor_from_legacy_baseline`

Live remains `blocked_human_only`. Final approval token is absent. Redis trim approval is absent.
