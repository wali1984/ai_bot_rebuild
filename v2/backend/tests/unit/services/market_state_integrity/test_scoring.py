from __future__ import annotations

from datetime import datetime, timezone

from v2.backend.app.services.market_state_integrity.scoring import score_market_state


def test_missing_event_and_candle_fields_do_not_default_clean() -> None:
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "pred-1",
        "feature_snapshot_id": "fs-1",
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feature_freshness_state": "CURRENT",
    }

    score = score_market_state(row)

    assert score.market_state_integrity_score < 80
    assert score.valid_for_training is False
    assert "source_event_time_missing" in score.reject_reasons
    assert "candle_closed_confirmed_missing" in score.reject_reasons


def test_future_feature_time_rejects_prediction_risk_paper_live() -> None:
    row = {
        "symbol": "ETHUSDT",
        "timeframe": "1m",
        "prediction_id": "pred-2",
        "feature_snapshot_id": "fs-2",
        "generated_utc": "2026-06-08T10:00:00Z",
        "decision_time_est": "2026-06-08T06:00:00-04:00",
        "source_event_time_utc": "2026-06-08T10:01:00Z",
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-08T09:59:00Z",
        "candle_close_time": "2026-06-08T10:00:00Z",
        "feature_freshness_state": "CURRENT",
    }

    score = score_market_state(row)

    assert "feature_timestamp_after_decision_cutoff" in score.reject_reasons
    assert score.valid_for_prediction is False
    assert score.valid_for_risk is False
    assert score.valid_for_paper is False
    assert score.valid_for_live is False


def test_current_trainer_consumable_feature_snapshot_can_train_with_optional_masks() -> None:
    row = {
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "fs-current-1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "missing_feature_count": 4,
        "missing_feature_flags": [
            "bid_ask_spread_bps",
            "depth_imbalance",
            "last_liq_bps_24h",
            "oi_change_pct",
        ],
        "features": {
            "open": 65.19,
            "high": 65.22,
            "low": 65.1,
            "close": 65.1,
            "volume": 5126.86,
            "rsi_14": 50.43,
        },
    }

    score = score_market_state(row)

    assert score.valid_for_training is True
    assert "MISSING_CRITICAL_FEATURE_FAMILY" not in score.reject_reasons
    assert score.source_lineage["optional_missing_features_masked"] is True
    assert score.source_lineage["inferred"]["source_event_time_est"] == "INFERRED_FROM_FEATURE_SNAPSHOT_GENERATED_AT"


def test_missing_liquidity_zone_fields_are_masked_optional_context() -> None:
    row = {
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "fs-current-liquidity-zones",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-14T18:00:00Z",
        "candle_close_time": "2026-06-14T18:01:00Z",
        "source_event_time_est": "2026-06-14T18:01:00Z",
        "source_received_time_est": "2026-06-14T18:01:01Z",
        "decision_time_est": "2026-06-14T18:01:01Z",
        "missing_feature_count": 3,
        "missing_feature_names": [
            "liquidity_zone_above",
            "liquidity_zone_below",
            "distance_to_liquidity_zone_bps",
        ],
        "features": {
            "open": 65.19,
            "high": 65.22,
            "low": 65.1,
            "close": 65.1,
        },
    }

    score = score_market_state(row)

    assert "MISSING_CRITICAL_FEATURE_FAMILY" not in score.reject_reasons
    assert score.source_lineage["optional_missing_features_masked"] is True


def test_missing_realized_slippage_error_is_masked_as_outcome_only_context() -> None:
    row = {
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "fs-current-realized-slippage",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-14T18:00:00Z",
        "candle_close_time": "2026-06-14T18:01:00Z",
        "source_event_time_est": "2026-06-14T18:01:00Z",
        "source_received_time_est": "2026-06-14T18:01:01Z",
        "decision_time_est": "2026-06-14T18:01:01Z",
        "missing_feature_count": 1,
        "missing_feature_names": ["realized_slippage_error"],
        "features": {
            "open": 65.19,
            "high": 65.22,
            "low": 65.1,
            "close": 65.1,
        },
    }

    score = score_market_state(row)

    assert "MISSING_CRITICAL_FEATURE_FAMILY" not in score.reject_reasons
    assert score.source_lineage["optional_missing_features_masked"] is True


def test_missing_realized_slippage_error_does_not_mask_missing_required_context() -> None:
    row = {
        "symbol": "SOLUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "fs-current-realized-slippage-plus-required",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-14T18:00:00Z",
        "candle_close_time": "2026-06-14T18:01:00Z",
        "source_event_time_est": "2026-06-14T18:01:00Z",
        "source_received_time_est": "2026-06-14T18:01:01Z",
        "decision_time_est": "2026-06-14T18:01:01Z",
        "missing_feature_count": 2,
        "missing_feature_names": ["realized_slippage_error", "close"],
        "features": {
            "open": 65.19,
            "high": 65.22,
            "low": 65.1,
            "close": 65.1,
        },
    }

    score = score_market_state(row)

    assert "MISSING_CRITICAL_FEATURE_FAMILY" in score.reject_reasons
    assert score.source_lineage["optional_missing_features_masked"] is False


def test_missing_mask_false_values_override_stale_missing_count_false_positive() -> None:
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "fs-mask-clean",
        "generated_at": generated,
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "candle_open_time": generated,
        "candle_close_time": generated,
        "source_event_time_est": generated,
        "source_received_time_est": generated,
        "decision_time_est": generated,
        "missing_feature_count": 192,
        "missing_mask": {"open": False, "high": False, "low": False, "close": False},
        "source_availability": {"ohlcv": True, "orderbook": True},
        "features": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
        },
    }

    score = score_market_state(row)

    assert "MISSING_CRITICAL_FEATURE_FAMILY" not in score.reject_reasons
    assert score.source_lineage["missing_feature_count"] == 0
    assert score.source_lineage["missing_mask"]["close"] is False
    assert score.source_lineage["source_availability"] == {"ohlcv": True, "orderbook": True}


def test_missing_mask_true_values_still_block_actual_missing_features() -> None:
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "fs-mask-missing",
        "generated_at": generated,
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "candle_open_time": generated,
        "candle_close_time": generated,
        "source_event_time_est": generated,
        "source_received_time_est": generated,
        "decision_time_est": generated,
        "missing_feature_count": 0,
        "missing_mask": {"open": False, "close": True},
        "features": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
        },
    }

    score = score_market_state(row)

    assert "MISSING_CRITICAL_FEATURE_FAMILY" in score.reject_reasons
    assert score.source_lineage["missing_feature_count"] == 1
    assert score.source_lineage["missing_feature_names"] == ["close"]


def test_current_feature_snapshot_missing_core_ohlc_still_rejects_training() -> None:
    row = {
        "symbol": "CAKEUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "fs-current-2",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": True,
        "missing_feature_count": 4,
        "missing_feature_flags": ["ema_12", "rsi_14", "macd", "last_liq_bps_24h"],
        "features": {
            "open": None,
            "high": None,
            "low": None,
            "close": None,
        },
    }

    score = score_market_state(row)

    assert score.valid_for_training is False
    assert "MISSING_CRITICAL_FEATURE_FAMILY" in score.reject_reasons
