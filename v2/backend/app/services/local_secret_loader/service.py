"""Local-only loader for legacy secrets copied into a gitignored vault.

The loader has a narrow job:

- read only from ``.local_secrets/legacy_runtime``
- expose raw values only through explicit backend usage calls
- never include values in repr(), redacted dicts, or public payload helpers
- deny frontend, live trading, and exchange mutation use by default

It does not create approval tokens and does not verify exchange account
permissions. Exchange-trading use remains blocked unless a future caller
supplies a separate approval token and account-permission verification.
"""
from __future__ import annotations

import ast
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_VAULT_ROOT = Path(".local_secrets/legacy_runtime")
MANIFEST_NAME = "secret_manifest_redacted.json"

BACKEND_READONLY_DATA = "backend_readonly_data"
BACKEND_CONFIG = "backend_config"
FRONTEND_PUBLIC = "frontend_public"
LIVE_TRADING = "live_trading"
EXCHANGE_MUTATION = "exchange_mutation"

_ENV_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
_LIVE_USE_APPROVAL_TOKEN = "LOCAL_SECRET_LIVE_USE_OPERATOR_APPROVED"


class SecretAccessDenied(RuntimeError):
    """Raised when a caller requests an unsafe or unsupported secret use."""


@dataclass(frozen=True)
class LocalSecretRecord:
    source_path: str
    destination_path: str
    key_names: tuple[str, ...]
    key_count: int
    value_redacted: bool
    secret_type_guess: str
    required_by_subsystem: str
    live_use_allowed: bool

    @classmethod
    def from_manifest_record(cls, record: dict[str, Any], vault_root: Path) -> "LocalSecretRecord":
        destination = Path(str(record.get("destination_path") or ""))
        if not destination:
            raise SecretAccessDenied("secret manifest record has no destination path")
        try:
            destination.resolve().relative_to(vault_root.resolve())
        except ValueError as exc:
            raise SecretAccessDenied("secret destination escapes local vault") from exc
        return cls(
            source_path=str(record.get("source_path") or ""),
            destination_path=str(destination),
            key_names=tuple(str(k) for k in (record.get("key_names") or ())),
            key_count=int(record.get("key_count") or len(record.get("key_names") or ())),
            value_redacted=bool(record.get("value_redacted")),
            secret_type_guess=str(record.get("secret_type_guess") or "unknown"),
            required_by_subsystem=str(record.get("required_by_subsystem") or "unknown"),
            live_use_allowed=bool(record.get("live_use_allowed")),
        )

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "key_names": list(self.key_names),
            "key_count": self.key_count,
            "value_redacted": True,
            "secret_type_guess": self.secret_type_guess,
            "required_by_subsystem": self.required_by_subsystem,
            "live_use_allowed": False,
        }


class SecretValue:
    """A raw secret value wrapper that redacts itself in logs/repr."""

    __slots__ = ("key", "_value", "source_path", "secret_type_guess")

    def __init__(self, *, key: str, value: str, source_path: str, secret_type_guess: str) -> None:
        self.key = key
        self._value = value
        self.source_path = source_path
        self.secret_type_guess = secret_type_guess

    def reveal(
        self,
        *,
        usage: str = BACKEND_READONLY_DATA,
        approval_token: str | None = None,
        account_permission_verified: bool = False,
    ) -> str:
        if usage == FRONTEND_PUBLIC:
            raise SecretAccessDenied("secrets cannot be returned for frontend/public usage")
        if usage == LIVE_TRADING:
            if approval_token != _LIVE_USE_APPROVAL_TOKEN:
                raise SecretAccessDenied("live secret use requires explicit operator approval token")
        if usage == EXCHANGE_MUTATION:
            if approval_token != _LIVE_USE_APPROVAL_TOKEN or not account_permission_verified:
                raise SecretAccessDenied(
                    "exchange mutation use requires approval token and account permission verification"
                )
        if usage not in {BACKEND_READONLY_DATA, BACKEND_CONFIG, LIVE_TRADING, EXCHANGE_MUTATION}:
            raise SecretAccessDenied(f"unsupported secret usage: {usage}")
        return self._value

    def redacted_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value_redacted": True,
            "source_path": self.source_path,
            "secret_type_guess": self.secret_type_guess,
            "live_use_allowed": False,
        }

    def __repr__(self) -> str:
        return (
            "SecretValue("
            f"key={self.key!r}, value='<redacted>', source_path={self.source_path!r}, "
            f"secret_type_guess={self.secret_type_guess!r})"
        )

    __str__ = __repr__


