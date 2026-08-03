from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v2 import pipeline as v2_pipeline
from app.main import create_app


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.set_calls: list[tuple[str, str]] = []
        self.xadd_calls: list[tuple[str, dict[str, str]]] = []

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: Any) -> bool:
        self.kv[key] = value if isinstance(value, str) else json.dumps(value)
        self.set_calls.append((key, self.kv[key]))
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.kv or key in self.streams else 0

    def xadd(self, stream: str, fields: dict[str, str], *args: Any, **kwargs: Any) -> str:
        entry_id = f"{int(time.time() * 1000)}-{len(self.streams.get(stream, []))}"
        self.streams.setdefault(stream, []).append((entry_id, dict(fields)))
        self.xadd_calls.append((stream, dict(fields)))
        return entry_id


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeRedis:
    redis = FakeRedis()
    public_dir = tmp_path / "v2/frontend/public/operator_runtime/v2_market_chart/latest"
    public_dir.mkdir(parents=True)
    (public_dir / "operator_dashboard_payload.json").write_text(
        json.dumps(
            {
                "schema_version": "test_chart_manifest",
                "payloads": {
                    "BTCUSDT": {"status": "CURRENT"},
                    "ETHUSDT": {"status": "STALE"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(v2_pipeline, "get_redis", lambda: redis)
    return redis


@pytest.fixture
def no_redis(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(v2_pipeline, "get_redis", lambda: None)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def trader_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Authenticated client (trader role -> 'operator' RBAC rank).

    RBAC derives the role from the JWT session, not a spoofable X-Role header,
    so operator-gated pipeline control requires a real login.
    """
    import os as _os

    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE", str(tmp_path / "auth_users.json"))
    monkeypatch.setenv("ALPHAFORGE_TRADER_ACCOUNT_STORE", str(tmp_path / "trader_accounts.json"))
    monkeypatch.setenv("ALPHAFORGE_INITIAL_TRADER_PASSWORD", "pipeline-trader-password")
    if "ALPHAFORGE_AUTH_SECRET" not in _os.environ:
        monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "pipeline-test-secret-minimum-32-chars-long")
    auth_client = TestClient(create_app())
    resp = auth_client.post(
        "/api/auth/login",
        json={"email": "wajidali1984@hotmail.com", "password": "pipeline-trader-password"},
    )
    assert resp.status_code == 200, resp.text
    return auth_client, {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_minimal_symbol(redis: FakeRedis, symbol: str, timeframe: str = "1m") -> None:
    redis.set(f"v2:market:prices:{symbol}", {"price": 100.0})
    redis.set(f"v2:market:ohlcv:binance:{symbol}:{timeframe}", {"close": 100.0})
    redis.set(
        f"v2:features:latest:{symbol}:{timeframe}",
        {"feature_snapshot_id": f"fs_{symbol}_{timeframe}"},
    )
    redis.set(f"v2:features:ta:{symbol}:{timeframe}", {"rsi_14": 55.0})
    redis.set(f"v2:prediction:{symbol}:{timeframe}", {"prediction_id": "p1"})


def test_pipeline_status_missing_redis_returns_safe_all_symbol_shape(
    client: TestClient,
    no_redis: None,
) -> None:
    res = client.get("/api/v2/pipeline/status?timeframes=1m")
    assert res.status_code == 200
    body = res.json()

    assert body["live_gate"] == "blocked_human_only"
    assert body["live_symbols"] == []
    assert body["exchange_action_taken"] is False
    assert body["control_stream_key"] == "v2:pipeline:control:requests"
    assert len(body["symbols"]) >= 25
    assert body["compatibility"]["row_count"] == len(body["symbols"])


def test_pipeline_status_reports_symbol_compatibility(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    _seed_minimal_symbol(fake_redis, "BTCUSDT")

    res = client.get("/api/v2/pipeline/status?symbols=BTCUSDT&timeframes=1m")
    assert res.status_code == 200
    body = res.json()

    assert body["compatibility"]["trainer_compatible_count"] == 1
    assert body["compatibility"]["backtest_compatible_count"] == 1
    assert body["compatibility"]["replay_compatible_count"] == 1
    assert body["compatibility"]["chart_visible_symbol_count"] == 1
    assert body["rows"][0]["chart_payload_path"].endswith("/BTCUSDT_1m_chart.json")


def test_pipeline_dry_run_does_not_write_redis(
    trader_auth,
    fake_redis: FakeRedis,
) -> None:
    client, headers = trader_auth
    _seed_minimal_symbol(fake_redis, "BTCUSDT")
    fake_redis.set_calls.clear()

    res = client.post(
        "/api/v2/pipeline/run",
        headers=headers,
        json={
            "run_type": "full_pipeline",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1m"],
            "dry_run": True,
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert body["queue_state"] == "DRY_RUN_NOT_QUEUED"
    assert body["stream_id"] is None
    assert fake_redis.xadd_calls == []
    assert fake_redis.set_calls == []


def test_pipeline_enqueue_writes_only_v2_pipeline_keys(
    trader_auth,
    fake_redis: FakeRedis,
) -> None:
    client, headers = trader_auth
    _seed_minimal_symbol(fake_redis, "BTCUSDT")
    fake_redis.set_calls.clear()

    res = client.post(
        "/api/v2/pipeline/run",
        headers=headers,
        json={
            "run_type": "trainer_cycle",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1m"],
            "dry_run": False,
        },
    )
    assert res.status_code == 200
    body = res.json()

    assert body["queue_state"] == "QUEUED"
    assert body["stream_id"] is not None
    written_streams = [stream for stream, _fields in fake_redis.xadd_calls]
    written_keys = [key for key, _value in fake_redis.set_calls]
    assert written_streams == [
        "v2:pipeline:control:requests",
        "v2:pipeline:control:audit",
    ]
    assert written_keys == ["v2:pipeline:control:last_request"]
    assert all(key.startswith("v2:pipeline:") for key in written_streams + written_keys)
    assert body["exchange_action_taken"] is False
    assert body["trainer_api_executed_job_inline"] is False


def test_pipeline_enqueue_requires_operator_role(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    res = client.post(
        "/api/v2/pipeline/run",
        headers={"X-Role": "public"},
        json={"run_type": "replay", "dry_run": False},
    )
    assert res.status_code == 403
