from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from v2.backend.app.services.native_trainer import (
    profiled_training_observation_manifest_v1 as manifest_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    AUTHENTICATED_PROFILED_OPTIMIZER_ADMISSION_V1_SCHEMA_VERSION,
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR,
    AuthenticatedProfiledOptimizerAdmissionV1Error,
    admit_authenticated_profiled_optimizer_candidate_v1,
    profiled_optimizer_external_completion_signing_payload_v1,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_INPUT_COUNT,
    LOGICAL_PROFILE_SELECTION_MASK,
    LOGICAL_PROFILE_SELECTION_MASK_SHA256,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    authenticate_profiled_training_observation_manifest_v1,
    build_profiled_training_observation_manifest_v1,
    read_profiled_training_observation_page_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_head_v1 as head_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_v1 as manifest_support,
)

WITNESS_ID = "unit/external-profiled-optimizer-witness-v1"
WITNESS_NAMESPACE = "unit/profiled-optimizer-completion"
WITNESS_SEQUENCE = 17
PREVIOUS_WITNESS_EVENT_SHA256 = hashlib.sha256(b"external-witness-event-16").hexdigest()
AUTHORIZATION_CHALLENGE = hashlib.sha256(b"adapter-one-time-challenge-v1").digest()
_WITNESS_PRIVATE_BYTES = hashlib.sha256(b"external-witness-private-test-key-v1").digest()


def _private_key(seed: bytes = _WITNESS_PRIVATE_BYTES) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_key_bytes(private_key: Ed25519PrivateKey) -> bytes:
    return private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


@pytest.fixture(scope="module")
def adapter_evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("authenticated-profiled-optimizer-admission")
    base = base_support._build_evidence(root / "base")
    source_root = root / "sources"
    source_root.mkdir()
    ledger, archive, observation, cost_root = manifest_support._setup_sources(
        source_root,
        base,
    )
    fixture_base = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(
        UTC
    )
    factory_wall_clock = fixture_base + timedelta(minutes=1)
    final_page_verified_at = (
        (fixture_base + timedelta(minutes=2))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    accepted_at = (
        (fixture_base + timedelta(minutes=3))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        manifest_module,
        "_factory_wall_clock_now",
        lambda: factory_wall_clock,
    )
    monkeypatch.setattr(head_support, "VERIFIED_AT", final_page_verified_at)
    try:
        built = build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=(root / "manifests").absolute(),
            training_observed_at=observation,
            auth_key_id=manifest_support.AUTH_KEY_ID,
            hmac_key=manifest_support.AUTH_KEY,
        )
        authenticated = authenticate_profiled_training_observation_manifest_v1(
            manifest_path=built.manifest_path,
            hmac_key=manifest_support.AUTH_KEY,
            expected_auth_key_id=manifest_support.AUTH_KEY_ID,
            expected_manifest_id=built.manifest_id,
            expected_observation_time=built.observation_time,
        )
        staging_store = ImmutableSourcePayloadStore((root / "completion-staging").absolute())
        _head, _epoch, final_page, completion = head_support._consume(
            build=built,
            ledger=ledger,
            archive=archive,
            store=staging_store,
        )
        assert final_page is not None
        page = read_profiled_training_observation_page_v1(
            manifest_path=built.manifest_path,
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            hmac_key=manifest_support.AUTH_KEY,
            expected_auth_key_id=manifest_support.AUTH_KEY_ID,
            expected_manifest_id=built.manifest_id,
            expected_observation_time=built.observation_time,
            limit=1,
        )
        assert len(page.examples) == 1
        private_key = _private_key()
        public_key = _public_key_bytes(private_key)
        public_key_sha256 = hashlib.sha256(public_key).hexdigest()
        signing_payload = profiled_optimizer_external_completion_signing_payload_v1(
            authenticated_manifest=authenticated,
            completion=completion,
            final_page=final_page,
            witness_id=WITNESS_ID,
            namespace=WITNESS_NAMESPACE,
            witness_public_key_sha256=public_key_sha256,
            authorization_sequence=WITNESS_SEQUENCE,
            previous_authorization_event_sha256=PREVIOUS_WITNESS_EVENT_SHA256,
            authorization_challenge=AUTHORIZATION_CHALLENGE,
            accepted_at=accepted_at,
        )
        unsigned = json.loads(
            signing_payload[len(PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR) :]
        )
        envelope = _canonical(
            {
                **unsigned,
                "signature_hex": private_key.sign(signing_payload).hex(),
            }
        )
        yield {
            "ledger": ledger,
            "cost_root": cost_root,
            "built": built,
            "authenticated": authenticated,
            "staging_store": staging_store,
            "final_page": final_page,
            "completion": completion,
            "candidate": page.examples[0],
            "public_key": public_key,
            "public_key_sha256": public_key_sha256,
            "signing_payload": signing_payload,
            "envelope": envelope,
            "accepted_at": accepted_at,
        }
    finally:
        monkeypatch.undo()


