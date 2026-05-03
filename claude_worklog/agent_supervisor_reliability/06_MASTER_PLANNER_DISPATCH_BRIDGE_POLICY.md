# Master Planner Dispatch Bridge Policy

## Objective

The Claude Master Rebuild Planner must not stop at operator handoff when it has generated an approved L1-L3 non-live task. It must safely dispatch that task through `agent_supervisor.py`.

## Allowed Dispatch Scope

The dispatch bridge may run only non-live L1-L3 tasks inside:

`/home/wali/Desktop/AI BOT REBUILD`

## Required Gates Before Dispatch

All must be true:

- standing non-live V2 approval exists
- task file exists under `claude_worklog/agent_supervisor/tasks/`
- task risk level is L1, L2, or L3
- task cwd is `/home/wali/Desktop/AI BOT REBUILD`
- task is not blocked approval
- task does not request forbidden live actions
- no active Claude/Codex/Ollama child process is already running
- no live/Redis/legacy/exchange/deploy action is requested
- git is clean or only ignored runtime files are dirty
- no live gate approval has been requested or bypassed

## Forbidden Dispatch

Never dispatch if prompt/task requests:

- mutation of `/home/wali/Desktop/AI BOT`
- Redis write/delete
- service restart
- exchange order action
- leverage/margin change
- live trading enablement
- deployment
- production migration
- secret exposure
- L4/L5 action

Negative safety language such as "do not write Redis" or "do not modify `/home/wali/Desktop/AI BOT`" is not itself a dispatch blocker.

## Dispatch Action

When gates pass, execute:

`python3 claude_worklog/tools/agent_supervisor.py --task-id <task_id>`

Then record:

- `master_planner_dispatch_bridge_started`
- `master_planner_dispatch_bridge_completed`
- `master_planner_dispatch_bridge_blocked`

## Recovery

If `supervisor.lock` points to a dead PID, the bridge may remove it before dispatch.

## Safety

The bridge does not grant live authority. It only eliminates manual shell intervention for approved non-live local tasks.

MASTER_PLANNER_DISPATCH_BRIDGE_POLICY_READY
