"""Change 2 fixtures: deterministic bounded information-gain exploration
selection in the adaptive policy shadow.

When the champion (exploitation) action resolves to REMAIN_FLAT and a bounded
exploration action carries a strictly positive learned exploration objective
(``utility > 0`` AND ``information_gain_contribution > 0``), the shadow selects
the information-seeking directional action deterministically -- breaking the
data-starvation deadlock -- while reference parity is preserved.
"""

from __future__ import annotations

import copy
import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.adaptive_system import (
    adaptive_hard_validator_v2,
    adaptive_objective_v2,
    adaptive_policy_shadow_v2,
)
from v2.backend.app.services.adaptive_system.adaptive_paper_policy_authorization_v2 import (  # noqa: E501
    authorize_adaptive_paper_policy_action,
)
from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
    build_adaptive_policy_shadow_candidate,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    _beta_bernoulli_information_gain,
    _canonical_sha256,
)
from v2.backend.tests.unit.services.adaptive_system.test_adaptive_policy_shadow_v2 import (  # noqa: E501
    _SEED,
    _calibration,
    _feature_snapshot,
    _intent,
    _registry,
)

_PRIVATE = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"adaptive-shadow-runtime-test-validator").digest()
)
_PUBLIC_HEX = _PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
).hex()

BOUNDED = "bounded_information_seeking_exploration"


@pytest.fixture(autouse=True)
def _validator_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adaptive_objective_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _PUBLIC_HEX,
    )
    monkeypatch.setattr(
        adaptive_hard_validator_v2,
        "CANONICAL_HARD_VALIDATOR_PUBLIC_KEY_HEX",
        _PUBLIC_HEX,
    )


def _controlled_statistic(
    *, after_cost_expectancy_bps: float, posterior_uncertainty: float, tail_0_9: float
) -> dict:
    # The input is capped at the uninformative Beta(1,1) parameter standard
    # deviation; Bernoulli outcome dispersion is never used as epistemic
    # authority.  Lower values represent larger authenticated effective N.
    epistemic_standard_deviation = min(posterior_uncertainty, (1.0 / 12.0) ** 0.5)
    symmetric_alpha = max(
        1.0,
        (1.0 / (4.0 * epistemic_standard_deviation**2) - 1.0) / 2.0,
    )
    information = _beta_bernoulli_information_gain(
        symmetric_alpha, symmetric_alpha
    )
    return {
        "sample_count": 40,
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "win_rate_posterior_mean": 0.5,
        "posterior_uncertainty": epistemic_standard_deviation,
        "posterior_uncertainty_source": (
            "HIERARCHICAL_BETA_EFFECTIVE_N_NATURAL_EXECUTIONS"
        ),
        "expected_information_gain_nats": information[
            "expected_information_gain_nats"
        ],
        "prior_entropy": information["prior_entropy"],
        "expected_posterior_entropy": information[
            "expected_posterior_entropy"
        ],
        "effective_sample_size": 2.0 * symmetric_alpha - 2.0,
        "bucket_identity": "global",
        "parent_bucket_identity": None,
        "posterior_alpha": symmetric_alpha,
        "posterior_beta": symmetric_alpha,
        "loss_probability": 0.2,
        "stop_out_probability": 0.01,
        "profit_exit_probability": 0.3,
        "reversal_probability": 0.02,
        "slippage_failure_probability": 0.1,
        "missed_tp_then_stop_probability": 0.02,
        "venue_infeasible_probability": 0.1,
        "return_bps_quantiles": {"0.1": -2.0, "0.5": 0.0, "0.9": 2.0},
        "tail_loss_bps_quantiles": {"0.1": 0.0, "0.5": 0.0, "0.9": tail_0_9},
        "mfe_bps_quantiles": {"0.1": 1.0, "0.5": 2.0, "0.9": 3.0},
        "mae_bps_quantiles": {"0.1": -2.0, "0.5": -1.0, "0.9": 0.0},
        "transaction_cost_bps_quantiles": {"0.1": 1.0, "0.5": 1.0, "0.9": 1.0},
        "slippage_bps_quantiles": {"0.1": 0.1, "0.5": 0.1, "0.9": 0.1},
        "market_impact_bps_quantiles": {"0.1": 0.1, "0.5": 0.1, "0.9": 0.1},
        "realized_volatility_bps_quantiles": {"0.1": 1.0, "0.5": 2.0, "0.9": 3.0},
        "funding_bps_mean": 0.0,
    }


