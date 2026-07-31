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
import math
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, Decimal

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

@pytest.fixture
def legacy_paper_authority(monkeypatch):
    """Pin the pre-2026-07-31 authority contracts (override disabled)."""
    monkeypatch.setenv("PAPER_EXPLORATION_LEGACY_AUTHORITY_FOR_TESTS", "true")


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
    # This suite isolates the still-supported useful-information term.  Keep
    # the separately tested terminal-equity terms positive but immaterial so
    # the fixtures continue to exercise bounded exploration specifically.
    weights["expected_log_equity_growth_reward"] = 1e-6
    weights["terminal_target_probability_reward"] = 1e-6 * math.log(1000.0)
    weights["correlation_penalty"] = 1e-6
    weights["information_gain_reward"] = 10.0
    optimizer = calibration["objective_weight_optimizer"]
    optimizer["expected_log_equity_growth_reward_derivation"] = {
        "method": "RETURN_SCALE_DIVIDED_BY_MEAN_ABSOLUTE_REALIZED_LOG_RETURN",
        "source_parameters": {
            "return_scale_bps": 1e-6,
            "mean_absolute_realized_log_return": 1.0,
        },
        "derived_value": weights["expected_log_equity_growth_reward"],
    }
    optimizer["terminal_target_probability_reward_derivation"] = {
        "method": (
            "EXPECTED_LOG_EQUITY_GROWTH_REWARD_TIMES_LN_TARGET_MULTIPLE"
        ),
        "source_parameters": {
            "expected_log_equity_growth_reward": weights[
                "expected_log_equity_growth_reward"
            ],
            "terminal_target_multiple": 1000.0,
        },
        "derived_value": weights["terminal_target_probability_reward"],
    }
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


def test_stays_flat_when_champion_flat_and_objective_nonpositive(
    legacy_paper_authority,
) -> None:
    """Fixture 3 (legacy authority): champion=REMAIN_FLAT and NO
    positive-objective exploration action (utility <= 0 ->
    exploration_action_id is None) -> stays flat, no wasteful exploration."""

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


def test_paper_semantics_selects_nonpositive_utility_exploration() -> None:
    """Operator directive 2026-07-31 (paper semantics): utility/information-
    gain positivity is TRADING_POLICY ranking input, never an eligibility
    veto.  The hard-valid directional exploration input becomes
    ``exploration_action_id`` even with nonpositive learned utility, the
    deterministic information-seeking selection fires, and reference parity
    holds."""

    result = _build(copy.deepcopy(_calibration()))  # default: exploration util < 0
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
    assert exploration_score.utility is not None
    assert exploration_score.utility <= 0.0

    selected = result.selected_adaptive_action
    assert selected.selected_action == "directional_trade"
    assert selected.policy_mode == BOUNDED
    assert result.parity_status == "PASS"
    assert result.parity_disagreement_count == 0
    # No live rail weakened.
    assert result.paper_only is True
    assert result.live_gate == "blocked_human_only"
    assert result.routes_to_live is False
    assert result.places_real_order is False


def test_paper_semantics_bootstrap_designation_precedes_positive_utility_exploration() -> None:  # noqa: E501
    """A designation keeps its BOOTSTRAP selection authority even when a
    positive-utility exploration action exists (the legacy exploration-absence
    precondition is TRADING_POLICY and carries no authority under paper
    semantics), and the independent reference replay agrees."""

    calibration = _calibration_with_statistic(
        _controlled_statistic(
            after_cost_expectancy_bps=-0.5,
            posterior_uncertainty=0.9,
            tail_0_9=1.0,
        )
    )
    result = _build_with_designation(
        _sub_minimum_target_intent(),
        calibration,
        _bootstrap_designation(),
    )
    evaluation = result.objective_evaluation

    assert evaluation.exploration_action_id is not None
    exploration_score = next(
        score
        for score in evaluation.scores
        if score.action_id == evaluation.exploration_action_id
    )
    assert exploration_score.utility is not None
    assert exploration_score.utility > 0.0

    assert result.selected_adaptive_action.policy_mode == BOOTSTRAP
    assert result.selected_adaptive_action.selected_action == "directional_trade"
    assert result.parity_status == "PASS"
    assert result.parity_disagreement_count == 0


