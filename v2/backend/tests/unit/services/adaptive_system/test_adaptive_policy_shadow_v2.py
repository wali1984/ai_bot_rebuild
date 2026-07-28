from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.adaptive_system import adaptive_hard_validator_v2
from v2.backend.app.services.adaptive_system import adaptive_objective_v2
from v2.backend.app.services.adaptive_system import adaptive_policy_shadow_v2 as policy_shadow
from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
    AdaptivePolicyShadowError,
    _continuous_performance_risk_multiplier,
    build_adaptive_policy_shadow_candidate,
)
from v2.backend.app.services.adaptive_system.candidate_outcome_calibration_v2 import (
    fit_candidate_outcome_calibration_v2,
)
from v2.backend.tests.unit.services.adaptive_system.test_candidate_outcome_calibration_v2 import (
    _observation,
)

_PRIVATE = Ed25519PrivateKey.from_private_bytes(
    hashlib.sha256(b"adaptive-shadow-runtime-test-validator").digest()
)
_SEED = _PRIVATE.private_bytes(
    serialization.Encoding.Raw,
    serialization.PrivateFormat.Raw,
    serialization.NoEncryption(),
)
_PUBLIC_HEX = _PRIVATE.public_key().public_bytes(
    serialization.Encoding.Raw,
    serialization.PublicFormat.Raw,
).hex()


def _sha(character: str) -> str:
    return character * 64


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


def _calibration() -> dict:
    return fit_candidate_outcome_calibration_v2(
        [_observation(index) for index in range(100)],
        generated_at_ms=3_000_000,
        source_archive_chain_sha256=_sha("c"),
    )


def _registry() -> dict:
    return {
        "schema_version": "model_registry_active_v2",
        "registry_generation": 3,
        "checkpoint_id": "checkpoint-3",
        "checkpoint_bundle_sha256": _sha("a"),
        "checkpoint_bundle": {
            "feature_abi_sha256": _sha("7"),
            "serving_feature_builder_sha": _sha("6"),
        },
        "paper_only": True,
        "live_eligible": False,
    }


def _feature_snapshot() -> dict:
    return {
        "feature_snapshot_id": "feature-snapshot-1",
        "feature_cutoff": "1970-01-01T00:16:40.000Z",
        "available_at": "1970-01-01T00:18:20.000Z",
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1",
        "latest_unclosed_exclusion_decision_time_ms": 1_100_000,
        "latest_closed_kline_close_time_ms": 999_999,
        "trainer_consumable": True,
        "content_sha256": _sha("5"),
    }


def test_performance_breaker_state_is_continuous_objective_input_not_veto() -> None:
    neutral = _continuous_performance_risk_multiplier({})
    adverse = _continuous_performance_risk_multiplier(
        {
            "performance_risk_state": {
                "current_drawdown_fraction": 0.008,
                "profit_factor": 0.703666,
                "expectancy_bps": -7.70099,
                "hard_trading_authority": False,
            }
        }
    )

    assert neutral == 1.0
    assert adverse == pytest.approx(1.305104099)
    assert adverse > neutral


