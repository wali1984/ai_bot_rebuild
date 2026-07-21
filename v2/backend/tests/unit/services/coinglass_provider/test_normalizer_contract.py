from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.services.coinglass_provider import publisher as coinglass_publisher
from v2.backend.app.services.coinglass_provider.endpoint_registry import (
    coinglass_endpoint_registry,
)
from v2.backend.app.services.coinglass_provider.normalizer import (
    normalize_coinglass_payload,
)
from v2.backend.app.services.coinglass_provider.publisher import (
    publish_coinglass_result,
)


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


def _spec(endpoint_id: str):
    return next(
        spec
        for spec in coinglass_endpoint_registry()
        if spec.endpoint_id == endpoint_id
    )


def _milliseconds(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def test_registry_uses_supported_truthful_one_hour_history_contracts() -> None:
    historical = {
        spec.endpoint_id: spec
        for spec in coinglass_endpoint_registry()
        if spec.source_interval is not None
    }
    assert set(historical) == {
        "long_short_ratio",
        "liquidation_orders",
        "trades",
        "orderbook_l2_l3",
    }
    for spec in historical.values():
        assert spec.source_interval == "1h"
        assert dict(spec.default_params)["interval"] == "1h"
    assert {
        endpoint_id: spec.max_source_age_seconds
        for endpoint_id, spec in historical.items()
    } == {
        "long_short_ratio": 3720,
        "liquidation_orders": 3660,
        "trades": 3660,
        "orderbook_l2_l3": 3660,
    }
    for spec in historical.values():
        assert {
            spec.cadence_seconds_top_symbols,
            spec.cadence_seconds_active_symbols,
            spec.cadence_seconds_full_universe,
        } == {300}
        assert spec.ttl_seconds == spec.max_source_age_seconds
    assert [
        spec.endpoint_id
        for spec in coinglass_endpoint_registry()
        if spec.response_scope == "all_symbols"
    ] == ["funding_rate"]
    assert historical["trades"].path == (
        "/api/futures/v2/taker-buy-sell-volume/history"
    )


def test_open_interest_uses_all_row_and_converts_percentages_to_fractions() -> None:
    # Representative v4 exchange-list shape from the CoinGlass contract.
    payload = {
        "code": "0",
        "data": [
            {
                "exchange": "All",
                "symbol": "BTC",
                "open_interest_usd": 57_437_891_724.5572,
                "open_interest_change_percent_5m": 0.34,
                "open_interest_change_percent_1h": 2.27,
            },
            {
                "exchange": "CME",
                "symbol": "BTC",
                "open_interest_usd": 12_294_999_402.5,
                "open_interest_change_percent_5m": 0.08,
                "open_interest_change_percent_1h": 1.13,
            },
        ],
    }
    normalized = normalize_coinglass_payload(
        spec=_spec("open_interest"),
        symbol="BTCUSDT",
        payload=payload,
        observed_at="2026-07-20T12:00:30Z",
    )

    assert normalized["features"]["coinglass_open_interest_usd"] == pytest.approx(
        57_437_891_724.5572
    )
    assert normalized["features"][
        "coinglass_open_interest_change_fraction_5m"
    ] == pytest.approx(0.0034)
    assert normalized["features"][
        "coinglass_open_interest_change_fraction_1h"
    ] == pytest.approx(0.0227)
    assert not any("delta_usd" in name for name in normalized["features"])
    assert "coinglass_oi_price_divergence_score" not in normalized["features"]
    assert normalized["feature_cutoff"] == "2026-07-20T12:00:30Z"
    assert normalized["temporal_contract_valid"] is True


def test_funding_and_account_percentages_are_canonical_fractions() -> None:
    observed_at = datetime(2026, 7, 20, 12, 1, 30, tzinfo=UTC)
    funding = normalize_coinglass_payload(
        spec=_spec("funding_rate"),
        symbol="BTCUSDT",
        payload={
            "code": "0",
            "data": [
                {
                    "symbol": "BTC",
                    "stablecoin_margin_list": [
                        {
                            "exchange": "Binance",
                            "funding_rate": 0.007343,
                            "next_funding_time": _milliseconds(
                                observed_at + timedelta(hours=2)
                            ),
                        }
                    ],
                }
            ],
        },
        observed_at=observed_at,
    )
    assert funding["features"]["coinglass_funding_rate"] == pytest.approx(
        0.00007343
    )
    assert funding["features"]["coinglass_next_funding_minutes"] == 120.0
    assert "coinglass_funding_rate_zscore" not in funding["features"]

    ratio_observed_at = observed_at + timedelta(hours=1)
    account_ratio = normalize_coinglass_payload(
        spec=_spec("long_short_ratio"),
        symbol="BTCUSDT",
        payload={
            "data": [
                {
                    "time": _milliseconds(
                        observed_at.replace(minute=0, second=0)
                    ),
                    "top_account_long_percent": 73.3,
                    "top_account_short_percent": 26.7,
                    "top_account_long_short_ratio": 2.75,
                },
                {
                    "time": _milliseconds(
                        ratio_observed_at.replace(minute=0, second=0)
                    ),
                    "top_account_long_percent": 74.18,
                    "top_account_short_percent": 25.82,
                    "top_account_long_short_ratio": 2.87,
                },
            ]
        },
        observed_at=ratio_observed_at,
    )
    assert account_ratio["features"]["coinglass_long_ratio"] == pytest.approx(
        0.733
    )
    assert account_ratio["features"]["coinglass_short_ratio"] == pytest.approx(
        0.267
    )
    assert account_ratio["bar_open"] == "2026-07-20T12:00:00Z"
    assert account_ratio["bar_close"] == "2026-07-20T13:00:00Z"
    assert account_ratio["feature_cutoff"] == "2026-07-20T13:00:00Z"
    assert account_ratio["source_interval"] == "1h"
    assert account_ratio["is_closed"] is True


def test_funding_fails_closed_without_binance_stablecoin_margin_entry() -> None:
    normalized = normalize_coinglass_payload(
        spec=_spec("funding_rate"),
        symbol="BTCUSDT",
        payload={
            "data": [
                {
                    "symbol": "BTC",
                    "stablecoin_margin_list": [
                        {"exchange": "Bybit", "funding_rate": 0.02}
                    ],
                }
            ]
        },
        observed_at="2026-07-20T12:00:30Z",
    )

    assert normalized["features"] == {}
    assert normalized["actual_payload_present"] is False
    assert normalized["temporal_contract_valid"] is False


def test_market_selects_requested_binance_instrument_independent_of_row_order() -> None:
    normalized = normalize_coinglass_payload(
        spec=_spec("market_snapshot"),
        symbol="BTCUSDT",
        payload={
            "data": [
                {
                    "exchange_name": "Binance",
                    "instrument_id": "BTCUSD_PERP",
                    "current_price": 64_000.0,
                    "price_change_percent_24h": -3.0,
                    "volume_usd": 100.0,
                },
                {
                    "exchange_name": "Binance",
                    "instrument_id": "BTCUSDC",
                    "current_price": 66_000.0,
                    "price_change_percent_24h": 1.0,
                    "volume_usd": 200.0,
                },
                {
                    "exchange_name": "Binance",
                    "instrument_id": "BTCUSDT",
                    "current_price": 67_500.0,
                    "price_change_percent_24h": 2.5,
                    "volume_usd": 1_500_000.0,
                },
                {
                    "exchange_name": "OKX",
                    "instrument_id": "BTC-USDT-SWAP",
                    "current_price": 67_450.0,
                    "volume_usd": 300.0,
                },
            ]
        },
        observed_at="2026-07-20T12:00:30Z",
    )

    assert normalized["features"]["coinglass_price_usd"] == 67_500.0
    assert normalized["features"][
        "coinglass_price_change_24h_fraction"
    ] == pytest.approx(0.025)
    assert normalized["features"]["coinglass_volume_24h_usd"] == 1_500_600.0
    assert normalized["features"]["coinglass_exchange_count"] == 2.0
    assert "coinglass_price_change_24h_pct" not in normalized["features"]
    assert "coinglass_price_change_24h_fraction" in _spec(
        "market_snapshot"
    ).feature_outputs


def test_historical_normalizer_walks_back_from_open_row_and_rejects_open_only() -> None:
    observed_at = datetime(2026, 7, 20, 13, 1, 30, tzinfo=UTC)
    closed_at = observed_at.replace(hour=12, minute=0, second=0)
    open_at = observed_at.replace(minute=0, second=0)
    spec = _spec("liquidation_orders")

    normalized = normalize_coinglass_payload(
        spec=spec,
        symbol="BTCUSDT",
        payload={
            "data": [
                {
                    "time": _milliseconds(closed_at),
                    "aggregated_short_liquidation_usd": 258.84,
                    "aggregated_long_liquidation_usd": 0.0,
                },
                {
                    "time": _milliseconds(open_at),
                    "aggregated_short_liquidation_usd": 9_000_000.0,
                    "aggregated_long_liquidation_usd": 1_000_000.0,
                },
            ]
        },
        observed_at=observed_at,
    )
    assert normalized["features"] == {
        "coinglass_liquidation_buy_usd_1h": 258.84,
        "coinglass_liquidation_sell_usd_1h": 0.0,
        "coinglass_liquidation_total_usd_1h": 258.84,
        "coinglass_liquidation_imbalance_usd": 258.84,
    }
    assert "coinglass_liquidation_cascade_score" not in normalized["features"]
    assert normalized["history_row_admission"] == "LATEST_CLOSED_ROW"

    rejected = normalize_coinglass_payload(
        spec=spec,
        symbol="BTCUSDT",
        payload={
            "data": [
                {
                    "time": _milliseconds(open_at),
                    "aggregated_short_liquidation_usd": 9_000_000.0,
                    "aggregated_long_liquidation_usd": 1_000_000.0,
                }
            ]
        },
        observed_at=observed_at,
    )
    assert rejected["features"] == {}
    assert rejected["actual_payload_present"] is False
    assert rejected["temporal_contract_valid"] is False
    assert rejected["history_row_admission"] == "NO_CLOSED_ROW"


def test_historical_source_age_accepts_boundary_and_rejects_older_closed_row() -> None:
    spec = _spec("liquidation_orders")
    bar_open = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    bar_close = bar_open + timedelta(hours=1)
    payload = {
        "data": [
            {
                "time": _milliseconds(bar_open),
                "aggregated_short_liquidation_usd": 200.0,
                "aggregated_long_liquidation_usd": 100.0,
            }
        ]
    }

    boundary = normalize_coinglass_payload(
        spec=spec,
        symbol="BTCUSDT",
        payload=payload,
        observed_at=bar_close + timedelta(seconds=3660),
    )
    assert boundary["source_age_seconds"] == 3660.0
    assert boundary["max_source_age_seconds"] == 3660
    assert boundary["source_fresh"] is True
    assert boundary["actual_payload_present"] is True
    assert boundary["temporal_contract_valid"] is True
    assert boundary["history_row_admission"] == "LATEST_CLOSED_ROW"

    stale = normalize_coinglass_payload(
        spec=spec,
        symbol="BTCUSDT",
        payload=payload,
        observed_at=bar_close + timedelta(seconds=3661),
    )
    assert stale["source_age_seconds"] == 3661.0
    assert stale["max_source_age_seconds"] == 3660
    assert stale["source_fresh"] is False
    assert stale["is_closed"] is True
    assert stale["features"] == {}
    assert stale["actual_payload_present"] is False
    assert stale["temporal_contract_valid"] is False
    assert stale["history_row_admission"] == "CLOSED_ROW_TOO_OLD"


def test_non_finite_negative_and_incomplete_values_are_not_admitted() -> None:
    normalized = normalize_coinglass_payload(
        spec=_spec("open_interest"),
        symbol="BTCUSDT",
        payload={
            "data": [
                {
                    "exchange": "All",
                    "open_interest_usd": math.nan,
                    "open_interest_change_percent_5m": math.inf,
                }
            ]
        },
        observed_at="2026-07-20T12:00:30Z",
    )
    assert normalized["features"] == {}
    assert normalized["temporal_contract_valid"] is False

    observed_at = datetime(2026, 7, 20, 13, 1, 30, tzinfo=UTC)
    trades = normalize_coinglass_payload(
        spec=_spec("trades"),
        symbol="BTCUSDT",
        payload={
            "data": [
                {
                    "time": _milliseconds(
                        observed_at.replace(hour=12, minute=0, second=0)
                    ),
                    "taker_buy_volume_usd": 1000.0,
                    "taker_sell_volume_usd": -1.0,
                }
            ]
        },
        observed_at=observed_at,
    )
    assert trades["features"] == {}


def test_publisher_exposes_closed_bar_evidence_and_fails_closed_on_open_only() -> None:
    redis_client = FakeRedis()
    spec = _spec("liquidation_orders")
    now = datetime.now(UTC)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    previous_hour = current_hour - timedelta(hours=1)

    accepted = publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=spec,
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {
                    "time": _milliseconds(previous_hour),
                    "aggregated_short_liquidation_usd": 2_000_000.0,
                    "aggregated_long_liquidation_usd": 1_000_000.0,
                },
                {
                    "time": _milliseconds(current_hour),
                    "aggregated_short_liquidation_usd": 8_000_000.0,
                    "aggregated_long_liquidation_usd": 1_000_000.0,
                },
            ]
        },
        rate_limit_status={"requests_per_minute": 65},
    )
    assert accepted["actual_payload_present"] is True
    aggregate = json.loads(
        redis_client.data["v2:features:coinglass:BTCUSDT:1m"]
    )
    endpoint = aggregate["endpoint_payloads"]["liquidation_orders"]
    assert endpoint["source_interval"] == "1h"
    assert endpoint["is_closed"] is True
    assert endpoint["source_fresh"] is True
    assert endpoint["max_source_age_seconds"] == 3660
    assert 0.0 <= endpoint["source_age_seconds"] <= 3660.0
    assert endpoint["bar_close"] == current_hour.isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    assert aggregate["decision_time_safe"] is True
    assert aggregate["temporal_contract_valid"] is True

    open_only_redis = FakeRedis()
    open_only = publish_coinglass_result(
        open_only_redis,
        env={"COINGLASS_API_KEY": "secret"},
        spec=spec,
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {
                    "time": _milliseconds(current_hour),
                    "aggregated_short_liquidation_usd": 8_000_000.0,
                    "aggregated_long_liquidation_usd": 1_000_000.0,
                }
            ]
        },
        rate_limit_status={"requests_per_minute": 65},
    )
    assert open_only["actual_payload_present"] is False
    open_aggregate = json.loads(
        open_only_redis.data["v2:features:coinglass:BTCUSDT:1m"]
    )
    assert open_aggregate["features"] == {}
    assert open_aggregate["decision_time_safe"] is False
    assert open_aggregate["provider_ready"] is False


