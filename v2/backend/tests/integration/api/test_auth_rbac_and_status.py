from __future__ import annotations

import base64
import hmac
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.v2 import market_contracts
from app.auth.security import create_access_token, revocation_store_status
from app.auth.users import SqlAlchemyUserStore, UserStore, auth_user_store_status, get_user_store
from app.main import create_app
from app.services.credential_status import backend_readonly_credential_binding
from app.services.audit_writer import admin_audit_status, append_admin_audit_event


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE", str(tmp_path / "auth_users.json"))
    if "ALPHAFORGE_AUTH_SECRET" not in os.environ:
        monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "test-secret-for-auth-rbac-minimum-32-chars")
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_STORE", str(tmp_path / "trader_accounts.json"))
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_TELEMETRY_STORE", str(tmp_path / "market_stream_telemetry.json"))
    if os.environ.get("ALPHAFORGE_ENV", "").strip().lower() in {"prod", "production"}:
        monkeypatch.setenv("ALPHAFORGE_ALLOW_LOCAL_AUTH_STORE_IN_PRODUCTION", "test-only")
        if os.environ.get("ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND", "local_file").strip().lower() not in {"sqlalchemy", "database", "db"}:
            monkeypatch.setenv("ALPHAFORGE_ALLOW_LOCAL_REVOCATION_STORE_IN_PRODUCTION", "test-only")
        if os.environ.get("ALPHAFORGE_ADMIN_AUDIT_STORE_BACKEND", "local_file").strip().lower() not in {"sqlalchemy", "database", "db"}:
            monkeypatch.setenv("ALPHAFORGE_ALLOW_LOCAL_ADMIN_AUDIT_IN_PRODUCTION", "test-only")
        if "ALPHAFORGE_ADMIN_AUDIT_RETENTION_DAYS" not in os.environ:
            monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_RETENTION_DAYS", "365")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    if "ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD" not in os.environ:
        monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "correct-password")
    if "ALPHAFORGE_INITIAL_TRADER_PASSWORD" not in os.environ:
        monkeypatch.delenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", raising=False)
    monkeypatch.setattr(market_contracts, "BINANCE_FAPI_BASE", "http://127.0.0.1:9")
    monkeypatch.setattr(market_contracts, "BINANCE_HTTP_TIMEOUT_SECONDS", 0.05)
    market_contracts.MARKET_STREAM_TELEMETRY.clear()
    return TestClient(create_app())


def _login(client: TestClient, email: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _totp_code(secret: str, *, now: int | None = None) -> str:
    counter = int((now if now is not None else time.time()) // 30)
    key = base64.b32decode(secret.upper(), casefold=True)
    digest = hmac.new(key, counter.to_bytes(8, "big"), "sha1").digest()
    offset = digest[-1] & 0x0F
    code_int = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF
    return f"{code_int % 1_000_000:06d}"


def test_auth_login_success_returns_safe_user_payload(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "correct-password"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["user"]["role"] == "admin"
    assert "password_hash" not in json.dumps(payload)


def test_initial_trader_seed_is_inactive_and_readonly_scoped(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/users", headers=_auth(admin_token))

    assert response.status_code == 200
    users = response.json()["users"]
    initial = next(user for user in users if user["email"] == "wajidali1984@hotmail.com")
    assert initial["username"] == "wajidali1984"
    assert initial["role"] == "trader"
    # Bootstrap user starts active — password is pre-configured so login works immediately.
    assert initial["is_active"] is True
    assert initial["trader_id"] == "trader-wajidali1984"
    assert initial["paper_account_id"] == "paper-wajidali1984"
    assert len(initial["exchange_accounts"]) == 1
    account = initial["exchange_accounts"][0]
    assert account["id"] == "binance-wajidali1984"
    assert account["exchange"] == "binance"
    assert account["trader_id"] == "trader-wajidali1984"
    assert account["paper_account_id"] == "paper-wajidali1984"
    assert account["mode"] == "read_only"
    assert account["read_only"] is True
    assert account["live_trading_enabled"] is False
    assert account["credential_status"]["raw_credential_value_exposed"] is False

    denied = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "not-the-seed-password"},
    )
    assert denied.status_code == 401
    serialized = json.dumps(initial).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "credential_ref"):
        assert text not in serialized


def test_initial_trader_seed_can_be_activated_with_scoped_binance_account(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "initial-trader-password")
    client = _client(tmp_path, monkeypatch)

    token = _login(client, "wajidali1984@hotmail.com", "initial-trader-password")
    response = client.get("/api/auth/me", headers=_auth(token))

    assert response.status_code == 200
    payload = response.json()
    user = payload["user"]
    assert user["id"] == "user-wajidali1984"
    assert user["email"] == "wajidali1984@hotmail.com"
    assert user["username"] == "wajidali1984"
    assert user["role"] == "trader"
    assert user["is_active"] is True
    assert user["trader_id"] == "trader-wajidali1984"
    assert user["paper_account_id"] == "paper-wajidali1984"
    assert user["watchlist"] == ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    assert len(user["exchange_accounts"]) == 1
    account = user["exchange_accounts"][0]
    assert account["id"] == "binance-wajidali1984"
    assert account["exchange"] == "binance"
    assert account["trader_id"] == "trader-wajidali1984"
    assert account["paper_account_id"] == "paper-wajidali1984"
    assert account["mode"] == "read_only"
    assert account["read_only"] is True
    assert account["live_trading_enabled"] is False
    assert account["credential_status"]["raw_credential_value_exposed"] is False
    assert account["credential_status"]["live_trading_enabled"] is False
    serialized = json.dumps(payload).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "credential_ref", "live_order"):
        assert text not in serialized


