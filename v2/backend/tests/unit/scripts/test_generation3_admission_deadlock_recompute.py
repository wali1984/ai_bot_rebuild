from __future__ import annotations

from scripts.generation3_admission_deadlock_recompute import independent_reference


def _values(**overrides):
    values = {
        "side": "long",
        "model_loss_probability": 0.20,
        "adaptive_model_loss_probability_limit": 0.0,
        "microstructure_action": "REDUCE_SIZE",
        "microstructure_score": 0.59,
        "exit_feasibility": 1.0,
        "expected_edge_after_cost_bps": 120.0,
        "confidence_overstatement_risk": 0.0,
        "decision_time_valid": True,
        "every_block_reason": [],
    }
    values.update(overrides)
    return values


def _material(**candidate_overrides):
    candidate = {
        "side": "long",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "paper_cohort_preemptive_controls_scoped": True,
        "paper_cohort_breaker_new_entries_allowed": True,
    }
    candidate.update(candidate_overrides)
    return {
        "candidate": candidate,
        "bucket_assessment": {
            "bucket_negative": False,
            "bucket_evidence_missing": True,
            "matched_quarantined_bucket_keys": [],
            "recent_ATR_stop_risk": 0.0,
        },
        "cost_evidence": {"expected_edge_after_cost_bps": 120.0},
        "advanced_indicator_evidence": {
            "advanced_indicator_block": False,
            "advanced_indicator_shadow": True,
        },
        "control_flags": {
            "allow_positive_edge_probation": True,
            "allow_paper_risk_controller_exploration": True,
        },
        "continuous_edge_guardian_gate": {},
        "altdata_evidence": {},
    }


def test_reference_allows_scoped_exploration_before_global_fail_closed_ceiling() -> None:
    result = independent_reference(_values(), material=_material())

    assert result["decision"] == "PAPER_RISK_CONTROLLER_EXPLORATION"
    assert result["allowed"] is True
    assert result["paper_risk_controller_exploration_eligible"] is True


def test_reference_keeps_global_ceiling_binding_without_cohort_allow() -> None:
    result = independent_reference(
        _values(),
        material=_material(paper_cohort_breaker_new_entries_allowed=False),
    )

    assert result["decision"] == "NO_TRADE"
    assert result["allowed"] is False


def test_reference_keeps_true_unsafe_microstructure_blocked() -> None:
    result = independent_reference(
        _values(microstructure_action="SHADOW_ONLY", microstructure_score=0.20),
        material=_material(),
    )

    assert result["decision"] == "NO_TRADE"
    assert result["allowed"] is False
    assert result["predicates"]["microstructure"] is False
