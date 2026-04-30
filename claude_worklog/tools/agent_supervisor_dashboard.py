#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import pathlib
import subprocess
import time
import urllib.request
from typing import Any, Dict, List, Optional

BASE = pathlib.Path("claude_worklog/agent_supervisor")
EVENTS = BASE / "events.jsonl"
STATUS = BASE / "status/current_status.json"
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


def ollama_status() -> Dict[str, Any]:
    data = {"api": "down", "model_count": 0, "models": []}
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
        models = payload.get("models", []) if isinstance(payload, dict) else []
        data["api"] = "up"
        data["model_count"] = len(models) if isinstance(models, list) else 0
        if isinstance(models, list):
            data["models"] = [m.get("name", "") for m in models[:5] if isinstance(m, dict)]
    except Exception:
        pass
    return data


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

        claude_path = which("claude")
        codex_path = which("codex")
        ollama_path = which("ollama")

        claude_ready = marker_contains(WORKSPACE / "claude_worklog/agent_supervisor/CLAUDE_LOCAL_AGENT_READY.md", "CLAUDE_LOCAL_AGENT_READY")
        codex_ready = marker_contains(WORKSPACE / "claude_worklog/agent_supervisor/CODEX_LOCAL_AGENT_READY.md", "CODEX_LOCAL_AGENT_READY")
        ollama_ready = marker_contains(WORKSPACE / "claude_worklog/agent_supervisor/OLLAMA_LOCAL_AGENT_READY.md", "OLLAMA_LOCAL_AGENT_READY")

        ol = ollama_status()
        current = read_json(WORKSPACE / STATUS)

        claude_ps = process_lines("claude")
        codex_ps = process_lines("codex")
        ollama_ps = process_lines("ollama")
        supervisor_ps = process_lines("agent_supervisor.py")

        print("=" * 96)
        print("AI BOT REBUILD - Agent Supervisor Dashboard")
        print(f"Timestamp: {now} | Refresh: {refresh_seconds}s")
        print("=" * 96)

        print("\n[AGENT INSTALL/AUTH STATUS]")
        print(f"Claude installed: {'yes' if claude_path else 'no'} | path: {claude_path or '-'}")
        print(f"Claude auth ready: {'yes' if claude_ready else 'no'}")
        print(f"Codex installed: {'yes' if codex_path else 'no'} | path: {codex_path or '-'}")
        print(f"Codex auth ready: {'yes' if codex_ready else 'no'}")
        print(f"Ollama installed: {'yes' if ollama_path else 'no'} | path: {ollama_path or '-'}")
        print(f"Ollama API: {ol['api']} | model count: {ol['model_count']} | models: {', '.join(ol['models']) if ol['models'] else '-'}")
        print(f"Ollama ready marker: {'yes' if ollama_ready else 'no'}")

        print("\n[PROCESS STATUS]")
        print(f"claude processes: {len(claude_ps)}")
        print(f"codex processes: {len(codex_ps)}")
        print(f"ollama processes: {len(ollama_ps)}")
        print(f"agent supervisor running: {'yes' if supervisor_ps else 'no'}")

        print("\n[LATEST TASK STATUS]")
        print(f"latest task id: {current.get('task_id', 'N/A')}")
        print(f"latest task agent: {current.get('agent', 'N/A')}")
        print(f"latest task status: {current.get('status', 'N/A')}")
        print(f"latest Claude run summary: {latest_agent_summary('claude')}")
        print(f"latest Codex run summary: {latest_agent_summary('codex')}")
        print(f"latest Ollama run summary: {latest_agent_summary('ollama')}")

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
