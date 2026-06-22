# Codex Review: V2 Autonomous No-Manual Next-Task Policy

GO/NO-GO: `V2_AUTONOMOUS_NO_MANUAL_NEXT_TASK_POLICY_CODEX_PASS`

This review covers the autonomous no-manual next-task policy only. It does not
approve edge, canary, live trading, legacy shutdown, Redis trim, checkpoint
deserialization, paid-feed activation, exchange mutation, or any approval
workflow.

## Findings

No blocking findings remain after scoped fixes during review.

## Fixes Applied During Review

- Added `claude_worklog/tools/v2_autonomous_no_manual_next_task_policy.py`.
- Registered `v2_autonomous_no_manual_next_task_policy` in Report Center.
- Installed and enabled the user timer
  `ai-bot-v2-autonomous-no-manual-next-task-policy.timer`.
- Fixed the Spark Claude worker child execution call so child runs receive the
  store, worker id, lease id, and lane group needed for heartbeat persistence.
- Changed Spark autoseed duplicate handling so existing terminal seed tasks are
  referenced instead of reset back to pending on every cycle.
- Retired the transient broad full-observation/no-manual seed pair as
  superseded after the classifier correctly mapped that blocker to
  external/event/operator context.

## Verified

- Every current Report Center action row is classified into one allowed bucket:
  `AUTOMATABLE_NOW`, `OPERATOR_DECISION_REQUIRED`,
  `EXTERNAL_SOURCE_REQUIRED`, `EVENT_DEPENDENT`, `POSITION_DEPENDENT`, or
  `UNSAFE_TO_AUTOMATE`.
- Current classification counts are:

  ```text
  AUTOMATABLE_NOW=0
  OPERATOR_DECISION_REQUIRED=3
  EXTERNAL_SOURCE_REQUIRED=2
  EVENT_DEPENDENT=0
  POSITION_DEPENDENT=0
  UNSAFE_TO_AUTOMATE=5
  ```

- The previous automatable burndown item was executed through Spark and its
  Codex failure is mapped as operator-required, not silently ignored.
- Queue-empty state is not treated as migration complete. The packet emits:
  `ALL_REMAINING_REPORT_CENTER_ACTIONS_ARE_OPERATOR_EVENT_EXTERNAL_POSITION_OR_UNSAFE`.
- The full-observation blocker is no longer seeded as a broad task; it is
  classified against the existing external-source/event/operator context.
- Current Spark queue has no pending safe automatable task:
  `queued_automatable_tasks=0`.
- Worker heartbeats are not counted as migration progress or active execution;
  `automation_executing=false` when `active_leases=0`.
- Unmapped Codex FAIL count is `0`.
- Report Center exposes the policy lane as fresh and READY, pointing to
  `/v2_autonomous_no_manual_next_task_policy/latest/operator_dashboard_payload.json`.
- The protected automation timers remain active: report center, replay miner,
  Spark worker pool, Codex runtime-soak governor, V2 paper runtime, and event
  watcher cycle.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- No approval artifact was created.
- No live/canary/shutdown/Redis-trim task is selected.
- Checkpoint deserialization and paid-feed activation remain operator-gated.
- Scoped scans found no executable old-Redis write path, exchange mutation
  path, truthy approval state, non-empty `live_symbols`, or raw secret material
  in the reviewed policy scope.

## Verification

```text
python -m py_compile \
  claude_worklog/tools/v2_autonomous_no_manual_next_task_policy.py \
  v2/backend/app/closed_loop/services/autoseed.py \
  v2/backend/app/closed_loop/workers/claude_worker.py \
  v2/backend/app/services/report_center/report_registry.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/tools/closed_loop_execution/test_autonomous_no_manual_next_task_policy.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_persistent_worker_pool.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Result: `36 passed in 6.08s`.

```text
PYTHONPATH=$PWD:$PWD/claude_worklog/tools .venv/bin/python \
  claude_worklog/tools/v2_autonomous_no_manual_next_task_policy.py --json

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty \
  claude_worklog/final_readiness/v2_autonomous_no_manual_next_task_policy/latest/*.json \
  v2/frontend/public/v2_autonomous_no_manual_next_task_policy/latest/*.json
```

Results: policy generation passed, Report Center re-index passed, JSON
validation passed, systemd timer install/start passed, and scoped safety scans
passed.
