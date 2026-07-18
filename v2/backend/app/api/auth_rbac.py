"""Backend-enforced auth and admin RBAC routes."""

from __future__ import annotations

import os
import re
import asyncio
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response, status

from app.api.v2._common import get_redis
from pydantic import BaseModel, ConfigDict, Field

from app.auth.security import (
    ROLE_RANK,
    SESSION_COOKIE,
    cookie_samesite_value,
    cookie_secure_enabled,
    create_access_token,
    require_admin,
    require_auth,
    require_superadmin,
    revoke_access_token,
    session_max_age_seconds,
    session_security_status,
    session_token_from_inputs,
    verify_admin_step_up_code,
)
from app.auth.users import UserRecord, UserStore, _verify_password, auth_user_store_status, get_user_store, safe_exchange_accounts, safe_user
from app.services.audit_writer import admin_audit_status, append_admin_audit_event
from app.services.credential_status import credential_vault_readiness_status
from app.services.deployment_readiness import (
    production_auth_session_hardening_readiness_status,
    production_https_smoke_readiness_status,
    production_alert_delivery_audit_readiness_status,
    production_paper_action_validation_readiness_status,
)
from app.services.trader_account_repository import TraderAccountRepository, get_trader_account_repository

router = APIRouter(prefix="/api", tags=["auth-rbac"])

_ALLOWED_EXCHANGES = {"binance", "kucoin", "bybit"}
OPERATOR_TZ = ZoneInfo("America/New_York")


def _auth_login_timeout_seconds() -> float:
    raw = os.environ.get("ALPHAFORGE_AUTH_LOGIN_TIMEOUT_SECONDS", "2.0").strip()
    try:
        return max(0.1, float(raw))
    except ValueError:
        return 2.0


async def _authenticate_bounded(store: UserStore, email: str, password: str) -> UserRecord | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(store.authenticate, email, password),
            timeout=_auth_login_timeout_seconds(),
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_service_unavailable",
        ) from exc


def _now_utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _admin_mutation_reason(reason: str | None) -> str | None:
    cleaned = (reason or "").strip()
    if _production_environment() and len(cleaned) < 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="admin_mutation_reason_required")
    return cleaned or None


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


class CreateUserRequest(BaseModel):
    email: str
    username: str = ""
    password: str = Field(min_length=1)
    role: str
    trader_id: str | None = None
    paper_account_id: str | None = None
    exchange_accounts: list[dict[str, Any]] = Field(default_factory=list)
    watchlist: list[str] = Field(default_factory=list)
    alert_preferences: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    reason: str | None = None


class UpdateUserRequest(BaseModel):
    email: str | None = None
    username: str | None = None
    password: str | None = None
    role: str | None = None
    trader_id: str | None = None
    paper_account_id: str | None = None
    exchange_accounts: list[dict[str, Any]] | None = None
    watchlist: list[str] | None = None
    alert_preferences: dict[str, Any] | None = None
    is_active: bool | None = None
    reason: str | None = None


class TraderPaperAccountRequest(BaseModel):
    trader_id: str = Field(min_length=1)
    paper_account_id: str | None = None
    currency: str = "USDT"
    equity: float | None = None
    realized_pnl: float | None = None
    unrealized_pnl: float | None = None
    positions: list[dict[str, Any]] | None = None
    orders: list[dict[str, Any]] | None = None
    executions: list[dict[str, Any]] | None = None
    signals: list[dict[str, Any]] | None = None
    source_status: str = "manual_paper_repository_update"


class RegisterRequest(BaseModel):
    email: str
    username: str = ""
    password: str = Field(min_length=8)


class LinkExchangeAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: str
    label: str = Field(min_length=1)
    account_type: str = "usd_m_futures"
    credential_ref: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class WatchlistUpdateRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class AdminUserActivationRequest(BaseModel):
    is_active: bool
    temporary_password: str | None = None
    reason: str = Field(min_length=3)


def _normalize_watchlist_symbols(symbols: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in symbols:
        symbol = str(value or "").strip().upper()
        if not symbol:
            continue
        if not re.fullmatch(r"[A-Z0-9]{3,32}", symbol):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_watchlist_symbol")
        if symbol not in normalized:
            normalized.append(symbol)
    if len(normalized) > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="watchlist_limit_exceeded")
    return normalized


