#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REBUILD = Path("/home/wali/Desktop/AI BOT REBUILD")
LEGACY = Path("/home/wali/Desktop/AI BOT")
OUT = REBUILD / "claude_worklog/legacy_readonly_audit"

WATCH_COMPONENTS = [
    "live_binance.py",
    "live_kucoin.py",
    "live_coinank.py",
    "live_binance_liquidations.py",
    "liquidation_bridge.py",
    "liquidation_levels_engine.py",
    "realtime_price_provider.py",
    "live_coinank_global_aggregator.py",
    "ohlcv_resampler_hotfix.py",
    "feature_pipeline.py",
    "live_technical_analysis.py",
    "monitor_trainer_predictions.py",
    "monitor_trainer_prices.py",
    "monitor_portfolio_primary.py",
    "monitor_portfolio_asjad.py",
    "vpn_monitor.py",
    "system_telegram_monitor.py",
    "monitor_system_memory.py",
]

PROCESS_PATTERNS = [
    "live_binance.py",
    "live_kucoin.py",
    "live_coinank.py",
    "live_binance_liquidations.py",
    "liquidation_bridge.py",
    "liquidation_levels_engine.py",
    "realtime_price_provider.py",
    "live_coinank_global_aggregator.py",
    "ingest.live_coinapi_wsds",
    "ingest.live_coinapi_v1",
    "ohlcv_resampler_hotfix.py",
    "feature_pipeline.py",
    "live_technical_analysis.py",
    "rl.orchestrator_worker",
    "rl.hybrid_trainer",
    "trading/trader.py",
    "trading/trader-asjad.py",
    "monitor_trainer_predictions.py",
    "monitor_trainer_prices.py",
    "monitor_portfolio",
]

SECRET_WORDS = re.compile(r"(secret|token|password|api[_-]?key|private)", re.I)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REBUILD,
        shell=isinstance(cmd, str),
        text=True,
        capture_output=True,
        check=False,
    )


def write(path: Path, text: str) -> None:
    def normalize_generated(value: str) -> str:
        value = re.sub(r"Generated: [^\n]+", "Generated: <stable>", value)
        value = re.sub(
            r"db(\d+):keys=\d+,expires=\d+,avg_ttl=\d+",
            r"db\1:keys=<stable>,expires=<stable>,avg_ttl=<stable>",
            value,
        )
        value = re.sub(r"\bcount=\d+\b", "count=<stable>", value)
        return re.sub(r"\b(XLEN|LLEN|HLEN|ZCARD|SCARD|STRLEN)=\d+\b", r"\1=<stable>", value)

    path.parent.mkdir(parents=True, exist_ok=True)
    if (
        path.name == "05_REDIS_READONLY_KEY_STREAM_INVENTORY.md"
        and path.exists()
        and os.environ.get("LEGACY_AUDIT_REFRESH_REDIS_INVENTORY") != "1"
    ):
        return
    if path.exists() and normalize_generated(path.read_text(errors="replace")) == normalize_generated(text):
        return
    path.write_text(text, encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_rel(path: Path) -> str:
    try:
        return path.relative_to(LEGACY).as_posix()
    except ValueError:
        return path.as_posix()


def find_legacy_file(name: str) -> list[Path]:
    if not LEGACY.exists():
        return []
    found: list[Path] = []
    direct = LEGACY / name
    if direct.is_file():
        found.append(direct)
    for path in LEGACY.rglob(Path(name).name):
        if path.is_file() and path not in found:
            found.append(path)
    return sorted(found)


def is_rebuild_automation_process(line: str) -> bool:
    markers = (
        "/home/wali/Desktop/AI BOT REBUILD",
        "claude_worklog/tools/",
        "claude --print",
        "codex exec",
        "ollama run",
        "agent_supervisor.py",
        "codex_non_live_watchdog.py",
        "parallel_capacity_scheduler.py",
        "legacy_readonly_audit_sentinel.py",
        "historical_pnl_trade_audit.py",
    )
    return any(marker in line for marker in markers)


def matching_process_lines(patterns: list[str]) -> list[str]:
    proc = run("ps -eo pid,ppid,cmd")
    return [
        line
        for line in proc.stdout.splitlines()
        if any(pattern in line for pattern in patterns) and not is_rebuild_automation_process(line)
    ]


def process_snapshot() -> str:
    lines = matching_process_lines(PROCESS_PATTERNS)
    return "\n".join(
        [
            "# Legacy Runtime Process Snapshot",
            "",
            f"Generated: {now()}",
            "",
            "Read-only process inspection. No services were restarted.",
            "",
            "```text",
            "\n".join(lines) if lines else "NO_MATCHING_LEGACY_PROCESSES_FOUND",
            "```",
            "",
        ]
    )


def startup_script_map() -> str:
    script = LEGACY / "scripts/start_all_services_production.sh"
    if not script.exists():
        return "# Legacy Startup Script Map\n\nMISSING scripts/start_all_services_production.sh\n"

    text = script.read_text(errors="replace")
    phase_lines: list[str] = []
    command_lines: list[str] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if re.search(
            r"phase|redis|nohup|python3|start_ingestor|hybrid_trainer|orchestrator_worker|trader",
            stripped,
            re.I,
        ):
            phase_lines.append(f"{idx}: {line}")
        if "python3" in stripped or "nohup" in stripped or "redis-server" in stripped:
            command_lines.append(f"{idx}: {line}")

    return "\n".join(
        [
            "# Legacy Startup Script Map",
            "",
            f"Generated: {now()}",
            "",
            f"Script: `{script}`",
            "",
            "## Relevant phase/service lines",
            "```text",
            "\n".join(phase_lines[:500]),
            "```",
            "",
            "## Start command lines",
            "```text",
            "\n".join(command_lines[:500]),
            "```",
            "",
        ]
    )


def code_function_inventory() -> str:
    rows = []
    for name in WATCH_COMPONENTS:
        for path in find_legacy_file(name):
            try:
                text = path.read_text(errors="replace")
                tree = ast.parse(text)
                funcs = [
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            except Exception as exc:
                funcs = [f"PARSE_ERROR:{exc}"]
                classes = []
            rows.append(
                {
                    "path": safe_rel(path),
                    "sha256": sha256(path),
                    "functions": funcs[:200],
                    "classes": classes[:100],
                }
            )

    lines = [
        "# Legacy Code Function Inventory",
        "",
        f"Generated: {now()}",
        "",
        "Read-only AST/hash inventory. No legacy files modified.",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row['path']}",
                f"- sha256: `{row['sha256']}`",
                f"- classes: {', '.join(row['classes']) if row['classes'] else '-'}",
                f"- functions: {', '.join(row['functions']) if row['functions'] else '-'}",
                "",
            ]
        )
    return "\n".join(lines)


