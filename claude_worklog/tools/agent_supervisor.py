#!/usr/bin/env python3
"""Agent Supervisor — reliability-hardened build.

Implements:
- Task definition vs runtime state separation (state/tasks/<id>.json)
- Daemon heartbeat (status/supervisor_heartbeat.json)
- Lockfile + duplicate-daemon protection (supervisor.lock)
- Stale-running detection
- No-event-for-N-minutes detection
- No-output-growth-for-N-minutes detection
- Subprocess timeout classification
- Quota / auth failure classification
- Retry policy (max_attempts, retry_count, resume_after_utc, retry reason)
- human_attention_required terminal state when retries exhausted
- Stale-state alerts surfaced through queue_status.json for dashboard
"""
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
STATE_DIR = BASE_DIR / "state"
STATE_TASKS_DIR = STATE_DIR / "tasks"
RUNS_DIR = BASE_DIR / "runs"
STATUS_DIR = BASE_DIR / "status"
LOGS_DIR = BASE_DIR / "logs"
TRACKED_PLANNER_DIR = BASE_DIR / "planner"
RUNTIME_DIR = BASE_DIR / "runtime"
RUNTIME_PLANNER_DIR = RUNTIME_DIR / "planner"
PLANNER_DIR = RUNTIME_PLANNER_DIR
EVENTS_FILE = BASE_DIR / "events.jsonl"
CURRENT_STATUS_FILE = STATUS_DIR / "current_status.json"
QUEUE_STATUS_FILE = STATUS_DIR / "queue_status.json"
AGENT_HEALTH_FILE = STATUS_DIR / "agent_health.json"
PLANNER_STATUS_FILE = STATUS_DIR / "planner_status.json"
HEARTBEAT_FILE = STATUS_DIR / "supervisor_heartbeat.json"
LOCK_FILE = BASE_DIR / "supervisor.lock"
NEXT_PHASE_FILE = BASE_DIR / "state/NEXT_PHASE.md"

AUTONOMOUS_CONTROL_PLANE_DIR = pathlib.Path("claude_worklog/autonomous_control_plane")
PLANNER_INPUT_PACKET_FILE = PLANNER_DIR / "PLANNER_INPUT_PACKET.md"
PLANNER_DECISION_FILE = PLANNER_DIR / "PLANNER_DECISION.md"
PLANNER_NEXT_TASKS_FILE = PLANNER_DIR / "NEXT_TASKS.json"
PLANNER_HUMAN_ACTION_FILE = PLANNER_DIR / "HUMAN_ACTION_REQUIRED.md"
PLANNER_GO_NO_GO_FILE = PLANNER_DIR / "PLANNER_GO_NO_GO.md"
PLANNER_OUTPUT_PREFIX = "claude_worklog/agent_supervisor/runtime/planner/"

WORKSPACE_ROOT = pathlib.Path(os.path.expanduser("~/Desktop/AI BOT REBUILD")).resolve()
FORBIDDEN_ROOT = pathlib.Path("/home/wali/Desktop/AI BOT").resolve()
STANDING_NON_LIVE_APPROVAL_FILE = pathlib.Path(
    "claude_worklog/approvals/STANDING_APPROVAL_NON_LIVE_V2_REBUILD_UNTIL_LIVE_GATE.md"
)
STANDING_NON_LIVE_APPROVAL_MARKER = "STANDING_APPROVAL_NON_LIVE_V2_REBUILD_UNTIL_LIVE_GATE"
STANDING_AUTONOMOUS_GOVERNOR_FILE = pathlib.Path(
    "claude_worklog/approvals/STANDING_AUTONOMOUS_GOVERNOR_UNTIL_LIVE_GATE.md"
)
STANDING_AUTONOMOUS_GOVERNOR_MARKER = "STANDING_AUTONOMOUS_GOVERNOR_UNTIL_LIVE_GATE"

SUPPORTED_AGENTS = {"claude", "codex", "ollama", "system_check"}
ALLOWED_AUTORUN = {"L0", "L1", "L2"}

DEFAULT_NO_EVENT_TIMEOUT_S = 1800
DEFAULT_NO_OUTPUT_GROWTH_TIMEOUT_S = 1200
DEFAULT_PLANNER_TIMEOUT_S = 420
HEARTBEAT_STALE_S = 600
SUPERVISOR_VERSION = "2.0-reliability-hardened"

DEFINITION_FIELDS = {
    "task_id", "agent", "risk_level", "cwd", "prompt", "command", "model",
    "depends_on", "priority", "emit_files", "allowed_output_prefixes",
    "required_output_files", "next_tasks_on_success", "next_tasks_on_failure",
    "max_attempts", "task_timeout_seconds", "no_event_timeout_seconds",
    "no_output_growth_timeout_seconds",
    "preapproved", "approval_file", "auto_commit", "commit_message",
    "next_recommended_action", "description",
    "predecessor_task_ids", "predecessor_required_marker",
    "predecessor_required_marker_file", "predecessor_codex_parallel_review_marker",
    "predecessor_codex_parallel_review_marker_file", "trigger_gate",
}

STATE_FIELDS = {
    "status", "retry_count", "run_pid", "last_run", "last_summary",
    "resume_after_utc", "last_status_change_ts", "last_retry_reason",
    "attention_reason", "history", "last_event_ts",
}

STATUS_VALUES = {
    "pending", "running", "completed", "failed",
    "blocked_quota", "blocked_auth", "blocked_approval", "blocked_dependency",
    "retry_scheduled", "skipped", "cancelled", "human_attention_required",
    "waiting_decision_packet", "delegated_decision_pending",
    "superseded_by_evidence",
}