def test_publisher_deduplicates_same_hour_lineage_and_replaces_next_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    spec = _spec("liquidation_orders")
    clock = {"now": "2026-07-20T13:05:00Z"}
    monkeypatch.setattr(coinglass_publisher, "_now", lambda: clock["now"])
    payload = {
        "data": [
            {
                "time": _milliseconds(datetime(2026, 7, 20, 12, tzinfo=UTC)),
                "aggregated_short_liquidation_usd": 200.0,
                "aggregated_long_liquidation_usd": 100.0,
            },
            {
                "time": _milliseconds(datetime(2026, 7, 20, 13, tzinfo=UTC)),
                "aggregated_short_liquidation_usd": 200.0,
                "aggregated_long_liquidation_usd": 100.0,
            },
        ]
    }
    raw_key = "v2:coinglass:liquidations:BTCUSDT"
    feature_key = "v2:features:coinglass:BTCUSDT:1m"

    first_result = publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=spec,
        symbol="BTCUSDT",
        http_status=200,
        payload=payload,
        rate_limit_status={"requests_per_minute": 65},
    )
    first_raw = json.loads(redis_client.data[raw_key])
    first_serialized_aggregate = redis_client.data[feature_key]
    first_payload_sha256 = hashlib.sha256(
        first_serialized_aggregate.encode("utf-8")
    ).hexdigest()
    first_aggregate = json.loads(first_serialized_aggregate)
    first_endpoint = first_aggregate["endpoint_payloads"]["liquidation_orders"]
    lineage_fields = (
        "event_time",
        "available_at",
        "ingested_at",
        "generated_at",
        "feature_cutoff",
        "feature_observation_hash",
    )
    first_lineage = {field: first_endpoint[field] for field in lineage_fields}
    assert first_result["deduplicated_refresh"] is False
    assert first_raw["expires_at"] == "2026-07-20T14:01:00Z"
    assert first_raw["ttl_seconds"] == 3360
    assert redis_client.ttls[raw_key] == 3360
    assert redis_client.ttls[feature_key] == 3360

    clock["now"] = "2026-07-20T13:10:00Z"
    duplicate_result = publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=spec,
        symbol="BTCUSDT",
        http_status=200,
        payload=payload,
        rate_limit_status={"requests_per_minute": 65},
    )
    duplicate_raw = json.loads(redis_client.data[raw_key])
    duplicate_serialized_aggregate = redis_client.data[feature_key]
    duplicate_aggregate = json.loads(duplicate_serialized_aggregate)
    duplicate_endpoint = duplicate_aggregate["endpoint_payloads"][
        "liquidation_orders"
    ]
    assert {
        field: duplicate_endpoint[field]
        for field in lineage_fields
    } == first_lineage
    assert duplicate_aggregate["feature_observation_hash"] == first_aggregate[
        "feature_observation_hash"
    ]
    assert duplicate_result["deduplicated_refresh"] is True
    assert duplicate_endpoint["source_age_seconds"] == 300.0
    assert duplicate_serialized_aggregate == first_serialized_aggregate
    assert hashlib.sha256(
        duplicate_serialized_aggregate.encode("utf-8")
    ).hexdigest() == first_payload_sha256
    assert "duplicate_refresh_count" not in duplicate_endpoint
    assert duplicate_raw["duplicate_refresh_count"] == 1
    assert duplicate_raw["last_observed_at"] == "2026-07-20T13:10:00Z"
    assert duplicate_raw["source_age_seconds"] == 300.0
    assert duplicate_raw["last_observed_source_age_seconds"] == 600.0
    assert duplicate_raw["ttl_seconds"] == 3360
    assert duplicate_raw["expires_at"] == first_raw["expires_at"]
    endpoint_status = json.loads(
        redis_client.data["v2:provider:coinglass:endpoint_status"]
    )
    status_row = endpoint_status["endpoints"]["liquidation_orders"]
    assert status_row["duplicate_refresh_count"] == 1
    assert status_row["last_observed_at"] == "2026-07-20T13:10:00Z"
    assert redis_client.ttls[raw_key] == 3060
    assert redis_client.ttls[feature_key] == 3060

    clock["now"] = "2026-07-20T14:05:00Z"
    next_result = publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=spec,
        symbol="BTCUSDT",
        http_status=200,
        payload=payload,
        rate_limit_status={"requests_per_minute": 65},
    )
    next_raw = json.loads(redis_client.data[raw_key])
    next_serialized_aggregate = redis_client.data[feature_key]
    next_aggregate = json.loads(next_serialized_aggregate)
    next_endpoint = next_aggregate["endpoint_payloads"]["liquidation_orders"]
    assert next_result["deduplicated_refresh"] is False
    assert next_endpoint["feature_cutoff"] == "2026-07-20T14:00:00Z"
    assert next_endpoint["available_at"] == "2026-07-20T14:05:00Z"
    assert next_serialized_aggregate != first_serialized_aggregate
    assert hashlib.sha256(next_serialized_aggregate.encode("utf-8")).hexdigest() != (
        first_payload_sha256
    )
    assert next_endpoint["feature_observation_hash"] != first_endpoint[
        "feature_observation_hash"
    ]
    assert next_aggregate["feature_observation_hash"] != first_aggregate[
        "feature_observation_hash"
    ]
    assert next_raw["expires_at"] == "2026-07-20T15:01:00Z"
    assert redis_client.ttls[raw_key] == 3360


