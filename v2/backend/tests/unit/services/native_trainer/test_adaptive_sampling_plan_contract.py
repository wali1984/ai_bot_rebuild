from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer import (
    adaptive_sampling_plan_contract as contract,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
    on_policy_behavior,
)

CHECKPOINT_ID = "v2_hybrid_ckpt_deadbeef_0123456789abcdef_abcdef012345"
CHECKPOINT_HASH = "c" * 64
CHECKPOINT_EVIDENCE_DIGEST = "e" * 64
PARENT_POLICY_FINGERPRINT = "d" * 64
CYCLE_ID = "v2_cycle_authenticated_plan_unit"
PROCESS_INSTANCE_ID = "unit-host:4242:restart-nonce"
AUTH_KEY_ID = "trainer-plan-auth-unit-v1"
AUTH_KEY = b"unit-sampling-plan-hmac-key-32b!"


def _candidate(index: int = 0) -> dict[str, object]:
    return {
        "symbol": f"COIN{index}USDT",
        "timeframe": "1m",
        "feature_tensor_id": f"tensor_{index}",
        "feature_cutoff": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:30Z",
        "candle_close_time": "2026-07-18T00:00:00Z",
        "candle_closed_confirmed": True,
        "decision_time": "2026-07-18T00:01:00Z",
        "row_classification": "TRAINABLE",
        "raw_action_logits": [0.0] * 7,
        "confidence_calibrated": 0.5,
        "confidence_calibration_fitted": True,
        "expected_move_bps": 12.0,
        "round_trip_cost_bps": 2.0,
        "exact_cost_provenance_valid": True,
        "exact_cost_payload_hash": "a" * 64,
        "served_policy_fingerprint_available": True,
        "served_policy_fingerprint": PARENT_POLICY_FINGERPRINT,
        "confidence_candidate_action": "long",
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_weight_sha256": CHECKPOINT_HASH,
        "checkpoint_evidence_digest": CHECKPOINT_EVIDENCE_DIGEST,
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
    }


