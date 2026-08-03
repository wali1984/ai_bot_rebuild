"""Unit tests for autonomous mission execution burndown metrics."""
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
    "v2_burndown_fail_to_remediation_mapper",
    "v2_autonomous_mission_backlog_autoseed",
    "v2_autonomous_mission_execution_burndown",
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
    pool_status = {
        "active_leases_count": 2,
        "worker_count_busy": 2,
        "worker_count_idle_ready": 4,
        "duplicate_task_leases": 0,
        "duplicate_file_locks": 0,
        "duplicate_worker_leases": 0,
        "blocker": None,
        "current_task_assignments": [],
    }
    monkeypatch.setattr(
        modules["v2_autonomous_mission_execution_burndown"].worker_pool,
        "run_pool_once",
        lambda **_: pool_status,
    )
    monkeypatch.setattr(
        modules["v2_autonomous_mission_execution_burndown"].autoseed,
        "seed_tasks",
        lambda **_: {
            "generated_tasks": [],
            "duplicate_suppressed": [],
            "refused": [],
        },
    )
    return {
        "repo": repo,
        "tasks_dir": repo / "claude_worklog" / "agent_supervisor" / "tasks",
        "report_index": repo / "v2" / "frontend" / "public" / "v2_report_center" / "latest" / "report_index.json",
        **modules,
    }


