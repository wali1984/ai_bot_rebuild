#!/usr/bin/env python3
"""Build a reproducible, secret-safe, low-level atlas of the tracked system.

This is documentation tooling only.  It performs static analysis over files
returned by ``git ls-files`` and never imports application modules, connects to
Redis, contacts a provider/exchange, or mutates runtime state.

The JSON artifacts are the exhaustive layer.  The generated Markdown files are
navigation aids for humans; they intentionally point back to the JSON records
instead of duplicating every edge in prose.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


CODE_SUFFIXES = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".swift": "swift",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
}
CONFIG_SUFFIXES = {
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "config",
    ".service": "systemd",
    ".timer": "systemd",
    ".socket": "systemd",
    ".sql": "sql",
}
SECRET_PATH_PARTS = {
    ".local_secrets",
    "secrets",
    ".ssh",
    ".aws",
}
SECRET_NAME_RE = re.compile(
    r"(?:^|[_.-])(secret|credential|private[_-]?key|auth[_-]?users?|auth[_-]?revocations?)(?:[_.-]|$)",
    re.IGNORECASE,
)
SENSITIVE_KEY_RE = re.compile(
    r"(?:^|_)(?:secret|password|passwd|pwd|token|api_token|api_key|access_key|account_key|"
    r"private_key|signing_key|encryption_key|license_key|client_secret|credential|"
    r"authorization|cookie|webhook_url|connection_string|dsn|sig)s?(?:_value|_values|_default)?$",
    re.IGNORECASE,
)
URI_USERINFO_RE = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)(?P<userinfo>(?!<redacted-userinfo>)[^/@\s]+)@"
)
SECRET_VALUE_PATTERNS = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bSG\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"https://hooks\.slack\.com/services/[^\s?#]+", re.IGNORECASE),
    re.compile(r"https://discord(?:app)?\.com/api/webhooks/[^\s?#]+", re.IGNORECASE),
)
SENSITIVE_ASSIGNMENT_LABEL = (
    r"password|passwd|pwd|secret|credential|token|api[_-]?key|api[_-]?secret|"
    r"access[_-]?key|account[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"client[_-]?secret|private[_-]?key|signing[_-]?key|encryption[_-]?key|"
    r"license[_-]?key|authorization|cookie|webhook[_-]?url|connection[_-]?string|dsn|sig"
)
SECRET_ASSIGNMENT_RE = re.compile(
    rf"(?i)\b({SENSITIVE_ASSIGNMENT_LABEL})"
    r"\s*[:=]\s*(?:[\"'])?([^\s,;|\"']{4,})(?:[\"'])?"
)
SECRET_CLI_FLAG_RE = re.compile(
    rf"(?i)(--(?:{SENSITIVE_ASSIGNMENT_LABEL})(?:=|\s+))"
    r"(?:[\"'])?([^\s,;|\"']{4,})(?:[\"'])?"
)
PRIVATE_KEY_BLOCK_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?"
    r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.DOTALL,
)
ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,}$")
REDIS_KEY_RE = re.compile(
    r"^(?:v2:|features:|feature:|market:|prediction:|predictions:|signal:|signals:|"
    r"trainer:|paper:|live:|risk:|portfolio:|position:|positions:|execution:|"
    r"orchestrator:|audit:|health:|heartbeat:|liq:|liquidation:|liquidations:|"
    r"microstructure:|altdata:|provider:|config:|decision:|decisions:|model:|"
    r"checkpoint:|redis:|stream:|ledger:|fills?:|orders?:)",
    re.IGNORECASE,
)
TEMPORAL_FIELDS = {
    "event_time",
    "ingested_at",
    "available_at",
    "generated_at",
    "feature_cutoff",
    "decision_time",
    "execution_time",
}
REDIS_READ_METHODS = {
    "get",
    "mget",
    "hget",
    "hgetall",
    "hmget",
    "xread",
    "xreadgroup",
    "xrange",
    "xrevrange",
    "xlen",
    "lrange",
    "smembers",
    "zrange",
    "zrevrange",
    "exists",
    "ttl",
    "pttl",
    "scan",
    "scan_iter",
    "keys",
    "subscribe",
}
REDIS_WRITE_METHODS = {
    "set",
    "setex",
    "psetex",
    "mset",
    "hset",
    "hmset",
    "xadd",
    "xdel",
    "xtrim",
    "lpush",
    "rpush",
    "sadd",
    "zadd",
    "publish",
    "delete",
    "unlink",
    "expire",
    "pexpire",
    "incr",
    "incrby",
    "decr",
    "decrby",
    "hincrby",
    "flushdb",
    "flushall",
}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "websocket"}
EXCHANGE_MUTATION_METHODS = {
    "create_order",
    "futures_create_order",
    "new_order",
    "place_order",
    "submit_order",
    "cancel_order",
    "cancel_all_orders",
    "futures_cancel_order",
    "change_leverage",
    "futures_change_leverage",
    "set_leverage",
    "change_margin_type",
    "futures_change_margin_type",
    "set_margin_mode",
    "withdraw",
    "transfer",
}
NETWORK_CALLS = {
    "requests.get",
    "requests.post",
    "requests.put",
    "requests.patch",
    "requests.delete",
    "httpx.get",
    "httpx.post",
    "client.get",
    "client.post",
    "session.get",
    "session.post",
    "urlopen",
    "websockets.connect",
}
FILE_WRITE_CALLS = {
    "write",
    "write_text",
    "write_bytes",
    "dump",
    "save",
    "savez",
    "savez_compressed",
    "replace",
    "rename",
    "unlink",
    "mkdir",
}
SUBPROCESS_CALLS = {
    "subprocess.run",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "os.system",
    "os.execv",
    "os.execve",
}
DB_WRITE_METHODS = {"add", "add_all", "commit", "flush", "execute", "delete", "merge", "bulk_save_objects"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_text(value: str | None, *, limit: int | None = None) -> str | None:
    """Remove credential-shaped values while retaining dependency-bearing text."""

    if value is None:
        return None
    rendered = PRIVATE_KEY_BLOCK_RE.sub("<redacted-private-key>", str(value))
    rendered = URI_USERINFO_RE.sub(lambda match: f"{match.group('scheme')}<redacted-userinfo>@", rendered)
    for pattern in SECRET_VALUE_PATTERNS:
        rendered = pattern.sub("<redacted-secret-like-value>", rendered)

    def redact_assignment(match: re.Match[str]) -> str:
        candidate = match.group(2)
        if candidate.startswith(("<redacted", "${", "{", "$")):
            return match.group(0)
        return f"{match.group(1)}=<redacted>"

    rendered = SECRET_ASSIGNMENT_RE.sub(redact_assignment, rendered)
    rendered = SECRET_CLI_FLAG_RE.sub(lambda match: f"{match.group(1)}<redacted>", rendered)
    if limit is not None and len(rendered) > limit:
        rendered = rendered[:limit] + "…"
    return rendered


SAFE_SENSITIVE_SENTINELS = {
    "",
    "<redacted>",
    "[redacted]",
    "any",
    "boolean",
    "false",
    "missing",
    "never",
    "none",
    "null",
    "number",
    "object",
    "present",
    "redacted",
    "string",
    "true",
    "undefined",
    "unknown",
    "void",
}
RECORD_DISCRIMINATOR_KEYS = {"name", "key", "field", "property", "label"}
RECORD_VALUE_KEYS = {"default", "initializer", "literal", "value", "values"}


def is_sensitive_label(value: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value))
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", normalized).strip("_").lower()
    return bool(SENSITIVE_KEY_RE.search(normalized))


def json_safe_value(
    value: Any,
    *,
    key_hint: str = "",
    sensitive_context: bool = False,
) -> Any:
    """Normalize arbitrary literals and sanitize every JSON serialization edge."""

    sensitive_context = sensitive_context or is_sensitive_label(key_hint)
    if isinstance(value, str):
        if sensitive_context and value.strip().lower() not in SAFE_SENSITIVE_SENTINELS:
            return "<redacted>"
        return sanitize_text(value)
    if value is None or isinstance(value, bool):
        return value
    if sensitive_context and not isinstance(value, (Mapping, list, tuple, set, frozenset)):
        return "<redacted>"
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        if math.isnan(value):
            rendered_float = "nan"
        else:
            rendered_float = "positive_infinity" if value > 0 else "negative_infinity"
        return {"type": "float", "value": rendered_float}
    if isinstance(value, bytes):
        return {"type": "bytes", "length": len(value), "value": "<redacted-binary>"}
    if isinstance(value, complex):
        return {
            "type": "complex",
            "real": json_safe_value(value.real),
            "imag": json_safe_value(value.imag),
        }
    if value is Ellipsis:
        return {"type": "ellipsis"}
    if isinstance(value, Mapping):
        record_contains_sensitive_value = any(
            isinstance(child, str) and is_sensitive_label(child)
            for key, child in value.items()
            if str(key).lower() in RECORD_DISCRIMINATOR_KEYS
        )
        output: dict[str, Any] = {}
        used_keys: set[str] = set()
        for key, child in value.items():
            raw_key = str(key)
            base_key = sanitize_text(raw_key) or "<empty-key>"
            key_contains_secret_shape = base_key != raw_key
            safe_key = base_key
            suffix = 2
            while safe_key in used_keys:
                safe_key = f"{base_key}#sanitized-collision-{suffix}"
                suffix += 1
            used_keys.add(safe_key)
            output[safe_key] = json_safe_value(
                child,
                key_hint=str(key),
                sensitive_context=(
                    sensitive_context and str(key).lower() not in RECORD_DISCRIMINATOR_KEYS
                )
                or key_contains_secret_shape
                or (
                    record_contains_sensitive_value
                    and str(key).lower() in RECORD_VALUE_KEYS
                ),
            )
        return output
    if isinstance(value, (list, tuple)):
        return [json_safe_value(child, sensitive_context=sensitive_context) for child in value]
    if isinstance(value, (set, frozenset)):
        normalized = [json_safe_value(child, sensitive_context=sensitive_context) for child in value]
        return {"type": type(value).__name__, "items": sorted(normalized, key=lambda item: repr(item))}
    return {"type": type(value).__name__, "representation": sanitize_text(repr(value), limit=300)}


def contains_secret_shape(value: Any) -> bool:
    """Return true when a strong credential value survives output sanitization."""

    if isinstance(value, str):
        if URI_USERINFO_RE.search(value) or PRIVATE_KEY_BLOCK_RE.search(value):
            return True
        return any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS)
    if isinstance(value, Mapping):
        return any(contains_secret_shape(key) or contains_secret_shape(child) for key, child in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(contains_secret_shape(child) for child in value)
    return False


def run_git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=repo)


def tracked_paths(repo: Path) -> list[str]:
    raw = run_git(repo, "ls-files", "-z")
    return sorted(p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p)


def worktree_status(
    repo: Path,
    *,
    excluded_prefix: str = "",
    additional_excluded_prefixes: Sequence[str] = (),
) -> list[str]:
    """Capture tracked and untracked path state, excluding this generator's outputs."""

    lines = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all").decode(
        "utf-8", errors="replace"
    ).splitlines()
    excluded_prefixes = tuple(
        prefix
        for prefix in (excluded_prefix, *additional_excluded_prefixes)
        if prefix
    )
    if not excluded_prefixes:
        return lines
    kept = []
    for line in lines:
        status_path = line[3:].strip('"') if len(line) > 3 else ""
        if any(status_path.startswith(prefix) for prefix in excluded_prefixes):
            continue
        kept.append(line)
    return kept


def is_secret_path(path: str) -> bool:
    parts = {p.lower() for p in Path(path).parts}
    path_obj = Path(path)
    name = path_obj.name
    if parts & SECRET_PATH_PARTS:
        return True
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return True
    if name.lower() in {"auth_users.json", "auth_revocations.json", "trader_accounts.json"}:
        return True
    # Source files whose names describe credential/secret handling are code and
    # must remain in the dependency atlas.  Secret-like non-code artifacts are
    # excluded because audit reports can themselves contain captured values.
    if path_obj.suffix.lower() in CODE_SUFFIXES:
        return False
    return bool(SECRET_NAME_RE.search(name))


