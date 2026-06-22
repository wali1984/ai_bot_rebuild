"""Unit tests for autonomous mission backlog auto-seeding.

The seeder must turn unresolved migration blockers into narrow,
paired implementation/review work without treating operator-only or
unsafe gates as automatable.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
MODULES = (
    "v2_closed_loop_lifecycle",
    "v2_current_work_filter",
    "v2_closed_loop_worker_pool",
    "v2_autonomous_mission_backlog_autoseed",
)


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    repo = tmp_path / "AI BOT REBUILD"
    (repo / "claude_worklog" / "agent_supervisor" / "tasks").mkdir(parents=True)
    (repo / "claude_worklog" / "tools").mkdir(parents=True)
    (repo / "v2" / "frontend" / "public" / "v2_report_center" / "latest").mkdir(parents=True)
    for mod_name in MODULES:
        (repo / "claude_worklog" / "tools" / f"{mod_name}.py").write_text(
            (TOOLS_DIR / f"{mod_name}.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    monkeypatch.syspath_prepend(str(repo / "claude_worklog" / "tools"))
    for mod_name in MODULES:
        sys.modules.pop(mod_name, None)
    modules = {name: importlib.import_module(name) for name in MODULES}
    return {
        "repo": repo,
        "tasks_dir": repo / "claude_worklog" / "agent_supervisor" / "tasks",
        "report_index": repo / "v2" / "frontend" / "public" / "v2_report_center" / "latest" / "report_index.json",
        **modules,
    }


def _write_report_index(path: Path, lanes: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "test",
                "blocked_count": len(lanes),
                "top_blockers": lanes[:3],
                "lanes": lanes,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_empty_queue_seeds_narrow_tasks_with_codex_pairs(isolated_workspace):
    ws = isolated_workspace
    seeder = ws["v2_autonomous_mission_backlog_autoseed"]
    _write_report_index(
        ws["report_index"],
        [
            {
                "report_id": "full_observation_builder",
                "title": "Full Observation Builder Status",
                "status": "BLOCKED",
                "go_no_go": "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
                "blocks_production_equivalence": True,
            },
            {
                "report_id": "runtime_soak_and_production_equivalence",
                "title": "Runtime Soak",
                "status": "BLOCKED",
                "go_no_go": "CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_BLOCKED",
                "blocks_production_equivalence": True,
            },
        ],
    )

    state = seeder.run_once(wait_seconds=0, install_outputs=False)

    assert state["seed_triggered"] is True
    assert state["empty_queue_migration_incomplete_triggered"] is True
    impl = [t for t in state["generated_tasks"] if t["task_role"] == "implementation"]
    reviews = [t for t in state["generated_tasks"] if t["task_role"] == "codex_review"]
    assert len(impl) == 3
    assert len(reviews) == 3
    assert all(t["mission_categories"] for t in impl)
    assert all(t["file_lock_group"] for t in impl)
    for task in impl:
        descriptor = json.loads((ws["repo"] / task["path"]).read_text())
        assert descriptor["report_only_work"] is False
        assert descriptor["ui_only_work"] is False
        assert descriptor["safety"]["live_gate"] == "blocked_human_only"
        assert descriptor["safety"]["live_symbols"] == []


def test_war_room_governor_seeds_required_parallel_lanes(isolated_workspace):
    ws = isolated_workspace
    seeder = ws["v2_autonomous_mission_backlog_autoseed"]
    _write_report_index(
        ws["report_index"],
        [
            {
                "report_id": "codex_24h_parallel_recovery_war_room_governor",
                "title": "Codex 24H Parallel Recovery War-Room Governor",
                "status": "BLOCKED",
                "go_no_go": "CODEX_24H_PARALLEL_RECOVERY_WAR_ROOM_GOVERNOR_BLOCKED",
                "blocks_production_equivalence": True,
            }
        ],
    )

    seed = seeder.seed_tasks(target_current_queue=3, max_new_implementation_tasks=3)

    impl = [t for t in seed["generated_tasks"] if t["task_role"] == "implementation"]
    task_ids = {t["task_id"] for t in impl}
    assert any(
        task_id.startswith("claude_autoseed_paper_fill_gate_block_reason_recording")
        for task_id in task_ids
    )
    assert any(
        task_id.startswith("claude_autoseed_observation_gap_feature_source_burndown")
        for task_id in task_ids
    )
    assert any(
        task_id.startswith("claude_autoseed_altdata_replay_bundle_snapshot_attachment")
        for task_id in task_ids
    )
    assert len(impl) == 3
    for task in impl:
        descriptor = json.loads((ws["repo"] / task["path"]).read_text())
        assert descriptor["report_only_work"] is False
        assert descriptor["safety"]["writes_old_redis"] is False
        assert descriptor["safety"]["calls_exchange_mutation"] is False
        assert descriptor["safety"]["approves_live"] is False


def test_operator_only_and_unsafe_blockers_are_not_seeded(isolated_workspace):
    ws = isolated_workspace
    seeder = ws["v2_autonomous_mission_backlog_autoseed"]
    _write_report_index(
        ws["report_index"],
        [
            {
                "report_id": "checkpoint_promotion",
                "title": "Checkpoint Promotion",
                "status": "OPERATOR_DECISION_REQUIRED",
                "go_no_go": "V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED",
            },
            {
                "report_id": "live_canary_safety",
                "title": "Live Canary Safety",
                "status": "BLOCKED",
                "go_no_go": "V2_LIVE_CANARY_BLOCKED",
            },
        ],
    )

    seed = seeder.seed_tasks()

    assert seed["mission_incomplete"] is True
    assert seed["automatable_blockers_exist"] is False
    assert seed["generated_tasks"] == []
    assert seed["inventory"]["operator_required_blocker_count"] >= 1
    assert seed["inventory"]["unsafe_blocker_count"] >= 1


def test_duplicate_suppression_prevents_reseed(isolated_workspace):
    ws = isolated_workspace
    seeder = ws["v2_autonomous_mission_backlog_autoseed"]
    _write_report_index(
        ws["report_index"],
        [
            {
                "report_id": "full_observation_builder",
                "title": "Full Observation Builder Status",
                "status": "BLOCKED",
                "go_no_go": "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
            }
        ],
    )

    first = seeder.seed_tasks()
    second = seeder.seed_tasks(target_current_queue=5, max_new_implementation_tasks=5)

    assert first["generated_tasks"]
    assert second["duplicate_suppressed"]
    first_ids = {task["task_id"] for task in first["generated_tasks"]}
    second_ids = {task["task_id"] for task in second["generated_tasks"]}
    assert first_ids.isdisjoint(second_ids)


def test_codex_reviews_are_dependency_gated_until_claude_completes(isolated_workspace):
    ws = isolated_workspace
    seeder = ws["v2_autonomous_mission_backlog_autoseed"]
    current_filter = ws["v2_current_work_filter"]
    _write_report_index(
        ws["report_index"],
        [
            {
                "report_id": "full_observation_builder",
                "title": "Full Observation Builder Status",
                "status": "BLOCKED",
                "go_no_go": "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
            }
        ],
    )
    seed = seeder.seed_tasks(target_current_queue=1, max_new_implementation_tasks=1)
    review = next(t for t in seed["generated_tasks"] if t["task_role"] == "codex_review")
    review_payload = json.loads((ws["repo"] / review["path"]).read_text())
    assert review_payload["status"] == "blocked_dependency"
    queue = current_filter.build_current_work_queue(active_window_hours=24)["queue"]
    ids = {row["task_id"] for row in queue["current"]}
    assert review["task_id"] not in ids

    impl = next(t for t in seed["generated_tasks"] if t["task_role"] == "implementation")
    impl_path = ws["repo"] / impl["path"]
    impl_payload = json.loads(impl_path.read_text())
    impl_payload["status"] = "completed"
    impl_path.write_text(json.dumps(impl_payload, indent=2, sort_keys=True) + "\n")
    promoted = seeder.promote_dependency_ready_codex_reviews()
    assert promoted and promoted[0]["task_id"] == review["task_id"]
    queue = current_filter.build_current_work_queue(active_window_hours=24)["queue"]
    ids = {row["task_id"] for row in queue["current"]}
    assert review["task_id"] in ids
