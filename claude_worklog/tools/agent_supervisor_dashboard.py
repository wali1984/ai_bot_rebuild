#!/usr/bin/env python3
"""Agent Supervisor Dashboard — reliability-hardened build.

Surfaces:
- Heartbeat (pid, age, loop_count, current_task, tmux session, heartbeat_stale flag)
- Lockfile holder
- Stale-state alerts (stale_running, no_event, no_output_growth)
- Quota / auth blocks
- human_attention_required tasks
- Existing queue/agent/process panels
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import time
from typing import Any, Dict, List, Optional

BASE = pathlib.Path("claude_worklog/agent_supervisor")
EVENTS = BASE / "events.jsonl"
STATUS = BASE / "status/current_status.json"
QUEUE_STATUS = BASE / "status/queue_status.json"
AGENT_HEALTH = BASE / "status/agent_health.json"
PLANNER_STATUS = BASE / "status/planner_status.json"
HEARTBEAT = BASE / "status/supervisor_heartbeat.json"
LOCK_FILE = BASE / "supervisor.lock"
RUNS = BASE / "runs"
TRACKED_PLANNER = BASE / "planner"
RUNTIME_PLANNER = BASE / "runtime/planner"
PLANNER_DECISION = RUNTIME_PLANNER / "PLANNER_DECISION.md"
PLANNER_HUMAN_ACTION = RUNTIME_PLANNER / "HUMAN_ACTION_REQUIRED.md"
PLANNER_GO_NO_GO = RUNTIME_PLANNER / "PLANNER_GO_NO_GO.md"
NEXT_PHASE = BASE / "state/NEXT_PHASE.md"
WORKSPACE = pathlib.Path(os.path.expanduser("~/Desktop/AI BOT REBUILD"))
REQUIREMENTS_INBOX = WORKSPACE / "claude_worklog/requirements_inbox"
MASTER_PLANNER_STATUS = WORKSPACE / "claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json"
EVIDENCE_RECONCILIATION_STATUS = WORKSPACE / "claude_worklog/agent_supervisor/status/evidence_reconciliation_status.json"
MASTER_PLANNER_SESSION = "ai_bot_claude_master_rebuild_planner"

HEARTBEAT_STALE_S = 600


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def planner_text(path: pathlib.Path) -> str:
    txt = read_text(path)
    if txt:
        return txt
    return read_text(TRACKED_PLANNER / path.name)


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def read_evidence_reconciliation_status() -> Dict[str, Any]:
    return read_json(EVIDENCE_RECONCILIATION_STATUS)


def cmd_out(cmd: List[str]) -> str:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip()
    except Exception:
        return ""


def git_cleanliness() -> str:
    out = cmd_out(["git", "-C", str(WORKSPACE), "status", "--short"])
    substantive = substantive_git_status_lines(out)
    return "clean" if not substantive else "dirty"


def substantive_git_status_lines(raw: str) -> List[str]:
    ignored_exact = {
        "claude_worklog/agent_supervisor/status/agent_health.json",
        "claude_worklog/agent_supervisor/status/supervisor_heartbeat.json",
        "claude_worklog/agent_supervisor/status/phase_017_watchdog.json",
        "claude_worklog/agent_supervisor/status/planner_status.json",
        "claude_worklog/agent_supervisor/supervisor.lock",
    }
    ignored_prefixes = (
        "claude_worklog/agent_supervisor/runtime/",
        "claude_worklog/agent_supervisor/runs/",
        "claude_worklog/agent_supervisor/state/tasks/",
    )
    lines: List[str] = []
    for ln in raw.splitlines():
        rel = ln[3:].strip() if len(ln) >= 4 else ln.strip()
        if rel in ignored_exact or any(rel.startswith(pfx) for pfx in ignored_prefixes):
            continue
        lines.append(ln)
    return lines


def which(name: str) -> Optional[str]:
    out = cmd_out(["bash", "-lc", f"command -v {name} || true"])
    return out.splitlines()[0].strip() if out.strip() else None


def process_lines(pattern: str) -> List[str]:
    out = cmd_out(["bash", "-lc", f"pgrep -af {pattern!r} || true"])
    return [ln for ln in out.splitlines() if ln.strip()]


def tmux_session_running(name: str) -> bool:
    try:
        p = subprocess.run(["tmux", "has-session", "-t", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        return p.returncode == 0
    except Exception:
        return False


def requirements_inbox_summary(master_status: Dict[str, Any]) -> Dict[str, Any]:
    files = sorted(p.name for p in REQUIREMENTS_INBOX.glob("REQ_*.md")) if REQUIREMENTS_INBOX.exists() else []
    processed = set(str(x) for x in (master_status.get("processed_requirements") or []))
    unprocessed = [name for name in files if name not in processed]
    return {
        "total": len(files),
        "processed": len(processed),
        "unprocessed": unprocessed,
    }


def process_running_for_task(task_id: str) -> bool:
    if not task_id:
        return False
    out = cmd_out(["bash", "-lc", f"pgrep -af {task_id!r} || true"])
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or "pgrep -af" in ln:
            continue
        return True
    return False


def task_state(task_id: str) -> Dict[str, Any]:
    if not task_id:
        return {}
    p = WORKSPACE / f"claude_worklog/agent_supervisor/state/tasks/{task_id}.json"
    return read_json(p)


def task_definition(task_id: str) -> Dict[str, Any]:
    if not task_id:
        return {}
    p = WORKSPACE / f"claude_worklog/agent_supervisor/tasks/{task_id}.json"
    return read_json(p)


def task_definition_path(task_id: str) -> str:
    return f"claude_worklog/agent_supervisor/tasks/{task_id}.json" if task_id else "-"


def task_runtime_state_path(task_id: str) -> str:
    return f"claude_worklog/agent_supervisor/state/tasks/{task_id}.json" if task_id else "-"


def last_events(n: int = 10) -> List[str]:
    if not EVENTS.exists():
        return []
    lines = EVENTS.read_text(encoding="utf-8", errors="ignore").splitlines()
    return lines[-n:]


def latest_agent_summary(agent_name: str) -> str:
    if not RUNS.exists():
        return "N/A"
    latest_mtime = 0.0
    latest_summary = "N/A"
    for run_dir in RUNS.glob("*"):
        summary = run_dir / "summary.json"
        if not summary.exists():
            continue
        data = read_json(summary)
        if str(data.get("agent")) != agent_name:
            continue
        mtime = summary.stat().st_mtime
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_summary = f"{data.get('task_id')} | {data.get('status')} | {data.get('summary')}"
    return latest_summary


def parse_iso_utc(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def heartbeat_age_seconds(hb: Dict[str, Any]) -> Optional[float]:
    parsed = parse_iso_utc(hb.get("last_loop_ts"))
    if parsed is None:
        return None
    return (dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()


def heartbeat_pid_alive(hb: Dict[str, Any]) -> Optional[bool]:
    pid = hb.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def continuous_monitor_status() -> str:
    log_path = WORKSPACE / "claude_worklog/monitoring/read_only_monitor.log"
    if not log_path.exists():
        return "unknown"
    txt = read_text(log_path)
    if "CRITICAL" in txt[-5000:]:
        return "critical-alerts-present"
    return "active-or-last-run-no-critical-tail"


def v2_build_gate_status() -> str:
    candidates = [
        WORKSPACE / "claude_worklog/v2_architecture_codex_review/16_ACTUAL_CODEX_RERUN_GO_NO_GO.md",
        WORKSPACE / "claude_worklog/v2_scaffold_planning/08_SCAFFOLD_PLANNING_GO_NO_GO.md",
        WORKSPACE / "claude_worklog/v2_scaffold_queue/06_CODEX_QUEUE_GO_NO_GO.md",
        WORKSPACE / "claude_worklog/v2_scaffold_queue/07_REMEDIATION_GO_NO_GO.md",
    ]
    lines = []
    for p in candidates:
        if p.exists():
            marker = read_text(p).splitlines()
            first = next((ln.strip() for ln in marker if ln.strip()), "unknown")
            lines.append(f"{p.name}:{first}")
    return " | ".join(lines) if lines else "unknown"


def live_mutation_gate_status() -> str:
    return "LIVE_MUTATION_BLOCKED_BY_DEFAULT"


def first_content_line(text: str) -> str:
    for ln in (text or "").splitlines():
        if ln.strip() and not ln.strip().startswith("#"):
            return ln.strip()
    return "-"


def autonomous_phase(planner: Dict[str, Any], queue: Dict[str, Any]) -> str:
    planner_status = str(planner.get("planner_status", "")).lower()
    if planner_status == "running":
        return "AUTONOMOUS_PLANNER_RUNNING"
    if bool(planner.get("human_action_required", False)):
        return "HUMAN_ACTION_REQUIRED"

    next_phase_marker = read_text(WORKSPACE / NEXT_PHASE)
    marker_upper = next_phase_marker.upper()
    next_planned = str(planner.get("next_planned_task") or "").lower()

    if "NEXT_PHASE_V2_SCAFFOLD_QUEUE_CREATION" in marker_upper:
        return "READY_FOR_V2_SCAFFOLD_QUEUE_CREATION"
    if next_planned.startswith("015") or "scaffold_queue" in next_planned:
        return "V2_SCAFFOLD_QUEUE_PLANNING"

    blocked_impl = int((queue.get("counts") or {}).get("blocked", 0) or 0)
    next_pending = str(queue.get("next_pending_task") or "")
    if blocked_impl > 0 and (next_pending.startswith("015") or next_planned.startswith("015")):
        return "V2_SCAFFOLD_IMPLEMENTATION_BLOCKED_APPROVAL"

    return "AUTONOMOUS_PLANNER_IDLE"


def render_alert_lines(queue: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    counts = {
        "stale_running": int(queue.get("stale_running_count", 0) or 0),
        "no_event": int(queue.get("no_event_count", 0) or 0),
        "no_output_growth": int(queue.get("no_output_growth_count", 0) or 0),
        "human_attention_required": int(queue.get("human_attention_required_count", 0) or 0),
    }
    blocked_quota = queue.get("blocked_quota") or {}
    has_alerts = any(v > 0 for v in counts.values()) or bool(blocked_quota)
    if not has_alerts:
        lines.append("no stale-state alerts")
        return lines

    if counts["stale_running"]:
        ids = queue.get("stale_running_tasks") or []
        lines.append(f"stale_running ({counts['stale_running']}): {', '.join(ids[:5]) or '-'}")
    if counts["no_event"]:
        ids = queue.get("no_event_tasks") or []
        lines.append(f"no_event ({counts['no_event']}): {', '.join(ids[:5]) or '-'}")
    if counts["no_output_growth"]:
        ids = queue.get("no_output_growth_tasks") or []
        lines.append(f"no_output_growth ({counts['no_output_growth']}): {', '.join(ids[:5]) or '-'}")
    if blocked_quota:
        lines.append(
            f"blocked_quota: {blocked_quota.get('task_id')} agent={blocked_quota.get('agent')} "
            f"resume={blocked_quota.get('resume_after_utc')}"
        )
    if counts["human_attention_required"]:
        for entry in (queue.get("human_attention_required_tasks") or [])[:5]:
            lines.append(
                f"human_attention_required: {entry.get('task_id')} agent={entry.get('agent')} "
                f"reason={entry.get('attention_reason') or entry.get('last_summary') or '-'}"
            )
    return lines


def print_dashboard(refresh_seconds: int) -> None:
    while True:
        os.system("clear")
        now = dt.datetime.now().isoformat()

        current = read_json(WORKSPACE / STATUS)
        queue = read_json(WORKSPACE / QUEUE_STATUS)
        health = read_json(WORKSPACE / AGENT_HEALTH)
        planner = read_json(WORKSPACE / PLANNER_STATUS)
        master_planner = read_json(MASTER_PLANNER_STATUS)
        req_summary = requirements_inbox_summary(master_planner if isinstance(master_planner, dict) else {})
        master_planner_daemon = tmux_session_running(MASTER_PLANNER_SESSION)
        current_task_id = str(current.get("task_id") or "") if isinstance(current, dict) else ""
        current_task_status = str(current.get("status") or "") if isinstance(current, dict) else ""
        current_task_state = task_state(current_task_id)
        current_task_def = task_definition(current_task_id)
        current_state_status = str(current_task_state.get("status") or "")
        current_def_status = str(current_task_def.get("status") or "")
        current_state_source = "runtime" if current_task_state else ("definition fallback" if current_def_status else "default pending")
        current_task_proc = process_running_for_task(current_task_id)
        running_state_stale = (
            current_task_status == "running"
            and current_state_status not in {"running", "completed"}
            and (not current_task_proc)
        )
        heartbeat = read_json(WORKSPACE / HEARTBEAT)
        lockfile = read_json(WORKSPACE / LOCK_FILE)

        claude_path = which("claude")
        codex_path = which("codex")
        ollama_path = which("ollama")

        claude_ps = process_lines("claude")
        codex_ps = process_lines("codex")
        ollama_ps = process_lines("ollama")
        supervisor_ps = process_lines("agent_supervisor.py")

        counts = queue.get("counts", {}) if isinstance(queue, dict) else {}
        blocked_quota = queue.get("blocked_quota", {}) if isinstance(queue, dict) else {}
        next_pending = queue.get("next_pending_task", "-")
        running_task = queue.get("current_running_task", "-")
        gate = queue.get("gate", "ARCHITECTURE_REMEDIATION_PARTIAL")
        claude_state = ((health.get("claude") or {}).get("ready_marker")) if isinstance(health, dict) else None
        codex_state = ((health.get("codex") or {}).get("ready_marker")) if isinstance(health, dict) else None
        ollama_models = ((health.get("ollama") or {}).get("models")) if isinstance(health, dict) else []
        last_auto_commit_hash = health.get("last_auto_commit_hash") if isinstance(health, dict) else None
        planner_status = planner.get("planner_status", "idle") if isinstance(planner, dict) else "idle"
        planner_decision_summary = planner.get("decision_summary") if isinstance(planner, dict) else "-"
        autonomous_mode_active = bool(planner.get("autonomous_mode_active")) if isinstance(planner, dict) else False
        human_action_required = bool(planner.get("human_action_required")) if isinstance(planner, dict) else False
        next_planned_task = planner.get("next_planned_task") if isinstance(planner, dict) else None
        will_execute_automatically = bool(planner.get("will_execute_automatically")) if isinstance(planner, dict) else False
        planner_go_no_go = planner_text(WORKSPACE / PLANNER_GO_NO_GO) or str(planner.get("planner_go_no_go", "-"))
        human_action_text = planner_text(WORKSPACE / PLANNER_HUMAN_ACTION)
        planner_decision_line = first_content_line(planner_text(WORKSPACE / PLANNER_DECISION))
        auto_phase = autonomous_phase(planner if isinstance(planner, dict) else {}, queue if isinstance(queue, dict) else {})

        current_time = dt.datetime.now(dt.timezone.utc)
        last_event_lines = last_events(1)
        last_event_age = "-"
        if last_event_lines:
            try:
                evt = json.loads(last_event_lines[-1])
                ts = parse_iso_utc(evt.get("ts"))
                if ts is not None:
                    last_event_age = str(int((current_time - ts).total_seconds()))
            except Exception:
                last_event_age = "-"

        hb_age = heartbeat_age_seconds(heartbeat)
        hb_alive = heartbeat_pid_alive(heartbeat)
        hb_stale = (hb_age is not None and hb_age > HEARTBEAT_STALE_S) or (hb_alive is False)

        print("=" * 96)
        print("AI BOT REBUILD - Agent Supervisor Dashboard (reliability-hardened)")
        print(f"Timestamp: {now} | Refresh: {refresh_seconds}s")
        print("=" * 96)
        print("VS Code/Copilot is terminal operator only.")
        print("Claude is planner/builder | Codex is reviewer | Copilot is shell/status assistant")

        print("\n[SUPERVISOR HEARTBEAT]")
        if heartbeat:
            print(f"pid: {heartbeat.get('pid')} (alive: {hb_alive})")
            print(f"started_at: {heartbeat.get('started_at')}")
            print(f"last_loop_ts: {heartbeat.get('last_loop_ts')}  age_s: {int(hb_age) if hb_age is not None else '-'}")
            print(f"loop_count: {heartbeat.get('loop_count')}")
            print(f"current_task: {heartbeat.get('current_task') or '-'}")
            print(f"tmux_session: {heartbeat.get('tmux_session') or '-'}")
            print(f"version: {heartbeat.get('version') or '-'}")
            print(f"heartbeat_stale: {'YES' if hb_stale else 'no'} (threshold {HEARTBEAT_STALE_S}s)")
        else:
            print("heartbeat: missing (daemon never started?)")

        print("\n[SUPERVISOR LOCK]")
        if lockfile:
            print(f"holder pid: {lockfile.get('pid')} acquired_at: {lockfile.get('acquired_at')}")
        else:
            print("lock: not held")

        print("\n[STALE-STATE ALERTS]")
        for line in render_alert_lines(queue if isinstance(queue, dict) else {}):
            print(f"  {line}")

        print("\n[AGENT INSTALL / HEALTH]")
        print(f"Claude installed: {'yes' if claude_path else 'no'} | path: {claude_path or '-'}")
        print(f"Claude ready marker: {'yes' if claude_state else 'no'}")
        print(f"Codex installed: {'yes' if codex_path else 'no'} | path: {codex_path or '-'}")
        print(f"Codex ready marker: {'yes' if codex_state else 'no'}")
        print(f"Ollama installed: {'yes' if ollama_path else 'no'} | path: {ollama_path or '-'}")
        print(f"Ollama models: {', '.join(ollama_models) if ollama_models else '-'}")

        print("\n[PROCESS STATUS]")
        print(f"claude processes: {len(claude_ps)}")
        print(f"codex processes: {len(codex_ps)}")
        print(f"ollama processes: {len(ollama_ps)}")
        print(f"agent supervisor running: {'yes' if supervisor_ps else 'no'}")

        print("\n[CLAUDE FULL AUTOMATION]")
        print(f"requirements inbox count: {req_summary.get('total', 0)}")
        print(f"requirements processed: {req_summary.get('processed', 0)}")
        unprocessed_req = req_summary.get("unprocessed") or []
        print(f"requirements unprocessed: {', '.join(unprocessed_req[:8]) if unprocessed_req else '-'}")
        print(f"master planner daemon: {'running' if master_planner_daemon else 'stopped'}")
        print(f"active requirement: {master_planner.get('active_requirement') or '-'}")
        print(f"active milestone: {master_planner.get('active_milestone') or '-'}")
        print(f"active task: {master_planner.get('active_task') or '-'}")
        print(f"current phase: {master_planner.get('current_phase') or '-'}")
        print(f"Claude Code profile: {master_planner.get('claude_code_profile') or 'Max20 consolidated default'}")
        print(f"task granularity mode: {master_planner.get('task_granularity_mode') or 'consolidated_default'}")
        print(f"split fallback enabled: {'yes' if master_planner.get('split_fallback_enabled', True) else 'no'}")
        print(f"quota monitor enabled: {'yes' if master_planner.get('quota_monitor_enabled', True) else 'no'}")
        print(f"Codex parallel lane: {master_planner.get('codex_parallel_lane') or 'Codex Pro parallel review/autofix lane'}")
        print(f"Codex parallel enabled: {'yes' if master_planner.get('codex_parallel_lane_enabled', True) else 'no'}")
        print(f"Codex parallel policy: {master_planner.get('codex_parallel_lane_policy') or 'git_clean_and_no_active_dirty_claude_output'}")
        print(f"active Codex gate: {master_planner.get('codex_gate') or '-'}")
        print(f"final live gate status: {master_planner.get('final_live_gate_status') or 'blocked_human_only'}")
        print(f"master planner blocked reason: {master_planner.get('blocked_reason') or '-'}")
        if unprocessed_req and not master_planner_daemon:
            print("warning: master planner daemon is stopped with unprocessed requirements")
        if unprocessed_req and not master_planner.get("active_requirement"):
            print("warning: requirements exist but planner has not selected an active requirement")
        print("manual task-design warning: use requirements_inbox; Claude should generate non-live tasks and Codex reviews")

        print("\n[QUEUE STATUS]")
        print(f"current gate: {gate}")
        print(f"autonomous phase: {auto_phase}")
        print(f"next pending task: {next_pending}")
        print(f"current running task: {running_task}")
        if blocked_quota:
            print(f"blocked_quota task: {blocked_quota.get('task_id')} | resume_after_utc: {blocked_quota.get('resume_after_utc')}")
        else:
            print("blocked_quota task: -")
        print(
            "counts => "
            f"completed={counts.get('completed', 0)} "
            f"failed={counts.get('failed', 0)} "
            f"blocked={counts.get('blocked', 0)} "
            f"pending={counts.get('pending', 0)} "
            f"running={counts.get('running', 0)} "
            f"retry={counts.get('retry_scheduled', 0)} "
            f"human_attention={counts.get('human_attention_required', 0)}"
        )

        print("\n[LATEST TASK STATUS]")
        print(f"latest task id: {current.get('task_id', '-')}")
        print(f"latest task agent: {current.get('agent', '-')}")
        print(f"latest task status: {current.get('status', '-')}")
        if current_task_id:
            print(
                f"latest task runtime-state: {current_state_status or '-'} "
                f"| process_alive: {'yes' if current_task_proc else 'no'} "
                f"| stale_status_view: {'yes' if running_state_stale else 'no'}"
            )
            print(f"task definition path: {task_definition_path(current_task_id)}")
            print(f"runtime state path: {task_runtime_state_path(current_task_id)}")
            print(f"runtime status: {current_state_status or '-'}")
            print(f"task definition status: {current_def_status or '-'}")
            print(f"state source: {current_state_source}")
        print(f"latest Claude run summary: {latest_agent_summary('claude')}")
        print(f"latest Codex run summary: {latest_agent_summary('codex')}")
        print(f"latest Ollama run summary: {latest_agent_summary('ollama')}")
        print(f"last auto-commit hash: {last_auto_commit_hash or '-'}")

        print("\n[AUTONOMOUS PLANNER]")
        print(f"planner status: {planner_status}")
        print(f"planner GO/NO-GO: {planner_go_no_go}")
        print(f"planner last decision: {planner_decision_line}")
        print(f"planner decision summary: {planner_decision_summary or '-'}")
        print(f"autonomous mode active: {'yes' if autonomous_mode_active else 'no'}")
        print(f"human action required: {'yes' if human_action_required else 'no'}")
        print(f"next planned task: {next_planned_task or '-'}")
        print(f"why next task was selected: {planner_decision_summary or '-'}")
        print(f"task will execute automatically: {'yes' if will_execute_automatically else 'no'}")
        if human_action_text:
            print(f"human action note: {first_content_line(human_action_text)}")

        print("\n[SAFETY & GATES]")
        print(f"continuous monitor status: {continuous_monitor_status()}")
        print(f"V2 build gate status: {v2_build_gate_status()}")
        print(f"live mutation gate status: {live_mutation_gate_status()}")
        raw_git = cmd_out(["git", "-C", str(WORKSPACE), "status", "--short"])
        substantive_dirty = substantive_git_status_lines(raw_git)
        print(f"git cleanliness: {'clean' if not substantive_dirty else 'dirty'}")
        if substantive_dirty:
            print("dirty git warning: substantive tracked/unignored changes present")
        elif raw_git.strip():
            print("dirty git warning: only ignored/runtime supervisor artifacts present")
        else:
            print("dirty git warning: none")
        print(f"last event age seconds: {last_event_age}")
        print(f"daemon heartbeat age seconds: {int(hb_age) if hb_age is not None else '-'}")

        evidence_status = read_evidence_reconciliation_status()
        if evidence_status:
            found = evidence_status.get("found_markers", {})
            superseded = evidence_status.get("superseded_tasks", {})
            print("\n[EVIDENCE RECONCILIATION]")
            print(f"generated_at: {evidence_status.get('generated_at')}")
            print(f"markers_found: {len(found)}")
            print(f"superseded_tasks: {len(superseded)}")
            for task_id, marker in list(superseded.items())[:10]:
                print(f"  {task_id} => {marker}")

        print("\n[LAST 10 EVENTS]")
        for ln in last_events(10):
            print(ln)

        print("\n(Press Ctrl+C to exit dashboard)")
        time.sleep(refresh_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Supervisor Dashboard (reliability-hardened)")
    parser.add_argument("--refresh-seconds", type=int, default=10)
    args = parser.parse_args()
    print_dashboard(max(1, args.refresh_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
