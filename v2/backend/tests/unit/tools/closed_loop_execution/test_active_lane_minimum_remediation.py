"""Unit tests for the V2 active-lane-minimum remediation orchestrator.

Covers the spec validation points:

* root cause classifier emits one of the documented codes;
* zombie running descriptors (dead pid) get reset to pending;
* a 3rd Claude lane is dispatched when safe pending work exists;
* a Codex real-job proof is captured when pending Codex work exists,
  and gracefully reports no_current_codex_work otherwise;
* synthetic probes are excluded from the active-lane proof;
* missing Claude CLI yields EXECUTOR_AUTH_OR_BINARY_MISSING;
* only 2 safe tasks → ONLY_TWO_SAFE_TASKS_AVAILABLE;
* no live / shutdown / exchange-mutation approval is ever surfaced.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
MODULES = (
    "v2_closed_loop_lifecycle",
    "v2_claude_task_runner",
    "v2_codex_review_runner",
    "v2_closed_loop_claude_codex_executor",
    "v2_current_work_filter",
    "v2_closed_loop_real_mode_enablement",
    "v2_closed_loop_active_lane_minimum_remediation",
)


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    repo = tmp_path / "AI BOT REBUILD"
    (repo / "claude_worklog" / "agent_supervisor" / "tasks").mkdir(parents=True)
    (repo / "claude_worklog" / "tools").mkdir(parents=True)
    (repo / "claude_worklog" / "final_readiness" / "v2_closed_loop_execution_real_mode_enablement" / "latest").mkdir(parents=True)
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
    return {"repo": repo, "tasks_dir": repo / "claude_worklog" / "agent_supervisor" / "tasks", **modules}


def _write_task(tasks_dir: Path, task_id: str, payload: dict[str, Any]) -> Path:
    p = tasks_dir / f"{task_id}.json"
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def _stub_systemctl_ok():
    return lambda args: {"cmd": ["systemctl", *args], "returncode": 0, "stdout": "active" if "is-active" in args else "enabled", "stderr": ""}


def test_classifier_executor_missing(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_active_lane_minimum_remediation"]
    monkeypatch.setattr(rm, "_run_systemctl", _stub_systemctl_ok())
    monkeypatch.setattr(ws["v2_claude_task_runner"], "discover_claude_executor",
                        lambda: {"available": False, "executor": None})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    _write_task(ws["tasks_dir"], "current_a", {
        "task_id": "current_a", "task_type": "CLAUDE_IMPLEMENTATION", "agent": "claude",
        "status": "pending", "current_active": True,
    })
    snap = rm.collect_state()
    rc = rm.classify_root_cause(snap)
    assert rc["code"] == "EXECUTOR_AUTH_OR_BINARY_MISSING"


def test_classifier_only_two_safe_tasks(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_active_lane_minimum_remediation"]
    monkeypatch.setattr(rm, "_run_systemctl", _stub_systemctl_ok())
    monkeypatch.setattr(ws["v2_claude_task_runner"], "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    for tid in ("current_a", "current_b"):
        _write_task(ws["tasks_dir"], tid, {
            "task_id": tid, "task_type": "CLAUDE_IMPLEMENTATION", "agent": "claude",
            "status": "pending", "current_active": True,
        })
    snap = rm.collect_state()
    rc = rm.classify_root_cause(snap)
    assert rc["code"] == "ONLY_TWO_SAFE_TASKS_AVAILABLE"


def test_zombie_reset_and_third_lane_dispatch(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_active_lane_minimum_remediation"]
    monkeypatch.setattr(rm, "_run_systemctl", _stub_systemctl_ok())
    cr = ws["v2_claude_task_runner"]
    co = ws["v2_codex_review_runner"]
    monkeypatch.setattr(cr, "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []})
    monkeypatch.setattr(co, "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})

    own_pid = os.getpid()

    def _fake_launch(descriptor_path, d, executor, *, dry_run=False):
        log_path = ws["v2_closed_loop_lifecycle"].LOG_DIR / f"{d['task_id']}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("ok\n", encoding="utf-8")
        ws["v2_closed_loop_lifecycle"].write_heartbeat(d["task_id"], own_pid, {"cmd": ["stub"]})
        return {"action": "launched", "task_id": d["task_id"], "pid": own_pid, "log_path": str(log_path)}
    monkeypatch.setattr(cr, "launch_claude_task", _fake_launch)
    monkeypatch.setattr(co, "run_codex_review", lambda *a, **k: {
        "action": "completed", "task_id": "x", "verdict": "X_CODEX_PASS",
        "fail_blockers": [], "started_utc": "0", "ended_utc": "0",
        "returncode": 0, "timed_out": False,
        "review_md": "stub", "verdict_md": "stub", "log_path": "stub",
        "command_form": ["codex", "exec", "review"],
    })

    # Two live lanes (real pid this process) + one zombie + one pending.
    ws["v2_closed_loop_lifecycle"].write_heartbeat("live_a", own_pid, {"cmd": ["stub"]})
    ws["v2_closed_loop_lifecycle"].write_heartbeat("live_b", own_pid, {"cmd": ["stub"]})
    _write_task(ws["tasks_dir"], "live_a", {
        "task_id": "live_a", "task_type": "CLAUDE_IMPLEMENTATION", "agent": "claude",
        "status": "running", "current_active": True, "pid_or_job_id": own_pid,
    })
    _write_task(ws["tasks_dir"], "live_b", {
        "task_id": "live_b", "task_type": "CLAUDE_IMPLEMENTATION", "agent": "claude",
        "status": "running", "current_active": True, "pid_or_job_id": own_pid,
    })
    _write_task(ws["tasks_dir"], "zombie", {
        "task_id": "zombie", "task_type": "CLAUDE_IMPLEMENTATION", "agent": "claude",
        "status": "running", "current_active": True, "pid_or_job_id": 2_000_000_000,
    })
    _write_task(ws["tasks_dir"], "pending_c", {
        "task_id": "pending_c", "task_type": "CLAUDE_IMPLEMENTATION", "agent": "claude",
        "status": "pending", "current_active": True,
    })

    state = rm.run_once(
        allow_real_dispatch=True,
        target_lanes=3,
        wait_after_dispatch_seconds=0,
        reset_zombies_flag=True,
    )
    assert state["zombies_reset"], "zombie should have been reset"
    assert state["third_lane_result"]["dispatched"] is True
    assert state["third_lane_result"]["candidate"] == "pending_c"
    assert state["utilization"]["active_lane_count"] >= 3
    assert state["marker"] == "V2_CLOSED_LOOP_ACTIVE_LANE_MINIMUM_REMEDIATION_READY"
    assert state["blockers"] == []


def test_synthetic_probes_excluded_from_proof(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_active_lane_minimum_remediation"]
    monkeypatch.setattr(rm, "_run_systemctl", _stub_systemctl_ok())
    own_pid = os.getpid()
    ws["v2_closed_loop_lifecycle"].write_heartbeat("real_mode_probe_claude_alpha", own_pid, {"cmd": ["stub"]})
    _write_task(ws["tasks_dir"], "real_mode_probe_claude_alpha", {
        "task_id": "real_mode_probe_claude_alpha", "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude", "status": "running", "current_active": True,
        "pid_or_job_id": own_pid,
    })
    proof = rm.collect_active_lane_proof()
    assert all(not p["task_id"].startswith("real_mode_probe_") for p in proof), proof


def test_codex_real_job_proof_records_pid_and_log(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_active_lane_minimum_remediation"]
    monkeypatch.setattr(rm, "_run_systemctl", _stub_systemctl_ok())
    monkeypatch.setattr(ws["v2_claude_task_runner"], "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "run_codex_review", lambda *a, **k: {
        "action": "completed", "task_id": "codex_a", "verdict": "ALPHA_CODEX_PASS",
        "fail_blockers": [], "started_utc": "0", "ended_utc": "0",
        "returncode": 0, "timed_out": False,
        "review_md": "stub", "verdict_md": "stub",
        "log_path": "claude_worklog/final_readiness/v2_closed_loop_execution/latest/logs/codex_a_codex.log",
        "command_form": ["codex", "exec", "review"],
    })
    _write_task(ws["tasks_dir"], "codex_a", {
        "task_id": "codex_a", "task_type": "CODEX_REVIEW", "agent": "codex",
        "status": "pending", "current_active": True,
    })
    snap = rm.collect_state()
    res = rm.maybe_dispatch_codex_probe(snap, allow_real_dispatch=True)
    assert res["dispatched"] is True
    assert res["command_form"] and res["command_form"][0] == "codex"
    assert res["pid_or_job_id"] == os.getpid()


def test_no_current_codex_work_reported(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_active_lane_minimum_remediation"]
    monkeypatch.setattr(rm, "_run_systemctl", _stub_systemctl_ok())
    monkeypatch.setattr(ws["v2_claude_task_runner"], "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    _write_task(ws["tasks_dir"], "claude_only", {
        "task_id": "claude_only", "task_type": "CLAUDE_IMPLEMENTATION", "agent": "claude",
        "status": "pending", "current_active": True,
    })
    snap = rm.collect_state()
    res = rm.maybe_dispatch_codex_probe(snap, allow_real_dispatch=True)
    assert res["dispatched"] is False
    assert res["no_current_codex_work"] is True


def test_no_live_or_shutdown_approval_in_outputs(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rm = ws["v2_closed_loop_active_lane_minimum_remediation"]
    monkeypatch.setattr(rm, "_run_systemctl", _stub_systemctl_ok())
    monkeypatch.setattr(ws["v2_claude_task_runner"], "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    state = rm.run_once(
        allow_real_dispatch=False,
        target_lanes=3,
        wait_after_dispatch_seconds=0,
        reset_zombies_flag=False,
    )
    blob = json.dumps(state)
    assert "\"approves_live\": true" not in blob
    assert "\"approves_canary\": true" not in blob
    assert "\"approves_legacy_shutdown\": true" not in blob
    assert "\"approves_redis_trim\": true" not in blob
    assert "blocked_human_only" in blob
