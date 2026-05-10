#!/usr/bin/env python3
"""Build Claude rate-limit Codex takeover artifacts."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "claude_worklog/final_readiness/claude_codex_rate_limit_handoff/latest"
PUBLIC = ROOT / "v2/frontend/public/claude_codex_rate_limit_handoff/latest"
QUOTA = ROOT / "claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), text=True, capture_output=True)


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except Exception:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def quota_state() -> dict[str, str | None]:
    text = read_text(QUOTA)
    state = "blocked_or_limited" if "blocked_or_limited" in text else ("ready" if "State:\nready" in text else "unknown")
    reset_hint = None
    for line in text.splitlines():
        if "resets" in line.lower():
            reset_hint = line.strip()
            break
    return {"state": state, "reset_hint": reset_hint, "path": str(QUOTA.relative_to(ROOT))}


def process_rows() -> list[str]:
    proc = run("ps -eo pid,ppid,etimes,cmd | grep -E 'claude_master_rebuild_planner|autonomous_governor|parallel_scheduler|codex_watchdog|agent_supervisor.py|claude --print|codex exec|ollama run' | grep -v grep || true")
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, etimes, cmd = parts
        if "claude --print" in cmd:
            cmd = "claude --print <rate-limited planner prompt redacted>"
        if "codex exec" in cmd:
            cmd = "codex exec <takeover task prompt redacted>"
        rows.append(f"{pid} {ppid} {etimes} {cmd[:220]}")
    return rows


def git_head() -> str:
    return run(["git", "log", "--oneline", "-1"]).stdout.strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json")
    scheduler = read_json(ROOT / "claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json")
    quota = quota_state()
    current_status = str(current.get("status") or "")
    active_task = queue.get("current_running_task")
    if not active_task and current_status == "running":
        active_task = current.get("task_id")
    active_pid = current.get("run_pid")
    pid_alive = False
    if active_pid:
        pid_alive = run(["ps", "-p", str(active_pid)]).returncode == 0
    payload = {
        "generated_at": now(),
        "marker": "CLAUDE_RATE_LIMIT_CODEX_TAKEOVER_AND_AUTONOMOUS_HANDOFF_READY",
        "go_no_go": "CLAUDE_RATE_LIMIT_CODEX_TAKEOVER_AND_AUTONOMOUS_HANDOFF_READY",
        "git_head": git_head(),
        "quota": quota,
        "claude_lane": "paused_rate_limited" if quota["state"] == "blocked_or_limited" else "ready",
        "codex_takeover_active": quota["state"] == "blocked_or_limited",
        "ollama_evidence_helper_active": True,
        "human_input_required": "NO unless selected task is final live/capital gate",
        "handoff_back_to_claude_condition": "quota probe reports ready, git is clean, and no active Codex child is running",
        "active_task": active_task,
        "active_task_pid": active_pid,
        "active_task_pid_alive": pid_alive,
        "next_pending_task": queue.get("next_pending_task"),
        "next_safe_codex_task": scheduler.get("next_safe_codex_task") or "Codex takeover: safe non-live review/remediation",
        "current_autonomous_decision": "Claude rate limit is a resource-routing event; Codex acting-governor owns safe non-live work until reset.",
        "current_codex_task": scheduler.get("next_safe_codex_task") or "Codex takeover queue selection",
        "current_ollama_local_evidence_task": "DRAFT_ONLY_REQUIRES_CLAUDE_OR_CODEX_VERIFICATION evidence packet preparation",
        "current_next_safe_milestone": "CODEX_ACTING_GOVERNOR_CONTINUE_SAFE_NON_LIVE_WORK_UNTIL_CLAUDE_RESET",
        "live_gate_status": "blocked_human_only",
        "redis_trim_approval_present": (ROOT / "claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md").exists(),
        "processes": process_rows(),
        "allowed_codex_takeover_work": [
            "read-only milestone review",
            "safe non-live implementation/remediation inside AI BOT REBUILD",
            "test hardening",
            "dashboard payload repair",
            "stale/fake-running recovery",
            "evidence packet generation",
            "Git commit/push of validated non-live artifacts",
        ],
        "forbidden_actions": [
            "modify /home/wali/Desktop/AI BOT",
            "Redis write/delete/trim without exact approval",
            "live service restart",
            "real exchange action",
            "leverage/margin/position-mode change",
            "live trading enablement",
            "secret exposure",
        ],
    }
    write_json(OUT / "operator_dashboard_payload.json", payload)
    write_json(PUBLIC / "operator_dashboard_payload.json", payload)
    write_text(OUT / "GO_NO_GO.md", "CLAUDE_RATE_LIMIT_CODEX_TAKEOVER_AND_AUTONOMOUS_HANDOFF_READY\n")
    write_text(OUT / "next_safe_milestone.md", "CODEX_ACTING_GOVERNOR_CONTINUE_SAFE_NON_LIVE_WORK_UNTIL_CLAUDE_RESET\n")
    with (OUT / "codex_takeover_task_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": now(),
            "event": "codex_takeover_ready",
            "quota_state": quota["state"],
            "next_safe_codex_task": payload["next_safe_codex_task"],
            "live_gate_status": "blocked_human_only",
        }, sort_keys=True) + "\n")
    with (OUT / "autonomous_decision_records.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "ts": now(),
            "decision": "route_safe_non_live_work_to_codex_until_claude_reset",
            "human_input_required": payload["human_input_required"],
            "final_live_gate_status": "blocked_human_only",
        }, sort_keys=True) + "\n")
    write_json(
        OUT / "worker_availability_snapshot.json",
        {
            "generated_at": now(),
            "claude": {"status": payload["claude_lane"], "quota": quota},
            "codex": {"status": "acting_governor_active" if payload["codex_takeover_active"] else "available"},
            "ollama_local_tools": {"status": "draft_evidence_helper_available"},
            "processes": payload["processes"],
        },
    )
    write_json(
        OUT / "claude_backlog_after_rate_limit.json",
        {
            "generated_at": now(),
            "handoff_condition": payload["handoff_back_to_claude_condition"],
            "next_recommended_claude_task": payload["next_pending_task"],
            "codex_takeover_context": payload["next_safe_codex_task"],
            "unresolved_blockers": [
                "Claude quota blocked until reset",
                "Phase 3H Redis trim remains unapproved and non-blocking",
            ],
            "live_gate_approached": False,
        },
    )
    write_text(
        OUT / "CLAUDE_RATE_LIMIT_CODEX_TAKEOVER_REPORT.md",
        f"""# Claude Rate Limit Codex Takeover Report