def test_bootstrap_selection_preconditions_are_policy_only(monkeypatch) -> None:
    """A2 unit contract: under paper semantics the selection helper ignores
    both legacy preconditions (exploration present, non-flat champion); under
    the pinned legacy authority it refuses exactly as before."""

    from types import SimpleNamespace

    from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
        _bootstrap_information_acquisition_selection,
    )

    match = SimpleNamespace(
        policy_mode=BOUNDED,
        selected_action="directional_trade",
        action_id=f"cdo2_unit:{BOUNDED}:long",
        hard_constraints_satisfied=True,
        expected_information_gain=0.5,
    )
    evaluation = SimpleNamespace(
        exploration_action_id=f"cdo2_unit:{BOUNDED}:short",
        champion_action_id="cdo2_unit:champion_exploitation:directional",
        scores=(),
    )
    designation = {"side": "LONG"}

    assert (
        _bootstrap_information_acquisition_selection(
            designation=designation,
            evaluation=evaluation,
            ordered_inputs=(match,),
        )
        == match.action_id
    )

    monkeypatch.setenv("PAPER_EXPLORATION_LEGACY_AUTHORITY_FOR_TESTS", "true")
    assert (
        _bootstrap_information_acquisition_selection(
            designation=designation,
            evaluation=evaluation,
            ordered_inputs=(match,),
        )
        is None
    )


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


def test_bootstrap_designation_selects_negative_utility_venue_minimum(
    legacy_paper_authority,
) -> None:
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


def test_bootstrap_designation_selects_with_evidenced_posterior() -> None:
    """Continuous paper learning: posterior evidence carries no authorization
    authority.  The same designation still selects the hard-valid
    venue-minimum experiment when the posterior already has authenticated
    evidence (natural closes, positive effective N, non-Beta(1,1)); the
    learned allocation, not a posterior gate, governs exploration."""

    result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_EVIDENCED_UNCERTAINTY),
        _bootstrap_designation(),
    )

    assert result.selected_adaptive_action.policy_mode == BOOTSTRAP
    assert result.selected_adaptive_action.selected_action == "directional_trade"
    assert any(
        comparison.venue_min_candidate_selected is True
        and comparison.selection_reason
        == "VENUE_MINIMUM_BOOTSTRAP_INFORMATION_ACQUISITION_SELECTED"
        for comparison in result.venue_minimum_objective_comparisons
    )


def test_bootstrap_designation_ignored_for_other_symbol(
    legacy_paper_authority,
) -> None:
    """A designation targeting a different symbol never fires here: under
    legacy authority the candidate stays flat under the nonpositive-utility
    rule."""

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


def test_evidenced_posterior_bootstrap_authorizes_through_paper_lane() -> None:
    """Evidence arrival must not flip exploration off at the LAST gate: the
    evidenced-posterior bootstrap selection authorizes through the standard
    adaptive paper lane exactly like the prior-only baseline — the ONLY
    variable versus the prior-only assertions is posterior evidence.
    """

    result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_EVIDENCED_UNCERTAINTY),
        _bootstrap_designation(),
    )
    assert result.parity_status == "PASS"
    assert result.parity_disagreement_count == 0

    authorization = authorize_adaptive_paper_policy_action(
        result, authorized_at_ms=5_000_000
    )
    assert authorization.policy_mode == BOOTSTRAP
    assert authorization.paper_entry_authority is True
    assert authorization.hard_validator_passed is True
    assert authorization.mandatory_stop_present is True
    assert authorization.routes_to_live is False
    assert authorization.places_real_order is False
    assert authorization.exchange_action_taken is False


