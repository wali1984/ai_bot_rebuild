#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE = pathlib.Path("/home/wali/Desktop/AI BOT REBUILD").resolve()
BASE = WORKSPACE / "claude_worklog/agent_supervisor"
STATUS_DIR = BASE / "status"
STATE_TASKS_DIR = BASE / "state/tasks"
PLANNER_DIR = BASE / "planner"
RUNS_DIR = BASE / "runs"
EVENTS_FILE = BASE / "events.jsonl"
WATCHDOG_STATUS_FILE = STATUS_DIR / "phase_017_watchdog.json"

TASK_017 = "017_remediate_v2_scaffold_queue_codex_blockers"
TASK_017_STATE = STATE_TASKS_DIR / f"{TASK_017}.json"
TASK_017_DEF = BASE / "tasks" / f"{TASK_017}.json"
TASK_017_RUN_DIR = RUNS_DIR / TASK_017

AUTON_START = WORKSPACE / "claude_worklog/tools/start_autonomous_agent_supervisor.sh"
AUTON_STOP = WORKSPACE / "claude_worklog/tools/stop_autonomous_agent_supervisor.sh"
SUPERVISOR_BIN = WORKSPACE / "claude_worklog/tools/agent_supervisor.py"

CURRENT_STATUS = STATUS_DIR / "current_status.json"
QUEUE_STATUS = STATUS_DIR / "queue_status.json"
PLANNER_STATUS = STATUS_DIR / "planner_status.json"

CODEX_GO_NO_GO = WORKSPACE / "claude_worklog/v2_scaffold_queue/06_CODEX_QUEUE_GO_NO_GO.md"
PHASE_REPORT_PASS = WORKSPACE / "claude_worklog/approvals/PHASE_017_CODEX_REREVIEW_PASS_HUMAN_APPROVAL_REQUIRED.md"
PHASE_REPORT_FAIL = WORKSPACE / "claude_worklog/approvals/PHASE_017_CODEX_REREVIEW_BLOCKERS.md"

ALLOWED_PREFIXES = [
    "claude_worklog/v2_scaffold_queue/",
    "claude_worklog/agent_supervisor/tasks/",
    "claude_worklog/v2_scaffold_queue_review/",
    "claude_worklog/agent_supervisor/planner/",
    "claude_worklog/approvals/",
]

IMPLEMENTATION_TASKS = [
    "015a_repo_package_skeleton",
    "015b_database_migration_skeleton",
    "015c_api_route_skeleton",
    "015d_enterprise_frontend_shell",
    "015e_test_ci_skeleton",
    "015f_agent_dashboard_integration",
]

MAX_DURATION_SECONDS = 4 * 60 * 60
POLL_SECONDS = 60
PLANNER_TIMEOUT_SECONDS = 12 * 60
TASK_CHILD_TIMEOUT_SECONDS = 45 * 60
NO_EVENT_TIMEOUT_SECONDS = 10 * 60
NO_GROWTH_TIMEOUT_SECONDS = 15 * 60

QUOTA_PATTERNS = ["usage limit", "rate limit", "quota", "too many requests", "resets"]
AUTH_PATTERNS = ["unauthorized", "not authenticated", "forbidden", "auth", "login"]


