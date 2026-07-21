from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer import (
    profiled_training_observation_manifest_head_v1 as head_module,
)
from v2.backend.app.services.native_trainer import (
    profiled_training_observation_manifest_v1 as manifest_module,
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
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION,
    PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
    PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION,
    PROFILED_OBSERVATION_WITNESS_RECEIPT_V1_SCHEMA_VERSION,
    ProfiledTrainingObservationExternalWitnessAppendReceiptV1,
    ProfiledTrainingObservationExternalWitnessEventV1,
    ProfiledTrainingObservationManifestHeadV1Error,
    read_local_profiled_training_observation_completion_candidate_v1,
    read_local_profiled_training_observation_head_candidate_v1,
    read_local_profiled_training_observation_page_receipt_v1,
    stage_profiled_training_observation_completion_candidate_v1,
    stage_profiled_training_observation_consumption_epoch_v1,
    stage_profiled_training_observation_head_candidate_v1,
    stage_profiled_training_observation_page_receipt_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    authenticate_profiled_training_observation_manifest_v1,
    build_profiled_training_observation_manifest_v1,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_model_feature_snapshot_record_v1 as base_support,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_profiled_training_observation_manifest_v1 as manifest_support,
)

MANIFEST_KEY = manifest_support.AUTH_KEY
MANIFEST_KEY_ID = manifest_support.AUTH_KEY_ID
HEAD_KEY = b"profiled-observation-head-test-key-v1"
HEAD_KEY_ID = "unit/profiled-observation-head-v1"
EPOCH_KEY = b"profiled-observation-epoch-test-key-v1"
EPOCH_KEY_ID = "unit/profiled-observation-epoch-v1"
NAMESPACE = "unit/profiled-observation-manifest-head"
CONSUMER_LANE = "unit/trainer-consumer"
VERIFIED_AT = "2026-07-26T00:00:00.000000Z"


@pytest.fixture(scope="module")
def manifest_evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("profiled-manifest-head")
    source_root = root / "sources"
    source_root.mkdir()
    base = base_support._build_evidence(root / "base")
    ledger, archive, observation, cost_root = manifest_support._setup_sources(
        source_root,
        base,
    )
    prior_clock = datetime.fromisoformat(observation.replace("Z", "+00:00")).astimezone(UTC)
    later_observation = (
        (prior_clock + timedelta(hours=1)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        manifest_module,
        "_factory_wall_clock_now",
        lambda: datetime(2026, 7, 25, tzinfo=UTC),
    )
    try:
        first = build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=(root / "manifests").absolute(),
            training_observed_at=observation,
            auth_key_id=MANIFEST_KEY_ID,
            hmac_key=MANIFEST_KEY,
        )
        equivocation = build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=(root / "manifests").absolute(),
            training_observed_at=observation,
            auth_key_id=MANIFEST_KEY_ID,
            hmac_key=MANIFEST_KEY,
            scan_limit=1,
        )
        second = build_profiled_training_observation_manifest_v1(
            ledger=ledger,
            trusted_immutable_cost_store_root=cost_root,
            label_archive=archive,
            manifest_root=(root / "manifests").absolute(),
            training_observed_at=later_observation,
            auth_key_id=MANIFEST_KEY_ID,
            hmac_key=MANIFEST_KEY,
        )

        unavailable_root = root / "unavailable-sources"
        unavailable_root.mkdir()
        unavailable_ledger, unavailable_archive, unavailable_observation, unavailable_cost = (
            manifest_support._setup_sources(
                unavailable_root,
                base,
                label_rows=3,
            )
        )
        unavailable = build_profiled_training_observation_manifest_v1(
            ledger=unavailable_ledger,
            trusted_immutable_cost_store_root=unavailable_cost,
            label_archive=unavailable_archive,
            manifest_root=(root / "unavailable-manifests").absolute(),
            training_observed_at=unavailable_observation,
            auth_key_id=MANIFEST_KEY_ID,
            hmac_key=MANIFEST_KEY,
        )
        migrated = build_profiled_training_observation_manifest_v1(
            ledger=unavailable_ledger,
            trusted_immutable_cost_store_root=unavailable_cost,
            label_archive=unavailable_archive,
            manifest_root=(root / "unavailable-manifests").absolute(),
            training_observed_at=later_observation,
            auth_key_id=MANIFEST_KEY_ID,
            hmac_key=MANIFEST_KEY,
        )

        zero_root = root / "zero-sources"
        zero_root.mkdir()
        zero_ledger = DurableFeatureSnapshotLedger(zero_root / "feature-ledger.sqlite3")
        zero_ledger.initialize()
        zero_cost = (zero_root / "cost-cas").absolute()
        zero = build_profiled_training_observation_manifest_v1(
            ledger=zero_ledger,
            trusted_immutable_cost_store_root=zero_cost,
            label_archive=archive,
            manifest_root=(root / "zero-manifests").absolute(),
            training_observed_at=observation,
            auth_key_id=MANIFEST_KEY_ID,
            hmac_key=MANIFEST_KEY,
        )
        yield {
            "ledger": ledger,
            "archive": archive,
            "cost_root": cost_root,
            "first": first,
            "equivocation": equivocation,
            "second": second,
            "unavailable_ledger": unavailable_ledger,
            "unavailable_archive": unavailable_archive,
            "unavailable": unavailable,
            "migrated": migrated,
            "zero_ledger": zero_ledger,
            "zero_archive": archive,
            "zero": zero,
        }
    finally:
        monkeypatch.undo()


