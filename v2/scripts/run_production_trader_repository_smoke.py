#!/usr/bin/env python3
"""Generate production trader repository/writer smoke evidence from safe artifacts.

This command validates already-produced repository, writer, and isolation evidence
for trader-scoped production storage. It does not connect to a production DB,
write repository state, call exchanges, submit/cancel orders, mutate leverage or
margin, touch the live gate, or enable live trading.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

JSON_SUFFIXES = {".json", ".jsonl"}
TRUE_VALUES = {"1", "true", "yes", "y", "on", "enabled", "pass", "passed", "ok", "verified"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "disabled", "fail", "failed", "missing", "pending", "none", "null"}
SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "access_token",
    "refresh_token",
    "authorization",
    "password_hash",
    "x_mbx_apikey",
    "x-mbx-apikey",
}
SAFE_SECRET_VALUES = {"", "none", "null", "redacted", "[redacted]", "masked", "hidden", "configured", "pending", "unavailable"}
SECRET_EXPOSURE_FLAG_KEYS = {"contains_credentials", "credentials_present", "secret_exposure_found", "secrets_exposed"}


@dataclass(frozen=True)
class LoadedArtifact:
    path: str
    payload: Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_files(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix.lower() in JSON_SUFFIXES:
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in JSON_SUFFIXES:
                    yield child


def _load_json_artifacts(paths: Sequence[Path], warnings: list[str]) -> list[LoadedArtifact]:
    loaded: list[LoadedArtifact] = []
    for path in _iter_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".jsonl":
                for index, line in enumerate(text.splitlines(), start=1):
                    stripped = line.strip()
                    if stripped:
                        loaded.append(LoadedArtifact(path=f"{path}:{index}", payload=json.loads(stripped)))
            else:
                loaded.append(LoadedArtifact(path=str(path), payload=json.loads(text)))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Skipped {path}: {exc}")
    return loaded


def _flatten(payload: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            yield key_text, value
            for child_key, child_value in _flatten(value):
                yield f"{key_text}.{child_key}", child_value
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            for child_key, child_value in _flatten(value):
                yield f"{index}.{child_key}", child_value


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _truthy_any(artifacts: Sequence[LoadedArtifact], aliases: set[str]) -> bool:
    normalized_aliases = {alias.lower() for alias in aliases}
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            if key.split(".")[-1].lower() in normalized_aliases and _as_bool(value) is True:
                return True
    return False


def _falsey_any(artifacts: Sequence[LoadedArtifact], aliases: set[str]) -> bool:
    normalized_aliases = {alias.lower() for alias in aliases}
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            if key.split(".")[-1].lower() in normalized_aliases and _as_bool(value) is False:
                return True
    return False


def _sensitive_value_seen(artifacts: Sequence[LoadedArtifact]) -> bool:
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            normalized_key = key.split(".")[-1].lower().replace("-", "_")
            if normalized_key in SECRET_EXPOSURE_FLAG_KEYS:
                continue
            if any(part.replace("-", "_") in normalized_key for part in SENSITIVE_KEY_PARTS):
                normalized_value = str(value).strip().lower()
                if normalized_value not in SAFE_SECRET_VALUES:
                    return True
    return False


def build_report(
    *,
    repository_evidence_paths: Sequence[Path],
    writer_evidence_paths: Sequence[Path],
    isolation_evidence_paths: Sequence[Path],
) -> dict[str, object]:
    warnings: list[str] = []
    repository_artifacts = _load_json_artifacts(repository_evidence_paths, warnings)
    writer_artifacts = _load_json_artifacts(writer_evidence_paths, warnings)
    isolation_artifacts = _load_json_artifacts(isolation_evidence_paths, warnings)
    all_artifacts = [*repository_artifacts, *writer_artifacts, *isolation_artifacts]

    if not repository_artifacts:
        warnings.append("No production repository evidence artifacts were found")
    if not writer_artifacts:
        warnings.append("No production writer evidence artifacts were found")
    if not isolation_artifacts:
        warnings.append("No trader isolation evidence artifacts were found")

    durable_user_repository = _truthy_any(all_artifacts, {"durable_user_repository", "production_user_repository", "users_repository_persistent"})
    durable_trader_account_repository = _truthy_any(all_artifacts, {"durable_trader_account_repository", "production_trader_account_repository", "trader_account_repository_persistent"})
    account_writer_persistence = _truthy_any(writer_artifacts, {"account_writer_persistence", "account_writer_persisted", "paper_account_writer_persisted"})
    activity_writer_persistence = _truthy_any(writer_artifacts, {"activity_writer_persistence", "positions_orders_executions_signals_persisted", "portfolio_activity_writers_persisted"})
    row_level_trader_isolation = _truthy_any(isolation_artifacts, {"row_level_trader_isolation", "trader_isolation_enforced", "tenant_isolation_enforced"})
    paper_account_uniqueness = _truthy_any(isolation_artifacts, {"paper_account_uniqueness", "paper_account_ids_unique", "paper_account_unique_constraint"})
    migration_applied = _truthy_any(repository_artifacts, {"migration_applied", "schema_migration_applied", "alembic_migration_applied"})
    backup_restore_verified = _truthy_any(repository_artifacts, {"backup_restore_verified", "backup_restore_tested"})
    contains_credentials = _truthy_any(all_artifacts, {"contains_credentials", "credentials_present"}) or _sensitive_value_seen(all_artifacts)
    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    exchange_mutation_enabled = _truthy_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    explicit_exchange_disabled = _falsey_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})

    missing_fields: list[str] = []
    required_flags = {
        "durable_user_repository": durable_user_repository,
        "durable_trader_account_repository": durable_trader_account_repository,
        "account_writer_persistence": account_writer_persistence,
        "activity_writer_persistence": activity_writer_persistence,
        "row_level_trader_isolation": row_level_trader_isolation,
        "paper_account_uniqueness": paper_account_uniqueness,
        "migration_applied": migration_applied,
        "backup_restore_verified": backup_restore_verified,
    }
    for field, value in required_flags.items():
        if not value:
            missing_fields.append(field)
    if contains_credentials:
        missing_fields.append("credential_free_repository_evidence")
    if live_trading_enabled or not explicit_live_disabled:
        missing_fields.append("live_trading_disabled")
    if exchange_mutation_enabled or not explicit_exchange_disabled:
        missing_fields.append("exchange_mutation_disabled")

    passed = bool(repository_artifacts and writer_artifacts and isolation_artifacts) and not missing_fields
    return {
        "production_trader_repository_smoke_status": "passed" if passed else "failed",
        "status": "passed" if passed else "failed",
        "source": "local_production_trader_repository_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "checked_at": _utc_now(),
        "durable_user_repository": durable_user_repository,
        "durable_trader_account_repository": durable_trader_account_repository,
        "account_writer_persistence": account_writer_persistence,
        "activity_writer_persistence": activity_writer_persistence,
        "row_level_trader_isolation": row_level_trader_isolation,
        "paper_account_uniqueness": paper_account_uniqueness,
        "migration_applied": migration_applied,
        "backup_restore_verified": backup_restore_verified,
        "contains_credentials": contains_credentials,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "files_checked": {
            "repository": len(repository_artifacts),
            "writer": len(writer_artifacts),
            "isolation": len(isolation_artifacts),
        },
        "artifact_paths": [artifact.path for artifact in all_artifacts[:100]],
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe production trader repository evidence smoke check")
    parser.add_argument("--repository-evidence-path", action="append", default=[], help="Repository evidence JSON/JSONL file or directory")
    parser.add_argument("--writer-evidence-path", action="append", default=[], help="Writer evidence JSON/JSONL file or directory")
    parser.add_argument("--isolation-evidence-path", action="append", default=[], help="Trader isolation evidence JSON/JSONL file or directory")
    parser.add_argument("--output", required=True, help="JSON artifact path to write")
    args = parser.parse_args(argv)

    report = build_report(
        repository_evidence_paths=_paths(args.repository_evidence_path),
        writer_evidence_paths=_paths(args.writer_evidence_path),
        isolation_evidence_paths=_paths(args.isolation_evidence_path),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["production_trader_repository_smoke_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
