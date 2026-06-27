"""Minimal file-backed user repository.

The repository is local/dev oriented and exists so backend auth/RBAC can be
server-enforced before a durable database-backed account service lands. It
stores bcrypt password hashes only and never stores plaintext passwords.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.db.engine import make_engine
from app.services.credential_status import safe_account_credential_status

Role = Literal["guest", "viewer", "trader", "admin", "superadmin"]
ROLES: set[str] = {"guest", "viewer", "trader", "admin", "superadmin"}


def _validate_user_scope(
    *,
    role: str,
    trader_id: str | None,
    paper_account_id: str | None,
    exchange_accounts: list[dict[str, Any]] | None = None,
) -> None:
    if role == "trader" and (not trader_id or not paper_account_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="trader_scope_required")
    if exchange_accounts and (not trader_id or not paper_account_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="exchange_account_scope_required")
    if exchange_accounts and role not in {"trader", "admin", "superadmin"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="exchange_account_role_required")


def _validate_unique_paper_account_scope(
    users: list["UserRecord"],
    *,
    current_user_id: str | None,
    paper_account_id: str | None,
    trader_id: str | None = None,
) -> None:
    normalized_paper_account_id = paper_account_id.strip() if isinstance(paper_account_id, str) else ""
    normalized_trader_id = trader_id.strip() if isinstance(trader_id, str) else ""
    if not normalized_paper_account_id and not normalized_trader_id:
        return
    for user in users:
        if current_user_id and user.get("id") == current_user_id:
            continue
        if normalized_trader_id and str(user.get("trader_id") or "").strip() == normalized_trader_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="trader_id_exists")
        if normalized_paper_account_id and str(user.get("paper_account_id") or "").strip() == normalized_paper_account_id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="paper_account_id_exists")


class ExchangeAccountRecord(TypedDict, total=False):
    id: str
    trader_id: str | None
    paper_account_id: str | None
    exchange: str
    label: str
    account_type: str
    mode: str
    credential_ref: str | None
    read_only: bool
    live_trading_enabled: bool
    status: str
    created_at: str
    updated_at: str


class UserRecord(TypedDict, total=False):
    id: str
    trader_id: str | None
    username: str
    email: str
    password_hash: str
    role: Role
    paper_account_id: str | None
    exchange_accounts: list[ExchangeAccountRecord]
    watchlist: list[str]
    alert_preferences: dict[str, Any]
    is_active: bool
    created_at: str
    updated_at: str
    last_login: str | None
    session_version: int


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _default_store_path() -> Path:
    return _repo_root() / "v2" / "backend" / "auth_users.json"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _production_environment() -> bool:
    return os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _auth_store_backend() -> str:
    return os.environ.get("ALPHAFORGE_AUTH_STORE_BACKEND", "local_file").strip().lower()


def _production_local_auth_store_override() -> bool:
    override = os.environ.get("ALPHAFORGE_ALLOW_LOCAL_AUTH_STORE_IN_PRODUCTION", "").strip().lower()
    return override in {"test", "test-only"} and bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _require_auth_user_repository() -> None:
    if _production_environment() and not _production_local_auth_store_override():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="production_auth_user_repository_required",
        )


def _auth_database_url() -> str:
    configured = os.environ.get("ALPHAFORGE_AUTH_DATABASE_URL", "").strip()
    if configured:
        return configured
    if _production_environment():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="production_auth_user_repository_required",
        )
    return ""


def _auth_database_auto_create_enabled() -> bool:
    return _truthy(os.environ.get("ALPHAFORGE_AUTH_DB_AUTO_CREATE"))


def auth_user_store_status() -> dict[str, Any]:
    backend = _auth_store_backend()
    production = _production_environment()
    database_configured = bool(os.environ.get("ALPHAFORGE_AUTH_DATABASE_URL", "").strip())
    database_backend = backend in {"sqlalchemy", "database", "db"}
    local_override = _production_local_auth_store_override()
    production_ready = production and database_backend and database_configured
    return {
        "backend": "sqlalchemy" if database_backend else "local_file",
        "production_environment": production,
        "database_url_configured": database_configured,
        "database_backend_selected": database_backend,
        "local_file_backend_selected": not database_backend,
        "local_file_production_override_active": local_override,
        "local_file_production_access_fail_closed": production and not database_backend and not local_override,
        "auto_create_schema_enabled": _auth_database_auto_create_enabled(),
        "durable_user_store_configured": database_backend and database_configured,
        "production_ready": production_ready,
        "contains_secret_values": False,
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "missing_fields": [] if production_ready else [
            field
            for field, missing in (
                ("auth_database_backend", not database_backend),
                ("auth_database_url", not database_configured),
            )
            if missing
        ],
    }


def _validate_password_policy(password: str) -> None:
    if not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_required")
    if not _production_environment():
        return
    if len(password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_policy_too_short")
    checks = {
        "lower": any(ch.islower() for ch in password),
        "upper": any(ch.isupper() for ch in password),
        "digit": any(ch.isdigit() for ch in password),
        "symbol": any(not ch.isalnum() for ch in password),
    }
    if not all(checks.values()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_policy_complexity_required")


def _hash_password(password: str) -> str:
    try:
        import bcrypt
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise RuntimeError("bcrypt is required for password hashing") from exc
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        import bcrypt
    except Exception as exc:  # pragma: no cover - dependency failure path
        raise RuntimeError("bcrypt is required for password verification") from exc
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


_SAFE_EXCHANGE_ACCOUNT_FIELDS = {
    "id",
    "trader_id",
    "paper_account_id",
    "exchange",
    "label",
    "account_type",
    "mode",
    "credential_ref",
    "read_only",
    "live_trading_enabled",
    "status",
    "created_at",
    "updated_at",
}


def safe_exchange_accounts(accounts: Any, *, expose_credential_ref: bool = False) -> list[dict[str, Any]]:
    if not isinstance(accounts, list):
        return []
    safe: list[dict[str, Any]] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        fields = _SAFE_EXCHANGE_ACCOUNT_FIELDS if expose_credential_ref else _SAFE_EXCHANGE_ACCOUNT_FIELDS.difference({"credential_ref"})
        safe_account = {key: account.get(key) for key in fields if key in account}
        safe_account["credential_status"] = safe_account_credential_status(account, expose_credential_ref=expose_credential_ref)
        safe.append(safe_account)
    return safe


def _scoped_exchange_accounts(
    accounts: Any,
    trader_id: str | None,
    paper_account_id: str | None,
) -> list[dict[str, Any]]:
    scoped = safe_exchange_accounts(accounts, expose_credential_ref=True)
    normalized_trader_id = trader_id.strip() if isinstance(trader_id, str) and trader_id.strip() else None
    normalized_paper_account_id = (
        paper_account_id.strip()
        if isinstance(paper_account_id, str) and paper_account_id.strip()
        else None
    )
    normalized: list[dict[str, Any]] = []
    for account in scoped:
        stored_account = {key: value for key, value in account.items() if key != "credential_status"}
        stored_account["trader_id"] = normalized_trader_id
        stored_account["paper_account_id"] = normalized_paper_account_id
        stored_account["mode"] = "read_only"
        stored_account["read_only"] = True
        stored_account["live_trading_enabled"] = False
        stored_account["status"] = safe_account_credential_status(stored_account)["status"]
        normalized.append(stored_account)
    return normalized


def _safe_user_exchange_accounts(user: UserRecord) -> list[dict[str, Any]]:
    trader_id = user.get("trader_id")
    paper_account_id = user.get("paper_account_id")
    if not trader_id or not paper_account_id:
        return []
    scoped: list[dict[str, Any]] = []
    for account in safe_exchange_accounts(user.get("exchange_accounts")):
        if (
            account.get("trader_id") == trader_id
            and account.get("paper_account_id") == paper_account_id
            and account.get("read_only") is True
            and account.get("live_trading_enabled") is False
        ):
            scoped.append(account)
    return scoped


def safe_user(user: UserRecord) -> dict[str, Any]:
    now = _now()
    return {
        "id": user.get("id", "unknown"),
        "trader_id": user.get("trader_id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "role": user.get("role", "trader"),
        "paper_account_id": user.get("paper_account_id"),
        "exchange_accounts": _safe_user_exchange_accounts(user),
        "watchlist": user.get("watchlist", []),
        "alert_preferences": user.get("alert_preferences", {}),
        "is_active": bool(user.get("is_active")),
        "created_at": user.get("created_at", now),
        "updated_at": user.get("updated_at", now),
        "last_login": user.get("last_login"),
    }


class UserStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get("ALPHAFORGE_AUTH_STORE", _default_store_path()))
        self._lock = threading.Lock()

    def _read(self) -> list[UserRecord]:
        _require_auth_user_repository()
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        users = payload.get("users") if isinstance(payload, dict) else None
        return users if isinstance(users, list) else []

    def _write(self, users: list[UserRecord]) -> None:
        _require_auth_user_repository()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps({"users": users}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def ensure_bootstrap_admin(self) -> None:
        email = os.environ.get("ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "")
        if not email or not password:
            return
        _validate_password_policy(password)
        with self._lock:
            users = self._read()
            if any(u.get("role") in ("admin", "superadmin") for u in users):
                return
            now = _now()
            users.append(
                {
                    "id": str(uuid4()),
                    "trader_id": "bootstrap-admin",
                    "username": email.split("@", 1)[0],
                    "email": email,
                    "password_hash": _hash_password(password),
                    "role": "admin",
                    "paper_account_id": None,
                    "exchange_accounts": [],
                    "watchlist": [],
                    "alert_preferences": {},
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                    "last_login": None,
                    "session_version": 0,
                }
            )
            self._write(users)

    def ensure_initial_trader(self) -> None:
        enabled = os.environ.get("ALPHAFORGE_SEED_INITIAL_TRADER", "true").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            return
        email = os.environ.get("ALPHAFORGE_INITIAL_TRADER_EMAIL", "wajidali1984@hotmail.com").strip().lower()
        username = os.environ.get("ALPHAFORGE_INITIAL_TRADER_USERNAME", "wajidali1984").strip() or "wajidali1984"
        trader_id = os.environ.get("ALPHAFORGE_INITIAL_TRADER_ID", "trader-wajidali1984").strip()
        paper_account_id = os.environ.get("ALPHAFORGE_INITIAL_TRADER_PAPER_ACCOUNT_ID", "paper-wajidali1984").strip()
        exchange_account_id = os.environ.get("ALPHAFORGE_INITIAL_TRADER_BINANCE_ACCOUNT_ID", "binance-wajidali1984").strip()
        exchange_label = os.environ.get("ALPHAFORGE_INITIAL_TRADER_BINANCE_LABEL", "Wajid Ali Binance Futures").strip()
        exchange_account_type = os.environ.get("ALPHAFORGE_INITIAL_TRADER_BINANCE_ACCOUNT_TYPE", "usd_m_futures").strip()
        credential_ref = os.environ.get(
            "ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF",
            "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY",
        ).strip()
        password = os.environ.get("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "")
        password_hash_override = os.environ.get("ALPHAFORGE_INITIAL_TRADER_PASSWORD_HASH", "").strip()
        if password:
            _validate_password_policy(password)
        if not email or "@" not in email or not trader_id or not paper_account_id or not exchange_account_id:
            return
        with self._lock:
            users = self._read()
            now = _now()
            exchange_account: ExchangeAccountRecord = {
                "id": exchange_account_id,
                "trader_id": trader_id,
                "paper_account_id": paper_account_id,
                "exchange": "binance",
                "label": exchange_label or "Wajid Ali Binance Futures",
                "account_type": exchange_account_type or "usd_m_futures",
                "mode": "read_only",
                "credential_ref": credential_ref or None,
                "read_only": True,
                "live_trading_enabled": False,
                "status": "credential_source_pending",
                "created_at": now,
                "updated_at": now,
            }
            exchange_account["status"] = safe_account_credential_status(exchange_account)["status"]
            for index, user in enumerate(users):
                if str(user.get("email", "")).lower() != email:
                    continue
                next_user: UserRecord = dict(user)
                changed = False
                if next_user.get("role") != "trader":
                    next_user["role"] = "trader"
                    changed = True
                if username and next_user.get("username") != username:
                    next_user["username"] = username
                    changed = True
                for key, value in {
                    "trader_id": trader_id,
                    "paper_account_id": paper_account_id,
                }.items():
                    if next_user.get(key) != value:
                        next_user[key] = value  # type: ignore[typeddict-item]
                        changed = True
                accounts = _scoped_exchange_accounts(
                    next_user.get("exchange_accounts"),
                    trader_id,
                    paper_account_id,
                )
                matched = False
                for account_index, account in enumerate(accounts):
                    if account.get("id") != exchange_account["id"]:
                        continue
                    matched = True
                    next_account = {
                        **account,
                        **exchange_account,
                        "created_at": account.get("created_at") or exchange_account["created_at"],
                        "updated_at": account.get("updated_at") or exchange_account["updated_at"],
                    }
                    if next_account != account:
                        next_account["updated_at"] = now
                        accounts[account_index] = next_account
                        changed = True
                    break
                if not matched:
                    accounts.insert(0, exchange_account)
                    changed = True
                if not next_user.get("watchlist"):
                    next_user["watchlist"] = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
                    changed = True
                if password_hash_override and next_user.get("password_hash") != password_hash_override:
                    next_user["password_hash"] = password_hash_override
                    next_user["is_active"] = True
                    next_user["session_version"] = int(next_user.get("session_version") or 0) + 1
                    changed = True
                elif password:
                    if not next_user.get("is_active"):
                        # Only reset password for inactive users — active users may have
                        # admin-set passwords that must not be overwritten by the seed default.
                        next_user["password_hash"] = _hash_password(password)
                        next_user["is_active"] = True
                        next_user["session_version"] = int(next_user.get("session_version") or 0) + 1
                        changed = True
                if changed:
                    _validate_user_scope(
                        role=str(next_user.get("role", "guest")),
                        trader_id=next_user.get("trader_id"),
                        paper_account_id=next_user.get("paper_account_id"),
                        exchange_accounts=accounts,
                    )
                    _validate_unique_paper_account_scope(
                        users,
                        current_user_id=str(next_user.get("id") or ""),
                        paper_account_id=str(next_user.get("paper_account_id") or ""),
                        trader_id=str(next_user.get("trader_id") or ""),
                    )
                    next_user["exchange_accounts"] = accounts  # type: ignore[typeddict-item]
                    next_user["updated_at"] = now
                    users[index] = next_user
                    self._write(users)
                return
            _validate_unique_paper_account_scope(
                users,
                current_user_id=None,
                paper_account_id=paper_account_id,
                trader_id=trader_id,
            )
            _validate_user_scope(
                role="trader",
                trader_id=trader_id,
                paper_account_id=paper_account_id,
                exchange_accounts=[exchange_account],
            )
            _resolved_hash = (
                password_hash_override
                if password_hash_override
                else _hash_password(password)
                if password
                else None
            )
            users.append(
                {
                    "id": "user-wajidali1984",
                    "trader_id": trader_id,
                    "username": username,
                    "email": email,
                    "password_hash": _resolved_hash or _hash_password(secrets.token_urlsafe(48)),
                    "role": "trader",
                    "paper_account_id": paper_account_id,
                    "exchange_accounts": [exchange_account],
                    "watchlist": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
                    "alert_preferences": {},
                    "is_active": bool(_resolved_hash),
                    "created_at": now,
                    "updated_at": now,
                    "last_login": None,
                    "session_version": 0,
                }
            )
            self._write(users)

    def ensure_seed_users(self) -> None:
        self.ensure_bootstrap_admin()
        self.ensure_initial_trader()

    def list_users(self) -> list[UserRecord]:
        self.ensure_seed_users()
        return self._read()

    def get_user(self, user_id: str) -> UserRecord | None:
        self.ensure_seed_users()
        return next((u for u in self._read() if u.get("id") == user_id), None)

    def get_by_email(self, email: str) -> UserRecord | None:
        self.ensure_seed_users()
        normalized = email.strip().lower()
        return next((u for u in self._read() if str(u.get("email", "")).lower() == normalized), None)

    def authenticate(self, email: str, password: str) -> UserRecord | None:
        user = self.get_by_email(email)
        if not user or not user.get("is_active"):
            return None
        if not _verify_password(password, str(user.get("password_hash", ""))):
            return None
        self.touch_login(user["id"])
        return self.get_user(user["id"])

    def create_user(
        self,
        *,
        email: str,
        username: str,
        password: str,
        role: str,
        trader_id: str | None = None,
        paper_account_id: str | None = None,
        exchange_accounts: list[dict[str, Any]] | None = None,
        watchlist: list[str] | None = None,
        alert_preferences: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> UserRecord:
        if role not in ROLES or role == "guest":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_role")
        normalized_email = email.strip().lower()
        if not normalized_email or "@" not in normalized_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email")
        if not password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="password_required")
        _validate_password_policy(password)
        _validate_user_scope(
            role=role,
            trader_id=trader_id,
            paper_account_id=paper_account_id,
            exchange_accounts=exchange_accounts,
        )
        with self._lock:
            users = self._read()
            if any(str(u.get("email", "")).lower() == normalized_email for u in users):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_exists")
            _validate_unique_paper_account_scope(
                users,
                current_user_id=None,
                paper_account_id=paper_account_id,
                trader_id=trader_id,
            )
            now = _now()
            user: UserRecord = {
                "id": str(uuid4()),
                "trader_id": trader_id,
                "username": username.strip() or normalized_email.split("@", 1)[0],
                "email": normalized_email,
                "password_hash": _hash_password(password),
                "role": role,  # type: ignore[typeddict-item]
                "paper_account_id": paper_account_id,
                "exchange_accounts": _scoped_exchange_accounts(exchange_accounts, trader_id, paper_account_id),
                "watchlist": watchlist or [],
                "alert_preferences": alert_preferences or {},
                "is_active": is_active,
                "created_at": now,
                "updated_at": now,
                "last_login": None,
                "session_version": 0,
            }
            users.append(user)
            self._write(users)
            return user

    def update_user(self, user_id: str, updates: dict[str, Any]) -> UserRecord:
        with self._lock:
            users = self._read()
            if not any(existing.get("id") == user_id for existing in users):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
            normalized_updates = dict(updates)
            if "email" in normalized_updates:
                normalized_email = str(normalized_updates["email"]).strip().lower()
                if not normalized_email or "@" not in normalized_email:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_email")
                if any(
                    existing.get("id") != user_id
                    and str(existing.get("email", "")).strip().lower() == normalized_email
                    for existing in users
                ):
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email_exists")
                normalized_updates["email"] = normalized_email
            for index, user in enumerate(users):
                if user.get("id") != user_id:
                    continue
                next_user = dict(user)
                for key in (
                    "trader_id",
                    "username",
                    "email",
                    "role",
                    "paper_account_id",
                    "exchange_accounts",
                    "watchlist",
                    "alert_preferences",
                    "is_active",
                ):
                    if key in normalized_updates:
                        if key == "role" and normalized_updates[key] not in ROLES:
                            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_role")
                        next_user[key] = (
                            _scoped_exchange_accounts(
                                normalized_updates[key],
                                next_user.get("trader_id"),
                                next_user.get("paper_account_id"),
                            )
                            if key == "exchange_accounts"
                            else normalized_updates[key]
                        )
                if ("trader_id" in normalized_updates or "paper_account_id" in normalized_updates) and "exchange_accounts" not in normalized_updates:
                    next_user["exchange_accounts"] = _scoped_exchange_accounts(
                        next_user.get("exchange_accounts"),
                        next_user.get("trader_id"),
                        next_user.get("paper_account_id"),
                    )  # type: ignore[typeddict-item]
                _validate_user_scope(
                    role=str(next_user.get("role", "guest")),
                    trader_id=next_user.get("trader_id"),
                    paper_account_id=next_user.get("paper_account_id"),
                    exchange_accounts=next_user.get("exchange_accounts"),
                )
                _validate_unique_paper_account_scope(
                    users,
                    current_user_id=user_id,
                    paper_account_id=next_user.get("paper_account_id"),
                    trader_id=next_user.get("trader_id"),
                )
                if normalized_updates.get("password"):
                    _validate_password_policy(str(normalized_updates["password"]))
                    next_user["password_hash"] = _hash_password(str(normalized_updates["password"]))
                    next_user["session_version"] = int(next_user.get("session_version") or 0) + 1
                next_user["updated_at"] = _now()
                users[index] = next_user  # type: ignore[list-item]
                self._write(users)
                return next_user  # type: ignore[return-value]
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            users = self._read()
            next_users = [u for u in users if u.get("id") != user_id]
            if len(next_users) == len(users):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user_not_found")
            self._write(next_users)

    def touch_login(self, user_id: str) -> None:
        with self._lock:
            users = self._read()
            for user in users:
                if user.get("id") == user_id:
                    user["last_login"] = _now()
                    user["updated_at"] = _now()
                    self._write(users)
                    return


class SqlAlchemyUserStore(UserStore):
    """SQL-backed user repository selected explicitly by environment.

    The table stores the safe auth user record as JSON plus indexed ownership
    columns. Schema creation is opt-in so production deployments can use
    migrations instead of implicit application DDL.
    """

    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or _auth_database_url()
        if not self.database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="auth_database_url_required",
            )
        self.path = Path("sqlalchemy-auth-user-store")
        self._lock = threading.Lock()
        self._engine = make_engine(self.database_url)

    def _ensure_schema(self) -> None:
        if not _auth_database_auto_create_enabled():
            return
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS alphaforge_auth_users (
                        id VARCHAR(128) PRIMARY KEY,
                        email VARCHAR(320) NOT NULL UNIQUE,
                        trader_id VARCHAR(128) UNIQUE,
                        paper_account_id VARCHAR(128) UNIQUE,
                        payload_json TEXT NOT NULL,
                        updated_at VARCHAR(64) NOT NULL
                    )
                    """
                )
            )
            if self._engine.dialect.name == "sqlite":
                columns = {
                    row["name"]
                    for row in connection.execute(text("PRAGMA table_info(alphaforge_auth_users)")).mappings().all()
                }
                if "trader_id" not in columns:
                    connection.execute(text("ALTER TABLE alphaforge_auth_users ADD COLUMN trader_id VARCHAR(128)"))
                connection.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_alphaforge_auth_users_trader_id
                        ON alphaforge_auth_users (trader_id)
                        """
                    )
                )

    def _database_unavailable(self, exc: Exception) -> HTTPException:
        detail = (
            "production_auth_user_repository_unavailable"
            if _production_environment()
            else "auth_user_repository_unavailable"
        )
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)

    def _read(self) -> list[UserRecord]:
        try:
            self._ensure_schema()
            with self._engine.connect() as connection:
                rows = connection.execute(
                    text("SELECT payload_json FROM alphaforge_auth_users ORDER BY email ASC")
                ).mappings().all()
        except SQLAlchemyError as exc:
            raise self._database_unavailable(exc)
        users: list[UserRecord] = []
        for row in rows:
            try:
                payload = json.loads(str(row["payload_json"]))
            except (KeyError, TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                users.append(payload)  # type: ignore[arg-type]
        return users

    def _write(self, users: list[UserRecord]) -> None:
        try:
            self._ensure_schema()
            with self._engine.begin() as connection:
                connection.execute(text("DELETE FROM alphaforge_auth_users"))
                for user in users:
                    connection.execute(
                        text(
                            """
                            INSERT INTO alphaforge_auth_users
                                (id, email, trader_id, paper_account_id, payload_json, updated_at)
                            VALUES
                                (:id, :email, :trader_id, :paper_account_id, :payload_json, :updated_at)
                            """
                        ),
                        {
                            "id": str(user.get("id") or ""),
                            "email": str(user.get("email") or "").lower(),
                            "trader_id": str(user.get("trader_id") or "").strip() or None,
                            "paper_account_id": str(user.get("paper_account_id") or "").strip() or None,
                            "payload_json": json.dumps(user, sort_keys=True),
                            "updated_at": str(user.get("updated_at") or _now()),
                        },
                    )
        except SQLAlchemyError as exc:
            raise self._database_unavailable(exc)


def get_user_store() -> UserStore:
    if _auth_store_backend() in {"sqlalchemy", "database", "db"}:
        return SqlAlchemyUserStore()
    return UserStore()