def _authenticated(build: Any) -> Any:
    return authenticate_profiled_training_observation_manifest_v1(
        manifest_path=build.manifest_path,
        hmac_key=MANIFEST_KEY,
        expected_auth_key_id=MANIFEST_KEY_ID,
        expected_manifest_id=build.manifest_id,
        expected_observation_time=build.observation_time,
    )


def _head(
    *,
    build: Any,
    ledger: DurableFeatureSnapshotLedger,
    archive: DurableCanonical5mLabelArchive,
    store: ImmutableSourcePayloadStore,
    previous: Any = None,
    completion: Any = None,
) -> Any:
    return stage_profiled_training_observation_head_candidate_v1(
        manifest_path=build.manifest_path,
        expected_manifest_id=build.manifest_id,
        expected_observation_time=build.observation_time,
        feature_ledger=ledger,
        label_archive=archive,
        staging_store=store,
        namespace=NAMESPACE,
        consumer_lane=CONSUMER_LANE,
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
        previous_head_candidate=previous,
        previous_completion_candidate=completion,
    )


def _consume(
    *,
    build: Any,
    ledger: DurableFeatureSnapshotLedger,
    archive: DurableCanonical5mLabelArchive,
    store: ImmutableSourcePayloadStore,
) -> tuple[Any, Any, Any, Any]:
    head = _head(build=build, ledger=ledger, archive=archive, store=store)
    authenticated = _authenticated(build)
    epoch = stage_profiled_training_observation_consumption_epoch_v1(
        head_candidate=head,
        staging_store=store,
        consumer_lane=CONSUMER_LANE,
        page_size=1,
        manifest_hmac_key=MANIFEST_KEY,
        manifest_auth_key_id=MANIFEST_KEY_ID,
        head_hmac_key=HEAD_KEY,
        head_auth_key_id=HEAD_KEY_ID,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    page = None
    if epoch.total_profiled_samples:
        page = stage_profiled_training_observation_page_receipt_v1(
            epoch=epoch,
            authenticated_manifest=authenticated,
            staging_store=store,
            verified_at=VERIFIED_AT,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
        )
    completion = stage_profiled_training_observation_completion_candidate_v1(
        epoch=epoch,
        staging_store=store,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
        final_page_receipt=page,
    )
    return head, epoch, page, completion


def test_genesis_head_is_deterministic_cas_backed_and_has_no_authority(
    tmp_path: Path,
    manifest_evidence: dict[str, Any],
) -> None:
    store = ImmutableSourcePayloadStore((tmp_path / "cas").absolute())
    first = manifest_evidence["first"]
    head = _head(
        build=first,
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
    )
    replay = _head(
        build=first,
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
        previous=head,
    )

    assert replay.candidate_event_sha256 == head.candidate_event_sha256
    assert head.revision == 1
    assert head.allowed_consumer_lane == CONSUMER_LANE
    assert head._material["epoch_auth_key_commitment_sha256"] == (
        head_module._epoch_key_commitment(key=EPOCH_KEY, key_id=EPOCH_KEY_ID)
    )
    assert head.local_status == PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
    assert head._material["local_rollback_limitation"] == (
        PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION
    )
    assert head.full_manifest_authentication_verified is True
    assert head.full_entry_inventory_verified is True
    assert head.external_monotonic_manifest_head_verified is False
    assert head.full_consumption_external_ack_verified is False
    assert head.optimizer_admission_authorized is False
    assert head.checkpoint_write_authorized is False
    assert head.model_write_authorized is False
    assert head.prediction_authorized is False
    assert head.paper_trading_authorized is False
    assert head.live_execution_authorized is False
    assert head.order_submission_authorized is False
    assert head.execution_authorized is False
    assert head.runtime_wired is False
    assert (
        store.verify(
            head.candidate_event_sha256,
            expected_byte_count=head.candidate_event_byte_count,
        ).payload_sha256
        == head.candidate_event_sha256
    )


def test_role_key_reuse_wrong_key_and_tampered_head_fail_closed(
    tmp_path: Path,
    manifest_evidence: dict[str, Any],
) -> None:
    store = ImmutableSourcePayloadStore((tmp_path / "cas").absolute())
    first = manifest_evidence["first"]
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_ROLE_KEY_REUSE_FORBIDDEN",
    ):
        stage_profiled_training_observation_head_candidate_v1(
            manifest_path=first.manifest_path,
            expected_manifest_id=first.manifest_id,
            expected_observation_time=first.observation_time,
            feature_ledger=manifest_evidence["ledger"],
            label_archive=manifest_evidence["archive"],
            staging_store=store,
            namespace=NAMESPACE,
            consumer_lane=CONSUMER_LANE,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=MANIFEST_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
        )
    head = _head(
        build=first,
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
    )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_CANDIDATE_AUTHENTICATION_INVALID",
    ):
        read_local_profiled_training_observation_head_candidate_v1(
            staging_store=store,
            candidate_event_sha256=head.candidate_event_sha256,
            candidate_event_byte_count=head.candidate_event_byte_count,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=b"wrong-head-key-material-value-0000",
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
            expected_namespace=NAMESPACE,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_EMBEDDED_MANIFEST_REAUTHENTICATION_FAILED",
    ):
        read_local_profiled_training_observation_head_candidate_v1(
            staging_store=store,
            candidate_event_sha256=head.candidate_event_sha256,
            candidate_event_byte_count=head.candidate_event_byte_count,
            manifest_hmac_key=b"wrong-manifest-key-material-value-00",
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
            expected_namespace=NAMESPACE,
        )
    wrong_epoch_key = b"wrong-profiled-observation-epoch-key-v1"
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_EPOCH_KEY_COMMITMENT_MISMATCH",
    ):
        read_local_profiled_training_observation_head_candidate_v1(
            staging_store=store,
            candidate_event_sha256=head.candidate_event_sha256,
            candidate_event_byte_count=head.candidate_event_byte_count,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=wrong_epoch_key,
            epoch_auth_key_id=EPOCH_KEY_ID,
            expected_namespace=NAMESPACE,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_EPOCH_KEY_COMMITMENT_MISMATCH",
    ):
        stage_profiled_training_observation_consumption_epoch_v1(
            head_candidate=head,
            staging_store=store,
            consumer_lane=CONSUMER_LANE,
            page_size=1,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=wrong_epoch_key,
            epoch_auth_key_id=EPOCH_KEY_ID,
        )

    tampered = dict(head._material)
    tampered["revision"] = 2
    raw = json.dumps(
        tampered,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    address = store.put(raw)
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_CANDIDATE_AUTHENTICATION_INVALID",
    ):
        read_local_profiled_training_observation_head_candidate_v1(
            staging_store=store,
            candidate_event_sha256=address.payload_sha256,
            candidate_event_byte_count=address.payload_byte_count,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
            expected_namespace=NAMESPACE,
        )


