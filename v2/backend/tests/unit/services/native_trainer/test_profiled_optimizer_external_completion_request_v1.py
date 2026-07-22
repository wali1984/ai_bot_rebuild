from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_request_v1 as request_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_external_witness_runtime_v1 as head_runtime_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR,
    profiled_optimizer_external_completion_signing_payload_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION,
    ProfiledTrainingExternalWitnessRuntimeResultV1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_authenticated_profiled_optimizer_admission_v1 as admission_support,
)

adapter_evidence = admission_support.adapter_evidence

PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256 = (
    request_module.PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
)
PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION = (
    request_module.PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION
)
PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN = (
    request_module.PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN
)
PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION = (
    request_module.PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION
)
ProfiledOptimizerExternalCompletionPreparedRequestV1 = (
    request_module.ProfiledOptimizerExternalCompletionPreparedRequestV1
)
ProfiledOptimizerExternalCompletionRequestV1Error = (
    request_module.ProfiledOptimizerExternalCompletionRequestV1Error
)
prepare_profiled_optimizer_external_completion_request_v1 = (
    request_module.prepare_profiled_optimizer_external_completion_request_v1
)
verify_profiled_optimizer_external_completion_response_v1 = (
    request_module.verify_profiled_optimizer_external_completion_response_v1
)

