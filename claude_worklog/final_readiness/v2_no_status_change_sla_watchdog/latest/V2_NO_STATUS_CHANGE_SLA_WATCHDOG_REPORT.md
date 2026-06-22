# V2 No Status Change SLA Watchdog

Generated: 2026-06-22T00:26:01.018218Z
GO/NO-GO: `V2_NO_STATUS_CHANGE_SLA_WATCHDOG_BLOCKED`
SLA state: `BLOCKED`
Root cause: `REPLAY_MINER_STALE`

## Executive Explanation

- Production score is flat because the automation control plane reported REPLAY_MINER_STALE.
- Automation is stalled because REPLAY_MINER_STALE.
- The next thing that can change this state is Spark remediation task seeded or referenced.

## Current Signals

- production score: `19.9`
- global blocker count: `9`
- automatable now: `2`
- active leases: `0`
- task completions last hour: `0`
- replay miner sample count: `113917`
- event watchers completed: `0`

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- No live/canary/shutdown/Redis-trim approval is created.
- No old Redis write or exchange mutation is allowed.
