#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
OUT = ROOT / "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest"
PUBLIC = ROOT / "v2/frontend/public/system_atlas_runtime_coverage/latest"
MAX_INLINE_HASH_BYTES = 100 * 1024 * 1024

SCAN_ROOTS = [
    ROOT / "legacy_reference",
    ROOT / "v2",
    ROOT / "tools",
    ROOT / "requirements",
    ROOT / ".claude",
    ROOT / "claude_worklog/requirements_inbox",
    ROOT / "claude_worklog/v2_requirements",
    ROOT / "claude_worklog/v2_architecture",
    ROOT / "claude_worklog/legacy_preservation",
    ROOT / "claude_worklog/phase2_core_rebuild",
    ROOT / "claude_worklog/final_readiness",
    ROOT / "claude_worklog/agent_supervisor/tasks",
    ROOT / "claude_worklog/tools",
]

SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".vite",
}

CODE_EXTENSIONS = {
    ".py",
    ".sh",
    ".bash",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".json",
    ".yml",
    ".yaml",
    ".service",
    ".timer",
    ".env",
    ".toml",
    ".ini",
    ".cfg",
}
SCRIPT_EXTENSIONS = {".py", ".sh", ".bash", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".service", ".timer"}
MAX_TEXT_SAMPLE_BYTES = 64_000

EXCHANGE_TOKENS = [
    "create_order",
    "cancel_order",
    "change_leverage",
    "change_margin",
    "change_margin_type",
    "change_position_mode",
    "close_position",
    "reduce_only",
    "stop_market",
    "take_profit",
    "trailing_stop",
    "hedge",
    "dca",
    "rebalance",
    "ADJUST_LEVERAGE",
    "ADJUST_LEVERAGE_AND_POSITION",
]

REDIS_WRITE_TOKENS = ["xadd", "set(", "hset", "delete(", "xdel", "xtrim", "flushall", "flushdb", "redis-cli set", "redis-cli xadd"]
REDIS_READ_TOKENS = ["xread", "xrange", "xrevrange", "get(", "hgetall", "scan_iter", "redis-cli get", "redis-cli scan"]
LINEAGE_FIELDS = [
    "feature_snapshot_id",
    "prediction_id",
    "signal_id",
    "model_id",
    "model_version",
    "checkpoint_id",
    "raw_model_output",
    "confidence_raw",
    "confidence_calibrated",
    "confidence_explanation",
    "top_positive",
    "top_negative",
    "freshness",
    "stale",
    "missing",
    "unused",
    "orchestrator_decision_id",
    "risk_decision_id",
    "execution_intent_id",
    "paper_trade_id",
    "shadow_decision_id",
]


@dataclass
class Evidence:
    claim: str
    raw_evidence_pointer: str
    verification_command: str
    confidence: str
    missing_evidence: str = ""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)


def read_text_sample(path: Path, limit: int = MAX_TEXT_SAMPLE_BYTES) -> str:
    try:
        return path.read_text(errors="replace")[:limit]
    except Exception:
        return ""


def sha256_file(path: Path, size: int | None = None) -> str:
    if size is None:
        size = path.stat().st_size
    if rel(path).startswith("legacy_reference/"):
        return f"DEFERRED_LEGACY_REFERENCE_BACKGROUND_SHA256_REQUIRED_size={size}"
    if size > MAX_INLINE_HASH_BYTES:
        return f"DEFERRED_LARGE_FILE_SHA256_REQUIRED_size={size}"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_files() -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
            for name in filenames:
                path = Path(dirpath) / name
                if path in seen or path.is_symlink():
                    continue
                seen.add(path)
                files.append(path)
    return sorted(files)


def first_line(path: Path) -> str:
    try:
        with path.open("rb") as f:
            return f.readline(300).decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def file_classification(path: Path, executable: bool, shebang: str) -> str:
    p = rel(path)
    suffix = path.suffix.lower()
    if "node_modules/" in p:
        return "third_party_dependency"
    if "/tests/" in p or "/test_" in p or p.endswith(".spec.ts"):
        return "active_test"
    if p.startswith("legacy_reference/"):
        return "legacy_reference_readonly"
    if p.endswith((".md", ".txt")):
        return "docs_or_evidence"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env"}:
        return "config_or_payload"
    if executable or shebang:
        return "script_candidate"
    if suffix in {".py", ".js", ".ts", ".tsx", ".mjs", ".cjs", ".sh"}:
        return "code_module"
    return "asset_or_other"