def test_failed_optional_poll_does_not_restamp_unchanged_feature_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    clock = {"now": "2026-07-20T12:00:00Z"}
    monkeypatch.setattr(coinglass_publisher, "_now", lambda: clock["now"])
    feature_key = "v2:features:coinglass:BTCUSDT:1m"
    publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=_spec("funding_rate"),
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {
                    "symbol": "BTC",
                    "stablecoin_margin_list": [
                        {"exchange": "Binance", "funding_rate": 0.01}
                    ],
                }
            ]
        },
        rate_limit_status={"requests_per_minute": 65, "tokens_available": 64},
    )
    admitted_serialized = redis_client.data[feature_key]
    admitted_sha256 = hashlib.sha256(admitted_serialized.encode("utf-8")).hexdigest()

    clock["now"] = "2026-07-20T12:01:00Z"
    failed = publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=_spec("liquidation_heatmap_or_levels"),
        symbol="BTCUSDT",
        http_status=200,
        payload={"code": "401", "msg": "Upgrade plan"},
        rate_limit_status={"requests_per_minute": 65, "tokens_available": 12},
        error_class="IN_BODY_401_UPGRADE_PLAN",
    )

    after_failure_serialized = redis_client.data[feature_key]
    assert failed["actual_payload_present"] is False
    assert after_failure_serialized == admitted_serialized
    assert hashlib.sha256(after_failure_serialized.encode("utf-8")).hexdigest() == (
        admitted_sha256
    )


