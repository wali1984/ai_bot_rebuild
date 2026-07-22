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
    authenticated_profiled_optimizer_admission_v1 as admission_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_manifest_v1 as manifest_module,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    AUTHENTICATED_PROFILED_OPTIMIZER_ADMISSION_V1_SCHEMA_VERSION,
    PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR,
    AuthenticatedProfiledOptimizerAdmissionV1Error,
    admit_authenticated_profiled_optimizer_candidate_v1,
    admit_authenticated_profiled_optimizer_manifest_batch_v1,
    profiled_optimizer_external_completion_signing_payload_v1,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
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
    MAX_PROFILED_OBSERVATION_PAGE_ROWS,
    authenticate_profiled_training_observation_manifest_v1,
    build_profiled_training_observation_manifest_v1,
    read_profiled_training_observation_page_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_ledger_loader_v1 as loader_support,
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
    fixture_base = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
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


def _consume_all_manifest_pages(
    *,
    built: Any,
    authenticated: Any,
    ledger: DurableFeatureSnapshotLedger,
    archive: DurableCanonical5mLabelArchive,
    staging_store: ImmutableSourcePayloadStore,
    verified_at: str,
    page_size: int,
) -> tuple[Any, Any]:
    head = head_support._head(
        build=built,
        ledger=ledger,
        archive=archive,
        store=staging_store,
    )
    epoch = head_support.stage_profiled_training_observation_consumption_epoch_v1(
        head_candidate=head,
        staging_store=staging_store,
        consumer_lane=head_support.CONSUMER_LANE,
        page_size=page_size,
        manifest_hmac_key=manifest_support.AUTH_KEY,
        manifest_auth_key_id=manifest_support.AUTH_KEY_ID,
        head_hmac_key=head_support.HEAD_KEY,
        head_auth_key_id=head_support.HEAD_KEY_ID,
        epoch_hmac_key=head_support.EPOCH_KEY,
        epoch_auth_key_id=head_support.EPOCH_KEY_ID,
    )
    final_page = None
    while final_page is None or final_page.has_more_manifest_entries:
        final_page = head_support.stage_profiled_training_observation_page_receipt_v1(
            epoch=epoch,
            authenticated_manifest=authenticated,
            staging_store=staging_store,
            verified_at=verified_at,
            manifest_hmac_key=manifest_support.AUTH_KEY,
            manifest_auth_key_id=manifest_support.AUTH_KEY_ID,
            head_hmac_key=head_support.HEAD_KEY,
            head_auth_key_id=head_support.HEAD_KEY_ID,
            epoch_hmac_key=head_support.EPOCH_KEY,
            epoch_auth_key_id=head_support.EPOCH_KEY_ID,
            previous_page_receipt=final_page,
        )
    completion = head_support.stage_profiled_training_observation_completion_candidate_v1(
        epoch=epoch,
        staging_store=staging_store,
        epoch_hmac_key=head_support.EPOCH_KEY,
        epoch_auth_key_id=head_support.EPOCH_KEY_ID,
        final_page_receipt=final_page,
    )
    return final_page, completion