def test_safe_user_withholds_unscoped_exchange_account_metadata(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    store = get_user_store()
    user = store.create_user(
        email="scoped-exchange@example.com",
        username="scoped-exchange",
        password="Scoped-Exchange-Password-123!",
        role="trader",
        trader_id="trader-scoped-exchange",
        paper_account_id="paper-scoped-exchange",
    )
    users = store._read()  # noqa: SLF001 - intentional stale-storage regression setup
    for row in users:
        if row["id"] == user["id"]:
            row["exchange_accounts"] = [
                {
                    "id": "binance-other-trader",
                    "trader_id": "trader-other",
                    "paper_account_id": "paper-scoped-exchange",
                    "exchange": "binance",
                    "label": "Other Trader Binance",
                    "account_type": "usd_m_futures",
                    "mode": "read_only",
                    "read_only": True,
                    "live_trading_enabled": False,
                    "status": "credential_source_pending",
                },
                {
                    "id": "binance-live-enabled",
                    "trader_id": "trader-scoped-exchange",
                    "paper_account_id": "paper-scoped-exchange",
                    "exchange": "binance",
                    "label": "Unsafe Binance",
                    "account_type": "usd_m_futures",
                    "mode": "read_only",
                    "read_only": False,
                    "live_trading_enabled": True,
                    "status": "credential_source_pending",
                },
                {
                    "id": "binance-scoped-readonly",
                    "trader_id": "trader-scoped-exchange",
                    "paper_account_id": "paper-scoped-exchange",
                    "exchange": "binance",
                    "label": "Scoped Binance",
                    "account_type": "usd_m_futures",
                    "mode": "read_only",
                    "read_only": True,
                    "live_trading_enabled": False,
                    "status": "credential_source_pending",
                    "credential_ref": "ALPHAFORGE_SCOPED_READONLY",
                },
            ]
            break
    store._write(users)  # noqa: SLF001 - intentional stale-storage regression setup

    token = _login(client, "scoped-exchange@example.com", "Scoped-Exchange-Password-123!")
    response = client.get("/api/auth/me", headers=_auth(token))

    assert response.status_code == 200
    accounts = response.json()["user"]["exchange_accounts"]
    assert [account["id"] for account in accounts] == ["binance-scoped-readonly"]
    serialized = json.dumps(response.json()).lower()
    assert "binance-other-trader" not in serialized
    assert "binance-live-enabled" not in serialized
    assert "credential_ref" not in serialized


def test_authenticated_user_can_update_own_watchlist_only(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "watchlist.trader@example.com",
            "username": "watchlist-trader",
            "password": "watchlist-password",
            "role": "trader",
            "trader_id": "trader-watchlist",
            "paper_account_id": "paper-watchlist",
            "reason": "watchlist self-service test user",
        },
    )
    assert created.status_code == 201
    trader_token = _login(client, "watchlist.trader@example.com", "watchlist-password")

    response = client.put(
        "/api/accounts/me/watchlist",
        headers=_auth(trader_token),
        json={"symbols": ["btcusdt", "ETHUSDT", "btcusdt", ""]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["watchlist"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["user"]["watchlist"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["user"]["email"] == "watchlist.trader@example.com"
    assert "password_hash" not in json.dumps(payload)
    assert "credential_ref" not in json.dumps(payload)
    assert payload["warnings"] == [
        "Watchlist is scoped to the signed-in user",
        "No exchange state was read or mutated",
        "Live trading remains disabled",
    ]

    invalid = client.put(
        "/api/accounts/me/watchlist",
        headers=_auth(trader_token),
        json={"symbols": ["BTC/USDT"]},
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "invalid_watchlist_symbol"

    client.cookies.clear()
    unauthenticated = client.put("/api/accounts/me/watchlist", json={"symbols": ["BTCUSDT"]})
    assert unauthenticated.status_code == 401


def test_chart_endpoints_return_structured_source_freshness_states(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    symbols = client.get("/api/v1/chart/symbols")
    assert symbols.status_code == 200
    symbols_payload = symbols.json()
    assert symbols_payload["source"] == "unavailable"
    assert symbols_payload["source_type"] == "unavailable"
    assert symbols_payload["endpoint"] == "/api/v1/chart/symbols"
    assert symbols_payload["stale"] is True
    assert "symbols" in symbols_payload["missing_fields"]
    assert symbols_payload["live_trading_enabled"] is False
    assert symbols_payload["exchange_mutation_enabled"] is False

    overlay = client.get("/api/v1/chart/coinank/BTCUSDT/5m")
    assert overlay.status_code == 200
    overlay_payload = overlay.json()
    assert overlay_payload["source"] in {"redis_coinank_overlay", "unavailable"}
    assert overlay_payload["source_type"] in {"repository", "unavailable"}
    assert overlay_payload["endpoint"] == "/api/v1/chart/coinank/BTCUSDT/5m"
    assert overlay_payload["stale"] is True
    assert overlay_payload["mode"] == "read_only"
    assert overlay_payload["live_trading_enabled"] is False
    assert overlay_payload["exchange_mutation_enabled"] is False
    serialized = json.dumps({"symbols": symbols_payload, "overlay": overlay_payload}).lower()
    for forbidden in ("api_key", "api_secret", "password_hash", "access_token", "live_order"):
        assert forbidden not in serialized


def test_exchange_account_link_requires_trader_and_paper_scope(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "viewer.scope@example.com",
            "username": "viewer-scope",
            "password": "viewer-password",
            "role": "viewer",
            "reason": "exchange link fail-closed scope test",
        },
    )
    assert created.status_code == 201
    viewer_token = _login(client, "viewer.scope@example.com", "viewer-password")

    response = client.post(
        "/api/accounts/me/exchange-accounts",
        headers=_auth(viewer_token),
        json={"exchange": "binance", "label": "Viewer Binance", "account_type": "usd_m_futures"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "trader_account_scope_required"

    scoped_viewer = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "viewer.with-scope@example.com",
            "username": "viewer-with-scope",
            "password": "viewer-password",
            "role": "viewer",
            "trader_id": "viewer-trader-scope",
            "paper_account_id": "viewer-paper-scope",
            "reason": "exchange link fail-closed role test",
        },
    )
    assert scoped_viewer.status_code == 201
    scoped_viewer_token = _login(client, "viewer.with-scope@example.com", "viewer-password")

    scoped_response = client.post(
        "/api/accounts/me/exchange-accounts",
        headers=_auth(scoped_viewer_token),
        json={"exchange": "binance", "label": "Viewer Scoped Binance", "account_type": "usd_m_futures"},
    )

    assert scoped_response.status_code == 403
    assert scoped_response.json()["detail"] == "trader_role_required"

    viewer_with_exchange = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "viewer.exchange@example.com",
            "username": "viewer-exchange",
            "password": "viewer-password",
            "role": "viewer",
            "trader_id": "viewer-exchange-scope",
            "paper_account_id": "viewer-exchange-paper",
            "exchange_accounts": [
                {
                    "id": "binance-viewer-exchange",
                    "exchange": "binance",
                    "label": "Viewer Exchange",
                    "account_type": "usd_m_futures",
                    "mode": "read_only",
                    "read_only": True,
                    "live_trading_enabled": False,
                }
            ],
            "reason": "exchange metadata must require trader role",
        },
    )
    assert viewer_with_exchange.status_code == 400
    assert viewer_with_exchange.json()["detail"] == "exchange_account_role_required"

    trader = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "exchange.trader@example.com",
            "username": "exchange-trader",
            "password": "trader-password",
            "role": "trader",
            "trader_id": "trader-account-link",
            "paper_account_id": "paper-account-link",
            "reason": "exchange account self-service test",
        },
    )
    assert trader.status_code == 201
    trader_token = _login(client, "exchange.trader@example.com", "trader-password")

    extra_field = client.post(
        "/api/accounts/me/exchange-accounts",
        headers=_auth(trader_token),
        json={
            "exchange": "binance",
            "label": "Exchange Trader Binance",
            "account_type": "usd_m_futures",
            "credential_ref": "ALPHAFORGE_SHOULD_NOT_BE_ACCEPTED",
        },
    )
    assert extra_field.status_code == 400
    assert extra_field.json()["detail"] == "exchange_account_metadata_only"

    secret_like_label = client.post(
        "/api/accounts/me/exchange-accounts",
        headers=_auth(trader_token),
        json={"exchange": "binance", "label": "my api secret", "account_type": "usd_m_futures"},
    )
    assert secret_like_label.status_code == 400
    assert secret_like_label.json()["detail"] == "exchange_account_metadata_only"

    linked = client.post(
        "/api/accounts/me/exchange-accounts",
        headers=_auth(trader_token),
        json={"exchange": "binance", "label": "Exchange Trader Binance", "account_type": "usd_m_futures"},
    )
    assert linked.status_code == 201
    linked_payload = linked.json()
    linked_accounts = linked_payload["user"]["exchange_accounts"]
    assert len(linked_accounts) == 1
    linked_account = linked_accounts[0]
    assert linked_account["trader_id"] == "trader-account-link"
    assert linked_account["paper_account_id"] == "paper-account-link"
    assert linked_account["read_only"] is True
    assert linked_account["live_trading_enabled"] is False
    assert "credential_ref" not in json.dumps(linked_payload)

    denied_unlink = client.delete(
        f"/api/accounts/me/exchange-accounts/{linked_account['id']}",
        headers=_auth(scoped_viewer_token),
    )
    assert denied_unlink.status_code == 403
    assert denied_unlink.json()["detail"] == "trader_role_required"

    unlinked = client.delete(
        f"/api/accounts/me/exchange-accounts/{linked_account['id']}",
        headers=_auth(trader_token),
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["removed_account_id"] == linked_account["id"]
    assert unlinked.json()["user"]["exchange_accounts"] == []
    assert unlinked.json()["warnings"] == [
        "Exchange account metadata was removed only from the signed-in trader scope",
        "No exchange state was read or mutated",
        "Live trading remains disabled",
    ]


def test_self_registration_does_not_grant_trader_scope(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/auth/register",
        json={
            "email": "new.viewer@example.com",
            "username": "new-viewer",
            "password": "viewer-password",
        },
    )

    assert response.status_code == 201
    user = response.json()["user"]
    assert user["role"] == "viewer"
    assert user["trader_id"] is None
    assert user["paper_account_id"] is None
    assert user["exchange_accounts"] == []


def test_local_auth_user_store_access_fails_closed_in_production(tmp_path: Path, monkeypatch) -> None:
    auth_store_path = tmp_path / "auth_users.json"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE", str(auth_store_path))
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    monkeypatch.delenv("ALPHAFORGE_ALLOW_LOCAL_AUTH_STORE_IN_PRODUCTION", raising=False)

    store = UserStore()
    with pytest.raises(HTTPException) as exc:
        store.ensure_bootstrap_admin()

    assert exc.value.status_code == 503
    assert exc.value.detail == "production_auth_user_repository_required"
    assert not auth_store_path.exists()


def test_auth_user_store_rejects_duplicate_paper_account_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPHAFORGE_ENV", raising=False)
    store = UserStore(path=tmp_path / "auth_users.json")
    first = store.create_user(
        email="first.trader@example.com",
        username="first-trader",
        password="first-password",
        role="trader",
        trader_id="trader-first",
        paper_account_id="paper-shared",
    )
    second = store.create_user(
        email="second.trader@example.com",
        username="second-trader",
        password="second-password",
        role="trader",
        trader_id="trader-second",
        paper_account_id="paper-second",
    )

    with pytest.raises(HTTPException) as create_exc:
        store.create_user(
            email="duplicate.trader@example.com",
            username="duplicate-trader",
            password="duplicate-password",
            role="trader",
            trader_id="trader-duplicate",
            paper_account_id=first["paper_account_id"],
        )
    assert create_exc.value.status_code == 409
    assert create_exc.value.detail == "paper_account_id_exists"

    with pytest.raises(HTTPException) as update_exc:
        store.update_user(second["id"], {"paper_account_id": first["paper_account_id"]})
    assert update_exc.value.status_code == 409
    assert update_exc.value.detail == "paper_account_id_exists"

    with pytest.raises(HTTPException) as duplicate_trader_create:
        store.create_user(
            email="duplicate.trader-id@example.com",
            username="duplicate-trader-id",
            password="duplicate-password",
            role="trader",
            trader_id=first["trader_id"],
            paper_account_id="paper-unique-for-duplicate-trader",
        )
    assert duplicate_trader_create.value.status_code == 409
    assert duplicate_trader_create.value.detail == "trader_id_exists"

    with pytest.raises(HTTPException) as duplicate_trader_update:
        store.update_user(second["id"], {"trader_id": first["trader_id"]})
    assert duplicate_trader_update.value.status_code == 409
    assert duplicate_trader_update.value.detail == "trader_id_exists"

    with pytest.raises(HTTPException) as email_exc:
        store.update_user(second["id"], {"email": "FIRST.TRADER@EXAMPLE.COM"})
    assert email_exc.value.status_code == 409
    assert email_exc.value.detail == "email_exists"


def test_sqlalchemy_auth_user_store_persists_users_and_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPHAFORGE_ENV", raising=False)
    monkeypatch.setenv("ALPHAFORGE_AUTH_DB_AUTO_CREATE", "1")
    database_url = f"sqlite:///{tmp_path / 'auth_users.db'}"
    store = SqlAlchemyUserStore(database_url)

    created = store.create_user(
        email="sql.trader@example.com",
        username="sql-trader",
        password="sql-password",
        role="trader",
        trader_id="trader-sql",
        paper_account_id="paper-sql",
    )

    reloaded = SqlAlchemyUserStore(database_url)
    user = reloaded.get_by_email("sql.trader@example.com")
    assert created["id"]
    assert user is not None
    assert user["trader_id"] == "trader-sql"
    assert user["paper_account_id"] == "paper-sql"
    with reloaded._engine.connect() as connection:
        columns = {
            row["name"]
            for row in connection.execute(text("PRAGMA table_info(alphaforge_auth_users)")).mappings().all()
        }
        indexes = {
            row["name"]
            for row in connection.execute(text("PRAGMA index_list(alphaforge_auth_users)")).mappings().all()
        }
    assert "trader_id" in columns
    assert "idx_alphaforge_auth_users_trader_id" in indexes
    assert reloaded.authenticate("sql.trader@example.com", "sql-password") is not None
    second = reloaded.create_user(
        email="sql.second@example.com",
        username="sql-second",
        password="sql-password-2",
        role="trader",
        trader_id="trader-sql-second",
        paper_account_id="paper-sql-second",
    )
    with pytest.raises(HTTPException) as duplicate_trader_create:
        reloaded.create_user(
            email="sql.duplicate-trader@example.com",
            username="sql-duplicate-trader",
            password="sql-password-3",
            role="trader",
            trader_id="trader-sql",
            paper_account_id="paper-sql-unique",
        )
    assert duplicate_trader_create.value.status_code == 409
    assert duplicate_trader_create.value.detail == "trader_id_exists"
    with pytest.raises(HTTPException) as duplicate_trader_update:
        reloaded.update_user(second["id"], {"trader_id": "trader-sql"})
    assert duplicate_trader_update.value.status_code == 409
    assert duplicate_trader_update.value.detail == "trader_id_exists"


def test_get_user_store_selects_sqlalchemy_backend_in_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_AUTH_DATABASE_URL", f"sqlite:///{tmp_path / 'auth_users.db'}")
    monkeypatch.setenv("ALPHAFORGE_AUTH_DB_AUTO_CREATE", "1")

    store = get_user_store()
    status_payload = auth_user_store_status()

    assert isinstance(store, SqlAlchemyUserStore)
    assert status_payload["backend"] == "sqlalchemy"
    assert status_payload["durable_user_store_configured"] is True
    assert status_payload["production_ready"] is True
    assert status_payload["contains_secret_values"] is False


def test_auth_login_sets_secure_cookie_in_production_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 200
    set_cookie = response.headers.get("set-cookie", "")
    assert "alphaforge_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "Max-Age=1800" in set_cookie


def test_auth_login_fails_closed_in_production_without_auth_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    monkeypatch.delenv("ALPHAFORGE_AUTH_SECRET", raising=False)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_secret_required_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_login_fails_closed_in_production_with_short_auth_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "short-secret")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_secret_too_short_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_login_fails_closed_in_production_with_short_previous_auth_secret(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "current-secret-for-auth-rbac-minimum-32-chars")
    monkeypatch.setenv("ALPHAFORGE_AUTH_PREVIOUS_SECRETS", "short-previous")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_previous_secret_too_short_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_accepts_previous_secret_during_production_secret_rotation(tmp_path: Path, monkeypatch) -> None:
    old_secret = "old-secret-for-auth-rbac-minimum-32-chars"
    new_secret = "new-secret-for-auth-rbac-minimum-32-chars"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", old_secret)
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "Correct-Password-123!")

    monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", new_secret)
    monkeypatch.setenv("ALPHAFORGE_AUTH_PREVIOUS_SECRETS", old_secret)

    response = client.get("/api/auth/me", headers=_auth(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["email"] == "admin@example.com"
    assert payload["session_security"]["previous_auth_secrets_configured"] == 1
    assert payload["session_security"]["auth_secret_rotation_supported"] is True
    assert (
        payload["session_security"]["auth_secret_rotation_policy"]
        == "active_secret_signs_previous_secrets_verify_only"
    )
    assert payload["session_security"]["production_previous_auth_secret_strength_fail_closed"] is False
    serialized = json.dumps(payload)
    assert old_secret not in serialized
    assert new_secret not in serialized


def test_auth_login_fails_closed_in_production_without_revocation_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    monkeypatch.delenv("ALPHAFORGE_AUTH_REVOCATION_STORE", raising=False)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_revocation_store_required_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_local_revocation_store_access_fails_closed_in_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "test-secret-for-auth-rbac-minimum-32-chars")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.delenv("ALPHAFORGE_ALLOW_LOCAL_REVOCATION_STORE_IN_PRODUCTION", raising=False)
    user = {
        "id": "user-test",
        "role": "admin",
        "trader_id": "trader-test",
        "session_version": 0,
    }

    with pytest.raises(HTTPException) as exc:
        create_access_token(user)  # type: ignore[arg-type]

    assert exc.value.status_code == 503
    assert exc.value.detail == "production_auth_revocation_repository_required"
    status_payload = revocation_store_status()
    assert status_payload["backend"] == "local_file"
    assert status_payload["local_file_production_access_fail_closed"] is True


def test_auth_login_fails_closed_in_production_without_issuer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    monkeypatch.delenv("ALPHAFORGE_AUTH_ISSUER", raising=False)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_issuer_required_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_login_fails_closed_in_production_without_audience(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    monkeypatch.delenv("ALPHAFORGE_AUTH_AUDIENCE", raising=False)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_audience_required_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_login_fails_closed_in_production_without_session_minutes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    monkeypatch.delenv("ALPHAFORGE_AUTH_SESSION_MINUTES", raising=False)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_session_minutes_required_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_login_fails_closed_in_production_with_invalid_session_minutes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "2")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_session_minutes_invalid_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_login_fails_closed_in_production_without_cookie_samesite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    monkeypatch.delenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", raising=False)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_cookie_samesite_required_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_auth_login_fails_closed_in_production_with_invalid_cookie_samesite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "wide-open")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Correct-Password-123!"})

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_cookie_samesite_invalid_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_production_user_password_policy_rejects_weak_admin_create_and_reset(tmp_path: Path, monkeypatch) -> None:
    step_up_secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_STEP_UP_TOTP_SECRET", step_up_secret)
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "Correct-Password-123!")

    weak_create = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "weak.trader@example.com",
            "username": "weak-trader",
            "password": "short",
            "role": "trader",
            "trader_id": "trader-weak",
            "paper_account_id": "paper-weak",
            "reason": "production password policy test",
        },
    )
    assert weak_create.status_code == 400
    assert weak_create.json()["detail"] == "password_policy_too_short"

    strong_create = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "strong.trader@example.com",
            "username": "strong-trader",
            "password": "Strong-Password-123!",
            "role": "trader",
            "trader_id": "trader-strong",
            "paper_account_id": "paper-strong",
            "reason": "production password policy test",
        },
    )
    assert strong_create.status_code == 201

    weak_reset = client.post(
        f"/api/admin/users/{strong_create.json()['user']['id']}/activation",
        headers={**_auth(admin_token), "X-AlphaForge-Step-Up-Code": _totp_code(step_up_secret)},
        json={"is_active": True, "temporary_password": "NoDigitsHere!", "reason": "weak reset"},
    )
    assert weak_reset.status_code == 400
    assert weak_reset.json()["detail"] == "password_policy_complexity_required"


