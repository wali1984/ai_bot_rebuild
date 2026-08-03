#!/usr/bin/env python3
"""Validate production trader alert delivery/audit evidence from safe artifacts.

This command checks already-produced alert repository, notification delivery, and
alert audit evidence. It does not create alerts, send notifications, call an
exchange, submit/cancel orders, mutate leverage or margin, touch live-gate state,
or enable live trading.
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
    "webhook_url",
    "webhook_token",
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
            if isinstance(value, bool) or (isinstance(value, (int, float)) and value in {0, 1}):
                continue
            if any(part.replace("-", "_") in normalized_key for part in SENSITIVE_KEY_PARTS):
                normalized_value = str(value).strip().lower()
                if normalized_value not in SAFE_SECRET_VALUES:
                    return True
    return False


def build_report(
    *,
    repository_paths: Sequence[Path],
    delivery_paths: Sequence[Path],
    audit_paths: Sequence[Path],
) -> dict[str, object]:
    warnings: list[str] = []
    repository_artifacts = _load_json_artifacts(repository_paths, warnings)
    delivery_artifacts = _load_json_artifacts(delivery_paths, warnings)
    audit_artifacts = _load_json_artifacts(audit_paths, warnings)
    all_artifacts = [*repository_artifacts, *delivery_artifacts, *audit_artifacts]
    if not repository_artifacts:
        warnings.append("No production alert repository evidence artifacts were found")
    if not delivery_artifacts:
        warnings.append("No production alert delivery evidence artifacts were found")
    if not audit_artifacts:
        warnings.append("No production alert audit evidence artifacts were found")

    alert_repository_configured = _truthy_any(all_artifacts, {"alert_repository_configured", "production_alert_repository", "durable_alert_repository"})
    alert_crud_validated = _truthy_any(all_artifacts, {"alert_crud_validated", "alert_create_update_delete_validated", "alert_actions_validated"})
    trader_scope_enforced = _truthy_any(all_artifacts, {"trader_scope_enforced", "trader_id_scope_enforced", "row_level_trader_scope"})
    paper_account_scope_enforced = _truthy_any(all_artifacts, {"paper_account_scope_enforced", "paper_account_id_scope_enforced", "paper_account_match_required"})
    delivery_service_configured = _truthy_any(all_artifacts, {"delivery_service_configured", "notification_delivery_configured", "alert_delivery_service_configured"})
    notification_delivery_tested = _truthy_any(all_artifacts, {"notification_delivery_tested", "delivery_test_passed", "alert_delivery_validated"})
    delivery_secret_redacted = _truthy_any(all_artifacts, {"delivery_secret_redacted", "webhook_secret_redacted", "notification_secret_redacted"})
    audit_repository_durable = _truthy_any(all_artifacts, {"audit_repository_durable", "durable_alert_audit_repository", "alert_audit_store_durable"})
    audit_events_linked = _truthy_any(all_artifacts, {"audit_events_linked", "alert_audit_events_linked", "alert_action_audit_linked"})
    audit_retention_enforced = _truthy_any(all_artifacts, {"audit_retention_enforced", "alert_audit_retention_enforced", "retention_policy_enforced"})
    access_control_enforced = _truthy_any(all_artifacts, {"access_control_enforced", "admin_only_audit_access", "alert_access_control_enforced"})
    contains_credentials = _truthy_any(all_artifacts, {"contains_credentials", "credentials_present"}) or _sensitive_value_seen(all_artifacts)

    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_transport_enabled", "order_transport_submit_enabled"})
    exchange_mutation_enabled = _truthy_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    real_order_submitted = _truthy_any(all_artifacts, {"real_order_submitted", "live_order_submitted", "places_real_order"})
    live_gate_mutation_enabled = _truthy_any(all_artifacts, {"live_gate_mutation_enabled", "live_gate_mutated", "live_gate_armed"})

    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_transport_enabled", "order_transport_submit_enabled"})
    explicit_exchange_disabled = _falsey_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    explicit_no_real_submit = _falsey_any(all_artifacts, {"real_order_submitted", "live_order_submitted", "places_real_order"})
    explicit_no_live_gate = _falsey_any(all_artifacts, {"live_gate_mutation_enabled", "live_gate_mutated", "live_gate_armed"})

    required_flags = {
        "alert_repository_configured": alert_repository_configured,
        "alert_crud_validated": alert_crud_validated,
        "trader_scope_enforced": trader_scope_enforced,
        "paper_account_scope_enforced": paper_account_scope_enforced,
        "delivery_service_configured": delivery_service_configured,
        "notification_delivery_tested": notification_delivery_tested,
        "delivery_secret_redacted": delivery_secret_redacted,
        "audit_repository_durable": audit_repository_durable,
        "audit_events_linked": audit_events_linked,
        "audit_retention_enforced": audit_retention_enforced,
        "access_control_enforced": access_control_enforced,
    }
    missing_fields = [field for field, value in required_flags.items() if not value]
    if contains_credentials:
        missing_fields.append("credential_free_alert_delivery_audit_evidence")
    if live_trading_enabled or not explicit_live_disabled:
        missing_fields.append("live_trading_disabled")
    if exchange_mutation_enabled or not explicit_exchange_disabled:
        missing_fields.append("exchange_mutation_disabled")
    if real_order_submitted or not explicit_no_real_submit:
        missing_fields.append("real_order_submission_absent")
    if live_gate_mutation_enabled or not explicit_no_live_gate:
        missing_fields.append("live_gate_mutation_absent")

    passed = bool(repository_artifacts and delivery_artifacts and audit_artifacts) and not missing_fields
    return {
        "production_alert_delivery_audit_smoke_status": "passed" if passed else "failed",
        "alerts_crud_delivery_audit_repositories_status": "passed" if passed else "failed",
        "status": "passed" if passed else "failed",
        "source": "local_production_alert_delivery_audit_smoke",
        "source_type": "local_smoke",
        "mode": "paper",
        "checked_at": _utc_now(),
        "alert_repository_configured": alert_repository_configured,
        "alert_crud_validated": alert_crud_validated,
        "trader_scope_enforced": trader_scope_enforced,
        "paper_account_scope_enforced": paper_account_scope_enforced,
        "delivery_service_configured": delivery_service_configured,
        "notification_delivery_tested": notification_delivery_tested,
        "delivery_secret_redacted": delivery_secret_redacted,
        "audit_repository_durable": audit_repository_durable,
        "audit_events_linked": audit_events_linked,
        "audit_retention_enforced": audit_retention_enforced,
        "access_control_enforced": access_control_enforced,
        "contains_credentials": contains_credentials,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "real_order_submitted": real_order_submitted,
        "live_gate_mutation_enabled": live_gate_mutation_enabled,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "files_checked": {
            "repository": len(repository_artifacts),
            "delivery": len(delivery_artifacts),
            "audit": len(audit_artifacts),
        },
        "artifact_paths": [artifact.path for artifact in all_artifacts[:100]],
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe production alert delivery/audit evidence smoke check")
    parser.add_argument("--repository-evidence-path", action="append", default=[], help="Alert repository evidence JSON/JSONL file or directory")
    parser.add_argument("--delivery-evidence-path", action="append", default=[], help="Alert delivery evidence JSON/JSONL file or directory")
    parser.add_argument("--audit-evidence-path", action="append", default=[], help="Alert audit evidence JSON/JSONL file or directory")
    parser.add_argument("--output", required=True, help="JSON artifact path to write")
    args = parser.parse_args(argv)

    report = build_report(
        repository_paths=_paths(args.repository_evidence_path),
        delivery_paths=_paths(args.delivery_evidence_path),
        audit_paths=_paths(args.audit_evidence_path),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["production_alert_delivery_audit_smoke_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
