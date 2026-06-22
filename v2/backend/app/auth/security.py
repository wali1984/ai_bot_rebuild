"""JWT-style session tokens and role dependencies.

This module is intentionally small and self-contained. It does not contact an
exchange, does not mutate live-gate state, and does not log secrets.
"""

from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.db.engine import make_engine
from app.auth.users import UserRecord, UserStore, auth_user_store_status, get_user_store

Role = Literal["guest", "viewer", "trader", "admin", "superadmin"]

ROLE_RANK: dict[str, int] = {
    "guest": 0,
    "viewer": 1,
    "trader": 2,
    "admin": 3,
    "superadmin": 4,
}

SESSION_COOKIE = "alphaforge_session"
PRODUCTION_AUTH_SECRET_MIN_LENGTH = 32
_PROCESS_SECRET = secrets.token_urlsafe(48)
_REVOCATION_LOCK = threading.Lock()


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _split_previous_secrets(raw: str) -> list[str]:
    normalized = raw.replace("\n", ",")
    return [value.strip() for value in normalized.split(",") if value.strip()]


def _validate_production_secret_strength(secret: str, *, detail: str) -> None:
    if production_environment() and len(secret) < PRODUCTION_AUTH_SECRET_MIN_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail,
        )


def _secret() -> bytes:
    configured = os.environ.get("ALPHAFORGE_AUTH_SECRET", "")
    if production_environment() and not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_secret_required_in_production",
        )
    if configured:
        _validate_production_secret_strength(configured, detail="auth_secret_too_short_in_production")
    return (configured or _PROCESS_SECRET).encode("utf-8")


def _previous_secrets() -> list[bytes]:
    secrets_configured = _split_previous_secrets(os.environ.get("ALPHAFORGE_AUTH_PREVIOUS_SECRETS", ""))
    for previous_secret in secrets_configured:
        _validate_production_secret_strength(
            previous_secret,
            detail="auth_previous_secret_too_short_in_production",
        )
    return [previous_secret.encode("utf-8") for previous_secret in secrets_configured]


def _verification_secrets() -> list[bytes]:
    return [_secret(), *_previous_secrets()]


def _revocation_store_configured() -> bool:
    if _revocation_store_backend() == "sqlalchemy":
        return bool(os.environ.get("ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL", "").strip())
    return bool(os.environ.get("ALPHAFORGE_AUTH_REVOCATION_STORE", "").strip())


def _revocation_store_backend() -> str:
    return os.environ.get("ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND", "local_file").strip().lower()


def _production_local_revocation_store_override() -> bool:
    override = os.environ.get("ALPHAFORGE_ALLOW_LOCAL_REVOCATION_STORE_IN_PRODUCTION", "").strip().lower()
    return override in {"test", "test-only"} and bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _revocation_database_url() -> str:
    configured = os.environ.get("ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL", "").strip()
    if configured:
        return configured
    if production_environment():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_revocation_store_required_in_production",
        )
    return ""


def _revocation_db_auto_create_enabled() -> bool:
    return _truthy(os.environ.get("ALPHAFORGE_AUTH_REVOCATION_DB_AUTO_CREATE"))


def revocation_store_status() -> dict[str, Any]:
    backend = _revocation_store_backend()
    database_backend = backend in {"sqlalchemy", "database", "db"}
    database_configured = bool(os.environ.get("ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL", "").strip())
    file_configured = bool(os.environ.get("ALPHAFORGE_AUTH_REVOCATION_STORE", "").strip())
    production_env = production_environment()
    local_override = _production_local_revocation_store_override()
    durable_configured = database_backend and database_configured
    return {
        "backend": "sqlalchemy" if database_backend else "local_file",
        "production_environment": production_env,
        "database_backend_selected": database_backend,
        "database_url_configured": database_configured,
        "local_file_backend_selected": not database_backend,
        "local_file_path_configured": file_configured,
        "local_file_production_override_active": local_override,
        "local_file_production_access_fail_closed": production_env and not database_backend and not local_override,
        "auto_create_schema_enabled": _revocation_db_auto_create_enabled(),
        "durable_revocation_store_configured": durable_configured,
        "production_ready": production_env and durable_configured,
        "contains_secret_values": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "missing_fields": [] if durable_configured else [
            field
            for field, missing in (
                ("auth_revocation_database_backend", not database_backend),
                ("auth_revocation_database_url", not database_configured),
            )
            if missing
        ],
    }


