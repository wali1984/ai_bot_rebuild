"""Tests for the trainer leverage/margin exploration study."""

from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.leverage_margin_exploration import (
    DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY,
    DEFAULT_MIN_LIQUIDATION_BUFFER_BPS,
    evaluate_leverage_for_candidate,
    evaluate_leverage_margin_grid,
)


def _measured_candidate(**overrides: object) -> dict[str, object]:
    candidate: dict[str, object] = {
        "expected_move_after_cost_bps": 40.0,
        "edge_uncertainty_bps": 5.0,
        "edge_evidence_count": 250.0,
        "edge_evidence_source": "purged_chronological_holdout_after_cost",
        "edge_available_at": "2026-07-17T17:59:00Z",
        "loss_probability": 0.35,
        "stop_distance_bps": 40.0,
        "modeled_adverse_move_bps": 100.0,
        "execution_uncertainty_bps": 5.0,
        "equity_usd": 200.0,
        "base_margin_usd": 60.0,
        "available_margin_usd": 180.0,
        "base_liquidation_buffer_bps": 9_500.0,
        "drawdown_bps": 0.0,
        "regime_risk_score": 0.10,
        "liquidity_score": 0.90,
        "risk_context_source": "point_in_time_market_and_account_snapshot",
        "risk_context_available_at": "2026-07-17T17:59:30Z",
        "decision_time": "2026-07-17T18:00:00Z",
    }
    candidate.update(overrides)
    return candidate


def test_positive_measured_edge_can_select_leverage_above_1x() -> None:
    out = evaluate_leverage_margin_grid(_measured_candidate())

    assert out["input_evidence_complete"] is True
    assert out["study_admission_allowed"] is True
    assert out["best_leverage"] == 3.0
    assert out["best_risk_adjusted_score"] > 0.0
    assert {row["leverage"] for row in out["per_leverage_breakdown"]} == {1.0, 2.0, 3.0}
    scores = [row["risk_adjusted_score"] for row in out["per_leverage_breakdown"]]
    assert len(set(scores)) == 3  # Regression: the old formula made every score identical.


def test_context_changes_can_reduce_optimal_leverage_without_a_static_edge_threshold() -> None:
    favorable = evaluate_leverage_margin_grid(_measured_candidate())
    stressed = evaluate_leverage_margin_grid(
        _measured_candidate(
            expected_move_after_cost_bps=12.0,
            edge_uncertainty_bps=5.0,
            loss_probability=0.55,
            stop_distance_bps=50.0,
            modeled_adverse_move_bps=150.0,
            drawdown_bps=1_000.0,
            regime_risk_score=0.40,
            liquidity_score=0.50,
        )
    )

    assert favorable["best_leverage"] == 3.0
    assert stressed["best_leverage"] == 2.0
    assert stressed["best_leverage"] < favorable["best_leverage"]


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("edge_uncertainty_bps", None, "MISSING_EDGE_UNCERTAINTY_BPS"),
        ("loss_probability", None, "MISSING_LOSS_PROBABILITY"),
        ("drawdown_bps", None, "MISSING_DRAWDOWN_BPS"),
        ("regime_risk_score", None, "MISSING_REGIME_RISK_SCORE"),
        ("liquidity_score", None, "MISSING_LIQUIDITY_SCORE"),
        ("base_margin_usd", None, "MISSING_BASE_MARGIN_USD"),
        ("available_margin_usd", None, "MISSING_AVAILABLE_MARGIN_USD"),
        ("base_liquidation_buffer_bps", None, "MISSING_BASE_LIQUIDATION_BUFFER_BPS"),
        ("edge_evidence_source", None, "MISSING_EDGE_EVIDENCE_SOURCE"),
        ("risk_context_source", None, "MISSING_RISK_CONTEXT_SOURCE"),
        ("edge_available_at", None, "MISSING_OR_INVALID_EDGE_AVAILABLE_AT"),
        (
            "risk_context_available_at",
            None,
            "MISSING_OR_INVALID_RISK_CONTEXT_AVAILABLE_AT",
        ),
        ("decision_time", None, "MISSING_OR_INVALID_DECISION_TIME"),
    ],
)
def test_missing_required_evidence_fails_closed(
    field: str,
    value: object,
    reason: str,
) -> None:
    out = evaluate_leverage_margin_grid(_measured_candidate(**{field: value}))

    assert out["input_evidence_complete"] is False
    assert out["study_admission_allowed"] is False
    assert out["best_leverage"] is None
    assert reason in out["input_rejection_reasons"]
    assert all(row["eligible"] is False for row in out["per_leverage_breakdown"])


