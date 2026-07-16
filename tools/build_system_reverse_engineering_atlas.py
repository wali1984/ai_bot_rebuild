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
import os
import re
import subprocess
import sys
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
    r"(?:secret|password|passwd|token|api[_-]?key|private[_-]?key|credential|authorization|cookie)",
    re.IGNORECASE,
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
    "dumps",
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


def run_git(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=repo)


def tracked_paths(repo: Path) -> list[str]:
    raw = run_git(repo, "ls-files", "-z")
    return sorted(p.decode("utf-8", errors="surrogateescape") for p in raw.split(b"\0") if p)


def is_secret_path(path: str) -> bool:
    parts = {p.lower() for p in Path(path).parts}
    name = Path(path).name
    if parts & SECRET_PATH_PARTS:
        return True
    if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
        return True
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
    if language_for(path) in CONFIG_SUFFIXES.values() | {"make", "dockerfile"}:
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
    if pretty:
        rendered = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    else:
        rendered = json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    path.write_text(rendered + "\n", encoding="utf-8")


def markdown_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def rendered_expr(node: ast.AST | None, *, limit: int = 500) -> str | None:
    if node is None:
        return None
    try:
        value = ast.unparse(node)
    except Exception:
        return None
    value = " ".join(value.split())
    return value[:limit]


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
        return {"state": "required_no_default"}
    value: Any
    try:
        value = ast.literal_eval(node)
    except Exception:
        value = rendered_expr(node, limit=300)
    text = str(value)
    if SENSITIVE_KEY_RE.search(text):
        return {"state": "expression_redacted"}
    if isinstance(value, str) and len(value) > 300:
        value = value[:300] + "…"
    return {"state": "default_present", "value": value}


def function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    returns = f" -> {rendered_expr(node.returns)}" if node.returns is not None else ""
    return f"{prefix} {node.name}({rendered_expr(node.args) or ''}){returns}"


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


