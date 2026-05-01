#!/usr/bin/env python3
import argparse
import datetime as dt
import glob
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None

BASE_DIR = pathlib.Path("claude_worklog/agent_supervisor")
TASKS_DIR = BASE_DIR / "tasks"
RUNS_DIR = BASE_DIR / "runs"
STATUS_DIR = BASE_DIR / "status"
LOGS_DIR = BASE_DIR / "logs"
EVENTS_FILE = BASE_DIR / "events.jsonl"
CURRENT_STATUS_FILE = STATUS_DIR / "current_status.json"
QUEUE_STATUS_FILE = STATUS_DIR / "queue_status.json"
AGENT_HEALTH_FILE = STATUS_DIR / "agent_health.json"

WORKSPACE_ROOT = pathlib.Path(os.path.expanduser("~/Desktop/AI BOT REBUILD")).resolve()
FORBIDDEN_ROOT = pathlib.Path("/home/wali/Desktop/AI BOT").resolve()

SUPPORTED_AGENTS = {"claude", "codex", "ollama", "system_check"}
ALLOWED_AUTORUN = {"L0", "L1", "L2"}

STATUS_VALUES = {
    "pending",
    "running",
    "completed",
    "failed",
    "blocked_quota",
    "blocked_auth",
    "blocked_approval",
    "blocked_dependency",
    "retry_scheduled",
    "skipped",
    "cancelled",
}

CREDENTIAL_PATTERN = re.compile(
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY-----|"
    r"xox[baprs]-|ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}",
    re.IGNORECASE,
)

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
            lines_with_banned = [ln.strip() for ln in combined.splitlines() if banned in ln]
            allowed_negation = {"do not", "don't", "dont", "never", "no "}
            if any(not any(tok in ln for tok in allowed_negation) for ln in lines_with_banned):
                return f"blocked by safety pattern: {banned}"

    return None


def run_cmd(cmd: List[str], cwd: pathlib.Path, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> int:
    return run_cmd_with_pid(cmd, cwd, stdout_path, stderr_path)[0]


def run_cmd_with_pid(
    cmd: List[str],
    cwd: pathlib.Path,
    stdout_path: pathlib.Path,
    stderr_path: pathlib.Path,
    timeout_seconds: Optional[int] = None,
    on_start: Optional[Callable[[int], None]] = None,
) -> Tuple[int, Optional[int]]:
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=out,
            stderr=err,
            text=True,
            preexec_fn=os.setsid,
        )
        if on_start is not None:
            try:
                on_start(proc.pid)
            except Exception:
                pass
        try:
            rc = proc.wait(timeout=timeout_seconds)
            return rc, proc.pid
        except subprocess.TimeoutExpired:
            err.write(f"\n[agent_supervisor] subprocess timeout after {timeout_seconds}s; terminating process tree\n")
            err.flush()
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                rc = proc.wait(timeout=10)
                return rc if rc != 0 else 124, proc.pid
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                return 124, proc.pid


def file_contains(path: pathlib.Path, needle: str) -> bool:
    if not path.exists():
        return False
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
        return needle in txt
    except Exception:
        return False


def read_text(path: pathlib.Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def normalize_relpath(path_str: str) -> str:
    return path_str.replace("\\", "/").strip()


def is_relpath_allowed(rel_path: str, allowed_output_prefixes: List[str]) -> bool:
    normalized = normalize_relpath(rel_path)
    for prefix in allowed_output_prefixes:
        pfx = normalize_relpath(prefix)
        if normalized.startswith(pfx):
            return True
    return False


def extract_emit_file_blocks(text: str) -> List[Dict[str, str]]:
    """
    Extract emit-file blocks from agent output.

    Supports both:
    A) Strict blocks:
       BEGIN_FILE: path
       ...content...
       END_FILE

    B) Fallback blocks:
       BEGIN_FILE: path
       ...content until next BEGIN_FILE or EOF
    """
    begin_pattern = re.compile(r"(?m)^BEGIN_FILE:\s*(.+?)\s*$")
    markers = list(begin_pattern.finditer(text))
    blocks: List[Dict[str, str]] = []

    for idx, marker in enumerate(markers):
        rel_path = normalize_relpath(marker.group(1))
        start = marker.end()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)

        content = text[start:end]
        if content.startswith("\n"):
            content = content[1:]

        # Strip optional strict terminator when present.
        content = re.sub(r"\n?END_FILE\s*$", "", content.rstrip(), flags=re.MULTILINE)

        blocks.append({"path": rel_path, "content": content})

    return blocks


