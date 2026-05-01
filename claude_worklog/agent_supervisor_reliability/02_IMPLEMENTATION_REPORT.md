# 02 — Agent Supervisor Reliability Hardening Implementation Report

Scope: reliability and governance hardening of the agent supervisor and dashboard.
This is **not** a V2 build. No live trader, live trainer, Redis, or legacy bot was touched.

## 1. Architectural changes delivered

### 1.1 Task definition vs runtime state separation
- New directory: `claude_worklog/agent_supervisor/state/tasks/<task_id>.json` holds runtime state.
- Task files under `tasks/` become **stable definitions only** (definition fields whitelisted).
- DEFINITION_FIELDS and STATE_FIELDS are explicit constants in `agent_supervisor.py`.
- New helpers:
  - `load_task_definition(path)` — definition-only view
  - `load_task_state(task_id)` — state-only view (creates default if missing)
  - `update_task_state(task_id, **fields)` — single write path with status-change history
  - `load_task(path)` — merged read-only view used by callers needing a unified dict
- Idempotent migration: `migrate_legacy_task_files()` runs on every daemon start and can be triggered explicitly via `python claude_worklog/tools/agent_supervisor.py --migrate`. It moves any legacy state fields out of definition files into state files; reruns are no-ops once definitions are clean.

### 1.2 Daemon heartbeat
- File: `claude_worklog/agent_supervisor/status/supervisor_heartbeat.json`.
- Fields: `pid`, `tmux_session`, `loop_count`, `last_loop_ts`, `current_task`, `last_event_ts`, `started_at`, `version`.
- Written every loop iteration in `daemon_loop()` and immediately upon assignment of a new running task.

### 1.3 Lockfile + duplicate-daemon protection
- File: `claude_worklog/agent_supervisor/supervisor.lock`.
- `acquire_lock()` refuses to start when an existing pid is alive (returns exit code 2 from `daemon_loop`).
- Stale lock with dead pid is taken over.
- `release_lock()` runs in a `try/finally` around the daemon loop.
- Event `duplicate_daemon_blocked` is appended to `events.jsonl` on refusal.

### 1.4 Stale-running detection
- `classify_running_task_alerts()` is the single inspection function.
- Raises `stale_running_no_process` when the registered run pid is dead, no `pgrep` match exists, and either the run output mtime is missing or older than the task timeout.
- `reconcile_stale_running_tasks()` consumes those alerts and:
  - completes the task if required outputs exist with no live process;
  - moves to `blocked_quota` with `resume_after_utc` if quota markers are present;
  - schedules a retry up to `max_attempts`;
  - escalates to `human_attention_required` once retries are exhausted.

### 1.5 No-event-for-N-minutes detection
- Default threshold: `DEFAULT_NO_EVENT_TIMEOUT_S = 1800` (30 min). Per-task override: `no_event_timeout_seconds`.
- Alert `no_event` is raised when `state.last_event_ts` is older than the threshold while the process is still active.
- Reconciler kills the run via retry escalation (does not directly SIGKILL active children — those are bounded by their own subprocess timeout); on max_attempts exhausted, escalates to human_attention_required.

### 1.6 No-output-growth detection
- Default threshold: `DEFAULT_NO_OUTPUT_GROWTH_TIMEOUT_S = 1200` (20 min). Per-task override: `no_output_growth_timeout_seconds`.
- Alert `no_output_growth` is raised when output mtimes (stdout, stderr, summary) have not advanced for the threshold while the process is still alive.

### 1.7 Subprocess hard timeout classification
- `run_cmd_with_pid()` returns `(rc, pid, timed_out)`. The forced 124 exit code on timeout is preserved, plus an explicit boolean.
- `run_task()` annotates the result with `timed_out=True` and sets `last_retry_reason="subprocess_timeout"`.

### 1.8 Quota / auth failure classification
- `classify_agent_block()` and `detect_quota_block()` retained and now feed both the live run path and the reconciler.
- Quota tasks receive `resume_after_utc`; on resume time, claude readiness is re-checked before scheduling a retry.