def test_publisher_does_not_reuse_legacy_rows_without_temporal_evidence() -> None:
    redis_client = FakeRedis()
    now = datetime.now(UTC)
    feature_key = "v2:features:coinglass:BTCUSDT:1m"
    redis_client.data[feature_key] = json.dumps(
        {
            "endpoint_payloads": {
                "funding_rate": {
                    "endpoint_id": "funding_rate",
                    "features": {"coinglass_funding_rate": 0.5},
                    "actual_payload_present": True,
                    "available_at": now.isoformat(),
                    "feature_cutoff": now.isoformat(),
                    "expires_at": (now + timedelta(minutes=10)).isoformat(),
                }
            }
        }
    )
    result = publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=_spec("liquidation_orders"),
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {
                    "time": _milliseconds(now + timedelta(minutes=1)),
                    "aggregated_short_liquidation_usd": 1000.0,
                    "aggregated_long_liquidation_usd": 500.0,
                }
            ]
        },
        rate_limit_status={"requests_per_minute": 65},
    )

    assert result["actual_payload_present"] is False
    aggregate = json.loads(redis_client.data[feature_key])
    assert aggregate["endpoint_payloads"] == {}
    assert aggregate["features"] == {}
    assert aggregate["decision_time_safe"] is False
    bridge_status = json.loads(
        redis_client.data["v2:provider:coinglass:feature_bridge_status"]
    )
    assert bridge_status["feature_bridge_ready"] is False