def _admit(
    evidence: dict[str, Any],
    *,
    candidate: Any | None = None,
    envelope: bytes | None = None,
    public_key: bytes | None = None,
    public_key_sha256: str | None = None,
    challenge: bytes = AUTHORIZATION_CHALLENGE,
) -> Any:
    built = evidence["built"]
    return admit_authenticated_profiled_optimizer_candidate_v1(
        candidate=evidence["candidate"] if candidate is None else candidate,
        manifest_path=built.manifest_path,
        ledger=evidence["ledger"],
        trusted_immutable_cost_store_root=evidence["cost_root"],
        manifest_hmac_key=manifest_support.AUTH_KEY,
        manifest_auth_key_id=manifest_support.AUTH_KEY_ID,
        expected_manifest_id=built.manifest_id,
        expected_observation_time=built.observation_time,
        local_completion=evidence["completion"],
        completion_staging_store=evidence["staging_store"],
        epoch_hmac_key=head_support.EPOCH_KEY,
        epoch_auth_key_id=head_support.EPOCH_KEY_ID,
        external_authorization_envelope=(evidence["envelope"] if envelope is None else envelope),
        expected_witness_id=WITNESS_ID,
        expected_witness_namespace=WITNESS_NAMESPACE,
        witness_public_key_bytes=(evidence["public_key"] if public_key is None else public_key),
        expected_witness_public_key_sha256=(
            evidence["public_key_sha256"] if public_key_sha256 is None else public_key_sha256
        ),
        expected_witness_sequence=WITNESS_SEQUENCE,
        expected_previous_witness_event_sha256=PREVIOUS_WITNESS_EVENT_SHA256,
        authorization_challenge=challenge,
    )


def _replace_trust(candidate: Any, **updates: Any) -> Any:
    example = candidate.training_example
    trust = {**example.trust_row, **updates}
    changed_example = replace(
        example,
        trust_row=trust,
        label_available_at=trust.get("label_available_at"),
    )
    return replace(candidate, training_example=changed_example)


