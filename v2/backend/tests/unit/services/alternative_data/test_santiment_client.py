from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any, Mapping


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.expiries: dict[str, int] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.expiries[key] = int(ex)
        return True

    def hset(self, key: str, mapping: Mapping[str, str]) -> int:
        self.hashes.setdefault(key, {}).update(dict(mapping))
        return len(mapping)

    def expire(self, key: str, ex: int) -> bool:
        self.expiries[key] = int(ex)
        return True


async def _noop_sleep(_seconds: float) -> None:
    return None


def _svc():
    return importlib.import_module(
        "v2.backend.app.services.alternative_data.santiment_client"
    )


def test_batch_query_uses_per_slug_json_and_estimated_metric_cost() -> None:
    svc = _svc()
    query = svc.build_batch_query(
        slugs=("bitcoin", "ethereum"),
        metrics=("social_volume_total", "sentiment_positive_total"),
    )

    assert "timeseriesDataPerSlugJson" in query
    assert 'selector: { slugs: ["bitcoin", "ethereum"] }' in query
    assert 'getMetric(metric: "social_volume_total")' in query
    assert svc.estimated_query_cost(("social_volume_total", "sentiment_positive_total")) == 2


def test_fetch_normalize_publish_writes_only_v2_santiment_keys() -> None:
    svc = _svc()
    fake_redis = FakeRedis()

    def fake_http(_url: str, headers: Mapping[str, str], body: Mapping[str, Any], _timeout: float):
        assert headers["Authorization"].startswith("Apikey ")
        assert "redacted-test-key" in headers["Authorization"]
        assert "timeseriesDataPerSlugJson" in body["query"]
        return svc.SantimentHttpResult(
            status_code=200,
            body={
                "data": {
                    "m_social_volume_total": {
                        "timeseriesDataPerSlugJson": json.dumps(
                            {
                                "bitcoin": [
                                    {"datetime": "2026-07-06T12:00:00Z", "value": 1000},
                                    {"datetime": "2026-07-06T12:05:00Z", "value": None},
                                ]
                            }
                        )
                    },
                    "m_sentiment_positive_total": {
                        "timeseriesDataPerSlugJson": json.dumps(
                            {"bitcoin": [{"datetime": "2026-07-06T12:05:00Z", "value": 8}]}
                        )
                    },
                    "m_sentiment_negative_total": {
                        "timeseriesDataPerSlugJson": json.dumps(
                            {"bitcoin": [{"datetime": "2026-07-06T12:05:00Z", "value": 2}]}
                        )
                    },
                    "m_whale_transaction_count_1m": {
                        "timeseriesDataPerSlugJson": json.dumps(
                            {"bitcoin": [{"datetime": "2026-07-06T12:05:00Z", "value": 12}]}
                        )
                    },
                    "m_exchange_inflow": {
                        "timeseriesDataPerSlugJson": json.dumps(
                            {"bitcoin": [{"datetime": "2026-07-06T12:05:00Z", "value": 2_500_000}]}
                        )
                    },
                    "m_percent_of_total_supply_on_exchanges": {
                        "timeseriesDataPerSlugJson": json.dumps(
                            {"bitcoin": [{"datetime": "2026-07-06T12:05:00Z", "value": 12.5}]}
                        )
                    },
                }
            },
            headers={
                "x-ratelimit-remaining-minute": "99",
                "x-ratelimit-remaining-hour": "3999",
                "x-ratelimit-remaining-month": "79999",
                "x-ratelimit-reset": "60",
            },
        )

    client = svc.SantimentProClient(
        api_key="redacted-test-key",
        http_post=fake_http,
        sleep_func=_noop_sleep,
    )
    result = asyncio.run(
        svc.fetch_normalize_publish_once(
            client=client,
            redis_client=fake_redis,
            symbols=("BTCUSDT",),
            metrics=(
                "social_volume_total",
                "sentiment_positive_total",
                "sentiment_negative_total",
                "whale_transaction_count_1m",
                "exchange_inflow",
                "percent_of_total_supply_on_exchanges",
            ),
            generated_utc="2026-07-06T12:06:00Z",
        )
    )

    status = result["status_payload"]
    payload = result["symbol_payloads"]["BTCUSDT"]
    assert status["provider_network_calls_attempted"] is True
    assert status["places_real_order"] is False
    assert payload["source_status"] == "API_OK"
    assert payload["santiment_social_volume_total"] == 1000.0
    assert payload["santiment_sentiment_score"] == 0.6
    assert payload["santiment_whale_transaction_count_1m"] == 12.0
    assert payload["santiment_exchange_inflow"] == 2500000.0
    assert payload["santiment_supply_on_exchanges_score"] == 0.875
    assert "social_volume_total" in payload["forward_filled_metrics"]
    assert sorted(fake_redis.store) == [
        "v2:altdata:santiment:status",
        "v2:altdata:santiment:symbol:BTCUSDT",
        "v2:features:santiment:BTCUSDT:1h",
        "v2:provider:santiment:feature_bridge_status",
    ]
    assert "v2:altdata:santiment:state" in fake_redis.hashes
    assert (
        fake_redis.expiries["v2:altdata:santiment:status"]
        >= svc.DEFAULT_EXECUTION_INTERVAL_SECONDS
    )
    assert (
        fake_redis.expiries["v2:altdata:santiment:symbol:BTCUSDT"]
        >= svc.DEFAULT_EXECUTION_INTERVAL_SECONDS
    )
    assert (
        fake_redis.expiries["v2:altdata:santiment:state"]
        >= svc.DEFAULT_EXECUTION_INTERVAL_SECONDS
    )
    assert all(key.startswith("v2:") for key in fake_redis.store)
    serialized = json.dumps(status) + json.dumps(payload) + json.dumps(fake_redis.store)
    assert "redacted-test-key" not in serialized


