from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    FEATURE_DECLARATIONS,
    ORDERED_FEATURE_NAMES,
    build_serving_feature_vector,
    feature_abi_sha256,
    feature_builder_sha256,
    serving_feature_abi_v2,
)

NOW = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)


def _record() -> dict:
    features = {name: 1.0 for name in ORDERED_FEATURE_NAMES}
    features.update(
        {
            "close": 100.0,
            "open": 99.0,
            "high": 101.0,
            "low": 98.0,
            "ema_12": 100.5,
            "ema_26": 99.5,
            "rsi_14": 55.0,
        }
    )
    return {
        "timeframe": "5m",
        "features": features,
        "feature_cutoff": (NOW - timedelta(minutes=2)).isoformat().replace("+00:00", "Z"),
        "record_available_at": (NOW - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "CLOSED_KLINE_FILTER_V1",
        "latest_unclosed_exclusion_decision_time_ms": int(
            (NOW - timedelta(seconds=30)).timestamp() * 1000
        ),
        "latest_closed_kline_close_time_ms": int((NOW - timedelta(minutes=1)).timestamp() * 1000),
    }


def _cost() -> dict:
    return {
        "source_event_time": (NOW - timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
        "producer_generated_at": (NOW - timedelta(seconds=9)).isoformat().replace("+00:00", "Z"),
        "record_available_at": (NOW - timedelta(seconds=8)).isoformat().replace("+00:00", "Z"),
        "expires_at": (NOW + timedelta(seconds=30)).isoformat().replace("+00:00", "Z"),
        "fee_bps_per_side": 5.0,
        "slippage_bps_per_side": 0.2,
        "funding_bps_at_decision_time": 0.3,
        "spread_bps": 0.1,
        "source_readback_verified": True,
    }


def test_abi_is_complete_deterministic_and_all_required() -> None:
    abi = serving_feature_abi_v2()
    assert abi["schema_version"] == "ServingFeatureABIV2"
    assert [item.position for item in FEATURE_DECLARATIONS] == list(range(29))
    assert tuple(abi["ordered_feature_names"]) == ORDERED_FEATURE_NAMES
    assert all(item.required and item.optional_reason is None for item in FEATURE_DECLARATIONS)
    assert len(feature_abi_sha256()) == 64
    assert len(feature_builder_sha256()) == 64


def test_same_builder_binds_exact_cost_and_never_zero_fills() -> None:
    vector = build_serving_feature_vector(
        feature_record=_record(),
        exact_cost_record=_cost(),
        decision_time=NOW.isoformat().replace("+00:00", "Z"),
    )
    assert vector.ordered_feature_names == ORDERED_FEATURE_NAMES
    assert vector.values[ORDERED_FEATURE_NAMES.index("fee_bps")] == 0.5
    assert vector.missing_mask == (0,) * len(ORDERED_FEATURE_NAMES)
    missing = _record()
    del missing["features"]["volume"]
    with pytest.raises(ValueError, match="REQUIRED_FEATURE_MISSING:volume"):
        build_serving_feature_vector(
            feature_record=missing,
            exact_cost_record=_cost(),
            decision_time=NOW.isoformat().replace("+00:00", "Z"),
        )


def test_builder_rejects_future_available_feature_and_unfinalized_candle() -> None:
    future = _record()
    future["record_available_at"] = (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="POINT_IN_TIME_CLOCK_ORDER_INVALID"):
        build_serving_feature_vector(
            feature_record=future,
            exact_cost_record=_cost(),
            decision_time=NOW.isoformat().replace("+00:00", "Z"),
        )
    unfinalized = _record()
    unfinalized["latest_unclosed_kline_excluded"] = False
    with pytest.raises(ValueError, match="LATEST_UNCLOSED_KLINE_NOT_EXCLUDED"):
        build_serving_feature_vector(
            feature_record=unfinalized,
            exact_cost_record=_cost(),
            decision_time=NOW.isoformat().replace("+00:00", "Z"),
        )


def test_builder_rejects_unverified_or_future_exact_cost() -> None:
    unverified = _cost()
    unverified["source_readback_verified"] = False
    with pytest.raises(ValueError, match="EXACT_COST_READBACK_UNVERIFIED"):
        build_serving_feature_vector(
            feature_record=_record(),
            exact_cost_record=unverified,
            decision_time=NOW.isoformat().replace("+00:00", "Z"),
        )
    expired = _cost()
    expired["expires_at"] = (NOW - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="EXACT_COST_CLOCK_ORDER_INVALID"):
        build_serving_feature_vector(
            feature_record=_record(),
            exact_cost_record=expired,
            decision_time=NOW.isoformat().replace("+00:00", "Z"),
        )