def test_valid_externally_witnessed_fixture_yields_typed_supervised_input_only(
    adapter_evidence: dict[str, Any],
) -> None:
    admitted = _admit(adapter_evidence)

    assert admitted.schema_version == AUTHENTICATED_PROFILED_OPTIMIZER_ADMISSION_V1_SCHEMA_VERSION
    assert admitted.manifest_id == adapter_evidence["built"].manifest_id
    assert admitted.manifest_metadata_sha256 == adapter_evidence["authenticated"].metadata_sha256
    assert (
        admitted.manifest_ordered_entry_identities_sha256
        == adapter_evidence["authenticated"].ordered_entry_identities_sha256
    )
    assert (
        admitted.completion_ordered_page_root_sha256
        == adapter_evidence["completion"].ordered_page_root_sha256
    )
    assert admitted.manifest_total_profiled_samples == 1
    assert admitted.manifest_admitted_example_count == 1
    assert admitted.manifest_label_unavailable_count == 0
    assert admitted.completion_consumed_entry_count == 1
    assert admitted.completion_admitted_entry_count == 1
    assert admitted.completion_label_unavailable_count == 0
    assert admitted.witness_namespace == WITNESS_NAMESPACE
    assert admitted.witness_public_key_sha256 == adapter_evidence["public_key_sha256"]
    assert admitted.witness_previous_event_sha256 == PREVIOUS_WITNESS_EVENT_SHA256
    assert admitted.witness_accepted_at == adapter_evidence["accepted_at"]
    assert admitted.sample_identity_sha256 == adapter_evidence["candidate"].sample_identity_sha256
    assert admitted.label_binding_sha256 == adapter_evidence["candidate"].label_binding_sha256
    assert admitted.tensor_binding_sha256 == adapter_evidence["candidate"].tensor_binding_sha256
    assert admitted.logical_profile_selection_mask == LOGICAL_PROFILE_SELECTION_MASK
    assert admitted.logical_profile_selection_mask_sha256 == LOGICAL_PROFILE_SELECTION_MASK_SHA256
    assert admitted.projection_schema_version == PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION
    assert (
        admitted.projection_implementation_sha256
        == PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
    )
    assert (
        admitted.projection_configuration_sha256
        == PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256
    )
    assert len(admitted.model_input) == LOGICAL_MODEL_INPUT_COUNT
    assert admitted.supervised_target.label_binding_sha256 == admitted.label_binding_sha256
    assert admitted.supervised_target.action_index in {0, 1, 2}
    assert admitted.supervised_target.canonical_finalized_label_bound is True
    assert admitted.supervised_target.future_labels_excluded_from_feature_tensor is True
    assert admitted.profiled_optimizer_admission_validated is True
    assert admitted.outcome_supervised_objective_eligible is True
    assert admitted.behavior_receipt_bound is False
    assert admitted.ppo_behavior_policy_terms_enabled is False
    ordered_feature_clocks = tuple(
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        for value in (
            admitted.model_feature_cutoff,
            admitted.source_feature_available_at,
            admitted.decision_feature_available_at,
            admitted.feature_generated_at,
            admitted.training_record_generated_at,
            admitted.decision_time,
            admitted.trainer_sample_available_at,
            admitted.observation_time,
        )
    )
    assert ordered_feature_clocks == tuple(sorted(ordered_feature_clocks))
    assert admitted.record_wide_evidence_cutoff != admitted.trainer_sample_available_at
    assert all(
        value is False
        for value in (
            admitted.optimizer_execution_authorized,
            admitted.checkpoint_write_authorized,
            admitted.model_write_authorized,
            admitted.prediction_authorized,
            admitted.paper_trading_authorized,
            admitted.live_execution_authorized,
            admitted.order_submission_authorized,
            admitted.execution_authorized,
            admitted.runtime_wired,
        )
    )


def test_local_completion_without_external_signature_cannot_self_authorize(
    adapter_evidence: dict[str, Any],
) -> None:
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_BYTES_INVALID",
    ):
        _admit(adapter_evidence, envelope=b"")


def test_signature_from_unpinned_private_key_is_rejected(
    adapter_evidence: dict[str, Any],
) -> None:
    wrong_private = _private_key(hashlib.sha256(b"wrong-witness-private-key").digest())
    unsigned = json.loads(
        adapter_evidence["signing_payload"][
            len(PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR) :
        ]
    )
    forged = _canonical(
        {
            **unsigned,
            "signature_hex": wrong_private.sign(adapter_evidence["signing_payload"]).hex(),
        }
    )

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_SIGNATURE_UNVERIFIED",
    ):
        _admit(adapter_evidence, envelope=forged)


def test_signed_authorization_cannot_be_replayed_under_a_different_challenge(
    adapter_evidence: dict[str, Any],
) -> None:
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_BINDING_MISMATCH",
    ):
        _admit(
            adapter_evidence,
            challenge=hashlib.sha256(b"different-one-time-challenge").digest(),
        )


def test_signed_boolean_cannot_alias_an_integer_manifest_binding(
    adapter_evidence: dict[str, Any],
) -> None:
    signing_payload = adapter_evidence["signing_payload"]
    unsigned = json.loads(
        signing_payload[
            len(PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR) :
        ]
    )
    assert unsigned["manifest_binding"]["total_profiled_samples"] == 1
    unsigned["manifest_binding"]["total_profiled_samples"] = True
    payload = PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR + _canonical(
        unsigned
    )
    forged = _canonical(
        {
            **unsigned,
            "signature_hex": _private_key().sign(payload).hex(),
        }
    )

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_BINDING_MISMATCH",
    ):
        _admit(adapter_evidence, envelope=forged)


def test_signed_envelope_with_altered_manifest_binding_is_rejected(
    adapter_evidence: dict[str, Any],
) -> None:
    altered = json.loads(adapter_evidence["envelope"])
    altered["manifest_binding"]["manifest_id"] = hashlib.sha256(b"different-manifest").hexdigest()
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_BINDING_MISMATCH",
    ):
        _admit(adapter_evidence, envelope=_canonical(altered))