def test_paper_loop_evidenced_designation_recognized_selected_and_authorized() -> None:
    """Cross-boundary payload binding: the REAL designation produced by the
    paper loop under an evidenced posterior AND a same-epoch closed bootstrap
    outcome (bootstrap_trigger.prior_only_posterior=False) is recognized by
    the shadow, selects the venue-minimum bootstrap action, and authorizes —
    so no gate anywhere converts evidence arrival into exploration shutdown.
    """

    from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
    from v2.backend.tests.unit.cli.test_v2_trade_management_paper_loop import (
        _bootstrap_designation_calibration,
        _bootstrap_designation_comparison,
        _bootstrap_designation_intent,
    )

    designation = paper_loop._paper_bootstrap_information_acquisition_designation(  # noqa: SLF001
        calibration=_bootstrap_designation_calibration(
            natural_execution_count=7,
            effective_sample_size=6.5,
            posterior_alpha=4.0,
            posterior_beta=5.0,
        ),
        previous_cycle_intents=[
            _bootstrap_designation_intent(
                "BTCUSDT",
                [_bootstrap_designation_comparison()],
                timeframe="15m",
            )
        ],
        current_epoch_closed_trade_rows=[
            {
                "adaptive_policy_action_policy_mode": (
                    "bootstrap_information_acquisition"
                )
            }
        ],
        current_epoch_open_position_rows=[],
    )
    assert designation is not None
    # The payload really encodes evidenced (non-prior-only) posterior state.
    assert designation["bootstrap_trigger"]["prior_only_posterior"] is False
    assert designation["current_epoch_bootstrap_closed_trades"] == 1

    result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_EVIDENCED_UNCERTAINTY),
        dict(designation),
    )

    assert result.selected_adaptive_action.policy_mode == BOOTSTRAP
    assert result.selected_adaptive_action.selected_action == "directional_trade"
    assert any(
        comparison.venue_min_candidate_selected is True
        and comparison.selection_reason
        == "VENUE_MINIMUM_BOOTSTRAP_INFORMATION_ACQUISITION_SELECTED"
        for comparison in result.venue_minimum_objective_comparisons
    )
    assert result.parity_status == "PASS"

    authorization = authorize_adaptive_paper_policy_action(
        result, authorized_at_ms=5_000_000
    )
    assert authorization.policy_mode == BOOTSTRAP
    assert authorization.paper_entry_authority is True
    assert authorization.routes_to_live is False
    assert authorization.places_real_order is False
    assert authorization.exchange_action_taken is False


def test_bootstrap_ranked_lower_rank_member_executes() -> None:
    """Same-cycle fallback, shadow side: ANY ranked designation member — not
    just rank 1 — may execute at its own turn.  A designation headed by a
    foreign candidate still fires for the rank-2 member's intent, while a
    ranked list without this candidate stays flat (no scope widening).
    """

    lower_rank_designation = _bootstrap_designation(
        symbol="ETHUSDT",
        timeframe="4h",
        side="SHORT",
        ranked_candidates=[
            {"symbol": "ETHUSDT", "timeframe": "4h", "side": "SHORT", "rank": 1},
            {"symbol": "BTCUSDT", "timeframe": "15m", "side": "LONG", "rank": 2},
        ],
    )
    result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_PRIOR_ONLY_UNCERTAINTY),
        lower_rank_designation,
    )
    assert result.selected_adaptive_action.policy_mode == BOOTSTRAP
    assert result.selected_adaptive_action.selected_action == "directional_trade"
    assert any(
        comparison.venue_min_candidate_selected is True
        and comparison.selection_reason
        == "VENUE_MINIMUM_BOOTSTRAP_INFORMATION_ACQUISITION_SELECTED"
        for comparison in result.venue_minimum_objective_comparisons
    )

    foreign_only_designation = _bootstrap_designation(
        symbol="ETHUSDT",
        timeframe="4h",
        side="SHORT",
        ranked_candidates=[
            {"symbol": "ETHUSDT", "timeframe": "4h", "side": "SHORT", "rank": 1},
        ],
    )
    foreign_result = _build_with_designation(
        _sub_minimum_target_intent(),
        _negative_utility_venue_minimum_calibration(_PRIOR_ONLY_UNCERTAINTY),
        foreign_only_designation,
    )
    # No scope widening: a ranked list without this candidate never fires the
    # BOOTSTRAP lane.  Under paper exploration semantics the candidate may
    # still explore as a plain BOUNDED action, so the contract is the mode,
    # not flatness.
    assert foreign_result.selected_adaptive_action.policy_mode != BOOTSTRAP
    assert not any(
        comparison.selection_reason
        == "VENUE_MINIMUM_BOOTSTRAP_INFORMATION_ACQUISITION_SELECTED"
        for comparison in foreign_result.venue_minimum_objective_comparisons
    )