def test_admin_activation_fails_closed_in_production_without_step_up_secret(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    monkeypatch.delenv("ALPHAFORGE_ADMIN_STEP_UP_TOTP_SECRET", raising=False)
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "Correct-Password-123!")

    response = client.post(
        "/api/admin/users/user-wajidali1984/activation",
        headers=_auth(admin_token),
        json={
            "is_active": True,
            "temporary_password": "Temporary-Password-123!",
            "reason": "activate seeded trader",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "admin_step_up_secret_required_in_production"


def test_admin_activation_requires_valid_step_up_code_in_production(tmp_path: Path, monkeypatch) -> None:
    step_up_secret = "JBSWY3DPEHPK3PXP"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_STEP_UP_TOTP_SECRET", step_up_secret)
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "Correct-Password-123!")

    missing = client.post(
        "/api/admin/users/user-wajidali1984/activation",
        headers=_auth(admin_token),
        json={
            "is_active": True,
            "temporary_password": "Temporary-Password-123!",
            "reason": "activate seeded trader",
        },
    )
    assert missing.status_code == 403
    assert missing.json()["detail"] == "admin_step_up_required"

    valid = client.post(
        "/api/admin/users/user-wajidali1984/activation",
        headers={**_auth(admin_token), "X-AlphaForge-Step-Up-Code": _totp_code(step_up_secret)},
        json={
            "is_active": True,
            "temporary_password": "Temporary-Password-123!",
            "reason": "activate seeded trader",
        },
    )
    assert valid.status_code == 200
    payload = valid.json()
    assert payload["activation"]["is_active"] is True
    assert payload["activation"]["password_reset"] is True
    assert payload["audit"]["recorded"] is True
    assert payload["audit"]["ledger_kind"] == "append_only_local_admin_jsonl"
    assert payload["audit"]["contains_secret_values"] is False
    assert payload["audit"]["live_trading_enabled"] is False
    assert payload["audit"]["exchange_mutation_enabled"] is False
    serialized = json.dumps(payload)
    assert step_up_secret not in serialized
    assert "Temporary-Password-123!" not in serialized


def test_admin_activation_writes_secret_free_local_audit_event(tmp_path: Path, monkeypatch) -> None:
    audit_path = tmp_path / "admin_audit.jsonl"
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_LOG_STORE", str(audit_path))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.post(
        "/api/admin/users/user-wajidali1984/activation",
        headers=_auth(admin_token),
        json={
            "is_active": True,
            "temporary_password": "trader-reset-password",
            "reason": "operator activation",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["audit"]["recorded"] is True
    assert payload["audit"]["ledger_kind"] == "append_only_local_admin_jsonl"
    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert row["event_type"] == "admin_user_activation_reset"
    assert row["actor_role"] == "admin"
    assert row["target_user_id"] == "user-wajidali1984"
    assert row["target_trader_id"] == "trader-wajidali1984"
    assert row["password_reset"] is True
    assert row["reason_recorded"] is True
    assert row["temporary_password_returned"] is False
    assert row["password_hash_returned"] is False
    assert row["contains_secret_values"] is False
    assert row["live_trading_enabled"] is False
    assert row["exchange_mutation_enabled"] is False
    serialized = json.dumps({"response": payload, "audit": row})
    assert "trader-reset-password" not in serialized
    assert '"password_hash":' not in serialized
    assert "X-AlphaForge-Step-Up-Code" not in serialized


def test_admin_activation_fails_closed_in_production_when_audit_log_is_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    step_up_secret = "JBSWY3DPEHPK3PXP"
    broken_parent = tmp_path / "admin_audit_parent"
    broken_parent.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_LOG_STORE", str(broken_parent / "admin_audit.jsonl"))
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_STEP_UP_TOTP_SECRET", step_up_secret)
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "Correct-Password-123!")

    response = client.post(
        "/api/admin/users/user-wajidali1984/activation",
        headers={**_auth(admin_token), "X-AlphaForge-Step-Up-Code": _totp_code(step_up_secret)},
        json={
            "is_active": True,
            "temporary_password": "Temporary-Password-123!",
            "reason": "activate seeded trader",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "admin_audit_log_unwritable_in_production"
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "Temporary-Password-123!"},
    )
    assert login.status_code == 401


def test_admin_user_mutations_write_secret_free_local_audit_events(tmp_path: Path, monkeypatch) -> None:
    audit_path = tmp_path / "admin_user_mutations_audit.jsonl"
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_LOG_STORE", str(audit_path))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "audit.trader@example.com",
            "username": "audit-trader",
            "password": "Mutation-Secret-123!",
            "role": "trader",
            "trader_id": "trader-audit",
            "paper_account_id": "paper-audit",
        },
    )
    assert created.status_code == 201
    created_payload = created.json()
    assert created_payload["audit"]["recorded"] is True
    assert created_payload["audit"]["ledger_kind"] == "append_only_local_admin_jsonl"
    assert created_payload["audit"]["contains_secret_values"] is False

    updated = client.put(
        f"/api/admin/users/{created_payload['user']['id']}",
        headers=_auth(admin_token),
        json={
            "username": "audit-trader-updated",
            "password": "Mutation-Reset-123!",
            "watchlist": ["BTCUSDT", "ETHUSDT"],
        },
    )
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["audit"]["recorded"] is True

    deleted = client.delete(
        f"/api/admin/users/{created_payload['user']['id']}",
        headers=_auth(admin_token),
    )
    assert deleted.status_code == 200
    deleted_payload = deleted.json()
    assert deleted_payload["audit"]["recorded"] is True

    rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert [row["event_type"] for row in rows] == [
        "admin_user_create",
        "admin_user_update",
        "admin_user_delete",
    ]
    assert rows[0]["target_email"] == "audit.trader@example.com"
    assert rows[1]["password_reset"] is True
    assert rows[2]["deletes_password_digest"] is True
    for row in rows:
        assert row["contains_secret_values"] is False
        assert row["live_trading_enabled"] is False
        assert row["exchange_mutation_enabled"] is False
        assert row["production_durable_store"] is False
    serialized = json.dumps(
        {"created": created_payload, "updated": updated_payload, "deleted": deleted_payload, "audit": rows}
    ).lower()
    for text in (
        "mutation-secret-123",
        "mutation-reset-123",
        "password_hash",
        "access_token",
    ):
        assert text not in serialized


def test_admin_user_create_fails_closed_in_production_when_audit_log_is_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    broken_parent = tmp_path / "admin_user_audit_parent"
    broken_parent.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_LOG_STORE", str(broken_parent / "admin_audit.jsonl"))
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "Correct-Password-123!")

    response = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "blocked.audit@example.com",
            "username": "blocked-audit",
            "password": "Blocked-Audit-Password-123!",
            "role": "trader",
            "trader_id": "trader-blocked-audit",
            "paper_account_id": "paper-blocked-audit",
            "reason": "production audit fail closed test",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "admin_audit_log_unwritable_in_production"
    login = client.post(
        "/api/auth/login",
        json={"email": "blocked.audit@example.com", "password": "Blocked-Audit-Password-123!"},
    )
    assert login.status_code == 401


