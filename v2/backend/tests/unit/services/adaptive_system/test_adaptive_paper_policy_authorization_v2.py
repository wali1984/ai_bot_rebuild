from __future__ import annotations

from dataclasses import fields, replace

import pytest

from v2.backend.app.domain.adaptive_policy_action_v2 import AdaptivePolicyActionV2
from v2.backend.app.services.adaptive_system import adaptive_hard_validator_v2
from v2.backend.app.services.adaptive_system import adaptive_objective_v2
from v2.backend.app.services.adaptive_system.adaptive_paper_policy_authorization_v2 import (
    AdaptivePaperPolicyAuthorizationError,
    AdaptivePaperPolicyAuthorizationV2,
    authorize_adaptive_paper_policy_action,
)
from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
    build_adaptive_policy_shadow_candidate,
)
from v2.backend.tests.unit.services.adaptive_system.test_adaptive_policy_shadow_v2 import (
    _PUBLIC_HEX,
    _SEED,
    _calibration,
    _feature_snapshot,
    _intent,
    _registry,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_calibration_v2 import (
    _observation,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    fit_candidate_outcome_calibration_v2,
)


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


def _result(*, directional: bool):
    calibration = (
        fit_candidate_outcome_calibration_v2(
            [
                replace(
                    _observation(index),
                    decision_disposition="REJECTED",
                    final_gross_return_bps=52.0,
                    final_after_cost_return_bps=50.0,
                    max_favorable_excursion_bps=80.0,
                    max_adverse_excursion_bps=-5.0,
                    transaction_cost_bps=2.0,
                    profitable=True,
                    loss=False,
                    stop_hit=False,
                    profit_target_hit=True,
                    short_horizon_reversal=False,
                    slippage_failure=False,
                    missed_tp_then_stop=False,
                    infeasible=False,
                )
                for index in range(100)
            ],
            generated_at_ms=3_000_000,
            source_archive_chain_sha256="c" * 64,
        )
        if directional
        else _calibration()
    )
    for index in range(128):
        intent = _intent()
        intent["policy_id"] = f"production-policy-{index}"
        result = build_adaptive_policy_shadow_candidate(
            intent=intent,
            feature_snapshot=_feature_snapshot(),
            paper_status={"paper_only": True, "open_position_count": 0},
            calibration=calibration,
            registry=_registry(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
        )
        if (result.selected_adaptive_action.selected_action == "directional_trade") is directional:
            return result
    raise AssertionError("deterministic fixture did not produce requested action")


def _recreate_action(action: AdaptivePolicyActionV2, **changes: object) -> AdaptivePolicyActionV2:
    values = {
        item.name: getattr(action, item.name)
        for item in fields(action)
        if item.name != "decision_id"
    }
    values.update(changes)
    return AdaptivePolicyActionV2.create(**values)


def test_authorizes_exact_directional_action_without_static_or_live_authority() -> None:
    result = _result(directional=True)
    authorization = authorize_adaptive_paper_policy_action(
        result,
        authorized_at_ms=4_000_001,
    )

    assert isinstance(authorization, AdaptivePaperPolicyAuthorizationV2)
    assert authorization.authorization_id == authorization.expected_authorization_id
    assert authorization.policy_trading_action_authority is True
    assert authorization.paper_entry_authority is True
    assert authorization.hard_validator_passed is True
    assert authorization.exact_action_venue_executable is True
    assert authorization.mandatory_stop_present is True
    assert authorization.exact_target_notional_usd > 0
    assert authorization.exact_target_quantity > 0
    assert authorization.exact_margin_allocation_usd == (
        authorization.exact_target_notional_usd / authorization.exact_leverage
    )
    assert authorization.exact_round_trip_cost_bps > 0
    assert authorization.static_confidence_final_authority is False
    assert authorization.static_loss_final_authority is False
    assert authorization.static_microstructure_final_authority is False
    assert authorization.static_exit_feasibility_final_authority is False
    assert authorization.static_exploration_tier_final_authority is False
    assert authorization.routes_to_live is False
    assert authorization.places_real_order is False
    assert authorization.exchange_action_taken is False


def test_flat_is_authoritative_learning_action_without_entry_authority() -> None:
    result = _result(directional=False)
    authorization = authorize_adaptive_paper_policy_action(
        result,
        authorized_at_ms=4_000_001,
    )

    assert authorization.policy_trading_action_authority is True
    assert authorization.paper_entry_authority is False
    assert authorization.selected_action == "remain_flat"
    assert authorization.exact_target_notional_usd == 0
    assert authorization.exact_round_trip_cost_bps == 0
    assert authorization.venue_attestation_id is None
    assert authorization.mandatory_stop_present is False


def test_changed_policy_action_cannot_reuse_exact_venue_attestation() -> None:
    result = _result(directional=True)
    action = result.selected_adaptive_action
    changed_notional = action.target_notional_usd + 1.0
    changed_action = _recreate_action(
        action,
        target_notional_usd=changed_notional,
        target_exposure_usd=(
            changed_notional if action.primary_side == "long" else -changed_notional
        ),
        margin_allocation_usd=changed_notional / action.leverage,
    )

    with pytest.raises(AdaptivePaperPolicyAuthorizationError, match="selected_action_changed"):
        authorize_adaptive_paper_policy_action(
            replace(result, selected_adaptive_action=changed_action),
            authorized_at_ms=4_000_001,
        )


def test_selection_receipt_cannot_be_rebound_to_another_evaluation() -> None:
    result = _result(directional=True)
    changed_action = _recreate_action(
        result.selected_adaptive_action,
        selection_receipt_sha256="f" * 64,
    )

    with pytest.raises(AdaptivePaperPolicyAuthorizationError, match="selection_receipt_mismatch"):
        authorize_adaptive_paper_policy_action(
            replace(result, selected_adaptive_action=changed_action),
            authorized_at_ms=4_000_001,
        )


def test_missing_selected_venue_attestation_fails_closed() -> None:
    result = _result(directional=True)
    selected = result.selected_adaptive_action
    selected_input_id = (
        result.objective_evaluation.exploration_action_id
        if selected.policy_mode == "bounded_information_seeking_exploration"
        else result.objective_evaluation.champion_action_id
    )
    selected_input = next(
        item for item in result.objective_inputs if item.action_id == selected_input_id
    )
    retained = tuple(
        item
        for item in result.venue_attestations
        if item.request.policy_action_sha256 != selected_input.action_sha256
    )

    with pytest.raises(
        AdaptivePaperPolicyAuthorizationError,
        match="exact_selected_venue_attestation_required",
    ):
        authorize_adaptive_paper_policy_action(
            replace(result, venue_attestations=retained),
            authorized_at_ms=4_000_001,
        )


def test_reference_disagreement_never_receives_authority() -> None:
    result = _result(directional=True)
    object.__setattr__(result, "parity_disagreement_count", 1)
    try:
        with pytest.raises(
            AdaptivePaperPolicyAuthorizationError,
            match="independent_reference_parity_required",
        ):
            authorize_adaptive_paper_policy_action(
                result,
                authorized_at_ms=4_000_001,
            )
    finally:
        object.__setattr__(result, "parity_disagreement_count", 0)


def test_authorization_record_rejects_static_authority_reintroduction() -> None:
    authorization = authorize_adaptive_paper_policy_action(
        _result(directional=True),
        authorized_at_ms=4_000_001,
    )

    with pytest.raises(AdaptivePaperPolicyAuthorizationError, match="must_be_false"):
        replace(authorization, static_loss_final_authority=True)