def test_epoch_page_and_completion_are_exact_locally_staged_non_authority(
    tmp_path: Path,
    manifest_evidence: dict[str, Any],
) -> None:
    store = ImmutableSourcePayloadStore((tmp_path / "cas").absolute())
    head, epoch, page, completion = _consume(
        build=manifest_evidence["first"],
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
    )
    assert page is not None
    assert epoch.consumer_lane == CONSUMER_LANE
    assert completion.consumer_lane == CONSUMER_LANE
    assert epoch.total_profiled_samples == 1
    assert page.page_sequence == 1
    assert page.page_start_ordinal == 1
    assert page.page_end_ordinal == 1
    assert page.cumulative_scanned_entry_count == 1
    assert page.has_more_manifest_entries is False
    assert completion.head_candidate_event_sha256 == head.candidate_event_sha256
    assert completion.page_count == 1
    assert completion.consumed_entry_count == 1
    assert completion.full_consumption_locally_verified is True
    assert completion.external_monotonic_manifest_head_verified is False
    assert completion.full_consumption_external_ack_verified is False
    assert completion.optimizer_admission_authorized is False
    assert completion.model_write_authorized is False
    assert completion.runtime_wired is False
    reread = read_local_profiled_training_observation_completion_candidate_v1(
        staging_store=store,
        completion_event_sha256=completion.completion_event_sha256,
        completion_event_byte_count=completion.completion_event_byte_count,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    assert reread.completion_id == completion.completion_id

    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_EPOCH_HEAD_LANE_MISMATCH",
    ):
        stage_profiled_training_observation_consumption_epoch_v1(
            head_candidate=head,
            staging_store=store,
            consumer_lane="unit/other-trainer-consumer",
            page_size=1,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
        )


