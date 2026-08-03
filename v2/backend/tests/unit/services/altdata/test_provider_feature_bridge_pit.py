"""Fail-closed PIT contracts for altdata provider inputs."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.cli import v2_altdata_confluence_loop as confluence_loop
from app.services.altdata import altdata_confluence_engine as confluence_engine
from app.services.altdata.altdata_confluence_engine import ProviderInput
from app.services.altdata.provider_feature_bridge import (
    load_coinank_input,
    load_coinglass_input,
    load_moralis_input,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str | bytes] = {}

    def get(self, key: str) -> str | bytes | None:
        return self.data.get(key)

    def set_payload(self, key: str, payload: dict[str, Any]) -> None:
        self.data[key] = json.dumps(payload)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
        self.data[key] = value
        return True


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _clocks() -> dict[str, str]:
    now = datetime.now(UTC)
    return {
        "feature_cutoff": _utc(now - timedelta(seconds=30)),
        "available_at": _utc(now - timedelta(seconds=2)),
        "generated_at": _utc(now - timedelta(seconds=1)),
    }


def _coinank_payload(*, consolidated: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": (
            "v2_coinank_symbol_intel_v1" if consolidated else "v2_coinank_symbol_feature_v1"
        ),
        "provider": "coinank",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **_clocks(),
        "actual_payload_present": True,
        "feature_eligible": True,
        "temporal_contract_valid": True,
        "trainer_consumable": True,
        "valid_for_prediction": True,
        "valid_for_paper": True,
        "features": {"coinank_long_short_ratio": 1.25},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }
    if consolidated:
        payload.update(
            {
                "consolidated_timeframe_context_only": True,
                "cross_timeframe_fallback_allowed": False,
            }
        )
    return payload


def _coinglass_payload() -> dict[str, Any]:
    return {
        "schema_version": "coinglass_aggregated_feature_payload_v2",
        "provider": "coinglass",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **_clocks(),
        "actual_payload_present": True,
        "provider_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "features": {"coinglass_funding_rate_zscore": -1.5},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _moralis_payload() -> dict[str, Any]:
    return {
        "schema_version": "moralis_feature_bridge_v1",
        "provider": "moralis",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **_clocks(),
        "actual_payload_present": True,
        "provider_ready": True,
        "feature_bridge_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "source_temporal_contract_valid": True,
        "trainer_isolation_active": False,
        "trainer_consumption_prerequisites_bound": True,
        "consumer_receipts_bound": True,
        "features": {"moralis_net_exchange_flow_usd": 500.0},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def test_coinank_accepts_exact_identity_flags_clocks_and_numeric_features() -> None:
    redis = FakeRedis()
    redis.set_payload("v2:features:coinank:BTCUSDT:1m", _coinank_payload())

    loaded = load_coinank_input(redis, "BTCUSDT", "1m")

    assert loaded.present is True
    assert loaded.stale is False
    assert loaded.features == {"coinank_long_short_ratio": 1.25}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actual_payload_present", 1),
        ("feature_eligible", "true"),
        ("temporal_contract_valid", 1),
        ("provider", "moralis"),
        ("symbol", "btcusdt"),
        ("timeframe", 1),
        ("timeframe", "5m"),
    ],
)
def test_coinank_rejects_coerced_or_mismatched_contract_fields(field: str, value: Any) -> None:
    redis = FakeRedis()
    payload = _coinank_payload()
    payload[field] = value
    redis.set_payload("v2:features:coinank:BTCUSDT:1m", payload)

    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False


@pytest.mark.parametrize(
    "invalid_clock",
    [
        "2026-07-20T12:00:00",
        "2026-07-20 12:00:00Z",
        "2026-07-20T08:00:00-04:00",
        1_753_011_200,
    ],
)
def test_coinank_rejects_non_strict_aware_utc_rfc3339_clocks(
    invalid_clock: Any,
) -> None:
    redis = FakeRedis()
    payload = _coinank_payload()
    payload["available_at"] = invalid_clock
    redis.set_payload("v2:features:coinank:BTCUSDT:1m", payload)

    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False


def test_coinank_rejects_feature_cutoff_after_available_at() -> None:
    redis = FakeRedis()
    payload = _coinank_payload()
    payload["feature_cutoff"] = payload["generated_at"]
    payload["available_at"] = _utc(datetime.now(UTC) - timedelta(seconds=2))
    redis.set_payload("v2:features:coinank:BTCUSDT:1m", payload)

    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False


def test_coinank_rejects_source_availability_after_feature_generation() -> None:
    redis = FakeRedis()
    payload = _coinank_payload()
    payload["available_at"] = _utc(datetime.now(UTC) - timedelta(seconds=1))
    payload["generated_at"] = _utc(datetime.now(UTC) - timedelta(seconds=2))
    redis.set_payload("v2:features:coinank:BTCUSDT:1m", payload)

    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False


@pytest.mark.parametrize("value", [True, "1.25", float("nan"), float("inf")])
def test_coinank_rejects_coerced_or_nonfinite_feature_values(value: Any) -> None:
    redis = FakeRedis()
    payload = _coinank_payload()
    payload["features"] = {"coinank_long_short_ratio": value}
    redis.set_payload("v2:features:coinank:BTCUSDT:1m", payload)

    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False


def test_coinank_consolidated_fallback_requires_same_timeframe_contract() -> None:
    redis = FakeRedis()
    payload = _coinank_payload(consolidated=True)
    redis.set_payload("v2:coinank:symbol:BTCUSDT", payload)

    assert load_coinank_input(redis, "BTCUSDT", "1m").present is True

    payload["cross_timeframe_fallback_allowed"] = 0
    redis.set_payload("v2:coinank:symbol:BTCUSDT", payload)
    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False

    payload = _coinank_payload(consolidated=True)
    payload["timeframe"] = "4h"
    redis.set_payload("v2:coinank:symbol:BTCUSDT", payload)
    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False


def test_coinglass_requires_exact_temporal_and_identity_contract() -> None:
    redis = FakeRedis()
    payload = _coinglass_payload()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is True

    payload["decision_time_safe"] = 1
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)
    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False


def test_provider_loader_returns_exact_engine_type_in_each_package_namespace() -> None:
    from v2.backend.app.services.altdata import (
        altdata_confluence_engine as v2_confluence_engine,
    )
    from v2.backend.app.services.altdata import (
        provider_feature_bridge as v2_provider_bridge,
    )

    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload())

    app_loaded = load_coinglass_input(redis, "BTCUSDT", "1m")
    assert type(app_loaded) is ProviderInput
    app_confluence = confluence_engine.build_confluence(
        symbol="BTCUSDT",
        timeframe="1m",
        coinglass=app_loaded,
        moralis=ProviderInput(provider="moralis", present=False),
        generated_utc=_utc(datetime.now(UTC) - timedelta(seconds=3)),
    )
    assert app_confluence["providers_invalid"] == []

    v2_loaded = v2_provider_bridge.load_coinglass_input(redis, "BTCUSDT", "1m")
    assert type(v2_loaded) is v2_confluence_engine.ProviderInput
    v2_confluence = v2_confluence_engine.build_confluence(
        symbol="BTCUSDT",
        timeframe="1m",
        coinglass=v2_loaded,
        moralis=v2_confluence_engine.ProviderInput(
            provider="moralis",
            present=False,
        ),
        generated_utc=_utc(datetime.now(UTC) - timedelta(seconds=3)),
    )
    assert v2_confluence["providers_invalid"] == []


def test_coinglass_rejects_malformed_feature_flag_collections() -> None:
    redis = FakeRedis()
    payload = _coinglass_payload()
    payload["missing_feature_flags"] = "coinglass_missing"
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False

    payload = _coinglass_payload()
    del payload["stale_feature_flags"]
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)
    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False


def test_moralis_does_not_merge_signal_snapshot_into_canonical_hold() -> None:
    redis = FakeRedis()
    held = _moralis_payload()
    held.update(
        {
            "actual_payload_present": False,
            "provider_ready": False,
            "feature_bridge_ready": False,
            "decision_time_safe": False,
            "temporal_contract_valid": False,
            "trainer_isolation_active": True,
            "trainer_consumption_prerequisites_bound": False,
            "consumer_receipts_bound": False,
            "features": {},
        }
    )
    redis.set_payload("v2:features:moralis:BTCUSDT:1m", held)
    redis.set_payload("v2:smart_money:signals:BTCUSDT", _moralis_payload())

    assert load_moralis_input(redis, "BTCUSDT", "1m").present is False


def test_moralis_release_declarations_do_not_authenticate_consumption() -> None:
    redis = FakeRedis()
    redis.set_payload("v2:smart_money:signals:BTCUSDT", _moralis_payload())

    loaded = load_moralis_input(redis, "BTCUSDT", "1m")

    assert loaded.present is False
    assert loaded.features == {}


@pytest.mark.parametrize(
    "hold_field",
    ["trainer_consumable", "valid_for_prediction", "valid_for_paper"],
)
def test_coinank_respects_explicit_downstream_holds(hold_field: str) -> None:
    redis = FakeRedis()
    payload = _coinank_payload()
    payload[hold_field] = False
    redis.set_payload("v2:features:coinank:BTCUSDT:1m", payload)

    assert load_coinank_input(redis, "BTCUSDT", "1m").present is False


def test_loader_rejects_invalid_utf8_instead_of_replacement_decoding() -> None:
    redis = FakeRedis()
    redis.data["v2:features:coinglass:BTCUSDT:1m"] = (
        b'{"schema_version":"coinglass_aggregated_feature_payload_v2",'
        b'"provider":"coinglass","symbol":"BTCUSDT","timeframe":"1m",'
        b'"features":{"bad\xffname":1}}'
    )

    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False


def test_unhashable_schema_is_totally_rejected_without_exception() -> None:
    redis = FakeRedis()
    payload = _coinglass_payload()
    payload["schema_version"] = []
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False


def test_extreme_integer_is_totally_rejected_without_overflow() -> None:
    redis = FakeRedis()
    payload = _coinglass_payload()
    payload["features"] = {"coinglass_funding_rate_zscore": 10**400}
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False


def test_feature_missing_mask_overlap_is_rejected_before_use() -> None:
    redis = FakeRedis()
    payload = _coinglass_payload()
    payload["missing_feature_flags"] = ["coinglass_funding_rate_zscore"]
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False


def test_feature_stale_mask_overlap_is_rejected_before_use() -> None:
    redis = FakeRedis()
    payload = _coinglass_payload()
    payload["stale_feature_flags"] = ["coinglass_funding_rate_zscore"]
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    assert load_coinglass_input(redis, "BTCUSDT", "1m").present is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trainer_isolation_active", 0),
        ("trainer_consumption_prerequisites_bound", 1),
        ("consumer_receipts_bound", "true"),
        ("source_temporal_contract_valid", 1),
    ],
)
def test_moralis_rejects_coerced_release_or_source_flags(field: str, value: Any) -> None:
    redis = FakeRedis()
    payload = _moralis_payload()
    payload[field] = value
    redis.set_payload("v2:features:moralis:BTCUSDT:1m", payload)

    assert load_moralis_input(redis, "BTCUSDT", "1m").present is False


def test_confluence_publication_orders_cutoff_generated_and_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis()
    cycle_started = datetime(2026, 7, 20, 12, 0, 0, tzinfo=UTC)
    provider_read_completed = cycle_started + timedelta(microseconds=500_000)
    composite_generated = cycle_started + timedelta(microseconds=750_000)
    published_available = cycle_started + timedelta(seconds=1)

    class PublisherClock:
        values = iter((cycle_started, published_available))

        @classmethod
        def now(cls, tz: object) -> datetime:  # noqa: ARG003
            return next(cls.values)

    provider_reads: list[str] = []

    def read_coinglass(_redis: Any, _symbol: str, _timeframe: str) -> ProviderInput:
        provider_reads.append("coinglass")
        clock = _utc(provider_read_completed)
        return ProviderInput(
            provider="coinglass",
            present=True,
            features={"coinglass_funding_rate_zscore": -1.5},
            feature_cutoff=clock,
            available_at=clock,
            generated_at=clock,
        )

    def read_missing(
        _redis: Any,
        _symbol: str,
        _timeframe: str,
        *,
        provider: str,
    ) -> ProviderInput:
        provider_reads.append(provider)
        return ProviderInput(provider=provider, present=False)

    def capture_after_reads() -> datetime:
        assert provider_reads == ["coinglass", "moralis", "coinank"]
        return composite_generated

    monkeypatch.setattr(confluence_loop, "datetime", PublisherClock)
    monkeypatch.setattr(confluence_loop, "load_coinglass_input", read_coinglass)
    monkeypatch.setattr(
        confluence_loop,
        "load_moralis_input",
        lambda redis_client, symbol, timeframe: read_missing(
            redis_client,
            symbol,
            timeframe,
            provider="moralis",
        ),
    )
    monkeypatch.setattr(
        confluence_loop,
        "load_coinank_input",
        lambda redis_client, symbol, timeframe: read_missing(
            redis_client,
            symbol,
            timeframe,
            provider="coinank",
        ),
    )
    monkeypatch.setattr(confluence_engine, "_utc_now", capture_after_reads)
    monkeypatch.setattr(
        confluence_loop,
        "publish_provider_consumption_status",
        lambda _redis: {},
    )

    confluence_loop.run_once(redis, symbols=["BTCUSDT"], timeframe="1m")

    published = json.loads(redis.data["v2:altdata:confluence:BTCUSDT:1m"])
    cutoff = datetime.fromisoformat(published["feature_cutoff"].replace("Z", "+00:00"))
    generated_at = datetime.fromisoformat(published["generated_at"])
    available_at = datetime.fromisoformat(published["available_at"])
    assert cutoff <= generated_at <= available_at
    assert cutoff == provider_read_completed
    assert generated_at == composite_generated
    assert published["decision_time_safe"] is True
