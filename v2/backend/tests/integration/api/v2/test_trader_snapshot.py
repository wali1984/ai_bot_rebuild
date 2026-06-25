from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.v2 import market_contracts
from app.main import create_app
from app.services.trader_account_repository import get_trader_account_repository


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE", str(tmp_path / "auth_users.json"))
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_STORE", str(tmp_path / "trader_accounts.json"))
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "snapshot-trader-password")
    if "ALPHAFORGE_AUTH_SECRET" not in os.environ:
        monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "snapshot-test-secret-minimum-32-chars")
    monkeypatch.setattr(market_contracts, "BINANCE_FAPI_BASE", "http://127.0.0.1:9")
    monkeypatch.setattr(market_contracts, "BINANCE_HTTP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(market_contracts, "get_redis", lambda: None)
    market_contracts.MARKET_STREAM_TELEMETRY.clear()
    return TestClient(create_app())


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "snapshot-trader-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_trader_snapshot_requires_backend_auth(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    response = client.get("/api/v2/trader/snapshot")

    assert response.status_code == 401


def test_trader_snapshot_is_scoped_to_authenticated_trader(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    headers = _login(client)
    repository = get_trader_account_repository()
    repository.upsert_account(
        trader_id="trader-wajidali1984",
        paper_account_id="paper-wajidali1984",
        equity=12_345.67,
        realized_pnl=123.45,
        unrealized_pnl=-12.3,
        positions=[
            {
                "id": "pos-btc",
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-wajidali1984",
                "symbol": "BTCUSDT",
                "side": "Long",
                "quantity": 0.1,
                "entry_price": 100_000,
                "current_price": 101_000,
                "mark_price_source": "test-mark",
                "updated_at": "2026-06-23T00:00:00Z",
            }
        ],
        orders=[
            {
                "id": "order-1",
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-wajidali1984",
                "symbol": "BTCUSDT",
                "status": "open",
            }
        ],
        executions=[
            {
                "id": "exec-1",
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-wajidali1984",
                "symbol": "BTCUSDT",
                "quantity": 0.1,
            }
        ],
        signals=[
            {
                "id": "sig-1",
                "trader_id": "trader-wajidali1984",
                "paper_account_id": "paper-wajidali1984",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "confidence": 75,
            }
        ],
        source_status="snapshot_test_seed",
    )

    response = client.get("/api/v2/trader/snapshot?trader_id=attacker", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoint"] == "/api/v2/trader/snapshot"
    assert payload["trader_context"]["trader_id"] == "trader-wajidali1984"
    assert "attacker" not in str(payload)
    assert payload["warnings"] == [
        "Authenticated trader snapshot is read-only",
        "No frontend-supplied trader ID is accepted",
        "Live execution remains blocked",
    ]
    snapshot = payload["data"]
    assert sorted(snapshot.keys()) == sorted(
        [
            "account",
            "portfolio",
            "positions",
            "orders",
            "executions",
            "history",
            "signals",
            "predictions",
            "risk",
            "market_status",
            "automation_status",
            "execution_status",
            "data_status",
        ]
    )
    account = snapshot["account"]["data"]
    assert account["trader_id"] == "trader-wajidali1984"
    assert account["account_id"] == "paper-wajidali1984"
    assert account["equity"] == 12345.67
    assert account["open_position_count"] == 1
    assert account["open_order_count"] == 1
    assert account["execution_count"] == 1
    assert snapshot["positions"]["data"][0]["id"] == "pos-btc"
    assert snapshot["orders"]["data"][0]["id"] == "order-1"
    assert snapshot["executions"]["data"][0]["id"] == "exec-1"
    assert snapshot["data_status"]["data"]["live_trading_enabled"] is False
    assert snapshot["data_status"]["data"]["exchange_mutation_enabled"] is False
    for section in snapshot.values():
        meta = section["meta"]
        assert "source" in meta
        assert "source_type" in meta
        assert "timestamp" in meta
        assert "received_at" in meta
        assert "sequence" in meta
        assert "freshness" in meta
        assert "quality" in meta
        assert isinstance(meta["missing_fields"], list)
        assert isinstance(meta["warnings"], list)


def test_trader_snapshot_health_reports_readonly_blocked_execution(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    headers = _login(client)

    response = client.get("/api/v2/trader/snapshot/health", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["endpoint"] == "/api/v2/trader/snapshot/health"
    assert payload["data"]["live_trading_enabled"] is False
    assert payload["data"]["exchange_mutation_enabled"] is False
    assert "account" in payload["data"]["sections"]
