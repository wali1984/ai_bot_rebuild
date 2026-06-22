"""Safe backend-only credential status helpers.

This module reports whether account-specific credential material appears to be
configured in the backend environment. It never returns raw credential values,
never signs requests, never calls an exchange, and never enables live trading.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NotRequired, TypedDict


class SafeCredentialStatus(TypedDict):
    credential_ref: NotRequired[str | None]
    credential_scope: str
    source_type: str
    configured: bool
    status: str
    read_only_required: bool
    live_trading_enabled: bool
    binding_blocked_reason: str | None
    raw_credential_value_exposed: bool
    checked_at: str


class CredentialVaultReadiness(TypedDict):
    status: str
    backend_only: bool
    environment_binding_supported: bool
    local_vault_file_supported: bool
    local_vault_file_configured: bool
    durable_production_vault_integrated: bool
    durable_production_vault_artifact_configured: bool
    durable_production_vault_artifact_valid: bool
    durable_production_vault_artifact_status: str
    credential_rotation_policy_status: str
    permission_probe_status: str
    permission_probe_artifact_configured: bool
    permission_probe_artifact_valid: bool
    permission_probe_artifact_status: str
    signed_read_validation_status: str
    signed_read_validation_artifact_configured: bool
    signed_read_validation_artifact_valid: bool
    signed_read_validation_artifact_status: str
    secret_redaction_smoke_status: str
    secret_redaction_smoke_artifact_configured: bool
    secret_redaction_smoke_artifact_valid: bool
    secret_redaction_smoke_artifact_status: str
    raw_credential_value_exposed: bool
    live_trading_enabled: bool
    exchange_mutation_enabled: bool
    missing_fields: list[str]
    warnings: list[str]
    checked_at: str


@dataclass(frozen=True)
class BackendCredentialBinding:
    """Backend-only credential binding.

    The raw values in this object must never be returned from API payloads.
    Public/user-facing payloads should use ``safe_status`` only.
    """

    credential_ref: str | None
    api_key: str
    api_secret: str
    safe_status: SafeCredentialStatus

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _env_prefix(credential_ref: str) -> str:
    return re.sub(r"[^A-Z0-9_]", "_", credential_ref.upper()).strip("_")


def _has_env_value(names: list[str]) -> bool:
    return any(bool(os.environ.get(name, "").strip()) for name in names)


def _first_env_value(names: list[str]) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _credential_vault_file_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_CREDENTIAL_VAULT_FILE", "").strip()
    return Path(configured) if configured else None


def _signed_read_validation_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_SIGNED_READ_VALIDATION_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _credential_permission_probe_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_CREDENTIAL_PERMISSION_PROBE_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _secret_redaction_smoke_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_SECRET_REDACTION_SMOKE_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _durable_credential_vault_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_DURABLE_CREDENTIAL_VAULT_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _durable_credential_vault_evidence() -> dict[str, Any]:
    path = _durable_credential_vault_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Durable credential vault artifact is not configured",
            "payload": {},
        }
    if not path.exists():
        return {
            "configured": True,
            "valid": False,
            "status": "missing",
            "warning": "Durable credential vault artifact is missing",
            "payload": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Durable credential vault artifact is unreadable",
            "payload": {},
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Durable credential vault artifact must be a JSON object",
            "payload": {},
        }
    raw_status = str(
        payload.get("durable_credential_vault_status")
        or payload.get("credential_vault_status")
        or payload.get("status")
        or ""
    ).strip().lower()
    required_true = (
        "durable_production_vault_integrated",
        "backend_only_secret_access",
        "read_only_scope_enforced",
        "credential_rotation_policy_configured",
        "secret_redaction_verified",
        "access_control_enforced",
        "audit_logging_enabled",
    )
    required_false = (
        "raw_credential_value_exposed",
        "contains_credentials",
        "live_trading_enabled",
        "exchange_mutation_enabled",
        "order_write_enabled",
        "withdraw_enabled",
    )
    valid = (
        raw_status in {"pass", "passed", "ok", "verified"}
        and all(payload.get(field) is True for field in required_true)
        and all(payload.get(field) is False for field in required_false)
        and not payload.get("missing_fields")
    )
    return {
        "configured": True,
        "valid": valid,
        "status": "passed" if valid else "rejected",
        "warning": None
        if valid
        else "Durable credential vault artifact must prove production vault integration, backend-only access, read-only scope, rotation policy, redaction, access control, audit logging, and no live/exchange mutation",
        "payload": payload,
    }


def _secret_redaction_smoke_evidence() -> dict[str, Any]:
    path = _secret_redaction_smoke_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Secret redaction smoke artifact is not configured",
        }
    if not path.exists():
        return {
            "configured": True,
            "valid": False,
            "status": "missing",
            "warning": "Secret redaction smoke artifact is missing",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Secret redaction smoke artifact is unreadable",
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Secret redaction smoke artifact must be a JSON object",
        }
    raw_status = str(payload.get("secret_redaction_smoke_status") or payload.get("status") or "").strip().lower()
    no_raw_credentials = payload.get("raw_credential_value_exposed") is False
    no_api_key = payload.get("api_key_exposed") is False
    no_api_secret = payload.get("api_secret_exposed") is False
    no_access_token = payload.get("access_token_exposed") is False
    safe_payloads = payload.get("safe_api_payloads_checked") is True or payload.get("frontend_payloads_checked") is True
    logs_checked = payload.get("logs_checked") is True
    screenshots_checked = payload.get("screenshots_checked") is True
    valid = (
        raw_status in {"pass", "passed", "ok"}
        and no_raw_credentials
        and no_api_key
        and no_api_secret
        and no_access_token
        and safe_payloads
        and logs_checked
        and screenshots_checked
    )
    return {
        "configured": True,
        "valid": valid,
        "status": "passed" if valid else "rejected",
        "warning": None
        if valid
        else "Secret redaction smoke artifact does not prove payload/log/screenshot secret redaction",
    }


def _permission_probe_evidence() -> dict[str, Any]:
    path = _credential_permission_probe_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Credential permission probe artifact is not configured",
        }
    if not path.exists():
        return {
            "configured": True,
            "valid": False,
            "status": "missing",
            "warning": "Credential permission probe artifact is missing",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Credential permission probe artifact is unreadable",
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Credential permission probe artifact must be a JSON object",
        }
    raw_status = str(payload.get("permission_probe_status") or payload.get("status") or "").strip().lower()
    read_only = (
        payload.get("read_only") is True
        or payload.get("read_only_permissions_validated") is True
        or payload.get("read_only_required") is True
    )
    live_disabled = payload.get("live_trading_enabled") is False
    exchange_mutation_disabled = payload.get("exchange_mutation_enabled") is False
    order_write_disabled = payload.get("order_write_enabled") is False or payload.get("trading_enabled") is False
    withdraw_disabled = payload.get("withdraw_enabled") is False
    valid = (
        raw_status in {"pass", "passed", "ok"}
        and read_only
        and live_disabled
        and exchange_mutation_disabled
        and order_write_disabled
        and withdraw_disabled
    )
    return {
        "configured": True,
        "valid": valid,
        "status": "passed" if valid else "rejected",
        "warning": None
        if valid
        else "Credential permission probe artifact does not prove read-only/no-withdraw/no-order-write status",
    }


def _signed_read_validation_evidence() -> dict[str, Any]:
    path = _signed_read_validation_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Signed read-only account validation artifact is not configured",
        }
    if not path.exists():
        return {
            "configured": True,
            "valid": False,
            "status": "missing",
            "warning": "Signed read-only account validation artifact is missing",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Signed read-only account validation artifact is unreadable",
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Signed read-only account validation artifact must be a JSON object",
        }
    raw_status = str(payload.get("signed_read_validation_status") or payload.get("status") or "").strip().lower()
    read_only = payload.get("read_only") is True or payload.get("read_only_required") is True
    live_disabled = payload.get("live_trading_enabled") is False
    exchange_mutation_disabled = payload.get("exchange_mutation_enabled") is False
    valid = raw_status in {"pass", "passed", "ok"} and read_only and live_disabled and exchange_mutation_disabled
    return {
        "configured": True,
        "valid": valid,
        "status": "passed" if valid else "rejected",
        "warning": None
        if valid
        else "Signed read-only account validation artifact does not prove read-only/no-mutation status",
    }


def _read_vault_entry(credential_ref: str | None) -> dict[str, Any]:
    if not credential_ref:
        return {}
    path = _credential_vault_file_path()
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    credentials = payload.get("credentials") if isinstance(payload.get("credentials"), dict) else payload
    entry = credentials.get(credential_ref) if isinstance(credentials, dict) else None
    return entry if isinstance(entry, dict) else {}


def _vault_value(entry: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = entry.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _credential_values(credential_ref: str | None) -> tuple[str, str, str]:
    key_names, secret_names = _credential_env_names(credential_ref)
    api_key = _first_env_value(key_names)
    api_secret = _first_env_value(secret_names)
    if api_key or api_secret:
        return api_key, api_secret, "environment"
    entry = _read_vault_entry(credential_ref)
    vault_key = _vault_value(entry, ("api_key", "key", "read_only_api_key"))
    vault_secret = _vault_value(entry, ("api_secret", "secret", "read_only_api_secret"))
    if vault_key or vault_secret:
        return vault_key, vault_secret, "vault_file"
    return "", "", "environment" if credential_ref else "unavailable"


def _credential_env_names(credential_ref: str | None) -> tuple[list[str], list[str]]:
    if not credential_ref:
        return [], []
    prefix = _env_prefix(credential_ref)
    return [f"{prefix}_API_KEY", f"{prefix}_KEY"], [f"{prefix}_API_SECRET", f"{prefix}_SECRET"]


def _is_readonly_credential_ref(credential_ref: str | None) -> bool:
    if not credential_ref:
        return False
    parts = _env_prefix(credential_ref).split("_")
    return "READONLY" in parts or ("READ" in parts and "ONLY" in parts)


def _readonly_binding_block_reason(
    credential_ref: str | None,
    *,
    read_only_required: bool,
    live_trading_enabled: bool,
) -> str | None:
    if not credential_ref:
        return "backend_binding_missing"
    if not read_only_required:
        return "read_only_required"
    if live_trading_enabled:
        return "live_trading_disabled_required"
    if not _is_readonly_credential_ref(credential_ref):
        return "readonly_credential_reference_required"
    return None


def safe_credential_status(
    credential_ref: str | None,
    *,
    read_only_required: bool = True,
    live_trading_enabled: bool = False,
    expose_credential_ref: bool = False,
) -> SafeCredentialStatus:
    public_ref = credential_ref if expose_credential_ref else None
    block_reason = _readonly_binding_block_reason(
        credential_ref,
        read_only_required=read_only_required,
        live_trading_enabled=live_trading_enabled,
    )
    base: dict[str, Any] = {
        "credential_scope": "backend_only_readonly",
        "read_only_required": read_only_required,
        "live_trading_enabled": False,
        "raw_credential_value_exposed": False,
        "checked_at": _now(),
    }

    if not credential_ref:
        return {
            **base,
            "source_type": "unavailable",
            "configured": False,
            "status": "backend_binding_missing",
            "binding_blocked_reason": block_reason,
        }

    if block_reason is not None:
        return {
            **base,
            "source_type": "unavailable",
            "configured": False,
            "status": "credential_binding_blocked",
            "binding_blocked_reason": block_reason,
        }

    api_key, api_secret, source_type = _credential_values(credential_ref)
    configured = bool(api_key and api_secret)
    result: dict[str, Any] = {
        **base,
        "source_type": source_type,
        "configured": configured,
        "status": (
            "credential_configured_read_only_pending_permission_probe"
            if configured
            else "credential_source_pending"
        ),
        "binding_blocked_reason": None,
    }
    if configured:
        result["credential_ref"] = public_ref
    return result


def safe_account_credential_status(account: dict[str, Any], *, expose_credential_ref: bool = False) -> SafeCredentialStatus:
    return safe_credential_status(
        account.get("credential_ref") if isinstance(account.get("credential_ref"), str) else None,
        read_only_required=bool(account.get("read_only", True)),
        live_trading_enabled=bool(account.get("live_trading_enabled", False)),
        expose_credential_ref=expose_credential_ref,
    )


def backend_readonly_credential_binding(account: dict[str, Any]) -> BackendCredentialBinding:
    """Resolve backend-only read-only credentials for an exchange account.

    This function centralizes env lookup so API routes do not need to derive
    credential variable names directly. It never calls an exchange and never
    exposes raw values through the safe status payload.
    """

    credential_ref = account.get("credential_ref") if isinstance(account.get("credential_ref"), str) else None
    safe_status = safe_account_credential_status(account, expose_credential_ref=False)
    if safe_status["binding_blocked_reason"] is not None:
        return BackendCredentialBinding(
            credential_ref=credential_ref,
            api_key="",
            api_secret="",
            safe_status=safe_status,
        )
    api_key, api_secret, _source_type = _credential_values(credential_ref)
    return BackendCredentialBinding(
        credential_ref=credential_ref,
        api_key=api_key,
        api_secret=api_secret,
        safe_status=safe_status,
    )


def credential_vault_readiness_status() -> CredentialVaultReadiness:
    durable_vault_evidence = _durable_credential_vault_evidence()
    secret_redaction_evidence = _secret_redaction_smoke_evidence()
    permission_probe_evidence = _permission_probe_evidence()
    signed_read_evidence = _signed_read_validation_evidence()
    missing_fields = ["durable_credential_vault_current_validation"]
    warnings = [
        "Environment and local vault-file binding are partial evidence only",
        "Durable production credential vault integration is pending",
        "No credential value is returned by safe status payloads",
        "No exchange request is made by this readiness status",
        "Live trading remains disabled",
    ]
    if not durable_vault_evidence["valid"]:
        missing_fields.extend(
            [
                "durable_production_credential_vault",
                "durable_credential_vault_artifact",
                "credential_rotation_policy",
            ]
        )
    if not permission_probe_evidence["valid"]:
        missing_fields.append("permission_probe")
    if not signed_read_evidence["valid"]:
        missing_fields.append("signed_readonly_account_validation")
    if not secret_redaction_evidence["valid"]:
        missing_fields.append("secret_redaction_smoke")
    if secret_redaction_evidence.get("warning"):
        warnings.append(str(secret_redaction_evidence["warning"]))
    if permission_probe_evidence.get("warning"):
        warnings.append(str(permission_probe_evidence["warning"]))
    if signed_read_evidence.get("warning"):
        warnings.append(str(signed_read_evidence["warning"]))
    if durable_vault_evidence.get("warning"):
        warnings.append(str(durable_vault_evidence["warning"]))
    durable_payload = (
        durable_vault_evidence["payload"] if isinstance(durable_vault_evidence.get("payload"), dict) else {}
    )
    return {
        "status": "artifact_present_pending_current_validation"
        if durable_vault_evidence["valid"]
        else "partial_backend_only_local_binding",
        "backend_only": True,
        "environment_binding_supported": True,
        "local_vault_file_supported": True,
        "local_vault_file_configured": _credential_vault_file_path() is not None,
        "durable_production_vault_integrated": durable_payload.get("durable_production_vault_integrated") is True,
        "durable_production_vault_artifact_configured": bool(durable_vault_evidence["configured"]),
        "durable_production_vault_artifact_valid": bool(durable_vault_evidence["valid"]),
        "durable_production_vault_artifact_status": str(durable_vault_evidence["status"]),
        "credential_rotation_policy_status": "configured"
        if durable_payload.get("credential_rotation_policy_configured") is True
        else "missing",
        "permission_probe_status": str(permission_probe_evidence["status"]),
        "permission_probe_artifact_configured": bool(permission_probe_evidence["configured"]),
        "permission_probe_artifact_valid": bool(permission_probe_evidence["valid"]),
        "permission_probe_artifact_status": str(permission_probe_evidence["status"]),
        "signed_read_validation_status": str(signed_read_evidence["status"]),
        "signed_read_validation_artifact_configured": bool(signed_read_evidence["configured"]),
        "signed_read_validation_artifact_valid": bool(signed_read_evidence["valid"]),
        "signed_read_validation_artifact_status": str(signed_read_evidence["status"]),
        "secret_redaction_smoke_status": str(secret_redaction_evidence["status"]),
        "secret_redaction_smoke_artifact_configured": bool(secret_redaction_evidence["configured"]),
        "secret_redaction_smoke_artifact_valid": bool(secret_redaction_evidence["valid"]),
        "secret_redaction_smoke_artifact_status": str(secret_redaction_evidence["status"]),
        "raw_credential_value_exposed": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "checked_at": _now(),
    }
