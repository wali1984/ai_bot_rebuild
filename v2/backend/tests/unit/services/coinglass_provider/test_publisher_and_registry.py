from __future__ import annotations

import json

from v2.backend.app.services.coinglass_provider.endpoint_registry import (
    coinglass_endpoint_registry,
    registry_payload,
)
from v2.backend.app.services.coinglass_provider.publisher import publish_coinglass_result


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.data[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str):
        return self.data.get(key)


def test_registry_exposes_per_endpoint_cadence_and_budget() -> None:
    payload = registry_payload()
    budgets = [row["rate_budget_per_minute"] for row in payload["endpoints"]]
    assert payload["hard_limit_per_minute"] == 285
    assert payload["normal_mode_max_per_minute"] == 210
    assert all(budget > 0 for budget in budgets)


def test_publisher_writes_raw_feature_health_usage_and_endpoint_map() -> None:
    r = FakeRedis()
    spec = next(s for s in coinglass_endpoint_registry() if s.endpoint_id == "funding_rate")
    result = publish_coinglass_result(
        r,
        env={"COINGLASS_API_KEY": "secret"},
        spec=spec,
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {
                    "symbol": "BTC",
                    "stablecoin_margin_list": [
                        {"exchange": "Binance", "funding_rate": 0.02}
                    ],
                }
            ]
        },
        rate_limit_status={"requests_per_minute": 210},
    )
    assert result["actual_payload_present"] is True
    assert "v2:coinglass:funding:BTCUSDT" in r.data
    assert "v2:features:coinglass:BTCUSDT:1m" in r.data
    assert r.ttls["v2:features:coinglass:BTCUSDT:1m"] == spec.ttl_seconds
    endpoint_status = json.loads(r.data["v2:provider:coinglass:endpoint_status"])
    assert endpoint_status["endpoints"]["funding_rate"]["actual_payload_present"] is True
    health = json.loads(r.data["v2:provider:coinglass:health"])
    assert health["dashboard_color"] == "GREEN"
    assert health["raw_key_exposed"] is False


def test_publisher_merges_endpoint_features_into_symbol_feature_payload() -> None:
    r = FakeRedis()
    funding = next(s for s in coinglass_endpoint_registry() if s.endpoint_id == "funding_rate")
    open_interest = next(
        s for s in coinglass_endpoint_registry() if s.endpoint_id == "open_interest"
    )

    publish_coinglass_result(
        r,
        env={"COINGLASS_API_KEY": "secret"},
        spec=funding,
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {
                    "symbol": "BTC",
                    "stablecoin_margin_list": [
                        {"exchange": "Binance", "funding_rate": 0.02}
                    ],
                }
            ]
        },
        rate_limit_status={"requests_per_minute": 210},
    )
    publish_coinglass_result(
        r,
        env={"COINGLASS_API_KEY": "secret"},
        spec=open_interest,
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {"exchange": "All", "open_interest_usd": 1234567},
                {"exchange": "CME", "open_interest_usd": 456789},
            ]
        },
        rate_limit_status={"requests_per_minute": 210},
    )

    feature_payload = json.loads(r.data["v2:features:coinglass:BTCUSDT:1m"])
    assert feature_payload["actual_payload_present"] is True
    assert feature_payload["features"]["coinglass_funding_rate"] == 0.0002
    assert feature_payload["features"]["coinglass_open_interest_usd"] == 1234567
    assert set(feature_payload["endpoint_payloads"]) == {"funding_rate", "open_interest"}
    assert feature_payload["actual_payload_endpoint_count"] == 2


def test_auth_backoff_status_stays_gray_not_degraded_yellow() -> None:
    r = FakeRedis()
    spec = next(s for s in coinglass_endpoint_registry() if s.endpoint_id == "open_interest")

    result = publish_coinglass_result(
        r,
        env={"COINGLASS_API_KEY": "secret"},
        spec=spec,
        symbol="BTCUSDT",
        http_status=None,
        payload=None,
        rate_limit_status={"requests_per_minute": 210},
        error_class="CONFIGURED_BUT_UNAUTHORIZED_OR_UNSUBSCRIBED",
    )

    assert result["status"] == "CONFIGURED_BUT_UNAUTHORIZED_OR_UNSUBSCRIBED"
    endpoint_status = json.loads(r.data["v2:provider:coinglass:endpoint_status"])
    row = endpoint_status["endpoints"]["open_interest"]
    assert row["actual_payload_present"] is False
    assert row["heartbeat_only"] is True
    assert row["dashboard_color"] == "GRAY"
    health = json.loads(r.data["v2:provider:coinglass:health"])
    assert health["dashboard_color"] == "GRAY"


def test_health_stays_green_when_actual_endpoint_exists_and_optional_endpoint_degrades() -> None:
    r = FakeRedis()
    open_interest = next(
        s for s in coinglass_endpoint_registry() if s.endpoint_id == "open_interest"
    )
    trades = next(s for s in coinglass_endpoint_registry() if s.endpoint_id == "trades")

    publish_coinglass_result(
        r,
        env={"COINGLASS_API_KEY": "secret"},
        spec=open_interest,
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {"exchange": "All", "open_interest_usd": 1234567},
                {"exchange": "CME", "open_interest_usd": 456789},
            ]
        },
        rate_limit_status={"requests_per_minute": 210},
    )
    publish_coinglass_result(
        r,
        env={"COINGLASS_API_KEY": "secret"},
        spec=trades,
        symbol="BTCUSDT",
        http_status=None,
        payload=None,
        rate_limit_status={"requests_per_minute": 210},
        error_class="ConnectTimeout",
    )

    endpoint_status = json.loads(r.data["v2:provider:coinglass:endpoint_status"])
    assert endpoint_status["actual_payload_endpoint_count"] == 1
    health = json.loads(r.data["v2:provider:coinglass:health"])
    assert health["status"] == "READY"
    assert health["actual_payload_count_5m"] == 1
    assert health["dashboard_color"] == "GREEN"


def test_plan_forbidden_optional_endpoint_does_not_poison_provider_backoff():
    """A single not-in-plan endpoint (in-body 401) must go gray alone; it must
    not push the provider-wide backoff into auth_forbidden and starve every
    endpoint scheduled after it (observed live 2026-07-08: heatmap 401 made
    trades/orderbook report CONFIGURED_BUT_UNAUTHORIZED)."""
    import httpx

    from v2.backend.app.services.coinglass_provider.client import CoinGlassClient
    from v2.backend.app.services.coinglass_provider.endpoint_registry import (
        coinglass_endpoint_registry,
    )
    from v2.backend.app.services.coinglass_provider.rate_limit import (
        CoinGlassRateLimiter,
    )

    spec = next(
        s for s in coinglass_endpoint_registry()
        if s.endpoint_id == "liquidation_heatmap_or_levels"
    )
    assert spec.optional_if_plan_forbidden is True

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "401", "msg": "Upgrade plan"})

    limiter = CoinGlassRateLimiter()
    client = CoinGlassClient(
        api_key="test-key",
        limiter=limiter,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    resp = client.get(spec, symbol="BTCUSDT")
    assert resp.error_class is not None and resp.error_class.startswith("IN_BODY_401")
    assert limiter.backoff.is_active() is False
    allowed, reason = limiter.allow_request()
    assert allowed is True, reason
