from __future__ import annotations

import datetime as dt
from pathlib import Path

from v2.backend.app.cli.v2_major_move_replay_future_window_completion import (
    _feedback_schema_status,
    _scan_detector_for_replay_row,
    _write_trainer_doc,
    classify_root_causes,
    replay_row_from_snapshot,
)
from v2.backend.app.services.market_move_detection import CandleInput
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    build_strategy_hedge_exit_feedback,
)


def _iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _candle(index: int, close: float) -> CandleInput:
    open_ms = 1_800_000_000_000 + index * 60_000
    return CandleInput(
        symbol="BTCUSDT",
        timeframe="1m",
        open_time_ms=open_ms,
        close_time_ms=open_ms + 59_999,
        available_at_ms=open_ms + 60_000,
        open=close - 1.0,
        high=close + 2.0,
        low=close - 2.0,
        close=close,
        volume=100.0 + index,
        closed=True,
    )


def _candle_mapping(index: int, close: float, *, volume: float = 100.0) -> dict[str, float | bool | str]:
    candle = _candle(index, close)
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe,
        "open_time": candle.open_time_ms,
        "close_time": candle.close_time_ms,
        "available_at": candle.available_at_ms,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": volume,
        "is_closed": True,
    }


def _audit_quality_fields() -> dict[str, object]:
    return {
        "actual_observed_spread_entry_bps": 1.4,
        "actual_observed_spread_exit_bps": 1.6,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:test",
        "expected_slippage_bps": 0.9,
        "expected_slippage_usd": 0.01,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_modeled": True,
        "realized_slippage_bps": 1.0,
        "realized_slippage_usd": 0.01,
        "implementation_shortfall_usd": 0.0,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "squeeze_evidence_components": {"spread_stress": 0.0},
        "mfe_bps": 20.0,
        "mfe_usd": 1.0,
        "mae_bps": 5.0,
        "mae_usd": 0.25,
        "intra_trade_high_price": 102.0,
        "intra_trade_low_price": 99.5,
        "trailing_stop_history": [],
    }


def test_future_window_labels_present_and_not_used_as_features() -> None:
    candles = [_candle(i, 100.0 + i) for i in range(260)]
    decision_ms = candles[10].available_at_ms
    snapshot = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "v2h_test",
        "decision_time_est": _iso(decision_ms),
        "all_tf_candle_timestamps": [candles[10].close_time_ms],
        "all_source_event_times": [candles[10].available_at_ms],
        "ppo_action": "short",
        "masa_forecast": {"expected_move_bps": -5.0, "confidence": 0.49},
        "feature_names": ["open_interest", "funding_rate", "microprice", "public_intel_score"],
    }

    row = replay_row_from_snapshot(snapshot, candles)

    assert row["future_window_status"] == "COMPLETE_CLOSED_CANDLE_LABELS"
    assert row["future_labels_used_as_features"] is False
    assert row["feature_available_before_decision"] is True
    assert row["future_price_5m"] is not None
    assert row["future_price_15m"] is not None
    assert row["future_price_1h"] is not None
    assert row["future_price_4h"] is not None
    assert row["future_available_at_4h"] is not None
    assert "WRONG_DIRECTION" in row["root_causes"]


def test_future_window_labels_not_used_as_features() -> None:
    candles = [_candle(i, 100.0 + i) for i in range(260)]
    decision_ms = candles[10].available_at_ms
    snapshot = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "prediction_id": "v2h_test",
        "decision_time_est": _iso(decision_ms),
        "all_tf_candle_timestamps": [candles[10].close_time_ms],
        "all_source_event_times": [candles[10].available_at_ms],
        "ppo_action": "short",
        "masa_forecast": {"expected_move_bps": -5.0, "confidence": 0.49},
        "feature_names": ["open_interest", "funding_rate", "microprice"],
    }

    row = replay_row_from_snapshot(snapshot, candles)

    assert row["future_window_status"] == "COMPLETE_CLOSED_CANDLE_LABELS"
    assert row["future_labels_used_as_features"] is False
    assert row["feature_available_before_decision"] is True


