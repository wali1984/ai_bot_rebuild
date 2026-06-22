"""Unit tests for the V2 closed-loop real-mode enablement orchestrator.

Covers the spec validation points:

* current-work filter excludes historical noise + recognises probes;
* systemd install verification stays read-only without an `enable`
  flag and reports per-timer is-enabled / is-active outcomes;
* probe materialization is idempotent;
* missing Claude executor blocks READY;
* active_lane_count is anchored on real pids;
* no live / shutdown / exchange-mutation approval in any emitted
  payload.
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
)


@pytest.fixture
def isolated_workspace(tmp_path, monkeypatch):
    repo = tmp_path / "AI BOT REBUILD"
    (repo / "claude_worklog" / "agent_supervisor" / "tasks").mkdir(parents=True)
    (repo / "claude_worklog" / "tools").mkdir(parents=True)
    (repo / "claude_worklog" / "final_readiness" / "v2_closed_loop_execution" / "latest" / "systemd").mkdir(parents=True)
    (repo / "v2" / "frontend" / "public").mkdir(parents=True)

    for mod_name in MODULES:
        (repo / "claude_worklog" / "tools" / f"{mod_name}.py").write_text(
            (TOOLS_DIR / f"{mod_name}.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    # Drop one stub unit so the install path can copy.
    (repo / "claude_worklog" / "final_readiness" / "v2_closed_loop_execution" / "latest" / "systemd" / "ai-bot-v2-closed-loop-executor.timer").write_text(
        "[Timer]\nOnUnitActiveSec=2min\n", encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".config" / "systemd" / "user").mkdir(parents=True)
    monkeypatch.syspath_prepend(str(repo / "claude_worklog" / "tools"))
    for mod_name in MODULES:
        sys.modules.pop(mod_name, None)
    modules = {name: importlib.import_module(name) for name in MODULES}
    return {"repo": repo, "tasks_dir": repo / "claude_worklog" / "agent_supervisor" / "tasks", **modules}


def _stub_systemctl(returncode: int = 0, stdout: str = "enabled"):
    def _runner(args):
        return {"cmd": ["systemctl", *args], "returncode": returncode, "stdout": stdout, "stderr": ""}
    return _runner


def test_current_work_filter_excludes_historical(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    cf = ws["v2_current_work_filter"]
    # One ancient + one current_active probe + one live-keyword (must exclude).
    (ws["tasks_dir"] / "ancient.json").write_text(json.dumps({
        "task_id": "ancient",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2020-01-01T00:00:00Z",
    }) + "\n")
    # Force the mtime back to 2020 so the file_mtime branch can't rescue it.
    ancient = ws["tasks_dir"] / "ancient.json"
    os.utime(ancient, (1577836800, 1577836800))

    (ws["tasks_dir"] / "current_probe.json").write_text(json.dumps({
        "task_id": "current_probe",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
        "current_active": True,
    }) + "\n")
    (ws["tasks_dir"] / "live_canary_anything.json").write_text(json.dumps({
        "task_id": "live_canary_anything",
        "task_type": "CLAUDE_IMPLEMENTATION",
        "agent": "claude",
        "status": "pending",
        "current_active": True,
    }) + "\n")
    result = cf.build_current_work_queue(active_window_hours=24)
    queue = result["queue"]
    ids = {row["task_id"] for row in queue["current"]}
    assert "current_probe" in ids
    assert "ancient" not in ids
    assert "live_canary_anything" not in ids
    assert queue["historical_excluded_count"] >= 2


def test_install_timers_dry_verification_only(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rme = ws["v2_closed_loop_real_mode_enablement"]
    monkeypatch.setattr(rme, "_run_systemctl", _stub_systemctl(0, "enabled"))
    result = rme.install_timers(install=False, enable=False)
    assert result["copied"] == []
    assert "verification" in result
    for timer, info in result["verification"].items():
        assert info["is_enabled"]["stdout"] == "enabled"


def test_install_timers_copy_and_enable(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rme = ws["v2_closed_loop_real_mode_enablement"]
    monkeypatch.setattr(rme, "_run_systemctl", _stub_systemctl(0, "enabled"))
    # Override the systemd dst so we can verify the copy lands in tmp.
    fake_dst = ws["repo"].parent / "home" / ".config" / "systemd" / "user"
    fake_dst.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(rme, "SYSTEMD_DST", fake_dst)
    result = rme.install_timers(install=True, enable=True)
    # The stub source only has one unit; the rest report as missing.
    assert "ai-bot-v2-closed-loop-executor.timer" in result["copied"]
    assert any("missing unit" in e for e in result["errors"])
    assert result["enabled"] is True
    assert result["enable_commands"]


def test_materialize_probe_descriptors_is_idempotent(isolated_workspace):
    ws = isolated_workspace
    rme = ws["v2_closed_loop_real_mode_enablement"]
    first = rme.materialize_probe_descriptors()
    second = rme.materialize_probe_descriptors()
    assert sum(1 for r in first if r["created"]) == 6
    assert all(r["created"] is False for r in second)


def test_run_once_blocks_when_claude_executor_missing(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rme = ws["v2_closed_loop_real_mode_enablement"]
    monkeypatch.setattr(rme, "_run_systemctl", _stub_systemctl(0, "enabled"))
    monkeypatch.setattr(ws["v2_claude_task_runner"], "discover_claude_executor",
                        lambda: {"available": False, "executor": None})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "run_codex_review",
                        lambda *a, **k: {"action": "completed", "task_id": "x", "verdict": "X_CODEX_PASS",
                                          "fail_blockers": [], "started_utc": "0", "ended_utc": "0",
                                          "returncode": 0, "timed_out": False,
                                          "review_md": "stub", "verdict_md": "stub", "log_path": "stub",
                                          "command_form": ["codex"]})
    state = rme.run_once(
        install_timers_flag=False,
        enable_timers_flag=False,
        allow_real_dispatch=True,
        materialize_probes=True,
        active_window_hours=24,
        target_lanes=3,
        wait_after_dispatch_seconds=0,
    )
    assert state["marker"] == "V2_CLOSED_LOOP_EXECUTION_ENGINE_REAL_MODE_ENABLEMENT_BLOCKED"
    assert "CLAUDE_EXECUTOR_NOT_AVAILABLE_OPERATOR_ACTION_REQUIRED" in state["blockers"]


def test_run_once_real_dispatch_anchors_on_living_pid(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rme = ws["v2_closed_loop_real_mode_enablement"]
    cr = ws["v2_claude_task_runner"]
    co = ws["v2_codex_review_runner"]
    monkeypatch.setattr(rme, "_run_systemctl", _stub_systemctl(0, "enabled"))
    monkeypatch.setattr(cr, "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []})
    monkeypatch.setattr(co, "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})

    # Stub the actual launchers so we don't spawn real CLI subprocesses
    # during tests; they record a pid of the test process (always alive).
    own_pid = os.getpid()

    def _fake_launch(descriptor_path, d, executor, *, dry_run=False):
        log_path = ws["v2_closed_loop_lifecycle"].LOG_DIR / f"{d['task_id']}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("V2_CLOSED_LOOP_LANE_HEARTBEAT_OK\n", encoding="utf-8")
        ws["v2_closed_loop_lifecycle"].write_heartbeat(d["task_id"], own_pid, {"cmd": ["stub"]})
        return {"action": "launched", "task_id": d["task_id"], "pid": own_pid, "log_path": str(log_path)}
    monkeypatch.setattr(cr, "launch_claude_task", _fake_launch)
    monkeypatch.setattr(co, "run_codex_review", lambda *a, **k: {
        "action": "completed", "task_id": "x", "verdict": "X_CODEX_PASS",
        "fail_blockers": [], "started_utc": "0", "ended_utc": "0",
        "returncode": 0, "timed_out": False,
        "review_md": "stub", "verdict_md": "stub", "log_path": "stub",
        "command_form": ["codex"],
    })

    state = rme.run_once(
        install_timers_flag=False,
        enable_timers_flag=False,
        allow_real_dispatch=True,
        materialize_probes=True,
        active_window_hours=24,
        target_lanes=3,
        wait_after_dispatch_seconds=0,
    )
    assert state["utilization"]["active_claude_jobs"] == 3
    assert state["utilization"]["dry_run"] is False
    # All three claude lane proofs must have an alive pid and a log file.
    alive_lanes = [l for l in state["proof"]["lanes"] if l["pid_alive"]]
    assert len(alive_lanes) == 3
    for lane in alive_lanes:
        assert lane["pid_or_job_id"] == own_pid
        assert lane["log_path"]
        assert lane["heartbeat_timestamp"]


def test_no_live_or_shutdown_approval_in_payload(isolated_workspace, monkeypatch):
    ws = isolated_workspace
    rme = ws["v2_closed_loop_real_mode_enablement"]
    monkeypatch.setattr(rme, "_run_systemctl", _stub_systemctl(0, "enabled"))
    monkeypatch.setattr(ws["v2_claude_task_runner"], "discover_claude_executor",
                        lambda: {"available": True, "executor": "claude_cli", "command_probe": ["/usr/bin/true"], "version": []})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "discover_codex_executor",
                        lambda: {"available": True, "executor": "codex_cli", "binary": "/usr/bin/true"})
    monkeypatch.setattr(ws["v2_claude_task_runner"], "launch_claude_task",
                        lambda *a, **k: {"action": "launched", "task_id": "x", "pid": 1, "log_path": "x"})
    monkeypatch.setattr(ws["v2_codex_review_runner"], "run_codex_review",
                        lambda *a, **k: {"action": "completed", "task_id": "x", "verdict": "X_CODEX_PASS",
                                          "fail_blockers": [], "started_utc": "0", "ended_utc": "0",
                                          "returncode": 0, "timed_out": False,
                                          "review_md": "stub", "verdict_md": "stub", "log_path": "stub",
                                          "command_form": ["codex"]})
    state = rme.run_once(
        install_timers_flag=False,
        enable_timers_flag=False,
        allow_real_dispatch=True,
        materialize_probes=True,
        active_window_hours=24,
        target_lanes=3,
        wait_after_dispatch_seconds=0,
    )
    blob = json.dumps(state)
    assert "\"approves_live\": true" not in blob
    assert "\"approves_canary\": true" not in blob
    assert "\"approves_legacy_shutdown\": true" not in blob
    assert "\"approves_redis_trim\": true" not in blob
    assert "blocked_human_only" in blob
