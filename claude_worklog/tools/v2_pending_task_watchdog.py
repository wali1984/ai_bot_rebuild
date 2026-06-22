"""V2 Pending-Task Watchdog.

Scans ``claude_worklog/agent_supervisor/tasks/`` and emits a status
payload describing pending and stale Claude / Codex tasks. Performs
**safe** annotations only: it never deletes or re-dispatches tasks
without an explicit ``--allow-redispatch`` flag, and even with that
flag it will only update the descriptor's ``status`` field to
``pending_redispatch`` and bump a ``last_dispatch_attempt_utc``
timestamp. Actual re-dispatch is the supervisor's job.

The watchdog is read-only with respect to legacy code, Redis, and any
exchange endpoint. It writes only JSON status under the autonomous
self-healing latest/ directories and per-task ``last_dispatch_attempt_utc``
annotations on the supervisor task descriptors it touches.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)

STALE_AGE_SECONDS_DEFAULT = 5 * 60  # 5 minutes per the prompt.


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _payload_age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None


def _is_claude_fix(name: str) -> bool:
    return bool(re.match(r"^\d+_claude_fix_", name))


def _is_codex_review(name: str) -> bool:
    return bool(
        re.match(r"^\d+_codex_review_", name)
        or name.startswith("codex_review_")
        or name.startswith("codex_takeover_")
    )


def _field_group_from_name(name: str) -> str | None:
    m = re.match(r"^\d+_(?:claude_fix|codex_review)_v2_full_observation_(.+)\.json$", name)
    return m.group(1) if m else None


def _scan_tasks(stale_seconds: int) -> dict[str, Any]:
    pending_claude: list[dict[str, Any]] = []
    pending_codex: list[dict[str, Any]] = []
    if not TASKS_DIR.exists():
        return {"pending_claude": pending_claude, "pending_codex": pending_codex}
    by_field_group: dict[str, list[str]] = {}
    for f in sorted(TASKS_DIR.iterdir()):
        if not f.name.endswith(".json"):
            continue
        d = _read_json(f)
        if not isinstance(d, dict):
            continue
        status = d.get("status")
        if status not in ("pending", "in_progress", "pending_redispatch"):
            continue
        age = _payload_age_seconds(f)
        entry = {
            "path": str(f.relative_to(REPO_ROOT)),
            "task_id": d.get("task_id"),
            "status": status,
            "age_seconds": age,
            "stale": (age is not None and age > stale_seconds),
            "last_dispatch_attempt_utc": d.get("last_dispatch_attempt_utc"),
            "dispatch_attempt_count": int(d.get("dispatch_attempt_count") or 0),
        }
        group = _field_group_from_name(f.name)
        if group:
            by_field_group.setdefault(group, []).append(f.name)
            entry["field_group"] = group
        if _is_claude_fix(f.name):
            pending_claude.append(entry)
        elif _is_codex_review(f.name):
            pending_codex.append(entry)
    return {
        "pending_claude": pending_claude,
        "pending_codex": pending_codex,
        "field_group_duplicates": {g: v for g, v in by_field_group.items() if len(v) > 1},
    }


def _annotate_redispatch(task_path: Path) -> dict[str, Any]:
    """Annotate the descriptor with a re-dispatch hint. SAFE: does NOT
    delete, does NOT restart the agent — the supervisor decides.
    Bumps ``dispatch_attempt_count`` and sets ``status`` to
    ``pending_redispatch`` so the supervisor sees the signal.
    """
    d = _read_json(task_path) or {}
    if not isinstance(d, dict):
        return {"changed": False, "reason": "unreadable"}
    if d.get("status") not in ("pending", "in_progress", "pending_redispatch"):
        return {"changed": False, "reason": f"status={d.get('status')}"}
    attempt = int(d.get("dispatch_attempt_count") or 0) + 1
    d["status"] = "pending_redispatch"
    d["dispatch_attempt_count"] = attempt
    d["last_dispatch_attempt_utc"] = _utc_iso()
    task_path.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Escalation: if we already tried twice (now bumping to 3+), suggest
    # operator handover. The watchdog never actually escalates by itself;
    # it just leaves a breadcrumb in the descriptor.
    if attempt >= 3:
        d["escalation_recommendation"] = "OPERATOR_REVIEW_REQUIRED_AFTER_REPEATED_STALL"
        task_path.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"changed": True, "attempt": attempt}


def run(stale_seconds: int, allow_redispatch: bool) -> dict[str, Any]:
    state = _scan_tasks(stale_seconds)
    stale_claude = [t for t in state["pending_claude"] if t["stale"]]
    stale_codex = [t for t in state["pending_codex"] if t["stale"]]
    actions: list[dict[str, Any]] = []
    if allow_redispatch:
        for entries in (stale_claude, stale_codex):
            for t in entries:
                p = REPO_ROOT / t["path"]
                annotated = _annotate_redispatch(p)
                actions.append({"path": t["path"], "result": annotated})
    return {
        "schema_version": "v2_autonomous_full_rebuild_self_healing_pending_task_watchdog_v1",
        "generated_utc": _utc_iso(),
        "stale_seconds_threshold": stale_seconds,
        "pending_claude_count": len(state["pending_claude"]),
        "pending_codex_count": len(state["pending_codex"]),
        "stale_claude_count": len(stale_claude),
        "stale_codex_count": len(stale_codex),
        "field_group_duplicates": state.get("field_group_duplicates", {}),
        "stale_claude_tasks": stale_claude,
        "stale_codex_tasks": stale_codex,
        "actions": actions,
        "allow_redispatch": allow_redispatch,
        "safety": {
            "did_not_touch_legacy": True,
            "did_not_write_redis": True,
            "did_not_call_exchange": True,
            "did_not_delete_tasks": True,
            "did_not_restart_agent": True,
        },
    }


def write_artifacts(state: dict[str, Any]) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    (WORKLOG_DIR / "pending_task_watchdog_status.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (PUBLIC_DIR / "pending_task_watchdog_status.json").write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stale-seconds", type=int, default=STALE_AGE_SECONDS_DEFAULT)
    p.add_argument(
        "--allow-redispatch",
        action="store_true",
        help="annotate stale descriptors with status=pending_redispatch; the supervisor performs actual re-dispatch.",
    )
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    state = run(args.stale_seconds, args.allow_redispatch)
    write_artifacts(state)
    if args.json:
        print(json.dumps(state, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "generated_utc": state["generated_utc"],
            "pending_claude_count": state["pending_claude_count"],
            "pending_codex_count": state["pending_codex_count"],
            "stale_claude_count": state["stale_claude_count"],
            "stale_codex_count": state["stale_codex_count"],
            "actions_taken": len(state["actions"]),
        }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
