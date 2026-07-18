from __future__ import annotations

import hashlib
import hmac
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.adaptive_sampling_plan_contract import (
    SAMPLING_PLAN_AUTH_DOMAIN_SEPARATOR,
    U53_DENOMINATOR,
    build_authenticated_sampling_plan_envelope,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_PUBLISHED,
    BehaviorReceiptArchiveError,
    append_lifecycle_event,
    archive_authenticated_sampling_plan_envelope,
    archive_behavior_receipt,
    archive_sampling_cohort_manifest,
    build_sampling_cohort_manifest,
    canonical_sha256,
    load_authenticated_sampling_plan_envelope,
    load_sampling_cohort_manifest,
    verify_archived_authenticated_sampling_plan_envelope,
    verify_archived_sampling_cohort_manifest,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    adaptive_on_policy_lane_plan,
    build_positive_edge_behavior_receipt,
)
from v2.backend.tests.unit.services.native_trainer.test_on_policy_behavior_receipt import (
    CHECKPOINT_EVIDENCE_DIGEST,
    CHECKPOINT_ID,
    _cost_provenance,
    _model_output,
)

PARENT_POLICY_FINGERPRINT = "d" * 64
CHECKPOINT_HASH = "c" * 64
AUTH_KEY_ID = "sampling-plan-archive-unit-v1"
AUTH_KEY = b"sampling-plan-archive-secret-material-v1"
WRONG_KEY = b"wrong-sampling-plan-secret-material-v1"
PROCESS_INSTANCE_ID = "unit-host:4242:restart-nonce"
CYCLE_ID = "v2_cycle_sampling_plan_archive_unit"
DECISION_TIME = "2026-07-18T00:01:00Z"
SEALED_AT = "2026-07-18T00:02:00Z"
MANIFEST_AT = "2026-07-18T00:02:10Z"
DRAW = U53_DENOMINATOR - 1


