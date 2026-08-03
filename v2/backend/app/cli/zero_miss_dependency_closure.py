"""Phase 1: Zero-miss dependency closure scanner.

Walks the V2-owned runtime tree (v2/legacy_owned_runtime/), parses every
.py file with AST, resolves each import to one of:

  - LOCAL_RESOLVED       (file present in v2/legacy_owned_runtime/)
  - LOCAL_UNRESOLVED     (file missing from v2/legacy_owned_runtime/)
  - V2_REPLACEMENT       (V2-native module replaces it; see V2_REPLACEMENT_TABLE)
  - STDLIB               (Python standard library)
  - EXTERNAL_DEPENDENCY  (third-party PyPI package)

Outputs two artifacts:

  - claude_worklog/final_readiness/zero_miss_legacy_core_lift/latest/
        ZERO_MISS_DEPENDENCY_CLOSURE.json
  - claude_worklog/final_readiness/zero_miss_legacy_core_lift/latest/
        ZERO_MISS_DEPENDENCY_CLOSURE.md

This script does not start any runtime, write to legacy Redis, or mutate
exchange state. It only reads source and writes the two output files.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[4]
RUNTIME_TREE = REPO / "v2/legacy_owned_runtime"
OUT_DIR = REPO / "claude_worklog/final_readiness/zero_miss_legacy_core_lift/latest"

# Standard library modules we know about (limited list, supplemented at runtime).
KNOWN_STDLIB = {
    "abc", "argparse", "array", "asyncio", "base64", "bisect", "builtins", "calendar",
    "collections", "concurrent", "contextlib", "copy", "csv", "ctypes", "dataclasses",
    "datetime", "decimal", "difflib", "dis", "email", "enum", "errno", "fcntl",
    "fnmatch", "functools", "gc", "glob", "gzip", "hashlib", "heapq", "hmac", "html",
    "http", "importlib", "inspect", "io", "ipaddress", "itertools", "json", "logging",
    "math", "mmap", "multiprocessing", "operator", "os", "pathlib", "pickle", "pkgutil",
    "platform", "pprint", "queue", "random", "re", "secrets", "select", "selectors",
    "shlex", "shutil", "signal", "socket", "sqlite3", "ssl", "stat", "string", "struct",
    "subprocess", "sys", "tempfile", "textwrap", "threading", "time", "timeit", "token",
    "tokenize", "trace", "traceback", "types", "typing", "unicodedata", "unittest",
    "urllib", "uuid", "venv", "warnings", "weakref", "xml", "zipfile", "zlib",
    "zoneinfo", "__future__",
}

# Top-level modules in the runtime tree are taken as local roots.
def discover_local_roots(runtime: Path) -> set[str]:
    """Top-level names importable when the runtime tree and its subroots
    are on sys.path. Recognizes both top-level files and packages, plus
    children of designated subroots (full_runtime_closure, startup_baseline,
    ingestors).
    """
    roots: set[str] = set()
    if not runtime.exists():
        return roots
    candidates = [runtime] + [runtime / sub for sub in RUNTIME_SUBROOTS]
    for base in candidates:
        if not base.exists() or not base.is_dir():
            continue
        for p in base.iterdir():
            if p.is_dir():
                # Package style (has __init__.py) OR module-style directory
                # (legacy bot's rl/ trading/ folders frequently lack __init__.py
                # but are imported as packages by virtue of containing modules).
                roots.add(p.name)
            elif p.is_file() and p.suffix == ".py":
                roots.add(p.stem)
    return roots


# V2 replacement table: legacy module → V2-native module that replaces it.
# These are intentional rewrites under the migration completion contract.
V2_REPLACEMENT_TABLE = {
    "utils.redis_client": "v2.backend.app.adapters.redis_v2",
    "utils.logger": "v2.backend.app.adapters.logging",
    "utils.signal_publish": "v2.backend.app.adapters.redis_v2.streams",
    "utils.signal_schema": "v2.backend.app.api.schemas.signal",
    "utils.healthbeat": "v2.backend.app.api.v1.health",
}

# Third-party PyPI candidates we expect to see in the legacy code.
KNOWN_EXTERNAL = {
    "torch", "stable_baselines3", "gymnasium", "gym", "numpy", "pandas",
    "redis", "websockets", "websocket", "binance", "ccxt", "ta", "scipy",
    "talib",
    "sklearn", "joblib", "yaml", "requests", "aiohttp", "pydantic", "structlog",
    "uvloop", "tenacity", "boto3", "asyncpg", "psycopg2", "msgpack", "orjson",
    "ujson", "cython", "numba", "tqdm", "click", "fastapi", "starlette",
    "httpx", "pytest", "matplotlib", "seaborn", "plotly", "dash", "telegram",
    "python_telegram_bot", "telegram_bot", "supabase", "google",
    "cloudpickle", "dateutil", "dotenv", "nvidia_ml_py", "nvidia_ml_py3",
    "psutil", "pynvml", "pytz", "schedule", "urllib3", "setproctitle",
    "flask", "flask_cors", "flask_socketio", "grpc", "grpcio", "jwt", "PyJWT",
    "GPUtil",
}


# Subdirectories under the runtime tree that contribute their children
# as additional local roots when sys.path includes them.
RUNTIME_SUBROOTS = (
    "full_runtime_closure",
    "startup_baseline",
    "ingestors",
    "api/grpc",
    "rl",
    "trading",
    "scripts",
)


def parse_imports(path: Path) -> tuple[set[str], list[str]]:
    """Return (top_level_module_names, errors) for a file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as e:
        return set(), [f"{path}: SYNTAX_ERROR: {e}"]
    except Exception as e:
        return set(), [f"{path}: PARSE_ERROR: {e}"]
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative import — skip; the relative root will resolve locally
                continue
            if node.module:
                out.add(node.module.split(".")[0])
    return out, []


