# No Live Side Effects Audit

Review timestamp: 2026-05-12

Inputs inspected:
- `v2`
- `claude_worklog/tools`
- `claude_worklog/agent_supervisor`

Verdict: BLOCKED

## Concrete Blockers

1. Redis write-capable preserved legacy ingestor remains under the `v2` tree.
   - Evidence: `v2/legacy_preserved/ingestors/live_coinank.py:166-168` writes heartbeat keys with `r.set(...)`.
   - Evidence: `v2/legacy_preserved/ingestors/live_coinank.py:194-196` writes diagnostic heartbeat keys with `r.set(...)`.
   - Evidence: `v2/legacy_preserved/ingestors/live_coinank.py:328-329` writes validation data with `r.xadd(...)` and `r.hset(...)`.
   - Evidence: `v2/legacy_preserved/ingestors/live_coinank.py:2249` writes last-error state with `r.set(...)`.
   - Evidence: `v2/legacy_preserved/ingestors/live_coinank.py:2261` deletes `lock:live_coinank` with `r.delete(...)`.
   - Evidence: `v2/legacy_preserved/ingestors/live_coinank.py:2287-2288` writes Redis heartbeat seed keys in the executable `__main__` path.

2. Deployment/publish-capable finalization script exists in reviewed tools.
   - Evidence: `claude_worklog/tools/finalize_claude_design_output.sh:56-64` stages files, commits, and runs `git push`.
   - This is not a live exchange action, but it violates the requested no-deployment/no-publish side-effect audit boundary for reviewed tooling.

3. Watchdog automation can stop/start control-plane sessions and push commits.
   - Evidence: `claude_worklog/tools/codex_non_live_watchdog.py:268-270` runs `git push` after committing recovery changes.
   - Evidence: `claude_worklog/tools/codex_non_live_watchdog.py:276-283` calls stop/start planner and supervisor scripts.
   - Evidence: `claude_worklog/tools/codex_non_live_watchdog.py:659` stops the planner during a cycle and `claude_worklog/tools/codex_non_live_watchdog.py:707-709` starts it again.
   - These appear scoped to non-live rebuild control-plane processes, not live trader/trainer services, but they are still automation side effects and should be gated out of a no-side-effects review surface.

## Checks

- No Redis writes: FAIL. Redis mutation calls exist in `v2/legacy_preserved/ingestors/live_coinank.py`.
- No live service restart: PARTIAL. No `systemctl restart` live-service execution was found in active V2 source. Reviewed supervisor tools do include tmux stop/start control-plane automation.
- No exchange order action: PASS for active V2 proof/domain surfaces. `v2/backend/app/proof/readonly_market_exchange_data_plane.py:95-105` defines forbidden mutation methods that raise instead of placing/canceling orders or changing leverage/margin.
- No deployment: FAIL. `claude_worklog/tools/finalize_claude_design_output.sh:63-64` and `claude_worklog/tools/codex_non_live_watchdog.py:268-270` can push to git remotes.
- Live gate remains blocked: PASS. Evidence includes `v2/backend/app/domain/paper_mode/flag.py:46-55`, `v2/backend/app/domain/risk_gateway/record.py:214-218`, and `v2/backend/app/proof/online_readiness_aggregator.py:63-80`, all preserving `blocked_human_only` / `live_blocked is True` behavior.

## Proposed Non-Live Autofix Tasks

1. Quarantine `v2/legacy_preserved/ingestors/live_coinank.py` behind an inert archive boundary:
   - Rename or relocate it out of executable/importable V2 paths, or replace executable Redis mutation paths with documentation-only fixtures.
   - Add an audit test that scans `v2/legacy_preserved/**` for Redis write/delete tokens and fails unless files are explicitly non-executable fixtures.

2. Split deploy/publish behavior out of reviewed local tooling:
   - Change `claude_worklog/tools/finalize_claude_design_output.sh` so it validates and writes local artifacts only.
   - Move `git commit` and `git push` into a separate human-invoked publish script with an explicit approval marker.

3. Gate watchdog side effects:
   - Add a `--dry-run` / `--no-push` / `--no-restart` mode and make it the default.
   - Require an explicit non-live control-plane approval file before any tmux stop/start or git push behavior.

4. Add a repository-level no-live-side-effects audit:
   - Scan active source and reviewed tools for Redis write/delete commands, exchange mutation methods, service restart commands, deployment commands, and live-gate enablement.
   - Exclude generated evidence registries only after the scanner records the exclusion reason.

Final recommendation: keep `CODEX_PARALLEL_REVIEW_BLOCKED` until Redis mutation-capable preserved legacy code and publish/restart-capable automation are quarantined or gated.