class _KeyResolver:
    def __init__(self, key: bytes) -> None:
        self.key = key
        self.calls: list[str] = []

    def __call__(self, key_id: str) -> bytes:
        self.calls.append(key_id)
        if key_id != AUTH_KEY_ID:
            raise KeyError(key_id)
        return self.key


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _sampling_plan() -> dict[str, Any]:
    model_output = _model_output()
    cost_provenance = _cost_provenance()
    candidate = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_tensor_id": "tensor_exact_behavior_1",
        "feature_cutoff": "2026-07-18T00:00:00Z",
        "available_at": "2026-07-18T00:00:30Z",
        "candle_close_time": "2026-07-18T00:00:00Z",
        "candle_closed_confirmed": True,
        "decision_time": DECISION_TIME,
        "row_classification": "TRAINABLE",
        "raw_action_logits": list(model_output.action_logits),
        "confidence_calibrated": 0.75,
        "confidence_calibration_fitted": True,
        "confidence_candidate_action": "long",
        "expected_move_bps": 12.0,
        "round_trip_cost_bps": 2.0,
        "exact_cost_provenance_valid": True,
        "exact_cost_payload_hash": cost_provenance["source_payload_sha256"],
        "served_policy_fingerprint_available": True,
        "served_policy_fingerprint": PARENT_POLICY_FINGERPRINT,
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint_weight_sha256": CHECKPOINT_HASH,
        "checkpoint_evidence_digest": CHECKPOINT_EVIDENCE_DIGEST,
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
    }
    return adaptive_on_policy_lane_plan(
        [candidate],
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
    draw: int = DRAW,
    cycle_id: str = CYCLE_ID,
    sealed_at: str = SEALED_AT,
) -> dict[str, Any]:
    return build_authenticated_sampling_plan_envelope(
        sampling_plan=_sampling_plan(),
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


def _receipt(
    *,
    prediction_id: str = "prediction_exact_archive_1",
    draw: int = DRAW,
) -> dict[str, Any]:
    plan = _sampling_plan()
    return build_positive_edge_behavior_receipt(
        prediction_id=prediction_id,
        model_output=_model_output(),
        symbol="BTCUSDT",
        timeframe="1m",
        checkpoint_id=CHECKPOINT_ID,
        checkpoint_weight_sha256=CHECKPOINT_HASH,
        checkpoint_evidence_digest=CHECKPOINT_EVIDENCE_DIGEST,
        checkpoint_evidence_verified=True,
        checkpoint_identity_verified=True,
        served_policy_fingerprint=PARENT_POLICY_FINGERPRINT,
        feature_tensor_id="tensor_exact_behavior_1",
        feature_vector_hash="tensor_exact_behavior_1",
        feature_cutoff="2026-07-18T00:00:00Z",
        available_at="2026-07-18T00:00:30Z",
        candle_close_time="2026-07-18T00:00:00Z",
        decision_time=DECISION_TIME,
        candle_closed_confirmed=True,
        round_trip_cost_bps=2.0,
        cost_provenance=_cost_provenance(),
        draw_u53=draw,
        sampling_plan_hash=plan["plan_hash"],
        sampling_plan_input_hash=plan["input_hash"],
    )


def _rewrite_archive_record(path: Path, mutate: Any) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("archive_content_sha256")
    mutate(record)
    record["archive_content_sha256"] = canonical_sha256(record)
    path.write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _archive_complete_pre_admission_manifest(
    *,
    root: Path,
    resolver: _KeyResolver,
    envelope: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    resolved_envelope = envelope or _envelope()
    resolved_receipt = receipt or _receipt()
    archive_behavior_receipt(resolved_receipt, root=root)
    archive_authenticated_sampling_plan_envelope(
        resolved_envelope,
        key_resolver=resolver,
        root=root,
    )
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=resolved_envelope,
        receipts_by_selected_index={0: resolved_receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    archive_sampling_cohort_manifest(
        manifest,
        key_resolver=resolver,
        root=root,
    )
    return resolved_envelope, resolved_receipt, manifest


def test_envelope_archive_is_idempotent_restart_verifiable_and_stores_no_key(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    resolver = _KeyResolver(AUTH_KEY)

    first = archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )
    second = archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )

    assert first.already_present is False
    assert second.already_present is True
    assert first.plan_instance_id == envelope["plan_instance_id"]
    archived_text = first.envelope_path.read_text(encoding="utf-8")
    assert AUTH_KEY.decode("ascii") not in archived_text
    assert AUTH_KEY.hex() not in archived_text

    restarted_resolver = _KeyResolver(AUTH_KEY)
    assert (
        load_authenticated_sampling_plan_envelope(
            envelope["plan_instance_id"],
            key_resolver=restarted_resolver,
            root=tmp_path,
        )
        == envelope
    )
    assert (
        verify_archived_authenticated_sampling_plan_envelope(
            envelope,
            key_resolver=restarted_resolver,
            root=tmp_path,
        )
        == envelope
    )
    assert restarted_resolver.calls == [AUTH_KEY_ID, AUTH_KEY_ID, AUTH_KEY_ID]


def test_envelope_read_rejects_wrong_key_and_self_consistent_payload_tamper(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    write = archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=_KeyResolver(AUTH_KEY),
        root=tmp_path,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_PLAN_ENVELOPE_AUTHENTICATION_INVALID",
    ):
        load_authenticated_sampling_plan_envelope(
            envelope["plan_instance_id"],
            key_resolver=_KeyResolver(WRONG_KEY),
            root=tmp_path,
        )

    def tamper(record: dict[str, Any]) -> None:
        record["envelope"]["selected_index_draws"][0]["draw_u53"] -= 1

    _rewrite_archive_record(write.envelope_path, tamper)
    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_PLAN_ENVELOPE_AUTHENTICATION_INVALID",
    ):
        load_authenticated_sampling_plan_envelope(
            envelope["plan_instance_id"],
            key_resolver=_KeyResolver(AUTH_KEY),
            root=tmp_path,
        )


def test_same_cycle_alternate_envelope_conflicts_on_one_plan_instance(
    tmp_path: Path,
) -> None:
    first = _envelope(draw=1, sealed_at="2026-07-18T00:02:00Z")
    alternate = _envelope(draw=2, sealed_at="2026-07-18T00:03:00Z")
    assert first["plan_instance_id"] == alternate["plan_instance_id"]
    assert first["cycle_binding_id"] != alternate["cycle_binding_id"]

    archive_authenticated_sampling_plan_envelope(
        first,
        key_resolver=_KeyResolver(AUTH_KEY),
        root=tmp_path,
    )
    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_PLAN_ENVELOPE_INSTANCE_CONFLICT",
    ):
        archive_authenticated_sampling_plan_envelope(
            alternate,
            key_resolver=_KeyResolver(AUTH_KEY),
            root=tmp_path,
        )