class LocalSecretLoader:
    """Read local legacy secrets from the gitignored vault."""

    def __init__(self, vault_root: Path | str = DEFAULT_VAULT_ROOT) -> None:
        self.vault_root = Path(vault_root)
        self.manifest_path = self.vault_root / MANIFEST_NAME

    def _assert_vault_path(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.vault_root.resolve())
        except ValueError as exc:
            raise SecretAccessDenied("path escapes local secret vault") from exc
        return resolved

    def load_manifest(self) -> dict[str, Any]:
        self._assert_vault_path(self.manifest_path)
        if not self.manifest_path.exists():
            raise FileNotFoundError(f"local secret manifest not found: {self.manifest_path}")
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if manifest.get("value_redacted") is not True:
            raise SecretAccessDenied("local secret manifest is not marked redacted")
        if manifest.get("live_use_allowed") is not False:
            raise SecretAccessDenied("local secret manifest incorrectly allows live use")
        return manifest

    def records(self) -> tuple[LocalSecretRecord, ...]:
        manifest = self.load_manifest()
        return tuple(
            LocalSecretRecord.from_manifest_record(record, self.vault_root)
            for record in manifest.get("records", ())
            if record.get("copied") is True
        )

    def redacted_public_status(self) -> dict[str, Any]:
        manifest = self.load_manifest()
        records = self.records()
        key_names: list[str] = []
        for record in records:
            key_names.extend(record.key_names)
        return {
            "secrets_copied": bool(records),
            "file_count": len(records),
            "key_count": int(manifest.get("key_count_total") or sum(r.key_count for r in records)),
            "key_names": sorted(set(key_names)),
            "value_redacted": True,
            "gitignored_required": True,
            "live_use_allowed": False,
            "frontend_public_contains_raw_values": False,
            "records": [record.redacted_dict() for record in records],
        }

    def get(self, key: str, *, usage: str = BACKEND_READONLY_DATA) -> SecretValue:
        if usage == FRONTEND_PUBLIC:
            raise SecretAccessDenied("secrets cannot be returned for frontend/public usage")
        for record in self.records():
            values = self._load_record_values(record)
            if key in values:
                return SecretValue(
                    key=key,
                    value=values[key],
                    source_path=record.destination_path,
                    secret_type_guess=record.secret_type_guess,
                )
        raise KeyError(key)

    def get_many(
        self,
        keys: Iterable[str],
        *,
        usage: str = BACKEND_READONLY_DATA,
    ) -> dict[str, SecretValue]:
        return {key: self.get(key, usage=usage) for key in keys}

    def _load_record_values(self, record: LocalSecretRecord) -> dict[str, str]:
        path = self._assert_vault_path(Path(record.destination_path))
        if not path.exists() or not path.is_file():
            return {}
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.name.startswith(".env"):
            return _parse_env_text(text)
        if path.suffix == ".json":
            return _parse_json_values(text)
        if path.suffix == ".py":
            return _parse_python_assignments(text)
        return {}


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_ASSIGNMENT.match(line)
        if not match:
            continue
        key, value = match.groups()
        values[key] = _strip_env_quotes(value)
    return values


def _parse_json_values(text: str) -> dict[str, str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    values: dict[str, str] = {}

    def walk(obj: Any, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                next_key = str(key) if not prefix else f"{prefix}.{key}"
                walk(value, next_key)
        elif isinstance(obj, (str, int, float, bool)) and prefix:
            values[prefix] = str(obj)

    walk(parsed)
    return values


def _parse_python_assignments(text: str) -> dict[str, str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets.extend(node.targets)
            value_node = node.value
        else:
            targets.append(node.target)
            value_node = node.value
        if value_node is None:
            continue
        try:
            value = ast.literal_eval(value_node)
        except Exception:
            continue
        if not isinstance(value, (str, int, float, bool)):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                values[target.id] = str(value)
            elif isinstance(target, ast.Attribute):
                values[target.attr] = str(value)
    return values