def test_venue_minimum_recompute_is_exact_smallest_executable_lot_and_authorizes() -> None:
    """P6 exactness + bounded-winner authorization: the venue-minimum
    recompute is the EXACT smallest executable lot
    max(min_qty, ceil(min_notional/entry/step)*step) — never inflated — and
    the winning bounded (non-bootstrap) venue-minimum action authorizes
    through the generic exploration-slot lane at that exact size.
    """

    intent = _low_cost_intent()
    # 100.0 does not divide evenly by step*entry (0.001 * 97.0), so ceiling
    # quantization is genuinely exercised.
    intent["entry_price"] = 97.0
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

    selected = next(
        item
        for item in result.venue_minimum_objective_comparisons
        if item.venue_min_candidate_selected
    )
    step = Decimal("0.001")
    entry = Decimal("97.0")
    expected_qty = max(
        Decimal("0.001"),
        (Decimal("100.0") / entry / step).to_integral_value(rounding=ROUND_CEILING)
        * step,
    )
    assert expected_qty == Decimal("1.031")
    expected_notional = float(expected_qty * entry)  # 100.007

    # (a) EXACT smallest executable lot at the venue minimum.
    assert selected.venue_min_notional_usd == pytest.approx(expected_notional)
    # (b) Within one step of the venue floor — rejects ANY inflation
    # (2x-minimum, wrong step quantization, rounding the learned target up).
    assert (
        selected.venue_min_notional_usd - selected.venue_filter_min_notional_usd
        < float(step * entry)
    )
    assert selected.raw_target_notional_usd < selected.venue_filter_min_notional_usd

    # (c) The selected action carries the exact recomputed size.
    assert result.selected_adaptive_action.policy_mode == BOUNDED
    assert result.selected_adaptive_action.target_notional_usd == pytest.approx(
        expected_notional
    )

    # (d) Generic exploration-slot authorization at the exact size — the
    # bounded venue-minimum winner is authorized, not silently dropped.
    authorization = authorize_adaptive_paper_policy_action(
        result, authorized_at_ms=5_000_000
    )
    payload = authorization.to_payload()
    assert authorization.paper_entry_authority is True
    assert authorization.policy_mode == BOUNDED
    assert payload["hard_validator_passed"] is True
    assert payload["selected_objective_input_id"].endswith(":venue_minimum")
    assert float(payload["exact_target_notional_usd"]) == pytest.approx(
        expected_notional
    )
    assert authorization.mandatory_stop_present is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def _shift_iso_ms(iso: str, delta_ms: int) -> str:
    parsed = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc
    )
    shifted = parsed + timedelta(milliseconds=delta_ms)
    return (
        shifted.strftime("%Y-%m-%dT%H:%M:%S.") + f"{shifted.microsecond // 1000:03d}Z"
    )


