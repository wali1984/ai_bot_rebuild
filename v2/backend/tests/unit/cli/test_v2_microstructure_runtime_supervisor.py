from __future__ import annotations

import json
import subprocess
from pathlib import Path

from v2.backend.app.cli import v2_microstructure_runtime_supervisor as supervisor


def test_paper_candidate_symbols_are_unique_and_valid(tmp_path) -> None:
    source = tmp_path / "paper.json"
    source.write_text(
        json.dumps(
            {
                "candidate_allocations": [
                    {"symbol": "ETHUSDT"},
                    {"symbol": "ethusdt"},
                    {"symbol": "BAD/USD"},
                    {"symbol": "SOLUSDT"},
                    {"symbol": ""},
                ]
            }
        ),
        encoding="utf-8",
    )

    assert supervisor._paper_candidate_symbols(source) == ["ETHUSDT", "SOLUSDT"]


def test_supervision_plan_batches_direct_recorder_with_safe_defaults(tmp_path) -> None:
    plan = supervisor.build_supervision_plan(
        symbols=["ETHUSDT", "SOLUSDT", "AAVEUSDT"],
        python_executable="/venv/python",
        replay_root=tmp_path / "replay",
        batch_size=2,
        direct_max_messages=120,
        direct_loop_max_runs=0,
        direct_interval_seconds=0.0,
        direct_venue_timeout_seconds=30.0,
        direct_ws_close_timeout_seconds=1.0,
        freshness_stale_bound_ms=1500.0,
        binance_speed="250ms",
        binance_include_book_ticker=False,
        binance_include_diff_depth=False,
        monitor_loop_max_runs=0,
        monitor_interval_seconds=1.0,
        monitor_ttl_seconds=300,
        monitor_timeframe="1m",
        monitor_exchanges="binance",
    )

    assert plan["direct_batches"] == [["ETHUSDT", "SOLUSDT"], ["AAVEUSDT"]]
    assert plan["direct_batch_count"] == 2
    assert plan["estimated_binance_stream_count"] == 9
    for command in plan["direct_commands"]:
        assert "--write-redis" in command
        assert "--verify-redis-freshness" in command
        assert "--binance-include-book-ticker" not in command
        assert "--binance-include-diff-depth" not in command
        assert command[command.index("--loop-max-runs") + 1] == "0"
        assert "create_order" not in " ".join(command)
    assert "--write-status" in plan["monitor_command"]
    assert "--write-redis" in plan["monitor_command"]
    assert plan["monitor_command"][plan["monitor_command"].index("--loop-max-runs") + 1] == "0"
    assert plan["monitor_exchanges"] == "binance"


def test_supervision_plan_keeps_book_ticker_opt_in(tmp_path) -> None:
    plan = supervisor.build_supervision_plan(
        symbols=["ETHUSDT"],
        python_executable="/venv/python",
        replay_root=tmp_path / "replay",
        batch_size=8,
        direct_max_messages=10,
        direct_loop_max_runs=1,
        direct_interval_seconds=0.0,
        direct_venue_timeout_seconds=30.0,
        direct_ws_close_timeout_seconds=1.0,
        freshness_stale_bound_ms=1500.0,
        binance_speed="250ms",
        binance_include_book_ticker=True,
        binance_include_diff_depth=False,
        monitor_loop_max_runs=1,
        monitor_interval_seconds=0.0,
        monitor_ttl_seconds=60,
        monitor_timeframe="1m",
        monitor_exchanges="binance",
    )

    assert plan["binance_include_book_ticker"] is True
    assert "--binance-include-book-ticker" in plan["direct_commands"][0]


def test_filter_symbols_by_provider_support_excludes_publicly_unsupported(monkeypatch) -> None:
    support = {
        "binance": {
            "ETHUSDT": {"orderbook_supported": True, "status": "TRADING"},
            "IPUSDT": {"orderbook_supported": False, "status": "SETTLING"},
        }
    }

    monkeypatch.setattr(supervisor, "fetch_provider_symbol_support", lambda symbols: support)
    monkeypatch.setattr(
        supervisor,
        "supported_symbols_for_exchange",
        lambda symbols, provider_symbol_support, exchange: ["ETHUSDT"],
    )

    symbols, status = supervisor.filter_symbols_by_provider_support(
        symbols=["ETHUSDT", "IPUSDT"],
        exchange="binance",
        enabled=True,
    )

    assert symbols == ["ETHUSDT"]
    assert status["enabled"] is True
    assert status["filtered_symbols"] == ["IPUSDT"]
    assert status["provider_symbol_support"] == support
    assert status["places_real_order"] is False
    assert status["transfer_or_withdrawal"] is False