def test_santiment_redis_ttls_cover_deployed_loop_cadence() -> None:
    svc = _svc()

    assert svc.DEFAULT_EXECUTION_INTERVAL_SECONDS == 21_600
    assert svc.DEFAULT_REDIS_STATUS_TTL_SECONDS >= svc.DEFAULT_EXECUTION_INTERVAL_SECONDS
    assert svc.DEFAULT_REDIS_SYMBOL_TTL_SECONDS >= svc.DEFAULT_EXECUTION_INTERVAL_SECONDS
    assert svc.DEFAULT_REDIS_STATE_TTL_SECONDS >= svc.DEFAULT_EXECUTION_INTERVAL_SECONDS


def test_rate_limit_headers_trigger_safety_sleep() -> None:
    svc = _svc()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_http(_url: str, _headers: Mapping[str, str], _body: Mapping[str, Any], _timeout: float):
        return svc.SantimentHttpResult(
            status_code=200,
            body={"data": {}},
            headers={
                "x-ratelimit-remaining-minute": "4",
                "x-ratelimit-remaining-hour": "3999",
                "x-ratelimit-remaining-month": "79999",
                "x-ratelimit-reset": "3",
            },
        )

    client = svc.SantimentProClient(
        api_key="redacted-test-key",
        http_post=fake_http,
        sleep_func=fake_sleep,
    )
    asyncio.run(client.fetch_batch(slugs=("bitcoin",), metrics=("social_volume_total",)))

    assert sleeps == [5.0]
    assert client.rate_limit.remaining_minute == 4


def test_http_429_retries_with_backoff(monkeypatch) -> None:
    svc = _svc()
    sleeps: list[float] = []
    calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def fake_http(_url: str, _headers: Mapping[str, str], _body: Mapping[str, Any], _timeout: float):
        calls["count"] += 1
        if calls["count"] == 1:
            return svc.SantimentHttpResult(status_code=429, body={}, headers={})
        return svc.SantimentHttpResult(status_code=200, body={"data": {}}, headers={})

    monkeypatch.setattr(svc.random, "uniform", lambda _low, _high: 0.0)
    client = svc.SantimentProClient(
        api_key="redacted-test-key",
        http_post=fake_http,
        sleep_func=fake_sleep,
    )

    result = asyncio.run(
        client.fetch_batch(slugs=("bitcoin",), metrics=("social_volume_total",))
    )

    assert result.status_code == 200
    assert calls["count"] == 2
    assert sleeps == [2.0]


def test_extract_per_slug_points_pivots_time_major_rows() -> None:
    """timeseriesDataPerSlugJson returns time-major rows; the extractor must
    pivot them to slug-major point lists (regression: values were silently
    null while datetimes parsed, so every payload carried missing flags)."""
    from v2.backend.app.services.alternative_data.santiment_client import (
        _extract_per_slug_points,
        _latest_forward_filled,
    )

    block = {
        "timeseriesDataPerSlugJson": [
            {
                "datetime": "2026-06-03T00:00:00Z",
                "data": [
                    {"slug": "bitcoin", "value": 1650.0},
                    {"slug": "ethereum", "value": 369.0},
                ],
            },
            {
                "datetime": "2026-06-04T00:00:00Z",
                "data": [
                    {"slug": "bitcoin", "value": 2883.0},
                    {"slug": "ethereum", "value": 441.0},
                ],
            },
        ]
    }
    per_slug = _extract_per_slug_points(block)
    assert set(per_slug) == {"bitcoin", "ethereum"}
    value, dt, forward_filled = _latest_forward_filled(per_slug["bitcoin"])
    assert value == 2883.0
    assert dt == "2026-06-04T00:00:00Z"
    assert forward_filled is False
