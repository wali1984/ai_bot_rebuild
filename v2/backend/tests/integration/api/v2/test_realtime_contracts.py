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

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: Any) -> bool:
        self.kv[key] = value if isinstance(value, str) else json.dumps(value)
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


def test_realtime_bootstrap_is_readonly_and_complete(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    fake_redis.kv["v2:portfolio:state"] = json.dumps({
        "paper_session_id": "paper-test",
        "starting_equity_usd": 3000.0,
        "equity_usd": 3001.25,
        "realized_net_pnl_usd": 1.25,
        "generated_utc": "2026-07-09T00:00:00Z",
    })

    response = client.get("/api/v2/realtime/bootstrap")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["schema_version"] == "enterprise_realtime_bootstrap_v1"
    assert body["generated_utc"].endswith("Z")
    assert body["display_timezone"] == "America/New_York"
    assert body["live_gate"] == "blocked_human_only"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False
    assert body["ui_hints"]["default_pnl_display"] == "usd_and_percent"

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
        snapshot = body["resources"][resource]
        assert snapshot["schema_version"] == "enterprise_ui_snapshot_v1"
        assert snapshot["resource"] == resource
        assert snapshot["generated_utc"].endswith("Z")
        assert snapshot["display_timezone"] == "America/New_York"
        assert "payload" in snapshot
        assert snapshot["routes_to_live"] is False
        assert snapshot["places_real_order"] is False


def test_realtime_resources_expose_materialized_keys_and_no_mutation_flags(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    response = client.get("/api/v2/realtime/resources")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_realtime_resources_v1"
    assert body["one_socket_per_session"] is True
    assert body["readonly_path_multiplexing"] is True
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False

    resources = {item["name"]: item for item in body["resources"]}
    assert set(resources) >= {
        "dashboard",
        "markets",
        "ai_brain",
        "risk",
        "portfolio",
        "providers",
        "system_health",
        "trader_cockpit",
    }
    for name, contract in resources.items():
        assert contract["redis_key"] == f"v2:ui:snapshot:{name}"
        assert contract["endpoint"].startswith("/api/v2/ui/")
        assert contract["cadence_seconds"] >= 1


def test_realtime_health_reports_public_ready_safety_contract(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    response = client.get("/api/v2/realtime/health")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_realtime_health_v1"
    assert body["status"] == "ok"
    assert body["resource_count"] == 8
    assert body["one_socket_per_session"] is True
    assert body["readonly_path_multiplexing"] is True
    assert body["live_gate"] == "blocked_human_only"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False


def test_realtime_websocket_sequences_resource_frames(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    with client.websocket_connect("/api/v2/realtime/ws?resources=portfolio,providers&interval_ms=1000") as websocket:
        bootstrap = websocket.receive_json()
        portfolio = websocket.receive_json()
        providers = websocket.receive_json()

    assert bootstrap["type"] == "bootstrap"
    assert bootstrap["sequence"] == 0
    assert bootstrap["payload"]["live_gate"] == "blocked_human_only"
    assert bootstrap["payload"]["routes_to_live"] is False
    assert bootstrap["payload"]["places_real_order"] is False

    assert portfolio["type"] == "resource_delta"
    assert portfolio["resource"] == "portfolio"
    assert portfolio["sequence"] == 1
    assert portfolio["payload"]["schema_version"] == "enterprise_ui_snapshot_v1"
    assert portfolio["payload"]["places_real_order"] is False

    assert providers["type"] == "resource_delta"
    assert providers["resource"] == "providers"
    assert providers["sequence"] == 2
    assert providers["payload"]["schema_version"] == "enterprise_ui_snapshot_v1"
    assert providers["payload"]["places_real_order"] is False