def test_hmac_valid_but_semantically_wrong_cycle_binding_is_rejected(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    envelope["cycle_binding_id"] = "f" * 64
    unsigned = dict(envelope)
    unsigned.pop("auth_tag")
    envelope["auth_tag"] = hmac.new(
        AUTH_KEY,
        SAMPLING_PLAN_AUTH_DOMAIN_SEPARATOR + _canonical_bytes(unsigned),
        hashlib.sha256,
    ).hexdigest()

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_PLAN_ENVELOPE_AUTHENTICATION_INVALID",
    ):
        archive_authenticated_sampling_plan_envelope(
            envelope,
            key_resolver=_KeyResolver(AUTH_KEY),
            root=tmp_path,
        )


def test_manifest_binds_envelope_tag_plan_draw_and_receipt_and_restarts(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope, receipt, manifest = _archive_complete_pre_admission_manifest(
        root=tmp_path,
        resolver=resolver,
    )

    assert manifest["sampling_plan_envelope_id"] == envelope["plan_instance_id"]
    assert manifest["sampling_plan_envelope_auth_tag"] == envelope["auth_tag"]
    assert manifest["sampling_plan_hash"] == envelope["sampling_plan_hash"]
    assert manifest["members"] == [
        {
            "selected_index": 0,
            "receipt_hash": receipt["receipt_hash"],
            "prediction_id": receipt["prediction_id"],
            "selected_action": receipt["selected_action"],
            "sample_draw_u53": DRAW,
        }
    ]

    restarted_resolver = _KeyResolver(AUTH_KEY)
    loaded = load_sampling_cohort_manifest(
        envelope["plan_instance_id"],
        key_resolver=restarted_resolver,
        root=tmp_path,
    )
    assert loaded == manifest
    assert (
        verify_archived_sampling_cohort_manifest(
            manifest,
            key_resolver=restarted_resolver,
            root=tmp_path,
        )
        == manifest
    )
    assert len(restarted_resolver.calls) >= 2
    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_PLAN_ENVELOPE_AUTHENTICATION_INVALID",
    ):
        load_sampling_cohort_manifest(
            envelope["plan_instance_id"],
            key_resolver=_KeyResolver(WRONG_KEY),
            root=tmp_path,
        )


def test_manifest_rejects_receipt_draw_not_committed_by_envelope() -> None:
    envelope = _envelope(draw=DRAW)
    receipt = _receipt(draw=DRAW - 1)

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_RECEIPT_PLAN_BINDING_INVALID",
    ):
        build_sampling_cohort_manifest(
            sampling_plan_envelope=envelope,
            receipts_by_selected_index={0: receipt},
            key_resolver=_KeyResolver(AUTH_KEY),
            generated_at=MANIFEST_AT,
        )


def test_one_envelope_cannot_archive_two_different_receipt_manifests(
    tmp_path: Path,
) -> None:
    envelope = _envelope()
    first_receipt = _receipt(prediction_id="prediction_manifest_first")
    second_receipt = _receipt(prediction_id="prediction_manifest_second")
    resolver = _KeyResolver(AUTH_KEY)
    for receipt in (first_receipt, second_receipt):
        archive_behavior_receipt(receipt, root=tmp_path)
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )
    first_manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: first_receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    second_manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: second_receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    archive_sampling_cohort_manifest(
        first_manifest,
        key_resolver=resolver,
        root=tmp_path,
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_MANIFEST_INSTANCE_CONFLICT",
    ):
        archive_sampling_cohort_manifest(
            second_manifest,
            key_resolver=resolver,
            root=tmp_path,
        )


def test_manifest_read_revalidates_receipt_blob_every_time(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope = _envelope()
    receipt = _receipt()
    receipt_write = archive_behavior_receipt(receipt, root=tmp_path)
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    archive_sampling_cohort_manifest(
        manifest,
        key_resolver=resolver,
        root=tmp_path,
    )

    def tamper_receipt(record: dict[str, Any]) -> None:
        record["receipt"]["prediction_id"] = "tampered-after-manifest"

    _rewrite_archive_record(receipt_write.blob_path, tamper_receipt)
    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="RECEIPT_HASH_CONTENT_MISMATCH",
    ):
        load_sampling_cohort_manifest(
            envelope["plan_instance_id"],
            key_resolver=_KeyResolver(AUTH_KEY),
            root=tmp_path,
        )