def _intent() -> dict:
    reservation_hash = _sha("3")
    return {
        "prediction_id": "prediction-1",
        "preemptive_decision_id": "preemptive-1",
        "preemptive_decision": "NO_TRADE",
        "preemptive_decision_reasons": ["STATIC_COMPARATOR_ONLY"],
        "policy_id": "production-policy-1",
        "policy_fingerprint": _sha("4"),
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "side": "long",
        "entry_price": 100.0,
        "fee_bps": 1.0,
        "observed_spread_bps": 1.0,
        "expected_slippage_bps": 1.0,
        "expected_funding_bps": 0.0,
        "depth_derived_price_impact_bps": 1.0,
        "cost_source_timestamp": "1970-01-01T00:18:20.000Z",
        "runtime_cost_capture_status": "PRODUCTION_GRADE_COST_CAPTURE",
        "runtime_cost_capture_source": "V2_PAPER_RUNTIME_DECISION_TIME_COST_CAPTURE",
        "runtime_cost_capture_missing_fields": [],
        "runtime_cost_capture_unexplained_missing_fields": [],
        "runtime_cost_capture_temporal_reject_reasons": [],
        "production_grade_cost_flag": True,
        "fallback_cost_flag": False,
        "feed_integrity_pass": True,
        "microstructure_action": "SHADOW_ONLY",
        "microstructure_continuous_estimates_complete": True,
        "microstructure_continuous_estimates_status": (
            "PASS_CALIBRATED_CONTINUOUS_ESTIMATES"
        ),
        "microstructure_continuous_estimates": {
            "schema_version": "microstructure_continuous_estimates_v1",
            "status": "PASS_CALIBRATED_CONTINUOUS_ESTIMATES",
            "complete": True,
            "fill_probability": 0.37,
            "slippage_bps": 7.0,
            "market_impact_bps": 9.0,
            "adverse_selection_probability": 0.61,
        },
        "paper_fill_allowed": False,
        "allocator_decision": "BLOCK_STATIC_CATEGORY_E",
        "paper_fill_block_reason": "STATIC_COMPARATOR_ONLY",
        "paper_exchange_filter_snapshot_hash": _sha("1"),
        "paper_cycle_base_resource_evidence_hash": _sha("2"),
        "paper_cycle_reservation_snapshot_hash": reservation_hash,
        "paper_dynamic_envelope_reservation_evidence_hash": _sha("8"),
        "paper_exchange_filter_snapshot": {
            "status": "READY",
            "rejection_reasons": [],
            "tick_size": 0.01,
            "step_size": 0.001,
            "min_qty": 0.001,
            "max_qty": 1000.0,
            "min_notional": 5.0,
        },
        "paper_cycle_base_resource_evidence": {
            "available_margin_usd": 1000.0,
        },
        "paper_cycle_reservation_snapshot": {
            "status": "PASS",
            "rejection_reasons": [],
            "cycle_identity": "cycle-1",
            "snapshot_hash": reservation_hash,
            "derived": {
                "remaining_total_notional_usd": 500.0,
                "remaining_symbol_notional_usd": 200.0,
                "remaining_margin_after_buffer_usd": 800.0,
                "remaining_projected_stress_loss_usd": 50.0,
                "remaining_per_candidate_risk_budget_usd": 20.0,
                "prior_reserved_margin_usd": 0.0,
            },
        },
        "paper_allocator_economic_contract": {
            "material": {
                "model_inputs": {
                    "max_qty": 1000.0,
                    "risk_envelope": {"max_effective_leverage": 1.0},
                }
            }
        },
        "entry_prediction_snapshot": {
            "prediction_id": "prediction-1",
            "feature_snapshot_id": "feature-snapshot-1",
            "mtf_snapshot_id": "market-state-1",
            "feature_cutoff": "1970-01-01T00:16:40.000Z",
            "available_at": "1970-01-01T00:18:20.000Z",
            "source_hashes": {"feature_vector_hash": _sha("9")},
        },
        "market_state_id": "market-state-1",
        "entry_feature_latest_unclosed_kline_excluded": True,
        "entry_feature_latest_unclosed_exclusion_method": (
            "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1"
        ),
        "entry_feature_latest_closed_kline_close_time_ms": 999_999,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def test_builds_complete_shadow_chain_with_zero_reference_disagreements() -> None:
    result = build_adaptive_policy_shadow_candidate(
        intent=_intent(),
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=_calibration(),
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )

    assert len(result.component_estimates) == 4
    assert len(result.objective_inputs) == 5
    assert len(result.venue_attestations) == 4
    assert result.parity_disagreement_count == 0
    assert result.parity_status == "PASS"
    assert result.selected_adaptive_action.execution_authority is False
    assert result.production_decision[
        "static_category_e_authority_consumed_by_adaptive_shadow"
    ] is False
    short_stats = _calibration()["side_timeframe_statistics"]["SHORT:15m"]
    short_input = next(
        item
        for item in result.objective_inputs
        if item.action_id.endswith(":champion_exploitation:short")
    )
    assert short_input.expected_tail_loss_bps == pytest.approx(
        short_stats["tail_loss_bps_quantiles"]["0.9"]
        * short_stats["loss_probability"]
    )
    assert short_input.expected_drawdown_contribution_bps == pytest.approx(
        abs(short_stats["mae_bps_quantiles"]["0.5"])
        * short_stats["loss_probability"]
    )
    assert result.routes_to_live is False
    assert result.places_real_order is False
    assert result.exchange_action_taken is False


def test_feed_integrity_false_blocks_every_typed_disposition_including_flat() -> None:
    intent = _intent()
    intent["feed_integrity_pass"] = False

    with pytest.raises(AdaptivePolicyShadowError, match="no_hard_valid_selection"):
        build_adaptive_policy_shadow_candidate(
            intent=intent,
            feature_snapshot=_feature_snapshot(),
            paper_status={"paper_only": True, "open_position_count": 0},
            calibration=_calibration(),
            registry=_registry(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
        )


def test_directional_typed_action_consumes_conservative_microstructure_estimates() -> None:
    intent = _intent()
    calibration = _calibration()
    registry = _registry()
    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=calibration,
        registry=registry,
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )
    selected = next(
        item
        for item in result.objective_inputs
        if item.action_id.endswith(":champion_exploitation:long")
    )
    statistics = policy_shadow._statistics(calibration, "LONG", "15m")  # noqa: SLF001
    plan = policy_shadow._physical_plan(  # noqa: SLF001
        intent=intent,
        statistics=statistics,
        side="LONG",
        mode=policy_shadow.CHAMPION_EXPLOITATION,
    )

    action = policy_shadow._policy_action(  # noqa: SLF001
        selected=selected,
        intent=intent,
        registry=registry,
        calibration=calibration,
        evaluation=result.objective_evaluation,
        plan=plan,
        statistics=statistics,
        state_id=selected.state_id,
        state_sha256=selected.state_sha256,
        source_receipts=(_sha("f"),),
        generated_at_ms=4_000_000,
    )

    assert action.expected_fill_probability == pytest.approx(
        min(1.0 - statistics["venue_infeasible_probability"], 0.37)
    )
    assert action.expected_slippage == pytest.approx(
        max(statistics["slippage_bps_quantiles"]["0.5"], 7.0)
    )
    assert action.expected_market_impact == pytest.approx(
        max(statistics["market_impact_bps_quantiles"]["0.5"], 9.0)
    )
    assert action.expected_adverse_selection == pytest.approx(
        max(statistics["slippage_failure_probability"], 0.61)
    )
    assert action.expected_cost_breakdown.slippage_bps == action.expected_slippage
    assert action.expected_cost_breakdown.market_impact_bps == action.expected_market_impact
    assert action.expected_cost_breakdown.total_cost_bps == pytest.approx(
        action.expected_cost_breakdown.fee_bps
        + action.expected_cost_breakdown.spread_bps
        + action.expected_cost_breakdown.slippage_bps
        + action.expected_cost_breakdown.market_impact_bps
        + action.expected_cost_breakdown.funding_bps
    )
    assert "MICROSTRUCTURE_CONTINUOUS_ESTIMATES_CONSUMED" in (
        action.decision_rationale_codes
    )


def test_missing_verified_finality_snapshot_fails_closed() -> None:
    snapshot = _feature_snapshot()
    snapshot["latest_unclosed_kline_excluded"] = False
    with pytest.raises(AdaptivePolicyShadowError, match="unclosed_kline"):
        build_adaptive_policy_shadow_candidate(
            intent=_intent(),
            feature_snapshot=snapshot,
            paper_status={"paper_only": True, "open_position_count": 0},
            calibration=_calibration(),
            registry=_registry(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
        )


def test_live_authority_flag_prevents_hard_valid_adaptive_trade() -> None:
    intent = _intent()
    intent["routes_to_live"] = True
    with pytest.raises(AdaptivePolicyShadowError, match="no_hard_valid_selection"):
        build_adaptive_policy_shadow_candidate(
            intent=intent,
            feature_snapshot=_feature_snapshot(),
            paper_status={"paper_only": True, "open_position_count": 0},
            calibration=_calibration(),
            registry=_registry(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime_cost_capture_status", "FALLBACK_COST_CAPTURE"),
        ("production_grade_cost_flag", False),
        ("fallback_cost_flag", True),
        ("runtime_cost_capture_missing_fields", ["fee_bps"]),
        ("runtime_cost_capture_temporal_reject_reasons", ["FUTURE_COST"]),
        ("expected_slippage_bps", "not-a-number"),
        ("cost_source_timestamp", "1970-01-01T01:23:20.000Z"),
    ),
)
def test_invalid_exact_cost_contract_cannot_produce_directional_action(
    field: str,
    value: object,
) -> None:
    intent = _intent()
    intent[field] = value

    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=_calibration(),
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )

    assert result.selected_adaptive_action.selected_action == "remain_flat"
    assert all(
        item.hard_constraints_satisfied is False
        for item in result.objective_inputs
        if item.selected_action == "directional_trade"
    )


def test_missing_physical_evidence_during_open_position_persists_fail_closed_flat() -> None:
    intent = _intent()
    intent["paper_cycle_reservation_snapshot"] = {}
    intent["paper_cycle_reservation_snapshot_hash"] = None

    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 1},
        calibration=_calibration(),
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )

    assert result.selected_adaptive_action.selected_action == "remain_flat"
    assert result.selected_adaptive_action.target_notional_usd == 0.0
    assert result.selected_adaptive_action.margin_allocation_usd == 0.0
    assert result.selected_adaptive_action.operator_catastrophic_envelope_id.startswith(
        "paper_nonexecuting_flat_envelope_"
    )
    assert len(result.component_estimates) == 0
    assert len(result.venue_attestations) == 0
    directional = [
        item for item in result.objective_inputs if item.selected_action == "directional_trade"
    ]
    flat = next(
        item for item in result.objective_inputs if item.selected_action == "remain_flat"
    )
    assert len(directional) == 4
    assert all(item.hard_constraints_satisfied is False for item in directional)
    assert flat.hard_constraints_satisfied is True
    dispositions = dict(result.action_dispositions)
    assert dispositions[flat.action_id] == ()
    assert {
        reason
        for item in directional
        for reason in dispositions[item.action_id]
    } == {"PHYSICAL_PLAN_UNAVAILABLE:reservation.derived:object_required"}
    assert result.routes_to_live is False
    assert result.places_real_order is False
    assert result.exchange_action_taken is False


