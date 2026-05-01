# 03 — Agent Supervisor Reliability Hardening Validation Report

Validation is performed against the new files. All commands assume the working directory is `/home/wali/Desktop/AI BOT REBUILD`.

## 1. Static / structural verification

| Claim | Evidence | Verification command | Confidence |
| --- | --- | --- | --- |
| New constants for state separation exist | `agent_supervisor.py` defines `DEFINITION_FIELDS`, `STATE_FIELDS`, `STATE_TASKS_DIR` | `grep -nE 'DEFINITION_FIELDS|STATE_FIELDS|STATE_TASKS_DIR' claude_worklog/tools/agent_supervisor.py` | high |
| Heartbeat file path defined | `HEARTBEAT_FILE = STATUS_DIR / "supervisor_heartbeat.json"` | `grep -n 'supervisor_heartbeat.json' claude_worklog/tools/agent_supervisor.py` | high |
| Lockfile + duplicate-daemon guard | `acquire_lock` returns False when live pid holds the lock | `grep -nA10 'def acquire_lock' claude_worklog/tools/agent_supervisor.py` | high |
| Stale alert classifier exists | `classify_running_task_alerts` returns `alerts` list | `grep -nA5 'def classify_running_task_alerts' claude_worklog/tools/agent_supervisor.py` | high |
| `human_attention_required` status registered | Added to `STATUS_VALUES` and `TERMINAL_BLOCKING_STATUSES` | `grep -n 'human_attention_required' claude_worklog/tools/agent_supervisor.py` | high |
| Dashboard surfaces heartbeat + alerts | `[SUPERVISOR HEARTBEAT]` and `[STALE-STATE ALERTS]` headers | `grep -n 'SUPERVISOR HEARTBEAT\|STALE-STATE ALERTS' claude_worklog/tools/agent_supervisor_dashboard.py` | high |

## 2. Runtime smoke tests (operator-driven)

Run the following sequence and capture outputs into `claude_worklog/agent_supervisor_reliability/runtime_evidence/`:

```
python claude_worklog/tools/agent_supervisor.py --migrate
python claude_worklog/tools/agent_supervisor.py --reconcile
python claude_worklog/tools/agent_supervisor.py --dry-run
ls claude_worklog/agent_supervisor/state/tasks/ | head
cat claude_worklog/agent_supervisor/status/queue_status.json
```

Expected:
- `--migrate` prints `{"migrated_definition_files": N}` (N >= 0). After the first run, every existing task definition under `tasks/` should have its STATE_FIELDS removed; rerunning prints 0.
- `state/tasks/<task_id>.json` exists for each task, including the currently running 014 task.
- `--reconcile` prints `{"reconciled": M}`. M is the number of running tasks the new logic transitioned (e.g. promoting `014_agent_supervisor_reliability_hardening` to `completed` when the parent claude subprocess has already exited and the required outputs exist).
- `--dry-run` writes `queue_status.json` with new keys: `stale_running_count`, `no_event_count`, `no_output_growth_count`, `human_attention_required_count`, plus matching `*_tasks` arrays.

## 3. Heartbeat verification

Start a short-lived daemon and inspect the heartbeat:

```
timeout 30 python claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 5 --stop-after-idle-minutes 0.1 || true
cat claude_worklog/agent_supervisor/status/supervisor_heartbeat.json
```

Expected:
- `supervisor_heartbeat.json` exists with `pid`, `loop_count >= 1`, `last_loop_ts` within the last minute, `version: "2.0-reliability-hardened"`.
- `claude_worklog/agent_supervisor/supervisor.lock` is **absent** after exit (lock released in finally clause).

## 4. Duplicate daemon protection

Open two shells. In shell A:

```
python claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30 --stop-after-idle-minutes 30
```

In shell B (while A is still running):

```
python claude_worklog/tools/agent_supervisor.py --daemon --poll-seconds 30 --stop-after-idle-minutes 30
echo $?
```

Expected:
- Shell B exits with code `2` and stderr contains `duplicate daemon: existing pid=...`.
- `events.jsonl` contains a `duplicate_daemon_blocked` entry.

## 5. Stale running reconciliation

Simulate a stale run (no live child process, required outputs already present): rely on the existing 014 task itself, which has required outputs after this batch is materialized. Then run:

```
python claude_worklog/tools/agent_supervisor.py --reconcile
cat claude_worklog/agent_supervisor/state/tasks/014_agent_supervisor_reliability_hardening.json
```

Expected:
- 014 status transitions from `running` to `completed` with `last_summary` referencing required outputs.
- `events.jsonl` shows `stale_running_reconciled` event with `alerts: [...]` and `active_process: false`.

## 6. Retry → human_attention_required escalation

The escalation path is unit-testable by constructing a synthetic state file:

```
python - <<'PY'
import json, pathlib
sp = pathlib.Path("claude_worklog/agent_supervisor/state/tasks/__synthetic_test.json")
sp.write_text(json.dumps({
    "task_id": "__synthetic_test",
    "status": "running",
    "retry_count": 99,
    "last_event_ts": "2020-01-01T00:00:00+00:00",
    "run_pid": None,
}))
PY
```

Construct a matching definition stub:

```
python - <<'PY'
import json, pathlib
tp = pathlib.Path("claude_worklog/agent_supervisor/tasks/__synthetic_test.json")
tp.write_text(json.dumps({
    "task_id": "__synthetic_test",
    "agent": "system_check",
    "risk_level": "L0",
    "max_attempts": 3,
    "task_timeout_seconds": 60,
    "command": "true"
}))
PY
python claude_worklog/tools/agent_supervisor.py --reconcile
cat claude_worklog/agent_supervisor/state/tasks/__synthetic_test.json
```

Expected:
- Status transitions to `human_attention_required`, `attention_reason` set, `last_summary` references "max_attempts ... exhausted".
- `derive_gate()` returns `BLOCKED_HUMAN_ATTENTION_REQUIRED` while this state persists.
- Cleanup: delete the two synthetic files after verification.

## 7. Dashboard rendering

Run the dashboard once (Ctrl+C after one render):

```
python claude_worklog/tools/agent_supervisor_dashboard.py --refresh-seconds 30
```

Expected:
- Output contains `[SUPERVISOR HEARTBEAT]`, `[SUPERVISOR LOCK]`, `[STALE-STATE ALERTS]` sections.
- Counts row includes `human_attention=N`.

## 8. Confidence and missing evidence

- High confidence on structural changes (file contents are observable in the new artifacts).
- Runtime evidence is operator-driven; this report enumerates exact commands and expected outputs. Empirical confirmation should be captured under `claude_worklog/agent_supervisor_reliability/runtime_evidence/` after the operator runs sections 2–7.