def test_inspect_runtime_owner_processes_flags_provider_filtered_active_symbol() -> None:
    ps_output = """
    101 1 .venv/bin/python -m v2.backend.app.cli.v2_direct_orderbook_recorder --symbols ETHUSDT,IPUSDT --exchange binance --write-redis --loop
    102 1 .venv/bin/python -m v2.backend.app.cli.v2_microstructure_feed_quality_monitor --loop --write-redis
    103 1 .venv/bin/python -m unrelated.worker --symbols IPUSDT
    104 1 /bin/bash -c .venv/bin/python -m v2.backend.app.cli.v2_microstructure_runtime_supervisor --run-managed
    """

    status = supervisor.inspect_runtime_owner_processes(
        expected_symbols=["ETHUSDT"],
        provider_filter_status={"filtered_symbols": ["IPUSDT"]},
        ps_output=ps_output,
        current_pid=999,
    )

    assert status["inspected"] is True
    assert status["owner_process_count"] == 2
    assert status["process_counts_by_kind"] == {
        "direct_orderbook_recorder": 1,
        "microstructure_feed_quality_monitor": 1,
    }
    assert status["active_direct_symbols"] == ["ETHUSDT", "IPUSDT"]
    assert status["provider_filtered_symbols_active"] == ["IPUSDT"]
    assert status["conflicting_external_owner"] is True
    assert "ACTIVE_OWNER_INCLUDES_PROVIDER_FILTERED_SYMBOL" in status["conflict_reasons"]
    assert status["read_only_inspection"] is True
    assert status["places_real_order"] is False
    assert status["redis_trim"] is False


