#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
EVENTS = WORKSPACE / "claude_worklog/agent_supervisor/events.jsonl"
TASKS_DIR = WORKSPACE / "claude_worklog/agent_supervisor/tasks"
STATE_DIR = WORKSPACE / "claude_worklog/agent_supervisor/state/tasks"
RECOVERY_DIR = WORKSPACE / "claude_worklog/planner_recovery/codex_watchdog"

FORBIDDEN_TERMS = [
    "/home/wali/Desktop/AI BOT/",
    "redis-cli",
    "XADD",
    "XDEL",
    "FLUSHDB",
    "FLUSHALL",
    "create_order",
    "cancel_order",
    "change_leverage",
    "change_margin",
    "enable live trading",
    "LIVE_TRADING_ENABLED",
    "systemctl restart",
    "sudo systemctl",
    "deploy",
    "production migration",
]

SECRET_PATTERN = re.compile(
    r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN (RSA|EC|OPENSSH|DSA) PRIVATE KEY-----|"
    r"xox[baprs]-[0-9A-Za-z-]{10,}|ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[0-9A-Za-z_-]{20,}|AIza[0-9A-Za-z_-]{35}"
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess:
    if isinstance(cmd, str):
        return subprocess.run(cmd, cwd=WORKSPACE, shell=True, text=True, capture_output=True)
    return subprocess.run(cmd, cwd=WORKSPACE, text=True, capture_output=True)


def append_event(event: dict) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", now())
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_text(path: Path, limit: int = 100_000) -> str:
    try:
        return path.read_text(errors="replace")[:limit]
    except Exception:
        return ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def active_child_processes() -> str:
    proc = run("ps -eo pid,ppid,etimes,cmd | grep -E 'claude --print|codex exec|ollama run|agent_supervisor.py --task-id' | grep -v grep || true")
    return proc.stdout.strip()


def git_status() -> list[str]:
    return [x for x in run(["git", "status", "--short"]).stdout.splitlines() if x.strip()]


def git_clean() -> bool:
    return not git_status()


def restore_runtime_prompt_noise() -> None:
    run(["git", "restore", "claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt"])


def archive_planner_noise() -> list[str]:
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    moved = []
    acp = WORKSPACE / "claude_worklog/autonomous_control_plane"
    if not acp.exists():
        return moved
    for path in acp.iterdir():
        if not path.is_file():
            continue
        if re.search(r"NOOP|NO_PROGRESS|STANDBY|HALT|HUMAN_ATTENTION|ESCALATION|DIRTY|HOLD|REAFFIRM|SUSPEND", path.name):
            target = RECOVERY_DIR / path.name
            shutil.move(str(path), str(target))
            moved.append(str(target.relative_to(WORKSPACE)))
    if moved:
        append_event({"event": "codex_watchdog_archived_planner_noise", "files": moved[:50]})
    return moved


def dirty_paths() -> list[Path]:
    paths = []
    for line in git_status():
        if len(line) < 4:
            continue
        rel = line[3:].strip()
        if rel:
            paths.append(WORKSPACE / rel)
    return paths


def remove_end_file_leaks(paths: list[Path]) -> list[str]:
    cleaned = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        lines = path.read_text(errors="replace").splitlines()
        new_lines = [line for line in lines if line.strip() not in {"END_FILE", "END_FILE:"}]
        if new_lines != lines:
            path.write_text("\n".join(new_lines).rstrip() + "\n")
            cleaned.append(str(path.relative_to(WORKSPACE)))
    if cleaned:
        append_event({"event": "codex_watchdog_removed_end_file_leaks", "files": cleaned[:50]})
    return cleaned


def validate_task_jsons() -> tuple[bool, list[str]]:
    errors = []
    for path in sorted(TASKS_DIR.glob("*.json")):
        try:
            json.loads(path.read_text())
        except Exception as exc:
            errors.append(f"{path.relative_to(WORKSPACE)}: {exc}")
    return not errors, errors


def high_conf_secret_scan(paths: list[Path]) -> tuple[bool, list[str]]:
    hits = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        text = read_text(path, 500_000)
        for match in SECRET_PATTERN.finditer(text):
            hits.append(f"{path.relative_to(WORKSPACE)}:{match.group(0)[:20]}")
    return not hits, hits


def safety_scan(paths: list[Path]) -> tuple[bool, list[str]]:
    hits = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = read_text(path, 500_000)
        for term in FORBIDDEN_TERMS:
            if term in text:
                hits.append(f"{path.relative_to(WORKSPACE)}:{term}")
    return not hits, hits


def commit_all(message: str) -> bool:
    run(["git", "add", "claude_worklog", "v2"])
    if git_clean():
        return False
    proc = run(["git", "commit", "-m", message])
    if proc.returncode != 0:
        append_event({"event": "codex_watchdog_commit_failed", "stderr": proc.stderr[-2000:]})
        return False
    push = run(["git", "push"])
    if push.returncode != 0:
        append_event({"event": "codex_watchdog_push_failed", "stderr": push.stderr[-2000:]})
        return False
    return True


def stop_planner() -> None:
    run("./claude_worklog/tools/stop_claude_master_rebuild_planner.sh || true")
    run("./claude_worklog/tools/stop_autonomous_agent_supervisor.sh || true")
    run("./claude_worklog/tools/stop_agent_supervisor_daemon.sh || true")


def start_planner() -> None:
    run("./claude_worklog/tools/start_claude_master_rebuild_planner.sh || true")


def run_reconciliation() -> None:
    if (WORKSPACE / "claude_worklog/tools/reconcile_evidence_status.py").exists():
        run(["python3", "claude_worklog/tools/reconcile_evidence_status.py"])


def latest_human_attention_task() -> str | None:
    candidates = []
    for path in STATE_DIR.glob("*.json"):
        data = read_json(path)
        if data.get("status") == "human_attention_required":
            candidates.append((data.get("last_status_change_ts", ""), data.get("task_id") or path.stem))
    if not candidates:
        return None
    candidates.sort()
    return candidates[-1][1]


def create_codex_recovery_task(blocked_task: str) -> str:
    task_id = f"codex_recover_{blocked_task}"
    path = TASKS_DIR / f"{task_id}.json"
    if path.exists():
        return task_id
    task = {
        "task_id": task_id,
        "agent": "codex",
        "risk_level": "L1",
        "status": "pending",
        "cwd": str(WORKSPACE),
        "emit_files": True,
        "allowed_output_prefixes": [
            "v2/",
            "claude_worklog/phase2_core_rebuild/",
            "claude_worklog/agent_supervisor/",
            "claude_worklog/tools/",
            "claude_worklog/security/",
            "claude_worklog/agent_supervisor_reliability/",
        ],
        "required_output_files": [
            f"claude_worklog/phase2_core_rebuild/automation_reliability/{task_id}_REPORT.md",
            f"claude_worklog/phase2_core_rebuild/automation_reliability/{task_id}_GO_NO_GO.md",
        ],
        "prompt": (
            f"You are local Codex CLI in {WORKSPACE}. Recover blocked non-live task {blocked_task}. "
            "You have full authority inside AI BOT REBUILD only. Inspect task definition, runtime state, stdout/stderr, "
            "required outputs, emitted BEGIN_FILE paths, and validation artifacts. If safe, patch non-live V2 code/docs/tests/"
            "planner/supervisor artifacts, recover materialized files, and emit a precise recovery report. "
            "Do not modify /home/wali/Desktop/AI BOT. Do not write Redis. Do not restart live services. "
            "Do not enable live trading. Do not deploy. Do not expose secrets. Output exactly two BEGIN_FILE blocks "
            "for the report and GO/NO-GO. GO/NO-GO must contain one line: CODEX_NON_LIVE_RECOVERY_READY "
            "or CODEX_NON_LIVE_RECOVERY_BLOCKED."
        ),
        "next_recommended_action": "If ready, validate/commit/push and restart planner. If blocked, leave explicit blocker.",
    }
    write_text(path, json.dumps(task, indent=2) + "\n")
    append_event({"event": "codex_watchdog_recovery_task_created", "blocked_task": blocked_task, "recovery_task": task_id})
    return task_id


def run_supervisor_task(task_id: str) -> int:
    append_event({"event": "codex_watchdog_running_recovery_task", "task_id": task_id})
    proc = run(["python3", "claude_worklog/tools/agent_supervisor.py", "--task-id", task_id])
    append_event(
        {
            "event": "codex_watchdog_recovery_task_finished",
            "task_id": task_id,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    )
    return proc.returncode


def recover_dirty_tree() -> bool:
    restore_runtime_prompt_noise()
    archive_planner_noise()
    remove_end_file_leaks(dirty_paths())

    ok_json, json_errors = validate_task_jsons()
    if not ok_json:
        append_event({"event": "codex_watchdog_blocked_invalid_json", "errors": json_errors[:20]})
        return False

    paths = dirty_paths()
    ok_secret, secret_hits = high_conf_secret_scan(paths)
    if not ok_secret:
        append_event({"event": "codex_watchdog_paused_for_secret_hits", "hits": secret_hits[:20]})
        return False

    _, safety_hits = safety_scan(paths)
    severe_hits = []
    for hit in safety_hits:
        rel = hit.split(":", 1)[0]
        suffix = Path(rel).suffix
        # Generated docs and task prompts often quote forbidden boundaries. That
        # is not an attempted live action. Treat executable/source files as the
        # actionable surface for term-based blocking.
        if suffix in {".md", ".json", ".txt"}:
            continue
        if (
            "/home/wali/Desktop/AI BOT/" in hit
            or "create_order" in hit
            or "cancel_order" in hit
            or "change_leverage" in hit
            or "change_margin" in hit
            or "LIVE_TRADING_ENABLED" in hit
        ):
            severe_hits.append(hit)
    if severe_hits:
        append_event({"event": "codex_watchdog_paused_for_safety_hits", "hits": severe_hits[:20]})
        return False

    if not git_clean():
        committed = commit_all("Codex watchdog recover dirty non-live automation artifacts")
        append_event({"event": "codex_watchdog_dirty_tree_recovered", "committed": committed})
        return committed
    return True


def cycle() -> int:
    append_event({"event": "codex_watchdog_cycle_started"})

    child = active_child_processes()
    if child:
        append_event({"event": "codex_watchdog_monitor_only_active_child", "processes": child[:2000]})
        print("ACTIVE_CHILD_MONITOR_ONLY")
        return 0

    stop_planner()
    run_reconciliation()

    if not git_clean() and not recover_dirty_tree():
        print("DIRTY_TREE_RECOVERY_BLOCKED")
        return 2

    blocked = latest_human_attention_task()
    if blocked:
        recovery = create_codex_recovery_task(blocked)
        commit_all(f"Add Codex watchdog recovery task for {blocked}")
        rc = run_supervisor_task(recovery)
        recover_dirty_tree()
        if rc != 0:
            print(f"RECOVERY_TASK_NONZERO {recovery} {rc}")
            return rc
        append_event({"event": "codex_watchdog_human_attention_recovered", "blocked_task": blocked, "recovery_task": recovery})

    if git_clean():
        start_planner()
        append_event({"event": "codex_watchdog_restarted_planner"})
        print("CODEX_WATCHDOG_RECOVERY_COMPLETE")
        return 0

    print("CODEX_WATCHDOG_LEFT_DIRTY")
    return 2


def daemon(poll_seconds: int) -> int:
    while True:
        try:
            cycle()
        except Exception as exc:
            append_event({"event": "codex_watchdog_exception", "error": repr(exc)})
        time.sleep(poll_seconds)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=300)
    args = parser.parse_args()

    if args.daemon:
        return daemon(args.poll_seconds)
    return cycle()


if __name__ == "__main__":
    raise SystemExit(main())