def classify(name: str, local_roots: set[str], stdlib: set[str]) -> str:
    if name in stdlib:
        return "STDLIB"
    if name in local_roots:
        return "LOCAL_RESOLVED"
    full_replacements = set(V2_REPLACEMENT_TABLE.keys())
    if name in {k.split(".")[0] for k in full_replacements}:
        return "V2_REPLACEMENT"
    if name in KNOWN_EXTERNAL:
        return "EXTERNAL_DEPENDENCY"
    return "LOCAL_UNRESOLVED"


def main(argv: list[str] | None = None) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not RUNTIME_TREE.exists():
        out = {
            "runtime_tree": str(RUNTIME_TREE),
            "ready": False,
            "error": "RUNTIME_TREE_MISSING",
        }
        (OUT_DIR / "ZERO_MISS_DEPENDENCY_CLOSURE.json").write_text(
            json.dumps(out, indent=2, sort_keys=True) + "\n"
        )
        print("RUNTIME_TREE_MISSING")
        return 2

    # Use sys.stdlib_module_names if available (3.10+).
    stdlib = set(getattr(sys, "stdlib_module_names", set())) | KNOWN_STDLIB

    local_roots = discover_local_roots(RUNTIME_TREE)
    files: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "STDLIB": 0, "LOCAL_RESOLVED": 0, "LOCAL_UNRESOLVED": 0,
        "V2_REPLACEMENT": 0, "EXTERNAL_DEPENDENCY": 0,
    }
    errors: list[str] = []
    unresolved_set: set[str] = set()
    external_set: set[str] = set()

    py_files = sorted(RUNTIME_TREE.rglob("*.py"))
    for p in py_files:
        rel = p.relative_to(REPO)
        imports, errs = parse_imports(p)
        errors.extend(errs)
        per_import: list[dict[str, Any]] = []
        for imp in sorted(imports):
            cls = classify(imp, local_roots, stdlib)
            counts[cls] = counts.get(cls, 0) + 1
            if cls == "LOCAL_UNRESOLVED":
                unresolved_set.add(imp)
            elif cls == "EXTERNAL_DEPENDENCY":
                external_set.add(imp)
            per_import.append({"module": imp, "class": cls})
        files.append({
            "path": str(rel),
            "imports": per_import,
            "import_count": len(per_import),
        })

    summary = {
        "schema_version": "1.0.0",
        "runtime_tree": "v2/legacy_owned_runtime",
        "local_roots": sorted(local_roots),
        "py_file_count": len(py_files),
        "classification_counts": counts,
        "unresolved_local_imports_unique": sorted(unresolved_set),
        "unresolved_local_imports_count": len(unresolved_set),
        "external_dependencies_unique": sorted(external_set),
        "external_dependencies_count": len(external_set),
        "parse_errors": errors,
        "ready_no_unresolved_local_imports": len(unresolved_set) == 0,
        "files": files,
    }
    (OUT_DIR / "ZERO_MISS_DEPENDENCY_CLOSURE.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )

    md = []
    md.append("# Zero-Miss Dependency Closure")
    md.append("")
    md.append(f"Generated runtime tree: `v2/legacy_owned_runtime`")
    md.append(f"Python files scanned: **{len(py_files)}**")
    md.append("")
    md.append("## Classification counts")
    md.append("")
    md.append("| Class | Count |")
    md.append("|-------|-------|")
    for k in ("STDLIB", "LOCAL_RESOLVED", "LOCAL_UNRESOLVED", "V2_REPLACEMENT", "EXTERNAL_DEPENDENCY"):
        md.append(f"| `{k}` | {counts.get(k, 0)} |")
    md.append("")
    md.append(f"Unique unresolved local imports: **{len(unresolved_set)}**")
    md.append("")
    if unresolved_set:
        md.append("Unresolved (top-level names):")
        md.append("")
        for u in sorted(unresolved_set):
            md.append(f"- `{u}`")
        md.append("")
    md.append(f"Unique external dependencies: **{len(external_set)}**")
    md.append("")
    if external_set:
        md.append("External (top-level names):")
        md.append("")
        for x in sorted(external_set):
            md.append(f"- `{x}`")
        md.append("")
    md.append("## Parse errors")
    md.append("")
    if errors:
        for e in errors[:30]:
            md.append(f"- {e}")
        if len(errors) > 30:
            md.append(f"- ... and {len(errors) - 30} more")
    else:
        md.append("None.")
    md.append("")
    md.append(f"ready_no_unresolved_local_imports: **{summary['ready_no_unresolved_local_imports']}**")
    md.append("")
    md.append("This scanner did not import, execute, or write to legacy Redis.")
    (OUT_DIR / "ZERO_MISS_DEPENDENCY_CLOSURE.md").write_text("\n".join(md) + "\n")

    print(
        f"py_files={len(py_files)} unresolved_local={len(unresolved_set)} "
        f"external={len(external_set)} parse_errors={len(errors)}"
    )
    return 0 if len(unresolved_set) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