def _calibration_with_statistic(statistic: dict) -> dict:
    calibration = copy.deepcopy(_calibration())
    uncertainty = calibration["posterior_uncertainty_calibration"]
    uncertainty["epistemic_parameter_uncertainty"] = statistic[
        "posterior_uncertainty"
    ]
    for field in (
        "posterior_alpha",
        "posterior_beta",
        "prior_entropy",
        "expected_posterior_entropy",
        "expected_information_gain_nats",
        "effective_sample_size",
    ):
        uncertainty[field] = statistic[field]
    calibration["uncertainty_calibration_sha256"] = _canonical_sha256(
        uncertainty
    )
    calibration["global_statistics"] = copy.deepcopy(statistic)
    for key in list(calibration["side_timeframe_statistics"]):
        calibration["side_timeframe_statistics"][key] = copy.deepcopy(statistic)
    calibration["side_timeframe_statistics"]["LONG:15m"] = copy.deepcopy(statistic)
    calibration["side_timeframe_statistics"]["SHORT:15m"] = copy.deepcopy(statistic)
    hierarchy = calibration["profitability_posterior_hierarchy"]
    for level in hierarchy["levels"].values():
        for entry in level.values():
            entry["posterior_alpha"] = statistic["posterior_alpha"]
            entry["posterior_beta"] = statistic["posterior_beta"]
            entry["posterior_mean"] = 0.5
            entry["posterior_variance"] = statistic["posterior_uncertainty"] ** 2
            entry["posterior_standard_deviation"] = statistic[
                "posterior_uncertainty"
            ]
            entry["prior_entropy"] = statistic["prior_entropy"]
            entry["expected_posterior_entropy"] = statistic[
                "expected_posterior_entropy"
            ]
            entry["expected_information_gain_nats"] = statistic[
                "expected_information_gain_nats"
            ]
            entry["effective_sample_evidence"]["effective_sample_size"] = statistic[
                "effective_sample_size"
            ]
    hierarchy_material = {
        key: value
        for key, value in hierarchy.items()
        if key != "posterior_hierarchy_sha256"
    }
    hierarchy["posterior_hierarchy_sha256"] = _canonical_sha256(
        hierarchy_material
    )
    calibration["posterior_hierarchy_sha256"] = hierarchy[
        "posterior_hierarchy_sha256"
    ]
    weights = calibration["learned_objective_weights"]
    weights["information_gain_reward"] = 10.0
    weight_material = {
        key: value
        for key, value in weights.items()
        if key != "objective_parameter_fingerprint"
    }
    weights["objective_parameter_fingerprint"] = _canonical_sha256(weight_material)
    material = {k: v for k, v in calibration.items() if k != "calibration_sha256"}
    calibration["calibration_sha256"] = _canonical_sha256(material)
    return calibration


def _low_cost_intent() -> dict:
    intent = _intent()
    intent["microstructure_continuous_estimates"]["slippage_bps"] = 0.1
    intent["microstructure_continuous_estimates"]["market_impact_bps"] = 0.1
    intent["microstructure_continuous_estimates"]["fill_probability"] = 0.8
    intent["microstructure_continuous_estimates"]["adverse_selection_probability"] = 0.2
    return intent


def _build(calibration: dict):
    return build_adaptive_policy_shadow_candidate(
        intent=_low_cost_intent(),
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=calibration,
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )


def test_exploration_fires_when_champion_flat_and_objective_positive() -> None:
    """Fixture 1: champion=REMAIN_FLAT (edge<=0), positive learned exploration
    objective -> the bounded exploration directional action is selected and is
    an authorizable action."""

    # Slightly negative edge -> champion directional utility < flat (util 0) so
    # champion resolves to flat; high posterior uncertainty + tiny tail -> the
    # exploration objective (utility) is strictly positive.
    calibration = _calibration_with_statistic(
        _controlled_statistic(
            after_cost_expectancy_bps=-0.5,
            posterior_uncertainty=0.9,
            tail_0_9=1.0,
        )
    )
    result = _build(calibration)
    evaluation = result.objective_evaluation

    champion_score = next(
        score
        for score in evaluation.scores
        if score.action_id == evaluation.champion_action_id
    )
    assert champion_score.selected_action == "remain_flat"
    assert evaluation.exploration_action_id is not None
    exploration_score = next(
        score
        for score in evaluation.scores
        if score.action_id == evaluation.exploration_action_id
    )
    assert exploration_score.utility is not None and exploration_score.utility > 0.0
    assert exploration_score.information_gain_contribution > 0.0

    selected = result.selected_adaptive_action
    assert selected.selected_action == "directional_trade"
    assert selected.policy_mode == BOUNDED
    assert selected.target_notional_usd > 0.0
    # Live authority never granted at the shadow layer.
    assert selected.execution_authority is False
    assert result.routes_to_live is False
    assert result.places_real_order is False

    # The selected information-seeking action authorizes through the standard
    # adaptive paper authorization lane (no parallel path).  hard_validator_passed
    # requires the full hard-check inputs + venue DECISION_EXECUTABLE + physical
    # catastrophic plan to have passed for this exact action.
    authorization = authorize_adaptive_paper_policy_action(
        result, authorized_at_ms=5_000_000
    )
    payload = authorization.to_payload()
    assert payload["hard_validator_passed"] is True
    assert payload["selected_action"] == "directional_trade"
    assert payload["selected_objective_input_id"] == evaluation.exploration_action_id


