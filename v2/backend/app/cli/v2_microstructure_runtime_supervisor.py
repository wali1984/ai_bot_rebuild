"""Operator-safe direct orderbook and microstructure runtime supervisor.

This command coordinates public market-data workers only:
  - no real orders
  - no test orders
  - no exchange cancel/modify
  - no leverage or margin mutation
  - no transfers or withdrawals
  - no old Redis writes
  - no Redis trim
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from v2.backend.app.cli.v2_direct_orderbook_recorder import fetch_provider_symbol_support, supported_symbols_for_exchange
from v2.backend.app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol, resolve_symbols


REPO_ROOT = Path(__file__).resolve().parents[4]
WORKER_ID = "v2_microstructure_runtime_supervisor"
PRODUCTION_GOAL_ID = "V2_PRODUCTION_RECOVERY_A_GRADE_PAPER_AND_LIVE_TRADER_GO_LIVE_COMPLETION"
PUBLIC_STATUS_REL = Path("v2/frontend/public/operator_runtime/v2_microstructure_runtime_supervisor/latest/status.json")
PUBLIC_PLAN_STATUS_REL = Path("v2/frontend/public/operator_runtime/v2_microstructure_runtime_supervisor/latest/deployment_plan_status.json")
PUBLIC_BOUNDED_STATUS_REL = Path("v2/frontend/public/operator_runtime/v2_microstructure_runtime_supervisor/latest/bounded_probe_status.json")
PUBLIC_MANAGED_STATUS_REL = Path("v2/frontend/public/operator_runtime/v2_microstructure_runtime_supervisor/latest/managed_run_status.json")
PUBLIC_OWNER_STATUS_REL = Path("v2/frontend/public/operator_runtime/v2_microstructure_runtime_supervisor/latest/runtime_owner_status.json")
GOAL_STATUS_REL = Path("goal_state") / PRODUCTION_GOAL_ID / "microstructure_runtime_supervisor_status.json"
GOAL_PLAN_STATUS_REL = Path("goal_state") / PRODUCTION_GOAL_ID / "microstructure_runtime_supervisor_deployment_plan_status.json"
GOAL_BOUNDED_STATUS_REL = Path("goal_state") / PRODUCTION_GOAL_ID / "microstructure_runtime_supervisor_bounded_probe_status.json"
GOAL_MANAGED_STATUS_REL = Path("goal_state") / PRODUCTION_GOAL_ID / "microstructure_runtime_supervisor_managed_run_status.json"
GOAL_OWNER_STATUS_REL = Path("goal_state") / PRODUCTION_GOAL_ID / "microstructure_runtime_supervisor_runtime_owner_status.json"
DEFAULT_PAPER_STATUS_REL = Path(
    "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/paper_adaptive_sizing_runtime_status.json"
)
DEFAULT_REPLAY_ROOT_REL = Path("v2/runtime/orderbook_replay")
DEFAULT_MANAGED_LOG_ROOT_REL = Path("v2/runtime/microstructure_runtime_supervisor")


@dataclass(frozen=True)
class ChildResult:
    name: str
    command: list[str]
    returncode: int | None
    terminated: bool
    stdout_tail: list[str]
    stderr_tail: list[str]
    parsed_json_tail: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": self.command,
            "returncode": self.returncode,
            "terminated": self.terminated,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "parsed_json_tail": self.parsed_json_tail,
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _normalize_symbols(symbols: Iterable[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in symbols:
        symbol = str(value or "").strip().upper()
        if not symbol or symbol in seen or not is_valid_runtime_symbol(symbol):
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _paper_candidate_symbols(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = payload.get("candidate_allocations") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return _normalize_symbols(row.get("symbol") for row in rows if isinstance(row, dict))


def _chunks(values: list[str], size: int) -> list[list[str]]:
    chunk_size = max(1, int(size))
    return [values[index : index + chunk_size] for index in range(0, len(values), chunk_size)]


def resolve_supervised_symbols(
    *,
    explicit: str | None,
    paper_candidates: bool,
    paper_status_path: Path,
    smoke_test: bool,
    max_symbols: int,
) -> tuple[list[str], str]:
    if explicit:
        symbols = resolve_symbols(explicit=explicit, smoke_test=smoke_test, include_baseline=True)
        source = "explicit"
    elif paper_candidates:
        symbols = _paper_candidate_symbols(paper_status_path)
        source = "paper_candidates"
        if not symbols:
            symbols = resolve_symbols(explicit=None, smoke_test=smoke_test, include_baseline=True)
            source = "resolver_fallback_after_empty_paper_candidates"
    else:
        symbols = resolve_symbols(explicit=None, smoke_test=smoke_test, include_baseline=True)
        source = "resolver"
    if max_symbols > 0:
        symbols = symbols[: int(max_symbols)]
        source = f"{source}_limited"
    return symbols, source


def filter_symbols_by_provider_support(
    *,
    symbols: list[str],
    exchange: str = "binance",
    enabled: bool,
) -> tuple[list[str], dict[str, Any]]:
    normalized = _normalize_symbols(symbols)
    if not enabled:
        return normalized, {
            "enabled": False,
            "exchange": exchange,
            "requested_symbols": normalized,
            "filtered_symbols": [],
            "provider_symbol_support": {},
        }
    provider_symbol_support = fetch_provider_symbol_support(normalized)
    supported = supported_symbols_for_exchange(normalized, provider_symbol_support, exchange)
    filtered = [symbol for symbol in normalized if symbol not in set(supported)]
    return supported, {
        "enabled": True,
        "exchange": exchange,
        "requested_symbols": normalized,
        "supported_symbols": supported,
        "supported_symbol_count": len(supported),
        "filtered_symbols": filtered,
        "filtered_symbol_count": len(filtered),
        "provider_symbol_support": provider_symbol_support,
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "transfer_or_withdrawal": False,
    }


def _command_string(command: list[str]) -> str:
    return " ".join(command)


def _value_after_flag(tokens: list[str], flag: str) -> str | None:
    try:
        index = tokens.index(flag)
    except ValueError:
        return None
    next_index = index + 1
    if next_index >= len(tokens):
        return None
    return tokens[next_index]


def _process_kind(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    executable_name = Path(tokens[0]).name
    if executable_name in {"bash", "sh", "dash", "zsh", "fish", "timeout"}:
        return None
    module = None
    for index, token in enumerate(tokens[:-1]):
        if token == "-m":
            module = tokens[index + 1]
            break
    if module == "v2.backend.app.cli.v2_direct_orderbook_recorder":
        return "direct_orderbook_recorder"
    if module == "v2.backend.app.cli.v2_microstructure_feed_quality_monitor":
        return "microstructure_feed_quality_monitor"
    if module == "v2.backend.app.cli.v2_microstructure_runtime_supervisor":
        return "microstructure_runtime_supervisor"
    return None


def inspect_runtime_owner_processes(
    *,
    expected_symbols: list[str],
    provider_filter_status: dict[str, Any] | None = None,
    ps_output: str | None = None,
    current_pid: int | None = None,
) -> dict[str, Any]:
    """Read-only process inventory for public market-data runtime ownership."""
    inspected_at = utc_now_iso()
    pid_to_skip = int(current_pid if current_pid is not None else os.getpid())
    ps_error = None
    if ps_output is None:
        try:
            completed = subprocess.run(
                ["ps", "-eo", "pid=,ppid=,args="],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                timeout=5.0,
            )
            ps_output = completed.stdout if completed.returncode == 0 else ""
            if completed.returncode != 0:
                ps_error = completed.stderr.strip() or f"ps_returncode_{completed.returncode}"
        except Exception as exc:
            ps_output = ""
            ps_error = str(exc)

    expected_set = set(_normalize_symbols(expected_symbols))
    provider_filter_status = provider_filter_status or {}
    provider_filtered_set = set(_normalize_symbols(provider_filter_status.get("filtered_symbols") or []))
    owner_processes: list[dict[str, Any]] = []
    direct_symbols: set[str] = set()
    process_counts_by_kind: dict[str, int] = {}
    for line in str(ps_output or "").splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) < 3:
            continue
        try:
            pid = int(fields[0])
            ppid = int(fields[1])
        except ValueError:
            continue
        if pid == pid_to_skip:
            continue
        try:
            tokens = shlex.split(fields[2])
        except ValueError:
            tokens = fields[2].split()
        kind = _process_kind(tokens)
        if not kind:
            continue
        command = fields[2]
        symbols = _normalize_symbols((_value_after_flag(tokens, "--symbols") or "").split(","))
        if kind == "direct_orderbook_recorder":
            direct_symbols.update(symbols)
        process_counts_by_kind[kind] = process_counts_by_kind.get(kind, 0) + 1
        owner_processes.append(
            {
                "pid": pid,
                "ppid": ppid,
                "kind": kind,
                "symbols": symbols,
                "symbol_count": len(symbols),
                "command": command,
            }
        )

    extra_symbols = sorted(direct_symbols - expected_set) if expected_set else sorted(direct_symbols)
    missing_symbols = sorted(expected_set - direct_symbols) if direct_symbols else sorted(expected_set)
    provider_filtered_active = sorted(direct_symbols & provider_filtered_set)
    conflict_reasons: list[str] = []
    if owner_processes:
        conflict_reasons.append("EXTERNAL_MICROSTRUCTURE_OWNER_PROCESS_ACTIVE")
    if provider_filtered_active:
        conflict_reasons.append("ACTIVE_OWNER_INCLUDES_PROVIDER_FILTERED_SYMBOL")
    if ps_error:
        conflict_reasons.append("PROCESS_INVENTORY_INCOMPLETE")
    return {
        "inspected": True,
        "inspected_at": inspected_at,
        "current_pid": pid_to_skip,
        "process_inventory_error": ps_error,
        "owner_process_count": len(owner_processes),
        "process_counts_by_kind": process_counts_by_kind,
        "owner_processes": owner_processes,
        "active_direct_symbols": sorted(direct_symbols),
        "active_direct_symbol_count": len(direct_symbols),
        "expected_symbols": sorted(expected_set),
        "expected_symbol_count": len(expected_set),
        "extra_active_direct_symbols": extra_symbols,
        "missing_expected_direct_symbols": missing_symbols,
        "provider_filtered_symbols_active": provider_filtered_active,
        "conflicting_external_owner": bool(owner_processes or ps_error),
        "conflict_reasons": conflict_reasons,
        "read_only_inspection": True,
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "transfer_or_withdrawal": False,
        "old_redis_writes": False,
        "redis_trim": False,
        "paper_online_runtime_restart": False,
        "legacy_restart": False,
    }


def build_supervision_plan(
    *,
    symbols: list[str],
    python_executable: str,
    replay_root: Path,
    batch_size: int,
    direct_max_messages: int,
    direct_loop_max_runs: int,
    direct_interval_seconds: float,
    direct_venue_timeout_seconds: float,
    direct_ws_close_timeout_seconds: float,
    freshness_stale_bound_ms: float,
    binance_speed: str,
    binance_include_book_ticker: bool,
    binance_include_diff_depth: bool,
    monitor_loop_max_runs: int,
    monitor_interval_seconds: float,
    monitor_ttl_seconds: int,
    monitor_timeframe: str,
    monitor_exchanges: str,
    provider_filter_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    batches = _chunks(_normalize_symbols(symbols), batch_size)
    direct_commands: list[list[str]] = []
    for batch in batches:
        command = [
            python_executable,
            "-m",
            "v2.backend.app.cli.v2_direct_orderbook_recorder",
            "--symbols",
            ",".join(batch),
            "--exchange",
            "binance",
            "--speed",
            str(binance_speed),
            "--max-messages",
            str(max(1, int(direct_max_messages))),
            "--write-redis",
            "--verify-redis-freshness",
            "--freshness-stale-bound-ms",
            str(float(freshness_stale_bound_ms)),
            "--loop",
            "--loop-max-runs",
            str(max(0, int(direct_loop_max_runs))),
            "--interval-seconds",
            str(max(0.0, float(direct_interval_seconds))),
            "--venue-timeout-seconds",
            str(max(1.0, float(direct_venue_timeout_seconds))),
            "--ws-close-timeout-seconds",
            str(max(0.1, float(direct_ws_close_timeout_seconds))),
            "--replay-root",
            str(replay_root),
        ]
        if binance_include_book_ticker:
            command.append("--binance-include-book-ticker")
        if binance_include_diff_depth:
            command.append("--binance-include-diff-depth")
        direct_commands.append(command)

    monitor_command = [
        python_executable,
        "-m",
        "v2.backend.app.cli.v2_microstructure_feed_quality_monitor",
        "--symbols",
        ",".join(_normalize_symbols(symbols)),
        "--exchanges",
        str(monitor_exchanges),
        "--timeframe",
        str(monitor_timeframe),
        "--write-redis",
        "--write-status",
        "--ttl-seconds",
        str(max(1, int(monitor_ttl_seconds))),
        "--loop",
        "--loop-max-runs",
        str(max(0, int(monitor_loop_max_runs))),
        "--interval-seconds",
        str(max(0.0, float(monitor_interval_seconds))),
        "--replay-root",
        str(replay_root),
    ]
    stream_count = len(_normalize_symbols(symbols)) * (3 + int(bool(binance_include_book_ticker)) + int(bool(binance_include_diff_depth)))
    return {
        "direct_batches": batches,
        "direct_batch_count": len(batches),
        "direct_batch_size": max(1, int(batch_size)),
        "direct_commands": direct_commands,
        "direct_command_strings": [_command_string(command) for command in direct_commands],
        "monitor_command": monitor_command,
        "monitor_command_string": _command_string(monitor_command),
        "estimated_binance_stream_count": stream_count,
        "binance_include_book_ticker": bool(binance_include_book_ticker),
        "binance_include_diff_depth": bool(binance_include_diff_depth),
        "direct_uses_redis_freshness_check": True,
        "direct_exchange": "binance",
        "monitor_exchanges": monitor_exchanges,
        "provider_filter_status": provider_filter_status or {"enabled": False},
    }


def _tail_lines(text: str, limit: int = 5) -> list[str]:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    return lines[-max(1, int(limit)) :]


def _parse_last_json(lines: list[str]) -> dict[str, Any] | None:
    for line in reversed(lines):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _tail_file(path: Path, limit: int = 5) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [line for line in lines if line.strip()][-max(1, int(limit)) :]


def _collect_process(
    name: str,
    command: list[str],
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float,
) -> ChildResult:
    terminated = False
    try:
        stdout, stderr = process.communicate(timeout=max(0.1, float(timeout_seconds)))
    except subprocess.TimeoutExpired:
        terminated = True
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5.0)
    stdout_tail = _tail_lines(stdout)
    return ChildResult(
        name=name,
        command=command,
        returncode=process.returncode,
        terminated=terminated,
        stdout_tail=stdout_tail,
        stderr_tail=_tail_lines(stderr),
        parsed_json_tail=_parse_last_json(stdout_tail),
    )


def run_bounded_supervision(
    *,
    repo_root: Path,
    plan: dict[str, Any],
    warmup_seconds: float,
    child_timeout_seconds: float,
) -> dict[str, Any]:
    direct_processes: list[tuple[str, list[str], subprocess.Popen[str]]] = []
    for index, command in enumerate(plan["direct_commands"], start=1):
        process = subprocess.Popen(
            command,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        direct_processes.append((f"direct_batch_{index}", command, process))
    time.sleep(max(0.0, float(warmup_seconds)))
    monitor_terminated = False
    try:
        monitor_completed = subprocess.run(
            plan["monitor_command"],
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=max(1.0, float(child_timeout_seconds)),
        )
        monitor_returncode = monitor_completed.returncode
        monitor_stdout = monitor_completed.stdout
        monitor_stderr = monitor_completed.stderr
    except subprocess.TimeoutExpired as exc:
        monitor_terminated = True
        monitor_returncode = None
        monitor_stdout = exc.stdout or ""
        monitor_stderr = exc.stderr or "monitor_timeout"
    direct_results = [
        _collect_process(
            name,
            command,
            process,
            timeout_seconds=max(0.1, float(child_timeout_seconds)),
        ).to_dict()
        for name, command, process in direct_processes
    ]
    monitor_stdout_tail = _tail_lines(monitor_stdout)
    return {
        "run_started_direct_processes": len(direct_processes),
        "direct_results": direct_results,
        "monitor_result": {
            "name": "microstructure_monitor",
            "command": plan["monitor_command"],
            "returncode": monitor_returncode,
            "terminated": monitor_terminated,
            "stdout_tail": monitor_stdout_tail,
            "stderr_tail": _tail_lines(monitor_stderr),
            "parsed_json_tail": _parse_last_json(monitor_stdout_tail),
        },
    }


def _terminate_child(process: subprocess.Popen[str], *, timeout_seconds: float = 5.0) -> bool:
    if process.poll() is not None:
        return False
    process.terminate()
    try:
        process.wait(timeout=max(0.1, float(timeout_seconds)))
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=max(0.1, float(timeout_seconds)))
    return True


def _spawn_logged_child(
    *,
    repo_root: Path,
    command: list[str],
    log_root: Path,
    name: str,
) -> tuple[subprocess.Popen[str], Any, Any, Path, Path]:
    log_root.mkdir(parents=True, exist_ok=True)
    stdout_path = log_root / f"{name}.out"
    stderr_path = log_root / f"{name}.err"
    stdout_handle = stdout_path.open("a", encoding="utf-8")
    stderr_handle = stderr_path.open("a", encoding="utf-8")
    child_env = os.environ.copy()
    child_env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        command,
        cwd=str(repo_root),
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
        env=child_env,
    )
    return process, stdout_handle, stderr_handle, stdout_path, stderr_path


def _managed_child_snapshot(child: dict[str, Any]) -> dict[str, Any]:
    stdout_tail = _tail_file(child["stdout_path"])
    return {
        "name": child["name"],
        "command": child["command"],
        "pid": child["process"].pid,
        "running": child["process"].poll() is None,
        "returncode": child["process"].poll(),
        "restart_count": int(child.get("restart_count") or 0),
        "stdout_path": str(child["stdout_path"]),
        "stderr_path": str(child["stderr_path"]),
        "stdout_tail": stdout_tail,
        "stderr_tail": _tail_file(child["stderr_path"]),
        "parsed_json_tail": _parse_last_json(stdout_tail),
    }


def _write_managed_running_status(
    *,
    paths: Iterable[Path],
    symbols: list[str],
    symbol_source: str,
    plan: dict[str, Any],
    started_at: str,
    duration_seconds: float,
    health_interval_seconds: float,
    restart_exited_children: bool,
    run_until_stopped: bool,
    children: list[dict[str, Any]],
    health_samples: list[dict[str, Any]],
    log_root: Path,
) -> int:
    target_paths = list(paths)
    if not target_paths:
        return 0
    run_result = {
        "managed_run": True,
        "status": "MANAGED_RUN_RUNNING",
        "started_at": started_at,
        "duration_seconds": duration_seconds,
        "health_interval_seconds": health_interval_seconds,
        "restart_exited_children": bool(restart_exited_children),
        "run_until_stopped": bool(run_until_stopped),
        "started_child_count": len(children),
        "health_samples": health_samples,
        "child_results": [_managed_child_snapshot(child) for child in children],
        "log_root": str(log_root),
    }
    payload = build_status_payload(
        symbols=symbols,
        symbol_source=symbol_source,
        plan=plan,
        run_result=run_result,
        run_bounded=False,
    )
    for path in target_paths:
        _write_json(path, payload)
    return len(target_paths)


def run_managed_supervision(
    *,
    repo_root: Path,
    plan: dict[str, Any],
    duration_seconds: float,
    health_interval_seconds: float,
    log_root: Path,
    restart_exited_children: bool,
    rolling_status_paths: Iterable[Path] = (),
    rolling_status_symbols: list[str] | None = None,
    rolling_status_symbol_source: str = "unknown",
    run_until_stopped: bool = False,
    stop_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    started_at = utc_now_iso()
    duration = max(1.0, float(duration_seconds))
    interval = max(0.5, float(health_interval_seconds))
    deadline = None if run_until_stopped else time.monotonic() + duration
    should_stop = stop_requested or (lambda: False)
    children: list[dict[str, Any]] = []
    all_commands = [
        (f"direct_batch_{index}", command)
        for index, command in enumerate(plan.get("direct_commands") or [], start=1)
    ]
    all_commands.append(("microstructure_monitor", list(plan.get("monitor_command") or [])))
    for name, command in all_commands:
        if not command:
            continue
        process, stdout_handle, stderr_handle, stdout_path, stderr_path = _spawn_logged_child(
            repo_root=repo_root,
            command=command,
            log_root=log_root,
            name=name,
        )
        children.append(
            {
                "name": name,
                "command": command,
                "process": process,
                "stdout_handle": stdout_handle,
                "stderr_handle": stderr_handle,
                "stdout_path": stdout_path,
                "stderr_path": stderr_path,
                "restart_count": 0,
            }
        )

    health_samples: list[dict[str, Any]] = []
    rolling_status_write_count = 0
    stopped_by_request = False
    try:
        while True:
            if should_stop():
                stopped_by_request = True
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            sample_children: list[dict[str, Any]] = []
            for child in children:
                process = child["process"]
                returncode = process.poll()
                if returncode is not None and restart_exited_children:
                    child["stdout_handle"].close()
                    child["stderr_handle"].close()
                    process, stdout_handle, stderr_handle, stdout_path, stderr_path = _spawn_logged_child(
                        repo_root=repo_root,
                        command=child["command"],
                        log_root=log_root,
                        name=child["name"],
                    )
                    child.update(
                        {
                            "process": process,
                            "stdout_handle": stdout_handle,
                            "stderr_handle": stderr_handle,
                            "stdout_path": stdout_path,
                            "stderr_path": stderr_path,
                            "restart_count": int(child.get("restart_count") or 0) + 1,
                        }
                    )
                    returncode = None
                sample_children.append(
                    {
                        "name": child["name"],
                        "pid": child["process"].pid,
                        "running": child["process"].poll() is None,
                        "returncode": child["process"].poll(),
                        "restart_count": int(child.get("restart_count") or 0),
                    }
                )
            health_samples.append({"sampled_at": utc_now_iso(), "children": sample_children})
            rolling_status_write_count += _write_managed_running_status(
                paths=rolling_status_paths,
                symbols=rolling_status_symbols or [],
                symbol_source=rolling_status_symbol_source,
                plan=plan,
                started_at=started_at,
                duration_seconds=duration,
                health_interval_seconds=interval,
                restart_exited_children=restart_exited_children,
                run_until_stopped=run_until_stopped,
                children=children,
                health_samples=health_samples,
                log_root=log_root,
            )
            if deadline is None:
                time.sleep(interval)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(interval, remaining))
    finally:
        for child in children:
            _terminate_child(child["process"])
            child["stdout_handle"].close()
            child["stderr_handle"].close()

    child_results: list[dict[str, Any]] = []
    for child in children:
        stdout_tail = _tail_file(child["stdout_path"])
        child_results.append(
            {
                "name": child["name"],
                "command": child["command"],
                "pid": child["process"].pid,
                "returncode": child["process"].returncode,
                "running_after_stop": child["process"].poll() is None,
                "restart_count": int(child.get("restart_count") or 0),
                "stdout_path": str(child["stdout_path"]),
                "stderr_path": str(child["stderr_path"]),
                "stdout_tail": stdout_tail,
                "stderr_tail": _tail_file(child["stderr_path"]),
                "parsed_json_tail": _parse_last_json(stdout_tail),
            }
        )
    return {
        "status": "MANAGED_RUN_STOPPED" if stopped_by_request else "MANAGED_RUN_COMPLETED",
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "duration_seconds": duration,
        "health_interval_seconds": interval,
        "restart_exited_children": bool(restart_exited_children),
        "run_until_stopped": bool(run_until_stopped),
        "stopped_by_request": bool(stopped_by_request),
        "started_child_count": len(children),
        "health_samples": health_samples,
        "child_results": child_results,
        "rolling_status_write_count": rolling_status_write_count,
    }


def _status_paths(repo_root: Path) -> tuple[Path, Path]:
    return repo_root / PUBLIC_STATUS_REL, repo_root / GOAL_STATUS_REL


def _typed_status_paths(repo_root: Path, status: str) -> tuple[Path, ...]:
    if status == "PLAN_READY":
        return repo_root / PUBLIC_PLAN_STATUS_REL, repo_root / GOAL_PLAN_STATUS_REL
    if status == "BOUNDED_RUN_COMPLETED":
        return repo_root / PUBLIC_BOUNDED_STATUS_REL, repo_root / GOAL_BOUNDED_STATUS_REL
    if status in {"MANAGED_RUN_RUNNING", "MANAGED_RUN_COMPLETED", "MANAGED_RUN_STOPPED"}:
        return repo_root / PUBLIC_MANAGED_STATUS_REL, repo_root / GOAL_MANAGED_STATUS_REL
    if status in {"RUNTIME_OWNER_INSPECTED", "RUNTIME_OWNER_CONFLICT"}:
        return repo_root / PUBLIC_OWNER_STATUS_REL, repo_root / GOAL_OWNER_STATUS_REL
    return ()


def _managed_signal_stop_callback() -> tuple[Callable[[], bool], Callable[[], None]]:
    stop_state = {"requested": False}
    previous_handlers: dict[int, Any] = {}

    def request_stop(signum, frame) -> None:
        stop_state["requested"] = True

    for managed_signal in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[int(managed_signal)] = signal.getsignal(managed_signal)
        signal.signal(managed_signal, request_stop)

    def restore() -> None:
        for managed_signal, previous_handler in previous_handlers.items():
            signal.signal(managed_signal, previous_handler)

    return lambda: bool(stop_state["requested"]), restore


def build_status_payload(
    *,
    symbols: list[str],
    symbol_source: str,
    plan: dict[str, Any],
    run_result: dict[str, Any] | None,
    run_bounded: bool,
) -> dict[str, Any]:
    monitor_tail = (run_result or {}).get("monitor_result", {}).get("parsed_json_tail") if isinstance(run_result, dict) else None
    monitor_feed_summary = monitor_tail.get("feed_summary") if isinstance(monitor_tail, dict) else None
    managed_monitor_tail = None
    if isinstance(run_result, dict):
        for child in run_result.get("child_results") or []:
            if child.get("name") == "microstructure_monitor":
                managed_monitor_tail = child.get("parsed_json_tail")
                break
    if not monitor_feed_summary and isinstance(managed_monitor_tail, dict):
        monitor_feed_summary = managed_monitor_tail.get("feed_summary")
    status = "PLAN_READY"
    if run_bounded:
        status = "BOUNDED_RUN_COMPLETED"
    if isinstance(run_result, dict) and run_result.get("status"):
        status = str(run_result.get("status") or "MANAGED_RUN_COMPLETED")
    elif isinstance(run_result, dict) and run_result.get("managed_run") is True:
        status = "MANAGED_RUN_COMPLETED"
    return {
        "schema_version": "v2_microstructure_runtime_supervisor_status_v1",
        "worker_id": WORKER_ID,
        "goal_id": PRODUCTION_GOAL_ID,
        "generated_at": utc_now_iso(),
        "status": status,
        "symbol_source": symbol_source,
        "symbols": symbols,
        "symbol_count": len(symbols),
        "plan": plan,
        "run_bounded": bool(run_bounded),
        "run_result": run_result or {},
        "monitor_feed_summary": monitor_feed_summary or {},
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "test_order_submitted": False,
        "cancel_or_modify_order": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "transfer_or_withdrawal": False,
        "old_redis_writes": False,
        "redis_trim": False,
        "paper_online_runtime_restart": False,
        "legacy_restart": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--paper-candidates", action="store_true")
    parser.add_argument("--paper-status-path", default=str(REPO_ROOT / DEFAULT_PAPER_STATUS_REL))
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--replay-root", default=str(REPO_ROOT / DEFAULT_REPLAY_ROOT_REL))
    parser.add_argument("--binance-speed", choices=("100ms", "250ms", "500ms"), default="250ms")
    parser.add_argument("--binance-include-book-ticker", action="store_true")
    parser.add_argument("--binance-include-diff-depth", action="store_true")
    parser.add_argument("--direct-max-messages", type=int, default=600)
    parser.add_argument("--direct-loop-max-runs", type=int, default=1)
    parser.add_argument("--direct-interval-seconds", type=float, default=0.0)
    parser.add_argument("--direct-venue-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--direct-ws-close-timeout-seconds", type=float, default=1.0)
    parser.add_argument("--freshness-stale-bound-ms", type=float, default=1500.0)
    parser.add_argument("--monitor-loop-max-runs", type=int, default=3)
    parser.add_argument("--monitor-interval-seconds", type=float, default=1.0)
    parser.add_argument("--monitor-ttl-seconds", type=int, default=300)
    parser.add_argument("--monitor-timeframe", default="1m")
    parser.add_argument("--monitor-exchanges", default="binance")
    parser.add_argument("--filter-provider-supported-symbols", action="store_true")
    parser.add_argument("--inspect-runtime-owner", action="store_true")
    parser.add_argument("--require-no-conflicting-owner", action="store_true")
    parser.add_argument("--run-bounded", action="store_true")
    parser.add_argument("--run-managed", action="store_true")
    parser.add_argument("--warmup-seconds", type=float, default=5.0)
    parser.add_argument("--child-timeout-seconds", type=float, default=90.0)
    parser.add_argument("--managed-duration-seconds", type=float, default=60.0)
    parser.add_argument("--managed-health-interval-seconds", type=float, default=5.0)
    parser.add_argument("--managed-log-root", default=str(REPO_ROOT / DEFAULT_MANAGED_LOG_ROOT_REL))
    parser.add_argument("--managed-until-stopped", action="store_true")
    parser.add_argument("--restart-exited-children", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols, symbol_source = resolve_supervised_symbols(
        explicit=args.symbols,
        paper_candidates=bool(args.paper_candidates),
        paper_status_path=Path(args.paper_status_path),
        smoke_test=bool(args.smoke_test),
        max_symbols=int(args.max_symbols),
    )
    provider_filter_status: dict[str, Any] = {"enabled": False}
    if args.filter_provider_supported_symbols:
        symbols, provider_filter_status = filter_symbols_by_provider_support(
            symbols=symbols,
            exchange="binance",
            enabled=True,
        )
        symbol_source = f"{symbol_source}_provider_supported"
    plan = build_supervision_plan(
        symbols=symbols,
        python_executable=str(args.python_executable),
        replay_root=Path(args.replay_root),
        batch_size=int(args.batch_size),
        direct_max_messages=int(args.direct_max_messages),
        direct_loop_max_runs=int(args.direct_loop_max_runs),
        direct_interval_seconds=float(args.direct_interval_seconds),
        direct_venue_timeout_seconds=float(args.direct_venue_timeout_seconds),
        direct_ws_close_timeout_seconds=float(args.direct_ws_close_timeout_seconds),
        freshness_stale_bound_ms=float(args.freshness_stale_bound_ms),
        binance_speed=str(args.binance_speed),
        binance_include_book_ticker=bool(args.binance_include_book_ticker),
        binance_include_diff_depth=bool(args.binance_include_diff_depth),
        monitor_loop_max_runs=int(args.monitor_loop_max_runs),
        monitor_interval_seconds=float(args.monitor_interval_seconds),
        monitor_ttl_seconds=int(args.monitor_ttl_seconds),
        monitor_timeframe=str(args.monitor_timeframe),
        monitor_exchanges=str(args.monitor_exchanges),
        provider_filter_status=provider_filter_status,
    )
    run_result = None
    if args.run_bounded and args.run_managed:
        raise SystemExit("--run-bounded and --run-managed are mutually exclusive")
    if args.managed_until_stopped and not args.run_managed:
        raise SystemExit("--managed-until-stopped requires --run-managed")
    if args.inspect_runtime_owner or args.require_no_conflicting_owner:
        runtime_owner_status = inspect_runtime_owner_processes(
            expected_symbols=symbols,
            provider_filter_status=provider_filter_status,
        )
        plan["runtime_owner_status"] = runtime_owner_status
        if args.require_no_conflicting_owner and runtime_owner_status.get("conflicting_external_owner"):
            run_result = {
                "status": "RUNTIME_OWNER_CONFLICT",
                "managed_run": False,
                "run_started": False,
                "runtime_owner_status": runtime_owner_status,
            }
            payload = build_status_payload(
                symbols=symbols,
                symbol_source=symbol_source,
                plan=plan,
                run_result=run_result,
                run_bounded=False,
            )
            for path in (*_status_paths(REPO_ROOT), *_typed_status_paths(REPO_ROOT, str(payload.get("status") or ""))):
                _write_json(path, payload)
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return 2
    if args.run_bounded:
        run_result = run_bounded_supervision(
            repo_root=REPO_ROOT,
            plan=plan,
            warmup_seconds=float(args.warmup_seconds),
            child_timeout_seconds=float(args.child_timeout_seconds),
        )
    if args.run_managed:
        stop_requested = None
        restore_signal_handlers = lambda: None
        if args.managed_until_stopped:
            stop_requested, restore_signal_handlers = _managed_signal_stop_callback()
        try:
            run_result = run_managed_supervision(
                repo_root=REPO_ROOT,
                plan=plan,
                duration_seconds=float(args.managed_duration_seconds),
                health_interval_seconds=float(args.managed_health_interval_seconds),
                log_root=Path(args.managed_log_root),
                restart_exited_children=bool(args.restart_exited_children),
                rolling_status_paths=(
                    *_status_paths(REPO_ROOT),
                    *_typed_status_paths(REPO_ROOT, "MANAGED_RUN_RUNNING"),
                ),
                rolling_status_symbols=symbols,
                rolling_status_symbol_source=symbol_source,
                run_until_stopped=bool(args.managed_until_stopped),
                stop_requested=stop_requested,
            )
        finally:
            restore_signal_handlers()
        run_result["managed_run"] = True
    if run_result is None and args.inspect_runtime_owner:
        run_result = {
            "status": "RUNTIME_OWNER_INSPECTED",
            "managed_run": False,
            "run_started": False,
            "runtime_owner_status": plan.get("runtime_owner_status") or {},
        }
    payload = build_status_payload(
        symbols=symbols,
        symbol_source=symbol_source,
        plan=plan,
        run_result=run_result,
        run_bounded=bool(args.run_bounded),
    )
    for path in (*_status_paths(REPO_ROOT), *_typed_status_paths(REPO_ROOT, str(payload.get("status") or ""))):
        _write_json(path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
