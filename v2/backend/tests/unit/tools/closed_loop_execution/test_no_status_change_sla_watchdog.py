"""Tests for the no-status-change SLA watchdog."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"


def _load_module():
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        sys.modules.pop("v2_no_status_change_sla_watchdog", None)
        return importlib.import_module("v2_no_status_change_sla_watchdog")
    finally:
        try:
            sys.path.remove(str(TOOLS_DIR))
        except ValueError:
            pass


def _base_snapshot(mod):
    now = mod.utc_iso()
    return {
        "report_center_generated_at": now,
        "replay_miner_generated_at": now,
        "event_watcher_generated_at": now,
        "no_manual_generated_at": now,
        "automatable_now_count": 0,
        "worker_active_leases": 0,
        "worker_queued_automatable_tasks": 0,
        "unmapped_codex_fail_count": 0,
        "remaining_operator_blockers": ["checkpoint_promotion"],
        "remaining_external_blockers": [],
        "remaining_event_blockers": [],
        "next_action_classification_counts": {"UNSAFE_TO_AUTOMATE": 0},
        "disallowed_classification_count": 0,
        "blocked_automatable_seed_count": 0,
    }


def test_root_cause_true_operator_wait_when_fresh() -> None:
    mod = _load_module()
    root = mod.classify_root_cause(_base_snapshot(mod))
    assert root["root_cause"] == "TRUE_OPERATOR_WAIT"
    assert root["root_cause_is_allowed"] is True


def test_report_center_stale_blocks_before_wait_classification() -> None:
    mod = _load_module()
    snap = _base_snapshot(mod)
    snap["report_center_generated_at"] = "2026-01-01T00:00:00Z"
    root = mod.classify_root_cause(snap)
    assert root["root_cause"] == "REPORT_CENTER_STALE"
    assert root["root_cause_is_allowed"] is False


def test_eligible_work_without_lease_is_worker_pool_idle() -> None:
    mod = _load_module()
    snap = _base_snapshot(mod)
    snap["remaining_operator_blockers"] = []
    snap["automatable_now_count"] = 1
    root = mod.classify_root_cause(snap)
    assert root["root_cause"] == "WORKER_POOL_IDLE_WITH_ELIGIBLE_WORK"
    assert root["root_cause_is_allowed"] is False


def test_misclassified_or_blocked_seed_is_not_true_wait() -> None:
    mod = _load_module()
    snap = _base_snapshot(mod)
    snap["remaining_operator_blockers"] = []
    snap["disallowed_classification_count"] = 1
    root = mod.classify_root_cause(snap)
    assert root["root_cause"] == "MISCLASSIFIED_AUTOMATABLE_WORK"
    assert root["root_cause_is_allowed"] is False

    snap["disallowed_classification_count"] = 0
    snap["blocked_automatable_seed_count"] = 1
    root2 = mod.classify_root_cause(snap)
    assert root2["root_cause"] == "MISCLASSIFIED_AUTOMATABLE_WORK"
    assert root2["root_cause_is_allowed"] is False


def test_non_allowed_root_seeds_spark_remediation(monkeypatch) -> None:
    mod = _load_module()
    snap = _base_snapshot(mod)
    calls = []

    def fake_seed(rows):
        calls.extend(rows)
        return {
            "generated_pair_count": 1,
            "generated_pairs": [{"implementation_task_id": "impl", "codex_review_task_id": "review"}],
        }

    monkeypatch.setattr(mod, "seed_automatable_tasks", fake_seed)
    remediation = mod.seed_stale_remediation(
        {"root_cause": "MISCLASSIFIED_AUTOMATABLE_WORK", "root_cause_is_allowed": False},
        snap,
    )
    assert remediation["remediation_seeded"] is True
    assert calls
    assert calls[0]["classification"] == mod.CLASS_AUTOMATABLE
    assert calls[0]["current_blockers"] == ["MISCLASSIFIED_AUTOMATABLE_WORK"]


def test_operator_reported_flat_history_covers_all_windows(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "WORKLOG_DIR", tmp_path / "worklog")
    monkeypatch.setattr(mod, "SNAPSHOT_HISTORY", tmp_path / "worklog" / "history.jsonl")
    snap = _base_snapshot(mod)
    snap.update(
        {
            "snapshot_utc": mod.utc_iso(),
            "production_score": 20.2,
            "migration_complete": False,
            "shutdown_ready": False,
            "live_ready": False,
            "paper_edge_proven": False,
            "global_blocker_count": 1,
            "report_center_blocked_count": 1,
            "replay_miner_sample_count": 100,
            "replay_miner_false_negative_count": 2,
            "replay_miner_windows_filled": {"1m": 1},
            "event_watchers_completed": 0,
            "external_source_state": [],
        }
    )
    history = mod.append_snapshot(snap, operator_reported_hours=12)
    comparison = mod.compare_snapshots(snap, history)
    assert comparison["operator_reported_no_change_synthetic_present"] is True
    assert comparison["status_flat_duration_seconds"] >= 12 * 60 * 60
    assert all(row["available"] is True for row in comparison["comparison_windows"].values())
    assert all(row["flat"] is True for row in comparison["comparison_windows"].values())


def test_replay_miner_progress_does_not_hide_visible_status_flatness(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "WORKLOG_DIR", tmp_path / "worklog")
    monkeypatch.setattr(mod, "SNAPSHOT_HISTORY", tmp_path / "worklog" / "history.jsonl")
    base = _base_snapshot(mod)
    base.update(
        {
            "snapshot_utc": mod.utc_iso(),
            "production_score": 20.2,
            "migration_complete": False,
            "shutdown_ready": False,
            "live_ready": False,
            "paper_edge_proven": False,
            "global_blocker_count": 1,
            "report_center_blocked_count": 1,
            "replay_miner_sample_count": 100,
            "replay_miner_false_negative_count": 2,
            "replay_miner_windows_filled": {"1m": 1},
            "event_watchers_completed": 0,
            "external_source_state": [],
            "operator_accepted_count": 0,
        }
    )
    history = mod.append_snapshot(base, operator_reported_hours=12)
    current = dict(base)
    current["snapshot_utc"] = mod.utc_iso()
    current["replay_miner_sample_count"] = 101
    current["replay_miner_windows_filled"] = {"1m": 2}
    history.append(current)
    comparison = mod.compare_snapshots(current, history)
    assert comparison["status_flat_duration_seconds"] >= 12 * 60 * 60
    assert comparison["observed_signal_flat_duration_seconds"] < 60
    for row in comparison["comparison_windows"].values():
        assert row["flat"] is True
        assert row["changed_fields"] == []
        assert "replay_miner_sample_count" in row["observed_signal_changed_fields"]


def test_ready_gate_allows_true_wait_and_blocks_stale() -> None:
    mod = _load_module()
    snap = _base_snapshot(mod)
    root = mod.classify_root_cause(snap)
    go, state, blockers = mod.determine_go_no_go(
        root,
        snap,
        {"status_flat_duration_seconds": 3600},
        {"remediation_seeded": False},
    )
    assert go == mod.GO_READY
    assert state == "EXPECTED_WAIT"
    assert blockers == []

    stale_root = {"root_cause": "REPLAY_MINER_STALE", "root_cause_is_allowed": False, "stale_flags": {}}
    go2, state2, blockers2 = mod.determine_go_no_go(
        stale_root,
        snap,
        {},
        {"remediation_seeded": False},
    )
    assert go2 == mod.GO_BLOCKED
    assert state2 == "BLOCKED"
    assert "REPLAY_MINER_STALE" in blockers2


def test_outputs_never_mark_live_or_shutdown_ready(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    monkeypatch.setattr(mod, "WORKLOG_DIR", tmp_path / "worklog")
    monkeypatch.setattr(mod, "PUBLIC_DIR", tmp_path / "public")
    status = {
        "generated_utc": mod.utc_iso(),
        "go_no_go": mod.GO_READY,
        "sla_state": "EXPECTED_WAIT",
        "blockers": [],
        "snapshot": {
            "production_score": 20.2,
            "global_blocker_count": 1,
            "automatable_now_count": 0,
            "worker_active_leases": 0,
            "task_completions_last_hour": 0,
            "replay_miner_sample_count": 100,
            "event_watchers_completed": 0,
        },
    }
    root = {"root_cause": "TRUE_OPERATOR_WAIT"}
    action_plan = {"next_operator_action": "decide", "next_automatic_action": "watch"}
    remediation = {"remediation_seeded": False}
    executive = {
        "STATUS_FLAT_DURATION": "1h",
        "WHY_STATUS_IS_FLAT": "operator decisions remain unresolved",
        "NEXT_OPERATOR_ACTION": "decide",
        "NEXT_AUTOMATIC_ACTION": "watch",
        "IS_AUTOMATION_STALLED": False,
        "IS_THIS_EXPECTED": True,
        "plain_english": [
            "Production score is flat because operator decisions remain unresolved.",
            "Automation is not stalled because TRUE_OPERATOR_WAIT.",
            "The next thing that can change this state is decide.",
        ],
    }
    mod.write_outputs(status, root, action_plan, remediation, executive)
    payload = json.loads((tmp_path / "worklog" / "operator_dashboard_payload.json").read_text())
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["shutdown_safe"] is False
    assert payload["live_ready"] is False
    assert payload["canary_ready"] is False