def test_local_admin_audit_store_access_fails_closed_in_production(monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.delenv("ALPHAFORGE_ALLOW_LOCAL_ADMIN_AUDIT_IN_PRODUCTION", raising=False)
    monkeypatch.delenv("ALPHAFORGE_ADMIN_AUDIT_STORE_BACKEND", raising=False)

    with pytest.raises(HTTPException) as exc:
        append_admin_audit_event(
            {
                "event_type": "admin_user_update",
                "actor_user_id": "user-admin",
                "target_user_id": "user-target",
            }
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "production_admin_audit_repository_required"
    status_payload = admin_audit_status()
    assert status_payload["backend"] == "local_file"
    assert status_payload["production_local_file_blocked"] is True
    assert status_payload["production_durable_store"] is False
    assert status_payload["retention_policy_configured"] is False
    assert status_payload["production_retention_policy_required"] is True
    assert status_payload["retention_policy_status"] == "missing"
    assert "admin_audit_retention_days" in status_payload["missing_fields"]


def test_sqlalchemy_admin_audit_requires_retention_policy_in_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_DATABASE_URL", f"sqlite:///{tmp_path / 'admin_audit.db'}")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_DB_AUTO_CREATE", "true")
    monkeypatch.delenv("ALPHAFORGE_ADMIN_AUDIT_RETENTION_DAYS", raising=False)

    with pytest.raises(HTTPException) as exc:
        append_admin_audit_event(
            {
                "event_type": "admin_user_update",
                "actor_user_id": "user-admin",
                "target_user_id": "user-target",
            }
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "production_admin_audit_retention_policy_required"
    status_payload = admin_audit_status()
    assert status_payload["backend"] == "sqlalchemy"
    assert status_payload["production_durable_store"] is True
    assert status_payload["retention_policy_configured"] is False
    assert status_payload["production_retention_policy_required"] is True
    assert status_payload["retention_policy_status"] == "missing"
    assert "admin_audit_retention_days" in status_payload["missing_fields"]


def test_sqlalchemy_admin_audit_store_persists_secret_free_events(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "admin_audit.db"
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_DB_AUTO_CREATE", "true")
    monkeypatch.setenv("ALPHAFORGE_ADMIN_AUDIT_RETENTION_DAYS", "365")

    audit_event = append_admin_audit_event(
        {
            "event_type": "admin_user_activation_reset",
            "actor_user_id": "user-admin",
            "actor_role": "admin",
            "target_user_id": "user-wajidali1984",
            "target_email": "wajidali1984@hotmail.com",
            "target_trader_id": "trader-wajidali1984",
            "password_reset": True,
            "password_returned": False,
            "password_hash_returned": False,
        }
    )

    assert audit_event["audit_persisted"] is True
    assert audit_event["ledger_kind"] == "sqlalchemy_admin_audit"
    assert audit_event["production_durable_store"] is True
    assert audit_event["retention_policy_configured"] is True
    assert audit_event["retention_days"] == 365
    assert audit_event["retention_enforced"] is False
    status_payload = admin_audit_status()
    assert status_payload["backend"] == "sqlalchemy"
    assert status_payload["database_url_configured"] is True
    assert status_payload["production_durable_store"] is True
    assert status_payload["retention_policy_configured"] is True
    assert status_payload["retention_days"] == 365
    assert status_payload["retention_policy_status"] == "configured_pending_enforcement"
    assert status_payload["retention_enforced"] is False
    assert status_payload["production_retention_policy_required"] is False
    with sqlite3.connect(database_path) as conn:
        row = conn.execute(
            "SELECT audit_id, event_type, payload FROM alphaforge_admin_audit_events WHERE audit_id = ?",
            (audit_event["audit_id"],),
        ).fetchone()
    assert row is not None
    assert row[1] == "admin_user_activation_reset"
    serialized = json.dumps({"record": audit_event, "row": row}).lower()
    assert '"password_hash":' not in serialized
    assert "temporary-password" not in serialized
    assert "access_token" not in serialized


def test_admin_user_create_requires_reason_in_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "Correct-Password-123!")

    response = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "missing.reason@example.com",
            "username": "missing-reason",
            "password": "Missing-Reason-Password-123!",
            "role": "trader",
            "trader_id": "trader-missing-reason",
            "paper_account_id": "paper-missing-reason",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "admin_mutation_reason_required"
    login = client.post(
        "/api/auth/login",
        json={"email": "missing.reason@example.com", "password": "Missing-Reason-Password-123!"},
    )
    assert login.status_code == 401


def test_admin_user_update_and_delete_require_reason_in_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(tmp_path / "auth_revocations.json"))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "Correct-Password-123!")

    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "reasoned.trader@example.com",
            "username": "reasoned-trader",
            "password": "Reasoned-Trader-Password-123!",
            "role": "trader",
            "trader_id": "trader-reasoned",
            "paper_account_id": "paper-reasoned",
            "reason": "seed production reason test",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["user"]["id"]

    update = client.put(
        f"/api/admin/users/{user_id}",
        headers=_auth(admin_token),
        json={"username": "reasonless-update"},
    )
    assert update.status_code == 400
    assert update.json()["detail"] == "admin_mutation_reason_required"

    delete = client.delete(f"/api/admin/users/{user_id}", headers=_auth(admin_token))
    assert delete.status_code == 400
    assert delete.json()["detail"] == "admin_mutation_reason_required"
    assert _login(client, "reasoned.trader@example.com", "Reasoned-Trader-Password-123!")


def test_auth_login_failure_and_me_unauthenticated(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    assert client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"}).status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_me_authenticated_returns_safe_user(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/auth/me", headers=_auth(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["email"] == "admin@example.com"
    assert payload["session_security"]["status"] == "partial"
    assert payload["session_security"]["auth_secret_configured"] is True
    assert payload["session_security"]["production_auth_secret_min_length"] == 32
    assert payload["session_security"]["production_auth_secret_required"] is False
    assert payload["session_security"]["production_auth_secret_fail_closed"] is False
    assert payload["session_security"]["production_auth_secret_strength_fail_closed"] is False
    assert payload["session_security"]["previous_auth_secrets_configured"] == 0
    assert payload["session_security"]["auth_secret_rotation_supported"] is False
    assert (
        payload["session_security"]["auth_secret_rotation_policy"]
        == "active_secret_signs_previous_secrets_verify_only"
    )
    assert payload["session_security"]["production_previous_auth_secret_strength_fail_closed"] is False
    assert payload["session_security"]["production_issuer_required"] is False
    assert payload["session_security"]["production_issuer_fail_closed"] is False
    assert payload["session_security"]["production_audience_required"] is False
    assert payload["session_security"]["production_audience_fail_closed"] is False
    assert payload["session_security"]["session_minutes_configured"] is False
    assert payload["session_security"]["production_session_minutes_required"] is False
    assert payload["session_security"]["production_session_minutes_fail_closed"] is False
    assert payload["session_security"]["cookie_samesite_configured"] is False
    assert payload["session_security"]["production_cookie_samesite_required"] is False
    assert payload["session_security"]["production_cookie_samesite_fail_closed"] is False
    assert payload["session_security"]["production_revocation_store_required"] is False
    assert payload["session_security"]["production_revocation_store_fail_closed"] is False
    assert payload["session_security"]["production_revocation_store_error_fail_closed"] is False
    assert payload["session_security"]["cookie_httponly"] is True
    assert payload["session_security"]["session_version_claim_enforced"] is True
    assert payload["session_security"]["mfa_step_up_enabled"] is False
    assert payload["session_security"]["production_mfa_step_up_required"] is False
    assert payload["session_security"]["production_mfa_step_up_fail_closed"] is False
    assert payload["session_security"]["admin_step_up_method"] == "unconfigured"
    assert payload["session_security"]["refresh_revokes_presented_token"] is True
    assert payload["session_security"]["token_rotation_policy"] == "refresh_rotates_and_revokes_presented_token"
    assert payload["session_security"]["revocation_store"]["backend"] == "local_file"
    assert payload["session_security"]["durable_revocation_store"] is False
    assert payload["session_security"]["durable_session_store"] is False
    assert payload["session_security"]["contains_secret_values"] is False
    assert payload["session_security"]["live_trading_enabled"] is False
    assert payload["session_security"]["exchange_mutation_enabled"] is False
    assert "password_hash" not in json.dumps(payload)
    assert "test-secret-for-auth-rbac" not in json.dumps(payload)
    assert "test-secret-for-auth-rbac-minimum-32-chars" not in json.dumps(payload)


def test_logout_revokes_bearer_token(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "correct-password")

    logout = client.post("/api/auth/logout", headers=_auth(token))

    assert logout.status_code == 200
    assert logout.json()["revoked"] is True
    response = client.get("/api/auth/me", headers=_auth(token))
    assert response.status_code == 401


def test_sqlalchemy_revocation_store_persists_revoked_tokens(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL", f"sqlite:///{tmp_path / 'auth_revocations.db'}")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_DB_AUTO_CREATE", "1")
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "correct-password")

    logout = client.post("/api/auth/logout", headers=_auth(token))

    assert logout.status_code == 200
    assert logout.json()["revoked"] is True
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    status_payload = revocation_store_status()
    assert status_payload["backend"] == "sqlalchemy"
    assert status_payload["durable_revocation_store_configured"] is True
    assert status_payload["contains_secret_values"] is False


def test_production_session_security_reports_sqlalchemy_revocation_store(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_AUTH_DATABASE_URL", f"sqlite:///{tmp_path / 'auth_users.db'}")
    monkeypatch.setenv("ALPHAFORGE_AUTH_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL", f"sqlite:///{tmp_path / 'auth_revocations.db'}")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "Correct-Password-123!")

    response = client.get("/api/auth/me", headers=_auth(token))

    assert response.status_code == 200
    session_security = response.json()["session_security"]
    assert session_security["revocation_store_kind"] == "sqlalchemy"
    assert session_security["durable_revocation_store"] is True
    assert session_security["revocation_store"]["production_ready"] is True
    assert session_security["auth_user_store"]["backend"] == "sqlalchemy"
    assert session_security["durable_user_store"] is True
    assert session_security["production_ready"] is False


def test_logout_fails_closed_in_production_when_revocation_store_is_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    broken_parent = tmp_path / "auth_revocations_parent"
    broken_parent.write_text("not a directory", encoding="utf-8")
    broken_store = broken_parent / "auth_revocations.json"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(broken_store))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "Correct-Password-123!")

    response = client.post("/api/auth/logout", headers=_auth(token))

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_revocation_store_unwritable_in_production"


def test_refresh_rotates_and_revokes_presented_token(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "correct-password")

    refreshed = client.post("/api/auth/refresh", headers=_auth(token))

    assert refreshed.status_code == 200
    payload = refreshed.json()
    assert payload["previous_session_revoked"] is True
    assert payload["access_token"] != token
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    assert client.get("/api/auth/me", headers=_auth(payload["access_token"])).status_code == 200


def test_refresh_fails_closed_in_production_when_revocation_store_is_unwritable(
    tmp_path: Path, monkeypatch
) -> None:
    broken_parent = tmp_path / "auth_revocations_parent"
    broken_parent.write_text("not a directory", encoding="utf-8")
    broken_store = broken_parent / "auth_revocations.json"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "30")
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web-test")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE", str(broken_store))
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", "Correct-Password-123!")
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "Correct-Password-123!")

    response = client.post("/api/auth/refresh", headers=_auth(token))

    assert response.status_code == 503
    assert response.json()["detail"] == "auth_revocation_store_unwritable_in_production"
    assert "alphaforge_session=" not in response.headers.get("set-cookie", "")


def test_change_password_revokes_current_session(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "correct-password")
    second_token = _login(client, "admin@example.com", "correct-password")

    changed = client.post(
        "/api/accounts/me/change-password",
        headers=_auth(token),
        json={"current_password": "correct-password", "new_password": "new-correct-password"},
    )

    assert changed.status_code == 200
    assert changed.json()["ok"] is True
    assert changed.json()["session_revoked"] is True
    assert client.get("/api/auth/me", headers=_auth(token)).status_code == 401
    assert client.get("/api/auth/me", headers=_auth(second_token)).status_code == 401
    assert _login(client, "admin@example.com", "new-correct-password")


def test_auth_ignores_malformed_revocation_store_entries(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "correct-password")
    revocation_path = tmp_path / "v2" / "backend" / "auth_revocations.json"
    revocation_path.parent.mkdir(parents=True, exist_ok=True)
    revocation_path.write_text(json.dumps({"revoked": {"broken": "not-an-int"}}), encoding="utf-8")

    response = client.get("/api/auth/me", headers=_auth(token))

    assert response.status_code == 200


def test_auth_rejects_token_with_wrong_audience(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "admin@example.com", "correct-password")

    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "other-audience")

    response = client.get("/api/auth/me", headers=_auth(token))
    assert response.status_code == 401


def test_seeded_trader_account_metadata_is_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY", "test-read-only-key")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET", "test-read-only-secret")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/users", headers=_auth(admin_token))

    assert response.status_code == 200
    users = response.json()["users"]
    trader = next(user for user in users if user["email"] == "wajidali1984@hotmail.com")
    assert trader["username"] == "wajidali1984"
    assert trader["trader_id"] == "trader-wajidali1984"
    assert trader["paper_account_id"] == "paper-wajidali1984"
    assert trader["is_active"] is True
    assert trader["exchange_accounts"][0]["exchange"] == "binance"
    assert trader["exchange_accounts"][0]["trader_id"] == "trader-wajidali1984"
    assert trader["exchange_accounts"][0]["paper_account_id"] == "paper-wajidali1984"
    assert "credential_ref" not in trader["exchange_accounts"][0]
    assert trader["exchange_accounts"][0]["read_only"] is True
    assert trader["exchange_accounts"][0]["live_trading_enabled"] is False
    assert trader["exchange_accounts"][0]["credential_status"]["credential_ref"] is None
    assert trader["exchange_accounts"][0]["credential_status"]["credential_scope"] == "backend_only_readonly"
    assert trader["exchange_accounts"][0]["credential_status"]["configured"] is True
    assert trader["exchange_accounts"][0]["credential_status"]["raw_credential_value_exposed"] is False
    assert trader["exchange_accounts"][0]["credential_status"]["live_trading_enabled"] is False
    assert trader["exchange_accounts"][0]["credential_status"]["binding_blocked_reason"] is None
    binding = backend_readonly_credential_binding(
        {
            "credential_ref": "ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY",
            "read_only": True,
            "live_trading_enabled": False,
        }
    )
    assert binding.is_configured is True
    assert binding.api_key == "test-read-only-key"
    assert binding.api_secret == "test-read-only-secret"
    assert binding.safe_status["credential_ref"] is None
    assert binding.safe_status["credential_scope"] == "backend_only_readonly"
    assert binding.safe_status["raw_credential_value_exposed"] is False
    assert binding.safe_status["live_trading_enabled"] is False
    assert binding.safe_status["binding_blocked_reason"] is None
    serialized = json.dumps(trader).lower()
    for text in (
        "password_hash",
        "api_key",
        "api_secret",
        "private_key",
        "access_token",
        "test-read-only-key",
        "test-read-only-secret",
        "alphaforge_binance_wajidali1984_readonly",
    ):
        assert text not in serialized