def _require_production_revocation_store() -> None:
    if production_environment() and not _revocation_store_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_revocation_store_required_in_production",
        )
    if (
        production_environment()
        and _revocation_store_backend() not in {"sqlalchemy", "database", "db"}
        and not _production_local_revocation_store_override()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="production_auth_revocation_repository_required",
        )


def _issuer() -> str:
    configured = os.environ.get("ALPHAFORGE_AUTH_ISSUER", "").strip()
    if production_environment() and not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_issuer_required_in_production",
        )
    return configured or "alphaforge-v2"


def _audience() -> str:
    configured = os.environ.get("ALPHAFORGE_AUTH_AUDIENCE", "").strip()
    if production_environment() and not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_audience_required_in_production",
        )
    return configured or "alphaforge-web"


def _session_minutes_state() -> tuple[int, bool, bool]:
    raw = os.environ.get("ALPHAFORGE_AUTH_SESSION_MINUTES", "").strip()
    configured = bool(raw)
    if not configured:
        return 480, False, False
    try:
        parsed = int(raw)
    except ValueError:
        return 480, True, True
    invalid = parsed < 5 or parsed > 24 * 60
    return min(max(parsed, 5), 24 * 60), True, invalid


def session_minutes() -> int:
    minutes, configured, invalid = _session_minutes_state()
    if production_environment() and not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_session_minutes_required_in_production",
        )
    if production_environment() and invalid:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_session_minutes_invalid_in_production",
        )
    return minutes


def session_max_age_seconds() -> int:
    return session_minutes() * 60


def cookie_secure_enabled() -> bool:
    return _truthy(os.environ.get("ALPHAFORGE_AUTH_COOKIE_SECURE")) or production_environment()


def _cookie_samesite_state() -> tuple[str, bool, bool]:
    configured = os.environ.get("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "").strip().lower()
    if configured in {"strict", "lax", "none"}:
        return configured, True, False
    return "lax", bool(configured), bool(configured)


def cookie_samesite_value() -> str:
    value, configured, invalid = _cookie_samesite_state()
    if production_environment() and not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_cookie_samesite_required_in_production",
        )
    if production_environment() and invalid:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth_cookie_samesite_invalid_in_production",
        )
    return value


def _admin_step_up_secret() -> str:
    return os.environ.get("ALPHAFORGE_ADMIN_STEP_UP_TOTP_SECRET", "").strip().replace(" ", "")


def _totp_code(secret: str, *, counter: int) -> str:
    try:
        key = base64.b32decode(secret.upper(), casefold=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin_step_up_secret_invalid_in_production",
        ) from exc
    digest = hmac.new(key, counter.to_bytes(8, "big"), "sha1").digest()
    offset = digest[-1] & 0x0F
    code_int = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{code_int % 1_000_000:06d}"