def test_stays_flat_when_champion_flat_and_objective_nonpositive() -> None:
    """Fixture 3: champion=REMAIN_FLAT and NO positive-objective exploration
    action (utility <= 0 -> exploration_action_id is None) -> stays flat, no
    wasteful exploration."""

    result = _build(copy.deepcopy(_calibration()))  # default: exploration util < 0
    evaluation = result.objective_evaluation

    champion_score = next(
        score
        for score in evaluation.scores
        if score.action_id == evaluation.champion_action_id
    )
    assert champion_score.selected_action == "remain_flat"
    # A bounded exploration action exists in the scores but its utility is <= 0,
    # so it is not an eligible exploration action.
    assert evaluation.exploration_action_id is None
    assert any(
        score.policy_mode == BOUNDED
        and score.utility is not None
        and score.utility <= 0.0
        for score in evaluation.scores
    )
    assert result.selected_adaptive_action.selected_action == "remain_flat"
    assert result.selected_adaptive_action.target_notional_usd == 0.0


def test_reference_parity_maintained_when_information_seeking_fires() -> None:
    """Fixture 5: independent objective and final-selection parity both pass."""

    calibration = _calibration_with_statistic(
        _controlled_statistic(
            after_cost_expectancy_bps=-0.5,
            posterior_uncertainty=0.9,
            tail_0_9=1.0,
        )
    )
    result = _build(calibration)

    # build_adaptive_policy_shadow_candidate raises AdaptivePolicyShadowError on
    # any parity disagreement; reaching here proves parity held.
    assert result.parity_status == "PASS"
    assert result.parity_disagreement_count == 0
    # And the information-seeking action was indeed selected in this scenario.
    assert result.selected_adaptive_action.policy_mode == BOUNDED


def test_subminimum_policy_budget_never_rounds_up_to_venue_minimum() -> None:
    """A useful candidate stays flat when its own risk budget is sub-minimum."""

    intent = _low_cost_intent()
    derived = intent["paper_cycle_reservation_snapshot"]["derived"]
    derived["remaining_total_notional_usd"] = 4.0
    derived["remaining_symbol_notional_usd"] = 4.0
    calibration = _calibration_with_statistic(
        _controlled_statistic(
            after_cost_expectancy_bps=-0.5,
            posterior_uncertainty=0.9,
            tail_0_9=1.0,
        )
    )

    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=calibration,
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )

    assert result.selected_adaptive_action.selected_action == "remain_flat"
    assert result.selected_adaptive_action.target_notional_usd == 0.0
    assert len(result.venue_minimum_objective_comparisons) == 2
    assert all(
        comparison.venue_min_candidate_hard_risk_pass is False
        and comparison.venue_min_candidate_selected is False
        and comparison.selection_reason
        == "VENUE_MINIMUM_HARD_RISK_OR_INTEGRITY_REJECTED"
        for comparison in result.venue_minimum_objective_comparisons
    )
    directional_reasons = {
        reason
        for action_id, reasons in result.action_dispositions
        if not action_id.endswith(":flat")
        for reason in reasons
    }
    assert (
        "PHYSICAL_PLAN_UNAVAILABLE:continuous_policy_target_below_venue_minimum"
        in directional_reasons
    )


