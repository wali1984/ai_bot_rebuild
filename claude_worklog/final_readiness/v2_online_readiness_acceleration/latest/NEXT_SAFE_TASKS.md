# Next Safe Non-Live Tasks (Online Readiness Acceleration Lane)

All follow-ups are non-live, file-system / read-only. None of them enable
live trading, restart live services, mutate legacy Redis, change leverage
/ margin / position mode, activate live keys, or expose secrets. The
final live/capital gate remains `blocked_human_only` until explicit human
approval is recorded outside this lane.

## Queued tasks (recommended order)

### 1. `codex_review_online_readiness_aggregator_freshness_extension`

- **Risk level:** L1 (review-only).
- **Scope:** Codex reviews the freshness extension diff:
  - `v2/backend/app/proof/online_readiness_aggregator.py`
  - `v2/backend/tests/unit/proof/test_online_readiness_aggregator_freshness.py`
- **Mandatory checks:**
  - The gating predicate (text-match against `required_marker`) remains
    the sole driver of `all_required_matched` and `go_no_go_marker`.
  - Staleness cannot demote READY to BLOCKED under any input.
  - No live-runtime imports were leaked (`redis`/`ccxt`/`websockets`/
    `requests`/`subprocess`).
  - SHA-256 is computed over `read_bytes()` output, not `strip()` text.
  - `_parse_now` is robust to invalid strings (returns `None`, never
    raises).
- **Emits:** `claude_worklog/final_readiness/online_readiness_codex_review/<run>/CODEX_GO_NO_GO.md`
  with `CODEX_ONLINE_READINESS_AGGREGATOR_FRESHNESS_PASS` or
  `..._FAIL`.

### 2. `claude_periodic_rollup_refresh_job`

- **Risk level:** L1 (additive read-only job).
- **Scope:** Add a V2 jobs-layer entry that periodically calls
  `write_online_readiness_rollup(repo_root, output_dir,
  now=datetime.now(tz=timezone.utc))` so the on-disk artifacts under
  `claude_worklog/final_readiness/online_readiness/latest/` carry an
  up-to-date `evidence_evaluated_at` and current `stale_lanes`. The job
  overwrites only the three artifacts the aggregator already owns; no
  Redis writes, no exchange interaction, no live-state mutation.
- **Allowed prefixes:** `v2/backend/app/jobs/`, `v2/backend/tests/unit/jobs/`,
  `claude_worklog/final_readiness/v2_jobs_layer_rollup_refresh/latest/`.
- **Codex review:** required.

### 3. `claude_wire_banner_api_freshness_fields`

- **Risk level:** L1 (additive, no behavior change).
- **Scope:** Pass `now=datetime.now(tz=timezone.utc)` from the banner
  handler at `v2/backend/app/api/v1/live_readiness.py` so the GUI sees
  populated `marker_age_seconds` / `stale` / `stale_lanes` fields. The
  handler must still write no files, touch no Redis, and import no
  live-runtime client.
- **Tests:** extend `test_live_readiness_banner.py` to assert that the
  response carries the freshness fields and that `stale_lanes` is the
  empty list when all lanes are fresh.
- **Codex review:** required.

### 4. `claude_extend_mission_control_banner_for_freshness`

- **Risk level:** L1 (frontend additive).
- **Scope:** Update the React component
  `v2/frontend/src/components/banners/MissionControlReadinessBanner.tsx`
  to render the new freshness fields (last evidence refresh, stale lanes
  list). Update the e2e mock fixture to include the new fields. Run
  `npm run typecheck`, `npm run build`, and the relevant Playwright e2e
  test.
- **Codex review:** required.

### 5. `claude_aggregate_online_readiness_into_non_live_operational_proof`

- **Risk level:** L1 (additive composition).
- **Scope:** Add the online-readiness aggregator as a required input to
  the existing `non_live_operational_proof` aggregator so the top-level
  proof harness fails fast when any lane regresses. No state change to
  the live gate; the composed marker remains gated by the existing
  `NON_LIVE_OPERATOR_PROOF_HARNESS_READY` text-match.
- **Codex review:** required.

## Further non-live followups (not yet emitted as supervisor task JSONs)

- Add a CLI entrypoint that emits a small text-only summary of stale
  lanes for tmux-based monitor dashboards (no GUI, no network).
- Extend the rollup to record the **last good** marker SHA per lane in
  an append-only ledger under
  `claude_worklog/final_readiness/online_readiness_history/`, enabling
  drift detection across rollup runs without re-reading every marker.

## Hard constraints carried forward

- `/home/wali/Desktop/AI BOT` remains read-only.
- No Redis writes / deletes / trims. No Redis trim approval files.
- No live restart, no order placement, no leverage / margin / position
  mode change, no live key activation, no live trading enable.
- Final live/capital gate remains `blocked_human_only`.
- All slices route through the supervisor with `emit_files: true` and
  explicit `allowed_output_prefixes`; no slice expands write scope.
