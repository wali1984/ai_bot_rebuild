"""Unit tests for the V2 persistent worker pool.

Covers each spec validation point in Phase 7:

* worker heartbeat counts as active lane;
* short-lived child process exit does not kill the worker lane;
* worker picks next task after child exits;
* two workers cannot lease the same task;
* file-lock conflict blocks the second worker;
* stale lease reclaim once;
* second stale creates takeover/remediation or blocks with exact reason;
* unsafe task refused;
* current-work filter excludes historical descriptors;
* active_lane_count uses worker heartbeats, not child PIDs;
* active_lane_count >= 3 while current automatable work exists.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
MODULES = (
    "v2_closed_loop_lifecycle",
    "v2_claude_task_runner",
    "v2_codex_review_runner",
    "v2_current_work_filter",
    "v2_closed_loop_worker_pool",
    "v2_closed_loop_claude_worker",
    "v2_closed_loop_codex_worker",
    "v2_closed_loop_persistent_worker_pool_orchestrator",
)


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    repo = tmp_path / "AI BOT REBUILD"
    (repo / "claude_worklog" / "agent_supervisor" / "tasks").mkdir(parents=True)
    (repo / "claude_worklog" / "tools").mkdir(parents=True)
    (repo / "v2" / "frontend" / "public").mkdir(parents=True)
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
        **modules,
    }


def _write_task(tasks_dir: Path, task_id: str, payload: dict[str, Any]) -> Path:
    p = tasks_dir / f"{task_id}.json"
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def test_worker_heartbeat_counts_as_active_lane(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    by_lane = wp.current_alive_workers_by_lane()
    assert len(by_lane[wp.LANE_TYPE_CLAUDE]) == 1
    assert by_lane[wp.LANE_TYPE_CLAUDE][0]["worker_id"] == "claude-1"


def test_active_lane_count_uses_worker_heartbeats_not_child_pids(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    # Synthesize a current pending task so the lane count comparison is
    # meaningful, but stamp a heartbeat for a worker that has *no*
    # child process — its lane must still count.
    _write_task(ws["tasks_dir"], "current_a", {
        "task_id": "current_a", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    wp.write_worker_heartbeat("claude-2", wp.LANE_TYPE_CLAUDE, state="busy", current_task_id="current_a")
    wp.write_worker_heartbeat("claude-3", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    status = wp.compute_pool_status(target_claude=3, target_codex=0)
    assert status["active_lane_count"] == 3
    assert status["blocker"] is None


def test_two_workers_cannot_lease_same_task(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    _write_task(ws["tasks_dir"], "current_x", {
        "task_id": "current_x", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    first = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    second = wp.claim_next_task("claude-2", wp.LANE_TYPE_CLAUDE)
    assert first is not None
    assert first["lease"]["task_id"] == "current_x"
    assert second is None  # nothing else current to claim


def test_file_lock_conflict_blocks_second_worker(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    _write_task(ws["tasks_dir"], "current_y_a", {
        "task_id": "current_y_a", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
        "file_lock_group": "shared_lock",
    })
    _write_task(ws["tasks_dir"], "current_y_b", {
        "task_id": "current_y_b", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
        "file_lock_group": "shared_lock",
    })
    first = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    second = wp.claim_next_task("claude-2", wp.LANE_TYPE_CLAUDE)
    assert first is not None
    assert second is None


def test_stale_lease_reclaim_once(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    _write_task(ws["tasks_dir"], "current_stale", {
        "task_id": "current_stale", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    res = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert res is not None
    # Force the lease heartbeat to look ancient.
    reg = wp.read_lease_registry()
    reg["leases"][0]["heartbeat_at"] = "2020-01-01T00:00:00Z"
    wp.write_lease_registry(reg)
    first = wp.reclaim_stale_leases()
    assert first["reclaimed"]
    assert not first["second_time"]
    # Mark the (now-released) lease back to leased + ancient heartbeat.
    reg = wp.read_lease_registry()
    reg["leases"][0]["status"] = "leased"
    reg["leases"][0]["heartbeat_at"] = "2020-01-01T00:00:00Z"
    wp.write_lease_registry(reg)
    second = wp.reclaim_stale_leases()
    assert second["second_time"], "second stale must escalate"


def test_terminal_descriptor_reconciles_active_lease(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    task = _write_task(ws["tasks_dir"], "current_terminal_sync", {
        "task_id": "current_terminal_sync", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    res = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert res is not None
    payload = json.loads(task.read_text(encoding="utf-8"))
    payload["status"] = "failed"
    task.write_text(json.dumps(payload), encoding="utf-8")
    reclaimed = wp.reclaim_stale_leases()
    assert reclaimed["terminal_synced"]
    reg = wp.read_lease_registry()
    assert reg["leases"][0]["status"] == "failed"
    status = wp.compute_pool_status(target_claude=3, target_codex=0)
    assert status["active_leases_count"] == 0


def test_unsafe_task_refused_at_lease_time(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    _write_task(ws["tasks_dir"], "live_canary_thing", {
        "task_id": "live_canary_thing", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
        "prompt": "do something with live_trading enabled",
    })
    res = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert res is None


def test_source_truth_completed_descriptor_not_claimed_by_file_pool(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    task = _write_task(ws["tasks_dir"], "current_source_truth_done", {
        "task_id": "current_source_truth_done",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
        "current_active": True,
        "resolved_from_source_truth": True,
        "source_truth_superseded": True,
        "source_truth_status": "completed",
    })
    res = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert res is None
    refreshed = json.loads(task.read_text(encoding="utf-8"))
    assert refreshed["status"] == "pending"
    assert wp.read_lease_registry()["leases"] == []
    status = wp.compute_pool_status(target_claude=3, target_codex=0)
    assert status["current_automatable_count"] == 0


def test_current_filter_excludes_historical_descriptors(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    # Ancient descriptor — no current_active flag, no recent mtime once
    # we backdate.
    p = _write_task(ws["tasks_dir"], "ancient", {
        "task_id": "ancient", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending",
        "created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-01-01T00:00:00Z",
    })
    os.utime(p, (1577836800, 1577836800))
    _write_task(ws["tasks_dir"], "current_p", {
        "task_id": "current_p", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    res = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert res is not None
    assert res["lease"]["task_id"] == "current_p"


def test_worker_picks_next_task_after_child_exits(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    cw = ws["v2_closed_loop_claude_worker"]
    cr = ws["v2_claude_task_runner"]
    monkeypatch.setattr(cr, "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli",
                                 "command_probe": ["/usr/bin/true"], "version": []})
    # Both subprocess.run calls succeed immediately — that's the
    # "short-lived child" scenario. The worker daemon itself must keep
    # iterating.
    import subprocess as sp
    monkeypatch.setattr(cw.subprocess, "run", lambda *a, **k: sp.CompletedProcess(args=a, returncode=0))
    _write_task(ws["tasks_dir"], "current_loop_a", {
        "task_id": "current_loop_a", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    _write_task(ws["tasks_dir"], "current_loop_b", {
        "task_id": "current_loop_b", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    summary = cw.run_worker("claude-1", max_iterations=3, task_timeout=5)
    assert summary["completed"] == 2
    # Both descriptors must be in a terminal state — worker did pick the
    # next task after the first child exited.
    a = json.loads((ws["tasks_dir"] / "current_loop_a.json").read_text())
    b = json.loads((ws["tasks_dir"] / "current_loop_b.json").read_text())
    assert a["status"] == "completed"
    assert b["status"] == "completed"


def test_worker_lane_survives_short_lived_child_exit(isolated_workspace, monkeypatch):
    """The worker daemon's heartbeat is the lane; the per-task child
    process exit must not drop the lane below the minimum."""
    ws = isolated_workspace
    cw = ws["v2_closed_loop_claude_worker"]
    cr = ws["v2_claude_task_runner"]
    wp = ws["v2_closed_loop_worker_pool"]
    monkeypatch.setattr(cr, "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli",
                                 "command_probe": ["/usr/bin/true"], "version": []})
    import subprocess as sp
    monkeypatch.setattr(cw.subprocess, "run", lambda *a, **k: sp.CompletedProcess(args=a, returncode=0))
    _write_task(ws["tasks_dir"], "current_short", {
        "task_id": "current_short", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    cw.run_worker("claude-1", max_iterations=2, task_timeout=5)
    # After the worker's iterations, the most recent heartbeat is
    # ``post_task`` or ``idle_ready`` — either way, the worker is still
    # a counted active lane.
    by_lane = wp.current_alive_workers_by_lane()
    assert len(by_lane[wp.LANE_TYPE_CLAUDE]) == 1


def test_claude_worker_refreshes_heartbeat_while_child_runs(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    cw = ws["v2_closed_loop_claude_worker"]
    wp = ws["v2_closed_loop_worker_pool"]
    _write_task(ws["tasks_dir"], "current_long_child", {
        "task_id": "current_long_child", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    claim = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert claim is not None

    class FakeProc:
        pid = 424242

        def __init__(self):
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            return None if self.poll_count < 3 else 0

        def terminate(self):
            pass

        def kill(self):
            pass

        def wait(self, timeout=None):  # noqa: ARG002
            return 0

    monkeypatch.setattr(cw.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(cw.time, "sleep", lambda *a, **k: None)
    res = cw.execute_task(
        "claude-1", claim,
        {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"]},
        timeout=5,
    )
    assert res["action"] == "completed"
    hb = next(h for h in wp.read_worker_heartbeats() if h["worker_id"] == "claude-1")
    assert hb["state"] == "busy"
    assert hb["child_pid"] == 424242
    reg = wp.read_lease_registry()
    assert reg["leases"][0]["heartbeat_at"] is not None


def test_codex_worker_refreshes_heartbeat_while_review_runs(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    cw = ws["v2_closed_loop_codex_worker"]
    co = ws["v2_codex_review_runner"]
    wp = ws["v2_closed_loop_worker_pool"]
    _write_task(ws["tasks_dir"], "current_codex_long", {
        "task_id": "current_codex_long", "task_type": "CODEX_REVIEW",
        "agent": "codex", "status": "pending", "current_active": True,
    })
    claim = wp.claim_next_task("codex-1", wp.LANE_TYPE_CODEX)
    assert claim is not None

    def _fake_review(*args, heartbeat_callback=None, **kwargs):  # noqa: ARG001
        assert heartbeat_callback is not None
        heartbeat_callback()
        heartbeat_callback()
        return {
            "verdict": "CURRENT_CODEX_PASS",
            "fail_blockers": [],
            "review_md": "review.md",
            "verdict_md": "verdict.md",
        }

    monkeypatch.setattr(co, "run_codex_review", _fake_review)
    res = cw.execute_review(
        "codex-1", claim,
        {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"},
        timeout=5,
    )
    assert res["action"] == "completed"
    hb = next(h for h in wp.read_worker_heartbeats() if h["worker_id"] == "codex-1")
    assert hb["state"] == "busy"
    assert hb["child_review_in_progress"] is True


def test_claude_executor_missing_yields_canonical_blocker(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    cw = ws["v2_closed_loop_claude_worker"]
    cr = ws["v2_claude_task_runner"]
    wp = ws["v2_closed_loop_worker_pool"]
    monkeypatch.setattr(cr, "discover_claude_executor",
                        lambda: {"available": False, "executor": None})
    monkeypatch.setattr(cw.time, "sleep", lambda *a, **k: None)
    cw.run_worker("claude-1", max_iterations=1)
    hbs = wp.read_worker_heartbeats()
    assert any(
        hb["worker_id"] == "claude-1"
        and hb.get("blocker") == "CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED"
        for hb in hbs
    )


def test_codex_executor_missing_yields_canonical_blocker(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    cw = ws["v2_closed_loop_codex_worker"]
    co = ws["v2_codex_review_runner"]
    wp = ws["v2_closed_loop_worker_pool"]
    monkeypatch.setattr(co, "discover_codex_executor",
                        lambda: {"available": False, "executor": None})
    monkeypatch.setattr(cw.time, "sleep", lambda *a, **k: None)
    cw.run_worker("codex-1", max_iterations=1)
    hbs = wp.read_worker_heartbeats()
    assert any(
        hb["worker_id"] == "codex-1"
        and hb.get("blocker") == "CODEX_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED"
        for hb in hbs
    )


def test_active_lane_count_at_least_three_when_work_exists(isolated_workspace):
    """When >=3 worker heartbeats are fresh and current automatable work
    exists, the pool status must report active_lane_count >= 3 and a
    null blocker."""
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    for i in range(3):
        _write_task(ws["tasks_dir"], f"current_min_{i}", {
            "task_id": f"current_min_{i}", "task_type": "CLAUDE_IMPLEMENTATION",
            "agent": "claude", "status": "pending", "current_active": True,
        })
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="busy", current_task_id="current_min_0")
    wp.write_worker_heartbeat("claude-2", wp.LANE_TYPE_CLAUDE, state="busy", current_task_id="current_min_1")
    wp.write_worker_heartbeat("claude-3", wp.LANE_TYPE_CLAUDE, state="busy", current_task_id="current_min_2")
    status = wp.compute_pool_status(target_claude=3, target_codex=0)
    assert status["active_lane_count"] >= 3
    assert status["blocker"] is None


def test_no_live_or_shutdown_approval_in_pool_payload(isolated_workspace):
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    status = wp.compute_pool_status(target_claude=3, target_codex=0)
    blob = json.dumps(status)
    assert "\"approves_live\": true" not in blob
    assert "\"approves_canary\": true" not in blob
    assert "\"approves_legacy_shutdown\": true" not in blob
    assert "\"approves_redis_trim\": true" not in blob
    assert "blocked_human_only" in blob


def test_orchestrator_emits_ready_when_pool_healthy(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    orch = ws["v2_closed_loop_persistent_worker_pool_orchestrator"]
    wp = ws["v2_closed_loop_worker_pool"]
    monkeypatch.setattr(orch, "_systemctl", lambda args: {"cmd": ["systemctl", *args], "returncode": 0, "stdout": "active" if "is-active" in args else "enabled", "stderr": ""})
    for i in range(1, 4):
        wp.write_worker_heartbeat(f"claude-{i}", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    _write_task(ws["tasks_dir"], "current_z", {
        "task_id": "current_z", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    state = orch.run_once(
        install_systemd=False,
        enable_systemd=False,
        direct_spawn=False,
        target_claude=3,
        target_codex=0,
        wait_seconds=0,
    )
    assert state["marker"] == "V2_CLOSED_LOOP_PERSISTENT_WORKER_POOL_READY"
    assert state["ready"] is True
    assert state["pool_status"]["active_lane_count"] >= 3


def test_orchestrator_blocks_on_second_stale_lease(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    orch = ws["v2_closed_loop_persistent_worker_pool_orchestrator"]
    wp = ws["v2_closed_loop_worker_pool"]
    monkeypatch.setattr(orch, "_systemctl", lambda args: {"cmd": ["systemctl", *args], "returncode": 0, "stdout": "active" if "is-active" in args else "enabled", "stderr": ""})
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    wp.write_worker_heartbeat("claude-2", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    wp.write_worker_heartbeat("claude-3", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    _write_task(ws["tasks_dir"], "current_second_stale", {
        "task_id": "current_second_stale", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "pending", "current_active": True,
    })
    res = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert res is not None
    reg = wp.read_lease_registry()
    reg["leases"][0]["was_stale"] = True
    reg["leases"][0]["heartbeat_at"] = "2020-01-01T00:00:00Z"
    wp.write_lease_registry(reg)
    state = orch.run_once(
        install_systemd=False,
        enable_systemd=False,
        direct_spawn=False,
        target_claude=3,
        target_codex=0,
        wait_seconds=0,
    )
    assert state["ready"] is False
    assert "SECOND_STALE_LEASE_REQUIRES_TAKEOVER_OR_OPERATOR_REMEDIATION" in state["blockers"]
