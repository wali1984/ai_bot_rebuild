#!/usr/bin/env python3
"""Validate auth/session hardening evidence from already-produced safe artifacts.

This command reads local JSON/JSONL evidence files and writes a sanitized smoke
artifact for production auth/session readiness. It does not call auth endpoints,
create tokens, log in users, mutate roles, touch exchanges, submit/cancel orders,
change leverage/margin, or mutate live gates.
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
    "cookie",
    "session_cookie",
    "jwt",
    "bearer",
    "credential_reference",
    "credential_ref",
}
SECRET_EXPOSURE_FLAG_KEYS = {
    "contains_credentials",
    "token_exposure_found",
    "plaintext_password_exposure_found",
    "raw_secret_visible",
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


def build_report(
    *,
    session_evidence_paths: Sequence[Path],
    rbac_evidence_paths: Sequence[Path],
    safety_evidence_paths: Sequence[Path],
) -> dict[str, object]:
    warnings: list[str] = []
    session_artifacts = _load_json_artifacts(session_evidence_paths, warnings)
    rbac_artifacts = _load_json_artifacts(rbac_evidence_paths, warnings)
    safety_artifacts = _load_json_artifacts(safety_evidence_paths, warnings)
    all_artifacts = [*session_artifacts, *rbac_artifacts, *safety_artifacts]

    if not session_artifacts:
        warnings.append("No auth/session evidence artifacts were found")
    if not rbac_artifacts:
        warnings.append("No backend RBAC denial evidence artifacts were found")
    if not safety_artifacts:
        warnings.append("No no-live-mutation auth safety evidence artifacts were found")

    production_auth_secret_configured = _truthy_any(session_artifacts, {"production_auth_secret_configured", "auth_secret_configured"})
    auth_secret_strength_verified = _truthy_any(session_artifacts, {"auth_secret_strength_verified", "auth_secret_min_length_ok", "strong_auth_secret"})
    issuer_configured = _truthy_any(session_artifacts, {"issuer_configured", "auth_issuer_configured"})
    audience_configured = _truthy_any(session_artifacts, {"audience_configured", "auth_audience_configured"})
    secure_cookie_enabled = _truthy_any(session_artifacts, {"secure_cookie_enabled", "cookie_secure", "cookie_secure_enabled"})
    cookie_samesite_configured = _truthy_any(session_artifacts, {"cookie_samesite_configured", "samesite_configured"})
    session_ttl_enforced = _truthy_any(session_artifacts, {"session_ttl_enforced", "session_minutes_configured", "ttl_enforced"})
    refresh_rotation_enabled = _truthy_any(session_artifacts, {"refresh_rotation_enabled", "refresh_revokes_presented_token"})
    revocation_store_durable = _truthy_any(session_artifacts, {"revocation_store_durable", "durable_revocation_store"})
    session_version_invalidation_enabled = _truthy_any(session_artifacts, {"session_version_invalidation_enabled", "session_version_claim_enforced"})
    password_change_revokes_sessions = _truthy_any(session_artifacts, {"password_change_revokes_sessions", "password_change_session_revocation"})
    admin_step_up_enabled = _truthy_any(session_artifacts, {"admin_step_up_enabled", "mfa_step_up_enabled", "admin_step_up_configured"})
    backend_role_checks_enforced = _truthy_any(rbac_artifacts, {"backend_role_checks_enforced", "rbac_checked", "backend_rbac_enforced"})
    unauthorized_admin_blocked = _truthy_any(rbac_artifacts, {"unauthorized_admin_blocked", "admin_unauthenticated_blocked", "unauthenticated_admin_blocked"})
    superadmin_admin_rejected = _truthy_any(rbac_artifacts, {"superadmin_admin_rejected", "admin_rejected_from_superadmin"})

    contains_credentials = _truthy_any(all_artifacts, {"contains_credentials", "credentials_present", "raw_secret_visible", "secret_exposure_found"}) or _sensitive_value_seen(all_artifacts)
    token_exposure_found = _truthy_any(all_artifacts, {"token_exposure_found", "access_token_visible", "refresh_token_visible"})
    plaintext_password_exposure_found = _truthy_any(all_artifacts, {"plaintext_password_exposure_found", "plaintext_password_visible"})
    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    exchange_mutation_enabled = _truthy_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    live_submit_available = _truthy_any(all_artifacts, {"live_submit_available", "live_order_submit_available"})
    live_cancel_available = _truthy_any(all_artifacts, {"live_cancel_available", "live_order_cancel_available"})
    leverage_mutation_available = _truthy_any(all_artifacts, {"leverage_mutation_available", "leverage_change_available"})
    margin_mutation_available = _truthy_any(all_artifacts, {"margin_mutation_available", "margin_mode_change_available"})

    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    explicit_exchange_mutation_disabled = _falsey_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})

    required_flags = {
        "production_auth_secret_configured": production_auth_secret_configured,
        "auth_secret_strength_verified": auth_secret_strength_verified,
        "issuer_configured": issuer_configured,
        "audience_configured": audience_configured,
        "secure_cookie_enabled": secure_cookie_enabled,
        "cookie_samesite_configured": cookie_samesite_configured,
        "session_ttl_enforced": session_ttl_enforced,
        "refresh_rotation_enabled": refresh_rotation_enabled,
        "revocation_store_durable": revocation_store_durable,
        "session_version_invalidation_enabled": session_version_invalidation_enabled,
        "password_change_revokes_sessions": password_change_revokes_sessions,
        "admin_step_up_enabled": admin_step_up_enabled,
        "backend_role_checks_enforced": backend_role_checks_enforced,
        "unauthorized_admin_blocked": unauthorized_admin_blocked,
        "superadmin_admin_rejected": superadmin_admin_rejected,
    }
    missing_fields = [field for field, value in required_flags.items() if not value]
    forbidden_flags = {
        "no_credential_exposure": contains_credentials,
        "no_token_exposure": token_exposure_found,
        "no_plaintext_password_exposure": plaintext_password_exposure_found,
        "live_trading_disabled": live_trading_enabled or not explicit_live_disabled,
        "exchange_mutation_disabled": exchange_mutation_enabled or not explicit_exchange_mutation_disabled,
        "live_submit_unavailable": live_submit_available,
        "live_cancel_unavailable": live_cancel_available,
        "leverage_mutation_unavailable": leverage_mutation_available,
        "margin_mutation_unavailable": margin_mutation_available,
    }
    for field, failed in forbidden_flags.items():
        if failed:
            missing_fields.append(field)

    passed = bool(session_artifacts and rbac_artifacts and safety_artifacts) and not missing_fields
    return {
        "production_auth_session_hardening_status": "passed" if passed else "failed",
        "auth_session_hardening_smoke_status": "passed" if passed else "failed",
        "source": "local_auth_session_hardening_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "generated_at": _utc_now(),
        "production_auth_secret_configured": production_auth_secret_configured,
        "auth_secret_strength_verified": auth_secret_strength_verified,
        "issuer_configured": issuer_configured,
        "audience_configured": audience_configured,
        "secure_cookie_enabled": secure_cookie_enabled,
        "cookie_samesite_configured": cookie_samesite_configured,
        "session_ttl_enforced": session_ttl_enforced,
        "refresh_rotation_enabled": refresh_rotation_enabled,
        "revocation_store_durable": revocation_store_durable,
        "session_version_invalidation_enabled": session_version_invalidation_enabled,
        "password_change_revokes_sessions": password_change_revokes_sessions,
        "admin_step_up_enabled": admin_step_up_enabled,
        "backend_role_checks_enforced": backend_role_checks_enforced,
        "unauthorized_admin_blocked": unauthorized_admin_blocked,
        "superadmin_admin_rejected": superadmin_admin_rejected,
        "contains_credentials": contains_credentials,
        "token_exposure_found": token_exposure_found,
        "plaintext_password_exposure_found": plaintext_password_exposure_found,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "live_submit_available": live_submit_available,
        "live_cancel_available": live_cancel_available,
        "leverage_mutation_available": leverage_mutation_available,
        "margin_mutation_available": margin_mutation_available,
        "missing_fields": sorted(set(missing_fields)),
        "warnings": warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-evidence-path", action="append", type=Path, default=[])
    parser.add_argument("--rbac-evidence-path", action="append", type=Path, default=[])
    parser.add_argument("--safety-evidence-path", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_report(
        session_evidence_paths=args.session_evidence_path,
        rbac_evidence_paths=args.rbac_evidence_path,
        safety_evidence_paths=args.safety_evidence_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["production_auth_session_hardening_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