@pytest.mark.parametrize(
    "identity_field",
    ("sample_identity_sha256", "label_binding_sha256", "tensor_binding_sha256"),
)
def test_altered_sample_label_or_tensor_identity_is_rejected(
    adapter_evidence: dict[str, Any],
    identity_field: str,
) -> None:
    altered = replace(
        adapter_evidence["candidate"],
        **{identity_field: hashlib.sha256(identity_field.encode("ascii")).hexdigest()},
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_EXAMPLE_IDENTITY_BINDING_INVALID",
    ):
        _admit(adapter_evidence, candidate=altered)


def test_altered_tensor_values_fail_direct_manifest_reopen_comparison(
    adapter_evidence: dict[str, Any],
) -> None:
    candidate = adapter_evidence["candidate"]
    tensor = candidate.training_example.tensor
    altered_tensor = replace(tensor, values=(tensor.values[0] + 1.0, *tensor.values[1:]))
    altered = replace(
        candidate,
        training_example=replace(candidate.training_example, tensor=altered_tensor),
    )

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_CANDIDATE_DIRECT_IDENTITY_MISMATCH",
    ):
        _admit(adapter_evidence, candidate=altered)


def test_altered_label_value_fails_direct_manifest_reopen_comparison(
    adapter_evidence: dict[str, Any],
) -> None:
    candidate = adapter_evidence["candidate"]
    altered = replace(
        candidate,
        training_example=replace(
            candidate.training_example,
            label_expected_move_after_cost_bps=(
                candidate.training_example.label_expected_move_after_cost_bps + 1.0
            ),
        ),
    )

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_CANDIDATE_DIRECT_IDENTITY_MISMATCH",
    ):
        _admit(adapter_evidence, candidate=altered)


def test_generated_and_postcommit_clock_collision_is_rejected(
    adapter_evidence: dict[str, Any],
) -> None:
    candidate = adapter_evidence["candidate"]
    postcommit = candidate.training_example.trust_row["trainer_sample_available_at"]
    altered = _replace_trust(candidate, record_generated_at=postcommit)

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_TRAINING_RECORD_AFTER_DECISION",
    ):
        _admit(adapter_evidence, candidate=altered)


def test_postcommit_available_at_cannot_be_relabelled_as_feature_availability(
    adapter_evidence: dict[str, Any],
) -> None:
    candidate = adapter_evidence["candidate"]
    altered = _replace_trust(
        candidate,
        available_at=candidate.training_example.trust_row["record_generated_at"],
        available_at_semantics="DECISION_TIME_FEATURE_AVAILABLE_AT",
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_LEGACY_AVAILABLE_AT_SEMANTICS_INVALID",
    ):
        _admit(adapter_evidence, candidate=altered)


def test_future_label_beyond_fixed_observation_is_rejected(
    adapter_evidence: dict[str, Any],
) -> None:
    candidate = adapter_evidence["candidate"]
    observation = datetime.fromisoformat(
        adapter_evidence["built"].observation_time.replace("Z", "+00:00")
    )
    future = (
        (observation + timedelta(seconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    altered = _replace_trust(
        candidate,
        label_available_at=future,
        outcome_available_at=future,
    )

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_LABEL_AVAILABILITY_ORDER_INVALID",
    ):
        _admit(adapter_evidence, candidate=altered)


def test_unfinished_label_claim_is_rejected(
    adapter_evidence: dict[str, Any],
) -> None:
    altered = _replace_trust(
        adapter_evidence["candidate"],
        candle_closed_confirmed=False,
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_TRUST_ROW_CONTRACT_INVALID",
    ):
        _admit(adapter_evidence, candidate=altered)


def test_behavior_policy_terms_remain_disabled_without_genuine_receipt_contract(
    adapter_evidence: dict[str, Any],
) -> None:
    candidate = adapter_evidence["candidate"]
    altered_example = replace(
        candidate.training_example,
        behavior_action_index=1,
        behavior_action="long",
    )
    altered = replace(candidate, training_example=altered_example)

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_GENUINE_BEHAVIOR_RECEIPT_CONTRACT_UNIMPLEMENTED",
    ):
        _admit(adapter_evidence, candidate=altered)
