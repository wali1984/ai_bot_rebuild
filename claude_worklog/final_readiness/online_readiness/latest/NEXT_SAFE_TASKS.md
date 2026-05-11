# Next Safe Non-Live Tasks (Online Readiness Lane)

All follow-ups are non-live, file-system / read-only. Codex parallel audit
remains active per `claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json`.

## Queued tasks (JSONs materialized this run)

1. `codex_review_online_readiness_aggregator`
   - Codex reviews `v2/backend/app/proof/online_readiness_aggregator.py` +
     `v2/backend/tests/unit/proof/test_online_readiness_aggregator.py` for
     read-only purity, import discipline, and lane-coverage correctness.
   - Emits `claude_worklog/final_readiness/online_readiness_codex_review/latest/CODEX_GO_NO_GO.md`
     (`CODEX_ONLINE_READINESS_AGGREGATOR_PASS` or `..._FAIL`).
   - L1, no source code changes.

2. `claude_wire_online_readiness_banner_api`
   - Adds a `GET /api/v1/live-readiness/banner` endpoint to
     `v2/backend/app/api/v1/live_readiness.py` that calls
     `build_online_readiness_rollup` and returns the rollup as JSON.
   - Strict read-only handler; no live mutation; no Redis; existing
     middleware order preserved; integration test added under
     `v2/backend/tests/integration/api/`.
   - Codex review gate required before merge.

3. `claude_online_readiness_banner_frontend`
   - Adds a Mission Control banner component that reads
     `/api/v1/live-readiness/banner` and renders a READY/BLOCKED chip plus
     the per-lane list. UI-polish work is **subordinate to the data
     contract** and runs only after the API task above lands.
   - Codex review gate required before merge.

## Further non-live followups (not yet emitted as JSONs)

4. Periodic re-run of `write_online_readiness_rollup` from the V2 jobs
   layer (`v2/backend/app/jobs/`) so the on-disk rollup tracks marker
   mtime changes without any operator action. No new state is created —
   the job overwrites only the three artifacts inside
   `claude_worklog/final_readiness/online_readiness/latest/`.

5. Extension of the rollup to include **lane mtimes and SHA-256 digests**
   so the GUI can show "last evidence refresh" and detect stale lanes
   without re-reading every marker file from the browser.

6. Add `online_readiness_aggregator` as a required input to the existing
   `non_live_operational_proof` aggregate rollup so the top-level proof
   harness fails fast when any lane regresses (Codex review required;
   no live state is touched).

## Hard constraints carried forward

- `/home/wali/Desktop/AI BOT` remains read-only.
- No Redis writes / deletes / trims. No Redis trim approval files.
- No live restart, no order placement, no leverage / margin / position
  mode change, no live key activation, no live trading enable.
- Final live/capital gate remains `blocked_human_only`.
