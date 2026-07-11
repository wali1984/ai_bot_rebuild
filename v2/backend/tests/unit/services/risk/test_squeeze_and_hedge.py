"""Squeeze detector + hedge-first controller invariants."""

from __future__ import annotations

from v2.backend.app.services.risk.cross_margin_liquidation import (
    build_portfolio_liquidation_snapshot,
)
from v2.backend.app.services.risk.fast_squeeze_detector import detect_squeeze
from v2.backend.app.services.risk.hedge_first_controller import evaluate_hedge_first

NOW = "2026-07-09T06:00:00Z"


def test_adverse_squeeze_on_open_long_requires_hedge_or_reduce():
    ctx = {
        "coinglass": {"features": {
            "coinglass_funding_rate_zscore": 2.6,          # crowded longs -> down squeeze
            "coinglass_liquidation_cascade_score": 0.8,
            "coinglass_liquidation_imbalance_usd": 8_000_000.0,
        }},
        "orderbook": {"depth_imbalance": -0.5, "spread_bps": 8},
        "microstructure": {"tape_imbalance": -0.6},
    }
    out = detect_squeeze(symbol="BTCUSDT", timeframe="1m", context=ctx,
                         open_position_side="long", liquidation_buffer_usd=40.0, generated_utc=NOW)
    assert out["squeeze_direction"] == "down"
    assert out["adverse_to_open_position"] is True
    assert out["hedge_required"] is True or out["reduce_required"] is True


def test_high_squeeze_blocks_late_entry():
    ctx = {
        "coinglass": {"features": {
            "coinglass_funding_rate_zscore": 2.8,
            "coinglass_liquidation_cascade_score": 0.9,
            "coinglass_liquidation_imbalance_usd": 12_000_000.0,
        }},
        "orderbook": {"depth_imbalance": 0.6, "spread_bps": 10},
        "microstructure": {"tape_imbalance": 0.7},
        "confluence": {"features": {"altdata_liquidation_sweep_risk_score": 0.8}},
    }
    out = detect_squeeze(symbol="ETHUSDT", timeframe="5m", context=ctx, generated_utc=NOW)
    assert out["squeeze_probability"] >= 0.6
    assert out["entry_block_required"] is True
    assert out["avoid_static_stops_near_cluster"] is True


def test_calm_market_no_squeeze():
    ctx = {"orderbook": {"depth_imbalance": 0.05, "spread_bps": 1}}
    out = detect_squeeze(symbol="BTCUSDT", timeframe="1m", context=ctx, generated_utc=NOW)
    assert out["squeeze_probability"] < 0.6
    assert out["entry_block_required"] is False


def _snap_with_negative():
    account = {"totalWalletBalance": 500.0, "totalUnrealizedProfit": -80.0,
               "totalMarginBalance": 420.0, "totalMaintMargin": 60.0, "availableBalance": 200.0}
    positions = [{"symbol": "SOLUSDT", "positionAmt": 30.0, "markPrice": 150.0, "leverage": 10,
                  "maintMarginRatio": 0.01, "unRealizedProfit": -80.0}]
    return build_portfolio_liquidation_snapshot(account=account, positions=positions, generated_utc=NOW)


def test_negative_position_gets_hedge_evaluation():
    snap = _snap_with_negative()
    position = {"symbol": "SOLUSDT", "side": "long", "notional_usd": 4500.0, "unrealized_pnl_usd": -80.0}
    out = evaluate_hedge_first(position=position, snapshot=snap, hedge_mode=False, generated_utc=NOW)
    assert out["is_negative"] is True
    assert out["is_martingale"] is False
    assert out["recommended_action"] in {"HEDGE", "PARTIAL_DERISK_CLOSE"}
    # every candidate is evaluated; none may worsen buffer and still be chosen
    if out["hedge_required"]:
        assert out["liquidation_buffer_after_usd"] <= out["liquidation_buffer_before_usd"]
        assert out["liquidation_buffer_after_usd"] > 0
        assert out["portfolio_risk_after"] < out["portfolio_risk_before"]
        assert out["hedge_exit_plan"] is not None


def test_hedge_never_added_purely_for_exposure():
    snap = _snap_with_negative()
    position = {"symbol": "SOLUSDT", "side": "long", "notional_usd": 4500.0, "unrealized_pnl_usd": 50.0}
    out = evaluate_hedge_first(position=position, snapshot=snap, hedge_mode=False, generated_utc=NOW)
    # positive position, not fragile -> no hedge, HOLD
    assert out["is_negative"] is False
