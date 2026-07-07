from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    V2UnifiedFeatureTensorBuilder,
)


def test_direct_orderbook_features_are_first_class_tensor_fields() -> None:
    builder = V2UnifiedFeatureTensorBuilder()
    tensor = builder.build(
        symbol="BTCUSDT",
        timeframe="1m",
        payloads={
            "features_latest": {"feature_snapshot_id": "snap-direct-ob", "features": {}},
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
                "source": "direct_binance",
                "best_bid": 100.0,
                "best_ask": 100.2,
                "best_bid_size": 3.0,
                "best_ask_size": 2.0,
                "bid_ask_mid": 100.1,
                "spread_bps": 1.998,
                "depth_5_bid_usd": 1000.0,
                "depth_5_ask_usd": 900.0,
                "depth_20_bid_usd": 5000.0,
                "depth_20_ask_usd": 4500.0,
                "depth_slope": 3.5,
                "estimated_price_impact_bps": 0.7,
                "source_latency_ms": 25.0,
                "sequence_gap_flag": 0,
                "available_at": "2026-06-01T00:00:00.000Z",
            },
            "microstructure": {},
        },
    )

    fields = dict(zip(tensor.feature_names, tensor.values, strict=True))
    missing = dict(zip(tensor.feature_names, tensor.missing_mask, strict=True))

    assert fields["bid_ask_mid"] == 100.1
    assert fields["best_bid_size"] == 3.0
    assert fields["best_ask_size"] == 2.0
    assert fields["depth_5_bid_usd"] == 1000.0
    assert fields["depth_20_ask_usd"] == 4500.0
    assert fields["estimated_price_impact_bps"] == 0.7
    assert fields["sequence_gap_flag"] == 0.0
    assert missing["spread_bps"] == 0