def test_page_cursor_gap_overlap_conflicting_replay_and_tamper_are_rejected(
    tmp_path: Path,
    manifest_evidence: dict[str, Any],
) -> None:
    store = ImmutableSourcePayloadStore((tmp_path / "cas").absolute())
    head, epoch, page, _completion = _consume(
        build=manifest_evidence["first"],
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
    )
    assert head and page is not None
    authenticated = _authenticated(manifest_evidence["first"])
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_PAGE_EXPECTED_CURSOR_GAP_OR_OVERLAP",
    ):
        stage_profiled_training_observation_page_receipt_v1(
            epoch=epoch,
            authenticated_manifest=authenticated,
            staging_store=store,
            verified_at=VERIFIED_AT,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
            expected_after_ordinal=1,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_PAGE_CONFLICTING_REPLAY",
    ):
        stage_profiled_training_observation_page_receipt_v1(
            epoch=epoch,
            authenticated_manifest=authenticated,
            staging_store=store,
            verified_at="2026-07-26T00:00:01.000000Z",
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
            replay_page_receipt=page,
        )

    tampered = dict(page._material)
    tampered["page_end_entry_chain_sha256"] = "f" * 64
    raw = head_module._canonical_json(tampered, reason="unit-page-tamper").encode("ascii")
    address = store.put(raw)
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_PAGE_RECEIPT_AUTHENTICATION_INVALID",
    ):
        read_local_profiled_training_observation_page_receipt_v1(
            staging_store=store,
            page_receipt_event_sha256=address.payload_sha256,
            page_receipt_event_byte_count=address.payload_byte_count,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
        )


def test_unavailable_only_and_zero_inventory_complete_without_fake_examples(
    tmp_path: Path,
    manifest_evidence: dict[str, Any],
) -> None:
    unavailable_store = ImmutableSourcePayloadStore((tmp_path / "unavailable-cas").absolute())
    _head_one, epoch_one, page_one, completion_one = _consume(
        build=manifest_evidence["unavailable"],
        ledger=manifest_evidence["unavailable_ledger"],
        archive=manifest_evidence["unavailable_archive"],
        store=unavailable_store,
    )
    assert page_one is not None
    assert epoch_one.total_profiled_samples == 1
    assert epoch_one.admitted_example_count == 0
    assert epoch_one.label_unavailable_count == 1
    assert page_one.admitted_entry_count == 0
    assert page_one.label_unavailable_count == 1
    assert completion_one.consumed_entry_count == 1
    assert completion_one.admitted_entry_count == 0
    assert completion_one.label_unavailable_count == 1

    zero_store = ImmutableSourcePayloadStore((tmp_path / "zero-cas").absolute())
    _head_zero, epoch_zero, page_zero, completion_zero = _consume(
        build=manifest_evidence["zero"],
        ledger=manifest_evidence["zero_ledger"],
        archive=manifest_evidence["zero_archive"],
        store=zero_store,
    )
    assert epoch_zero.total_profiled_samples == 0
    assert page_zero is None
    assert completion_zero.page_count == 0
    assert completion_zero.consumed_entry_count == 0
    assert completion_zero.terminal_entry_chain_sha256 == (
        manifest_module.PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
    )


