#!/usr/bin/env python3
import argparse
import datetime as dt
import glob
import json
import os
import pathlib
import shlex
import subprocess
import sys
import urllib.request
from typing import Any, Dict, List, Optional

BASE_DIR = pathlib.Path("claude_worklog/agent_supervisor")
TASKS_DIR = BASE_DIR / "tasks"
RUNS_DIR = BASE_DIR / "runs"
STATUS_DIR = BASE_DIR / "status"
LOGS_DIR = BASE_DIR / "logs"
EVENTS_FILE = BASE_DIR / "events.jsonl"
CURRENT_STATUS_FILE = STATUS_DIR / "current_status.json"

WORKSPACE_ROOT = pathlib.Path(os.path.expanduser("~/Desktop/AI BOT REBUILD")).resolve()
FORBIDDEN_ROOT = pathlib.Path("/home/wali/Desktop/AI BOT").resolve()

SUPPORTED_AGENTS = {"claude", "codex", "ollama", "system_check"}
ALLOWED_AUTORUN = {"L0", "L1", "L2"}

BANNED_PATTERNS = [
    "redis-cli",
    "xadd",
    "xdel",
    "del ",
    "flushdb",
    "flushall",
    "restart",
    "systemctl restart",
    "pkill",
    "kill ",
    "place order",
    "cancel order",
    "set leverage",
    "set margin",
    "build v2",
    "pip install",
    "npm install",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def ensure_dirs() -> None:
    for p in [BASE_DIR, TASKS_DIR, RUNS_DIR, STATUS_DIR, LOGS_DIR]:
        p.mkdir(parents=True, exist_ok=True)


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def append_event(event: Dict[str, Any]) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def in_workspace(path: pathlib.Path) -> bool:
    try:
        rp = path.resolve()
        return rp == WORKSPACE_ROOT or WORKSPACE_ROOT in rp.parents
    except Exception:
        return False


def task_approved(task: Dict[str, Any]) -> bool:
    risk = str(task.get("risk_level", "L0")).upper()
    if risk in ALLOWED_AUTORUN:
        if risk == "L2":
            return True
        return True
    approval_file = task.get("approval_file")
    if not approval_file:
        return False
    ap = pathlib.Path(approval_file)
    if not ap.is_absolute():
        ap = WORKSPACE_ROOT / ap
    return ap.exists()


def validate_task(task: Dict[str, Any]) -> Optional[str]:
    agent = task.get("agent")
    if agent not in SUPPORTED_AGENTS:
        return f"unsupported agent: {agent}"

    task_cwd = pathlib.Path(task.get("cwd", str(WORKSPACE_ROOT))).expanduser()
    if not task_cwd.is_absolute():
        task_cwd = WORKSPACE_ROOT / task_cwd
    if not in_workspace(task_cwd):
        return "task cwd outside AI BOT REBUILD"

    prompt = str(task.get("prompt", "")).lower()
    command = str(task.get("command", "")).lower()
    combined = f"{prompt}\n{command}"

    if str(FORBIDDEN_ROOT) in combined:
        return "task references forbidden root /home/wali/Desktop/AI BOT"

    for banned in BANNED_PATTERNS:
        if banned in combined:
            return f"blocked by safety pattern: {banned}"

    return None


def run_cmd(cmd: List[str], cwd: pathlib.Path, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> int:
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.run(cmd, cwd=str(cwd), stdout=out, stderr=err, text=True)
        return proc.returncode


def file_contains(path: pathlib.Path, needle: str) -> bool:
    if not path.exists():
        return False
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
        return needle in txt
    except Exception:
        return False


def codex_ready() -> bool:
    ready_file = BASE_DIR / "CODEX_LOCAL_AGENT_READY.md"
    return file_contains(ready_file, "CODEX_LOCAL_AGENT_READY")


def claude_ready() -> bool:
    ready_file = BASE_DIR / "CLAUDE_LOCAL_AGENT_READY.md"
    return file_contains(ready_file, "CLAUDE_LOCAL_AGENT_READY")


def ollama_has_model() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        models = data.get("models", [])
        return isinstance(models, list) and len(models) > 0
    except Exception:
        return False


def run_task(task_path: pathlib.Path) -> Dict[str, Any]:
    task = load_json(task_path)
    task_id = str(task.get("task_id", task_path.stem))
    agent = str(task.get("agent", ""))
    risk = str(task.get("risk_level", "L0")).upper()
    start = now_iso()

    run_dir = RUNS_DIR / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    summary_path = run_dir / "summary.json"

    result: Dict[str, Any] = {
        "task_id": task_id,
        "agent": agent,
        "risk_level": risk,
        "start_time": start,
        "end_time": None,
        "status": "blocked",
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "summary": "",
        "next_recommended_action": "",
    }

    validation_error = validate_task(task)
    if validation_error:
        result["status"] = "blocked"
        result["summary"] = validation_error
        result["next_recommended_action"] = "fix task definition"
    elif not task_approved(task):
        result["status"] = "blocked"
        result["summary"] = f"approval required for risk level {risk}"
        result["next_recommended_action"] = "add approval file and rerun"
    else:
        cwd = pathlib.Path(task.get("cwd", str(WORKSPACE_ROOT))).expanduser()
        if not cwd.is_absolute():
            cwd = WORKSPACE_ROOT / cwd

        precheck_file = task.get("precheck_file")
        precheck_contains = task.get("precheck_contains")
        if precheck_file and precheck_contains:
            pf = pathlib.Path(precheck_file)
            if not pf.is_absolute():
                pf = WORKSPACE_ROOT / pf
            if file_contains(pf, str(precheck_contains)):
                stdout_path.write_text("precheck satisfied\n", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                result["status"] = "completed"
                result["summary"] = "precheck satisfied; existing artifact verified"
                result["next_recommended_action"] = "proceed to next task"
                result["end_time"] = now_iso()
                write_json(summary_path, result)
                return result

        rc = 1
        if agent == "claude":
            if not claude_ready():
                result["status"] = "blocked"
                result["summary"] = "claude not ready"
                result["next_recommended_action"] = "complete claude auth test"
            else:
                prompt = str(task.get("prompt", ""))
                rc = run_cmd(["claude", "--print", prompt, "--output-format", "text"], cwd, stdout_path, stderr_path)
                result["status"] = "completed" if rc == 0 else "failed"
        elif agent == "codex":
            if not codex_ready():
                result["status"] = "blocked"
                result["summary"] = "codex not ready"
                result["next_recommended_action"] = "complete codex auth test"
            else:
                prompt = str(task.get("prompt", ""))
                rc = run_cmd(["codex", "exec", prompt], cwd, stdout_path, stderr_path)
                result["status"] = "completed" if rc == 0 else "failed"
        elif agent == "ollama":
            if not ollama_has_model():
                stdout_path.write_text("ollama running but no model present\n", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                result["status"] = "skipped"
                result["summary"] = "ollama model missing"
                result["next_recommended_action"] = "pull a small model explicitly if needed"
            else:
                prompt = str(task.get("prompt", ""))
                model = str(task.get("model", "llama3"))
                rc = run_cmd(["ollama", "run", model, prompt], cwd, stdout_path, stderr_path)
                result["status"] = "completed" if rc == 0 else "failed"
        elif agent == "system_check":
            cmd = task.get("command")
            if not cmd:
                stdout_path.write_text("", encoding="utf-8")
                stderr_path.write_text("missing command\n", encoding="utf-8")
                result["status"] = "failed"
            else:
                rc = run_cmd(["bash", "-lc", str(cmd)], cwd, stdout_path, stderr_path)
                result["status"] = "completed" if rc == 0 else "failed"

        if not result["summary"]:
            result["summary"] = f"agent run status: {result['status']}"
        if not result["next_recommended_action"]:
            result["next_recommended_action"] = task.get("next_recommended_action", "inspect run output")

    result["end_time"] = now_iso()

    task["status"] = result["status"]
    task["last_run"] = {
        "start": result["start_time"],
        "end": result["end_time"],
        "status": result["status"],
    }
    write_json(task_path, task)
    write_json(summary_path, result)
    write_json(CURRENT_STATUS_FILE, result)
    append_event(result)
    return result


def next_task_file() -> Optional[pathlib.Path]:
    files = sorted(pathlib.Path(p) for p in glob.glob(str(TASKS_DIR / "*.json")))
    for f in files:
        try:
            task = load_json(f)
        except Exception:
            continue
        status = str(task.get("status", "pending")).lower()
        if status in {"pending", "queued", "retry"}:
            return f
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Supervisor")
    parser.add_argument("--task-id", help="Run a specific task_id from tasks directory")
    args = parser.parse_args()

    ensure_dirs()

    task_file: Optional[pathlib.Path] = None
    if args.task_id:
        candidate = TASKS_DIR / f"{args.task_id}.json"
        if candidate.exists():
            task_file = candidate
        else:
            for p in TASKS_DIR.glob("*.json"):
                try:
                    t = load_json(p)
                    if str(t.get("task_id")) == args.task_id:
                        task_file = p
                        break
                except Exception:
                    continue
    else:
        task_file = next_task_file()

    if not task_file:
        status = {
            "task_id": None,
            "agent": None,
            "start_time": now_iso(),
            "end_time": now_iso(),
            "status": "idle",
            "stdout_path": None,
            "stderr_path": None,
            "summary": "no pending task",
            "next_recommended_action": "add pending task json",
        }
        write_json(CURRENT_STATUS_FILE, status)
        append_event(status)
        print("No pending task.")
        return 0

    result = run_task(task_file)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {"completed", "skipped"} else 1


if __name__ == "__main__":
    sys.exit(main())