AUTHORIZATION_NAMESPACE = admission_support.WITNESS_NAMESPACE
FIXED_CHALLENGE = admission_support.AUTHORIZATION_CHALLENGE
FIXED_VECTOR_PUBLIC_KEY_HEX = (
    "ee97b3847dce453a76251e9243739135f35e7cd8ee5a018abf498af80aa9571a"
)
FIXED_VECTOR_REQUEST_SHA256 = "80c7b8057e8eeb31c291666a5f1f44eab825b4563e9207f8f1fb15c00c65dc71"
FIXED_VECTOR_IDEMPOTENCY_KEY = "c3f2fa28977cb515e90aba31994a9a5cace7795e6513a44a712d25fcdb34eaf5"
FIXED_VECTOR_SIGNATURE_HEX = (
    "80fe3e236403fded6b14750bebbbc188f9031ac9b0fb0ea549bd28c8e88e5158"
    "e43477a44da8c4294076fc04ecf08c6292620518d2c23ba00a646cb594c75500"
)
FIXED_VECTOR_ENVELOPE_SHA256 = (
    "7e3d8e9d58a5de847a316f3036059dbb54fd33177469fc7ef888334d02142489"
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _h(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _fixed_vector_prepared() -> ProfiledOptimizerExternalCompletionPreparedRequestV1:
    witness_id = "fixed-completion-witness-v1"
    namespace = "fixed/profiled-optimizer-completion"
    public_key_sha256 = hashlib.sha256(bytes.fromhex(FIXED_VECTOR_PUBLIC_KEY_HEX)).hexdigest()
    challenge = bytes.fromhex(
        "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
    )
    manifest_id = _h("fixed-manifest")
    head_event_sha256 = _h("fixed-manifest-head")
    epoch_id = _h("fixed-epoch")
    consumer_lane = "fixed/profiled-consumer-v1"
    final_page_material = {
        "epoch_id": epoch_id,
        "page_sequence": 1,
        "cumulative_scanned_entry_count": 1,
        "cumulative_admitted_entry_count": 1,
        "cumulative_label_unavailable_count": 0,
        "page_end_entry_chain_sha256": _h("fixed-terminal-chain"),
        "page_transition_sha256": _h("fixed-page-transition"),
        "ordered_page_root_sha256": _h("fixed-ordered-page-root"),
        "verified_at": "2026-07-26T00:00:00.000000Z",
        "has_more_manifest_entries": False,
        **{name: False for name in request_module._LOCAL_EVENT_AUTHORITY_FIELDS},
    }
    final_page_bytes = _canonical(final_page_material)
    final_page_sha256 = hashlib.sha256(final_page_bytes).hexdigest()
    completion_material = {
        "completion_id": _h("fixed-completion-id"),
        "epoch_id": epoch_id,
        "consumer_lane": consumer_lane,
        "manifest_id": manifest_id,
        "head_candidate_event_sha256": head_event_sha256,
        "head_revision": 1,
        "page_count": 1,
        "consumed_entry_count": 1,
        "admitted_entry_count": 1,
        "label_unavailable_count": 0,
        "terminal_entry_chain_sha256": _h("fixed-terminal-chain"),
        "final_page_receipt_event_sha256": final_page_sha256,
        "final_page_transition_sha256": _h("fixed-page-transition"),
        "ordered_page_root_sha256": _h("fixed-ordered-page-root"),
        "full_consumption_locally_verified": True,
        **{name: False for name in request_module._LOCAL_EVENT_AUTHORITY_FIELDS},
    }
    completion_bytes = _canonical(completion_material)
    completion_sha256 = hashlib.sha256(completion_bytes).hexdigest()
    manifest_binding = {
        "schema_version": "profiled_optimizer_manifest_binding_v1",
        "manifest_id": manifest_id,
        "metadata_sha256": _h("fixed-metadata"),
        "metadata_auth_tag": _h("fixed-metadata-auth"),
        "auth_key_id": "fixed/manifest-key-v1",
        "observation_time": "2026-07-25T00:00:00.000000Z",
        "observation_context_sha256": _h("fixed-observation-context"),
        "feature_ledger_high_water_sha256": _h("fixed-feature-high-water"),
        "feature_ledger_archive_chain_sha256": _h("fixed-feature-archive"),
        "feature_ledger_ordered_receipts_sha256": _h("fixed-feature-receipts"),
        "label_archive_high_water_sha256": _h("fixed-label-high-water"),
        "label_archive_archive_chain_sha256": _h("fixed-label-archive"),
        "label_archive_ordered_receipts_sha256": _h("fixed-label-receipts"),
        "entry_chain_head_sha256": _h("fixed-entry-chain-head"),
        "ordered_entry_identities_sha256": _h("fixed-entry-identities"),
        "total_profiled_samples": 1,
        "admitted_example_count": 1,
        "label_unavailable_count": 0,
        "ledger_exclusion_count": 0,
        "ledger_exclusion_inventory_sha256": _h("fixed-exclusion-inventory"),
    }
    completion_binding = {
        "schema_version": "profiled_optimizer_full_consumption_binding_v1",
        "completion_event_sha256": completion_sha256,
        "completion_event_byte_count": len(completion_bytes),
        "completion_id": _h("fixed-completion-id"),
        "epoch_id": epoch_id,
        "consumer_lane": consumer_lane,
        "head_candidate_event_sha256": head_event_sha256,
        "head_revision": 1,
        "manifest_id": manifest_id,
        "page_count": 1,
        "consumed_entry_count": 1,
        "admitted_entry_count": 1,
        "label_unavailable_count": 0,
        "terminal_entry_chain_sha256": _h("fixed-terminal-chain"),
        "final_page_receipt_event_sha256": final_page_sha256,
        "final_page_transition_sha256": _h("fixed-page-transition"),
        "ordered_page_root_sha256": _h("fixed-ordered-page-root"),
        "final_page_verified_at": "2026-07-26T00:00:00.000000Z",
        "full_consumption_locally_verified": True,
    }
    claim_template = _canonical(
        {
            "schema_version": "profiled_optimizer_external_completion_authorization_v1",
            "signature_algorithm": "Ed25519",
            "signature_domain": (
                "v2/native-trainer/profiled-optimizer-external-completion-authorization/v1"
            ),
            "witness_id": witness_id,
            "namespace": namespace,
            "declared_witness_public_key_sha256": public_key_sha256,
            "authorization_sequence": 1,
            "previous_authorization_event_sha256": (
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
            ),
            "authorization_challenge_sha256": hashlib.sha256(challenge).hexdigest(),
            "authorization_challenge_byte_count": len(challenge),
            "authorization_scope": "EXACT_PROFILED_OUTCOME_SUPERVISED_INPUT_ADMISSION_ONLY",
            "manifest_binding": manifest_binding,
            "full_consumption_binding": completion_binding,
            "external_monotonic_manifest_head_verified": True,
            "full_consumption_external_ack_verified": True,
            "profiled_optimizer_admission_authorized": True,
            "outcome_supervised_objective_only": True,
            "behavior_policy_terms_authorized": False,
            **{name: False for name in request_module._DOWNSTREAM_AUTHORITY_FIELDS},
        }
    )
    head_binding = {
        "schema_version": "profiled_optimizer_external_completion_manifest_head_binding_v1",
        "witness_id": witness_id,
        "witness_public_key_sha256": public_key_sha256,
        "namespace": namespace,
        "sequence": 1,
        "event_sha256": head_event_sha256,
        "operation_id": _h("fixed-head-operation"),
        "signed_head_durably_anchored": True,
    }
    base_request = {
        "schema_version": PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION,
        "request_domain": PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN,
        "witness_id": witness_id,
        "witness_public_key_sha256": public_key_sha256,
        "authorization_namespace": namespace,
        "expected_authorization_sequence": 0,
        "expected_previous_authorization_event_sha256": (
            PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
        ),
        "manifest_head_binding": head_binding,
        "authorization_challenge_sha256": hashlib.sha256(challenge).hexdigest(),
        "authorization_challenge_byte_count": len(challenge),
        "authorization_challenge_base64": base64.b64encode(challenge).decode("ascii"),
        "authorization_claim_template_sha256": hashlib.sha256(claim_template).hexdigest(),
        "authorization_claim_template_byte_count": len(claim_template),
        "authorization_claim_template_base64": base64.b64encode(claim_template).decode("ascii"),
        "completion_event_sha256": completion_sha256,
        "completion_event_byte_count": len(completion_bytes),
        "completion_event_base64": base64.b64encode(completion_bytes).decode("ascii"),
        "final_page_receipt_event_sha256": final_page_sha256,
        "final_page_receipt_event_byte_count": len(final_page_bytes),
        "final_page_receipt_event_base64": base64.b64encode(final_page_bytes).decode("ascii"),
        "authorization_scope": "EXACT_PROFILED_OUTCOME_SUPERVISED_INPUT_ADMISSION_ONLY",
        "outcome_supervised_objective_only": True,
        "behavior_policy_terms_authorized": False,
        "full_consumption_locally_verified": True,
        **{name: False for name in request_module._REQUEST_AUTHORITY_FIELDS},
    }
    idempotency_key = hashlib.sha256(
        PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN.encode("ascii")
        + b"\0"
        + _canonical(base_request)
    ).hexdigest()
    request_bytes = _canonical({**base_request, "idempotency_key": idempotency_key})
    return ProfiledOptimizerExternalCompletionPreparedRequestV1(
        schema_version=PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION,
        witness_id=witness_id,
        witness_public_key_sha256=public_key_sha256,
        authorization_namespace=namespace,
        expected_authorization_sequence=0,
        expected_previous_authorization_event_sha256=(
            PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
        ),
        manifest_id=manifest_id,
        completion_event_sha256=completion_sha256,
        completion_event_byte_count=len(completion_bytes),
        completion_event_bytes=completion_bytes,
        final_page_receipt_event_sha256=final_page_sha256,
        final_page_receipt_event_byte_count=len(final_page_bytes),
        final_page_receipt_event_bytes=final_page_bytes,
        manifest_head_namespace=namespace,
        manifest_head_sequence=1,
        manifest_head_event_sha256=head_event_sha256,
        manifest_head_operation_id=_h("fixed-head-operation"),
        authorization_challenge=challenge,
        authorization_challenge_sha256=hashlib.sha256(challenge).hexdigest(),
        authorization_claim_template=claim_template,
        authorization_claim_template_sha256=hashlib.sha256(claim_template).hexdigest(),
        idempotency_key=idempotency_key,
        request_sha256=hashlib.sha256(request_bytes).hexdigest(),
        request_byte_count=len(request_bytes),
        request_bytes=request_bytes,
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        profiled_optimizer_admission_authorized=False,
        optimizer_execution_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _construction_token=request_module._PREPARED_TOKEN,
    )


def _head_anchor(evidence: dict[str, Any]) -> ProfiledTrainingExternalWitnessRuntimeResultV1:
    completion = evidence["completion"]
    return ProfiledTrainingExternalWitnessRuntimeResultV1(
        schema_version=PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION,
        operation_id=hashlib.sha256(b"fixed-manifest-head-operation-v1").hexdigest(),
        witness_id=admission_support.WITNESS_ID,
        witness_public_key_sha256=evidence["public_key_sha256"],
        namespace=AUTHORIZATION_NAMESPACE,
        expected_sequence=completion.head_revision - 1,
        anchored_sequence=completion.head_revision,
        event_sha256=completion.head_candidate_event_sha256,
        recovered_operation_ids=(),
        network_append_attempt_count=1,
        candidate_dispatched_after_recovery=True,
        candidate_was_recovered=False,
        journal_operation_count=1,
        journal_transition_count=2,
        journal_anchored_count=1,
        journal_pending_count=0,
        signed_head_durably_anchored=True,
        _construction_token=head_runtime_module._RESULT_TOKEN,
    )


def _prepared(
    evidence: dict[str, Any],
    *,
    challenge: bytes = FIXED_CHALLENGE,
    expected_sequence: int = 0,
    predecessor: str = PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256,
    namespace: str = AUTHORIZATION_NAMESPACE,
    head_anchor: ProfiledTrainingExternalWitnessRuntimeResultV1 | None = None,
) -> Any:
    return prepare_profiled_optimizer_external_completion_request_v1(
        authenticated_manifest=evidence["authenticated"],
        completion=evidence["completion"],
        final_page=evidence["final_page"],
        completion_staging_store=evidence["staging_store"],
        manifest_head_anchor=_head_anchor(evidence) if head_anchor is None else head_anchor,
        authorization_namespace=namespace,
        expected_authorization_sequence=expected_sequence,
        expected_previous_authorization_event_sha256=predecessor,
        authorization_challenge=challenge,
    )


def _signed_envelope(
    prepared: Any,
    *,
    accepted_at: str | None = None,
    private_key: Ed25519PrivateKey | None = None,
) -> bytes:
    template = json.loads(prepared.authorization_claim_template)
    if accepted_at is None:
        final_page_verified_at = datetime.fromisoformat(
            template["full_consumption_binding"]["final_page_verified_at"].replace(
                "Z", "+00:00"
            )
        ).astimezone(UTC)
        accepted_at = (
            (final_page_verified_at + timedelta(minutes=1))
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    unsigned = {**template, "accepted_at": accepted_at}
    key = admission_support._private_key() if private_key is None else private_key
    signature = key.sign(
        PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR
        + _canonical(unsigned)
    ).hex()
    return _canonical({**unsigned, "signature_hex": signature})


def test_prepared_request_is_exact_deterministic_and_non_authorizing(
    adapter_evidence: dict[str, Any],
) -> None:
    first = _prepared(adapter_evidence)
    replay = _prepared(adapter_evidence)
    request = json.loads(first.request_bytes)

    assert first == replay
    assert first.request_bytes == replay.request_bytes
    assert first.schema_version == PROFILED_OPTIMIZER_COMPLETION_PREPARED_REQUEST_V1_SCHEMA_VERSION
    assert request["schema_version"] == PROFILED_OPTIMIZER_COMPLETION_REQUEST_V1_SCHEMA_VERSION
    assert request["request_domain"] == PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN
    assert request["expected_authorization_sequence"] == 0
    assert (
        request["expected_previous_authorization_event_sha256"]
        == PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
    )
    assert request["manifest_head_binding"]["event_sha256"] == (
        adapter_evidence["completion"].head_candidate_event_sha256
    )
    assert request["manifest_head_binding"]["sequence"] == (
        adapter_evidence["completion"].head_revision
    )
    assert request["authorization_challenge_byte_count"] == 32
    assert request["authorization_challenge_sha256"] == hashlib.sha256(
        FIXED_CHALLENGE
    ).hexdigest()
    assert first.request_sha256 == hashlib.sha256(first.request_bytes).hexdigest()
    base = {name: value for name, value in request.items() if name != "idempotency_key"}
    assert first.idempotency_key == hashlib.sha256(
        PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN.encode("ascii")
        + b"\0"
        + _canonical(base)
    ).hexdigest()
    for name in (
        "external_monotonic_manifest_head_verified",
        "full_consumption_external_ack_verified",
        "profiled_optimizer_admission_authorized",
        "optimizer_execution_authorized",
        "checkpoint_write_authorized",
        "model_write_authorized",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
        "order_submission_authorized",
        "execution_authorized",
        "runtime_wired",
    ):
        assert request[name] is False
        assert getattr(first, name) is False


def test_claim_template_is_the_existing_signing_material_minus_acceptance_clock(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared = _prepared(adapter_evidence)
    signing_payload = profiled_optimizer_external_completion_signing_payload_v1(
        authenticated_manifest=adapter_evidence["authenticated"],
        completion=adapter_evidence["completion"],
        final_page=adapter_evidence["final_page"],
        witness_id=admission_support.WITNESS_ID,
        namespace=AUTHORIZATION_NAMESPACE,
        witness_public_key_sha256=adapter_evidence["public_key_sha256"],
        authorization_sequence=1,
        previous_authorization_event_sha256=(
            PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
        ),
        authorization_challenge=FIXED_CHALLENGE,
        accepted_at=adapter_evidence["accepted_at"],
    )
    unsigned = json.loads(
        signing_payload[len(PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR) :]
    )
    unsigned.pop("accepted_at")

    assert prepared.authorization_claim_template == _canonical(unsigned)


def test_signed_response_verifies_exact_request_and_grants_admission_only(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared = _prepared(adapter_evidence)
    envelope = _signed_envelope(prepared)
    verified = verify_profiled_optimizer_external_completion_response_v1(
        prepared=prepared,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )

    assert verified.request_sha256 == prepared.request_sha256
    assert verified.authorization_sequence == 1
    assert verified.previous_authorization_event_sha256 == (
        PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
    )
    assert verified.authorization_envelope_sha256 == hashlib.sha256(envelope).hexdigest()
    assert verified.external_monotonic_manifest_head_verified is True
    assert verified.full_consumption_external_ack_verified is True
    assert verified.profiled_optimizer_admission_authorized is True
    assert verified.optimizer_execution_authorized is False
    assert verified.checkpoint_write_authorized is False
    assert verified.model_write_authorized is False
    assert verified.prediction_authorized is False
    assert verified.paper_trading_authorized is False
    assert verified.live_execution_authorized is False
    assert verified.order_submission_authorized is False
    assert verified.execution_authorized is False
    assert verified.runtime_wired is False

    changed_accepted_at = (
        (
            datetime.fromisoformat(verified.accepted_at.replace("Z", "+00:00"))
            + timedelta(minutes=1)
        )
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    for changes in (
        {"accepted_at": changed_accepted_at},
        {"manifest_id": hashlib.sha256(b"changed-manifest-result").hexdigest()},
        {"authorization_sequence": 2},
        {"request_sha256": hashlib.sha256(b"changed-request-result").hexdigest()},
    ):
        with pytest.raises(
            ProfiledOptimizerExternalCompletionRequestV1Error,
            match="VERIFIED_RESPONSE_BINDING_INVALID",
        ):
            replace(verified, **changes)


def test_literal_independent_completion_authorization_ed25519_vector() -> None:
    """Verify frozen bytes without calling any test or production signer."""

    prepared = _fixed_vector_prepared()
    unsigned = {
        **json.loads(prepared.authorization_claim_template),
        "accepted_at": "2026-07-27T00:00:00.000000Z",
    }
    envelope = _canonical(
        {
            **unsigned,
            "signature_hex": FIXED_VECTOR_SIGNATURE_HEX,
        }
    )

    assert prepared.request_sha256 == FIXED_VECTOR_REQUEST_SHA256
    assert prepared.idempotency_key == FIXED_VECTOR_IDEMPOTENCY_KEY
    assert hashlib.sha256(envelope).hexdigest() == FIXED_VECTOR_ENVELOPE_SHA256
    verified = verify_profiled_optimizer_external_completion_response_v1(
        prepared=prepared,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=bytes.fromhex(FIXED_VECTOR_PUBLIC_KEY_HEX),
    )
    assert verified.authorization_envelope_sha256 == FIXED_VECTOR_ENVELOPE_SHA256
    assert verified.authorization_sequence == 1


def test_authorization_log_sequence_is_distinct_from_manifest_head_sequence(
    adapter_evidence: dict[str, Any],
) -> None:
    predecessor = hashlib.sha256(b"completion-authorization-event-16").hexdigest()
    prepared = _prepared(
        adapter_evidence,
        expected_sequence=16,
        predecessor=predecessor,
    )
    envelope = _signed_envelope(prepared)
    verified = verify_profiled_optimizer_external_completion_response_v1(
        prepared=prepared,
        authorization_envelope_bytes=envelope,
        witness_public_key_bytes=adapter_evidence["public_key"],
    )

    assert prepared.manifest_head_sequence == adapter_evidence["completion"].head_revision == 1
    assert verified.authorization_sequence == 17
    assert verified.previous_authorization_event_sha256 == predecessor


@pytest.mark.parametrize(
    ("sequence", "predecessor", "reason"),
    (
        (True, PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256, "EXPECTED_SEQUENCE"),
        (-1, PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256, "EXPECTED_SEQUENCE"),
        (2**63 - 1, hashlib.sha256(b"prior").hexdigest(), "EXPECTED_SEQUENCE"),
        (0, hashlib.sha256(b"not-genesis").hexdigest(), "GENESIS_PREDECESSOR"),
        (1, PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256, "SUCCESSOR_PREDECESSOR"),
    ),
)
def test_invalid_sequence_or_predecessor_fails_before_request_creation(
    adapter_evidence: dict[str, Any],
    sequence: int,
    predecessor: str,
    reason: str,
) -> None:
    with pytest.raises(ProfiledOptimizerExternalCompletionRequestV1Error, match=reason):
        _prepared(
            adapter_evidence,
            expected_sequence=sequence,
            predecessor=predecessor,
        )


@pytest.mark.parametrize("challenge", (b"x" * 31, b"x" * 33, bytearray(b"x" * 32)))
def test_challenge_must_be_exact_raw_256_bits(
    adapter_evidence: dict[str, Any],
    challenge: Any,
) -> None:
    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="CHALLENGE_INVALID",
    ):
        _prepared(adapter_evidence, challenge=challenge)


def test_zero_admitted_inventory_never_invents_a_final_page_authorization(
    adapter_evidence: dict[str, Any],
) -> None:
    authenticated = replace(
        adapter_evidence["authenticated"],
        admitted_example_count=0,
        label_unavailable_count=adapter_evidence["authenticated"].total_profiled_samples,
    )

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="ZERO_ADMITTED_INVENTORY_FORBIDDEN",
    ):
        prepare_profiled_optimizer_external_completion_request_v1(
            authenticated_manifest=authenticated,
            completion=adapter_evidence["completion"],
            final_page=adapter_evidence["final_page"],
            completion_staging_store=adapter_evidence["staging_store"],
            manifest_head_anchor=_head_anchor(adapter_evidence),
            authorization_namespace=AUTHORIZATION_NAMESPACE,
            expected_authorization_sequence=0,
            expected_previous_authorization_event_sha256=(
                PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
            ),
            authorization_challenge=FIXED_CHALLENGE,
        )


def test_head_namespace_event_and_sequence_are_not_caller_substitutable(
    adapter_evidence: dict[str, Any],
) -> None:
    anchor = _head_anchor(adapter_evidence)
    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="HEAD_OR_STAGING_BINDING_INVALID",
    ):
        _prepared(adapter_evidence, namespace="unit/another-namespace")
    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="HEAD_OR_STAGING_BINDING_INVALID",
    ):
        _prepared(
            adapter_evidence,
            head_anchor=replace(
                anchor,
                event_sha256=hashlib.sha256(b"wrong-head-event").hexdigest(),
            ),
        )
    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="HEAD_OR_STAGING_BINDING_INVALID",
    ):
        _prepared(
            adapter_evidence,
            head_anchor=replace(
                anchor,
                expected_sequence=1,
                anchored_sequence=2,
            ),
        )


def test_claim_epoch_and_consumer_lane_must_match_exact_local_event_bytes(
    adapter_evidence: dict[str, Any],
) -> None:
    forged_epoch = hashlib.sha256(b"forged-completion-epoch").hexdigest()
    cases = (
        (
            replace(adapter_evidence["completion"], epoch_id=forged_epoch),
            replace(adapter_evidence["final_page"], epoch_id=forged_epoch),
        ),
        (
            replace(
                adapter_evidence["completion"],
                consumer_lane="forged/profiled-consumer-lane",
            ),
            adapter_evidence["final_page"],
        ),
    )

    for completion, final_page in cases:
        with pytest.raises(
            ProfiledOptimizerExternalCompletionRequestV1Error,
            match="LOCAL_EVENT_BINDING_INVALID",
        ):
            prepare_profiled_optimizer_external_completion_request_v1(
                authenticated_manifest=adapter_evidence["authenticated"],
                completion=completion,
                final_page=final_page,
                completion_staging_store=adapter_evidence["staging_store"],
                manifest_head_anchor=_head_anchor(adapter_evidence),
                authorization_namespace=AUTHORIZATION_NAMESPACE,
                expected_authorization_sequence=0,
                expected_previous_authorization_event_sha256=(
                    PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_GENESIS_SHA256
                ),
                authorization_challenge=FIXED_CHALLENGE,
            )


@pytest.mark.parametrize(
    ("event_name", "field_name"),
    (
        ("completion", "head_revision"),
        ("completion", "consumed_entry_count"),
        ("final_page", "page_sequence"),
        ("final_page", "cumulative_scanned_entry_count"),
    ),
)
def test_raw_local_event_boolean_cannot_alias_an_integer_binding(
    adapter_evidence: dict[str, Any],
    event_name: str,
    field_name: str,
) -> None:
    prepared = _prepared(adapter_evidence)
    completion_material = json.loads(prepared.completion_event_bytes)
    final_page_material = json.loads(prepared.final_page_receipt_event_bytes)
    target = completion_material if event_name == "completion" else final_page_material
    assert target[field_name] == 1
    target[field_name] = True

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="LOCAL_EVENT_CONTRACT_INVALID",
    ):
        request_module._validate_local_event_material(
            completion_bytes=_canonical(completion_material),
            final_page_bytes=_canonical(final_page_material),
            claim_template=json.loads(prepared.authorization_claim_template),
        )


