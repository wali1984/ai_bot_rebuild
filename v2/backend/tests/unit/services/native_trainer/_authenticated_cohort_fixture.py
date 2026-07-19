"""Real authenticated single-member cohort fixtures for PPO unit tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract import (
    build_authenticated_sampling_plan_envelope,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    archive_authenticated_sampling_plan_envelope,
    archive_behavior_receipt,
    archive_sampling_cohort_completeness_proof,
    archive_sampling_cohort_manifest,
    build_sampling_cohort_completeness_proof,
    build_sampling_cohort_manifest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    adaptive_on_policy_lane_plan,
)

TEST_SAMPLING_PLAN_AUTH_KEY_ID = "pytest-native-trainer-cohort-v1"
TEST_SAMPLING_PLAN_AUTH_KEY = b"pytest-native-trainer-cohort-auth-key-material-v1"


def sampling_plan_key_resolver(key_id: str) -> bytes:
    if key_id != TEST_SAMPLING_PLAN_AUTH_KEY_ID:
        raise KeyError(key_id)
    return TEST_SAMPLING_PLAN_AUTH_KEY


def build_single_member_sampling_plan(
    *,
    symbol: str,
    timeframe: str,
    feature_tensor_id: str,
    feature_cutoff: str,
    available_at: str,
    candle_close_time: str,
    decision_time: str,
    raw_action_logits: Sequence[float],
    expected_move_bps: float,
    exact_cost_payload_hash: str,
    parent_policy_fingerprint: str,
    checkpoint_id: str,
    checkpoint_weight_sha256: str,
    checkpoint_evidence_digest: str,
) -> dict[str, Any]:
    candidate = {
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_tensor_id": feature_tensor_id,
        "feature_cutoff": feature_cutoff,
        "available_at": available_at,
        "candle_close_time": candle_close_time,
        "candle_closed_confirmed": True,
        "decision_time": decision_time,
        "row_classification": "TRAINABLE",
        "raw_action_logits": [float(value) for value in raw_action_logits],
        "confidence_calibrated": 0.5,
        "confidence_calibration_fitted": True,
        "confidence_candidate_action": ("long" if expected_move_bps >= 0.0 else "short"),
        "expected_move_bps": float(expected_move_bps),
        "round_trip_cost_bps": 2.0,
        "exact_cost_provenance_valid": True,
        "exact_cost_payload_hash": exact_cost_payload_hash,
        "served_policy_fingerprint_available": True,
        "served_policy_fingerprint": parent_policy_fingerprint,
        "checkpoint_id": checkpoint_id,
        "checkpoint_weight_sha256": checkpoint_weight_sha256,
        "checkpoint_evidence_digest": checkpoint_evidence_digest,
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
    }
    return adaptive_on_policy_lane_plan(
        [candidate],
        paper_margin_status={
            "schema_version": "paper_account_margin_v1",
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
            "paper_new_entries_halted": False,
            "new_entries_allowed": True,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        },
        carry_in=1.0,
        single_candidate_ordinary_credit_in=1,
    )


def archive_single_member_pre_admission_cohort(
    *,
    root: Path,
    sampling_plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    parent_policy_fingerprint: str,
    checkpoint_id: str,
    checkpoint_weight_sha256: str,
) -> tuple[Any, dict[str, Any]]:
    decision_time = str(receipt["decision_time"])
    identity = str(receipt["prediction_id"])
    envelope = build_authenticated_sampling_plan_envelope(
        sampling_plan=sampling_plan,
        cycle_id=f"pytest-cohort-cycle:{identity}",
        process_instance_id="pytest-native-trainer:single-process",
        parent_policy_fingerprint=parent_policy_fingerprint,
        checkpoint_id=checkpoint_id,
        checkpoint_weight_sha256=checkpoint_weight_sha256,
        selected_index_draws={0: int(receipt["sample_draw_u53"])},
        sealed_at=decision_time,
        auth_key_id=TEST_SAMPLING_PLAN_AUTH_KEY_ID,
        hmac_key=TEST_SAMPLING_PLAN_AUTH_KEY,
    )
    receipt_write = archive_behavior_receipt(receipt, root=root)
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=sampling_plan_key_resolver,
        root=root,
    )
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: receipt},
        key_resolver=sampling_plan_key_resolver,
        generated_at=decision_time,
    )
    archive_sampling_cohort_manifest(
        manifest,
        key_resolver=sampling_plan_key_resolver,
        root=root,
    )
    return receipt_write, manifest


def archive_single_member_terminalized_cohort(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    receipt_hash: str,
    generated_at: str,
) -> dict[str, Any]:
    proof = build_sampling_cohort_completeness_proof(
        manifest=manifest,
        terminal_dispositions={receipt_hash: "ENTRY_OUTCOME_FINALIZED"},
        generated_at=generated_at,
    )
    archive_sampling_cohort_completeness_proof(
        proof,
        key_resolver=sampling_plan_key_resolver,
        root=root,
    )
    return proof
