# Codex Review: V2 Codex Spark Parallel Closed-Loop Runtime

GO/NO-GO: `V2_CODEX_SPARK_PARALLEL_CLOSED_LOOP_RUNTIME_CODEX_PASS`

This review covers the first-class V2 closed-loop Spark runtime only. It does
not approve edge, canary, live trading, legacy shutdown, Redis trim, exchange
mutation, or production equivalence.

## Findings

No blocking findings remain after scoped fixes during this review.

## Fixes Applied During Review

- Staged Claude/Codex lane systemd units no longer use `--max-iterations=1`;
  the worker services run as durable daemons and keep systemd notify/watchdog
  heartbeats alive beyond child task lifetime.
- Spark autoseed and burndown units now call first-class
  `v2.backend.app.closed_loop` module CLIs instead of old worklog tools.
- Spark service output paths now resolve to the repo root, so worklog/public
  JSON are outputs of the SQLite truth plane rather than misplaced source data.
- Worker safety checks now read the persisted descriptor payload from SQLite,
  so valid leased tasks are not falsely refused and unsafe envelopes still fail
  before execution.
- Second-stale lease escalation now creates a remediation task and a fail-map
  row instead of silently failing a lease.
- Codex executor failures now map to an operator-required fail classification.
- Executive payloads now distinguish Spark runtime readiness from global
  migration readiness: `MIGRATION_COMPLETE`, `PAPER_EDGE_PROVEN`,
  `LIVE_READY`, and `LEGACY_SHUTDOWN_READY` remain false.

## Verified

- `v2/backend/app/closed_loop` exists with a mission-classified lane registry,
  SQLite WAL lease store, autoseed/burndown/fail-mapper services, metrics, and
  Claude/Codex workers.
- Worklog tool wrappers remain compatible and delegate to the new implementation.
- SQLite is the lease/task/event source of truth. Worklog and public JSON are
  generated outputs only.
- Unique SQLite indexes prevent duplicate active task leases and duplicate
  active `file_lock_group` leases.
- Autoseed emits paired `CLAUDE_IMPLEMENTATION` and `CODEX_REVIEW` descriptors,
  and Codex reviews wait for the Claude dependency.
- Codex FAIL maps to remediation, operator-required, or unsafe classification.
- Stale lease reclaim works, and second stale now creates exact remediation
  evidence.
- Worker heartbeats persist while child Claude/Codex processes run, and child
  exit does not define the lane lifetime.
- Type=notify/WatchdogSec systemd unit templates exist. Rollout remains
  canary-gated; this is not a production deployment approval.
- The LoadCredential plan references credential names only and does not expose
  raw secret values.
- Alert/metric artifacts cover idle-with-work, stale heartbeat, unmapped fail,
  duplicate lease, stale payload, and flat burndown conditions.
- Report Center can read Spark executive payload truth from
  `/v2_codex_spark_parallel_closed_loop/latest/executive_payload_spark_status.json`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- No executable old-Redis write path was found in the reviewed Spark runtime
  scope.
- No exchange mutation path was found in the reviewed Spark runtime scope.
- No live/canary/shutdown approval was created.
- Existing automation was not stopped.

## Verification

```text
python -m py_compile \
  v2/backend/app/closed_loop/lease_store/sqlite_store.py \
  v2/backend/app/closed_loop/workers/claude_worker.py \
  v2/backend/app/closed_loop/workers/codex_worker.py \
  v2/backend/app/closed_loop/services/autoseed.py \
  v2/backend/app/closed_loop/services/burndown.py \
  v2/backend/app/closed_loop/services/executive_payloads.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/unit/app/closed_loop/test_sqlite_store.py \
  v2/backend/tests/unit/tools/closed_loop_execution/test_production_equivalence_final_blocker_classification.py -q
```

Results: py_compile passed; focused Spark/classifier tests passed `28/28`.

JSON validation and report-center re-index were run after this review.
