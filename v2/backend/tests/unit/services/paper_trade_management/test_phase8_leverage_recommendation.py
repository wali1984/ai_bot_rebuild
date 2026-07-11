"""Phase 8 — Per-trade leverage and margin recommendation tests.

Validates:
 - Recommendations are per-symbol/TF/signal (not ALL_SYMBOLS aggregate)
 - live_gate is always "blocked_human_only"
 - mutates_exchange is always False
 - paper_only is always True
 - all_symbols_aggregate is always False
 - CROSS margin is never recommended
 - recommended_leverage is bounded in [1, PAPER_MAX_LEVERAGE]
 - High confidence + low volatility → max leverage (3x)
 - Low confidence or flat direction → min leverage (1x)
 - High volatility → min leverage (1x)
 - max_loss_budget_usd respects cap
 - validate_leverage_recommendation catches invariant violations
"""
from __future__ import annotations

import pytest

from app.services.paper_trade_management.leverage_recommendation import (
    LIVE_GATE,
    MUTATES_EXCHANGE,
    PAPER_MAX_LEVERAGE,
    LeverageRecommendationConfig,
    recommend_leverage_for_signal,
    validate_leverage_recommendation,
)


def _rec(**overrides) -> dict:
    base = dict(
        symbol="BTCUSDT",
        timeframe="1h",
        signal_id="sig_abc123",
        direction="long",
        confidence_calibrated=0.78,
        expected_move_after_cost_bps=20.0,
    )
    base.update(overrides)
    return recommend_leverage_for_signal(**base)


# ── Safety invariants ─────────────────────────────────────────────────────────

def test_live_gate_is_always_blocked() -> None:
    rec = _rec()
    assert rec["live_gate"] == LIVE_GATE


def test_mutates_exchange_is_always_false() -> None:
    for direction in ("long", "short", "flat"):
        rec = _rec(direction=direction)
        assert rec["mutates_exchange"] is False, f"mutates_exchange not False for direction={direction}"


def test_paper_only_is_always_true() -> None:
    rec = _rec()
    assert rec["paper_only"] is True


def test_all_symbols_aggregate_is_always_false() -> None:
    rec = _rec()
    assert rec["all_symbols_aggregate"] is False


def test_recommended_margin_mode_is_always_isolated() -> None:
    for direction in ("long", "short", "flat"):
        rec = _rec(direction=direction)
        assert rec["recommended_margin_mode"] == "isolated", (
            f"CROSS margin returned for direction={direction}"
        )


def test_recommended_leverage_bounded() -> None:
    for confidence in [0.3, 0.55, 0.75, 0.95]:
        rec = _rec(confidence_calibrated=confidence)
        assert 1 <= rec["recommended_leverage"] <= PAPER_MAX_LEVERAGE, (
            f"leverage {rec['recommended_leverage']} out of bounds for confidence={confidence}"
        )


# ── Per-symbol/TF/signal: each recommendation is independent ─────────────────

def test_recommendation_is_per_symbol_not_all_symbols() -> None:
    btc = _rec(symbol="BTCUSDT", signal_id="sig_btc")
    eth = _rec(symbol="ETHUSDT", signal_id="sig_eth")
    assert btc["symbol"] == "BTCUSDT"
    assert eth["symbol"] == "ETHUSDT"
    assert btc["signal_id"] == "sig_btc"
    assert eth["signal_id"] == "sig_eth"


def test_recommendation_includes_signal_id() -> None:
    rec = _rec(signal_id="sig_x99")
    assert rec["signal_id"] == "sig_x99"


# ── Leverage tier logic ───────────────────────────────────────────────────────

def test_flat_direction_gives_1x() -> None:
    rec = _rec(direction="flat", confidence_calibrated=0.90)
    assert rec["recommended_leverage"] == 1


def test_low_confidence_gives_1x() -> None:
    rec = _rec(confidence_calibrated=0.40, direction="long")
    assert rec["recommended_leverage"] == 1


def test_high_volatility_gives_1x() -> None:
    rec = _rec(confidence_calibrated=0.90, atr_bps=120.0)
    assert rec["recommended_leverage"] == 1


