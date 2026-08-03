from __future__ import annotations

import os
from pathlib import Path

from v2.backend.app.cli import v2_monthly_10k_profit_target_monitor as monitor_cli
from v2.backend.app.services.profit_target_monitor import ProfitTargetMonitorPaths


def _payload() -> dict:
    return {
        "operator_dashboard_payload.json": {
            "gate": monitor_cli.READY,
            "generated_est": "2026-06-14T02:30:00-04:00",
            "goal_status": "LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL",
            "trainer_capability_status": "TRAINER_DATASET_TOO_SMALL",
            "hedging_status": "HEDGING_BLOCKED_NO_VALID_HEDGE_CONTEXT",
            "goal_simulation_status": "GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE",
            "paper_equity": 10_000.0,
            "paper_run_rate_monthly_pnl": -100.0,
            "required_monthly_return_pct": 1.0,
            "live_available_margin": 0.0,
            "live_target_executable": False,
            "adaptive_leverage_margin_selection_status": "LIVE_READY_BALANCE_HELD_NO_ACTION",
            "paper_recommended_leverage": 1.0,
            "live_leverage_margin_action_status": "LIVE_READY_BALANCE_HELD_NO_ACTION",
            "blockers": ["capital shortfall"],
            "safety": {
                "real_order": False,
                "test_order": False,
                "leverage_margin_mutation": False,
                "old_redis_write": False,
            },
        }
    }


def test_monthly_profit_target_monitor_one_shot(monkeypatch, tmp_path: Path, capsys) -> None:
    calls: list[Path] = []

    def fake_publish(paths):
        calls.append(paths.repo_root)
        return _payload()

    monkeypatch.setattr(monitor_cli, "publish_all", fake_publish)

    exit_code = monitor_cli.main(["--repo-root", str(tmp_path)])

    assert exit_code == 0
    assert calls == [tmp_path.resolve()]
    assert "LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL" in capsys.readouterr().out


def test_monthly_profit_target_monitor_loop_uses_interval_without_live_mutation(monkeypatch, tmp_path: Path) -> None:
    calls = 0
    sleeps: list[float] = []

    def fake_publish(_paths):
        nonlocal calls
        calls += 1
        return _payload()

    monkeypatch.setattr(monitor_cli, "publish_all", fake_publish)
    monkeypatch.setattr(monitor_cli.time, "sleep", lambda seconds: sleeps.append(seconds))

    exit_code = monitor_cli.main(
        ["--repo-root", str(tmp_path), "--loop", "--interval-seconds", "7", "--max-iterations", "2"]
    )

    assert exit_code == 0
    assert calls == 2
    assert sleeps == [7.0]


def test_monthly_profit_target_monitor_loop_exits_when_existing_pid_is_alive(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    paths = ProfitTargetMonitorPaths(repo_root=tmp_path.resolve(), public_root=tmp_path.resolve() / "v2/frontend/public")
    paths.operator_dir.mkdir(parents=True, exist_ok=True)
    (paths.operator_dir / "monitor.pid").write_text("12345\n", encoding="utf-8")

    def fail_publish(_paths):
        raise AssertionError("duplicate monitor must not publish")

    monkeypatch.setattr(monitor_cli, "publish_all", fail_publish)
    monkeypatch.setattr(monitor_cli, "_pid_is_alive", lambda pid: pid == 12345)

    exit_code = monitor_cli.main(["--repo-root", str(tmp_path), "--loop", "--interval-seconds", "1"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "MONITOR_LOOP_ALREADY_RUNNING" in output
    assert "12345" in output


def test_monthly_profit_target_monitor_loop_replaces_stale_pid_file(monkeypatch, tmp_path: Path) -> None:
    paths = ProfitTargetMonitorPaths(repo_root=tmp_path.resolve(), public_root=tmp_path.resolve() / "v2/frontend/public")
    paths.operator_dir.mkdir(parents=True, exist_ok=True)
    pid_file = paths.operator_dir / "monitor.pid"
    pid_file.write_text("12345\n", encoding="utf-8")
    monkeypatch.setattr(monitor_cli, "_pid_is_alive", lambda _pid: False)

    acquired, locked_pid_file, existing_pid = monitor_cli._acquire_loop_lock(tmp_path.resolve())

    assert acquired is True
    assert locked_pid_file == pid_file
    assert existing_pid is None
    assert pid_file.read_text(encoding="utf-8").strip() == str(os.getpid())
