from __future__ import annotations

from v2.backend.app.services.strategy_router.reporting import (
    summarize_strategy_router_performance,
)


def test_reporting_groups_by_mode_and_regime() -> None:
    report = summarize_strategy_router_performance(
        accepted_rows=[
            {
                "strategy_selected_mode": "trend_mode",
                "strategy_regime_labels": ["TREND"],
                "realized_pnl_usdt": 12.5,
                "fees_usdt": 1.0,
                "slippage_bps": 2.0,
            }
        ],
        blocked_rows=[
            {
                "strategy_selected_mode": "no_trade_mode",
                "strategy_regime_labels": ["DATA_UNRELIABLE", "NO_TRADE"],
                "strategy_router_block_reason": "DATA_QUALITY_BELOW_THRESHOLD",
            }
        ],
        shadow_rows=[],
        held_rows=[],
    )

    assert report["total_rows"] == 2
    assert report["mode_counts"]["trend_mode"] == 1
    assert report["mode_counts"]["no_trade_mode"] == 1
    assert report["regime_counts"]["TREND"] == 1
    assert report["regime_counts"]["DATA_UNRELIABLE"] == 1
    assert report["by_mode"]["trend_mode"]["trade_count"] == 1
    assert report["by_regime"]["DATA_UNRELIABLE"]["blocked_trades"] == 1