def _plan() -> dict[str, object]:
    return on_policy_behavior.adaptive_on_policy_lane_plan(
        [_candidate()],
        paper_margin_status={
            "schema_version": "paper_account_margin_v1",
            "generated_utc": "2026-07-18T00:01:10Z",
            "status": "PASS",
            "invariant_holds": True,
            "margin_base_usd": 100.0,
            "free_margin_after_buffer_usd": 75.0,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        paper_entry_freeze={
            "schema_version": "paper_entry_freeze_v1",
            "generated_utc": "2026-07-18T00:01:11Z",
            "paper_new_entries_halted": False,
            "new_entries_allowed": True,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        carry_in=1.0,
        single_candidate_ordinary_credit_in=1,
    )


def _envelope(
    *,
    draw: int = 123456789,
    sealed_at: str = "2026-07-18T00:02:00Z",
    cycle_id: str = CYCLE_ID,
) -> dict[str, object]:
    return contract.build_authenticated_sampling_plan_envelope(
        sampling_plan=_plan(),
        cycle_id=cycle_id,
        process_instance_id=PROCESS_INSTANCE_ID,
        parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256=CHECKPOINT_HASH,
        selected_index_draws={0: draw},
        sealed_at=sealed_at,
        auth_key_id=AUTH_KEY_ID,
        hmac_key=AUTH_KEY,
    )


def _rehash_plan(plan: dict[str, object]) -> None:
    unsigned = dict(plan)
    unsigned.pop("plan_hash", None)
    plan["plan_hash"] = contract.canonical_sha256(unsigned)


def _rehash_plan_input_and_plan(plan: dict[str, object]) -> None:
    plan["input_hash"] = contract.canonical_sha256(
        {
            "schema_version": plan["schema_version"],
            "formula": plan["formula"],
            "carry_in": plan["carry_in"],
            "single_candidate_ordinary_credit_in": plan[
                "single_candidate_ordinary_credit_in"
            ],
            "paper_margin_inputs": plan["paper_margin_inputs"],
            "paper_entry_freeze_inputs": plan["paper_entry_freeze_inputs"],
            "candidate_audit": plan["candidate_audit"],
        }
    )
    _rehash_plan(plan)


def test_neutral_contract_import_does_not_load_hybrid_trainer() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    code = "\n".join(
        (
            "import sys",
            "import v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract",
            "prefix = 'v2.backend.app.services.native_trainer.hybrid_cuda_trainer'",
            "assert not any(name.startswith(prefix) for name in sys.modules)",
        )
    )
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_on_policy_behavior_reexports_neutral_contract_without_semantic_drift() -> None:
    plan = _plan()

    assert (
        on_policy_behavior.adaptive_on_policy_lane_plan_rejection_reasons
        is contract.adaptive_on_policy_lane_plan_rejection_reasons
    )
    assert on_policy_behavior.U53_DENOMINATOR == contract.U53_DENOMINATOR
    assert contract.adaptive_on_policy_lane_plan_rejection_reasons(plan) == []
    assert contract.validated_adaptive_on_policy_lane_plan(plan) == plan
    candidate = plan["candidate_audit"][0]
    assert candidate["served_policy_fingerprint_available"] is True
    assert candidate["served_policy_fingerprint"] == PARENT_POLICY_FINGERPRINT
    assert candidate["confidence_candidate_action"] == "long"
    assert candidate["exact_cost_provenance_valid"] is True
    assert candidate["confidence_calibration_fitted"] is True
    assert candidate["raw_action_logits"] == [0.0] * 7


def test_authenticated_envelope_binds_full_plan_cycle_checkpoint_and_exact_draw() -> None:
    envelope = _envelope()
    expected_instance = contract.sampling_plan_instance_id(
        cycle_id=CYCLE_ID,
        process_instance_id=PROCESS_INSTANCE_ID,
    )

    assert envelope["plan_instance_id"] == expected_instance
    assert envelope["sampling_plan"] == _plan()
    assert envelope["sampling_plan_hash"] == _plan()["plan_hash"]
    assert envelope["selected_index_draws"] == [
        {
            "selected_index": 0,
            "draw_u53": 123456789,
            "draw_denominator": contract.U53_DENOMINATOR,
        }
    ]
    assert envelope["selected_draw_count"] == 1
    assert envelope["sealed_at"] == "2026-07-18T00:02:00.000000Z"
    assert envelope["paper_only"] is True
    assert envelope["routes_to_live"] is False
    assert envelope["places_real_order"] is False
    assert len(str(envelope["auth_tag"])) == 64

    verified = contract.verify_authenticated_sampling_plan_envelope(
        envelope,
        hmac_key=AUTH_KEY,
        expected_cycle_id=CYCLE_ID,
        expected_process_instance_id=PROCESS_INSTANCE_ID,
        expected_parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
        expected_checkpoint_id=CHECKPOINT_ID,
        expected_checkpoint_weight_sha256=CHECKPOINT_HASH,
        expected_auth_key_id=AUTH_KEY_ID,
        expected_plan_instance_id=expected_instance,
    )
    assert verified == envelope
    assert verified is not envelope


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("cycle_id", "v2_cycle_tampered"),
        ("process_instance_id", "other-host:9:nonce"),
        ("parent_policy_fingerprint", "1" * 64),
        ("checkpoint_id", "v2_hybrid_ckpt_feedface_0123456789abcdef_abcdef012345"),
        ("checkpoint_weight_sha256", "2" * 64),
        ("sealed_at", "2026-07-18T00:03:00.000000Z"),
        ("auth_key_id", "another-key"),
        ("auth_domain", "wrong/domain"),
        ("plan_instance_id", "3" * 64),
    ),
)
def test_every_identity_and_auth_binding_tamper_fails_hmac(
    field: str, replacement: str
) -> None:
    envelope = _envelope()
    envelope[field] = replacement

    reasons = contract.authenticated_sampling_plan_envelope_rejection_reasons(
        envelope,
        hmac_key=AUTH_KEY,
    )

    assert "sampling_plan_envelope_authentication_invalid" in reasons


def test_nested_plan_and_draw_tampering_fail_hmac_and_semantics() -> None:
    plan_tampered = _envelope()
    plan_tampered["sampling_plan"]["market_static_sampling_threshold_used"] = True
    plan_reasons = contract.authenticated_sampling_plan_envelope_rejection_reasons(
        plan_tampered,
        hmac_key=AUTH_KEY,
    )
    assert "sampling_plan_envelope_authentication_invalid" in plan_reasons
    assert "sampling_plan_envelope_plan_invalid" in plan_reasons

    draw_tampered = _envelope()
    draw_tampered["selected_index_draws"][0]["draw_u53"] += 1
    draw_reasons = contract.authenticated_sampling_plan_envelope_rejection_reasons(
        draw_tampered,
        hmac_key=AUTH_KEY,
    )
    assert "sampling_plan_envelope_authentication_invalid" in draw_reasons
    assert "sampling_plan_envelope_cycle_binding_invalid" in draw_reasons


