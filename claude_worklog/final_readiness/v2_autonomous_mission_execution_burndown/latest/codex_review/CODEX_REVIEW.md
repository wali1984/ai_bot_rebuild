# Codex Review: V2 Autonomous Mission Execution Burndown

GO/NO-GO: `V2_AUTONOMOUS_MISSION_EXECUTION_BURNDOWN_CODEX_FAIL`

This review covers the autonomous mission execution burndown packet only. It
does not approve edge, canary, live trading, legacy shutdown, Redis trim,
exchange mutation, model production readiness, or any approval workflow.

## Blocking Findings

1. **Codex FAIL is not visibly connected to a newly created remediation or
   operator-required classification.**

   The refreshed burndown payload reports:

   ```text
   Codex_FAIL_count_last_hour=1
   remediations_created_last_hour=0
   codex_fail_to_remediation_loop_visible=false
   ```

   Two remediation descriptors completed in the last hour, but both completed
   as `failed`, and the packet does not tie the current Codex FAIL to a safe
   newly-created remediation or an explicit operator-required / unsafe-to-fix
   classification. This fails the requirement that Codex FAIL creates
   remediation when safe.

2. **Mission blocker count did not decrease, and the READY packet gives no
   exact blocker explaining why burn-down did not happen in this cycle.**

   The refreshed blocker matrix reports:

   ```text
   blocker_count_before=4
   blocker_count_after=4
   blockers_burned_down=0
   blockers_newly_discovered=0
   status.blockers=[]
   ```

   The remaining blockers are still visible in the matrix, but the burndown
   packet marks READY with no explicit reason for zero net burn-down. This
   fails the review requirement that blockers either decrease or the non-burn
   reason is explicit.

## Verified Healthy

- Active leases are not counted as migration progress by themselves. The
  packet states that worker heartbeats, report-center refreshes, queued
  descriptors, and Codex reviews are excluded from implementation progress.
- Completed implementation tasks are separated from reviews and report/control
  artifacts:

  ```text
  tasks_completed_last_hour=74
  implementation_tasks_completed_last_hour=39
  Codex_reviews_completed_last_hour=35
  report_only_or_control_artifacts_completed_last_hour=0
  ```

- Sampled implementation completions carry `report_only_work=false` and
  `descriptor_only_progress_counted=false`.
- Current-work filtering, after refresh, reports no current safe automatable
  work left silently queued:

  ```text
  current_automatable_count=0
  historical_excluded_count=804
  ```

- No fake live/shutdown/model/edge readiness was found in the reviewed
  burndown artifacts.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Scoped scans found no executable old-Redis write path, exchange mutation
  path, truthy approval, non-empty `live_symbols`, or raw secret material in
  the reviewed burndown scope.

## Verification

```text
PYTHONPATH=$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_autonomous_mission_execution_burndown.py --json

PYTHONPATH=$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_current_work_filter.py --json

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

python -m py_compile \
  claude_worklog/tools/v2_autonomous_mission_execution_burndown.py \
  claude_worklog/tools/v2_autonomous_mission_backlog_autoseed.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/tools/closed_loop_execution/test_autonomous_mission_execution_burndown.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_autonomous_mission_backlog_autoseed.py -q

jq empty \
  claude_worklog/final_readiness/v2_autonomous_mission_execution_burndown/latest/*.json \
  v2/frontend/public/v2_autonomous_mission_execution_burndown/latest/*.json
```

Results: py_compile passed, focused tests passed `7/7`, JSON validation passed,
report-center re-index passed, and scoped safety scans passed.

## Required Remediation Before Pass

1. When `Codex_FAIL_count_last_hour > 0`, emit a current remediation descriptor
   or an explicit non-automatable/operator-required classification for each
   FAIL, and expose the mapping in `remediation_flow_status.json`.
2. If `blocker_count_after >= blocker_count_before`, keep the packet BLOCKED
   or expose an exact acceptable reason, such as all remaining blockers being
   operator-gated or external/event-dependent.
3. Add regression coverage so `V2_AUTONOMOUS_MISSION_EXECUTION_BURNDOWN_READY`
   cannot be emitted when `codex_fail_to_remediation_loop_visible=false` or
   blocker count is flat without an explicit reason.