def dependency_graph() -> str:
    return "\n".join(
        [
            "# Legacy Service Dependency Graph",
            "",
            f"Generated: {now()}",
            "",
            "Evidence-based approximate graph from startup script and known running services.",
            "",
            "```text",
            "redis-server",
            "  -> ingestors",
            "      -> live_binance.py",
            "      -> live_kucoin.py",
            "      -> live_coinank.py",
            "      -> live_binance_liquidations.py",
            "      -> live_coinank_global_aggregator.py",
            "      -> ingest.live_coinapi_wsds",
            "      -> ingest.live_coinapi_v1",
            "  -> market data bridges",
            "      -> liquidation_bridge.py",
            "      -> liquidation_levels_engine.py",
            "      -> realtime_price_provider.py",
            "  -> pipelines",
            "      -> ohlcv_resampler_hotfix.py",
            "      -> feature_pipeline.py",
            "      -> live_technical_analysis.py",
            "  -> trainer",
            "      -> rl.hybrid_trainer",
            "      -> monitor_trainer_predictions.py",
            "      -> monitor_trainer_prices.py",
            "  -> orchestrator",
            "      -> rl.orchestrator_worker",
            "  -> trader",
            "      -> trading/trader.py",
            "      -> trading/trader-asjad.py if enabled",
            "  -> portfolio monitors",
            "      -> monitor_portfolio_primary.py",
            "      -> monitor_portfolio_asjad.py",
            "```",
            "",
        ]
    )


def normalize_redis_key_pattern(key: str) -> str:
    key = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "<uuid>",
        key,
    )
    key = re.sub(r"\d+\.\d+", "<num>", key)
    return re.sub(r"\d{4,}", "<num>", key)


def redis_readonly_inventory(limit: int = 500) -> str:
    if not shutil.which("redis-cli"):
        return "# Redis Read-Only Key/Stream Inventory\n\nredis-cli not found.\n"

    lines = [
        "# Redis Read-Only Key/Stream Inventory",
        "",
        f"Generated: {now()}",
        "",
        "Read-only metadata only. No values dumped. No writes executed.",
        "",
    ]
    ping = run(["redis-cli", "PING"])
    if ping.returncode != 0:
        lines.extend(["Redis unavailable or auth required.", "", "```text", ping.stderr, "```"])
        return "\n".join(lines)

    lines.append(f"- PING: `{ping.stdout.strip()}`")
    info = run(["redis-cli", "INFO", "keyspace"])
    if info.returncode == 0:
        lines.extend(["", "## INFO keyspace", "```text", info.stdout.strip(), "```"])

    scan = run(f"redis-cli --scan | sort | head -n {limit}")
    keys = [key for key in scan.stdout.splitlines() if key.strip()]
    patterns: dict[tuple[str, str], int] = {}
    for key in keys:
        display = "[REDACTED_SECRET_LIKE_KEY_NAME]" if SECRET_WORDS.search(key) else normalize_redis_key_pattern(key)
        key_type = run(["redis-cli", "TYPE", key]).stdout.strip()
        patterns[(display, key_type)] = patterns.get((display, key_type), 0) + 1
    lines.extend(["", f"## Sampled key patterns (limit {limit})", ""])
    for (pattern, key_type), count in sorted(patterns.items()):
        lines.append(f"- `{pattern}` type={key_type} count={count}")
    return "\n".join(lines) + "\n"