def test_manifest_member_metadata_cannot_diverge_from_exact_receipt(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope = _envelope()
    receipt = _receipt()
    assert receipt["selected_action"] == "long"
    archive_behavior_receipt(receipt, root=tmp_path)
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    tampered = deepcopy(manifest)
    tampered["members"][0]["selected_action"] = "short"
    identity = {
        "sampling_plan_envelope_id": tampered["sampling_plan_envelope_id"],
        "sampling_plan_envelope_auth_tag": tampered[
            "sampling_plan_envelope_auth_tag"
        ],
        "sampling_plan_cycle_binding_id": tampered[
            "sampling_plan_cycle_binding_id"
        ],
        "sampling_plan_hash": tampered["sampling_plan_hash"],
        "sampling_plan_input_hash": tampered["sampling_plan_input_hash"],
        "parent_policy_fingerprint": tampered["parent_policy_fingerprint"],
        "members": tampered["members"],
    }
    tampered["cohort_id"] = canonical_sha256(identity)
    unsigned = dict(tampered)
    unsigned.pop("manifest_digest")
    tampered["manifest_digest"] = canonical_sha256(unsigned)

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_MANIFEST_RECEIPT_IDENTITY_MISMATCH",
    ):
        archive_sampling_cohort_manifest(
            tampered,
            key_resolver=resolver,
            root=tmp_path,
        )


def test_manifest_envelope_tag_tamper_fails_binding_before_archive(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope = _envelope()
    receipt = _receipt()
    archive_behavior_receipt(receipt, root=tmp_path)
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    tampered = deepcopy(manifest)
    tampered["sampling_plan_envelope_auth_tag"] = "f" * 64
    identity = {
        "sampling_plan_envelope_id": tampered["sampling_plan_envelope_id"],
        "sampling_plan_envelope_auth_tag": tampered[
            "sampling_plan_envelope_auth_tag"
        ],
        "sampling_plan_cycle_binding_id": tampered[
            "sampling_plan_cycle_binding_id"
        ],
        "sampling_plan_hash": tampered["sampling_plan_hash"],
        "sampling_plan_input_hash": tampered["sampling_plan_input_hash"],
        "parent_policy_fingerprint": tampered["parent_policy_fingerprint"],
        "members": tampered["members"],
    }
    tampered["cohort_id"] = canonical_sha256(identity)
    unsigned = dict(tampered)
    unsigned.pop("manifest_digest")
    tampered["manifest_digest"] = canonical_sha256(unsigned)

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_MANIFEST_ENVELOPE_BINDING_INVALID",
    ):
        archive_sampling_cohort_manifest(
            tampered,
            key_resolver=resolver,
            root=tmp_path,
        )


def test_first_manifest_is_rejected_after_receipt_lifecycle_admission(
    tmp_path: Path,
) -> None:
    resolver = _KeyResolver(AUTH_KEY)
    envelope = _envelope()
    receipt = _receipt()
    archive_behavior_receipt(receipt, root=tmp_path)
    archive_authenticated_sampling_plan_envelope(
        envelope,
        key_resolver=resolver,
        root=tmp_path,
    )
    manifest = build_sampling_cohort_manifest(
        sampling_plan_envelope=envelope,
        receipts_by_selected_index={0: receipt},
        key_resolver=resolver,
        generated_at=MANIFEST_AT,
    )
    append_lifecycle_event(
        receipt_hash=receipt["receipt_hash"],
        event_type=EVENT_PUBLISHED,
        binding={
            "prediction_id": receipt["prediction_id"],
            "decision_time": receipt["decision_time"],
        },
        root=tmp_path,
        recorded_at=receipt["decision_time"],
    )

    with pytest.raises(
        BehaviorReceiptArchiveError,
        match="SAMPLING_COHORT_MANIFEST_NOT_PRE_ADMISSION",
    ):
        archive_sampling_cohort_manifest(
            manifest,
            key_resolver=resolver,
            root=tmp_path,
        )