def _reject_secret_like_account_metadata(*values: str) -> None:
    combined = " ".join(str(value or "") for value in values).lower()
    if re.search(r"(api[_ -]?key|api[_ -]?secret|private[_ -]?key|secret|credential[_ -]?ref|access[_ -]?token)", combined):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="exchange_account_metadata_only")


def _admin_audit_response(audit_event: dict[str, Any]) -> dict[str, Any]:
    return {
        "audit_id": audit_event.get("audit_id"),
        "recorded": bool(audit_event.get("audit_persisted")),
        "ledger_kind": audit_event.get("ledger_kind"),
        "production_durable_store": audit_event.get("production_durable_store"),
        "contains_secret_values": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=cookie_secure_enabled(),
        samesite=cookie_samesite_value(),
        max_age=session_max_age_seconds(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=cookie_secure_enabled(),
        httponly=True,
        samesite=cookie_samesite_value(),
    )


# Brute-force protection for /auth/login. Fail-OPEN on any Redis error so a
# Redis blip can never lock a legitimate operator out.
_LOGIN_MAX_FAILS = int(os.environ.get("V2_LOGIN_MAX_FAILS", "10"))
_LOGIN_FAIL_WINDOW_SECONDS = int(os.environ.get("V2_LOGIN_FAIL_WINDOW_SECONDS", "900"))


def _login_rl_key(http_request: Request | None, email: str) -> str:
    ip = http_request.client.host if (http_request and http_request.client) else "unknown"
    return f"v2:auth:login_fail:{ip}:{(email or '').strip().lower()}"


def _login_rl_current_fails(http_request: Request | None, email: str) -> int:
    try:
        r = get_redis()
        if r is None:
            return 0
        return int(r.get(_login_rl_key(http_request, email)) or 0)
    except Exception:
        return 0


def _login_rl_record_failure(http_request: Request | None, email: str) -> None:
    try:
        r = get_redis()
        if r is None:
            return
        key = _login_rl_key(http_request, email)
        pipe = r.pipeline()
        pipe.incr(key)
        pipe.expire(key, _LOGIN_FAIL_WINDOW_SECONDS)
        pipe.execute()
    except Exception:
        return


def _login_rl_clear(http_request: Request | None, email: str) -> None:
    try:
        r = get_redis()
        if r is not None:
            r.delete(_login_rl_key(http_request, email))
    except Exception:
        return


@router.post("/auth/login")
async def login(
    request: LoginRequest,
    response: Response,
    http_request: Request,
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    if _login_rl_current_fails(http_request, request.email) >= _LOGIN_MAX_FAILS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_login_attempts",
        )
    user = await _authenticate_bounded(store, request.email, request.password)
    if not user:
        _login_rl_record_failure(http_request, request.email)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    _login_rl_clear(http_request, request.email)
    token = create_access_token(user)
    _set_session_cookie(response, token)
    return {"access_token": token, "token_type": "bearer", "user": safe_user(user)}


@router.get("/auth/health")
async def auth_health() -> dict[str, Any]:
    store_status = auth_user_store_status()
    now = _now_utc()
    return {
        "schema_version": "auth_health_v1",
        "generated_at_utc": now,
        "generated_at_et": datetime.now(OPERATOR_TZ).isoformat(timespec="seconds"),
        "source": "auth_user_store_status",
        "status": "ok",
        "staleness_seconds": 0,
        "freshness_status": "fresh",
        "canonical_owner": "/api/auth/health",
        "data_quality_status": "fresh" if store_status.get("production_ready") else "degraded",
        "login_endpoint_available": True,
        "auth_store_backend": store_status.get("backend"),
        "durable_user_store_configured": store_status.get("durable_user_store_configured"),
        "production_ready": store_status.get("production_ready"),
        "contains_secret_values": False,
        "raw_credential_value_exposed": False,
        "live_gate": "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        "exchange_mutation_enabled": False,
        "session_security": session_security_status(),
        "warnings": store_status.get("missing_fields") or [],
    }


@router.post("/auth/logout")
async def logout(
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
) -> dict[str, bool]:
    token = session_token_from_inputs(authorization, session_cookie)
    try:
        revoked = revoke_access_token(token)
    except HTTPException as exc:
        if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise
        revoked = False
    _clear_session_cookie(response)
    return {"ok": True, "revoked": revoked}


@router.post("/auth/refresh")
async def refresh(
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    user: UserRecord = Depends(require_auth),
) -> dict[str, Any]:
    previous_token = session_token_from_inputs(authorization, session_cookie)
    token = create_access_token(user)
    try:
        previous_revoked = revoke_access_token(previous_token)
    except HTTPException as exc:
        if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise
        previous_revoked = False
    _set_session_cookie(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": safe_user(user),
        "previous_session_revoked": previous_revoked,
    }


@router.get("/auth/me")
async def me(user: UserRecord = Depends(require_auth)) -> dict[str, Any]:
    return {"user": safe_user(user), "session_security": session_security_status()}


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    response: Response,
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    """Self-registration for new users. Creates a 'viewer' account pending admin upgrade to trader.
    Live trading always blocked. Exchange accounts can be linked after approval."""
    normalized_email = request.email.strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email")
    username = (request.username.strip() or normalized_email.split("@")[0])[:30]
    user = store.create_user(
        email=normalized_email,
        username=username,
        password=request.password,
        role="viewer",
        trader_id=None,
        paper_account_id=None,
        exchange_accounts=[],
        watchlist=[],
        alert_preferences={},
        is_active=True,
    )
    token = create_access_token(user)
    _set_session_cookie(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": safe_user(user),
        "note": "Account created as viewer. An admin can upgrade your role to trader.",
        "warnings": ["Live trading is disabled system-wide", "Exchange accounts can be linked after role upgrade"],
    }


@router.post("/accounts/me/exchange-accounts", status_code=status.HTTP_201_CREATED)
async def link_exchange_account(
    request: LinkExchangeAccountRequest,
    user: UserRecord = Depends(require_auth),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    """Link exchange account metadata only.

    This route never accepts API keys, secrets, or backend credential reference
    names. Live trading is always forced disabled.
    """
    exchange = request.exchange.strip().lower()
    if exchange not in _ALLOWED_EXCHANGES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unsupported_exchange: {exchange}")
    if request.credential_ref is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="exchange_account_metadata_only")
    trader_id = user.get("trader_id")
    paper_account_id = user.get("paper_account_id")
    if not trader_id or not paper_account_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="trader_account_scope_required")
    if user.get("role") != "trader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="trader_role_required")
    _reject_secret_like_account_metadata(request.label, request.account_type)
    safe_id_part = re.sub(r"[^a-z0-9]", "", trader_id)[:20]
    account_id = f"{exchange}-{safe_id_part}"
    now = _now_utc()
    new_account: dict[str, Any] = {
        "id": account_id,
        "trader_id": trader_id,
        "paper_account_id": paper_account_id,
        "exchange": exchange,
        "label": request.label.strip(),
        "account_type": request.account_type.strip() or "usd_m_futures",
        "mode": "read_only",
        "credential_ref": None,
        "read_only": True,
        "live_trading_enabled": False,
        "status": "credential_binding_required",
        "created_at": now,
        "updated_at": now,
    }
    accounts: list[dict[str, Any]] = list(user.get("exchange_accounts") or [])
    if any(a.get("id") == account_id for a in accounts):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="exchange_account_exists")
    accounts.append(new_account)
    updated = store.update_user(user["id"], {"exchange_accounts": accounts})
    return {
        "user": safe_user(updated),
        "warnings": [
            "Account access setup must be completed through the secure account-link workflow",
            "Private exchange values are never accepted by this route",
            "Live trading is blocked system-wide",
            "Read-only mode is enforced",
        ],
    }


