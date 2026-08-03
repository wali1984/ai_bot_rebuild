from __future__ import annotations

import datetime as dt
import math

import pytest

from v2.backend.app.services.feature_pipeline_native.service import (
    FEATURE_CATEGORIES,
    FeaturePipelineNativeService,
    NativeFeatureInputs,
    compute_feature_snapshot,
    feature_snapshot_id,
)


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _ohlcv(n: int = 30, base: float = 100.0) -> tuple[dict, ...]:
    out = []
    for i in range(n):
        c = base + i * 0.5
        out.append({"open": c - 0.1, "high": c + 0.4, "low": c - 0.5, "close": c, "volume": 1000.0 + i})
    return tuple(out)


def test_snapshot_id_is_sha256_with_v2_prefix() -> None:
    fid = feature_snapshot_id("BTCUSDT", "1m", _now_iso(), {"a": 1, "b": 2})
    assert fid.startswith("v2_fsnap_")
    assert len(fid) == len("v2_fsnap_") + 64


def test_snapshot_id_deterministic_for_same_inputs() -> None:
    ts = _now_iso()
    a = feature_snapshot_id("BTCUSDT", "1m", ts, {"a": 1, "b": 2})
    b = feature_snapshot_id("BTCUSDT", "1m", ts, {"b": 2, "a": 1})
    assert a == b


def test_compute_with_full_inputs_emits_features_and_categories() -> None:
    inputs = NativeFeatureInputs(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        ohlcv_window=_ohlcv(60),
        ohlcv_window_age_seconds=10,
        bid_price=99.5,
        ask_price=100.5,
        bid_size=5.0,
        ask_size=5.0,
        orderbook_age_seconds=2,
        higher_tf_label="15m",
        higher_tf_close_window=tuple(100.0 + i for i in range(20)),
        higher_tf_age_seconds=30,
        funding_rate=0.0001,
        funding_age_seconds=120,
        open_interest=1_000_000.0,
        open_interest_prior=950_000.0,
        open_interest_age_seconds=60,
        last_liquidation_notional_24h=50_000.0,
        liquidation_age_seconds=120,
        paper_position_notional=1000.0,
        paper_position_entry_price=99.0,
        paper_position_age_seconds=120,
    )
    snap = compute_feature_snapshot(inputs)
    assert snap.feature_snapshot_id.startswith("v2_fsnap_")
    assert snap.feature_count >= 10
    for cat in (
        "ohlcv_derived",
        "ta_indicators",
        "multi_timeframe",
        "microstructure",
        "funding_oi_liquidation",
        "portfolio_aware",
        "freshness",
    ):
        assert cat in snap.categories_present
    assert snap.features.get("rsi_14") is not None
    assert snap.features.get("ema_12") is not None
    assert snap.features.get("ema_26") is not None
    assert snap.features.get("macd") is not None
    assert snap.features.get("bb_width_pct") is not None
    assert snap.features.get("atr_percentile") is not None
    assert 0.0 <= snap.features["atr_percentile"] <= 1.0
    assert snap.features.get("bid_ask_spread_bps") is not None
    assert snap.features.get("funding_rate") is not None
    assert snap.features.get("oi_change_pct") is not None
    assert snap.features.get("paper_position_present") == 1


def test_missing_inputs_produce_explicit_missing_flags_not_fabrication() -> None:
    inputs = NativeFeatureInputs(symbol="BTCUSDT", timeframe="1m", generated_utc=_now_iso())
    snap = compute_feature_snapshot(inputs)
    # without OHLCV we expect explicit missing flags rather than zeros
    assert "ohlcv_returns" in snap.missing_feature_flags
    assert "ohlcv_range_body" in snap.missing_feature_flags
    assert "ohlcv_true_range" in snap.missing_feature_flags
    assert "ohlcv_atr_percentile" in snap.missing_feature_flags
    assert "bid_ask_spread_bps" in snap.missing_feature_flags
    assert "funding_rate" in snap.missing_feature_flags
    # paper_position_present is always emitted as 0/1
    assert snap.features.get("paper_position_present") == 0