@pytest.fixture(scope="module")
def batch_adapter_evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[int, dict[str, Any]]:
    root = tmp_path_factory.mktemp("authenticated-profiled-optimizer-batch")
    ledger = DurableFeatureSnapshotLedger(root / "feature-ledger.sqlite3")
    cost_root = (root / "cost-cas").absolute()
    parents = []
    for ordinal in range(8):
        if ordinal == 6:
            with pytest.MonkeyPatch.context() as symbol_patch:
                symbol_patch.setattr(base_support.capture_support, "SYMBOL", "ETHUSDT")
                parent = base_support._build_evidence(root / f"base-{ordinal}").record
        else:
            parent = base_support._build_evidence(root / f"base-{ordinal}").record
        parents.append(parent)
    pairs = [
        (
            parent,
            loader_support._child_record(
                parent,
                cost_store_root=cost_root,
                original_tensor_suffix=f"-batch-{ordinal}",
            ),
        )
        for ordinal, parent in enumerate(parents)
    ]
    parent_envelope = parents[0]["frozen_envelope"]
    feature_values = dict(
        zip(
            parent_envelope["ordered_feature_names"],
            parent_envelope["feature_values"],
            strict=True,
        )
    )
    archive = DurableCanonical5mLabelArchive(root / "labels.sqlite3")
    archive.append_candles(
        manifest_support._label_candles(
            decision_time=parent_envelope["tensor_decision_time"],
            entry_price=float(feature_values["close"]),
        )
    )
    observation_clock = max(
        datetime.now(tz=UTC) + timedelta(minutes=10),
        datetime(2026, 7, 23, tzinfo=UTC),
    )
    observation = observation_clock.isoformat(timespec="microseconds").replace("+00:00", "Z")
    factory_wall_clock = observation_clock + timedelta(minutes=1)
    final_page_verified_at = (
        (observation_clock + timedelta(minutes=2))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    accepted_at = (
        (observation_clock + timedelta(minutes=3))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    private_key = _private_key()
    public_key = _public_key_bytes(private_key)
    public_key_sha256 = hashlib.sha256(public_key).hexdigest()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        manifest_module,
        "_factory_wall_clock_now",
        lambda: factory_wall_clock,
    )
    evidences: dict[int, dict[str, Any]] = {}
    appended = 0
    try:
        for target_count in (1, 3, 6, 8):
            new_records = [record for pair in pairs[appended:target_count] for record in pair]
            result = loader_support._append_after_latest_decision(ledger, new_records)
            assert result.inserted_rows == 2 * (target_count - appended)
            appended = target_count
            built = build_profiled_training_observation_manifest_v1(
                ledger=ledger,
                trusted_immutable_cost_store_root=cost_root,
                label_archive=archive,
                manifest_root=(root / f"manifests-{target_count}").absolute(),
                training_observed_at=observation,
                auth_key_id=manifest_support.AUTH_KEY_ID,
                hmac_key=manifest_support.AUTH_KEY,
            )
            expected_unavailable = 1 if target_count == 8 else 0
            expected_admitted = target_count - expected_unavailable
            assert built.total_profiled_samples == target_count
            assert built.admitted_examples == expected_admitted
            assert built.label_unavailable_samples == expected_unavailable
            authenticated = authenticate_profiled_training_observation_manifest_v1(
                manifest_path=built.manifest_path,
                hmac_key=manifest_support.AUTH_KEY,
                expected_auth_key_id=manifest_support.AUTH_KEY_ID,
                expected_manifest_id=built.manifest_id,
                expected_observation_time=built.observation_time,
            )
            staging_store = ImmutableSourcePayloadStore(
                (root / f"completion-staging-{target_count}").absolute()
            )
            final_page, completion = _consume_all_manifest_pages(
                built=built,
                authenticated=authenticated,
                ledger=ledger,
                archive=archive,
                staging_store=staging_store,
                verified_at=final_page_verified_at,
                page_size=2,
            )
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
                signing_payload[
                    len(PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR) :
                ]
            )
            envelope = _canonical(
                {
                    **unsigned,
                    "signature_hex": private_key.sign(signing_payload).hex(),
                }
            )
            page = read_profiled_training_observation_page_v1(
                manifest_path=built.manifest_path,
                ledger=ledger,
                trusted_immutable_cost_store_root=cost_root,
                hmac_key=manifest_support.AUTH_KEY,
                expected_auth_key_id=manifest_support.AUTH_KEY_ID,
                expected_manifest_id=built.manifest_id,
                expected_observation_time=built.observation_time,
                limit=target_count,
            )
            assert len(page.examples) == expected_admitted
            evidences[target_count] = {
                "ledger": ledger,
                "cost_root": cost_root,
                "archive": archive,
                "built": built,
                "authenticated": authenticated,
                "staging_store": staging_store,
                "final_page": final_page,
                "completion": completion,
                "candidates": page.examples,
                "public_key": public_key,
                "public_key_sha256": public_key_sha256,
                "envelope": envelope,
                "accepted_at": accepted_at,
            }
        yield evidences
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