def language_for(path: str) -> str:
    p = Path(path)
    if p.name == "Makefile" or p.suffix == ".mk":
        return "make"
    if p.name.lower().startswith("dockerfile"):
        return "dockerfile"
    return CODE_SUFFIXES.get(p.suffix.lower(), CONFIG_SUFFIXES.get(p.suffix.lower(), "other"))


def stratum_for(path: str) -> str:
    p = path.replace("\\", "/")
    low = p.lower()
    if "/tests/" in f"/{low}/" or Path(low).name.startswith("test_") or low.endswith(".spec.ts"):
        return "test"
    if low.startswith("v2/legacy_preserved/"):
        return "preserved_legacy_source"
    if low.startswith("legacy_reference/"):
        return "raw_legacy_reference"
    if low.startswith("v2/backend/app/"):
        if "/api/" in low:
            return "backend_api"
        if "/cli/" in low:
            return "backend_cli"
        if "/services/" in low:
            return "backend_service"
        if "/domain/" in low:
            return "backend_domain"
        if "/adapters/" in low:
            return "backend_adapter"
        if "/composition/" in low:
            return "backend_composition"
        return "backend_core"
    if low.startswith("v2/frontend/src/"):
        return "web_frontend"
    if low.startswith("v2/frontend/tests/"):
        return "web_test"
    if low.startswith("v2/mobile/sources/"):
        return "mobile"
    if low.startswith("v2/mobile/tests/"):
        return "mobile_test"
    if low.startswith("claude_worklog/systemd/") or "/systemd/" in low or low.endswith((".service", ".timer", ".socket")):
        return "service_definition"
    if low.startswith(("tools/", "scripts/", "v2/scripts/", "v2/tools/", "claude_worklog/tools/")):
        return "operational_tooling"
    if low.startswith("docs/") or low.startswith("v2/docs/") or low.endswith(".md"):
        return "documentation"
    if low.startswith(("claude_worklog/", "raw_evidence/", "goal_state/", "artifacts/")):
        return "evidence_or_runtime_artifact"
    if language_for(path) in set(CONFIG_SUFFIXES.values()) | {"make", "dockerfile"}:
        return "configuration"
    return "repository_support"