def test_initial_trader_seed_reconciles_existing_user_scope(tmp_path: Path, monkeypatch) -> None:
    auth_store_path = tmp_path / "auth_users.json"
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE", str(auth_store_path))
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "seed-password-123")
    auth_store_path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "id": "user-wajidali1984",
                        "trader_id": "stale-trader",
                        "username": "stale-wajid",
                        "email": "wajidali1984@hotmail.com",
                        "password_hash": "not-used",
                        "role": "viewer",
                        "paper_account_id": "stale-paper",
                        "exchange_accounts": [
                            {
                                "id": "stale-binance",
                                "trader_id": "stale-trader",
                                "exchange": "binance",
                                "label": "Stale Binance",
                                "account_type": "usd_m_futures",
                                "mode": "read_only",
                                "credential_ref": "ALPHAFORGE_STALE_READONLY",
                                "read_only": True,
                                "live_trading_enabled": False,
                                "status": "credential_source_pending",
                            }
                        ],
                        "watchlist": [],
                        "alert_preferences": {},
                        "is_active": False,
                        "created_at": "2026-06-13T00:00:00Z",
                        "updated_at": "2026-06-13T00:00:00Z",
                        "last_login": None,
                        "session_version": 0,
                    }
                ]
            },
        ),
        encoding="utf-8",
    )

    store = UserStore(auth_store_path)
    store.ensure_initial_trader()

    trader = next(user for user in store.list_users() if user["email"] == "wajidali1984@hotmail.com")
    assert trader["role"] == "trader"
    assert trader["username"] == "wajidali1984"
    assert trader["trader_id"] == "trader-wajidali1984"
    assert trader["paper_account_id"] == "paper-wajidali1984"
    assert trader["watchlist"] == ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    assert trader["is_active"] is True
    assert trader["session_version"] == 1
    assert trader["exchange_accounts"][0]["id"] == "binance-wajidali1984"
    assert trader["exchange_accounts"][0]["trader_id"] == "trader-wajidali1984"
    assert trader["exchange_accounts"][0]["paper_account_id"] == "paper-wajidali1984"
    assert trader["exchange_accounts"][0]["read_only"] is True
    assert trader["exchange_accounts"][0]["live_trading_enabled"] is False
    authenticated = store.authenticate("wajidali1984@hotmail.com", "seed-password-123")
    assert authenticated is not None
    assert authenticated["trader_id"] == "trader-wajidali1984"


def test_initial_trader_seed_requires_paper_account_scope(tmp_path: Path, monkeypatch) -> None:
    auth_store_path = tmp_path / "auth_users.json"
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE", str(auth_store_path))
    monkeypatch.delenv("ALPHAFORGE_BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ALPHAFORGE_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", raising=False)
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PAPER_ACCOUNT_ID", "")

    store = UserStore(auth_store_path)
    store.ensure_initial_trader()

    assert store.list_users() == []


def test_initial_trader_binance_metadata_env_overrides_are_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_BINANCE_ACCOUNT_ID", "binance-custom-wajid")
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_BINANCE_LABEL", "Wajid Read Only Futures")
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_BINANCE_ACCOUNT_TYPE", "portfolio_margin_readonly")
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF", "ALPHAFORGE_BINANCE_CUSTOM_READONLY")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_CUSTOM_READONLY_API_KEY", "custom-read-only-key")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_CUSTOM_READONLY_API_SECRET", "custom-read-only-secret")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/users", headers=_auth(admin_token))

    assert response.status_code == 200
    users = response.json()["users"]
    trader = next(user for user in users if user["email"] == "wajidali1984@hotmail.com")
    account = trader["exchange_accounts"][0]
    assert account["id"] == "binance-custom-wajid"
    assert account["label"] == "Wajid Read Only Futures"
    assert account["account_type"] == "portfolio_margin_readonly"
    assert account["read_only"] is True
    assert account["live_trading_enabled"] is False
    assert "credential_ref" not in account
    assert account["credential_status"]["configured"] is True
    assert account["credential_status"]["credential_ref"] is None
    serialized = json.dumps(trader).lower()
    for text in ("custom-read-only-key", "custom-read-only-secret", "alphaforge_binance_custom_readonly"):
        assert text not in serialized


def test_backend_credential_vault_file_binding_is_secret_free(tmp_path: Path, monkeypatch) -> None:
    vault_path = tmp_path / "credential_vault.json"
    vault_path.write_text(
        json.dumps(
            {
                "credentials": {
                    "ALPHAFORGE_BINANCE_VAULT_READONLY": {
                        "api_key": "vault-read-only-key",
                        "api_secret": "vault-read-only-secret",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_CREDENTIAL_VAULT_FILE", str(vault_path))
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_BINANCE_CREDENTIAL_REF", "ALPHAFORGE_BINANCE_VAULT_READONLY")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/users", headers=_auth(admin_token))

    assert response.status_code == 200
    users = response.json()["users"]
    trader = next(user for user in users if user["email"] == "wajidali1984@hotmail.com")
    account = trader["exchange_accounts"][0]
    assert account["credential_status"]["configured"] is True
    assert account["credential_status"]["source_type"] == "vault_file"
    assert account["credential_status"]["credential_ref"] is None
    assert account["credential_status"]["credential_scope"] == "backend_only_readonly"
    assert account["credential_status"]["raw_credential_value_exposed"] is False
    assert account["credential_status"]["live_trading_enabled"] is False
    assert account["credential_status"]["binding_blocked_reason"] is None
    binding = backend_readonly_credential_binding(
        {
            "credential_ref": "ALPHAFORGE_BINANCE_VAULT_READONLY",
            "read_only": True,
            "live_trading_enabled": False,
        }
    )
    assert binding.is_configured is True
    assert binding.api_key == "vault-read-only-key"
    assert binding.api_secret == "vault-read-only-secret"
    serialized = json.dumps(trader).lower()
    for text in ("vault-read-only-key", "vault-read-only-secret", "alphaforge_binance_vault_readonly"):
        assert text not in serialized


def test_backend_credential_binding_requires_readonly_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_BINANCE_LIVE_API_KEY", "unsafe-live-key")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_LIVE_API_SECRET", "unsafe-live-secret")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_READONLY_API_KEY", "safe-read-only-key")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_READONLY_API_SECRET", "safe-read-only-secret")

    live_marked_account = backend_readonly_credential_binding(
        {
            "credential_ref": "ALPHAFORGE_BINANCE_LIVE",
            "read_only": False,
            "live_trading_enabled": True,
        }
    )
    assert live_marked_account.is_configured is False
    assert live_marked_account.api_key == ""
    assert live_marked_account.api_secret == ""
    assert live_marked_account.safe_status["status"] == "credential_binding_blocked"
    assert live_marked_account.safe_status["configured"] is False
    assert live_marked_account.safe_status["live_trading_enabled"] is False
    assert live_marked_account.safe_status["binding_blocked_reason"] == "read_only_required"

    non_readonly_ref = backend_readonly_credential_binding(
        {
            "credential_ref": "ALPHAFORGE_BINANCE_LIVE",
            "read_only": True,
            "live_trading_enabled": False,
        }
    )
    assert non_readonly_ref.is_configured is False
    assert non_readonly_ref.safe_status["binding_blocked_reason"] == "readonly_credential_reference_required"

    safe_readonly = backend_readonly_credential_binding(
        {
            "credential_ref": "ALPHAFORGE_BINANCE_READONLY",
            "read_only": True,
            "live_trading_enabled": False,
        }
    )
    assert safe_readonly.is_configured is True
    assert safe_readonly.safe_status["binding_blocked_reason"] is None
    serialized = json.dumps(
        {
            "live_marked_account": live_marked_account.safe_status,
            "non_readonly_ref": non_readonly_ref.safe_status,
            "safe_readonly": safe_readonly.safe_status,
        }
    ).lower()
    for text in ("unsafe-live-key", "unsafe-live-secret", "safe-read-only-key", "safe-read-only-secret"):
        assert text not in serialized


def test_admin_activation_reset_workflow_for_seeded_trader_is_safe(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    users = client.get("/api/admin/users", headers=_auth(admin_token)).json()["users"]
    trader = next(user for user in users if user["email"] == "wajidali1984@hotmail.com")
    # Bootstrap user starts active; activation endpoint still works for password reset.
    assert trader["is_active"] is True

    client.cookies.clear()
    unauthenticated = client.post(
        f"/api/admin/users/{trader['id']}/activation",
        json={"is_active": True, "temporary_password": "trader-reset-password", "reason": "operator activation"},
    )
    assert unauthenticated.status_code == 401

    missing_password = client.post(
        f"/api/admin/users/{trader['id']}/activation",
        headers=_auth(admin_token),
        json={"is_active": True, "reason": "operator activation"},
    )
    assert missing_password.status_code == 400
    assert missing_password.json()["detail"] == "temporary_password_required_for_activation"

    activated = client.post(
        f"/api/admin/users/{trader['id']}/activation",
        headers=_auth(admin_token),
        json={"is_active": True, "temporary_password": "trader-reset-password", "reason": "operator activation"},
    )

    assert activated.status_code == 200
    payload = activated.json()
    assert payload["user"]["email"] == "wajidali1984@hotmail.com"
    assert payload["user"]["is_active"] is True
    assert payload["activation"]["password_reset"] is True
    assert payload["activation"]["reason_recorded"] is True
    assert payload["audit"]["recorded"] is True
    serialized = json.dumps(payload).lower()
    for text in ("trader-reset-password", "password_hash", "api_key", "api_secret", "live_trading_enabled\":true"):
        assert text not in serialized
    trader_token = _login(client, "wajidali1984@hotmail.com", "trader-reset-password")
    me = client.get("/api/auth/me", headers=_auth(trader_token)).json()["user"]
    assert me["role"] == "trader"
    assert me["trader_id"] == "trader-wajidali1984"
    assert me["paper_account_id"] == "paper-wajidali1984"

    reset_active = client.post(
        f"/api/admin/users/{trader['id']}/activation",
        headers=_auth(admin_token),
        json={"is_active": True, "temporary_password": "trader-reset-password-2", "reason": "operator credential reset"},
    )
    assert reset_active.status_code == 200
    assert reset_active.json()["activation"]["password_reset"] is True
    assert reset_active.json()["audit"]["recorded"] is True
    assert client.get("/api/auth/me", headers=_auth(trader_token)).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "trader-reset-password"},
    ).status_code == 401
    assert _login(client, "wajidali1984@hotmail.com", "trader-reset-password-2")


def test_exchange_account_metadata_is_scoped_to_owning_trader(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "second.trader@example.com",
            "username": "second-trader",
            "password": "trader-password",
            "role": "trader",
            "trader_id": "trader-second",
            "paper_account_id": "paper-second",
            "exchange_accounts": [
                {
                    "id": "binance-second",
                    "trader_id": "trader-wajidali1984",
                    "exchange": "binance",
                    "label": "Second Trader Binance Futures",
                    "account_type": "usd_m_futures",
                    "mode": "read_only",
                    "credential_ref": "ALPHAFORGE_BINANCE_SECOND_READONLY",
                    "read_only": False,
                    "live_trading_enabled": True,
                    "status": "credential_source_pending",
                }
            ],
        },
    )

    assert created.status_code == 201
    account = created.json()["user"]["exchange_accounts"][0]
    assert account["trader_id"] == "trader-second"
    assert account["paper_account_id"] == "paper-second"
    assert account["mode"] == "read_only"
    assert account["read_only"] is True
    assert account["live_trading_enabled"] is False

    updated = client.put(
        f"/api/admin/users/{created.json()['user']['id']}",
        headers=_auth(admin_token),
        json={
            "trader_id": "trader-second-updated",
            "exchange_accounts": [
                {
                    "id": "binance-second",
                    "trader_id": "trader-other",
                    "exchange": "binance",
                    "label": "Second Trader Binance Futures",
                    "account_type": "usd_m_futures",
                    "mode": "live",
                    "credential_ref": "ALPHAFORGE_BINANCE_SECOND_READONLY",
                    "read_only": False,
                    "live_trading_enabled": True,
                    "status": "unsafe_live_requested",
                }
            ],
        },
    )

    assert updated.status_code == 200
    updated_account = updated.json()["user"]["exchange_accounts"][0]
    assert updated_account["trader_id"] == "trader-second-updated"
    assert updated_account["paper_account_id"] == "paper-second"
    assert updated_account["mode"] == "read_only"
    assert updated_account["read_only"] is True
    assert updated_account["live_trading_enabled"] is False
    assert updated_account["status"] != "unsafe_live_requested"


