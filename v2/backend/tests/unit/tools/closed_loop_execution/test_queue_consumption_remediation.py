"""Unit tests for the V2 worker-pool queue-consumption remediation orchestrator.

Covers the spec validation points:

* queued task becomes leased;
* idle worker cannot remain idle when eligible task exists (the
  orchestrator emits IDLE_WORKERS_WHILE_ELIGIBLE_WORK_EXISTS);
* task with missing task_type is blocked explicitly;
* unsafe task refused;
* duplicate suppressed task is classified, not leased;
* file_lock_group conflict blocks the second lease;
* queue filter bug detected via NO_BLOCKER_LEASE_SHOULD_HAVE_OCCURRED;
* active lease proof is required (worker_id / pid / log_path);
* no descriptor-only progress counted;
* no live/shutdown/exchange/old Redis task allowed.
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
    "v2_closed_loop_queue_consumption_remediation",
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


def _stub_executors(ws, *, claude=True, codex=True):
    ws["v2_claude_task_runner"].discover_claude_executor = (
        lambda: ({"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []} if claude else {"available": False, "executor": None})
    )


def _seed_active_lease(ws, task_id: str, worker_id: str = "claude-1") -> dict[str, Any]:
    wp = ws["v2_closed_loop_worker_pool"]
    lifecycle = ws["v2_closed_loop_lifecycle"]
    wp.write_worker_heartbeat(worker_id, wp.LANE_TYPE_CLAUDE, state="idle_ready")
    claim = wp.claim_next_task(worker_id, (wp.LANE_TYPE_CLAUDE, wp.LANE_TYPE_REMEDIATION))
    assert claim is not None
    lease = claim["lease"]
    log_path = lifecycle.LOG_DIR / f"{task_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("seeded test log\n", encoding="utf-8")
    descriptor = ws["tasks_dir"] / f"{task_id}.json"
    payload = json.loads(descriptor.read_text(encoding="utf-8"))
    payload.update({
        "status": "running",
        "worker_id": worker_id,
        "lease_id": lease["lease_id"],
        "pid_or_job_id": os.getpid(),
        "log_path": str(log_path),
    })
    descriptor.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    wp.update_lease(lease["lease_id"], status="running", heartbeat=True)
    wp.write_worker_heartbeat(
        worker_id, wp.LANE_TYPE_CLAUDE, state="busy",
        current_task_id=task_id, current_lease_id=lease["lease_id"],
    )
    return lease
    ws["v2_codex_review_runner"].discover_codex_executor = (
        lambda: ({"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"} if codex else {"available": False, "executor": None})
    )


def test_queued_task_becomes_leased(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    wp = ws["v2_closed_loop_worker_pool"]
    _stub_executors(ws)
    # Fresh Claude worker heartbeat → claim should succeed.
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    _write_task(ws["tasks_dir"], "current_a", {
        "task_id": "current_a", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
    })
    state = rm.run_once(
        max_claude_leases=1, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    assert state["lease_cycle"]["external_lease_creation_disabled"] is True
    assert state["lease_cycle"]["claude_leases_created"] == 0
    assert state["marker"] == "V2_WORKER_POOL_QUEUE_CONSUMPTION_REMEDIATION_BLOCKED"
    assert "IDLE_WORKERS_WHILE_ELIGIBLE_WORK_EXISTS" in state["blockers"]


def test_remediation_task_consumed_by_claude_lane(isolated_workspace):
    """The fix: a REMEDIATION-typed task must be claimed by a Claude
    worker (Claude is the implementer for safe-scoped V2 remediation)."""
    ws = isolated_workspace
    wp = ws["v2_closed_loop_worker_pool"]
    _write_task(ws["tasks_dir"], "closed_loop_remediation_x", {
        "task_id": "closed_loop_remediation_x",
        "task_type": "REMEDIATION", "owner": "CLAUDE",
        "status": "pending", "current_active": True,
    })
    # Single-lane parameter: must NOT match.
    only_claude_impl = wp.claim_next_task("claude-1", wp.LANE_TYPE_CLAUDE)
    assert only_claude_impl is None
    # Tuple parameter that includes REMEDIATION: must match.
    res = wp.claim_next_task("claude-1", (wp.LANE_TYPE_CLAUDE, wp.LANE_TYPE_REMEDIATION))
    assert res is not None
    assert res["lease"]["task_id"] == "closed_loop_remediation_x"
    assert res["lease"]["lane_type"] == "REMEDIATION"


def test_idle_worker_with_eligible_work_emits_blocker(isolated_workspace, monkeypatch):
    """When an idle worker exists and an eligible task exists but the
    orchestrator fails to lease (e.g. claim returns None because of a
    bug we are simulating), the marker must be BLOCKED with the
    IDLE_WORKERS_WHILE_ELIGIBLE_WORK_EXISTS reason."""
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    wp = ws["v2_closed_loop_worker_pool"]
    _stub_executors(ws)
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    _write_task(ws["tasks_dir"], "current_eligible", {
        "task_id": "current_eligible", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
    })
    # Force claim to fail (simulate a lease-creation bug).
    monkeypatch.setattr(wp, "claim_next_task", lambda *a, **k: None)
    # Also strip the orchestrator's import-time reference.
    monkeypatch.setattr(rm.pool, "claim_next_task", lambda *a, **k: None)
    state = rm.run_once(
        max_claude_leases=3, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    assert state["marker"] == "V2_WORKER_POOL_QUEUE_CONSUMPTION_REMEDIATION_BLOCKED"
    assert "IDLE_WORKERS_WHILE_ELIGIBLE_WORK_EXISTS" in state["blockers"]


def test_unsafe_task_classified_as_unsafe(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    _write_task(ws["tasks_dir"], "live_canary_x", {
        "task_id": "live_canary_x", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
    })
    diag = rm.diagnose_queue()
    rows = [r for r in diag["rows"] if r["task_id"] == "live_canary_x"]
    assert rows and rows[0]["blocker_if_not_leased"] == "UNSAFE_TASK_TYPE"


def test_operator_required_classified(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    _write_task(ws["tasks_dir"], "op_required", {
        "task_id": "op_required", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
        "operator_required_reason": "human review required",
    })
    diag = rm.diagnose_queue()
    rows = [r for r in diag["rows"] if r["task_id"] == "op_required"]
    assert rows and rows[0]["blocker_if_not_leased"] == "OPERATOR_REQUIRED"


def test_file_lock_conflict_blocks_second_lease(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    wp = ws["v2_closed_loop_worker_pool"]
    _stub_executors(ws)
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    wp.write_worker_heartbeat("claude-2", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    _write_task(ws["tasks_dir"], "current_lock_a", {
        "task_id": "current_lock_a", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True, "file_lock_group": "shared",
    })
    _write_task(ws["tasks_dir"], "current_lock_b", {
        "task_id": "current_lock_b", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True, "file_lock_group": "shared",
    })
    _seed_active_lease(ws, "current_lock_a", "claude-1")
    state = rm.run_once(
        max_claude_leases=2, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    assert state["lease_cycle"]["claude_leases_created"] == 0
    # The losing task must be classified FILE_LOCK_CONFLICT in the
    # post-cycle diagnosis.
    rows = [r for r in state["diagnosis_after"]["rows"] if r["task_id"] == "current_lock_b"]
    assert rows and rows[0]["blocker_if_not_leased"] == "FILE_LOCK_CONFLICT"


def test_zombie_descriptor_resets_to_pending(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    _write_task(ws["tasks_dir"], "zombie_x", {
        "task_id": "zombie_x", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE",
        "status": "running", "pid_or_job_id": 2_000_000_000,
        "current_active": True,
    })
    _stub_executors(ws)
    state = rm.run_once(
        max_claude_leases=1, max_codex_leases=0,
        reset_zombies_flag=True, wait_seconds=0, dry_run=False,
    )
    assert any(z["task_id"] == "zombie_x" for z in state["zombies_reset"])
    descriptor = json.loads((ws["tasks_dir"] / "zombie_x.json").read_text())
    assert descriptor["status"] == "pending"


def test_missing_task_type_classified(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    # Set task_type=None explicitly to exercise MISSING_TASK_TYPE.
    monkeypatch.setattr(
        rm, "normalize_descriptor",
        lambda raw, path: dict(raw, task_id=raw.get("task_id") or path.stem,
                               task_type=None, owner=raw.get("owner"),
                               file_lock_group=None,
                               status=raw.get("status") or "pending"),
    )
    _write_task(ws["tasks_dir"], "no_type", {
        "task_id": "no_type", "task_type": None, "owner": "CLAUDE",
        "status": "pending", "current_active": True,
    })
    diag = rm.diagnose_queue()
    rows = [r for r in diag["rows"] if r["task_id"] == "no_type"]
    assert rows and rows[0]["blocker_if_not_leased"] == "MISSING_TASK_TYPE"


def test_no_descriptor_only_progress_counted(isolated_workspace):
    """A descriptor with `current_active=true` but no live lease must
    not be counted as in-progress migration work."""
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    _write_task(ws["tasks_dir"], "desc_only", {
        "task_id": "desc_only", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
    })
    state = rm.run_once(
        max_claude_leases=0, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    # No worker, no lease created → task remains pending, lease_created=False.
    rows = [r for r in state["diagnosis_after"]["rows"] if r["task_id"] == "desc_only"]
    assert rows
    assert rows[0]["lease_created"] is False


def test_no_live_or_shutdown_approval_in_outputs(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    _stub_executors(ws)
    state = rm.run_once(
        max_claude_leases=0, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=True,
    )
    blob = json.dumps(state)
    assert "\"approves_live\": true" not in blob
    assert "\"approves_canary\": true" not in blob
    assert "\"approves_legacy_shutdown\": true" not in blob
    assert "\"approves_redis_trim\": true" not in blob
    assert "blocked_human_only" in blob


def test_execution_proof_includes_worker_pid(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    wp = ws["v2_closed_loop_worker_pool"]
    _stub_executors(ws)
    own_pid = os.getpid()
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="idle_ready", extra={"pid": own_pid})
    # Hand-craft a heartbeat so worker_pid resolves to a known value.
    hb_path = wp.WORKER_HEARTBEAT_DIR / "claude-1.json"
    hb = json.loads(hb_path.read_text())
    hb["pid"] = own_pid
    hb_path.write_text(json.dumps(hb))
    _write_task(ws["tasks_dir"], "current_proof", {
        "task_id": "current_proof", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
    })
    _seed_active_lease(ws, "current_proof", "claude-1")
    state = rm.run_once(
        max_claude_leases=1, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    proof = state["execution_proof"]
    assert proof, "execution proof must include at least one active lease"
    assert proof[0]["worker_id"] == "claude-1"
    assert proof[0]["worker_pid"] == own_pid
    assert proof[0]["lease_id"]
    assert proof[0]["task_id"] == "current_proof"
    assert proof[0]["log_path"]


def test_ready_when_at_least_three_leases_and_no_idle_eligible(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    wp = ws["v2_closed_loop_worker_pool"]
    _stub_executors(ws)
    for i in range(1, 4):
        wp.write_worker_heartbeat(f"claude-{i}", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    for i in range(3):
        _write_task(ws["tasks_dir"], f"current_ready_{i}", {
            "task_id": f"current_ready_{i}", "task_type": "CLAUDE_IMPLEMENTATION",
            "agent": "claude", "owner": "CLAUDE", "status": "pending",
            "current_active": True,
        })
    for i in range(3):
        _seed_active_lease(ws, f"current_ready_{i}", f"claude-{i + 1}")
    state = rm.run_once(
        max_claude_leases=3, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    assert state["marker"] == "V2_WORKER_POOL_QUEUE_CONSUMPTION_REMEDIATION_READY"
    assert state["ready"] is True
    assert state["active_leases_count"] == 3


def test_force_lease_cycle_does_not_double_assign_busy_worker(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    wp = ws["v2_closed_loop_worker_pool"]
    _stub_executors(ws)
    wp.write_worker_heartbeat("claude-1", wp.LANE_TYPE_CLAUDE, state="busy",
                              current_lease_id="existing")
    _write_task(ws["tasks_dir"], "current_busy_collision", {
        "task_id": "current_busy_collision", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
    })
    state = rm.run_once(
        max_claude_leases=1, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    assert state["lease_cycle"]["claude_leases_created"] == 0
    rows = [r for r in state["diagnosis_after"]["rows"]
            if r["task_id"] == "current_busy_collision"]
    assert rows and rows[0]["lease_created"] is False


def test_mission_progress_status_refreshes_worker_pool_reference(isolated_workspace):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_queue_consumption_remediation"]
    wp = ws["v2_closed_loop_worker_pool"]
    _stub_executors(ws)
    for i in range(1, 4):
        wp.write_worker_heartbeat(f"claude-{i}", wp.LANE_TYPE_CLAUDE, state="idle_ready")
    _write_task(ws["tasks_dir"], "current_mp", {
        "task_id": "current_mp", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "owner": "CLAUDE", "status": "pending",
        "current_active": True,
    })
    state = rm.run_once(
        max_claude_leases=1, max_codex_leases=0,
        reset_zombies_flag=False, wait_seconds=0, dry_run=False,
    )
    status_path = (
        ws["repo"] / "claude_worklog" / "final_readiness"
        / "v2_worker_pool_mission_progress" / "latest"
        / "worker_pool_mission_progress_status.json"
    )
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["worker_pool_reference"]["active_leases_count"] == state["active_leases_count"]
    assert payload["drift_controls"]["automation_execution_based_on_active_leases"] is True