def test_high_confidence_low_volatility_gives_3x() -> None:
    cfg = LeverageRecommendationConfig(
        high_confidence_threshold=0.75,
        low_volatility_threshold_bps=30.0,
        max_leverage=3,
    )
    rec = _rec(confidence_calibrated=0.85, atr_bps=15.0)
    assert rec["recommended_leverage"] == 3


def test_moderate_confidence_gives_2x() -> None:
    rec = _rec(confidence_calibrated=0.65, atr_bps=50.0)
    assert rec["recommended_leverage"] == 2


def test_negative_after_cost_edge_gives_1x() -> None:
    # A high-confidence, low-volatility signal that would otherwise be 3x must
    # stay at 1x when the after-cost expectation is non-positive: leverage is
    # derived from positive risk-adjusted edge, never applied to a losing edge.
    rec = _rec(
        confidence_calibrated=0.90,
        atr_bps=15.0,
        expected_move_after_cost_bps=-15.0,
    )
    assert rec["recommended_leverage"] == 1
    assert rec["reason_tier"] == "NON_POSITIVE_AFTER_COST_EDGE_1X"


def test_zero_after_cost_edge_gives_1x() -> None:
    rec = _rec(
        confidence_calibrated=0.90,
        atr_bps=15.0,
        expected_move_after_cost_bps=0.0,
    )
    assert rec["recommended_leverage"] == 1


# ── Liquidation distance ──────────────────────────────────────────────────────

def test_liquidation_distance_decreases_with_higher_leverage() -> None:
    rec_1x = _rec(confidence_calibrated=0.40)
    rec_2x = _rec(confidence_calibrated=0.65, atr_bps=50.0)
    assert rec_1x["recommended_leverage"] == 1
    assert rec_2x["recommended_leverage"] == 2
    # Higher leverage → closer to liquidation (lower bps)
    assert rec_1x["liquidation_distance_bps"] > rec_2x["liquidation_distance_bps"]


def test_liquidation_distance_positive() -> None:
    for conf in [0.3, 0.65, 0.90]:
        rec = _rec(confidence_calibrated=conf)
        assert rec["liquidation_distance_bps"] >= 0.0


# ── Budget fields ─────────────────────────────────────────────────────────────

def test_confidence_budget_pct_within_cap() -> None:
    rec = _rec(confidence_calibrated=0.99)
    assert rec["confidence_budget_pct"] <= 0.05  # PAPER_MAX_CONFIDENCE_BUDGET_PCT


def test_max_loss_budget_usd_within_cap() -> None:
    rec = _rec(equity_usd=10000.0)
    assert rec["max_loss_budget_usd"] <= 50.0  # PAPER_MAX_LOSS_BUDGET_USD


def test_reason_contains_symbol_and_leverage() -> None:
    rec = _rec(symbol="BTCUSDT", confidence_calibrated=0.65, atr_bps=50.0)
    assert "BTCUSDT" in rec["reason"]
    assert "lev=2x" in rec["reason"]


# ── Validate invariants ───────────────────────────────────────────────────────

def test_validate_passes_on_correct_recommendation() -> None:
    rec = _rec()
    violations = validate_leverage_recommendation(rec)
    assert violations == []


def test_validate_catches_wrong_live_gate() -> None:
    rec = _rec()
    rec["live_gate"] = "enabled"
    violations = validate_leverage_recommendation(rec)
    assert any("live_gate" in v for v in violations)


def test_validate_catches_mutates_exchange_true() -> None:
    rec = _rec()
    rec["mutates_exchange"] = True
    violations = validate_leverage_recommendation(rec)
    assert any("mutates_exchange" in v for v in violations)


def test_validate_catches_cross_margin_mode() -> None:
    rec = _rec()
    rec["recommended_margin_mode"] = "cross"
    violations = validate_leverage_recommendation(rec)
    assert any("isolated" in v for v in violations)


def test_validate_catches_all_symbols_aggregate_true() -> None:
    rec = _rec()
    rec["all_symbols_aggregate"] = True
    violations = validate_leverage_recommendation(rec)
    assert any("all_symbols_aggregate" in v for v in violations)


def test_validate_catches_leverage_over_cap() -> None:
    rec = _rec()
    rec["recommended_leverage"] = 10
    violations = validate_leverage_recommendation(rec)
    assert any("recommended_leverage" in v for v in violations)
