"""Hard-rule coverage for preemptive edge control (Claude lane).

Covers fail-closed on missing evidence/guardian, NO_TRADE on negative buckets
and non-positive after-cost edge, stop-inside-noise, trust haircut to
REDUCE_SIZE_PAPER_ONLY, the day-zero counterfactual replay of the 2026-07
high-confidence loss cluster admission, and summarize hard-fail counters.
"""

from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.decision import (
    PREEMPTIVE_DECISIONS,
    evaluate_candidate,
    summarize_decisions,
)

GUARDIAN_ALLOW = {
    "status": "ACTIVE",
    "a_grade_new_entries_allowed": True,
    "new_entries_allowed": True,
}
GUARDIAN_HALTED = {
    "status": "HALTED_PERFORMANCE",
    "a_grade_new_entries_allowed": False,
}


def _candidate(**overrides) -> dict:
    base = {
        "symbol": "DOGEUSDT",
        "timeframe": "15m",
        "side": "long",
        "strategy_selected_mode": "trend_mode",
        "market_regime_at_entry": "TREND",
        "confidence_calibrated": 0.72,
        "expected_move_bps": 55.0,
        "expected_move_after_cost_bps": 45.0,
        "pre_trade_fee_bps": 4.0,
        "expected_slippage_bps": 2.0,
        "observed_spread_bps": 1.5,
        "stop_distance_bps": 70.0,
        "entry_atr_bps": 80.0,
        "atr_bps": 80.0,
        "target_notional_usd": 200.0,
        "allocated_margin_usd": 100.0,
        "orderbook_depth_usd": 5000.0,
        "composite_microstructure_trust_score": 0.72,
        "trade_tape_confirmation_score": 0.7,
        "cross_venue_confirmation_score": 0.7,
        "risk_budget_usd": 2.0,
        "advanced_indicator_context": {
            "bullish_fvg_present": False,
            "bearish_fvg_present": False,
            "sweep_risk_long_side": 0.15,
            "trade_tape_confirmation_score": 0.72,
            "fvg_orderbook_trust_confluence": 0.72,
            "fvg_expected_edge_after_cost": 45.0,
            "distance_to_vwap_bps": 4.0,
            "cvd_slope": 0.2,
        },
    }
    base.update(overrides)
    return base


def _winning_history(n: int = 5) -> list[dict]:
    return [
        {
            "symbol": "DOGEUSDT",
            "timeframe": "15m",
            "side": "long",
            "strategy_selected_mode": "trend_mode",
            "market_regime_at_entry": "TREND",
            "confidence_calibrated": 0.72,
            "realized_pnl_bps": 50.0,
            "realized_net_pnl_usd": 1.0,
            "gross_notional_usd": 200.0,
            "exit_reason": "TIER_2_TRAILING_STOP",
        }
        for _ in range(n)
    ]


def test_missing_candidate_fails_closed_no_trade() -> None:
    result = evaluate_candidate({}, continuous_edge_guardian_gate=GUARDIAN_ALLOW)
    assert result["preemptive_decision"] == "NO_TRADE"
    assert result["preemptive_decision_id"]


def test_decision_object_always_has_id_and_valid_decision() -> None:
    result = evaluate_candidate(
        _candidate(),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )
    assert result["preemptive_decision"] in PREEMPTIVE_DECISIONS
    assert result["preemptive_decision_id"].startswith("pec_")
    assert result["places_real_order"] is False
    assert result["routes_to_live"] is False


def test_guardian_missing_blocks_entry() -> None:
    result = evaluate_candidate(
        _candidate(),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=None,
    )
    assert result["preemptive_decision"] == "NO_TRADE"


def test_guardian_halted_blocks_entry() -> None:
    result = evaluate_candidate(
        _candidate(),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_HALTED,
    )
    assert result["preemptive_decision"] == "NO_TRADE"


def test_negative_bucket_blocks_entry() -> None:
    losing = [
        {**row, "realized_pnl_bps": -50.0, "realized_net_pnl_usd": -1.0}
        for row in _winning_history(5)
    ]
    result = evaluate_candidate(
        _candidate(),
        closed_rows=losing,
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )
    assert result["preemptive_decision"] == "NO_TRADE"


def test_non_positive_edge_after_cost_blocks_entry() -> None:
    result = evaluate_candidate(
        _candidate(expected_move_after_cost_bps=-2.0, expected_move_bps=5.0),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )
    assert result["preemptive_decision"] == "NO_TRADE"


def test_stop_inside_noise_cannot_be_allowed() -> None:
    result = evaluate_candidate(
        _candidate(stop_distance_bps=10.0, entry_atr_bps=100.0, atr_bps=100.0),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )
    assert result["preemptive_decision"] != "ALLOW"


def test_low_trust_caps_to_reduce_size_paper_only() -> None:
    result = evaluate_candidate(
        _candidate(composite_microstructure_trust_score=0.55),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )
    assert result["preemptive_decision"] == "REDUCE_SIZE_PAPER_ONLY"
    assert result["allow_reduced_size_paper_only"] is True


def test_day_zero_cluster_entry_counterfactual_is_not_allowed() -> None:
    candidate = _candidate(
        symbol="CRVUSDT",
        timeframe="4h",
        side="short",
        strategy_selected_mode="scalp_mode",
        market_regime_at_entry="HIGH_VOLATILITY",
        confidence_calibrated=0.784,
        confidence_raw=0.999999,
        expected_move_bps=-29.4,
        expected_move_after_cost_bps=-17.4,
    )
    for field in (
        "composite_microstructure_trust_score",
        "trade_tape_confirmation_score",
        "cross_venue_confirmation_score",
    ):
        candidate.pop(field, None)
    result = evaluate_candidate(
        candidate,
        closed_rows=[],
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )
    assert result["preemptive_decision"] not in {"ALLOW", "REDUCE_SIZE_PAPER_ONLY"}


def test_summarize_flags_accepted_row_without_decision_as_hard_fail() -> None:
    decisions = [
        evaluate_candidate(
            _candidate(),
            closed_rows=_winning_history(),
            continuous_edge_guardian_gate=GUARDIAN_ALLOW,
        )
    ]
    summary = summarize_decisions(
        decisions,
        accepted_rows=[{"symbol": "DOGEUSDT"}],
        generated_utc="2026-07-07T22:00:00Z",
    )
    assert summary["accepted_without_preemptive_decision"] == 1
    assert summary["hard_fail"] is True
