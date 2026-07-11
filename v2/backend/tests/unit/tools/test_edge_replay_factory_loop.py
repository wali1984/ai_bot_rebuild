from __future__ import annotations

from datetime import datetime, timezone

import tools.edge_replay_factory_loop as factory


def _source_row(**overrides):
    row = {
        "prediction_id": "pred-1",
        "signal_id": "sig-1",
        "decision_id": "dec-1",
        "feature_snapshot_id": "feat-1",
        "entry_feature_snapshot_id": "feat-1",
        "mtf_snapshot_id": "mtf-1",
        "market_state_id": "mstate-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "side": "long",
        "entry_price": 100.0,
        "entry_price_utc": "2026-07-09T12:00:00Z",
        "feature_cutoff": "2026-07-09T11:59:00Z",
        "available_at": "2026-07-09T11:59:30Z",
        "decision_time": "2026-07-09T12:00:00Z",
        "strategy_id": "trend",
        "strategy_family": "trend",
        "strategy_subtype": "pullback",
        "source_hashes": {"features": "hash"},
        "paper_only": True,
        "places_real_order": False,
        "future_labels_used_as_features": False,
    }
    row.update(overrides)
    return row


def test_matures_shadow_row_from_closed_candle_without_live_flags() -> None:
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row()],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 101.0,
                    "high": 101.5,
                    "low": 99.5,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=timezone.utc),
        min_hold_seconds=900,
    )

    assert len(matured) == 1
    assert pending == []
    assert rejected == []
    row = matured[0]
    assert row["trainer_feedback_source"] == "V2_CONTINUOUS_EDGE_FACTORY_COUNTERFACTUAL_CLOSED_WINDOW"
    assert row["trainer_consumable"] is True
    assert row["counterfactual_label_matured"] is True
    assert row["counterfactual_label_pending"] is False
    assert row["future_labels_used_as_features"] is False
    assert row["counts_as_final_a_plus"] is False
    assert row["counts_as_live_ready"] is False
    assert row["routes_to_live"] is False
    assert row["places_real_order"] is False
    assert row["realized_net_pnl_bps"] > 0


def test_rejects_feature_available_after_decision_time() -> None:
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row(available_at="2026-07-09T12:00:01Z")],
        candles_by_symbol_timeframe={
            ("BTCUSDT", "1m"): [
                {
                    "close": 101.0,
                    "candle_close_time": "2026-07-09T12:15:00Z",
                    "candle_closed_confirmed": True,
                }
            ]
        },
        now=datetime(2026, 7, 9, 12, 16, tzinfo=timezone.utc),
    )

    assert matured == []
    assert pending == []
    assert rejected[0]["reject_reasons"] == ["AVAILABLE_AT_AFTER_DECISION_TIME"]


def test_pending_until_closed_exit_candle_available() -> None:
    matured, pending, rejected = factory.mature_counterfactual_rows(
        [_source_row()],
        candles_by_symbol_timeframe={("BTCUSDT", "1m"): []},
        now=datetime(2026, 7, 9, 12, 16, tzinfo=timezone.utc),
    )

    assert matured == []
    assert rejected == []
    assert pending[0]["pending_reason"] == "NO_CLOSED_EXIT_CANDLE_AVAILABLE"