def test_response_replay_under_new_challenge_fails(
    adapter_evidence: dict[str, Any],
) -> None:
    original = _prepared(adapter_evidence)
    envelope = _signed_envelope(original)
    changed = _prepared(adapter_evidence, challenge=hashlib.sha256(b"new-challenge").digest())

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="AUTHORIZATION_BINDING_MISMATCH",
    ):
        verify_profiled_optimizer_external_completion_response_v1(
            prepared=changed,
            authorization_envelope_bytes=envelope,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )


def test_response_replay_under_new_predecessor_fails(
    adapter_evidence: dict[str, Any],
) -> None:
    original = _prepared(adapter_evidence)
    envelope = _signed_envelope(original)
    changed = _prepared(
        adapter_evidence,
        expected_sequence=1,
        predecessor=hashlib.sha256(b"anchored-authorization-one").hexdigest(),
    )

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="AUTHORIZATION_BINDING_MISMATCH",
    ):
        verify_profiled_optimizer_external_completion_response_v1(
            prepared=changed,
            authorization_envelope_bytes=envelope,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )


def test_signed_boolean_cannot_alias_requested_authorization_sequence(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared = _prepared(adapter_evidence)
    unsigned = {
        **json.loads(prepared.authorization_claim_template),
        "accepted_at": adapter_evidence["accepted_at"],
    }
    unsigned["authorization_sequence"] = True
    payload = PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR + _canonical(
        unsigned
    )
    envelope = _canonical(
        {
            **unsigned,
            "signature_hex": admission_support._private_key().sign(payload).hex(),
        }
    )

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="AUTHORIZATION_BINDING_MISMATCH",
    ):
        verify_profiled_optimizer_external_completion_response_v1(
            prepared=prepared,
            authorization_envelope_bytes=envelope,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )


