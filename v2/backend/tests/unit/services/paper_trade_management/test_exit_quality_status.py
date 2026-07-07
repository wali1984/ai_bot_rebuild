from __future__ import annotations

from v2.backend.app.services.paper_trade_management.exit_quality_status import (
    build_adaptive_exit_policy_status,
    build_churn_equity_bleed_block_status,
    build_execution_cost_parity_status,
    build_mfe_mae_exit_quality_status,
)


def _runtime_stop_status(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "paper_exit_policy_version": "PAPER_EXIT_AFTER_COST_TRAILING_FLOOR_V1",
        "static_stop_loss_enabled": False,
        "static_take_profit_enabled": False,
        "static_profit_lock_enabled": False,
        "static_profit_bank_enabled": False,
        "static_max_hold_enabled": False,
        "trailing_stop_enabled": True,
        "min_profit_before_trailing_bps": 30.0,
        "trailing_stop_min_after_cost_buffer_bps": 12.0,
        "atr_trailing_stop_multiplier": 1.5,
        "new_close_event_count": 0,
    }
    row.update(overrides)
    return row


def test_adaptive_exit_policy_status_requires_static_runtime_exits_disabled() -> None:
    ready = build_adaptive_exit_policy_status(_runtime_stop_status())
    blocked = build_adaptive_exit_policy_status(
        _runtime_stop_status(static_take_profit_enabled=True)
    )

    assert ready["status"] == "ADAPTIVE_EXIT_POLICY_READY"
    assert ready["overall_pass"] is True
    assert ready["pass_conditions"]["static_take_profit_disabled"] is True
    assert ready["no_live_mutation"] is True
    assert blocked["overall_pass"] is False
    assert "static_take_profit_disabled" in blocked["blockers"]


def test_mfe_mae_exit_quality_blocks_dirty_path_rows() -> None:
    clean = build_mfe_mae_exit_quality_status(
        [
            {
                "close_id": "close-1",
                "symbol": "BTCUSDT",
                "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
                "mfe_bps": 12.0,
                "mae_bps": 40.0,
                "intra_trade_high_price": 101.0,
                "intra_trade_low_price": 99.0,
                "realized_pnl_bps": -18.0,
            }
        ]
    )
    dirty = build_mfe_mae_exit_quality_status(
        [
            {
                "close_id": "close-2",
                "symbol": "ETHUSDT",
                "close_reason": "TIER_2_TRAILING_STOP",
                "mfe_bps": 42.0,
            }
        ]
    )

    assert clean["overall_pass"] is False
    assert clean["pass_conditions"]["mfe_not_wasted_into_negative_realized_rows"] is False
    assert dirty["dirty_path_row_count"] == 1
    assert dirty["pass_conditions"]["closed_trades_have_mfe_mae_path"] is False
    assert dirty["sample_dirty_path_rows"][0]["missing_path_fields"] == [
        "mae_bps",
        "intra_trade_high_price",
        "intra_trade_low_price",
    ]


def test_mfe_mae_exit_quality_passes_complete_adaptive_profitable_rows() -> None:
    status = build_mfe_mae_exit_quality_status(
        [
            {
                "close_id": "close-1",
                "symbol": "BTCUSDT",
                "close_reason": "TIER_2_TRAILING_STOP",
                "mfe_bps": 120.0,
                "mae_bps": 5.0,
                "intra_trade_high_price": 101.2,
                "intra_trade_low_price": 100.0,
                "realized_pnl_bps": 42.0,
            }
        ]
    )

    assert status["status"] == "MFE_MAE_EXIT_QUALITY_READY"
    assert status["overall_pass"] is True
    assert status["static_exit_reason_count"] == 0
    assert status["adaptive_exit_reason_count"] == 1


def test_churn_equity_bleed_block_status_preserves_governor_pass_conditions() -> None:
    status = build_churn_equity_bleed_block_status(
        {
            "state": "ACTIVE",
            "new_entries_allowed": True,
            "duplicate_new_entries": 0,
            "same_candle_reentry_count": 0,
            "same_prediction_duplicate_count": 0,
            "same_signal_duplicate_count": 0,
            "places_real_order": False,
            "routes_to_live": False,
            "pass_conditions": {
                "duplicate_new_entries_eq_zero": True,
                "same_candle_reentry_unexplained_eq_zero": True,
                "cost_drag_within_envelope": True,
                "economic_trade_count_reconciles": True,
            },
        }
    )

    assert status["status"] == "CHURN_EQUITY_BLEED_BLOCK_READY"
    assert status["overall_pass"] is True
    assert status["no_live_mutation"] is True


def test_execution_cost_parity_requires_fee_slippage_funding_and_spread() -> None:
    ready = build_execution_cost_parity_status(
        [
            {
                "fill_id": "fill-1",
                "symbol": "SOLUSDT",
                "fee_bps": 4.0,
                "expected_slippage_bps": 2.0,
                "expected_funding_bps": 0.5,
                "actual_observed_spread_entry_bps": 1.2,
                "bid_ask_spread_bps_fallback": False,
            }
        ]
    )
    blocked = build_execution_cost_parity_status(
        [
            {
                "fill_id": "fill-2",
                "symbol": "SOLUSDT",
                "fee_bps": 4.0,
                "bid_ask_spread_bps_fallback": True,
            }
        ]
    )

    assert ready["status"] == "EXECUTION_COST_PARITY_READY"
    assert ready["overall_pass"] is True
    assert blocked["overall_pass"] is False
    assert blocked["incomplete_cost_row_count"] == 1
    assert blocked["sample_incomplete_cost_rows"][0]["fallback_treated_as_real"] is True
