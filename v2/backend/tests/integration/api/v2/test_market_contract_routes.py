from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v2 import market_contracts
from app.auth.users import get_user_store
from app.main import create_app
from app.services.paper_audit_ledger import append_local_paper_audit_event, local_paper_audit_ledger_metadata
from app.services.trader_account_repository import (
    SqlAlchemyTraderAccountRepository,
    TraderAccountRepository,
    get_trader_account_repository,
)


def _client(tmp_path: Path, monkeypatch, *, isolate_redis: bool = False) -> TestClient:
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(market_contracts, "BINANCE_FAPI_BASE", "http://127.0.0.1:9")
    monkeypatch.setattr(market_contracts, "BINANCE_HTTP_TIMEOUT_SECONDS", 0.05)
    market_contracts.MARKET_STREAM_TELEMETRY.clear()
    if isolate_redis:
        monkeypatch.setattr(market_contracts, "get_redis", lambda: None)
    return TestClient(create_app())


def _configure_auth_for_later_production(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "x" * 48)
    monkeypatch.setenv("ALPHAFORGE_AUTH_ISSUER", "alphaforge-v2")
    monkeypatch.setenv("ALPHAFORGE_AUTH_AUDIENCE", "alphaforge-web")
    monkeypatch.setenv("ALPHAFORGE_AUTH_SESSION_MINUTES", "480")
    monkeypatch.setenv("ALPHAFORGE_AUTH_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_DATABASE_URL", f"sqlite:///{tmp_path / 'revocations.db'}")
    monkeypatch.setenv("ALPHAFORGE_AUTH_REVOCATION_DB_AUTO_CREATE", "1")
    monkeypatch.setenv("ALPHAFORGE_ALLOW_LOCAL_AUTH_STORE_IN_PRODUCTION", "test-only")


def _write_json(root: Path, relative: str, payload: dict) -> None:
    path = root / "v2" / "frontend" / "public" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _assert_contract(response: dict, endpoint: str) -> None:
    assert response["endpoint"] == endpoint
    assert "source" in response
    assert response["source_type"] in {"api", "repository", "static_payload", "static_snapshot", "unavailable", "redis_live"}
    assert "received_at" in response
    assert "stale" in response
    assert isinstance(response["missing_fields"], list)
    assert isinstance(response["warnings"], list)
    assert response["mode"] in {"paper", "read_only", "live_blocked", "paper_preview_unverified"}
    if "trader_context" in response:
        assert "account_scope" in response
        assert response["account_scope"]["live_trading_enabled"] is False
        assert response["account_scope"]["exchange_mutation_enabled"] is False


def test_alerts_contract_returns_structured_unavailable_state(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.get("/api/v2/alerts")

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload, "/api/v2/alerts")
    assert payload["source_type"] == "unavailable"
    assert payload["stale"] is True
    assert payload["data"]["alerts"] == []
    assert payload["data"]["create_enabled"] is False
    assert payload["data"]["delivery_enabled"] is False
    assert payload["data"]["audit_logging_enabled"] is False
    assert "alert_repository" in payload["missing_fields"]
    assert "notification_delivery" in payload["missing_fields"]
    assert "mutated" not in json.dumps(payload).lower()


def test_authenticated_alerts_use_scoped_local_repository_without_delivery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    client = _client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    initial = client.get("/api/v2/alerts").json()
    _assert_contract(initial, "/api/v2/alerts")
    _assert_authenticated_account_scope(initial, verified=True)
    assert initial["source_type"] == "repository"
    assert initial["data"]["create_enabled"] is True
    assert initial["data"]["delivery_enabled"] is False
    assert initial["data"]["audit_logging_enabled"] is True
    assert initial["data"]["alerts"] == []
    assert "notification_delivery" in initial["missing_fields"]

    invalid_create = client.post(
        "/api/v2/alerts",
        json={
            "alert_type": "Price movement",
            "symbol": "btcusdt../",
            "condition": "Last price above",
            "threshold": 125000,
            "enabled": True,
        },
    )
    assert invalid_create.status_code == 400
    invalid_create_payload = invalid_create.json()
    _assert_contract(invalid_create_payload, "/api/v2/alerts")
    assert invalid_create_payload["source_type"] == "unavailable"
    assert "symbol" in invalid_create_payload["missing_fields"]
    assert "Enter a valid market symbol" in invalid_create_payload["warnings"]
    assert invalid_create_payload["data"]["alerts"] == []

    created = client.post(
        "/api/v2/alerts",
        json={
            "alert_type": "Price movement",
            "symbol": "BTCUSDT",
            "condition": "Last price above",
            "threshold": 125000,
            "enabled": True,
        },
    ).json()
    _assert_contract(created, "/api/v2/alerts")
    _assert_authenticated_account_scope(created, verified=True)
    assert created["data"]["last_action"]["type"] == "created"
    alert = created["data"]["alerts"][0]
    assert alert["trader_id"] == "trader-wajidali1984"
    assert alert["paper_account_id"] == "paper-wajidali1984"
    assert alert["delivery_enabled"] is False
    assert alert["audit_event_count"] == 1
    alert_id = alert["id"]

    updated = client.put(f"/api/v2/alerts/{alert_id}", json={"muted": True}).json()
    _assert_contract(updated, "/api/v2/alerts")
    assert updated["data"]["last_action"]["type"] == "updated"
    assert updated["data"]["alerts"][0]["muted"] is True
    assert updated["data"]["alerts"][0]["delivery_enabled"] is False
    assert updated["data"]["alerts"][0]["audit_event_count"] == 2

    invalid_update = client.put(f"/api/v2/alerts/{alert_id}", json={"symbol": "btcusdt../"})
    assert invalid_update.status_code == 400
    invalid_update_payload = invalid_update.json()
    _assert_contract(invalid_update_payload, "/api/v2/alerts")
    assert invalid_update_payload["source_type"] == "unavailable"
    assert "symbol" in invalid_update_payload["missing_fields"]
    assert "Enter a valid market symbol" in invalid_update_payload["warnings"]

    after_invalid_update = client.get("/api/v2/alerts").json()
    _assert_contract(after_invalid_update, "/api/v2/alerts")
    assert after_invalid_update["data"]["alerts"][0]["symbol"] == "BTCUSDT"

    deleted = client.delete(f"/api/v2/alerts/{alert_id}").json()
    _assert_contract(deleted, "/api/v2/alerts")
    assert deleted["data"]["last_action"]["type"] == "deleted"
    assert deleted["data"]["alerts"] == []
    assert "notification_delivery" in deleted["missing_fields"]
    serialized = json.dumps(deleted).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "live_order"):
        assert text not in serialized


def test_authenticated_alerts_can_use_sqlalchemy_repository_without_delivery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    monkeypatch.setenv("ALPHAFORGE_ALERT_STORE_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_ALERT_DATABASE_URL", f"sqlite:///{tmp_path / 'alerts.db'}")
    monkeypatch.setenv("ALPHAFORGE_ALERT_DB_AUTO_CREATE", "1")
    client = _client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    created = client.post(
        "/api/v2/alerts",
        json={
            "alert_type": "Funding rate",
            "symbol": "BTCUSDT",
            "condition": "Funding above",
            "threshold": 0.0004,
            "enabled": True,
        },
    ).json()
    _assert_contract(created, "/api/v2/alerts")
    _assert_authenticated_account_scope(created, verified=True)
    assert created["source"] == "sqlalchemy_trader_alert_repository"
    assert created["data"]["repository_status"] == "sqlalchemy_repository"
    assert created["data"]["delivery_enabled"] is False
    assert created["data"]["alerts"][0]["alert_type"] == "Funding rate"

    listed = client.get("/api/v2/alerts").json()
    _assert_contract(listed, "/api/v2/alerts")
    assert listed["source"] == "sqlalchemy_trader_alert_repository"
    assert listed["data"]["alerts"][0]["paper_account_id"] == "paper-wajidali1984"
    assert listed["data"]["alerts"][0]["delivery_enabled"] is False
    assert "notification_delivery" in listed["missing_fields"]


def _assert_authenticated_account_scope(payload: dict, *, verified: bool) -> None:
    assert payload["account_scope"]["scope"] == "authenticated_trader"
    assert payload["account_scope"]["trader_id"] == "trader-wajidali1984"
    assert payload["account_scope"]["paper_account_id"] == "paper-wajidali1984"
    if verified:
        assert payload["account_scope"]["data_trader_id"] == "trader-wajidali1984"
        assert payload["account_scope"]["data_paper_account_id"] == "paper-wajidali1984"
    assert payload["account_scope"]["authenticated"] is True
    assert payload["account_scope"]["actor_scope_present"] is True
    assert payload["account_scope"]["data_account_specific"] is verified
    assert payload["account_scope"]["data_scope_matches_actor"] is verified
    assert payload["account_scope"]["scope_verified"] is verified
    assert payload["account_scope"]["live_trading_enabled"] is False
    assert payload["account_scope"]["exchange_mutation_enabled"] is False


def test_account_readiness_contract_is_scoped_and_secret_free(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    client = _client(tmp_path, monkeypatch)

    public_payload = client.get("/api/v2/account/readiness").json()
    _assert_contract(public_payload, "/api/v2/account/readiness")
    assert public_payload["source_type"] == "unavailable"
    assert public_payload["mode"] == "paper"
    assert "trader_session" in public_payload["missing_fields"]
    assert public_payload["data"]["account_specific"] is False
    assert public_payload["data"]["live_trading_enabled"] is False
    assert public_payload["data"]["exchange_mutation_enabled"] is False

    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    get_trader_account_repository().upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=1000,
        realized_pnl=0,
        unrealized_pnl=0,
        positions=[],
        orders=[],
        executions=[],
        signals=[],
        source_status="test_account_readiness_repository",
    )
    payload = client.get("/api/v2/account/readiness").json()
    _assert_contract(payload, "/api/v2/account/readiness")
    _assert_authenticated_account_scope(payload, verified=True)
    assert payload["source_type"] == "repository"
    assert payload["data"]["trader_id"] == "trader-wajidali1984"
    assert payload["data"]["paper_account_id"] == "paper-wajidali1984"
    assert payload["data"]["account_specific"] is True
    assert payload["data"]["account_present"] is True
    assert payload["data"]["paper_account_uniqueness_enforced"] is True
    assert payload["data"]["contains_credentials"] is False
    assert payload["data"]["live_trading_enabled"] is False
    assert payload["data"]["exchange_mutation_enabled"] is False
    assert "production_database_repository" in payload["missing_fields"]
    serialized = json.dumps(payload).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token", "credential_ref"):
        assert text not in serialized