def test_non_positive_or_uncertain_edge_produces_no_recommendation() -> None:
    negative = evaluate_leverage_margin_grid(
        _measured_candidate(expected_move_after_cost_bps=-10.0)
    )
    uncertain = evaluate_leverage_margin_grid(
        _measured_candidate(expected_move_after_cost_bps=4.0, edge_uncertainty_bps=5.0)
    )

    assert negative["best_leverage"] is None
    assert negative["study_admission_allowed"] is False
    assert "NON_POSITIVE_AFTER_COST_EDGE" in negative["input_rejection_reasons"]
    assert uncertain["best_leverage"] is None
    assert "EDGE_LOWER_BOUND_NOT_POSITIVE" in uncertain["input_rejection_reasons"]


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("edge_available_at", "EDGE_AVAILABLE_AFTER_DECISION_TIME"),
        ("risk_context_available_at", "RISK_CONTEXT_AVAILABLE_AFTER_DECISION_TIME"),
    ],
)
def test_future_available_evidence_is_rejected(field: str, reason: str) -> None:
    out = evaluate_leverage_margin_grid(
        _measured_candidate(**{field: "2026-07-17T18:00:01Z"})
    )

    assert out["best_leverage"] is None
    assert out["study_admission_allowed"] is False
    assert reason in out["input_rejection_reasons"]
    assert all(row["point_in_time_safe"] is False for row in out["per_leverage_breakdown"])


def test_margin_and_notional_are_not_conflated() -> None:
    row = evaluate_leverage_for_candidate(
        **_measured_candidate(),
        leverage=3.0,
    )

    assert row["allocated_margin_usd"] == pytest.approx(60.0)
    assert row["gross_notional_usd"] == pytest.approx(180.0)
    assert row["levered_max_loss_usd"] == pytest.approx(1.89)


def test_stressed_liquidation_buffer_rejects_only_unsafe_leverage() -> None:
    out = evaluate_leverage_margin_grid(
        _measured_candidate(
            base_liquidation_buffer_bps=2_000.0,
            base_margin_usd=20.0,
            modeled_adverse_move_bps=200.0,
            execution_uncertainty_bps=10.0,
        )
    )
    rows = {row["leverage"]: row for row in out["per_leverage_breakdown"]}

    assert rows[1.0]["eligible"] is True
    assert rows[2.0]["eligible"] is True
    assert rows[3.0]["eligible"] is False
    assert rows[3.0]["reject_reason"] == "STRESSED_LIQUIDATION_BUFFER_BELOW_IMMUTABLE_FLOOR"


def test_modeled_max_loss_over_cap_rejects_leverage() -> None:
    row = evaluate_leverage_for_candidate(
        **_measured_candidate(
            equity_usd=200.0,
            base_margin_usd=180.0,
            available_margin_usd=200.0,
            stop_distance_bps=500.0,
            modeled_adverse_move_bps=500.0,
        ),
        leverage=3.0,
    )

    assert row["eligible"] is False
    assert row["reject_reason"] == "MODELED_MAX_LOSS_EXCEEDS_IMMUTABLE_PER_TRADE_CAP"


def test_callers_can_tighten_but_not_widen_immutable_safety_caps() -> None:
    widened = evaluate_leverage_for_candidate(
        **_measured_candidate(),
        leverage=1.0,
        min_liquidation_buffer_bps=1.0,
        max_loss_fraction_of_equity=0.50,
    )
    tightened = evaluate_leverage_for_candidate(
        **_measured_candidate(),
        leverage=1.0,
        min_liquidation_buffer_bps=1_000.0,
        max_loss_fraction_of_equity=0.005,
    )

    assert widened["effective_min_liquidation_buffer_bps"] == DEFAULT_MIN_LIQUIDATION_BUFFER_BPS
    assert widened["effective_max_loss_fraction_of_equity"] == DEFAULT_MAX_LOSS_FRACTION_OF_EQUITY
    assert tightened["effective_min_liquidation_buffer_bps"] == 1_000.0
    assert tightened["effective_max_loss_fraction_of_equity"] == 0.005


def test_leverage_above_existing_study_envelope_is_rejected() -> None:
    row = evaluate_leverage_for_candidate(**_measured_candidate(), leverage=4.0)

    assert row["eligible"] is False
    assert row["reject_reason"] == "LEVERAGE_ABOVE_IMMUTABLE_STUDY_CAP"


def test_cross_margin_is_not_falsely_claimed_as_evaluated() -> None:
    out = evaluate_leverage_margin_grid(_measured_candidate())
    modes = {row["margin_mode"]: row for row in out["per_margin_mode_breakdown"]}

    assert out["best_margin_mode"] == "isolated"
    assert out["margin_modes_evaluated"] == ["isolated"]
    assert modes["cross"]["evaluated"] is False
    assert modes["cross"]["eligible"] is False
    assert modes["cross"]["reject_reason"] == (
        "CROSS_MARGIN_REQUIRES_ACCOUNT_WIDE_STRESS_AND_CONTAGION_MODEL"
    )


def test_study_never_routes_to_live() -> None:
    out = evaluate_leverage_margin_grid(_measured_candidate())

    assert out["study_only"] is True
    assert out["routes_to_live"] is False
    assert out["places_real_order"] is False
    assert out["leverage_mutated"] is False
    assert out["margin_mutated"] is False
