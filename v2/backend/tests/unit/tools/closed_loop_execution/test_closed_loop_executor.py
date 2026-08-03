"""Unit tests for the V2 closed-loop Claude/Codex execution engine.

Covers the spec-mandated validation points:

* pending task becomes running when the executor is available;
* no executor available blocks the READY marker;
* stale task relaunches once, second stall creates a takeover descriptor;
* Codex FAIL creates a remediation descriptor;
* Codex PASS completes the task;
* duplicate suppression works;
* file locks prevent parallel edits on the same lock group;
* active lane count uses real running pids, not descriptors alone;
* no live / shutdown / exchange-mutation approval is ever emitted.
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
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    """Reload the closed-loop modules against a sandboxed REPO_ROOT."""
    repo = tmp_path / "AI BOT REBUILD"
    (repo / "claude_worklog" / "agent_supervisor" / "tasks").mkdir(parents=True)
    (repo / "claude_worklog" / "tools").mkdir(parents=True)
    (repo / "v2" / "frontend" / "public").mkdir(parents=True)

    # Place a copy of the shared lifecycle module so its REPO_ROOT
    # resolution lands inside the sandbox.
    for mod_name in (
        "v2_closed_loop_lifecycle",
        "v2_claude_task_runner",
        "v2_codex_review_runner",
        "v2_closed_loop_claude_codex_executor",
    ):
        sandbox_path = repo / "claude_worklog" / "tools" / f"{mod_name}.py"
        sandbox_path.write_text(
            (TOOLS_DIR / f"{mod_name}.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    monkeypatch.syspath_prepend(str(repo / "claude_worklog" / "tools"))
    # Drop any previously cached version pointing at the real repo so
    # the import below resolves REPO_ROOT against the sandbox copy.
    for mod_name in (
        "v2_closed_loop_lifecycle",
        "v2_claude_task_runner",
        "v2_codex_review_runner",
        "v2_closed_loop_claude_codex_executor",
    ):
        sys.modules.pop(mod_name, None)
    lifecycle = importlib.import_module("v2_closed_loop_lifecycle")
    claude_runner = importlib.import_module("v2_claude_task_runner")
    codex_runner = importlib.import_module("v2_codex_review_runner")
    coordinator = importlib.import_module("v2_closed_loop_claude_codex_executor")
    return {
        "repo": repo,
        "tasks_dir": repo / "claude_worklog" / "agent_supervisor" / "tasks",
        "lifecycle": lifecycle,
        "claude_runner": claude_runner,
        "codex_runner": codex_runner,
        "coordinator": coordinator,
    }


def _write_task(tasks_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    p = tasks_dir / f"{name}.json"
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def _executor_available(name: str = "test_executor") -> dict[str, Any]:
    return {"available": True, "executor": name, "command_probe": ["/usr/bin/true"], "version": []}


def _executor_missing() -> dict[str, Any]:
    return {"available": False, "executor": None, "marker": "CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED"}


def test_pending_task_becomes_running_when_executor_available(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["claude_runner"]
    monkeypatch.setattr(runner, "discover_claude_executor", lambda: _executor_available("claude_cli"))

    launches: list[dict[str, Any]] = []

    def _fake_launch(descriptor_path, d, executor, *, dry_run=False):
        launches.append({"task_id": d["task_id"]})
        return {"action": "launched", "task_id": d["task_id"], "pid": 99999, "log_path": "stub.log"}

    monkeypatch.setattr(runner, "launch_claude_task", _fake_launch)

    path = _write_task(ws["tasks_dir"], "001_claude_fix_alpha", {
        "task_id": "001_claude_fix_alpha",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
        "prompt": "noop",
    })
    state = runner.run_once(max_lanes=3, dry_run=False)
    assert len(state["dispatched"]) == 1
    assert launches == [{"task_id": "001_claude_fix_alpha"}]
    refreshed = json.loads(path.read_text())
    assert refreshed["status"] == "running"
    assert refreshed["pid_or_job_id"] == 99999


def test_no_executor_blocks_ready(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["claude_runner"]
    coord = ws["coordinator"]
    monkeypatch.setattr(runner, "discover_claude_executor", lambda: _executor_missing())
    monkeypatch.setattr(ws["codex_runner"], "discover_codex_executor", lambda: {"available": False, "executor": None})

    _write_task(ws["tasks_dir"], "002_claude_fix_beta", {
        "task_id": "002_claude_fix_beta",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
    })
    state = coord.run_once(claude_lanes=3, codex_lanes=3, target_lanes=3, dry_run=False)
    assert state["marker"] == "V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_BLOCKED"
    assert state["ready"] is False


def test_stale_task_relaunches_once_then_takeover(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["claude_runner"]
    lifecycle = ws["lifecycle"]
    monkeypatch.setattr(runner, "discover_claude_executor", lambda: _executor_available())
    monkeypatch.setattr(runner, "descriptor_running", lambda d: True)
    monkeypatch.setattr(runner, "stalled", lambda d: True)

    relaunches: list[str] = []

    def _fake_launch(descriptor_path, d, executor, *, dry_run=False):
        relaunches.append(d["task_id"])
        return {"action": "launched", "task_id": d["task_id"], "pid": 12345, "log_path": "stub.log"}

    monkeypatch.setattr(runner, "launch_claude_task", _fake_launch)

    path = _write_task(ws["tasks_dir"], "003_claude_fix_gamma", {
        "task_id": "003_claude_fix_gamma",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "running",
        "pid_or_job_id": 1,
        "stall_count": 0,
        "max_stall_relaunches": 1,
    })

    # First pass: relaunch.
    runner.run_once(max_lanes=3, dry_run=False)
    d = json.loads(path.read_text())
    assert d["stall_count"] == 1
    assert relaunches == ["003_claude_fix_gamma"]

    # Second pass: stall again -> takeover created, status=stale.
    runner.run_once(max_lanes=3, dry_run=False)
    d = json.loads(path.read_text())
    assert d["status"] == "stale"
    assert d["stall_count"] == 2
    takeover = ws["tasks_dir"] / "closed_loop_takeover_003_claude_fix_gamma.json"
    assert takeover.exists()
    tk = json.loads(takeover.read_text())
    assert tk["task_type"] == "CODEX_TAKEOVER"
    assert tk["safety"]["live_gate"] == "blocked_human_only"


def test_codex_pass_completes_task(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["codex_runner"]
    monkeypatch.setattr(runner, "discover_codex_executor", lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})

    def _fake_review(descriptor_path, d, executor, *, dry_run, timeout=900):
        return {
            "action": "completed",
            "task_id": d["task_id"],
            "verdict": "ALPHA_LANE_CODEX_PASS",
            "fail_blockers": [],
            "started_utc": "2026-01-01T00:00:00Z",
            "ended_utc": "2026-01-01T00:01:00Z",
            "returncode": 0,
            "timed_out": False,
            "review_md": "stub.md",
            "verdict_md": "stub_go.md",
            "log_path": "stub.log",
            "command_form": ["codex", "review", "--uncommitted"],
        }
    monkeypatch.setattr(runner, "run_codex_review", _fake_review)

    path = _write_task(ws["tasks_dir"], "004_codex_review_alpha", {
        "task_id": "004_codex_review_alpha",
        "task_type": "CODEX_REVIEW",
        "agent": "codex",
        "status": "pending",
    })
    state = runner.run_once(max_lanes=3, dry_run=False)
    assert state["reviews"][0]["verdict"].endswith("_CODEX_PASS")
    d = json.loads(path.read_text())
    assert d["status"] == "completed"


def test_codex_fail_creates_remediation(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["codex_runner"]
    monkeypatch.setattr(runner, "discover_codex_executor", lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})

    def _fake_review(descriptor_path, d, executor, *, dry_run, timeout=900):
        return {
            "action": "failed",
            "task_id": d["task_id"],
            "verdict": "BETA_LANE_CODEX_FAIL",
            "fail_blockers": ["Blocker: dataset quality counter undercounts insufficient_evidence"],
            "started_utc": "2026-01-01T00:00:00Z",
            "ended_utc": "2026-01-01T00:01:00Z",
            "returncode": 1,
            "timed_out": False,
            "review_md": "stub.md",
            "verdict_md": "stub_go.md",
            "log_path": "stub.log",
            "command_form": ["codex", "review", "--uncommitted"],
        }
    monkeypatch.setattr(runner, "run_codex_review", _fake_review)

    path = _write_task(ws["tasks_dir"], "005_codex_review_beta", {
        "task_id": "005_codex_review_beta",
        "task_type": "CODEX_REVIEW",
        "agent": "codex",
        "status": "pending",
    })
    state = runner.run_once(max_lanes=3, dry_run=False)
    assert any(r["task_id"] == "005_codex_review_beta" for r in state["remediations_created"])
    rem_path = ws["tasks_dir"] / "closed_loop_remediation_005_codex_review_beta.json"
    assert rem_path.exists()
    rem = json.loads(rem_path.read_text())
    assert rem["task_type"] == "REMEDIATION"
    assert rem["safety"]["approves_live"] is False
    d = json.loads(path.read_text())
    assert d["status"] == "failed"


def test_codex_fail_with_live_blocker_routes_operator(isolated_workspace, monkeypatch):
    """Blockers that mention live trading / shutdown must NOT auto-spawn
    remediation — they go to the operator instead."""
    ws = isolated_workspace
    runner = ws["codex_runner"]
    monkeypatch.setattr(runner, "discover_codex_executor", lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    monkeypatch.setattr(runner, "run_codex_review", lambda descriptor_path, d, executor, *, dry_run, timeout=900: {
        "action": "failed",
        "task_id": d["task_id"],
        "verdict": "GAMMA_LANE_CODEX_FAIL",
        "fail_blockers": ["Blocker: live trading kill switch must be reviewed by operator"],
        "started_utc": "0", "ended_utc": "0", "returncode": 1, "timed_out": False,
        "review_md": "stub.md", "verdict_md": "stub_go.md", "log_path": "stub.log",
        "command_form": ["codex", "review", "--uncommitted"],
    })
    _write_task(ws["tasks_dir"], "006_codex_review_gamma", {
        "task_id": "006_codex_review_gamma",
        "task_type": "CODEX_REVIEW",
        "agent": "codex",
        "status": "pending",
    })
    state = runner.run_once(max_lanes=3, dry_run=False)
    assert not state["remediations_created"], "live blocker must not auto-remediate"
    rem_path = ws["tasks_dir"] / "closed_loop_remediation_006_codex_review_gamma.json"
    assert not rem_path.exists()
    assert any(o["task_id"] == "006_codex_review_gamma" for o in state["operator_required"])


def test_duplicate_suppression(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["claude_runner"]
    monkeypatch.setattr(runner, "discover_claude_executor", lambda: _executor_available())
    monkeypatch.setattr(runner, "launch_claude_task", lambda *a, **k: {
        "action": "launched", "task_id": "x", "pid": 1, "log_path": "x"})

    _write_task(ws["tasks_dir"], "007_claude_fix_dup_a", {
        "task_id": "007_claude_fix_dup_a",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
        "duplicate_suppression_key": "shared-key",
    })
    second = _write_task(ws["tasks_dir"], "008_claude_fix_dup_b", {
        "task_id": "008_claude_fix_dup_b",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
        "duplicate_suppression_key": "shared-key",
    })
    runner.run_once(max_lanes=3, dry_run=False)
    d = json.loads(second.read_text())
    assert d["status"] == "duplicate_suppressed"


def test_file_lock_blocks_parallel_edits(isolated_workspace):
    ws = isolated_workspace
    lifecycle = ws["lifecycle"]
    with lifecycle.file_lock("shared-lock-group") as a:
        assert a is True
        with lifecycle.file_lock("shared-lock-group", timeout=0.05) as b:
            assert b is False


def test_active_lane_count_uses_real_pids(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    coord = ws["coordinator"]
    lifecycle = ws["lifecycle"]
    # Descriptor claims status=running with a dead pid; coordinator must
    # NOT count it as an active lane.
    _write_task(ws["tasks_dir"], "009_claude_fix_zombie", {
        "task_id": "009_claude_fix_zombie",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "running",
        "pid_or_job_id": 2_000_000_000,  # certainly dead
    })
    descriptors = coord.collect_descriptors()
    active = coord.count_real_active_lanes(descriptors)
    assert active == {"claude": 0, "codex": 0}


def test_no_live_or_shutdown_approval_in_outputs(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    coord = ws["coordinator"]
    monkeypatch.setattr(ws["claude_runner"], "discover_claude_executor", lambda: _executor_available())
    monkeypatch.setattr(ws["codex_runner"], "discover_codex_executor", lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    monkeypatch.setattr(ws["claude_runner"], "launch_claude_task", lambda *a, **k: {"action": "launched", "task_id": "x", "pid": 1, "log_path": "x"})
    monkeypatch.setattr(ws["codex_runner"], "run_codex_review", lambda *a, **k: {
        "action": "completed", "task_id": "x", "verdict": "X_CODEX_PASS", "fail_blockers": [],
        "started_utc": "0", "ended_utc": "0", "returncode": 0, "timed_out": False,
        "review_md": "stub", "verdict_md": "stub", "log_path": "stub", "command_form": ["codex"],
    })
    state = coord.run_once(claude_lanes=3, codex_lanes=3, target_lanes=3, dry_run=False)
    blob = json.dumps(state)
    assert "\"approves_live\": true" not in blob
    assert "\"approves_canary\": true" not in blob
    assert "\"approves_legacy_shutdown\": true" not in blob
    assert "\"approves_redis_trim\": true" not in blob
    assert "blocked_human_only" in blob


def test_below_minimum_lanes_blocks(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    coord = ws["coordinator"]
    # Executors available, but the launch path is mocked to refuse dispatch.
    # The pending Claude task therefore stays pending, automatable_work_count
    # stays > 0, and active_lane_count is 0 -> ACTIVE_LANES_BELOW_MINIMUM.
    monkeypatch.setattr(ws["claude_runner"], "discover_claude_executor", lambda: _executor_available())
    monkeypatch.setattr(ws["codex_runner"], "discover_codex_executor", lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    monkeypatch.setattr(
        ws["claude_runner"], "launch_claude_task",
        lambda *a, **k: {"action": "failed_launch", "task_id": "blocked", "error": "stub"},
    )
    _write_task(ws["tasks_dir"], "010_claude_fix_idle", {
        "task_id": "010_claude_fix_idle",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
    })
    state = coord.run_once(claude_lanes=3, codex_lanes=3, target_lanes=3, dry_run=False)
    util = state["utilization"]
    assert util["automatable_work_count"] >= 1
    assert util["status"] == "BLOCKED"
    assert util["blocker"] == "ACTIVE_LANES_BELOW_MINIMUM"
    assert state["marker"] == "V2_CLOSED_LOOP_CLAUDE_CODEX_EXECUTION_ENGINE_BLOCKED"


def test_source_truth_completed_descriptor_is_not_dispatched_without_explicit_reopen(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["claude_runner"]
    monkeypatch.setattr(runner, "discover_claude_executor", lambda: _executor_available())
    monkeypatch.setattr(runner, "launch_claude_task", lambda *a, **k: {
        "action": "launched", "task_id": "x", "pid": 1, "log_path": "x",
    })
    task = _write_task(
        ws["tasks_dir"],
        "011_claude_fix_omega",
        {
            "task_id": "011_claude_fix_omega",
            "task_type": "CLAUDE_IMPLEMENTATION",
            "agent": "claude",
            "status": "pending",
            "resolved_from_source_truth": True,
            "source_truth_superseded": True,
            "source_truth_status": "completed",
        },
    )
    state = runner.run_once(max_lanes=3, dry_run=False)
    assert state["dispatched"] == []
    refreshed = json.loads(task.read_text(encoding="utf-8"))
    assert refreshed["status"] == "pending"
    assert refreshed["resolved_from_source_truth"] is True


def test_codex_source_truth_completed_review_descriptor_not_dispatched_without_explicit_reopen(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    runner = ws["codex_runner"]
    monkeypatch.setattr(runner, "discover_codex_executor", lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    monkeypatch.setattr(runner, "run_codex_review", lambda *a, **k: {
        "action": "completed", "task_id": "y", "verdict": "Z_CODEX_PASS",
        "fail_blockers": [], "started_utc": "0", "ended_utc": "0", "returncode": 0, "timed_out": False,
        "review_md": "stub", "verdict_md": "stub", "log_path": "stub.log", "command_form": ["codex"],
    })
    task = _write_task(
        ws["tasks_dir"],
        "012_codex_review_omega",
        {
            "task_id": "012_codex_review_omega",
            "task_type": "CODEX_REVIEW",
            "agent": "codex",
            "status": "pending",
            "resolved_from_source_truth": True,
            "source_truth_superseded": True,
            "source_truth_status": "completed",
        },
    )
    state = runner.run_once(max_lanes=3, dry_run=False)
    assert state["reviews"] == []
    refreshed = json.loads(task.read_text(encoding="utf-8"))
    assert refreshed["status"] == "pending"


def test_reconcile_source_truth_completion_marks_running_terminal_without_reopen(isolated_workspace):
    ws = isolated_workspace
    lifecycle = ws["lifecycle"]
    task = _write_task(
        ws["tasks_dir"],
        "013_claude_fix_source_truth_running",
        {
            "task_id": "013_claude_fix_source_truth_running",
            "task_type": "CLAUDE_IMPLEMENTATION",
            "agent": "claude",
            "status": "running",
            "prompt": "original narrow scope",
            "pid_or_job_id": 123456789,
            "worker_id": "claude-1",
            "lease_id": "lease-1",
        },
    )
    state_dir = ws["repo"] / "claude_worklog" / "agent_supervisor" / "state" / "tasks"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "013_claude_fix_source_truth_running.json").write_text(
        json.dumps({
            "task_id": "013_claude_fix_source_truth_running",
            "status": "completed",
            "last_run": {"end": "2026-05-24T04:52:45.057758+00:00"},
        }),
        encoding="utf-8",
    )
    result = lifecycle.reconcile_source_truth_completions(
        task_paths=[task],
        apply_updates=True,
    )
    assert result["completed_from_source_truth_count"] == 1
    assert result["redispatch_suppressed_count"] == 1
    assert result["leases_to_clear"] == ["013_claude_fix_source_truth_running"]
    refreshed = json.loads(task.read_text(encoding="utf-8"))
    assert refreshed["status"] == "completed"
    assert refreshed["prompt"] == "original narrow scope"
    assert refreshed["resolved_from_source_truth"] is True
    assert refreshed["source_truth_superseded"] is True
    assert refreshed["source_truth_status"] == "completed"
    assert "pid_or_job_id" not in refreshed
    assert "worker_id" not in refreshed
    assert "lease_id" not in refreshed
    assert "source_truth_reopened" not in refreshed
    assert "reopen_from_source_truth" not in refreshed


def test_reconcile_source_truth_completed_descriptor_clears_stale_active_lease(isolated_workspace):
    ws = isolated_workspace
    lifecycle = ws["lifecycle"]
    task_id = "014_codex_review_source_truth_done"
    task = _write_task(
        ws["tasks_dir"],
        task_id,
        {
            "task_id": task_id,
            "task_type": "CODEX_REVIEW",
            "agent": "codex",
            "status": "completed",
            "resolved_from_source_truth": True,
            "source_truth_superseded": True,
            "source_truth_status": "completed",
        },
    )
    state_dir = ws["repo"] / "claude_worklog" / "agent_supervisor" / "state" / "tasks"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{task_id}.json").write_text(
        json.dumps({
            "task_id": task_id,
            "status": "completed",
            "last_status_change_ts": "2026-05-24T11:28:53.617463+00:00",
        }),
        encoding="utf-8",
    )
    lifecycle.LIFECYCLE_DIR.mkdir(parents=True, exist_ok=True)
    lifecycle.write_json_atomic(
        lifecycle.WORKER_LEASES_PATH,
        {
            "schema_version": "v2_closed_loop_worker_leases_v1",
            "leases": [
                {
                    "lease_id": "lease-014",
                    "task_id": task_id,
                    "status": "running",
                    "heartbeat_at": "2026-05-25T04:27:37Z",
                }
            ],
        },
    )
    result = lifecycle.reconcile_source_truth_completions(
        task_paths=[task],
        apply_updates=True,
    )
    assert result["completed_from_source_truth_count"] == 0
    assert result["already_completed_source_truth_count"] == 1
    assert result["leases_to_clear"] == [task_id]
    clear = lifecycle.clear_active_worker_leases(result["leases_to_clear"])
    assert clear["cleared_count"] == 1
    registry = json.loads(lifecycle.WORKER_LEASES_PATH.read_text(encoding="utf-8"))
    assert registry["leases"][0]["status"] == "completed"
    assert registry["leases"][0]["failure_reason"] == "source_truth_completed"


def test_pair_codex_reviews_skips_source_truth_completed_claude_task(isolated_workspace):
    ws = isolated_workspace
    coord = ws["coordinator"]
    artifact = ws["repo"] / "claude_worklog" / "final_readiness" / "old_task" / "artifact.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}", encoding="utf-8")
    descriptor = {
        "task_id": "015_claude_fix_old_completed",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "completed",
        "expected_output_paths": [
            "claude_worklog/final_readiness/old_task/artifact.json",
        ],
        "resolved_from_source_truth": True,
        "source_truth_superseded": True,
        "source_truth_status": "completed",
    }
    enqueued = coord.pair_codex_reviews([descriptor], dry_run=False)
    assert enqueued == []
    assert not (ws["tasks_dir"] / "closed_loop_codex_review_015_claude_fix_old_completed.json").exists()


def test_verdict_extractor_picks_last_pass(isolated_workspace):
    ws = isolated_workspace
    runner = ws["codex_runner"]
    verdict, blockers = runner.extract_verdict("noise\nALPHA_LANE_CODEX_FAIL\nfinal: BETA_LANE_CODEX_PASS\n")
    assert verdict == "BETA_LANE_CODEX_PASS"
    assert blockers == []
    verdict, blockers = runner.extract_verdict("blocker: needs fix\nGAMMA_LANE_CODEX_FAIL\n")
    assert verdict == "GAMMA_LANE_CODEX_FAIL"
    assert blockers and "blocker" in blockers[0].lower()
