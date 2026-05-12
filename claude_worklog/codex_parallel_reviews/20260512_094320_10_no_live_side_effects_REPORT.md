# No Live Side Effects Audit

Generated: 2026-05-12

Review inputs:
- `v2`
- `claude_worklog/tools`
- `claude_worklog/agent_supervisor`

Decision: `CODEX_PARALLEL_REVIEW_BLOCKED`

## Scope-Safe Review Actions

Read-only scans were run with `rg`, `sed`, and `nl`. No Redis command was executed, no live service was restarted, no exchange action was attempted, no leverage/margin setting was changed, no live trading gate was enabled, and no deployment was performed.

## Findings

### BLOCKER 1 - Redis write/delete code remains executable under `v2`

`v2/legacy_preserved/ingestors/live_coinank.py` is a preserved live ingestor, but it is still an executable Python module under the reviewed `v2` tree. It imports live config and the legacy Redis client at import/startup time:

- `v2/legacy_preserved/ingestors/live_coinank.py:19` loads `get_live_config()`.
- `v2/legacy_preserved/ingestors/live_coinank.py:32` imports `get_redis`.
- `v2/legacy_preserved/ingestors/live_coinank.py:47-51` performs a Redis health check before startup.

The same file contains many direct Redis mutation paths:

- Heartbeat writes: `r.set(...)` at lines `166-168`, `194-196`, and `2287-2288`.
- Debug/status writes: `r.set(...)` at line `205`.
- Stream/hash writes: `r.xadd(...)` and `r.hset(...)` at lines `328-329`.
- Backfill writes/trims: `r.set(...)`, `r.lpush(...)`, and `r.ltrim(...)` at lines `905`, `909`, and `912`.
- Feature/latest writes: `r.set(...)` at lines `1294`, `1305`, `1365`, `1368`, and `1369`.
- Lock deletion: `r.delete(...)` at line `2261`.

This violates the audit check `no Redis writes` for the inspected `v2` tree.

### BLOCKER 2 - Control-plane automation includes restart and push behavior

`claude_worklog/tools/codex_non_live_watchdog.py` can commit and push local changes:

- `git add`, `git commit`, and `git push` are invoked at lines `262-269`.

It can also stop and start rebuild planner/supervisor sessions:

- Stop commands are invoked at lines `276-278`.
- Start command is invoked at line `285-286`.
- The restart path is reached at lines `710-712`.

`claude_worklog/tools/autonomous_non_live_rebuild_controller.py` also commits and pushes:

- `git add`, `git commit`, and `git push` are invoked at lines `424-429`.

These are not exchange/order actions, and the stopped sessions appear to be rebuild control-plane sessions rather than live trading services. However, for this audit topic the reviewed tooling is not strictly side-effect-free: it contains restart-like control-plane behavior and remote push behavior that should be explicitly fenced away from read-only parallel review execution.

## Passing Observations

- Exchange mutation methods in `v2/backend/app/proof/readonly_market_exchange_data_plane.py` are forbidden stubs: `create_order`, `cancel_order`, `change_leverage`, and `change_margin` all call `forbidden_mutation(...)` at lines `95-105`.
- Focused source scans found no direct exchange order placement calls outside those forbidden stubs.
- `v2/config/runtime_paths.example.json` keeps `live_trading_enabled` set to `false` at line `11`.
- Multiple UI/control-plane surfaces preserve `blocked_human_only` live-gate status.

## Proposed Non-Live Autofix Tasks

1. Quarantine `v2/legacy_preserved/ingestors/live_coinank.py` so it cannot be imported or executed accidentally from V2. A safe fix is to move it into a non-executable archived evidence location or add a hard import-time/runtime guard that raises unless an explicit human-only archival inspection flag is set. Do not run it.
2. Add a focused static test that fails if `v2/legacy_preserved/**` contains Redis mutation tokens such as `.set(`, `.hset(`, `.xadd(`, `.lpush(`, `.delete(`, `XADD`, `XDEL`, `XTRIM`, `FLUSHDB`, or `FLUSHALL` unless the file is marked as inert archive text.
3. Split read-only review tools from automation recovery tools. Read-only parallel reviews should not be able to call functions that run `git push`, stop/start tmux sessions, or launch supervisor/planner processes.
4. Add a static guard test for `claude_worklog/tools/*parallel*review*` and review task runners that rejects `git push`, `tmux kill-session`, stop/start supervisor scripts, `systemctl`, `docker compose up`, `kubectl apply`, `helm upgrade`, and `terraform apply`.

## Evidence Commands

- `rg -n` scans for Redis mutation, service restart, exchange mutation, deployment, and live-gate tokens across the requested inputs.
- Focused scans excluded generated `v2/frontend/dist/**`, `v2/frontend/public/**`, and documentation where needed to distinguish executable source from historical/proof text.
- `nl -ba` was used to collect concrete line references for blockers.