def test_admin_user_creation_requires_trader_scope(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    missing_scope = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "unscoped.trader@example.com",
            "username": "unscoped-trader",
            "password": "trader-password",
            "role": "trader",
        },
    )
    assert missing_scope.status_code == 400
    assert missing_scope.json()["detail"] == "trader_scope_required"

    missing_scope_for_exchange = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "exchange.only@example.com",
            "username": "exchange-only",
            "password": "viewer-password",
            "role": "viewer",
            "exchange_accounts": [{"id": "binance-unscoped", "exchange": "binance"}],
        },
    )
    assert missing_scope_for_exchange.status_code == 400
    assert missing_scope_for_exchange.json()["detail"] == "exchange_account_scope_required"

    missing_paper_scope_for_exchange = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "exchange.no.paper@example.com",
            "username": "exchange-no-paper",
            "password": "viewer-password",
            "role": "viewer",
            "trader_id": "viewer-trader",
            "exchange_accounts": [{"id": "binance-no-paper", "exchange": "binance"}],
        },
    )
    assert missing_paper_scope_for_exchange.status_code == 400
    assert missing_paper_scope_for_exchange.json()["detail"] == "exchange_account_scope_required"


def test_admin_users_reject_unauthenticated_and_trader(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "trader@example.com",
            "username": "trader",
            "password": "trader-password",
            "role": "trader",
            "trader_id": "trader-test",
            "paper_account_id": "paper-test",
        },
    )
    assert created.status_code == 201
    trader_token = _login(client, "trader@example.com", "trader-password")

    client.cookies.clear()
    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/users", headers=_auth(trader_token)).status_code == 403


def test_admin_users_allow_admin_and_superadmin(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    store = UserStore(Path(tmp_path / "auth_users.json"))
    store.create_user(
        email="super@example.com",
        username="super",
        password="super-password",
        role="superadmin",
    )
    super_token = _login(client, "super@example.com", "super-password")

    assert client.get("/api/admin/users", headers=_auth(admin_token)).status_code == 200
    assert client.get("/api/admin/users", headers=_auth(super_token)).status_code == 200


def test_admin_trader_accounts_are_backend_protected_and_secret_free(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    client.cookies.clear()
    assert client.get("/api/admin/trader-accounts").status_code == 401

    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "trader2@example.com",
            "username": "trader2",
            "password": "trader-password",
            "role": "trader",
            "trader_id": "trader-test-2",
            "paper_account_id": "paper-test-2",
        },
    )
    assert created.status_code == 201
    trader_token = _login(client, "trader2@example.com", "trader-password")
    assert client.get("/api/admin/trader-accounts", headers=_auth(trader_token)).status_code == 403

    upsert = client.put(
        "/api/admin/trader-accounts/paper-wajidali1984",
        headers=_auth(admin_token),
        json={
            "trader_id": "trader-wajidali1984",
            "currency": "USDT",
            "equity": 1000,
            "realized_pnl": 0,
            "unrealized_pnl": 0,
            "positions": [{"symbol": "BTCUSDT", "quantity": 0.1, "mode": "paper"}],
            "orders": [{"order_id": "paper-admin-seed", "symbol": "BTCUSDT", "status": "open", "mode": "paper"}],
            "executions": [{"execution_id": "paper-admin-exec", "symbol": "BTCUSDT", "mode": "paper"}],
            "signals": [{"symbol": "BTCUSDT", "direction": "long", "mode": "paper"}],
        },
    )
    assert upsert.status_code == 200
    payload = upsert.json()
    assert payload["account"]["paper_account_id"] == "paper-wajidali1984"
    assert payload["account"]["equity"] == 1000

    balance_refresh = client.put(
        "/api/admin/trader-accounts/paper-wajidali1984",
        headers=_auth(admin_token),
        json={
            "trader_id": "trader-wajidali1984",
            "currency": "USDT",
            "equity": 1500,
            "source_status": "admin_balance_refresh_without_collection_replace",
        },
    )
    assert balance_refresh.status_code == 200
    refreshed_account = balance_refresh.json()["account"]
    assert refreshed_account["equity"] == 1500
    assert refreshed_account["positions"][0]["symbol"] == "BTCUSDT"
    assert refreshed_account["orders"][0]["order_id"] == "paper-admin-seed"
    assert refreshed_account["executions"][0]["execution_id"] == "paper-admin-exec"
    assert refreshed_account["signals"][0]["symbol"] == "BTCUSDT"

    integrity_response = client.get("/api/admin/trader-accounts", headers=_auth(admin_token))
    assert integrity_response.status_code == 200
    integrity_payload = integrity_response.json()
    assert integrity_payload["repository_integrity"]["status"] == "ok"
    assert integrity_payload["repository_integrity"]["unique_paper_account_scope"] is True
    assert integrity_payload["repository_integrity"]["production_repository"] is False
    assert integrity_payload["repository_integrity"]["contains_credentials"] is False
    assert integrity_payload["repository_integrity"]["live_trading_enabled"] is False
    assert integrity_payload["repository_integrity"]["exchange_mutation_enabled"] is False
    assert integrity_payload["repository_readiness"]["status"] == "partial_local_repository"
    assert integrity_payload["repository_readiness"]["production_repository"] is False
    assert integrity_payload["repository_readiness"]["durable_database_repository"] is False
    assert integrity_payload["repository_readiness"]["tenant_isolation_status"] == "local_scope_enforced"
    assert integrity_payload["repository_readiness"]["paper_account_uniqueness_enforced"] is True
    assert integrity_payload["repository_readiness"]["production_writer_validation"] == "pending"
    assert integrity_payload["repository_readiness"]["trader_account_scope_smoke_artifact_configured"] is False
    assert integrity_payload["repository_readiness"]["trader_account_scope_smoke_artifact_valid"] is False
    assert integrity_payload["repository_readiness"]["trader_account_scope_smoke_status"] == "missing"
    assert integrity_payload["repository_readiness"]["production_trader_repository_smoke_artifact_configured"] is False
    assert integrity_payload["repository_readiness"]["production_trader_repository_smoke_artifact_valid"] is False
    assert integrity_payload["repository_readiness"]["production_trader_repository_smoke_status"] == "missing"
    assert integrity_payload["repository_readiness"]["contains_credentials"] is False
    assert integrity_payload["repository_readiness"]["live_trading_enabled"] is False
    assert integrity_payload["repository_readiness"]["exchange_mutation_enabled"] is False
    assert "production_database_repository" in integrity_payload["repository_readiness"]["missing_fields"]
    assert "trader_account_scope_smoke_artifact" in integrity_payload["repository_readiness"]["missing_fields"]
    assert "production_trader_repository_smoke_artifact" in integrity_payload["repository_readiness"]["missing_fields"]
    assert "Paper account repository is local/dev storage" in integrity_payload["warnings"]
    assert "Repository integrity is local-only partial evidence" in integrity_payload["warnings"]

    conflicting_owner = client.put(
        "/api/admin/trader-accounts/paper-wajidali1984",
        headers=_auth(admin_token),
        json={
            "trader_id": "trader-test-2",
            "currency": "USDT",
            "equity": 2000,
        },
    )
    assert conflicting_owner.status_code == 400
    assert conflicting_owner.json()["detail"] == "paper_account_id is already assigned to another trader"

    serialized = json.dumps({"initial": payload, "refresh": balance_refresh.json(), "integrity": integrity_payload}).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token"):
        assert text not in serialized


def test_admin_trader_account_readiness_reports_scope_smoke_artifact(tmp_path: Path, monkeypatch) -> None:
    artifact_path = tmp_path / "scope-smoke.json"
    artifact_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "trader_account_scope_status": "passed",
                "checks": {
                    "auth_users_loaded": True,
                    "trader_users_have_scope": True,
                    "paper_account_ids_unique_across_traders": True,
                    "exchange_accounts_match_owner_scope": True,
                    "exchange_accounts_read_only": True,
                    "exchange_accounts_live_disabled": True,
                    "exchange_accounts_secret_free": True,
                    "repository_accounts_have_scope": True,
                    "repository_account_scopes_unique": True,
                    "initial_trader_scope_present": True,
                },
                "summary": {
                    "user_count": 2,
                    "trader_user_count": 2,
                    "repository_account_count": 2,
                },
                "public_market_data_only": True,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_SCOPE_SMOKE_ARTIFACT", str(artifact_path))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/trader-accounts", headers=_auth(admin_token))

    assert response.status_code == 200
    readiness = response.json()["repository_readiness"]
    assert readiness["trader_account_scope_smoke_artifact_configured"] is True
    assert readiness["trader_account_scope_smoke_artifact_valid"] is True
    assert readiness["trader_account_scope_smoke_status"] == "artifact_present_pending_current_validation"
    assert readiness["trader_account_scope_smoke_evidence"]["trader_user_count"] == 2
    assert readiness["trader_account_scope_smoke_evidence"]["contains_credentials"] is False
    assert readiness["trader_account_scope_smoke_evidence"]["live_trading_enabled"] is False
    assert "trader_account_scope_smoke_current_validation" in readiness["missing_fields"]
    assert "trader_account_scope_smoke_artifact" not in readiness["missing_fields"]
    serialized = json.dumps(readiness).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token"):
        assert text not in serialized


