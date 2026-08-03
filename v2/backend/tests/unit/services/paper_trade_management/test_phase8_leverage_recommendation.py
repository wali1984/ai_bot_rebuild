"""Phase 8 — Per-trade leverage and margin recommendation tests.

Validates:
 - Recommendations are per-symbol/TF/signal (not ALL_SYMBOLS aggregate)
 - live_gate is always "blocked_human_only"
 - mutates_exchange is always False
 - paper_only is always True
 - all_symbols_aggregate is always False
 - CROSS margin is never recommended
 - recommended_leverage is continuous and bounded in [1, PAPER_MAX_LEVERAGE]
 - confidence, after-cost edge, and ATR modulate leverage monotonically
 - no former confidence/ATR/edge boundary creates a selection cliff
 - authorized 75x/50x/20x symbol ceilings remain exact
 - max_loss_budget_usd respects cap
 - validate_leverage_recommendation catches invariant violations
"""
from __future__ import annotations

from dataclasses import fields

import pytest
from app.services.paper_trade_management.leverage_recommendation import (
    LIVE_GATE,
    PAPER_MAX_LEVERAGE,
    PAPER_MAX_LOSS_BUDGET_USD,
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
        assert rec["mutates_exchange"] is False, (
            f"mutates_exchange not False for direction={direction}"
        )


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
        rec = _rec(confidence_calibrated=confidence, atr_bps=25.0)
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


def test_confidence_continuously_modulates_leverage() -> None:
    lower = _rec(
        confidence_calibrated=0.40,
        direction="long",
        atr_bps=20.0,
        expected_move_after_cost_bps=30.0,
    )
    higher = _rec(
        confidence_calibrated=0.80,
        direction="long",
        atr_bps=20.0,
        expected_move_after_cost_bps=30.0,
    )
    assert 1.0 < lower["recommended_leverage"] < higher["recommended_leverage"]


def test_higher_volatility_continuously_reduces_leverage() -> None:
    low = _rec(confidence_calibrated=0.90, atr_bps=30.0)
    medium = _rec(confidence_calibrated=0.90, atr_bps=60.0)
    high = _rec(confidence_calibrated=0.90, atr_bps=120.0)
    assert (
        low["recommended_leverage"]
        > medium["recommended_leverage"]
        > high["recommended_leverage"]
        >= 1.0
    )


def test_high_confidence_low_volatility_scales_up_adaptively() -> None:
    # 2026-07-18 operator directive: leverage is per-symbol adaptive. High conf +
    # low vol + positive after-cost edge now earns well above the old fixed 3x,
    # bounded by the BTC ceiling (75x) and liquidation safety.
    rec = _rec(confidence_calibrated=0.80, atr_bps=15.0, expected_move_after_cost_bps=30.0)
    assert rec["recommended_leverage"] > 3
    assert rec["symbol_leverage_ceiling"] == 75
    assert rec["recommended_leverage"] <= rec["adaptive_leverage_ceiling"]
    assert rec["reason_tier"] == "CONTINUOUS_CONFIDENCE_EDGE_ATR_SCALED"


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
    rec = _rec(
        symbol="DOGEUSDT",
        confidence_calibrated=0.99,
        atr_bps=10.0,
        expected_move_after_cost_bps=90.0,
    )
    assert rec["symbol_leverage_ceiling"] == 20
    assert rec["recommended_leverage"] <= 20


def test_tier2_major_capped_at_50x() -> None:
    rec = _rec(
        symbol="SOLUSDT",
        confidence_calibrated=0.99,
        atr_bps=10.0,
        expected_move_after_cost_bps=90.0,
    )
    assert rec["symbol_leverage_ceiling"] == 50
    assert rec["recommended_leverage"] <= 50


def test_authorized_symbol_ceilings_are_exact_and_not_environment_mutable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("PAPER_MAX_LEVERAGE_MAJOR_TIER1", "999")
    monkeypatch.setenv("PAPER_MAX_LEVERAGE_MAJOR_TIER2", "1")
    monkeypatch.setenv("PAPER_MAX_LEVERAGE_ALT", "999")
    expected = {
        "BTCUSDT": 75,
        "ETHUSDT": 75,
        "SOLUSDT": 50,
        "LTCUSDT": 50,
        "XRPUSDT": 50,
        "DOGEUSDT": 20,
        "ADAUSDT": 20,
    }
    assert PAPER_MAX_LEVERAGE == 75
    for symbol, ceiling in expected.items():
        rec = _rec(
            symbol=symbol,
            confidence_calibrated=1.0,
            atr_bps=1.0,
            expected_move_after_cost_bps=1_000_000.0,
        )
        assert rec["symbol_leverage_ceiling"] == ceiling
        assert rec["adaptive_leverage_ceiling"] == pytest.approx(ceiling)
        assert rec["recommended_leverage"] <= ceiling


def test_market_selection_config_contains_no_confidence_atr_or_edge_thresholds() -> None:
    names = {item.name for item in fields(LeverageRecommendationConfig)}
    assert names.isdisjoint(
        {
            "very_high_confidence_threshold",
            "high_confidence_threshold",
            "low_confidence_threshold",
            "low_volatility_threshold_bps",
            "high_volatility_threshold_bps",
            "strong_edge_bps_for_5x",
        }
    )


@pytest.mark.parametrize("former_boundary", [0.55, 0.75, 0.85])
def test_no_confidence_cliff_at_former_boundaries(former_boundary: float) -> None:
    epsilon = 1e-6
    below = _rec(
        confidence_calibrated=former_boundary - epsilon,
        atr_bps=25.0,
        expected_move_after_cost_bps=35.0,
    )["recommended_leverage"]
    above = _rec(
        confidence_calibrated=former_boundary + epsilon,
        atr_bps=25.0,
        expected_move_after_cost_bps=35.0,
    )["recommended_leverage"]
    assert 0.0 < above - below < 0.001


@pytest.mark.parametrize("former_boundary", [30.0, 80.0])
def test_no_atr_cliff_at_former_boundaries(former_boundary: float) -> None:
    epsilon = 1e-6
    below = _rec(
        confidence_calibrated=0.9,
        atr_bps=former_boundary - epsilon,
        expected_move_after_cost_bps=45.0,
    )["recommended_leverage"]
    above = _rec(
        confidence_calibrated=0.9,
        atr_bps=former_boundary + epsilon,
        expected_move_after_cost_bps=45.0,
    )["recommended_leverage"]
    assert 0.0 < below - above < 0.001


@pytest.mark.parametrize("former_boundary", [20.0, 40.0])
def test_no_edge_cliff_at_former_reference_values(former_boundary: float) -> None:
    epsilon = 1e-6
    below = _rec(
        confidence_calibrated=0.9,
        atr_bps=30.0,
        expected_move_after_cost_bps=former_boundary - epsilon,
    )["recommended_leverage"]
    above = _rec(
        confidence_calibrated=0.9,
        atr_bps=30.0,
        expected_move_after_cost_bps=former_boundary + epsilon,
    )["recommended_leverage"]
    assert 0.0 < above - below < 0.001


def test_recommendation_is_monotonic_in_each_market_evidence_axis() -> None:
    confidence_path = [
        _rec(
            confidence_calibrated=value,
            atr_bps=30.0,
            expected_move_after_cost_bps=40.0,
        )["recommended_leverage"]
        for value in (0.0, 0.2, 0.5, 0.8, 1.0)
    ]
    edge_path = [
        _rec(
            confidence_calibrated=0.9,
            atr_bps=30.0,
            expected_move_after_cost_bps=value,
        )["recommended_leverage"]
        for value in (-10.0, 0.0, 5.0, 20.0, 60.0)
    ]
    atr_path = [
        _rec(
            confidence_calibrated=0.9,
            atr_bps=value,
            expected_move_after_cost_bps=40.0,
        )["recommended_leverage"]
        for value in (5.0, 15.0, 30.0, 60.0, 120.0)
    ]
    assert confidence_path == sorted(confidence_path)
    assert edge_path == sorted(edge_path)
    assert atr_path == sorted(atr_path, reverse=True)


def test_signed_edge_is_symmetric_for_profitable_long_and_short() -> None:
    long = _rec(
        direction="long",
        confidence_calibrated=0.87,
        atr_bps=30.0,
        expected_move_after_cost_bps=45.0,
    )
    short = _rec(
        direction="short",
        confidence_calibrated=0.87,
        atr_bps=30.0,
        expected_move_after_cost_bps=-45.0,
    )
    assert long["recommended_leverage"] == short["recommended_leverage"]
    assert long["direction_aligned_after_cost_edge_bps"] == 45.0
    assert short["direction_aligned_after_cost_edge_bps"] == 45.0
    assert long["direction_aligned_edge_source"] == "SIGNED_EDGE_ALIGNED_TO_LONG"
    assert short["direction_aligned_edge_source"] == "SIGNED_EDGE_ALIGNED_TO_SHORT"


def test_adverse_signed_edge_is_1x_for_both_directions() -> None:
    adverse_long = _rec(
        direction="long",
        confidence_calibrated=1.0,
        atr_bps=10.0,
        expected_move_after_cost_bps=-100.0,
    )
    adverse_short = _rec(
        direction="short",
        confidence_calibrated=1.0,
        atr_bps=10.0,
        expected_move_after_cost_bps=100.0,
    )
    assert adverse_long["recommended_leverage"] == 1.0
    assert adverse_short["recommended_leverage"] == 1.0
    assert adverse_long["direction_aligned_after_cost_edge_bps"] == -100.0
    assert adverse_short["direction_aligned_after_cost_edge_bps"] == -100.0


def test_profitable_short_leverage_is_monotonic_with_signed_edge_magnitude() -> None:
    leverage_path = [
        _rec(
            direction="short",
            confidence_calibrated=0.9,
            atr_bps=30.0,
            expected_move_after_cost_bps=value,
        )["recommended_leverage"]
        for value in (0.0, -5.0, -20.0, -60.0)
    ]
    assert leverage_path == sorted(leverage_path)


def test_unknown_direction_fails_closed() -> None:
    rec = _rec(
        direction="sideways",
        confidence_calibrated=1.0,
        atr_bps=1.0,
        expected_move_after_cost_bps=1_000.0,
    )
    assert rec["recommended_leverage"] == 1.0
    assert rec["direction_aligned_after_cost_edge_bps"] is None
    assert rec["reason_tier"] == "DIRECTION_INVALID_FAIL_CLOSED_1X"


def test_malformed_optional_evidence_fails_closed_without_raising() -> None:
    rec = recommend_leverage_for_signal(
        symbol=None,  # type: ignore[arg-type]
        timeframe=None,  # type: ignore[arg-type]
        signal_id="malformed-evidence",
        direction="long",
        confidence_calibrated="not-a-number",  # type: ignore[arg-type]
        expected_move_after_cost_bps="not-a-number",  # type: ignore[arg-type]
        atr_bps="not-a-number",  # type: ignore[arg-type]
        equity_usd="not-a-number",  # type: ignore[arg-type]
    )

    assert rec["symbol"] == ""
    assert rec["timeframe"] == ""
    assert rec["recommended_leverage"] == 1.0
    assert rec["confidence_quality"] == 0.0
    assert rec["volatility_budget_bps"] is None
    assert rec["max_loss_budget_usd"] == PAPER_MAX_LOSS_BUDGET_USD
    assert rec["reason_tier"] == "ATR_EVIDENCE_INVALID_FAIL_CLOSED_1X"


def test_paper_recommendation_retains_fractional_continuity() -> None:
    rec = _rec(
        confidence_calibrated=0.63,
        atr_bps=43.0,
        expected_move_after_cost_bps=17.0,
    )
    assert isinstance(rec["recommended_leverage"], float)
    assert not rec["recommended_leverage"].is_integer()
    assert rec["market_selection_formula"].startswith(
        "1 + (adaptive_ceiling - 1)"
    )


def test_high_volatility_continuously_contracts_to_liquidation_safe_leverage() -> None:
    calm = _rec(
        confidence_calibrated=0.95,
        atr_bps=45.0,
        expected_move_after_cost_bps=60.0,
    )
    choppy = _rec(
        confidence_calibrated=0.95,
        atr_bps=90.0,
        expected_move_after_cost_bps=60.0,
    )
    assert 1.0 < choppy["recommended_leverage"] < calm["recommended_leverage"]
    assert choppy["recommended_leverage"] <= choppy[
        "liquidation_safe_leverage_ceiling"
    ]
    assert choppy["liquidation_distance_bps"] >= (5.0 * 90.0) - 1e-9


def test_missing_or_invalid_atr_fails_closed_without_a_static_default() -> None:
    for atr in (None, 0.0, -1.0, float("nan"), float("inf")):
        rec = _rec(
            confidence_calibrated=1.0,
            atr_bps=atr,
            expected_move_after_cost_bps=1_000.0,
        )
        assert rec["recommended_leverage"] == 1.0
        assert rec["adaptive_leverage_ceiling"] == 1.0
        assert rec["reason_tier"] == "ATR_EVIDENCE_INVALID_FAIL_CLOSED_1X"
        assert rec["volatility_budget_bps"] is None
        assert rec["volatility_budget_source"] == (
            "ATR_EVIDENCE_INVALID_FAIL_CLOSED"
        )


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
    assert rec["reason_tier"] == (
        "CONTINUOUS_NON_POSITIVE_DIRECTION_ALIGNED_EDGE_1X"
    )


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


def test_confidence_budget_is_continuous_from_zero_without_a_static_floor() -> None:
    zero = _rec(confidence_calibrated=0.0)["confidence_budget_pct"]
    epsilon = _rec(confidence_calibrated=1e-6)["confidence_budget_pct"]
    moderate = _rec(confidence_calibrated=0.5)["confidence_budget_pct"]
    assert zero == 0.0
    assert 0.0 < epsilon < moderate < 0.05


def test_max_loss_budget_usd_within_cap() -> None:
    rec = _rec(equity_usd=10000.0)
    assert rec["max_loss_budget_usd"] <= 50.0  # PAPER_MAX_LOSS_BUDGET_USD


def test_reason_contains_symbol_and_leverage() -> None:
    rec = _rec(symbol="BTCUSDT", confidence_calibrated=0.65, atr_bps=50.0)
    assert "BTCUSDT" in rec["reason"]
    assert f"lev={rec['recommended_leverage']:.8f}x" in rec["reason"]


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