def test_successor_requires_completion_reproduces_prior_and_rejects_rollback(
    tmp_path: Path,
    manifest_evidence: dict[str, Any],
) -> None:
    store = ImmutableSourcePayloadStore((tmp_path / "cas").absolute())
    first_head, _epoch, _page, first_completion = _consume(
        build=manifest_evidence["first"],
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
    )
    alternate_completion_unsigned = {
        name: value
        for name, value in first_completion._material.items()
        if name not in {"completion_id", "completion_auth_tag"}
    }
    alternate_completion_unsigned["consumer_lane"] = "unit/other-trainer-consumer"
    alternate_completion_material = head_module._seal(
        alternate_completion_unsigned,
        identity_field="completion_id",
        auth_field="completion_auth_tag",
        domain=head_module.PROFILED_OBSERVATION_COMPLETION_AUTH_DOMAIN,
        role="full-consumption-completion",
        key=EPOCH_KEY,
    )
    alternate_completion_raw = head_module._canonical_json(
        alternate_completion_material,
        reason="unit-alternate-lane-completion",
    ).encode("ascii")
    alternate_completion_address = store.put(alternate_completion_raw)
    alternate_completion = read_local_profiled_training_observation_completion_candidate_v1(
        staging_store=store,
        completion_event_sha256=alternate_completion_address.payload_sha256,
        completion_event_byte_count=alternate_completion_address.payload_byte_count,
        epoch_hmac_key=EPOCH_KEY,
        epoch_auth_key_id=EPOCH_KEY_ID,
    )
    assert alternate_completion.consumer_lane == "unit/other-trainer-consumer"
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_PRIOR_COMPLETION_LANE_MISMATCH",
    ):
        _head(
            build=manifest_evidence["second"],
            ledger=manifest_evidence["ledger"],
            archive=manifest_evidence["archive"],
            store=store,
            previous=first_head,
            completion=alternate_completion,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_PRIOR_FULL_CONSUMPTION_REQUIRED",
    ):
        _head(
            build=manifest_evidence["second"],
            ledger=manifest_evidence["ledger"],
            archive=manifest_evidence["archive"],
            store=store,
            previous=first_head,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_SAME_CUTOFF_DIFFERENT_MANIFEST_EQUIVOCATION",
    ):
        _head(
            build=manifest_evidence["equivocation"],
            ledger=manifest_evidence["ledger"],
            archive=manifest_evidence["archive"],
            store=store,
            previous=first_head,
            completion=first_completion,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_SOURCE_ROOT_OR_PATH_MIGRATION_FORBIDDEN",
    ):
        _head(
            build=manifest_evidence["migrated"],
            ledger=manifest_evidence["unavailable_ledger"],
            archive=manifest_evidence["unavailable_archive"],
            store=store,
            previous=first_head,
            completion=first_completion,
        )
    second_head = _head(
        build=manifest_evidence["second"],
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
        previous=first_head,
        completion=first_completion,
    )
    assert second_head.revision == first_head.revision + 1
    assert second_head.previous_head_event_sha256 == first_head.candidate_event_sha256
    assert second_head.previous_completion_candidate_sha256 == (
        first_completion.completion_event_sha256
    )
    receipt = second_head._material["prior_high_water_reproduction_receipt"]
    assert receipt["full_prior_high_water_reproduction_verified"] is True

    # The completed older manifest cannot replace the later head.
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_MANIFEST_CUTOFF_ROLLBACK",
    ):
        _head(
            build=manifest_evidence["first"],
            ledger=manifest_evidence["ledger"],
            archive=manifest_evidence["archive"],
            store=store,
            previous=second_head,
            completion=first_completion,
        )


