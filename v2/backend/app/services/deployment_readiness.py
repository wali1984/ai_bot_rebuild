"""Safe deployment readiness artifact helpers.

This module reads already-produced production HTTPS smoke artifacts and exposes
sanitized metadata only. It never calls a deployment, exchange, or live gate;
never submits/cancels orders; and never enables live trading.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict


class ProductionHttpsSmokeReadiness(TypedDict):
    status: str
    production_https_smoke_artifact_configured: bool
    production_https_smoke_artifact_valid: bool
    production_https_smoke_artifact_status: str
    https_enabled: bool
    routes_checked: bool
    public_status_checked: bool
    public_status_safe: bool
    auth_gate_checked: bool
    admin_unauthenticated_blocked: bool
    superadmin_admin_rejected: bool
    console_errors_absent: bool
    secret_exposure_found: bool
    live_trading_enabled: bool
    exchange_mutation_enabled: bool
    live_submit_available: bool
    live_cancel_available: bool
    leverage_mutation_available: bool
    margin_mutation_available: bool
    missing_routes: list[str]
    missing_fields: list[str]
    warnings: list[str]
    checked_at: str


class ProductionPaperActionValidationReadiness(TypedDict):
    status: str
    production_paper_action_validation_artifact_configured: bool
    production_paper_action_validation_artifact_valid: bool
    production_paper_action_validation_artifact_status: str
    paper_submit_validated: bool
    paper_cancel_validated: bool
    paper_fill_validated: bool
    paper_fill_disabled_by_policy: bool
    production_paper_actions_fail_closed: bool
    service_verified_paper_only: bool
    trader_scope_enforced: bool
    paper_account_scope_enforced: bool
    backend_owned_order_ids: bool
    durable_repository_verified: bool
    audit_event_linked: bool
    contains_credentials: bool
    live_transport_enabled: bool
    exchange_mutation_enabled: bool
    real_order_submitted: bool
    real_order_cancelled: bool
    leverage_mutation_enabled: bool
    margin_mutation_enabled: bool
    live_gate_mutation_enabled: bool
    missing_fields: list[str]
    warnings: list[str]
    checked_at: str


class ProductionAlertDeliveryAuditReadiness(TypedDict):
    status: str
    production_alert_delivery_audit_artifact_configured: bool
    production_alert_delivery_audit_artifact_valid: bool
    production_alert_delivery_audit_artifact_status: str
    alert_repository_configured: bool
    alert_crud_validated: bool
    trader_scope_enforced: bool
    paper_account_scope_enforced: bool
    delivery_service_configured: bool
    notification_delivery_tested: bool
    delivery_secret_redacted: bool
    audit_repository_durable: bool
    audit_events_linked: bool
    audit_retention_enforced: bool
    access_control_enforced: bool
    contains_credentials: bool
    live_trading_enabled: bool
    exchange_mutation_enabled: bool
    real_order_submitted: bool
    live_gate_mutation_enabled: bool
    missing_fields: list[str]
    warnings: list[str]
    checked_at: str


class ProductionAuthSessionHardeningReadiness(TypedDict):
    status: str
    production_auth_session_hardening_artifact_configured: bool
    production_auth_session_hardening_artifact_valid: bool
    production_auth_session_hardening_artifact_status: str
    production_auth_secret_configured: bool
    auth_secret_strength_verified: bool
    issuer_configured: bool
    audience_configured: bool
    secure_cookie_enabled: bool
    cookie_samesite_configured: bool
    session_ttl_enforced: bool
    refresh_rotation_enabled: bool
    revocation_store_durable: bool
    session_version_invalidation_enabled: bool
    password_change_revokes_sessions: bool
    admin_step_up_enabled: bool
    backend_role_checks_enforced: bool
    unauthorized_admin_blocked: bool
    superadmin_admin_rejected: bool
    contains_credentials: bool
    token_exposure_found: bool
    plaintext_password_exposure_found: bool
    live_trading_enabled: bool
    exchange_mutation_enabled: bool
    live_submit_available: bool
    live_cancel_available: bool
    leverage_mutation_available: bool
    margin_mutation_available: bool
    missing_fields: list[str]
    warnings: list[str]
    checked_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _production_https_smoke_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_PRODUCTION_HTTPS_SMOKE_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _production_paper_action_validation_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_PRODUCTION_PAPER_ACTION_VALIDATION_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _production_alert_delivery_audit_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_PRODUCTION_ALERT_DELIVERY_AUDIT_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _production_auth_session_hardening_artifact_path() -> Path | None:
    configured = os.environ.get("ALPHAFORGE_AUTH_SESSION_HARDENING_ARTIFACT", "").strip()
    return Path(configured) if configured else None


def _read_artifact() -> dict[str, Any]:
    path = _production_https_smoke_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Production HTTPS smoke artifact is not configured",
            "payload": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": f"Production HTTPS smoke artifact could not be read: {exc}",
            "payload": {},
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Production HTTPS smoke artifact must be a JSON object",
            "payload": {},
        }

    status_value = str(payload.get("production_https_smoke_status") or payload.get("status") or "").strip().lower()
    required_true = (
        "https_enabled",
        "routes_checked",
        "public_status_checked",
        "public_status_safe",
        "auth_gate_checked",
        "admin_unauthenticated_blocked",
        "superadmin_admin_rejected",
        "console_errors_absent",
    )
    forbidden_true = (
        "secret_exposure_found",
        "live_trading_enabled",
        "exchange_mutation_enabled",
        "live_submit_available",
        "live_cancel_available",
        "leverage_mutation_available",
        "margin_mutation_available",
    )
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and all(payload.get(field) is True for field in required_true)
        and all(payload.get(field) is False for field in forbidden_true)
        and not payload.get("missing_fields")
        and not payload.get("missing_routes")
    )
    return {
        "configured": True,
        "valid": valid,
        "status": "passed" if valid else "rejected",
        "warning": None
        if valid
        else "Production HTTPS smoke artifact must prove HTTPS route/status/auth/console coverage, no secret exposure, and no live/exchange mutation",
        "payload": payload,
    }


def production_https_smoke_readiness_status() -> ProductionHttpsSmokeReadiness:
    evidence = _read_artifact()
    payload = evidence["payload"] if isinstance(evidence.get("payload"), dict) else {}
    missing_fields = ["production_https_smoke_current_validation"]
    if not evidence["valid"]:
        missing_fields.append("production_https_smoke_artifact")
    artifact_missing_fields = payload.get("missing_fields") if isinstance(payload.get("missing_fields"), list) else []
    for field in artifact_missing_fields:
        if isinstance(field, str) and field not in missing_fields:
            missing_fields.append(field)
    warnings = [
        "Production HTTPS smoke artifacts are partial evidence until current validation and deployment review pass",
        "No exchange request is made by this readiness status",
        "Live trading remains disabled",
    ]
    if evidence.get("warning"):
        warnings.append(str(evidence["warning"]))
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        warnings.append(str(warning))
    return {
        "status": "artifact_present_pending_current_validation" if evidence["valid"] else "missing",
        "production_https_smoke_artifact_configured": bool(evidence["configured"]),
        "production_https_smoke_artifact_valid": bool(evidence["valid"]),
        "production_https_smoke_artifact_status": str(evidence["status"]),
        "https_enabled": payload.get("https_enabled") is True,
        "routes_checked": payload.get("routes_checked") is True,
        "public_status_checked": payload.get("public_status_checked") is True,
        "public_status_safe": payload.get("public_status_safe") is True,
        "auth_gate_checked": payload.get("auth_gate_checked") is True,
        "admin_unauthenticated_blocked": payload.get("admin_unauthenticated_blocked") is True,
        "superadmin_admin_rejected": payload.get("superadmin_admin_rejected") is True,
        "console_errors_absent": payload.get("console_errors_absent") is True,
        "secret_exposure_found": payload.get("secret_exposure_found") is True,
        "live_trading_enabled": payload.get("live_trading_enabled") is True,
        "exchange_mutation_enabled": payload.get("exchange_mutation_enabled") is True,
        "live_submit_available": payload.get("live_submit_available") is True,
        "live_cancel_available": payload.get("live_cancel_available") is True,
        "leverage_mutation_available": payload.get("leverage_mutation_available") is True,
        "margin_mutation_available": payload.get("margin_mutation_available") is True,
        "missing_routes": [str(route) for route in payload.get("missing_routes", [])]
        if isinstance(payload.get("missing_routes"), list)
        else [],
        "missing_fields": missing_fields,
        "warnings": warnings,
        "checked_at": _now(),
    }


def _read_paper_action_artifact() -> dict[str, Any]:
    path = _production_paper_action_validation_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Production paper action validation artifact is not configured",
            "payload": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": f"Production paper action validation artifact could not be read: {exc}",
            "payload": {},
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Production paper action validation artifact must be a JSON object",
            "payload": {},
        }

    status_value = str(
        payload.get("production_paper_action_validation_smoke_status")
        or payload.get("production_paper_submit_cancel_validation_status")
        or payload.get("status")
        or ""
    ).strip().lower()
    required_true = (
        "paper_submit_validated",
        "paper_cancel_validated",
        "production_paper_actions_fail_closed",
        "service_verified_paper_only",
        "trader_scope_enforced",
        "paper_account_scope_enforced",
        "backend_owned_order_ids",
        "durable_repository_verified",
        "audit_event_linked",
    )
    required_false = (
        "contains_credentials",
        "live_transport_enabled",
        "exchange_mutation_enabled",
        "real_order_submitted",
        "real_order_cancelled",
        "leverage_mutation_enabled",
        "margin_mutation_enabled",
        "live_gate_mutation_enabled",
    )
    fill_policy_ok = payload.get("paper_fill_validated") is True or payload.get("paper_fill_disabled_by_policy") is True
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
        and all(payload.get(field) is True for field in required_true)
        and fill_policy_ok
        and all(payload.get(field) is False for field in required_false)
        and not payload.get("missing_fields")
    )
    return {
        "configured": True,
        "valid": valid,
        "status": "passed" if valid else "rejected",
        "warning": None
        if valid
        else "Production paper action artifact must prove paper-only submit/cancel/fill or fill-policy validation, trader and paper-account scope, durable repository and audit linkage, and no live/exchange mutation",
        "payload": payload,
    }


def production_paper_action_validation_readiness_status() -> ProductionPaperActionValidationReadiness:
    evidence = _read_paper_action_artifact()
    payload = evidence["payload"] if isinstance(evidence.get("payload"), dict) else {}
    missing_fields = ["production_paper_submit_cancel_current_validation"]
    if not evidence["valid"]:
        missing_fields.append("production_paper_action_validation_artifact")
    artifact_missing_fields = payload.get("missing_fields") if isinstance(payload.get("missing_fields"), list) else []
    for field in artifact_missing_fields:
        if isinstance(field, str) and field not in missing_fields:
            missing_fields.append(field)
    warnings = [
        "Production paper action artifacts are partial evidence until current validation and review pass",
        "No paper endpoint is called by this readiness status",
        "No exchange request is made by this readiness status",
        "Live trading remains disabled",
    ]
    if evidence.get("warning"):
        warnings.append(str(evidence["warning"]))
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        warnings.append(str(warning))
    return {
        "status": "artifact_present_pending_current_validation" if evidence["valid"] else "missing",
        "production_paper_action_validation_artifact_configured": bool(evidence["configured"]),
        "production_paper_action_validation_artifact_valid": bool(evidence["valid"]),
        "production_paper_action_validation_artifact_status": str(evidence["status"]),
        "paper_submit_validated": payload.get("paper_submit_validated") is True,
        "paper_cancel_validated": payload.get("paper_cancel_validated") is True,
        "paper_fill_validated": payload.get("paper_fill_validated") is True,
        "paper_fill_disabled_by_policy": payload.get("paper_fill_disabled_by_policy") is True,
        "production_paper_actions_fail_closed": payload.get("production_paper_actions_fail_closed") is True,
        "service_verified_paper_only": payload.get("service_verified_paper_only") is True,
        "trader_scope_enforced": payload.get("trader_scope_enforced") is True,
        "paper_account_scope_enforced": payload.get("paper_account_scope_enforced") is True,
        "backend_owned_order_ids": payload.get("backend_owned_order_ids") is True,
        "durable_repository_verified": payload.get("durable_repository_verified") is True,
        "audit_event_linked": payload.get("audit_event_linked") is True,
        "contains_credentials": payload.get("contains_credentials") is True,
        "live_transport_enabled": payload.get("live_transport_enabled") is True,
        "exchange_mutation_enabled": payload.get("exchange_mutation_enabled") is True,
        "real_order_submitted": payload.get("real_order_submitted") is True,
        "real_order_cancelled": payload.get("real_order_cancelled") is True,
        "leverage_mutation_enabled": payload.get("leverage_mutation_enabled") is True,
        "margin_mutation_enabled": payload.get("margin_mutation_enabled") is True,
        "live_gate_mutation_enabled": payload.get("live_gate_mutation_enabled") is True,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "checked_at": _now(),
    }


def _read_alert_delivery_audit_artifact() -> dict[str, Any]:
    path = _production_alert_delivery_audit_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Production alert delivery/audit artifact is not configured",
            "payload": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": f"Production alert delivery/audit artifact could not be read: {exc}",
            "payload": {},
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Production alert delivery/audit artifact must be a JSON object",
            "payload": {},
        }

    status_value = str(
        payload.get("production_alert_delivery_audit_smoke_status")
        or payload.get("alerts_crud_delivery_audit_repositories_status")
        or payload.get("status")
        or ""
    ).strip().lower()
    required_true = (
        "alert_repository_configured",
        "alert_crud_validated",
        "trader_scope_enforced",
        "paper_account_scope_enforced",
        "delivery_service_configured",
        "notification_delivery_tested",
        "delivery_secret_redacted",
        "audit_repository_durable",
        "audit_events_linked",
        "audit_retention_enforced",
        "access_control_enforced",
    )
    required_false = (
        "contains_credentials",
        "live_trading_enabled",
        "exchange_mutation_enabled",
        "real_order_submitted",
        "live_gate_mutation_enabled",
    )
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
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
        else "Production alert delivery/audit artifact must prove durable repository, delivery validation, scope enforcement, audit retention/access control, secret redaction, and no live/exchange mutation",
        "payload": payload,
    }


def production_alert_delivery_audit_readiness_status() -> ProductionAlertDeliveryAuditReadiness:
    evidence = _read_alert_delivery_audit_artifact()
    payload = evidence["payload"] if isinstance(evidence.get("payload"), dict) else {}
    missing_fields = ["production_alert_delivery_audit_current_validation"]
    if not evidence["valid"]:
        missing_fields.append("production_alert_delivery_audit_artifact")
    artifact_missing_fields = payload.get("missing_fields") if isinstance(payload.get("missing_fields"), list) else []
    for field in artifact_missing_fields:
        if isinstance(field, str) and field not in missing_fields:
            missing_fields.append(field)
    warnings = [
        "Production alert delivery/audit artifacts are partial evidence until current validation and review pass",
        "No notification is sent by this readiness status",
        "No exchange request is made by this readiness status",
        "Live trading remains disabled",
    ]
    if evidence.get("warning"):
        warnings.append(str(evidence["warning"]))
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        warnings.append(str(warning))
    return {
        "status": "artifact_present_pending_current_validation" if evidence["valid"] else "missing",
        "production_alert_delivery_audit_artifact_configured": bool(evidence["configured"]),
        "production_alert_delivery_audit_artifact_valid": bool(evidence["valid"]),
        "production_alert_delivery_audit_artifact_status": str(evidence["status"]),
        "alert_repository_configured": payload.get("alert_repository_configured") is True,
        "alert_crud_validated": payload.get("alert_crud_validated") is True,
        "trader_scope_enforced": payload.get("trader_scope_enforced") is True,
        "paper_account_scope_enforced": payload.get("paper_account_scope_enforced") is True,
        "delivery_service_configured": payload.get("delivery_service_configured") is True,
        "notification_delivery_tested": payload.get("notification_delivery_tested") is True,
        "delivery_secret_redacted": payload.get("delivery_secret_redacted") is True,
        "audit_repository_durable": payload.get("audit_repository_durable") is True,
        "audit_events_linked": payload.get("audit_events_linked") is True,
        "audit_retention_enforced": payload.get("audit_retention_enforced") is True,
        "access_control_enforced": payload.get("access_control_enforced") is True,
        "contains_credentials": payload.get("contains_credentials") is True,
        "live_trading_enabled": payload.get("live_trading_enabled") is True,
        "exchange_mutation_enabled": payload.get("exchange_mutation_enabled") is True,
        "real_order_submitted": payload.get("real_order_submitted") is True,
        "live_gate_mutation_enabled": payload.get("live_gate_mutation_enabled") is True,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "checked_at": _now(),
    }


def _read_auth_session_hardening_artifact() -> dict[str, Any]:
    path = _production_auth_session_hardening_artifact_path()
    if path is None:
        return {
            "configured": False,
            "valid": False,
            "status": "pending",
            "warning": "Production auth/session hardening artifact is not configured",
            "payload": {},
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": f"Production auth/session hardening artifact could not be read: {exc}",
            "payload": {},
        }
    if not isinstance(payload, dict):
        return {
            "configured": True,
            "valid": False,
            "status": "invalid",
            "warning": "Production auth/session hardening artifact must be a JSON object",
            "payload": {},
        }

    status_value = str(
        payload.get("production_auth_session_hardening_status")
        or payload.get("auth_session_hardening_status")
        or payload.get("status")
        or ""
    ).strip().lower()
    required_true = (
        "production_auth_secret_configured",
        "auth_secret_strength_verified",
        "issuer_configured",
        "audience_configured",
        "secure_cookie_enabled",
        "cookie_samesite_configured",
        "session_ttl_enforced",
        "refresh_rotation_enabled",
        "revocation_store_durable",
        "session_version_invalidation_enabled",
        "password_change_revokes_sessions",
        "admin_step_up_enabled",
        "backend_role_checks_enforced",
        "unauthorized_admin_blocked",
        "superadmin_admin_rejected",
    )
    required_false = (
        "contains_credentials",
        "token_exposure_found",
        "plaintext_password_exposure_found",
        "live_trading_enabled",
        "exchange_mutation_enabled",
        "live_submit_available",
        "live_cancel_available",
        "leverage_mutation_available",
        "margin_mutation_available",
    )
    valid = (
        status_value in {"pass", "passed", "ok", "verified"}
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
        else "Production auth/session hardening artifact must prove strong secrets, issuer/audience, secure cookies, TTL, refresh rotation, durable revocation, session-version invalidation, password-change revocation, admin step-up, RBAC denial, and no secret/live/exchange exposure",
        "payload": payload,
    }


def production_auth_session_hardening_readiness_status() -> ProductionAuthSessionHardeningReadiness:
    evidence = _read_auth_session_hardening_artifact()
    payload = evidence["payload"] if isinstance(evidence.get("payload"), dict) else {}
    missing_fields = ["production_auth_session_hardening_current_validation"]
    if not evidence["valid"]:
        missing_fields.append("production_auth_session_hardening_artifact")
    artifact_missing_fields = payload.get("missing_fields") if isinstance(payload.get("missing_fields"), list) else []
    for field in artifact_missing_fields:
        if isinstance(field, str) and field not in missing_fields:
            missing_fields.append(field)
    warnings = [
        "Production auth/session hardening artifacts are partial evidence until current validation and security review pass",
        "No credential values or tokens are returned by this readiness status",
        "No exchange request is made by this readiness status",
        "Live trading remains disabled",
    ]
    if evidence.get("warning"):
        warnings.append(str(evidence["warning"]))
    for warning in payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else []:
        warnings.append(str(warning))
    return {
        "status": "artifact_present_pending_current_validation" if evidence["valid"] else "missing",
        "production_auth_session_hardening_artifact_configured": bool(evidence["configured"]),
        "production_auth_session_hardening_artifact_valid": bool(evidence["valid"]),
        "production_auth_session_hardening_artifact_status": str(evidence["status"]),
        "production_auth_secret_configured": payload.get("production_auth_secret_configured") is True,
        "auth_secret_strength_verified": payload.get("auth_secret_strength_verified") is True,
        "issuer_configured": payload.get("issuer_configured") is True,
        "audience_configured": payload.get("audience_configured") is True,
        "secure_cookie_enabled": payload.get("secure_cookie_enabled") is True,
        "cookie_samesite_configured": payload.get("cookie_samesite_configured") is True,
        "session_ttl_enforced": payload.get("session_ttl_enforced") is True,
        "refresh_rotation_enabled": payload.get("refresh_rotation_enabled") is True,
        "revocation_store_durable": payload.get("revocation_store_durable") is True,
        "session_version_invalidation_enabled": payload.get("session_version_invalidation_enabled") is True,
        "password_change_revokes_sessions": payload.get("password_change_revokes_sessions") is True,
        "admin_step_up_enabled": payload.get("admin_step_up_enabled") is True,
        "backend_role_checks_enforced": payload.get("backend_role_checks_enforced") is True,
        "unauthorized_admin_blocked": payload.get("unauthorized_admin_blocked") is True,
        "superadmin_admin_rejected": payload.get("superadmin_admin_rejected") is True,
        "contains_credentials": payload.get("contains_credentials") is True,
        "token_exposure_found": payload.get("token_exposure_found") is True,
        "plaintext_password_exposure_found": payload.get("plaintext_password_exposure_found") is True,
        "live_trading_enabled": payload.get("live_trading_enabled") is True,
        "exchange_mutation_enabled": payload.get("exchange_mutation_enabled") is True,
        "live_submit_available": payload.get("live_submit_available") is True,
        "live_cancel_available": payload.get("live_cancel_available") is True,
        "leverage_mutation_available": payload.get("leverage_mutation_available") is True,
        "margin_mutation_available": payload.get("margin_mutation_available") is True,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "checked_at": _now(),
    }