def test_aged_calibration_fit_pending_refit_still_authorizes_bootstrap() -> None:
    """Continuous paper trading: a calibration artifact whose fit is 14 DAYS
    old (refit long overdue) still evaluates and authorizes the next bounded
    paper experiment.  Every non-calibration timestamp is shifted by the same
    delta so all relative ages match the passing baseline and ONLY the fit
    age grows — the test fails the moment any fit-age/staleness ceiling is
    introduced anywhere in the evaluate-and-authorize chain.
    """

    delta_ms = 14 * 24 * 3_600_000
    aged_decision_ms = 4_000_000 + delta_ms

    intent = _sub_minimum_target_intent()
    intent["cost_source_timestamp"] = _shift_iso_ms(
        intent["cost_source_timestamp"], delta_ms
    )
    prediction = intent["entry_prediction_snapshot"]
    prediction["feature_cutoff"] = _shift_iso_ms(
        prediction["feature_cutoff"], delta_ms
    )
    prediction["available_at"] = _shift_iso_ms(prediction["available_at"], delta_ms)
    intent["entry_feature_latest_closed_kline_close_time_ms"] += delta_ms

    snapshot = _feature_snapshot()
    snapshot["feature_cutoff"] = prediction["feature_cutoff"]
    snapshot["available_at"] = prediction["available_at"]
    snapshot["latest_unclosed_exclusion_decision_time_ms"] += delta_ms
    snapshot["latest_closed_kline_close_time_ms"] += delta_ms

    calibration = _negative_utility_venue_minimum_calibration(
        _PRIOR_ONLY_UNCERTAINTY
    )
    # Precondition pin: fixture drift cannot hollow out the scenario — the
    # fit really is at least 14 days older than the decision instant.
    fit_available_at_ms = int(calibration["fit_record_available_at_ms"])
    assert aged_decision_ms - fit_available_at_ms >= delta_ms

    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=snapshot,
        paper_status={
            "paper_only": True,
            "open_position_count": 0,
            "bootstrap_information_acquisition_designation": (
                _bootstrap_designation()
            ),
        },
        calibration=calibration,
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=aged_decision_ms,
    )

    assert result.parity_status == "PASS"
    assert result.selected_adaptive_action.policy_mode == BOOTSTRAP
    assert result.selected_adaptive_action.selected_action == "directional_trade"

    authorization = authorize_adaptive_paper_policy_action(
        result, authorized_at_ms=aged_decision_ms + 1
    )
    assert authorization.paper_entry_authority is True
    assert authorization.policy_mode == BOOTSTRAP
    assert authorization.routes_to_live is False
    assert authorization.places_real_order is False


def test_queue_head_failure_predicate_from_real_shadow_evaluations() -> None:
    """The paper loop's queue-head failure predicate — which runs inline in
    the cycle accept path to drive the same-cycle rank fallback — classifies
    REAL AdaptivePolicyShadowResult objects without raising, so shadow-result
    shape drift fails here instead of crashing a live paper cycle.
    """

    from v2.backend.app.cli.v2_trade_management_paper_loop import (
        _paper_bootstrap_queue_head_failure_predicate,
    )

    # (a) Hard-invalid head: sub-minimum risk budget rejects every
    # venue-minimum action; the predicate surfaces the first hard reason.
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
    hard_invalid_result = _build_with_designation(
        intent, calibration, _bootstrap_designation()
    )
    predicate = _paper_bootstrap_queue_head_failure_predicate(
        hard_invalid_result, "LONG"
    )
    assert predicate.startswith("EXPLORATION_INPUT_HARD_INVALID:")
    assert "continuous_policy_target_below_venue_minimum" in predicate

    # (b) A positive-utility exploration action exists: bootstrap yields.
    positive_result = _build(
        _calibration_with_statistic(
            _controlled_statistic(
                after_cost_expectancy_bps=-0.5,
                posterior_uncertainty=0.9,
                tail_0_9=1.0,
            )
        )
    )
    assert (
        _paper_bootstrap_queue_head_failure_predicate(positive_result, "LONG")
        == "POSITIVE_UTILITY_EXPLORATION_EXISTS"
    )

    # (c) A side that maps to no lineage input is classified fail-safe, not a
    # crash.
    assert (
        _paper_bootstrap_queue_head_failure_predicate(positive_result, None)
        == "NO_EXPLORATION_INPUT_FOR_LINEAGE_SIDE"
    )
