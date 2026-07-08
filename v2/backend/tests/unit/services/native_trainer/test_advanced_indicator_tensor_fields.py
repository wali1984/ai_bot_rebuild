from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    V2UnifiedFeatureTensorBuilder,
)


def test_advanced_indicator_fields_enter_tensor_with_masks() -> None:
    tensor = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="5m",
        payloads={
            "features_latest": {"feature_snapshot_id": "snap-advanced", "features": {}},
            "ohlcv": {
                "open": 100,
                "high": 110,
                "low": 99,
                "close": 108,
                "volume": 1000,
                "candle_closed_confirmed": True,
            },
            "fvg": {
                "bullish_fvg_present": True,
                "fvg_size_bps": 18.0,
                "distance_to_fvg_bps": -5.0,
                "fvg_retest_confirmed": True,
            },
            "market_structure": {
                "bos_direction": "up",
                "choch_direction": None,
                "order_block_strength": 0.7,
                "premium_discount_zone": "discount",
            },
            "liquidity_zones": {
                "nearest_liquidity_above": 112.0,
                "distance_to_liquidity_above_bps": 37.0,
                "sweep_risk_long_side": 0.2,
            },
            "vwap_features": {
                "session_vwap": 104.0,
                "distance_to_vwap_bps": 25.0,
                "vwap_slope": 3.0,
            },
            "volume_profile": {
                "volume_profile_poc": 105.0,
                "high_volume_node_above": 109.0,
            },
            "cvd_features": {"cvd": 10.0, "cvd_slope": 2.0},
            "advanced_trade_tape": {
                "trade_imbalance": 0.4,
                "large_trade_cluster": 1,
                "sweep_prints": 0,
            },
        },
    )

    by_name = {name: i for i, name in enumerate(tensor.feature_names)}
    assert tensor.values[by_name["bullish_fvg_present"]] == 1.0
    assert tensor.values[by_name["bos_direction_code"]] == 1.0
    assert tensor.values[by_name["premium_discount_zone_code"]] == -1.0
    assert tensor.values[by_name["distance_to_vwap_bps"]] == 25.0
    assert tensor.values[by_name["trade_imbalance"]] == 0.4
    assert tensor.missing_mask[by_name["bearish_fvg_present"]] == 1