def test_v2_trader_context_withholds_unscoped_exchange_accounts(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    store = get_user_store()
    user = store.create_user(
        email="v2.scope@example.com",
        username="v2-scope",
        password="scope-password",
        role="trader",
        trader_id="trader-v2-scope",
        paper_account_id="paper-v2-scope",
    )
    users = store._read()  # noqa: SLF001 - intentional stale-storage regression setup
    for row in users:
        if row["id"] == user["id"]:
            row["exchange_accounts"] = [
                {
                    "id": "binance-other-trader",
                    "trader_id": "trader-other",
                    "paper_account_id": "paper-v2-scope",
                    "exchange": "binance",
                    "label": "Other Trader Binance",
                    "account_type": "usd_m_futures",
                    "mode": "read_only",
                    "read_only": True,
                    "live_trading_enabled": False,
                    "status": "credential_source_pending",
                    "credential_ref": "ALPHAFORGE_OTHER_READONLY",
                },
                {
                    "id": "binance-live-enabled",
                    "trader_id": "trader-v2-scope",
                    "paper_account_id": "paper-v2-scope",
                    "exchange": "binance",
                    "label": "Unsafe Binance",
                    "account_type": "usd_m_futures",
                    "mode": "read_only",
                    "read_only": False,
                    "live_trading_enabled": True,
                    "status": "credential_source_pending",
                    "credential_ref": "ALPHAFORGE_UNSAFE_READONLY",
                },
                {
                    "id": "binance-scoped-readonly",
                    "trader_id": "trader-v2-scope",
                    "paper_account_id": "paper-v2-scope",
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

    login = client.post(
        "/api/auth/login",
        json={"email": "v2.scope@example.com", "password": "scope-password"},
    )
    assert login.status_code == 200
    get_trader_account_repository().upsert_account(
        trader_id="trader-v2-scope",
        paper_account_id="paper-v2-scope",
        equity=1000,
        realized_pnl=0,
        unrealized_pnl=0,
        positions=[],
        orders=[],
        executions=[],
        signals=[],
        source_status="test_v2_trader_context_scope",
    )

    payload = client.get("/api/v2/account/readiness").json()

    _assert_contract(payload, "/api/v2/account/readiness")
    assert [account["id"] for account in payload["trader_context"]["exchange_accounts"]] == ["binance-scoped-readonly"]
    serialized = json.dumps(payload).lower()
    assert "binance-other-trader" not in serialized
    assert "binance-live-enabled" not in serialized
    assert "credential_ref" not in serialized


def test_account_scope_proof_requires_data_scope_to_match_actor() -> None:
    context = {
        "scope": "authenticated_trader",
        "trader_id": "trader-wajidali1984",
        "paper_account_id": "paper-wajidali1984",
    }

    proof = market_contracts._account_scope_context(
        context,
        {
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-other",
            "account_specific": True,
        },
    )

    assert proof["authenticated"] is True
    assert proof["actor_scope_present"] is True
    assert proof["data_account_specific"] is True
    assert proof["data_scope_matches_actor"] is False
    assert proof["scope_verified"] is False
    assert "does not match authenticated trader" in proof["warnings"][0]


def test_trader_context_is_not_account_specific_without_complete_scope() -> None:
    context = market_contracts._trader_context(
        {
            "id": "user-incomplete",
            "username": "incomplete",
            "email": "incomplete@example.com",
            "role": "trader",
            "trader_id": "trader-incomplete",
            "paper_account_id": None,
            "exchange_accounts": [],
        }
    )

    assert context["scope"] == "authenticated_trader"
    assert context["account_specific"] is False
    assert "paper workspace" in context["warnings"][0].lower()


def test_account_scope_matching_fails_closed_on_partial_scope(tmp_path: Path) -> None:
    repository = TraderAccountRepository(path=tmp_path / "trader_accounts.json")
    repository.upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=1000,
    )

    assert repository.get_account(trader_id="trader-wajidali1984", paper_account_id=None) is None
    assert repository.get_account(trader_id=None, paper_account_id="paper-wajidali1984") is None

    actor = {
        "trader_id": "trader-wajidali1984",
        "paper_account_id": "paper-wajidali1984",
    }
    partial_payload = {
        "trader_id": "trader-wajidali1984",
        "paper_account": {"equity": 1000},
    }
    partial_row = {"paper_account_id": "paper-wajidali1984", "symbol": "BTCUSDT"}

    assert market_contracts._payload_matches_actor(partial_payload, actor) is False
    assert market_contracts._row_matches_actor(partial_row, actor) is False


def test_trader_account_repository_integrity_allows_unique_multi_trader_scopes(tmp_path: Path) -> None:
    repository = TraderAccountRepository(path=tmp_path / "trader_accounts.json")
    repository.upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=1000,
    )
    repository.upsert_account(
        trader_id="trader-second",
        paper_account_id="paper-second",
        equity=500,
    )

    integrity = repository.integrity_report()

    assert integrity["status"] == "ok"
    assert integrity["unique_paper_account_scope"] is True
    assert integrity["duplicate_paper_account_ids"] == []
    assert integrity["duplicate_account_scopes"] == []
    assert integrity["contains_credentials"] is False
    assert integrity["live_trading_enabled"] is False
    assert integrity["exchange_mutation_enabled"] is False


def test_static_portfolio_fallback_withholds_unscoped_or_mismatched_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    client = _client(tmp_path, monkeypatch, isolate_redis=True)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    good_scope = {
        "trader_id": "trader-wajidali1984",
        "paper_account_id": "paper-wajidali1984",
    }
    wrong_scope = {
        "trader_id": "trader-other",
        "paper_account_id": "paper-other",
    }
    _write_json(
        tmp_path,
        "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        {
            "generated_utc": "2026-06-14T00:00:00Z",
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-wajidali1984",
            "equity": 1000,
            "realized_pnl_usd": 4,
            "net_unrealized_pnl": -1,
            "positions": [
                {**good_scope, "symbol": "BTCUSDT", "quantity": 0.1},
                {**wrong_scope, "symbol": "ETHUSDT", "quantity": 1},
                {"symbol": "SOLUSDT", "quantity": 5},
            ],
        },
    )

    portfolio = client.get("/api/v2/portfolio").json()
    _assert_contract(portfolio, "/api/v2/portfolio")
    _assert_authenticated_account_scope(portfolio, verified=True)
    assert [row["symbol"] for row in portfolio["data"]["positions"]] == ["BTCUSDT"]
    assert "positions_scope" in portfolio["missing_fields"]

    positions = client.get("/api/v2/account/positions").json()
    _assert_contract(positions, "/api/v2/account/positions")
    _assert_authenticated_account_scope(positions, verified=True)
    assert [row["symbol"] for row in positions["data"]["positions"]] == ["BTCUSDT"]
    assert "positions_scope" in positions["missing_fields"]
    serialized = json.dumps(portfolio) + json.dumps(positions)
    assert "ETHUSDT" not in serialized
    assert "SOLUSDT" not in serialized


def test_local_trader_account_repository_writes_fail_closed_in_production(tmp_path: Path, monkeypatch) -> None:
    store_path = tmp_path / "trader_accounts.json"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    repository = TraderAccountRepository(path=store_path)

    assert repository.list_accounts() == []
    assert not store_path.exists()

    with pytest.raises(HTTPException) as exc:
        repository.upsert_account(
            trader_id="trader-wajidali1984",
            paper_account_id="paper-wajidali1984",
            equity=1000,
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "production_trader_account_repository_required"
    assert not store_path.exists()


def test_sqlalchemy_trader_account_repository_persists_scoped_account(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPHAFORGE_ENV", raising=False)
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_DB_AUTO_CREATE", "true")
    database_path = tmp_path / "trader_accounts.db"
    database_url = f"sqlite:///{database_path}"
    repository = SqlAlchemyTraderAccountRepository(database_url)

    repository.upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=1000,
        source_status="sqlalchemy_repository_test",
    )
    reloaded = SqlAlchemyTraderAccountRepository(database_url)
    account = reloaded.get_account(trader_id="trader-wajidali1984", paper_account_id="paper-wajidali1984")
    readiness = reloaded.readiness_report()

    assert account is not None
    assert account["equity"] == 1000
    assert readiness["repository_kind"] == "sqlalchemy"
    assert readiness["durable_database_repository"] is True
    assert readiness["database_url_configured"] is True
    assert readiness["production_writer_validation"] == "pending"
    assert readiness["live_trading_enabled"] is False
    assert readiness["exchange_mutation_enabled"] is False
    with sqlite3.connect(database_path) as connection:
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(alphaforge_trader_paper_accounts)").fetchall()
        }
    assert "idx_alphaforge_trader_paper_accounts_trader_id" in indexes


def test_get_trader_account_repository_selects_sqlalchemy_backend_in_production(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_REPOSITORY_BACKEND", "sqlalchemy")
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_DATABASE_URL", f"sqlite:///{tmp_path / 'trader_accounts.db'}")
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_DB_AUTO_CREATE", "true")

    repository = get_trader_account_repository()
    account = repository.upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=1000,
        source_status="sqlalchemy_repository_production_test",
    )
    readiness = repository.readiness_report()

    assert isinstance(repository, SqlAlchemyTraderAccountRepository)
    assert account["paper_account_id"] == "paper-wajidali1984"
    assert readiness["repository_kind"] == "sqlalchemy"
    assert readiness["production_repository"] is True
    assert readiness["durable_database_repository"] is True
    assert readiness["migration_status"] == "auto_create_enabled"
    assert readiness["live_trading_enabled"] is False
    assert readiness["exchange_mutation_enabled"] is False