def test_separate_venue_minimum_candidate_recomputes_and_can_win() -> None:
    """A sub-minimum target remains unchanged while a second candidate wins."""

    intent = _low_cost_intent()
    intent["paper_exchange_filter_snapshot"]["min_notional"] = 100.0
    calibration = _calibration_with_statistic(
        _controlled_statistic(
            after_cost_expectancy_bps=-0.01,
            posterior_uncertainty=0.01,
            tail_0_9=0.01,
        )
    )
    weights = calibration["learned_objective_weights"]
    weights["information_gain_reward"] = 10_000.0
    weight_material = {
        key: value
        for key, value in weights.items()
        if key != "objective_parameter_fingerprint"
    }
    weights["objective_parameter_fingerprint"] = _canonical_sha256(weight_material)
    calibration_material = {
        key: value for key, value in calibration.items() if key != "calibration_sha256"
    }
    calibration["calibration_sha256"] = _canonical_sha256(calibration_material)

    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=calibration,
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )

    comparisons = result.venue_minimum_objective_comparisons
    assert len(comparisons) == 2
    selected = next(item for item in comparisons if item.venue_min_candidate_selected)
    assert selected.raw_target_notional_usd < selected.venue_filter_min_notional_usd
    assert selected.venue_min_notional_usd >= selected.venue_filter_min_notional_usd
    assert selected.venue_min_candidate_utility is not None
    assert selected.venue_min_candidate_utility > 0.0
    assert selected.venue_min_candidate_information_gain > 0.0
    assert selected.venue_min_candidate_expected_information_gain_nats > 0.0
    assert selected.posterior_expected_information_gain_nats > 0.0
    assert selected.posterior_alpha > 0.0
    assert selected.posterior_beta > 0.0
    assert selected.bucket_identity
    assert selected.venue_min_candidate_hard_risk_pass is True
    assert selected.production_reference_disagreement_count == 0
    assert selected.venue_min_candidate_expected_cost_usd > 0.0
    assert selected.venue_min_candidate_expected_loss_usd > 0.0
    assert selected.venue_min_candidate_margin_usd > 0.0
    assert selected.stop_loss_usd > 0.0
    assert selected.available_liquidity_capacity_usd == 100_000.0
    assert 0.0 < selected.liquidity_utilization < 1.0
    assert selected.sweep_risk == 0.2
    assert result.selected_adaptive_action.target_notional_usd == pytest.approx(
        selected.venue_min_notional_usd
    )
    assert result.selected_adaptive_action.expected_information_gain > 0.0
    assert result.selected_adaptive_action.expected_market_impact == pytest.approx(
        selected.expected_market_impact_bps
    )
    assert result.selected_adaptive_action.expected_fill_probability == pytest.approx(
        selected.expected_fill_probability
    )
    assert result.selected_adaptive_action.expected_adverse_selection == pytest.approx(
        selected.expected_adverse_selection_probability
    )
    assert result.selected_adaptive_action.policy_mode == BOUNDED


# --- Bootstrap information acquisition (paper-only) -------------------------
#
# While the global profitability posterior is prior-only (zero authenticated
# natural execution closes / zero effective independent N / untouched
# Beta(1, 1)), the paper loop may designate at most one venue-minimum
# information-acquisition experiment per cycle.  The shadow recognizes the
# designation only when every unchanged hard rail already passed; monetary
# utility is deliberately allowed to be nonpositive but expected information
# gain must be strictly positive.

BOOTSTRAP = "bootstrap_information_acquisition"

_PRIOR_ONLY_UNCERTAINTY = {
    "natural_execution_count": 0,
    "effective_sample_size": 0.0,
    "posterior_alpha": 1.0,
    "posterior_beta": 1.0,
}

# Fails every prior-only trigger arm: closes exist, effective N is positive,
# and the posterior has moved off Beta(1, 1).
_EVIDENCED_UNCERTAINTY = {
    "natural_execution_count": 7,
    "effective_sample_size": 6.5,
    "posterior_alpha": 4.0,
    "posterior_beta": 5.0,
}


def _calibration_with_uncertainty_block(
    calibration: dict, uncertainty: dict
) -> dict:
    """Overwrite the bootstrap-trigger fields and re-seal the calibration.

    Production reads the trigger from the fitted artifact's
    ``posterior_uncertainty_calibration`` block, so the fields are updated in
    place there and both nested and top-level seals are recomputed.
    """

    calibration = copy.deepcopy(calibration)
    block = calibration["posterior_uncertainty_calibration"]
    block.update(copy.deepcopy(uncertainty))
    calibration["uncertainty_calibration_sha256"] = _canonical_sha256(block)
    material = {k: v for k, v in calibration.items() if k != "calibration_sha256"}
    calibration["calibration_sha256"] = _canonical_sha256(material)
    return calibration


