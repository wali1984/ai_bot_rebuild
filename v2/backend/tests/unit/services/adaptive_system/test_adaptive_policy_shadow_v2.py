from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.adaptive_system import adaptive_hard_validator_v2
from v2.backend.app.services.adaptive_system import adaptive_objective_v2
from v2.backend.app.services.adaptive_system.adaptive_policy_shadow_v2 import (
    AdaptivePolicyShadowError,
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
