"""Compatibility wrapper for autonomous mission autoseed.

This wrapper keeps the legacy file-backed autoseed API that existing closed-loop
tests and operators still use. The Spark CLI remains the process entrypoint, but
``seed_tasks`` and ``promote_dependency_ready_codex_reviews`` are restored so
older orchestration can continue to work during cutover.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import v2_current_work_filter as current_work_filter
from v2.backend.app.closed_loop.services.autoseed import (
    main as _spark_main,
    run_once,
)

__all__ = [
    "main",
    "promote_dependency_ready_codex_reviews",
    "run_once",
    "seed_tasks",
]

REPORT_INDEX_PATH = (
    REPO_ROOT / "v2" / "frontend" / "public" / "v2_report_center" / "latest" / "report_index.json"
)
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_mission_backlog_autoseed"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_mission_backlog_autoseed"
    / "latest"
)

SAFETY = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "writes_old_redis": False,
    "calls_exchange_mutation": False,
}

DEFAULT_TASK_BLUEPRINTS = (
    {
        "slug": "paper_fill_gate_block_reason_recording",
        "title": "Paper fill gate block reason recording",
        "mission_categories": ["paper edge"],
        "file_lock_group": "paper_fill_gate_block_reason_recording",
    },
    {
        "slug": "observation_gap_feature_source_burndown",
        "title": "Observation gap feature source burndown",
        "mission_categories": ["observation completeness"],
        "file_lock_group": "observation_gap_feature_source_burndown",
    },
    {
        "slug": "altdata_replay_bundle_snapshot_attachment",
        "title": "Altdata replay bundle snapshot attachment",
        "mission_categories": ["runtime stability"],
        "file_lock_group": "altdata_replay_bundle_snapshot_attachment",
    },
)


def _utc_iso() -> str:
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


def _mirror_payload(name: str, payload: dict[str, Any], *, install_outputs: bool) -> None:
    if not install_outputs:
        return
    _write_json(WORKLOG_DIR / name, payload)
    _write_json(PUBLIC_DIR / name, payload)


def _load_report_lanes() -> list[dict[str, Any]]:
    lanes = _read_json(REPORT_INDEX_PATH).get("lanes")
    return lanes if isinstance(lanes, list) else []


def _inventory(lanes: list[dict[str, Any]]) -> dict[str, int]:
    operator_required = 0
    unsafe = 0
    automatable = 0
    for lane in lanes:
        status = str(lane.get("status") or "")
        marker = str(lane.get("go_no_go") or "").upper()
        title = str(lane.get("title") or "").upper()
        report_id = str(lane.get("report_id") or "").upper()
        if status == "OPERATOR_DECISION_REQUIRED" or "OPERATOR_REQUIRED" in marker:
            operator_required += 1
            continue
        if "LIVE_CANARY" in marker or "LIVE_CANARY" in report_id or "LIVE CANARY" in title:
            unsafe += 1
            continue
        if status == "BLOCKED":
            automatable += 1
    return {
        "operator_required_blocker_count": operator_required,
        "unsafe_blocker_count": unsafe,
        "automatable_blocker_count": automatable,
    }


def _blueprints_for_lanes(lanes: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    for lane in lanes:
        marker = str(lane.get("go_no_go") or "")
        if marker == "CODEX_24H_PARALLEL_RECOVERY_WAR_ROOM_GOVERNOR_BLOCKED":
            return DEFAULT_TASK_BLUEPRINTS
    return DEFAULT_TASK_BLUEPRINTS


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _build_task_descriptor(
    *,
    task_id: str,
    task_role: str,
    title: str,
    mission_categories: list[str],
    file_lock_group: str,
    depends_on_task_id: str | None = None,
    paired_task_id: str | None = None,
) -> dict[str, Any]:
    task_type = "CLAUDE_IMPLEMENTATION" if task_role == "implementation" else "CODEX_REVIEW"
    status = "pending" if task_role == "implementation" else "blocked_dependency"
    return {
        "task_id": task_id,
        "task_type": task_type,
        "task_role": task_role,
        "title": title,
        "status": status,
        "created_at": _utc_iso(),
        "updated_at": _utc_iso(),
        "current_active": True,
        "mission_categories": mission_categories,
        "file_lock_group": file_lock_group,
        "depends_on": [depends_on_task_id] if depends_on_task_id else [],
        "depends_on_task_id": depends_on_task_id,
        "paired_task_id": paired_task_id,
        "codex_pair_task_id": depends_on_task_id if task_role == "codex_review" else None,
        "report_only_work": False,
        "ui_only_work": False,
        "safety": dict(SAFETY),
        "safe_envelope": dict(SAFETY),
        "writes_old_redis": False,
        "calls_exchange_mutation": False,
        "approves_live": False,
    }


def seed_tasks(
    *,
    target_current_queue: int = 3,
    max_new_implementation_tasks: int = 3,
) -> dict[str, Any]:
    lanes = _load_report_lanes()
    inventory = _inventory(lanes)
    automatable_blockers_exist = inventory["automatable_blocker_count"] > 0
    result: dict[str, Any] = {
        "mission_incomplete": bool(lanes),
        "automatable_blockers_exist": automatable_blockers_exist,
        "inventory": inventory,
        "generated_tasks": [],
        "duplicate_suppressed": [],
        "refused": [],
        "target_current_queue": target_current_queue,
        "max_new_implementation_tasks": max_new_implementation_tasks,
    }
    if not automatable_blockers_exist:
        return result

    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    blueprints = _blueprints_for_lanes(lanes)[:max_new_implementation_tasks]
    for index, blueprint in enumerate(blueprints, start=1):
        impl_id = f"claude_autoseed_{blueprint['slug']}_r{index}"
        review_id = f"codex_review_{impl_id}"
        impl_path = _task_path(impl_id)
        review_path = _task_path(review_id)
        if impl_path.exists() or review_path.exists():
            result["duplicate_suppressed"].append(
                {
                    "implementation_task_id": impl_id,
                    "codex_review_task_id": review_id,
                }
            )
            continue

        impl = _build_task_descriptor(
            task_id=impl_id,
            task_role="implementation",
            title=str(blueprint["title"]),
            mission_categories=list(blueprint["mission_categories"]),
            file_lock_group=str(blueprint["file_lock_group"]),
            paired_task_id=review_id,
        )
        review = _build_task_descriptor(
            task_id=review_id,
            task_role="codex_review",
            title=f"Codex review for {impl_id}",
            mission_categories=list(blueprint["mission_categories"]),
            file_lock_group=str(blueprint["file_lock_group"]),
            depends_on_task_id=impl_id,
            paired_task_id=impl_id,
        )
        _write_json(impl_path, impl)
        _write_json(review_path, review)
        result["generated_tasks"].extend(
            [
                {
                    "task_id": impl_id,
                    "path": _relative(impl_path),
                    "task_role": "implementation",
                    "mission_categories": list(blueprint["mission_categories"]),
                    "file_lock_group": str(blueprint["file_lock_group"]),
                },
                {
                    "task_id": review_id,
                    "path": _relative(review_path),
                    "task_role": "codex_review",
                    "mission_categories": list(blueprint["mission_categories"]),
                    "file_lock_group": str(blueprint["file_lock_group"]),
                },
            ]
        )
    return result


def promote_dependency_ready_codex_reviews() -> list[dict[str, Any]]:
    promoted: list[dict[str, Any]] = []
    for path in sorted(TASKS_DIR.glob("*.json")):
        payload = _read_json(path)
        if payload.get("task_type") != "CODEX_REVIEW" or payload.get("status") != "blocked_dependency":
            continue
        dependency_id = str(payload.get("depends_on_task_id") or "")
        if not dependency_id:
            continue
        dependency = _read_json(_task_path(dependency_id))
        if dependency.get("status") != "completed":
            continue
        payload["status"] = "pending"
        payload["updated_at"] = _utc_iso()
        _write_json(path, payload)
        promoted.append({"task_id": str(payload.get("task_id") or path.stem), "path": _relative(path)})
    return promoted


def run_once(
    *,
    wait_seconds: int = 0,
    install_outputs: bool = True,
    max_new_tasks: int = 3,
) -> dict[str, Any]:
    _ = wait_seconds
    queue = current_work_filter.build_current_work_queue(active_window_hours=24)["queue"]
    lanes = _load_report_lanes()
    current_count = int(queue.get("current_automatable_count") or 0)
    inventory = _inventory(lanes)
    mission_incomplete = bool(lanes)
    empty_queue_migration_incomplete_triggered = current_count == 0 and mission_incomplete
    seed_result = seed_tasks(
        target_current_queue=3,
        max_new_implementation_tasks=max_new_tasks,
    )
    seed_triggered = empty_queue_migration_incomplete_triggered and bool(
        seed_result["generated_tasks"] or seed_result["duplicate_suppressed"]
    )
    state = {
        "schema_version": "v2_autonomous_mission_backlog_autoseed_v1",
        "generated_utc": _utc_iso(),
        "wait_seconds": wait_seconds,
        "seed_triggered": seed_triggered,
        "empty_queue_migration_incomplete_triggered": empty_queue_migration_incomplete_triggered,
        "mission_incomplete": mission_incomplete,
        "inventory": inventory,
        **seed_result,
    }
    _mirror_payload("operator_dashboard_payload.json", state, install_outputs=install_outputs)
    _mirror_payload("autoseed_status.json", state, install_outputs=install_outputs)
    return state


def main(argv: list[str] | None = None) -> int:  # noqa: D401
    """Entry point: strip legacy flags then delegate to Spark autoseed."""
    if argv is None:
        argv = sys.argv[1:]

    legacy = argparse.ArgumentParser(add_help=False)
    legacy.add_argument("--wait-seconds", type=int, default=None)
    legacy.add_argument("--json", action="store_true", default=False)
    _legacy_ns, remaining = legacy.parse_known_args(argv)

    return _spark_main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
