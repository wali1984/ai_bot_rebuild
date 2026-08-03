"""Contract tests for GET /api/v2/goal/trajectory-1000x.

Mirrors the enterprise-UI contract test style: FakeRedis seeded with the
tracker payload, TestClient against the real app, assertions on the
read-only contract envelope and honest-staleness fields.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v2 import control_center_status as v2_control_center_status
from app.main import create_app

GOAL_KEY = "v2:goal:trajectory_1000x"
ROUTE = "/api/v2/goal/trajectory-1000x"


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
    # goal_trajectory imports get_redis from _common directly; patch its
    # module-level reference plus the helper module it borrows from.
    from app.api.v2 import goal_trajectory as v2_goal_trajectory

    monkeypatch.setattr(v2_goal_trajectory, "get_redis", lambda: redis)
    monkeypatch.setattr(v2_control_center_status, "get_redis", lambda: redis)
    return redis


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _tracker_payload(generated_utc: str) -> dict[str, Any]:
    return {
        "schema_version": "v2_goal_trajectory_1000x_v1",
        "generated_utc": generated_utc,
        "objective": "1000x_in_90_days_research_objective_not_a_promise",
        "paper_session_id": "paper_3000_final_pre_live_20260713T190904Z",
        "session_started_utc": "2026-07-13T19:09:04Z",
        "days_elapsed": 3.479,
        "starting_equity_usd": 3000.0,
        "equity_usd": 3004.19,
        "realized_pnl_usd": 4.24,
        "unrealized_pnl_usd": -0.06,
        "multiple_now": 1.0014,
        "target_multiple": 1000.0,
        "target_days": 90.0,
        "required_daily_rate_pct": 7.978,
        "actual_daily_rate_pct": 0.0401,
        "on_track": False,
        "required_equity_today_usd": 3918.24,
        "equity_gap_vs_required_usd": -914.05,
        "days_to_target_at_required_rate_from_here": 90.0,
        "binding_constraint": {
            "constraint": "PERFORMANCE_CIRCUIT_HALTED",
            "detail": "entry circuit halted on negative rolling evidence",
            "evidence": {"key": "v2:paper:performance_circuit_breaker_status"},
        },
        "open_position_count": 7,
        "closed_trade_count": 55,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "live_gate": "blocked_human_only",
    }


def test_goal_trajectory_contract_fresh_payload(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    generated = (
        datetime.now(UTC) - timedelta(seconds=60)
    ).isoformat().replace("+00:00", "Z")
    fake_redis.kv[GOAL_KEY] = json.dumps(_tracker_payload(generated))

    response = client.get(ROUTE)
    assert response.status_code == 200
    body = response.json()

    assert body["schema_version"] == "goal_trajectory_1000x_contract_v1"
    assert body["canonical_owner"] == ROUTE
    assert body["source"] == f"redis:{GOAL_KEY}"
    assert body["live_gate"] == "blocked_human_only"
    assert body["places_real_order"] is False
    assert body["routes_to_live"] is False

    data = body["data"]
    assert data["source_key_present"] is True
    assert data["generated_utc"] == generated
    # Honest server-side staleness: about 60s old, definitely not stale.
    assert data["age_seconds"] is not None
    assert 0 <= data["age_seconds"] < 300
    assert data["is_stale"] is False
    assert data["stale_after_seconds"] == 900.0
    # Trajectory fields pass through verbatim.
    assert data["objective"] == (
        "1000x_in_90_days_research_objective_not_a_promise"
    )
    assert data["multiple_now"] == 1.0014
    assert data["target_multiple"] == 1000.0
    assert data["required_daily_rate_pct"] == 7.978
    assert data["on_track"] is False
    assert data["binding_constraint"]["constraint"] == (
        "PERFORMANCE_CIRCUIT_HALTED"
    )
    assert body["staleness_seconds"] == data["age_seconds"]
    assert body["freshness_status"] == "fresh"


def test_goal_trajectory_stale_payload_flagged(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    generated = (
        datetime.now(UTC) - timedelta(seconds=3600)
    ).isoformat().replace("+00:00", "Z")
    fake_redis.kv[GOAL_KEY] = json.dumps(_tracker_payload(generated))

    response = client.get(ROUTE)
    assert response.status_code == 200
    body = response.json()
    data = body["data"]

    assert data["source_key_present"] is True
    assert data["age_seconds"] > 900
    assert data["is_stale"] is True
    assert body["freshness_status"] == "stale"


def test_goal_trajectory_missing_key_is_honest(
    client: TestClient, fake_redis: FakeRedis
) -> None:
    assert GOAL_KEY not in fake_redis.kv

    response = client.get(ROUTE)
    assert response.status_code == 200
    body = response.json()
    data = body["data"]

    assert data["source_key_present"] is False
    assert data["generated_utc"] is None
    assert data["age_seconds"] is None
    assert data["is_stale"] is True
    assert data["missing_reason"] == (
        "GOAL_TRAJECTORY_KEY_MISSING_OR_EXPIRED_TRACKER_STALE"
    )