def _write_task(tasks_dir: Path, task_id: str, payload: dict[str, Any]) -> None:
    data = {"task_id": task_id, **payload}
    (tasks_dir / f"{task_id}.json").write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_report_index(path: Path, lanes: list[dict[str, Any]] | None = None) -> None:
    payload = {
        "lanes": lanes if lanes is not None else [
            {
                "report_id": "checkpoint_promotion",
                "title": "Checkpoint Promotion",
                "status": "OPERATOR_DECISION_REQUIRED",
                "go_no_go": "V2_CHECKPOINT_PROMOTION_OPERATOR_REQUIRED",
            },
        ],
        "blocked_count": sum(
            1 for lane in (lanes or []) if lane.get("status") in ("BLOCKED", "FAIL")
        ),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _seed_previous_status(repo: Path, blockers_after: list[dict[str, Any]]) -> None:
    """Seed prior burndown status so blocker_count_before equals len(blockers_after)+delta."""
    worklog_dir = (
        repo
        / "claude_worklog"
        / "final_readiness"
        / "v2_autonomous_mission_execution_burndown"
        / "latest"
    )
    worklog_dir.mkdir(parents=True, exist_ok=True)
    (worklog_dir / "mission_execution_burndown_status.json").write_text(
        json.dumps(
            {
                "blocker_burndown_matrix": {
                    "blockers_after": blockers_after,
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_burndown_counts_real_implementation_not_report_only(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _write_report_index(ws["report_index"])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["paper edge", "risk control"],
        "report_only_work": False,
        "current_active": True,
    })
    _write_task(ws["tasks_dir"], "report_center_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["runtime stability"],
        "report_only_work": True,
        "current_active": True,
    })

    state = mod.run_once(autoseed_followup=False)

    assert state["go_no_go"] == mod.READY_MARKER
    assert state["tasks_completed_last_hour"] == 2
    assert state["implementation_tasks_completed_last_hour"] == 1
    assert state["mission_categories_moved"]["paper edge"]["completed_implementation_count"] == 1
    assert state["not_counted_as_progress"]["report_center_refresh"] is True
    assert state["flat_blocker_count_reason"]["reason_code"] == (
        "ALL_REMAINING_BLOCKERS_OPERATOR_REQUIRED"
    )


def test_burndown_blocks_when_codex_fail_unmapped(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    mapper = ws["v2_burndown_fail_to_remediation_mapper"]
    monkeypatch.setattr(
        mapper,
        "classify_codex_fail",
        lambda **kwargs: {
            "codex_fail_id": kwargs["verdict"].get("task_id"),
            "codex_review_path": kwargs["verdict"].get("path"),
            "failed_gate": kwargs["verdict"].get("verdict"),
            "fail_blockers": [],
            "remediation_required": True,
            "remediation_descriptor_created": False,
            "remediation_descriptor_path": None,
            "existing_remediation_descriptor_path": None,
            "duplicate_suppressed": False,
            "operator_required": False,
            "unsafe_to_fix": False,
            "not_automatable_reason": None,
            "next_action": "unmapped",
            "terminal_classification": None,
        },
    )
    now = mod.utc_iso()
    _write_report_index(ws["report_index"])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["observation completeness"],
        "current_active": True,
    })
    out = (
        ws["repo"]
        / "claude_worklog"
        / "final_readiness"
        / "v2_closed_loop_execution"
        / "latest"
        / "codex_review_outputs"
        / "review_fail"
    )
    out.mkdir(parents=True)
    (out / "CODEX_GO_NO_GO.md").write_text("SAMPLE_CODEX_FAIL\n", encoding="utf-8")

    state = mod.run_once(autoseed_followup=False)

    assert state["go_no_go"] == mod.BLOCKED_MARKER
    assert "CODEX_FAIL_WITHOUT_TERMINAL_CLASSIFICATION" in state["blockers"]
    assert state["codex_fail_to_remediation_map"]["any_unmapped"] is True


def test_burndown_allows_codex_fail_with_existing_remediation(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _write_report_index(ws["report_index"])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["observation completeness"],
        "current_active": True,
    })
    review_id = "review_existing_remediation"
    out = (
        ws["repo"]
        / "claude_worklog"
        / "final_readiness"
        / "v2_closed_loop_execution"
        / "latest"
        / "codex_review_outputs"
        / review_id
    )
    out.mkdir(parents=True)
    (out / "CODEX_GO_NO_GO.md").write_text("SAMPLE_CODEX_FAIL\n", encoding="utf-8")
    _write_task(ws["tasks_dir"], review_id, {
        "task_type": "CODEX_REVIEW",
        "status": "failed",
        "completed_at": now,
        "fail_blockers": ["narrow blocker requiring code change"],
        "next_action": "SAMPLE_CODEX_FAIL",
    })
    _write_task(ws["tasks_dir"], f"closed_loop_remediation_{review_id}", {
        "task_type": "REMEDIATION",
        "status": "completed",
        "completed_at": now,
        "codex_pair_task_id": review_id,
    })

    state = mod.run_once(autoseed_followup=False)

    rows = state["codex_fail_to_remediation_map"]["mapping"]
    assert any(
        row["terminal_classification"] == "EXISTING_REMEDIATION_REFERENCED"
        for row in rows
    )
    assert state["codex_fail_to_remediation_map"]["any_unmapped"] is False
    assert state["go_no_go"] == mod.READY_MARKER


def test_burndown_classifies_operator_required_fail(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _write_report_index(ws["report_index"])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["observation completeness"],
        "current_active": True,
    })
    review_id = "review_operator_required"
    out = (
        ws["repo"]
        / "claude_worklog"
        / "final_readiness"
        / "v2_closed_loop_execution"
        / "latest"
        / "codex_review_outputs"
        / review_id
    )
    out.mkdir(parents=True)
    (out / "CODEX_GO_NO_GO.md").write_text("SAMPLE_CODEX_FAIL\n", encoding="utf-8")
    _write_task(ws["tasks_dir"], review_id, {
        "task_type": "CODEX_REVIEW",
        "status": "failed",
        "completed_at": now,
        "fail_blockers": [
            "Provide an operator-approved checkpoint blob under protected runtime",
        ],
        "next_action": "SAMPLE_CODEX_FAIL",
    })

    state = mod.run_once(autoseed_followup=False)

    rows = state["codex_fail_to_remediation_map"]["mapping"]
    assert rows and rows[0]["terminal_classification"] == "OPERATOR_REQUIRED"
    assert rows[0]["operator_required"] is True
    assert rows[0]["remediation_descriptor_created"] is False
    assert state["go_no_go"] == mod.READY_MARKER


