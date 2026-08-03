#!/usr/bin/env python3
"""Validate durable paper audit policy evidence from safe artifacts.

This command checks already-produced policy/audit evidence for a production
paper-audit setup. It does not write paper audit rows, connect to an exchange,
submit/cancel orders, mutate leverage or margin, touch live-gate state, or
enable live trading.
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
    "private_key",
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


def build_report(*, evidence_paths: Sequence[Path]) -> dict[str, object]:
    warnings: list[str] = []
    artifacts = _load_json_artifacts(evidence_paths, warnings)
    if not artifacts:
        warnings.append("No durable paper audit policy evidence artifacts were found")

    production_durable_store = _truthy_any(artifacts, {"production_durable_store", "durable_audit_store", "durable_paper_audit_store"})
    retention_enforced = _truthy_any(artifacts, {"retention_enforced", "retention_policy_enforced", "paper_audit_retention_enforced"})
    production_writer_hardened = _truthy_any(artifacts, {"production_writer_hardened", "writer_hardening_verified", "audit_writer_hardened"})
    audit_verification_passed = _truthy_any(artifacts, {"audit_verification_passed", "audit_chain_verification_passed", "audit_integrity_verified"})
    backup_restore_verified = _truthy_any(artifacts, {"backup_restore_verified", "backup_restore_tested", "audit_backup_restore_verified"})
    access_control_enforced = _truthy_any(artifacts, {"access_control_enforced", "audit_access_control_enforced", "admin_only_audit_access"})
    contains_credentials = _truthy_any(artifacts, {"contains_credentials", "credentials_present"}) or _sensitive_value_seen(artifacts)
    live_transport_enabled = _truthy_any(artifacts, {"live_transport_enabled", "live_trading_enabled", "order_transport_submit_enabled"})
    exchange_mutation_enabled = _truthy_any(artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    explicit_live_disabled = _falsey_any(artifacts, {"live_transport_enabled", "live_trading_enabled", "order_transport_submit_enabled"})
    explicit_exchange_disabled = _falsey_any(artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})

    required_flags = {
        "production_durable_store": production_durable_store,
        "retention_enforced": retention_enforced,
        "production_writer_hardened": production_writer_hardened,
        "audit_verification_passed": audit_verification_passed,
        "backup_restore_verified": backup_restore_verified,
        "access_control_enforced": access_control_enforced,
    }
    missing_fields = [field for field, value in required_flags.items() if not value]
    if contains_credentials:
        missing_fields.append("credential_free_audit_policy_evidence")
    if live_transport_enabled or not explicit_live_disabled:
        missing_fields.append("live_transport_disabled")
    if exchange_mutation_enabled or not explicit_exchange_disabled:
        missing_fields.append("exchange_mutation_disabled")

    passed = bool(artifacts) and not missing_fields
    return {
        "durable_paper_audit_policy_smoke_status": "passed" if passed else "failed",
        "durable_paper_audit_policy_status": "passed" if passed else "failed",
        "status": "passed" if passed else "failed",
        "source": "local_durable_paper_audit_policy_smoke",
        "source_type": "local_smoke",
        "mode": "paper",
        "checked_at": _utc_now(),
        "production_durable_store": production_durable_store,
        "retention_enforced": retention_enforced,
        "production_writer_hardened": production_writer_hardened,
        "audit_verification_passed": audit_verification_passed,
        "backup_restore_verified": backup_restore_verified,
        "access_control_enforced": access_control_enforced,
        "contains_credentials": contains_credentials,
        "live_transport_enabled": live_transport_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "files_checked": len(artifacts),
        "artifact_paths": [artifact.path for artifact in artifacts[:100]],
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe durable paper audit policy evidence smoke check")
    parser.add_argument("--evidence-path", action="append", default=[], help="Durable audit policy evidence JSON/JSONL file or directory")
    parser.add_argument("--output", required=True, help="JSON artifact path to write")
    args = parser.parse_args(argv)

    report = build_report(evidence_paths=_paths(args.evidence_path))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["durable_paper_audit_policy_smoke_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
