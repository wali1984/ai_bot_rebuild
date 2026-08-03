#!/usr/bin/env python3
"""Validate production paper action evidence from safe artifacts.

This command checks already-produced paper submit/cancel/fill validation evidence.
It does not call paper endpoints, write repository rows, connect to an exchange,
submit/cancel real orders, mutate leverage or margin, touch live-gate state, or
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
        warnings.append("No production paper action validation evidence artifacts were found")

    paper_submit_validated = _truthy_any(artifacts, {"paper_submit_validated", "paper_submit_validation_passed", "verified_paper_submit", "submit_validation_passed"})
    paper_cancel_validated = _truthy_any(artifacts, {"paper_cancel_validated", "paper_cancel_validation_passed", "verified_paper_cancel", "cancel_validation_passed"})
    paper_fill_validated = _truthy_any(artifacts, {"paper_fill_validated", "paper_fill_validation_passed", "verified_paper_fill", "fill_validation_passed"})
    paper_fill_disabled_by_policy = _truthy_any(artifacts, {"paper_fill_disabled_by_policy", "fill_disabled_by_policy", "manual_fill_policy", "no_auto_fill_policy"})
    production_paper_actions_fail_closed = _truthy_any(artifacts, {"production_paper_actions_fail_closed", "paper_actions_fail_closed", "fail_closed_without_verified_service"})
    service_verified_paper_only = _truthy_any(artifacts, {"service_verified_paper_only", "paper_only_service_verified", "verified_paper_only_execution_service"})
    trader_scope_enforced = _truthy_any(artifacts, {"trader_scope_enforced", "trader_id_scope_enforced", "row_level_trader_scope"})
    paper_account_scope_enforced = _truthy_any(artifacts, {"paper_account_scope_enforced", "paper_account_id_scope_enforced", "paper_account_match_required"})
    backend_owned_order_ids = _truthy_any(artifacts, {"backend_owned_order_ids", "local_order_ids_backend_owned", "paper_order_ids_backend_owned"})
    durable_repository_verified = _truthy_any(artifacts, {"durable_repository_verified", "production_repository_verified", "paper_order_repository_verified"})
    audit_event_linked = _truthy_any(artifacts, {"audit_event_linked", "paper_order_audit_linked", "audit_ledger_linked"})
    contains_credentials = _truthy_any(artifacts, {"contains_credentials", "credentials_present"}) or _sensitive_value_seen(artifacts)

    live_transport_enabled = _truthy_any(artifacts, {"live_transport_enabled", "live_trading_enabled", "order_transport_submit_enabled"})
    exchange_mutation_enabled = _truthy_any(artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    real_order_submitted = _truthy_any(artifacts, {"real_order_submitted", "live_order_submitted", "places_real_order"})
    real_order_cancelled = _truthy_any(artifacts, {"real_order_cancelled", "live_order_cancelled", "exchange_cancel_submitted"})
    leverage_mutation_enabled = _truthy_any(artifacts, {"leverage_mutation_enabled", "allow_leverage_mutation", "leverage_changed"})
    margin_mutation_enabled = _truthy_any(artifacts, {"margin_mutation_enabled", "allow_margin_mode_mutation", "margin_mode_changed"})
    live_gate_mutation_enabled = _truthy_any(artifacts, {"live_gate_mutation_enabled", "live_gate_mutated", "live_gate_armed"})

    explicit_live_disabled = _falsey_any(artifacts, {"live_transport_enabled", "live_trading_enabled", "order_transport_submit_enabled"})
    explicit_exchange_disabled = _falsey_any(artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    explicit_no_real_submit = _falsey_any(artifacts, {"real_order_submitted", "live_order_submitted", "places_real_order"})
    explicit_no_real_cancel = _falsey_any(artifacts, {"real_order_cancelled", "live_order_cancelled", "exchange_cancel_submitted"})
    explicit_no_leverage = _falsey_any(artifacts, {"leverage_mutation_enabled", "allow_leverage_mutation", "leverage_changed"})
    explicit_no_margin = _falsey_any(artifacts, {"margin_mutation_enabled", "allow_margin_mode_mutation", "margin_mode_changed"})
    explicit_no_live_gate = _falsey_any(artifacts, {"live_gate_mutation_enabled", "live_gate_mutated", "live_gate_armed"})

    required_flags = {
        "paper_submit_validated": paper_submit_validated,
        "paper_cancel_validated": paper_cancel_validated,
        "paper_fill_validated_or_policy_disabled": paper_fill_validated or paper_fill_disabled_by_policy,
        "production_paper_actions_fail_closed": production_paper_actions_fail_closed,
        "service_verified_paper_only": service_verified_paper_only,
        "trader_scope_enforced": trader_scope_enforced,
        "paper_account_scope_enforced": paper_account_scope_enforced,
        "backend_owned_order_ids": backend_owned_order_ids,
        "durable_repository_verified": durable_repository_verified,
        "audit_event_linked": audit_event_linked,
    }
    missing_fields = [field for field, value in required_flags.items() if not value]
    if contains_credentials:
        missing_fields.append("credential_free_paper_action_evidence")
    if live_transport_enabled or not explicit_live_disabled:
        missing_fields.append("live_transport_disabled")
    if exchange_mutation_enabled or not explicit_exchange_disabled:
        missing_fields.append("exchange_mutation_disabled")
    if real_order_submitted or not explicit_no_real_submit:
        missing_fields.append("real_order_submission_absent")
    if real_order_cancelled or not explicit_no_real_cancel:
        missing_fields.append("real_order_cancellation_absent")
    if leverage_mutation_enabled or not explicit_no_leverage:
        missing_fields.append("leverage_mutation_absent")
    if margin_mutation_enabled or not explicit_no_margin:
        missing_fields.append("margin_mutation_absent")
    if live_gate_mutation_enabled or not explicit_no_live_gate:
        missing_fields.append("live_gate_mutation_absent")

    passed = bool(artifacts) and not missing_fields
    return {
        "production_paper_action_validation_smoke_status": "passed" if passed else "failed",
        "production_paper_submit_cancel_validation_status": "passed" if passed else "failed",
        "status": "passed" if passed else "failed",
        "source": "local_production_paper_action_validation_smoke",
        "source_type": "local_smoke",
        "mode": "paper",
        "checked_at": _utc_now(),
        "paper_submit_validated": paper_submit_validated,
        "paper_cancel_validated": paper_cancel_validated,
        "paper_fill_validated": paper_fill_validated,
        "paper_fill_disabled_by_policy": paper_fill_disabled_by_policy,
        "production_paper_actions_fail_closed": production_paper_actions_fail_closed,
        "service_verified_paper_only": service_verified_paper_only,
        "trader_scope_enforced": trader_scope_enforced,
        "paper_account_scope_enforced": paper_account_scope_enforced,
        "backend_owned_order_ids": backend_owned_order_ids,
        "durable_repository_verified": durable_repository_verified,
        "audit_event_linked": audit_event_linked,
        "contains_credentials": contains_credentials,
        "live_transport_enabled": live_transport_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "real_order_submitted": real_order_submitted,
        "real_order_cancelled": real_order_cancelled,
        "leverage_mutation_enabled": leverage_mutation_enabled,
        "margin_mutation_enabled": margin_mutation_enabled,
        "live_gate_mutation_enabled": live_gate_mutation_enabled,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "files_checked": len(artifacts),
        "artifact_paths": [artifact.path for artifact in artifacts[:100]],
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe production paper action validation evidence smoke check")
    parser.add_argument("--evidence-path", action="append", default=[], help="Paper action validation evidence JSON/JSONL file or directory")
    parser.add_argument("--output", required=True, help="JSON artifact path to write")
    args = parser.parse_args(argv)

    report = build_report(evidence_paths=_paths(args.evidence_path))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["production_paper_action_validation_smoke_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