def test_sqlalchemy_trader_account_repository_readiness_is_structured_without_database_url() -> None:
    repository = SqlAlchemyTraderAccountRepository("")
    readiness = repository.readiness_report()
    integrity = repository.integrity_report()

    assert readiness["repository_kind"] == "sqlalchemy"
    assert readiness["status"] == "sqlalchemy_repository_missing_database_url"
    assert readiness["database_url_configured"] is False
    assert readiness["durable_database_repository"] is False
    assert "production_database_repository" in readiness["missing_fields"]
    assert readiness["live_trading_enabled"] is False
    assert readiness["exchange_mutation_enabled"] is False
    assert integrity["repository_kind"] == "sqlalchemy"
    assert integrity["database_url_configured"] is False


def test_local_paper_audit_ledger_writes_fail_closed_in_production(tmp_path: Path, monkeypatch) -> None:
    ledger_path = tmp_path / "paper_audit_ledger.jsonl"
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    monkeypatch.setenv("ALPHAFORGE_PAPER_AUDIT_LEDGER_STORE", str(ledger_path))

    with pytest.raises(HTTPException) as exc:
        append_local_paper_audit_event(
            {
                "audit_id": "paper-audit-production-blocked",
                "audit_event": "paper_order_staged_local",
                "action": "stage",
                "order_id": "paper-order-production-blocked",
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-wajidali1984",
                "mode": "paper",
                "created_at": "2026-06-14T00:00:00Z",
                "exchange_mutation_enabled": False,
                "live_transport_enabled": False,
            }
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "production_paper_audit_ledger_required"
    assert not ledger_path.exists()


def test_local_paper_audit_ledger_records_retention_metadata(tmp_path: Path, monkeypatch) -> None:
    ledger_path = tmp_path / "paper_audit_ledger.jsonl"
    monkeypatch.delenv("ALPHAFORGE_ENV", raising=False)
    monkeypatch.setenv("ALPHAFORGE_PAPER_AUDIT_LEDGER_STORE", str(ledger_path))
    monkeypatch.setenv("ALPHAFORGE_PAPER_AUDIT_RETENTION_DAYS", "180")

    event = append_local_paper_audit_event(
        {
            "audit_id": "paper-audit-retention",
            "audit_event": "paper_order_staged_local",
            "action": "stage",
            "order_id": "paper-order-retention",
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-wajidali1984",
            "mode": "paper",
            "created_at": "2026-06-14T00:00:00Z",
            "exchange_mutation_enabled": False,
            "live_transport_enabled": False,
        }
    )
    metadata = local_paper_audit_ledger_metadata(event_count=1, events=[event])

    assert event["retention_policy_configured"] is True
    assert event["retention_days"] == 180
    assert event["retention_enforced"] is False
    assert event["durable_paper_audit_policy_status"] == "partial_local_retention_metadata"
    assert event["durable_paper_audit_policy_artifact_configured"] is False
    assert event["durable_paper_audit_policy_artifact_valid"] is False
    assert event["durable_paper_audit_policy_artifact_status"] == "pending"
    assert metadata["retention_policy_configured"] is True
    assert metadata["retention_days"] == 180
    assert metadata["retention_enforced"] is False
    assert metadata["durable_paper_audit_policy_status"] == "partial_local_retention_metadata"
    assert "durable_paper_audit_policy" in metadata["missing_fields"]
    assert "durable_paper_audit_policy_artifact" in metadata["missing_fields"]


def test_local_paper_audit_metadata_accepts_durable_policy_artifact_as_partial_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "durable_paper_audit_policy.json"
    artifact.write_text(
        json.dumps(
            {
                "durable_paper_audit_policy_status": "passed",
                "production_durable_store": True,
                "retention_enforced": True,
                "production_writer_hardened": True,
                "audit_verification_passed": True,
                "live_transport_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_DURABLE_PAPER_AUDIT_POLICY_ARTIFACT", str(artifact))

    metadata = local_paper_audit_ledger_metadata(event_count=0, events=[])

    assert metadata["durable_paper_audit_policy_status"] == "artifact_present_pending_current_validation"
    assert metadata["durable_paper_audit_policy_artifact_configured"] is True
    assert metadata["durable_paper_audit_policy_artifact_valid"] is True
    assert metadata["durable_paper_audit_policy_artifact_status"] == "verified"
    assert metadata["durable_paper_audit_policy_artifact_production_durable_store"] is True
    assert metadata["durable_paper_audit_policy_artifact_retention_enforced"] is True
    assert metadata["durable_paper_audit_policy_artifact_writer_hardened"] is True
    assert metadata["durable_paper_audit_policy_artifact_audit_verified"] is True
    assert metadata["production_durable_store"] is False
    assert "durable_paper_audit_policy_artifact" not in metadata["missing_fields"]
    assert "durable_paper_audit_policy_current_validation" in metadata["missing_fields"]
    assert artifact.exists()


def test_paper_repository_blocked_response_is_structured_contract() -> None:
    actor = {
        "trader_id": "trader-wajidali1984",
        "paper_account_id": "paper-wajidali1984",
        "role": "trader",
    }

    payload = market_contracts._paper_repository_blocked_response(
        endpoint="/api/v2/orders/paper",
        actor=actor,
        action="submit",
        symbol="BTCUSDT",
        detail="production_trader_account_repository_required",
    )

    _assert_contract(payload, "/api/v2/orders/paper")
    assert payload["source_type"] == "unavailable"
    assert payload["data"]["accepted"] is False
    assert payload["data"]["reason"] == "paper_repository_unavailable"
    assert payload["data"]["trader_id"] == "trader-wajidali1984"
    assert payload["data"]["paper_account_id"] == "paper-wajidali1984"
    assert "production_trader_account_repository_required" in payload["warnings"]
    assert "production_trader_account_repository" in payload["missing_fields"]
    assert payload["account_scope"]["live_trading_enabled"] is False
    assert payload["account_scope"]["exchange_mutation_enabled"] is False


def _assert_paper_execution_policy(policy: dict) -> None:
    assert policy["status"] == "partial_local_policy"
    assert policy["mode"] == "paper"
    assert policy["requires_authenticated_trader_scope"] is True
    assert policy["local_paper_repository_enabled"] is True
    assert policy["local_paper_staging_enabled"] is True
    assert policy["local_paper_cancel_enabled"] is True
    assert policy["local_manual_fill_enabled"] is True
    assert policy["auto_fill_enabled"] is False
    assert policy["verified_production_paper_submit_cancel"] is False
    assert policy["verified_paper_execution_service"] is False
    assert policy["production_environment"] is False
    assert policy["production_paper_actions_enabled"] is False
    assert policy["production_paper_actions_status"] == "local_repository_only_pending_production_validation"
    assert policy["local_paper_actions_allowed_in_production"] is False
    assert policy["production_requires_verified_paper_execution_service"] is True
    assert policy["product_decision"] == "keep_production_paper_submit_cancel_fill_disabled_until_verified_service"
    assert policy["production_validation_status"] == "pending"
    assert policy["production_paper_fill_writer_status"] == "missing"
    assert policy["production_paper_fill_writer_artifact_configured"] is False
    assert policy["production_paper_fill_writer_artifact_valid"] is False
    assert policy["production_paper_fill_writer_artifact_status"] == "pending"
    assert policy["paper_fill_writer_validated"] is False
    assert policy["paper_only_fill_writer"] is False
    assert policy["durable_repository_enabled"] is False
    assert policy["live_transport_enabled"] is False
    assert policy["exchange_mutation_enabled"] is False
    assert policy["real_order_submission_enabled"] is False
    assert policy["real_order_cancel_enabled"] is False
    assert policy["position_risk_mutation_enabled"] is False
    assert policy["collateral_mode_mutation_enabled"] is False
    assert policy["live_gate_mutation_enabled"] is False
    assert policy["contains_exchange_credentials"] is False
    assert "production_paper_submit_cancel_validation" in policy["missing_fields"]
    assert "production_paper_fill_writer" in policy["missing_fields"]
    assert "production_paper_fill_writer_artifact" in policy["missing_fields"]
    assert "production_paper_fill_writer_current_validation" in policy["missing_fields"]
    assert "verified_paper_execution_service" in policy["missing_fields"]
    assert "durable_paper_audit_policy" in policy["missing_fields"]


def test_production_paper_actions_fail_closed_until_verified_service(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "Test-password-123!")
    _configure_auth_for_later_production(tmp_path, monkeypatch)
    _write_json(
        tmp_path,
        "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
        {"symbol": "BTCUSDT", "generated_at": "2026-06-13T03:00:00Z", "last_price": 100000},
    )
    client = _client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "Test-password-123!"},
    )
    assert login.status_code == 200
    get_trader_account_repository().upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=250000,
        realized_pnl=0,
        unrealized_pnl=0,
        positions=[],
        orders=[],
        executions=[],
        signals=[],
        source_status="test_paper_repository",
    )

    monkeypatch.setenv("ALPHAFORGE_ENV", "production")
    preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "mode": "paper",
        },
    ).json()
    _assert_contract(preview, "/api/v2/orders/preview")
    assert preview["data"]["allowed"] is False
    assert preview["data"]["reason"] == "production_paper_actions_disabled"
    assert preview["data"]["estimated_notional"] == 10000
    policy = preview["data"]["paper_execution_policy"]
    assert policy["production_environment"] is True
    assert policy["production_paper_actions_enabled"] is False
    assert policy["production_paper_actions_status"] == "disabled_pending_verified_paper_execution_service"
    assert policy["local_paper_actions_allowed_in_production"] is False
    assert "production_paper_submit_cancel_validation" in preview["missing_fields"]
    assert "production_paper_fill_writer" in preview["missing_fields"]
    assert "verified_paper_execution_service" in preview["missing_fields"]

    submitted = client.post(
        "/api/v2/orders/paper",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "mode": "paper",
        },
    ).json()
    _assert_contract(submitted, "/api/v2/orders/paper")
    assert submitted["data"]["accepted"] is False
    assert submitted["data"]["reason"] == "production_paper_actions_disabled"
    assert submitted["data"]["order"] is None
    assert "production_paper_submit_cancel_validation" in submitted["missing_fields"]
    assert "production_paper_fill_writer" in submitted["missing_fields"]
    assert submitted["account_scope"]["live_trading_enabled"] is False
    assert submitted["account_scope"]["exchange_mutation_enabled"] is False