def test_publisher_does_not_reuse_historical_row_past_source_age_bound() -> None:
    redis_client = FakeRedis()
    now = datetime.now(UTC).replace(microsecond=0)
    bar_close = now - timedelta(seconds=3661)
    bar_open = bar_close - timedelta(hours=1)
    available_at = bar_close + timedelta(seconds=60)
    feature_key = "v2:features:coinglass:BTCUSDT:1m"
    redis_client.data[feature_key] = json.dumps(
        {
            "endpoint_payloads": {
                "liquidation_orders": {
                    "endpoint_id": "liquidation_orders",
                    "feature_family": "liquidation_orders",
                    "features": {"coinglass_liquidation_total_usd_1h": 1000.0},
                    "event_time": bar_open.isoformat(),
                    "available_at": available_at.isoformat(),
                    "feature_cutoff": bar_close.isoformat(),
                    "source_interval": "1h",
                    "bar_open": bar_open.isoformat(),
                    "bar_close": bar_close.isoformat(),
                    "is_closed": True,
                    "source_age_seconds": 60.0,
                    "max_source_age_seconds": 3660,
                    "source_fresh": True,
                    "temporal_contract_valid": True,
                    "expires_at": (now + timedelta(minutes=10)).isoformat(),
                    "actual_payload_present": True,
                }
            }
        }
    )

    publish_coinglass_result(
        redis_client,
        env={"COINGLASS_API_KEY": "secret"},
        spec=_spec("funding_rate"),
        symbol="BTCUSDT",
        http_status=200,
        payload={
            "data": [
                {
                    "symbol": "BTC",
                    "stablecoin_margin_list": [
                        {"exchange": "Binance", "funding_rate": 0.01}
                    ],
                }
            ]
        },
        rate_limit_status={"requests_per_minute": 65},
    )

    aggregate = json.loads(redis_client.data[feature_key])
    assert set(aggregate["endpoint_payloads"]) == {"funding_rate"}
    assert "coinglass_liquidation_total_usd_1h" not in aggregate["features"]