def trainer_runtime_evidence() -> str:
    lines = matching_process_lines(["rl.hybrid_trainer", "monitor_trainer_predictions", "monitor_trainer_prices"])
    return "\n".join(
        [
            "# Trainer Runtime Evidence",
            "",
            f"Generated: {now()}",
            "",
            "Read-only process/log evidence.",
            "",
            "## Processes",
            "```text",
            "\n".join(lines) if lines else "NO_TRAINER_PROCESS_MATCHES",
            "```",
            "",
            "## Required V2 impact",
            "- preserve GPU/checkpoint/batching assumptions",
            "- detect process-alive / worker-dead",
            "- emit prediction_id and feature_snapshot_id",
            "- expose confidence attribution",
            "- block stale/missing feature input",
            "",
        ]
    )


def orchestrator_trader_evidence() -> str:
    lines = matching_process_lines(["orchestrator_worker", "trading/trader", "monitor_portfolio"])
    return "\n".join(
        [
            "# Orchestrator / Trader Runtime Evidence",
            "",
            f"Generated: {now()}",
            "",
            "Read-only process evidence.",
            "",
            "```text",
            "\n".join(lines) if lines else "NO_ORCHESTRATOR_TRADER_PROCESS_MATCHES",
            "```",
            "",
            "## Required V2 impact",
            "- decisions must include decision_id",
            "- risk gateway must default-deny stale/unsafe signals",
            "- paper ledger must capture open/close/reduce/hedge/block",
            "- shadow mode must compare legacy vs V2",
            "",
        ]
    )


def failure_case_register() -> str:
    existing = sorted((REBUILD / "claude_worklog/legacy_failure_cases").glob("*.md"))
    lines = ["# Legacy Failure Case Register", "", f"Generated: {now()}", ""]
    if not existing:
        lines.append("No legacy failure cases recorded yet.")
    for path in existing:
        lines.extend([f"## {path.name}", "", f"- path: `{path}`", ""])
        for line in path.read_text(errors="replace").splitlines()[:40]:
            if line.strip():
                lines.append(line)
        lines.append("")
    return "\n".join(lines)


def v2_build_impact_map() -> str:
    return "\n".join(
        [
            "# V2 Build Impact Map From Legacy Evidence",
            "",
            f"Generated: {now()}",
            "",
            "| Legacy evidence | V2 requirement impact | MVP lane |",
            "|---|---|---|",
            "| Trainer worker health gaps | trainer liveness, worker health, prediction output | paper_backtest_mvp |",
            "| LAB hedge unwind failure | risk gateway, paper ledger, replay scenario, explainability | paper_backtest_mvp |",
            "| Ingestor/process map | source freshness, feature snapshots, symbol aliases | legacy_parity |",
            "| Redis stream/key metadata | replay/backtest input discovery, no live writes | paper_backtest_mvp |",
            "| Orchestrator/trader process map | decision_id, risk_decision_id, execution_intent_id | paper_backtest_mvp |",
            "",
        ]
    )


def audit_index() -> str:
    return "\n".join(
        [
            "# Legacy Read-Only Audit Index",
            "",
            f"Generated: {now()}",
            "",
            "- `01_PROCESS_SNAPSHOT.md`",
            "- `02_STARTUP_SCRIPT_MAP.md`",
            "- `03_LEGACY_CODE_FUNCTION_INVENTORY.md`",
            "- `04_SERVICE_DEPENDENCY_GRAPH.md`",
            "- `05_REDIS_READONLY_KEY_STREAM_INVENTORY.md`",
            "- `06_TRAINER_RUNTIME_EVIDENCE.md`",
            "- `07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`",
            "- `08_FAILURE_CASE_REGISTER.md`",
            "- `09_V2_BUILD_IMPACT_MAP.md`",
            "- `10_GO_NO_GO.md`",
            "",
            "Legacy audit is read-only. No mutation performed.",
            "",
        ]
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    write(OUT / "00_AUDIT_INDEX.md", audit_index())
    write(OUT / "01_PROCESS_SNAPSHOT.md", process_snapshot())
    write(OUT / "02_STARTUP_SCRIPT_MAP.md", startup_script_map())
    write(OUT / "03_LEGACY_CODE_FUNCTION_INVENTORY.md", code_function_inventory())
    write(OUT / "04_SERVICE_DEPENDENCY_GRAPH.md", dependency_graph())
    write(OUT / "05_REDIS_READONLY_KEY_STREAM_INVENTORY.md", redis_readonly_inventory())
    write(OUT / "06_TRAINER_RUNTIME_EVIDENCE.md", trainer_runtime_evidence())
    write(OUT / "07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md", orchestrator_trader_evidence())
    write(OUT / "08_FAILURE_CASE_REGISTER.md", failure_case_register())
    write(OUT / "09_V2_BUILD_IMPACT_MAP.md", v2_build_impact_map())
    write(OUT / "10_GO_NO_GO.md", "LEGACY_READONLY_AUDIT_SENTINEL_READY\n")
    print("LEGACY_READONLY_AUDIT_SENTINEL_READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