def test_existing_position_blocks_new_direction_but_not_nonexecuting_flat() -> None:
    result = build_adaptive_policy_shadow_candidate(
        intent=_intent(),
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 1},
        calibration=_calibration(),
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )

    directional = [
        item for item in result.objective_inputs if item.selected_action == "directional_trade"
    ]
    flat = next(
        item for item in result.objective_inputs if item.selected_action == "remain_flat"
    )
    assert len(result.component_estimates) == 4
    assert len(result.venue_attestations) == 4
    assert all(item.hard_constraints_satisfied is False for item in directional)
    assert all(
        dict(result.action_dispositions)[item.action_id]
        == ("position_transition_validity",)
        for item in directional
    )
    assert flat.hard_constraints_satisfied is True
    assert dict(result.action_dispositions)[flat.action_id] == ()
    assert result.selected_adaptive_action.selected_action == "remain_flat"


def test_close_or_reduce_only_microstructure_blocks_new_entry_but_remains_input() -> None:
    intent = _intent()
    intent["microstructure_action"] = "CLOSE_OR_REDUCE_ONLY"

    result = build_adaptive_policy_shadow_candidate(
        intent=intent,
        feature_snapshot=_feature_snapshot(),
        paper_status={"paper_only": True, "open_position_count": 0},
        calibration=_calibration(),
        registry=_registry(),
        validator_seed=_SEED,
        generated_at_ms=4_000_000,
    )

    directional = [
        item for item in result.objective_inputs if item.selected_action == "directional_trade"
    ]
    assert all(item.hard_constraints_satisfied is False for item in directional)
    assert all(
        dict(result.action_dispositions)[item.action_id]
        == ("position_transition_validity",)
        for item in directional
    )
    assert result.selected_adaptive_action.selected_action == "remain_flat"


def test_nonfinite_cost_payload_fails_before_any_policy_decision() -> None:
    intent = _intent()
    intent["expected_slippage_bps"] = float("nan")

    with pytest.raises(ValueError, match="Out of range float values"):
        build_adaptive_policy_shadow_candidate(
            intent=intent,
            feature_snapshot=_feature_snapshot(),
            paper_status={"paper_only": True, "open_position_count": 0},
            calibration=_calibration(),
            registry=_registry(),
            validator_seed=_SEED,
            generated_at_ms=4_000_000,
        )