def test_paper_execution_policy_reports_production_fill_writer_artifact(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "Test-password-123!")
    _configure_auth_for_later_production(tmp_path, monkeypatch)
    artifact = tmp_path / "production_paper_fill_writer.json"
    artifact.write_text(
        json.dumps(
            {
                "production_paper_fill_writer_status": "verified",
                "paper_fill_writer_validated": True,
                "paper_only_fill_writer": True,
                "trader_scope_enforced": True,
                "paper_account_scope_enforced": True,
                "backend_owned_order_ids": True,
                "idempotency_enforced": True,
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
    monkeypatch.setenv("ALPHAFORGE_PRODUCTION_PAPER_FILL_WRITER_ARTIFACT", str(artifact))
    _write_json(
        tmp_path,
        "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
        {"symbol": "BTCUSDT", "generated_at": "2026-06-13T03:00:00Z", "last_price": 100000},
    )
    client = _client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "Test-password-123!"},
    )
    assert login.status_code == 200
    get_trader_account_repository().upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=250000,
        realized_pnl=0,
        unrealized_pnl=0,
        positions=[],
        orders=[],
        executions=[],
        signals=[],
        source_status="test_paper_repository",
    )
    monkeypatch.setenv("ALPHAFORGE_ENV", "production")

    preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "mode": "paper",
        },
    ).json()

    _assert_contract(preview, "/api/v2/orders/preview")
    policy = preview["data"]["paper_execution_policy"]
    assert policy["production_paper_fill_writer_status"] == "artifact_present_pending_current_validation"
    assert policy["production_paper_fill_writer_artifact_configured"] is True
    assert policy["production_paper_fill_writer_artifact_valid"] is True
    assert policy["production_paper_fill_writer_artifact_status"] == "verified"
    assert policy["paper_fill_writer_validated"] is True
    assert policy["paper_only_fill_writer"] is True
    assert policy["paper_fill_writer_trader_scope_enforced"] is True
    assert policy["paper_fill_writer_paper_account_scope_enforced"] is True
    assert policy["paper_fill_writer_idempotency_enforced"] is True
    assert "production_paper_fill_writer_artifact" not in policy["missing_fields"]
    assert "production_paper_fill_writer_current_validation" in policy["missing_fields"]
    assert policy["production_paper_actions_enabled"] is False
    assert policy["live_transport_enabled"] is False
    assert policy["exchange_mutation_enabled"] is False
    serialized = json.dumps(policy).lower()
    for text in ("api_key", "api_secret", "access_token", "live_order"):
        assert text not in serialized

    filled = client.post(
        "/api/v2/orders/paper/paper-test-order/fill",
        json={"price": 100000, "reason": "test production block"},
    ).json()
    _assert_contract(filled, "/api/v2/orders/paper/paper-test-order/fill")
    assert filled["data"]["accepted"] is False
    assert filled["data"]["reason"] == "production_paper_actions_disabled"
    assert filled["data"]["execution"] is None

    canceled = client.post("/api/v2/orders/paper/paper-test-order/cancel").json()
    _assert_contract(canceled, "/api/v2/orders/paper/paper-test-order/cancel")
    assert canceled["data"]["accepted"] is False
    assert canceled["data"]["reason"] == "production_paper_actions_disabled"