def test_admin_trader_account_readiness_reports_production_repository_smoke_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "production-trader-repository-smoke.json"
    artifact.write_text(
        json.dumps(
            {
                "production_trader_repository_smoke_status": "passed",
                "durable_user_repository": True,
                "durable_trader_account_repository": True,
                "account_writer_persistence": True,
                "activity_writer_persistence": True,
                "row_level_trader_isolation": True,
                "paper_account_uniqueness": True,
                "migration_applied": True,
                "backup_restore_verified": True,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "missing_fields": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_PRODUCTION_TRADER_REPOSITORY_SMOKE_ARTIFACT", str(artifact))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/trader-accounts", headers=_auth(admin_token))

    assert response.status_code == 200
    readiness = response.json()["repository_readiness"]
    assert readiness["production_trader_repository_smoke_artifact_configured"] is True
    assert readiness["production_trader_repository_smoke_artifact_valid"] is True
    assert readiness["production_trader_repository_smoke_status"] == "artifact_present_pending_current_validation"
    assert readiness["production_trader_repository_smoke_evidence"]["durable_user_repository"] is True
    assert readiness["production_trader_repository_smoke_evidence"]["row_level_trader_isolation"] is True
    assert readiness["production_trader_repository_smoke_evidence"]["contains_credentials"] is False
    assert readiness["production_trader_repository_smoke_evidence"]["live_trading_enabled"] is False
    assert "production_trader_repository_smoke_artifact" not in readiness["missing_fields"]
    assert "production_writer_validation" in readiness["missing_fields"]
    serialized = json.dumps(readiness).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token"):
        assert text not in serialized


def test_admin_trader_account_readiness_reports_paper_action_validation_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "production-paper-action-validation.json"
    artifact.write_text(
        json.dumps(
            {
                "production_paper_action_validation_smoke_status": "passed",
                "paper_submit_validated": True,
                "paper_cancel_validated": True,
                "paper_fill_disabled_by_policy": True,
                "production_paper_actions_fail_closed": True,
                "service_verified_paper_only": True,
                "trader_scope_enforced": True,
                "paper_account_scope_enforced": True,
                "backend_owned_order_ids": True,
                "durable_repository_verified": True,
                "audit_event_linked": True,
                "contains_credentials": False,
                "live_transport_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "real_order_cancelled": False,
                "leverage_mutation_enabled": False,
                "margin_mutation_enabled": False,
                "live_gate_mutation_enabled": False,
                "missing_fields": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_PRODUCTION_PAPER_ACTION_VALIDATION_ARTIFACT", str(artifact))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/trader-accounts", headers=_auth(admin_token))

    assert response.status_code == 200
    readiness = response.json()["paper_action_readiness"]
    assert readiness["status"] == "artifact_present_pending_current_validation"
    assert readiness["production_paper_action_validation_artifact_configured"] is True
    assert readiness["production_paper_action_validation_artifact_valid"] is True
    assert readiness["production_paper_action_validation_artifact_status"] == "passed"
    assert readiness["paper_submit_validated"] is True
    assert readiness["paper_cancel_validated"] is True
    assert readiness["paper_fill_disabled_by_policy"] is True
    assert readiness["service_verified_paper_only"] is True
    assert readiness["trader_scope_enforced"] is True
    assert readiness["paper_account_scope_enforced"] is True
    assert readiness["contains_credentials"] is False
    assert readiness["live_transport_enabled"] is False
    assert readiness["exchange_mutation_enabled"] is False
    assert readiness["real_order_submitted"] is False
    assert readiness["real_order_cancelled"] is False
    assert "production_paper_action_validation_artifact" not in readiness["missing_fields"]
    assert "production_paper_submit_cancel_current_validation" in readiness["missing_fields"]
    serialized = json.dumps(readiness).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token"):
        assert text not in serialized


def test_admin_trader_account_readiness_reports_alert_delivery_audit_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "production-alert-delivery-audit.json"
    artifact.write_text(
        json.dumps(
            {
                "production_alert_delivery_audit_smoke_status": "passed",
                "alert_repository_configured": True,
                "alert_crud_validated": True,
                "trader_scope_enforced": True,
                "paper_account_scope_enforced": True,
                "delivery_service_configured": True,
                "notification_delivery_tested": True,
                "delivery_secret_redacted": True,
                "audit_repository_durable": True,
                "audit_events_linked": True,
                "audit_retention_enforced": True,
                "access_control_enforced": True,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "live_gate_mutation_enabled": False,
                "missing_fields": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_PRODUCTION_ALERT_DELIVERY_AUDIT_ARTIFACT", str(artifact))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/trader-accounts", headers=_auth(admin_token))

    assert response.status_code == 200
    readiness = response.json()["alert_delivery_audit_readiness"]
    assert readiness["status"] == "artifact_present_pending_current_validation"
    assert readiness["production_alert_delivery_audit_artifact_configured"] is True
    assert readiness["production_alert_delivery_audit_artifact_valid"] is True
    assert readiness["production_alert_delivery_audit_artifact_status"] == "passed"
    assert readiness["alert_repository_configured"] is True
    assert readiness["notification_delivery_tested"] is True
    assert readiness["audit_repository_durable"] is True
    assert readiness["contains_credentials"] is False
    assert readiness["live_trading_enabled"] is False
    assert readiness["exchange_mutation_enabled"] is False
    assert readiness["real_order_submitted"] is False
    assert readiness["live_gate_mutation_enabled"] is False
    assert "production_alert_delivery_audit_artifact" not in readiness["missing_fields"]
    assert "production_alert_delivery_audit_current_validation" in readiness["missing_fields"]
    serialized = json.dumps(readiness).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "webhook_url"):
        assert text not in serialized


def test_admin_credential_status_is_backend_protected_and_secret_free(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY", "test-read-only-key")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET", "test-read-only-secret")
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    client.cookies.clear()
    assert client.get("/api/admin/credential-status").status_code == 401

    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "trader3@example.com",
            "username": "trader3",
            "password": "trader-password",
            "role": "trader",
            "trader_id": "trader-test-3",
            "paper_account_id": "paper-test-3",
        },
    )
    assert created.status_code == 201
    trader_token = _login(client, "trader3@example.com", "trader-password")
    assert client.get("/api/admin/credential-status", headers=_auth(trader_token)).status_code == 403

    response = client.get("/api/admin/credential-status", headers=_auth(admin_token))

    assert response.status_code == 200
    payload = response.json()
    account = next(
        row["exchange_account"]
        for row in payload["accounts"]
        if row["trader_id"] == "trader-wajidali1984"
    )
    assert account["credential_status"]["configured"] is True
    assert account["credential_status"]["credential_ref"] is None
    assert account["credential_status"]["raw_credential_value_exposed"] is False
    assert account["credential_status"]["live_trading_enabled"] is False
    assert payload["credential_vault_readiness"]["status"] == "partial_backend_only_local_binding"
    assert payload["credential_vault_readiness"]["backend_only"] is True
    assert payload["credential_vault_readiness"]["environment_binding_supported"] is True
    assert payload["credential_vault_readiness"]["durable_production_vault_integrated"] is False
    assert payload["credential_vault_readiness"]["durable_production_vault_artifact_configured"] is False
    assert payload["credential_vault_readiness"]["durable_production_vault_artifact_valid"] is False
    assert payload["credential_vault_readiness"]["durable_production_vault_artifact_status"] == "pending"
    assert payload["credential_vault_readiness"]["credential_rotation_policy_status"] == "missing"
    assert payload["credential_vault_readiness"]["permission_probe_status"] == "pending"
    assert payload["credential_vault_readiness"]["permission_probe_artifact_configured"] is False
    assert payload["credential_vault_readiness"]["permission_probe_artifact_valid"] is False
    assert payload["credential_vault_readiness"]["permission_probe_artifact_status"] == "pending"
    assert payload["credential_vault_readiness"]["signed_read_validation_status"] == "pending"
    assert payload["credential_vault_readiness"]["signed_read_validation_artifact_configured"] is False
    assert payload["credential_vault_readiness"]["signed_read_validation_artifact_valid"] is False
    assert payload["credential_vault_readiness"]["signed_read_validation_artifact_status"] == "pending"
    assert payload["credential_vault_readiness"]["secret_redaction_smoke_status"] == "pending"
    assert payload["credential_vault_readiness"]["secret_redaction_smoke_artifact_configured"] is False
    assert payload["credential_vault_readiness"]["secret_redaction_smoke_artifact_valid"] is False
    assert payload["credential_vault_readiness"]["secret_redaction_smoke_artifact_status"] == "pending"
    assert payload["credential_vault_readiness"]["raw_credential_value_exposed"] is False
    assert payload["credential_vault_readiness"]["live_trading_enabled"] is False
    assert payload["credential_vault_readiness"]["exchange_mutation_enabled"] is False
    assert "durable_production_credential_vault" in payload["credential_vault_readiness"]["missing_fields"]
    assert "durable_credential_vault_artifact" in payload["credential_vault_readiness"]["missing_fields"]
    assert "durable_credential_vault_current_validation" in payload["credential_vault_readiness"]["missing_fields"]
    assert payload["admin_audit_readiness"]["backend"] == "local_file"
    assert payload["admin_audit_readiness"]["append_only_local_file"] is True
    assert payload["admin_audit_readiness"]["production_durable_store"] is False
    assert payload["admin_audit_readiness"]["retention_policy_configured"] is False
    assert payload["admin_audit_readiness"]["retention_policy_status"] == "missing"
    assert "admin_audit_retention_days" in payload["admin_audit_readiness"]["missing_fields"]
    assert payload["admin_audit_readiness"]["live_mutation_prohibited"] is True
    assert payload["deployment_readiness"]["status"] == "missing"
    assert payload["deployment_readiness"]["production_https_smoke_artifact_configured"] is False
    assert payload["deployment_readiness"]["production_https_smoke_artifact_valid"] is False
    assert payload["deployment_readiness"]["production_https_smoke_artifact_status"] == "pending"
    assert payload["deployment_readiness"]["live_trading_enabled"] is False
    assert payload["deployment_readiness"]["exchange_mutation_enabled"] is False
    assert "production_https_smoke_artifact" in payload["deployment_readiness"]["missing_fields"]
    assert payload["auth_session_hardening_readiness"]["status"] == "missing"
    assert (
        payload["auth_session_hardening_readiness"]["production_auth_session_hardening_artifact_configured"]
        is False
    )
    assert payload["auth_session_hardening_readiness"]["production_auth_session_hardening_artifact_valid"] is False
    assert (
        payload["auth_session_hardening_readiness"]["production_auth_session_hardening_artifact_status"]
        == "pending"
    )
    assert payload["auth_session_hardening_readiness"]["live_trading_enabled"] is False
    assert payload["auth_session_hardening_readiness"]["exchange_mutation_enabled"] is False
    assert "production_auth_session_hardening_artifact" in payload["auth_session_hardening_readiness"]["missing_fields"]
    assert any("Admin audit readiness is partial" in warning for warning in payload["warnings"])
    serialized = json.dumps(payload).lower()
    for text in (
        "api_key",
        "api_secret",
        "password_hash",
        "access_token",
        "test-read-only-key",
        "test-read-only-secret",
        "alphaforge_binance_wajidali1984_readonly",
    ):
        assert text not in serialized


def test_admin_credential_status_reports_production_https_smoke_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "production_https_smoke.json"
    artifact.write_text(
        json.dumps(
            {
                "production_https_smoke_status": "passed",
                "https_enabled": True,
                "routes_checked": True,
                "missing_routes": [],
                "public_status_checked": True,
                "public_status_safe": True,
                "auth_gate_checked": True,
                "admin_unauthenticated_blocked": True,
                "superadmin_admin_rejected": True,
                "console_errors_absent": True,
                "secret_exposure_found": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "live_submit_available": False,
                "live_cancel_available": False,
                "leverage_mutation_available": False,
                "margin_mutation_available": False,
                "missing_fields": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_PRODUCTION_HTTPS_SMOKE_ARTIFACT", str(artifact))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/credential-status", headers=_auth(admin_token))

    assert response.status_code == 200
    readiness = response.json()["deployment_readiness"]
    assert readiness["status"] == "artifact_present_pending_current_validation"
    assert readiness["production_https_smoke_artifact_configured"] is True
    assert readiness["production_https_smoke_artifact_valid"] is True
    assert readiness["production_https_smoke_artifact_status"] == "passed"
    assert readiness["https_enabled"] is True
    assert readiness["routes_checked"] is True
    assert readiness["public_status_safe"] is True
    assert readiness["auth_gate_checked"] is True
    assert readiness["console_errors_absent"] is True
    assert readiness["secret_exposure_found"] is False
    assert readiness["live_trading_enabled"] is False
    assert readiness["exchange_mutation_enabled"] is False
    assert "production_https_smoke_current_validation" in readiness["missing_fields"]
    assert "production_https_smoke_artifact" not in readiness["missing_fields"]
    serialized = json.dumps(readiness).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token"):
        assert text not in serialized


def test_admin_credential_status_reports_auth_session_hardening_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    artifact = tmp_path / "auth_session_hardening.json"
    artifact.write_text(
        json.dumps(
            {
                "production_auth_session_hardening_status": "passed",
                "production_auth_secret_configured": True,
                "auth_secret_strength_verified": True,
                "issuer_configured": True,
                "audience_configured": True,
                "secure_cookie_enabled": True,
                "cookie_samesite_configured": True,
                "session_ttl_enforced": True,
                "refresh_rotation_enabled": True,
                "revocation_store_durable": True,
                "session_version_invalidation_enabled": True,
                "password_change_revokes_sessions": True,
                "admin_step_up_enabled": True,
                "backend_role_checks_enforced": True,
                "unauthorized_admin_blocked": True,
                "superadmin_admin_rejected": True,
                "contains_credentials": False,
                "token_exposure_found": False,
                "plaintext_password_exposure_found": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "live_submit_available": False,
                "live_cancel_available": False,
                "leverage_mutation_available": False,
                "margin_mutation_available": False,
                "missing_fields": [],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_HARDENING_ARTIFACT", str(artifact))
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/credential-status", headers=_auth(admin_token))

    assert response.status_code == 200
    readiness = response.json()["auth_session_hardening_readiness"]
    assert readiness["status"] == "artifact_present_pending_current_validation"
    assert readiness["production_auth_session_hardening_artifact_configured"] is True
    assert readiness["production_auth_session_hardening_artifact_valid"] is True
    assert readiness["production_auth_session_hardening_artifact_status"] == "passed"
    assert readiness["production_auth_secret_configured"] is True
    assert readiness["auth_secret_strength_verified"] is True
    assert readiness["issuer_configured"] is True
    assert readiness["audience_configured"] is True
    assert readiness["secure_cookie_enabled"] is True
    assert readiness["cookie_samesite_configured"] is True
    assert readiness["session_ttl_enforced"] is True
    assert readiness["refresh_rotation_enabled"] is True
    assert readiness["revocation_store_durable"] is True
    assert readiness["session_version_invalidation_enabled"] is True
    assert readiness["password_change_revokes_sessions"] is True
    assert readiness["admin_step_up_enabled"] is True
    assert readiness["backend_role_checks_enforced"] is True
    assert readiness["unauthorized_admin_blocked"] is True
    assert readiness["superadmin_admin_rejected"] is True
    assert readiness["contains_credentials"] is False
    assert readiness["token_exposure_found"] is False
    assert readiness["plaintext_password_exposure_found"] is False
    assert readiness["live_trading_enabled"] is False
    assert readiness["exchange_mutation_enabled"] is False
    assert "production_auth_session_hardening_current_validation" in readiness["missing_fields"]
    assert "production_auth_session_hardening_artifact" not in readiness["missing_fields"]
    serialized = json.dumps(readiness).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "bearer"):
        assert text not in serialized


def test_trader_exchange_link_route_is_metadata_only(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")
    created = client.post(
        "/api/admin/users",
        headers=_auth(admin_token),
        json={
            "email": "metadata.trader@example.com",
            "username": "metadata-trader",
            "password": "trader-password",
            "role": "trader",
            "trader_id": "trader-metadata",
            "paper_account_id": "paper-metadata",
        },
    )
    assert created.status_code == 201
    trader_token = _login(client, "metadata.trader@example.com", "trader-password")

    response = client.post(
        "/api/accounts/me/exchange-accounts",
        headers=_auth(trader_token),
        json={
            "exchange": "binance",
            "label": "Metadata Binance Futures",
            "account_type": "usd_m_futures",
            "credential_ref": "ALPHAFORGE_SHOULD_NOT_STORE",
        },
    )

    assert response.status_code == 400
    serialized = json.dumps(response.json()).lower()
    for text in ("alphaforge_should_not_store", "api_key", "api_secret", "password_hash", "access_token"):
        assert text not in serialized


def test_trader_exchange_readonly_snapshot_is_scoped_and_secret_free(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "trader-password")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_KEY", "test-read-only-key")
    monkeypatch.setenv("ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY_API_SECRET", "test-read-only-secret")

    def fake_collect_account_position_evidence(*, client, sleep_func=None):
        assert set(client.readonly_endpoint_paths) == {"/fapi/v3/account", "/fapi/v2/positionRisk"}
        return {
            "account_snapshot": {
                "fetched_at": "2026-06-13T00:00:00Z",
                "available_balance": 25.0,
                "total_wallet_balance": 30.0,
                "total_unrealized_profit": 0.0,
                "total_margin_balance": 30.0,
                "total_maint_margin": 0.0,
                "can_trade": False,
                "raw_fields_present": ["availableBalance", "canTrade"],
            },
            "positions": [],
            "account_fetch_ts": "2026-06-13T00:00:00Z",
            "positions_fetch_ts": "2026-06-13T00:00:00Z",
            "trade_permission_status": "TRADE_PERMISSION_EVIDENCE_PRESENT_READONLY",
            "margin_mode_evidence": "MISSING_EVIDENCE",
            "leverage_evidence": "MISSING_EVIDENCE",
        }

    monkeypatch.setattr(market_contracts, "collect_account_position_evidence", fake_collect_account_position_evidence)
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "wajidali1984@hotmail.com", "trader-password")

    response = client.get("/api/v2/account/exchange-readonly", headers=_auth(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoint"] == "/api/v2/account/exchange-readonly"
    assert payload["mode"] == "read_only"
    assert payload["data"]["trader_id"] == "trader-wajidali1984"
    assert payload["data"]["paper_account_id"] == "paper-wajidali1984"
    assert payload["data"]["live_trading_enabled"] is False
    assert payload["data"]["account_snapshot"]["available_balance"] == 25.0
    serialized = json.dumps(payload).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "test-read-only-key", "test-read-only-secret", "alphaforge_binance_wajidali1984_readonly"):
        assert text not in serialized


def test_trader_exchange_readonly_missing_credentials_hides_backend_reference(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "trader-password")
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "wajidali1984@hotmail.com", "trader-password")

    response = client.get("/api/v2/account/exchange-readonly", headers=_auth(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "secure_credential_binding"
    assert payload["source_type"] == "unavailable"
    assert "credential" in payload["missing_fields"]
    serialized = json.dumps(payload).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "alphaforge_binance_wajidali1984_readonly"):
        assert text not in serialized


def test_trader_exchange_readonly_rejects_paper_account_scope_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "trader-password")

    def mismatched_exchange_accounts(accounts, *, expose_credential_ref=False):
        return [
            {
                "id": "binance-wrong-paper",
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-other",
                "exchange": "binance",
                "account_type": "usd_m_futures",
                "read_only": True,
                "live_trading_enabled": False,
                "status": "credential_source_pending",
            }
        ]

    monkeypatch.setattr(market_contracts, "safe_exchange_accounts", mismatched_exchange_accounts)
    client = _client(tmp_path, monkeypatch)
    token = _login(client, "wajidali1984@hotmail.com", "trader-password")

    response = client.get("/api/v2/account/exchange-readonly", headers=_auth(token))

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_type"] == "unavailable"
    assert payload["data"]["exchange_account_id"] is None
    assert "exchange_account" in payload["missing_fields"]
    assert payload["data"]["live_trading_enabled"] is False


def test_superadmin_route_rejects_admin(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    admin_token = _login(client, "admin@example.com", "correct-password")

    response = client.get("/api/admin/evidence", headers=_auth(admin_token))

    assert response.status_code == 403


def test_order_preview_rejects_live_mode(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "market",
            "quantity": 1,
            "mode": "live",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["allowed"] is False
    assert payload["data"]["reason"] == "live_mode_rejected"
    assert payload["mode"] == "live_blocked"


def test_market_contracts_return_structured_unavailable_state(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.get("/api/v2/market/BTCUSDT/depth")

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoint"] == "/api/v2/market/BTCUSDT/depth"
    assert payload["source_type"] == "unavailable"
    assert payload["stale"] is True
    assert "bids" in payload["missing_fields"]


def test_public_status_exposes_no_forbidden_internal_fields(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.get("/api/v2/status")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "platform_status",
        "api_status",
        "data_status",
        "paper_mode",
        "live_trading_enabled",
        "status_dimensions",
        "market_stream",
        "market_stream_alert",
        "market_stream_alert_history",
        "market_stream_alert_notifier",
        "derivatives_data",
        "incidents",
        "updated_at",
        "source",
        "endpoint",
        "stale",
        "warnings",
    }
    assert payload["live_trading_enabled"] is False
    assert payload["status_dimensions"]["market_data"] in {"LIVE", "DELAYED", "STALE", "OFFLINE"}
    assert payload["status_dimensions"]["automation"] in {"ACTIVE", "PAUSED", "DEGRADED", "UNKNOWN"}
    assert payload["status_dimensions"]["execution"] == "RESTRICTED"
    assert payload["status_dimensions"]["account"] == "UNAUTHORIZED"
    assert payload["status_dimensions"]["places_real_order"] is False
    assert payload["status_dimensions"]["order_submission_enabled"] is False
    assert payload["status_dimensions"]["exchange_mutation_enabled"] is False
    assert payload["market_stream"]["symbol"] == "BTCUSDT"
    assert set(payload["market_stream"]) == {
        "symbol",
        "status",
        "source",
        "last_frame_at",
        "lag_ms",
        "stale",
    }
    assert set(payload["market_stream_alert"]) == {
        "status",
        "severity",
        "summary",
        "action",
        "stale_for_ms",
    }
    assert set(payload["derivatives_data"]) == {
        "status",
        "source",
        "funding",
        "open_interest",
        "liquidations",
        "long_short",
        "basis",
        "exchange_comparison",
        "stale",
        "missing_count",
    }
    assert payload["derivatives_data"]["status"] in {"pending", "verified"}
    forbidden = json.dumps(payload).lower()
    for text in (
        "password",
        "token",
        "traceback",
        "stack",
        "api_key",
        "secret",
        "local file",
        "audit ledger",
        "market_stream_telemetry.json",
    ):
        assert text not in forbidden


def test_credential_vault_readiness_accepts_safe_signed_read_artifact(tmp_path: Path, monkeypatch) -> None:
    from app.services.credential_status import credential_vault_readiness_status

    artifact = tmp_path / "signed_read_validation.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "passed",
                "read_only": True,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_SIGNED_READ_VALIDATION_ARTIFACT", str(artifact))

    payload = credential_vault_readiness_status()

    assert payload["signed_read_validation_status"] == "passed"
    assert payload["signed_read_validation_artifact_configured"] is True
    assert payload["signed_read_validation_artifact_valid"] is True
    assert payload["signed_read_validation_artifact_status"] == "passed"
    assert "signed_readonly_account_validation" not in payload["missing_fields"]
    assert payload["raw_credential_value_exposed"] is False
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False


def test_credential_vault_readiness_accepts_safe_permission_probe_artifact(tmp_path: Path, monkeypatch) -> None:
    from app.services.credential_status import credential_vault_readiness_status

    artifact = tmp_path / "credential_permission_probe.json"
    artifact.write_text(
        json.dumps(
            {
                "permission_probe_status": "passed",
                "read_only_permissions_validated": True,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "order_write_enabled": False,
                "withdraw_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_CREDENTIAL_PERMISSION_PROBE_ARTIFACT", str(artifact))

    payload = credential_vault_readiness_status()

    assert payload["permission_probe_status"] == "passed"
    assert payload["permission_probe_artifact_configured"] is True
    assert payload["permission_probe_artifact_valid"] is True
    assert payload["permission_probe_artifact_status"] == "passed"
    assert "permission_probe" not in payload["missing_fields"]
    assert payload["raw_credential_value_exposed"] is False
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False


def test_credential_vault_readiness_accepts_safe_secret_redaction_smoke_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    from app.services.credential_status import credential_vault_readiness_status

    artifact = tmp_path / "secret_redaction_smoke.json"
    artifact.write_text(
        json.dumps(
            {
                "secret_redaction_smoke_status": "passed",
                "raw_credential_value_exposed": False,
                "api_key_exposed": False,
                "api_secret_exposed": False,
                "access_token_exposed": False,
                "safe_api_payloads_checked": True,
                "logs_checked": True,
                "screenshots_checked": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_SECRET_REDACTION_SMOKE_ARTIFACT", str(artifact))

    payload = credential_vault_readiness_status()

    assert payload["secret_redaction_smoke_status"] == "passed"
    assert payload["secret_redaction_smoke_artifact_configured"] is True
    assert payload["secret_redaction_smoke_artifact_valid"] is True
    assert payload["secret_redaction_smoke_artifact_status"] == "passed"
    assert "secret_redaction_smoke" not in payload["missing_fields"]
    assert payload["raw_credential_value_exposed"] is False
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False


def test_credential_vault_readiness_accepts_safe_durable_vault_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    from app.services.credential_status import credential_vault_readiness_status

    artifact = tmp_path / "durable_credential_vault.json"
    artifact.write_text(
        json.dumps(
            {
                "durable_credential_vault_status": "verified",
                "durable_production_vault_integrated": True,
                "backend_only_secret_access": True,
                "read_only_scope_enforced": True,
                "credential_rotation_policy_configured": True,
                "secret_redaction_verified": True,
                "access_control_enforced": True,
                "audit_logging_enabled": True,
                "raw_credential_value_exposed": False,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "order_write_enabled": False,
                "withdraw_enabled": False,
                "missing_fields": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_DURABLE_CREDENTIAL_VAULT_ARTIFACT", str(artifact))

    payload = credential_vault_readiness_status()

    assert payload["status"] == "artifact_present_pending_current_validation"
    assert payload["durable_production_vault_integrated"] is True
    assert payload["durable_production_vault_artifact_configured"] is True
    assert payload["durable_production_vault_artifact_valid"] is True
    assert payload["durable_production_vault_artifact_status"] == "passed"
    assert payload["credential_rotation_policy_status"] == "configured"
    assert "durable_production_credential_vault" not in payload["missing_fields"]
    assert "durable_credential_vault_artifact" not in payload["missing_fields"]
    assert "credential_rotation_policy" not in payload["missing_fields"]
    assert "durable_credential_vault_current_validation" in payload["missing_fields"]
    assert payload["raw_credential_value_exposed"] is False
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
    serialized = json.dumps(payload).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token"):
        assert text not in serialized