def risk_for(path: Path, text: str, executable: bool) -> str:
    lower = text.lower()
    p = rel(path)
    if "/node_modules/" in p:
        return "L0_THIRD_PARTY"
    if any(token.lower() in lower for token in EXCHANGE_TOKENS):
        return "TIER_A_EXCHANGE_REVIEW_REQUIRED"
    if any(token in lower for token in REDIS_WRITE_TOKENS):
        return "TIER_A_REDIS_WRITER_REVIEW_REQUIRED"
    if executable:
        return "L2_EXECUTABLE_REVIEW_REQUIRED"
    if p.startswith("legacy_reference/"):
        return "L2_LEGACY_REFERENCE_READONLY"
    return "L1_NON_LIVE"


def build_file_manifest(files: list[Path]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for path in files:
        st = path.stat()
        mode = st.st_mode
        executable = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        line_one = first_line(path)
        shebang = line_one if line_one.startswith("#!") else ""
        text = read_text_sample(path) if path.suffix.lower() in SCRIPT_EXTENSIONS or shebang else ""
        classification = file_classification(path, executable, shebang)
        risk = risk_for(path, text, executable)
        digest = sha256_file(path, st.st_size)
        manifest.append(
            {
                "path": rel(path),
                "size": st.st_size,
                "sha256": digest,
                "extension": path.suffix.lower(),
                "language": language_for(path),
                "executable": executable,
                "shebang": shebang,
                "last_modified_time": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                "classification": classification,
                "risk_level": risk,
                "reviewed": risk not in {"TIER_A_EXCHANGE_REVIEW_REQUIRED", "TIER_A_REDIS_WRITER_REVIEW_REQUIRED", "L2_EXECUTABLE_REVIEW_REQUIRED"},
                "evidence_pointer": f"{rel(path)} sha256={digest}",
            }
        )
    return manifest


def language_for(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".py": "python",
        ".sh": "shell",
        ".bash": "shell",
        ".js": "javascript",
        ".jsx": "javascript",
        ".mjs": "javascript",
        ".cjs": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".json": "json",
        ".md": "markdown",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".service": "systemd_unit",
        ".timer": "systemd_unit",
    }.get(suffix, "unknown")


def extract_imports(path: Path, text: str) -> list[str]:
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except Exception:
            return []
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        return sorted(set(imports))
    if path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        return sorted(set(re.findall(r"(?:from|import)\s+['\"]([^'\"]+)['\"]|require\(['\"]([^'\"]+)['\"]\)", text)))
    return []


def script_status(path: Path, text: str, manifest_entry: dict[str, Any]) -> str:
    p = manifest_entry["path"]
    if "node_modules/" in p:
        return "config_only"
    if "/tests/" in p or "/test_" in p or p.endswith(".spec.ts"):
        return "active_test"
    if p.startswith("claude_worklog/") and p.endswith(".md"):
        return "docs_only"
    if p.startswith("legacy_reference/"):
        return "active_runtime" if re.search(r"live_|trader|trainer|orchestrator|monitor|redis", p, re.I) else "unsafe_unknown"
    if p.startswith("v2/backend/app/") or p.startswith("v2/frontend/src/"):
        return "active_imported"
    if p.startswith("claude_worklog/tools/") or p.startswith("tools/"):
        return "active_manual"
    if manifest_entry["executable"] or manifest_entry["shebang"]:
        return "unsafe_unknown"
    if path.suffix.lower() in CODE_EXTENSIONS:
        return "active_imported"
    return "config_only"


def build_script_registry(files: list[Path], manifest_by_path: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scripts: list[dict[str, Any]] = []
    for path in files:
        entry = manifest_by_path[rel(path)]
        if "node_modules/" in entry["path"]:
            continue
        if path.suffix.lower() not in SCRIPT_EXTENSIONS and not entry["executable"] and not entry["shebang"]:
            continue
        text = read_text_sample(path)
        imports = extract_imports(path, text)
        redis_reads = [t for t in REDIS_READ_TOKENS if t in text.lower()]
        redis_writes = [t for t in REDIS_WRITE_TOKENS if t in text.lower()]
        exchange_actions = [t for t in EXCHANGE_TOKENS if re.search(re.escape(t), text, re.I)]
        status = script_status(path, text, entry)
        if entry["risk_level"].startswith("TIER_A") and status == "active_imported":
            status = "unsafe_unknown"
        scripts.append(
            {
                "path": entry["path"],
                "classification": status,
                "risk_level": entry["risk_level"],
                "imports": imports,
                "imported_by": [],
                "subprocess_callers": bool(re.search(r"subprocess|Popen|os\.system", text)),
                "shell_callers": bool(re.search(r"\bbash\b|\bsh\b|&&|\|\|", text)),
                "cron_systemd_tmux_docker_references": bool(re.search(r"cron|systemd|tmux|docker", text, re.I)),
                "cli_entry_points": bool(re.search(r"if __name__ == ['\"]__main__['\"]|argparse|click\\.|typer\\.", text)),
                "redis_reads": redis_reads,
                "redis_writes": redis_writes,
                "file_reads_writes": bool(re.search(r"open\(|read_text|write_text|Path\(", text)),
                "env_vars": env_names(text),
                "exchange_api_calls": exchange_actions,
                "logs_emitted": bool(re.search(r"logging|logger\.|console\.log|print\(", text)),
                "tests": find_tests_for(entry["path"]),
                "runtime_evidence": "see RUNTIME_PROCESS_MAP and SCRIPT_USAGE_EVIDENCE",
                "non_usage_evidence": "" if status != "unsafe_unknown" else "no verified non-usage evidence",
                "v2_action": v2_action_for(entry["path"], status),
            }
        )
    graph = {"nodes": [{"id": row["path"], "classification": row["classification"]} for row in scripts], "edges": []}
    return scripts, graph


def env_names(text: str) -> list[str]:
    names: set[str] = set()
    for pattern in [
        r"os\.environ\[['\"]([A-Z0-9_]+)['\"]\]",
        r"os\.getenv\(['\"]([A-Z0-9_]+)['\"]",
        r"getenv\(['\"]([A-Z0-9_]+)['\"]",
        r"process\.env\.([A-Z0-9_]+)",
    ]:
        names.update(re.findall(pattern, text))
    return sorted(names)


def find_tests_for(path: str) -> list[str]:
    stem = Path(path).stem
    if not stem:
        return []
    candidates = []
    for test in (ROOT / "v2/backend/tests").glob(f"**/*{stem}*"):
        if test.is_file():
            candidates.append(rel(test))
    return candidates[:20]


def v2_action_for(path: str, status: str) -> str:
    if path.startswith("legacy_reference/"):
        return "wrap_or_reference_readonly" if status != "unsafe_unknown" else "review_before_use"
    if path.startswith("v2/"):
        return "keep_and_monitor"
    if status == "unsafe_unknown":
        return "classify_before_live_readiness"
    return "monitor"


def process_map() -> list[dict[str, Any]]:
    proc = run(["ps", "-eo", "pid,ppid,etimes,cmd"], timeout=10)
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        pid, ppid, etimes, cmd = parts
        if "grep -E" in cmd:
            continue
        mapped = map_process(cmd)
        rows.append(
            {
                "pid": int(pid),
                "ppid": int(ppid),
                "age_seconds": int(etimes),
                "cmd": cmd,
                "mapped_file_or_module": mapped,
                "status": "mapped" if mapped else "unmapped",
                "evidence_pointer": "ps -eo pid,ppid,etimes,cmd",
            }
        )
    return rows


def map_process(cmd: str) -> str:
    for pattern in [
        "claude_worklog/tools/claude_master_rebuild_planner.py",
        "claude_worklog/tools/codex_non_live_watchdog.py",
        "claude_worklog/tools/parallel_capacity_scheduler.py",
        "claude_worklog/tools/agent_supervisor.py",
        "v2/node_modules/.bin/vite",
    ]:
        if pattern in cmd:
            return pattern
    m = re.search(r"python3?\s+([^ ]+\.py)", cmd)
    if m and (ROOT / m.group(1)).exists():
        return m.group(1)
    return ""


def redis_map(scripts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    gaps: list[str] = []
    keys: list[dict[str, Any]] = []
    redis_available = False
    try:
        ping = run(["redis-cli", "PING"], timeout=3)
        redis_available = ping.returncode == 0 and "PONG" in ping.stdout
    except Exception:
        redis_available = False
    if redis_available:
        scan = run(["redis-cli", "--scan"], timeout=15)
        for key in scan.stdout.splitlines()[:5000]:
            key = key.strip()
            if not key:
                continue
            type_proc = run(["redis-cli", "TYPE", key], timeout=3)
            typ = type_proc.stdout.strip()
            length = None
            if typ == "stream":
                length = run(["redis-cli", "XLEN", key], timeout=3).stdout.strip()
            elif typ == "list":
                length = run(["redis-cli", "LLEN", key], timeout=3).stdout.strip()
            elif typ == "hash":
                length = "hash"
            keys.append(
                {
                    "key": key,
                    "type": typ,
                    "length_or_size": length,
                    "last_event_timestamp": "unknown",
                    "producer": "unknown",
                    "consumer": "unknown",
                    "reader_files": [s["path"] for s in scripts if key in json.dumps(s)][:20],
                    "writer_files": [s["path"] for s in scripts if s["redis_writes"] and key in json.dumps(s)][:20],
                    "account_symbol_scope": "unknown",
                    "system": "legacy_or_unknown",
                    "unmapped_status": "unmapped" if not any(key in json.dumps(s) for s in scripts) else "mapped_by_text",
                }
            )
    else:
        gaps.append("Redis was not available to read with PING/SCAN, so runtime key inventory is missing.")
    writer_scripts = [s["path"] for s in scripts if s.get("redis_writes")]
    for path in writer_scripts:
        gaps.append(f"Redis writer token requires raw review: {path}")
    return keys, gaps


def exchange_action_map(scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for script in scripts:
        for action in script.get("exchange_api_calls", []):
            rows.append(
                {
                    "file": script["path"],
                    "function_or_class": "raw_token_match",
                    "action_type": action,
                    "risk_class": "TIER_A_EXCHANGE_ACTION",
                    "callable_in_v2": script["path"].startswith("v2/") and "readonly_market_exchange_data_plane" not in script["path"],
                    "blocked_or_fail_closed": "forbidden_by_policy_or_requires_raw_review",
                    "tests": script.get("tests", []),
                    "raw_evidence_pointer": f"{script['path']} token={action}",
                }
            )
    return rows


def lineage_map(files: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    coverage: dict[str, list[str]] = {field: [] for field in LINEAGE_FIELDS}
    for path in files:
        if path.suffix.lower() not in SCRIPT_EXTENSIONS:
            continue
        text = read_text_sample(path)
        for field in LINEAGE_FIELDS:
            if field in text:
                coverage[field].append(rel(path))
    gaps = []
    for field, refs in coverage.items():
        rows.append({"field": field, "status": "present" if refs else "missing", "evidence_links": refs[:50]})
        if not refs:
            gaps.append(f"Missing lineage evidence for {field}")
    return rows, gaps


def startup_config_maps(files: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    startup: list[dict[str, Any]] = []
    config: list[dict[str, Any]] = []
    gaps: list[str] = []
    for path in files:
        p = rel(path)
        if path.suffix.lower() not in CODE_EXTENSIONS and path.name.lower() not in {".env", "config.py", "settings.py"}:
            continue
        text = read_text_sample(path)
        if re.search(r"systemd|tmux|cron|docker|uvicorn|vite|python3|npm run", text, re.I) or path.suffix in {".service", ".timer", ".sh"}:
            startup.append({"path": p, "entrypoint_refs": sorted(set(re.findall(r"(?:python3?|npm|uvicorn|vite|tmux|docker|systemctl)[^\\n;&|]*", text)))[:20], "evidence_pointer": p})
        envs = env_names(text)
        if envs or path.name.lower() in {".env", "config.py", "settings.py"} or path.suffix.lower() in {".env", ".toml", ".ini", ".cfg", ".yaml", ".yml"}:
            config.append({"path": p, "env_var_names_only": envs, "gui_equivalent": "unknown", "safety_critical_hidden_settings": [e for e in envs if re.search(r"KEY|SECRET|TOKEN|LIVE|LEVERAGE|MARGIN", e)]})
    if not startup:
        gaps.append("No startup paths discovered.")
    return startup, config, gaps


def monitor_map(scripts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    monitors = [s for s in scripts if re.search(r"monitor|watchdog|sentinel|health|status", s["path"], re.I)]
    rows = []
    for s in monitors:
        rows.append(
            {
                "script_path": s["path"],
                "owner_module": owner_for(s["path"]),
                "status": "mapped" if s["classification"] != "unsafe_unknown" else "unknown",
                "last_run": "unknown",
                "last_success": "unknown",
                "last_failure": "unknown",
                "metrics_emitted": [],
                "redis_keys_watched": s.get("redis_reads", []),
                "logs_watched": [],
                "processes_watched": [],
                "alerts": ["classification_required"] if s["classification"] == "unsafe_unknown" else [],
                "classification": s["classification"],
            }
        )
    return rows


def owner_for(path: str) -> str:
    if "trainer" in path:
        return "trainer"
    if "risk" in path:
        return "risk_gateway"
    if "codex" in path:
        return "codex_watchdog"
    if "claude" in path or "planner" in path:
        return "planner"
    if "frontend" in path:
        return "frontend"
    return "unknown"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_md(path: Path, title: str, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + title + "\n\n" + "\n".join(lines).rstrip() + "\n")


def table_lines(rows: list[dict[str, Any]], fields: list[str], limit: int = 200) -> list[str]:
    out = ["| " + " | ".join(fields) + " |", "| " + " | ".join("---" for _ in fields) + " |"]
    for row in rows[:limit]:
        out.append("| " + " | ".join(str(row.get(f, "")).replace("\n", " ")[:220] for f in fields) + " |")
    if len(rows) > limit:
        out.append(f"\nShowing {limit} of {len(rows)} rows. Full data is in JSON.")
    return out


def main() -> int:
    generated_at = now()
    OUT.mkdir(parents=True, exist_ok=True)
    files = iter_files()
    manifest = build_file_manifest(files)
    manifest_by_path = {row["path"]: row for row in manifest}
    scripts, graph = build_script_registry(files, manifest_by_path)
    processes = process_map()
    redis_keys, redis_gaps = redis_map(scripts)
    exchange_actions = exchange_action_map(scripts)
    lineage, lineage_gaps = lineage_map(files)
    startup, config, config_gaps = startup_config_maps(files)
    monitors = monitor_map(scripts)

    unsafe_unknowns = [s for s in scripts if s["classification"] == "unsafe_unknown"]
    deferred_hashes = [m for m in manifest if str(m["sha256"]).startswith("DEFERRED_LARGE_FILE")]
    unmapped_processes = [p for p in processes if p["status"] == "unmapped" and "ps -eo" not in p["cmd"]]
    unmapped_exchange = [a for a in exchange_actions if a["blocked_or_fail_closed"] != "fail_closed_tested"]
    unmapped_redis_writers = [s for s in scripts if s.get("redis_writes")]
    runtime_status = {
        "generated_at": generated_at,
        "monitor_prepared": True,
        "monitor_started": False,
        "monitor_completed_12h": False,
        "status": "prepared_not_run",
        "allowed_write_dir": rel(OUT / "runtime_monitor"),
        "live_gate_status": "blocked_human_only",
    }

    gaps = []
    gaps.extend([f"deferred sha256 for large file: {m['path']} {m['sha256']}" for m in deferred_hashes[:500]])
    gaps.extend([f"unsafe_unknown script: {s['path']}" for s in unsafe_unknowns[:500]])
    gaps.extend([f"unmapped active process: {p['cmd']}" for p in unmapped_processes[:100]])
    gaps.extend([f"unmapped exchange action path: {a['file']} token={a['action_type']}" for a in unmapped_exchange[:500]])
    gaps.extend([f"unmapped Redis writer path: {s['path']} tokens={s['redis_writes']}" for s in unmapped_redis_writers[:500]])
    gaps.extend(redis_gaps)
    gaps.extend(lineage_gaps)
    gaps.extend(config_gaps)
    gaps.append("12-hour read-only runtime monitor has been prepared but has not completed.")

    codex_pass = not gaps
    final_ready = codex_pass and runtime_status["monitor_completed_12h"]

    evidence = [
        asdict(Evidence("File manifest generated", "FILE_MANIFEST.json", "python3 claude_worklog/tools/build_system_atlas_runtime_coverage.py", "high")),
        asdict(Evidence("Runtime process map generated from ps", "RUNTIME_PROCESS_MAP.json", "ps -eo pid,ppid,etimes,cmd", "high")),
        asdict(Evidence("Redis map uses read-only redis-cli commands only when available", "REDIS_KEY_STREAM_MAP.json", "redis-cli PING && redis-cli --scan", "medium", "" if redis_keys else "Redis unavailable or empty")),
        asdict(Evidence("Exchange mutation tokens are mapped for raw review", "EXCHANGE_ACTION_MAP.json", "regex scan over code-like files", "medium")),
        asdict(Evidence("12-hour monitor not completed", "runtime_monitor/runtime_monitor_status.json", "read runtime monitor status", "high", "12-hour collection must run before READY")),
    ]

    # Required JSON outputs.
    write_json(OUT / "FILE_MANIFEST.json", {"generated_at": generated_at, "count": len(manifest), "files": manifest})
    write_json(OUT / "SCRIPT_REGISTRY.json", {"generated_at": generated_at, "count": len(scripts), "scripts": scripts})
    write_json(OUT / "SCRIPT_DEPENDENCY_GRAPH.json", {"generated_at": generated_at, **graph})
    write_json(OUT / "RUNTIME_PROCESS_MAP.json", {"generated_at": generated_at, "processes": processes})
    write_json(OUT / "REDIS_KEY_STREAM_MAP.json", {"generated_at": generated_at, "redis_available": bool(redis_keys), "keys": redis_keys, "gaps": redis_gaps})
    write_json(OUT / "EXCHANGE_ACTION_MAP.json", {"generated_at": generated_at, "actions": exchange_actions})
    write_json(OUT / "TRAINER_SIGNAL_LINEAGE_MAP.json", {"generated_at": generated_at, "fields": lineage})
    write_json(OUT / "STARTUP_PATH_MAP.json", {"generated_at": generated_at, "startup_paths": startup})
    write_json(OUT / "CONFIG_ENV_MAP.json", {"generated_at": generated_at, "config_paths": config})
    write_json(OUT / "MONITOR_SCRIPT_MAP.json", {"generated_at": generated_at, "monitors": monitors})
    write_json(OUT / "EVIDENCE_MANIFEST.json", {"generated_at": generated_at, "evidence": evidence})

    runtime_dir = OUT / "runtime_monitor"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    write_json(runtime_dir / "runtime_monitor_status.json", runtime_status)
    for name in ["runtime_snapshots.jsonl", "trainer_metrics.jsonl", "script_status.jsonl", "signal_trace.jsonl", "prediction_trace.jsonl"]:
        (runtime_dir / name).write_text("")
    write_md(
        runtime_dir / "12H_RUNTIME_MONITOR_PLAN.md",
        "12H Runtime Monitor Plan",
        [
            "Prepared read-only monitor output directory.",
            "",
            "The monitor may sample Redis with SCAN/TYPE/XLEN/XREVRANGE/GET/HGETALL/TTL only.",
            "It must not use DEL/XDEL/XTRIM/SET/HSET/XADD/FLUSHALL/FLUSHDB.",
            "Status: prepared, not completed.",
            "",
            "12H_RUNTIME_MONITOR_PLAN_READY",
        ],
    )
    write_md(runtime_dir / "12H_RUNTIME_MONITOR_SUMMARY.md", "12H Runtime Monitor Summary", ["The 12-hour runtime monitor has not completed.", "", "12H_RUNTIME_MONITOR_BLOCKED_NOT_RUN"])

    # Required markdown outputs.
    write_md(OUT / "FILE_MANIFEST.md", "File Manifest", [f"Generated: {generated_at}", f"Files inventoried: {len(manifest)}", "", *table_lines(manifest, ["path", "size", "sha256", "classification", "risk_level"], 80)])
    write_md(OUT / "SCRIPT_REGISTRY.md", "Script Registry", [f"Scripts/code-like files: {len(scripts)}", "", *table_lines(scripts, ["path", "classification", "risk_level", "v2_action"], 120)])
    write_md(OUT / "SCRIPT_DEPENDENCY_GRAPH.md", "Script Dependency Graph", [f"Nodes: {len(graph['nodes'])}", f"Edges: {len(graph['edges'])}", "Full graph is in JSON."])
    write_md(OUT / "SCRIPT_USAGE_EVIDENCE.md", "Script Usage Evidence", ["Usage evidence is derived from imports, process map, command references, and path classification.", "", *table_lines(scripts, ["path", "classification", "runtime_evidence", "non_usage_evidence"], 120)])
    write_md(OUT / "SCRIPT_UNKNOWN_GAPS.md", "Script Unknown Gaps", [*(f"- {s['path']}" for s in unsafe_unknowns[:500]), "" if unsafe_unknowns else "No unsafe_unknown scripts detected by this pass."])
    write_md(OUT / "RUNTIME_PROCESS_MAP.md", "Runtime Process Map", table_lines(processes, ["pid", "age_seconds", "mapped_file_or_module", "status", "cmd"], 120))
    write_md(OUT / "REDIS_KEY_STREAM_MAP.md", "Redis Key Stream Map", ["Read-only Redis inspection only.", "", *table_lines(redis_keys, ["key", "type", "length_or_size", "system", "unmapped_status"], 120)])
    write_md(OUT / "REDIS_UNMAPPED_GAPS.md", "Redis Unmapped Gaps", [*(f"- {g}" for g in redis_gaps), "" if redis_gaps else "No Redis gaps detected by this pass."])
    write_md(OUT / "EXCHANGE_ACTION_MAP.md", "Exchange Action Map", table_lines(exchange_actions, ["file", "action_type", "risk_class", "callable_in_v2", "blocked_or_fail_closed"], 160))
    write_md(OUT / "TIER_A_EXCHANGE_ACTION_RAW_REVIEW.md", "Tier A Exchange Action Raw Review", [*(f"- {a['file']} :: {a['action_type']} :: {a['raw_evidence_pointer']}" for a in exchange_actions[:500]), "" if exchange_actions else "No exchange mutation tokens detected."])
    write_md(OUT / "TRAINER_SIGNAL_LINEAGE_MAP.md", "Trainer Signal Lineage Map", table_lines(lineage, ["field", "status", "evidence_links"], 80))
    write_md(OUT / "TRAINER_SIGNAL_LINEAGE_GAPS.md", "Trainer Signal Lineage Gaps", [*(f"- {g}" for g in lineage_gaps), "" if lineage_gaps else "No trainer lineage gaps detected by text scan."])
    write_md(OUT / "SIGNAL_EXPLAINABILITY_EVIDENCE_GAPS.md", "Signal Explainability Evidence Gaps", [*(f"- {g}" for g in lineage_gaps), "" if lineage_gaps else "No signal explainability gaps detected by text scan."])
    write_md(OUT / "STARTUP_PATH_MAP.md", "Startup Path Map", table_lines(startup, ["path", "entrypoint_refs", "evidence_pointer"], 120))
    write_md(OUT / "CONFIG_ENV_MAP.md", "Config Env Map", table_lines(config, ["path", "env_var_names_only", "gui_equivalent", "safety_critical_hidden_settings"], 120))
    write_md(OUT / "CONFIG_GUI_COVERAGE_GAPS.md", "Config GUI Coverage Gaps", ["Every config path with `gui_equivalent=unknown` requires GUI coverage review.", "", *[f"- {c['path']}" for c in config if c["gui_equivalent"] == "unknown"][:500]])
    write_md(OUT / "MONITOR_SCRIPT_MAP.md", "Monitor Script Map", table_lines(monitors, ["script_path", "owner_module", "status", "classification"], 120))
    write_json(OUT / "MONITOR_CENTER_DASHBOARD_PAYLOAD.json", {"generated_at": generated_at, "monitors": monitors})
    write_md(OUT / "EVIDENCE_INTEGRITY_POLICY.md", "Evidence Integrity Policy", ["Summaries are navigation only. Final claims require raw evidence pointer, verification command, confidence level, and missing evidence field.", "", "EVIDENCE_INTEGRITY_POLICY_READY"])
    write_md(OUT / "RAW_EVIDENCE_POINTERS.md", "Raw Evidence Pointers", [f"- {e['claim']}: {e['raw_evidence_pointer']} via `{e['verification_command']}`" for e in evidence])
    write_md(OUT / "UNKNOWN_GAPS.md", "Unknown Gaps", [*(f"- {g}" for g in gaps[:1000]), "" if gaps else "No blocking gaps detected."])
    write_md(
        OUT / "CODEX_ADVERSARIAL_COVERAGE_REVIEW.md",
        "Codex Adversarial Coverage Review",
        [
            "This local Codex pass challenges coverage completeness.",
            "",
            f"Unsafe unknown scripts: {len(unsafe_unknowns)}",
            f"Unmapped exchange action paths: {len(unmapped_exchange)}",
            f"Unmapped Redis writer paths: {len(unmapped_redis_writers)}",
            f"Unmapped active runtime processes: {len(unmapped_processes)}",
            f"Trainer lineage gaps: {len(lineage_gaps)}",
            f"12-hour monitor completed: {runtime_status['monitor_completed_12h']}",
            "",
            "Result: FAIL" if not codex_pass else "Result: PASS",
            "",
            "CODEX_ADVERSARIAL_COVERAGE_REVIEW_READY",
        ],
    )
    (OUT / "CODEX_COVERAGE_GO_NO_GO.md").write_text(("PHASE3A_SYSTEM_ATLAS_COVERAGE_CODEX_PASS" if codex_pass else "PHASE3A_SYSTEM_ATLAS_COVERAGE_CODEX_FAIL") + "\n")

    dashboard_payload = {
        "generated_at": generated_at,
        "live_gate_status": "blocked_human_only",
        "go_no_go": "PHASE3A_SYSTEM_ATLAS_12H_RUNTIME_COVERAGE_AND_EVIDENCE_INTEGRITY_READY" if final_ready else "PHASE3A_SYSTEM_ATLAS_12H_RUNTIME_COVERAGE_AND_EVIDENCE_INTEGRITY_BLOCKED",
        "counts": {
            "files": len(manifest),
            "deferred_large_file_hashes": len(deferred_hashes),
            "scripts": len(scripts),
            "unsafe_unknown": len(unsafe_unknowns),
            "exchange_action_paths": len(exchange_actions),
            "unmapped_exchange_action_paths": len(unmapped_exchange),
            "redis_keys": len(redis_keys),
            "redis_writer_paths": len(unmapped_redis_writers),
            "runtime_processes": len(processes),
            "unmapped_runtime_processes": len(unmapped_processes),
            "trainer_lineage_gaps": len(lineage_gaps),
            "monitor_scripts": len(monitors),
            "blocking_gaps": len(gaps),
        },
        "runtime_monitor": runtime_status,
        "top_gaps": gaps[:50],
        "artifact_paths": {
            "file_manifest": "/system_atlas_runtime_coverage/latest/FILE_MANIFEST.json",
            "script_registry": "/system_atlas_runtime_coverage/latest/SCRIPT_REGISTRY.json",
            "runtime_process_map": "/system_atlas_runtime_coverage/latest/RUNTIME_PROCESS_MAP.json",
            "unknown_gaps": "/system_atlas_runtime_coverage/latest/UNKNOWN_GAPS.md",
        },
    }
    write_json(OUT / "operator_dashboard_payload.json", dashboard_payload)
    write_json(PUBLIC / "operator_dashboard_payload.json", dashboard_payload)

    write_md(
        OUT / "PHASE3A_SYSTEM_ATLAS_RUNTIME_COVERAGE_REPORT.md",
        "Phase 3A System Atlas Runtime Coverage Report",
        [
            f"Generated: {generated_at}",
            "",
            f"Files inventoried: {len(manifest)}",
            f"Scripts/code-like files: {len(scripts)}",
            f"Unsafe unknown scripts: {len(unsafe_unknowns)}",
            f"Exchange action token paths: {len(exchange_actions)}",
            f"Redis writer token paths: {len(unmapped_redis_writers)}",
            f"Runtime processes: {len(processes)}",
            f"Unmapped runtime processes: {len(unmapped_processes)}",
            f"Trainer lineage gaps: {len(lineage_gaps)}",
            f"12-hour runtime monitor completed: {runtime_status['monitor_completed_12h']}",
            "",
            "Final status is BLOCKED until every unsafe unknown, unmapped exchange path, Redis writer path, active runtime process, and the 12-hour monitor completion gap is resolved.",
            "",
            "PHASE3A_SYSTEM_ATLAS_RUNTIME_COVERAGE_REPORT_READY",
        ],
    )
    (OUT / "GO_NO_GO.md").write_text(("PHASE3A_SYSTEM_ATLAS_12H_RUNTIME_COVERAGE_AND_EVIDENCE_INTEGRITY_READY" if final_ready else "PHASE3A_SYSTEM_ATLAS_12H_RUNTIME_COVERAGE_AND_EVIDENCE_INTEGRITY_BLOCKED") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