def test_market_contracts_return_structured_unavailable_states(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, isolate_redis=True)

    endpoints = [
        "/api/v2/market/overview",
        "/api/v2/market/BTCUSDT",
        "/api/v2/market/BTCUSDT/candles",
        "/api/v2/market/BTCUSDT/indicators",
        "/api/v2/market/BTCUSDT/depth",
        "/api/v2/market/BTCUSDT/trades",
        "/api/v2/market/BTCUSDT/derivatives",
        "/api/v2/account/positions",
        "/api/v2/execution/audit-events",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == 200
        payload = response.json()
        _assert_contract(payload, endpoint)
        assert payload["source_type"] == "unavailable"
        assert payload["stale"] is True
        assert payload["missing_fields"]


def test_market_contracts_reject_malformed_symbols_and_timeframes(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    for endpoint, expected_contract_endpoint in [
        ("/api/v2/market/btcusdt..", "/api/v2/market/{symbol}"),
        ("/api/v2/market/btcusdt../ticker", "/api/v2/market/{symbol}/ticker"),
        ("/api/v2/market/btcusdt../derivatives", "/api/v2/market/{symbol}/derivatives"),
        ("/api/v2/market/btcusdt../candles", "/api/v2/market/{symbol}/candles"),
        ("/api/v2/market/btcusdt../indicators", "/api/v2/market/{symbol}/indicators"),
        ("/api/v2/market/btcusdt../depth", "/api/v2/market/{symbol}/depth"),
        ("/api/v2/market/btcusdt../trades", "/api/v2/market/{symbol}/trades"),
    ]:
        payload = client.get(endpoint).json()
        _assert_contract(payload, expected_contract_endpoint)
        assert payload["source_type"] == "unavailable"
        assert payload["symbol"] is None
        assert "symbol" in payload["missing_fields"]
        assert "Enter a valid market symbol" in payload["warnings"]

    invalid_timeframe = client.get("/api/v2/market/BTCUSDT/candles?timeframe=2m").json()
    _assert_contract(invalid_timeframe, "/api/v2/market/BTCUSDT/candles")
    assert invalid_timeframe["source_type"] == "unavailable"
    assert invalid_timeframe["symbol"] == "BTCUSDT"
    assert "timeframe" in invalid_timeframe["missing_fields"]
    assert "Select a supported chart timeframe" in invalid_timeframe["warnings"]

    invalid_indicator_timeframe = client.get("/api/v2/market/BTCUSDT/indicators?timeframe=2m").json()
    _assert_contract(invalid_indicator_timeframe, "/api/v2/market/BTCUSDT/indicators")
    assert invalid_indicator_timeframe["source_type"] == "unavailable"
    assert invalid_indicator_timeframe["symbol"] == "BTCUSDT"
    assert "timeframe" in invalid_indicator_timeframe["missing_fields"]
    assert "Select a supported chart timeframe" in invalid_indicator_timeframe["warnings"]


def test_backend_native_stream_matcher_rejects_unknown_channels() -> None:
    assert market_contracts._native_stream_matches_request("btcusdt@ticker", "BTCUSDT", "1m") is True
    assert market_contracts._native_stream_matches_request("@ticker", "BTCUSDT", "1m") is False
    assert market_contracts._native_stream_matches_request("btcusdt@unknown", "BTCUSDT", "1m") is False
    assert market_contracts._native_stream_matches_request("ethusdt@ticker", "BTCUSDT", "1m") is False
    assert market_contracts._native_stream_matches_request("btcusdt@kline_1m@trade", "BTCUSDT", "1m") is False


def test_market_stream_status_returns_public_safe_alert_contract(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/api/v2/market/BTCUSDT/stream-status")

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload, "/api/v2/market/BTCUSDT/stream-status")
    assert payload["data"]["symbol"] == "BTCUSDT"
    assert payload["data"]["production_alerting_integrated"] is False
    assert payload["data"]["production_alerting_status"] == "missing"
    assert payload["data"]["production_alerting_artifact_configured"] is False
    assert payload["data"]["production_alerting_artifact_valid"] is False
    assert payload["data"]["production_alerting_artifact_status"] == "pending"
    assert payload["data"]["production_validation_integrated"] is False
    assert payload["data"]["production_validation_status"] == "missing"
    assert payload["data"]["production_validation_artifact_configured"] is False
    assert payload["data"]["production_validation_artifact_valid"] is False
    assert payload["data"]["production_validation_artifact_status"] == "pending"
    assert payload["data"]["alert"]["status"] == "active"
    assert payload["data"]["alert"]["severity"] == "warning"
    assert "production_alerting" in payload["missing_fields"]
    assert "production_stream_validation" in payload["missing_fields"]
    assert "production_stream_current_validation" in payload["missing_fields"]
    assert "last_frame_at" in payload["missing_fields"]
    serialized = json.dumps(payload).lower()
    for forbidden in ("api_key", "api_secret", "password_hash", "signed account", "exchange secret"):
        assert forbidden not in serialized

    invalid_symbol = client.get("/api/v2/market/btcusdt../stream-status").json()
    _assert_contract(invalid_symbol, "/api/v2/market/{symbol}/stream-status")
    assert invalid_symbol["source_type"] == "unavailable"
    assert invalid_symbol["symbol"] is None
    assert "symbol" in invalid_symbol["missing_fields"]
    assert "Enter a valid market symbol" in invalid_symbol["warnings"]


def test_market_stream_status_accepts_production_alerting_artifact_as_partial_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "production_stream_alerting.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "passed",
                "production_alerting_integrated": True,
                "dashboard_integrated": True,
                "stale_alerts_enabled": True,
                "reconnect_alerts_enabled": True,
                "lag_monitoring_enabled": True,
                "missing_source_alerts_enabled": True,
                "public_market_data_only": True,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_PRODUCTION_ALERTING_ARTIFACT", str(artifact))
    client = _client(tmp_path, monkeypatch)

    payload = client.get("/api/v2/market/BTCUSDT/stream-status").json()

    _assert_contract(payload, "/api/v2/market/BTCUSDT/stream-status")
    assert payload["data"]["production_alerting_integrated"] is True
    assert payload["data"]["production_alerting_status"] == "artifact_present_pending_current_validation"
    assert payload["data"]["production_alerting_artifact_configured"] is True
    assert payload["data"]["production_alerting_artifact_valid"] is True
    assert payload["data"]["production_alerting_artifact_status"] == "verified"
    assert payload["data"]["production_alerting_evidence"]["dashboard_integrated"] is True
    assert "production_alerting" not in payload["missing_fields"]
    assert "production_stream_validation" in payload["missing_fields"]
    assert "production_stream_current_validation" in payload["missing_fields"]
    assert payload["mode"] == "read_only"
    serialized = json.dumps(payload).lower()
    for forbidden in ("api_key", "api_secret", "password_hash", "signed account", "exchange secret"):
        assert forbidden not in serialized


def test_market_stream_status_accepts_production_validation_artifact_as_partial_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "production_stream_validation.json"
    artifact.write_text(
        json.dumps(
            {
                "status": "passed",
                "public_stream_connected": True,
                "native_stream_validated": True,
                "symbol_timeframe_filter_verified": True,
                "freshness_enforced": True,
                "stale_detection_verified": True,
                "telemetry_persisted": True,
                "fallback_labeling_verified": True,
                "no_static_presented_as_live": True,
                "public_market_data_only": True,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_MARKET_STREAM_PRODUCTION_VALIDATION_ARTIFACT", str(artifact))
    client = _client(tmp_path, monkeypatch)

    payload = client.get("/api/v2/market/BTCUSDT/stream-status").json()

    _assert_contract(payload, "/api/v2/market/BTCUSDT/stream-status")
    assert payload["data"]["production_validation_integrated"] is True
    assert payload["data"]["production_validation_status"] == "artifact_present_pending_current_validation"
    assert payload["data"]["production_validation_artifact_configured"] is True
    assert payload["data"]["production_validation_artifact_valid"] is True
    assert payload["data"]["production_validation_artifact_status"] == "verified"
    assert payload["data"]["production_validation_evidence"]["public_stream_connected"] is True
    assert payload["data"]["production_validation_evidence"]["telemetry_persisted"] is True
    assert "production_stream_validation" not in payload["missing_fields"]
    assert "production_stream_current_validation" in payload["missing_fields"]
    assert payload["mode"] == "read_only"
    serialized = json.dumps(payload).lower()
    for forbidden in ("api_key", "api_secret", "password_hash", "signed account", "exchange secret"):
        assert forbidden not in serialized


def test_static_market_payloads_are_labeled_as_fallback_not_live(tmp_path: Path, monkeypatch) -> None:
    _write_json(
        tmp_path,
        "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
        {
            "symbol": "BTCUSDT",
            "generated_at": "2026-06-13T03:00:00Z",
            "last_price": 104000.25,
            "quote_volume_24h": 987654321.5,
            "funding_rate": 0.0001,
            "open_interest": 123456.7,
            "open_interest_change_pct": 0.018,
            "bid": 104000.0,
            "ask": 104000.5,
            "spread_bps": 0.048,
            "book_bid_5": 21.5,
            "book_ask_5": 18.25,
        },
    )
    _write_json(
        tmp_path,
        "operator_runtime/v2_professional_market_chart/latest/operator_dashboard_payload.json",
        {
            "generated_at": "2026-06-13T03:00:00Z",
            "symbols": ["BTCUSDT", "BTC/USDT", "ethusdt.."],
            "timeframes": ["1m", "5m"],
        },
    )
    _write_json(
        tmp_path,
        "operator_runtime/v2_professional_market_chart/latest/BTCUSDT_1m_chart.json",
        {
            "generated_at": "2026-06-13T03:00:00Z",
            "candles": [
                {"time": 1781323200, "open": 103900, "high": 104050, "low": 103800, "close": 104000, "volume": 12.3}
            ],
        },
    )

    client = _client(tmp_path, monkeypatch)
    for endpoint in [
        "/api/v2/market/overview",
        "/api/v2/market/BTCUSDT",
        "/api/v2/market/BTCUSDT/ticker",
        "/api/v2/market/BTCUSDT/candles",
        "/api/v2/market/BTCUSDT/depth",
        "/api/v2/market/BTCUSDT/derivatives",
    ]:
        payload = client.get(endpoint).json()
        _assert_contract(payload, endpoint)
        assert payload["source_type"] == "static_payload"
        assert payload["mode"] == "read_only"
        assert any("Static" in warning or "fallback" in warning for warning in payload["warnings"])
        if endpoint == "/api/v2/market/overview":
            assert payload["data"]["symbols"] == ["BTCUSDT"]


def test_market_overview_filters_malformed_public_inventory_symbols(tmp_path: Path, monkeypatch) -> None:
    def fake_public_json(path: str, params: dict):
        assert path == "/fapi/v1/ticker/24hr"
        return (
            [
                {"symbol": "BTCUSDT", "lastPrice": "100000", "priceChangePercent": "1.5", "highPrice": "101000", "lowPrice": "99000", "volume": "123", "quoteVolume": "12300000", "count": 42, "weightedAvgPrice": "100010"},
                {"symbol": "ETHUSDT", "lastPrice": "5000", "priceChangePercent": "-2.25", "highPrice": "5200", "lowPrice": "4800", "volume": "456", "quoteVolume": "2280000", "count": 84, "weightedAvgPrice": "5005"},
                {"symbol": "BTC/USDT"},
                {"symbol": "solusdt.."},
                {"symbol": "DOGEUSD"},
            ],
            "binance-public-ticker-inventory",
            None,
        )

    monkeypatch.setattr(market_contracts, "_binance_public_json", fake_public_json)
    client = _client(tmp_path, monkeypatch)

    payload = client.get("/api/v2/market/overview").json()

    _assert_contract(payload, "/api/v2/market/overview")
    assert payload["source_type"] == "api"
    assert payload["data"]["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert payload["data"]["count"] == 2
    assert payload["data"]["tickers"][0]["symbol"] == "BTCUSDT"
    assert payload["data"]["tickers"][0]["last_price"] == 100000
    assert payload["data"]["tickers"][0]["change_24h"] == 0.015
    assert payload["data"]["tickers"][0]["turnover_24h"] == 12300000
    assert payload["data"]["tickers"][1]["symbol"] == "ETHUSDT"


def test_market_indicators_derive_from_public_closed_klines_for_prochart(tmp_path: Path, monkeypatch) -> None:
    base_open_ms = 1781323200000
    minute_ms = 60_000
    klines = [
        [
            base_open_ms + (index * minute_ms),
            str(100000 + index),
            str(100100 + index),
            str(99900 + index),
            str(100050 + index),
            "10.0",
            base_open_ms + ((index + 1) * minute_ms) - 1,
            "1000000",
            100 + index,
            "5.0",
            "500000",
        ]
        for index in range(60)
    ]

    def fake_public_json(path: str, params: dict):
        assert path == "/fapi/v1/klines"
        assert params["symbol"] == "BTCUSDT"
        assert params["interval"] == "1m"
        return (klines, "binance-public-klines", None)

    monkeypatch.setattr(market_contracts, "_binance_public_json", fake_public_json)
    client = _client(tmp_path, monkeypatch)

    payload = client.get("/api/v2/market/BTCUSDT/indicators").json()

    _assert_contract(payload, "/api/v2/market/BTCUSDT/indicators")
    assert payload["source_type"] == "api"
    assert payload["source"] == "binance-public-klines"
    assert payload["data"]["symbol"] == "BTCUSDT"
    assert payload["data"]["timeframe"] == "1m"
    assert payload["data"]["controls_enabled"] is True
    assert payload["data"]["indicator_count"] > 0
    assert payload["data"]["ema20"]
    assert payload["data"]["ema50"]
    assert payload["data"]["bb_upper"]
    assert payload["data"]["bb_lower"]
    assert payload["data"]["bb_middle"]
    assert payload["data"]["ai_target"] == []
    assert "ai_target" in payload["missing_fields"]
    assert "typed_realtime_indicator_repository" not in payload["missing_fields"]
    assert any("closed klines" in warning for warning in payload["warnings"])
    serialized = json.dumps(payload).lower()
    assert "api_key" not in serialized
    assert "api_secret" not in serialized


def test_derivatives_contract_uses_public_funding_oi_and_long_short_sources(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPHAFORGE_DERIVATIVES_REALTIME_SOURCE_ARTIFACT", raising=False)

    def fake_public_json(path: str, params: dict):
        assert params.get("symbol") == "BTCUSDT"
        if path == "/fapi/v1/ticker/24hr":
            return (
                {
                    "symbol": "BTCUSDT",
                    "lastPrice": "100000",
                    "priceChangePercent": "1.5",
                    "highPrice": "101000",
                    "lowPrice": "99000",
                    "volume": "1234",
                    "quoteVolume": "123400000",
                },
                "binance-public-ticker",
                None,
            )
        if path == "/fapi/v1/premiumIndex":
            return (
                {
                    "symbol": "BTCUSDT",
                    "markPrice": "100100",
                    "indexPrice": "100000",
                    "lastFundingRate": "0.0001",
                    "nextFundingTime": 1781326800000,
                },
                "binance-public-premium",
                None,
            )
        if path == "/fapi/v1/openInterest":
            return ({"symbol": "BTCUSDT", "openInterest": "23456"}, "binance-public-oi", None)
        if path == "/fapi/v1/fundingRate":
            return (
                [{"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingTime": 1781323200000}],
                "binance-public-funding-history",
                None,
            )
        if path == "/futures/data/openInterestHist":
            return (
                [{"symbol": "BTCUSDT", "sumOpenInterest": "23456", "sumOpenInterestValue": "2345600000", "timestamp": 1781323200000}],
                "binance-public-oi-history",
                None,
            )
        if path == "/futures/data/globalLongShortAccountRatio":
            return (
                [{"symbol": "BTCUSDT", "longShortRatio": "1.25", "timestamp": 1781323200000}],
                "binance-public-long-short",
                None,
            )
        return (None, "unavailable", "unexpected public endpoint")

    monkeypatch.setattr(market_contracts, "_binance_public_json", fake_public_json)
    client = _client(tmp_path, monkeypatch)

    payload = client.get("/api/v2/market/BTCUSDT/derivatives").json()

    _assert_contract(payload, "/api/v2/market/BTCUSDT/derivatives")
    assert payload["source_type"] == "api"
    assert payload["data"]["funding_history"]
    assert payload["data"]["open_interest_history"]
    assert payload["data"]["long_short_ratio"] == 1.25
    assert payload["data"]["basis"] == 0.001
    assert payload["data"]["liquidation_stream_status"]["live_trading_enabled"] is False
    assert payload["data"]["liquidation_stream_status"]["exchange_mutation_enabled"] is False
    assert "source" in payload["data"]["liquidation_stream_status"]
    assert payload["data"]["production_source_validation"]["valid"] is False
    assert payload["data"]["production_source_validation"]["live_trading_enabled"] is False
    assert payload["data"]["production_source_validation"]["exchange_mutation_enabled"] is False
    assert "liquidations_1h" in payload["missing_fields"]
    assert "production_derivatives_realtime_source_validation" in payload["missing_fields"]
    serialized = json.dumps(payload).lower()
    assert "live account" not in serialized
    assert "api_key" not in serialized

    artifact = tmp_path / "derivatives_realtime_source.json"
    artifact.write_text(
        json.dumps(
            {
                "derivatives_realtime_source_status": "passed",
                "funding_realtime_verified": True,
                "open_interest_realtime_verified": True,
                "liquidation_source_verified": True,
                "long_short_source_verified": True,
                "basis_source_verified": True,
                "exchange_comparison_verified": True,
                "freshness_enforced": True,
                "stale_marking_verified": True,
                "source_labels_verified": True,
                "no_static_presented_as_live": True,
                "fake_live_data_detected": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "live_submit_available": False,
                "live_cancel_available": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ALPHAFORGE_DERIVATIVES_REALTIME_SOURCE_ARTIFACT", str(artifact))
    verified_payload = client.get("/api/v2/market/BTCUSDT/derivatives").json()

    _assert_contract(verified_payload, "/api/v2/market/BTCUSDT/derivatives")
    validation = verified_payload["data"]["production_source_validation"]
    assert validation["valid"] is True
    assert validation["status"] == "verified"
    assert validation["live_trading_enabled"] is False
    assert validation["exchange_mutation_enabled"] is False
    assert "production_derivatives_realtime_source_validation" not in verified_payload["missing_fields"]
    verified_serialized = json.dumps(verified_payload).lower()
    for text in ("api_key", "api_secret", "password_hash", "access_token"):
        assert text not in verified_serialized


def test_order_preview_is_preview_only_and_rejects_live_mode(tmp_path: Path, monkeypatch) -> None:
    _write_json(
        tmp_path,
        "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
        {"symbol": "BTCUSDT", "generated_at": "2026-06-13T03:00:00Z", "last_price": 100000},
    )
    _write_json(
        tmp_path,
        "operator_runtime/paper_online/latest/paper_runtime_status.json",
        {"generated_at": "2026-06-13T03:00:00Z", "paper_account": {"equity": 50000}},
    )

    client = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "market",
            "quantity": 0.1,
            "mode": "live",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    _assert_contract(payload, "/api/v2/orders/preview")
    assert payload["data"]["allowed"] is False
    assert payload["data"]["mode"] == "live_blocked"
    assert payload["data"]["reason"] == "live_mode_rejected"
    _assert_paper_execution_policy(payload["data"]["paper_execution_policy"])
    assert "mutate" not in json.dumps(payload).lower()


def test_market_data_websocket_emits_read_only_contract_snapshot(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    with client.websocket_connect("/ws/market-data?symbol=BTCUSDT&interval_ms=1000") as websocket:
        payload = websocket.receive_json()

    assert payload["type"] == "market_snapshot"
    assert payload["endpoint"] == "/ws/market-data"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["mode"] == "read_only"
    assert payload["source_type"] == "api"
    assert payload["ticker"]["mode"] == "read_only"
    assert payload["depth"]["mode"] == "read_only"
    assert payload["trades"]["mode"] == "read_only"
    assert "live_blocked" not in json.dumps(payload)


def test_market_data_websocket_rejects_invalid_symbol_and_timeframe(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    with client.websocket_connect("/ws/market-data?symbol=btcusdt..&timeframe=1m") as websocket:
        payload = websocket.receive_json()
    assert payload["type"] == "market_snapshot"
    assert payload["source_type"] == "unavailable"
    assert payload["symbol"] is None
    assert "symbol" in payload["missing_fields"]
    assert "Enter a valid market symbol" in payload["warnings"]

    with client.websocket_connect("/ws/market-data?symbol=BTCUSDT&timeframe=2m") as websocket:
        invalid_timeframe = websocket.receive_json()
    assert invalid_timeframe["type"] == "market_snapshot"
    assert invalid_timeframe["source_type"] == "unavailable"
    assert invalid_timeframe["symbol"] is None
    assert "timeframe" in invalid_timeframe["missing_fields"]
    assert "Select a supported chart timeframe" in invalid_timeframe["warnings"]


def test_portfolio_contract_uses_paper_mode_without_live_account_claim(tmp_path: Path, monkeypatch) -> None:
    _write_json(
        tmp_path,
        "operator_runtime/paper_online/latest/paper_runtime_status.json",
        {"generated_at": "2026-06-13T03:00:00Z", "paper_account": {"equity": 50000, "realized_pnl": 12}},
    )
    client = _client(tmp_path, monkeypatch)

    payload = client.get("/api/v2/portfolio").json()

    _assert_contract(payload, "/api/v2/portfolio")
    assert payload["mode"] == "paper"
    assert payload["source_type"] == "static_payload"
    assert "live account" not in json.dumps(payload).lower()


def test_authenticated_trader_receives_global_paper_runtime_projection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    _write_json(
        tmp_path,
        "operator_runtime/paper_online/latest/paper_runtime_status.json",
        {"generated_at": "2026-06-13T03:00:00Z", "paper_account": {"equity": 50000, "realized_pnl": 12}},
    )
    _write_json(
        tmp_path,
        "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        {
            "generated_at": "2026-06-13T03:00:00Z",
            "equity": 50000,
            "positions": [{"symbol": "BTCUSDT", "quantity": 1}],
        },
    )
    client = _client(tmp_path, monkeypatch, isolate_redis=True)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    portfolio = client.get("/api/v2/portfolio").json()
    _assert_contract(portfolio, "/api/v2/portfolio")
    _assert_authenticated_account_scope(portfolio, verified=True)
    assert portfolio["data"]["account_scope"] == "authenticated_trader"
    assert portfolio["source_type"] == "static_payload"
    assert portfolio["data"]["account_specific"] is True
    assert portfolio["data"]["equity"] == 50000
    assert portfolio["data"]["positions"][0]["symbol"] == "BTCUSDT"
    assert portfolio["data"]["positions"][0]["trader_id"] == "trader-wajidali1984"
    assert portfolio["data"]["positions"][0]["paper_account_id"] == "paper-wajidali1984"
    assert "equity" not in portfolio["missing_fields"]

    preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "market",
            "quantity": 0.1,
            "mode": "paper",
        },
    ).json()
    _assert_contract(preview, "/api/v2/orders/preview")
    assert preview["data"]["allowed"] is False
    assert preview["data"]["available_paper_balance"] is None
    assert preview["data"]["reason"] == "paper_balance_unavailable"
    _assert_paper_execution_policy(preview["data"]["paper_execution_policy"])


def test_authenticated_trader_receives_paper_runtime_signal_projection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    _write_json(
        tmp_path,
        "operator_runtime/v2_signals/latest/signals_payload.json",
        {
            "generated_at": "2026-06-13T03:00:00Z",
            "cuda_prediction_contract": {
                "prediction_rows": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "5m",
                        "selected_action": "short",
                        "confidence_calibrated": 0.7,
                        "price_target": 99600,
                        "price_target_after_cost": 99500,
                        "last_price": 100000,
                        "signal_id": "runtime-signal-btc",
                        "prediction_id": "runtime-prediction-btc",
                        "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
                        "model_version": "paper-runtime-test",
                        "feature_snapshot_id": "feature-snapshot-test",
                        "market_state_id": "market-state-test",
                    }
                ]
            },
        },
    )
    client = _client(tmp_path, monkeypatch, isolate_redis=True)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    signals = client.get("/api/v2/signals?symbol=BTCUSDT").json()

    _assert_contract(signals, "/api/v2/signals?symbol=BTCUSDT")
    _assert_authenticated_account_scope(signals, verified=True)
    assert signals["source_type"] == "static_payload"
    assert signals["data"]["active_signal"]["signal_id"] == "runtime-signal-btc"
    assert signals["data"]["active_signal"]["prediction_id"] == "runtime-prediction-btc"
    assert signals["data"]["active_signal"]["direction"] == "SHORT"
    assert signals["data"]["active_signal"]["confidence"] == 0.7
    assert signals["data"]["active_signal"]["target_1"] == 99500
    assert signals["data"]["active_signal"]["exchange_action_taken"] is False
    assert signals["data"]["active_signal"]["exchange_call_invariant"] == "LIVE_TRADING_BLOCKED"

    eth_signals = client.get("/api/v2/signals?symbol=ETHUSDT").json()
    _assert_contract(eth_signals, "/api/v2/signals?symbol=ETHUSDT")
    _assert_authenticated_account_scope(eth_signals, verified=True)
    assert eth_signals["data"]["active_signal"] is None
    assert "active_signal" in eth_signals["missing_fields"]


def test_authenticated_trader_does_not_receive_partially_matched_fallback_account_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    _write_json(
        tmp_path,
        "operator_runtime/paper_online/latest/paper_runtime_status.json",
        {
            "generated_at": "2026-06-13T03:00:00Z",
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-other",
            "paper_account": {
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-other",
                "equity": 50000,
                "realized_pnl": 12,
            },
        },
    )
    _write_json(
        tmp_path,
        "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        {
            "generated_at": "2026-06-13T03:00:00Z",
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-other",
            "equity": 50000,
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "quantity": 1,
                    "trader_id": "trader-wajidali1984",
                    "paper_account_id": "paper-other",
                }
            ],
        },
    )
    client = _client(tmp_path, monkeypatch, isolate_redis=True)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    portfolio = client.get("/api/v2/portfolio").json()
    _assert_contract(portfolio, "/api/v2/portfolio")
    _assert_authenticated_account_scope(portfolio, verified=True)
    assert portfolio["data"]["account_scope"] == "authenticated_trader"
    assert portfolio["source_type"] == "repository"
    assert portfolio["data"]["equity"] is None
    assert portfolio["data"]["positions"] == []
    assert "equity" in portfolio["missing_fields"]


def test_repository_contracts_filter_mixed_scope_rows_for_authenticated_trader(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    client = _client(tmp_path, monkeypatch, isolate_redis=True)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200

    good_scope = {
        "trader_id": "trader-wajidali1984",
        "paper_account_id": "paper-wajidali1984",
    }
    wrong_scope = {
        "trader_id": "trader-other",
        "paper_account_id": "paper-other",
    }
    repository = get_trader_account_repository()
    repository.upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=250000,
        realized_pnl=0,
        unrealized_pnl=0,
        positions=[
            {**good_scope, "symbol": "BTCUSDT", "side": "Long", "quantity": 0.1},
            {**wrong_scope, "symbol": "ETHUSDT", "side": "Short", "quantity": 1},
            {"symbol": "SOLUSDT", "side": "Long", "quantity": 5},
        ],
        orders=[
            {**good_scope, "order_id": "paper-good-order", "symbol": "BTCUSDT", "status": "open"},
            {**wrong_scope, "order_id": "paper-other-order", "symbol": "ETHUSDT", "status": "open"},
            {"order_id": "paper-unscoped-order", "symbol": "SOLUSDT", "status": "open"},
        ],
        executions=[
            {**good_scope, "execution_id": "exec-good", "order_id": "paper-good-order", "symbol": "BTCUSDT"},
            {**wrong_scope, "execution_id": "exec-other", "order_id": "paper-other-order", "symbol": "ETHUSDT"},
            {"execution_id": "exec-unscoped", "order_id": "paper-unscoped-order", "symbol": "SOLUSDT"},
        ],
        signals=[
            {**good_scope, "signal_id": "signal-good", "symbol": "BTCUSDT", "direction": "Long"},
            {**wrong_scope, "signal_id": "signal-other", "symbol": "ETHUSDT", "direction": "Short"},
            {"signal_id": "signal-unscoped", "symbol": "SOLUSDT", "direction": "Long"},
        ],
        source_status="mixed_scope_rows_test",
    )

    portfolio = client.get("/api/v2/portfolio").json()
    _assert_contract(portfolio, "/api/v2/portfolio")
    _assert_authenticated_account_scope(portfolio, verified=True)
    assert [row["symbol"] for row in portfolio["data"]["positions"]] == ["BTCUSDT"]
    assert "positions_scope" in portfolio["missing_fields"]

    positions = client.get("/api/v2/account/positions").json()
    _assert_contract(positions, "/api/v2/account/positions")
    _assert_authenticated_account_scope(positions, verified=True)
    assert [row["symbol"] for row in positions["data"]["positions"]] == ["BTCUSDT"]
    assert "positions_scope" in positions["missing_fields"]

    orders = client.get("/api/v2/execution/orders").json()
    _assert_contract(orders, "/api/v2/execution/orders")
    _assert_authenticated_account_scope(orders, verified=True)
    assert [row["order_id"] for row in orders["data"]["orders"]] == ["paper-good-order"]
    assert "orders_scope" in orders["missing_fields"]

    executions = client.get("/api/v2/execution/executions").json()
    _assert_contract(executions, "/api/v2/execution/executions")
    _assert_authenticated_account_scope(executions, verified=True)
    assert [row["execution_id"] for row in executions["data"]["executions"]] == ["exec-good"]
    assert "executions_scope" in executions["missing_fields"]

    signals = client.get("/api/v2/signals").json()
    _assert_contract(signals, "/api/v2/signals")
    _assert_authenticated_account_scope(signals, verified=True)
    assert signals["data"]["active_signal"]["signal_id"] == "signal-good"
    assert "signals_scope" in signals["missing_fields"]

    btc_signals = client.get("/api/v2/signals?symbol=BTCUSDT").json()
    _assert_contract(btc_signals, "/api/v2/signals?symbol=BTCUSDT")
    _assert_authenticated_account_scope(btc_signals, verified=True)
    assert btc_signals["data"]["active_signal"]["signal_id"] == "signal-good"

    eth_signals = client.get("/api/v2/signals?symbol=ETHUSDT").json()
    _assert_contract(eth_signals, "/api/v2/signals?symbol=ETHUSDT")
    assert eth_signals["account_scope"]["scope"] == "authenticated_trader"
    assert eth_signals["account_scope"]["live_trading_enabled"] is False
    assert eth_signals["account_scope"]["exchange_mutation_enabled"] is False
    assert eth_signals["data"]["active_signal"] is None
    assert "active_signal_symbol_match" in eth_signals["missing_fields"]

    invalid_symbol_signals = client.get("/api/v2/signals?symbol=btcusdt..").json()
    _assert_contract(invalid_symbol_signals, "/api/v2/signals?symbol={symbol}")
    assert invalid_symbol_signals["source_type"] == "unavailable"
    assert invalid_symbol_signals["symbol"] is None
    assert "symbol" in invalid_symbol_signals["missing_fields"]
    assert "active_signal" in invalid_symbol_signals["missing_fields"]
    assert "Enter a valid market symbol" in invalid_symbol_signals["warnings"]
    assert invalid_symbol_signals["account_scope"]["live_trading_enabled"] is False
    assert invalid_symbol_signals["account_scope"]["exchange_mutation_enabled"] is False

    serialized = json.dumps([portfolio, positions, orders, executions, signals])
    assert "paper-other-order" not in serialized
    assert "exec-other" not in serialized
    assert "signal-other" not in serialized
    assert "paper-unscoped-order" not in serialized
    assert "exec-unscoped" not in serialized
    assert "signal-unscoped" not in serialized


def test_authenticated_trader_can_stage_fill_and_reject_cancel_local_paper_order_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    _write_json(
        tmp_path,
        "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
        {"symbol": "BTCUSDT", "generated_at": "2026-06-13T03:00:00Z", "last_price": 100000},
    )
    client = _client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200
    get_trader_account_repository().upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=250000,
        realized_pnl=0,
        unrealized_pnl=0,
        positions=[],
        orders=[],
        executions=[],
        signals=[],
        source_status="test_paper_repository",
    )

    preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "mode": "paper",
        },
    ).json()
    _assert_contract(preview, "/api/v2/orders/preview")
    assert preview["source_type"] == "repository"
    assert "Trader account repository" in preview["source"]
    assert "/home/" not in preview["source"]
    assert "trader_accounts.json" not in preview["source"]
    assert preview["data"]["allowed"] is True
    assert preview["data"]["reason"] == "paper_preview_ready"
    assert preview["symbol"] == "BTCUSDT"
    assert "Reference price was supplied by the paper preview request" in preview["warnings"]

    invalid_symbol_preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "btcusdt../",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "mode": "paper",
        },
    ).json()
    _assert_contract(invalid_symbol_preview, "/api/v2/orders/preview")
    assert invalid_symbol_preview["data"]["allowed"] is False
    assert invalid_symbol_preview["data"]["reason"] == "symbol_invalid"
    assert invalid_symbol_preview["data"]["friendly_reason"] == "Enter a valid market symbol"
    assert "symbol" in invalid_symbol_preview["missing_fields"]
    assert invalid_symbol_preview["symbol"] is None

    mismatched_preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-other",
            "mode": "paper",
        },
    ).json()
    _assert_contract(mismatched_preview, "/api/v2/orders/preview")
    assert mismatched_preview["data"]["allowed"] is False
    assert mismatched_preview["data"]["reason"] == "paper_account_scope_mismatch"
    assert "paper_account_scope" in mismatched_preview["missing_fields"]

    mismatched_trader_preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "trader_id": "trader-other",
            "paper_account_id": "paper-wajidali1984",
            "mode": "paper",
        },
    ).json()
    _assert_contract(mismatched_trader_preview, "/api/v2/orders/preview")
    assert mismatched_trader_preview["data"]["allowed"] is False
    assert mismatched_trader_preview["data"]["reason"] == "trader_scope_mismatch"
    assert "trader_scope" in mismatched_trader_preview["missing_fields"]

    missing_scope_submit = client.post(
        "/api/v2/orders/paper",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "mode": "paper",
        },
    ).json()
    _assert_contract(missing_scope_submit, "/api/v2/orders/paper")
    assert missing_scope_submit["data"]["accepted"] is False
    assert missing_scope_submit["data"]["reason"] == "paper_action_scope_required"
    assert missing_scope_submit["data"]["friendly_reason"] == "Paper action requires a signed-in trader and matching paper account"
    assert "request_trader_id" in missing_scope_submit["missing_fields"]
    assert "request_paper_account_id" in missing_scope_submit["missing_fields"]

    submitted = client.post(
        "/api/v2/orders/paper",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-wajidali1984",
            "mode": "paper",
        },
    ).json()
    _assert_contract(submitted, "/api/v2/orders/paper")
    assert submitted["data"]["accepted"] is True
    assert submitted["data"]["order"]["status"] == "open"
    assert submitted["data"]["order"]["audit_event"] == "paper_order_staged_local"
    assert submitted["symbol"] == "BTCUSDT"
    assert submitted["data"]["order"]["symbol"] == "BTCUSDT"
    assert submitted["data"]["order"]["trader_id"] == "trader-wajidali1984"
    assert submitted["data"]["order"]["paper_account_id"] == "paper-wajidali1984"

    staged_orders = client.get("/api/v2/execution/orders").json()
    _assert_contract(staged_orders, "/api/v2/execution/orders")
    _assert_authenticated_account_scope(staged_orders, verified=True)
    assert staged_orders["data"]["orders"][0]["order_id"] == submitted["data"]["order"]["order_id"]
    assert staged_orders["data"]["orders"][0]["trader_id"] == "trader-wajidali1984"
    assert staged_orders["data"]["orders"][0]["paper_account_id"] == "paper-wajidali1984"

    invalid_symbol_submit = client.post(
        "/api/v2/orders/paper",
        json={
            "symbol": "btcusdt../",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "trader_id": "trader-wajidali1984",
            "paper_account_id": "paper-wajidali1984",
            "mode": "paper",
        },
    ).json()
    _assert_contract(invalid_symbol_submit, "/api/v2/orders/paper")
    assert invalid_symbol_submit["data"]["accepted"] is False
    assert invalid_symbol_submit["data"]["reason"] == "symbol_invalid"
    assert invalid_symbol_submit["data"]["friendly_reason"] == "Enter a valid market symbol"
    assert "symbol" in invalid_symbol_submit["missing_fields"]
    assert invalid_symbol_submit["symbol"] is None
    assert submitted["data"]["order"]["id"].startswith("paper-")
    assert submitted["data"]["order"]["order_id"].startswith("paper-")
    assert submitted["data"]["order"]["live_transport_enabled"] is False
    assert submitted["data"]["order"]["exchange_mutation_enabled"] is False
    _assert_paper_execution_policy(submitted["data"]["paper_execution_policy"])
    order_id = submitted["data"]["order"]["order_id"]

    filled = client.post(
        f"/api/v2/orders/paper/{order_id}/fill",
        json={"price": 100000, "reason": "test local paper fill"},
    ).json()
    _assert_contract(filled, f"/api/v2/orders/paper/{order_id}/fill")
    assert filled["data"]["accepted"] is True
    assert filled["data"]["order"]["status"] == "filled"
    assert filled["data"]["execution"]["order_id"] == order_id
    assert filled["data"]["execution"]["audit_event"] == "paper_order_filled_local"
    assert filled["data"]["execution"]["live_transport_enabled"] is False
    assert filled["data"]["execution"]["exchange_mutation_enabled"] is False
    _assert_paper_execution_policy(filled["data"]["paper_execution_policy"])

    positions = client.get("/api/v2/account/positions").json()
    _assert_contract(positions, "/api/v2/account/positions")
    _assert_authenticated_account_scope(positions, verified=True)
    assert positions["data"]["positions"][0]["symbol"] == "BTCUSDT"
    assert positions["data"]["positions"][0]["trader_id"] == "trader-wajidali1984"
    assert positions["data"]["positions"][0]["paper_account_id"] == "paper-wajidali1984"
    assert positions["data"]["positions"][0]["side"] == "Long"

    executions = client.get("/api/v2/execution/executions").json()
    _assert_contract(executions, "/api/v2/execution/executions")
    _assert_authenticated_account_scope(executions, verified=True)
    assert executions["data"]["executions"][0]["order_id"] == order_id

    canceled = client.post(f"/api/v2/orders/paper/{order_id}/cancel").json()
    _assert_contract(canceled, f"/api/v2/orders/paper/{order_id}/cancel")
    assert canceled["data"]["accepted"] is False
    assert canceled["data"]["reason"] == "paper_cancel_rejected"
    _assert_paper_execution_policy(canceled["data"]["paper_execution_policy"])
    account = get_trader_account_repository().get_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
    )
    assert account is not None
    audit_events = account.get("audit_events", [])
    audit_names = [event.get("audit_event") for event in audit_events]
    assert "paper_order_staged_local" in audit_names
    assert "paper_order_filled_local" in audit_names
    assert all(event.get("exchange_mutation_enabled") is False for event in audit_events)
    assert all(event.get("live_transport_enabled") is False for event in audit_events)
    assert all(event.get("tamper_evident") is True for event in audit_events)
    assert all(isinstance(event.get("event_hash"), str) and event["event_hash"] for event in audit_events)
    staged_event = next(event for event in audit_events if event.get("audit_event") == "paper_order_staged_local")
    filled_event = next(event for event in audit_events if event.get("audit_event") == "paper_order_filled_local")
    assert filled_event["previous_event_hash"] == staged_event["event_hash"]

    audit_response = client.get("/api/v2/execution/audit-events").json()
    _assert_contract(audit_response, "/api/v2/execution/audit-events")
    _assert_authenticated_account_scope(audit_response, verified=True)
    assert audit_response["source_type"] == "repository"
    assert audit_response["mode"] == "paper"
    assert audit_response["data"]["account_scope"] == "authenticated_trader"
    assert audit_response["data"]["account_specific"] is True
    assert audit_response["data"]["trader_id"] == "trader-wajidali1984"
    assert audit_response["data"]["audit_policy"]["tamper_evident"] is True
    assert audit_response["data"]["audit_policy"]["production_durable_store"] is False
    assert audit_response["data"]["audit_policy"]["live_mutation_prohibited"] is True
    assert audit_response["data"]["audit_policy"]["chain_integrity"]["verified"] is True
    assert audit_response["data"]["audit_policy"]["chain_integrity"]["window_complete"] is True
    assert audit_response["data"]["audit_policy"]["chain_integrity"]["expected_event_count"] == len(audit_response["data"]["audit_events"])
    assert audit_response["data"]["audit_policy"]["chain_integrity"]["link_mismatch_count"] == 0
    assert audit_response["data"]["audit_ledger"]["append_only_local_file"] is True
    assert audit_response["data"]["audit_ledger"]["production_durable_store"] is False
    assert audit_response["data"]["audit_ledger"]["live_mutation_prohibited"] is True
    assert audit_response["data"]["audit_ledger"]["chain_integrity"]["verified"] is True
    assert audit_response["data"]["audit_ledger"]["chain_integrity"]["window_complete"] is True
    assert audit_response["data"]["audit_ledger"]["chain_integrity"]["expected_event_count"] == len(audit_response["data"]["audit_ledger_events"])
    assert audit_response["data"]["audit_ledger"]["chain_integrity"]["hash_mismatch_count"] == 0
    assert any(event["audit_event"] == "paper_order_filled_local" for event in audit_response["data"]["audit_ledger_events"])
    assert any(event["audit_event"] == "paper_order_filled_local" for event in audit_response["data"]["audit_events"])
    assert all(event["exchange_mutation_enabled"] is False for event in audit_response["data"]["audit_events"])
    assert all(event["live_transport_enabled"] is False for event in audit_response["data"]["audit_events"])
    assert all(event["tamper_evident"] is True for event in audit_response["data"]["audit_events"])

    get_trader_account_repository().upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=300000,
        realized_pnl=0,
        unrealized_pnl=0,
        source_status="balance_refresh_without_collection_replace",
    )
    preserved_account = get_trader_account_repository().get_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
    )
    assert preserved_account is not None
    preserved_audit_names = [event.get("audit_event") for event in preserved_account.get("audit_events", [])]
    assert "paper_order_staged_local" in preserved_audit_names
    assert "paper_order_filled_local" in preserved_audit_names
    assert preserved_account.get("orders")
    assert preserved_account.get("executions")
    assert preserved_account.get("positions")

    serialized = json.dumps(canceled).lower()
    assert "no exchange state was read or mutated" in serialized
    for forbidden in ("api_key", "api_secret", "live_order", "leverage", "margin mutation"):
        assert forbidden not in serialized


