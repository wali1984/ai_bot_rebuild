#!/usr/bin/env python3
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
RUNS = BASE / "runs"
WORKSPACE = pathlib.Path(os.path.expanduser("~/Desktop/AI BOT REBUILD"))


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


def marker_contains(path: pathlib.Path, token: str) -> bool:
    return token in read_text(path)


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
    # Architectural default-safe signal.
    return "LIVE_MUTATION_BLOCKED_BY_DEFAULT"


def print_dashboard(refresh_seconds: int) -> None:
    while True:
        os.system("clear")
        now = dt.datetime.now().isoformat()

        current = read_json(WORKSPACE / STATUS)
        queue = read_json(WORKSPACE / QUEUE_STATUS)
        health = read_json(WORKSPACE / AGENT_HEALTH)

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

        print("=" * 96)
        print("AI BOT REBUILD - Agent Supervisor Dashboard")
        print(f"Timestamp: {now} | Refresh: {refresh_seconds}s")
        print("=" * 96)
        print("VS Code/Copilot is terminal operator only.")
        print("Active agents: Claude/Codex/Ollama")

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
            f"retry={counts.get('retry_scheduled', 0)}"
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
    parser = argparse.ArgumentParser(description="Agent Supervisor Dashboard")
    parser.add_argument("--refresh-seconds", type=int, default=10)
    args = parser.parse_args()
    print_dashboard(max(1, args.refresh_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
