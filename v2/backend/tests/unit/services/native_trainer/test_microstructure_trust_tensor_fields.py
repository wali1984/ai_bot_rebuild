from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    V2UnifiedFeatureTensorBuilder,
)


def test_microstructure_trust_features_are_tensor_fields_without_neutral_default() -> None:
    builder = V2UnifiedFeatureTensorBuilder()
    tensor = builder.build(
        symbol="BTCUSDT",
        timeframe="1m",
        payloads={
            "features_latest": {"feature_snapshot_id": "snap-micro", "features": {}},
            "ohlcv": {
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 10.0,
                "quote_volume": 1000.0,
                "candle_closed_confirmed": True,
            },
            "orderbook": {
                "best_bid": 100.0,
                "best_ask": 100.2,
                "bids": [[100.0, 2.0]],
                "asks": [[100.2, 2.0]],
            },
            "microstructure": {
                "microstructure_trust_score": 0.42,
                "feed_latency_ms": 55.0,
                "spread_instability": 0.2,
                "depth_persistence": 0.4,
                "cancel_pressure": 0.7,
                "book_trade_divergence": 1.0,
                "cross_venue_confirmation": 0.3,
                "sweep_risk": 0.8,
                "post_sweep_reversal_probability": 0.6,
                "liquidation_cascade_risk": 0.9,
                "realized_slippage_error": 3.0,
            },
        },
    )

    values = dict(zip(tensor.feature_names, tensor.values, strict=True))
    missing = dict(zip(tensor.feature_names, tensor.missing_mask, strict=True))

    assert values["microstructure_trust_score"] == 0.42
    assert values["feed_latency_ms"] == 55.0
    assert values["sweep_risk"] == 0.8
    assert values["liquidation_cascade_risk"] == 0.9
    assert missing["microstructure_trust_score"] == 0


def test_missing_microstructure_trust_is_masked_not_silently_neutral() -> None:
    builder = V2UnifiedFeatureTensorBuilder()
    tensor = builder.build(
        symbol="BTCUSDT",
        timeframe="1m",
        payloads={
            "features_latest": {"feature_snapshot_id": "snap-missing-micro", "features": {}},
            "ohlcv": {"close": 100.0, "candle_closed_confirmed": True},
            "orderbook": {},
            "microstructure": {},
        },
    )

    values = dict(zip(tensor.feature_names, tensor.values, strict=True))
    missing = dict(zip(tensor.feature_names, tensor.missing_mask, strict=True))

    assert values["microstructure_trust_score"] == 0.0
    assert missing["microstructure_trust_score"] == 1