def test_response_clock_must_follow_observation_and_final_page(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared = _prepared(adapter_evidence)
    envelope = _signed_envelope(
        prepared,
        accepted_at=adapter_evidence["final_page"].verified_at,
    )

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="PRECEDES_FULL_CONSUMPTION",
    ):
        verify_profiled_optimizer_external_completion_response_v1(
            prepared=prepared,
            authorization_envelope_bytes=envelope,
            witness_public_key_bytes=adapter_evidence["public_key"],
        )


def test_changed_key_and_signature_fail_closed(adapter_evidence: dict[str, Any]) -> None:
    prepared = _prepared(adapter_evidence)
    envelope = _signed_envelope(prepared)
    wrong_private = Ed25519PrivateKey.generate()
    wrong_public = admission_support._public_key_bytes(wrong_private)

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="PUBLIC_KEY_FINGERPRINT_MISMATCH",
    ):
        verify_profiled_optimizer_external_completion_response_v1(
            prepared=prepared,
            authorization_envelope_bytes=envelope,
            witness_public_key_bytes=wrong_public,
        )
    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="SIGNATURE_UNVERIFIED",
    ):
        verify_profiled_optimizer_external_completion_response_v1(
            prepared=prepared,
            authorization_envelope_bytes=_signed_envelope(
                prepared,
                private_key=wrong_private,
            ),
            witness_public_key_bytes=adapter_evidence["public_key"],
        )


