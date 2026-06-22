# Codex Review: V2 No Status Change SLA Watchdog

GO/NO-GO: `V2_NO_STATUS_CHANGE_SLA_WATCHDOG_CODEX_PASS`

This review covers the no-status-change SLA watchdog only. It does not approve
edge, canary, live trading, legacy shutdown, Redis trim, checkpoint
deserialization, paid-feed activation, exchange mutation, or any approval
workflow.

## Findings

No blocking findings remain after scoped fixes during review.

## Fixes Applied During Review

- Added explicit `disallowed_classification_count` and
  `blocked_automatable_seed_count` snapshot signals, with
  `MISCLASSIFIED_AUTOMATABLE_WORK` classification when either becomes nonzero.
- Separated operator-visible status flatness from background evidence movement.
  Replay-miner sample/window growth no longer hides that production score,
  blocker count, shutdown/live state, and next-action classification are flat.
- Added regression coverage for misclassified/blocked seed detection,
  remediation seeding for non-allowed roots, synthetic 12-hour flat-history
  coverage, and replay-miner progress not resetting visible flat duration.

## Verified

- Flat status is detected over all required windows. The latest watchdog
  comparison reports 30m, 1h, 6h, and 12h windows all `available=true` and
  `flat=true` for operator-visible status, with
  `STATUS_FLAT_DURATION=12.1h`.
- Background evidence movement remains visible separately:
  `observed_signal_changed_fields=["replay_miner_sample_count",
  "replay_miner_windows_filled"]`, and
  `observed_signal_flat_duration_human=1m`.
- Root cause is classified exactly as `TRUE_EXTERNAL_SOURCE_WAIT`, with
  `root_cause_is_allowed=true`.
- TRUE wait states are not treated as automation failures. The action plan
  keeps remediation unseeded with
  `ROOT_CAUSE_IS_TRUE_WAIT_NOT_AUTOMATION_FAILURE`.
- TRUE operator wait is separately covered by regression test and is classified
  as `TRUE_OPERATOR_WAIT`, not stale automation.
- Automation stale / misclassified automatable work paths are fail-closed:
  stale roots block, and non-allowed roots call the Spark no-manual seeder to
  create or reference a paired implementation/review remediation task.
- Current queue state has no safe automatable work silently waiting:
  `AUTOMATABLE_NOW=0`, `worker_queued_automatable_tasks=0`,
  `worker_active_leases=0`, `disallowed_classification_count=0`, and
  `blocked_automatable_seed_count=0`.
- Watcher, replay-miner, report-center, and next-action classifier freshness
  are checked. Latest stale flags are all false:
  `report_center_stale=false`, `replay_miner_stale=false`,
  `event_watcher_stale=false`, and `next_action_classifier_stale=false`.
- Replay miner remains fresh and moving:
  `replay_miner_generated_at=2026-05-25T17:43:57Z`,
  `replay_miner_sample_count=3981`.
- Event watcher payload remains fresh and does not fake completion:
  `event_watcher_generated_at=2026-05-25T17:43:04Z`,
  `event_watcher_count=2`, and `event_watchers_completed=0`.
- Executive payload explains the flat state plainly:
  "Production score is flat because external source adoption and API/key/tier
  decisions remain unresolved."
- Missing external-source variables are listed by env-var name only:
  `CRYPTOQUANT_API_KEY`, `GLASSNODE_API_KEY`, `SANTIMENT_API_KEY`,
  `TM_API_KEY`, and `TOKENMETRICS_API_KEY`; raw values are not read or printed.
- The watchdog timer and protected automation timers are active: SLA watchdog,
  report center, replay miner, event watcher cycle, no-manual policy, Spark
  worker pool, and Codex runtime-soak governor.
- Report Center exposes `v2_no_status_change_sla_watchdog` as fresh and points
  to `/v2_no_status_change_sla_watchdog/latest/operator_dashboard_payload.json`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `shutdown_safe=false`
- `live_ready=false`
- `canary_ready=false`
- No approval artifact was created in the watchdog scope.
- Scoped scans found no executable old-Redis write path, exchange mutation
  path, truthy approval state, non-empty `live_symbols`, fake readiness, or raw
  secret material in the reviewed watchdog scope.

## Verification

```text
python -m py_compile \
  claude_worklog/tools/v2_no_status_change_sla_watchdog.py \
  v2/backend/app/services/report_center/report_registry.py
```

Result: pass.

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/tools/closed_loop_execution/test_no_status_change_sla_watchdog.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_autonomous_no_manual_next_task_policy.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Result: `27 passed in 0.77s`.

```text
PYTHONPATH=$PWD:$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_no_status_change_sla_watchdog.py --json

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty \
  claude_worklog/final_readiness/v2_no_status_change_sla_watchdog/latest/*.json \
  v2/frontend/public/v2_no_status_change_sla_watchdog/latest/*.json \
  v2/frontend/public/v2_report_center/latest/safe_summaries/v2_no_status_change_sla_watchdog.json
```

Results: watchdog generation passed, report-center re-index passed, JSON
validation passed, systemd activity checks passed, and scoped safety scans
passed.