def test_order_preview_rejects_authenticated_user_without_trader_scope(tmp_path: Path, monkeypatch) -> None:
    _write_json(
        tmp_path,
        "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
        {"symbol": "BTCUSDT", "generated_at": "2026-06-13T03:00:00Z", "last_price": 100000},
    )
    client = _client(tmp_path, monkeypatch)
    get_user_store().create_user(
        email="viewer-preview@example.com",
        username="viewer-preview",
        password="Viewer-Preview-Password-123!",
        role="viewer",
    )
    login = client.post(
        "/api/auth/login",
        json={"email": "viewer-preview@example.com", "password": "Viewer-Preview-Password-123!"},
    )
    assert login.status_code == 200

    preview = client.post(
        "/api/v2/orders/preview",
        json={
            "symbol": "BTCUSDT",
            "side": "buy",
            "order_type": "limit",
            "quantity": 0.1,
            "price": 100000,
            "mode": "paper",
        },
    ).json()

    _assert_contract(preview, "/api/v2/orders/preview")
    assert preview["data"]["allowed"] is False
    assert preview["data"]["reason"] == "trader_account_scope_required"
    assert preview["data"]["friendly_reason"] == "Trader profile and paper workspace are required for paper preview"
    assert preview["data"]["available_paper_balance"] is None
    assert "trader_scope" in preview["missing_fields"]
    assert "paper_account_scope" in preview["missing_fields"]


def test_local_paper_fill_rejects_corrupt_order_side(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "test-password")
    client = _client(tmp_path, monkeypatch)
    login = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "test-password"},
    )
    assert login.status_code == 200
    repository = get_trader_account_repository()
    repository.upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=250000,
        realized_pnl=0,
        unrealized_pnl=0,
        positions=[],
        orders=[],
        executions=[],
        signals=[],
        source_status="test_paper_repository",
    )
    order = repository.append_paper_order(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        order={"symbol": "BTCUSDT", "side": "hold", "type": "limit", "quantity": 0.1, "price": 100000},
    )

    filled = client.post(
        f"/api/v2/orders/paper/{order['order_id']}/fill",
        json={"price": 100000, "reason": "test corrupt side"},
    ).json()

    _assert_contract(filled, f"/api/v2/orders/paper/{order['order_id']}/fill")
    assert filled["data"]["accepted"] is False
    assert filled["data"]["reason"] == "paper_fill_rejected"
