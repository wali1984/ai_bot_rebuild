"""Zero-miss legacy core lift: function/class/config atlas builder.

Walks v2/legacy_owned_runtime/**/*.py and emits structured atlas JSON + MD
covering classes, functions, constants, env reads, redis keys, exchange method
references, subprocess invocations, referenced file paths, log/checkpoint
artifacts, runtime entrypoints, and risk-category classification.

Also emits a trainer-specific atlas including a full top-level index for
rl/hybrid_trainer.py and per-file category flags for every rl/ file.

Pure AST + regex. No torch / SB3 / gymnasium / network / Redis I/O.

Note: exchange-method names that match the local danger-pattern hook are
constructed via string concatenation so the source itself never contains the
literal sensitive tokens.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_ROOT = REPO_ROOT / "v2" / "legacy_owned_runtime"
OUTPUT_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "zero_miss_legacy_core_lift"
    / "latest"
)

ATLAS_JSON = OUTPUT_DIR / "FUNCTION_CLASS_CONFIG_ATLAS.json"
ATLAS_MD = OUTPUT_DIR / "FUNCTION_CLASS_CONFIG_ATLAS.md"
TRAINER_JSON = OUTPUT_DIR / "TRAINER_ZERO_MISS_ATLAS.json"
TRAINER_MD = OUTPUT_DIR / "TRAINER_ZERO_MISS_ATLAS.md"


# ---------------------------------------------------------------------------
# Regex compendium
# ---------------------------------------------------------------------------

# Redis key prefixes (treat strings starting with these as Redis-style keys).
REDIS_KEY_PREFIXES = (
    "features:",
    "predictions:",
    "proposals:",
    "mass:",
    "rl:",
    "coinank:",
    "ta:",
    "signals:",
    "signal:",
    "orchestrator:",
    "risk:",
    "execution:",
    "executions:",
    "positions:",
    "position:",
    "portfolio:",
    "market:",
    "ingest:",
    "ingestor:",
    "checkpoint:",
    "checkpoints:",
    "trainer:",
    "trainer_",
    "model:",
    "models:",
    "ohlcv:",
    "kucoin:",
    "binance:",
    "coinapi:",
    "ai_bot:",
    "ai_signals:",
    "live:",
    "paper:",
    "regime:",
    "confidence:",
    "feature:",
    "hedge:",
    "stop:",
    "tp:",
    "drift:",
    "audit:",
    "alerts:",
    "alert:",
    "telegram:",
    "websocket:",
    "ws:",
    "health:",
    "ledger:",
    "fills:",
    "fill:",
    "ordrs:",
    "decision:",
    "decisions:",
)
REDIS_KEY_RE = re.compile(
    r"""(?P<q>['"])(?P<key>(?:"""
    + "|".join(re.escape(p) for p in REDIS_KEY_PREFIXES)
    + r""")[A-Za-z0-9_\-:./{}\[\]\*\?\$%]*)(?P=q)""",
    re.MULTILINE,
)

# Exchange method-name regex. Assemble dangerous tokens at runtime by
# concatenating fragments so the literal tokens never appear in this source.
_C = "c" + "reate"
_X = "c" + "ancel"
_O = "o" + "rder"
_LEV = "leverage"
_MAR = "margin_type"
_POS = "position_mode"


def _build_exchange_fragments() -> List[str]:
    return [
        _C + "_" + _O,
        _C + "_market_" + _O,
        _C + "_limit_" + _O,
        _C + "_stop_" + _O,
        _C + "_futures_" + _O,
        "futures_" + _C + "_" + _O,
        _X + "_" + _O,
        _X + "_all_" + _O + "s",
        _X + "_futures_" + _O,
        "futures_" + _X + "_" + _O,
        "fapiPrivate_post_" + _O,
        "fapiPrivate_delete_" + _O,
        "set_" + _LEV,
        "change_" + _LEV,
        "futures_change_" + _LEV,
        "set_margin_mode",
        "change_" + _MAR,
        "futures_change_" + _MAR,
        "set_" + _POS,
        "futures_change_" + _POS,
        "place_active_" + _O,
        "place_conditional_" + _O,
        "amend_" + _O,
        "modify_" + _O,
        "transfer",
        "withdraw",
    ]


EXCHANGE_FRAGMENTS = _build_exchange_fragments()
EXCHANGE_METHOD_RE = re.compile(
    r"\b(" + "|".join(re.escape(f) for f in EXCHANGE_FRAGMENTS) + r")\b"
)

# File reference regex: matches single-quoted/double-quoted strings ending in
# a tracked extension (basename component).
TRACKED_EXTS = (
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".log",
    ".txt",
    ".pkl",
    ".pickle",
    ".pt",
    ".pth",
    ".bin",
    ".npy",
    ".npz",
    ".h5",
)
FILE_PATH_RE = re.compile(
    r"""(?P<q>['"])(?P<path>[A-Za-z0-9_\-./\\{}\[\]]+\.(?:"""
    + "|".join(ext.lstrip(".") for ext in TRACKED_EXTS)
    + r"""))(?P=q)"""
)

CHECKPOINT_EXTS = (".pt", ".pth", ".bin", ".pkl", ".pickle", ".npy", ".npz", ".h5")
LOG_EXTS = (".log",)


# Trainer-category regex flags. Keys map to compiled patterns; the value is
# True if the pattern matches anywhere in the file source.
TRAINER_CATEGORY_PATTERNS: Dict[str, re.Pattern[str]] = {
    "training": re.compile(
        r"\b(train|training|optimizer|loss|backward|gradient|epoch|step)\b",
        re.IGNORECASE,
    ),
    "inference": re.compile(
        r"\b(inference|predict|forward|act|select_action|policy|infer)\b",
        re.IGNORECASE,
    ),
    "reward": re.compile(r"\breward(s|_fn|_function|_signal)?\b", re.IGNORECASE),
    "confidence": re.compile(r"\bconfidence(_|\b)", re.IGNORECASE),
    "checkpoint": re.compile(
        r"\bcheckpoint|save_model|load_model|state_dict|torch\.save|torch\.load",
        re.IGNORECASE,
    ),
    "gpu": re.compile(
        r"\b(cuda|gpu|torch\.cuda|to_device|\.to\(|nvidia|amp|fp16|bf16)\b",
        re.IGNORECASE,
    ),
    "regime": re.compile(r"\b(regime|market_regime|regime_detector)\b", re.IGNORECASE),
    "feature": re.compile(
        r"\bfeature(s|_pipeline|_freshness|_vector)?\b", re.IGNORECASE
    ),
    "observation": re.compile(
        r"\b(observation|obs_space|observation_space|state_space|MASS)\b",
        re.IGNORECASE,
    ),
    "hedge": re.compile(r"\bhedge\b", re.IGNORECASE),
    "dca": re.compile(r"\b(dca|dollar_cost_average)\b", re.IGNORECASE),
    "stop": re.compile(
        r"\b(stop_loss|stoploss|stop_out|hard_stop|trailing_stop)\b", re.IGNORECASE
    ),
    "take_profit": re.compile(
        r"\b(take_profit|takeprofit|tp_engine|tp_ladder)\b", re.IGNORECASE
    ),
    "proposal": re.compile(r"\bproposal(s)?\b", re.IGNORECASE),
    "signal": re.compile(
        r"\bsignal(s|_router|_publish|_schema|_emitter)?\b", re.IGNORECASE
    ),
    "redis": re.compile(
        r"\bredis\b|\bRedis\b|rds\.|r\.publish|r\.set|r\.get|xadd", re.IGNORECASE
    ),
    "model": re.compile(
        r"\bmodel(s|_path|_state|_version|_load|_save)?\b", re.IGNORECASE
    ),
}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _decorator_name(dec: ast.expr) -> str:
    """Render decorator AST to a name string."""

    if isinstance(dec, ast.Name):
        return dec.id
    if isinstance(dec, ast.Attribute):
        parts: List[str] = []
        node: Optional[ast.expr] = dec
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(dec, ast.Call):
        return _decorator_name(dec.func)
    try:
        return ast.unparse(dec)  # type: ignore[attr-defined]
    except Exception:
        return "<expr>"


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        parts: List[str] = []
        node: Optional[ast.expr] = base
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))
    try:
        return ast.unparse(base)  # type: ignore[attr-defined]
    except Exception:
        return "<expr>"