def test_run_bounded_supervision_launches_children_without_shell(monkeypatch, tmp_path) -> None:
    popen_calls: list[dict[str, object]] = []
    run_calls: list[dict[str, object]] = []

    class FakeProcess:
        returncode = 0

        def __init__(self, command, **kwargs):
            popen_calls.append({"command": command, **kwargs})

        def communicate(self, timeout=None):
            return '{"direct":true}\n', ""

        def terminate(self):
            raise AssertionError("terminate should not be needed")

        def kill(self):
            raise AssertionError("kill should not be needed")

    class FakeCompleted:
        returncode = 0
        stdout = '{"feed_summary":{"fail_closed_rows":0}}\n'
        stderr = ""

    def fake_run(command, **kwargs):
        run_calls.append({"command": command, **kwargs})
        return FakeCompleted()

    monkeypatch.setattr(supervisor.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(supervisor.subprocess, "run", fake_run)
    monkeypatch.setattr(supervisor.time, "sleep", lambda seconds: None)

    plan = {
        "direct_commands": [["python", "-m", "direct", "--write-redis"]],
        "monitor_command": ["python", "-m", "monitor", "--write-redis"],
    }
    result = supervisor.run_bounded_supervision(
        repo_root=tmp_path,
        plan=plan,
        warmup_seconds=0.0,
        child_timeout_seconds=1.0,
    )

    assert popen_calls[0]["command"] == plan["direct_commands"][0]
    assert popen_calls[0]["cwd"] == str(tmp_path)
    assert popen_calls[0]["stdout"] is subprocess.PIPE
    assert "shell" not in popen_calls[0]
    assert run_calls[0]["command"] == plan["monitor_command"]
    assert run_calls[0]["check"] is False
    assert result["run_started_direct_processes"] == 1
    assert result["direct_results"][0]["parsed_json_tail"] == {"direct": True}
    assert result["monitor_result"]["parsed_json_tail"] == {"feed_summary": {"fail_closed_rows": 0}}


def test_run_managed_supervision_logs_health_and_stops_children(monkeypatch, tmp_path) -> None:
    popen_calls: list[dict[str, object]] = []
    terminated: list[int] = []
    monotonic_values = iter([0.0, 0.0, 0.25, 0.75, 1.25])

    class FakeProcess:
        next_pid = 1000

        def __init__(self, command, **kwargs):
            FakeProcess.next_pid += 1
            self.pid = FakeProcess.next_pid
            self.returncode = None
            self.stdout = kwargs["stdout"]
            popen_calls.append({"command": command, **kwargs, "pid": self.pid})

        def poll(self):
            return self.returncode

        def terminate(self):
            terminated.append(self.pid)
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(supervisor.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(monotonic_values, 2.0))
    monkeypatch.setattr(supervisor.time, "sleep", lambda seconds: None)

    plan = {
        "direct_commands": [["python", "-m", "direct", "--loop"]],
        "monitor_command": ["python", "-m", "monitor", "--loop"],
    }
    result = supervisor.run_managed_supervision(
        repo_root=tmp_path,
        plan=plan,
        duration_seconds=1.0,
        health_interval_seconds=0.5,
        log_root=tmp_path / "logs",
        restart_exited_children=False,
    )

    assert len(popen_calls) == 2
    assert {call["command"][2] for call in popen_calls} == {"direct", "monitor"}
    assert "shell" not in popen_calls[0]
    assert popen_calls[0]["env"]["PYTHONUNBUFFERED"] == "1"
    assert terminated == [1001, 1002]
    assert result["started_child_count"] == 2
    assert result["health_samples"]
    assert all(child["running_after_stop"] is False for child in result["child_results"])
    assert all(child["returncode"] == -15 for child in result["child_results"])


def test_run_managed_supervision_restarts_exited_children_when_enabled(monkeypatch, tmp_path) -> None:
    popen_calls: list[dict[str, object]] = []
    monotonic_values = iter([0.0, 0.0, 0.25, 0.75, 1.25])

    class FakeProcess:
        next_pid = 2000

        def __init__(self, command, **kwargs):
            FakeProcess.next_pid += 1
            self.pid = FakeProcess.next_pid
            self.returncode = 7 if len(popen_calls) == 0 else None
            popen_calls.append({"command": command, **kwargs, "pid": self.pid})

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(supervisor.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(monotonic_values, 2.0))
    monkeypatch.setattr(supervisor.time, "sleep", lambda seconds: None)

    result = supervisor.run_managed_supervision(
        repo_root=tmp_path,
        plan={
            "direct_commands": [["python", "-m", "direct", "--loop"]],
            "monitor_command": [],
        },
        duration_seconds=1.0,
        health_interval_seconds=0.5,
        log_root=tmp_path / "logs",
        restart_exited_children=True,
    )

    assert len(popen_calls) == 2
    assert result["child_results"][0]["restart_count"] == 1
    assert result["health_samples"][0]["children"][0]["running"] is True


def test_run_managed_supervision_writes_running_status(monkeypatch, tmp_path) -> None:
    monotonic_values = iter([0.0, 0.0, 0.25, 0.75, 1.25])

    class FakeProcess:
        next_pid = 3000

        def __init__(self, command, **kwargs):
            FakeProcess.next_pid += 1
            self.pid = FakeProcess.next_pid
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(supervisor.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(monotonic_values, 2.0))
    monkeypatch.setattr(supervisor.time, "sleep", lambda seconds: None)

    status_path = tmp_path / "status.json"
    managed_status_path = tmp_path / "managed_status.json"
    result = supervisor.run_managed_supervision(
        repo_root=tmp_path,
        plan={
            "direct_commands": [["python", "-m", "direct", "--loop"]],
            "monitor_command": ["python", "-m", "monitor", "--loop"],
        },
        duration_seconds=1.0,
        health_interval_seconds=0.5,
        log_root=tmp_path / "logs",
        restart_exited_children=False,
        rolling_status_paths=(status_path, managed_status_path),
        rolling_status_symbols=["ETHUSDT"],
        rolling_status_symbol_source="explicit",
    )

    payload = json.loads(status_path.read_text())
    managed_payload = json.loads(managed_status_path.read_text())
    assert result["rolling_status_write_count"] == 4
    assert payload["status"] == "MANAGED_RUN_RUNNING"
    assert payload["symbol_source"] == "explicit"
    assert payload["symbols"] == ["ETHUSDT"]
    assert payload["run_result"]["started_child_count"] == 2
    assert payload["run_result"]["health_samples"]
    assert payload["run_result"]["child_results"][0]["running"] is True
    assert payload["places_real_order"] is False
    assert payload["redis_trim"] is False
    assert managed_payload["status"] == "MANAGED_RUN_RUNNING"


def test_run_managed_supervision_until_stopped_uses_stop_callback(monkeypatch, tmp_path) -> None:
    terminated: list[int] = []
    sleep_calls: list[float] = []
    stop_checks = iter([False, True])

    class FakeProcess:
        next_pid = 4000

        def __init__(self, command, **kwargs):
            FakeProcess.next_pid += 1
            self.pid = FakeProcess.next_pid
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            terminated.append(self.pid)
            self.returncode = -15

        def wait(self, timeout=None):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(supervisor.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(supervisor.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    result = supervisor.run_managed_supervision(
        repo_root=tmp_path,
        plan={
            "direct_commands": [["python", "-m", "direct", "--loop"]],
            "monitor_command": ["python", "-m", "monitor", "--loop"],
        },
        duration_seconds=999.0,
        health_interval_seconds=0.5,
        log_root=tmp_path / "logs",
        restart_exited_children=False,
        run_until_stopped=True,
        stop_requested=lambda: next(stop_checks, True),
    )

    assert result["status"] == "MANAGED_RUN_STOPPED"
    assert result["run_until_stopped"] is True
    assert result["stopped_by_request"] is True
    assert sleep_calls == [0.5]
    assert terminated == [4001, 4002]
    assert all(child["running_after_stop"] is False for child in result["child_results"])


def test_main_writes_plan_status(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)

    assert supervisor.main(
        [
            "--symbols",
            "ETHUSDT,SOLUSDT",
            "--batch-size",
            "1",
            "--python-executable",
            "/venv/python",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 0

    public_status = tmp_path / supervisor.PUBLIC_STATUS_REL
    public_plan_status = tmp_path / supervisor.PUBLIC_PLAN_STATUS_REL
    goal_status = tmp_path / supervisor.GOAL_STATUS_REL
    goal_plan_status = tmp_path / supervisor.GOAL_PLAN_STATUS_REL
    assert public_status.exists()
    assert public_plan_status.exists()
    assert goal_status.exists()
    assert goal_plan_status.exists()
    payload = json.loads(public_status.read_text())
    output = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PLAN_READY"
    assert payload["symbol_count"] == 2
    assert payload["places_real_order"] is False
    assert payload["old_redis_writes"] is False
    assert output["plan"]["direct_batch_count"] == 2


def test_main_can_write_provider_filtered_plan_status(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        supervisor,
        "fetch_provider_symbol_support",
        lambda symbols: {
            "binance": {
                "ETHUSDT": {"orderbook_supported": True, "status": "TRADING"},
                "IPUSDT": {"orderbook_supported": False, "status": "SETTLING"},
            }
        },
    )
    monkeypatch.setattr(
        supervisor,
        "supported_symbols_for_exchange",
        lambda symbols, provider_symbol_support, exchange: ["ETHUSDT"],
    )

    assert supervisor.main(
        [
            "--symbols",
            "ETHUSDT,IPUSDT",
            "--filter-provider-supported-symbols",
            "--python-executable",
            "/venv/python",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 0

    payload = json.loads((tmp_path / supervisor.PUBLIC_STATUS_REL).read_text())
    output = json.loads(capsys.readouterr().out)
    assert payload["symbols"] == ["ETHUSDT"]
    assert payload["symbol_source"] == "explicit_provider_supported"
    assert payload["plan"]["provider_filter_status"]["filtered_symbols"] == ["IPUSDT"]
    assert payload["plan"]["direct_commands"][0][payload["plan"]["direct_commands"][0].index("--symbols") + 1] == "ETHUSDT"
    assert output["plan"]["provider_filter_status"]["filtered_symbol_count"] == 1


def test_main_writes_runtime_owner_inspection_status(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        supervisor,
        "inspect_runtime_owner_processes",
        lambda **kwargs: {
            "inspected": True,
            "conflicting_external_owner": False,
            "owner_process_count": 0,
            "read_only_inspection": True,
        },
    )

    assert supervisor.main(
        [
            "--symbols",
            "ETHUSDT",
            "--inspect-runtime-owner",
            "--python-executable",
            "/venv/python",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 0

    public_status = tmp_path / supervisor.PUBLIC_STATUS_REL
    owner_status = tmp_path / supervisor.PUBLIC_OWNER_STATUS_REL
    payload = json.loads(public_status.read_text())
    output = json.loads(capsys.readouterr().out)
    assert owner_status.exists()
    assert payload["status"] == "RUNTIME_OWNER_INSPECTED"
    assert payload["plan"]["runtime_owner_status"]["read_only_inspection"] is True
    assert output["run_result"]["run_started"] is False


def test_main_require_no_conflicting_owner_fails_closed_before_managed_run(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        supervisor,
        "inspect_runtime_owner_processes",
        lambda **kwargs: {
            "inspected": True,
            "conflicting_external_owner": True,
            "owner_process_count": 1,
            "conflict_reasons": ["EXTERNAL_MICROSTRUCTURE_OWNER_PROCESS_ACTIVE"],
            "read_only_inspection": True,
        },
    )
    monkeypatch.setattr(
        supervisor,
        "run_managed_supervision",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("managed run should not start")),
    )

    assert supervisor.main(
        [
            "--symbols",
            "ETHUSDT",
            "--run-managed",
            "--require-no-conflicting-owner",
            "--python-executable",
            "/venv/python",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 2

    public_status = tmp_path / supervisor.PUBLIC_STATUS_REL
    owner_status = tmp_path / supervisor.PUBLIC_OWNER_STATUS_REL
    payload = json.loads(public_status.read_text())
    output = json.loads(capsys.readouterr().out)
    assert owner_status.exists()
    assert payload["status"] == "RUNTIME_OWNER_CONFLICT"
    assert payload["run_result"]["run_started"] is False
    assert output["plan"]["runtime_owner_status"]["conflicting_external_owner"] is True


def test_main_writes_managed_status(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        supervisor,
        "run_managed_supervision",
        lambda **kwargs: {
            "managed_run": True,
            "child_results": [
                {
                    "name": "microstructure_monitor",
                    "parsed_json_tail": {"feed_summary": {"fail_closed_rows": 0}},
                }
            ],
        },
    )

    assert supervisor.main(
        [
            "--symbols",
            "ETHUSDT",
            "--run-managed",
            "--managed-duration-seconds",
            "1",
            "--python-executable",
            "/venv/python",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 0

    public_status = tmp_path / supervisor.PUBLIC_STATUS_REL
    managed_status = tmp_path / supervisor.PUBLIC_MANAGED_STATUS_REL
    goal_managed_status = tmp_path / supervisor.GOAL_MANAGED_STATUS_REL
    assert public_status.exists()
    assert managed_status.exists()
    assert goal_managed_status.exists()
    payload = json.loads(public_status.read_text())
    output = json.loads(capsys.readouterr().out)
    assert payload["status"] == "MANAGED_RUN_COMPLETED"
    assert payload["monitor_feed_summary"] == {"fail_closed_rows": 0}
    assert output["status"] == "MANAGED_RUN_COMPLETED"


def test_main_writes_until_stopped_managed_status(monkeypatch, tmp_path, capsys) -> None:
    captured_kwargs: dict[str, object] = {}
    restored: list[bool] = []

    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        supervisor,
        "_managed_signal_stop_callback",
        lambda: (lambda: True, lambda: restored.append(True)),
    )

    def fake_run_managed_supervision(**kwargs):
        captured_kwargs.update(kwargs)
        return {
            "status": "MANAGED_RUN_STOPPED",
            "managed_run": True,
            "run_until_stopped": True,
            "stopped_by_request": True,
            "child_results": [],
        }

    monkeypatch.setattr(supervisor, "run_managed_supervision", fake_run_managed_supervision)

    assert supervisor.main(
        [
            "--symbols",
            "ETHUSDT",
            "--run-managed",
            "--managed-until-stopped",
            "--python-executable",
            "/venv/python",
            "--replay-root",
            str(tmp_path / "replay"),
        ]
    ) == 0

    payload = json.loads((tmp_path / supervisor.PUBLIC_STATUS_REL).read_text())
    output = json.loads(capsys.readouterr().out)
    assert captured_kwargs["run_until_stopped"] is True
    assert callable(captured_kwargs["stop_requested"])
    assert restored == [True]
    assert payload["status"] == "MANAGED_RUN_STOPPED"
    assert output["status"] == "MANAGED_RUN_STOPPED"


def test_supervision_plan_shard_mode_replaces_binance_batches(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        supervisor,
        "resolve_symbols",
        lambda **_kwargs: [f"AA{i:03d}USDT" for i in range(148)],
    )
    plan = supervisor.build_supervision_plan(
        symbols=["ETHUSDT", "SOLUSDT", "AAVEUSDT"],
        python_executable="/venv/python",
        replay_root=tmp_path / "replay",
        batch_size=8,
        direct_max_messages=600,
        direct_loop_max_runs=0,
        direct_interval_seconds=0.5,
        direct_venue_timeout_seconds=30.0,
        direct_ws_close_timeout_seconds=1.0,
        freshness_stale_bound_ms=1500.0,
        binance_speed="250ms",
        binance_include_book_ticker=False,
        binance_include_diff_depth=False,
        monitor_loop_max_runs=0,
        monitor_interval_seconds=1.0,
        monitor_ttl_seconds=300,
        monitor_timeframe="1m",
        monitor_exchanges="binance,kucoin",
        kucoin_symbols=["ETHUSDT", "SOLUSDT"],
        binance_shard_count=4,
        direct_shard_max_messages=25000,
        direct_shard_replay_capture=False,
    )

    assert plan["direct_binance_shard_mode"] is True
    assert plan["direct_binance_shard_count"] == 4
    # Binance explicit-symbol batches are replaced by shard children.
    assert plan["direct_batches"] == []
    shard_commands = [
        command for command in plan["direct_commands"] if "--shard-count" in command
    ]
    assert len(shard_commands) == 4
    for index, command in enumerate(shard_commands):
        assert command[command.index("--shard-index") + 1] == str(index)
        assert command[command.index("--shard-count") + 1] == "4"
        assert "--symbols" not in command
        assert "--no-replay-capture" in command
        assert command[command.index("--binance-partial-depth-levels") + 1] == "20"
        assert command[command.index("--max-messages") + 1] == "25000"
        assert "--write-redis" in command
        assert "--verify-redis-freshness" in command
        assert command[command.index("--loop-max-runs") + 1] == "0"
    # KuCoin cross-venue children keep explicit batches and replay capture.
    kucoin_commands = [
        command
        for command in plan["direct_commands"]
        if "--exchange" in command and command[command.index("--exchange") + 1] == "kucoin"
    ]
    assert len(kucoin_commands) == 1
    assert "--no-replay-capture" not in kucoin_commands[0]
    assert kucoin_commands[0][kucoin_commands[0].index("--symbols") + 1] == "ETHUSDT,SOLUSDT"
    # Stream estimate covers the full resolver universe (one depth20 stream per
    # symbol in shard mode), not the supervisor symbol list.
    assert plan["estimated_binance_stream_count"] == 148


def test_supervision_plan_shard_mode_disabled_by_default(tmp_path) -> None:
    plan = supervisor.build_supervision_plan(
        symbols=["ETHUSDT", "SOLUSDT", "AAVEUSDT"],
        python_executable="/venv/python",
        replay_root=tmp_path / "replay",
        batch_size=2,
        direct_max_messages=120,
        direct_loop_max_runs=0,
        direct_interval_seconds=0.0,
        direct_venue_timeout_seconds=30.0,
        direct_ws_close_timeout_seconds=1.0,
        freshness_stale_bound_ms=1500.0,
        binance_speed="250ms",
        binance_include_book_ticker=False,
        binance_include_diff_depth=False,
        monitor_loop_max_runs=0,
        monitor_interval_seconds=1.0,
        monitor_ttl_seconds=300,
        monitor_timeframe="1m",
        monitor_exchanges="binance",
    )

    assert plan["direct_binance_shard_mode"] is False
    assert plan["direct_batches"] == [["ETHUSDT", "SOLUSDT"], ["AAVEUSDT"]]
    for command in plan["direct_commands"]:
        assert "--shard-count" not in command
        assert "--no-replay-capture" not in command