def safe_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def json_write(path: Path, value: Any, *, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = json_safe_value(value)
    if contains_secret_shape(value):
        raise ValueError(f"secret-shaped value survived atlas sanitization for {path.name}")
    if pretty:
        rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    else:
        rendered = json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
    path.write_text(rendered + "\n", encoding="utf-8")


def markdown_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = sanitize_text(text) or ""
    if contains_secret_shape(rendered):
        raise ValueError(f"secret-shaped value survived atlas sanitization for {path.name}")
    path.write_text(rendered.rstrip() + "\n", encoding="utf-8")


def revalidate_tracked_inputs(
    repo: Path,
    expected_paths: Sequence[str],
    regular_hashes: Mapping[str, str],
    symlink_targets: Mapping[str, str],
    nonregular_states: Mapping[str, str],
) -> dict[str, Any]:
    """Prove that every content-bearing worktree input stayed unchanged."""

    current_paths = tracked_paths(repo)
    changed: list[dict[str, Any]] = []
    for rel, expected_hash in regular_hashes.items():
        absolute = repo / rel
        try:
            mode = absolute.lstat().st_mode
        except FileNotFoundError:
            changed.append({"path": rel, "reason": "missing_at_end"})
            continue
        if not stat.S_ISREG(mode):
            changed.append({"path": rel, "reason": "type_changed_from_regular"})
            continue
        if sha256_bytes(absolute.read_bytes()) != expected_hash:
            changed.append({"path": rel, "reason": "content_hash_changed"})
    for rel, target in symlink_targets.items():
        absolute = repo / rel
        if not absolute.is_symlink():
            changed.append({"path": rel, "reason": "type_changed_from_symlink"})
        elif os.readlink(absolute) != target:
            changed.append({"path": rel, "reason": "symlink_target_changed"})
    for rel, expected_state in nonregular_states.items():
        absolute = repo / rel
        try:
            mode = absolute.lstat().st_mode
            current_state = f"mode:{stat.S_IFMT(mode):o}"
        except FileNotFoundError:
            current_state = "missing"
        if current_state != expected_state:
            changed.append({"path": rel, "reason": f"state_changed:{expected_state}->{current_state}"})
    return {
        "tracked_path_list_unchanged": list(expected_paths) == current_paths,
        "tracked_path_count_start": len(expected_paths),
        "tracked_path_count_end": len(current_paths),
        "changed_inputs": changed,
        "content_inputs_unchanged": not changed and list(expected_paths) == current_paths,
    }


def publish_staged_atlas(
    staging: Path,
    destination: Path,
    *,
    replace: Any = os.replace,
) -> None:
    """Swap a complete atlas directory into place and roll back on failure.

    ``staging`` must be on the same filesystem as ``destination``. A reader can
    briefly observe a missing destination between the two directory renames,
    but can never observe a mixed generation. The prior generation is restored
    if the second rename raises.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}-rollback-",
            dir=destination.parent,
        )
    )
    backup.rmdir()
    had_destination = destination.exists()
    preserve_backup = False
    try:
        if had_destination:
            replace(destination, backup)
        try:
            replace(staging, destination)
        except BaseException as promotion_error:
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            if had_destination and backup.exists():
                try:
                    replace(backup, destination)
                except BaseException as restore_error:
                    preserve_backup = True
                    raise RuntimeError(
                        "Atlas promotion and rollback both failed; the prior "
                        f"generation is preserved for manual recovery at {backup}. "
                        f"Promotion error: {type(promotion_error).__name__}: "
                        f"{promotion_error}."
                    ) from restore_error
            raise
    finally:
        if backup.exists() and not preserve_backup:
            shutil.rmtree(backup, ignore_errors=True)


def rendered_expr(node: ast.AST | None, *, limit: int = 500) -> str | None:
    if node is None:
        return None
    try:
        value = ast.unparse(node)
    except Exception:
        return None
    value = " ".join(value.split())
    return sanitize_text(value, limit=limit)


def ast_source_span(node: ast.AST) -> dict[str, int]:
    """Return a stable, JSON-safe CPython AST source span."""

    line = int(getattr(node, "lineno", 1) or 1)
    column = int(getattr(node, "col_offset", 0) or 0)
    return {
        "line": line,
        "column": column,
        "end_line": int(getattr(node, "end_lineno", line) or line),
        "end_column": int(getattr(node, "end_col_offset", column) or column),
    }


def dotted_name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = dotted_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    return rendered_expr(node, limit=200) or ""


def literal_string(node: ast.AST | None, constants: Mapping[str, str] | None = None) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{" + (rendered_expr(value.value, limit=120) or "expr") + "}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = literal_string(node.left, constants)
        right = literal_string(node.right, constants)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.Name) and constants and node.id in constants:
        return constants[node.id]
    return None


def safe_default(node: ast.AST | None, constants: Mapping[str, str] | None = None) -> Any:
    if node is None:
        return {"state": "no_explicit_default"}
    value: Any
    try:
        value = ast.literal_eval(node)
    except Exception:
        value = rendered_expr(node, limit=300)
    text = str(value)
    if contains_secret_shape(text):
        return {"state": "expression_redacted"}
    return {"state": "default_present", "value": json_safe_value(value)}


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    def render_arg(arg: ast.arg, prefix: str = "") -> str:
        annotation = f": {rendered_expr(arg.annotation)}" if arg.annotation is not None else ""
        return f"{prefix}{arg.arg}{annotation}"

    def render_default(arg: ast.arg, default: ast.AST) -> str:
        if is_sensitive_label(arg.arg):
            return "<default:redacted>"
        rendered = rendered_expr(default, limit=300)
        if rendered is None:
            return "<default:unavailable>"
        return rendered

    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {rendered_expr(node.returns)}" if node.returns is not None else ""
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults_start = len(positional) - len(args.defaults)
    pieces: list[str] = []
    for index, arg in enumerate(positional):
        rendered = render_arg(arg)
        if index >= defaults_start:
            rendered += f"={render_default(arg, args.defaults[index - defaults_start])}"
        pieces.append(rendered)
        if args.posonlyargs and index + 1 == len(args.posonlyargs):
            pieces.append("/")
    if args.vararg is not None:
        pieces.append(render_arg(args.vararg, "*"))
    elif args.kwonlyargs:
        pieces.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        rendered = render_arg(arg)
        if default is not None:
            rendered += f"={render_default(arg, default)}"
        pieces.append(rendered)
    if args.kwarg is not None:
        pieces.append(render_arg(args.kwarg, "**"))
    return f"{prefix} {node.name}({', '.join(pieces)}){returns}"


def module_name_for_path(path: str) -> str | None:
    p = Path(path)
    if p.suffix != ".py":
        return None
    parts = list(p.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def module_aliases(path: str) -> set[str]:
    module = module_name_for_path(path)
    if not module:
        return set()
    aliases = {module}
    if module.startswith("v2.backend."):
        aliases.add(module.removeprefix("v2.backend."))
    if module.startswith("v2."):
        aliases.add(module.removeprefix("v2."))
    return aliases


def resolve_relative_import(
    current_module: str,
    level: int,
    imported: str | None,
    *,
    current_is_package: bool = False,
) -> str:
    if level == 0:
        return imported or ""
    parts = current_module.split(".")
    if parts and not current_is_package:
        parts = parts[:-1]
    if level:
        drop = max(0, level - 1)
        if drop:
            parts = parts[:-drop] if drop <= len(parts) else []
    if imported:
        parts.extend(imported.split("."))
    return ".".join(parts)


@dataclass
class SymbolState:
    symbol_id: str
    path: str
    qualname: str
    kind: str
    line_start: int
    line_end: int
    signature: str | None = None
    decorators: list[str] = field(default_factory=list)
    doc: str | None = None
    calls: set[str] = field(default_factory=set)
    raises: set[str] = field(default_factory=set)
    exception_handlers: set[str] = field(default_factory=set)
    side_effects: set[str] = field(default_factory=set)
    redis_reads: set[str] = field(default_factory=set)
    redis_writes: set[str] = field(default_factory=set)
    redis_unknown_or_declarations: set[str] = field(default_factory=set)
    env_reads: set[str] = field(default_factory=set)
    data_reads: set[str] = field(default_factory=set)
    data_writes: set[str] = field(default_factory=set)
    temporal_fields: set[str] = field(default_factory=set)
    exchange_mutations: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol_id": self.symbol_id,
            "path": self.path,
            "qualname": self.qualname,
            "kind": self.kind,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "signature": self.signature,
            "decorators": sorted(self.decorators),
            "doc": self.doc,
            "calls_raw": sorted(self.calls),
            "raises": sorted(self.raises),
            "exception_handlers": sorted(self.exception_handlers),
            "side_effects": sorted(self.side_effects),
            "redis_reads": sorted(self.redis_reads),
            "redis_writes": sorted(self.redis_writes),
            "redis_unknown_or_declarations": sorted(self.redis_unknown_or_declarations),
            "env_reads": sorted(self.env_reads),
            "data_fields_read": sorted(self.data_reads),
            "data_fields_written": sorted(self.data_writes),
            "temporal_fields": sorted(self.temporal_fields),
            "exchange_mutations": sorted(self.exchange_mutations),
        }


class PythonAtlasVisitor(ast.NodeVisitor):
    """Collect nested symbols, contracts, calls, keys, fields, and side effects."""

    def __init__(self, path: str, source: str, tree: ast.Module) -> None:
        self.path = path
        self.source = source
        self.tree = tree
        self.module_name = module_name_for_path(path) or path
        self.is_package_module = Path(path).name == "__init__.py"
        self.scope: list[str] = []
        self.class_scope: list[str] = []
        self.symbol_stack: list[SymbolState] = []
        self.symbols: list[SymbolState] = []
        self.imports: list[dict[str, Any]] = []
        self.import_aliases: dict[str, dict[str, str | None]] = {}
        self.constants: dict[str, str] = {}
        self.constant_records: list[dict[str, Any]] = []
        self.contracts: list[dict[str, Any]] = []
        self.api_routes: list[dict[str, Any]] = []
        self.env_refs: list[dict[str, Any]] = []
        self.redis_ops: list[dict[str, Any]] = []
        self.exchange_refs: list[dict[str, Any]] = []
        self.data_field_reads: list[dict[str, Any]] = []
        self.data_field_writes: list[dict[str, Any]] = []
        self.redis_operational_nodes: set[int] = set()
        self.module_symbol = SymbolState(
            symbol_id=f"{path}:<module>",
            path=path,
            qualname="<module>",
            kind="module",
            line_start=1,
            line_end=max(1, line_count(source)),
        )
        self.symbols.append(self.module_symbol)
        self._collect_constants()

    def _record_redis_reference(
        self,
        key: str,
        node: ast.AST,
        *,
        operation: str,
        access: str,
        client_expression: str = "",
    ) -> None:
        if not REDIS_KEY_RE.match(key):
            return
        item = {
            "key_pattern": key,
            "operation": operation,
            "access": access,
            "path": self.path,
            **ast_source_span(node),
            "symbol_id": self.current_symbol_id,
            "client_expression": client_expression,
        }
        self.redis_ops.append(item)
        if access == "write":
            self.current.redis_writes.add(key)
            self.current.side_effects.add("redis_write")
        elif access == "read":
            self.current.redis_reads.add(key)
        else:
            self.current.redis_unknown_or_declarations.add(key)

    @property
    def current(self) -> SymbolState:
        return self.symbol_stack[-1] if self.symbol_stack else self.module_symbol

    @property
    def current_symbol_id(self) -> str:
        return self.current.symbol_id

    def _collect_constants(self) -> None:
        for node in self.tree.body:
            targets: list[ast.expr] = []
            value: ast.AST | None = None
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            if value is None:
                continue
            text_value = literal_string(value, self.constants)
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    if text_value is not None:
                        self.constants[target.id] = text_value
                    self.constant_records.append(
                        {
                            "path": self.path,
                            "name": target.id,
                            "line": getattr(node, "lineno", 1),
                            "value_kind": type(value).__name__,
                            "value": "<redacted>"
                            if is_sensitive_label(target.id)
                            else (text_value if text_value is not None and len(text_value) <= 300 else None),
                            "expression": "<redacted>"
                            if is_sensitive_label(target.id)
                            else rendered_expr(value),
                        }
                    )

    def _record_data_read(self, field_name: str, node: ast.AST, access: str) -> None:
        if not field_name or len(field_name) > 200:
            return
        self.current.data_reads.add(field_name)
        if field_name in TEMPORAL_FIELDS:
            self.current.temporal_fields.add(field_name)
        self.data_field_reads.append(
            {
                "field": field_name,
                "path": self.path,
                **ast_source_span(node),
                "symbol_id": self.current_symbol_id,
                "access": access,
            }
        )

    def _record_data_write(self, field_name: str, node: ast.AST, access: str) -> None:
        if not field_name or len(field_name) > 200:
            return
        self.current.data_writes.add(field_name)
        if field_name in TEMPORAL_FIELDS:
            self.current.temporal_fields.add(field_name)
        self.data_field_writes.append(
            {
                "field": field_name,
                "path": self.path,
                **ast_source_span(node),
                "symbol_id": self.current_symbol_id,
                "access": access,
            }
        )

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.imports.append(
                {"module": alias.name, "name": None, "alias": alias.asname, "line": node.lineno, "level": 0}
            )
            self.import_aliases[local] = {"module": alias.name, "name": None}
        return self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        module = resolve_relative_import(
            self.module_name,
            node.level,
            node.module,
            current_is_package=self.is_package_module,
        )
        for alias in node.names:
            local = alias.asname or alias.name
            self.imports.append(
                {
                    "module": module,
                    "name": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                    "level": node.level,
                }
            )
            self.import_aliases[local] = {"module": module, "name": alias.name}
        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        qualname = ".".join([*self.scope, node.name])
        bases = [dotted_name(base) for base in node.bases]
        decorators = [dotted_name(dec) for dec in node.decorator_list]
        symbol = SymbolState(
            symbol_id=f"{self.path}:{qualname}@{node.lineno}",
            path=self.path,
            qualname=qualname,
            kind="class",
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            signature=f"class {node.name}({', '.join(bases)})",
            decorators=decorators,
            doc=(ast.get_docstring(node, clean=True) or "").split("\n", 1)[0][:500] or None,
        )
        self.symbols.append(symbol)
        is_contract = any(
            token in base
            for base in bases
            for token in ("BaseModel", "TypedDict", "Base", "DeclarativeBase", "Protocol", "Enum")
        ) or any("dataclass" in dec for dec in decorators)
        if is_contract:
            fields: list[dict[str, Any]] = []
            for child in node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    fields.append(
                        {
                            "name": child.target.id,
                            "annotation": rendered_expr(child.annotation),
                            "default": {"state": "redacted_sensitive_field"}
                            if is_sensitive_label(child.target.id)
                            else safe_default(child.value),
                            **ast_source_span(child.target),
                        }
                    )
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and not target.id.startswith("_"):
                            fields.append(
                                {
                                    "name": target.id,
                                    "annotation": None,
                                    "default": {"state": "redacted_sensitive_field"}
                                    if is_sensitive_label(target.id)
                                    else safe_default(child.value),
                                    **ast_source_span(target),
                                }
                            )
            self.contracts.append(
                {
                    "contract_id": symbol.symbol_id,
                    "path": self.path,
                    "name": qualname,
                    "kind": "python_class_contract",
                    "bases": bases,
                    "decorators": decorators,
                    "fields": fields,
                    "line_start": node.lineno,
                    "line_end": getattr(node, "end_lineno", node.lineno),
                }
            )
            for item in fields:
                symbol.data_writes.add(item["name"])
                if item["name"] in TEMPORAL_FIELDS:
                    symbol.temporal_fields.add(item["name"])
        self.scope.append(node.name)
        self.class_scope.append(node.name)
        self.symbol_stack.append(symbol)
        self.generic_visit(node)
        self.symbol_stack.pop()
        self.class_scope.pop()
        self.scope.pop()
        return None

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualname = ".".join([*self.scope, node.name])
        kind = "method" if self.class_scope else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
        symbol = SymbolState(
            symbol_id=f"{self.path}:{qualname}@{node.lineno}",
            path=self.path,
            qualname=qualname,
            kind=kind,
            line_start=node.lineno,
            line_end=getattr(node, "end_lineno", node.lineno),
            signature=function_signature(node),
            decorators=[dotted_name(dec) for dec in node.decorator_list],
            doc=(ast.get_docstring(node, clean=True) or "").split("\n", 1)[0][:500] or None,
        )
        self.symbols.append(symbol)
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            method = dotted_name(dec.func).split(".")[-1].lower()
            route = literal_string(dec.args[0], self.constants) if dec.args else None
            if method in HTTP_METHODS and route:
                self.api_routes.append(
                    {
                        "path": route,
                        "method": method.upper(),
                        "handler_symbol_id": symbol.symbol_id,
                        "source_path": self.path,
                        **ast_source_span(dec),
                        "decorator": dotted_name(dec.func),
                    }
                )
        self.scope.append(node.name)
        self.symbol_stack.append(symbol)
        self.generic_visit(node)
        self.symbol_stack.pop()
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._visit_function(node)
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._visit_function(node)
        return None

    def visit_Raise(self, node: ast.Raise) -> Any:
        if node.exc is not None:
            self.current.raises.add(dotted_name(node.exc) or type(node.exc).__name__)
        return self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Any:
        self.current.exception_handlers.add(dotted_name(node.type) or "bare_except")
        return self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> Any:
        for key in node.keys:
            value = literal_string(key, self.constants)
            if value is not None:
                self._record_data_write(value, node, "dict_literal")
        return self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if id(node) not in self.redis_operational_nodes and isinstance(node.value, str) and REDIS_KEY_RE.match(node.value):
            self._record_redis_reference(
                node.value,
                node,
                operation="literal_reference",
                access="declared_unknown",
            )
        return self.generic_visit(node)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> Any:
        key = literal_string(node, self.constants)
        if id(node) not in self.redis_operational_nodes and key and REDIS_KEY_RE.match(key):
            self._record_redis_reference(
                key,
                node,
                operation="formatted_literal_reference",
                access="declared_unknown",
            )
            # Avoid separately recording only the static fragments of the same
            # f-string; formatted values still need normal traversal for calls.
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    self.visit(value.value)
            return None
        return self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        value = literal_string(node.slice, self.constants)
        if value is not None and dotted_name(node.value) == "os.environ":
            self._record_env(value, node, None)
        elif value is not None and not REDIS_KEY_RE.match(value):
            if isinstance(node.ctx, ast.Store):
                self._record_data_write(value, node, "subscript_store")
            else:
                self._record_data_read(value, node, "subscript_read")
        return self.generic_visit(node)

    def _record_env(self, key: str, node: ast.Call | ast.Subscript, default: ast.AST | None) -> None:
        if not ENV_KEY_RE.match(key):
            return
        item = {
            "key": key,
            "path": self.path,
            **ast_source_span(node),
            "symbol_id": self.current_symbol_id,
            "default": {"state": "redacted"} if is_sensitive_label(key) else safe_default(default),
        }
        self.env_refs.append(item)
        self.current.env_reads.add(key)

    def visit_Call(self, node: ast.Call) -> Any:
        call = dotted_name(node.func)
        if call:
            self.current.calls.add(call)
        short = call.split(".")[-1]

        if call in SUBPROCESS_CALLS:
            self.current.side_effects.add("subprocess")
        if call in NETWORK_CALLS or any(token in call.lower() for token in ("websocket", "httpclient", "asyncclient")):
            self.current.side_effects.add("network")
        if short in FILE_WRITE_CALLS and any(token in call.lower() for token in ("path", "file", "json", "torch", "numpy", "np.")):
            self.current.side_effects.add("filesystem_write")
        if short in DB_WRITE_METHODS and any(token in call.lower() for token in ("session", "repo", "repository", "db", "database")):
            self.current.side_effects.add("database_write")
        if short in EXCHANGE_MUTATION_METHODS:
            self.current.side_effects.add("exchange_mutation_reference")
            self.current.exchange_mutations.add(short)
            self.exchange_refs.append(
                {
                    "operation": short,
                    "path": self.path,
                    **ast_source_span(node),
                    "symbol_id": self.current_symbol_id,
                    "call": call,
                }
            )

        env_target = call in {"os.getenv", "os.environ.get"}
        if env_target and node.args:
            key = literal_string(node.args[0], self.constants)
            if key:
                default = node.args[1] if len(node.args) > 1 else None
                self._record_env(key, node, default)

        redis_access: str | None = None
        if short in REDIS_WRITE_METHODS:
            redis_access = "write"
        elif short in REDIS_READ_METHODS:
            redis_access = "read"
        else:
            call_lower = call.lower()
            if "redis" in call_lower or short.startswith(("_redis_", "redis_")):
                if any(token in short.lower() for token in ("set", "write", "publish", "push", "add", "delete", "expire", "update")):
                    redis_access = "write"
                elif any(token in short.lower() for token in ("get", "read", "scan", "load", "fetch", "exists", "ttl")):
                    redis_access = "read"
                else:
                    redis_access = "unknown"
        if redis_access and node.args:
            key_args = [(arg, literal_string(arg, self.constants)) for arg in node.args[:3]]
            for arg, key in key_args:
                if key and REDIS_KEY_RE.match(key):
                    self.redis_operational_nodes.add(id(arg))
                    self._record_redis_reference(
                        key,
                        node,
                        operation=short,
                        access=redis_access,
                        client_expression=dotted_name(getattr(node.func, "value", None)),
                    )

        if short == "get" and node.args:
            receiver = dotted_name(getattr(node.func, "value", None))
            key = literal_string(node.args[0], self.constants)
            if key and receiver not in {"os.environ"} and not REDIS_KEY_RE.match(key):
                self._record_data_read(key, node, "mapping_get")

        return self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> Any:
        for target in node.targets:
            if isinstance(target, ast.Subscript):
                key = literal_string(target.slice, self.constants)
                if key and not REDIS_KEY_RE.match(key):
                    self._record_data_write(key, target, "assignment")
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> Any:
        if isinstance(node.target, ast.Subscript):
            key = literal_string(node.target.slice, self.constants)
            if key and not REDIS_KEY_RE.match(key):
                self._record_data_write(key, node.target, "annotated_assignment")
        return self.generic_visit(node)


def parse_python(path: str, text: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError, RecursionError) as exc:
        return {
            "path": path,
            "parse_status": "error",
            "parse_error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "line": getattr(exc, "lineno", None),
            },
            "symbols": [],
            "imports": [],
            "import_aliases": {},
            "constants": [],
            "contracts": [],
            "api_routes": [],
            "env_refs": [],
            "redis_ops": [],
            "exchange_refs": [],
            "data_field_reads": [],
            "data_field_writes": [],
            "has_main_guard": False,
        }
    visitor = PythonAtlasVisitor(path, text, tree)
    visitor.visit(tree)
    return {
        "path": path,
        "parse_status": "ok",
        "parse_error": None,
        "symbols": [symbol.as_dict() for symbol in visitor.symbols],
        "imports": visitor.imports,
        "import_aliases": visitor.import_aliases,
        "constants": visitor.constant_records,
        "contracts": visitor.contracts,
        "api_routes": visitor.api_routes,
        "env_refs": visitor.env_refs,
        "redis_ops": visitor.redis_ops,
        "exchange_refs": visitor.exchange_refs,
        "data_field_reads": visitor.data_field_reads,
        "data_field_writes": visitor.data_field_writes,
        "has_main_guard": "if __name__" in text and "__main__" in text,
    }


SWIFT_TYPE_RE = re.compile(r"^\s*(?:public\s+|private\s+|internal\s+|fileprivate\s+|open\s+)*(?:final\s+)?(struct|class|enum|protocol|actor|extension)\s+([A-Za-z_][A-Za-z0-9_.]*)")
SWIFT_FUNC_RE = re.compile(r"^\s*(?:@[A-Za-z0-9_().,\s]+\s+)*(?:public\s+|private\s+|internal\s+|fileprivate\s+|open\s+|static\s+|class\s+|mutating\s+|nonmutating\s+|override\s+|convenience\s+)*(func|init|deinit|subscript)\s*([A-Za-z_][A-Za-z0-9_]*)?")
SWIFT_FIELD_RE = re.compile(r"^\s*(?:@[A-Za-z0-9_().,\s]+\s+)*(?:public\s+|private\s+|internal\s+|fileprivate\s+|static\s+|let\s+|var\s+)+(?:let|var)?\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^={]+)")


def parse_swift(path: str, text: str) -> dict[str, Any]:
    symbols: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    imports: list[dict[str, Any]] = []
    type_stack: list[tuple[str, int]] = []
    brace_depth = 0
    current_contract: dict[str, Any] | None = None
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("import "):
            imports.append(
                {
                    "module": stripped.split()[1],
                    "line": number,
                    "column": len(line) - len(line.lstrip()),
                    "end_line": number,
                    "end_column": len(line),
                }
            )
        type_match = SWIFT_TYPE_RE.match(line)
        if type_match:
            kind, name = type_match.groups()
            qualname = ".".join([*(item[0] for item in type_stack), name])
            symbols.append(
                {
                    "symbol_id": f"{path}:{qualname}@{number}",
                    "path": path,
                    "qualname": qualname,
                    "kind": f"swift_{kind}",
                    "line_start": number,
                    "line_end": number,
                    "column": type_match.start(),
                    "end_column": len(line),
                    "signature": stripped[:500],
                    "parser_confidence": "heuristic",
                }
            )
            type_stack.append((name, brace_depth + line.count("{") - line.count("}")))
            if kind in {"struct", "class", "enum", "protocol"}:
                current_contract = {
                    "contract_id": f"{path}:{qualname}@{number}",
                    "path": path,
                    "name": qualname,
                    "kind": f"swift_{kind}",
                    "fields": [],
                    "line_start": number,
                    "column": type_match.start(),
                    "parser_confidence": "heuristic",
                }
                contracts.append(current_contract)
        func_match = SWIFT_FUNC_RE.match(line)
        if func_match:
            kind, name = func_match.groups()
            local_name = name or kind
            qualname = ".".join([*(item[0] for item in type_stack), local_name])
            symbols.append(
                {
                    "symbol_id": f"{path}:{qualname}@{number}",
                    "path": path,
                    "qualname": qualname,
                    "kind": f"swift_{kind}",
                    "line_start": number,
                    "line_end": number,
                    "column": func_match.start(),
                    "end_column": len(line),
                    "signature": stripped[:500],
                    "parser_confidence": "heuristic",
                }
            )
        field_match = SWIFT_FIELD_RE.match(line)
        if field_match and current_contract:
            field_name, annotation = field_match.groups()
            current_contract["fields"].append(
                {
                    "name": field_name,
                    "annotation": annotation.strip()[:300],
                    "line": number,
                    "column": field_match.start(1),
                    "end_line": number,
                    "end_column": field_match.end(2),
                }
            )
        brace_depth += line.count("{") - line.count("}")
        while type_stack and brace_depth < type_stack[-1][1]:
            type_stack.pop()
            current_contract = contracts[-1] if type_stack and contracts else None
    for contract in contracts:
        contract["line_end"] = len(lines)
    api_refs = [
        {
            "path": match.group(0),
            "source_path": path,
            "line": i,
            "column": match.start(),
            "end_line": i,
            "end_column": match.end(),
            "kind": "swift_api_reference",
        }
        for i, line in enumerate(lines, start=1)
        for match in re.finditer(r"/api/(?:v1|v2)/[A-Za-z0-9_./{}?=&-]+", line)
    ]
    env_refs = [
        {"key": match.group(1), "path": path, "line": i, "symbol_id": None, "default": {"state": "unknown"}}
        for i, line in enumerate(lines, start=1)
        for match in re.finditer(r"environment\s*\[\s*[\"']([A-Z][A-Z0-9_]+)[\"']\s*\]", line)
    ]
    return {
        "path": path,
        "parse_status": "heuristic",
        "symbols": symbols,
        "contracts": contracts,
        "imports": imports,
        "api_refs": api_refs,
        "env_refs": env_refs,
    }


def aggregate_sites(rows: Iterable[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in rows:
        key = str(row.get(key_name, ""))
        if key:
            site = {k: v for k, v in row.items() if k != key_name}
            fingerprint = json.dumps(json_safe_value(site), sort_keys=True, ensure_ascii=False)
            grouped[key][fingerprint] = site
    return [
        {
            key_name: key,
            "sites": sorted(
                sites.values(),
                key=lambda item: (
                    str(item.get("path", "")),
                    int(item.get("line", 0)),
                    int(item.get("column", 0)),
                    str(item.get("operation", "")),
                    str(item.get("access", "")),
                ),
            ),
        }
        for key, sites in sorted(grouped.items())
    ]


def deduplicate_site_records(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate only records with identical complete, sanitized identity."""

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        fingerprint = json.dumps(
            json_safe_value(row),
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        unique[fingerprint] = row
    return list(unique.values())


def resolve_import_graph(python_modules: list[dict[str, Any]], known_paths: set[str]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    module_to_paths: dict[str, set[str]] = defaultdict(set)
    for path in sorted(known_paths):
        for alias in module_aliases(path):
            module_to_paths[alias].add(path)
    edges: list[dict[str, Any]] = []
    reverse: dict[str, set[str]] = defaultdict(set)
    for module in python_modules:
        source = module["path"]
        seen: set[tuple[str, str | None]] = set()
        for item in module.get("imports", []):
            imported_module = str(item.get("module") or "")
            imported_name = item.get("name")
            candidates = set(module_to_paths.get(imported_module, set()))
            if not candidates and imported_name:
                candidates.update(module_to_paths.get(f"{imported_module}.{imported_name}", set()))
            if not candidates:
                probe = imported_module
                while probe and not candidates:
                    candidates.update(module_to_paths.get(probe, set()))
                    probe = probe.rsplit(".", 1)[0] if "." in probe else ""
            target = next(iter(candidates)) if len(candidates) == 1 else None
            edge_key = (target or imported_module, imported_name)
            if edge_key in seen:
                continue
            seen.add(edge_key)
            edges.append(
                {
                    "from_path": source,
                    "to_path": target,
                    "external_module": None if target else imported_module,
                    "imported_name": imported_name,
                    "line": item.get("line"),
                    "resolved": target is not None,
                    "resolution_reason": "unique_module_alias" if target else ("ambiguous_module_alias" if candidates else "external_or_missing"),
                    "candidate_paths": sorted(candidates),
                }
            )
            if target:
                reverse[target].add(source)
    return sorted(edges, key=lambda x: (x["from_path"], str(x["to_path"]), str(x["external_module"]))), reverse


def resolve_python_calls(
    python_modules: list[dict[str, Any]], import_edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, set[str]], dict[str, set[str]]]:
    symbols_by_path: dict[str, list[dict[str, Any]]] = {
        module["path"]: module.get("symbols", []) for module in python_modules
    }
    by_path_simple: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    by_path_qualname: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path, symbols in symbols_by_path.items():
        for symbol in symbols:
            sid = symbol["symbol_id"]
            by_path_simple[path][symbol["qualname"].split(".")[-1]].append(sid)
            by_path_qualname[path][symbol["qualname"]].append(sid)
    imported_paths: dict[str, set[str]] = defaultdict(set)
    for edge in import_edges:
        if edge.get("to_path"):
            imported_paths[edge["from_path"]].add(edge["to_path"])
    edges: list[dict[str, Any]] = []
    callers: dict[str, set[str]] = defaultdict(set)
    callees: dict[str, set[str]] = defaultdict(set)
    for module in python_modules:
        path = module["path"]
        aliases = module.get("import_aliases", {})
        for symbol in module.get("symbols", []):
            caller = symbol["symbol_id"]
            class_prefix = symbol["qualname"].rsplit(".", 1)[0] if "." in symbol["qualname"] else ""
            for raw_call in symbol.get("calls_raw", []):
                target: str | None = None
                confidence = "unresolved"
                reason = "dynamic_or_external"
                pieces = raw_call.split(".")
                simple = pieces[-1]
                if raw_call.startswith(("self.", "cls.")) and class_prefix:
                    same_class = by_path_qualname[path].get(f"{class_prefix}.{simple}", [])
                    if len(same_class) == 1:
                        target, confidence, reason = same_class[0], "high", "same_class_method"
                if target is None and len(pieces) == 1 and len(by_path_simple[path].get(simple, [])) == 1:
                    target, confidence, reason = by_path_simple[path][simple][0], "high", "same_module_unique_unqualified_name"
                first = pieces[0]
                alias = aliases.get(first)
                if target is None and alias:
                    candidate_paths = [
                        imported
                        for imported in imported_paths[path]
                        if (module_name_for_path(imported) or "").endswith(str(alias.get("module") or ""))
                        or str(alias.get("module") or "").endswith(module_name_for_path(imported) or "")
                    ]
                    imported_name = str(alias.get("name") or (simple if len(pieces) > 1 else first))
                    possible = sorted({
                        sid
                        for candidate_path in candidate_paths
                        for sid in by_path_simple[candidate_path].get(imported_name if len(pieces) == 1 else simple, [])
                    })
                    if len(possible) == 1:
                        target, confidence, reason = possible[0], "medium", "import_alias_resolution"
                edge = {
                    "caller_symbol_id": caller,
                    "callee_symbol_id": target,
                    "raw_call": raw_call,
                    "confidence": confidence,
                    "resolution_reason": reason,
                }
                edges.append(edge)
                if target:
                    callers[target].add(caller)
                    callees[caller].add(target)
    return edges, callers, callees


def parse_systemd(path: str, text: str) -> dict[str, Any]:
    section = ""
    values: dict[str, list[dict[str, Any]]] = defaultdict(list)
    env_refs: list[dict[str, Any]] = []
    environment_files: list[dict[str, Any]] = []
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        rendered = value
        key_lower = key.lower()
        if key_lower == "environment":
            try:
                assignments = shlex.split(value, posix=True)
            except ValueError:
                assignments = [value]
            for assignment in assignments:
                if "=" not in assignment:
                    continue
                env_key = assignment.split("=", 1)[0]
                if ENV_KEY_RE.match(env_key):
                    env_refs.append(
                        {
                            "key": env_key,
                            "path": path,
                            "line": number,
                            "symbol_id": None,
                            "role": "systemd_definition",
                            "default": {"state": "defined_in_systemd_redacted"},
                        }
                    )
        elif key_lower == "environmentfile":
            environment_files.append({"line": number, "path_expression": sanitize_text(value, limit=500)})
        if key_lower.startswith("environment") or is_sensitive_label(key):
            if "=" in value:
                env_key = value.strip('"\'').split("=", 1)[0]
                rendered = f"{env_key}=<redacted>"
            else:
                rendered = "<redacted>"
        values[f"{section}.{key}"].append({"line": number, "value": rendered})
    return {
        "path": path,
        "kind": "systemd",
        "directives": dict(sorted(values.items())),
        "env_refs": env_refs,
        "environment_files": environment_files,
    }


def parse_makefile(path: str, text: str) -> dict[str, Any]:
    targets = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith(("\t", " ", "#")):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*:(?![=])", line)
        if match:
            targets.append({"target": match.group(1), "line": number})
    return {"path": path, "kind": "make", "targets": targets}


def parse_shell(path: str, text: str) -> dict[str, Any]:
    functions = []
    commands = []
    env_refs = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(\))?\s*\{", line)
        if match:
            functions.append(
                {
                    "symbol_id": f"{path}:{match.group(1)}@{number}",
                    "path": path,
                    "qualname": match.group(1),
                    "kind": "shell_function",
                    "line_start": number,
                    "line_end": number,
                    "signature": line.strip()[:300],
                    "parser_confidence": "heuristic",
                }
            )
        for key in re.findall(r"\$\{([A-Z][A-Z0-9_]+)(?::[-+?][^}]*)?\}|\$([A-Z][A-Z0-9_]+)", line):
            env_key = key[0] or key[1]
            env_refs.append({"key": env_key, "path": path, "line": number, "symbol_id": None, "default": {"state": "shell_expression"}})
        if re.search(r"\b(?:python3?|node|npm|systemctl|redis-cli|uvicorn|docker|swift)\b", line) and not line.lstrip().startswith("#"):
            commands.append({"line": number, "command": line.strip()[:800]})
    return {"path": path, "kind": "shell", "symbols": functions, "commands": commands, "env_refs": env_refs}


def flatten_json_config(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            yield from flatten_json_config(child, next_prefix)
    elif isinstance(value, list):
        yield prefix, {"type": "list", "length": len(value)}
    else:
        yield prefix, value


def parse_static_config(path: str, text: str, language: str) -> dict[str, Any] | None:
    if language == "json":
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        entries = []
        for key, value in flatten_json_config(parsed):
            if not key:
                continue
            if is_sensitive_label(key):
                rendered: Any = "<redacted>"
            elif isinstance(value, (str, int, float, bool)) or value is None:
                rendered = value if not isinstance(value, str) or len(value) <= 300 else value[:300] + "…"
            else:
                rendered = value
            entries.append({"key": key, "value": rendered, "value_type": type(value).__name__})
        return {"path": path, "kind": "json", "entries": entries}
    entries = []
    section = ""
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        section_match = re.match(r"^\[([^]]+)\]$", line)
        if section_match:
            section = section_match.group(1)
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_.-]*)\s*[:=]\s*(.+)$", line)
        if match:
            key, value = match.groups()
            dotted = f"{section}.{key}" if section else key
            entries.append(
                {
                    "key": dotted,
                    "line": number,
                    "value": "<redacted>" if is_sensitive_label(dotted) else value[:500],
                    "value_type": "text_expression",
                }
            )
    return {"path": path, "kind": language, "entries": entries}


def should_parse_static_config(path: str, stratum: str, language: str) -> bool:
    if language not in {"json", "toml", "yaml", "ini", "config"}:
        return False
    low = path.lower()
    if stratum in {"evidence_or_runtime_artifact", "documentation"}:
        return False
    return any(
        token in low
        for token in ("/config/", "package.json", "pyproject.toml", "docker-compose", "tsconfig", "playwright", "codemagic", ".github/workflows")
    )


def render_summary(
    metadata: dict[str, Any],
    file_manifest: list[dict[str, Any]],
    python_modules: list[dict[str, Any]],
    ts_atlas: dict[str, Any],
    swift_modules: list[dict[str, Any]],
    shell_modules: list[dict[str, Any]],
    import_edges: list[dict[str, Any]],
    call_edges: list[dict[str, Any]],
    contracts: list[dict[str, Any]],
    api_routes: list[dict[str, Any]],
    env_registry: list[dict[str, Any]],
    redis_registry: list[dict[str, Any]],
    data_registry: list[dict[str, Any]],
) -> str:
    strata = Counter(item["stratum"] for item in file_manifest)
    languages = Counter(item["language"] for item in file_manifest)
    py_symbols = sum(len(item.get("symbols", [])) for item in python_modules)
    ts_symbols = len(ts_atlas.get("symbols", []))
    swift_symbols = sum(len(item.get("symbols", [])) for item in swift_modules)
    shell_symbols = sum(len(item.get("symbols", [])) for item in shell_modules)
    parse_errors = [item for item in python_modules if item.get("parse_status") == "error"]
    lines = [
        "# Low-Level System Atlas",
        "",
        f"Generated: `{metadata['generated_at']}`",
        "",
        f"Source commit at scan start: `{metadata['git_head_start']}`",
        "",
        f"Source commit at scan end: `{metadata['git_head_end']}`",
        "",
        f"Tracked input content stable from capture through revalidation: `{metadata['snapshot_consistent']}`",
        "",
        "This atlas is a static, credential-shape-sanitized reconstruction index. It does not prove that a service is currently running; runtime observations belong in the operator manual and current-state report. Validate machine files against `ATLAS_BUILD_MANIFEST.json`; Markdown is only a navigation layer.",
        "",
        "## Coverage",
        "",
        f"- Git-tracked paths at capture: **{metadata['git_tracked_path_count']:,}**; cataloged paths excluding generated atlas outputs: **{len(file_manifest):,}**",
        f"- Python modules parsed: **{len(python_modules):,}**; Python symbols including module scopes: **{py_symbols:,}**",
        f"- TypeScript/JavaScript symbols: **{ts_symbols:,}**",
        f"- Swift symbols: **{swift_symbols:,}** (heuristic parser; source lines retained)",
        f"- Shell functions: **{shell_symbols:,}** (heuristic parser)",
        f"- Resolved/internal Python import edges: **{sum(1 for e in import_edges if e['resolved']):,}** of **{len(import_edges):,}**",
        f"- Resolved Python call edges: **{sum(1 for e in call_edges if e['callee_symbol_id']):,}** of **{len(call_edges):,}** static call references",
        f"- Data/schema contracts: **{len(contracts):,}**",
        f"- API route definitions/references: **{len(api_routes):,}**",
        f"- Environment keys: **{len(env_registry):,}**",
        f"- Redis key patterns: **{len(redis_registry):,}**",
        f"- Data field names: **{len(data_registry):,}**",
        f"- Python parse errors: **{len(parse_errors):,}**",
        "",
        "## Source strata",
        "",
        "| Stratum | Files |",
        "|---|---:|",
    ]
    lines.extend(f"| `{name}` | {count:,} |" for name, count in sorted(strata.items()))
    lines.extend(["", "## Languages / file kinds", "", "| Kind | Files |", "|---|---:|"])
    lines.extend(f"| `{name}` | {count:,} |" for name, count in sorted(languages.items()))
    lines.extend(
        [
            "",
            "## Canonical artifacts",
            "",
            "| Artifact | Question it answers |",
            "|---|---|",
            "| [ATLAS_BUILD_MANIFEST.json](ATLAS_BUILD_MANIFEST.json) | Which staged artifact hashes, analyzers, source snapshot and regeneration command define this generation? |",
            "| [FILE_MODULE_CATALOG.json](FILE_MODULE_CATALOG.json) | What files exist, what are their hashes/size/language/stratum, and which modules failed parsing? |",
            "| [PYTHON_SYMBOL_CATALOG.json](PYTHON_SYMBOL_CATALOG.json) | What does every Python function/class/method/module scope contain and touch? |",
            "| [TYPESCRIPT_JAVASCRIPT_ATLAS.json](TYPESCRIPT_JAVASCRIPT_ATLAS.json) | What web/JS symbols, imports, interfaces, calls, env keys, and API references exist? |",
            "| [SWIFT_SYMBOL_CONTRACT_CATALOG.json](SWIFT_SYMBOL_CONTRACT_CATALOG.json) | What iOS/watch/CLI types, functions, imports, API references, and model fields exist? |",
            "| [PYTHON_IMPORT_GRAPH.json](PYTHON_IMPORT_GRAPH.json) | Which Python module directly imports which module, and which imports are external/dynamic? |",
            "| [PYTHON_CALL_GRAPH.json](PYTHON_CALL_GRAPH.json) | Which symbol calls which statically resolvable symbol; unresolved calls remain explicitly listed? |",
            "| [CHANGE_IMPACT_INDEX.json](CHANGE_IMPACT_INDEX.json) | What file-level surfaces exist system-wide, and what direct Python reverse import/call dependents plus cross-language key/field/API/config surfaces are known? |",
            "| [CONFIG_ENV_REGISTRY.json](CONFIG_ENV_REGISTRY.json) | Which environment/static configuration keys exist, defaults where safe, and every consumer/site? |",
            "| [REDIS_KEY_USAGE_REGISTRY.json](REDIS_KEY_USAGE_REGISTRY.json) | Which key patterns are read, written, declared, or unresolved, with operation, file, symbol, line, and column? |",
            "| [DATA_CONTRACT_FIELD_REGISTRY.json](DATA_CONTRACT_FIELD_REGISTRY.json) | Which schema/payload fields are declared/read/written and where? |",
            "| [API_ROUTE_REGISTRY.json](API_ROUTE_REGISTRY.json) | Which backend route handlers and client references exist? |",
            "| [ENTRYPOINT_SERVICE_REGISTRY.json](ENTRYPOINT_SERVICE_REGISTRY.json) | Which Python mains, shell commands, Make targets, package scripts, and systemd directives start work? |",
            "| [EXCHANGE_MUTATION_REFERENCE_REGISTRY.json](EXCHANGE_MUTATION_REFERENCE_REGISTRY.json) | Which source symbols contain order/cancel/leverage/margin/transfer mutation references? |",
            "",
            "## Change-impact procedure",
            "",
            "1. Find the path in `CHANGE_IMPACT_INDEX.json.file_surfaces`; for Python, also find the module/symbol record.",
            "2. Review proven Python callers/importers plus Redis readers/writers/declarations, shared fields, config consumers, routes, tests, side effects, and exchange references. Non-Python call/import resolution remains in its dedicated compiler/heuristic atlas and requires manual traversal.",
            "3. Repeat recursively for each direct dependent; static analysis cannot prove dynamic imports, reflection, Redis consumers built from runtime strings, or provider-side behavior.",
            "4. For any strategy, PPO, MASA, risk, or live-execution change, treat static impact as the lower bound and run the subsystem tests plus paper/replay validation. Never infer live approval from this atlas.",
            "",
            "## Parser limits that must not be hidden",
            "",
            "- Python uses the CPython AST and records all nested definitions. Calls are retained even when a target cannot be resolved; resolution confidence is explicit.",
            "- TypeScript/JavaScript uses the repository's pinned TypeScript compiler AST.",
            "- Swift and shell use line/brace heuristics because SwiftSyntax and a shell AST library are not repository dependencies. Every record includes its source line so ambiguous cases can be verified directly.",
            "- Redis keys assembled through opaque runtime concatenation may appear only as partial patterns or unresolved calls. Search consumers before changing a key.",
            "- Secret-classified paths are inventoried without reading, hashing, or sizing their contents. Credential-shaped values found in analyzable source are sanitized at every serialization boundary; key names remain for dependency mapping. This is defense in depth, not a formal DLP proof: review generated artifacts before publishing them outside the host.",
            "- Publication stages a complete generation beside the canonical directory, then swaps the directory by same-filesystem rename. If promotion raises, restoration of the prior directory is attempted; if restoration itself fails, the recovery directory is retained and named in the raised error. Readers must still validate every manifest hash and retry if the directory is briefly absent or a process crash interrupts publication.",
        ]
    )
    if parse_errors:
        lines.extend(["", "## Python parse failures", ""])
        for item in parse_errors:
            lines.append(f"- `{item['path']}`: `{item['parse_error']}`")
    return "\n".join(lines)


def render_module_index(modules: list[dict[str, Any]]) -> str:
    lines = [
        "# Python Module-by-Module Index",
        "",
        "This table covers Python modules and their resolved Python import/call surface. Use `CHANGE_IMPACT_INDEX.json.file_surfaces` plus the TypeScript/JavaScript, Swift, shell, systemd and configuration registries for non-Python paths.",
        "",
        "| File | Stratum | LOC | Symbols | Direct importers | Redis R/W/U | Env | Routes | Exchange refs |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in sorted(modules, key=lambda row: row["path"]):
        lines.append(
            "| [`{path}`](../../../{path}) | `{stratum}` | {loc} | {symbols} | {importers} | {reads}/{writes}/{unknown} | {env} | {routes} | {exchange} |".format(
                **item
            )
        )
    return "\n".join(lines)


def build(repo: Path, out: Path, *, typescript_builder: Path) -> dict[str, Any]:
    started = utc_now()
    generator_path = Path(__file__).resolve()
    generator_hash_start = sha256_bytes(generator_path.read_bytes())
    typescript_builder_hash_start = sha256_bytes(typescript_builder.read_bytes())
    head_start = run_git(repo, "rev-parse", "HEAD").decode().strip()
    all_tracked_paths = tracked_paths(repo)
    try:
        output_prefix = out.resolve().relative_to(repo.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        output_prefix = ""
    status_start = worktree_status(repo, excluded_prefix=output_prefix)
    generated_output_paths_excluded = [
        path for path in all_tracked_paths if output_prefix and path.startswith(output_prefix)
    ]
    paths = [path for path in all_tracked_paths if path not in set(generated_output_paths_excluded)]

    file_manifest: list[dict[str, Any]] = []
    python_modules: list[dict[str, Any]] = []
    swift_modules: list[dict[str, Any]] = []
    shell_modules: list[dict[str, Any]] = []
    systemd_units: list[dict[str, Any]] = []
    makefiles: list[dict[str, Any]] = []
    static_configs: list[dict[str, Any]] = []
    skipped_secret_paths: list[str] = []
    regular_input_hashes: dict[str, str] = {}
    symlink_targets: dict[str, str] = {}
    nonregular_states: dict[str, str] = {}

    for rel in paths:
        absolute = repo / rel
        language = language_for(rel)
        stratum = stratum_for(rel)
        try:
            mode = absolute.lstat().st_mode
        except FileNotFoundError:
            file_manifest.append(
                {
                    "path": rel,
                    "path_kind": "missing_worktree_path",
                    "size_bytes": None,
                    "sha256": None,
                    "language": language,
                    "stratum": stratum,
                    "line_count": None,
                    "secret_path_excluded_from_content_scan": is_secret_path(rel),
                }
            )
            nonregular_states[rel] = "missing"
            continue
        secret_path = is_secret_path(rel)
        if stat.S_ISLNK(mode):
            target = os.readlink(absolute)
            symlink_targets[rel] = target
            file_manifest.append(
                {
                    "path": rel,
                    "path_kind": "symlink",
                    "symlink_target": sanitize_text(target, limit=500),
                    "size_bytes": len(os.fsencode(target)),
                    "sha256": None,
                    "language": "symlink",
                    "stratum": stratum,
                    "line_count": None,
                    "secret_path_excluded_from_content_scan": secret_path,
                }
            )
            continue
        if not stat.S_ISREG(mode):
            state = f"mode:{stat.S_IFMT(mode):o}"
            nonregular_states[rel] = state
            file_manifest.append(
                {
                    "path": rel,
                    "path_kind": "nonregular",
                    "filesystem_mode_type": state,
                    "size_bytes": None,
                    "sha256": None,
                    "language": language,
                    "stratum": stratum,
                    "line_count": None,
                    "secret_path_excluded_from_content_scan": secret_path,
                }
            )
            continue
        if secret_path:
            skipped_secret_paths.append(rel)
            file_manifest.append(
                {
                    "path": rel,
                    "path_kind": "regular_file",
                    "content_state": "excluded_secret_path_not_read_or_hashed",
                    "size_bytes": None,
                    "sha256": None,
                    "language": language,
                    "stratum": stratum,
                    "line_count": None,
                    "secret_path_excluded_from_content_scan": True,
                }
            )
            continue
        data = absolute.read_bytes()
        content_hash = sha256_bytes(data)
        regular_input_hashes[rel] = content_hash
        manifest_item = {
            "path": rel,
            "path_kind": "regular_file",
            "size_bytes": len(data),
            "sha256": content_hash,
            "language": language,
            "stratum": stratum,
            "secret_path_excluded_from_content_scan": False,
        }
        text = safe_text(data) if language != "other" or b"\0" not in data[:4096] else ""
        manifest_item["line_count"] = line_count(text) if text else None
        file_manifest.append(manifest_item)
        if language == "python":
            parsed = parse_python(rel, text)
            parsed["line_count"] = manifest_item["line_count"]
            parsed["sha256"] = manifest_item["sha256"]
            parsed["stratum"] = stratum
            python_modules.append(parsed)
        elif language == "swift":
            parsed = parse_swift(rel, text)
            parsed["line_count"] = manifest_item["line_count"]
            parsed["sha256"] = manifest_item["sha256"]
            parsed["stratum"] = stratum
            swift_modules.append(parsed)
        elif language == "shell":
            parsed = parse_shell(rel, text)
            parsed["line_count"] = manifest_item["line_count"]
            parsed["sha256"] = manifest_item["sha256"]
            parsed["stratum"] = stratum
            shell_modules.append(parsed)
        elif language == "systemd":
            systemd_units.append(parse_systemd(rel, text))
        elif language == "make":
            makefiles.append(parse_makefile(rel, text))
        elif should_parse_static_config(rel, stratum, language):
            parsed_config = parse_static_config(rel, text, language)
            if parsed_config:
                static_configs.append(parsed_config)

    final_out = out
    final_out.parent.mkdir(parents=True, exist_ok=True)
    out = Path(
        tempfile.mkdtemp(
            prefix=f".{final_out.name}-stage-",
            dir=final_out.parent,
        )
    )
    try:
        staging_prefix = out.resolve().relative_to(repo.resolve()).as_posix().rstrip("/") + "/"
    except ValueError:
        staging_prefix = ""
    ts_out = out / "TYPESCRIPT_JAVASCRIPT_ATLAS.json"
    try:
        subprocess.run(
            ["node", str(typescript_builder), "--repo-root", str(repo), "--out", str(ts_out)],
            cwd=repo,
            check=True,
        )
        ts_atlas = json.loads(ts_out.read_text(encoding="utf-8"))
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise

    known_python_paths = {item["path"] for item in python_modules}
    import_edges, reverse_importers = resolve_import_graph(python_modules, known_python_paths)
    call_edges, callers, callees = resolve_python_calls(python_modules, import_edges)

    python_symbols = [symbol for module in python_modules for symbol in module.get("symbols", [])]
    contracts = [contract for module in python_modules for contract in module.get("contracts", [])]
    contracts.extend(ts_atlas.get("contracts", []))
    contracts.extend(contract for module in swift_modules for contract in module.get("contracts", []))
    api_routes = [route for module in python_modules for route in module.get("api_routes", [])]
    api_routes.extend(ts_atlas.get("api_references", []))
    api_routes.extend(reference for module in swift_modules for reference in module.get("api_refs", []))
    env_refs = [reference for module in python_modules for reference in module.get("env_refs", [])]
    env_refs.extend(ts_atlas.get("env_references", []))
    env_refs.extend(reference for module in swift_modules for reference in module.get("env_refs", []))
    env_refs.extend(reference for module in shell_modules for reference in module.get("env_refs", []))
    env_refs.extend(reference for unit in systemd_units for reference in unit.get("env_refs", []))
    env_registry = aggregate_sites(env_refs, "key")

    redis_ops = [operation for module in python_modules for operation in module.get("redis_ops", [])]
    redis_registry = aggregate_sites(redis_ops, "key_pattern")
    exchange_refs = [reference for module in python_modules for reference in module.get("exchange_refs", [])]

    data_reads = [row for module in python_modules for row in module.get("data_field_reads", [])]
    data_writes = [row for module in python_modules for row in module.get("data_field_writes", [])]
    for contract in contracts:
        for contract_field in contract.get("fields", []):
            declaration_site = {
                "field": contract_field.get("name"),
                "path": contract.get("path"),
                "line": contract_field.get("line", contract.get("line_start", 1)),
                "symbol_id": contract.get("contract_id"),
                "access": "contract_declaration",
            }
            for span_key in ("column", "end_line", "end_column"):
                if span_key in contract_field:
                    declaration_site[span_key] = contract_field[span_key]
            data_writes.append(declaration_site)
    field_group: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"read_sites": [], "write_or_declaration_sites": []})
    for row in data_reads:
        field_group[str(row.get("field"))]["read_sites"].append({k: v for k, v in row.items() if k != "field"})
    for row in data_writes:
        if row.get("field"):
            field_group[str(row.get("field"))]["write_or_declaration_sites"].append({k: v for k, v in row.items() if k != "field"})
    data_registry = [
        {
            "field": name,
            "temporal_semantic": name in TEMPORAL_FIELDS,
            "read_sites": sorted(
                deduplicate_site_records(value["read_sites"]),
                key=lambda x: (
                    str(x.get("path", "")),
                    int(x.get("line") or 0),
                    int(x.get("column") or 0),
                    int(x.get("end_line") or 0),
                    int(x.get("end_column") or 0),
                ),
            ),
            "write_or_declaration_sites": sorted(
                deduplicate_site_records(value["write_or_declaration_sites"]),
                key=lambda x: (
                    str(x.get("path", "")),
                    int(x.get("line") or 0),
                    int(x.get("column") or 0),
                    int(x.get("end_line") or 0),
                    int(x.get("end_column") or 0),
                ),
            ),
        }
        for name, value in sorted(field_group.items())
        if name and name != "None"
    ]

    env_by_path: dict[str, set[str]] = defaultdict(set)
    redis_reads_by_path: dict[str, set[str]] = defaultdict(set)
    redis_writes_by_path: dict[str, set[str]] = defaultdict(set)
    redis_unknown_by_path: dict[str, set[str]] = defaultdict(set)
    routes_by_path: dict[str, list[str]] = defaultdict(list)
    exchange_by_path: dict[str, set[str]] = defaultdict(set)
    fields_read_by_path: dict[str, set[str]] = defaultdict(set)
    fields_write_by_path: dict[str, set[str]] = defaultdict(set)
    for row in env_refs:
        env_by_path[str(row.get("path"))].add(str(row.get("key")))
    for row in redis_ops:
        if row.get("access") == "write":
            target = redis_writes_by_path
        elif row.get("access") == "read":
            target = redis_reads_by_path
        else:
            target = redis_unknown_by_path
        target[str(row.get("path"))].add(str(row.get("key_pattern")))
    for row in api_routes:
        source_path = str(row.get("source_path") or row.get("path_source") or row.get("path") or "")
        route = str(row.get("path") or row.get("route") or "")
        if source_path and route:
            routes_by_path[source_path].append(route)
    for row in exchange_refs:
        exchange_by_path[str(row.get("path"))].add(str(row.get("operation")))
    for row in data_reads:
        fields_read_by_path[str(row.get("path"))].add(str(row.get("field")))
    for row in data_writes:
        fields_write_by_path[str(row.get("path"))].add(str(row.get("field")))

    tests_by_imported_path: dict[str, set[str]] = defaultdict(set)
    for target, importers in reverse_importers.items():
        for importer in importers:
            if stratum_for(importer) in {"test", "web_test", "mobile_test"}:
                tests_by_imported_path[target].add(importer)

    imports_from_path: dict[str, set[str]] = defaultdict(set)
    for edge in import_edges:
        if edge.get("to_path"):
            imports_from_path[str(edge["from_path"])].add(str(edge["to_path"]))

    module_impact: list[dict[str, Any]] = []
    python_module_map = {item["path"]: item for item in python_modules}
    for path, module in sorted(python_module_map.items()):
        imported_internal = sorted(imports_from_path.get(path, set()))
        side_effects = sorted({effect for symbol in module.get("symbols", []) for effect in symbol.get("side_effects", [])})
        module_impact.append(
            {
                "path": path,
                "stratum": module.get("stratum"),
                "line_count": module.get("line_count"),
                "sha256": module.get("sha256"),
                "symbols": [symbol["symbol_id"] for symbol in module.get("symbols", [])],
                "imports_internal": imported_internal,
                "direct_importers": sorted(reverse_importers.get(path, set())),
                "direct_importing_tests": sorted(tests_by_imported_path.get(path, set())),
                "env_keys": sorted(env_by_path.get(path, set())),
                "redis_reads": sorted(redis_reads_by_path.get(path, set())),
                "redis_writes": sorted(redis_writes_by_path.get(path, set())),
                "redis_unknown_or_declarations": sorted(redis_unknown_by_path.get(path, set())),
                "data_fields_read": sorted(fields_read_by_path.get(path, set())),
                "data_fields_written_or_declared": sorted(fields_write_by_path.get(path, set())),
                "api_routes": sorted(set(routes_by_path.get(path, []))),
                "side_effects": side_effects,
                "exchange_mutation_references": sorted(exchange_by_path.get(path, set())),
            }
        )

    unresolved_calls_by_caller: dict[str, set[str]] = defaultdict(set)
    for edge in call_edges:
        if edge.get("callee_symbol_id") is None:
            unresolved_calls_by_caller[str(edge["caller_symbol_id"])].add(str(edge["raw_call"]))

    symbol_impact = []
    for symbol in python_symbols:
        sid = symbol["symbol_id"]
        symbol_impact.append(
            {
                "symbol_id": sid,
                "path": symbol["path"],
                "qualname": symbol["qualname"],
                "direct_callers": sorted(callers.get(sid, set())),
                "resolved_callees": sorted(callees.get(sid, set())),
                "unresolved_or_external_calls": sorted(unresolved_calls_by_caller.get(sid, set())),
                "redis_reads": symbol.get("redis_reads", []),
                "redis_writes": symbol.get("redis_writes", []),
                "redis_unknown_or_declarations": symbol.get("redis_unknown_or_declarations", []),
                "env_reads": symbol.get("env_reads", []),
                "data_fields_read": symbol.get("data_fields_read", []),
                "data_fields_written": symbol.get("data_fields_written", []),
                "side_effects": symbol.get("side_effects", []),
                "exchange_mutations": symbol.get("exchange_mutations", []),
            }
        )

    static_config_registry = [
        {"path": config["path"], "kind": config["kind"], "entries": config.get("entries", [])}
        for config in static_configs
    ]
    symbols_by_any_path: dict[str, list[str]] = defaultdict(list)
    for symbol in python_symbols:
        symbols_by_any_path[str(symbol.get("path"))].append(str(symbol.get("symbol_id")))
    for symbol in ts_atlas.get("symbols", []):
        symbols_by_any_path[str(symbol.get("path"))].append(str(symbol.get("symbol_id")))
    for module in swift_modules:
        for symbol in module.get("symbols", []):
            symbols_by_any_path[str(module.get("path"))].append(str(symbol.get("symbol_id")))
    for module in shell_modules:
        for symbol in module.get("symbols", []):
            symbols_by_any_path[str(module.get("path"))].append(str(symbol.get("symbol_id")))
    static_config_by_path = {str(config["path"]): config for config in static_config_registry}
    systemd_by_path = {str(unit["path"]): unit for unit in systemd_units}
    file_surfaces = []
    for item in file_manifest:
        path = str(item["path"])
        language = str(item.get("language") or "other")
        if language == "python":
            analysis_depth = "python_ast_with_resolved_import_and_conservative_call_graph"
        elif language in {"typescript", "javascript"}:
            analysis_depth = "typescript_compiler_ast_raw_import_call_contract_surface"
        elif language in {"swift", "shell"}:
            analysis_depth = "heuristic_symbol_contract_surface"
        elif language == "systemd":
            analysis_depth = "directive_and_environment_definition_surface"
        elif path in static_config_by_path:
            analysis_depth = "static_configuration_key_surface"
        else:
            analysis_depth = "manifest_only"
        file_surfaces.append(
            {
                "path": path,
                "path_kind": item.get("path_kind"),
                "language": language,
                "stratum": item.get("stratum"),
                "sha256": item.get("sha256"),
                "analysis_depth": analysis_depth,
                "symbols": sorted(symbols_by_any_path.get(path, [])),
                "direct_importers": sorted(reverse_importers.get(path, set())) if language == "python" else [],
                "env_keys": sorted(env_by_path.get(path, set())),
                "redis_reads": sorted(redis_reads_by_path.get(path, set())),
                "redis_writes": sorted(redis_writes_by_path.get(path, set())),
                "redis_unknown_or_declarations": sorted(redis_unknown_by_path.get(path, set())),
                "data_fields_read": sorted(fields_read_by_path.get(path, set())),
                "data_fields_written_or_declared": sorted(fields_write_by_path.get(path, set())),
                "api_routes_or_references": sorted(set(routes_by_path.get(path, []))),
                "exchange_mutation_references": sorted(exchange_by_path.get(path, set())),
                "static_config_entry_count": len(static_config_by_path.get(path, {}).get("entries", [])),
                "systemd_directive_count": len(systemd_by_path.get(path, {}).get("directives", {})),
            }
        )
    config_registry = {
        "environment_keys": env_registry,
        "static_configuration_files": static_config_registry,
        "security_note": "Secret-like values and paths are redacted or excluded. Key names remain for dependency mapping.",
    }

    python_entrypoints = [
        {
            "kind": "python_main_guard",
            "path": module["path"],
            "symbols": [s["symbol_id"] for s in module.get("symbols", []) if s["qualname"] in {"main", "<module>"}],
        }
        for module in python_modules
        if module.get("has_main_guard")
    ]
    package_scripts = []
    for config in static_configs:
        if Path(config["path"]).name == "package.json":
            for entry in config.get("entries", []):
                key = str(entry.get("key") or "")
                if key.startswith("scripts.") and key.count(".") == 1:
                    package_scripts.append(
                        {
                            "kind": "package_script",
                            "path": config["path"],
                            "name": key.removeprefix("scripts."),
                            "command": entry.get("value"),
                        }
                    )
    entrypoint_registry = {
        "python_main_guards": python_entrypoints,
        "shell_entrypoints": shell_modules,
        "systemd_units": systemd_units,
        "make_targets": makefiles,
        "package_scripts": package_scripts,
    }

    expected_typescript_hash_by_path = {
        str(item["path"]): str(item["sha256"])
        for item in file_manifest
        if item.get("path_kind") == "regular_file"
        and item.get("language") in {"typescript", "javascript"}
        and not item.get("secret_path_excluded_from_content_scan")
        and item.get("sha256")
    }
    typescript_hash_mismatches = []
    typescript_modules_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for module in ts_atlas.get("modules", []):
        path = str(module.get("path") or "")
        typescript_modules_by_path[path].append(module)
    for path, expected in sorted(expected_typescript_hash_by_path.items()):
        modules_for_path = typescript_modules_by_path.get(path, [])
        if not modules_for_path:
            typescript_hash_mismatches.append(
                {"path": path, "reason": "missing_typescript_module"}
            )
            continue
        if len(modules_for_path) != 1:
            typescript_hash_mismatches.append(
                {
                    "path": path,
                    "reason": "duplicate_typescript_modules",
                    "observed_count": len(modules_for_path),
                }
            )
            continue
        observed = str(modules_for_path[0].get("sha256") or "")
        if expected != observed:
            typescript_hash_mismatches.append(
                {
                    "path": path,
                    "reason": "typescript_snapshot_hash_mismatch",
                }
            )
    for path, modules_for_path in sorted(typescript_modules_by_path.items()):
        if path not in expected_typescript_hash_by_path:
            typescript_hash_mismatches.append(
                {
                    "path": path,
                    "reason": "unexpected_typescript_module",
                    "observed_count": len(modules_for_path),
                }
            )
    reported_typescript_count = ts_atlas.get("metadata", {}).get("tracked_source_files")
    if reported_typescript_count != len(expected_typescript_hash_by_path):
        typescript_hash_mismatches.append(
            {
                "path": None,
                "reason": "typescript_reported_source_count_mismatch",
                "expected_count": len(expected_typescript_hash_by_path),
                "reported_count": reported_typescript_count,
            }
        )
    typescript_structure_mismatches: list[dict[str, Any]] = []
    for path, modules_for_path in sorted(typescript_modules_by_path.items()):
        if len(modules_for_path) != 1:
            continue
        module = modules_for_path[0]
        module_symbols = module.get("symbols")
        if not isinstance(module_symbols, list) or not any(
            isinstance(symbol, Mapping)
            and symbol.get("path") == path
            and symbol.get("qualname") == "<module>"
            and symbol.get("symbol_id") == f"{path}:<module>"
            for symbol in module_symbols
        ):
            typescript_structure_mismatches.append(
                {"path": path, "reason": "missing_typescript_module_scope_symbol"}
            )
    for collection_name in (
        "symbols",
        "contracts",
        "calls",
        "imports",
        "env_references",
        "api_references",
        "route_definitions",
        "parse_diagnostics",
    ):
        expected_count = sum(
            len(module.get(collection_name, []))
            for module in ts_atlas.get("modules", [])
            if isinstance(module.get(collection_name, []), list)
        )
        top_level = ts_atlas.get(collection_name)
        observed_count = len(top_level) if isinstance(top_level, list) else None
        if observed_count != expected_count:
            typescript_structure_mismatches.append(
                {
                    "path": None,
                    "reason": "typescript_flattened_collection_count_mismatch",
                    "collection": collection_name,
                    "expected_count": expected_count,
                    "observed_count": observed_count,
                }
            )
    input_validation = revalidate_tracked_inputs(
        repo,
        all_tracked_paths,
        regular_input_hashes,
        symlink_targets,
        nonregular_states,
    )
    head_end = run_git(repo, "rev-parse", "HEAD").decode().strip()
    status_end = worktree_status(
        repo,
        excluded_prefix=output_prefix,
        additional_excluded_prefixes=(staging_prefix,),
    )
    generator_hash_end = sha256_bytes(generator_path.read_bytes())
    typescript_builder_hash_end = sha256_bytes(typescript_builder.read_bytes())
    analyzer_inputs_unchanged = (
        generator_hash_start == generator_hash_end
        and typescript_builder_hash_start == typescript_builder_hash_end
    )
    typescript_provenance_mismatches: list[dict[str, Any]] = []
    raw_typescript_metadata = ts_atlas.get("metadata", {})
    typescript_metadata = (
        raw_typescript_metadata if isinstance(raw_typescript_metadata, Mapping) else {}
    )
    raw_compiler_provenance = typescript_metadata.get("typescript_compiler", {})
    compiler_provenance = (
        raw_compiler_provenance if isinstance(raw_compiler_provenance, Mapping) else {}
    )
    raw_compiler_provenance_end = typescript_metadata.get("typescript_compiler_end", {})
    compiler_provenance_end = (
        raw_compiler_provenance_end
        if isinstance(raw_compiler_provenance_end, Mapping)
        else {}
    )
    provenance_schema_errors: list[str] = []
    compiler_version = str(compiler_provenance.get("version") or "")
    if compiler_provenance.get("verified") is not True:
        provenance_schema_errors.append("verified_not_true")
    if not compiler_version:
        provenance_schema_errors.append("missing_version")
    if not str(compiler_provenance.get("lockfile") or ""):
        provenance_schema_errors.append("missing_lockfile")
    if not str(compiler_provenance.get("package_path") or ""):
        provenance_schema_errors.append("missing_package_path")
    if not isinstance(compiler_provenance.get("lockfile_version"), (int, str)):
        provenance_schema_errors.append("missing_lockfile_version")
    for hash_field in (
        "lockfile_sha256",
        "package_manifest_sha256",
        "compiler_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(compiler_provenance.get(hash_field) or "")):
            provenance_schema_errors.append(f"invalid_{hash_field}")
    if "integrity" not in compiler_provenance or not isinstance(
        compiler_provenance.get("integrity"),
        (str, type(None)),
    ):
        provenance_schema_errors.append("missing_or_invalid_integrity")
    if provenance_schema_errors:
        typescript_provenance_mismatches.append(
            {
                "reason": "typescript_compiler_provenance_schema_invalid",
                "path": None,
                "details": sorted(provenance_schema_errors),
            }
        )
    expected_parser = f"typescript@{compiler_version}" if compiler_version else ""
    if not expected_parser or typescript_metadata.get("parser") != expected_parser:
        typescript_provenance_mismatches.append(
            {
                "reason": "typescript_parser_version_mismatch",
                "path": None,
            }
        )
    if dict(compiler_provenance_end) != dict(compiler_provenance):
        typescript_provenance_mismatches.append(
            {
                "reason": "typescript_compiler_start_end_provenance_mismatch",
                "path": None,
            }
        )
    compiler_lockfile = str(compiler_provenance.get("lockfile") or "")
    compiler_lockfile_hash = str(compiler_provenance.get("lockfile_sha256") or "")
    expected_lockfile_hash = next(
        (
            str(item.get("sha256"))
            for item in file_manifest
            if item.get("path") == compiler_lockfile and item.get("sha256")
        ),
        "",
    )
    if not compiler_lockfile or not expected_lockfile_hash or compiler_lockfile_hash != expected_lockfile_hash:
        typescript_provenance_mismatches.append(
            {
                "reason": "typescript_lockfile_snapshot_hash_mismatch",
                "path": compiler_lockfile or None,
            }
        )
    if typescript_metadata.get("typescript_compiler_snapshot_consistent") is not True:
        typescript_provenance_mismatches.append(
            {"reason": "typescript_compiler_snapshot_not_revalidated", "path": None}
        )
    snapshot_consistent = (
        head_start == head_end
        and bool(input_validation["content_inputs_unchanged"])
        and not typescript_hash_mismatches
        and not typescript_structure_mismatches
        and not typescript_provenance_mismatches
        and analyzer_inputs_unchanged
    )
    metadata = {
        "schema_version": 2,
        "generated_at": started,
        "completed_at": utc_now(),
        "repo_root": str(repo),
        "source_snapshot_kind": "tracked_worktree_content_with_start_end_hash_revalidation",
        "git_head_start": head_start,
        "git_head_end": head_end,
        "snapshot_consistent": snapshot_consistent,
        "content_snapshot_validation": input_validation,
        "typescript_snapshot_hash_mismatches": typescript_hash_mismatches,
        "typescript_structure_mismatches": typescript_structure_mismatches,
        "typescript_provenance_mismatches": typescript_provenance_mismatches,
        "typescript_expected_regular_source_count": len(expected_typescript_hash_by_path),
        "typescript_emitted_module_count": sum(len(items) for items in typescript_modules_by_path.values()),
        "working_tree_status_start": status_start,
        "working_tree_status_end": status_end,
        "working_tree_status_unchanged": status_start == status_end,
        "working_tree_status_scope": "tracked_and_untracked_paths_excluding_generated_output_and_staging_prefixes",
        "git_tracked_path_count": len(all_tracked_paths),
        "cataloged_path_count": len(file_manifest),
        "content_scanned_regular_file_count": len(regular_input_hashes),
        "generated_output_paths_excluded": generated_output_paths_excluded,
        "tracked_file_count": len(file_manifest),
        "secret_paths_excluded": skipped_secret_paths,
        "generator_sha256": generator_hash_start,
        "generator_sha256_end": generator_hash_end,
        "typescript_builder_sha256": typescript_builder_hash_start,
        "typescript_builder_sha256_end": typescript_builder_hash_end,
        "analyzer_inputs_unchanged": analyzer_inputs_unchanged,
    }

    json_write(out / "ATLAS_METADATA.json", metadata)
    json_write(out / "FILE_MODULE_CATALOG.json", {"metadata": metadata, "files": file_manifest, "python_modules": [{k: v for k, v in module.items() if k not in {"symbols", "contracts", "data_field_reads", "data_field_writes"}} for module in python_modules]}, pretty=False)
    json_write(out / "PYTHON_SYMBOL_CATALOG.json", {"metadata": metadata, "symbols": python_symbols}, pretty=False)
    json_write(out / "SWIFT_SYMBOL_CONTRACT_CATALOG.json", {"metadata": metadata, "modules": swift_modules}, pretty=False)
    json_write(out / "PYTHON_IMPORT_GRAPH.json", {"metadata": metadata, "edges": import_edges}, pretty=False)
    json_write(out / "PYTHON_CALL_GRAPH.json", {"metadata": metadata, "edges": call_edges}, pretty=False)
    json_write(out / "DATA_CONTRACTS.json", {"metadata": metadata, "contracts": contracts}, pretty=False)
    json_write(out / "DATA_CONTRACT_FIELD_REGISTRY.json", {"metadata": metadata, "fields": data_registry}, pretty=False)
    json_write(out / "CONFIG_ENV_REGISTRY.json", {"metadata": metadata, **config_registry})
    json_write(out / "REDIS_KEY_USAGE_REGISTRY.json", {"metadata": metadata, "keys": redis_registry}, pretty=False)
    json_write(out / "API_ROUTE_REGISTRY.json", {"metadata": metadata, "routes_and_references": api_routes}, pretty=False)
    json_write(out / "ENTRYPOINT_SERVICE_REGISTRY.json", {"metadata": metadata, **entrypoint_registry}, pretty=False)
    json_write(out / "EXCHANGE_MUTATION_REFERENCE_REGISTRY.json", {"metadata": metadata, "references": exchange_refs})
    json_write(
        out / "CHANGE_IMPACT_INDEX.json",
        {
            "metadata": metadata,
            "coverage": {
                "file_surfaces": "all cataloged tracked paths",
                "resolved_module_and_symbol_dependency_graph": "python_only",
                "typescript_javascript": "compiler AST symbols/imports/raw calls/contracts/routes in dedicated atlas and file surfaces",
                "swift_shell": "heuristic symbols/contracts/references in dedicated catalogs and file surfaces",
                "systemd_static_config": "directives/environment definitions/config keys in file surfaces and registries",
            },
            "file_surfaces": file_surfaces,
            "modules": module_impact,
            "symbols": symbol_impact,
            "static_configuration_files": static_config_registry,
            "environment_keys": env_registry,
            "redis_keys": redis_registry,
            "data_fields": data_registry,
            "api_routes": api_routes,
        },
        pretty=False,
    )

    summary = render_summary(
        metadata,
        file_manifest,
        python_modules,
        ts_atlas,
        swift_modules,
        shell_modules,
        import_edges,
        call_edges,
        contracts,
        api_routes,
        env_registry,
        redis_registry,
        data_registry,
    )
    markdown_write(out / "ATLAS_SUMMARY.md", summary)
    module_rows = [
        {
            "path": module["path"],
            "stratum": module["stratum"],
            "loc": module["line_count"] or 0,
            "symbols": len(module["symbols"]),
            "importers": len(reverse_importers.get(module["path"], set())),
            "reads": len(redis_reads_by_path.get(module["path"], set())),
            "writes": len(redis_writes_by_path.get(module["path"], set())),
            "unknown": len(redis_unknown_by_path.get(module["path"], set())),
            "env": len(env_by_path.get(module["path"], set())),
            "routes": len(routes_by_path.get(module["path"], [])),
            "exchange": len(exchange_by_path.get(module["path"], set())),
        }
        for module in python_modules
    ]
    markdown_write(out / "MODULE_BY_MODULE_INDEX.md", render_module_index(module_rows))

    artifact_records = []
    for artifact in sorted(path for path in out.iterdir() if path.is_file()):
        data = artifact.read_bytes()
        artifact_records.append(
            {"name": artifact.name, "size_bytes": len(data), "sha256": sha256_bytes(data)}
        )
    build_manifest = {
        "schema_version": 1,
        "atlas_schema_version": metadata["schema_version"],
        "generated_at": metadata["generated_at"],
        "source": {
            "git_head_start": head_start,
            "git_head_end": head_end,
            "snapshot_consistent": snapshot_consistent,
            "git_tracked_path_count": len(all_tracked_paths),
            "cataloged_path_count": len(file_manifest),
        },
        "analyzers": {
            "python_generator_sha256": metadata["generator_sha256"],
            "typescript_builder_sha256": metadata["typescript_builder_sha256"],
            "typescript_parser": ts_atlas.get("metadata", {}).get("parser"),
        },
        "regeneration_command": "python3 tools/build_system_reverse_engineering_atlas.py --repo-root . --out-dir docs/system_audit_2026_master/atlas",
        "artifacts": artifact_records,
        "publication_rule": "All listed artifacts are staged in one sibling directory, then the complete directory is swapped by same-filesystem rename. Failed promotion attempts restore the prior directory; if restoration also fails, its recovery directory is preserved and reported. Readers must reject an absent or hash-mismatching generation and retry.",
    }
    json_write(out / "ATLAS_BUILD_MANIFEST.json", build_manifest)
    published = False
    if snapshot_consistent:
        publish_staged_atlas(out, final_out)
        published = True
    else:
        # Preserve the last validated generation. The inconsistent metadata is
        # returned to the caller/stdout but never becomes the canonical atlas.
        shutil.rmtree(out, ignore_errors=True)

    return {
        "metadata": metadata,
        "published": published,
        "counts": {
            "files": len(file_manifest),
            "python_modules": len(python_modules),
            "python_symbols": len(python_symbols),
            "typescript_javascript_symbols": len(ts_atlas.get("symbols", [])),
            "swift_symbols": sum(len(item.get("symbols", [])) for item in swift_modules),
            "import_edges": len(import_edges),
            "call_edges": len(call_edges),
            "contracts": len(contracts),
            "environment_keys": len(env_registry),
            "redis_key_patterns": len(redis_registry),
            "data_fields": len(data_registry),
            "api_routes_and_references": len(api_routes),
            "exchange_mutation_references": len(exchange_refs),
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument(
        "--out-dir",
        default="docs/system_audit_2026_master/atlas",
        help="Absolute path or path relative to repository root",
    )
    parser.add_argument(
        "--typescript-builder",
        default="tools/build_typescript_reverse_engineering_atlas.cjs",
        help="TypeScript compiler-AST helper path relative to repository root",
    )
    args = parser.parse_args(argv)
    repo = Path(args.repo_root).expanduser().resolve()
    out = Path(args.out_dir).expanduser()
    if not out.is_absolute():
        out = repo / out
    ts_builder = Path(args.typescript_builder).expanduser()
    if not ts_builder.is_absolute():
        ts_builder = repo / ts_builder
    if not (repo / ".git").exists():
        parser.error(f"not a git repository root: {repo}")
    result = build(repo, out.resolve(), typescript_builder=ts_builder.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["metadata"]["snapshot_consistent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
