# Codex Review: V2 Closed-Loop Persistent Worker Pool

GO/NO-GO: `V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_CODEX_PASS`

This review covers the persistent closed-loop worker pool only. It does not
approve edge, canary, live trading, legacy shutdown, Redis trim, exchange
mutation, or any approval workflow.

## Findings

No blocking findings remain after scoped V2-side fixes during this review.

## Fixes Applied During Review

- Claude workers now supervise child task processes with `Popen` and refresh
  both worker heartbeat and lease heartbeat while the child is running.
- Codex review execution now supports heartbeat callbacks, and Codex workers
  refresh both worker heartbeat and lease heartbeat while review work runs.
- Active-work lane accounting includes `CODEX_TAKEOVER` separately from
  `CODEX_REVIEW`.
- The orchestrator blocks if all workers for a lane are alive but stuck in
  executor-unavailable state while matching current work exists.
- Active leases are reconciled against terminal descriptor status, so
  completed/failed descriptors cannot leave false running leases behind.
- Second-stale lease reclaim now creates an exact blocking reason:
  `SECOND_STALE_LEASE_REQUIRES_TAKEOVER_OR_OPERATOR_REMEDIATION`.
- Persistent worker-pool payloads now include `go_no_go`, so the report center
  exposes the READY marker instead of an INFO-only summary.
- Regression tests now cover child-process heartbeat persistence, Codex review
  heartbeat persistence, terminal descriptor lease reconciliation, and
  second-stale blocking.

## Verified

- Persistent worker daemons exist for both Claude and Codex.
- User systemd units are installed/enabled/active:
  3 Claude workers, 3 Codex workers, and the worker-pool timer.
- Worker-pool maintainer is installed as a systemd oneshot/timer and runs
  `v2_closed_loop_worker_pool.py run-once --spawn`, which restores missing
  worker daemons up to the configured bounded targets.
- Current worker-pool status:

  ```text
  marker=V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_READY
  ready=true
  blockers=[]
  current_automatable_count=6
  active_lane_count=6
  active_claude_workers=3
  active_codex_workers=3
  active_leases_count=0
  duplicate_task_leases=0
  duplicate_file_locks=0
  ```

- Current worker processes are live daemon PIDs with non-zombie `Ss` process
  state. Active lanes are counted from worker daemon PID plus fresh heartbeat,
  not descriptor counts and not child PIDs.
- Child Claude/Codex processes exiting quickly do not kill the worker lane; the
  daemon remains alive and immediately loops to claim the next eligible task.
- Current-work filtering remains active and excludes historical noise:
  `historical_excluded_count=709`.
- No current unsafe live/canary/shutdown task is selected.
- No duplicate active task leases or duplicate active `file_lock_group` leases
  were found.
- Stale lease reclaim is implemented. First stale releases once; second stale
  now blocks with an exact remediation/operator-required reason.
- Codex runner uses valid installed CLI command forms and does not use the
  unsupported legacy review-flag form.
- Report center exposes `v2_closed_loop_persistent_worker_pool` as READY,
  non-stale, and pointing to
  `/v2_closed_loop_persistent_worker_pool/latest/persistent_worker_pool_enablement_status.json`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Scoped scans found no executable old-Redis write path, exchange mutation
  path, truthy approval, non-empty `live_symbols`, or raw secret material in
  the reviewed worker-pool scope.

## Verification

```text
python -m py_compile \
  claude_worklog/tools/v2_closed_loop_worker_pool.py \
  claude_worklog/tools/v2_closed_loop_claude_worker.py \
  claude_worklog/tools/v2_closed_loop_codex_worker.py \
  claude_worklog/tools/v2_closed_loop_persistent_worker_pool_orchestrator.py \
  claude_worklog/tools/v2_codex_review_runner.py \
  claude_worklog/tools/v2_current_work_filter.py \
  v2/backend/app/services/report_center/report_registry.py
```

Result: pass.

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/tools/closed_loop_execution/test_persistent_worker_pool.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_closed_loop_executor.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_real_mode_enablement.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_active_lane_minimum_remediation.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Result: `57 passed in 42.79s`.

```text
PYTHONPATH=$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_closed_loop_persistent_worker_pool_orchestrator.py \
  --install-systemd --enable-systemd --target-claude 3 --target-codex 3 --wait-seconds 5 --json

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty worker-pool and report-center JSON artifacts
```

Results: worker pool READY, report-center re-index passed, JSON validation
passed.

## Residual System State

The persistent worker pool is ready, but the system is not live-ready. The
report center still shows live/recovery blockers including the war-room
governor, runtime soak, observation builder, checkpoint promotion, unproven
paper edge, and human-only live/shutdown gates.
