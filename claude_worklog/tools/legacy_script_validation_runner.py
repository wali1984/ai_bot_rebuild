#!/usr/bin/env python3
"""Static validator for scripts under v2/legacy_owned_runtime.

This intentionally does not import or execute legacy Python modules. The legacy
tree contains trading, cleanup, restart, and Redis-mutating entrypoints, so a
blanket runtime execution pass is unsafe. This validator gives every script a
traceable inventory row, an execution class, Python/shell syntax status, and a
static dependency scan.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEGACY_ROOT = REPO_ROOT / "v2" / "legacy_owned_runtime"
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "claude_worklog/final_readiness/legacy_script_validation_20260603/latest"
)
DEFAULT_PUBLIC_DIR = REPO_ROOT / "v2/frontend/public/legacy_script_validation_20260603/latest"
SCRIPT_SUFFIXES = {".py", ".sh", ".ps1"}

MUTATING_EXCHANGE_RE = re.compile(
    r"\b("
    r"futures_create_order|create_order|cancel_order|futures_cancel_order|"
    r"set_leverage|futures_change_leverage|change_leverage|"
    r"set_margin_mode|set_margin|futures_change_margin_type|change_margin"
    r")\b"
)
REDIS_WRITE_RE = re.compile(
    r"\.(set|setex|setnx|hset|hmset|xadd|rpush|lpush|sadd|zadd|delete|flushdb|flushall)\s*\("
)
DESTRUCTIVE_RE = re.compile(
    r"\b(flushdb|flushall|delete\s*\(|kill\s+-9|pkill|systemctl\s+restart|"
    r"systemctl\s+stop|shutdown|reboot|close_all_positions|cancel_orders)\b",
    re.IGNORECASE,
)
NETWORK_READ_RE = re.compile(
    r"\b(requests\.get|aiohttp\.ClientSession|urllib\.request\.urlopen|"
    r"websockets\.connect|websocket|ccxt|binance|kucoin|coinapi|coinank|"
    r"alphavantage|tokenmetrics)\b",
    re.IGNORECASE,
)
PAID_OR_KEYED_RE = re.compile(
    r"\b(COINAPI|TOKENMETRICS|ALPHAVANTAGE|LUNARCRUSH|NANSEN|COINGLASS|"
    r"coinapi_wsds|tokenmetrics|alphavantage)\b",
    re.IGNORECASE,
)
TRAINING_RE = re.compile(
    r"\b(stable_baselines3|PPO|gymnasium|torch|cuda|trainer|training|train_model)\b",
    re.IGNORECASE,
)
MAIN_GUARD_RE = re.compile(r"if\s+__name__\s*==\s*['\"]__main__['\"]")

KNOWN_SAFE_V2_PROBES = {
    "ingest/live_kucoin.py": "validated_by_v2_legacy_ingestor_adapter",
    "ingest/live_coinapi_v1.py": "validated_by_v2_legacy_ingestor_adapter",
    "ingest/live_coinank_global_aggregator.py": "validated_by_v2_coinank_and_liquidation_bridge",
    "ingest/liquidation_bridge.py": "validated_by_v2_coinank_and_liquidation_bridge",
    "ingest/realtime_price_provider.py": "covered_by_v2_native_ingestors_live_loop",
    "ingest/live_binance.py": "covered_by_v2_native_ingestors_live_loop",
}

LOCAL_TOP_LEVELS = {
    "__init__",
    "api",
    "config",
    "config_accounts",
    "full_runtime_closure",
    "ingest",
    "ingestors",
    "monitoring",
    "risk",
    "rl",
    "scripts",
    "services",
    "startup_baseline",
    "tools",
    "trading",
    "utils",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def list_scripts(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SCRIPT_SUFFIXES)


def python_syntax(path: Path, text: str) -> dict[str, Any]:
    try:
        compile(text, str(path), "exec", dont_inherit=True)
        return {"status": "ok", "error": None}
    except SyntaxError as exc:
        return {
            "status": "syntax_error",
            "error": {
                "type": "SyntaxError",
                "message": exc.msg,
                "line": exc.lineno,
                "offset": exc.offset,
                "text": (exc.text or "").strip(),
            },
        }
    except Exception as exc:
        return {
            "status": "compile_error",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }


def shell_syntax(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".sh":
        return {"status": "not_shell", "error": None}
    bash = shutil.which("bash")
    if not bash:
        return {"status": "not_checked_bash_missing", "error": "bash not found"}
    try:
        proc = subprocess.run(
            [bash, "-n", str(path)],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {"status": "check_error", "error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode == 0:
        return {"status": "ok", "error": None}
    return {"status": "syntax_error", "error": (proc.stderr or proc.stdout).strip()}


def powershell_syntax(path: Path) -> dict[str, Any]:
    if path.suffix.lower() != ".ps1":
        return {"status": "not_powershell", "error": None}
    pwsh = shutil.which("pwsh")
    if not pwsh:
        return {
            "status": "not_checked_pwsh_missing",
            "error": "pwsh not installed; file inventoried and classified only",
        }
    command = (
        "$errors=$null; "
        f"[System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw {json.dumps(str(path))}), [ref]$errors) | Out-Null; "
        "if ($errors -and $errors.Count -gt 0) { $errors | ConvertTo-Json -Compress; exit 1 }"
    )
    try:
        proc = subprocess.run(
            [pwsh, "-NoProfile", "-Command", command],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except Exception as exc:
        return {"status": "check_error", "error": f"{type(exc).__name__}: {exc}"}
    if proc.returncode == 0:
        return {"status": "ok", "error": None}
    return {"status": "syntax_error", "error": (proc.stderr or proc.stdout).strip()}


def imported_top_levels(text: str) -> tuple[set[str], str | None]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return set(), f"syntax_error:{exc.lineno}"
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            if node.module:
                imports.add(node.module.split(".", 1)[0])
    return imports, None


def collect_local_top_levels(legacy_root: Path) -> set[str]:
    local = set(LOCAL_TOP_LEVELS)
    for path in legacy_root.rglob("*.py"):
        if path.name == "__init__.py":
            local.add(path.parent.name)
        else:
            local.add(path.stem)
        try:
            top = path.relative_to(legacy_root).parts[0]
        except Exception:
            continue
        if top.endswith(".py"):
            local.add(Path(top).stem)
        else:
            local.add(top)
    return local


def dependency_scan(imports: set[str], local_top_levels: set[str]) -> dict[str, Any]:
    missing: list[str] = []
    available: list[str] = []
    skipped_local_or_stdlib: list[str] = []
    stdlib = getattr(sys, "stdlib_module_names", set())
    for name in sorted(imports):
        if not name or name in local_top_levels or name in stdlib:
            skipped_local_or_stdlib.append(name)
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                spec = __import__("importlib.util").util.find_spec(name)
        except Exception:
            spec = None
        if spec is None:
            missing.append(name)
        else:
            available.append(name)
    return {
        "available_third_party": available,
        "missing_third_party": missing,
        "skipped_local_or_stdlib": skipped_local_or_stdlib,
    }


def classify(path: Path, text: str, legacy_root: Path) -> dict[str, Any]:
    rel_legacy = path.relative_to(legacy_root).as_posix()
    lower_path = rel_legacy.lower()
    lower_text = text.lower()
    categories: set[str] = set()
    blockers: set[str] = set()

    if MUTATING_EXCHANGE_RE.search(text):
        categories.add("exchange_mutation_path")
        blockers.add("exchange_mutation_marker")
    if REDIS_WRITE_RE.search(text):
        categories.add("redis_write_path")
    if DESTRUCTIVE_RE.search(text) or any(token in lower_path for token in ("cleanup", "close_all", "emergency", "restart", "stop_")):
        categories.add("destructive_or_maintenance_path")
        blockers.add("destructive_or_maintenance_marker")
    if "/trading/" in f"/{lower_path}" or "trader" in lower_path:
        categories.add("trading_runtime")
        blockers.add("legacy_trading_runtime")
    if "/risk/" in f"/{lower_path}" or lower_path.startswith("risk/"):
        categories.add("risk_runtime")
    if "/api/" in f"/{lower_path}" or lower_path.startswith("api/"):
        categories.add("api_server_or_route")
    if "/ingest/" in f"/{lower_path}" or lower_path.startswith("ingestors/") or lower_path.startswith("ingest/"):
        categories.add("legacy_ingestor")
    if NETWORK_READ_RE.search(text):
        categories.add("network_or_exchange_read_path")
    if PAID_OR_KEYED_RE.search(text) or any(token in lower_path for token in ("tokenmetrics", "alphavantage", "coinapi_wsds")):
        categories.add("keyed_or_paid_provider_path")
    if TRAINING_RE.search(text) or "/rl/" in f"/{lower_path}" or lower_path.startswith("rl/"):
        categories.add("trainer_or_rl_path")
    if MAIN_GUARD_RE.search(text):
        categories.add("has_main_guard")
    if "argparse" in text or "click." in text:
        categories.add("cli_like")
    if path.suffix.lower() in {".sh", ".ps1"}:
        categories.add("shell_or_powershell_script")

    v2_coverage = KNOWN_SAFE_V2_PROBES.get(rel_legacy)
    if v2_coverage:
        categories.add(v2_coverage)

    if "exchange_mutation_marker" in blockers:
        execution_class = "operator_gated_exchange_mutation_not_executed"
    elif "destructive_or_maintenance_marker" in blockers:
        execution_class = "operator_gated_destructive_or_maintenance_not_executed"
    elif "legacy_trading_runtime" in blockers:
        execution_class = "operator_gated_trading_runtime_not_executed"
    elif v2_coverage:
        execution_class = v2_coverage
    elif "legacy_ingestor" in categories and "keyed_or_paid_provider_path" in categories:
        execution_class = "operator_gated_keyed_or_paid_ingestor_not_executed"
    elif "trainer_or_rl_path" in categories:
        execution_class = "trainer_or_rl_static_validated_runtime_gated"
    elif "api_server_or_route" in categories:
        execution_class = "api_static_validated_runtime_not_started"
    elif "legacy_ingestor" in categories:
        execution_class = "legacy_ingestor_static_validated_runtime_not_started"
    elif path.suffix.lower() in {".sh", ".ps1"}:
        execution_class = "script_syntax_validated_runtime_not_started"
    else:
        execution_class = "static_validated_not_runtime_started"

    return {
        "relative_path": rel(path),
        "legacy_relative_path": rel_legacy,
        "suffix": path.suffix.lower(),
        "categories": sorted(categories),
        "runtime_blockers": sorted(blockers),
        "execution_class": execution_class,
        "safe_to_execute_blindly": execution_class.startswith("validated_by_")
        or execution_class.startswith("covered_by_"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    suffix_counts = Counter(row["suffix"] for row in rows)
    syntax_counts = Counter(row["syntax_status"] for row in rows)
    execution_counts = Counter(row["execution_class"] for row in rows)
    category_counts: Counter[str] = Counter()
    missing_dependency_counts: Counter[str] = Counter()
    for row in rows:
        category_counts.update(row["categories"])
        missing_dependency_counts.update(row.get("missing_third_party", []))
    return {
        "script_count": len(rows),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "syntax_counts": dict(sorted(syntax_counts.items())),
        "execution_class_counts": dict(sorted(execution_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "missing_dependency_counts": dict(missing_dependency_counts.most_common()),
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_markdown(summary: dict[str, Any], rows: list[dict[str, Any]], generated_utc: str) -> str:
    syntax_failures = [r for r in rows if r["syntax_status"] not in {"ok", "not_checked_pwsh_missing"}]
    gated = [r for r in rows if r["execution_class"].startswith("operator_gated")]
    validated = [r for r in rows if r["safe_to_execute_blindly"]]
    top_missing = list(summary["missing_dependency_counts"].items())[:20]

    lines = [
        "# Legacy Script Validation Report",
        "",
        f"Generated UTC: {generated_utc}",
        "Scope: `v2/legacy_owned_runtime` Python, shell, and PowerShell scripts.",
        "Safety: static pass only; no legacy Python modules were imported or executed.",
        "",
        "## Summary",
        f"- Scripts inventoried: {summary['script_count']}",
        f"- Syntax status: `{summary['syntax_counts']}`",
        f"- Runtime classes: `{summary['execution_class_counts']}`",
        f"- Safe V2-covered runtime probes: {len(validated)}",
        f"- Operator-gated scripts not executed: {len(gated)}",
        "",
        "## Syntax Failures",
    ]
    if not syntax_failures:
        lines.append("- None.")
    else:
        for row in syntax_failures[:60]:
            lines.append(
                f"- `{row['relative_path']}`: {row['syntax_status']} "
                f"{json.dumps(row.get('syntax_error'), sort_keys=True)}"
            )
        if len(syntax_failures) > 60:
            lines.append(f"- ... {len(syntax_failures) - 60} additional failures in JSON artifacts.")

    lines.extend(["", "## Safe V2-Covered Scripts"])
    if not validated:
        lines.append("- None.")
    else:
        for row in validated:
            lines.append(f"- `{row['legacy_relative_path']}` -> `{row['execution_class']}`")

    lines.extend(["", "## Top Missing Third-Party Imports"])
    if not top_missing:
        lines.append("- None detected by static import scan.")
    else:
        for name, count in top_missing:
            lines.append(f"- `{name}`: referenced by {count} file(s)")

    lines.extend(
        [
            "",
            "## Verdict",
            "All legacy scripts were inventoried and statically classified. Runtime execution is only considered safe through V2-covered adapters/native workers or explicit operator-gated starts; direct blanket execution of the legacy folder remains blocked because trading, cleanup, restart, and un-prefixed Redis-write scripts are present.",
            "",
        ]
    )
    return "\n".join(lines)


def build_go_no_go(summary: dict[str, Any], rows: list[dict[str, Any]], generated_utc: str) -> str:
    syntax_failures = [r for r in rows if r["syntax_status"] not in {"ok", "not_checked_pwsh_missing"}]
    operator_gated = [r for r in rows if r["execution_class"].startswith("operator_gated")]
    verdict = "NO_GO_FOR_BLANKET_LEGACY_EXECUTION"
    if not syntax_failures:
        syntax_line = "GO for static syntax coverage of Python and shell scripts."
    else:
        syntax_line = f"NO_GO for static syntax coverage until {len(syntax_failures)} syntax issue(s) are resolved."
    lines = [
        "# Legacy Script Validation GO/NO-GO",
        "",
        f"Generated UTC: {generated_utc}",
        f"Verdict: `{verdict}`",
        "",
        f"- {syntax_line}",
        "- GO for V2-covered adapter/native runtime probes listed in the report.",
        f"- NO-GO for blanket direct execution: {len(operator_gated)} operator-gated script(s) contain trading, destructive maintenance, paid/keyed provider, or legacy runtime markers.",
        "- LIVE_GATE remains `blocked_human_only`; `live_symbols=[]`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-root", type=Path, default=DEFAULT_LEGACY_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--public-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
    parser.add_argument("--skip-public", action="store_true")
    args = parser.parse_args(argv)

    generated_utc = utc_iso()
    legacy_root = args.legacy_root.resolve()
    if not legacy_root.exists():
        raise SystemExit(f"legacy root not found: {legacy_root}")

    rows: list[dict[str, Any]] = []
    by_dir: defaultdict[str, int] = defaultdict(int)
    scripts = list_scripts(legacy_root)
    local_top_levels = collect_local_top_levels(legacy_root)
    for path in scripts:
        text = read_text(path)
        classification = classify(path, text, legacy_root)
        if path.suffix.lower() == ".py":
            syntax = python_syntax(path, text)
            shell = {"status": "not_shell", "error": None}
            ps = {"status": "not_powershell", "error": None}
            imports, import_parse_error = imported_top_levels(text)
            deps = dependency_scan(imports, local_top_levels)
        elif path.suffix.lower() == ".sh":
            syntax = shell_syntax(path)
            shell = syntax
            ps = {"status": "not_powershell", "error": None}
            import_parse_error = None
            deps = {"available_third_party": [], "missing_third_party": [], "skipped_local_or_stdlib": []}
        else:
            syntax = powershell_syntax(path)
            shell = {"status": "not_shell", "error": None}
            ps = syntax
            import_parse_error = None
            deps = {"available_third_party": [], "missing_third_party": [], "skipped_local_or_stdlib": []}

        parent = path.relative_to(legacy_root).parent.as_posix()
        by_dir[parent] += 1
        row = {
            **classification,
            "size_bytes": path.stat().st_size,
            "line_count": text.count("\n") + (1 if text else 0),
            "sha256": sha256_file(path),
            "syntax_status": syntax["status"],
            "syntax_error": syntax.get("error"),
            "shell_syntax_status": shell["status"],
            "powershell_syntax_status": ps["status"],
            "import_parse_error": import_parse_error,
            "available_third_party": deps["available_third_party"],
            "missing_third_party": deps["missing_third_party"],
        }
        rows.append(row)

    summary = summarize(rows)
    payload = {
        "schema_version": "legacy_script_validation_static_v1",
        "generated_utc": generated_utc,
        "legacy_root": rel(legacy_root),
        "script_count": len(rows),
        "summary": summary,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "notes": [
            "Static validator does not import or execute legacy Python modules.",
            "Direct blanket execution remains unsafe because operator-gated scripts are present.",
        ],
    }
    inventory = {
        "schema_version": "legacy_script_inventory_v1",
        "generated_utc": generated_utc,
        "legacy_root": rel(legacy_root),
        "script_count": len(rows),
        "by_suffix": summary["suffix_counts"],
        "by_directory": dict(sorted(by_dir.items())),
        "scripts": rows,
    }
    classification = {
        "schema_version": "legacy_script_classification_v1",
        "generated_utc": generated_utc,
        "execution_class_counts": summary["execution_class_counts"],
        "category_counts": summary["category_counts"],
        "scripts": [
            {
                "relative_path": r["relative_path"],
                "legacy_relative_path": r["legacy_relative_path"],
                "categories": r["categories"],
                "runtime_blockers": r["runtime_blockers"],
                "execution_class": r["execution_class"],
                "safe_to_execute_blindly": r["safe_to_execute_blindly"],
            }
            for r in rows
        ],
    }
    syntax_status = {
        "schema_version": "legacy_script_syntax_status_v1",
        "generated_utc": generated_utc,
        "syntax_counts": summary["syntax_counts"],
        "scripts": [
            {
                "relative_path": r["relative_path"],
                "legacy_relative_path": r["legacy_relative_path"],
                "suffix": r["suffix"],
                "syntax_status": r["syntax_status"],
                "syntax_error": r["syntax_error"],
            }
            for r in rows
        ],
    }
    dependency_status = {
        "schema_version": "legacy_script_dependency_status_v1",
        "generated_utc": generated_utc,
        "missing_dependency_counts": summary["missing_dependency_counts"],
        "scripts_with_missing_dependencies": [
            {
                "relative_path": r["relative_path"],
                "legacy_relative_path": r["legacy_relative_path"],
                "missing_third_party": r["missing_third_party"],
            }
            for r in rows
            if r["missing_third_party"]
        ],
    }

    for target_dir in [args.out_dir] + ([] if args.skip_public else [args.public_dir]):
        write_json(target_dir / "legacy_script_inventory.json", inventory)
        write_json(target_dir / "legacy_script_classification.json", classification)
        write_json(target_dir / "legacy_script_syntax_status.json", syntax_status)
        write_json(target_dir / "legacy_script_dependency_status.json", dependency_status)
        write_json(target_dir / "operator_dashboard_payload.json", payload)
        (target_dir / "LEGACY_SCRIPT_VALIDATION_REPORT.md").write_text(
            build_markdown(summary, rows, generated_utc),
            encoding="utf-8",
        )
        (target_dir / "GO_NO_GO.md").write_text(
            build_go_no_go(summary, rows, generated_utc),
            encoding="utf-8",
        )

    print(
        json.dumps(
            {
                "generated_utc": generated_utc,
                "script_count": len(rows),
                "syntax_counts": summary["syntax_counts"],
                "execution_class_counts": summary["execution_class_counts"],
                "output_dir": rel(args.out_dir.resolve()),
                "public_dir": None if args.skip_public else rel(args.public_dir.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