@pytest.mark.parametrize(
    "draws",
    (
        {},
        {0: -1},
        {0: contract.U53_DENOMINATOR},
        {0: True},
        {0: 1, 1: 2},
    ),
)
def test_builder_requires_exact_selected_index_u53_draw_set(
    draws: dict[int, int],
) -> None:
    with pytest.raises(
        contract.AdaptiveSamplingPlanContractError,
        match="^sampling_plan_selected_draw",
    ):
        contract.build_authenticated_sampling_plan_envelope(
            sampling_plan=_plan(),
            cycle_id=CYCLE_ID,
            process_instance_id=PROCESS_INSTANCE_ID,
            parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
            checkpoint_id=CHECKPOINT_ID,
            checkpoint_weight_sha256=CHECKPOINT_HASH,
            selected_index_draws=draws,
            sealed_at="2026-07-18T00:02:00Z",
            auth_key_id=AUTH_KEY_ID,
            hmac_key=AUTH_KEY,
        )


def test_builder_rejects_short_or_text_hmac_keys() -> None:
    for invalid_key in (b"k" * 31, "k" * 64):
        with pytest.raises(contract.AdaptiveSamplingPlanContractError):
            contract.build_authenticated_sampling_plan_envelope(
                sampling_plan=_plan(),
                cycle_id=CYCLE_ID,
                process_instance_id=PROCESS_INSTANCE_ID,
                parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
                checkpoint_id=CHECKPOINT_ID,
                checkpoint_weight_sha256=CHECKPOINT_HASH,
                selected_index_draws={0: 1},
                sealed_at="2026-07-18T00:02:00Z",
                auth_key_id=AUTH_KEY_ID,
                hmac_key=invalid_key,  # type: ignore[arg-type]
            )


def test_builder_rejects_noncausal_seal_and_checkpoint_drift() -> None:
    with pytest.raises(
        contract.AdaptiveSamplingPlanContractError,
        match="^sampling_plan_sealed_before_inputs$",
    ):
        _envelope(sealed_at="2026-07-18T00:01:05Z")

    with pytest.raises(
        contract.AdaptiveSamplingPlanContractError,
        match="^sampling_plan_checkpoint_binding_mismatch$",
    ):
        contract.build_authenticated_sampling_plan_envelope(
            sampling_plan=_plan(),
            cycle_id=CYCLE_ID,
            process_instance_id=PROCESS_INSTANCE_ID,
            parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
            checkpoint_id=CHECKPOINT_ID,
            checkpoint_weight_sha256="9" * 64,
            selected_index_draws={0: 1},
            sealed_at="2026-07-18T00:02:00Z",
            auth_key_id=AUTH_KEY_ID,
            hmac_key=AUTH_KEY,
        )


def test_plan_validator_recomputes_static_safety_and_selected_eligible_set() -> None:
    static_plan = copy.deepcopy(_plan())
    static_plan["market_static_sampling_threshold_used"] = True
    _rehash_plan(static_plan)
    assert (
        "adaptive_sampling_plan_static_market_threshold_invalid"
        in contract.adaptive_on_policy_lane_plan_rejection_reasons(static_plan)
    )

    selection_plan = copy.deepcopy(_plan())
    candidate = selection_plan["candidate_audit"][0]
    candidate["eligible"] = False
    candidate["rejection_reasons"] = ["served_policy_fingerprint_unavailable"]
    candidate["adaptive_score"] = 0.0
    candidate["candidate_token_credit"] = 0.0
    input_material = {
        "schema_version": selection_plan["schema_version"],
        "formula": selection_plan["formula"],
        "carry_in": selection_plan["carry_in"],
        "single_candidate_ordinary_credit_in": selection_plan[
            "single_candidate_ordinary_credit_in"
        ],
        "paper_margin_inputs": selection_plan["paper_margin_inputs"],
        "paper_entry_freeze_inputs": selection_plan[
            "paper_entry_freeze_inputs"
        ],
        "candidate_audit": selection_plan["candidate_audit"],
    }
    selection_plan["input_hash"] = contract.canonical_sha256(input_material)
    _rehash_plan(selection_plan)
    selection_reasons = contract.adaptive_on_policy_lane_plan_rejection_reasons(
        selection_plan
    )
    assert "adaptive_sampling_plan_selection_semantics_invalid" in selection_reasons


@pytest.mark.parametrize(
    "truth_field",
    (
        "served_policy_fingerprint_available",
        "exact_cost_provenance_valid",
        "confidence_calibration_fitted",
    ),
)
def test_selected_candidate_requires_sealed_producer_truth(
    truth_field: str,
) -> None:
    plan = copy.deepcopy(_plan())
    plan["candidate_audit"][0][truth_field] = False
    _rehash_plan_input_and_plan(plan)

    reasons = contract.adaptive_on_policy_lane_plan_rejection_reasons(plan)

    assert "adaptive_sampling_plan_candidate_rejections_mismatch" in reasons
    assert "adaptive_sampling_plan_candidate_rank_hash_invalid" in reasons
    with pytest.raises(
        contract.AdaptiveSamplingPlanContractError,
        match="^adaptive_sampling_plan_invalid:",
    ):
        contract.build_authenticated_sampling_plan_envelope(
            sampling_plan=plan,
            cycle_id=CYCLE_ID,
            process_instance_id=PROCESS_INSTANCE_ID,
            parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
            checkpoint_id=CHECKPOINT_ID,
            checkpoint_weight_sha256=CHECKPOINT_HASH,
            selected_index_draws={0: 1},
            sealed_at="2026-07-18T00:02:00Z",
            auth_key_id=AUTH_KEY_ID,
            hmac_key=AUTH_KEY,
        )