def test_burndown_classifies_unsafe_fail(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _write_report_index(ws["report_index"])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["observation completeness"],
        "current_active": True,
    })
    review_id = "review_unsafe"
    out = (
        ws["repo"]
        / "claude_worklog"
        / "final_readiness"
        / "v2_closed_loop_execution"
        / "latest"
        / "codex_review_outputs"
        / review_id
    )
    out.mkdir(parents=True)
    (out / "CODEX_GO_NO_GO.md").write_text("SAMPLE_CODEX_FAIL\n", encoding="utf-8")
    _write_task(ws["tasks_dir"], review_id, {
        "task_type": "CODEX_REVIEW",
        "status": "failed",
        "completed_at": now,
        "fail_blockers": [
            "Cannot proceed without enabling live trading on canary symbols",
        ],
        "next_action": "SAMPLE_CODEX_FAIL",
    })

    state = mod.run_once(autoseed_followup=False)

    rows = state["codex_fail_to_remediation_map"]["mapping"]
    assert rows and rows[0]["terminal_classification"] == "UNSAFE_TO_FIX_AUTOMATION_BLOCKED"
    assert rows[0]["unsafe_to_fix"] is True
    assert rows[0]["remediation_descriptor_created"] is False


def test_burndown_blocks_when_flat_blocker_count_no_reason(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    _write_report_index(ws["report_index"], lanes=[
        {
            "report_id": "full_observation_builder",
            "title": "Full Observation Builder",
            "status": "BLOCKED",
            "go_no_go": "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
        },
        {
            "report_id": "runtime_soak",
            "title": "Runtime Soak",
            "status": "BLOCKED",
            "go_no_go": "RUNTIME_SOAK_BLOCKED",
        },
    ])

    state = mod.run_once(autoseed_followup=False)

    assert state["flat_blocker_count_reason"]["is_flat"] is True
    assert state["flat_blocker_count_reason"]["reason_code"] == (
        "NO_MEASURABLE_BURNDOWN_THIS_CYCLE_BLOCKED"
    )
    assert state["go_no_go"] == mod.BLOCKED_MARKER


def test_burndown_ready_when_impl_completed_awaiting_review(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _write_report_index(ws["report_index"], lanes=[
        {
            "report_id": "full_observation_builder",
            "title": "Full Observation Builder",
            "status": "BLOCKED",
            "go_no_go": "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
        },
    ])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["paper edge"],
        "current_active": True,
    })

    state = mod.run_once(autoseed_followup=False)

    assert state["flat_blocker_count_reason"]["reason_code"] == (
        "IMPLEMENTATION_COMPLETED_AWAITING_CODEX_REVIEW"
    )
    assert state["flat_blocker_count_reason"]["ready_allowed"] is True
    assert state["go_no_go"] == mod.READY_MARKER


def test_burndown_blocks_when_flat_blocker_count_due_codex_fail(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    mapper = ws["v2_burndown_fail_to_remediation_mapper"]
    monkeypatch.setattr(
        mapper,
        "classify_codex_fail",
        lambda **kwargs: {
            "codex_fail_id": kwargs["verdict"].get("task_id"),
            "codex_review_path": kwargs["verdict"].get("path"),
            "failed_gate": kwargs["verdict"].get("verdict"),
            "fail_blockers": [],
            "remediation_required": True,
            "remediation_descriptor_created": False,
            "remediation_descriptor_path": None,
            "existing_remediation_descriptor_path": None,
            "duplicate_suppressed": False,
            "operator_required": False,
            "unsafe_to_fix": False,
            "not_automatable_reason": None,
            "next_action": "unmapped",
            "terminal_classification": None,
        },
    )
    now = mod.utc_iso()
    _write_report_index(ws["report_index"], lanes=[
        {
            "report_id": "full_observation_builder",
            "title": "Full Observation Builder",
            "status": "BLOCKED",
            "go_no_go": "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
        },
    ])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["paper edge"],
        "current_active": True,
    })
    out = (
        ws["repo"]
        / "claude_worklog"
        / "final_readiness"
        / "v2_closed_loop_execution"
        / "latest"
        / "codex_review_outputs"
        / "review_x"
    )
    out.mkdir(parents=True)
    (out / "CODEX_GO_NO_GO.md").write_text("SAMPLE_CODEX_FAIL\n", encoding="utf-8")

    state = mod.run_once(autoseed_followup=False)

    assert state["flat_blocker_count_reason"]["reason_code"] == (
        "BLOCKER_UNCHANGED_DUE_CODEX_FAIL"
    )
    assert state["go_no_go"] == mod.BLOCKED_MARKER


