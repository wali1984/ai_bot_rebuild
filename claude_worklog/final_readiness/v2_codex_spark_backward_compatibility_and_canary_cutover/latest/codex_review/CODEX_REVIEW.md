# Codex Review: V2 Codex Spark Backward Compatibility and Canary Cutover

GO/NO-GO: `V2_CODEX_SPARK_BACKWARD_COMPATIBILITY_AND_CANARY_CUTOVER_CODEX_PASS`

This review covers Spark backward compatibility and canary cutover safety only.
It does not approve edge, canary rollout, live trading, legacy shutdown, Redis
trim, exchange mutation, or any approval workflow.

## Findings

No blocking findings remain after scoped fixes during review.

## Fixes Applied During Review

- Restored the legacy file-backed worker-pool helper API used by queue
  remediation, persistent-worker tests, and rollback mode while keeping the
  default CLI delegated to Spark.
- Restored legacy imported Claude worker APIs:
  `run_worker(worker_id, max_iterations=..., task_timeout=...)` and
  `execute_task(worker_id, claim, executor, timeout=...)`.
- Restored legacy imported Codex worker APIs:
  `run_worker(worker_id, max_iterations=..., task_timeout=...)` and
  `execute_review(worker_id, claim, executor, timeout=...)`.
- Fixed Spark SQLite fallback DB placement so it uses
  `claude_worklog/final_readiness/v2_closed_loop_spark/state/leases.db`
  instead of repo-root `leases.db`; the existing DB was copied there for audit
  preservation.
- Made Spark wrappers self-locate the repo root before importing `v2.*`, so
  systemd oneshots do not depend on fragile shell/PYTHONPATH parsing.
- Reset and started the burndown oneshot after the wrapper fix; it completed
  successfully and its timer remains active/enabled.

## Verified

- Existing wrapper CLIs still accept prior args, including worker-pool
  `run-once --spawn --target-claude --target-codex`, Claude/Codex
  `--worker-id`, autoseed `--wait-seconds --json`, burndown `--json`, and the
  fail-mapper help path.
- Existing file-backed output schemas and helper APIs remain compatible with
  the older queue-consumption and persistent-worker tools.
- Report center re-index completed successfully and parsed current Spark and
  existing automation payloads.
- Replay miner timer is enabled/active and the miner payload is fresh:
  `generated_at=2026-05-25T03:02:39Z`, `bundles_total=3173`.
- Report center timer, replay miner timer, worker-pool timer, and burndown
  timer are enabled/active.
- Existing persistent workers were not paused: 3 Claude worker services and
  3 Codex worker services are active.
- Existing active lease/task state was not deleted; file-backed and Spark
  stores remain available.
- Spark remains canary-gated:
  `canary_gate_verdict=CANARY_GATED_NOT_PRODUCTION_READY` and
  `spark_cannot_mark_production_ready=true`.
- Rollback exists through `claude_worklog/tools/v2_codex_spark_rollback.py`,
  and `LEASE_BACKEND=file` now exercises a real file-backed fallback path.
- Spark SQLite DB is preserved at
  `claude_worklog/final_readiness/v2_closed_loop_spark/state/leases.db`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Scoped scans found no executable old-Redis write path, exchange mutation
  path, truthy approval, non-empty `live_symbols`, or raw secret material in
  the reviewed Spark/backward-compatibility scope. Exchange-string hits were
  safety refusal tokens only.

## Verification

```text
python -m py_compile \
  claude_worklog/tools/v2_closed_loop_worker_pool.py \
  claude_worklog/tools/v2_closed_loop_claude_worker.py \
  claude_worklog/tools/v2_closed_loop_codex_worker.py \
  claude_worklog/tools/v2_autonomous_mission_backlog_autoseed.py \
  claude_worklog/tools/v2_autonomous_mission_execution_burndown.py \
  claude_worklog/tools/v2_burndown_fail_to_remediation_mapper.py \
  v2/backend/app/closed_loop/lease_store/sqlite_store.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/tools/closed_loop_execution/test_queue_consumption_remediation.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_persistent_worker_pool.py \
  claude_worklog/tools/tests/test_backward_compat.py -q

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty Spark/backward-compatibility and report-center JSON artifacts
```

Results: py_compile passed, focused compatibility tests passed `61/61`,
report-center re-index passed, JSON validation passed, and scoped safety scans
passed.

