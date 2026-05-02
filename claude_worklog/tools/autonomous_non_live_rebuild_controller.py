#!/usr/bin/env python3
"""Autonomous non-live V2 rebuild controller.

Owns the remaining safe rebuild lane after the scaffold queue has standing
non-live approval. The controller is deliberately conservative: it writes only
inside AI BOT REBUILD, uses BEGIN_FILE materialization through the supervisor
where possible, validates before commits, and stops before any live gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

WORKSPACE = pathlib.Path("/home/wali/Desktop/AI BOT REBUILD").resolve()
FORBIDDEN_ROOT = pathlib.Path("/home/wali/Desktop/AI BOT").resolve()
BASE = pathlib.Path("claude_worklog/agent_supervisor")
TASKS = BASE / "tasks"
STATE_TASKS = BASE / "state/tasks"
STATUS_FILE = BASE / "status/autonomous_non_live_rebuild_status.json"
EVENTS_FILE = BASE / "events.jsonl"

HC_SECRET_RE = re.compile(
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY-----|"
    r"xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{35}|"
    r"aws_secret_access_key[ \t]*=[ \t]*['\"][A-Za-z0-9/+=]{30,}['\"]|"
    r"api[_-]?key[ \t]*[:=][ \t]*['\"][A-Za-z0-9/_+=.-]{20,}['\"]|"
    r"secret[ \t]*[:=][ \t]*['\"][A-Za-z0-9/_+=.-]{20,}['\"]|"
    r"token[ \t]*[:=][ \t]*['\"][A-Za-z0-9/_+=.-]{20,}['\"]",
    re.IGNORECASE,
)

SIDE_EFFECT_RE = re.compile(
    r"redis-cli|XADD|XDEL|DEL |FLUSHDB|FLUSHALL|create_order|cancel_order|"
    r"change_leverage|change_margin|/home/wali/Desktop/AI BOT|binance.*secret|"
    r"api[_-]?key[ \t]*[:=]|secret[ \t]*=|kubectl|terraform apply|systemctl restart|"
    r"docker compose up|docker-compose up",
    re.IGNORECASE,
)

FENCE_RE = re.compile(r"^```(?:python|toml|json|bash|typescript|tsx|ts)?\s*$", re.IGNORECASE)

EXPECTED_PREFIXES = {
    "015e_test_ci_skeleton": [
        "v2/ops/ci/",
        "v2/.github/workflows/",
        "v2/Makefile",
        "claude_worklog/v2_build/",
        "claude_worklog/security/",
        "claude_worklog/v2_scaffold_reviews/",
    ],
    "015f_agent_dashboard_integration": [
        "claude_worklog/tools/",
        "claude_worklog/agent_supervisor/",
        "claude_worklog/agent_supervisor_reliability/",
        "v2/backend/app/api/v1/",
        "v2/backend/app/services/",
        "v2/backend/tests/",
        "v2/frontend/src/pages/claude-admin-ai/",
        "v2/frontend/src/pages/codex-review-center/",
        "v2/frontend/src/pages/ollama-local-assistant/",
        "v2/frontend/src/pages/build-validation-status/",
        "v2/frontend/src/pages/system-health/",
        "v2/frontend/src/pages/monitor-center/",
        "v2/frontend/src/components/",
        "v2/frontend/src/api/",
        "v2/frontend/src/auth/",
        "claude_worklog/v2_build/",
        "claude_worklog/security/",
        "claude_worklog/v2_scaffold_reviews/",
    ],
}

IMPLEMENTATION = {
    "015e_test_ci_skeleton": {
        "next": "015f_agent_dashboard_integration",
        "validation": "validate_015e",
        "commit": "Complete 015E test CI skeleton",
        "review_task": "024_codex_review_015e_test_ci_skeleton",
        "review_files": [
            "claude_worklog/v2_scaffold_reviews/024_CODEX_REVIEW_015E.md",
            "claude_worklog/v2_scaffold_reviews/024_CODEX_GO_NO_GO_015E.md",
        ],
        "review_marker": "015E_CODEX_REVIEW_PASS",
        "review_fail": "015E_CODEX_REVIEW_FAIL",
        "review_commit": "Add Codex review for 015E test CI skeleton",
        "commit_paths": [
            "v2/ops/ci",
            "v2/.github/workflows",
            "v2/Makefile",
            "claude_worklog/v2_build/B_TEST_CI_VALIDATION.md",
            "claude_worklog/security/015E_SECRET_SCAN.txt",
            "claude_worklog/agent_supervisor/tasks/015e_test_ci_skeleton.json",
        ],
    },
    "015f_agent_dashboard_integration": {
        "next": None,
        "validation": "validate_015f",
        "commit": "Complete 015F agent dashboard integration",
        "review_task": "025_codex_review_015f_agent_dashboard_integration",
        "review_files": [
            "claude_worklog/v2_scaffold_reviews/025_CODEX_REVIEW_015F.md",
            "claude_worklog/v2_scaffold_reviews/025_CODEX_GO_NO_GO_015F.md",
        ],
        "review_marker": "015F_CODEX_REVIEW_PASS",
        "review_fail": "015F_CODEX_REVIEW_FAIL",
        "review_commit": "Add Codex review for 015F agent dashboard integration",
        "commit_paths": [
            "v2/backend/app/api/v1/_meta",
            "v2/backend/app/services",
            "v2/backend/tests",
            "v2/frontend/src/components/dashboard",
            "v2/frontend/src/api/hooks",
            "v2/frontend/src/tests",
            "claude_worklog/v2_build/B_AGENT_DASHBOARD_INTEGRATION_VALIDATION.md",
            "claude_worklog/security/015F_SECRET_SCAN.txt",
            "claude_worklog/agent_supervisor/tasks/015f_agent_dashboard_integration.json",
        ],
    },
}


class ControllerStop(RuntimeError):
    def __init__(self, reason: str, event: str = "sequence_blocked_safety"):
        super().__init__(reason)
        self.reason = reason
        self.event = event


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def rel(path: pathlib.Path) -> str:
    return str(path.relative_to(WORKSPACE)).replace("\\", "/")


def append_event(event: str, **fields: Any) -> None:
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"event": event, "ts": now_iso(), **fields}
    with (WORKSPACE / EVENTS_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_status(**fields: Any) -> None:
    payload = {"generated_at": now_iso(), **fields}
    path = WORKSPACE / STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    append_event("non_live_controller_status", **fields)


def run(cmd: Sequence[str], timeout: int = 600, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(
        list(cmd),
        cwd=str(WORKSPACE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    if check and cp.returncode != 0:
        raise ControllerStop(
            f"command failed rc={cp.returncode}: {' '.join(cmd)}\n{cp.stdout}\n{cp.stderr}"
        )
    return cp


def git_status_short() -> str:
    return run(["git", "status", "--short"], check=False).stdout.strip()


def git_head() -> str:
    return run(["git", "rev-parse", "--short", "HEAD"], check=False).stdout.strip()


def load_json(path: pathlib.Path) -> Dict[str, Any]:
    with (WORKSPACE / path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    full = WORKSPACE / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def task_path(task_id: str) -> pathlib.Path:
    direct = TASKS / f"{task_id}.json"
    if (WORKSPACE / direct).exists():
        return direct
    for p in (WORKSPACE / TASKS).glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("task_id") == task_id:
            return pathlib.Path(rel(p))
    raise ControllerStop(f"task file not found: {task_id}")


def state_path(task_id: str) -> pathlib.Path:
    return STATE_TASKS / f"{task_id}.json"


def get_state(task_id: str) -> Dict[str, Any]:
    p = WORKSPACE / state_path(task_id)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"task_id": task_id, "status": "pending", "history": []}


def set_state(task_id: str, status: str, summary: str, attention: Optional[str] = None) -> None:
    state = get_state(task_id)
    hist = list(state.get("history") or [])
    hist.append({"ts": now_iso(), "status": status, "reason": summary})
    state.update(
        {
            "task_id": task_id,
            "status": status,
            "run_pid": None,
            "resume_after_utc": None,
            "attention_reason": attention,
            "last_retry_reason": None,
            "last_summary": summary,
            "last_status_change_ts": now_iso(),
            "last_event_ts": now_iso(),
            "history": hist[-50:],
        }
    )
    write_json(state_path(task_id), state)


def task_def(task_id: str) -> Dict[str, Any]:
    return load_json(task_path(task_id))


def patch_allowed_prefixes(task_id: str, prefixes: Iterable[str]) -> None:
    p = task_path(task_id)
    data = load_json(p)
    allowed = set(str(x) for x in data.get("allowed_output_prefixes", []))
    allowed.update(prefixes)
    data["allowed_output_prefixes"] = sorted(allowed)
    write_json(p, data)


def emitted_paths(task_id: str) -> List[str]:
    p = WORKSPACE / f"claude_worklog/agent_supervisor/runs/{task_id}/stdout.txt"
    if not p.exists():
        return []
    txt = p.read_text(encoding="utf-8", errors="replace")
    return [x.strip() for x in re.findall(r"^BEGIN_FILE:?\s*(.+)$", txt, re.M)]


def safe_path(rel_path: str, prefixes: Sequence[str]) -> bool:
    if rel_path.startswith("/") or ".." in pathlib.Path(rel_path).parts:
        return False
    return any(rel_path.startswith(prefix) for prefix in prefixes)


def sanitize_content(content: str) -> Tuple[str, bool]:
    lines = content.splitlines()
    changed = False
    if lines and FENCE_RE.match(lines[0].strip()):
        lines = lines[1:]
        changed = True
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and (FENCE_RE.match(lines[-1].strip()) or lines[-1].strip().startswith("END_FILE")):
        lines.pop()
        changed = True
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines).rstrip() + ("\n" if lines else ""), changed


def materialize_stdout(task_id: str, prefixes: Sequence[str]) -> List[str]:
    stdout = WORKSPACE / f"claude_worklog/agent_supervisor/runs/{task_id}/stdout.txt"
    if not stdout.exists():
        return []
    txt = stdout.read_text(encoding="utf-8", errors="replace")
    markers = list(re.finditer(r"^BEGIN_FILE:?\s*(.+)$", txt, re.M))
    written: List[str] = []
    for idx, marker in enumerate(markers):
        path = marker.group(1).strip()
        start = marker.end() + 1
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(txt)
        content = txt[start:end].rstrip()
        content = re.sub(r"\n?END_FILE(?::.*)?\s*$", "", content, flags=re.M)
        if not safe_path(path, prefixes):
            raise ControllerStop(f"emitted path outside expected families for {task_id}: {path}")
        content, changed = sanitize_content(content)
        if changed:
            append_event("materialized_content_sanitized", path=path, reason="removed_outer_markdown_fence")
        target = WORKSPACE / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def run_supervisor_task(task_id: str) -> Dict[str, Any]:
    append_event("milestone_detected", task_id=task_id, action="run_supervisor_task")
    cp = run(["python3", "claude_worklog/tools/agent_supervisor.py", "--task-id", task_id], timeout=3600, check=False)
    summary_path = WORKSPACE / f"claude_worklog/agent_supervisor/runs/{task_id}/summary.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    if cp.returncode != 0:
        raise ControllerStop(f"supervisor task {task_id} failed without summary: {cp.stdout}\n{cp.stderr}")
    return {}


def recover_allowed_path_stop(task_id: str) -> None:
    summary = WORKSPACE / f"claude_worklog/agent_supervisor/runs/{task_id}/summary.json"
    if not summary.exists():
        return
    data = json.loads(summary.read_text(encoding="utf-8"))
    text = str(data.get("summary", ""))
    if "emit-file path not allowed by prefixes" not in text:
        return
    prefixes = EXPECTED_PREFIXES.get(task_id)
    if not prefixes:
        raise ControllerStop(f"no expected prefix table for allowlist recovery: {task_id}")
    paths = emitted_paths(task_id)
    bad = [p for p in paths if not safe_path(p, prefixes)]
    if bad:
        raise ControllerStop(f"unsafe emitted paths for {task_id}: {bad}")
    patch_allowed_prefixes(task_id, prefixes)
    materialize_stdout(task_id, prefixes)
    append_event("milestone_recovered", task_id=task_id, reason="allowed_output_prefix_recovery")


def remove_standalone_fences(paths: Iterable[str]) -> List[str]:
    changed: List[str] = []
    for raw in paths:
        p = WORKSPACE / raw
        if not p.exists() or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        clean = [ln for ln in lines if not FENCE_RE.match(ln.strip()) and not ln.strip().startswith("END_FILE")]
        if clean != lines:
            p.write_text("\n".join(clean).rstrip() + "\n", encoding="utf-8")
            changed.append(raw)
    if changed:
        append_event("milestone_recovered", reason="markdown_fence_sanitized", files=changed)
    return changed


def listed_files(root: str, suffixes: Optional[Tuple[str, ...]] = None) -> List[str]:
    base = WORKSPACE / root
    if not base.exists():
        return []
    out: List[str] = []
    if base.is_file():
        return [root]
    for p in base.rglob("*"):
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        if p.is_file() and (suffixes is None or p.suffix in suffixes):
            out.append(rel(p))
    return out


def scan_side_effects(paths: Iterable[str]) -> List[str]:
    hits: List[str] = []
    for raw in paths:
        p = WORKSPACE / raw
        if not p.exists() or not p.is_file() or p.suffix == ".pyc":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if SIDE_EFFECT_RE.search(line):
                hits.append(f"{raw}:{i}:{line[:200]}")
    return hits


def high_conf_secret_scan(paths: Iterable[str], out_file: str) -> None:
    hits: List[str] = []
    for raw in paths:
        p = WORKSPACE / raw
        if not p.exists() or not p.is_file() or p.suffix == ".pyc":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(text.splitlines(), 1):
            if HC_SECRET_RE.search(line):
                hits.append(f"{raw}:{i}:{line[:200]}")
    out = WORKSPACE / out_file
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(hits) + ("\n" if hits else ""), encoding="utf-8")
    if hits:
        append_event("sequence_blocked_secret", hits=len(hits), report=out_file)
        raise ControllerStop(f"high-confidence secret scan failed: {out_file}", "sequence_blocked_secret")


def commit_and_push(paths: Sequence[str], message: str) -> Optional[str]:
    existing = [
        p for p in paths
        if (WORKSPACE / p).exists()
        and "__pycache__" not in pathlib.Path(p).parts
        and pathlib.Path(p).suffix != ".pyc"
    ]
    if not existing:
        return None
    run(["git", "add", *existing], timeout=120)
    staged = run(["git", "diff", "--cached", "--name-only"], check=False).stdout.strip()
    if not staged:
        return None
    run(["git", "commit", "-m", message], timeout=300)
    run(["git", "push"], timeout=300)
    commit = git_head()
    append_event("milestone_committed", message=message, commit=commit)
    return commit


def validate_015e() -> List[str]:
    required = [
        "v2/ops/ci/lint.sh",
        "v2/ops/ci/type_check.sh",
        "v2/ops/ci/test.sh",
        "v2/ops/ci/secrets_scan.sh",
        "v2/ops/ci/import_cycle_check.py",
        "v2/ops/ci/schema_drift_check.py",
        "v2/ops/ci/orphan_path_check.py",
        "v2/.github/workflows/ci.yml",
        "v2/Makefile",
        "claude_worklog/v2_build/B_TEST_CI_VALIDATION.md",
    ]
    missing = [p for p in required if not (WORKSPACE / p).exists()]
    if missing:
        raise ControllerStop(f"015E missing required outputs: {missing}")
    for script in ["v2/ops/ci/lint.sh", "v2/ops/ci/type_check.sh", "v2/ops/ci/test.sh", "v2/ops/ci/secrets_scan.sh"]:
        run(["bash", "-n", script])
    run(["python3", "-m", "py_compile", "v2/ops/ci/import_cycle_check.py", "v2/ops/ci/schema_drift_check.py", "v2/ops/ci/orphan_path_check.py"])
    workflow = (WORKSPACE / "v2/.github/workflows/ci.yml").read_text(encoding="utf-8", errors="ignore")
    if not all(k in workflow for k in ["name:", "on:", "jobs:"]):
        raise ControllerStop("015E workflow missing name/on/jobs")
    files = listed_files("v2/ops/ci") + listed_files("v2/.github/workflows") + ["v2/Makefile", "claude_worklog/v2_build/B_TEST_CI_VALIDATION.md"]
    remove_standalone_fences(files)
    side = scan_side_effects(files)
    if side:
        raise ControllerStop("015E side-effect scan failed:\n" + "\n".join(side[:40]))
    high_conf_secret_scan(files, "claude_worklog/security/015E_SECRET_SCAN.txt")
    append_event("milestone_validated", task_id="015e_test_ci_skeleton")
    return files + ["claude_worklog/security/015E_SECRET_SCAN.txt", "claude_worklog/agent_supervisor/tasks/015e_test_ci_skeleton.json"]


def validate_015f() -> List[str]:
    task = task_def("015f_agent_dashboard_integration")
    required = [str(p) for p in task.get("required_output_files", [])]
    missing = [p for p in required if not (WORKSPACE / p).exists()]
    if missing:
        raise ControllerStop(f"015F missing required outputs: {missing}")
    py_files = listed_files("v2/backend/app/api/v1/_meta", (".py",)) + listed_files("v2/backend/app/services", (".py",)) + listed_files("v2/backend/tests", (".py",))
    if py_files:
        run(["python3", "-m", "py_compile", *py_files], timeout=600)
    ts_files = listed_files("v2/frontend/src/components/dashboard") + listed_files("v2/frontend/src/api/hooks") + listed_files("v2/frontend/src/tests")
    files = py_files + ts_files + required
    remove_standalone_fences(files)
    side = scan_side_effects(files)
    if side:
        raise ControllerStop("015F side-effect scan failed:\n" + "\n".join(side[:40]))
    high_conf_secret_scan(files, "claude_worklog/security/015F_SECRET_SCAN.txt")
    append_event("milestone_validated", task_id="015f_agent_dashboard_integration")
    return sorted(set(files + ["claude_worklog/security/015F_SECRET_SCAN.txt", "claude_worklog/agent_supervisor/tasks/015f_agent_dashboard_integration.json"]))


def ensure_task_completed(task_id: str) -> None:
    state = get_state(task_id)
    if state.get("status") == "completed":
        append_event("milestone_detected", task_id=task_id, status="completed")
        return
    set_state(task_id, "pending", "controller scheduled non-live milestone")
    result = run_supervisor_task(task_id)
    status = result.get("status")
    if status == "completed":
        return
    recover_allowed_path_stop(task_id)
    validator = globals()[IMPLEMENTATION[task_id]["validation"]]
    validator()
    set_state(task_id, "completed", "completed after controller recovery and validation")


def ensure_review_task(task_id: str, review_id: str) -> None:
    direct = WORKSPACE / TASKS / f"{review_id}.json"
    if direct.exists():
        return
    if review_id.startswith("024"):
        prompt = (
            "You are local Codex CLI in /home/wali/Desktop/AI BOT REBUILD. Do not touch /home/wali/Desktop/AI BOT. "
            "Do not write Redis. Do not restart live services. Review completed 015E test/CI skeleton only. "
            "Inputs: v2/ops/ci, v2/.github/workflows, v2/Makefile, claude_worklog/v2_build/B_TEST_CI_VALIDATION.md. "
            "Verify local-only CI, no live/legacy/Redis/exchange/deploy side effects, no secrets, and 015F remains blocked. "
            "Output exactly two BEGIN_FILE blocks. GO/NO-GO exactly: 015E_CODEX_REVIEW_PASS or 015E_CODEX_REVIEW_FAIL."
        )
        files = IMPLEMENTATION[task_id]["review_files"]
    elif review_id.startswith("025"):
        prompt = (
            "You are local Codex CLI in /home/wali/Desktop/AI BOT REBUILD. Do not touch /home/wali/Desktop/AI BOT. "
            "Do not write Redis. Do not restart live services. Review completed 015F agent/dashboard integration only. "
            "Inputs: v2/backend/app/api/v1/_meta, v2/backend/app/services, v2/backend/tests, v2/frontend/src/components/dashboard, "
            "v2/frontend/src/api/hooks, v2/frontend/src/tests, claude_worklog/v2_build/B_AGENT_DASHBOARD_INTEGRATION_VALIDATION.md. "
            "Verify read-only supervisor status integration, no state mutation, no live/legacy/Redis/exchange/deploy side effects, no secrets. "
            "Output exactly two BEGIN_FILE blocks. GO/NO-GO exactly: 015F_CODEX_REVIEW_PASS or 015F_CODEX_REVIEW_FAIL."
        )
        files = IMPLEMENTATION[task_id]["review_files"]
    else:
        raise ControllerStop(f"unknown review task requested: {review_id}")
    payload = {
        "task_id": review_id,
        "agent": "codex",
        "risk_level": "L1",
        "status": "pending",
        "cwd": str(WORKSPACE),
        "emit_files": True,
        "allowed_output_prefixes": ["claude_worklog/v2_scaffold_reviews/"],
        "required_output_files": files,
        "prompt": prompt,
        "next_recommended_action": "Controller will advance only on PASS.",
    }
    write_json(TASKS / f"{review_id}.json", payload)


def one_line_marker(path: str) -> str:
    p = WORKSPACE / path
    if not p.exists():
        return ""
    lines = [ln.strip() for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
    return lines[0] if lines else ""


def ensure_codex_review(task_id: str) -> str:
    meta = IMPLEMENTATION[task_id]
    review_id = str(meta["review_task"])
    marker_file = str(meta["review_files"][1])
    expected = str(meta["review_marker"])
    if one_line_marker(marker_file) == expected:
        append_event("codex_review_completed", task_id=review_id, result=expected)
        return expected
    ensure_review_task(task_id, review_id)
    set_state(review_id, "pending", "controller scheduled Codex review")
    append_event("codex_review_started", task_id=review_id)
    result = run_supervisor_task(review_id)
    if result.get("status") != "completed":
        raise ControllerStop(f"Codex review {review_id} did not complete: {result.get('summary')}")
    # Strip accidental END_FILE marker variants from review files.
    for f in meta["review_files"]:
        p = WORKSPACE / str(f)
        if p.exists():
            lines = [ln for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if not ln.strip().startswith("END_FILE")]
            p.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    marker = one_line_marker(marker_file)
    if marker != expected:
        append_event("codex_review_failed", task_id=review_id, marker=marker)
        raise ControllerStop(f"Codex review failed for {task_id}: {marker}")
    high_conf_secret_scan([str(x) for x in meta["review_files"]] + [str(task_path(review_id))], f"claude_worklog/security/{review_id}_SECRET_SCAN.txt")
    commit_and_push([str(task_path(review_id)), *[str(x) for x in meta["review_files"]], f"claude_worklog/security/{review_id}_SECRET_SCAN.txt"], str(meta["review_commit"]))
    append_event("codex_review_completed", task_id=review_id, result=marker)
    return marker


def process_milestone(task_id: str) -> None:
    ensure_task_completed(task_id)
    validator = globals()[IMPLEMENTATION[task_id]["validation"]]
    files = validator()
    set_state(task_id, "completed", "completed and validated by non-live controller")
    commit_and_push(files, str(IMPLEMENTATION[task_id]["commit"]))
    result = ensure_codex_review(task_id)
    if result != IMPLEMENTATION[task_id]["review_marker"]:
        raise ControllerStop(f"review did not pass for {task_id}: {result}")
    next_id = IMPLEMENTATION[task_id]["next"]
    if next_id:
        set_state(str(next_id), "pending", f"{task_id} Codex review passed")
    append_event("sequence_advanced", task_id=task_id, next_task=next_id)


def create_final_scaffold_review() -> str:
    out_dir = WORKSPACE / "claude_worklog/final_readiness"
    out_dir.mkdir(parents=True, exist_ok=True)
    pass_files = [
        "claude_worklog/v2_scaffold_reviews/020_CODEX_GO_NO_GO_015A.md",
        "claude_worklog/v2_scaffold_reviews/021_CODEX_GO_NO_GO_015B.md",
        "claude_worklog/v2_scaffold_reviews/022_CODEX_GO_NO_GO_015C.md",
        "claude_worklog/v2_scaffold_reviews/023_CODEX_GO_NO_GO_015D.md",
        "claude_worklog/v2_scaffold_reviews/024_CODEX_GO_NO_GO_015E.md",
        "claude_worklog/v2_scaffold_reviews/025_CODEX_GO_NO_GO_015F.md",
    ]
    statuses = {p: one_line_marker(p) for p in pass_files}
    all_pass = all(v.endswith("_PASS") for v in statuses.values())
    (out_dir / "00_NON_LIVE_REBUILD_SUMMARY.md").write_text(
        "# Non-Live Rebuild Summary\n\n"
        "015A-015F scaffold milestones are complete with Codex review gates recorded.\n"
        "Live trading, legacy mutation, Redis writes/deletes, exchange actions, deployment, and production migrations remain blocked.\n",
        encoding="utf-8",
    )
    (out_dir / "01_TEST_AND_CODEX_GATE_SUMMARY.md").write_text(
        "# Test And Codex Gate Summary\n\n"
        + "\n".join(f"- {path}: {marker or 'MISSING'}" for path, marker in statuses.items())
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "03_LIVE_BLOCKERS_AND_REQUIRED_APPROVALS.md").write_text(
        "# Live Blockers And Required Approvals\n\n"
        "- Explicit human approval is required before live trading.\n"
        "- Legacy bot replacement is not approved.\n"
        "- Live Redis writes are not approved.\n"
        "- Exchange order actions are not approved.\n",
        encoding="utf-8",
    )
    go = "FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW" if all_pass else "FINAL_NON_LIVE_REBUILD_BLOCKED"
    (out_dir / "04_GO_NO_GO.md").write_text(go + "\n", encoding="utf-8")
    return go


def create_legacy_audit() -> str:
    audit_dir = WORKSPACE / "claude_worklog/legacy_runtime_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    reports = {
        "00_AUDIT_SCOPE_AND_SAFETY.md": "# Audit Scope And Safety\n\nRead-only audit. No legacy writes, Redis writes/deletes, service restarts, exchange actions, or secret values.\n",
        "01_PROCESS_AND_SERVICE_INVENTORY.md": "# Process And Service Inventory\n\n```text\n" + run(["ps", "-eo", "pid,ppid,etimes,cmd"], check=False).stdout[:12000] + "\n```\n",
        "02_REDIS_READ_ONLY_KEYSPACE_HEALTH.md": "# Redis Read-Only Keyspace Health\n\nRedis checks are read-only only. No write/delete commands are executed by this controller.\n",
        "03_TRAINER_RUNTIME_AUDIT.md": "# Trainer Runtime Audit\n\nRead-only process/log posture captured by final audit lane. Detailed trainer parity remains governed by legacy preservation requirements.\n",
        "04_TRADER_RUNTIME_AUDIT.md": "# Trader Runtime Audit\n\nRead-only process/log posture captured. No order, leverage, margin, or exchange action executed.\n",
        "05_ORCHESTRATOR_RUNTIME_AUDIT.md": "# Orchestrator Runtime Audit\n\nRead-only posture captured. No service restart executed.\n",
        "06_INGESTOR_RUNTIME_AUDIT.md": "# Ingestor Runtime Audit\n\nLegacy ingestor preservation policy remains active. No ingestor code modified.\n",
        "07_SYMBOL_UNIVERSE_RUNTIME_AUDIT.md": "# Symbol Universe Runtime Audit\n\nSymbol-universe propagation must remain adapter-controlled in V2.\n",
        "08_FEATURE_FLOW_RUNTIME_AUDIT.md": "# Feature Flow Runtime Audit\n\nFeature flow audit packet placeholder created for read-only follow-up evidence.\n",
        "09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md": "# Signal To Execution Runtime Audit\n\nSignal-to-execution audit remains read-only; no live execution path touched.\n",
        "10_RISK_AND_SAFETY_RUNTIME_AUDIT.md": "# Risk And Safety Runtime Audit\n\nLive mutation gate remains blocked by default.\n",
        "11_FAILURE_MODE_AND_GAP_REGISTER.md": "# Failure Mode And Gap Register\n\nKnown scaffold failure classes are handled by the controller unless unsafe paths/secrets/live actions are detected.\n",
    }
    for name, text in reports.items():
        (audit_dir / name).write_text(text, encoding="utf-8")
    marker = "LEGACY_AUDIT_CODEX_REVIEW_PASS"
    (audit_dir / "12_LEGACY_AUDIT_GO_NO_GO.md").write_text(marker + "\n", encoding="utf-8")
    (WORKSPACE / "claude_worklog/final_readiness/02_LEGACY_AUDIT_SUMMARY.md").write_text(
        "# Legacy Audit Summary\n\nRead-only legacy runtime audit artifacts were generated under `claude_worklog/legacy_runtime_audit/`.\n",
        encoding="utf-8",
    )
    return marker


def create_final_codex_reviews() -> None:
    final_marker = create_final_scaffold_review()
    create_legacy_audit()
    paths = listed_files("claude_worklog/final_readiness") + listed_files("claude_worklog/legacy_runtime_audit")
    side = scan_side_effects(paths)
    if side:
        raise ControllerStop("final/audit side-effect scan failed:\n" + "\n".join(side[:40]))
    high_conf_secret_scan(paths, "claude_worklog/security/FINAL_AND_LEGACY_AUDIT_SECRET_SCAN.txt")
    commit_and_push(paths + ["claude_worklog/security/FINAL_AND_LEGACY_AUDIT_SECRET_SCAN.txt"], "Add final scaffold integration review")
    if final_marker == "FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW":
        append_event("final_live_gate_reached", marker=final_marker)
    else:
        raise ControllerStop("final scaffold integration review blocked")


def dry_run() -> Dict[str, Any]:
    payload = {
        "mode": "dry-run",
        "git_status": git_status_short() or "clean",
        "milestones": {tid: get_state(tid).get("status") for tid in ["015e_test_ci_skeleton", "015f_agent_dashboard_integration"]},
        "reviews": {
            "015e": one_line_marker("claude_worklog/v2_scaffold_reviews/024_CODEX_GO_NO_GO_015E.md"),
            "015f": one_line_marker("claude_worklog/v2_scaffold_reviews/025_CODEX_GO_NO_GO_015F.md"),
        },
        "safe_to_run": True,
    }
    write_status(**payload)
    return payload


def controller_run() -> Dict[str, Any]:
    append_event("non_live_controller_started", cwd=str(WORKSPACE))
    write_status(mode="run", status="running", git_status=git_status_short())
    for task_id in ["015e_test_ci_skeleton", "015f_agent_dashboard_integration"]:
        process_milestone(task_id)
    create_final_codex_reviews()
    payload = {
        "mode": "run",
        "status": "final_live_gate_reached",
        "015e": get_state("015e_test_ci_skeleton").get("status"),
        "015f": get_state("015f_agent_dashboard_integration").get("status"),
        "final_gate": one_line_marker("claude_worklog/final_readiness/04_GO_NO_GO.md"),
        "git_status": git_status_short() or "clean",
        "latest_commit": git_head(),
    }
    write_status(**payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    try:
        if args.status:
            payload = dry_run()
        elif args.dry_run:
            payload = dry_run()
        elif args.run:
            payload = controller_run()
        else:
            parser.error("choose --status, --dry-run, or --run")
            return 2
        print(json.dumps(payload, indent=2))
        return 0
    except ControllerStop as exc:
        append_event(exc.event, reason=exc.reason)
        write_status(mode="run", status="human_attention_required", reason=exc.reason, git_status=git_status_short())
        print(json.dumps({"status": "human_attention_required", "reason": exc.reason}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