def _batch_admit(
    evidence: dict[str, Any],
    *,
    envelope: bytes | None = None,
    page_limit: int = 2,
) -> Any:
    built = evidence["built"]
    return admit_authenticated_profiled_optimizer_manifest_batch_v1(
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
        witness_public_key_bytes=evidence["public_key"],
        expected_witness_public_key_sha256=evidence["public_key_sha256"],
        expected_witness_sequence=WITNESS_SEQUENCE,
        expected_previous_witness_event_sha256=PREVIOUS_WITNESS_EVENT_SHA256,
        authorization_challenge=AUTHORIZATION_CHALLENGE,
        page_limit=page_limit,
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


def test_local_research_validator_proves_pit_lineage_without_granting_authority(
    adapter_evidence: dict[str, Any],
) -> None:
    validated = (
        admission_module.validate_profiled_observation_example_for_local_research_v1(
            ledger=adapter_evidence["ledger"],
            candidate=adapter_evidence["candidate"],
            observation_time=adapter_evidence["built"].observation_time,
        )
    )

    assert validated.ordinal == adapter_evidence["candidate"].ordinal
    assert validated.sample_identity_sha256 == (
        adapter_evidence["candidate"].sample_identity_sha256
    )
    assert validated.model_feature_cutoff <= validated.source_feature_available_at
    assert validated.source_feature_available_at <= (
        validated.decision_feature_available_at
    )
    assert validated.decision_feature_available_at <= validated.feature_generated_at
    assert validated.feature_generated_at <= validated.training_record_generated_at
    assert validated.training_record_generated_at <= validated.decision_time
    assert validated.decision_time < validated.trainer_sample_available_at
    assert validated.decision_time < validated.label_available_at
    assert all(
        getattr(validated, name) is False
        for name in (
            "optimizer_execution_authorized",
            "checkpoint_write_authorized",
            "prediction_authorized",
            "serving_authorized",
            "paper_trading_authorized",
            "live_execution_authorized",
            "order_submission_authorized",
            "runtime_wired",
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
        signing_payload[len(PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR) :]
    )
    assert unsigned["manifest_binding"]["total_profiled_samples"] == 1
    unsigned["manifest_binding"]["total_profiled_samples"] = True
    payload = PROFILED_OPTIMIZER_EXTERNAL_COMPLETION_AUTHORIZATION_SEPARATOR + _canonical(unsigned)
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


def test_batch_admission_is_field_exact_equivalent_to_single_row_admission(
    batch_adapter_evidence: dict[int, dict[str, Any]],
) -> None:
    evidence = batch_adapter_evidence[3]
    batch = _batch_admit(evidence, page_limit=2)
    singles = tuple(
        _admit({**evidence, "candidate": candidate}) for candidate in evidence["candidates"]
    )

    assert batch == singles
    assert tuple(item.ordinal for item in batch) == (1, 2, 3)


def test_batch_walks_each_bounded_page_once_and_reconciles_exact_inventory(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = batch_adapter_evidence[6]
    original_page_reader = admission_module.read_profiled_training_observation_page_v1
    page_calls: list[tuple[int, int]] = []

    def counted_page_reader(**kwargs: Any) -> Any:
        page_calls.append((kwargs["after_ordinal"], kwargs["limit"]))
        return original_page_reader(**kwargs)

    monkeypatch.setattr(
        admission_module,
        "read_profiled_training_observation_page_v1",
        counted_page_reader,
    )
    batch = _batch_admit(evidence, page_limit=2)

    assert page_calls == [(0, 2), (2, 2), (4, 2)]
    assert len(batch) == evidence["built"].admitted_examples == 6
    assert tuple(item.ordinal for item in batch) == (1, 2, 3, 4, 5, 6)
    assert tuple(item.sample_identity_sha256 for item in batch) == tuple(
        candidate.sample_identity_sha256 for candidate in evidence["candidates"]
    )
    assert all(item.manifest_total_profiled_samples == 6 for item in batch)
    assert all(item.manifest_admitted_example_count == 6 for item in batch)
    assert all(item.manifest_label_unavailable_count == 0 for item in batch)
    assert all(item.completion_consumed_entry_count == 6 for item in batch)
    assert all(item.completion_admitted_entry_count == 6 for item in batch)
    assert all(item.completion_label_unavailable_count == 0 for item in batch)
    assert all(
        value is False
        for item in batch
        for value in (
            item.optimizer_execution_authorized,
            item.checkpoint_write_authorized,
            item.model_write_authorized,
            item.prediction_authorized,
            item.paper_trading_authorized,
            item.live_execution_authorized,
            item.order_submission_authorized,
            item.execution_authorized,
            item.runtime_wired,
        )
    )


def test_batch_advances_across_real_label_unavailable_row_without_admitting_it(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = batch_adapter_evidence[8]
    original_page_reader = admission_module.read_profiled_training_observation_page_v1
    pages: list[tuple[int, int, int, tuple[int, ...]]] = []

    def counted_page_reader(**kwargs: Any) -> Any:
        page = original_page_reader(**kwargs)
        pages.append(
            (
                page.requested_after_ordinal,
                page.next_after_ordinal,
                page.label_unavailable_scanned,
                tuple(candidate.ordinal for candidate in page.examples),
            )
        )
        return page

    monkeypatch.setattr(
        admission_module,
        "read_profiled_training_observation_page_v1",
        counted_page_reader,
    )
    batch = _batch_admit(evidence, page_limit=2)

    assert pages == [
        (0, 2, 0, (1, 2)),
        (2, 4, 0, (3, 4)),
        (4, 6, 0, (5, 6)),
        (6, 8, 1, (8,)),
    ]
    assert tuple(item.ordinal for item in batch) == (1, 2, 3, 4, 5, 6, 8)
    assert all(item.manifest_total_profiled_samples == 8 for item in batch)
    assert all(item.manifest_admitted_example_count == 7 for item in batch)
    assert all(item.manifest_label_unavailable_count == 1 for item in batch)
    assert all(item.completion_consumed_entry_count == 8 for item in batch)
    assert all(item.completion_admitted_entry_count == 7 for item in batch)
    assert all(item.completion_label_unavailable_count == 1 for item in batch)


def test_batch_full_authentication_and_witness_verification_counts_are_constant(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_manifest_auth = admission_module.authenticate_profiled_training_observation_manifest_v1
    original_external_verify = admission_module._verify_external_authorization
    original_read_metadata = manifest_module._read_metadata
    original_complete_stream_verify = manifest_module._verify_complete_entry_stream
    original_full_sqlite_check = manifest_module._run_full_sqlite_check
    original_verify_entry_row = manifest_module._verify_entry_row
    counts = {
        "manifest_auth": 0,
        "external_verify": 0,
        "page_reads": 0,
        "complete_stream_verify": 0,
        "full_sqlite_check": 0,
        "entry_row_verify": 0,
    }
    metadata_read_modes: list[bool] = []

    def counted_manifest_auth(**kwargs: Any) -> Any:
        counts["manifest_auth"] += 1
        return original_manifest_auth(**kwargs)

    def counted_external_verify(**kwargs: Any) -> Any:
        counts["external_verify"] += 1
        return original_external_verify(**kwargs)

    def counted_read_metadata(*args: Any, **kwargs: Any) -> Any:
        metadata_read_modes.append(kwargs["full_database_check"])
        return original_read_metadata(*args, **kwargs)

    def counted_complete_stream_verify(*args: Any, **kwargs: Any) -> Any:
        counts["complete_stream_verify"] += 1
        return original_complete_stream_verify(*args, **kwargs)

    def counted_full_sqlite_check(*args: Any, **kwargs: Any) -> Any:
        counts["full_sqlite_check"] += 1
        return original_full_sqlite_check(*args, **kwargs)

    def counted_verify_entry_row(*args: Any, **kwargs: Any) -> Any:
        counts["entry_row_verify"] += 1
        return original_verify_entry_row(*args, **kwargs)

    original_page_reader = admission_module.read_profiled_training_observation_page_v1

    def counted_page_reader(**kwargs: Any) -> Any:
        counts["page_reads"] += 1
        return original_page_reader(**kwargs)

    monkeypatch.setattr(
        admission_module,
        "authenticate_profiled_training_observation_manifest_v1",
        counted_manifest_auth,
    )
    monkeypatch.setattr(
        admission_module,
        "_verify_external_authorization",
        counted_external_verify,
    )
    monkeypatch.setattr(
        admission_module,
        "read_profiled_training_observation_page_v1",
        counted_page_reader,
    )
    monkeypatch.setattr(manifest_module, "_read_metadata", counted_read_metadata)
    monkeypatch.setattr(
        manifest_module,
        "_verify_complete_entry_stream",
        counted_complete_stream_verify,
    )
    monkeypatch.setattr(
        manifest_module,
        "_run_full_sqlite_check",
        counted_full_sqlite_check,
    )
    monkeypatch.setattr(manifest_module, "_verify_entry_row", counted_verify_entry_row)

    observed: list[tuple[int, int, int, int, int, int, int, tuple[bool, ...]]] = []
    for row_count in (1, 3, 6):
        counts.update(
            manifest_auth=0,
            external_verify=0,
            page_reads=0,
            complete_stream_verify=0,
            full_sqlite_check=0,
            entry_row_verify=0,
        )
        metadata_read_modes.clear()
        result = _batch_admit(batch_adapter_evidence[row_count], page_limit=2)
        observed.append(
            (
                row_count,
                counts["manifest_auth"],
                counts["external_verify"],
                counts["page_reads"],
                counts["complete_stream_verify"],
                counts["full_sqlite_check"],
                counts["entry_row_verify"],
                tuple(metadata_read_modes),
            )
        )
        assert len(result) == row_count

    assert observed == [
        (1, 2, 1, 1, 2, 2, 3, (True, False, True)),
        (3, 2, 1, 2, 2, 2, 10, (True, False, False, True)),
        (6, 2, 1, 3, 2, 2, 20, (True, False, False, False, True)),
    ]


def test_batch_rejects_signed_envelope_tamper_before_returning_any_admission(
    batch_adapter_evidence: dict[int, dict[str, Any]],
) -> None:
    evidence = batch_adapter_evidence[3]
    altered = json.loads(evidence["envelope"])
    altered["manifest_binding"]["admitted_example_count"] = 2

    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_EXTERNAL_AUTHORIZATION_BINDING_MISMATCH",
    ):
        _batch_admit(evidence, envelope=_canonical(altered))


def test_batch_rejects_page_inventory_tamper(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = batch_adapter_evidence[3]
    original_page_reader = admission_module.read_profiled_training_observation_page_v1

    def tampered_page_reader(**kwargs: Any) -> Any:
        page = original_page_reader(**kwargs)
        if kwargs["after_ordinal"] == 0:
            object.__setattr__(page, "next_after_ordinal", page.next_after_ordinal + 1)
        return page

    monkeypatch.setattr(
        admission_module,
        "read_profiled_training_observation_page_v1",
        tampered_page_reader,
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_BATCH_PAGE_INVENTORY_INVALID",
    ):
        _batch_admit(evidence, page_limit=2)


def test_batch_rejects_aggregate_inventory_mismatch_after_late_page(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = batch_adapter_evidence[6]
    original_page_reader = admission_module.read_profiled_training_observation_page_v1

    def tampered_page_reader(**kwargs: Any) -> Any:
        page = original_page_reader(**kwargs)
        if kwargs["after_ordinal"] == 2:
            object.__setattr__(page, "examples", page.examples[1:])
            object.__setattr__(page, "label_unavailable_scanned", 1)
        return page

    monkeypatch.setattr(
        admission_module,
        "read_profiled_training_observation_page_v1",
        tampered_page_reader,
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_BATCH_FULL_INVENTORY_MISMATCH",
    ):
        _batch_admit(evidence, page_limit=2)


def test_batch_rejects_manifest_storage_identity_movement(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = batch_adapter_evidence[3]
    original_manifest_auth = admission_module.authenticate_profiled_training_observation_manifest_v1
    calls = 0

    def moved_manifest_auth(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        authenticated = original_manifest_auth(**kwargs)
        if calls == 2:
            return replace(
                authenticated,
                manifest_file_inode=authenticated.manifest_file_inode + 1,
            )
        return authenticated

    monkeypatch.setattr(
        admission_module,
        "authenticate_profiled_training_observation_manifest_v1",
        moved_manifest_auth,
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_MANIFEST_MOVED_DURING_ADMISSION",
    ):
        _batch_admit(evidence, page_limit=2)
    assert calls == 2


@pytest.mark.parametrize(
    "page_limit",
    [0, -1, True, MAX_PROFILED_OBSERVATION_PAGE_ROWS + 1],
)
def test_batch_rejects_invalid_page_limit_before_reading_manifest(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    page_limit: Any,
) -> None:
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_BATCH_PAGE_LIMIT_INVALID",
    ):
        _batch_admit(batch_adapter_evidence[1], page_limit=page_limit)


def test_batch_rejects_unfinished_candidate_before_returning_partial_results(
    batch_adapter_evidence: dict[int, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = batch_adapter_evidence[6]
    original_page_reader = admission_module.read_profiled_training_observation_page_v1

    def dirty_page_reader(**kwargs: Any) -> Any:
        page = original_page_reader(**kwargs)
        if kwargs["after_ordinal"] == 2:
            dirty = _replace_trust(page.examples[0], candle_closed_confirmed=False)
            object.__setattr__(page, "examples", (dirty, *page.examples[1:]))
        return page

    monkeypatch.setattr(
        admission_module,
        "read_profiled_training_observation_page_v1",
        dirty_page_reader,
    )
    with pytest.raises(
        AuthenticatedProfiledOptimizerAdmissionV1Error,
        match="PROFILED_OPTIMIZER_TRUST_ROW_CONTRACT_INVALID",
    ):
        _batch_admit(evidence, page_limit=2)
