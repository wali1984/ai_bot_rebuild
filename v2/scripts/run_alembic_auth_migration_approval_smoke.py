#!/usr/bin/env python3
"""Validate Alembic auth/revocation/admin-audit migration approval evidence.

This command reads already-produced JSON/JSONL approval artifacts and writes a
sanitized readiness artifact. It does not run Alembic, connect to a database,
modify schemas, submit/cancel orders, mutate leverage/margin, touch live gates,
call exchanges, or enable live trading.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

JSON_SUFFIXES = {".json", ".jsonl"}
TRUE_VALUES = {"1", "true", "yes", "y", "on", "pass", "passed", "ok", "verified", "approved"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "fail", "failed", "missing", "pending", "none", "null"}
SENSITIVE_KEY_PARTS = {
    "api_key",
    "api_secret",
    "secret",
    "password",
    "password_hash",
    "access_token",
    "refresh_token",
    "authorization",
    "credential_ref",
}
SAFE_SECRET_VALUES = {"", "none", "null", "redacted", "[redacted]", "masked", "hidden", "configured", "pending", "unavailable"}


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
            if isinstance(value, bool) or (isinstance(value, (int, float)) and value in {0, 1}):
                continue
            if any(part in normalized_key for part in SENSITIVE_KEY_PARTS):
                normalized_value = str(value).strip().lower()
                if normalized_value not in SAFE_SECRET_VALUES:
                    return True
    return False


def build_report(*, approval_artifact_paths: Sequence[Path], safety_artifact_paths: Sequence[Path]) -> dict[str, object]:
    warnings: list[str] = []
    approval_artifacts = _load_json_artifacts(approval_artifact_paths, warnings)
    safety_artifacts = _load_json_artifacts(safety_artifact_paths, warnings)
    all_artifacts = [*approval_artifacts, *safety_artifacts]

    if not approval_artifacts:
        warnings.append("No Alembic migration approval artifacts were found")
    if not safety_artifacts:
        warnings.append("No migration safety artifacts were found")

    auth_user_migration_present = _truthy_any(approval_artifacts, {"auth_user_migration_present", "users_migration_present"})
    revocation_migration_present = _truthy_any(approval_artifacts, {"revocation_migration_present", "token_revocation_migration_present"})
    admin_audit_migration_present = _truthy_any(approval_artifacts, {"admin_audit_migration_present", "audit_migration_present"})
    migration_reviewed = _truthy_any(approval_artifacts, {"migration_reviewed", "review_approved", "schema_review_approved"})
    rollback_plan_reviewed = _truthy_any(approval_artifacts, {"rollback_plan_reviewed", "rollback_tested", "downgrade_reviewed"})
    retention_policy_reviewed = _truthy_any(approval_artifacts, {"retention_policy_reviewed", "audit_retention_reviewed"})
    uniqueness_constraints_reviewed = _truthy_any(approval_artifacts, {"uniqueness_constraints_reviewed", "paper_account_uniqueness_reviewed"})
    no_plaintext_password_columns = _truthy_any(approval_artifacts, {"no_plaintext_password_columns", "password_hash_only"})
    migration_not_applied_by_runner = _truthy_any(approval_artifacts, {"migration_not_applied_by_runner", "approval_only", "no_db_mutation_by_runner"})

    secret_exposure_found = _truthy_any(all_artifacts, {"secret_exposure_found", "contains_credentials"}) or _sensitive_value_seen(all_artifacts)
    database_mutation_performed = _truthy_any(all_artifacts, {"database_mutation_performed", "migration_applied", "schema_mutated"})
    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    exchange_mutation_enabled = _truthy_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    explicit_exchange_disabled = _falsey_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})

    required_flags = {
        "auth_user_migration_present": auth_user_migration_present,
        "revocation_migration_present": revocation_migration_present,
        "admin_audit_migration_present": admin_audit_migration_present,
        "migration_reviewed": migration_reviewed,
        "rollback_plan_reviewed": rollback_plan_reviewed,
        "retention_policy_reviewed": retention_policy_reviewed,
        "uniqueness_constraints_reviewed": uniqueness_constraints_reviewed,
        "no_plaintext_password_columns": no_plaintext_password_columns,
        "migration_not_applied_by_runner": migration_not_applied_by_runner,
    }
    missing_fields = [field for field, value in required_flags.items() if not value]
    forbidden_flags = {
        "no_secret_exposure": secret_exposure_found,
        "no_database_mutation_by_smoke_runner": database_mutation_performed,
        "live_trading_disabled": live_trading_enabled or not explicit_live_disabled,
        "exchange_mutation_disabled": exchange_mutation_enabled or not explicit_exchange_disabled,
    }
    for field, failed in forbidden_flags.items():
        if failed:
            missing_fields.append(field)

    passed = bool(approval_artifacts and safety_artifacts) and not missing_fields
    return {
        "alembic_auth_migration_approval_status": "passed" if passed else "failed",
        "source": "local_alembic_auth_migration_approval_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "generated_at": _utc_now(),
        "auth_user_migration_present": auth_user_migration_present,
        "revocation_migration_present": revocation_migration_present,
        "admin_audit_migration_present": admin_audit_migration_present,
        "migration_reviewed": migration_reviewed,
        "rollback_plan_reviewed": rollback_plan_reviewed,
        "retention_policy_reviewed": retention_policy_reviewed,
        "uniqueness_constraints_reviewed": uniqueness_constraints_reviewed,
        "no_plaintext_password_columns": no_plaintext_password_columns,
        "migration_not_applied_by_runner": migration_not_applied_by_runner,
        "secret_exposure_found": secret_exposure_found,
        "database_mutation_performed": database_mutation_performed,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "missing_fields": sorted(set(missing_fields)),
        "warnings": warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approval-artifact-path", action="append", type=Path, default=[])
    parser.add_argument("--safety-artifact-path", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(
        approval_artifact_paths=args.approval_artifact_path,
        safety_artifact_paths=args.safety_artifact_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["alembic_auth_migration_approval_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
