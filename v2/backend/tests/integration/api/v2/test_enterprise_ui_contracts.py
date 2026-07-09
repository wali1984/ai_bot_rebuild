from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v2 import realtime as v2_realtime
from app.api.v2 import ui as v2_ui
from app.main import create_app


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: Any) -> bool:
        self.kv[key] = value if isinstance(value, str) else json.dumps(value)
        self.set_calls.append((key, self.kv[key]))
        return True

    def ping(self) -> bool:
        return True


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(v2_ui, "get_redis", lambda: redis)
    monkeypatch.setattr(v2_realtime, "get_redis", lambda: redis)
    return redis


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_ui_portfolio_returns_canonical_pnl_contract(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.kv["v2:portfolio:state"] = json.dumps({
        "generated_utc": "2026-07-09T00:00:00Z",
        "paper_session_id": "paper-session-test",
        "starting_equity_usd": 3000.0,
        "equity": 3000.68,
        "realized_net_pnl_usd": 0.68,
        "unrealized_pnl_usd": 0.0,
        "closed_trade_count": 1,
    })

    response = client.get("/api/v2/ui/portfolio")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_ui_snapshot_v1"
    assert body["resource"] == "portfolio"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False
    payload = body["payload"]
    assert payload["schema_version"] == "canonical_pnl_v1"
    assert payload["equity_usd"] == 3000.68
    assert payload["net_pnl_usd"] == 0.68
    assert payload["reconciliation_status"] == "PASS"
    assert payload["paper_only"] is True


def test_ui_provider_cards_do_not_allow_heartbeat_only_green(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.kv["v2:provider:coinglass:health"] = json.dumps({
        "status": "GREEN",
        "dashboard_color": "green",
        "heartbeat_only": True,
        "actual_payload_count": 0,
    })

    response = client.get("/api/v2/ui/providers")
    assert response.status_code == 200
    providers = response.json()["payload"]["providers"]
    coinglass = next(card for card in providers if card["provider"] == "coinglass")
    assert coinglass["heartbeat_only"] is True
    assert coinglass["dashboard_color"] == "yellow"
    assert coinglass["raw_key_exposed"] is False
    assert coinglass["places_real_order"] is False


def test_ui_ai_brain_exposes_page_contract_without_live_routes(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.kv["v2:altdata:provider_consumption_status"] = json.dumps({
        "provider_tensor_consumption": True,
        "confluence_trade_block_score": 0.2,
        "confluence_reduce_size_score": 0.1,
        "confluence_hedge_required_score": 0.0,
        "provider_contribution_last_50": {"status": "current", "sample_count": 50},
    })
    fake_redis.kv["v2:provider:coinglass:feature_bridge_status"] = json.dumps({
        "feature_count": 12,
        "actual_payload_count": 3,
        "heartbeat_only": False,
    })
    fake_redis.kv["v2:provider:santiment:feature_bridge_status"] = json.dumps({
        "feature_count": 18,
        "actual_payload_count": 4,
        "heartbeat_only": False,
    })
    fake_redis.kv["v2:provider:moralis:feature_bridge_status"] = json.dumps({
        "feature_count": 10,
        "actual_payload_count": 2,
        "heartbeat_only": False,
    })

    response = client.get("/api/v2/ui/ai-brain")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_ui_snapshot_v1"
    assert body["resource"] == "ai_brain"
    payload = body["payload"]
    contract = payload["ai_page_contract"]
    assert contract["schema_version"] == "enterprise_ai_page_contract_v1"
    assert contract["ppo_tensor_provider_features"] is True
    assert contract["masa_tensor_provider_features"] is True
    assert contract["provider_feature_count_by_provider"]["coinglass"] == 12
    assert contract["provider_feature_count_by_provider"]["santiment"] == 18
    assert contract["provider_feature_count_by_provider"]["moralis"] == 10
    assert contract["routes_to_live"] is False
    assert contract["places_real_order"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_realtime_bootstrap_returns_all_resources(client: TestClient, fake_redis: FakeRedis) -> None:
    response = client.get("/api/v2/realtime/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_realtime_bootstrap_v1"
    assert body["live_gate"] == "blocked_human_only"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False
    for resource in (
        "dashboard",
        "markets",
        "ai_brain",
        "risk",
        "portfolio",
        "providers",
        "system_health",
        "trader_cockpit",
    ):
        assert resource in body["resources"]
        assert body["resources"][resource]["schema_version"] == "enterprise_ui_snapshot_v1"


def test_realtime_health_and_resource_registry(client: TestClient, fake_redis: FakeRedis) -> None:
    health = client.get("/api/v2/realtime/health").json()
    assert health["status"] == "ok"
    assert health["one_socket_per_session"] is True
    assert health["readonly_path_multiplexing"] is True
    assert health["websocket_endpoint"] == "/api/v2/realtime/ws"
    assert health["places_real_order"] is False

    resources = client.get("/api/v2/realtime/resources").json()
    assert resources["schema_version"] == "enterprise_realtime_resources_v1"
    assert {row["name"] for row in resources["resources"]} >= {"dashboard", "portfolio", "providers"}
    assert resources["one_socket_per_session"] is True
    assert resources["readonly_path_multiplexing"] is True


def test_realtime_websocket_multiplexes_readonly_resource_paths(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(path: str, headers: dict[str, str]) -> dict[str, Any]:
        return {
            "data": {"path": path, "ok": True},
            "source": path,
            "source_type": "api",
            "endpoint": path,
            "timestamp": "2026-07-09T00:00:00Z",
            "received_at": "2026-07-09T00:00:00Z",
            "lag_ms": 0,
            "stale": False,
            "missing_fields": [],
            "warnings": [],
            "mode": "read_only",
        }

    monkeypatch.setattr(v2_realtime, "_readonly_resource_resolve_payload", fake_resolve)

    with client.websocket_connect(
        "/api/v2/realtime/ws?resources=portfolio&path=/api/v2/portfolio&path_interval_ms=5000",
    ) as websocket:
        bootstrap = websocket.receive_json()
        assert bootstrap["type"] == "bootstrap"

        frames = [websocket.receive_json() for _ in range(2)]
        path_frame = next(frame for frame in frames if frame["type"] == "resource_path_delta")
        assert path_frame["path"] == "/api/v2/portfolio"
        assert path_frame["payload"]["transport"] == "websocket"
        assert path_frame["payload"]["data"]["ok"] is True
        assert path_frame["payload"].get("places_real_order") is not True