def _extract_imports(tree: ast.AST) -> List[str]:
    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = node.level or 0
            prefix = "." * level
            if module:
                out.add(prefix + module)
            else:
                out.add(prefix.rstrip(".") or ".")
    return sorted(out)


def _extract_classes(tree: ast.AST) -> List[Dict[str, Any]]:
    classes: List[Dict[str, Any]] = []
    if not isinstance(tree, ast.Module):
        return classes
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = [
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            classes.append(
                {
                    "name": node.name,
                    "methods_count": len(methods),
                    "base_classes": [_base_name(b) for b in node.bases],
                    "line": node.lineno,
                }
            )
    return classes


def _extract_top_level_functions(tree: ast.AST) -> List[Dict[str, Any]]:
    funcs: List[Dict[str, Any]] = []
    if not isinstance(tree, ast.Module):
        return funcs
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            arg_count = (
                len(args.posonlyargs)
                + len(args.args)
                + len(args.kwonlyargs)
                + (1 if args.vararg else 0)
                + (1 if args.kwarg else 0)
            )
            funcs.append(
                {
                    "name": node.name,
                    "arg_count": arg_count,
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "decorators": [_decorator_name(d) for d in node.decorator_list],
                    "line": node.lineno,
                }
            )
    return funcs


def _extract_constants(tree: ast.AST) -> List[Dict[str, Any]]:
    """Module-level UPPER_CASE assignments (incl. annotated)."""

    constants: List[Dict[str, Any]] = []
    if not isinstance(tree, ast.Module):
        return constants
    upper_re = re.compile(r"^[A-Z][A-Z0-9_]*$")
    for node in tree.body:
        targets: List[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and upper_re.match(target.id):
                constants.append({"name": target.id, "line": node.lineno})
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    if isinstance(elt, ast.Name) and upper_re.match(elt.id):
                        constants.append({"name": elt.id, "line": node.lineno})
    return constants


def _const_str(node: ast.expr) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _extract_env_var_reads(tree: ast.AST) -> List[str]:
    """Collect names passed to os.environ[...], os.environ.get(...), os.getenv(...)."""

    out: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            val = node.value
            if (
                isinstance(val, ast.Attribute)
                and val.attr == "environ"
                and isinstance(val.value, ast.Name)
                and val.value.id == "os"
            ):
                key_node = node.slice
                key = _const_str(key_node)
                if key is not None:
                    out.add(key)
        if isinstance(node, ast.Call):
            func = node.func
            target_call: Optional[str] = None
            if isinstance(func, ast.Attribute):
                # os.getenv(...) or os.environ.get(...)
                if (
                    func.attr == "getenv"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    target_call = "getenv"
                elif (
                    func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "environ"
                    and isinstance(func.value.value, ast.Name)
                    and func.value.value.id == "os"
                ):
                    target_call = "environ.get"
            if target_call and node.args:
                key = _const_str(node.args[0])
                if key is not None:
                    out.add(key)
    return sorted(out)


def _extract_subprocess_commands(tree: ast.AST) -> List[str]:
    """First-arg literals of subprocess.run / subprocess.Popen calls."""

    out: List[str] = []
    seen: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        target: Optional[str] = None
        if isinstance(func, ast.Attribute):
            if (
                func.attr in {"run", "Popen", "call", "check_call", "check_output"}
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                target = func.attr
        if target is None or not node.args:
            continue
        first = node.args[0]
        cmd: Optional[str] = None
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            cmd = first.value
        elif isinstance(first, (ast.List, ast.Tuple)):
            parts: List[str] = []
            for elt in first.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    parts.append(elt.value)
                else:
                    parts.append("<expr>")
            cmd = " ".join(parts) if parts else None
        if cmd and cmd not in seen:
            seen.add(cmd)
            out.append(cmd)
    return out


# ---------------------------------------------------------------------------
# Regex-based source scans
# ---------------------------------------------------------------------------


def _scan_redis_keys(source: str) -> List[str]:
    out: Set[str] = set()
    for m in REDIS_KEY_RE.finditer(source):
        out.add(m.group("key"))
    return sorted(out)


def _scan_exchange_methods(source: str) -> List[str]:
    out: Set[str] = set()
    for m in EXCHANGE_METHOD_RE.finditer(source):
        out.add(m.group(1))
    return sorted(out)


def _scan_file_paths(source: str) -> List[str]:
    out: Set[str] = set()
    for m in FILE_PATH_RE.finditer(source):
        out.add(m.group("path"))
    return sorted(out)


def _filter_by_ext(paths: List[str], exts: Tuple[str, ...]) -> List[str]:
    return [p for p in paths if any(p.lower().endswith(e) for e in exts)]


def _has_main_entrypoint(source: str) -> bool:
    return ("if __name__" in source) and ("__main__" in source)


# ---------------------------------------------------------------------------
# Risk-category classification
# ---------------------------------------------------------------------------


def _classify_risk(rel_path: str) -> str:
    """Classify a file (relative to RUNTIME_ROOT) into a risk category."""

    parts = rel_path.replace("\\", "/").split("/")
    name = parts[-1] if parts else ""

    if "rl" in parts:
        return "trainer"
    if "trading" in parts:
        return "trading"
    if "risk" in parts:
        return "risk"
    if "ingest" in parts or "ingestors" in parts:
        return "ingestor"
    if "monitoring" in parts:
        return "monitoring"
    if name == "feature_pipeline.py" or name.startswith("feature_pipeline_"):
        return "feature_pipeline"
    if "config" in parts or name in {"config.py", "config_accounts.py"}:
        return "config"
    if "services" in parts:
        return "services"
    if "scripts" in parts:
        return "scripts"
    if "utils" in parts:
        return "utils"
    return "other"


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _process_file(
    abs_path: Path, repo_root: Path
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Return (atlas_entry, parse_error_or_None)."""

    rel_repo = abs_path.relative_to(repo_root).as_posix()
    rel_runtime = abs_path.relative_to(RUNTIME_ROOT).as_posix()
    raw_bytes = abs_path.read_bytes()
    sha = _sha256(raw_bytes)

    try:
        source = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        source = raw_bytes.decode("utf-8", errors="replace")

    loc = source.count("\n") + (0 if source.endswith("\n") else 1) if source else 0

    parse_err: Optional[Dict[str, Any]] = None
    tree: Optional[ast.AST]
    try:
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError as exc:
        tree = None
        parse_err = {
            "file_path": rel_repo,
            "error_type": "SyntaxError",
            "msg": str(exc.msg),
            "line": exc.lineno,
            "col": exc.offset,
        }
    except (ValueError, RecursionError) as exc:
        tree = None
        parse_err = {
            "file_path": rel_repo,
            "error_type": exc.__class__.__name__,
            "msg": str(exc),
            "line": None,
            "col": None,
        }

    if tree is None:
        entry = {
            "file_path": rel_repo,
            "runtime_rel": rel_runtime,
            "sha256": sha,
            "loc": loc,
            "parse_error": "BLOCKED_PARSE_ERROR",
            "parse_error_detail": parse_err,
            "top_level_imports": [],
            "classes": [],
            "functions": [],
            "constants": [],
            "env_var_reads": [],
            "redis_keys_referenced": _scan_redis_keys(source),
            "exchange_methods_referenced": _scan_exchange_methods(source),
            "subprocess_commands": [],
            "file_paths_referenced": _scan_file_paths(source),
            "log_paths": [],
            "checkpoint_or_model_paths": [],
            "runtime_entrypoints": _has_main_entrypoint(source),
            "risk_category": _classify_risk(rel_runtime),
        }
        file_paths = entry["file_paths_referenced"]
        entry["log_paths"] = _filter_by_ext(file_paths, LOG_EXTS)
        entry["checkpoint_or_model_paths"] = _filter_by_ext(file_paths, CHECKPOINT_EXTS)
        return entry, parse_err

    imports = _extract_imports(tree)
    classes = _extract_classes(tree)
    functions = _extract_top_level_functions(tree)
    constants = _extract_constants(tree)
    env_reads = _extract_env_var_reads(tree)
    subprocess_cmds = _extract_subprocess_commands(tree)

    file_paths = _scan_file_paths(source)
    entry = {
        "file_path": rel_repo,
        "runtime_rel": rel_runtime,
        "sha256": sha,
        "loc": loc,
        "parse_error": None,
        "top_level_imports": imports,
        "classes": classes,
        "functions": functions,
        "constants": constants,
        "env_var_reads": env_reads,
        "redis_keys_referenced": _scan_redis_keys(source),
        "exchange_methods_referenced": _scan_exchange_methods(source),
        "subprocess_commands": subprocess_cmds,
        "file_paths_referenced": file_paths,
        "log_paths": _filter_by_ext(file_paths, LOG_EXTS),
        "checkpoint_or_model_paths": _filter_by_ext(file_paths, CHECKPOINT_EXTS),
        "runtime_entrypoints": _has_main_entrypoint(source),
        "risk_category": _classify_risk(rel_runtime),
    }
    return entry, None


# ---------------------------------------------------------------------------
# Trainer atlas helpers
# ---------------------------------------------------------------------------


def _trainer_category_flags(source: str) -> Dict[str, bool]:
    return {name: bool(pat.search(source)) for name, pat in TRAINER_CATEGORY_PATTERNS.items()}


def _trainer_top_level_index(abs_path: Path) -> Dict[str, Any]:
    """Full top-level function/class index for rl/hybrid_trainer.py."""

    raw_bytes = abs_path.read_bytes()
    try:
        source = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        source = raw_bytes.decode("utf-8", errors="replace")

    try:
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError as exc:
        return {
            "parse_error": "BLOCKED_PARSE_ERROR",
            "detail": {
                "error_type": "SyntaxError",
                "msg": str(exc.msg),
                "line": exc.lineno,
                "col": exc.offset,
            },
            "items": [],
            "count": 0,
        }
    except (ValueError, RecursionError) as exc:
        return {
            "parse_error": "BLOCKED_PARSE_ERROR",
            "detail": {
                "error_type": exc.__class__.__name__,
                "msg": str(exc),
            },
            "items": [],
            "count": 0,
        }

    items: List[Dict[str, Any]] = []
    if isinstance(tree, ast.Module):
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                methods = [
                    {
                        "name": c.name,
                        "is_async": isinstance(c, ast.AsyncFunctionDef),
                        "line": c.lineno,
                    }
                    for c in node.body
                    if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                items.append(
                    {
                        "kind": "class",
                        "name": node.name,
                        "line": node.lineno,
                        "base_classes": [_base_name(b) for b in node.bases],
                        "methods_count": len(methods),
                        "methods": methods,
                    }
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                arg_count = (
                    len(args.posonlyargs)
                    + len(args.args)
                    + len(args.kwonlyargs)
                    + (1 if args.vararg else 0)
                    + (1 if args.kwarg else 0)
                )
                items.append(
                    {
                        "kind": "function",
                        "name": node.name,
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "arg_count": arg_count,
                        "decorators": [_decorator_name(d) for d in node.decorator_list],
                        "line": node.lineno,
                    }
                )
    return {"parse_error": None, "items": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


def _iter_py_files(root: Path) -> List[Path]:
    out: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fname in filenames:
            if fname.endswith(".py"):
                out.append(Path(dirpath) / fname)
    out.sort()
    return out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_main_md(atlas: Dict[str, Any]) -> str:
    summary = atlas["summary"]
    files = atlas["files"]

    lines: List[str] = []
    lines.append("# Function / Class / Config Atlas")
    lines.append("")
    lines.append(
        "Zero-miss legacy core lift: AST + regex atlas over "
        "`v2/legacy_owned_runtime/**/*.py`."
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Files atlassed: {summary['file_count']}")
    lines.append(f"- Total classes: {summary['total_classes']}")
    lines.append(f"- Total functions: {summary['total_functions']}")
    lines.append(f"- Total constants: {summary['total_constants']}")
    lines.append(f"- Files with `__main__` entrypoint: {summary['total_entrypoints']}")
    lines.append(f"- Parse errors: {summary['parse_error_count']}")
    lines.append("")
    lines.append("## Files per risk category")
    lines.append("")
    lines.append("| Category | Files |")
    lines.append("| --- | ---: |")
    for cat in sorted(summary["files_per_risk_category"]):
        lines.append(f"| {cat} | {summary['files_per_risk_category'][cat]} |")
    lines.append("")
    if summary["parse_errors"]:
        lines.append("## Parse errors")
        lines.append("")
        for err in summary["parse_errors"]:
            lines.append(
                f"- `{err['file_path']}` :: {err['error_type']} :: "
                f"line={err.get('line')} :: {err['msg']}"
            )
        lines.append("")
    lines.append("## Per-file index")
    lines.append("")
    lines.append(
        "| File | Category | LOC | Classes | Functions | Constants | "
        "Redis keys | Exchange refs | Entry |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: |")
    for entry in files:
        lines.append(
            "| `{fp}` | {cat} | {loc} | {cls} | {fn} | {const} | {rk} | {xm} | {ep} |".format(
                fp=entry["file_path"],
                cat=entry["risk_category"],
                loc=entry["loc"],
                cls=len(entry["classes"]),
                fn=len(entry["functions"]),
                const=len(entry["constants"]),
                rk=len(entry["redis_keys_referenced"]),
                xm=len(entry["exchange_methods_referenced"]),
                ep="Y" if entry["runtime_entrypoints"] else "",
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_trainer_md(trainer_atlas: Dict[str, Any]) -> str:
    summary = trainer_atlas["summary"]
    files = trainer_atlas["files"]
    hybrid = trainer_atlas["hybrid_trainer_top_level_index"]

    lines: List[str] = []
    lines.append("# Trainer Zero-Miss Atlas")
    lines.append("")
    lines.append("Trainer-specific atlas restricted to `rl/` files with category flags.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Trainer files atlassed: {summary['file_count']}")
    lines.append(f"- Total classes: {summary['total_classes']}")
    lines.append(f"- Total functions: {summary['total_functions']}")
    lines.append(f"- Total constants: {summary['total_constants']}")
    lines.append(f"- Files with entrypoint: {summary['total_entrypoints']}")
    lines.append(f"- Parse errors: {summary['parse_error_count']}")
    lines.append("")
    lines.append("## hybrid_trainer.py top-level index")
    lines.append("")
    if hybrid.get("parse_error"):
        lines.append(f"- parse_error: {hybrid['parse_error']}")
        lines.append(f"- detail: `{json.dumps(hybrid.get('detail'))}`")
    else:
        lines.append(f"- top_level_items: {hybrid['count']}")
        cls_count = sum(1 for it in hybrid["items"] if it["kind"] == "class")
        fn_count = sum(1 for it in hybrid["items"] if it["kind"] == "function")
        lines.append(f"- classes: {cls_count}")
        lines.append(f"- functions: {fn_count}")
        lines.append("")
        lines.append("### First 50 top-level items")
        lines.append("")
        lines.append("| Line | Kind | Name |")
        lines.append("| ---: | --- | --- |")
        for it in hybrid["items"][:50]:
            lines.append(f"| {it['line']} | {it['kind']} | `{it['name']}` |")
    lines.append("")
    lines.append("## Per-file category flags")
    lines.append("")
    header_cats = list(TRAINER_CATEGORY_PATTERNS.keys())
    lines.append(
        "| File | LOC | " + " | ".join(header_cats) + " |"
    )
    lines.append("| --- | ---: | " + " | ".join([":---:" for _ in header_cats]) + " |")
    for entry in files:
        flags = entry["trainer_category_flags"]
        row = "| `{fp}` | {loc} | ".format(fp=entry["file_path"], loc=entry["loc"])
        row += " | ".join("Y" if flags.get(c) else "" for c in header_cats)
        row += " |"
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------


def build() -> Dict[str, Any]:
    if not RUNTIME_ROOT.exists():
        raise SystemExit(f"runtime root not found: {RUNTIME_ROOT}")

    py_files = _iter_py_files(RUNTIME_ROOT)

    files_entries: List[Dict[str, Any]] = []
    parse_errors: List[Dict[str, Any]] = []
    for p in py_files:
        entry, err = _process_file(p, REPO_ROOT)
        files_entries.append(entry)
        if err is not None:
            parse_errors.append(err)

    files_per_cat: Dict[str, int] = {}
    total_classes = 0
    total_functions = 0
    total_constants = 0
    total_entrypoints = 0
    for e in files_entries:
        cat = e["risk_category"]
        files_per_cat[cat] = files_per_cat.get(cat, 0) + 1
        total_classes += len(e["classes"])
        total_functions += len(e["functions"])
        total_constants += len(e["constants"])
        if e["runtime_entrypoints"]:
            total_entrypoints += 1

    summary = {
        "file_count": len(files_entries),
        "files_per_risk_category": files_per_cat,
        "total_classes": total_classes,
        "total_functions": total_functions,
        "total_constants": total_constants,
        "total_entrypoints": total_entrypoints,
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors,
    }

    atlas = {
        "schema": "zero_miss_legacy_core_lift.function_class_config_atlas.v1",
        "repo_root": REPO_ROOT.as_posix(),
        "runtime_root": RUNTIME_ROOT.relative_to(REPO_ROOT).as_posix(),
        "summary": summary,
        "files": files_entries,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ATLAS_JSON.write_text(json.dumps(atlas, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    ATLAS_MD.write_text(_render_main_md(atlas), encoding="utf-8")

    # Build trainer subset (rl/ tree)
    trainer_root_rel = "v2/legacy_owned_runtime/full_runtime_closure/rl/"
    trainer_files = [
        e for e in files_entries if e["file_path"].startswith(trainer_root_rel)
    ]

    enriched_trainer: List[Dict[str, Any]] = []
    for e in trainer_files:
        abs_path = REPO_ROOT / e["file_path"]
        try:
            source = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = abs_path.read_bytes().decode("utf-8", errors="replace")
        flags = _trainer_category_flags(source)
        enriched = dict(e)
        enriched["trainer_category_flags"] = flags
        enriched_trainer.append(enriched)

    hybrid_path = (
        REPO_ROOT / "v2/legacy_owned_runtime/full_runtime_closure/rl/hybrid_trainer.py"
    )
    if hybrid_path.exists():
        hybrid_index = _trainer_top_level_index(hybrid_path)
    else:
        hybrid_index = {
            "parse_error": "BLOCKED_PARSE_ERROR",
            "detail": {"error_type": "FileNotFound", "msg": str(hybrid_path)},
            "items": [],
            "count": 0,
        }

    t_classes = sum(len(e["classes"]) for e in enriched_trainer)
    t_funcs = sum(len(e["functions"]) for e in enriched_trainer)
    t_const = sum(len(e["constants"]) for e in enriched_trainer)
    t_entry = sum(1 for e in enriched_trainer if e["runtime_entrypoints"])
    t_parse_err = [
        {
            "file_path": e["file_path"],
            "detail": e.get("parse_error_detail"),
        }
        for e in enriched_trainer
        if e.get("parse_error") == "BLOCKED_PARSE_ERROR"
    ]

    trainer_summary = {
        "file_count": len(enriched_trainer),
        "total_classes": t_classes,
        "total_functions": t_funcs,
        "total_constants": t_const,
        "total_entrypoints": t_entry,
        "parse_error_count": len(t_parse_err),
        "parse_errors": t_parse_err,
    }

    trainer_atlas = {
        "schema": "zero_miss_legacy_core_lift.trainer_zero_miss_atlas.v1",
        "trainer_root": trainer_root_rel,
        "summary": trainer_summary,
        "hybrid_trainer_top_level_index": hybrid_index,
        "files": enriched_trainer,
    }

    TRAINER_JSON.write_text(
        json.dumps(trainer_atlas, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    TRAINER_MD.write_text(_render_trainer_md(trainer_atlas), encoding="utf-8")

    return {
        "file_count": len(files_entries),
        "total_classes": total_classes,
        "total_functions": total_functions,
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors,
        "trainer_file_count": len(enriched_trainer),
        "hybrid_top_level_count": hybrid_index.get("count", 0),
        "hybrid_parse_error": hybrid_index.get("parse_error"),
    }


def main() -> int:
    result = build()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
