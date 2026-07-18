from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    V2UnifiedFeatureTensorBuilder,
)

DECISION_TIME = "2026-07-18T12:00:00Z"
AVAILABLE_AT = "2026-07-18T11:59:59Z"


def _causal(payload: dict[str, object]) -> dict[str, object]:
    return {**payload, "available_at": AVAILABLE_AT}


def test_advanced_indicator_fields_enter_tensor_with_masks() -> None:
    tensor = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="5m",
        decision_time=DECISION_TIME,
        payloads={
            "features_latest": _causal(
                {"feature_snapshot_id": "snap-advanced", "features": {}}
            ),
            "ohlcv": {
                "open": 100,
                "high": 110,
                "low": 99,
                "close": 108,
                "volume": 1000,
                "candle_closed_confirmed": True,
                "candle_close_time": AVAILABLE_AT,
                "available_at": AVAILABLE_AT,
            },
            "fvg": _causal({
                "bullish_fvg_present": True,
                "fvg_size_bps": 18.0,
                "distance_to_fvg_bps": -5.0,
                "fvg_retest_confirmed": True,
            }),
            "market_structure": _causal({
                "bos_direction": "up",
                "choch_direction": None,
                "order_block_strength": 0.7,
                "premium_discount_zone": "discount",
            }),
            "liquidity_zones": _causal({
                "nearest_liquidity_above": 112.0,
                "distance_to_liquidity_above_bps": 37.0,
                "sweep_risk_long_side": 0.2,
            }),
            "vwap_features": _causal({
                "session_vwap": 104.0,
                "distance_to_vwap_bps": 25.0,
                "vwap_slope": 3.0,
            }),
            "volume_profile": _causal({
                "volume_profile_poc": 105.0,
                "high_volume_node_above": 109.0,
            }),
            "cvd_features": _causal({"cvd": 10.0, "cvd_slope": 2.0}),
            "advanced_trade_tape": _causal({
                "trade_imbalance": 0.4,
                "large_trade_cluster": 1,
                "sweep_prints": 0,
            }),
        },
    )

    by_name = {name: i for i, name in enumerate(tensor.feature_names)}
    assert tensor.values[by_name["bullish_fvg_present"]] == 1.0
    assert tensor.values[by_name["bos_direction_code"]] == 1.0
    assert tensor.values[by_name["premium_discount_zone_code"]] == -1.0
    assert tensor.values[by_name["distance_to_vwap_bps"]] == 25.0
    assert tensor.values[by_name["trade_imbalance"]] == 0.4
    assert tensor.missing_mask[by_name["bearish_fvg_present"]] == 1
