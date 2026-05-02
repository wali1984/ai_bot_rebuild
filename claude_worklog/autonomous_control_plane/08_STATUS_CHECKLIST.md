# Autonomous Rebuild Status Checklist

## Purpose

This checklist defines how to inspect the autonomous AI BOT REBUILD safely without interrupting Claude, Codex, Ollama, the supervisor, or the legacy live bot.

## Golden Rule

Status checks are read-only.

Do not manually run implementation tasks unless the controller is stopped and a recovery plan explicitly says to.

## Current autonomous architecture

- Claude Master Rebuild Planner:
  - reads requirements inbox
  - generates safe non-live tasks
  - bridges tasks into agent_supervisor
  - tracks active requirement and milestone

- Agent Supervisor:
  - executes generated tasks
  - writes runtime state
  - materializes BEGIN_FILE outputs
  - enforces allowed output paths
  - handles validation, timeout, quota/auth classifications

- Codex:
  - reviews each milestone
  - produces PASS/FAIL markers
  - blocks unsafe or incomplete work

- Ollama:
  - local summarization / context compression

- Legacy bot:
  - read-only monitored
  - not mutated
  - not restarted

## Status levels

### Green

Healthy if all are true:

- Git clean or only ignored runtime files changed
- Claude Master Planner running
- No human_attention_required
- No blocked_human_only except final live gate
- No secret scan failures
- No live/Redis/legacy/exchange/deploy action attempted
- 015A-015F complete
- final live gate remains blocked
- active task is non-live
- Codex review tasks progress after implementation tasks

### Yellow

Investigate if:

- Planner running but no events for more than expected poll interval
- Current task running with quiet stdout/stderr but child process alive and under timeout
- Git dirty while task is running
- Queue display stale but runtime state is consistent
- Codex review pending after implementation completion
- quota block has resume_after_utc

### Red

Stop and inspect if:

- human_attention_required
- blocked_auth without clear prompt-permission-model explanation
- blocked_quota without resume_after_utc
- secret scan high-confidence failure
- task attempts /home/wali/Desktop/AI BOT mutation
- Redis write/delete attempt
- service restart attempt
- exchange/order/leverage/margin attempt
- deployment attempt
- live trading enablement attempt
- implementation task runs out of sequence
- final live gate is bypassed

## Standard quick status command

Run:

```bash
cd "$HOME/Desktop/AI BOT REBUILD"
./claude_worklog/tools/status_claude_master_rebuild_planner.sh
```

## Full safe status command

Run:

```bash
cd "$HOME/Desktop/AI BOT REBUILD"

echo "=== TIME ==="
date -Is

echo
echo "=== GIT ==="
git status --short
git log --oneline -5

echo
echo "=== MASTER PLANNER ==="
./claude_worklog/tools/status_claude_master_rebuild_planner.sh 2>/dev/null || true

echo
echo "=== SUPERVISOR ==="
./claude_worklog/tools/status_autonomous_agent_supervisor.sh 2>/dev/null || true

echo
echo "=== ACTIVE AGENT PROCESSES ==="
ps -eo pid,ppid,etimes,cmd | grep -E "claude_master_rebuild_planner.py|agent_supervisor.py|claude --print|codex exec|ollama run" | grep -v grep || true

echo
echo "=== MASTER PLANNER STATUS ==="
cat claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json 2>/dev/null || true

echo
echo "=== PLANNER STATUS ==="
cat claude_worklog/agent_supervisor/status/planner_status.json 2>/dev/null || true

echo
echo "=== CURRENT STATUS ==="
cat claude_worklog/agent_supervisor/status/current_status.json 2>/dev/null || true

echo
echo "=== QUEUE STATUS ==="
cat claude_worklog/agent_supervisor/status/queue_status.json 2>/dev/null || true

echo
echo "=== REQUIREMENTS INBOX ==="
find claude_worklog/requirements_inbox -maxdepth 1 -type f -name "*.md" | sort

echo
echo "=== LATEST EVENTS ==="
tail -n 80 claude_worklog/agent_supervisor/events.jsonl 2>/dev/null || true

echo
echo "=== LIVE SAFETY GATES ==="
grep -RInE "LIVE_MUTATION_BLOCKED|blocked_human_only|FINAL.*LIVE|LIVE.*BLOCKED" \
  claude_worklog/agent_supervisor/status \
  claude_worklog/final_readiness \
  claude_worklog/autonomous_control_plane \
  2>/dev/null || true
```

## Sequence status command

Run:

```bash
cd "$HOME/Desktop/AI BOT REBUILD"

python3 - <<'PY'
import json
from pathlib import Path

task_ids = [
    "015a_repo_package_skeleton",
    "015b_database_migration_skeleton",
    "015c_api_route_skeleton",
    "015d_enterprise_frontend_shell",
    "015e_test_ci_skeleton",
    "015f_agent_dashboard_integration",
    "030_legacy_ingestor_copy_and_hash_inventory",
    "031_dynamic_symbol_universe_foundation",
    "041_feature_snapshot_attribution_pipeline_foundation",
    "042_coinank_uploaded_symbol_alias_fixture",
]

for tid in task_ids:
    p = Path(f"claude_worklog/agent_supervisor/state/tasks/{tid}.json")
    d = json.loads(p.read_text()) if p.exists() else {}
    print(f"{tid}: {d.get('status')} | {d.get('last_summary', '')}")
PY
```

## Current requirement processing check

Run:

```bash
cd "$HOME/Desktop/AI BOT REBUILD"

echo "=== Active requirement ==="
cat claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json 2>/dev/null | grep -E "active_requirement|active_task|current_phase|codex_gate|blocked_reason|human_attention_required|next_action" || true

echo
echo "=== Inbox ==="
ls -1 claude_worklog/requirements_inbox

echo
echo "=== Runtime planner output ==="
ls -lh claude_worklog/agent_supervisor/runtime/master_planner 2>/dev/null || true
```

## When to leave it alone

Leave the system running if:

- an active Claude/Codex process exists,
- the task is non-live,
- no high-confidence secret scan failed,
- no safety gate is tripped,
- implementation tasks are in expected order,
- final live gate remains blocked.

## When to stop daemon

Stop only if Red condition occurs.

Commands:

```bash
cd "$HOME/Desktop/AI BOT REBUILD"

./claude_worklog/tools/stop_claude_master_rebuild_planner.sh || true
./claude_worklog/tools/stop_autonomous_agent_supervisor.sh || true
./claude_worklog/tools/stop_agent_supervisor_daemon.sh || true

pkill -f "claude_master_rebuild_planner.py" || true
pkill -f "agent_supervisor.py --autonomous-daemon" || true
pkill -f "agent_supervisor.py --daemon" || true
pkill -f "claude --print" || true
pkill -f "codex exec" || true
pkill -f "ollama run" || true
```

## Dashboard

Dashboard should be launched in a detached terminal and left running. It is for observation only.

Expected command:

```bash
cd "$HOME/Desktop/AI BOT REBUILD"
./claude_worklog/tools/launch_agent_supervisor_dashboard.sh
```

STATUS_CHECKLIST_READY