def resolve_relative_import(current_module: str, level: int, imported: str | None) -> str:
    parts = current_module.split(".")
    if parts and parts[-1] != "__init__":
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
                            if SENSITIVE_KEY_RE.search(target.id)
                            else (text_value if text_value is not None and len(text_value) <= 300 else None),
                            "expression": "<redacted>"
                            if SENSITIVE_KEY_RE.search(target.id)
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
                "line": getattr(node, "lineno", 1),
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
                "line": getattr(node, "lineno", 1),
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
        module = resolve_relative_import(self.module_name, node.level, node.module)
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
            symbol_id=f"{self.path}:{qualname}",
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
                            "default": safe_default(child.value),
                            "line": child.lineno,
                        }
                    )
                elif isinstance(child, ast.Assign):
                    for target in child.targets:
                        if isinstance(target, ast.Name) and not target.id.startswith("_"):
                            fields.append(
                                {
                                    "name": target.id,
                                    "annotation": None,
                                    "default": safe_default(child.value),
                                    "line": child.lineno,
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
                self._record_data_write(item["name"], node, "schema_declaration")
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
            symbol_id=f"{self.path}:{qualname}",
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
                        "line": dec.lineno,
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

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        value = literal_string(node.slice, self.constants)
        if value is not None and not (
            dotted_name(node.value) == "os.environ" or REDIS_KEY_RE.match(value)
        ):
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
            "line": getattr(node, "lineno", 1),
            "symbol_id": self.current_symbol_id,
            "default": {"state": "redacted"} if SENSITIVE_KEY_RE.search(key) else safe_default(default),
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
                    "line": node.lineno,
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

        if short in REDIS_READ_METHODS | REDIS_WRITE_METHODS and node.args:
            key = literal_string(node.args[0], self.constants)
            if key and REDIS_KEY_RE.match(key):
                access = "write" if short in REDIS_WRITE_METHODS else "read"
                self.redis_ops.append(
                    {
                        "key_pattern": key,
                        "operation": short,
                        "access": access,
                        "path": self.path,
                        "line": node.lineno,
                        "symbol_id": self.current_symbol_id,
                        "client_expression": dotted_name(getattr(node.func, "value", None)),
                    }
                )
                if access == "write":
                    self.current.redis_writes.add(key)
                    self.current.side_effects.add("redis_write")
                else:
                    self.current.redis_reads.add(key)

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
            imports.append({"module": stripped.split()[1], "line": number})
        type_match = SWIFT_TYPE_RE.match(line)
        if type_match:
            kind, name = type_match.groups()
            qualname = ".".join([*(item[0] for item in type_stack), name])
            symbols.append(
                {
                    "symbol_id": f"{path}:{qualname}",
                    "path": path,
                    "qualname": qualname,
                    "kind": f"swift_{kind}",
                    "line_start": number,
                    "line_end": number,
                    "signature": stripped[:500],
                    "parser_confidence": "heuristic",
                }
            )
            type_stack.append((name, brace_depth + line.count("{") - line.count("}")))
            if kind in {"struct", "class", "enum", "protocol"}:
                current_contract = {
                    "contract_id": f"{path}:{qualname}",
                    "path": path,
                    "name": qualname,
                    "kind": f"swift_{kind}",
                    "fields": [],
                    "line_start": number,
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
                    "signature": stripped[:500],
                    "parser_confidence": "heuristic",
                }
            )
        field_match = SWIFT_FIELD_RE.match(line)
        if field_match and current_contract:
            field_name, annotation = field_match.groups()
            current_contract["fields"].append(
                {"name": field_name, "annotation": annotation.strip()[:300], "line": number}
            )
        brace_depth += line.count("{") - line.count("}")
        while type_stack and brace_depth < type_stack[-1][1]:
            type_stack.pop()
            current_contract = contracts[-1] if type_stack and contracts else None
    for contract in contracts:
        contract["line_end"] = len(lines)
    api_refs = [
        {"path": match.group(0), "source_path": path, "line": i, "kind": "swift_api_reference"}
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
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = str(row.get(key_name, ""))
        if key:
            grouped[key].append({k: v for k, v in row.items() if k != key_name})
    return [{key_name: key, "sites": sorted(sites, key=lambda x: (str(x.get("path", "")), int(x.get("line", 0))))} for key, sites in sorted(grouped.items())]


def resolve_import_graph(python_modules: list[dict[str, Any]], known_paths: set[str]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    module_to_path: dict[str, str] = {}
    for path in known_paths:
        for alias in module_aliases(path):
            module_to_path.setdefault(alias, path)
    edges: list[dict[str, Any]] = []
    reverse: dict[str, set[str]] = defaultdict(set)
    for module in python_modules:
        source = module["path"]
        seen: set[tuple[str, str | None]] = set()
        for item in module.get("imports", []):
            imported_module = str(item.get("module") or "")
            imported_name = item.get("name")
            target = module_to_path.get(imported_module)
            if target is None and imported_name:
                target = module_to_path.get(f"{imported_module}.{imported_name}")
            if target is None:
                probe = imported_module
                while probe and target is None:
                    target = module_to_path.get(probe)
                    probe = probe.rsplit(".", 1)[0] if "." in probe else ""
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
    symbol_records: dict[str, dict[str, Any]] = {}
    for path, symbols in symbols_by_path.items():
        for symbol in symbols:
            sid = symbol["symbol_id"]
            symbol_records[sid] = symbol
            by_path_simple[path][symbol["qualname"].split(".")[-1]].append(sid)
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
                    candidate = f"{path}:{class_prefix}.{simple}"
                    if candidate in symbol_records:
                        target, confidence, reason = candidate, "high", "same_class_method"
                if target is None and len(by_path_simple[path].get(simple, [])) == 1:
                    target, confidence, reason = by_path_simple[path][simple][0], "high", "same_module_unique_name"
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
                    possible = [
                        sid
                        for candidate_path in candidate_paths
                        for sid in by_path_simple[candidate_path].get(imported_name if len(pieces) == 1 else simple, [])
                    ]
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
        if key.lower().startswith("environment") or SENSITIVE_KEY_RE.search(key):
            if "=" in value:
                env_key = value.strip('"\'').split("=", 1)[0]
                rendered = f"{env_key}=<redacted>"
            else:
                rendered = "<redacted>"
        values[f"{section}.{key}"].append({"line": number, "value": rendered})
    return {"path": path, "kind": "systemd", "directives": dict(sorted(values.items()))}


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
            if SENSITIVE_KEY_RE.search(key):
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
                    "value": "<redacted>" if SENSITIVE_KEY_RE.search(dotted) else value[:500],
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
        f"Generated: `{metadata['generated_at']}`  ",
        f"Source commit at scan start: `{metadata['git_head_start']}`  ",
        f"Source commit at scan end: `{metadata['git_head_end']}`  ",
        f"Stable commit snapshot: `{metadata['snapshot_consistent']}`  ",
        "",
        "This atlas is a static, secret-safe reconstruction index. It does not prove that a service is currently running; runtime observations belong in the operator manual and current-state report. JSON files in this directory are canonical and Markdown is only a navigation layer.",
        "",
        "## Coverage",
        "",
        f"- Tracked files inventoried: **{len(file_manifest):,}**",
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
            "| `FILE_MODULE_CATALOG.json` | What files exist, what are their hashes/size/language/stratum, and which modules failed parsing? |",
            "| `PYTHON_SYMBOL_CATALOG.json` | What does every Python function/class/method/module scope contain and touch? |",
            "| `TYPESCRIPT_JAVASCRIPT_ATLAS.json` | What web/JS symbols, imports, interfaces, calls, env keys, and API references exist? |",
            "| `SWIFT_SYMBOL_CONTRACT_CATALOG.json` | What iOS/watch/CLI types, functions, imports, API references, and model fields exist? |",
            "| `PYTHON_IMPORT_GRAPH.json` | Which Python module directly imports which module, and which imports are external/dynamic? |",
            "| `PYTHON_CALL_GRAPH.json` | Which symbol calls which statically resolvable symbol; unresolved calls remain explicitly listed? |",
            "| `CHANGE_IMPACT_INDEX.json` | For each file/symbol/config/Redis/data/API surface, what direct reverse dependents are known? |",
            "| `CONFIG_ENV_REGISTRY.json` | Which environment/static configuration keys exist, defaults where safe, and every consumer/site? |",
            "| `REDIS_KEY_USAGE_REGISTRY.json` | Which key patterns are read/written, with operation, file, symbol, and line? |",
            "| `DATA_CONTRACT_FIELD_REGISTRY.json` | Which schema/payload fields are declared/read/written and where? |",
            "| `API_ROUTE_REGISTRY.json` | Which backend route handlers and client references exist? |",
            "| `ENTRYPOINT_SERVICE_REGISTRY.json` | Which Python mains, shell commands, Make targets, package scripts, and systemd directives start work? |",
            "| `EXCHANGE_MUTATION_REFERENCE_REGISTRY.json` | Which source symbols contain order/cancel/leverage/margin/transfer mutation references? |",
            "",
            "## Change-impact procedure",
            "",
            "1. Find the symbol or file in `CHANGE_IMPACT_INDEX.json`.",
            "2. Review direct callers/importers, Redis readers/writers, shared fields, config consumers, routes, tests, side effects, and exchange references.",
            "3. Repeat recursively for each direct dependent; static analysis cannot prove dynamic imports, reflection, Redis consumers built from runtime strings, or provider-side behavior.",
            "4. For any strategy, PPO, MASA, risk, or live-execution change, treat static impact as the lower bound and run the subsystem tests plus paper/replay validation. Never infer live approval from this atlas.",
            "",
            "## Parser limits that must not be hidden",
            "",
            "- Python uses the CPython AST and records all nested definitions. Calls are retained even when a target cannot be resolved; resolution confidence is explicit.",
            "- TypeScript/JavaScript uses the repository's pinned TypeScript compiler AST.",
            "- Swift and shell use line/brace heuristics because SwiftSyntax and a shell AST library are not repository dependencies. Every record includes its source line so ambiguous cases can be verified directly.",
            "- Redis keys assembled through opaque runtime concatenation may appear only as partial patterns or unresolved calls. Search consumers before changing a key.",
            "- Secret-like paths and secret values are never read into the atlas. Only secret key names referenced by source may appear, with defaults redacted.",
        ]
    )
    if parse_errors:
        lines.extend(["", "## Python parse failures", ""])
        for item in parse_errors:
            lines.append(f"- `{item['path']}`: `{item['parse_error']}`")
    return "\n".join(lines)


def render_module_index(modules: list[dict[str, Any]]) -> str:
    lines = [
        "# Module-by-Module Index",
        "",
        "This is the human navigation table. Use `CHANGE_IMPACT_INDEX.json` and the symbol catalogs for complete details.",
        "",
        "| File | Stratum | LOC | Symbols | Direct importers | Redis R/W | Env | Routes | Exchange refs |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in sorted(modules, key=lambda row: row["path"]):
        lines.append(
            "| `{path}` | `{stratum}` | {loc} | {symbols} | {importers} | {reads}/{writes} | {env} | {routes} | {exchange} |".format(
                **item
            )
        )
    return "\n".join(lines)


def build(repo: Path, out: Path, *, typescript_builder: Path) -> dict[str, Any]:
    started = utc_now()
    head_start = run_git(repo, "rev-parse", "HEAD").decode().strip()
    status_start = run_git(repo, "status", "--porcelain=v1").decode("utf-8", errors="replace").splitlines()
    paths = tracked_paths(repo)

    file_manifest: list[dict[str, Any]] = []
    python_modules: list[dict[str, Any]] = []
    swift_modules: list[dict[str, Any]] = []
    shell_modules: list[dict[str, Any]] = []
    systemd_units: list[dict[str, Any]] = []
    makefiles: list[dict[str, Any]] = []
    static_configs: list[dict[str, Any]] = []
    skipped_secret_paths: list[str] = []

    for rel in paths:
        absolute = repo / rel
        if not absolute.is_file():
            continue
        language = language_for(rel)
        stratum = stratum_for(rel)
        data = absolute.read_bytes()
        secret_path = is_secret_path(rel)
        manifest_item = {
            "path": rel,
            "size_bytes": len(data),
            "sha256": sha256_bytes(data),
            "language": language,
            "stratum": stratum,
            "secret_path_excluded_from_content_scan": secret_path,
        }
        if secret_path:
            manifest_item["line_count"] = None
            skipped_secret_paths.append(rel)
            file_manifest.append(manifest_item)
            continue
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

    out.mkdir(parents=True, exist_ok=True)
    ts_out = out / "TYPESCRIPT_JAVASCRIPT_ATLAS.json"
    subprocess.run(
        ["node", str(typescript_builder), "--repo-root", str(repo), "--out", str(ts_out)],
        cwd=repo,
        check=True,
    )
    ts_atlas = json.loads(ts_out.read_text(encoding="utf-8"))

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
    env_registry = aggregate_sites(env_refs, "key")

    redis_ops = [operation for module in python_modules for operation in module.get("redis_ops", [])]
    redis_registry = aggregate_sites(redis_ops, "key_pattern")
    exchange_refs = [reference for module in python_modules for reference in module.get("exchange_refs", [])]

    data_reads = [row for module in python_modules for row in module.get("data_field_reads", [])]
    data_writes = [row for module in python_modules for row in module.get("data_field_writes", [])]
    for contract in contracts:
        for contract_field in contract.get("fields", []):
            data_writes.append(
                {
                    "field": contract_field.get("name"),
                    "path": contract.get("path"),
                    "line": contract_field.get("line", contract.get("line_start", 1)),
                    "symbol_id": contract.get("contract_id"),
                    "access": "contract_declaration",
                }
            )
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
            "read_sites": sorted(value["read_sites"], key=lambda x: (str(x.get("path", "")), int(x.get("line") or 0))),
            "write_or_declaration_sites": sorted(value["write_or_declaration_sites"], key=lambda x: (str(x.get("path", "")), int(x.get("line") or 0))),
        }
        for name, value in sorted(field_group.items())
        if name and name != "None"
    ]

    env_by_path: dict[str, set[str]] = defaultdict(set)
    redis_reads_by_path: dict[str, set[str]] = defaultdict(set)
    redis_writes_by_path: dict[str, set[str]] = defaultdict(set)
    routes_by_path: dict[str, list[str]] = defaultdict(list)
    exchange_by_path: dict[str, set[str]] = defaultdict(set)
    fields_read_by_path: dict[str, set[str]] = defaultdict(set)
    fields_write_by_path: dict[str, set[str]] = defaultdict(set)
    for row in env_refs:
        env_by_path[str(row.get("path"))].add(str(row.get("key")))
    for row in redis_ops:
        target = redis_writes_by_path if row.get("access") == "write" else redis_reads_by_path
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

    module_impact: list[dict[str, Any]] = []
    python_module_map = {item["path"]: item for item in python_modules}
    for path, module in sorted(python_module_map.items()):
        imported_internal = sorted({edge["to_path"] for edge in import_edges if edge["from_path"] == path and edge.get("to_path")})
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
                "data_fields_read": sorted(fields_read_by_path.get(path, set())),
                "data_fields_written_or_declared": sorted(fields_write_by_path.get(path, set())),
                "api_routes": sorted(set(routes_by_path.get(path, []))),
                "side_effects": side_effects,
                "exchange_mutation_references": sorted(exchange_by_path.get(path, set())),
            }
        )

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
                "unresolved_or_external_calls": sorted(
                    edge["raw_call"]
                    for edge in call_edges
                    if edge["caller_symbol_id"] == sid and edge["callee_symbol_id"] is None
                ),
                "redis_reads": symbol.get("redis_reads", []),
                "redis_writes": symbol.get("redis_writes", []),
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
        if "if __name__" in (repo / module["path"]).read_text(encoding="utf-8", errors="replace")
        and "__main__" in (repo / module["path"]).read_text(encoding="utf-8", errors="replace")
    ]
    package_scripts = []
    for config in static_configs:
        if Path(config["path"]).name == "package.json":
            try:
                raw_package = json.loads((repo / config["path"]).read_text(encoding="utf-8"))
                for name, command in (raw_package.get("scripts") or {}).items():
                    package_scripts.append(
                        {"kind": "package_script", "path": config["path"], "name": name, "command": command}
                    )
            except Exception:
                pass
    entrypoint_registry = {
        "python_main_guards": python_entrypoints,
        "shell_entrypoints": shell_modules,
        "systemd_units": systemd_units,
        "make_targets": makefiles,
        "package_scripts": package_scripts,
    }

    head_end = run_git(repo, "rev-parse", "HEAD").decode().strip()
    status_end = run_git(repo, "status", "--porcelain=v1").decode("utf-8", errors="replace").splitlines()
    metadata = {
        "schema_version": 1,
        "generated_at": started,
        "completed_at": utc_now(),
        "repo_root": str(repo),
        "git_head_start": head_start,
        "git_head_end": head_end,
        "snapshot_consistent": head_start == head_end,
        "working_tree_status_start": status_start,
        "working_tree_status_end": status_end,
        "tracked_file_count": len(file_manifest),
        "secret_paths_excluded": skipped_secret_paths,
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
    json_write(out / "CHANGE_IMPACT_INDEX.json", {"metadata": metadata, "modules": module_impact, "symbols": symbol_impact, "environment_keys": env_registry, "redis_keys": redis_registry, "data_fields": data_registry, "api_routes": api_routes}, pretty=False)

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
            "env": len(env_by_path.get(module["path"], set())),
            "routes": len(routes_by_path.get(module["path"], [])),
            "exchange": len(exchange_by_path.get(module["path"], set())),
        }
        for module in python_modules
    ]
    markdown_write(out / "MODULE_BY_MODULE_INDEX.md", render_module_index(module_rows))

    return {
        "metadata": metadata,
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