def _bootstrap_designation(**overrides: object) -> dict:
    designation: dict = {
        "schema_version": "bootstrap_information_acquisition_designation_v1",
        "paper_only": True,
        "side": "LONG",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
    }
    designation.update(overrides)
    return designation


def _sub_minimum_target_intent() -> dict:
    intent = _low_cost_intent()
    intent["paper_exchange_filter_snapshot"]["min_notional"] = 100.0
    return intent


def _negative_utility_venue_minimum_calibration(uncertainty: dict) -> dict:
    # Tiny posterior uncertainty -> tiny information gain, so with the fixture
    # default information_gain_reward (10.0, deliberately NOT doctored upward
    # the way test_separate_venue_minimum_candidate_recomputes_and_can_win
    # must) the venue-minimum recompute utility stays strictly negative and no
    # positive-objective exploration action exists.
    return _calibration_with_uncertainty_block(
        _calibration_with_statistic(
            _controlled_statistic(
                after_cost_expectancy_bps=-0.01,
                posterior_uncertainty=0.01,
                tail_0_9=0.01,
            )
        ),
        uncertainty,
    )


def _build_with_designation(
    intent: dict, calibration: dict, designation: dict | None
):
    paper_status: dict = {"paper_only": True, "open_position_count": 0}
    if designation is not None:
        paper_status["bootstrap_information_acquisition_designation"] = designation
    return build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status=paper_status,
        calibration=calibration,
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )


def test_bootstrap_designation_selects_negative_utility_venue_minimum() -> None:
    """Prior-only posterior + this cycle's designation -> the hard-valid
    venue-minimum information-acquisition action is selected even though its
    recomputed monetary utility is negative, parity holds, every paper-only
    safety flag stays intact, and the action authorizes through the standard
    adaptive paper lane as a bootstrap-mode action."""

    result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_PRIOR_ONLY_UNCERTAINTY),
        _bootstrap_designation(),
    )
    evaluation = result.objective_evaluation

    # Preconditions the bootstrap rule requires: flat champion baseline and no
    # positive-utility exploration action anywhere in the evaluation.
    champion_score = next(
        score
        for score in evaluation.scores
        if score.action_id == evaluation.champion_action_id
    )
    assert champion_score.selected_action == "remain_flat"
    assert evaluation.exploration_action_id is None

    selected = result.selected_adaptive_action
    assert selected.selected_action == "directional_trade"
    assert selected.policy_mode == BOOTSTRAP
    assert selected.expected_information_gain > 0.0
    assert selected.target_notional_usd > 0.0

    comparison = next(
        item
        for item in result.venue_minimum_objective_comparisons
        if item.venue_min_candidate_selected
    )
    assert comparison.side == "LONG"
    assert (
        comparison.selection_reason
        == "VENUE_MINIMUM_BOOTSTRAP_INFORMATION_ACQUISITION_SELECTED"
    )
    assert comparison.venue_min_candidate_hard_risk_pass is True
    assert comparison.venue_min_candidate_utility is not None
    assert comparison.venue_min_candidate_utility <= 0.0
    assert comparison.venue_min_candidate_expected_information_gain_nats > 0.0
    assert selected.target_notional_usd == pytest.approx(
        comparison.venue_min_notional_usd
    )

    # Independent reference replay agrees (the rule is mirrored, not shared).
    assert result.parity_status == "PASS"
    assert result.parity_disagreement_count == 0

    # No safety rail weakened: paper-only human-blocked on the result, the
    # comparison row, and the typed action; never any live/exchange authority.
    assert result.paper_only is True
    assert result.live_gate == "blocked_human_only"
    assert result.routes_to_live is False
    assert result.places_real_order is False
    assert result.exchange_action_taken is False
    assert comparison.paper_only is True
    assert comparison.routes_to_live is False
    assert comparison.places_real_order is False
    assert comparison.exchange_action_taken is False
    assert selected.paper_only is True
    assert selected.live_gate == "blocked_human_only"
    assert selected.routes_to_live is False
    assert selected.places_real_order is False
    assert selected.exchange_action_taken is False
    assert selected.execution_authority is False

    authorization = authorize_adaptive_paper_policy_action(
        result, authorized_at_ms=5_000_000
    )
    assert authorization.policy_mode == BOOTSTRAP
    assert authorization.paper_entry_authority is True
    assert authorization.mandatory_stop_present is True
    assert authorization.hard_validator_passed is True
    assert authorization.routes_to_live is False
    assert authorization.places_real_order is False
    assert authorization.exchange_action_taken is False