def test_validator_recomputes_logits_hash_entropy_and_rank_binding() -> None:
    plan = copy.deepcopy(_plan())
    plan["candidate_audit"][0]["raw_action_logits"][0] = 5.0
    _rehash_plan_input_and_plan(plan)

    reasons = contract.adaptive_on_policy_lane_plan_rejection_reasons(plan)

    assert "adaptive_sampling_plan_candidate_distribution_invalid" in reasons
    assert "adaptive_sampling_plan_candidate_rank_hash_invalid" in reasons


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("served_policy_fingerprint", "f" * 64),
        ("confidence_candidate_action", "short"),
    ),
)
def test_selected_candidate_fingerprint_and_after_cost_side_are_bound(
    field: str,
    replacement: str,
) -> None:
    plan = copy.deepcopy(_plan())
    plan["candidate_audit"][0][field] = replacement
    _rehash_plan_input_and_plan(plan)

    reasons = contract.adaptive_on_policy_lane_plan_rejection_reasons(plan)

    assert "adaptive_sampling_plan_candidate_rank_hash_invalid" in reasons
    if field == "served_policy_fingerprint":
        with pytest.raises(
            contract.AdaptiveSamplingPlanContractError,
            match="^adaptive_sampling_plan_invalid:",
        ):
            contract.build_authenticated_sampling_plan_envelope(
                sampling_plan=plan,
                cycle_id=CYCLE_ID,
                process_instance_id=PROCESS_INSTANCE_ID,
                parent_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
                checkpoint_id=CHECKPOINT_ID,
                checkpoint_weight_sha256=CHECKPOINT_HASH,
                selected_index_draws={0: 1},
                sealed_at="2026-07-18T00:02:00Z",
                auth_key_id=AUTH_KEY_ID,
                hmac_key=AUTH_KEY,
            )
    else:
        assert "adaptive_sampling_plan_candidate_rejections_mismatch" in reasons


def test_older_plan_without_new_observable_evidence_fails_closed() -> None:
    plan = copy.deepcopy(_plan())
    candidate = plan["candidate_audit"][0]
    for field in (
        "served_policy_fingerprint_available",
        "served_policy_fingerprint",
        "exact_cost_provenance_valid",
        "confidence_calibration_fitted",
        "raw_action_logits",
    ):
        candidate.pop(field)
    _rehash_plan_input_and_plan(plan)

    reasons = contract.adaptive_on_policy_lane_plan_rejection_reasons(plan)

    assert "adaptive_sampling_plan_candidate_shape_invalid" in reasons
    assert "adaptive_sampling_plan_candidate_rejections_mismatch" in reasons
    assert "adaptive_sampling_plan_candidate_distribution_invalid" in reasons
    assert "adaptive_sampling_plan_candidate_rank_hash_invalid" in reasons


def test_cycle_has_one_deterministic_instance_identity_and_conflicting_bindings() -> None:
    first = _envelope(draw=1, sealed_at="2026-07-18T00:02:00Z")
    alternate = _envelope(draw=2, sealed_at="2026-07-18T00:03:00Z")
    other_cycle = _envelope(cycle_id="v2_cycle_authenticated_plan_other")

    assert first["plan_instance_id"] == alternate["plan_instance_id"]
    assert first["cycle_binding_id"] != alternate["cycle_binding_id"]
    assert first["auth_tag"] != alternate["auth_tag"]
    assert first["plan_instance_id"] != other_cycle["plan_instance_id"]


def test_verifier_uses_constant_time_hmac_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = _envelope()
    observed: list[tuple[str, str]] = []
    real_compare_digest = contract.hmac.compare_digest

    def observed_compare_digest(expected: str, supplied: str) -> bool:
        observed.append((expected, supplied))
        return real_compare_digest(expected, supplied)

    monkeypatch.setattr(contract.hmac, "compare_digest", observed_compare_digest)

    assert (
        contract.authenticated_sampling_plan_envelope_rejection_reasons(
            envelope,
            hmac_key=AUTH_KEY,
        )
        == []
    )
    assert observed == [(envelope["auth_tag"], envelope["auth_tag"])]
