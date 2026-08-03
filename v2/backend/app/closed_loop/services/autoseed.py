"""Autoseed service for Spark: generates implementation + paired Codex review tasks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore
from v2.backend.app.closed_loop.lane_registry import all_lane_configs, get_group_for_mission_category

REPO_ROOT = Path(__file__).resolve().parents[5]
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_codex_spark_parallel_closed_loop"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_codex_spark_parallel_closed_loop"
    / "latest"
)

TASK_MIRROR_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_closed_loop_execution"
    / "latest"
    / "tasks"
)

SAFE_ENVELOPE = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
}

TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "mission_category": "runtime_stability",
        "title": "Spark runtime backlog seed",
        "scope_paths": ["v2/backend/app", "claude_worklog/final_readiness/v2_codex_spark_parallel_closed_loop"],
        "notes": "Narrow implementation task for runtime stability work.",
    },
    {
        "mission_category": "model_policy_readiness",
        "title": "Spark model-policy seed",
        "scope_paths": ["v2/backend/app/services", "v2/backend/app/cli"],
        "notes": "Readiness task for model and policy pipeline work.",
    },
    {
        "mission_category": "paper_edge",
        "title": "Spark proof seed",
        "scope_paths": ["v2/backend/app/services/proof"],
        "notes": "Proof task with Codex review coverage.",
    },
)


def _safe_enforced_descriptor(task_id: str, task_type: str, mission_category: str, lane_group: str, owner: str, *, file_lock_group: str, depends_on_task_id: str | None = None, paired_task_id: str | None = None) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task_type": task_type,
        "lane_type": task_type,
        "mission_category": mission_category,
        "lane_group": lane_group,
        "owner": owner,
        "agent": "codex" if task_type == "CODEX_REVIEW" else "claude",
        "status": "pending",
        "file_lock_group": file_lock_group,
        "paired_task_id": paired_task_id,
        "depends_on_task_id": depends_on_task_id,
        "safe_envelope": SAFE_ENVELOPE.copy(),
        "prompt": f"Implement {task_id} under V2 closed-loop constraints",
        "scope_paths": [],
    }


def _next_id(prefix: str, sequence: int) -> str:
    return f"{prefix}_{sequence:03d}"


def _task_id_from_template(seq: int, mission_category: str) -> str:
    safe = mission_category.replace("-", "_").replace(" ", "_")
    return _next_id(f"closed_loop_{safe}_task", seq)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _write_mirror(task: dict[str, Any]) -> None:
    TASK_MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    (TASK_MIRROR_DIR / f"{task['task_id']}.json").write_text(
        json.dumps(task, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def run_once(*, db_path: str | None = None, max_new_tasks: int = 3, mission_filter: list[str] | None = None) -> dict[str, Any]:
    store = SQLiteLeaseStore(db_path=db_path)
    generated: list[dict[str, Any]] = []
    sequence = 1
    for template in TEMPLATES[:max_new_tasks]:
        mission_category = template["mission_category"]
        if mission_filter and mission_category not in mission_filter:
            continue
        lane = get_group_for_mission_category(mission_category)
        if lane is None:
            continue
        impl_task_id = _task_id_from_template(sequence, mission_category)
        sequence += 1
        lock_group = f"{mission_category}_{sequence}"
        impl_task = _safe_enforced_descriptor(
            task_id=impl_task_id,
            task_type="CLAUDE_IMPLEMENTATION",
            mission_category=mission_category,
            lane_group=lane,
            owner="CLAUDE",
            file_lock_group=lock_group,
        )
        impl_task["title"] = template["title"]
        impl_task["scope_paths"] = template["scope_paths"]
        impl_task["notes"] = template.get("notes")

        codex_task_id = f"codex_review_{impl_task_id}"
        existing_impl = store.get_task(impl_task_id)
        existing_codex = store.get_task(codex_task_id)
        if existing_impl or existing_codex:
            generated.append(
                {
                    "implementation": impl_task_id,
                    "codex_review": codex_task_id,
                    "lane_group": lane,
                    "status": "DUPLICATE_SUPPRESSED_EXISTING_TASK_REFERENCED",
                    "implementation_status": (existing_impl or {}).get("status"),
                    "codex_review_status": (existing_codex or {}).get("status"),
                }
            )
            continue

        codex_task = _safe_enforced_descriptor(
            task_id=codex_task_id,
            task_type="CODEX_REVIEW",
            mission_category=mission_category,
            lane_group=f"{lane.replace('claude', 'codex')}",
            owner="CODEX",
            file_lock_group=lock_group,
            depends_on_task_id=impl_task_id,
            paired_task_id=impl_task_id,
        )
        codex_task["title"] = f"Codex review for {impl_task_id}"
        codex_task["codex_pair_task_id"] = impl_task_id
        codex_task["prompt"] = f"Review implementation descriptor {impl_task_id}"

        impl_task["paired_task_id"] = codex_task_id
        store.create_task(impl_task, status="pending")
        store.create_task(codex_task, status="pending")
        _write_mirror(impl_task)
        _write_mirror(codex_task)

        generated.append(
            {
                "implementation": impl_task["task_id"],
                "codex_review": codex_task["task_id"],
                "lane_group": lane,
            }
        )

    result: dict[str, Any] = {
        "marker": "V2_CODEX_SPARK_AUTONOMOUS_SEED_SUCCESS",
        "generated_pairs": generated,
        "lane_registry": {
            "lane_count": len(all_lane_configs()),
            "lane_ids": [cfg.lane_group for cfg in all_lane_configs()],
        },
    }
    status_path = WORKLOG_DIR / "autoseed_pairing_status.json"
    sample_path = WORKLOG_DIR / "generated_task_pair_samples.json"
    _write_json(status_path, result)
    _write_json(sample_path, {"pairs": generated[:10]})
    store.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--max-new-tasks", type=int, default=3)
    parser.add_argument("--mission-category", action="append", default=None)
    args = parser.parse_args(argv)
    run_once(db_path=args.db_path, max_new_tasks=args.max_new_tasks, mission_filter=args.mission_category)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
