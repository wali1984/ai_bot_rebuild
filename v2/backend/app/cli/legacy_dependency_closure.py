"""Legacy dependency closure scanner.

Given a legacy script path, recursively detects local imports and produces the
closure needed to port/copy the worker. Outputs JSON.

Usage:
    python3 -m v2.backend.app.cli.legacy_dependency_closure --root v2/legacy_preserved/startup_baseline --entry ingest/live_binance.py
    python3 -m v2.backend.app.cli.legacy_dependency_closure --root v2/legacy_preserved/startup_baseline --all
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Static scanner only. It never opens Binance connections; any runtime Binance
# REST path must use BINANCE_REST_FALLBACK_ALLOWED under the WebSocket-primary
# transport policy.
BINANCE_REST_FALLBACK_POLICY = "BINANCE_REST_FALLBACK_ALLOWED"

# External libraries we recognize but never claim to "port" (just record).
KNOWN_EXTERNAL = {
    "talib",
    "ta_lib",
    "ta",
    "numpy",
    "pandas",
    "sklearn",
    "xgboost",
    "torch",
    "stable_baselines3",
    "ccxt",
    "binance",
    "redis",
    "websocket",
    "websockets",
    "requests",
    "aiohttp",
    "asyncio",
    "fastapi",
    "pydantic",
    "sqlalchemy",
    "alembic",
    "structlog",
    "uvicorn",
    "httpx",
    "psutil",
    "nvidia_smi",
    "pynvml",
}

# Standard library that we should not list as "external dependency to install".
STDLIB_GUESS = {
    "abc", "argparse", "array", "ast", "asyncio", "base64", "binascii", "bisect",
    "builtins", "bz2", "calendar", "collections", "concurrent", "configparser",
    "contextlib", "copy", "csv", "ctypes", "dataclasses", "datetime", "decimal",
    "difflib", "enum", "errno", "fcntl", "fractions", "functools", "gc",
    "getopt", "getpass", "glob", "gzip", "hashlib", "heapq", "hmac", "html",
    "http", "imp", "importlib", "inspect", "io", "ipaddress", "itertools",
    "json", "keyword", "linecache", "locale", "logging", "math", "mimetypes",
    "multiprocessing", "operator", "os", "pathlib", "pickle", "platform",
    "pprint", "queue", "random", "re", "resource", "select", "selectors",
    "shlex", "shutil", "signal", "site", "smtplib", "socket", "socketserver",
    "sqlite3", "ssl", "stat", "string", "struct", "subprocess", "sys", "syslog",
    "tempfile", "textwrap", "threading", "time", "timeit", "tokenize", "trace",
    "traceback", "tracemalloc", "typing", "unicodedata", "unittest", "urllib",
    "uuid", "warnings", "weakref", "xml", "zipfile", "zoneinfo",
}


@dataclass
class FileAnalysis:
    legacy_rel_path: str
    exists: bool = False
    parse_error: Optional[str] = None
    local_imports: List[str] = field(default_factory=list)
    external_imports: List[str] = field(default_factory=list)
    stdlib_imports: List[str] = field(default_factory=list)
    unknown_imports: List[str] = field(default_factory=list)
    redis_usage: bool = False
    exchange_api_usage: bool = False
    subprocess_usage: bool = False
    config_usage: bool = False
    log_file_writes: List[str] = field(default_factory=list)


def _collect_import_names(tree: ast.AST) -> Set[str]:
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # Relative import — we mark separately via .module if present.
                if node.module:
                    names.add(f".{node.module.split('.')[0]}")
                else:
                    names.add(".__package__")
            elif node.module:
                names.add(node.module.split(".")[0])
    return names


def _detect_runtime_uses(source: str) -> Dict[str, Any]:
    flags = {
        "redis_usage": False,
        "exchange_api_usage": False,
        "subprocess_usage": False,
        "config_usage": False,
        "log_file_writes": [],
    }
    lowered = source.lower()
    if "import redis" in source or "from redis" in source or "redis.Redis(" in source:
        flags["redis_usage"] = True
    if any(token in lowered for token in ("ccxt", "binance.client", "fapi.binance.com", "futures_", "create_market_order", "kucoin")):
        flags["exchange_api_usage"] = True
    if "subprocess" in source or "Popen(" in source:
        flags["subprocess_usage"] = True
    if "from config import" in source or "import config" in source or "config.py" in source:
        flags["config_usage"] = True
    # naive log-file path extraction (handles double-quoted "logs/foo.log" and
    # single-quoted variants commonly seen in legacy)
    for line in source.splitlines():
        if "logs/" in line and (".log" in line or ".pid" in line):
            flags["log_file_writes"].append(line.strip()[:120])
    return flags


def analyze(root: Path, rel_path: str, known_local: Set[str]) -> FileAnalysis:
    fa = FileAnalysis(legacy_rel_path=rel_path)
    src = root / rel_path
    if not src.exists():
        return fa
    fa.exists = True
    if src.suffix != ".py":
        # Shell scripts: do minimal heuristic — list referenced .py paths.
        text = src.read_text(errors="replace")
        py_refs = []
        for token in text.replace("'", " ").replace('"', " ").split():
            if token.endswith(".py"):
                py_refs.append(token)
        fa.local_imports = sorted(set(py_refs))
        runtime = _detect_runtime_uses(text)
        for k, v in runtime.items():
            setattr(fa, k, v)
        return fa
    try:
        source = src.read_text(errors="replace")
        tree = ast.parse(source, filename=str(src))
    except SyntaxError as exc:
        fa.parse_error = f"SyntaxError: {exc}"
        return fa
    names = _collect_import_names(tree)
    for name in sorted(names):
        if name.startswith("."):
            fa.local_imports.append(name)
            continue
        if name in known_local:
            fa.local_imports.append(name)
        elif name in STDLIB_GUESS:
            fa.stdlib_imports.append(name)
        elif name in KNOWN_EXTERNAL:
            fa.external_imports.append(name)
        else:
            # Could be local (a top-level module name) — record as unknown_imports;
            # closure caller will resolve by checking whether <name>.py exists
            # under root.
            fa.unknown_imports.append(name)
    runtime = _detect_runtime_uses(source)
    for k, v in runtime.items():
        setattr(fa, k, v)
    return fa


def _resolve_local_module(root: Path, name: str) -> Optional[str]:
    candidates = [
        root / f"{name}.py",
        root / name / "__init__.py",
    ]
    for c in candidates:
        if c.exists():
            return str(c.relative_to(root))
    return None


def _resolve_local_module_in_roots(roots: List[Path], name: str) -> Optional[Tuple[Path, str]]:
    for candidate_root in roots:
        rel = _resolve_local_module(candidate_root, name)
        if rel:
            return candidate_root, rel
    return None


def _analysis_key(primary_root: Path, source_root: Path, rel_path: str) -> str:
    if source_root.resolve() == primary_root.resolve():
        return rel_path
    return f"{source_root.name}/{rel_path}"


def closure(root: Path, entries: List[str], additional_roots: Optional[List[Path]] = None) -> Dict[str, Any]:
    roots = [root] + [r for r in (additional_roots or []) if r.resolve() != root.resolve()]
    visited: Set[Tuple[str, str]] = set()
    pending: List[Tuple[Path, str]] = [(root, entry) for entry in entries]
    known_local: Set[str] = set()
    # First pass: enumerate the set of "obviously local" top-level module names
    # by listing top-level .py files in the primary and additional roots.
    for scan_root in roots:
        for p in scan_root.rglob("*.py"):
            rel = p.relative_to(scan_root).as_posix()
            parts = rel.split("/")
            known_local.add(parts[0].removesuffix(".py"))
            if len(parts) > 1:
                known_local.add(parts[0])  # package name
    analyses: Dict[str, FileAnalysis] = {}
    while pending:
        cur_root, cur = pending.pop()
        visit_key = (str(cur_root.resolve()), cur)
        if visit_key in visited:
            continue
        visited.add(visit_key)
        fa = analyze(cur_root, cur, known_local)
        analyses[_analysis_key(root, cur_root, cur)] = fa
        # Walk every recognized local import (module name) to its file.
        for name in fa.local_imports:
            if name.startswith("."):
                continue
            if name.endswith(".py"):
                # Shell scripts emit explicit .py references; queue them as-is.
                if (cur_root / name).exists() and (str(cur_root.resolve()), name) not in visited and (cur_root, name) not in pending:
                    pending.append((cur_root, name))
                continue
            res = _resolve_local_module_in_roots(roots, name)
            if res and (str(res[0].resolve()), res[1]) not in visited and res not in pending:
                pending.append(res)
        # Resolve still-unknown imports against root layout (top-level module
        # names that weren't pre-populated in known_local for any reason).
        unresolved: List[str] = []
        for u in fa.unknown_imports:
            res = _resolve_local_module_in_roots(roots, u)
            if res:
                fa.local_imports.append(u)
                if (str(res[0].resolve()), res[1]) not in visited and res not in pending:
                    pending.append(res)
            else:
                unresolved.append(u)
        fa.unknown_imports = unresolved
    return {
        "root": str(root),
        "additional_roots": [str(r) for r in roots[1:]],
        "entries": entries,
        "analyses": {k: vars(v) for k, v in analyses.items()},
        "totals": {
            "files_analyzed": len(analyses),
            "files_with_parse_error": sum(1 for fa in analyses.values() if fa.parse_error),
            "files_with_redis_usage": sum(1 for fa in analyses.values() if fa.redis_usage),
            "files_with_exchange_api_usage": sum(1 for fa in analyses.values() if fa.exchange_api_usage),
            "files_with_subprocess_usage": sum(1 for fa in analyses.values() if fa.subprocess_usage),
            "files_with_config_usage": sum(1 for fa in analyses.values() if fa.config_usage),
            "files_with_unresolved_imports": sum(1 for fa in analyses.values() if fa.unknown_imports),
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="root directory of the preserved baseline")
    parser.add_argument("--additional-root", action="append", default=[], help="additional preserved root for cross-tree local imports")
    parser.add_argument("--entry", action="append", default=[], help="entry script (repeatable)")
    parser.add_argument("--all", action="store_true", help="analyze every .py and .sh in --root")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(json.dumps({"error": f"root not a directory: {root}"}))
        return 2
    additional_roots = [Path(p).resolve() for p in args.additional_root]
    missing_additional = [str(p) for p in additional_roots if not p.is_dir()]
    if missing_additional:
        print(json.dumps({"error": f"additional root not a directory: {missing_additional[0]}"}))
        return 2
    if args.all:
        entries = [p.relative_to(root).as_posix() for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in {".py", ".sh"}]
    elif args.entry:
        entries = args.entry
    else:
        print(json.dumps({"error": "must provide --entry or --all"}))
        return 2
    result = closure(root, entries, additional_roots=additional_roots)
    print(json.dumps(result, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