def test_burndown_ready_when_blocker_count_decreases(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _seed_previous_status(ws["repo"], blockers_after=[
        {"report_id": "old_a", "operator_gated": False, "external_event_position_dependent": False},
        {"report_id": "old_b", "operator_gated": False, "external_event_position_dependent": False},
    ])
    _write_report_index(ws["report_index"], lanes=[
        {
            "report_id": "old_a",
            "title": "Old A",
            "status": "BLOCKED",
            "go_no_go": "OLD_A_BLOCKED",
        },
    ])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["paper edge"],
        "current_active": True,
    })

    state = mod.run_once(autoseed_followup=False)

    assert state["blocker_count_before"] == 2
    assert state["blocker_count_after"] == 1
    assert state["flat_blocker_count_reason"]["is_flat"] is False
    assert state["go_no_go"] == mod.READY_MARKER


def test_burndown_counts_codex_pass_and_fail(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _write_report_index(ws["report_index"])
    _write_task(ws["tasks_dir"], "impl_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["observation completeness"],
        "current_active": True,
    })
    out = ws["repo"] / "claude_worklog" / "final_readiness" / "v2_closed_loop_execution" / "latest" / "codex_review_outputs" / "review_a"
    out.mkdir(parents=True)
    (out / "CODEX_GO_NO_GO.md").write_text("SAMPLE_CODEX_PASS\n", encoding="utf-8")
    out2 = out.parent / "review_b"
    out2.mkdir()
    (out2 / "CODEX_GO_NO_GO.md").write_text("SAMPLE_CODEX_FAIL\n", encoding="utf-8")

    state = mod.run_once(autoseed_followup=False)

    assert state["Codex_PASS_count_last_hour"] == 1
    assert state["Codex_FAIL_count_last_hour"] == 1


def test_burndown_blocks_without_recent_implementation(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    _write_report_index(ws["report_index"])

    state = mod.run_once(autoseed_followup=False)

    assert state["go_no_go"] == mod.BLOCKED_MARKER
    assert "NO_IMPLEMENTATION_TASK_COMPLETED_LAST_HOUR" in state["blockers"]
    assert state["implementation_tasks_completed_last_hour"] == 0


def test_burndown_refuses_to_count_report_only_completions(isolated_workspace):
    ws = isolated_workspace
    mod = ws["v2_autonomous_mission_execution_burndown"]
    now = mod.utc_iso()
    _write_report_index(ws["report_index"])
    _write_task(ws["tasks_dir"], "report_center_done", {
        "task_type": "CLAUDE_IMPLEMENTATION",
        "status": "completed",
        "completed_at": now,
        "mission_categories": ["runtime stability"],
        "report_only_work": True,
        "current_active": True,
    })

    state = mod.run_once(autoseed_followup=False)

    assert state["implementation_tasks_completed_last_hour"] == 0
    assert state["go_no_go"] == mod.BLOCKED_MARKER
    assert state["task_completion_last_hour"]["report_only_or_control_artifacts_completed_last_hour"]
