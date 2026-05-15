from __future__ import annotations

import datetime as dt

from v2.backend.app.services.paper_shadow_outcome_observer.service import (
    evaluate_observation_request,
)


def test_future_positive_outcome_never_authorizes_current_fill() -> None:
    result = evaluate_observation_request(
        {
            "event_id": "evt_positive_future",
            "intent_id": "intent_positive_future",
            "risk_decision_id": "risk_positive_future",
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_reference_price": 100.0,
            "event_ts": "2026-01-01T00:00:00Z",
            "expected_move_after_cost_bps": 2.0,
            "expected_move_source": "native_trainer_expected_move_bps",
            "cost_bps": 6.0,
            "block_reason": "confidence_below_canary_threshold",
        },
        price_samples=[
            {
                "symbol": "BTCUSDT",
                "time": "2026-01-01T00:05:00Z",
                "high": 101.0,
                "low": 99.9,
                "close": 100.5,
            }
        ],
        now=dt.datetime(2026, 1, 1, 1, 1, tzinfo=dt.timezone.utc),
    )

    assert result["would_have_beaten_costs"] is True
    assert result["after_cost_correct"] is True
    assert result["no_trade_correct"] is False
    assert result["fill_allowed"] is False
    assert result["paper_fill_recorded"] is False
    assert result["fee_charged_usdt"] == 0.0


def test_future_failed_outcome_tracks_no_trade_correct_without_positive_edge() -> None:
    result = evaluate_observation_request(
        {
            "event_id": "evt_failed_future",
            "intent_id": "intent_failed_future",
            "risk_decision_id": "risk_failed_future",
            "symbol": "BTCUSDT",
            "side": "short",
            "entry_reference_price": 100.0,
            "event_ts": "2026-01-01T00:00:00Z",
            "expected_move_after_cost_bps": 1.0,
            "expected_move_source": "native_trainer_expected_move_bps",
            "cost_bps": 6.0,
            "block_reason": "expected_edge_below_costs",
        },
        price_samples=[
            {
                "symbol": "BTCUSDT",
                "time": "2026-01-01T00:15:00Z",
                "high": 100.05,
                "low": 99.99,
                "close": 100.0,
            }
        ],
        now=dt.datetime(2026, 1, 1, 1, 1, tzinfo=dt.timezone.utc),
    )

    assert result["would_have_beaten_costs"] is False
    assert result["after_cost_correct"] is False
    assert result["no_trade_correct"] is True
    assert result["fill_allowed"] is False
    assert result["paper_fill_recorded"] is False


def test_all_horizons_emit_outcome_metrics_when_future_data_exists() -> None:
    result = evaluate_observation_request(
        {
            "event_id": "evt_all_horizons",
            "intent_id": "intent_all_horizons",
            "risk_decision_id": "risk_all_horizons",
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_reference_price": 100.0,
            "event_ts": "2026-01-01T00:00:00Z",
            "expected_move_after_cost_bps": 8.0,
            "cost_bps": 6.0,
            "block_reason": "expected_edge_below_costs",
        },
        price_samples=[
            {"symbol": "BTCUSDT", "time": "2026-01-01T00:05:00Z", "high": 100.2, "low": 99.8, "close": 100.1},
            {"symbol": "BTCUSDT", "time": "2026-01-01T00:15:00Z", "high": 100.3, "low": 99.7, "close": 100.2},
            {"symbol": "BTCUSDT", "time": "2026-01-01T00:30:00Z", "high": 100.4, "low": 99.6, "close": 100.3},
            {"symbol": "BTCUSDT", "time": "2026-01-01T01:00:00Z", "high": 100.5, "low": 99.5, "close": 100.4},
        ],
        now=dt.datetime(2026, 1, 1, 1, 1, tzinfo=dt.timezone.utc),
    )

    assert result["completed"] is True
    for horizon in ("horizon_5m", "horizon_15m", "horizon_30m", "horizon_1h"):
        row = result["horizons"][horizon]
        assert row["status"] == "COMPLETED"
        assert "realized_return_bps" in row
        assert "max_favorable_excursion_bps" in row
        assert "max_adverse_excursion_bps" in row
        assert "would_have_beaten_costs" in row
        assert "would_have_hit_stop" in row
        assert "would_have_hit_take_profit" in row


def test_missing_observation_inputs_fail_closed() -> None:
    result = evaluate_observation_request(
        {
            "event_id": "evt_missing",
            "symbol": "BTCUSDT",
            "side": "long",
            "block_reason": "EDGE_AFTER_COSTS_MISSING_BLOCK",
        },
        price_samples=[],
        now=dt.datetime(2026, 1, 1, 1, 1, tzinfo=dt.timezone.utc),
    )

    assert result["outcome_status"] == "MISSING_EVIDENCE_CANNOT_OBSERVE"
    assert result["after_cost_correct"] == "MISSING_EVIDENCE"
    assert result["no_trade_correct"] == "MISSING_EVIDENCE"
    assert result["fill_allowed"] is False
    assert result["paper_fill_recorded"] is False