def materialize_emit_files(
    stdout_path: pathlib.Path,
    allowed_output_prefixes: List[str],
) -> Dict[str, Any]:
    result = {
        "materialized_files": [],
        "errors": [],
        "blocks_found": 0,
    }

    if not stdout_path.exists():
        result["errors"].append("stdout file missing for emit-file parse")
        return result

    text = stdout_path.read_text(encoding="utf-8", errors="ignore")
    blocks = extract_emit_file_blocks(text)
    result["blocks_found"] = len(blocks)

    for block in blocks:
        rel_path = normalize_relpath(block.get("path", ""))
        content = str(block.get("content", ""))

        if not rel_path:
            result["errors"].append("empty emit-file path")
            continue

        p = pathlib.Path(rel_path)
        if p.is_absolute():
            result["errors"].append(f"refused absolute emit-file path: {rel_path}")
            continue

        if ".." in p.parts:
            result["errors"].append(f"refused path traversal emit-file path: {rel_path}")
            continue

        if not is_relpath_allowed(rel_path, allowed_output_prefixes):
            result["errors"].append(f"emit-file path not allowed by prefixes: {rel_path}")
            continue

        target = (WORKSPACE_ROOT / p).resolve()
        if not in_workspace(target):
            result["errors"].append(f"refused emit-file outside workspace: {rel_path}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        result["materialized_files"].append(rel_path)

    return result


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


def ollama_models() -> List[str]:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        models = data.get("models", [])
        if not isinstance(models, list):
            return []
        return [m.get("name", "") for m in models if isinstance(m, dict)]
    except Exception:
        return []


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


def parse_claude_reset_to_utc(raw: str) -> Optional[str]:
    match = re.search(r"resets\s+([0-9]{1,2}:[0-9]{2}\s*[ap]m)\s*\(([^)]+)\)", raw, re.IGNORECASE)
    if not match or ZoneInfo is None:
        return None
    try:
        time_str = match.group(1).lower().replace(" ", "")
        tz_name = match.group(2).strip()
        hh, mm = time_str[:-2].split(":")
        ap = time_str[-2:]
        hour = int(hh) % 12
        if ap == "pm":
            hour += 12
        minute = int(mm)

        tz = ZoneInfo(tz_name)
        now_local = dt.datetime.now(tz)
        candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now_local:
            candidate += dt.timedelta(days=1)
        return candidate.astimezone(dt.timezone.utc).isoformat()
    except Exception:
        return None


def command_quick(cmd: List[str], timeout: int = 30) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception as ex:
        return 1, "", str(ex)


def classify_agent_block(agent: str, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> Tuple[Optional[str], Optional[str]]:
    raw = (read_text(stdout_path) + "\n" + read_text(stderr_path)).lower()
    if agent == "claude":
        if any(k in raw for k in ["usage limit", "hit your limit", "resets", "quota"]):
            return "blocked_quota", parse_claude_reset_to_utc(read_text(stdout_path) + "\n" + read_text(stderr_path))
        if any(k in raw for k in ["unauthorized", "not authenticated", "auth", "forbidden", "login"]):
            return "blocked_auth", None
    if agent == "codex":
        if any(k in raw for k in ["rate limit", "quota", "usage limit", "too many requests"]):
            return "blocked_quota", None
        if any(k in raw for k in ["unauthorized", "not authenticated", "auth", "forbidden", "login"]):
            return "blocked_auth", None
    return None, None


def run_claude_readiness_check() -> bool:
    rc, out, err = command_quick(["claude", "--print", "Print CLAUDE_READY_FOR_SMALL_TASK", "--output-format", "text"], timeout=40)
    return rc == 0 and "CLAUDE_READY_FOR_SMALL_TASK" in (out + "\n" + err)


def get_task_file_by_id(task_id: str) -> Optional[pathlib.Path]:
    direct = TASKS_DIR / f"{task_id}.json"
    if direct.exists():
        return direct
    for p in TASKS_DIR.glob("*.json"):
        try:
            t = load_json(p)
            if str(t.get("task_id")) == task_id:
                return p
        except Exception:
            continue
    return None


def list_tasks() -> List[Tuple[pathlib.Path, Dict[str, Any]]]:
    items: List[Tuple[pathlib.Path, Dict[str, Any]]] = []
    for p in sorted(pathlib.Path(x) for x in glob.glob(str(TASKS_DIR / "*.json"))):
        try:
            items.append((p, load_json(p)))
        except Exception:
            continue
    return items


def dependency_blockers(task: Dict[str, Any], status_map: Dict[str, str]) -> List[str]:
    deps = [str(x) for x in task.get("depends_on", []) if str(x).strip()]
    return [d for d in deps if status_map.get(d) != "completed"]


def check_required_outputs(task: Dict[str, Any]) -> List[str]:
    required = [str(x) for x in task.get("required_output_files", []) if str(x).strip()]
    missing: List[str] = []
    for req in required:
        rp = pathlib.Path(req)
        if rp.is_absolute():
            missing.append(req)
            continue
        full = (WORKSPACE_ROOT / rp).resolve()
        if not full.exists():
            missing.append(req)
    return missing


def default_task_timeout_seconds(task: Dict[str, Any]) -> int:
    risk = str(task.get("risk_level", "L0")).upper()
    if risk in {"L0", "L1", "L2"}:
        return 1800
    approval_file = str(task.get("approval_file", "")).strip()
    preapproved = bool(task.get("preapproved", False))
    if preapproved or approval_file:
        return 1800
    return 900


def task_timeout_seconds(task: Dict[str, Any]) -> int:
    try:
        val = int(task.get("task_timeout_seconds", 0))
        if val > 0:
            return val
    except Exception:
        pass
    return default_task_timeout_seconds(task)


def process_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def has_active_process_for_task(task_id: str) -> bool:
    if not task_id:
        return False
    try:
        proc = subprocess.run(
            ["pgrep", "-af", task_id],
            cwd=str(WORKSPACE_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            return False
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        for ln in lines:
            if "pgrep -af" in ln:
                continue
            return True
        return False
    except Exception:
        return False


def detect_quota_block(agent: str, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> Tuple[bool, Optional[str]]:
    raw = (read_text(stdout_path) + "\n" + read_text(stderr_path)).lower()
    if agent == "claude":
        if any(k in raw for k in ["usage limit", "hit your limit", "resets", "quota", "rate limit"]):
            return True, parse_claude_reset_to_utc(read_text(stdout_path) + "\n" + read_text(stderr_path))
    if agent == "codex":
        if any(k in raw for k in ["rate limit", "quota", "usage limit", "too many requests"]):
            return True, None
    return False, None


def task_last_activity_ts(summary_path: pathlib.Path, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> Optional[float]:
    ts: List[float] = []
    for p in [summary_path, stdout_path, stderr_path]:
        if p.exists():
            try:
                ts.append(p.stat().st_mtime)
            except Exception:
                continue
    if not ts:
        return None
    return max(ts)


def stale_running_now(task: Dict[str, Any], task_id: str) -> bool:
    if str(task.get("status", "")) != "running":
        return False
    run_dir = RUNS_DIR / task_id
    summary_path = run_dir / "summary.json"
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"

    active = process_alive(task.get("run_pid")) or has_active_process_for_task(task_id)
    if active:
        return False
    if not check_required_outputs(task):
        return False

    timeout_s = task_timeout_seconds(task)
    last_ts = task_last_activity_ts(summary_path, stdout_path, stderr_path)
    if last_ts is None:
        return True
    return (time.time() - last_ts) > float(timeout_s)


def reconcile_stale_running_tasks() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    reconciled = 0

    for task_path, task in list_tasks():
        if str(task.get("status", "pending")) != "running":
            continue

        task_id = str(task.get("task_id", task_path.stem))
        agent = str(task.get("agent", ""))
        risk = str(task.get("risk_level", "L0")).upper()

        run_dir = RUNS_DIR / task_id
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"
        summary_path = run_dir / "summary.json"

        required_missing = check_required_outputs(task)
        active = process_alive(task.get("run_pid")) or has_active_process_for_task(task_id)
        timeout_s = task_timeout_seconds(task)
        last_ts = task_last_activity_ts(summary_path, stdout_path, stderr_path)
        idle_seconds = (time.time() - last_ts) if last_ts is not None else float(timeout_s) + 1.0

        quota_blocked, reset_iso = detect_quota_block(agent, stdout_path, stderr_path)
        status: Optional[str] = None
        summary = ""
        reason = ""
        materialized: List[str] = []

        if not required_missing and not active:
            status = "completed"
            summary = "normalized stale-running task: required output files exist"
            reason = "required_outputs_present_no_active_process"
            materialized = [str(x) for x in task.get("required_output_files", []) if str(x).strip()]
        elif quota_blocked:
            status = "blocked_quota"
            summary = f"{agent} blocked_quota detected during stale-running reconciliation"
            reason = "quota_detected"
            resume = parse_iso_utc(reset_iso)
            if resume is None:
                resume = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)
            task["resume_after_utc"] = resume.isoformat()
        elif (not active) and idle_seconds > float(timeout_s):
            max_attempts = int(task.get("max_attempts", 3))
            retry_count = int(task.get("retry_count", 0))
            if retry_count < max_attempts:
                task["retry_count"] = retry_count + 1
                task["resume_after_utc"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat()
                status = "retry_scheduled"
                summary = f"stale-running timeout recovered; retry {retry_count + 1}/{max_attempts} scheduled"
                reason = "timeout_retry_scheduled"
            else:
                status = "failed"
                summary = "stale-running timeout recovered as failed: no active process and no output growth"
                reason = "timeout_failed"

        if not status:
            continue

        start_time = None
        if isinstance(task.get("last_run"), dict):
            start_time = task.get("last_run", {}).get("start")

        end_time = now.isoformat()
        task["status"] = status
        task["run_pid"] = None
        task["last_run"] = {
            "start": start_time,
            "end": end_time,
            "status": status,
        }
        task["last_summary"] = summary
        write_json(task_path, task)

        run_summary = {
            "task_id": task_id,
            "agent": agent,
            "risk_level": risk,
            "start_time": start_time,
            "end_time": end_time,
            "status": status,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "summary": summary,
            "next_recommended_action": "continue queue if completed; retry later if blocked_quota/retry_scheduled; inspect output if failed",
            "materialized_files": materialized,
            "run_pid": None,
        }
        write_json(summary_path, run_summary)
        write_json(CURRENT_STATUS_FILE, run_summary)
        append_event({
            "event": "stale_running_reconciled",
            **run_summary,
            "reason": reason,
            "timeout_seconds": timeout_s,
            "idle_seconds": int(idle_seconds),
            "active_process": active,
        })
        set_next_tasks(task, success=status == "completed")
        reconciled += 1

    return reconciled


def task_approved_v2(task: Dict[str, Any]) -> Tuple[bool, str]:
    risk = str(task.get("risk_level", "L0")).upper()
    approval_file = str(task.get("approval_file", "")).strip()
    preapproved = bool(task.get("preapproved", False))

    if risk in {"L0", "L1"}:
        return True, ""
    if risk == "L2":
        cwd = pathlib.Path(task.get("cwd", str(WORKSPACE_ROOT))).expanduser()
        if not cwd.is_absolute():
            cwd = WORKSPACE_ROOT / cwd
        return in_workspace(cwd), "L2 allowed only inside AI BOT REBUILD"
    if risk == "L3":
        if preapproved:
            return True, ""
        if not approval_file:
            return False, "L3 requires approval_file or preapproved=true"
        ap = pathlib.Path(approval_file)
        if not ap.is_absolute():
            ap = WORKSPACE_ROOT / ap
        return ap.exists(), "L3 approval_file missing"
    if risk == "L4":
        if not approval_file:
            return False, "L4 requires approval_file"
        ap = pathlib.Path(approval_file)
        if not ap.is_absolute():
            ap = WORKSPACE_ROOT / ap
        return ap.exists(), "L4 approval_file missing"
    if risk == "L5":
        return False, "L5 never auto-executes; recommendation packet only"
    return False, f"unsupported risk level {risk}"


def task_priority(task: Dict[str, Any]) -> int:
    try:
        return int(task.get("priority", 0))
    except Exception:
        return 0


def should_defer_resume(task: Dict[str, Any]) -> bool:
    st = str(task.get("status", ""))
    if st not in {"blocked_quota", "retry_scheduled"}:
        return False
    resume = parse_iso_utc(task.get("resume_after_utc"))
    if resume is None:
        return False
    return dt.datetime.now(dt.timezone.utc) < resume


def safe_secret_scan(paths: List[pathlib.Path]) -> Tuple[bool, List[str]]:
    hits: List[str] = []
    for p in paths:
        if not p.exists() or not p.is_file():
            continue
        txt = read_text(p)
        for idx, line in enumerate(txt.splitlines(), start=1):
            if CREDENTIAL_PATTERN.search(line):
                hits.append(f"{p}:{idx}:{line[:180]}")
    return (len(hits) == 0), hits


def auto_commit_task_outputs(task_path: pathlib.Path, task: Dict[str, Any], result: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
    if not bool(task.get("auto_commit", False)):
        return False, "auto_commit disabled", None

    risk = str(task.get("risk_level", "L0")).upper()
    if risk not in {"L0", "L1", "L2"}:
        return False, f"auto_commit blocked for risk {risk}", None

    materialized = [str(x) for x in result.get("materialized_files", []) if str(x).strip()]
    stage_rel = [str(task_path.relative_to(WORKSPACE_ROOT))]
    candidates_rel = list(dict.fromkeys(materialized + stage_rel))

    candidates: List[pathlib.Path] = []
    for rel in candidates_rel:
        if "/runs/" in rel or "/logs/" in rel or "/packets/" in rel:
            continue
        p = (WORKSPACE_ROOT / rel).resolve()
        if not in_workspace(p):
            continue
        candidates.append(p)

    if not candidates:
        return False, "no commit-eligible files", None

    ok, hits = safe_secret_scan(candidates)
    if not ok:
        return False, "secret scan blocked auto-commit: " + " | ".join(hits[:5]), None

    for p in candidates:
        if p.exists():
            subprocess.run(["git", "add", str(p)], cwd=str(WORKSPACE_ROOT), check=False)

    msg = str(task.get("commit_message", "")).strip() or f"Auto-commit task {task.get('task_id')} outputs"
    commit = subprocess.run(["git", "commit", "-m", msg], cwd=str(WORKSPACE_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = (commit.stdout or "") + (commit.stderr or "")
    if commit.returncode != 0:
        if "nothing to commit" in out.lower():
            return False, "nothing to commit", None
        return False, out.strip(), None

    last = subprocess.run(["git", "log", "--oneline", "-1"], cwd=str(WORKSPACE_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    line = (last.stdout or "").strip()
    commit_hash = line.split()[0] if line else None
    return True, "auto-commit successful", commit_hash


def derive_gate(tasks: List[Tuple[pathlib.Path, Dict[str, Any]]]) -> str:
    status_map = {str(t.get("task_id", "")): str(t.get("status", "pending")) for _, t in tasks}

    if status_map.get("010_actual_codex_architecture_rerun_after_remediation") == "running":
        return "CODEX_RERUN_RUNNING"
    if any(v == "blocked_quota" for v in status_map.values()):
        return "WAITING_FOR_CLAUDE_QUOTA"
    if status_map.get("010_actual_codex_architecture_rerun_after_remediation") == "completed":
        gate_file = WORKSPACE_ROOT / "claude_worklog/v2_architecture_codex_review/16_ACTUAL_CODEX_RERUN_GO_NO_GO.md"
        txt = read_text(gate_file)
        if "PASS" in txt:
            return "READY_FOR_SCAFFOLD_PLANNING"
        return "BLOCKED_BY_CODEX"
    if all(status_map.get(k) == "completed" for k in [
        "012c_feature_explainability_completeness",
        "012d_trainer_liveness_validation_evidence",
        "012e_milestone_go_no_go_integration",
    ]):
        return "READY_FOR_CODEX_RERUN"
    if any(status_map.get(k) == "running" for k in [
        "012c_feature_explainability_completeness",
        "012d_trainer_liveness_validation_evidence",
        "012e_milestone_go_no_go_integration",
    ]):
        return "RUNNING_ARCHITECTURE_REMEDIATION"
    return "ARCHITECTURE_REMEDIATION_PARTIAL"


def write_health_and_queue(current: Dict[str, Any]) -> None:
    write_json(CURRENT_STATUS_FILE, current)

    tasks = list_tasks()
    status_map = {str(t.get("task_id", "")): str(t.get("status", "pending")) for _, t in tasks}
    counts = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "blocked": 0,
        "retry_scheduled": 0,
        "skipped": 0,
        "cancelled": 0,
    }
    next_pending = None
    running = None
    blocked_quota = None
    runnable_candidates: List[Tuple[int, str]] = []
    stale_running_count = 0

    for _, t in tasks:
        tid = str(t.get("task_id", ""))
        st = str(t.get("status", "pending"))
        if st == "pending":
            counts["pending"] += 1
            if next_pending is None:
                next_pending = tid
        elif st == "running":
            counts["running"] += 1
            if running is None:
                running = tid
            if stale_running_now(t, tid):
                stale_running_count += 1
        elif st == "completed":
            counts["completed"] += 1
        elif st in {"failed", "blocked_auth", "blocked_approval", "blocked_dependency", "blocked_quota"}:
            if st == "failed":
                counts["failed"] += 1
            else:
                counts["blocked"] += 1
            if st == "blocked_quota" and blocked_quota is None:
                blocked_quota = {
                    "task_id": tid,
                    "agent": t.get("agent"),
                    "resume_after_utc": t.get("resume_after_utc"),
                }
        elif st == "retry_scheduled":
            counts["retry_scheduled"] += 1
        elif st == "skipped":
            counts["skipped"] += 1
        elif st == "cancelled":
            counts["cancelled"] += 1

        if st in {"completed", "running", "cancelled", "failed", "blocked_auth", "blocked_approval"}:
            continue
        if should_defer_resume(t):
            continue
        blockers = dependency_blockers(t, status_map)
        if blockers:
            continue
        runnable_candidates.append((-task_priority(t), tid))

    if runnable_candidates:
        runnable_candidates.sort()
        next_pending = runnable_candidates[0][1]

    queue_payload = {
        "generated_at": now_iso(),
        "next_pending_task": next_pending,
        "current_running_task": running,
        "blocked_quota": blocked_quota,
        "stale_running_count": stale_running_count,
        "counts": counts,
        "gate": derive_gate(tasks),
    }
    write_json(QUEUE_STATUS_FILE, queue_payload)

    ollama_list = ollama_models()
    health_payload = {
        "generated_at": now_iso(),
        "terminal_operator": "VS Code/Copilot",
        "active_agents": ["Claude", "Codex", "Ollama"],
        "claude": {"ready_marker": claude_ready()},
        "codex": {"ready_marker": codex_ready()},
        "ollama": {"model_count": len(ollama_list), "models": ollama_list[:8]},
        "last_auto_commit_hash": current.get("auto_commit", {}).get("commit_hash"),
    }
    write_json(AGENT_HEALTH_FILE, health_payload)


def set_next_tasks(task: Dict[str, Any], success: bool) -> None:
    key = "next_tasks_on_success" if success else "next_tasks_on_failure"
    next_ids = [str(x) for x in task.get(key, []) if str(x).strip()]
    for ntid in next_ids:
        tf = get_task_file_by_id(ntid)
        if not tf:
            continue
        try:
            t = load_json(tf)
            if str(t.get("status", "")) in {"completed", "running"}:
                continue
            t["status"] = "pending"
            write_json(tf, t)
        except Exception:
            continue


def select_next_task_file() -> Optional[pathlib.Path]:
    tasks = list_tasks()
    status_map = {str(t.get("task_id", "")): str(t.get("status", "pending")) for _, t in tasks}
    candidates: List[Tuple[int, str, pathlib.Path]] = []

    for p, task in tasks:
        status = str(task.get("status", "pending"))
        tid = str(task.get("task_id", p.stem))

        if status == "completed":
            continue
        if status in {"cancelled", "failed", "blocked_auth", "blocked_approval"}:
            continue
        if should_defer_resume(task):
            continue

        blockers = dependency_blockers(task, status_map)
        if blockers:
            if status != "blocked_dependency":
                task["status"] = "blocked_dependency"
                task["last_summary"] = f"waiting on dependencies: {', '.join(blockers)}"
                write_json(p, task)
            continue
        if status == "blocked_dependency":
            task["status"] = "pending"
            write_json(p, task)

        candidates.append((-task_priority(task), tid, p))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


def run_task(task_path: pathlib.Path, dry_run: bool = False) -> Dict[str, Any]:
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
        "status": "failed",
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "summary": "",
        "next_recommended_action": "inspect run output",
        "materialized_files": [],
        "auto_commit": {
            "attempted": False,
            "ok": False,
            "message": "",
            "commit_hash": None,
        },
    }

    validation_error = validate_task(task)
    if validation_error:
        result["status"] = "failed"
        result["summary"] = validation_error
        result["next_recommended_action"] = "fix task definition"
    else:
        approved, reason = task_approved_v2(task)
        if not approved:
            result["status"] = "blocked_approval"
            result["summary"] = reason
            result["next_recommended_action"] = "add approval and rerun"
        else:
            status_map = {str(t.get("task_id", "")): str(t.get("status", "pending")) for _, t in list_tasks()}
            blockers = dependency_blockers(task, status_map)
            if blockers:
                result["status"] = "blocked_dependency"
                result["summary"] = f"waiting on dependencies: {', '.join(blockers)}"
            else:
                existing_missing = check_required_outputs(task)
                if not existing_missing and str(task.get("status", "")) == "completed":
                    result["status"] = "completed"
                    result["summary"] = "required outputs already exist"
                elif dry_run:
                    result["status"] = "pending"
                    result["summary"] = "dry-run: task not executed"
                else:
                    task["status"] = "running"
                    task["last_run"] = {
                        "start": start,
                        "end": None,
                        "status": "running",
                    }
                    task["run_pid"] = None
                    write_json(task_path, task)
                    running_status = {
                        "task_id": task_id,
                        "agent": agent,
                        "risk_level": risk,
                        "start_time": start,
                        "end_time": None,
                        "status": "running",
                        "stdout_path": str(stdout_path),
                        "stderr_path": str(stderr_path),
                        "summary": "task execution in progress",
                        "next_recommended_action": "wait for completion",
                        "materialized_files": [],
                        "run_pid": None,
                    }
                    write_json(summary_path, running_status)
                    write_health_and_queue(running_status)
                    append_event({"event": "task_running", **running_status})

                    cwd = pathlib.Path(task.get("cwd", str(WORKSPACE_ROOT))).expanduser()
                    if not cwd.is_absolute():
                        cwd = WORKSPACE_ROOT / cwd
                    hard_timeout_s = task_timeout_seconds(task)

                    rc = 1
                    run_pid: Optional[int] = None

                    def _mark_run_pid(pid: int) -> None:
                        task["run_pid"] = pid
                        write_json(task_path, task)
                        running_status["run_pid"] = pid
                        write_json(summary_path, running_status)
                        write_health_and_queue(running_status)

                    if agent == "claude":
                        if not claude_ready():
                            result["status"] = "blocked_auth"
                            result["summary"] = "claude not ready"
                        else:
                            prompt = str(task.get("prompt", ""))
                            rc, run_pid = run_cmd_with_pid(["claude", "--print", prompt, "--output-format", "text"], cwd, stdout_path, stderr_path, timeout_seconds=hard_timeout_s, on_start=_mark_run_pid)
                            result["status"] = "completed" if rc == 0 else "failed"
                    elif agent == "codex":
                        if not codex_ready():
                            result["status"] = "blocked_auth"
                            result["summary"] = "codex not ready"
                        else:
                            prompt = str(task.get("prompt", ""))
                            rc, run_pid = run_cmd_with_pid(["codex", "exec", prompt], cwd, stdout_path, stderr_path, timeout_seconds=hard_timeout_s, on_start=_mark_run_pid)
                            result["status"] = "completed" if rc == 0 else "failed"
                    elif agent == "ollama":
                        model = str(task.get("model", "llama3"))
                        if not any(m == model for m in ollama_models()):
                            result["status"] = "blocked_dependency"
                            result["summary"] = f"ollama model missing: {model}"
                        else:
                            prompt = str(task.get("prompt", ""))
                            rc, run_pid = run_cmd_with_pid(["ollama", "run", model, prompt], cwd, stdout_path, stderr_path, timeout_seconds=hard_timeout_s, on_start=_mark_run_pid)
                            result["status"] = "completed" if rc == 0 else "failed"
                    elif agent == "system_check":
                        cmd = task.get("command")
                        if not cmd:
                            stdout_path.write_text("", encoding="utf-8")
                            stderr_path.write_text("missing command\n", encoding="utf-8")
                            result["status"] = "failed"
                        else:
                            rc, run_pid = run_cmd_with_pid(["bash", "-lc", str(cmd)], cwd, stdout_path, stderr_path, timeout_seconds=hard_timeout_s, on_start=_mark_run_pid)
                            result["status"] = "completed" if rc == 0 else "failed"

                    result["run_pid"] = run_pid

                    if result["status"] == "failed":
                        classified_status, reset_iso = classify_agent_block(agent, stdout_path, stderr_path)
                        if classified_status:
                            result["status"] = classified_status
                            result["summary"] = f"{agent} {classified_status} detected"
                            if classified_status == "blocked_quota":
                                resume = parse_iso_utc(reset_iso)
                                if resume is None:
                                    resume = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)
                                task["resume_after_utc"] = resume.isoformat()

                    emit_files = bool(task.get("emit_files", False))
                    if emit_files and agent in {"claude", "codex"} and result["status"] == "completed":
                        allowed_prefixes = [str(x) for x in task.get("allowed_output_prefixes", []) if str(x).strip()]
                        if not allowed_prefixes:
                            result["status"] = "failed"
                            result["summary"] = "emit_files=true but allowed_output_prefixes missing"
                        else:
                            mat = materialize_emit_files(stdout_path, allowed_prefixes)
                            result["materialized_files"] = mat.get("materialized_files", [])
                            errors = mat.get("errors", [])
                            if errors:
                                result["status"] = "failed"
                                result["summary"] = "; ".join(errors)

                            missing_required = check_required_outputs(task)
                            if missing_required:
                                retry_mat = materialize_emit_files(stdout_path, allowed_prefixes)
                                result["materialized_files"] = list(
                                    dict.fromkeys(result["materialized_files"] + retry_mat.get("materialized_files", []))
                                )
                                missing_required = check_required_outputs(task)

                            if missing_required:
                                result["status"] = "failed"
                                prior = result.get("summary", "")
                                extra = f"missing required output files: {', '.join(missing_required)}"
                                result["summary"] = f"{prior}; {extra}".strip("; ")

                    if result["status"] == "blocked_quota" and agent == "claude":
                        resume_at = parse_iso_utc(task.get("resume_after_utc"))
                        if resume_at is not None and dt.datetime.now(dt.timezone.utc) >= resume_at:
                            if run_claude_readiness_check():
                                result["status"] = "retry_scheduled"
                                result["summary"] = "claude ready check passed; retry scheduled"
                                task["resume_after_utc"] = None
                            else:
                                task["resume_after_utc"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).isoformat()

                    max_attempts = int(task.get("max_attempts", 3))
                    retry_count = int(task.get("retry_count", 0))
                    if result["status"] == "failed" and retry_count < max_attempts:
                        task["retry_count"] = retry_count + 1
                        task["resume_after_utc"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat()
                        result["status"] = "retry_scheduled"
                        result["summary"] = (result.get("summary", "failed") + f"; retry {retry_count + 1}/{max_attempts} scheduled")
    if not result["summary"]:
        result["summary"] = f"agent run status: {result['status']}"

    if result["status"] == "completed" and bool(task.get("auto_commit", False)) and not dry_run:
        result["auto_commit"]["attempted"] = True
        ok, msg, commit_hash = auto_commit_task_outputs(task_path, task, result)
        result["auto_commit"]["ok"] = ok
        result["auto_commit"]["message"] = msg
        result["auto_commit"]["commit_hash"] = commit_hash
        if not ok and "secret scan blocked" in msg:
            result["status"] = "failed"
            result["summary"] = msg

    result["end_time"] = now_iso()

    task["status"] = result["status"]
    task["run_pid"] = None
    task.setdefault("retry_count", int(task.get("retry_count", 0)))
    task["last_run"] = {
        "start": result["start_time"],
        "end": result["end_time"],
        "status": result["status"],
    }
    write_json(task_path, task)
    write_json(summary_path, result)
    write_health_and_queue(result)
    append_event(result)
    set_next_tasks(task, success=result["status"] == "completed")
    return result


def normalize_existing_completion() -> None:
    closures = [
        ("012a_database_lineage_constraints", WORKSPACE_ROOT / "claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md"),
        ("012b_api_lineage_enforcement", WORKSPACE_ROOT / "claude_worklog/v2_architecture_remediation/12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md"),
    ]
    for task_id, closure in closures:
        if not closure.exists():
            continue
        tf = get_task_file_by_id(task_id)
        if not tf:
            continue
        task = load_json(tf)
        if str(task.get("status", "")) != "completed":
            task["status"] = "completed"
            write_json(tf, task)


def dry_run_queue() -> Dict[str, Any]:
    payload = {
        "generated_at": now_iso(),
        "next_task_file": str(select_next_task_file()) if select_next_task_file() else None,
        "gate": derive_gate(list_tasks()),
    }
    status = {
        "task_id": None,
        "agent": None,
        "start_time": now_iso(),
        "end_time": now_iso(),
        "status": "pending",
        "summary": "dry-run queue check completed",
        "next_recommended_action": "start daemon if queue is valid",
    }
    write_health_and_queue(status)
    append_event({"event": "dry_run", **payload})
    return payload


def daemon_loop(poll_seconds: int, max_run_hours: Optional[float], stop_after_idle_minutes: Optional[float], dry_run: bool) -> int:
    started = dt.datetime.now(dt.timezone.utc)
    idle_started = started
    reconcile_stale_running_tasks()
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        if max_run_hours is not None and (now - started).total_seconds() >= max_run_hours * 3600:
            status = {
                "task_id": None,
                "agent": None,
                "start_time": now_iso(),
                "end_time": now_iso(),
                "status": "cancelled",
                "summary": "daemon max-run-hours reached",
                "next_recommended_action": "restart daemon if needed",
            }
            write_health_and_queue(status)
            append_event(status)
            return 0

        reconcile_stale_running_tasks()

        task_file = select_next_task_file()
        if not task_file:
            status = {
                "task_id": None,
                "agent": None,
                "start_time": now_iso(),
                "end_time": now_iso(),
                "status": "pending",
                "summary": "no runnable task",
                "next_recommended_action": "wait for dependencies/quota or add pending tasks",
            }
            write_health_and_queue(status)
            append_event(status)
            if stop_after_idle_minutes is not None and (now - idle_started).total_seconds() >= stop_after_idle_minutes * 60:
                return 0
            time.sleep(max(5, poll_seconds))
            continue

        idle_started = now
        result = run_task(task_file, dry_run=dry_run)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        time.sleep(max(2, poll_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Supervisor")
    parser.add_argument("--task-id", help="Run a specific task_id from tasks directory")
    parser.add_argument("--daemon", action="store_true", help="Run autonomous queue manager loop")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--max-run-hours", type=float)
    parser.add_argument("--stop-after-idle-minutes", type=float)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    ensure_dirs()
    normalize_existing_completion()

    if args.dry_run and not args.task_id and not args.daemon:
        payload = dry_run_queue()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.daemon:
        return daemon_loop(
            poll_seconds=max(5, args.poll_seconds),
            max_run_hours=args.max_run_hours,
            stop_after_idle_minutes=args.stop_after_idle_minutes,
            dry_run=args.dry_run,
        )

    task_file: Optional[pathlib.Path] = None
    if args.task_id:
        task_file = get_task_file_by_id(args.task_id)
    else:
        task_file = select_next_task_file()

    if not task_file:
        status = {
            "task_id": None,
            "agent": None,
            "start_time": now_iso(),
            "end_time": now_iso(),
            "status": "pending",
            "stdout_path": None,
            "stderr_path": None,
            "summary": "no runnable task",
            "next_recommended_action": "check dependency/quota/approval statuses",
        }
        write_health_and_queue(status)
        append_event(status)
        print("No runnable task.")
        return 0

    result = run_task(task_file, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {
        "completed",
        "skipped",
        "pending",
        "retry_scheduled",
        "blocked_dependency",
        "blocked_quota",
        "blocked_auth",
        "blocked_approval",
    } else 1


if __name__ == "__main__":
    sys.exit(main())