# -----------------------------
# basic helpers
# -----------------------------
def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def append_event(event: Dict[str, Any]) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", now_iso())
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run(cmd: List[str], timeout: Optional[int] = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(WORKSPACE),
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def process_list() -> List[Dict[str, Any]]:
    cp = run(["ps", "-eo", "pid,ppid,etimes,cmd"])
    out = cp.stdout or ""
    rows: List[Dict[str, Any]] = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("PID "):
            continue
        if not re.search(r"agent_supervisor.py|claude --print|codex exec|ollama run", ln):
            continue
        parts = ln.split(maxsplit=3)
        if len(parts) < 4:
            continue
        rows.append({
            "pid": int(parts[0]),
            "ppid": int(parts[1]),
            "etimes": int(parts[2]),
            "cmd": parts[3],
        })
    return rows


def planner_processes(procs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in procs:
        cmd = p.get("cmd", "")
        if "claude --print" in cmd and "You are Claude planner for AI BOT REBUILD" in cmd:
            out.append(p)
    return out


def daemon_running(procs: List[Dict[str, Any]]) -> bool:
    return any("agent_supervisor.py --autonomous-daemon" in p["cmd"] for p in procs)


def stop_agent_children() -> List[int]:
    """Stop stale agent child processes only (claude/codex/ollama subprocesses)."""
    killed: List[int] = []
    for p in process_list():
        cmd = p.get("cmd", "")
        if "agent_supervisor.py" in cmd:
            continue
        pid = int(p.get("pid", 0) or 0)
        if pid <= 0:
            continue
        try:
            os.kill(pid, 15)
            killed.append(pid)
        except Exception:
            continue
    return killed


def read_first_line(path: pathlib.Path) -> str:
    try:
        for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = ln.strip()
            if s:
                return s
    except Exception:
        pass
    return ""


def latest_event_age_seconds() -> Optional[int]:
    if not EVENTS_FILE.exists():
        return None
    try:
        lines = EVENTS_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not lines:
            return None
        last = json.loads(lines[-1])
        ts = last.get("ts")
        if not ts:
            return None
        parsed = dt.datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        age = int((dt.datetime.now(dt.timezone.utc) - parsed.astimezone(dt.timezone.utc)).total_seconds())
        return max(age, 0)
    except Exception:
        return None


def file_stats(path: pathlib.Path) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False, "size": 0, "mtime": None}
    st = path.stat()
    return {"exists": True, "size": st.st_size, "mtime": int(st.st_mtime)}


def is_implementation_blocked() -> Tuple[bool, Dict[str, str]]:
    statuses: Dict[str, str] = {}
    ok = True
    for tid in IMPLEMENTATION_TASKS:
        p = STATE_TASKS_DIR / f"{tid}.json"
        d = load_json(p, {})
        st = str(d.get("status", ""))
        statuses[tid] = st
        if st != "blocked_approval":
            ok = False
    return ok, statuses


def start_daemon() -> Tuple[bool, str]:
    env = os.environ.copy()
    env["AGENT_SUPERVISOR_PLANNER_TIMEOUT_SECONDS"] = str(PLANNER_TIMEOUT_SECONDS)
    cp = subprocess.run(
        [str(AUTON_START)],
        cwd=str(WORKSPACE),
        env=env,
        timeout=60,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    msg = (cp.stdout + "\n" + cp.stderr).strip()
    return cp.returncode == 0, msg


def stop_daemon() -> None:
    run(["bash", str(AUTON_STOP)], timeout=60)
    # ensure stale agent child processes do not continue detached
    stop_agent_children()


def safe_relpath(path_text: str, allowed_prefixes: List[str]) -> Optional[pathlib.Path]:
    rel = path_text.replace("\\", "/").strip()
    if not rel:
        return None
    p = pathlib.Path(rel)
    if p.is_absolute() or ".." in p.parts:
        return None
    if not any(rel.startswith(pref) for pref in allowed_prefixes):
        return None
    full = (WORKSPACE / p).resolve()
    if WORKSPACE not in full.parents and full != WORKSPACE:
        return None
    return full


def materialize_begin_file_blocks(stdout_path: pathlib.Path, allowed_prefixes: List[str]) -> Dict[str, Any]:
    res: Dict[str, Any] = {"materialized_files": [], "errors": []}
    if not stdout_path.exists():
        res["errors"].append("stdout_missing")
        return res

    text = stdout_path.read_text(encoding="utf-8", errors="ignore")
    markers = list(re.finditer(r"(?m)^BEGIN_FILE:\s*(.+?)\s*$", text))
    for idx, m in enumerate(markers):
        rel = m.group(1).strip()
        start = m.end()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        content = text[start:end]
        content = re.sub(r"\n?END_FILE\s*$", "", content.rstrip(), flags=re.MULTILINE)
        if content.startswith("\n"):
            content = content[1:]

        target = safe_relpath(rel, allowed_prefixes)
        if target is None:
            res["errors"].append(f"unsafe_path:{rel}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content + "\n", encoding="utf-8")
        res["materialized_files"].append(str(target.relative_to(WORKSPACE)))
    return res


def required_outputs_exist(task_def: Dict[str, Any]) -> Tuple[bool, List[str]]:
    req = [str(x) for x in task_def.get("required_output_files", []) if str(x).strip()]
    missing: List[str] = []
    for rel in req:
        p = safe_relpath(rel, ALLOWED_PREFIXES)
        if p is None:
            # required outputs may include allowed files outside runtime allowed list in older defs;
            # still allow existence check in workspace but refuse materialization there.
            p = (WORKSPACE / rel).resolve()
            if WORKSPACE not in p.parents and p != WORKSPACE:
                missing.append(rel)
                continue
        if not p.exists():
            missing.append(rel)
    return len(missing) == 0, missing


def normalize_task_state(task_id: str, status: str, summary: str, materialized_files: Optional[List[str]] = None) -> None:
    p = STATE_TASKS_DIR / f"{task_id}.json"
    d = load_json(p, {})
    now = now_iso()
    hist = list(d.get("history") or [])
    hist.append({"ts": now, "status": status, "reason": summary})
    d.update({
        "task_id": task_id,
        "status": status,
        "run_pid": None,
        "last_run": {"start": d.get("last_run", {}).get("start"), "end": now, "status": status},
        "last_summary": summary,
        "last_status_change_ts": now,
        "last_event_ts": now,
        "history": hist[-50:],
    })
    if status == "blocked_quota":
        d["last_retry_reason"] = "quota_detected_by_watchdog"
    elif status == "blocked_auth":
        d["last_retry_reason"] = "auth_detected_by_watchdog"
    elif status == "human_attention_required":
        d["attention_reason"] = summary
    p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")

    append_event({
        "event": "phase_017_recovered" if status == "completed" else "phase_017_failed",
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "materialized_files": materialized_files or [],
    })


def detect_quota_or_auth(stdout: str, stderr: str) -> Tuple[bool, bool]:
    text = (stdout + "\n" + stderr).lower()
    quota = any(x in text for x in QUOTA_PATTERNS)
    auth = any(x in text for x in AUTH_PATTERNS)
    return quota, auth


def secret_scan_files(files: List[str]) -> Tuple[bool, List[str]]:
    hit_pat = re.compile(r"api[_-]?key|secret|token|password|private|binance[_-]?secret|sk-|AKIA|BEGIN.*KEY", re.IGNORECASE)
    hits: List[str] = []
    for rel in files:
        p = (WORKSPACE / rel).resolve()
        if not p.exists() or p.suffix == ".pyc":
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if hit_pat.search(txt):
            hits.append(rel)
    return len(hits) == 0, hits


def commit_and_push(files: List[str], message: str) -> Tuple[bool, str]:
    existing = [f for f in files if (WORKSPACE / f).exists()]
    if not existing:
        return False, "no_files_to_commit"

    add = run(["git", "add", "--"] + existing)
    if add.returncode != 0:
        return False, (add.stdout + "\n" + add.stderr).strip()

    commit = run(["git", "commit", "-m", message])
    if commit.returncode != 0:
        out = (commit.stdout + "\n" + commit.stderr).strip()
        if "nothing to commit" in out.lower():
            return True, "nothing_to_commit"
        return False, out

    push = run(["git", "push"])
    if push.returncode != 0:
        return False, (push.stdout + "\n" + push.stderr).strip()
    return True, "pushed"


def planner_once_no_execute() -> Dict[str, Any]:
    env = os.environ.copy()
    env["AGENT_SUPERVISOR_PLANNER_TIMEOUT_SECONDS"] = str(PLANNER_TIMEOUT_SECONDS)
    cp = subprocess.run(
        [
            sys.executable,
            str(SUPERVISOR_BIN),
            "--planner-once",
            "--no-execute-planned-tasks",
        ],
        cwd=str(WORKSPACE),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = load_json(PLANNER_STATUS, {})
    return {
        "returncode": cp.returncode,
        "stdout": cp.stdout,
        "stderr": cp.stderr,
        "planner_status": payload,
    }


def task_file_for_id(task_id: str) -> pathlib.Path:
    return BASE / "tasks" / f"{task_id}.json"


def run_supervisor_task(task_id: str) -> Dict[str, Any]:
    cp = subprocess.run(
        [sys.executable, str(SUPERVISOR_BIN), "--task-id", task_id],
        cwd=str(WORKSPACE),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return {"returncode": cp.returncode, "stdout": cp.stdout, "stderr": cp.stderr}


def safe_non_implementation_task(task_id: str) -> bool:
    if task_id in IMPLEMENTATION_TASKS:
        return False
    tf = task_file_for_id(task_id)
    task = load_json(tf, {})
    risk = str(task.get("risk_level", "")).upper()
    if risk not in {"L1", "L2"}:
        return False
    purpose = str(task.get("purpose", "")).lower()
    prompt = str(task.get("prompt", "")).lower()
    if "implementation" in purpose or "build v2" in prompt:
        return False
    if "015a" in prompt or "015b" in prompt or "015c" in prompt or "015d" in prompt or "015e" in prompt or "015f" in prompt:
        return False
    return True


def preflight() -> Dict[str, Any]:
    raw_git = run(["git", "status", "--short"]).stdout.strip()
    ignored_runtime = {
        "claude_worklog/agent_supervisor/status/phase_017_watchdog.json",
    }
    kept_lines: List[str] = []
    for ln in (raw_git.splitlines() if raw_git else []):
        rel = ln[3:].strip() if len(ln) >= 4 else ln.strip()
        if rel in ignored_runtime:
            continue
        kept_lines.append(ln)
    git_status = "\n".join(kept_lines).strip()
    git_clean = (git_status == "")
    state017 = load_json(TASK_017_STATE, {})
    t017_pending = (state017.get("status") == "pending")
    impl_ok, impl_states = is_implementation_blocked()
    procs = process_list()
    daemon_is_running = daemon_running(procs)

    safe_to_start = git_clean and t017_pending and impl_ok
    return {
        "git_clean": git_clean,
        "t017_pending": t017_pending,
        "impl_blocked": impl_ok,
        "daemon_running": daemon_is_running,
        "safe_to_start": safe_to_start,
        "impl_states": impl_states,
        "git_status": git_status,
        "raw_git_status": raw_git,
    }


def collect_snapshot(started_at: float) -> Dict[str, Any]:
    current = load_json(CURRENT_STATUS, {})
    queue = load_json(QUEUE_STATUS, {})
    planner = load_json(PLANNER_STATUS, {})
    t017 = load_json(TASK_017_STATE, {})
    procs = process_list()

    stdout_stats = file_stats(TASK_017_RUN_DIR / "stdout.txt")
    stderr_stats = file_stats(TASK_017_RUN_DIR / "stderr.txt")

    age = latest_event_age_seconds()
    elapsed = int(time.time() - started_at)

    return {
        "ts": now_iso(),
        "elapsed_seconds": elapsed,
        "current_status": current,
        "queue_status": queue,
        "planner_status": planner,
        "task_017_state": t017,
        "stdout_stats": stdout_stats,
        "stderr_stats": stderr_stats,
        "event_age_seconds": age,
        "processes": procs,
    }


def planner_stuck(snapshot: Dict[str, Any]) -> bool:
    planner = snapshot.get("planner_status", {})
    if planner.get("planner_status") != "running":
        return False
    for p in planner_processes(snapshot.get("processes", [])):
        if p.get("etimes", 0) > PLANNER_TIMEOUT_SECONDS:
            return True
    return False


def task_child_timed_out(snapshot: Dict[str, Any]) -> bool:
    for p in snapshot.get("processes", []):
        cmd = p.get("cmd", "")
        if TASK_017 in cmd and p.get("etimes", 0) > TASK_CHILD_TIMEOUT_SECONDS:
            return True
    return False


def task_017_child_age_seconds(snapshot: Dict[str, Any]) -> Optional[int]:
    ages: List[int] = []
    for p in snapshot.get("processes", []):
        cmd = p.get("cmd", "")
        if TASK_017 in cmd:
            ages.append(int(p.get("etimes", 0) or 0))
    if not ages:
        return None
    return max(ages)


def no_output_growth(snapshot: Dict[str, Any]) -> bool:
    t017 = snapshot.get("task_017_state", {})
    if t017.get("status") != "running":
        return False
    now_ts = int(time.time())
    mtimes = []
    for s in [snapshot.get("stdout_stats", {}), snapshot.get("stderr_stats", {})]:
        m = s.get("mtime")
        if m is not None:
            mtimes.append(int(m))
    if not mtimes:
        return True
    last = max(mtimes)
    return (now_ts - last) > NO_GROWTH_TIMEOUT_SECONDS


def has_active_task_017_process(snapshot: Dict[str, Any]) -> bool:
    return any(TASK_017 in str(p.get("cmd", "")) for p in snapshot.get("processes", []))


def task_running_without_process(snapshot: Dict[str, Any]) -> bool:
    t017 = snapshot.get("task_017_state", {})
    if t017.get("status") != "running":
        return False
    pid = t017.get("run_pid")
    if not pid:
        # no pid recorded and no child command for task
        return not any(TASK_017 in p.get("cmd", "") for p in snapshot.get("processes", []))
    try:
        os.kill(int(pid), 0)
        return False
    except Exception:
        return True


def read_task_logs() -> Tuple[str, str]:
    out = ""
    err = ""
    so = TASK_017_RUN_DIR / "stdout.txt"
    se = TASK_017_RUN_DIR / "stderr.txt"
    if so.exists():
        out = so.read_text(encoding="utf-8", errors="ignore")
    if se.exists():
        err = se.read_text(encoding="utf-8", errors="ignore")
    return out, err


def finalize_with_codex_followup() -> Dict[str, Any]:
    planner = planner_once_no_execute()
    pstat = planner.get("planner_status", {})
    next_tasks = pstat.get("next_planned_tasks") or []

    codex_task_id = None
    for tid in next_tasks:
        tf = task_file_for_id(str(tid))
        task = load_json(tf, {})
        if str(task.get("agent", "")) == "codex" and safe_non_implementation_task(str(tid)):
            codex_task_id = str(tid)
            break

    codex_run = None
    codex_result = "not_run"
    if codex_task_id:
        codex_run = run_supervisor_task(codex_task_id)
        verdict = read_first_line(CODEX_GO_NO_GO).upper()
        if "PASS" in verdict:
            PHASE_REPORT_PASS.parent.mkdir(parents=True, exist_ok=True)
            PHASE_REPORT_PASS.write_text(
                "HUMAN_APPROVAL_REQUIRED_TO_UNBLOCK_015A_ONLY\n"
                "Codex scaffold queue re-review passed. Keep 015B-015F blocked_approval.\n",
                encoding="utf-8",
            )
            codex_result = "pass"
        else:
            PHASE_REPORT_FAIL.parent.mkdir(parents=True, exist_ok=True)
            PHASE_REPORT_FAIL.write_text(
                "CODEX_SCAFFOLD_QUEUE_REREVIEW_BLOCKED\n"
                "Implementation tasks remain blocked_approval. Review 06_CODEX_QUEUE_REVIEW.md for blockers.\n",
                encoding="utf-8",
            )
            codex_result = "blocked"

    return {
        "planner_once": planner,
        "codex_rereview_task": codex_task_id,
        "codex_rereview_run": codex_run,
        "codex_rereview_result": codex_result,
    }


def poll_loop() -> int:
    started = time.time()
    append_event({"event": "phase_017_started", "task_id": TASK_017})

    # clear stale child processes from prior interrupted runs
    stale_killed = stop_agent_children()
    if stale_killed:
        append_event({"event": "phase_017_recovered", "reason": "stale_agent_children_stopped", "pids": stale_killed})

    ok, msg = start_daemon()
    if not ok:
        append_event({"event": "phase_017_failed", "reason": "daemon_start_failed", "detail": msg})
        write_json(WATCHDOG_STATUS_FILE, {"ts": now_iso(), "status": "failed", "reason": "daemon_start_failed", "detail": msg})
        return 1

    last_progress_emit = 0.0

    while True:
        snapshot = collect_snapshot(started)
        write_json(WATCHDOG_STATUS_FILE, snapshot)

        if time.time() - last_progress_emit >= 60:
            append_event({
                "event": "phase_017_progress",
                "task_017_status": snapshot.get("task_017_state", {}).get("status"),
                "planner_status": snapshot.get("planner_status", {}).get("planner_status"),
                "event_age_seconds": snapshot.get("event_age_seconds"),
            })
            last_progress_emit = time.time()

        # hard guard: implementation tasks must stay blocked
        impl_ok, impl_states = is_implementation_blocked()
        if not impl_ok:
            stop_daemon()
            normalize_task_state(TASK_017, "human_attention_required", "implementation task unblocked during phase")
            append_event({"event": "phase_017_failed", "reason": "implementation_unblocked", "impl_states": impl_states})
            return 2

        # timeout guard
        if (time.time() - started) > MAX_DURATION_SECONDS:
            stop_daemon()
            normalize_task_state(TASK_017, "human_attention_required", "phase watchdog exceeded max duration")
            append_event({"event": "phase_017_failed", "reason": "max_duration_exceeded"})
            return 3

        t017 = snapshot.get("task_017_state", {})
        task_def = load_json(TASK_017_DEF, {})

        # quota/auth detection
        stdout, stderr = read_task_logs()
        quota, auth = detect_quota_or_auth(stdout, stderr)
        if quota:
            stop_daemon()
            normalize_task_state(TASK_017, "blocked_quota", "quota detected in 017 logs")
            append_event({"event": "phase_017_blocked_quota", "task_id": TASK_017})
            return 4
        if auth:
            stop_daemon()
            normalize_task_state(TASK_017, "blocked_auth", "auth detected in 017 logs")
            append_event({"event": "phase_017_failed", "reason": "auth_detected"})
            return 5

        # daemon missing recovery
        if not daemon_running(snapshot.get("processes", [])) and t017.get("status") not in {"completed", "failed", "blocked_quota", "blocked_auth", "human_attention_required"}:
            ok2, msg2 = start_daemon()
            append_event({"event": "phase_017_recovered", "reason": "daemon_missing", "restart_ok": ok2, "detail": msg2})
            if not ok2:
                stop_daemon()
                normalize_task_state(TASK_017, "human_attention_required", "daemon missing and restart failed")
                return 6

        # planner stuck recovery
        task_running = (t017.get("status") == "running") or bool(snapshot.get("queue_status", {}).get("current_running_task"))
        if planner_stuck(snapshot) and (not task_running):
            stop_daemon()
            ok3, msg3 = start_daemon()
            append_event({"event": "phase_017_recovered", "reason": "planner_stuck_restart", "restart_ok": ok3, "detail": msg3})
            if not ok3:
                normalize_task_state(TASK_017, "human_attention_required", "planner stuck and daemon restart failed")
                return 7

        # no events timeout
        eage = snapshot.get("event_age_seconds")
        if isinstance(eage, int) and eage > NO_EVENT_TIMEOUT_SECONDS and (not task_running):
            stop_daemon()
            ok4, msg4 = start_daemon()
            append_event({"event": "phase_017_recovered", "reason": "no_events_timeout_restart", "restart_ok": ok4, "detail": msg4})
            if not ok4:
                normalize_task_state(TASK_017, "human_attention_required", "no events timeout and restart failed")
                return 8

        # stuck-running recoveries
        req_ok, _missing = required_outputs_exist(task_def)
        if t017.get("status") == "running" and req_ok:
            # ensure BEGIN_FILE outputs are materialized if needed
            mat = materialize_begin_file_blocks(TASK_017_RUN_DIR / "stdout.txt", ALLOWED_PREFIXES)
            normalize_task_state(TASK_017, "completed", "required outputs present; normalized by watchdog", mat.get("materialized_files", []))
            append_event({"event": "phase_017_recovered", "reason": "required_outputs_present_normalized_completed"})
            t017 = load_json(TASK_017_STATE, {})

        if task_child_timed_out(snapshot):
            stop_daemon()
            normalize_task_state(TASK_017, "human_attention_required", "task child exceeded timeout")
            return 9

        if no_output_growth(snapshot):
            child_age = task_017_child_age_seconds(snapshot)
            if req_ok:
                mat = materialize_begin_file_blocks(TASK_017_RUN_DIR / "stdout.txt", ALLOWED_PREFIXES)
                normalize_task_state(TASK_017, "completed", "no growth but required outputs present; normalized", mat.get("materialized_files", []))
                append_event({"event": "phase_017_recovered", "reason": "no_output_growth_with_outputs"})
            elif child_age is not None and child_age <= TASK_CHILD_TIMEOUT_SECONDS:
                append_event({
                    "event": "phase_017_recovered",
                    "reason": "no_output_growth_watch",
                    "task_child_age_seconds": child_age,
                    "action": "waiting_until_child_timeout",
                })
            else:
                stop_daemon()
                normalize_task_state(TASK_017, "human_attention_required", "017 stuck running with no output growth")
                return 10

        if task_running_without_process(snapshot):
            if req_ok:
                mat = materialize_begin_file_blocks(TASK_017_RUN_DIR / "stdout.txt", ALLOWED_PREFIXES)
                normalize_task_state(TASK_017, "completed", "process missing but outputs present; normalized", mat.get("materialized_files", []))
                append_event({"event": "phase_017_recovered", "reason": "running_without_process_with_outputs"})
            else:
                # Grace period: queue/state can lag process startup/teardown by one poll.
                append_event({
                    "event": "phase_017_recovered",
                    "reason": "running_without_process_watch",
                    "action": "waiting_for_next_poll",
                })
                time.sleep(POLL_SECONDS)
                snapshot2 = collect_snapshot(started)
                t017_2 = snapshot2.get("task_017_state", {})
                req_ok_2, _missing2 = required_outputs_exist(task_def)
                if task_running_without_process(snapshot2):
                    if req_ok_2:
                        mat = materialize_begin_file_blocks(TASK_017_RUN_DIR / "stdout.txt", ALLOWED_PREFIXES)
                        normalize_task_state(TASK_017, "completed", "process missing but outputs present; normalized", mat.get("materialized_files", []))
                    else:
                        stop_daemon()
                        normalize_task_state(TASK_017, "human_attention_required", "017 marked running but no process and no required outputs")
                        return 11
                else:
                    t017 = t017_2

        # completion path
        t017 = load_json(TASK_017_STATE, {})
        if t017.get("status") == "completed":
            stop_daemon()

            # gather materialized files from summary + git diff fallback
            summary = load_json(TASK_017_RUN_DIR / "summary.json", {})
            materialized = [str(x) for x in summary.get("materialized_files", []) if str(x).strip()]
            if not materialized:
                cp = run(["git", "diff", "--name-only", "HEAD"])
                for rel in (cp.stdout or "").splitlines():
                    rel = rel.strip()
                    if any(rel.startswith(pfx) for pfx in ALLOWED_PREFIXES):
                        materialized.append(rel)
            materialized = sorted(set(materialized))

            scan_ok, hits = secret_scan_files(materialized)
            if not scan_ok:
                append_event({"event": "phase_017_failed", "reason": "secret_scan_hits", "hits": hits})
                write_json(WATCHDOG_STATUS_FILE, {
                    "ts": now_iso(),
                    "status": "failed",
                    "reason": "secret_scan_hits",
                    "hits": hits,
                    "materialized_files": materialized,
                })
                return 12

            commit_ok, commit_msg = commit_and_push(materialized, "Phase 017 autonomous scaffold queue remediation outputs")

            follow = finalize_with_codex_followup()

            # commit/push follow-up marker files if created
            marker_files = []
            for p in [PHASE_REPORT_PASS, PHASE_REPORT_FAIL]:
                if p.exists():
                    marker_files.append(str(p.relative_to(WORKSPACE)))
            if marker_files:
                commit_and_push(marker_files, "Record phase 017 codex re-review gate outcome")

            append_event({
                "event": "phase_017_completed",
                "task_id": TASK_017,
                "materialized_files": materialized,
                "committed": commit_ok,
                "commit_result": commit_msg,
                "followup": {
                    "codex_rereview_task": follow.get("codex_rereview_task"),
                    "codex_rereview_result": follow.get("codex_rereview_result"),
                },
            })

            write_json(WATCHDOG_STATUS_FILE, {
                "ts": now_iso(),
                "status": "completed",
                "task_017_final_state": t017,
                "materialized_files": materialized,
                "commit_result": {"ok": commit_ok, "message": commit_msg},
                "followup": follow,
            })
            return 0

        # failure terminal states
        if t017.get("status") in {"blocked_quota", "blocked_auth", "failed", "human_attention_required"}:
            stop_daemon()
            append_event({"event": "phase_017_failed", "reason": f"terminal_state_{t017.get('status')}"})
            write_json(WATCHDOG_STATUS_FILE, {"ts": now_iso(), "status": "failed", "task_017_state": t017})
            return 13

        time.sleep(POLL_SECONDS)


def print_yes_no(name: str, val: bool) -> None:
    print(f"{name} {'yes' if val else 'no'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run phase 017 with watchdog")
    parser.add_argument("--dry-run", action="store_true", help="Preflight only")
    args = parser.parse_args()

    pf = preflight()
    if args.dry_run:
        print_yes_no("git clean", pf["git_clean"])
        print_yes_no("017 pending", pf["t017_pending"])
        print_yes_no("015A–015F blocked", pf["impl_blocked"])
        print_yes_no("daemon running", pf["daemon_running"])
        print_yes_no("safe_to_start", pf["safe_to_start"])
        return 0 if pf["safe_to_start"] else 2

    if not pf["safe_to_start"]:
        print("Preflight unsafe. Aborting.")
        print(json.dumps(pf, indent=2))
        return 2

    rc = poll_loop()

    # final report block
    t017 = load_json(TASK_017_STATE, {})
    status_file = load_json(WATCHDOG_STATUS_FILE, {})
    impl_ok, _impl_states = is_implementation_blocked()

    completed = status_file.get("status") == "completed"
    mat_files = status_file.get("materialized_files", []) if completed else []
    commit_ok = bool((status_file.get("commit_result") or {}).get("ok")) if completed else False
    codex_rerun_task = ((status_file.get("followup") or {}).get("codex_rereview_task")) if completed else None
    codex_rerun_result = ((status_file.get("followup") or {}).get("codex_rereview_result")) if completed else "not_run"

    print("017 final state", t017.get("status"))
    print("017 outputs materialized", "yes" if bool(mat_files) else "no")
    print("017 committed", "yes" if commit_ok else "no")
    print("017 pushed", "yes" if commit_ok else "no")
    print("Codex re-review run", "yes" if bool(codex_rerun_task) else "no")
    print("Codex re-review result", codex_rerun_result)
    print("015A–015F still blocked_approval", "yes" if impl_ok else "no")
    print("human approval required", "yes" if codex_rerun_result == "pass" else "no")

    if codex_rerun_result == "pass":
        print("next recommended action", "Human review and approve unblocking 015A only; keep 015B-015F blocked.")
    elif codex_rerun_result == "blocked":
        print("next recommended action", "Review blocker report and keep implementation tasks blocked.")
    else:
        print("next recommended action", "Inspect phase_017_watchdog.json and task state before retry.")

    print("git status")
    gs = run(["git", "status", "--short"]) 
    print(gs.stdout.strip())
    print("GitHub latest pushed commit")
    gl = run(["git", "log", "--oneline", "-1", "origin/master"])
    print((gl.stdout or "").strip())

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