def test_prepared_request_rejects_noncanonical_and_float_tamper(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared = _prepared(adapter_evidence)
    noncanonical = prepared.request_bytes + b" "
    with pytest.raises(ProfiledOptimizerExternalCompletionRequestV1Error):
        replace(
            prepared,
            request_bytes=noncanonical,
            request_byte_count=len(noncanonical),
            request_sha256=hashlib.sha256(noncanonical).hexdigest(),
        )
    material = json.loads(prepared.request_bytes)
    material["expected_authorization_sequence"] = 0.0
    float_bytes = json.dumps(material, separators=(",", ":"), sort_keys=True).encode("ascii")
    with pytest.raises(ProfiledOptimizerExternalCompletionRequestV1Error):
        replace(
            prepared,
            request_bytes=float_bytes,
            request_byte_count=len(float_bytes),
            request_sha256=hashlib.sha256(float_bytes).hexdigest(),
        )


def test_parser_rejects_semantic_non_ascii_hidden_in_canonical_escape() -> None:
    with pytest.raises(ProfiledOptimizerExternalCompletionRequestV1Error):
        request_module._parse_exact_json(
            b'{"value":"\\u00e9"}',
            reason="TEST_NON_ASCII_MUST_FAIL",
        )


def test_successor_request_rejects_boolean_wire_sequence(
    adapter_evidence: dict[str, Any],
) -> None:
    prepared = _prepared(
        adapter_evidence,
        expected_sequence=1,
        predecessor=hashlib.sha256(b"anchored-completion-authorization-one").hexdigest(),
    )
    material = json.loads(prepared.request_bytes)
    material["expected_authorization_sequence"] = True
    base = {name: value for name, value in material.items() if name != "idempotency_key"}
    idempotency_key = hashlib.sha256(
        PROFILED_OPTIMIZER_COMPLETION_REQUEST_DOMAIN.encode("ascii")
        + b"\0"
        + _canonical(base)
    ).hexdigest()
    request_bytes = _canonical({**base, "idempotency_key": idempotency_key})

    with pytest.raises(
        ProfiledOptimizerExternalCompletionRequestV1Error,
        match="PREPARED_REQUEST_BINDING_INVALID",
    ):
        replace(
            prepared,
            idempotency_key=idempotency_key,
            request_bytes=request_bytes,
            request_byte_count=len(request_bytes),
            request_sha256=hashlib.sha256(request_bytes).hexdigest(),
        )


def test_request_module_has_no_network_private_key_or_runtime_authority_calls() -> None:
    module_path = (
        Path(__file__).resolve().parents[6]
        / "v2/backend/app/services/native_trainer/"
        "profiled_optimizer_external_completion_request_v1.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "Ed25519PrivateKey" not in source
    assert "httpx" not in source
    assert "optimizer.step" not in source
    assert "torch.save" not in source
    assert "submit_order" not in source
