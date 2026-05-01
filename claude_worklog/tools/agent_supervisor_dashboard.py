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
HEARTBEAT = BASE / "status/supervisor_heartbeat.json"
LOCK_FILE = BASE / "supervisor.lock"
RUNS = BASE / "runs"
WORKSPACE = pathlib.Path(os.path.expanduser("~/Desktop/AI BOT REBUILD"))

HEARTBEAT_STALE_S = 600


def read_text(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def read_json(path: pathlib.Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def cmd_out(cmd: List[str]) -> str:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip()
    except Exception:
        return ""


def which(name: str) -> Optional[str]:
    out = cmd_out(["bash", "-lc", f"command -v {name} || true"])
    return out.splitlines()[0].strip() if out.strip() else None


def process_lines(pattern: str) -> List[str]:
    out = cmd_out(["bash", "-lc", f"pgrep -af {pattern!r} || true"])
    return [ln for ln in out.splitlines() if ln.strip()]


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
    codex_gate = WORKSPACE / "claude_worklog/v2_architecture_codex_review/11_CODEX_ARCHITECTURE_GO_NO_GO.md"
    if codex_gate.exists():
        return read_text(codex_gate) or "unknown"
    return "unknown"


def live_mutation_gate_status() -> str:
    return "LIVE_MUTATION_BLOCKED_BY_DEFAULT"


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

        hb_age = heartbeat_age_seconds(heartbeat)
        hb_alive = heartbeat_pid_alive(heartbeat)
        hb_stale = (hb_age is not None and hb_age > HEARTBEAT_STALE_S) or (hb_alive is False)

        print("=" * 96)
        print("AI BOT REBUILD - Agent Supervisor Dashboard (reliability-hardened)")
        print(f"Timestamp: {now} | Refresh: {refresh_seconds}s")
        print("=" * 96)
        print("VS Code/Copilot is terminal operator only.")
        print("Active agents: Claude/Codex/Ollama")

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

        print("\n[QUEUE STATUS]")
        print(f"current gate: {gate}")
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
        print(f"latest Claude run summary: {latest_agent_summary('claude')}")
        print(f"latest Codex run summary: {latest_agent_summary('codex')}")
        print(f"latest Ollama run summary: {latest_agent_summary('ollama')}")
        print(f"last auto-commit hash: {last_auto_commit_hash or '-'}")

        print("\n[SAFETY & GATES]")
        print(f"continuous monitor status: {continuous_monitor_status()}")
        print(f"V2 build gate status: {v2_build_gate_status()}")
        print(f"live mutation gate status: {live_mutation_gate_status()}")

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