@router.delete("/accounts/me/exchange-accounts/{account_id}", status_code=status.HTTP_200_OK)
async def unlink_exchange_account(
    account_id: str,
    user: UserRecord = Depends(require_auth),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    trader_id = user.get("trader_id")
    paper_account_id = user.get("paper_account_id")
    if not trader_id or not paper_account_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="trader_account_scope_required")
    if user.get("role") != "trader":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="trader_role_required")
    accounts: list[dict[str, Any]] = list(user.get("exchange_accounts") or [])
    target = next((a for a in accounts if a.get("id") == account_id), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exchange_account_not_found")
    if (
        target.get("trader_id") != trader_id
        or target.get("paper_account_id") != paper_account_id
        or target.get("read_only") is not True
        or target.get("live_trading_enabled") is not False
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exchange_account_not_found")
    filtered = [a for a in accounts if a.get("id") != account_id]
    if len(filtered) == len(accounts):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="exchange_account_not_found")
    updated = store.update_user(user["id"], {"exchange_accounts": filtered})
    return {
        "user": safe_user(updated),
        "removed_account_id": account_id,
        "warnings": [
            "Exchange account metadata was removed only from the signed-in trader scope",
            "No exchange state was read or mutated",
            "Live trading remains disabled",
        ],
    }


@router.put("/accounts/me/watchlist", status_code=status.HTTP_200_OK)
async def update_my_watchlist(
    request: WatchlistUpdateRequest,
    user: UserRecord = Depends(require_auth),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    symbols = _normalize_watchlist_symbols(request.symbols)
    updated = store.update_user(user["id"], {"watchlist": symbols})
    return {
        "user": safe_user(updated),
        "watchlist": symbols,
        "warnings": [
            "Watchlist is scoped to the signed-in user",
            "No exchange state was read or mutated",
            "Live trading remains disabled",
        ],
    }


@router.post("/accounts/me/change-password")
async def change_password(
    request: ChangePasswordRequest,
    response: Response,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    user: UserRecord = Depends(require_auth),
    store: UserStore = Depends(get_user_store),
) -> dict[str, bool]:
    if not _verify_password(request.current_password, str(user.get("password_hash", ""))):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_current_password")
    if len(request.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_too_short")
    store.update_user(user["id"], {"password": request.new_password})
    token = session_token_from_inputs(authorization, session_cookie)
    try:
        session_revoked = revoke_access_token(token)
    except HTTPException:
        session_revoked = False
    _clear_session_cookie(response)
    return {"ok": True, "session_revoked": session_revoked}


@router.get("/admin/users")
async def list_users(
    _actor: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    return {"users": [safe_user(user) for user in store.list_users()]}


@router.post("/admin/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    actor: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    reason = _admin_mutation_reason(request.reason)
    requested = request.model_dump(exclude={"reason"})
    # Privilege-boundary: an actor may never grant a role that outranks their own
    # (blocks admin -> superadmin self-escalation via a minted account).
    _actor_rank = ROLE_RANK.get(str(actor.get("role") or ""), 0)
    if request.role and ROLE_RANK.get(request.role, 0) > _actor_rank:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot_grant_role_above_own_rank",
        )
    normalized_email = request.email.strip().lower()
    audit_event = append_admin_audit_event(
        {
            "event_type": "admin_user_create",
            "actor_user_id": actor.get("id"),
            "actor_role": actor.get("role"),
            "target_user_id": f"pending_user_create:{normalized_email}",
            "target_email": normalized_email,
            "target_role": request.role,
            "target_trader_id": request.trader_id,
            "target_paper_account_id": request.paper_account_id,
            "target_exchange_accounts": len(request.exchange_accounts or []),
            "watchlist_count": len(request.watchlist or []),
            "alert_preferences_keys": sorted((request.alert_preferences or {}).keys()),
            "requested_is_active": bool(request.is_active),
            "reason_recorded": reason is not None,
            "reason": reason,
            "password_supplied": bool(request.password),
            "password_returned": False,
            "password_digest_returned": False,
        }
    )
    user = store.create_user(**requested)
    return {"user": safe_user(user), "audit": _admin_audit_response(audit_event)}


@router.put("/admin/users/{user_id}")
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    step_up_code: str | None = Header(default=None, alias="X-AlphaForge-Step-Up-Code"),
    actor: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    reason = _admin_mutation_reason(request.reason)
    updates = {key: value for key, value in request.model_dump(exclude={"reason"}).items() if value is not None}
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
    # Privilege-boundary: an actor may not grant a role above their own rank, may
    # not modify a target that already outranks them, and password resets require
    # step-up MFA (parity with set_user_activation, which the raw update bypassed).
    _actor_rank = ROLE_RANK.get(str(actor.get("role") or ""), 0)
    if request.role and ROLE_RANK.get(request.role, 0) > _actor_rank:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cannot_grant_role_above_own_rank")
    if ROLE_RANK.get(str(target.get("role") or ""), 0) > _actor_rank:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="cannot_modify_higher_ranked_user")
    if "password" in updates:
        verify_admin_step_up_code(step_up_code)
    safe_updated_fields = sorted(key for key in updates if key != "password")
    audit_event = append_admin_audit_event(
        {
            "event_type": "admin_user_update",
            "actor_user_id": actor.get("id"),
            "actor_role": actor.get("role"),
            "target_user_id": target.get("id"),
            "target_email": target.get("email"),
            "target_role": target.get("role"),
            "target_trader_id": target.get("trader_id"),
            "requested_email": request.email.strip().lower() if request.email else None,
            "requested_role": request.role,
            "requested_trader_id": request.trader_id,
            "requested_paper_account_id": request.paper_account_id,
            "requested_exchange_accounts": len(request.exchange_accounts) if request.exchange_accounts is not None else None,
            "requested_is_active": request.is_active,
            "updated_fields": safe_updated_fields,
            "reason_recorded": reason is not None,
            "reason": reason,
            "password_reset": "password" in updates,
            "password_returned": False,
            "password_digest_returned": False,
        }
    )
    user = store.update_user(user_id, updates)
    return {"user": safe_user(user), "audit": _admin_audit_response(audit_event)}


@router.post("/admin/users/{user_id}/activation")
async def set_user_activation(
    user_id: str,
    request: AdminUserActivationRequest,
    step_up_code: str | None = Header(default=None, alias="X-AlphaForge-Step-Up-Code"),
    actor: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    verify_admin_step_up_code(step_up_code)
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
    updates: dict[str, Any] = {"is_active": request.is_active}
    password_reset = request.temporary_password is not None
    if request.temporary_password is not None:
        if len(request.temporary_password) < 8:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="temporary_password_too_short")
        updates["password"] = request.temporary_password
    elif request.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="temporary_password_required_for_activation")
    audit_event = append_admin_audit_event(
        {
            "event_type": "admin_user_activation_reset",
            "actor_user_id": actor.get("id"),
            "actor_role": actor.get("role"),
            "target_user_id": target.get("id"),
            "target_email": target.get("email"),
            "target_role": target.get("role"),
            "target_trader_id": target.get("trader_id"),
            "requested_is_active": request.is_active,
            "previous_is_active": bool(target.get("is_active")),
            "password_reset": password_reset,
            "reason_recorded": bool(request.reason.strip()),
            "reason": request.reason.strip(),
            "step_up_checked": True,
            "temporary_password_returned": False,
            "password_hash_returned": False,
        }
    )
    user = store.update_user(user_id, updates)
    return {
        "user": safe_user(user),
        "activation": {
            "is_active": user.get("is_active"),
            "password_reset": password_reset,
            "reason_recorded": bool(request.reason.strip()),
        },
        "audit": _admin_audit_response(audit_event),
        "warnings": [
            "Admin activation/reset does not expose password hashes or temporary passwords",
            "Exchange credentials are not changed by this workflow",
            "Live trading remains disabled",
        ],
    }


@router.delete("/admin/users/{user_id}")
async def delete_user(
    user_id: str,
    reason: str | None = Query(default=None),
    actor: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    mutation_reason = _admin_mutation_reason(reason)
    target = store.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
    audit_event = append_admin_audit_event(
        {
            "event_type": "admin_user_delete",
            "actor_user_id": actor.get("id"),
            "actor_role": actor.get("role"),
            "target_user_id": target.get("id"),
            "target_email": target.get("email"),
            "target_role": target.get("role"),
            "target_trader_id": target.get("trader_id"),
            "target_paper_account_id": target.get("paper_account_id"),
            "target_exchange_accounts": len(target.get("exchange_accounts") or []),
            "reason_recorded": mutation_reason is not None,
            "reason": mutation_reason,
            "deletes_password_digest": True,
            "password_returned": False,
            "password_digest_returned": False,
        }
    )
    store.delete_user(user_id)
    return {"ok": True, "audit": _admin_audit_response(audit_event)}


@router.get("/admin/trader-accounts")
async def list_trader_accounts(
    _actor: UserRecord = Depends(require_admin),
    repository: TraderAccountRepository = Depends(get_trader_account_repository),
) -> dict[str, Any]:
    integrity = repository.integrity_report()
    readiness = repository.readiness_report()
    repository_kind = readiness.get("repository_kind")
    storage_warning = (
        "SQLAlchemy paper account repository is configured but production writer validation remains pending"
        if repository_kind == "sqlalchemy"
        else "Paper account repository is local/dev storage"
    )
    integrity_warning = (
        "Repository integrity is SQL-backed partial evidence until production validation passes"
        if repository_kind == "sqlalchemy"
        else "Repository integrity is local-only partial evidence"
    )
    return {
        "accounts": repository.list_accounts(),
        "repository_integrity": integrity,
        "repository_readiness": readiness,
        "paper_action_readiness": production_paper_action_validation_readiness_status(),
        "alert_delivery_audit_readiness": production_alert_delivery_audit_readiness_status(),
        "warnings": [
            storage_warning,
            integrity_warning,
            "Repository readiness is partial and production database writers remain pending",
            "Paper action readiness is partial until production paper submit/cancel/fill validation passes",
            "Alert delivery/audit readiness is partial until production notification delivery and durable audit validation pass",
            "No exchange secrets are stored or exposed",
            "No live order submit/cancel path is available here",
        ],
    }


@router.get("/admin/credential-status")
async def list_credential_status(
    _actor: UserRecord = Depends(require_admin),
    store: UserStore = Depends(get_user_store),
) -> dict[str, Any]:
    accounts: list[dict[str, Any]] = []
    for user in store.list_users():
        for account in safe_exchange_accounts(user.get("exchange_accounts")):
            accounts.append(
                {
                    "user_id": user.get("id"),
                    "trader_id": user.get("trader_id"),
                    "paper_account_id": user.get("paper_account_id"),
                    "exchange_account": account,
                }
            )
    return {
        "accounts": accounts,
        "credential_vault_readiness": credential_vault_readiness_status(),
        "admin_audit_readiness": admin_audit_status(),
        "deployment_readiness": production_https_smoke_readiness_status(),
        "auth_session_hardening_readiness": production_auth_session_hardening_readiness_status(),
        "warnings": [
            "Credential status is backend-only metadata",
            "Credential vault readiness is partial and production vault integration remains pending",
            "Admin audit readiness is partial until production migrations and retention policy are complete",
            "Deployment readiness is partial until production HTTPS smoke and current validation pass",
            "Auth/session hardening readiness is partial until production security evidence and current validation pass",
            "No raw credential values are returned",
            "No exchange state is read or mutated",
            "Live trading remains disabled",
        ],
    }


@router.put("/admin/trader-accounts/{paper_account_id}")
async def upsert_trader_account(
    paper_account_id: str,
    request: TraderPaperAccountRequest,
    _actor: UserRecord = Depends(require_admin),
    repository: TraderAccountRepository = Depends(get_trader_account_repository),
) -> dict[str, Any]:
    try:
        account = repository.upsert_account(
            **{**request.model_dump(), "paper_account_id": paper_account_id}
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "account": account,
        "warnings": [
            "Paper repository update only",
            "No exchange state was read or mutated",
            "No live order submit/cancel path was enabled",
        ],
    }


@router.get("/admin/evidence")
async def superadmin_evidence(_actor: UserRecord = Depends(require_superadmin)) -> dict[str, Any]:
    return {
        "status": "available",
        "scope": "superadmin",
        "live_trading_enabled": False,
        "warnings": ["Superadmin evidence route is read-only in this pass."],
    }