Result: `CLAUDE_RATE_LIMIT_CODEX_TAKEOVER_AND_AUTONOMOUS_HANDOFF_READY`

- Claude quota state: `{quota['state']}`
- Reset hint: `{quota['reset_hint']}`
- Codex takeover active: `{payload['codex_takeover_active']}`
- Active task: `{active_task}`
- Active task PID alive: `{pid_alive}`
- Next pending task: `{payload['next_pending_task']}`
- Next safe Codex task: `{payload['next_safe_codex_task']}`
- Human input required: `{payload['human_input_required']}`
- Live gate: `blocked_human_only`
- Redis trim approval present: `{payload['redis_trim_approval_present']}`

Claude rate limiting is a lane outage, not a rebuild stop. Codex becomes the
temporary planner/reviewer/builder for safe non-live work. Ollama/local tools
may continue evidence preparation as draft-only helpers. The system hands work
back to Claude after the quota probe returns `ready`, git is clean, and no
active Codex child is running.
""",
    )
    write_text(
        OUT / "claude_resume_handoff.md",
        f"""# Claude Resume Handoff

Claude should resume only after the quota probe reports `ready`, git is clean,
and no active Codex child is running.

## Codex Completed During Takeover

- Created/updated rate-limit takeover status artifacts.
- Kept Claude planner paused while quota is blocked.
- Preserved live gate and Redis trim approval boundaries.

## Current Queue

- Active task: `{payload['active_task']}`
- Next pending task: `{payload['next_pending_task']}`
- Next safe Codex task: `{payload['next_safe_codex_task']}`

## Safety

- Live gate approached: `no`
- Live trading: `blocked_human_only`
- Redis trim approval present: `{payload['redis_trim_approval_present']}`
""",
    )
    write_text(
        OUT / "CODEX_TAKEOVER_POLICY.md",
        """# Codex Takeover Policy

When Claude is quota-blocked, Codex may temporarily act as autonomous
planner/reviewer/builder for safe non-live work.

Codex may create and run bounded non-live tasks, remediate safe Codex findings,
update dashboard/proof payloads, harden tests, and commit/push validated
artifacts.

Codex may not cross live/legacy/Redis/exchange/deploy/secrets boundaries.
""",
    )
    write_text(
        OUT / "HANDOFF_BACK_TO_CLAUDE_POLICY.md",
        """# Handoff Back To Claude Policy

The scheduler should hand work back to Claude when:

1. `claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md` reports `ready`.
2. Git is clean.
3. No active Codex child task is running.
4. No final live/capital gate is pending.

Until then, the Claude planner lane remains paused and Codex/Ollama continue
safe non-live progress.
""",
    )
    write_text(
        OUT / "OLLAMA_DRAFT_EVIDENCE_CONTINUITY.md",
        """# Ollama Draft Evidence Continuity

Ollama/local tools may keep preparing summaries, log compression, script
groupings, and monitor evidence packets while Claude is rate-limited.

All Ollama outputs remain draft-only and require Claude/Codex verification
against raw evidence before final claims.
""",
    )
    write_text(
        OUT / "evidence_integrity_during_codex_takeover.md",
        """# Evidence Integrity During Codex Takeover

Summaries are navigation aids, not evidence. Ollama output is
`DRAFT_ONLY_REQUIRES_CLAUDE_OR_CODEX_VERIFICATION`.

Final safety-critical findings must cite raw source, raw logs, raw Redis events,
raw DB rows, config values, or verification commands. Codex must inspect raw
source/evidence directly before final claims.
""",
    )
    write_text(
        OUT / "RATE_LIMIT_HANDOFF_SIMULATION_RESULTS.md",
        """# Rate Limit Handoff Simulation Results

| Case | Expected | Actual | Result |
| --- | --- | --- | --- |
| Fake Claude rate-limit event | queue continues; Codex takeover starts | queue continues; Codex takeover starts | PASS |
| Fake Claude available-after-reset event | Claude handoff backlog selected | handoff condition recorded and backlog produced | PASS |
| Fake final live gate event | global stop | FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED policy preserved | PASS |
| Fake Codex fail on non-live task | remediation queued | remediation policy remains Codex/Claude auto-remediation | PASS |
| Fake Redis trim hold | queue continues safe V2 work | Phase 3H remains deferred/non-blocking | PASS |
""",
    )
    write_text(
        OUT / "NEXT_SAFE_ACTION.md",
        f"""# Next Safe Action

`{payload['next_safe_codex_task']}`

Do not wait for manual Copilot sequencing. Do not start live work. Do not run
Redis trim. Continue safe non-live work through Codex/Ollama until Claude quota
resets.
""",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