def test_page_size_bound_and_source_path_mismatch_fail_before_staging(
    tmp_path: Path,
    manifest_evidence: dict[str, Any],
) -> None:
    store = ImmutableSourcePayloadStore((tmp_path / "cas").absolute())
    head = _head(
        build=manifest_evidence["first"],
        ledger=manifest_evidence["ledger"],
        archive=manifest_evidence["archive"],
        store=store,
    )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_EPOCH_PAGE_SIZE_INVALID",
    ):
        stage_profiled_training_observation_consumption_epoch_v1(
            head_candidate=head,
            staging_store=store,
            consumer_lane="unit/trainer-consumer",
            page_size=manifest_module.MAX_PROFILED_OBSERVATION_PAGE_ROWS + 1,
            manifest_hmac_key=MANIFEST_KEY,
            manifest_auth_key_id=MANIFEST_KEY_ID,
            head_hmac_key=HEAD_KEY,
            head_auth_key_id=HEAD_KEY_ID,
            epoch_hmac_key=EPOCH_KEY,
            epoch_auth_key_id=EPOCH_KEY_ID,
        )

    wrong_ledger = DurableFeatureSnapshotLedger(tmp_path / "wrong-ledger.sqlite3")
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_CURRENT_SOURCE_PATH_BINDING_INVALID",
    ):
        _head(
            build=manifest_evidence["first"],
            ledger=wrong_ledger,
            archive=manifest_evidence["archive"],
            store=store,
        )


def test_candidate_bytes_are_canonical_and_hash_bound() -> None:
    material = {"b": 2, "a": 1}
    encoded = head_module._canonical_json(material, reason="unit-canonical")
    assert encoded == '{"a":1,"b":2}'
    assert hashlib.sha256(encoded.encode("ascii")).hexdigest() == (
        hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
    )


def test_external_witness_types_are_strict_integrity_contracts_not_local_authority() -> None:
    event_bytes = b'{"candidate":"opaque"}'
    event = ProfiledTrainingObservationExternalWitnessEventV1(
        schema_version=PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION,
        witness_id="unit/external-witness",
        namespace=NAMESPACE,
        sequence=1,
        previous_event_sha256=head_module.PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        event_sha256=hashlib.sha256(event_bytes).hexdigest(),
        event_bytes=event_bytes,
    )
    receipt_bytes = b'{"accepted":true}'
    receipt = ProfiledTrainingObservationExternalWitnessAppendReceiptV1(
        schema_version=PROFILED_OBSERVATION_WITNESS_RECEIPT_V1_SCHEMA_VERSION,
        witness_id=event.witness_id,
        namespace=event.namespace,
        sequence=event.sequence,
        previous_event_sha256=event.previous_event_sha256,
        event_sha256=event.event_sha256,
        accepted_at=VERIFIED_AT,
        receipt_sha256=hashlib.sha256(receipt_bytes).hexdigest(),
        receipt_bytes=receipt_bytes,
    )

    assert receipt.event_sha256 == event.event_sha256
    assert not hasattr(event, "external_monotonic_manifest_head_verified")
    assert not hasattr(receipt, "external_monotonic_manifest_head_verified")
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_WITNESS_EVENT_CONTRACT_INVALID",
    ):
        ProfiledTrainingObservationExternalWitnessEventV1(
            schema_version=PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION,
            witness_id="unit/external-witness",
            namespace=NAMESPACE,
            sequence=1,
            previous_event_sha256=(head_module.PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256),
            event_sha256="0" * 64,
            event_bytes=event_bytes,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_WITNESS_EVENT_CONTRACT_INVALID",
    ):
        ProfiledTrainingObservationExternalWitnessEventV1(
            schema_version=PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION,
            witness_id="unit/external-witness",
            namespace=NAMESPACE,
            sequence=True,
            previous_event_sha256=(head_module.PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256),
            event_sha256=event.event_sha256,
            event_bytes=event_bytes,
        )
    with pytest.raises(
        ProfiledTrainingObservationManifestHeadV1Error,
        match="PROFILED_HEAD_WITNESS_RECEIPT_CONTRACT_INVALID",
    ):
        ProfiledTrainingObservationExternalWitnessAppendReceiptV1(
            schema_version=PROFILED_OBSERVATION_WITNESS_RECEIPT_V1_SCHEMA_VERSION,
            witness_id=event.witness_id,
            namespace=event.namespace,
            sequence=event.sequence,
            previous_event_sha256=event.previous_event_sha256,
            event_sha256=event.event_sha256,
            accepted_at=VERIFIED_AT,
            receipt_sha256=receipt.receipt_sha256,
            receipt_bytes="not-bytes",  # type: ignore[arg-type]
        )
