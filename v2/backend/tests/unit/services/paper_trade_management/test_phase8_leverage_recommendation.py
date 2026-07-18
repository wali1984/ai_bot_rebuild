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


def test_high_confidence_low_volatility_scales_up_adaptively() -> None:
    # 2026-07-18 operator directive: leverage is per-symbol adaptive. High conf +
    # low vol + positive after-cost edge now earns well above the old fixed 3x,
    # bounded by the BTC ceiling (75x) and liquidation safety.
    rec = _rec(confidence_calibrated=0.80, atr_bps=15.0, expected_move_after_cost_bps=30.0)
    assert rec["recommended_leverage"] > 3
    assert rec["symbol_leverage_ceiling"] == 75
    assert rec["recommended_leverage"] <= rec["adaptive_leverage_ceiling"]
    assert rec["reason_tier"].startswith("ADAPTIVE_EVIDENCE_SCALED_")


def test_max_evidence_approaches_symbol_ceiling() -> None:
    # Very high confidence + strong after-cost edge + very tight range approaches
    # the BTC ceiling (75x) — earned, not granted.
    rec = _rec(confidence_calibrated=0.99, atr_bps=10.0, expected_move_after_cost_bps=60.0)
    assert rec["recommended_leverage"] >= 60
    assert rec["recommended_leverage"] <= 75


def test_high_confidence_weak_edge_stays_low() -> None:
    # High confidence but weak after-cost edge -> low leverage: the edge axis
    # gates the multiplicative quality score, so weak edge cannot lever up.
    rec = _rec(confidence_calibrated=0.87, atr_bps=15.0, expected_move_after_cost_bps=6.0)
    assert rec["recommended_leverage"] <= 12


def test_moderate_confidence_gives_modest_leverage() -> None:
    rec = _rec(confidence_calibrated=0.65, atr_bps=50.0, expected_move_after_cost_bps=20.0)
    assert 1 <= rec["recommended_leverage"] <= 6


def test_alt_symbol_capped_at_20x() -> None:
    # Non-major alt caps at 20x even with maximal evidence.
    rec = _rec(symbol="DOGEUSDT", confidence_calibrated=0.99, atr_bps=10.0, expected_move_after_cost_bps=90.0)
    assert rec["symbol_leverage_ceiling"] == 20
    assert rec["recommended_leverage"] <= 20


def test_tier2_major_capped_at_50x() -> None:
    rec = _rec(symbol="SOLUSDT", confidence_calibrated=0.99, atr_bps=10.0, expected_move_after_cost_bps=90.0)
    assert rec["symbol_leverage_ceiling"] == 50
    assert rec["recommended_leverage"] <= 50


def test_high_volatility_forces_liquidation_safe_low_leverage() -> None:
    # Choppy market: high-vol gate -> 1x, and the liq-safe ceiling contracts too.
    rec = _rec(confidence_calibrated=0.95, atr_bps=90.0, expected_move_after_cost_bps=60.0)
    assert rec["recommended_leverage"] == 1
    assert rec["reason_tier"] == "HIGH_VOLATILITY_1X"


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
    rec_low = _rec(confidence_calibrated=0.40)  # low conf -> 1x
    rec_high = _rec(confidence_calibrated=0.90, atr_bps=15.0, expected_move_after_cost_bps=45.0)
    assert rec_low["recommended_leverage"] < rec_high["recommended_leverage"]
    # Higher leverage → closer to liquidation (lower bps)
    assert rec_low["liquidation_distance_bps"] > rec_high["liquidation_distance_bps"]


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
    assert f"lev={rec['recommended_leverage']}x" in rec["reason"]


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
    rec["recommended_leverage"] = PAPER_MAX_LEVERAGE + 5  # above the absolute cap (75)
    violations = validate_leverage_recommendation(rec)
    assert any("recommended_leverage" in v for v in violations)


def test_validate_catches_leverage_over_symbol_ceiling() -> None:
    # An alt (20x ceiling) recommended above its tier must be flagged even though
    # the value is under the absolute 75x cap.
    rec = _rec(symbol="DOGEUSDT")
    rec["recommended_leverage"] = 40
    violations = validate_leverage_recommendation(rec)
    assert any("symbol ceiling" in v for v in violations)