def test_root_cause_classifier_uses_completed_future_labels() -> None:
    row = {
        "future_window_status": "COMPLETE_CLOSED_CANDLE_LABELS",
        "realized_move_after_cost_bps_4h": 50.0,
        "selected_action": "short",
        "confidence_calibrated": 0.50,
        "expected_move_after_cost_bps": -1.0,
        "liquidation_context": "feature_names_present",
        "oi_context": "feature_names_present",
        "funding_context": "feature_names_present",
        "microstructure_context": "feature_names_present",
        "news_public_intel_context": "feature_names_present",
    }

    causes = classify_root_causes(row)

    assert "WRONG_DIRECTION" in causes
    assert "CONFIDENCE_TOO_LOW" in causes
    assert "EXPECTED_MOVE_NEGATIVE" in causes
    assert "MAJOR_MOVE_REPLAY_FUTURE_WINDOW_MISSING" not in causes


def test_major_move_feedback_fields_present() -> None:
    close_event = {
        "trainer_feedback_id": "trainer_feedback_test",
        "outcome_label_id": "paper_outcome_test",
        "position_id": "paper_position_test",
        "symbol": "BTCUSDT",
        "prediction_id": "prediction_test",
        "entry_prediction_id": "prediction_test",
        "signal_id": "signal_test",
        "entry_signal_id": "signal_test",
        "feature_snapshot_id": "feature_snapshot_test",
        "entry_feature_snapshot_id": "feature_snapshot_test",
        "market_state_id": "market_state_test",
        "entry_market_state_id": "market_state_test",
        "timeframe": "1m",
        "action": "long",
        "entry_price": 100.0,
        "exit_price": 102.0,
        "realized_pnl": 2.0,
        "exit_time": "2026-06-11T10:05:00Z",
        "strategy_id": "correlated_major_squeeze",
        "strategy_family": "breakout",
        "strategy_subtype": "correlated_major_squeeze",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "entry_reason": "paper_only_major_move_candidate",
        "exit_reason": "take_profit",
        "realized_pnl_bps": 25.0,
        "hold_time_seconds": 600,
        "market_regime_at_entry": "correlated_breakout_squeeze",
        "market_regime_at_exit": "correlated_breakout_squeeze",
        "market_regime": "correlated_breakout_squeeze",
        "liquidity_zone_context": {"source": "test"},
        "liquidity_context": {"source": "test"},
        "liquidation_distance_context": {"source": "test"},
        "microstructure_context": {"source": "test"},
        "oi_funding_context": {"source": "test"},
        "public_intel_context": {"source": "test"},
        "major_move_context": {"source": "test", "major_move_signal_id": "major_move_test"},
        "drawdown_at_entry": 0.0,
        "major_move_signal_id": "major_move_test",
        "squeeze_evidence_score": 0.7,
        "future_window_label_source": "closed_candle_replay_label",
        **_audit_quality_fields(),
    }

    row = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label=dict(close_event))

    assert row["trainer_consumable"] is True
    assert row["major_move_signal_id"] == "major_move_test"
    assert row["strategy_subtype"] == "correlated_major_squeeze"
    assert row["future_window_label_source"] == "closed_candle_replay_label"
    assert row["major_move_context"]["major_move_signal_id"] == "major_move_test"
    assert row["missing_feedback_fields"] == []


