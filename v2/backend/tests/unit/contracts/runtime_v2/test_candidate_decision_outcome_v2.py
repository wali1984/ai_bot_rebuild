from __future__ import annotations

from v2.backend.app.contracts.runtime_v2.candidate_decision_outcome_v2 import (
    CandidateDecisionOutcomeV2,
    MaturedLabelsV2,
)


def _decision(**overrides):
    kw = dict(
        candidate_id="cand-1",
        state_id="state-1",
        prediction_id="pred-1",
        policy_id="policy-1",
        checkpoint_generation=4,
        symbol="OPUSDT",
        timeframe="1h",
        disposition="REJECTED",
        proposed_action={"side": "long"},
        selected_action={"selected_action": "FLAT"},
        model_distributions={"long": 0.3, "short": 0.2, "hold": 0.5},
        component_estimates={"loss_probability": 0.6},
        portfolio_state={"equity_usd": 2985.0},
        execution_state={"venue_min_notional": 5.0},
        decision_rationale="loss_probability above policy input",
        decision_time="2026-07-27T18:00:00Z",
        disposition_reason="EXIT_FEASIBILITY_BELOW_POLICY_INPUT",
    )
    kw.update(overrides)
    return CandidateDecisionOutcomeV2(**kw)


def _matured(**overrides):
    kw = dict(
        matured=True,
        future_returns_bps_by_horizon={"5m": 3.0, "1h": 12.0},
        max_favorable_excursion_bps=20.0,
        max_adverse_excursion_bps=-8.0,
        realized_volatility_bps=15.0,
        estimated_executable_entry=1.23,
        estimated_executable_exit=1.24,
        fees_bps=2.0,
        spread_bps=1.0,
        slippage_bps=1.5,
        funding_bps=0.5,
        market_impact_bps=0.3,
        stop_result="NOT_HIT",
        time_exit_result="HORIZON",
        profit_exit_result="NONE",
        realized_action_pnl_bps=None,
        counts_as_paper_profit=False,
        counterfactual_outcomes={
            "unhedged": {"pnl_bps": 8.0, "counts_as_paper_profit": False},
            "alternative_side": {"pnl_bps": -8.0, "counts_as_paper_profit": False},
        },
    )
    kw.update(overrides)
    return MaturedLabelsV2(**kw)


def test_rejected_candidate_is_recorded_with_reason():
    assert _decision().validate() == []


def test_every_disposition_is_recordable():
    for disp in ("TRADED", "REJECTED", "INFEASIBLE", "RISK_REDUCED", "FLAT", "HEDGED"):
        d = _decision(disposition=disp, disposition_reason="x")
        assert "DISPOSITION_INVALID" not in "".join(d.validate())


def test_non_traded_without_reason_rejected():
    reasons = _decision(disposition="FLAT", disposition_reason="").validate()
    assert "NON_TRADED_WITHOUT_REASON" in reasons


def test_counterfactual_can_never_be_paper_profit():
    ml = _matured(counterfactual_outcomes={"hedged": {"pnl_bps": 5.0, "counts_as_paper_profit": True}})
    reasons = _decision(disposition="TRADED", matured_labels=ml).validate()
    assert "COUNTERFACTUAL_COUNTS_AS_PROFIT_FORBIDDEN:hedged" in reasons


def test_only_traded_candidate_may_book_profit():
    ml = _matured(realized_action_pnl_bps=10.0, counts_as_paper_profit=True)
    reasons = _decision(disposition="REJECTED", matured_labels=ml).validate()
    assert "NON_TRADED_CANDIDATE_CLAIMS_PAPER_PROFIT" in reasons


def test_traded_candidate_with_profit_and_finite_pnl_valid():
    ml = _matured(realized_action_pnl_bps=10.0, counts_as_paper_profit=True)
    assert _decision(disposition="TRADED", disposition_reason="admitted", matured_labels=ml).validate() == []


def test_profit_without_finite_pnl_rejected():
    ml = _matured(realized_action_pnl_bps=None, counts_as_paper_profit=True)
    reasons = _decision(disposition="TRADED", matured_labels=ml).validate()
    assert "PROFIT_CLAIMED_WITHOUT_FINITE_REALIZED_PNL" in reasons


def test_unknown_counterfactual_arm_rejected():
    ml = _matured(counterfactual_outcomes={"telepathy": {"pnl_bps": 1.0, "counts_as_paper_profit": False}})
    reasons = _decision(matured_labels=ml).validate()
    assert "COUNTERFACTUAL_ARM_UNKNOWN:telepathy" in reasons


def test_content_hash_deterministic_and_sensitive():
    assert _decision().content_sha256() == _decision().content_sha256()
    assert _decision().content_sha256() != _decision(candidate_id="cand-2").content_sha256()