def verify_admin_step_up_code(code: str | None, *, now: int | None = None) -> bool:
    secret = _admin_step_up_secret()
    if production_environment() and not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin_step_up_secret_required_in_production",
        )
    if not production_environment():
        return True
    normalized_code = str(code or "").strip()
    if not normalized_code:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_step_up_required")
    if not normalized_code.isdigit() or len(normalized_code) != 6:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_step_up_invalid")
    current_counter = int((now if now is not None else time.time()) // 30)
    valid_codes = {_totp_code(secret, counter=current_counter + offset) for offset in (-1, 0, 1)}
    if normalized_code not in valid_codes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_step_up_invalid")
    return True


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _revocation_store_path() -> Path:
    repo_root = _repo_root()
    default_path = (
        repo_root / "backend" / "auth_revocations.json"
        if (repo_root / "backend" / "app").exists()
        else repo_root / "v2" / "backend" / "auth_revocations.json"
    )
    return Path(
        os.environ.get(
            "ALPHAFORGE_AUTH_REVOCATION_STORE",
            str(default_path),
        )
    )


def _ensure_revocation_schema(engine_url: str) -> None:
    if not _revocation_db_auto_create_enabled():
        return
    engine = make_engine(engine_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS alphaforge_auth_revocations (
                    jti VARCHAR(128) PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                )
                """
            )
        )


def _read_sql_revocations() -> dict[str, int]:
    url = _revocation_database_url()
    try:
        _ensure_revocation_schema(url)
        engine = make_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT jti, expires_at FROM alphaforge_auth_revocations")
            ).mappings().all()
    except SQLAlchemyError as exc:
        if production_environment():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="auth_revocation_store_unreadable_in_production",
            ) from exc
        return {}
    clean: dict[str, int] = {}
    for row in rows:
        jti = row.get("jti")
        expires_at = row.get("expires_at")
        if not isinstance(jti, str) or not jti:
            continue
        try:
            clean[jti] = int(expires_at)
        except (TypeError, ValueError):
            continue
    return clean


def _write_sql_revocations(revoked: dict[str, int]) -> None:
    url = _revocation_database_url()
    try:
        _ensure_revocation_schema(url)
        engine = make_engine(url)
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM alphaforge_auth_revocations"))
            for jti, expires_at in revoked.items():
                connection.execute(
                    text(
                        """
                        INSERT INTO alphaforge_auth_revocations (jti, expires_at)
                        VALUES (:jti, :expires_at)
                        """
                    ),
                    {"jti": jti, "expires_at": int(expires_at)},
                )
    except SQLAlchemyError as exc:
        if production_environment():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="auth_revocation_store_unwritable_in_production",
            ) from exc


def session_security_status() -> dict[str, Any]:
    """Return secret-free session hardening posture for safe status payloads."""

    auth_secret = os.environ.get("ALPHAFORGE_AUTH_SECRET", "")
    auth_secret_too_short = bool(auth_secret) and len(auth_secret) < PRODUCTION_AUTH_SECRET_MIN_LENGTH
    previous_secrets = _split_previous_secrets(os.environ.get("ALPHAFORGE_AUTH_PREVIOUS_SECRETS", ""))
    previous_secret_too_short = any(len(previous_secret) < PRODUCTION_AUTH_SECRET_MIN_LENGTH for previous_secret in previous_secrets)
    admin_step_up_secret_configured = bool(_admin_step_up_secret())
    issuer_configured = bool(os.environ.get("ALPHAFORGE_AUTH_ISSUER", "").strip())
    audience_configured = bool(os.environ.get("ALPHAFORGE_AUTH_AUDIENCE", "").strip())
    revocation_store_configured = _revocation_store_configured()
    revocation_status = revocation_store_status()
    session_minutes_value, session_minutes_configured, session_minutes_invalid = _session_minutes_state()
    cookie_samesite, cookie_samesite_configured, cookie_samesite_invalid = _cookie_samesite_state()
    durable_session_store = False
    auth_store = auth_user_store_status()
    production_env = production_environment()
    secure_cookie = cookie_secure_enabled()
    production_ready = (
        production_env
        and bool(auth_secret)
        and not auth_secret_too_short
        and not previous_secret_too_short
        and issuer_configured
        and audience_configured
        and revocation_store_configured
        and revocation_status["durable_revocation_store_configured"]
        and session_minutes_configured
        and cookie_samesite_configured
        and admin_step_up_secret_configured
        and not session_minutes_invalid
        and not cookie_samesite_invalid
        and secure_cookie
        and auth_store["durable_user_store_configured"]
        and durable_session_store
    )
    return {
        "status": "production_configured" if production_ready else "partial",
        "production_ready": production_ready,
        "production_environment": production_env,
        "auth_secret_configured": bool(auth_secret),
        "production_auth_secret_min_length": PRODUCTION_AUTH_SECRET_MIN_LENGTH,
        "production_auth_secret_required": production_env,
        "production_auth_secret_fail_closed": production_env and not bool(auth_secret),
        "production_auth_secret_strength_fail_closed": production_env and auth_secret_too_short,
        "previous_auth_secrets_configured": len(previous_secrets),
        "auth_secret_rotation_supported": bool(previous_secrets),
        "auth_secret_rotation_policy": "active_secret_signs_previous_secrets_verify_only",
        "production_previous_auth_secret_strength_fail_closed": production_env and previous_secret_too_short,
        "issuer_configured": issuer_configured,
        "production_issuer_required": production_env,
        "production_issuer_fail_closed": production_env and not issuer_configured,
        "audience_configured": audience_configured,
        "production_audience_required": production_env,
        "production_audience_fail_closed": production_env and not audience_configured,
        "session_minutes": session_minutes_value,
        "session_minutes_configured": session_minutes_configured,
        "production_session_minutes_required": production_env,
        "production_session_minutes_fail_closed": production_env and (not session_minutes_configured or session_minutes_invalid),
        "cookie_httponly": True,
        "cookie_secure": secure_cookie,
        "cookie_samesite": cookie_samesite,
        "cookie_samesite_configured": cookie_samesite_configured,
        "production_cookie_samesite_required": production_env,
        "production_cookie_samesite_fail_closed": production_env and (not cookie_samesite_configured or cookie_samesite_invalid),
        "revocation_store_configured": revocation_store_configured,
        "production_revocation_store_required": production_env,
        "production_revocation_store_fail_closed": production_env and not revocation_store_configured,
        "production_revocation_store_error_fail_closed": production_env,
        "revocation_store_kind": revocation_status["backend"],
        "revocation_store": revocation_status,
        "auth_user_store": auth_store,
        "durable_user_store": bool(auth_store["durable_user_store_configured"]),
        "session_version_claim_enforced": True,
        "durable_session_store": durable_session_store,
        "durable_revocation_store": bool(revocation_status["durable_revocation_store_configured"]),
        "mfa_step_up_enabled": admin_step_up_secret_configured,
        "production_mfa_step_up_required": production_env,
        "production_mfa_step_up_fail_closed": production_env and not admin_step_up_secret_configured,
        "admin_step_up_method": "totp_env_secret" if admin_step_up_secret_configured else "unconfigured",
        "refresh_revokes_presented_token": True,
        "token_rotation_policy": "refresh_rotates_and_revokes_presented_token",
        "contains_secret_values": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
    }


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def create_access_token(user: UserRecord, *, minutes: int | None = None) -> str:
    _require_production_revocation_store()
    _previous_secrets()
    now = datetime.now(UTC)
    ttl_minutes = session_minutes() if minutes is None else min(max(int(minutes), 5), 24 * 60)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": _issuer(),
        "aud": _audience(),
        "sub": user["id"],
        "role": user["role"],
        "trader_id": user.get("trader_id"),
        "session_version": int(user.get("session_version") or 0),
        "jti": secrets.token_urlsafe(24),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
    }
    header_part = _b64encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    payload_part = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = _b64encode(hmac.new(_secret(), signing_input, sha256).digest())
    return f"{header_part}.{payload_part}.{signature}"


def _read_revocations() -> dict[str, int]:
    _require_production_revocation_store()
    if _revocation_store_backend() in {"sqlalchemy", "database", "db"}:
        return _read_sql_revocations()
    path = _revocation_store_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        if production_environment():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="auth_revocation_store_unreadable_in_production",
            )
        return {}
    revoked = payload.get("revoked") if isinstance(payload, dict) else None
    if not isinstance(revoked, dict):
        return {}
    clean: dict[str, int] = {}
    for jti, exp in revoked.items():
        if not isinstance(jti, str) or not jti:
            continue
        try:
            clean[jti] = int(exp)
        except (TypeError, ValueError):
            continue
    return clean


def _write_revocations(revoked: dict[str, int]) -> None:
    if _revocation_store_backend() in {"sqlalchemy", "database", "db"}:
        _write_sql_revocations(revoked)
        return
    path = _revocation_store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps({"revoked": revoked}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        if production_environment():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="auth_revocation_store_unwritable_in_production",
            )
        return


def _pruned_revocations(now_ts: int) -> dict[str, int]:
    return {jti: exp for jti, exp in _read_revocations().items() if exp >= now_ts}


def _is_revoked(payload: dict[str, Any]) -> bool:
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        return True
    now_ts = int(datetime.now(UTC).timestamp())
    with _REVOCATION_LOCK:
        existing = _read_revocations()
        revoked = {jti: exp for jti, exp in existing.items() if exp >= now_ts}
        if len(revoked) != len(existing):
            _write_revocations(revoked)
        return jti in revoked


def _session_version_matches(payload: dict[str, Any], user: UserRecord) -> bool:
    token_version = payload.get("session_version")
    if token_version is None:
        token_version = 0
    try:
        return int(token_version) == int(user.get("session_version") or 0)
    except (TypeError, ValueError):
        return False


def _decode_token(token: str, *, check_revocation: bool = True) -> dict[str, Any]:
    try:
        header_part, payload_part, signature = token.split(".", 2)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session") from exc
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    if not any(
        hmac.compare_digest(signature, _b64encode(hmac.new(secret, signing_input, sha256).digest()))
        for secret in _verification_secrets()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    try:
        header = json.loads(_b64decode(header_part))
        payload = json.loads(_b64decode(payload_part))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    if payload.get("iss") != _issuer() or payload.get("aud") != _audience():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(datetime.now(UTC).timestamp()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_expired")
    iat = payload.get("iat")
    if not isinstance(iat, int) or iat > int(datetime.now(UTC).timestamp()) + 60:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    if check_revocation and _is_revoked(payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_revoked")
    return payload


def _token_from_auth_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def session_token_from_inputs(authorization: str | None, session_cookie: str | None) -> str | None:
    return _token_from_auth_header(authorization) or session_cookie


def revoke_access_token(token: str | None) -> bool:
    if not token:
        return False
    payload = _decode_token(token, check_revocation=False)
    jti = payload.get("jti")
    exp = payload.get("exp")
    if not isinstance(jti, str) or not isinstance(exp, int):
        return False
    now_ts = int(datetime.now(UTC).timestamp())
    with _REVOCATION_LOCK:
        revoked = _pruned_revocations(now_ts)
        revoked[jti] = exp
        _write_revocations(revoked)
    return True


async def require_auth(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    store: UserStore = Depends(get_user_store),
) -> UserRecord:
    token = session_token_from_inputs(authorization, session_cookie)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication_required")
    payload = _decode_token(token)
    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_session")
    user = store.get_user(user_id)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="inactive_or_missing_user")
    if not _session_version_matches(payload, user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session_revoked")
    return user


async def optional_auth(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    store: UserStore = Depends(get_user_store),
) -> UserRecord | None:
    token = session_token_from_inputs(authorization, session_cookie)
    if not token:
        return None
    try:
        payload = _decode_token(token)
    except HTTPException:
        return None
    user_id = payload.get("sub")
    if not isinstance(user_id, str):
        return None
    user = store.get_user(user_id)
    if not user or not user.get("is_active"):
        return None
    if not _session_version_matches(payload, user):
        return None
    return user


def require_role(min_role: Role):
    threshold = ROLE_RANK[min_role]

    async def _dependency(user: UserRecord = Depends(require_auth)) -> UserRecord:
        role = str(user.get("role", "guest"))
        if ROLE_RANK.get(role, 0) < threshold:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
        return user

    return _dependency


def require_any_role(*roles: Role):
    allowed = set(roles)

    async def _dependency(user: UserRecord = Depends(require_auth)) -> UserRecord:
        if str(user.get("role", "guest")) not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient_role")
        return user

    return _dependency


require_admin = require_role("admin")
require_superadmin = require_role("superadmin")