### 1.9 Retry policy
- Definition fields: `max_attempts` (default 3), `task_timeout_seconds`, `no_event_timeout_seconds`, `no_output_growth_timeout_seconds`.
- State fields: `retry_count`, `resume_after_utc`, `last_retry_reason`.
- On a `failed` outcome, the supervisor schedules a retry with a +5 minute resume window. After the (max_attempts-1)th retry, status moves to `human_attention_required` instead of remaining `failed`.

### 1.10 human_attention_required classification
- New status added to `STATUS_VALUES` and `TERMINAL_BLOCKING_STATUSES`.
- Triggered by:
  - retries exhausted in `run_task()` and `reconcile_stale_running_tasks()`
  - secret scan blocking auto-commit (`attention_reason="secret_scan_blocked_auto_commit"`)
- Selector excludes these tasks from auto-runnable queue (`select_next_task_file`).
- Gate `BLOCKED_HUMAN_ATTENTION_REQUIRED` is surfaced from `derive_gate()` whenever any task is in this status.

### 1.11 Dashboard stale-state alerts
- Dashboard adds:
  - **SUPERVISOR HEARTBEAT** panel (pid, alive, age_s, loop_count, current_task, tmux session, heartbeat_stale flag at 600s).
  - **SUPERVISOR LOCK** panel (holder pid, acquired_at).
  - **STALE-STATE ALERTS** panel (stale_running, no_event, no_output_growth, blocked_quota, human_attention_required with task ids).
  - Counts row extended with `human_attention=N`.

## 2. Files written

| Path | Role |
| --- | --- |
| `claude_worklog/tools/agent_supervisor.py` | reliability-hardened daemon |
| `claude_worklog/tools/agent_supervisor_dashboard.py` | dashboard with heartbeat + alerts |
| `claude_worklog/agent_supervisor_reliability/02_IMPLEMENTATION_REPORT.md` | this report |
| `claude_worklog/agent_supervisor_reliability/03_VALIDATION_REPORT.md` | validation steps and expected outcomes |
| `claude_worklog/agent_supervisor_reliability/04_GO_NO_GO.md` | GO/NO-GO marker |

## 3. Files created at runtime

| Path | Owner | Lifecycle |
| --- | --- | --- |
| `claude_worklog/agent_supervisor/state/tasks/<id>.json` | supervisor | per-task state, append-history capped at 50 |
| `claude_worklog/agent_supervisor/status/supervisor_heartbeat.json` | daemon | overwritten every loop |
| `claude_worklog/agent_supervisor/supervisor.lock` | daemon | acquired on start, released on exit |
| `claude_worklog/agent_supervisor/status/queue_status.json` | every health pulse | now includes alert lists |
| `claude_worklog/agent_supervisor/events.jsonl` | every transition | append-only |

## 4. Safety boundaries observed

- No writes outside the workspace root.
- `BANNED_PATTERNS` and `FORBIDDEN_ROOT` checks in `validate_task` retained.
- Auto-commit still blocked for risk levels above L2 and gated by `safe_secret_scan`. A secret hit now drives `human_attention_required` instead of a silent failure.
- L4/L5 approval logic unchanged.
- No legacy bot mutation, no Redis writes, no exchange-related actions.

## 5. Observability events

New / updated events emitted to `events.jsonl`:
- `task_running`, `task_completed` (existing)
- `stale_running_reconciled` — now carries `alerts`, `output_idle_seconds`, `event_idle_seconds`, `active_process`
- `duplicate_daemon_blocked` — emitted when a second daemon is refused
- `daemon_cancelled` — when `--max-run-hours` triggers a clean exit
- `no_runnable_task` — heartbeat-friendly liveness signal
- `dry_run` (existing)

## 6. Backwards compatibility notes

- Existing legacy task files keep working: on first read by the new daemon, state is migrated and definitions are rewritten without state fields. Tasks under `state/tasks/` become authoritative.
- Existing `runs/<task_id>/summary.json` and `events.jsonl` schema is preserved.
- The dashboard will display "heartbeat: missing" until the new daemon writes its first heartbeat.
