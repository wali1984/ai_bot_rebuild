"""Adversarial tests for canonical alt-data confluence reconstruction."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import pytest
from app.services.altdata import altdata_confluence_engine, canonical_confluence_consumer
from app.services.altdata.altdata_confluence_engine import ProviderInput
from app.services.altdata.canonical_confluence_consumer import (
    BOUNDARY_SCHEMA_VERSION,
    CanonicalConfluenceContractError,
    rebuild_canonical_confluence,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str | bytes] = {}
        self.read_keys: list[str] = []

    def get(self, key: str) -> str | bytes | None:
        self.read_keys.append(key)
        return self.data.get(key)

    def set_payload(self, key: str, payload: dict[str, Any]) -> None:
        self.data[key] = json.dumps(payload)


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@pytest.fixture
def base_time(monkeypatch: pytest.MonkeyPatch) -> datetime:
    base = datetime.now(UTC)
    ticks = count()

    def monotonic_clock() -> datetime:
        return base + timedelta(milliseconds=next(ticks))

    monkeypatch.setattr(canonical_confluence_consumer, "_utc_now", monotonic_clock)
    monkeypatch.setattr(altdata_confluence_engine, "_utc_now", monotonic_clock)
    return base


def _clocks(base: datetime, *, available_age_seconds: float = 2.0) -> dict[str, str]:
    available_at = base - timedelta(seconds=available_age_seconds)
    return {
        "feature_cutoff": _utc(available_at - timedelta(seconds=1)),
        "available_at": _utc(available_at),
        "generated_at": _utc(available_at + timedelta(milliseconds=500)),
    }


def _coinglass_payload(base: datetime) -> dict[str, Any]:
    return {
        "schema_version": "coinglass_aggregated_feature_payload_v2",
        "provider": "coinglass",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **_clocks(base),
        "actual_payload_present": True,
        "provider_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "features": {"coinglass_funding_rate_zscore": -1.5},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _coinank_payload(base: datetime) -> dict[str, Any]:
    return {
        "schema_version": "v2_coinank_symbol_feature_v1",
        "provider": "coinank",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **_clocks(base),
        "actual_payload_present": True,
        "feature_eligible": True,
        "temporal_contract_valid": True,
        "trainer_consumable": True,
        "valid_for_prediction": True,
        "valid_for_paper": True,
        "features": {"coinank_funding_rate": -0.0002},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _moralis_payload(base: datetime) -> dict[str, Any]:
    return {
        "schema_version": "moralis_feature_bridge_v1",
        "provider": "moralis",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        **_clocks(base),
        "actual_payload_present": True,
        "provider_ready": True,
        "feature_bridge_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "source_temporal_contract_valid": True,
        "trainer_isolation_active": False,
        "trainer_consumption_prerequisites_bound": True,
        "consumer_receipts_bound": True,
        "features": {"moralis_net_exchange_flow_usd": -2_000_000.0},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _seed_fresh_providers(redis: FakeRedis, base: datetime) -> None:
    redis.set_payload(
        "v2:features:coinglass:BTCUSDT:1m",
        _coinglass_payload(base),
    )
    redis.set_payload(
        "v2:features:coinank:BTCUSDT:1m",
        _coinank_payload(base),
    )
    redis.set_payload(
        "v2:features:moralis:BTCUSDT:1m",
        _moralis_payload(base),
    )


def _assert_identity_is_not_authority(identity: dict[str, Any]) -> None:
    assert identity["algorithm"] == "sha256"
    assert len(identity["digest"]) == 64
    int(identity["digest"], 16)
    assert identity["role"] == "non_authoritative_content_identity_only"
    assert identity["authenticates_source"] is False
    assert identity["authorizes_consumption"] is False
    assert identity["is_cryptographic_proof"] is False
    assert identity["is_signature"] is False


def test_rebuilds_fresh_confluence_with_explicit_pit_clocks_and_lineage(
    base_time: datetime,
) -> None:
    redis = FakeRedis()
    _seed_fresh_providers(redis, base_time)

    result = rebuild_canonical_confluence(redis, symbol="BTCUSDT", timeframe="1m")

    assert result["schema_version"] == "altdata_confluence_v1"
    assert result["boundary_schema_version"] == BOUNDARY_SCHEMA_VERSION
    assert result["symbol"] == "BTCUSDT"
    assert result["timeframe"] == "1m"
    assert result["reconstructed_from_canonical_provider_inputs"] is True
    assert result["cached_confluence_consumed"] is False
    assert result["providers_loaded_fresh"] == ["coinank", "coinglass"]
    assert result["providers_present"] == ["coinank", "coinglass"]
    assert result["providers_missing"] == ["moralis"]
    assert result["actual_payload_present"] is True
    assert result["decision_time_safe"] is True
    assert result["features"]["altdata_confluence_long_score"] is not None

    cycle_started_at = _parse(result["cycle_started_at"])
    observed_at = _parse(result["observed_at"])
    engine_generated_at = _parse(result["confluence_engine_generated_at"])
    generated_at = _parse(result["generated_at"])
    available_at = _parse(result["available_at"])
    assert cycle_started_at <= observed_at <= engine_generated_at <= generated_at <= available_at
    assert _parse(result["feature_cutoff"]) <= observed_at
    assert result["generated_utc"] == result["generated_at"]

    for provider in ("coinglass", "moralis", "coinank"):
        lineage = result["provider_lineage"][provider]
        assert lineage["provider"] == provider
        _assert_identity_is_not_authority(lineage["content_identity"])
    assert result["provider_lineage"]["moralis"]["masked"] is True
    assert result["provider_lineage"]["moralis"]["canonical_loader_present"] is False
    _assert_identity_is_not_authority(result["content_identity"])
    json.dumps(result, allow_nan=False, sort_keys=True)


def test_all_unavailable_providers_are_none_masked_including_legacy_hedge_floor(
    base_time: datetime,  # noqa: ARG001
) -> None:
    result = rebuild_canonical_confluence(FakeRedis(), symbol="BTCUSDT", timeframe="1m")

    assert result["actual_payload_present"] is False
    assert result["decision_time_safe"] is False
    assert result["heartbeat_only"] is True
    assert all(value is None for value in result["features"].values())
    assert set(result["missing_feature_flags"]) == set(result["features"])
    assert result["features"]["altdata_hedge_required_score"] is None
    assert all(row["masked"] is True for row in result["provider_lineage"].values())


def test_stale_provider_remains_source_visible_but_cannot_contribute_or_zero_fill(
    base_time: datetime,
) -> None:
    redis = FakeRedis()
    stale = _coinglass_payload(base_time)
    stale.update(_clocks(base_time, available_age_seconds=601.0))
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", stale)

    result = rebuild_canonical_confluence(redis, symbol="BTCUSDT", timeframe="1m")

    assert result["providers_stale"] == ["coinglass"]
    assert result["providers_present"] == []
    assert all(value is None for value in result["features"].values())
    lineage = result["provider_lineage"]["coinglass"]
    assert lineage["canonical_loader_present"] is True
    assert lineage["canonical_loader_stale"] is True
    assert lineage["admitted_as_fresh_input"] is False
    assert lineage["mask_reason"] == "stale_at_consumer_observation"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload, base: payload.update(schema_version="coinglass_legacy_v1"),
        lambda payload, base: payload.update(provider="forged"),
        lambda payload, base: payload.update(symbol="ETHUSDT"),
        lambda payload, base: payload.update(timeframe="5m"),
        lambda payload, base: payload.update(decision_time_safe=1),
        lambda payload, base: payload.update(
            features={"coinglass_funding_rate_zscore": float("nan")}
        ),
        lambda payload, base: payload.update(
            feature_cutoff=_utc(base + timedelta(hours=1)),
            available_at=_utc(base + timedelta(hours=1, seconds=1)),
            generated_at=_utc(base + timedelta(hours=1, seconds=2)),
        ),
    ],
    ids=(
        "schema",
        "provider-identity",
        "symbol-identity",
        "timeframe-identity",
        "coerced-bool",
        "nan",
        "future-clocks",
    ),
)
def test_adversarial_source_payloads_are_masked_by_the_canonical_bridge(
    base_time: datetime,
    mutate: Callable[[dict[str, Any], datetime], None],
) -> None:
    redis = FakeRedis()
    payload = _coinglass_payload(base_time)
    mutate(payload, base_time)
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", payload)

    result = rebuild_canonical_confluence(redis, symbol="BTCUSDT", timeframe="1m")

    assert result["provider_lineage"]["coinglass"]["canonical_loader_present"] is False
    assert result["provider_lineage"]["coinglass"]["masked"] is True
    assert result["providers_present"] == []
    assert all(value is None for value in result["features"].values())


@pytest.mark.parametrize(
    ("forged", "reason"),
    [
        (
            ProviderInput(
                provider="forged",
                present=True,
                features={"coinglass_funding_rate_zscore": -1.0},
                feature_cutoff="2026-01-01T00:00:00Z",
                available_at="2026-01-01T00:00:00Z",
                generated_at="2026-01-01T00:00:00Z",
            ),
            "provider_identity_invalid",
        ),
        (
            ProviderInput(
                provider="coinglass",
                present=True,
                features={"coinglass_funding_rate_zscore": True},  # type: ignore[dict-item]
                feature_cutoff="2026-01-01T00:00:00Z",
                available_at="2026-01-01T00:00:00Z",
                generated_at="2026-01-01T00:00:00Z",
            ),
            "provider_feature_field_invalid",
        ),
    ],
    ids=("identity", "bool-feature"),
)
def test_boundary_revalidates_even_a_forged_bridge_result(
    base_time: datetime,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    forged: ProviderInput,
    reason: str,
) -> None:
    monkeypatch.setattr(
        canonical_confluence_consumer.provider_feature_bridge,
        "load_coinglass_input",
        lambda *_args: forged,
    )

    result = rebuild_canonical_confluence(FakeRedis(), symbol="BTCUSDT", timeframe="1m")

    lineage = result["provider_lineage"]["coinglass"]
    assert lineage["boundary_contract_valid"] is False
    assert lineage["mask_reason"] == reason
    assert lineage["canonical_loader_present"] is False
    assert all(value is None for value in result["features"].values())


def test_forged_cached_confluence_is_never_read_or_merged(base_time: datetime) -> None:
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base_time))
    redis.set_payload(
        "v2:altdata:confluence:BTCUSDT:1m",
        {
            "schema_version": "altdata_confluence_v1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "actual_payload_present": True,
            "decision_time_safe": True,
            "features": {"altdata_trade_block_score": 1.0},
        },
    )

    result = rebuild_canonical_confluence(redis, symbol="BTCUSDT", timeframe="1m")

    assert "v2:altdata:confluence:BTCUSDT:1m" not in redis.read_keys
    assert result["features"]["altdata_trade_block_score"] is None
    assert result["cached_confluence_consumed"] is False


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda row, base: row.update(schema_version="altdata_confluence_v0"), "schema"),
        (lambda row, base: row.update(symbol="ETHUSDT"), "symbol"),
        (
            lambda row, base: row["features"].update(
                altdata_derivatives_pressure_score=True
            ),
            "feature_type",
        ),
        (
            lambda row, base: row["features"].update(
                altdata_derivatives_pressure_score=float("nan")
            ),
            "feature_value",
        ),
        (
            lambda row, base: row.update(
                generated_at=_utc(base + timedelta(days=1)),
                generated_utc=_utc(base + timedelta(days=1)),
            ),
            "clock_order",
        ),
    ],
    ids=("schema", "symbol", "bool-feature", "nan-feature", "future-clock"),
)
def test_reconstructed_envelope_is_independently_validated(
    base_time: datetime,
    monkeypatch: pytest.MonkeyPatch,
    mutation: Callable[[dict[str, Any], datetime], None],
    reason: str,
) -> None:
    redis = FakeRedis()
    redis.set_payload("v2:features:coinglass:BTCUSDT:1m", _coinglass_payload(base_time))
    real_build = altdata_confluence_engine.build_confluence

    def forged_build(**kwargs: Any) -> dict[str, Any]:
        row = copy.deepcopy(real_build(**kwargs))
        mutation(row, base_time)
        return row

    monkeypatch.setattr(altdata_confluence_engine, "build_confluence", forged_build)

    with pytest.raises(CanonicalConfluenceContractError, match=reason):
        rebuild_canonical_confluence(redis, symbol="BTCUSDT", timeframe="1m")


@pytest.mark.parametrize(
    ("symbol", "timeframe", "reason"),
    [
        ("btcusdt", "1m", "symbol_invalid"),
        ("BTC:USDT", "1m", "symbol_invalid"),
        ("BTCUSDT", " 1m", "timeframe_invalid"),
        ("BTCUSDT", "0m", "timeframe_invalid"),
        ("BTCUSDT", True, "timeframe_invalid"),
    ],
)
def test_call_identity_is_exact_and_never_coerced_before_redis_read(
    base_time: datetime,  # noqa: ARG001
    symbol: Any,
    timeframe: Any,
    reason: str,
) -> None:
    redis = FakeRedis()

    with pytest.raises(CanonicalConfluenceContractError, match=reason):
        rebuild_canonical_confluence(redis, symbol=symbol, timeframe=timeframe)

    assert redis.read_keys == []


def test_identity_hashes_are_stable_across_boundary_clock_changes(base_time: datetime) -> None:
    redis = FakeRedis()
    _seed_fresh_providers(redis, base_time)

    first = rebuild_canonical_confluence(redis, symbol="BTCUSDT", timeframe="1m")
    second = rebuild_canonical_confluence(redis, symbol="BTCUSDT", timeframe="1m")

    assert first["generated_at"] != second["generated_at"]
    assert first["content_identity"]["digest"] == second["content_identity"]["digest"]
    for provider in ("coinglass", "moralis", "coinank"):
        assert (
            first["provider_lineage"][provider]["content_identity"]["digest"]
            == second["provider_lineage"][provider]["content_identity"]["digest"]
        )
