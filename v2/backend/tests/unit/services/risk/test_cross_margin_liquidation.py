"""Cross-margin portfolio liquidation invariants."""

from __future__ import annotations

from v2.backend.app.services.risk.cross_margin_liquidation import (
    build_portfolio_liquidation_snapshot,
    marginal_liquidation_impact,
)

NOW = "2026-07-09T06:00:00Z"


def _account(**over):
    base = {
        "totalWalletBalance": 1000.0,
        "totalUnrealizedProfit": 0.0,
        "totalInitialMargin": 200.0,
        "totalMaintMargin": 50.0,
        "totalMarginBalance": 1000.0,
        "availableBalance": 800.0,
    }
    base.update(over)
    return base


def _positions():
    return [
        {"symbol": "BTCUSDT", "positionAmt": 0.05, "markPrice": 60000.0, "leverage": 5,
         "maintMarginRatio": 0.004, "unRealizedProfit": 0.0},
        {"symbol": "SOLUSDT", "positionAmt": 20.0, "markPrice": 150.0, "leverage": 10,
         "maintMarginRatio": 0.01, "unRealizedProfit": 0.0},
    ]


def test_portfolio_level_buffer_computed():
    snap = build_portfolio_liquidation_snapshot(account=_account(), positions=_positions(), generated_utc=NOW)
    assert snap["portfolio_level_computed"] is True
    assert snap["per_position_only"] is False
    assert snap["open_position_count"] == 2
    assert snap["portfolio_liquidation_buffer_usd"] == 950.0  # 1000 - 50
    assert snap["portfolio_liquidation_buffer_pct"] == 95.0
    assert len(snap["position_liquidation_register"]) == 2
    assert all(row["estimated_position_liquidation_price"] is not None for row in snap["position_liquidation_register"])


def test_correlated_shock_reduces_buffer():
    snap = build_portfolio_liquidation_snapshot(account=_account(), positions=_positions(), generated_utc=NOW)
    shocks = snap["correlated_shock_scenarios"]
    assert "btc_down_20pct" in shocks
    # both positions long -> down shock hurts both -> worst case < base buffer
    assert snap["worst_case_liquidation_buffer_usd"] < snap["portfolio_liquidation_buffer_usd"]
    assert shocks["btc_down_20pct"]["portfolio_pnl_delta_usd"] < 0


def test_a_position_can_look_safe_while_portfolio_breaches():
    # Thin margin balance + heavy correlated long exposure => portfolio breach.
    account = _account(totalMarginBalance=300.0, totalWalletBalance=300.0, totalMaintMargin=40.0)
    big = [
        {"symbol": "SOLUSDT", "positionAmt": 100.0, "markPrice": 150.0, "leverage": 20,
         "maintMarginRatio": 0.01, "unRealizedProfit": 0.0},
        {"symbol": "ETHUSDT", "positionAmt": 3.0, "markPrice": 3000.0, "leverage": 20,
         "maintMarginRatio": 0.01, "unRealizedProfit": 0.0},
    ]
    snap = build_portfolio_liquidation_snapshot(account=account, positions=big, generated_utc=NOW)
    assert snap["correlated_shock_scenarios"]["btc_down_20pct"]["liquidation_breached"] is True


def test_marginal_hedge_impact_flags_worse_buffer():
    snap = build_portfolio_liquidation_snapshot(account=_account(), positions=_positions(), generated_utc=NOW)
    impact = marginal_liquidation_impact(
        snapshot=snap, added_notional_usd=1000.0, added_symbol="BTCUSDT", added_side="short",
    )
    assert impact["maintenance_margin_added_usd"] > 0
    assert impact["liquidation_buffer_after_usd"] < impact["liquidation_buffer_before_usd"]
    assert impact["worsens_liquidation_buffer"] is True