def test_bootstrap_designation_ignored_without_prior_only_posterior() -> None:
    """The same designation is inert once the posterior carries evidence
    (natural closes, positive effective N, non-Beta(1,1)): selection stays
    flat and the venue-minimum reason remains the nonpositive-utility
    rejection."""

    result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_EVIDENCED_UNCERTAINTY),
        _bootstrap_designation(),
    )

    assert result.selected_adaptive_action.selected_action == "remain_flat"
    assert result.selected_adaptive_action.target_notional_usd == 0.0
    assert result.selected_adaptive_action.policy_mode != BOOTSTRAP
    assert all(
        comparison.venue_min_candidate_selected is False
        and comparison.selection_reason
        == "VENUE_MINIMUM_RECOMPUTED_UTILITY_NONPOSITIVE"
        for comparison in result.venue_minimum_objective_comparisons
    )


def test_bootstrap_designation_ignored_for_other_symbol() -> None:
    """A designation targeting a different symbol never fires here: the
    candidate stays flat under the unchanged nonpositive-utility rule."""

    result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_PRIOR_ONLY_UNCERTAINTY),
        _bootstrap_designation(symbol="ETHUSDT"),
    )

    assert result.selected_adaptive_action.selected_action == "remain_flat"
    assert result.selected_adaptive_action.target_notional_usd == 0.0
    assert result.selected_adaptive_action.policy_mode != BOOTSTRAP
    assert all(
        comparison.venue_min_candidate_selected is False
        and comparison.selection_reason
        == "VENUE_MINIMUM_RECOMPUTED_UTILITY_NONPOSITIVE"
        for comparison in result.venue_minimum_objective_comparisons
    )


def test_bootstrap_designation_never_overrides_hard_invalid_candidate() -> None:
    """A prior-only designation cannot resurrect a hard-blocked candidate: the
    sub-minimum risk budget keeps every venue-minimum action hard-rejected and
    the selection stays flat -- no rail is weakened by bootstrap mode."""

    intent = _low_cost_intent()
    derived = intent["paper_cycle_reservation_snapshot"]["derived"]
    derived["remaining_total_notional_usd"] = 4.0
    derived["remaining_symbol_notional_usd"] = 4.0
    calibration = _calibration_with_uncertainty_block(
        _calibration_with_statistic(
            _controlled_statistic(
                after_cost_expectancy_bps=-0.5,
                posterior_uncertainty=0.9,
                tail_0_9=1.0,
            )
        ),
        _PRIOR_ONLY_UNCERTAINTY,
    )

    result = _build_with_designation(intent, calibration, _bootstrap_designation())

    assert result.selected_adaptive_action.selected_action == "remain_flat"
    assert result.selected_adaptive_action.target_notional_usd == 0.0
    assert result.selected_adaptive_action.policy_mode != BOOTSTRAP
    assert len(result.venue_minimum_objective_comparisons) == 2
    assert all(
        comparison.venue_min_candidate_hard_risk_pass is False
        and comparison.venue_min_candidate_selected is False
        and comparison.selection_reason
        == "VENUE_MINIMUM_HARD_RISK_OR_INTEGRITY_REJECTED"
        for comparison in result.venue_minimum_objective_comparisons
    )
    directional_reasons = {
        reason
        for action_id, reasons in result.action_dispositions
        if not action_id.endswith(":flat")
        for reason in reasons
    }
    assert (
        "PHYSICAL_PLAN_UNAVAILABLE:continuous_policy_target_below_venue_minimum"
        in directional_reasons
    )


def test_final_selection_reference_disagreement_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calibration = _calibration_with_statistic(
        _controlled_statistic(
            after_cost_expectancy_bps=-0.5,
            posterior_uncertainty=0.9,
            tail_0_9=1.0,
        )
    )
    monkeypatch.setattr(
        adaptive_policy_shadow_v2,
        "select_reference_action_id",
        lambda *_args, **_kwargs: "forged-reference-action",
    )

    with pytest.raises(
        adaptive_policy_shadow_v2.AdaptivePolicyShadowError,
        match="final_selection_disagreement_count=1",
    ):
        _build(calibration)
