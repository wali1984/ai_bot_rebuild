# Codex Review: V2 Closed-Loop Active-Lane Minimum Remediation

GO/NO-GO: `V2_CLOSED_LOOP_ACTIVE_LANE_MINIMUM_REMEDIATION_CODEX_PASS`

This review covers active-lane minimum remediation only. It does not approve
edge, canary, live trading, legacy shutdown, Redis trim, exchange mutation, or
any approval workflow.

## Findings

No blocking findings remain for the remediation contract because the packet now
blocks honestly when the active-lane minimum is not sustained. The original
closed-loop engine remains operationally blocked.

## Fixes Applied During Review

- Fixed shared PID liveness so zombie processes are not counted as active
  lanes.
- Normalized active-lane descriptors before proof collection, so legacy task
  descriptors get inferred `task_type`, `owner`, and `file_lock_group`.
- Fixed active-lane proof in the real-mode status path to use the same
  normalized descriptor semantics.
- Fixed active-lane dispatch routing so `CODEX_TAKEOVER` tasks do not fall
  through to the Claude launcher.
- Added a `NO_ACTIVE_LANE_SHORTFALL` root-cause state for clean ready snapshots
  so stale shortfall text is not carried forward when the minimum is already
  met.
- Refreshed the active-lane, real-mode, original closed-loop, and report-center
  payloads after the fixes.

## Verified

- Current-work filtering excludes historical task noise:

  ```text
  current_automatable_count=7
  historical_excluded_count=706
  ```

- The active-lane remediation status is honest and blocked:

  ```text
  marker=V2_CLOSED_LOOP_ACTIVE_LANE_MINIMUM_REMEDIATION_BLOCKED
  active_lane_count=1
  target_active_lanes=3
  blocker=ACTIVE_LANES_BELOW_MINIMUM
  dry_run=false
  ```

- The exact blocker is non-fake:

  ```text
  root_cause.code=CLAUDE_RUNNER_DISPATCH_LIMIT_BUG
  root_cause.detail=7 current automatable items and 1 pending-safe item exist,
  but the runner has only 1 real lane; 3 zombie running descriptors were reset.
  ```

- Active lanes are counted only from real running jobs with PID/log/heartbeat
  evidence. Defunct Claude PIDs are no longer counted.
- Dead probe PIDs and descriptor-only lanes are not counted.
- File-lock groups are inferred and present on active/proof descriptors.
- Historical excluded descriptors were not bulk-launched.
- Codex runner command forms remain valid for the installed CLI.
- No current pending Codex work exists, and this is explicitly recorded:

  ```text
  no_current_codex_work=true
  reason=no pending current Codex review work; active_codex_jobs may stay 0
  ```

- The upstream original closed-loop status was re-run and remains blocked:

  ```text
  marker=V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_BLOCKED
  automatable_work_count=7
  active_lane_count=1
  blocker=ACTIVE_LANES_BELOW_MINIMUM
  ```

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Scoped scans found no executable old-Redis write path, no exchange mutation
  path, no invalid `codex exec --review` command, no truthy approval, and no
  non-empty `live_symbols` in the reviewed active-lane remediation scope.

## Residual Risk

The remediation attempted bounded top-up and briefly reached 3 lanes, but the
launched Claude jobs exited quickly and became defunct. The corrected proof now
rejects those zombies and keeps the packet BLOCKED. The next implementation
fix should address Claude runner process lifecycle/reaping and durable lane
work selection.

## Verification

```text
python -m py_compile \
  claude_worklog/tools/v2_closed_loop_lifecycle.py \
  claude_worklog/tools/v2_closed_loop_active_lane_minimum_remediation.py \
  claude_worklog/tools/v2_closed_loop_real_mode_enablement.py \
  claude_worklog/tools/v2_claude_task_runner.py \
  claude_worklog/tools/v2_codex_review_runner.py \
  claude_worklog/tools/v2_closed_loop_claude_codex_executor.py \
  claude_worklog/tools/v2_current_work_filter.py
```

Result: pass.

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/tools/closed_loop_execution/test_closed_loop_executor.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_real_mode_enablement.py -q
```

Result: `19 passed in 0.34s`.

```text
PYTHONPATH=$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_closed_loop_active_lane_minimum_remediation.py --json

PYTHONPATH=$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_closed_loop_real_mode_enablement.py --no-probes --json

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty active-lane, real-mode, and original closed-loop JSON artifacts
```

Results: active-lane and original closed-loop statuses are honestly BLOCKED,
report-center re-index passed, and JSON validation passed.
