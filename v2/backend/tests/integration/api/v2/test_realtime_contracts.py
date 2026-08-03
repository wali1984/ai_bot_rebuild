from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
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
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRedis]:
    v2_realtime._clear_realtime_caches_for_tests()
    redis = FakeRedis()
    monkeypatch.setattr(v2_ui, "get_redis", lambda: redis)
    monkeypatch.setattr(v2_realtime, "get_redis", lambda: redis)
    yield redis
    v2_realtime._clear_realtime_caches_for_tests()


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
    assert body["portfolio"]["schema_version"] == "enterprise_realtime_resource_alias_v1"
    assert body["portfolio"]["endpoint"] == "/api/v2/ui/portfolio"
    assert body["risk"]["schema_version"] == "enterprise_realtime_resource_alias_v1"
    assert body["risk"]["endpoint"] == "/api/v2/ui/risk"
    assert body["providers"]["schema_version"] == "enterprise_realtime_resource_alias_v1"
    assert "providers" not in body["resources"]["dashboard"]["payload"]
    assert body["resources"]["dashboard"]["payload"]["resource_refs"]["providers"] == "/api/v2/ui/providers"

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


def test_realtime_bootstrap_degrades_when_read_model_builder_times_out(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow_bootstrap(_client: Any) -> dict[str, Any]:
        time.sleep(0.2)
        return {"unexpected": "late"}

    monkeypatch.setattr(v2_realtime, "build_enterprise_bootstrap", slow_bootstrap)
    monkeypatch.setattr(v2_realtime, "ENTERPRISE_REALTIME_BOOTSTRAP_TIMEOUT_SECONDS", 0.01)

    response = client.get("/api/v2/realtime/bootstrap")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_realtime_bootstrap_v1"
    assert body["status"] == "degraded"
    assert body["resources"]["portfolio"]["schema_version"] == "enterprise_ui_snapshot_v1"
    assert body["resources"]["portfolio"]["data_quality"] == "degraded"
    assert body["live_gate"] == "blocked_human_only"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False


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


def test_ui_snapshot_uses_live_fallback_when_materialized_view_is_stale(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    fake_redis.kv["v2:ui:snapshot:portfolio"] = json.dumps({
        "schema_version": "enterprise_ui_snapshot_v1",
        "resource": "portfolio",
        "generated_utc": "2000-01-01T00:00:00Z",
        "payload": {
            "schema_version": "stale_fixture_should_not_drive_ui",
            "paper_equity_usd": 1.0,
            "routes_to_live": False,
            "places_real_order": False,
        },
        "routes_to_live": False,
        "places_real_order": False,
    })
    fake_redis.kv["v2:portfolio:state"] = json.dumps({
        "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "paper_session_id": "fresh-session",
        "starting_equity_usd": 3000.0,
        "equity": 3004.25,
        "realized_net_pnl_usd": 4.25,
        "unrealized_pnl_usd": 0.0,
        "closed_trade_count": 1,
    })

    response = client.get("/api/v2/ui/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_ui_snapshot_v1"
    assert body["source_type"] == "computed_fallback"
    assert body["source"] == "compact_live_fallback"
    assert body["freshness_status"] == "fresh"
    assert body["data_quality_status"] == "partial"
    assert body["stale_materialized_source_key"] == "v2:ui:snapshot:portfolio"
    assert body["stale_materialized_age_seconds"] > 300
    assert "redis_materialized_view_stale" in body["missing_sections"]
    assert body["payload"]["schema_version"] == "canonical_pnl_v1"
    assert body["payload"]["paper_equity_usd"] == 3004.25
    assert body["payload"]["paper_total_pnl_usd"] == 4.25
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False


def test_enterprise_stream_aliases_emit_readonly_sse_events(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    for path in (
        "/api/v2/stream/runtime?once=true",
        "/api/v2/stream/trading?once=true",
        "/api/v2/stream/providers?once=true",
        "/api/v2/stream/trainer?once=true",
        "/api/v2/stream/risk?once=true",
    ):
        with client.stream("GET", path) as response:
            body = response.read().decode("utf-8")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        data_line = next(line for line in body.splitlines() if line.startswith("data: "))
        payload = json.loads(data_line.removeprefix("data: "))
        stream_name = path.split("/stream/", 1)[1].split("?", 1)[0]
        assert payload["schema_version"] == "enterprise_runtime_stream_event_v1"
        assert payload["generated_at_utc"].endswith("Z")
        assert payload["generated_at_et"]
        assert payload["source"] == f"enterprise_realtime_stream:{stream_name}"
        assert payload["canonical_owner"] == f"/api/v2/stream/{stream_name}"
        assert payload["staleness_seconds"] is None or payload["staleness_seconds"] >= 0
        assert payload["freshness_status"] in {"fresh", "degraded", "stale", "unknown", "missing"}
        assert payload["data_quality_status"] in {"fresh", "partial", "stale", "missing", "unknown"}
        assert payload["source_resource_count"] == len(payload["resources"])
        assert payload["source_resources"] == list(payload["resources"].keys())
        assert payload["live_gate"] == "blocked_human_only"
        assert payload["routes_to_live"] is False
        assert payload["places_real_order"] is False


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
