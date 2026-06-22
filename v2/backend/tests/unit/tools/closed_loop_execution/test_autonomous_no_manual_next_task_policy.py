"""Tests for the autonomous no-manual next-task policy."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"


def _load_policy_module():
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        sys.modules.pop("v2_autonomous_no_manual_next_task_policy", None)
        return importlib.import_module("v2_autonomous_no_manual_next_task_policy")
    finally:
        try:
            sys.path.remove(str(TOOLS_DIR))
        except ValueError:
            pass


def test_full_observation_uses_external_context_not_broad_task() -> None:
    mod = _load_policy_module()
    item = mod.ActionItem(
        source="top_blockers",
        report_id="full_observation_builder",
        title="Full Observation Builder Status",
        status="BLOCKED",
        owner="CLAUDE",
        next_action=None,
        current_blockers=(),
        raw={"report_id": "full_observation_builder", "status": "BLOCKED"},
    )
    row = mod.classify_action(
        item,
        {
            "external_source": {"external_source_blocker_count": 1},
            "operator_decision_center": {},
            "event_watchers": {},
        },
    )
    assert row["classification"] == mod.CLASS_EXTERNAL
    assert "EXTERNAL_SOURCE" in row["classification_reason"]


def test_policy_seeds_paired_safe_task_for_automatable_action(tmp_path, monkeypatch) -> None:
    mod = _load_policy_module()
    monkeypatch.setattr(
        mod,
        "TASK_MIRROR_DIR",
        tmp_path / "mirrors",
    )
    rows = [
        {
            "source": "top_blockers",
            "report_id": "v2_autonomous_mission_execution_burndown",
            "title": "V2 Autonomous Mission Execution Burndown",
            "status": "BLOCKED",
            "owner": "SYSTEM",
            "next_action": None,
            "current_blockers": ["FLAT_BLOCKER_COUNT_REASON_BLOCKS_READY"],
            "classification": mod.CLASS_AUTOMATABLE,
            "classification_reason": "CURRENT_BLOCKING_WORK_IS_SAFE_TO_AUTOMATE",
            "mission_category": "runtime_stability",
            "source_key": "burndown_source",
            "allowed_classification": True,
        }
    ]
    status = mod.seed_automatable_tasks(rows, db_path=str(tmp_path / "leases.db"))
    assert status["generated_pair_count"] == 1

    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    try:
        impl = store.get_task(status["generated_pairs"][0]["implementation_task_id"])
        review = store.get_task(status["generated_pairs"][0]["codex_review_task_id"])
        assert impl is not None
        assert review is not None
        assert impl["agent"] == "claude"
        assert review["agent"] == "codex"
        assert review["depends_on_task_id"] == impl["task_id"]
        assert impl["payload_json"]["safe_envelope"]["live_gate"] == "blocked_human_only"
        assert impl["payload_json"]["safe_envelope"]["live_symbols"] == []
    finally:
        store.close()


def test_build_status_blocks_unmapped_codex_fail(tmp_path, monkeypatch) -> None:
    mod = _load_policy_module()
    monkeypatch.setattr(mod, "_load_report_index", lambda: {
        "generated_at": "2026-05-25T00:00:00Z",
        "top_blockers": [],
        "next_automatable_actions": [],
        "next_operator_decisions": [],
    })
    monkeypatch.setattr(mod, "_load_context_payloads", lambda: {})
    monkeypatch.setattr(mod, "protected_worker_status", lambda: {
        "protected_units": {},
        "protected_unit_count": 0,
        "stopped_or_failed_units": {},
        "workers_must_not_stop_policy": True,
    })
    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    store.add_codex_fail_map(
        codex_task_id="codex_failed_task",
        classification="fail_without_mapping",
        remediation_task_id=None,
        operator_required=False,
        unsafe_to_fix=False,
    )
    store.close()

    status = mod.build_policy_status(db_path=str(tmp_path / "leases.db"), seed_tasks=False)
    assert status["go_no_go"] == mod.GO_BLOCKED
    assert "UNMAPPED_CODEX_FAIL_PRESENT" in status["blockers"]


def test_claude_worker_child_receives_heartbeat_context(tmp_path, monkeypatch) -> None:
    from v2.backend.app.closed_loop.workers import claude_worker

    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    task = {
        "task_id": "heartbeat_context_task",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "lane_type": "CLAUDE_IMPLEMENTATION",
        "mission_category": "runtime_stability",
        "lane_group": "runtime-claude",
        "owner": "CLAUDE",
        "agent": "claude",
        "status": "pending",
        "file_lock_group": "heartbeat_context_task",
        "safe_envelope": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
        "prompt": "test",
    }
    store.create_task(task, status="pending")
    store.heartbeat_worker(
        "claude-test",
        state="idle_ready",
        lane_group="runtime-claude",
        worker_kind="claude",
    )
    claim = store.claim_task(
        worker_id="claude-test",
        lane_group="runtime-claude",
        worker_kind="claude",
    )
    assert claim is not None
    captured: dict[str, object] = {}

    def fake_run_child(task_arg, timeout, store, worker_id, lease_id, lane_group):  # noqa: ANN001
        captured.update(
            task_id=task_arg["task_id"],
            timeout=timeout,
            store=store,
            worker_id=worker_id,
            lease_id=lease_id,
            lane_group=lane_group,
        )
        return 0, "completed"

    monkeypatch.setattr(claude_worker, "_run_child", fake_run_child)
    result = claude_worker.execute_task(store, "claude-test", claim, timeout=7)
    assert result["action"] == "completed"
    assert captured["task_id"] == "heartbeat_context_task"
    assert captured["worker_id"] == "claude-test"
    assert captured["lease_id"] == claim["lease"]["lease_id"]
    assert captured["lane_group"] == "runtime-claude"
    store.close()


def test_spark_autoseed_does_not_reset_existing_terminal_tasks(tmp_path, monkeypatch) -> None:
    from v2.backend.app.closed_loop.services import autoseed

    monkeypatch.setattr(autoseed, "WORKLOG_DIR", tmp_path / "worklog")
    monkeypatch.setattr(autoseed, "PUBLIC_DIR", tmp_path / "public")
    monkeypatch.setattr(autoseed, "TASK_MIRROR_DIR", tmp_path / "tasks")
    db_path = tmp_path / "leases.db"

    first = autoseed.run_once(db_path=str(db_path), max_new_tasks=1)
    impl_id = first["generated_pairs"][0]["implementation"]
    store = SQLiteLeaseStore(db_path=db_path)
    store.complete_task(impl_id, status="completed")
    store.close()

    second = autoseed.run_once(db_path=str(db_path), max_new_tasks=1)
    assert second["generated_pairs"][0]["status"] == "DUPLICATE_SUPPRESSED_EXISTING_TASK_REFERENCED"
    store = SQLiteLeaseStore(db_path=db_path)
    try:
        assert store.get_task(impl_id)["status"] == "completed"
    finally:
        store.close()