TERMINAL_BLOCKING_STATUSES = {
    "failed", "cancelled", "blocked_auth", "blocked_approval",
    "human_attention_required", "superseded_by_evidence",
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

LIVE_FORBIDDEN_PATTERNS = [
    "redis-cli",
    "xadd",
    "xdel",
    "flushdb",
    "flushall",
    "redis write",
    "redis writes",
    "write redis",
    "delete redis",
    "delete redis keys",
    "restart live",
    "restart legacy",
    "systemctl restart",
    "pkill",
    "kill ",
    "place order",
    "cancel order",
    "place/cancel orders",
    "set leverage",
    "set margin",
    "enable live trading",
    "live trading",
    "exchange order",
    "deploy",
    "deployment",
    "production migration",
    "production database migration",
    "production db migration",
    "print secret",
    "commit secret",
    "send secret",
    "secret value",
    "secret values",
    "mutate legacy",
    "modify /home/wali/desktop/ai bot",
    "change /home/wali/desktop/ai bot",
    "write /home/wali/desktop/ai bot",
]

SAFETY_NEGATIONS = {"do not", "don't", "dont", "never", "no ", "without", "must not", "read-only", "read only"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def now_ts() -> float:
    return time.time()


def set_planner_output_target(promote: bool = False) -> None:
    """Select planner output storage.

    Default daemon/planner operation writes ignored runtime files. Tracked
    planner files are touched only when --promote-planner-output is supplied.
    """
    global PLANNER_DIR
    global PLANNER_INPUT_PACKET_FILE
    global PLANNER_DECISION_FILE
    global PLANNER_NEXT_TASKS_FILE
    global PLANNER_HUMAN_ACTION_FILE
    global PLANNER_GO_NO_GO_FILE
    global PLANNER_OUTPUT_PREFIX

    PLANNER_DIR = TRACKED_PLANNER_DIR if promote else RUNTIME_PLANNER_DIR
    PLANNER_INPUT_PACKET_FILE = PLANNER_DIR / "PLANNER_INPUT_PACKET.md"
    PLANNER_DECISION_FILE = PLANNER_DIR / "PLANNER_DECISION.md"
    PLANNER_NEXT_TASKS_FILE = PLANNER_DIR / "NEXT_TASKS.json"
    PLANNER_HUMAN_ACTION_FILE = PLANNER_DIR / "HUMAN_ACTION_REQUIRED.md"
    PLANNER_GO_NO_GO_FILE = PLANNER_DIR / "PLANNER_GO_NO_GO.md"
    base = "claude_worklog/agent_supervisor/planner/" if promote else "claude_worklog/agent_supervisor/runtime/planner/"
    PLANNER_OUTPUT_PREFIX = base


def ensure_dirs() -> None:
    for p in [BASE_DIR, TASKS_DIR, STATE_DIR, STATE_TASKS_DIR, RUNS_DIR, STATUS_DIR, LOGS_DIR, TRACKED_PLANNER_DIR, RUNTIME_PLANNER_DIR]:
        p.mkdir(parents=True, exist_ok=True)


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def append_event(event: Dict[str, Any]) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", now_iso())
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def in_workspace(path: pathlib.Path) -> bool:
    try:
        rp = path.resolve()
        return rp == WORKSPACE_ROOT or WORKSPACE_ROOT in rp.parents
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Task definition + runtime state separation
# ---------------------------------------------------------------------------


def load_task_definition(task_path: pathlib.Path) -> Dict[str, Any]:
    raw = load_json(task_path)
    return dict(raw)


def task_state_path(task_id: str) -> pathlib.Path:
    return STATE_TASKS_DIR / f"{task_id}.json"


def state_path_for(task_id: str) -> pathlib.Path:
    return task_state_path(task_id)


def default_task_state(task_id: str, fallback_status: str = "pending") -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "status": fallback_status or "pending",
        "retry_count": 0,
        "run_pid": None,
        "last_run": None,
        "last_summary": "",
        "resume_after_utc": None,
        "last_status_change_ts": None,
        "last_retry_reason": None,
        "attention_reason": None,
        "history": [],
        "last_event_ts": None,
    }


def load_task_state(task_id: str) -> Dict[str, Any]:
    sp = task_state_path(task_id)
    if sp.exists():
        try:
            return load_json(sp)
        except Exception:
            pass
    return default_task_state(task_id)


def write_task_state(task_id: str, state: Dict[str, Any]) -> None:
    state = dict(state)
    state["task_id"] = task_id
    write_json(task_state_path(task_id), state)


def update_task_state(task_id: str, **fields: Any) -> Dict[str, Any]:
    state = load_task_state(task_id)
    new_status = fields.get("status")
    if new_status and new_status != state.get("status"):
        state["last_status_change_ts"] = now_iso()
        hist = list(state.get("history") or [])
        hist.append({
            "ts": now_iso(),
            "status": new_status,
            "reason": fields.get("last_retry_reason")
                       or fields.get("attention_reason")
                       or fields.get("last_summary"),
        })
        state["history"] = hist[-50:]
    state.update(fields)
    state["last_event_ts"] = now_iso()
    write_task_state(task_id, state)
    append_event({
        "event": "runtime_state_updated",
        "task_id": task_id,
        "status": state.get("status"),
        "state_path": str(task_state_path(task_id)),
    })
    append_event({
        "event": "task_definition_untouched",
        "task_id": task_id,
        "definition_dir": str(TASKS_DIR),
    })
    return state


def save_task_state(task_id: str, state: Dict[str, Any]) -> None:
    write_task_state(task_id, state)


def set_task_runtime_status(task_id: str, status: str, summary: str = "", **fields: Any) -> Dict[str, Any]:
    fields = dict(fields)
    fields["status"] = status
    if summary:
        fields["last_summary"] = summary
    return update_task_state(task_id, **fields)


def merged_task_view(task_def: Dict[str, Any]) -> Dict[str, Any]:
    """Return immutable task intent plus runtime state for scheduling."""
    task_id = str(task_def.get("task_id", ""))
    definition = {k: v for k, v in task_def.items() if k in DEFINITION_FIELDS or k.startswith("_")}
    if not task_id:
        task_id = str(definition.get("task_id", ""))
    sp = task_state_path(task_id) if task_id else None
    if sp is not None and sp.exists():
        state = load_task_state(task_id)
    else:
        state = default_task_state(task_id, str(task_def.get("status", "pending") or "pending"))
    merged = dict(definition)
    merged.update({k: v for k, v in state.items() if k in STATE_FIELDS or k == "task_id"})
    return merged


def load_task(task_path: pathlib.Path) -> Dict[str, Any]:
    """Return merged definition + runtime state for callers that want one view."""
    raw = load_task_definition(task_path)
    raw.setdefault("task_id", task_path.stem)
    return merged_task_view(raw)


def migrate_legacy_task_files() -> int:
    """One-shot migration: pull state fields out of legacy task definition files
    into state/tasks/<id>.json so definitions become stable.
    Idempotent and state-only: task definition files are never rewritten."""
    moved = 0
    if not TASKS_DIR.exists():
        return 0
    for p in sorted(TASKS_DIR.glob("*.json")):
        try:
            raw = load_json(p)
        except Exception:
            continue
        task_id = str(raw.get("task_id", p.stem))
        sp = task_state_path(task_id)

        legacy_state = {k: raw[k] for k in STATE_FIELDS if k in raw}

        if not sp.exists():
            base = default_task_state(task_id, str(raw.get("status", "pending") or "pending"))
            base.update(legacy_state)
            write_task_state(task_id, base)
            moved += 1
        elif legacy_state:
            existing = load_json(sp)
            for k, v in legacy_state.items():
                existing.setdefault(k, v)
            write_task_state(task_id, existing)
            moved += 1
        append_event({
            "event": "task_definition_untouched",
            "task_id": task_id,
            "definition_path": str(p),
        })
    return moved


# ---------------------------------------------------------------------------
# Validation + safety
# ---------------------------------------------------------------------------


def line_is_negated(line: str) -> bool:
    return any(tok in line for tok in SAFETY_NEGATIONS)


def line_mentions_forbidden_root(line: str) -> bool:
    """Match the live legacy root without matching the rebuild workspace.

    `/home/wali/Desktop/AI BOT REBUILD` shares a textual prefix with the live
    bot root. Safety checks must treat the live root as a path boundary match,
    otherwise safe non-live tasks fail just because their cwd is the rebuild
    workspace.
    """
    root = re.escape(str(FORBIDDEN_ROOT).lower())
    return re.search(root + r"(?! rebuild)(?=$|[/'\"\\\s,.;:)\]])", line) is not None


def line_requests_forbidden_root_mutation(line: str) -> bool:
    if not line_mentions_forbidden_root(line) or line_is_negated(line):
        return False
    root = re.escape(str(FORBIDDEN_ROOT).lower())
    mutation = r"(write|modify|edit|patch|delete|remove|move|copy\s+to|touch|mutate|change)"
    return (
        re.search(mutation + r".{0,120}" + root, line) is not None
        or re.search(root + r".{0,120}" + mutation, line) is not None
    )


def has_standing_non_live_v2_rebuild_approval() -> bool:
    approval_path = WORKSPACE_ROOT / STANDING_NON_LIVE_APPROVAL_FILE
    ok = approval_path.exists() and STANDING_NON_LIVE_APPROVAL_MARKER in read_text(approval_path)
    if ok:
        append_event({
            "event": "standing_non_live_v2_approval_detected",
            "approval_file": str(STANDING_NON_LIVE_APPROVAL_FILE),
        })
    return ok


def has_standing_autonomous_governor_approval() -> bool:
    approval_path = WORKSPACE_ROOT / STANDING_AUTONOMOUS_GOVERNOR_FILE
    ok = approval_path.exists() and STANDING_AUTONOMOUS_GOVERNOR_MARKER in read_text(approval_path)
    if ok:
        append_event({
            "event": "standing_autonomous_governor_approval_detected",
            "approval_file": str(STANDING_AUTONOMOUS_GOVERNOR_FILE),
        })
    return ok


def final_live_gate_text(text: str) -> bool:
    lowered = text.lower()
    live_terms = (
        "enable live trading",
        "switch paper",
        "switch shadow",
        "live execution",
        "activate live trading api",
        "real exchange order",
        "place real order",
        "cancel real order",
        "change real exchange leverage",
        "change real exchange margin",
        "disable kill switch",
        "final live gate",
        "real capital",
    )
    return any(term in lowered for term in live_terms)


def task_requires_final_live_gate(task: Dict[str, Any]) -> bool:
    if str(task.get("risk_level", "")).upper() == "L5":
        return True
    joined = "\n".join(str(task.get(k, "")) for k in ("task_id", "description", "prompt", "command", "next_recommended_action"))
    return final_live_gate_text(joined)


def task_requires_non_live_decision_packet(task: Dict[str, Any]) -> bool:
    if task_requires_final_live_gate(task):
        return False
    joined = "\n".join(str(task.get(k, "")) for k in ("task_id", "description", "prompt", "command", "attention_reason", "next_recommended_action"))
    decision_terms = (
        "human approval",
        "approval_file",
        "approval file",
        "backup durability",
        "decision packet",
        "non-live approval",
        "redis trim hold",
        "operator reviews",
    )
    return any(term in joined.lower() for term in decision_terms)


def non_live_v2_task_safety_block(task: Dict[str, Any]) -> Optional[str]:
    risk = str(task.get("risk_level", "L0")).upper()
    if risk in {"L4", "L5"}:
        return f"risk level {risk} requires explicit live/final approval"

    task_cwd = pathlib.Path(task.get("cwd", str(WORKSPACE_ROOT))).expanduser()
    if not task_cwd.is_absolute():
        task_cwd = WORKSPACE_ROOT / task_cwd
    if not in_workspace(task_cwd):
        return "task cwd outside AI BOT REBUILD"

    prompt = str(task.get("prompt", ""))
    command = str(task.get("command", ""))
    combined = f"{prompt}\n{command}".lower()
    lines = [ln.strip() for ln in combined.splitlines()]

    if any(line_requests_forbidden_root_mutation(ln) for ln in lines):
        return "task mutates forbidden legacy root /home/wali/Desktop/AI BOT"

    for banned in LIVE_FORBIDDEN_PATTERNS:
        lines_with_banned = [ln for ln in lines if banned in ln]
        if any(not line_is_negated(ln) for ln in lines_with_banned):
            return f"non-live V2 standing approval blocked by safety pattern: {banned}"

    return None


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

    root_lines = [ln.strip() for ln in combined.splitlines()]
    if any(line_requests_forbidden_root_mutation(ln) for ln in root_lines):
        return "task mutates forbidden root /home/wali/Desktop/AI BOT"

    for banned in BANNED_PATTERNS:
        if banned in combined:
            lines_with_banned = [ln.strip() for ln in combined.splitlines() if banned in ln]
            if any(not line_is_negated(ln) for ln in lines_with_banned):
                return f"blocked by safety pattern: {banned}"

    return None


def task_approved_v2(task: Dict[str, Any]) -> Tuple[bool, str]:
    risk = str(task.get("risk_level", "L0")).upper()
    approval_file = str(task.get("approval_file", "")).strip()
    preapproved = bool(task.get("preapproved", False))
    task_id = str(task.get("task_id", ""))

    if risk in {"L1", "L2", "L3"} and (
        has_standing_non_live_v2_rebuild_approval()
        or has_standing_autonomous_governor_approval()
    ):
        safety_block = non_live_v2_task_safety_block(task)
        if safety_block:
            append_event({
                "event": "non_live_v2_task_blocked_by_safety",
                "task_id": task_id,
                "risk_level": risk,
                "reason": safety_block,
            })
            return False, safety_block
        append_event({
            "event": "non_live_v2_task_auto_unblocked",
            "task_id": task_id,
            "risk_level": risk,
            "approval_file": str(
                STANDING_AUTONOMOUS_GOVERNOR_FILE
                if has_standing_autonomous_governor_approval()
                else STANDING_NON_LIVE_APPROVAL_FILE
            ),
        })
        return True, ""

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


# ---------------------------------------------------------------------------
# Subprocess execution with hard timeout
# ---------------------------------------------------------------------------


def run_cmd_with_pid(
    cmd: List[str],
    cwd: pathlib.Path,
    stdout_path: pathlib.Path,
    stderr_path: pathlib.Path,
    timeout_seconds: Optional[int] = None,
    on_start: Optional[Callable[[int], None]] = None,
) -> Tuple[int, Optional[int], bool]:
    """Run a child process bounded by timeout. Returns (returncode, pid, timed_out).
    On timeout, kills entire process group; returncode forced to 124."""
    timed_out = False
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
            return rc, proc.pid, False
        except subprocess.TimeoutExpired:
            timed_out = True
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
                proc.wait(timeout=10)
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
            return 124, proc.pid, timed_out


def file_contains(path: pathlib.Path, needle: str) -> bool:
    if not path.exists():
        return False
    try:
        return needle in path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def read_text(path: pathlib.Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def planner_fallback_path(path: pathlib.Path) -> pathlib.Path:
    if RUNTIME_PLANNER_DIR in path.parents or path.parent == RUNTIME_PLANNER_DIR:
        return TRACKED_PLANNER_DIR / path.name
    return RUNTIME_PLANNER_DIR / path.name


def read_planner_text(path: pathlib.Path) -> str:
    txt = read_text(path)
    if txt:
        return txt
    return read_text(planner_fallback_path(path))


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

        content = re.sub(r"\n?END_FILE(?::.*)?\s*$", "", content.rstrip(), flags=re.MULTILINE)
        blocks.append({"path": rel_path, "content": content})

    return blocks


FENCE_LINE_RE = re.compile(r"^```(?:python|toml|json|bash)?\s*$", re.IGNORECASE)


def sanitize_emitted_file_content(rel_path: str, content: str) -> Tuple[str, bool]:
    """Remove wrapper markdown fences accidentally included in emitted files."""
    lines = content.splitlines()
    removed = False

    if lines and FENCE_LINE_RE.match(lines[0].strip()):
        lines = lines[1:]
        removed = True

    while lines and not lines[-1].strip():
        lines = lines[:-1]
    while lines and FENCE_LINE_RE.match(lines[-1].strip()):
        lines = lines[:-1]
        removed = True
        while lines and not lines[-1].strip():
            lines = lines[:-1]

    sanitized = "\n".join(lines).rstrip()
    if content.endswith("\n") or sanitized:
        sanitized += "\n"
    return sanitized, removed


TRAINER_LIVENESS_TEST_FILE_REMAP = {
    "test_signal_snapshot.py": "test_signal_snapshot_invariants.py",
    "test_signal_invariants.py": "test_signal_snapshot_invariants.py",
    "test_sla_config.py": "test_sla_config_invariants.py",
    "test_alert.py": "test_alert_invariants.py",
    "test_evaluator_zero_growth.py": "test_evaluator_zero_stream_growth.py",
    "test_evaluator_fatal_log.py": "test_evaluator_fatal_log_signature.py",
    "test_public_surface_imports.py": "test_public_surface.py",
    "test_evaluation_no_alert.py": "test_evaluator_no_alert.py",
    "test_evaluation_age_exceeds_threshold.py": "test_evaluator_age_exceeds.py",
    "test_evaluation_zero_stream_growth.py": "test_evaluator_zero_stream_growth.py",
    "test_evaluation_fatal_log_signature.py": "test_evaluator_fatal_log_signature.py",
    "test_evaluation_multi_reason_alert.py": "test_evaluator_multi_reason.py",
}


def safe_path_remap_candidate(rel_path: str, required_output_files: List[str]) -> Optional[str]:
    """Return a known-safe canonical emitted path if the task explicitly requires it.

    This intentionally supports only recurring non-live V2 layout mistakes.
    The canonical target must be present in required_output_files, which keeps
    the materializer from inventing paths or broadening a task's write scope.
    """
    normalized = normalize_relpath(rel_path)
    required = {normalize_relpath(x) for x in required_output_files if str(x).strip()}
    candidates: List[str] = []

    prefix_pairs = (
        ("v2/app/domain/", "v2/backend/app/domain/"),
        ("v2/tests/symbol_universe/", "v2/backend/tests/unit/symbol_universe/"),
        ("v2/tests/feature_snapshots/", "v2/backend/tests/unit/feature_snapshots/"),
    )
    for wrong, right in prefix_pairs:
        if normalized.startswith(wrong):
            candidates.append(right + normalized[len(wrong):])

    trainer_prefixes = (
        "v2/tests/trainer_liveness/",
        "v2/backend/tests/trainer_liveness/",
        "v2/tests/control_plane/trainer_liveness/",
    )
    trainer_right = "v2/backend/tests/unit/domain/trainer_liveness/"
    for wrong in trainer_prefixes:
        if normalized.startswith(wrong):
            filename = normalized[len(wrong):]
            candidates.append(trainer_right + filename)
            candidates.append(trainer_right + TRAINER_LIVENESS_TEST_FILE_REMAP.get(filename, filename))

    for candidate in candidates:
        candidate_path = pathlib.Path(candidate)
        if candidate_path.is_absolute() or ".." in candidate_path.parts:
            continue
        target = (WORKSPACE_ROOT / candidate_path).resolve()
        if candidate in required and in_workspace(target):
            return candidate
    return None


def materialize_emit_files(
    stdout_path: pathlib.Path,
    allowed_output_prefixes: List[str],
    required_output_files: Optional[List[str]] = None,
    task_risk_level: str = "L0",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "materialized_files": [],
        "errors": [],
        "blocks_found": 0,
        "safe_path_remaps": [],
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
            remapped = None
            if str(task_risk_level).upper() in {"L1", "L2", "L3"}:
                remapped = safe_path_remap_candidate(rel_path, required_output_files or [])
            if remapped and is_relpath_allowed(remapped, allowed_output_prefixes):
                append_event({
                    "event": "safe_path_remap_materialized",
                    "source_path": rel_path,
                    "canonical_path": remapped,
                    "risk_level": str(task_risk_level).upper(),
                })
                result["safe_path_remaps"].append({"source_path": rel_path, "canonical_path": remapped})
                rel_path = remapped
                p = pathlib.Path(rel_path)
            else:
                result["errors"].append(f"emit-file path not allowed by prefixes: {rel_path}")
                continue

        target = (WORKSPACE_ROOT / p).resolve()
        if not in_workspace(target):
            result["errors"].append(f"refused emit-file outside workspace: {rel_path}")
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        content, sanitized = sanitize_emitted_file_content(rel_path, content)
        if sanitized:
            append_event({
                "event": "materialized_content_sanitized",
                "path": rel_path,
                "reason": "removed_outer_markdown_fence",
            })
        target.write_text(content, encoding="utf-8")
        result["materialized_files"].append(rel_path)

    return result


# ---------------------------------------------------------------------------
# Agent readiness
# ---------------------------------------------------------------------------


def codex_ready() -> bool:
    return file_contains(BASE_DIR / "CODEX_LOCAL_AGENT_READY.md", "CODEX_LOCAL_AGENT_READY")


def claude_ready() -> bool:
    return file_contains(BASE_DIR / "CLAUDE_LOCAL_AGENT_READY.md", "CLAUDE_LOCAL_AGENT_READY")


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


PROMPT_PERMISSION_MODEL_PATTERNS = [
    "permission denials",
    "approve writes",
    "grant permission",
    "permission denied",
    "i need you to approve writes",
    "could you grant permission",
]

AUTH_FAILURE_PATTERNS = [
    "not authenticated",
    "login required",
    "invalid api key",
    "auth token expired",
    "unauthorized",
    "401",
    "403",
]


def is_prompt_permission_model_error(raw: str) -> bool:
    return any(k in raw for k in PROMPT_PERMISSION_MODEL_PATTERNS)


def is_auth_failure(raw: str) -> bool:
    return any(k in raw for k in AUTH_FAILURE_PATTERNS)


def classify_agent_block(agent: str, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> Tuple[Optional[str], Optional[str]]:
    raw = (read_text(stdout_path) + "\n" + read_text(stderr_path)).lower()
    if is_prompt_permission_model_error(raw):
        return "failed", "prompt_permission_model_error"
    if agent == "claude":
        if any(k in raw for k in ["usage limit", "hit your limit", "resets", "quota"]):
            return "blocked_quota", parse_claude_reset_to_utc(read_text(stdout_path) + "\n" + read_text(stderr_path))
        if is_auth_failure(raw):
            return "blocked_auth", None
    if agent == "codex":
        if any(k in raw for k in ["rate limit", "quota", "usage limit", "too many requests"]):
            return "blocked_quota", None
        if is_auth_failure(raw):
            return "blocked_auth", None
    return None, None


def detect_quota_block(agent: str, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> Tuple[bool, Optional[str]]:
    raw = (read_text(stdout_path) + "\n" + read_text(stderr_path)).lower()
    if agent == "claude":
        if any(k in raw for k in ["usage limit", "hit your limit", "resets", "quota", "rate limit"]):
            return True, parse_claude_reset_to_utc(read_text(stdout_path) + "\n" + read_text(stderr_path))
    if agent == "codex":
        if any(k in raw for k in ["rate limit", "quota", "usage limit", "too many requests"]):
            return True, None
    return False, None


def run_claude_readiness_check() -> bool:
    rc, out, err = command_quick(
        ["claude", "--print", "Print CLAUDE_READY_FOR_SMALL_TASK", "--output-format", "text"],
        timeout=40,
    )
    return rc == 0 and "CLAUDE_READY_FOR_SMALL_TASK" in (out + "\n" + err)


# ---------------------------------------------------------------------------
# Autonomous planner mode
# ---------------------------------------------------------------------------


def git_status_short() -> str:
    rc, out, err = command_quick(["git", "status", "--short"], timeout=20)
    if rc != 0:
        return (out + "\n" + err).strip() or "git_status_unavailable"
    return out.strip() or "CLEAN"


def tail_events(n: int = 20) -> List[str]:
    p = WORKSPACE_ROOT / EVENTS_FILE
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        return lines[-n:]
    except Exception:
        return []


def latest_go_no_go_files(limit: int = 12) -> List[pathlib.Path]:
    root = WORKSPACE_ROOT / "claude_worklog"
    if not root.exists():
        return []
    files: List[pathlib.Path] = []
    for pat in ["**/*GO_NO_GO*.md", "**/*go_no_go*.md"]:
        files.extend(root.glob(pat))
    uniq: Dict[str, pathlib.Path] = {}
    for p in files:
        uniq[str(p.resolve())] = p
    ranked: List[Tuple[float, pathlib.Path]] = []
    for p in uniq.values():
        try:
            ranked.append((p.stat().st_mtime, p))
        except Exception:
            continue
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in ranked[:max(1, limit)]]


def read_next_phase_marker() -> str:
    txt = read_text(WORKSPACE_ROOT / NEXT_PHASE_FILE)
    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
    return lines[-1] if lines else "NEXT_PHASE_UNKNOWN"


def build_planner_input_packet() -> pathlib.Path:
    PLANNER_DIR.mkdir(parents=True, exist_ok=True)

    control_files = [
        WORKSPACE_ROOT / AUTONOMOUS_CONTROL_PLANE_DIR / "00_MASTER_OBJECTIVE.md",
        WORKSPACE_ROOT / AUTONOMOUS_CONTROL_PLANE_DIR / "01_AGENT_ROLES.md",
        WORKSPACE_ROOT / AUTONOMOUS_CONTROL_PLANE_DIR / "02_AUTONOMOUS_DECISION_POLICY.md",
        WORKSPACE_ROOT / AUTONOMOUS_CONTROL_PLANE_DIR / "03_PLANNER_LOOP_SPEC.md",
        WORKSPACE_ROOT / AUTONOMOUS_CONTROL_PLANE_DIR / "04_STATUS_AND_DASHBOARD_REQUIREMENTS.md",
        WORKSPACE_ROOT / AUTONOMOUS_CONTROL_PLANE_DIR / "05_GO_NO_GO.md",
    ]

    current_status = read_text(WORKSPACE_ROOT / CURRENT_STATUS_FILE)
    queue_status = read_text(WORKSPACE_ROOT / QUEUE_STATUS_FILE)
    next_phase = read_text(WORKSPACE_ROOT / NEXT_PHASE_FILE)
    git_short = git_status_short()

    monitor_candidates = [
        WORKSPACE_ROOT / "claude_worklog/monitoring_summary.md",
        WORKSPACE_ROOT / "claude_worklog/continuous_monitoring/monitoring_summary.md",
        WORKSPACE_ROOT / "claude_worklog/evidence_packets/README.md",
    ]
    monitor_text = ""
    for mc in monitor_candidates:
        if mc.exists():
            monitor_text = read_text(mc)
            if monitor_text:
                break

    gate_lines: List[str] = []
    for gf in latest_go_no_go_files(limit=12):
        rel = gf.relative_to(WORKSPACE_ROOT)
        first_line = ""
        txt = read_text(gf)
        for ln in txt.splitlines():
            if ln.strip():
                first_line = ln.strip()
                break
        gate_lines.append(f"- {rel}: {first_line or 'EMPTY'}")

    sections: List[str] = []
    sections.append("# Planner Input Packet")
    sections.append("")
    sections.append(f"Generated at: {now_iso()}")
    sections.append(f"Workspace: {WORKSPACE_ROOT}")
    sections.append("")
    sections.append("## Git Status --short")
    sections.append("")
    sections.append("```text")
    sections.append(git_short)
    sections.append("```")
    sections.append("")
    sections.append("## Next Phase Marker")
    sections.append("")
    sections.append(next_phase or "NEXT_PHASE_MISSING")
    sections.append("")
    sections.append("## current_status.json")
    sections.append("")
    sections.append("```json")
    sections.append(current_status or "{}")
    sections.append("```")
    sections.append("")
    sections.append("## queue_status.json")
    sections.append("")
    sections.append("```json")
    sections.append(queue_status or "{}")
    sections.append("```")
    sections.append("")
    sections.append("## Latest GO/NO-GO Markers")
    sections.append("")
    sections.extend(gate_lines or ["- none found"])
    sections.append("")
    sections.append("## Monitoring / Evidence Summary (truncated)")
    sections.append("")
    sections.append((monitor_text[:3000] if monitor_text else "none found"))
    sections.append("")
    sections.append("## Recent Supervisor Events (tail)")
    sections.append("")
    sections.extend(tail_events(20) or ["none"])

    for cf in control_files:
        rel = cf.relative_to(WORKSPACE_ROOT)
        sections.append("")
        sections.append(f"## {rel}")
        sections.append("")
        txt = read_text(cf)
        sections.append((txt[:3500] if txt else "MISSING"))

    PLANNER_INPUT_PACKET_FILE.write_text("\n".join(sections).strip() + "\n", encoding="utf-8")
    return PLANNER_INPUT_PACKET_FILE


def parse_planner_next_tasks() -> List[str]:
    source = PLANNER_NEXT_TASKS_FILE if PLANNER_NEXT_TASKS_FILE.exists() else planner_fallback_path(PLANNER_NEXT_TASKS_FILE)
    if not source.exists():
        return []
    raw = read_text(source)
    data: Any = None
    try:
        data = json.loads(raw)
    except Exception:
        # Accept markdown-wrapped JSON by slicing first/last braces.
        start_obj = raw.find("{")
        end_obj = raw.rfind("}")
        start_arr = raw.find("[")
        end_arr = raw.rfind("]")
        candidate = ""
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            candidate = raw[start_obj:end_obj + 1]
        elif start_arr != -1 and end_arr != -1 and end_arr > start_arr:
            candidate = raw[start_arr:end_arr + 1]
        if not candidate:
            return []
        try:
            data = json.loads(candidate)
        except Exception:
            return []

    items: List[Any] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ["next_tasks", "next_planned_tasks", "tasks", "task_ids", "items"]:
            val = data.get(key)
            if isinstance(val, list):
                items = val
                break

    task_ids: List[str] = []
    for item in items:
        if isinstance(item, str):
            tid = item.strip()
        elif isinstance(item, dict):
            tid = str(item.get("task_id", "")).strip()
        else:
            tid = ""
        if tid:
            task_ids.append(tid)
    return list(dict.fromkeys(task_ids))


def planner_go_no_go_value() -> str:
    txt = read_planner_text(PLANNER_GO_NO_GO_FILE)
    allowed = {
        "PLANNER_NEXT_TASKS_READY",
        "PLANNER_HUMAN_ACTION_REQUIRED",
        "PLANNER_BLOCKED",
    }
    for ln in txt.splitlines():
        s = ln.strip().strip("`")
        if s in allowed:
            return s
    return "PLANNER_BLOCKED"


def planner_human_action_required() -> bool:
    marker = planner_go_no_go_value().strip().upper()
    if marker == "PLANNER_HUMAN_ACTION_REQUIRED":
        return True
    if marker == "PLANNER_NEXT_TASKS_READY":
        return False
    txt = read_planner_text(PLANNER_HUMAN_ACTION_FILE).lower()
    if "no human action required" in txt:
        return False
    return "human action required: yes" in txt or "human approval" in txt


def first_non_empty_line(path: pathlib.Path) -> str:
    txt = read_text(path)
    for ln in txt.splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def planner_task_trigger_gate_ok(task: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate optional per-task trigger gate contract.

    If a task defines trigger_gate.file + trigger_gate.expected_value,
    the referenced marker must exist and match exactly.
    """
    tg = task.get("trigger_gate")
    if not isinstance(tg, dict):
        return True, ""

    gate_file_raw = str(tg.get("file", "")).strip()
    expected = str(tg.get("expected_value", "")).strip()
    if not gate_file_raw or not expected:
        return True, ""

    gate_path = pathlib.Path(gate_file_raw)
    if not gate_path.is_absolute():
        gate_path = WORKSPACE_ROOT / gate_path
    gate_path = gate_path.resolve()

    if not in_workspace(gate_path):
        return False, f"trigger_gate file outside workspace: {gate_file_raw}"
    if not gate_path.exists():
        return False, f"trigger_gate file missing: {gate_file_raw}"

    actual = first_non_empty_line(gate_path)
    if actual != expected:
        return False, (
            f"trigger_gate mismatch for {gate_file_raw}: "
            f"expected '{expected}' got '{actual or 'EMPTY'}'"
        )
    return True, ""


def planner_task_autorun_allowed(task_path: pathlib.Path, human_required: bool) -> Tuple[bool, str]:
    if human_required:
        return False, "human action required"

    task = load_task(task_path)
    gate_ok, gate_reason = planner_task_trigger_gate_ok(task)
    if not gate_ok:
        return False, gate_reason

    risk = str(task.get("risk_level", "L0")).upper()
    standing_allows_l3 = risk == "L3" and has_standing_non_live_v2_rebuild_approval()
    if risk not in ALLOWED_AUTORUN and not standing_allows_l3:
        return False, f"risk level {risk} not auto-runnable"

    if standing_allows_l3:
        safety_block = non_live_v2_task_safety_block(task)
        if safety_block:
            append_event({
                "event": "non_live_v2_task_blocked_by_safety",
                "task_id": str(task.get("task_id", "")),
                "risk_level": risk,
                "reason": safety_block,
            })
            return False, safety_block

    validation_error = validate_task(task)
    if validation_error:
        return False, validation_error

    approved, reason = task_approved_v2(task)
    if not approved:
        return False, reason

    status_map = task_status_map(list_tasks())
    blockers = dependency_blockers(task, status_map)
    blockers.extend(predecessor_marker_blockers(task))
    if blockers:
        return False, f"waiting on dependencies: {', '.join(blockers)}"

    status = task_effective_status(task)
    if status in {
        "completed", "running", "cancelled", "failed", "blocked_auth",
        "blocked_approval", "human_attention_required", "superseded_by_evidence",
    }:
        return False, f"task status {status} not runnable"

    return True, "allowed"


def write_planner_fallback_files(
    go_no_go: str,
    decision: str,
    human_action_required: bool,
    next_tasks: Optional[List[str]] = None,
) -> None:
    PLANNER_DIR.mkdir(parents=True, exist_ok=True)
    PLANNER_DECISION_FILE.write_text(decision.strip() + "\n", encoding="utf-8")
    payload = {
        "next_tasks": [{"task_id": tid} for tid in (next_tasks or [])],
        "human_action_required": human_action_required,
        "generated_at": now_iso(),
    }
    write_json(PLANNER_NEXT_TASKS_FILE, payload)
    human_text = [
        "# Human Action Required",
        "",
        f"human action required: {'yes' if human_action_required else 'no'}",
        "",
        decision.strip(),
    ]
    PLANNER_HUMAN_ACTION_FILE.write_text("\n".join(human_text).strip() + "\n", encoding="utf-8")
    PLANNER_GO_NO_GO_FILE.write_text(go_no_go.strip() + "\n", encoding="utf-8")


def run_ollama_local_summary(packet_path: pathlib.Path) -> str:
    models = ollama_models()
    if not models:
        return "Ollama fallback unavailable: no local model detected"
    model = models[0]
    prompt = (
        "Summarize this planner packet in <=12 bullets with safe next steps only. "
        "Do not propose live trading or Redis mutation.\n\n"
        + read_text(packet_path)[:12000]
    )
    rc, out, err = command_quick(["ollama", "run", model, prompt], timeout=180)
    if rc == 0 and out.strip():
        return out.strip()
    return (out + "\n" + err).strip() or "Ollama fallback failed"


def write_planner_status(payload: Dict[str, Any]) -> None:
    write_json(PLANNER_STATUS_FILE, payload)


def run_planner_once(
    no_execute_planned_tasks: bool = False,
    autonomous_mode_active: bool = False,
    promote_planner_output: bool = False,
) -> Dict[str, Any]:
    ensure_dirs()
    set_planner_output_target(promote_planner_output)
    packet_path = build_planner_input_packet()
    start = now_iso()

    running_payload = {
        "generated_at": start,
        "planner_status": "running",
        "autonomous_mode_active": autonomous_mode_active,
        "no_execute_planned_tasks": bool(no_execute_planned_tasks),
        "planner_go_no_go": "PLANNER_BLOCKED",
        "human_action_required": False,
        "next_planned_task": None,
        "next_planned_tasks": [],
        "will_execute_automatically": False,
        "executed_tasks": [],
        "decision_summary": "planner cycle started",
    }
    write_planner_status(running_payload)

    run_dir = RUNS_DIR / "planner_once"
    run_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"

    planner_status = "blocked"
    decision_summary = "planner blocked"
    blocked_reason = ""

    planner_prompt = (
        "You are Claude planner for AI BOT REBUILD. "
        f"Read {PLANNER_INPUT_PACKET_FILE} and decide the next safe task only. "
        "Hard constraints: do not touch /home/wali/Desktop/AI BOT, do not write Redis, do not delete Redis keys, "
        "do not restart live services, do not place/cancel orders, do not change leverage/margin, "
        "do not enable live trading. Safe non-live V2 rebuild milestones may run only when the standing "
        "non-live approval exists and supervisor safety/dependency gates pass. "
        f"Output BEGIN_FILE blocks only under {PLANNER_OUTPUT_PREFIX} for these files exactly: "
        "PLANNER_DECISION.md, NEXT_TASKS.json, HUMAN_ACTION_REQUIRED.md, PLANNER_GO_NO_GO.md. "
        "PLANNER_GO_NO_GO.md must be exactly one line: PLANNER_NEXT_TASKS_READY or "
        "PLANNER_HUMAN_ACTION_REQUIRED or PLANNER_BLOCKED. "
        "NEXT_TASKS.json must include task_id entries and dependency/gate context."
    )

    planner_timeout_s = int(os.environ.get("AGENT_SUPERVISOR_PLANNER_TIMEOUT_SECONDS", str(DEFAULT_PLANNER_TIMEOUT_S)))

    rc = 1
    timed_out = False
    if not claude_ready():
        planner_status = "blocked_auth"
        blocked_reason = "claude not ready marker missing"
        decision_summary = blocked_reason
        write_planner_fallback_files(
            "PLANNER_BLOCKED",
            "# Planner Decision\n\nPlanner blocked: Claude readiness marker missing.",
            human_action_required=True,
            next_tasks=[],
        )
    else:
        rc, _pid, timed_out = run_cmd_with_pid(
            ["claude", "--print", planner_prompt, "--output-format", "text"],
            WORKSPACE_ROOT,
            stdout_path,
            stderr_path,
            timeout_seconds=max(60, planner_timeout_s),
            on_start=None,
        )
        if rc == 0:
            mat = materialize_emit_files(stdout_path, [PLANNER_OUTPUT_PREFIX])
            missing: List[str] = []
            for p in [
                PLANNER_DECISION_FILE,
                PLANNER_NEXT_TASKS_FILE,
                PLANNER_HUMAN_ACTION_FILE,
                PLANNER_GO_NO_GO_FILE,
            ]:
                if p.exists():
                    continue
                if p.is_absolute():
                    try:
                        missing.append(str(p.relative_to(WORKSPACE_ROOT)))
                    except Exception:
                        missing.append(str(p))
                else:
                    missing.append(str(p))
            errors = [str(x) for x in mat.get("errors", [])]
            if missing or errors:
                planner_status = "blocked"
                blocked_reason = "; ".join(errors + ([f"missing planner outputs: {', '.join(missing)}"] if missing else []))
                decision_summary = blocked_reason
                write_planner_fallback_files(
                    "PLANNER_BLOCKED",
                    "# Planner Decision\n\nPlanner blocked due to malformed Claude planner output.",
                    human_action_required=True,
                    next_tasks=[],
                )
            else:
                planner_status = "ready"
                decision_summary = "planner decision materialized"
        else:
            classified, _reset_iso = classify_agent_block("claude", stdout_path, stderr_path)
            if timed_out:
                classified = classified or "blocked"
                blocked_reason = "planner subprocess timeout"
            if classified == "blocked_quota":
                planner_status = "blocked_quota"
                blocked_reason = "claude quota blocked"
                ollama_summary = run_ollama_local_summary(packet_path)
                write_planner_fallback_files(
                    "PLANNER_BLOCKED",
                    "# Planner Decision\n\nClaude quota blocked. Ollama fallback summary:\n\n" + ollama_summary,
                    human_action_required=True,
                    next_tasks=[],
                )
            elif classified == "blocked_auth":
                planner_status = "blocked_auth"
                blocked_reason = "claude auth blocked"
                write_planner_fallback_files(
                    "PLANNER_BLOCKED",
                    "# Planner Decision\n\nPlanner blocked: Claude auth/login issue detected.",
                    human_action_required=True,
                    next_tasks=[],
                )
            else:
                planner_status = "blocked"
                blocked_reason = "claude planner invocation failed"
                write_planner_fallback_files(
                    "PLANNER_BLOCKED",
                    "# Planner Decision\n\nPlanner blocked: Claude execution failed.",
                    human_action_required=True,
                    next_tasks=[],
                )
            decision_summary = blocked_reason

    go_no_go = planner_go_no_go_value()
    human_required = planner_human_action_required() or (go_no_go == "PLANNER_HUMAN_ACTION_REQUIRED")
    next_tasks = parse_planner_next_tasks()

    decision_text = read_planner_text(PLANNER_DECISION_FILE)
    for ln in decision_text.splitlines():
        stripped = ln.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("```"):
            continue
        if stripped.startswith("BEGIN_FILE") or stripped.startswith("END_FILE"):
            continue
        if stripped.startswith("---"):
            continue
        if stripped:
            decision_summary = ln.strip()
            break

    executed_tasks: List[Dict[str, Any]] = []
    will_execute_automatically = (
        go_no_go == "PLANNER_NEXT_TASKS_READY"
        and (not human_required)
        and (not no_execute_planned_tasks)
        and (planner_status == "ready")
    )

    if will_execute_automatically:
        for tid in next_tasks:
            tf = get_task_file_by_id(tid)
            if not tf:
                executed_tasks.append({"task_id": tid, "status": "skipped", "reason": "task file not found"})
                continue
            ok, reason = planner_task_autorun_allowed(tf, human_required)
            if not ok:
                executed_tasks.append({"task_id": tid, "status": "skipped", "reason": reason})
                continue
            result = run_task(tf, dry_run=False)
            executed_tasks.append({
                "task_id": tid,
                "status": result.get("status"),
                "summary": result.get("summary"),
            })

    end = now_iso()
    final_status = planner_status
    if planner_status == "ready":
        if go_no_go == "PLANNER_HUMAN_ACTION_REQUIRED":
            final_status = "human_action_required"
        elif go_no_go == "PLANNER_BLOCKED":
            final_status = "blocked"

    payload = {
        "generated_at": end,
        "start_time": start,
        "end_time": end,
        "planner_status": final_status,
        "planner_go_no_go": go_no_go,
        "human_action_required": bool(human_required),
        "autonomous_mode_active": autonomous_mode_active,
        "no_execute_planned_tasks": bool(no_execute_planned_tasks),
        "next_planned_task": next_tasks[0] if next_tasks else None,
        "next_planned_tasks": next_tasks,
        "will_execute_automatically": bool(will_execute_automatically),
        "executed_tasks": executed_tasks,
        "decision_summary": decision_summary,
        "blocked_reason": blocked_reason,
        "input_packet_path": str(PLANNER_INPUT_PACKET_FILE),
        "planner_decision_path": str(PLANNER_DECISION_FILE),
        "planner_next_tasks_path": str(PLANNER_NEXT_TASKS_FILE),
        "planner_human_action_path": str(PLANNER_HUMAN_ACTION_FILE),
        "planner_go_no_go_path": str(PLANNER_GO_NO_GO_FILE),
    }
    write_planner_status(payload)
    append_event({
        "event": "planner_decision",
        "planner_status": final_status,
        "planner_go_no_go": go_no_go,
        "human_action_required": bool(human_required),
        "next_planned_task": payload.get("next_planned_task"),
        "will_execute_automatically": bool(will_execute_automatically),
        "executed_task_count": len(executed_tasks),
    })
    return payload


# ---------------------------------------------------------------------------
# Task discovery / queue
# ---------------------------------------------------------------------------


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
            items.append((p, load_task(p)))
        except Exception:
            continue
    return items


def dependency_blockers(task: Dict[str, Any], status_map: Dict[str, str]) -> List[str]:
    deps = [str(x) for x in task.get("depends_on", []) if str(x).strip()]
    deps.extend(str(x) for x in task.get("predecessor_task_ids", []) if str(x).strip())
    satisfied = {"completed", "superseded_by_evidence"}
    return [d for d in deps if status_map.get(d) not in satisfied]


def task_effective_status(task: Dict[str, Any]) -> str:
    """Prefer runtime state over task-definition status for scheduling decisions."""
    tid = str(task.get("task_id", "")).strip()
    definition_status = str(task.get("status", "pending"))
    if not tid:
        return definition_status
    state_status = str(load_task_state(tid).get("status", "")).strip()
    return state_status or definition_status


def task_status_map(tasks: List[Tuple[pathlib.Path, Dict[str, Any]]]) -> Dict[str, str]:
    return {
        str(t.get("task_id", "")): task_effective_status(t)
        for _, t in tasks
    }


def predecessor_marker_blockers(task: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    marker_pairs = [
        (
            str(task.get("predecessor_required_marker_file", "")).strip(),
            str(task.get("predecessor_required_marker", "")).strip(),
        ),
        (
            str(task.get("predecessor_codex_parallel_review_marker_file", "")).strip(),
            str(task.get("predecessor_codex_parallel_review_marker", "")).strip(),
        ),
    ]
    for marker_file, marker in marker_pairs:
        if not marker_file and not marker:
            continue
        if not marker_file or not marker:
            blockers.append(f"incomplete predecessor marker gate: {marker_file or marker}")
            continue
        marker_path = pathlib.Path(marker_file)
        if not marker_path.is_absolute():
            marker_path = WORKSPACE_ROOT / marker_path
        marker_path = marker_path.resolve()
        if not in_workspace(marker_path):
            blockers.append(f"predecessor marker file outside workspace: {marker_file}")
            continue
        if not marker_path.exists():
            blockers.append(f"predecessor marker file missing: {marker_file}")
            continue
        if marker not in read_text(marker_path):
            blockers.append(f"predecessor marker missing: {marker} in {marker_file}")
    return blockers


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


def task_no_event_timeout_seconds(task: Dict[str, Any]) -> int:
    try:
        val = int(task.get("no_event_timeout_seconds", 0))
        if val > 0:
            return val
    except Exception:
        pass
    return DEFAULT_NO_EVENT_TIMEOUT_S


def task_no_output_growth_timeout_seconds(task: Dict[str, Any]) -> int:
    try:
        val = int(task.get("no_output_growth_timeout_seconds", 0))
        if val > 0:
            return val
    except Exception:
        pass
    return DEFAULT_NO_OUTPUT_GROWTH_TIMEOUT_S


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
        for ln in (proc.stdout or "").splitlines():
            ln = ln.strip()
            if not ln or "pgrep -af" in ln:
                continue
            return True
        return False
    except Exception:
        return False


def task_last_output_growth_ts(summary_path: pathlib.Path, stdout_path: pathlib.Path, stderr_path: pathlib.Path) -> Optional[float]:
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


def task_last_event_ts_seconds(state: Dict[str, Any]) -> Optional[float]:
    parsed = parse_iso_utc(state.get("last_event_ts"))
    if parsed is None:
        return None
    return parsed.timestamp()


# ---------------------------------------------------------------------------
# Stale state classification
# ---------------------------------------------------------------------------


def classify_running_task_alerts(task: Dict[str, Any], task_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Pure inspection — does NOT mutate task state. Returns alert flags."""
    run_dir = RUNS_DIR / task_id
    summary_path = run_dir / "summary.json"
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"

    pid = state.get("run_pid") or task.get("run_pid")
    active = process_alive(pid) or has_active_process_for_task(task_id)

    timeout_s = task_timeout_seconds(task)
    no_event_s = task_no_event_timeout_seconds(task)
    no_output_s = task_no_output_growth_timeout_seconds(task)

    last_output_ts = task_last_output_growth_ts(summary_path, stdout_path, stderr_path)
    last_event_ts = task_last_event_ts_seconds(state)

    now = now_ts()
    output_idle = (now - last_output_ts) if last_output_ts is not None else None
    event_idle = (now - last_event_ts) if last_event_ts is not None else None

    alerts: List[str] = []
    if not active and (output_idle is None or output_idle > timeout_s):
        alerts.append("stale_running_no_process")
    if active and output_idle is not None and output_idle > no_output_s:
        alerts.append("no_output_growth")
    if active and event_idle is not None and event_idle > no_event_s:
        alerts.append("no_event")
    return {
        "task_id": task_id,
        "active_process": bool(active),
        "output_idle_seconds": int(output_idle) if output_idle is not None else None,
        "event_idle_seconds": int(event_idle) if event_idle is not None else None,
        "timeout_seconds": timeout_s,
        "no_event_timeout_seconds": no_event_s,
        "no_output_growth_timeout_seconds": no_output_s,
        "alerts": alerts,
    }


def stale_running_now(task: Dict[str, Any], task_id: str) -> bool:
    if str(task.get("status", "")) != "running":
        return False
    state = load_task_state(task_id)
    info = classify_running_task_alerts(task, task_id, state)
    if "stale_running_no_process" in info["alerts"]:
        if not check_required_outputs(task):
            return False
        return True
    return False


# ---------------------------------------------------------------------------
# Reconciler
# ---------------------------------------------------------------------------


def _decide_retry_or_attention(task: Dict[str, Any], reason: str) -> Tuple[str, str, Optional[str]]:
    """Return (status, summary, resume_after_utc_iso)."""
    max_attempts = int(task.get("max_attempts", 3))
    retry_count = int(task.get("retry_count", 0))
    if retry_count + 1 < max_attempts:
        resume = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat()
        return (
            "retry_scheduled",
            f"reconciled with retry {retry_count + 1}/{max_attempts}: {reason}",
            resume,
        )
    return (
        "human_attention_required",
        f"max_attempts {max_attempts} exhausted after reason: {reason}",
        None,
    )


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

        state = load_task_state(task_id)
        info = classify_running_task_alerts(task, task_id, state)
        active = info["active_process"]
        alerts = info["alerts"]

        required_missing = check_required_outputs(task)
        quota_blocked, reset_iso = detect_quota_block(agent, stdout_path, stderr_path)

        status: Optional[str] = None
        summary = ""
        reason = ""
        resume_iso: Optional[str] = None
        retry_count_increment = 0
        materialized: List[str] = []
        attention_reason: Optional[str] = None

        if not required_missing and not active:
            status = "completed"
            summary = "normalized stale-running task: required output files exist"
            reason = "required_outputs_present_no_active_process"
            materialized = [str(x) for x in task.get("required_output_files", []) if str(x).strip()]
        elif quota_blocked and not active:
            status = "blocked_quota"
            summary = f"{agent} blocked_quota detected during stale-running reconciliation"
            reason = "quota_detected"
            resume = parse_iso_utc(reset_iso)
            if resume is None:
                resume = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)
            resume_iso = resume.isoformat()
        elif "stale_running_no_process" in alerts:
            new_status, new_summary, new_resume = _decide_retry_or_attention(task, "stale_running_no_process")
            status = new_status
            summary = new_summary
            reason = "stale_running_no_process"
            resume_iso = new_resume
            retry_count_increment = 1 if new_status == "retry_scheduled" else 0
            if new_status == "human_attention_required":
                attention_reason = "max_attempts_exhausted_stale_running"
        elif "no_output_growth" in alerts or "no_event" in alerts:
            new_status, new_summary, new_resume = _decide_retry_or_attention(
                task, "no_output_growth" if "no_output_growth" in alerts else "no_event",
            )
            status = new_status
            summary = new_summary
            reason = "; ".join(alerts)
            resume_iso = new_resume
            retry_count_increment = 1 if new_status == "retry_scheduled" else 0
            if new_status == "human_attention_required":
                attention_reason = f"max_attempts_exhausted_{reason}"

        if not status:
            continue

        start_time = None
        last_run = state.get("last_run") or {}
        if isinstance(last_run, dict):
            start_time = last_run.get("start")

        end_time = now.isoformat()
        new_state_fields: Dict[str, Any] = {
            "status": status,
            "run_pid": None,
            "last_run": {"start": start_time, "end": end_time, "status": status},
            "last_summary": summary,
            "last_retry_reason": reason if status == "retry_scheduled" else state.get("last_retry_reason"),
            "attention_reason": attention_reason or (None if status != "human_attention_required" else state.get("attention_reason")),
            "resume_after_utc": resume_iso if resume_iso is not None else (None if status == "completed" else state.get("resume_after_utc")),
        }
        if retry_count_increment:
            new_state_fields["retry_count"] = int(task.get("retry_count", 0)) + retry_count_increment

        update_task_state(task_id, **new_state_fields)

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
            "next_recommended_action": "continue queue if completed; retry later if blocked_quota/retry_scheduled; human review if human_attention_required",
            "materialized_files": materialized,
            "run_pid": None,
        }
        write_json(summary_path, run_summary)
        write_json(CURRENT_STATUS_FILE, run_summary)
        append_event({
            "event": "stale_running_reconciled",
            **run_summary,
            "reason": reason,
            "alerts": alerts,
            "timeout_seconds": info["timeout_seconds"],
            "output_idle_seconds": info["output_idle_seconds"],
            "event_idle_seconds": info["event_idle_seconds"],
            "active_process": active,
        })
        set_next_tasks(task, success=status == "completed")
        reconciled += 1

    return reconciled


# ---------------------------------------------------------------------------
# Auto-commit
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Health, queue, gates
# ---------------------------------------------------------------------------


def derive_gate(tasks: List[Tuple[pathlib.Path, Dict[str, Any]]]) -> str:
    status_map = task_status_map(tasks)

    final_live_attention = [
        t for _, t in tasks
        if task_effective_status(t) == "human_attention_required" and task_requires_final_live_gate(t)
    ]
    if final_live_attention:
        return "BLOCKED_FINAL_LIVE_GATE"
    if status_map.get("010_actual_codex_architecture_rerun_after_remediation") == "running":
        return "CODEX_RERUN_RUNNING"
    if any(v == "blocked_quota" for v in status_map.values()):
        return "WAITING_FOR_CLAUDE_QUOTA"
    if any(v == "human_attention_required" for v in status_map.values()):
        return "NON_LIVE_DECISION_PACKETS_PRESENT_QUEUE_CONTINUES"
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


def task_priority(task: Dict[str, Any]) -> int:
    try:
        return int(task.get("priority", 0))
    except Exception:
        return 0


def should_defer_resume(task: Dict[str, Any]) -> bool:
    st = task_effective_status(task)
    if st not in {"blocked_quota", "retry_scheduled"}:
        return False
    resume = parse_iso_utc(task.get("resume_after_utc"))
    if resume is None:
        return False
    return dt.datetime.now(dt.timezone.utc) < resume


def write_health_and_queue(current: Dict[str, Any]) -> None:
    write_json(CURRENT_STATUS_FILE, current)

    tasks = list_tasks()
    status_map = task_status_map(tasks)
    counts = {
        "pending": 0, "running": 0, "completed": 0, "failed": 0, "blocked": 0,
        "retry_scheduled": 0, "skipped": 0, "cancelled": 0,
        "human_attention_required": 0, "superseded_by_evidence": 0,
        "waiting_decision_packet": 0, "delegated_decision_pending": 0,
    }
    next_pending = None
    running = None
    blocked_quota = None
    runnable_candidates: List[Tuple[int, str]] = []

    stale_running_tasks: List[str] = []
    no_event_tasks: List[str] = []
    no_output_growth_tasks: List[str] = []
    human_attention_tasks: List[Dict[str, Any]] = []
    final_live_gate_tasks: List[Dict[str, Any]] = []
    non_blocking_decision_packets: List[Dict[str, Any]] = []

    for _, t in tasks:
        tid = str(t.get("task_id", ""))
        st = task_effective_status(t)
        if st == "pending":
            counts["pending"] += 1
            if next_pending is None:
                next_pending = tid
        elif st == "running":
            counts["running"] += 1
            if running is None:
                running = tid
            state = load_task_state(tid)
            info = classify_running_task_alerts(t, tid, state)
            if "stale_running_no_process" in info["alerts"]:
                stale_running_tasks.append(tid)
            if "no_event" in info["alerts"]:
                no_event_tasks.append(tid)
            if "no_output_growth" in info["alerts"]:
                no_output_growth_tasks.append(tid)
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
        elif st == "human_attention_required":
            counts["human_attention_required"] += 1
            attention_row = {
                "task_id": tid,
                "agent": t.get("agent"),
                "attention_reason": t.get("attention_reason"),
                "last_summary": t.get("last_summary"),
            }
            human_attention_tasks.append(attention_row)
            if task_requires_final_live_gate(t):
                final_live_gate_tasks.append(attention_row)
            else:
                non_blocking_decision_packets.append(attention_row)
        elif st == "superseded_by_evidence":
            counts["superseded_by_evidence"] += 1
        elif st in {"waiting_decision_packet", "delegated_decision_pending"}:
            counts[st] += 1
            non_blocking_decision_packets.append({
                "task_id": tid,
                "agent": t.get("agent"),
                "attention_reason": t.get("attention_reason"),
                "last_summary": t.get("last_summary"),
            })

        if st in {"completed", "running", "cancelled", "failed",
                  "blocked_auth", "blocked_approval", "human_attention_required",
                  "waiting_decision_packet", "delegated_decision_pending",
                  "superseded_by_evidence"}:
            continue
        if should_defer_resume(t):
            continue
        blockers = dependency_blockers(t, status_map)
        blockers.extend(predecessor_marker_blockers(t))
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
        "stale_running_count": len(stale_running_tasks),
        "stale_running_tasks": stale_running_tasks,
        "no_event_count": len(no_event_tasks),
        "no_event_tasks": no_event_tasks,
        "no_output_growth_count": len(no_output_growth_tasks),
        "no_output_growth_tasks": no_output_growth_tasks,
        "human_attention_required_count": len(human_attention_tasks),
        "human_attention_required_tasks": human_attention_tasks,
        "final_live_gate_required_count": len(final_live_gate_tasks),
        "final_live_gate_required_tasks": final_live_gate_tasks,
        "non_blocking_decision_packet_count": len(non_blocking_decision_packets),
        "non_blocking_decision_packets": non_blocking_decision_packets,
        "human_attention_global_blocking": bool(final_live_gate_tasks),
        "manual_copilot_prompting_required": False,
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
        "last_auto_commit_hash": current.get("auto_commit", {}).get("commit_hash") if isinstance(current.get("auto_commit"), dict) else None,
        "supervisor_version": SUPERVISOR_VERSION,
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
            t = load_task(tf)
            if str(t.get("status", "")) in {"completed", "running"}:
                continue
            update_task_state(ntid, status="pending")
        except Exception:
            continue


def select_next_task_file() -> Optional[pathlib.Path]:
    tasks = list_tasks()
    status_map = task_status_map(tasks)
    candidates: List[Tuple[int, str, pathlib.Path]] = []

    for p, task in tasks:
        tid = str(task.get("task_id", p.stem))
        status = task_effective_status(task)

        if status == "completed":
            continue
        if status in {
            "cancelled", "failed", "blocked_auth", "blocked_approval",
            "human_attention_required", "superseded_by_evidence",
        }:
            continue
        if should_defer_resume(task):
            continue

        blockers = dependency_blockers(task, status_map)
        blockers.extend(predecessor_marker_blockers(task))
        if blockers:
            if status != "blocked_dependency":
                update_task_state(
                    tid,
                    status="blocked_dependency",
                    last_summary=f"waiting on dependencies: {', '.join(blockers)}",
                )
            continue
        if status == "blocked_dependency" and str(task.get("attention_reason", "")) == "manual_sequence_hold":
            continue
        if status == "blocked_dependency":
            update_task_state(tid, status="pending")

        candidates.append((-task_priority(task), tid, p))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


# ---------------------------------------------------------------------------
# Lockfile + heartbeat
# ---------------------------------------------------------------------------


def acquire_lock() -> Tuple[bool, str]:
    """Acquire supervisor lock. Refuses if a live daemon already holds it."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.exists():
        try:
            existing = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
            other_pid = int(existing.get("pid", 0) or 0)
            if other_pid and process_alive(other_pid) and other_pid != os.getpid():
                return False, f"duplicate daemon: existing pid={other_pid} acquired_at={existing.get('acquired_at')}"
        except Exception:
            pass
    payload = {
        "pid": os.getpid(),
        "acquired_at": now_iso(),
        "tmux_session": os.environ.get("TMUX_PANE") or os.environ.get("TMUX") or "",
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "version": SUPERVISOR_VERSION,
    }
    write_json(LOCK_FILE, payload)
    return True, "lock acquired"


def release_lock() -> None:
    try:
        if not LOCK_FILE.exists():
            return
        existing = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        if int(existing.get("pid", 0) or 0) == os.getpid():
            LOCK_FILE.unlink()
    except Exception:
        pass


def write_heartbeat(loop_count: int, current_task: Optional[str], started_at: str, last_event_ts: Optional[str]) -> None:
    payload = {
        "pid": os.getpid(),
        "tmux_session": os.environ.get("TMUX_PANE") or os.environ.get("TMUX") or "",
        "loop_count": loop_count,
        "last_loop_ts": now_iso(),
        "current_task": current_task,
        "last_event_ts": last_event_ts or now_iso(),
        "started_at": started_at,
        "version": SUPERVISOR_VERSION,
    }
    write_json(HEARTBEAT_FILE, payload)


# ---------------------------------------------------------------------------
# Run a single task
# ---------------------------------------------------------------------------


def run_task(task_path: pathlib.Path, dry_run: bool = False) -> Dict[str, Any]:
    task = load_task(task_path)
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
        "timed_out": False,
        "attention_reason": None,
        "last_retry_reason": None,
    }

    task_status = task_effective_status(task)
    if task_status == "superseded_by_evidence":
        marker = str(task.get("superseded_by_evidence", "")).strip()
        result["status"] = "superseded_by_evidence"
        result["summary"] = (
            "task not executed because committed evidence supersedes this task"
            + (f": {marker}" if marker else "")
        )
        result["next_recommended_action"] = "continue with latest evidence-backed task"
        append_event({
            "event": "task_execution_skipped_superseded_by_evidence",
            "task_id": task_id,
            "marker": marker,
        })
    else:
        validation_error = validate_task(task)
        if validation_error:
            result["status"] = "failed"
            result["summary"] = validation_error
            result["next_recommended_action"] = "fix task definition"
        else:
            approved, reason = task_approved_v2(task)
            if not approved:
                if task_requires_final_live_gate(task):
                    result["status"] = "human_attention_required"
                    result["attention_reason"] = "final_live_gate_required"
                    result["next_recommended_action"] = "operator final live/capital approval required"
                elif task_requires_non_live_decision_packet(task):
                    result["status"] = "waiting_decision_packet"
                    result["attention_reason"] = "non_live_decision_packet_created"
                    result["next_recommended_action"] = "continue unrelated safe V2 work; this subtask waits on a decision packet"
                else:
                    result["status"] = "blocked_approval"
                    result["next_recommended_action"] = "add approval and rerun"
                result["summary"] = reason
            else:
                status_map = task_status_map(list_tasks())
                blockers = dependency_blockers(task, status_map)
                blockers.extend(predecessor_marker_blockers(task))
                if blockers:
                    result["status"] = "blocked_dependency"
                    result["summary"] = f"waiting on dependencies: {', '.join(blockers)}"
                else:
                    existing_missing = check_required_outputs(task)
                    if not existing_missing and task_effective_status(task) == "completed":
                        result["status"] = "completed"
                        result["summary"] = "required outputs already exist"
                    elif dry_run:
                        result["status"] = "pending"
                        result["summary"] = "dry-run: task not executed"
                    else:
                        update_task_state(
                            task_id,
                            status="running",
                            last_run={"start": start, "end": None, "status": "running"},
                            run_pid=None,
                        )
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
                        timed_out = False

                        def _mark_run_pid(pid: int) -> None:
                            update_task_state(task_id, run_pid=pid)
                            running_status["run_pid"] = pid
                            write_json(summary_path, running_status)
                            write_health_and_queue(running_status)

                        if agent == "claude":
                            if not claude_ready():
                                result["status"] = "blocked_auth"
                                result["summary"] = "claude not ready"
                            else:
                                prompt = str(task.get("prompt", ""))
                                rc, run_pid, timed_out = run_cmd_with_pid(
                                    ["claude", "--print", prompt, "--output-format", "text"],
                                    cwd, stdout_path, stderr_path,
                                    timeout_seconds=hard_timeout_s, on_start=_mark_run_pid,
                                )
                                result["status"] = "completed" if rc == 0 else "failed"
                        elif agent == "codex":
                            if not codex_ready():
                                result["status"] = "blocked_auth"
                                result["summary"] = "codex not ready"
                            else:
                                prompt = str(task.get("prompt", ""))
                                rc, run_pid, timed_out = run_cmd_with_pid(
                                    ["codex", "exec", prompt],
                                    cwd, stdout_path, stderr_path,
                                    timeout_seconds=hard_timeout_s, on_start=_mark_run_pid,
                                )
                                result["status"] = "completed" if rc == 0 else "failed"
                        elif agent == "ollama":
                            model = str(task.get("model", "llama3"))
                            if not any(m == model for m in ollama_models()):
                                result["status"] = "blocked_dependency"
                                result["summary"] = f"ollama model missing: {model}"
                            else:
                                prompt = str(task.get("prompt", ""))
                                rc, run_pid, timed_out = run_cmd_with_pid(
                                    ["ollama", "run", model, prompt],
                                    cwd, stdout_path, stderr_path,
                                    timeout_seconds=hard_timeout_s, on_start=_mark_run_pid,
                                )
                                result["status"] = "completed" if rc == 0 else "failed"
                        elif agent == "system_check":
                            cmd = task.get("command")
                            if not cmd:
                                stdout_path.write_text("", encoding="utf-8")
                                stderr_path.write_text("missing command\n", encoding="utf-8")
                                result["status"] = "failed"
                            else:
                                rc, run_pid, timed_out = run_cmd_with_pid(
                                    ["bash", "-lc", str(cmd)],
                                    cwd, stdout_path, stderr_path,
                                    timeout_seconds=hard_timeout_s, on_start=_mark_run_pid,
                                )
                                result["status"] = "completed" if rc == 0 else "failed"

                        result["run_pid"] = run_pid
                        result["timed_out"] = timed_out

                        if timed_out and result["status"] == "failed":
                            result["summary"] = (
                                (result.get("summary") or "")
                                + f" subprocess hard timeout after {hard_timeout_s}s"
                            ).strip()
                            result["last_retry_reason"] = "subprocess_timeout"

                        if result["status"] == "failed":
                            classified_status, classifier_detail = classify_agent_block(agent, stdout_path, stderr_path)
                            if classified_status:
                                result["status"] = classified_status
                                result["summary"] = f"{agent} {classified_status} detected"
                                if classifier_detail == "prompt_permission_model_error":
                                    result["summary"] = "task prompt permission-model error: headless task attempted direct writes"
                                    result["last_retry_reason"] = "prompt_permission_model_error"
                                    result["attention_reason"] = "task_prompt_must_use_begin_file_emit_mode"
                                    append_event({
                                        "event": "task_prompt_permission_model_error",
                                        "task_id": task_id,
                                        "agent": agent,
                                    })
                                if classified_status == "blocked_quota":
                                    resume = parse_iso_utc(classifier_detail)
                                    if resume is None:
                                        resume = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)
                                    update_task_state(task_id, resume_after_utc=resume.isoformat())

                        emit_files = bool(task.get("emit_files", False))
                        if emit_files and agent in {"claude", "codex"} and result["status"] == "completed":
                            allowed_prefixes = [str(x) for x in task.get("allowed_output_prefixes", []) if str(x).strip()]
                            if not allowed_prefixes:
                                result["status"] = "failed"
                                result["summary"] = "emit_files=true but allowed_output_prefixes missing"
                            else:
                                required_outputs = [str(x) for x in task.get("required_output_files", []) if str(x).strip()]
                                task_risk = str(task.get("risk_level", "L0")).upper()
                                mat = materialize_emit_files(stdout_path, allowed_prefixes, required_outputs, task_risk)
                                result["materialized_files"] = mat.get("materialized_files", [])
                                errors = mat.get("errors", [])
                                if errors:
                                    result["status"] = "failed"
                                    result["summary"] = "; ".join(errors)

                                missing_required = check_required_outputs(task)
                                if missing_required:
                                    retry_mat = materialize_emit_files(stdout_path, allowed_prefixes, required_outputs, task_risk)
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
                                    result["last_retry_reason"] = "quota_reset_recovered"
                                    update_task_state(task_id, resume_after_utc=None)
                                else:
                                    update_task_state(
                                        task_id,
                                        resume_after_utc=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).isoformat(),
                                    )

                        max_attempts = int(task.get("max_attempts", 3))
                        retry_count = int(task.get("retry_count", 0))
                        if result["status"] == "failed" and result.get("last_retry_reason") != "prompt_permission_model_error":
                            if retry_count + 1 < max_attempts:
                                new_retry = retry_count + 1
                                update_task_state(
                                    task_id,
                                    retry_count=new_retry,
                                    resume_after_utc=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)).isoformat(),
                                    last_retry_reason=result.get("last_retry_reason") or "task_failed",
                                )
                                result["status"] = "retry_scheduled"
                                result["summary"] = (
                                    result.get("summary", "failed")
                                    + f"; retry {new_retry}/{max_attempts} scheduled"
                                )
                            else:
                                result["status"] = "human_attention_required"
                                result["attention_reason"] = (
                                    f"max_attempts {max_attempts} exhausted; last reason: "
                                    + (result.get("last_retry_reason") or "task_failed")
                                )
                                result["summary"] = (
                                    result.get("summary", "failed")
                                    + f"; max_attempts {max_attempts} exhausted -> human_attention_required"
                                )

    if not result["summary"]:
        result["summary"] = f"agent run status: {result['status']}"

    if result["status"] == "completed" and bool(task.get("auto_commit", False)) and not dry_run:
        result["auto_commit"]["attempted"] = True
        ok, msg, commit_hash = auto_commit_task_outputs(task_path, task, result)
        result["auto_commit"]["ok"] = ok
        result["auto_commit"]["message"] = msg
        result["auto_commit"]["commit_hash"] = commit_hash
        if not ok and "secret scan blocked" in msg:
            result["status"] = "human_attention_required"
            result["attention_reason"] = "secret_scan_blocked_auto_commit"
            result["summary"] = msg

    result["end_time"] = now_iso()

    update_fields: Dict[str, Any] = {
        "status": result["status"],
        "run_pid": None,
        "last_run": {"start": result["start_time"], "end": result["end_time"], "status": result["status"]},
        "last_summary": result["summary"],
    }
    if result.get("attention_reason"):
        update_fields["attention_reason"] = result["attention_reason"]
    if result.get("last_retry_reason"):
        update_fields["last_retry_reason"] = result["last_retry_reason"]
    update_task_state(task_id, **update_fields)

    write_json(summary_path, result)
    write_health_and_queue(result)
    append_event({"event": "task_completed", **result})
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
        state = load_task_state(task_id)
        if str(state.get("status", "")) != "completed":
            update_task_state(task_id, status="completed")


def dry_run_queue() -> Dict[str, Any]:
    nf = select_next_task_file()
    payload = {
        "generated_at": now_iso(),
        "next_task_file": str(nf) if nf else None,
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


# ---------------------------------------------------------------------------
# Daemon loop
# ---------------------------------------------------------------------------


def daemon_loop(poll_seconds: int, max_run_hours: Optional[float], stop_after_idle_minutes: Optional[float], dry_run: bool) -> int:
    ok, message = acquire_lock()
    if not ok:
        sys.stderr.write(f"[agent_supervisor] {message}\n")
        append_event({"event": "duplicate_daemon_blocked", "message": message})
        return 2

    started = dt.datetime.now(dt.timezone.utc)
    started_iso = started.isoformat()
    idle_started = started
    loop_count = 0
    last_event_ts = started_iso
    current_task: Optional[str] = None

    write_heartbeat(loop_count, current_task, started_iso, last_event_ts)
    migrate_legacy_task_files()
    reconcile_stale_running_tasks()

    try:
        while True:
            loop_count += 1
            now = dt.datetime.now(dt.timezone.utc)
            write_heartbeat(loop_count, current_task, started_iso, last_event_ts)

            if max_run_hours is not None and (now - started).total_seconds() >= max_run_hours * 3600:
                status = {
                    "task_id": None, "agent": None,
                    "start_time": now_iso(), "end_time": now_iso(),
                    "status": "cancelled",
                    "summary": "daemon max-run-hours reached",
                    "next_recommended_action": "restart daemon if needed",
                }
                write_health_and_queue(status)
                append_event({"event": "daemon_cancelled", **status})
                return 0

            reconcile_stale_running_tasks()

            task_file = select_next_task_file()
            if not task_file:
                status = {
                    "task_id": None, "agent": None,
                    "start_time": now_iso(), "end_time": now_iso(),
                    "status": "pending",
                    "summary": "no runnable task",
                    "next_recommended_action": "wait for dependencies/quota or add pending tasks",
                }
                write_health_and_queue(status)
                append_event({"event": "no_runnable_task", **status})
                last_event_ts = now_iso()
                if stop_after_idle_minutes is not None and (now - idle_started).total_seconds() >= stop_after_idle_minutes * 60:
                    return 0
                time.sleep(max(5, poll_seconds))
                continue

            idle_started = now
            try:
                td = load_task(task_file)
                current_task = str(td.get("task_id", task_file.stem))
            except Exception:
                current_task = task_file.stem
            write_heartbeat(loop_count, current_task, started_iso, last_event_ts)

            result = run_task(task_file, dry_run=dry_run)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            last_event_ts = now_iso()
            current_task = None
            time.sleep(max(2, poll_seconds))
    finally:
        release_lock()


def autonomous_daemon_loop(
    poll_seconds: int,
    max_run_hours: Optional[float],
    stop_after_idle_minutes: Optional[float],
    no_execute_planned_tasks: bool,
    promote_planner_output: bool = False,
) -> int:
    ok, message = acquire_lock()
    if not ok:
        sys.stderr.write(f"[agent_supervisor] {message}\n")
        append_event({"event": "duplicate_daemon_blocked", "message": message})
        return 2

    started = dt.datetime.now(dt.timezone.utc)
    started_iso = started.isoformat()
    idle_started = started
    loop_count = 0
    last_event_ts = started_iso

    write_heartbeat(loop_count, "planner", started_iso, last_event_ts)
    migrate_legacy_task_files()
    reconcile_stale_running_tasks()

    try:
        while True:
            loop_count += 1
            now = dt.datetime.now(dt.timezone.utc)
            write_heartbeat(loop_count, "planner", started_iso, last_event_ts)

            if max_run_hours is not None and (now - started).total_seconds() >= max_run_hours * 3600:
                append_event({
                    "event": "autonomous_daemon_cancelled",
                    "reason": "max_run_hours_reached",
                })
                return 0

            planner_payload = run_planner_once(
                no_execute_planned_tasks=no_execute_planned_tasks,
                autonomous_mode_active=True,
                promote_planner_output=promote_planner_output,
            )
            last_event_ts = now_iso()

            next_tasks = planner_payload.get("next_planned_tasks") or []
            if not next_tasks:
                if stop_after_idle_minutes is not None and (now - idle_started).total_seconds() >= stop_after_idle_minutes * 60:
                    return 0
            else:
                idle_started = now

            time.sleep(max(5, poll_seconds))
    finally:
        release_lock()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent Supervisor (reliability-hardened)")
    parser.add_argument("--task-id", help="Run a specific task_id from tasks directory")
    parser.add_argument("--daemon", action="store_true", help="Run autonomous queue manager loop")
    parser.add_argument("--planner-once", action="store_true", help="Run one autonomous planner cycle")
    parser.add_argument("--autonomous-daemon", action="store_true", help="Run autonomous planner daemon loop")
    parser.add_argument("--no-execute-planned-tasks", action="store_true", help="Plan only; do not auto-run planned tasks")
    parser.add_argument("--promote-planner-output", action="store_true", help="Write planner packet/output to tracked planner files")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--max-run-hours", type=float)
    parser.add_argument("--stop-after-idle-minutes", type=float)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reconcile", action="store_true", help="Run reconciler once and exit")
    parser.add_argument("--migrate", action="store_true", help="Migrate legacy task state and exit")
    args = parser.parse_args()

    ensure_dirs()
    moved = migrate_legacy_task_files()
    if args.migrate:
        print(json.dumps({"migrated_definition_files": moved}))
        return 0
    normalize_existing_completion()

    if args.reconcile:
        n = reconcile_stale_running_tasks()
        current = load_json(CURRENT_STATUS_FILE)
        if current:
            write_health_and_queue(current)
        print(json.dumps({"reconciled": n}))
        return 0

    if args.planner_once:
        payload = run_planner_once(
            no_execute_planned_tasks=bool(args.no_execute_planned_tasks),
            autonomous_mode_active=False,
            promote_planner_output=bool(args.promote_planner_output),
        )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.autonomous_daemon:
        return autonomous_daemon_loop(
            poll_seconds=max(5, args.poll_seconds),
            max_run_hours=args.max_run_hours,
            stop_after_idle_minutes=args.stop_after_idle_minutes,
            no_execute_planned_tasks=bool(args.no_execute_planned_tasks),
            promote_planner_output=bool(args.promote_planner_output),
        )

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
            "task_id": None, "agent": None,
            "start_time": now_iso(), "end_time": now_iso(),
            "status": "pending",
            "stdout_path": None, "stderr_path": None,
            "summary": "no runnable task",
            "next_recommended_action": "check dependency/quota/approval statuses",
        }
        write_health_and_queue(status)
        append_event({"event": "no_runnable_task", **status})
        print("No runnable task.")
        return 0

    result = run_task(task_file, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in {
        "completed", "skipped", "pending",
        "retry_scheduled", "blocked_dependency", "blocked_quota",
        "blocked_auth", "blocked_approval", "superseded_by_evidence",
    } else 1


if __name__ == "__main__":
    sys.exit(main())