def test_wrong_direction_case_is_labeled_for_trainer_feedback() -> None:
    close_event = {
        "trainer_feedback_id": "trainer_feedback_wrong_direction",
        "outcome_label_id": "paper_outcome_wrong_direction",
        "position_id": "paper_position_wrong_direction",
        "symbol": "BTCUSDT",
        "prediction_id": "prediction_wrong_direction",
        "entry_prediction_id": "prediction_wrong_direction",
        "signal_id": "signal_wrong_direction",
        "entry_signal_id": "signal_wrong_direction",
        "feature_snapshot_id": "feature_snapshot_wrong_direction",
        "entry_feature_snapshot_id": "feature_snapshot_wrong_direction",
        "market_state_id": "market_state_wrong_direction",
        "entry_market_state_id": "market_state_wrong_direction",
        "timeframe": "1m",
        "action": "short",
        "entry_price": 100.0,
        "exit_price": 102.0,
        "realized_pnl": -2.0,
        "exit_time": "2026-06-11T10:05:00Z",
        "strategy_id": "correlated_major_squeeze",
        "strategy_family": "breakout",
        "strategy_subtype": "correlated_major_squeeze",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "entry_reason": "paper_only_major_move_candidate",
        "exit_reason": "wrong_direction_after_major_move",
        "realized_pnl_bps": -200.0,
        "hold_time_seconds": 600,
        "market_regime": "correlated_breakout_squeeze",
        "market_regime_at_entry": "correlated_breakout_squeeze",
        "market_regime_at_exit": "correlated_breakout_squeeze",
        "liquidity_context": {"source": "test"},
        "liquidity_zone_context": {"source": "test"},
        "liquidation_distance_context": {"source": "test"},
        "microstructure_context": {"source": "test"},
        "oi_funding_context": {"source": "test"},
        "public_intel_context": {"source": "test"},
        "major_move_signal_id": "major_move_wrong_direction",
        "major_move_context": {
            "source": "test",
            "major_move_signal_id": "major_move_wrong_direction",
            "trainer_label": "WRONG_DIRECTION",
        },
        "squeeze_evidence_score": 0.77,
        "future_window_label_source": "closed_candle_replay_label",
        "drawdown_at_entry": 0.0,
        **_audit_quality_fields(),
    }

    row = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label=dict(close_event))

    assert row["trainer_consumable"] is True
    assert row["exit_reason"] == "wrong_direction_after_major_move"
    assert row["major_move_context"]["trainer_label"] == "WRONG_DIRECTION"
    assert row["realized_pnl_bps"] < 0


def test_major_move_feedback_schema_probe_is_consumable() -> None:
    status = _feedback_schema_status()

    assert status["status"] == "READY"
    assert status["trainer_consumable_rows"] == 1
    assert status["sample_feedback_row"]["missing_feedback_fields"] == []


def test_replay_detector_scan_uses_closed_candles_without_future_label_features() -> None:
    candles = [
        _candle_mapping(0, 100.0, volume=900.0),
        _candle_mapping(1, 100.1, volume=950.0),
        _candle_mapping(2, 100.0, volume=920.0),
        _candle_mapping(3, 100.1, volume=900.0),
        _candle_mapping(4, 102.0, volume=2200.0),
    ]
    decision_ms = int(candles[3]["available_at"])

    class RedisProbe:
        def get(self, key: str):  # noqa: ANN001
            assert key == "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
            return candles

    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "decision_time": _iso(decision_ms),
        "future_available_at_5m": _iso(int(candles[-1]["available_at"])),
    }

    signal = _scan_detector_for_replay_row(RedisProbe(), row)  # type: ignore[arg-type]

    assert signal["symbol"] == "BTCUSDT"
    assert signal["direction"] == "long"
    assert signal["reject_reasons"] == ()
    assert signal["future_labels_used_as_features"] is False
    assert signal["candidate_time"] == _iso(int(candles[-1]["available_at"]))


def test_trainer_instructions_doc_status(tmp_path: Path) -> None:
    docs = tmp_path / "v2/docs"
    docs.mkdir(parents=True)
    (docs / "trainer-instructions.md").write_text("", encoding="utf-8")

    status = _write_trainer_doc(tmp_path)

    assert status["line_count_before"] == 0
    assert status["line_count"] > 0
    assert status["status"] == "READY"
    assert all(status["required_sections_present"].values())
