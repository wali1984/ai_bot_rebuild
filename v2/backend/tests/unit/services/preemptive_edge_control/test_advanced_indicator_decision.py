from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.decision import evaluate_candidate


GUARDIAN_ALLOW = {
    "status": "ACTIVE",
    "a_grade_new_entries_allowed": True,
    "new_entries_allowed": True,
}


def _candidate(**overrides) -> dict:
    base = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "strategy_id": "trend_mode",
        "market_regime": "TREND",
        "confidence_raw": 0.68,
        "confidence_calibrated": 0.66,
        "expected_move_after_cost_bps": 22.0,
        "composite_microstructure_trust_score": 0.78,
        "trade_tape_confirmation_score": 0.7,
        "stop_distance_bps": 45.0,
        "ATR_bps": 18.0,
        "spread_bps": 2.0,
        "slippage_bps": 2.0,
        "funding_bps": 0.2,
        "gross_notional_usd": 1000.0,
        "risk_budget_usd": 8.0,
    }
    base.update(overrides)
    return base


def _winning_history() -> list[dict]:
    return [
        {
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "side": "long",
            "strategy_selected_mode": "trend_mode",
            "market_regime_at_entry": "TREND",
            "confidence_calibrated": 0.70,
            "realized_pnl_bps": 40.0,
            "realized_net_pnl_usd": 4.0,
            "gross_notional_usd": 1000.0,
            "exit_reason": "TAKE_PROFIT",
        }
        for _ in range(5)
    ]


def test_high_liquidity_sweep_risk_blocks_before_entry() -> None:
    result = evaluate_candidate(
        _candidate(
            advanced_indicator_context={
                "sweep_risk_long_side": 0.92,
                "trade_tape_confirmation_score": 0.3,
            }
        ),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )

    assert result["preemptive_decision"] == "NO_TRADE"
    assert "LIQUIDITY_SWEEP_RISK_HIGH_UNCONFIRMED" in result["preemptive_decision_reasons"]
    assert result["advanced_indicator_consumed"] is True


def test_choch_against_direction_blocks_before_entry() -> None:
    result = evaluate_candidate(
        _candidate(advanced_indicator_context={"choch_direction": "down"}),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )

    assert result["preemptive_decision"] == "NO_TRADE"
    assert "CHOCH_AGAINST_LONG_DIRECTION" in result["preemptive_decision_reasons"]


def test_missing_advanced_indicator_context_shadows_instead_of_defaulting_neutral() -> None:
    result = evaluate_candidate(
        _candidate(),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )

    assert result["preemptive_decision"] == "SHADOW_ONLY"
    assert "ADVANCED_INDICATOR_CONTEXT_MISSING" in result["preemptive_decision_reasons"]
    assert result["advanced_indicator_shadow"] is True


def test_invalid_advanced_indicator_contract_shadows_instead_of_defaulting_neutral() -> None:
    result = evaluate_candidate(
        _candidate(
            advanced_indicator_context={"sweep_risk_long_side": 0.1},
            advanced_indicator_invalid_contract_keys=[{"key": "v2:market:fvg:BTCUSDT:5m"}],
        ),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )

    assert result["preemptive_decision"] == "SHADOW_ONLY"
    assert "ADVANCED_INDICATOR_CONTRACT_INVALID_OR_UNREPAIRED" in result["preemptive_decision_reasons"]
    assert result["advanced_indicator_shadow"] is True


def test_fvg_alone_cannot_override_bad_after_cost_edge() -> None:
    result = evaluate_candidate(
        _candidate(
            expected_move_after_cost_bps=-4.0,
            advanced_indicator_context={
                "bullish_fvg_present": True,
                "fvg_trade_tape_confirmation": 0.9,
                "fvg_orderbook_trust_confluence": 0.9,
                "fvg_expected_edge_after_cost": 12.0,
            },
        ),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )

    assert result["preemptive_decision"] == "NO_TRADE"
    assert result["fvg_standalone_allows_trade"] is False


def test_fvg_confluence_uses_computed_exit_feasibility_score() -> None:
    result = evaluate_candidate(
        _candidate(
            expected_move_after_cost_bps=50.0,
            advanced_indicator_context={
                "bullish_fvg_present": True,
                "fvg_trade_tape_confirmation": 0.9,
                "fvg_orderbook_trust_confluence": 0.9,
                "fvg_expected_edge_after_cost": 50.0,
            },
        ),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate=GUARDIAN_ALLOW,
    )

    assert "FVG_CONFLUENCE_WITHOUT_VALID_EXIT_FEASIBILITY" not in result["preemptive_decision_reasons"]
    assert result["advanced_indicator_shadow"] is False


def test_guardian_halted_executable_candidate_routes_to_paper_risk_controller_exploration_only() -> None:
    result = evaluate_candidate(
        _candidate(
            expected_move_after_cost_bps=60.0,
            exit_feasibility_score=0.82,
            advanced_indicator_context={
                "bullish_fvg_present": True,
                "fvg_trade_tape_confirmation": 0.9,
                "fvg_orderbook_trust_confluence": 0.9,
                "fvg_expected_edge_after_cost": 60.0,
            },
        ),
        closed_rows=_winning_history(),
        continuous_edge_guardian_gate={
            "status": "HALTED_AFTER_PIT_THRESHOLD_MET",
            "a_grade_new_entries_allowed": False,
            "new_entries_allowed": False,
        },
        allow_paper_risk_controller_exploration=True,
    )

    assert result["preemptive_decision"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert result["preemptive_action"] == "ALLOW_PAPER_RISK_CONTROLLER_EXPLORATION"
    assert result["allow_paper_risk_controller_exploration"] is True
    assert result["paper_risk_controller_exploration"] is True
    assert result["preemptive_counts_as_a_plus"] is False
    assert result["preemptive_counts_as_live_ready"] is False
    assert result["routes_to_live"] is False
    assert result["places_real_order"] is False
    assert result["allow_live_dry_run"] is False
