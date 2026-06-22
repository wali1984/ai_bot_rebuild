"""Compatibility wrapper for autonomous mission burndown.

The Spark CLI remains the entrypoint, but this module restores the legacy
file-backed burndown contract that existing tests and operator artifacts still
depend on.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import v2_autonomous_mission_backlog_autoseed as autoseed
import v2_burndown_fail_to_remediation_mapper as fail_mapper
import v2_closed_loop_worker_pool as worker_pool
from v2.backend.app.closed_loop.services.burndown import main as _spark_main

__all__ = [
    "BLOCKED_MARKER",
    "READY_MARKER",
    "autoseed",
    "main",
    "run_once",
    "utc_iso",
    "worker_pool",
]

READY_MARKER = "V2_AUTONOMOUS_MISSION_EXECUTION_BURNDOWN_READY"
BLOCKED_MARKER = "V2_AUTONOMOUS_MISSION_EXECUTION_BURNDOWN_BLOCKED"
REPORT_INDEX_PATH = (
    REPO_ROOT / "v2" / "frontend" / "public" / "v2_report_center" / "latest" / "report_index.json"
)
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
CODEx_OUTPUTS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_execution"
    / "latest"
    / "codex_review_outputs"
)
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_mission_execution_burndown"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_mission_execution_burndown"
    / "latest"
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mirror_payload(name: str, payload: dict[str, Any]) -> None:
    _write_json(WORKLOG_DIR / name, payload)
    _write_json(PUBLIC_DIR / name, payload)


def _iso_to_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _within_last_hour(value: Any) -> bool:
    ts = _iso_to_ts(value)
    if ts is None:
        return False
    return (time.time() - ts) <= 3600


def _load_lanes() -> list[dict[str, Any]]:
    lanes = _read_json(REPORT_INDEX_PATH).get("lanes")
    return lanes if isinstance(lanes, list) else []


def _blocked_lanes(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for lane in lanes:
        status = str(lane.get("status") or "")
        if status not in {"BLOCKED", "FAIL"}:
            continue
        out.append(
            {
                "report_id": str(lane.get("report_id") or ""),
                "operator_gated": False,
                "external_event_position_dependent": False,
            }
        )
    return out


def _operator_required_count(lanes: list[dict[str, Any]]) -> int:
    count = 0
    for lane in lanes:
        status = str(lane.get("status") or "")
        marker = str(lane.get("go_no_go") or "").upper()
        if status == "OPERATOR_DECISION_REQUIRED" or "OPERATOR_REQUIRED" in marker:
            count += 1
    return count


def _task_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(TASKS_DIR.glob("*.json")):
        payload = _read_json(path)
        if payload:
            payload["_path"] = str(path)
            records.append(payload)
    return records


def _mission_categories_moved(tasks: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for task in tasks:
        raw_categories = task.get("mission_categories") or []
        if isinstance(raw_categories, str):
            raw_categories = [raw_categories]
        if task.get("task_type") != "CLAUDE_IMPLEMENTATION" or task.get("status") != "completed":
            continue
        if not _within_last_hour(task.get("completed_at")):
            continue
        if task.get("report_only_work") or task.get("ui_only_work"):
            continue
        for category in raw_categories:
            bucket = counts.setdefault(str(category), {"completed_implementation_count": 0})
            bucket["completed_implementation_count"] += 1
    return counts


def _codex_review_verdicts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not CODEx_OUTPUTS_DIR.exists():
        return rows
    for path in sorted(CODEx_OUTPUTS_DIR.glob("*/CODEX_GO_NO_GO.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        task_id = path.parent.name
        task = _read_json(TASKS_DIR / f"{task_id}.json")
        remediation_path = TASKS_DIR / f"closed_loop_remediation_{task_id}.json"
        rows.append(
            {
                "task_id": task_id,
                "path": str(path.relative_to(REPO_ROOT)),
                "verdict": text.strip(),
                "fail_blockers": task.get("fail_blockers") or [],
                "next_action": task.get("next_action"),
                "existing_remediation_descriptor_path": (
                    str(remediation_path.relative_to(REPO_ROOT)) if remediation_path.exists() else None
                ),
            }
        )
    return rows


def run_once(*, autoseed_followup: bool = True) -> dict[str, Any]:
    lanes = _load_lanes()
    blockers_after_rows = _blocked_lanes(lanes)
    previous = _read_json(WORKLOG_DIR / "mission_execution_burndown_status.json")
    blocker_count_before = len(
        (((previous.get("blocker_burndown_matrix") or {}).get("blockers_after")) or blockers_after_rows)
    )
    blocker_count_after = len(blockers_after_rows)
    task_rows = _task_records()
    tasks_completed_last_hour = sum(
        1 for task in task_rows if task.get("status") in {"completed", "failed"} and _within_last_hour(task.get("completed_at"))
    )
    implementation_tasks_completed_last_hour = sum(
        1
        for task in task_rows
        if task.get("task_type") == "CLAUDE_IMPLEMENTATION"
        and task.get("status") == "completed"
        and _within_last_hour(task.get("completed_at"))
        and not task.get("report_only_work")
        and not task.get("ui_only_work")
    )
    report_only_completed = any(
        task.get("task_type") == "CLAUDE_IMPLEMENTATION"
        and task.get("status") == "completed"
        and _within_last_hour(task.get("completed_at"))
        and (task.get("report_only_work") or task.get("ui_only_work"))
        for task in task_rows
    )
    mission_categories_moved = _mission_categories_moved(task_rows)
    verdict_rows = _codex_review_verdicts()
    codex_pass_count = sum(1 for row in verdict_rows if "CODEX_PASS" in row["verdict"])
    codex_fail_inputs = [row for row in verdict_rows if "CODEX_FAIL" in row["verdict"]]
    codex_fail_mapping = [fail_mapper.classify_codex_fail(verdict=row) for row in codex_fail_inputs]
    any_unmapped = any(row.get("terminal_classification") is None for row in codex_fail_mapping)

    operator_required_count = _operator_required_count(lanes)
    is_flat = blocker_count_before == blocker_count_after
    reason_code = "BLOCKER_COUNT_DECREASED_PROGRESS"
    ready_allowed = implementation_tasks_completed_last_hour > 0 and not any_unmapped
    if blocker_count_after == 0 and operator_required_count > 0:
        reason_code = "ALL_REMAINING_BLOCKERS_OPERATOR_REQUIRED"
    elif is_flat and any_unmapped:
        reason_code = "BLOCKER_UNCHANGED_DUE_CODEX_FAIL"
        ready_allowed = False
    elif is_flat and implementation_tasks_completed_last_hour > 0:
        reason_code = "IMPLEMENTATION_COMPLETED_AWAITING_CODEX_REVIEW"
    elif is_flat:
        reason_code = "NO_MEASURABLE_BURNDOWN_THIS_CYCLE_BLOCKED"
        ready_allowed = False

    blockers: list[str] = []
    if implementation_tasks_completed_last_hour == 0:
        blockers.append("NO_IMPLEMENTATION_TASK_COMPLETED_LAST_HOUR")
    if any_unmapped:
        blockers.append("CODEX_FAIL_WITHOUT_TERMINAL_CLASSIFICATION")
    go_no_go = READY_MARKER if ready_allowed and not blockers else BLOCKED_MARKER

    pool_status = worker_pool.run_pool_once()
    autoseed_result = (
        autoseed.seed_tasks(target_current_queue=3, max_new_implementation_tasks=3)
        if autoseed_followup
        else {"invoked": False}
    )
    payload = {
        "schema_version": "v2_autonomous_mission_execution_burndown_v1",
        "generated_utc": utc_iso(),
        "go_no_go": go_no_go,
        "blockers": blockers,
        "tasks_completed_last_hour": tasks_completed_last_hour,
        "implementation_tasks_completed_last_hour": implementation_tasks_completed_last_hour,
        "task_completion_last_hour": {
            "report_only_or_control_artifacts_completed_last_hour": report_only_completed,
        },
        "mission_categories_moved": mission_categories_moved,
        "not_counted_as_progress": {
            "report_center_refresh": report_only_completed,
        },
        "Codex_PASS_count_last_hour": codex_pass_count,
        "Codex_FAIL_count_last_hour": len(codex_fail_inputs),
        "codex_fail_to_remediation_map": {
            "mapping": codex_fail_mapping,
            "any_unmapped": any_unmapped,
        },
        "blocker_count_before": blocker_count_before,
        "blocker_count_after": blocker_count_after,
        "flat_blocker_count_reason": {
            "is_flat": is_flat,
            "reason_code": reason_code,
            "ready_allowed": ready_allowed and implementation_tasks_completed_last_hour > 0,
        },
        "blocker_burndown_matrix": {
            "blockers_before": previous.get("blocker_burndown_matrix", {}).get("blockers_after")
            or blockers_after_rows,
            "blockers_after": blockers_after_rows,
        },
        "worker_pool_status": pool_status,
        "autoseed_result": autoseed_result,
    }
    _mirror_payload("mission_execution_burndown_status.json", payload)
    _mirror_payload("operator_dashboard_payload.json", payload)
    return payload


def main(argv: list[str] | None = None) -> int:  # noqa: D401
    """Entry point: strip legacy flags then delegate to Spark burndown."""
    if argv is None:
        argv = sys.argv[1:]

    legacy = argparse.ArgumentParser(add_help=False)
    legacy.add_argument("--json", action="store_true", default=False)
    _legacy_ns, remaining = legacy.parse_known_args(argv)

    return _spark_main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
