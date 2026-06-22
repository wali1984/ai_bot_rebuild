#!/usr/bin/env python3
"""Validate durable credential-vault evidence from safe local artifacts.

This command produces a sanitized artifact compatible with
ALPHAFORGE_DURABLE_CREDENTIAL_VAULT_ARTIFACT. It reads already-produced JSON or
JSONL evidence only. It never reads raw environment secrets, calls an exchange,
signs requests, submits/cancels orders, changes leverage/margin, mutates live
gates, or enables live trading.
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
SAFE_SECRET_VALUES = {"", "none", "null", "redacted", "[redacted]", "masked", "hidden", "configured", "pending", "unavailable"}
SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "password",
    "password_hash",
    "access_token",
    "refresh_token",
    "authorization",
    "x_mbx_apikey",
    "x-mbx-apikey",
    "credential_reference",
    "credential_ref",
}
SECRET_EXPOSURE_FLAG_KEYS = {
    "raw_credential_value_exposed",
    "contains_credentials",
    "credential_exposure_found",
    "secret_exposure_found",
    "secrets_exposed",
}


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
            if isinstance(value, bool) or (isinstance(value, (int, float)) and value in {0, 1}):
                continue
            if any(part.replace("-", "_") in normalized_key for part in SENSITIVE_KEY_PARTS):
                normalized_value = str(value).strip().lower()
                if normalized_value not in SAFE_SECRET_VALUES:
                    return True
    return False


def build_report(*, vault_evidence_paths: Sequence[Path], safety_evidence_paths: Sequence[Path]) -> dict[str, object]:
    warnings: list[str] = []
    vault_artifacts = _load_json_artifacts(vault_evidence_paths, warnings)
    safety_artifacts = _load_json_artifacts(safety_evidence_paths, warnings)
    all_artifacts = [*vault_artifacts, *safety_artifacts]

    if not vault_artifacts:
        warnings.append("No durable credential-vault evidence artifacts were found")
    if not safety_artifacts:
        warnings.append("No credential-vault safety evidence artifacts were found")

    durable_production_vault_integrated = _truthy_any(vault_artifacts, {"durable_production_vault_integrated", "production_vault_integrated", "durable_vault_integrated"})
    backend_only_secret_access = _truthy_any(vault_artifacts, {"backend_only_secret_access", "backend_only_access", "frontend_secret_access_blocked"})
    read_only_scope_enforced = _truthy_any(vault_artifacts, {"read_only_scope_enforced", "readonly_scope_enforced", "read_only_credentials_only"})
    credential_rotation_policy_configured = _truthy_any(vault_artifacts, {"credential_rotation_policy_configured", "rotation_policy_configured", "rotation_policy_present"})
    secret_redaction_verified = _truthy_any(vault_artifacts, {"secret_redaction_verified", "redaction_verified", "safe_payload_redaction_verified"})
    access_control_enforced = _truthy_any(vault_artifacts, {"access_control_enforced", "vault_access_control_enforced"})
    audit_logging_enabled = _truthy_any(vault_artifacts, {"audit_logging_enabled", "vault_audit_logging_enabled", "audit_log_enabled"})

    raw_credential_value_exposed = _truthy_any(all_artifacts, {"raw_credential_value_exposed", "credential_exposure_found", "secret_exposure_found"}) or _sensitive_value_seen(all_artifacts)
    contains_credentials = _truthy_any(all_artifacts, {"contains_credentials", "credentials_present"}) or raw_credential_value_exposed
    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    exchange_mutation_enabled = _truthy_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    order_write_enabled = _truthy_any(all_artifacts, {"order_write_enabled", "trading_enabled", "order_submit_enabled"})
    withdraw_enabled = _truthy_any(all_artifacts, {"withdraw_enabled", "withdrawal_enabled"})
    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    explicit_exchange_mutation_disabled = _falsey_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})

    required_flags = {
        "durable_production_vault_integrated": durable_production_vault_integrated,
        "backend_only_secret_access": backend_only_secret_access,
        "read_only_scope_enforced": read_only_scope_enforced,
        "credential_rotation_policy_configured": credential_rotation_policy_configured,
        "secret_redaction_verified": secret_redaction_verified,
        "access_control_enforced": access_control_enforced,
        "audit_logging_enabled": audit_logging_enabled,
    }
    missing_fields = [field for field, value in required_flags.items() if not value]
    forbidden_flags = {
        "no_raw_credential_exposure": raw_credential_value_exposed,
        "no_credentials_in_artifact": contains_credentials,
        "live_trading_disabled": live_trading_enabled or not explicit_live_disabled,
        "exchange_mutation_disabled": exchange_mutation_enabled or not explicit_exchange_mutation_disabled,
        "order_write_disabled": order_write_enabled,
        "withdraw_disabled": withdraw_enabled,
    }
    for field, failed in forbidden_flags.items():
        if failed:
            missing_fields.append(field)

    passed = bool(vault_artifacts and safety_artifacts) and not missing_fields
    return {
        "durable_credential_vault_status": "passed" if passed else "failed",
        "credential_vault_status": "passed" if passed else "failed",
        "source": "local_durable_credential_vault_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "generated_at": _utc_now(),
        "durable_production_vault_integrated": durable_production_vault_integrated,
        "backend_only_secret_access": backend_only_secret_access,
        "read_only_scope_enforced": read_only_scope_enforced,
        "credential_rotation_policy_configured": credential_rotation_policy_configured,
        "secret_redaction_verified": secret_redaction_verified,
        "access_control_enforced": access_control_enforced,
        "audit_logging_enabled": audit_logging_enabled,
        "raw_credential_value_exposed": raw_credential_value_exposed,
        "contains_credentials": contains_credentials,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "order_write_enabled": order_write_enabled,
        "withdraw_enabled": withdraw_enabled,
        "missing_fields": sorted(set(missing_fields)),
        "warnings": warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-evidence-path", action="append", type=Path, default=[])
    parser.add_argument("--safety-evidence-path", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_report(
        vault_evidence_paths=args.vault_evidence_path,
        safety_evidence_paths=args.safety_evidence_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["durable_credential_vault_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
