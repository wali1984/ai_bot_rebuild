from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from v2.backend.app.services.prediction_serving import serving_activation_v2 as activation
from v2.backend.app.services.prediction_serving.serving_feature_abi_v2 import (
    ORDERED_FEATURE_NAMES,
    feature_abi_sha256,
    feature_builder_sha256,
)


def test_current_universe_smoke_is_read_only_directional_and_distribution_bound(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=4)
    weight = tmp_path / "checkpoint.pt"
    weight.write_bytes(b"checkpoint")
    values = {
        "expected_funding_bps": 0.0,
        "expected_slippage_bps": 1.0,
        "fee_bps": 5.0,
        "spread_bps": 1.0,
        "bb_width_pct": 0.01,
        "body_pct": 0.001,
        "close": 100.0,
        "ema_12": 100.0,
        "ema_26": 100.0,
        "high": 101.0,
        "log_return": 0.001,
        "low": 99.0,
        "macd": 0.1,
        "macd_hist": 0.1,
        "macd_signal": 0.1,
        "num_trades": 100.0,
        "open": 100.0,
        "quote_volume": 1000.0,
        "range_pct": 0.02,
        "ret_pct": 0.001,
        "rsi_14": 50.0,
        "taker_buy_base_vol": 5.0,
        "taker_buy_quote_vol": 500.0,
        "taker_buy_ratio": 0.5,
        "taker_sell_base_vol": 5.0,
        "taker_sell_quote_vol": 500.0,
        "taker_sell_ratio": 0.5,
        "true_range_pct": 0.02,
        "volume": 10.0,
    }
    snapshot = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "features": values,
        "feature_cutoff": cutoff.isoformat(),
        "generated_at": now.isoformat(),
        "feature_snapshot_id": "snapshot-1",
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "TEST_CLOSED_ONLY",
        "latest_unclosed_exclusion_decision_time_ms": int(now.timestamp() * 1000),
        "latest_closed_kline_close_time_ms": int(cutoff.timestamp() * 1000),
    }
    cost = {
        "source_event_time": (now - timedelta(seconds=2)).isoformat(),
        "producer_generated_at": (now - timedelta(seconds=1)).isoformat(),
        "record_available_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),
        "funding_bps_at_decision_time": 0.0,
        "slippage_bps_per_side": 1.0,
        "fee_bps_per_side": 5.0,
        "spread_bps": 1.0,
        "source_readback_verified": True,
    }
    bundle = SimpleNamespace(
        weight_file_path=str(weight),
        weight_sha256=hashlib.sha256(b"checkpoint").hexdigest(),
        feature_abi_sha256=feature_abi_sha256(),
        ordered_feature_names=ORDERED_FEATURE_NAMES,
        training_feature_builder_sha=feature_builder_sha256(),
        serving_feature_builder_sha=feature_builder_sha256(),
        calibration_state={
            "fitted": True,
            "probability_semantics_valid": True,
            "model_parameter_fingerprint": "fp",
            "row_digest": "digest",
        },
        model_parameter_fingerprint="fp",
        live_eligible=False,
        checkpoint_promotable=False,
        training_manifest_id="manifest-1",
        training_manifest_sha256="a" * 64,
        checkpoint_id="checkpoint-1",
    )
    monkeypatch.setattr(
        activation,
        "ProvisionalCheckpoint",
        lambda _path: SimpleNamespace(
            serving_feature_abi_v2=True,
            forward=lambda _values: {"action": "long", "probabilities": [1.0, 0.0, 0.0]},
        ),
    )
    monkeypatch.setattr(
        activation,
        "_checkpoint_meta",
        lambda _path: {
            "standardize_mean": [0.0] * len(ORDERED_FEATURE_NAMES),
            "observed_training_std": [100.0] * len(ORDERED_FEATURE_NAMES),
            "training_feature_min": [-100.0] * len(ORDERED_FEATURE_NAMES),
            "training_feature_max": [100.0] * len(ORDERED_FEATURE_NAMES),
            "paper_only": True,
            "routes_to_live": False,
        },
    )
    monkeypatch.setattr(activation, "read_current_feature_snapshot", lambda *_args: snapshot)
    monkeypatch.setattr(activation, "read_json_key", lambda *_args: cost)
    monkeypatch.setattr(activation, "read_active", lambda *_args, **_kwargs: {"generation": 1})

    report = activation.evaluate_current_universe(
        object(),
        bundle=bundle,
        manifest={
            "manifest_id": "manifest-1",
            "manifest_sha256": "a" * 64,
            "feature_abi_sha256": feature_abi_sha256(),
        },
        symbols=[f"S{i}USDT" for i in range(10)],
        timeframes=["5m"],
    )

    assert report["accepted_current_rows"] == 10
    assert report["prediction_distribution"]["long"] == 10
    assert report["feature_distribution_drift_above_limit"] is False
    assert report["shadow_prediction_valid"] is False  # one action is rejected
    assert report["activation_eligible"] is False
