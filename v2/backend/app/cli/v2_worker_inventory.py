from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v2.backend.app.runtime_contracts.worker_status import (
    V2WorkerStatus,
    WorkerMigrationStatus,
    utc_now,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "codex_independent_v2_support" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "codex_independent_v2_support" / "latest"
BACKLOG_PATH = REPO_ROOT / "claude_worklog" / "final_readiness" / "script_migration_backlog" / "latest" / "script_migration_backlog.json"


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _read_json(path: Path, fallback: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {} if fallback is None else fallback


def _rel(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _process_lines() -> list[str]:
    try:
        output = subprocess.check_output(["ps", "-eo", "pid,ppid,etimes,pcpu,pmem,cmd"], text=True)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in output.splitlines() if "grep " not in line]


def _pid_from_process(lines: list[str], marker: str) -> int | None:
    for line in lines:
        if marker not in line:
            continue
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        try:
            return int(parts[0])
        except ValueError:
            return None
    return None


def _text_has_any(path: Path, tokens: tuple[str, ...]) -> bool:
    try:
        text = path.read_text(errors="ignore").lower()
    except OSError:
        return False
    return any(token in text for token in tokens)


def _danger_tokens() -> tuple[str, ...]:
    return (
        "create_" + "order",
        "cancel_" + "order",
        "change_" + "leverage",
        "change_" + "margin",
        "futures_" + "create_" + "order",
        "futures_" + "change_" + "leverage",
        "futures_" + "change_" + "margin_type",
    )


def _redis_write_tokens() -> tuple[str, ...]:
    return (
        "x" + "add",
        "h" + "set",
        "x" + "del",
        "x" + "trim",
        "flush" + "all",
        "flush" + "db",
    )


def _has_test(root: Path, fragments: tuple[str, ...]) -> bool:
    tests_root = root / "v2" / "backend" / "tests"
    if not tests_root.exists():
        return False
    for path in tests_root.rglob("test_*.py"):
        name = str(path).lower()
        if all(fragment in name for fragment in fragments):
            return True
    return False


def _contains_category(backlog: Any, category: str) -> bool:
    if isinstance(backlog, dict):
        return any(_contains_category(value, category) for value in backlog.values())
    if isinstance(backlog, list):
        return any(_contains_category(value, category) for value in backlog)
    return category in str(backlog)


@dataclass(frozen=True)
class WorkerSpec:
    category: str
    purpose: str
    legacy_path: str | None
    v2_path: str | None
    command: str | None
    test_fragments: tuple[str, ...]
    payload_path: str | None
    gui_route: str | None
    runtime_marker: str | None = None
    legacy_dependency_mode: str = "none"
    preferred_missing_status: WorkerMigrationStatus = WorkerMigrationStatus.MISSING_IN_V2


WORKER_SPECS: tuple[WorkerSpec, ...] = (
    WorkerSpec("market_ingestor", "V2 market data API and source ingestion surface", "legacy_reference/ingest", "v2/backend/app/api/v1/ingestors.py", None, ("ingestor",), None, "/mission-control"),
    WorkerSpec("coinank_bridge", "Coinank market-intelligence bridge into V2 public truth", "legacy_reference/ingest/live_coinank.py", "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json", None, ("coinank",), "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json", "/mission-control", legacy_dependency_mode="readonly_wrapper", preferred_missing_status=WorkerMigrationStatus.WRAPPED_READONLY_ONLY),
    WorkerSpec("feature_snapshot_builder", "Feature snapshot contract and freshness builder", "legacy_reference/feature_pipeline.py", "v2/backend/app/services/feature_assembly.py", None, ("feature", "snapshot"), None, "/monitor"),
    WorkerSpec("trainer_bridge", "Trainer prediction bridge into current V2 payloads", "legacy_module:rl.hybrid_trainer", "v2/backend/app/composition/trainer_prediction_output/runtime.py", None, ("trainer",), "v2/frontend/public/operator_runtime/paper_online/latest/trainer_prediction_current_record.json", "/trainer", legacy_dependency_mode="readonly_wrapper", preferred_missing_status=WorkerMigrationStatus.WRAPPED_READONLY_ONLY),
    WorkerSpec("orchestrator_adapter", "V2 orchestrator decision adapter", "legacy_module:rl.orchestrator_worker", "v2/backend/app/composition/orchestrator_decision/runtime.py", None, ("orchestrator",), "v2/frontend/public/operator_runtime/paper_online/latest/current_signal_lineage.json", "/signals"),
    WorkerSpec("signal_publisher", "Current signal publication and lineage surface", "legacy_reference/trading/signal_router.py", "v2/backend/app/services/signal_publisher.py", None, ("signal",), "v2/frontend/public/operator_runtime/paper_online/latest/current_signal_lineage.json", "/signals"),
    WorkerSpec("risk_gateway_worker", "Fail-closed V2 risk decision worker", "legacy_reference/trading/risk", "v2/backend/app/composition/risk_gateway/runtime.py", None, ("risk_gateway",), "v2/frontend/public/operator_runtime/paper_online/latest/current_risk_decisions.json", "/risk"),
    WorkerSpec("paper_execution_worker", "Paper-only execution loop and evidence", "legacy_reference/trading/execution_engine.py", "v2/backend/app/cli/paper_online_runtime.py", "python3 -m v2.backend.app.cli.paper_online_runtime --once --write-evidence", ("paper_online_runtime",), "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json", "/paper", runtime_marker="paper_online_runtime", preferred_missing_status=WorkerMigrationStatus.PAPER_ONLY),
    WorkerSpec("execution_ledger_worker", "Paper execution ledger projection", "legacy_reference/trading/execution_engine.py", "v2/backend/app/composition/paper_execution_ledger/runtime.py", None, ("paper_execution_ledger",), "v2/frontend/public/operator_runtime/paper_online/latest/paper_ledger_tail.json", "/paper"),
    WorkerSpec("account_position_monitor", "Read-only account and position evidence", "legacy_reference/trading/position_reporter.py", "v2/backend/app/cli/account_permission_and_soak.py", "python3 -m v2.backend.app.cli.account_permission_and_soak --write-evidence", ("account_permission",), "v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json", "/risk"),
    WorkerSpec("replay_worker", "Replay/backtest evidence runner", "legacy_reference/replay", "v2/backend/app/composition/replay_backtest_runner/runtime.py", None, ("replay",), None, "/replay"),
    WorkerSpec("script_monitor_worker", "Supervisor and migration monitor surface", "claude_worklog/tools/agent_supervisor.py", "claude_worklog/tools/agent_supervisor.py", None, ("agent_supervisor",), None, "/monitor", runtime_marker="agent_supervisor.py", legacy_dependency_mode="monitor_only"),
    WorkerSpec("config_manager", "Configuration guard and operator state manager", "legacy_reference/config.py", "v2/backend/app/settings.py", None, ("settings",), None, "/admin"),
    WorkerSpec("admin_ai_backend", "Admin AI evidence query backend", "legacy_reference/Public Dashboard/api.py", "v2/backend/app/api/v1/claude_admin.py", None, ("claude_admin",), None, "/admin"),
    WorkerSpec("live_execution_stub", "Live execution stays blocked; stub only", "legacy_reference/trading/trader.py", "v2/backend/app/composition/live_canary_blocker_guard/runtime.py", None, ("live_canary",), "v2/frontend/public/v2_paper_online_recovery/latest/operator_dashboard_payload.json", "/risk", preferred_missing_status=WorkerMigrationStatus.BLOCKED),
)


def classify_worker(root: Path, spec: WorkerSpec, backlog: Any, processes: list[str]) -> dict[str, Any]:
    v2_path = root / spec.v2_path if spec.v2_path and not spec.v2_path.startswith("legacy_module:") else None
    legacy_path = root / spec.legacy_path if spec.legacy_path and not spec.legacy_path.startswith("legacy_module:") else None
    v2_exists = bool(v2_path and v2_path.exists())
    legacy_exists = bool(legacy_path and legacy_path.exists()) or bool(spec.legacy_path and spec.legacy_path.startswith("legacy_module:"))
    test_present = _has_test(root, spec.test_fragments)
    backlog_only = _contains_category(backlog, spec.category)
    runtime_pid = _pid_from_process(processes, spec.runtime_marker) if spec.runtime_marker else None
    command_present = bool(spec.command)
    payload_present = bool(spec.payload_path and (root / spec.payload_path).exists())

    if spec.category == "paper_execution_worker" and v2_exists and command_present:
        status = WorkerMigrationStatus.PAPER_ONLY
    elif spec.legacy_dependency_mode == "readonly_wrapper" and v2_exists:
        status = WorkerMigrationStatus.WRAPPED_READONLY_ONLY
    elif v2_exists and command_present and test_present and payload_present and runtime_pid is not None:
        status = WorkerMigrationStatus.MIGRATED_AND_RUNNING
    elif v2_exists and command_present and test_present and payload_present:
        status = WorkerMigrationStatus.MIGRATED_NOT_RUNNING
    elif backlog_only and not v2_exists:
        status = WorkerMigrationStatus.BACKLOG_ONLY
    elif legacy_exists and not v2_exists:
        status = WorkerMigrationStatus.LEGACY_ONLY
    elif v2_exists:
        status = WorkerMigrationStatus.BLOCKED
    else:
        status = spec.preferred_missing_status

    blocker: str | None = None
    blockers: list[str] = []
    if status == WorkerMigrationStatus.BACKLOG_ONLY:
        blocker = "backlog_item_only_not_migrated"
        blockers.append(blocker)
    elif status == WorkerMigrationStatus.LEGACY_ONLY:
        blocker = "legacy_only_not_v2_migration"
        blockers.append(blocker)
    elif status == WorkerMigrationStatus.BLOCKED:
        missing = []
        if not command_present:
            missing.append("runnable_command")
        if not test_present:
            missing.append("test")
        if spec.payload_path and not payload_present:
            missing.append("public_payload")
        blocker = "missing_" + "_".join(missing or ["runtime_evidence"])
        blockers.append(blocker)
    elif status == WorkerMigrationStatus.MISSING_IN_V2:
        blocker = "missing_v2_worker"
        blockers.append(blocker)
    elif status == WorkerMigrationStatus.WRAPPED_READONLY_ONLY:
        blocker = "readonly_wrapper_not_independent_runtime"
        blockers.append(blocker)

    scan_paths = [path for path in (v2_path, legacy_path) if path and path.is_file()]
    redis_write_risk = any(_text_has_any(path, _redis_write_tokens()) for path in scan_paths)
    live_action_risk = any(_text_has_any(path, _danger_tokens()) for path in scan_paths)

    status_record = V2WorkerStatus(
        worker_id=spec.category,
        category=spec.category,
        purpose=spec.purpose,
        status=status,
        generated_at=utc_now(),
        freshness_seconds=0,
        source_paths=tuple(path for path in (spec.legacy_path, spec.v2_path) if path),
        evidence_status="EVIDENCE_PRESENT" if v2_exists or payload_present else "EVIDENCE_MISSING",
        legacy_dependency_mode=spec.legacy_dependency_mode,
        runtime_pid=runtime_pid,
        runnable_command=spec.command,
        public_payload_path=spec.payload_path,
        test_status="present" if test_present else "missing",
        codex_status="classified_by_codex_support_inventory",
        blockers=tuple(blockers),
        next_action=_next_action(spec.category, status, blocker),
    ).to_dict()

    return {
        **status_record,
        "legacy_path": spec.legacy_path,
        "v2_path": spec.v2_path if v2_exists else None,
        "purpose": spec.purpose,
        "category": spec.category,
        "runnable_command": spec.command,
        "tests": "present" if test_present else "missing",
        "payload_path": spec.payload_path if payload_present else None,
        "gui_route": spec.gui_route,
        "redis_reads": "read_reference_only_or_none",
        "redis_writes": "write_reference_detected_readonly_source" if redis_write_risk else "none_detected",
        "exchange_calls": "mutation_reference_detected_readonly_source" if live_action_risk else "none_detected",
        "old_redis_write_risk": redis_write_risk,
        "live_action_risk": live_action_risk,
        "status": status.value,
        "blocker": blocker,
        "next_action": _next_action(spec.category, status, blocker),
    }


def _next_action(category: str, status: WorkerMigrationStatus, blocker: str | None) -> str:
    if status == WorkerMigrationStatus.MIGRATED_AND_RUNNING:
        return "keep worker monitored and publish fresh public payload"
    if status == WorkerMigrationStatus.MIGRATED_NOT_RUNNING:
        return "start or supervise the V2 worker after Claude migration owner confirms"
    if status == WorkerMigrationStatus.PAPER_ONLY:
        return "keep paper/shadow evidence fresh; do not promote to live"
    if status == WorkerMigrationStatus.WRAPPED_READONLY_ONLY:
        return f"Claude should port {category} into independent V2 runtime"
    if status == WorkerMigrationStatus.BACKLOG_ONLY:
        return f"Claude should schedule {category} as P0/P1 migration work"
    if blocker:
        return f"resolve {blocker}"
    return f"create V2 worker for {category}"


def build_inventory(root: Path = REPO_ROOT) -> dict[str, Any]:
    backlog = _read_json(root / "claude_worklog" / "final_readiness" / "script_migration_backlog" / "latest" / "script_migration_backlog.json", {})
    processes = _process_lines()
    workers = [classify_worker(root, spec, backlog, processes) for spec in WORKER_SPECS]
    status_counts: dict[str, int] = {}
    for worker in workers:
        status_counts[worker["status"]] = status_counts.get(worker["status"], 0) + 1
    migrated_count = sum(1 for worker in workers if worker["status"] in {"MIGRATED_AND_RUNNING", "MIGRATED_NOT_RUNNING"})
    next_worker = next(
        (worker["category"] for worker in workers if worker["status"] in {"MISSING_IN_V2", "LEGACY_ONLY", "BACKLOG_ONLY", "BLOCKED", "WRAPPED_READONLY_ONLY"}),
        None,
    )
    return {
        "generated_at": utc_now(),
        "codex_lane": "CODEX_INDEPENDENT_BUILDER_LANE_ACTIVE",
        "live_gate": "blocked_human_only",
        "legacy_mode": "read_only_reference",
        "backlog_source_present": (root / BACKLOG_PATH.relative_to(REPO_ROOT)).exists(),
        "worker_count": len(workers),
        "migrated_count": migrated_count,
        "status_counts": status_counts,
        "next_recommended_claude_worker": next_worker,
        "workers": workers,
        "old_redis_writes": "none_performed",
        "exchange_actions": "none_performed",
    }


def build_report(payload: dict[str, Any]) -> str:
    rows = []
    for worker in payload["workers"]:
        rows.append(
            "| {category} | {status} | {blocker} | {next_action} |".format(
                category=worker["category"],
                status=worker["status"],
                blocker=worker.get("blocker") or "none",
                next_action=worker["next_action"],
            )
        )
    return "\n".join(
        [
            "# V2 Worker Inventory Report",
            "",
            f"Generated: {payload['generated_at']}",
            "",
            "Codex classified worker migration coverage without mutating legacy, old Redis, or exchange state.",
            "",
            f"Live gate: `{payload['live_gate']}`",
            f"Workers: {payload['worker_count']}",
            f"Migrated count: {payload['migrated_count']}",
            f"Next recommended Claude worker: `{payload.get('next_recommended_claude_worker')}`",
            "",
            "| Category | Status | Blocker | Next action |",
            "| --- | --- | --- | --- |",
            *rows,
            "",
            "Backlog-only entries are not counted as migrated. Read-only wrappers are not counted as independent V2 runtime.",
        ]
    )


def write_outputs(payload: dict[str, Any]) -> None:
    _write_json(FINAL_DIR / "v2_worker_inventory.json", payload)
    _write_json(PUBLIC_DIR / "v2_worker_inventory.json", payload)
    _write_text(FINAL_DIR / "V2_WORKER_INVENTORY_REPORT.md", build_report(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build V2 worker inventory support payload.")
    parser.add_argument("--write", action="store_true", help="write inventory artifacts")
    args = parser.parse_args(argv)
    payload = build_inventory(REPO_ROOT)
    if args.write:
        write_outputs(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