def test_stale_inputs_produce_stale_flags() -> None:
    inputs = NativeFeatureInputs(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        ohlcv_window=_ohlcv(5),
        ohlcv_window_age_seconds=9999,
        bid_price=99.5,
        ask_price=100.5,
        bid_size=1.0,
        ask_size=1.0,
        orderbook_age_seconds=9999,
        funding_rate=0.0001,
        funding_age_seconds=999999,
        open_interest=1_000_000.0,
        open_interest_prior=900_000.0,
        open_interest_age_seconds=999999,
        last_liquidation_notional_24h=10000.0,
        liquidation_age_seconds=999999,
        paper_position_notional=1000.0,
        paper_position_entry_price=99.0,
        paper_position_age_seconds=999999,
    )
    snap = compute_feature_snapshot(inputs)
    for name in ("ohlcv_window", "orderbook", "funding", "open_interest", "liquidation", "paper_position"):
        assert name in snap.stale_feature_flags


def test_short_ohlcv_window_does_not_compute_long_ta() -> None:
    inputs = NativeFeatureInputs(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        ohlcv_window=_ohlcv(5),
        ohlcv_window_age_seconds=5,
    )
    snap = compute_feature_snapshot(inputs)
    # ta_indicators category should be absent because closes < 26
    assert "ta_indicators" not in snap.categories_present
    for k in ("ema_12", "ema_26", "rsi_14", "macd", "bb_width_pct"):
        assert k in snap.missing_feature_flags


def test_orderbook_present_emits_microstructure_features() -> None:
    inputs = NativeFeatureInputs(
        symbol="BTCUSDT",
        timeframe="1m",
        generated_utc=_now_iso(),
        bid_price=99.95,
        ask_price=100.05,
        bid_size=10.0,
        ask_size=5.0,
        orderbook_age_seconds=1,
    )
    snap = compute_feature_snapshot(inputs)
    assert "microstructure" in snap.categories_present
    assert snap.features["bid_ask_spread_bps"] is not None
    assert snap.features["depth_imbalance"] is not None
    assert snap.features["micro_price"] is not None
    assert 0.0 <= snap.features["toxicity_proxy"] <= 1.0


def test_macd_components_present_for_long_window() -> None:
    closes_window = _ohlcv(60)
    inputs = NativeFeatureInputs(
        symbol="BTCUSDT", timeframe="1m", generated_utc=_now_iso(),
        ohlcv_window=closes_window, ohlcv_window_age_seconds=5,
    )
    snap = compute_feature_snapshot(inputs)
    assert snap.features["macd"] is not None
    assert snap.features["macd_signal"] is not None
    assert snap.features["macd_hist"] is not None


def test_service_status_payload_holds_safety_invariants_and_categories() -> None:
    svc = FeaturePipelineNativeService()
    s = svc.current_paper_only_status()
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["approves_live"] is False
    assert s["approves_canary"] is False
    assert s["approves_legacy_shutdown"] is False
    assert s["approves_redis_trim"] is False
    assert s["is_bridge_only"] is False
    assert s["reads_legacy_features_keys_as_authoritative"] is False
    assert s["writes_to_legacy_redis"] is False
    assert s["exchange_mutation_reachable"] is False
    assert s["feature_snapshot_id_emitted"] is True
    # every required category is listed
    for cat in FEATURE_CATEGORIES:
        assert cat in s["feature_categories_implemented"]
    # legacy SHA256 citations present
    cits = s["legacy_behavior_mapping"]
    assert "feature_pipeline.py" in cits
    assert len(cits["feature_pipeline.py"]["sha256"]) == 64


def test_service_compute_returns_full_schema_including_mapping() -> None:
    svc = FeaturePipelineNativeService()
    inputs = NativeFeatureInputs(
        symbol="BTCUSDT", timeframe="1m", generated_utc=_now_iso(),
        ohlcv_window=_ohlcv(30), ohlcv_window_age_seconds=5,
    )
    out = svc.compute(inputs)
    assert out["schema_version"] == "1.0.0"
    assert out["feature_snapshot_id"].startswith("v2_fsnap_")
    assert out["live_gate"] == "blocked_human_only"
    assert out["live_symbols"] == []
    assert "legacy_behavior_mapping" in out
    assert "feature_pipeline.py" in out["legacy_behavior_mapping"]


def test_no_legacy_redis_or_exchange_imports_in_service() -> None:
    """The service module must not import any redis or ccxt/binance client."""
    p = "v2/backend/app/services/feature_pipeline_native/service.py"
    text = open(p).read()
    # explicit forbids
    assert "import redis" not in text
    assert "from redis" not in text
    assert "import ccxt" not in text
    assert "from ccxt" not in text
    assert "import binance" not in text
