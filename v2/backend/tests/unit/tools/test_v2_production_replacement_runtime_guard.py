from __future__ import annotations

import subprocess

from claude_worklog.tools import v2_production_replacement_runtime_guard as guard


def test_canonical_paper_loop_hold_recognizes_effective_noop(
    monkeypatch,
    tmp_path,
) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            "LoadState=loaded\n"
            "ActiveState=inactive\n"
            "SubState=dead\n"
            "MainPID=0\n"
            "RefuseManualStart=no\n"
            "ExecStart={ path=/usr/bin/true ; argv[]=/usr/bin/true ; }\n"
            "DropInPaths=/tmp/99-operator-hold.conf\n"
        ),
        stderr="",
    )
    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: completed)
    monkeypatch.setattr(guard, "DELIBERATELY_STOPPED_FILE", tmp_path / "missing")
    monkeypatch.setattr(guard, "_connect_redis", lambda: None)

    status = guard._canonical_paper_loop_hold_status()

    assert status["held"] is True
    assert status["reason"] == "PAPER_LOOP_EXPLICIT_OPERATOR_HOLD"
    assert status["hold_evidence"] == ["EFFECTIVE_EXEC_START_NOOP"]


def test_canonical_paper_loop_hold_recognizes_self_healer_marker(
    monkeypatch,
    tmp_path,
) -> None:
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            "LoadState=loaded\n"
            "ActiveState=active\n"
            "SubState=running\n"
            "MainPID=1234\n"
            "RefuseManualStart=no\n"
            "ExecStart={ path=/repo/.venv/bin/python ; }\n"
            "DropInPaths=\n"
        ),
        stderr="",
    )
    marker = tmp_path / "deliberately_stopped_units.txt"
    marker.write_text(
        f"# operator holds\n{guard.CANONICAL_PAPER_LOOP_UNIT}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: completed)
    monkeypatch.setattr(guard, "DELIBERATELY_STOPPED_FILE", marker)
    monkeypatch.setattr(guard, "_connect_redis", lambda: None)

    status = guard._canonical_paper_loop_hold_status()

    assert status["held"] is True
    assert status["hold_evidence"] == ["DELIBERATELY_STOPPED_MARKER"]


def test_trade_management_phase_does_not_spawn_when_paper_loop_is_held(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        guard,
        "_canonical_paper_loop_hold_status",
        lambda: {
            "held": True,
            "reason": "PAPER_LOOP_EXPLICIT_OPERATOR_HOLD",
        },
    )

    def unexpected_spawn(*args, **kwargs):
        raise AssertionError("held trade-management phase must not spawn")

    monkeypatch.setattr(guard.subprocess, "run", unexpected_spawn)

    result = guard._run_phase("trade_mgmt")

    assert result["returncode"] is None
    assert result["status"] == "SKIPPED_CANONICAL_PAPER_LOOP_HELD"


def test_trade_management_phase_observes_canonical_writer_without_spawning(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        guard,
        "_canonical_paper_loop_hold_status",
        lambda: {
            "held": False,
            "reason": "PAPER_LOOP_NOT_EXPLICITLY_HELD",
            "active_state": "active",
            "main_pid": "5678",
        },
    )

    def unexpected_spawn(*args, **kwargs):
        raise AssertionError("trade-management guard must remain observer-only")

    monkeypatch.setattr(guard.subprocess, "run", unexpected_spawn)

    result = guard._run_phase("trade_mgmt")

    assert result["returncode"] == 0
    assert result["status"] == "OBSERVED_CANONICAL_PAPER_LOOP_ACTIVE"


def test_trade_management_phase_reports_inactive_without_becoming_writer(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        guard,
        "_canonical_paper_loop_hold_status",
        lambda: {
            "held": False,
            "reason": "PAPER_LOOP_NOT_EXPLICITLY_HELD",
            "active_state": "inactive",
            "main_pid": "0",
        },
    )

    def unexpected_spawn(*args, **kwargs):
        raise AssertionError("inactive canonical writer must not be impersonated")

    monkeypatch.setattr(guard.subprocess, "run", unexpected_spawn)

    result = guard._run_phase("trade_mgmt")

    assert result["returncode"] == 3
    assert result["status"] == "CANONICAL_PAPER_LOOP_NOT_ACTIVE"


def test_guard_reports_held_trade_management_phase_as_degraded(monkeypatch) -> None:
    def phase_result(phase: str) -> dict:
        if phase == "trade_mgmt":
            return {
                "phase": phase,
                "returncode": None,
                "status": "SKIPPED_CANONICAL_PAPER_LOOP_HELD",
                "hold_status": {
                    "held": True,
                    "reason": "PAPER_LOOP_EXPLICIT_OPERATOR_HOLD",
                },
                "stdout_tail": "",
                "stderr_tail": "",
            }
        return {
            "phase": phase,
            "returncode": 0,
            "status": "COMPLETED",
            "stdout_tail": "",
            "stderr_tail": "",
        }

    monkeypatch.setattr(guard, "_run_phase", phase_result)
    monkeypatch.setattr(guard, "_connect_redis", lambda: object())
    monkeypatch.setattr(guard, "_count_pattern", lambda *_args: 1)
    monkeypatch.setattr(guard, "_process_running", lambda *_args: True)
    monkeypatch.setattr(guard, "_payload_fresh", lambda *_args: (True, 0))

    status = guard.run_guard()

    assert status["classification"] == "V2_PRODUCTION_REPLACEMENT_RUNTIME_DEGRADED"
    assert status["required_workers_returncode_ok"] is False
    assert status["operator_held_phases"][0]["phase"] == "trade_mgmt"
    assert (
        "phase_operator_held:trade_mgmt:PAPER_LOOP_EXPLICIT_OPERATOR_HOLD"
        in status["failed_checks"]
    )
