from __future__ import annotations

import copy
import hashlib
import inspect
import json
import struct
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
)
from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256,
    AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256,
    AuthenticatedOhlcvProfileTransformV1Result,
    transform_authenticated_ohlcv_profile_v1,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_multitimeframe_capture_set_v1 import (
    build_canonical_ohlcv_multitimeframe_capture_set_v1,
    canonical_ohlcv_multitimeframe_capture_set_v1_contract,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    TEMPORAL_REJECTION_INELIGIBILITY_REASON,
    validate_feature_snapshot_record,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_ENABLED_SLOT_ORDINALS,
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
    LOGICAL_ORDERED_FEATURE_NAMES,
    LOGICAL_PROFILE_SELECTION_MASK,
    PHYSICAL_MODEL_FEATURE_COUNT,
    PHYSICAL_ORDERED_FEATURE_NAMES,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
    ProfiledModelFeatureSnapshotRecordV1Error,
    build_profiled_model_feature_snapshot_record_v1,
    validate_profiled_model_feature_snapshot_record_v1,
    validate_profiled_model_logical_projection_claim_v1,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TrainerSourceProvenanceLedgerEntryV4,
    TrainerSourceProvenanceLedgerV4,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_multitimeframe_capture_set_v1 as capture_support,
)

TRANSFORM_AVAILABLE_AT = "2026-07-21T12:00:00.800000Z"
RECORD_GENERATED_AT = "2026-07-21T12:00:00.850000Z"
_MODEL_VECTOR_HASH_DOMAIN = b"canonical_feature_model_vector_v3\0"
_COST_FIELDS = {
    "fee_bps",
    "spread_bps",
    "expected_slippage_bps",
    "expected_funding_bps",
}


@dataclass(frozen=True)
class Evidence:
    contract: dict[str, Any]
    transformed: AuthenticatedOhlcvProfileTransformV1Result
    capture_store: ImmutableSourcePayloadStore
    artifact_store: ImmutableSourcePayloadStore
    source_ledger: TrainerSourceProvenanceLedgerV4
    source_entries: tuple[
        TrainerSourceProvenanceLedgerEntryV4,
        TrainerSourceProvenanceLedgerEntryV4,
    ]
    record: dict[str, Any]


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _clock(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _build_evidence(root: Path) -> Evidence:
    captures, _source_stores = capture_support._capture_pair(root / "source-payloads")
    source_ledger = TrainerSourceProvenanceLedgerV4(root / "source-provenance")
    recorded_clocks = (
        datetime(2026, 7, 21, 12, 0, 0, 600_000, tzinfo=UTC),
        datetime(2026, 7, 21, 12, 0, 0, 610_000, tzinfo=UTC),
    )
    source_entries = tuple(
        source_ledger.append_atomic_capture(
            capture,
            trainer_run_id="profiled-model-record-test",
            trainer_cycle_id=f"profiled-model-record-{index}",
            ledger_clock=lambda value=recorded_clocks[index]: value,
        ).entry
        for index, capture in enumerate(captures)
    )
    capture_store = ImmutableSourcePayloadStore(root / "capture-set")
    capture_set = build_canonical_ohlcv_multitimeframe_capture_set_v1(
        profile=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
        atomic_captures=captures,
        capture_set_store=capture_store,
        generated_at=_clock(capture_support.GENERATED),
        decision_time=_clock(capture_support.DECISION),
    )
    contract = canonical_ohlcv_multitimeframe_capture_set_v1_contract(capture_set)
    transformed = transform_authenticated_ohlcv_profile_v1(
        contract,
        expected_capture_set_sha256=contract["capture_set_sha256"],
    )
    artifact_store = ImmutableSourcePayloadStore(root / "model-evidence")
    record = build_profiled_model_feature_snapshot_record_v1(
        transform_result=transformed,
        capture_set_contract=contract,
        capture_set_store=capture_store,
        artifact_store=artifact_store,
        source_provenance_ledger=source_ledger,
        source_provenance_entries=source_entries,
        transform_available_at=TRANSFORM_AVAILABLE_AT,
        generated_at=RECORD_GENERATED_AT,
    )
    return Evidence(
        contract=contract,
        transformed=transformed,
        capture_store=capture_store,
        artifact_store=artifact_store,
        source_ledger=source_ledger,
        source_entries=source_entries,
        record=record,
    )


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> Evidence:
    return _build_evidence(tmp_path_factory.mktemp("profiled-model-record"))


def _validate(
    evidence: Evidence,
    *,
    record: dict[str, Any] | None = None,
    transformed: AuthenticatedOhlcvProfileTransformV1Result | None = None,
    contract: dict[str, Any] | None = None,
):  # type: ignore[no-untyped-def]
    return validate_profiled_model_feature_snapshot_record_v1(
        evidence.record if record is None else record,
        transform_result=evidence.transformed if transformed is None else transformed,
        capture_set_contract=evidence.contract if contract is None else contract,
        capture_set_store=evidence.capture_store,
        artifact_store=evidence.artifact_store,
        source_provenance_ledger=evidence.source_ledger,
        source_provenance_entries=evidence.source_entries,
    )


def _rehash_capture_contract(contract: dict[str, Any]) -> str:
    for timeframe in contract["timeframes"]:
        for row in timeframe["rows"]:
            identity = {
                key: value
                for key, value in row.items()
                if key not in {"source_read_receipt_v4", "row_identity_sha256"}
            }
            row["row_identity_sha256"] = hashlib.sha256(
                _canonical_bytes(identity)
            ).hexdigest()
        timeframe["ordered_row_identity_sha256s"] = [
            row["row_identity_sha256"] for row in timeframe["rows"]
        ]
        timeframe_material = {
            key: value
            for key, value in timeframe.items()
            if key != "timeframe_capture_sha256"
        }
        timeframe["timeframe_capture_sha256"] = hashlib.sha256(
            _canonical_bytes(timeframe_material)
        ).hexdigest()
    root_material = {
        key: value
        for key, value in contract.items()
        if key
        not in {"content_address", "capture_set_sha256", "capture_set_manifest_byte_count"}
    }
    payload = _canonical_bytes(root_material)
    digest = hashlib.sha256(payload).hexdigest()
    contract["capture_set_sha256"] = digest
    contract["capture_set_manifest_byte_count"] = len(payload)
    contract["content_address"]["payload_sha256"] = digest
    contract["content_address"]["payload_byte_count"] = len(payload)
    return digest


def test_exact_35_only_record_is_v3_valid_quarantined_and_cost_free(
    evidence: Evidence,
) -> None:
    envelope = evidence.record["frozen_envelope"]
    normalized = validate_feature_snapshot_record(evidence.record)
    validation = _validate(evidence)

    assert normalized["strict_training_eligible"] == 0
    assert envelope["ordered_feature_names"] == list(PHYSICAL_ORDERED_FEATURE_NAMES)
    assert len(envelope["feature_values"]) == PHYSICAL_MODEL_FEATURE_COUNT == 35
    assert not _COST_FIELDS.intersection(envelope["ordered_feature_names"])
    assert all(name not in json.dumps(evidence.record) for name in _COST_FIELDS)
    assert envelope["missing_mask"] == [0] * 35
    assert envelope["stale_mask"] == [0] * 35
    assert envelope["source_availability_mask"] == [1] * 35
    assert envelope["temporal_rejection_reasons"] == [
        PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON
    ]
    assert envelope["strict_training_ineligibility_reasons"] == [
        TEMPORAL_REJECTION_INELIGIBILITY_REASON
    ]
    assert validation.record_sha256 == evidence.record["record_sha256"]


def test_values_have_no_caller_scalar_path_and_equal_recomputed_artifact(
    evidence: Evidence,
) -> None:
    signature = inspect.signature(build_profiled_model_feature_snapshot_record_v1)
    envelope = evidence.record["frozen_envelope"]

    assert "feature_values" not in signature.parameters
    assert "physical_feature_values" not in signature.parameters
    assert tuple(envelope["feature_values"]) == evidence.transformed.ordered_feature_values

    tampered = copy.deepcopy(evidence.record)
    tampered["frozen_envelope"]["feature_values"][0] += 1.0
    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_LEDGER_V3_INVALID",
    ):
        _validate(evidence, record=tampered)


def test_receipt_graph_binds_cas_artifact_configuration_and_implementation(
    evidence: Evidence,
) -> None:
    envelope = evidence.record["frozen_envelope"]
    lineage = envelope["source_lineage_material"]
    receipts = envelope["source_read_receipts"]

    assert len(receipts) == 2 + 2 + 35
    assert lineage["transform_artifact_sha256"] == evidence.transformed.artifact_sha256
    assert lineage["transform_implementation_sha256"] == (
        AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
    )
    assert lineage["transform_configuration_sha256"] == (
        AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
    )
    artifact_address = lineage["transform_artifact_address"]
    assert evidence.artifact_store.get(
        artifact_address["payload_sha256"],
        expected_byte_count=artifact_address["payload_byte_count"],
    ) == evidence.transformed.artifact_json.encode("ascii")
    for feature in lineage["feature_evidence"]:
        assert feature["implementation_sha256"] == (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_IMPLEMENTATION_SHA256
        )
        assert feature["global_configuration_sha256"] == (
            AUTHENTICATED_OHLCV_PROFILE_TRANSFORM_V1_CONFIGURATION_SHA256
        )
        scalar_address = feature["scalar_payload_address"]
        scalar = evidence.artifact_store.get(
            scalar_address["payload_sha256"],
            expected_byte_count=4,
        )
        assert scalar.hex() == feature["value_float32_be_hex"]


def test_provenance_entries_are_fresh_exact_and_recorded_before_transform(
    evidence: Evidence,
) -> None:
    validation = _validate(evidence)
    lineage = evidence.record["frozen_envelope"]["source_lineage_material"]
    source = lineage["source_provenance_binding"]

    assert source["provenance_recorded_before_transform"] is True
    assert [item["physical_timeframe"] for item in source["timeframe_bindings"]] == [
        "5m",
        "1h",
    ]
    assert [item["source_ledger_entry_sha256"] for item in source["timeframe_bindings"]] == [
        entry.entry_sha256 for entry in evidence.source_entries
    ]
    assert validation.source_provenance_binding_sha256 == (
        source["source_provenance_binding_sha256"]
    )
    assert all(
        item["source_ledger_recorded_at"] <= TRANSFORM_AVAILABLE_AT
        for item in source["timeframe_bindings"]
    )


def test_exact_5m_1h_finality_and_point_in_time_clocks_are_exposed(
    evidence: Evidence,
) -> None:
    lineage = evidence.record["frozen_envelope"]["source_lineage_material"]
    decision = lineage["capture_timestamps"]["decision_time"]
    timeframes = lineage["timeframe_evidence"]

    assert [item["physical_timeframe"] for item in timeframes] == ["5m", "1h"]
    assert [item["exact_closed_row_count"] for item in timeframes] == [71, 34]
    assert timeframes[1]["feature_cutoff"] <= timeframes[0]["feature_cutoff"] < decision
    for item in timeframes:
        assert item["event_time"] == item["feature_cutoff"]
        assert item["available_at"] <= lineage["capture_timestamps"]["generated_at"]
        assert item["atomic_consumer_observed_at"] <= TRANSFORM_AVAILABLE_AT
        assert len(item["ordered_row_identity_sha256s"]) == item["exact_closed_row_count"]
        assert len(item["ordered_source_receipt_sha256s"]) == (
            item["exact_closed_row_count"]
        )


def test_logical_projection_has_exact_446_selection_and_1784_hash(
    evidence: Evidence,
) -> None:
    projection = _validate(evidence).logical_projection

    assert projection.ordered_feature_names == LOGICAL_ORDERED_FEATURE_NAMES
    assert len(projection.feature_values) == LOGICAL_MODEL_FEATURE_COUNT == 446
    assert len(projection.model_vector) == LOGICAL_MODEL_INPUT_COUNT == 1784
    assert projection.profile_selection_mask == LOGICAL_PROFILE_SELECTION_MASK
    assert projection.enabled_slot_ordinals == LOGICAL_ENABLED_SLOT_ORDINALS
    assert sum(projection.profile_selection_mask) == 35
    enabled = set(ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals)
    for ordinal in range(LOGICAL_MODEL_FEATURE_COUNT):
        if ordinal in enabled:
            assert projection.source_availability_mask[ordinal] == 1
            assert projection.feature_source_labels[ordinal] is not None
            assert projection.feature_source_receipt_sha256s[ordinal] is not None
        else:
            assert (
                projection.feature_values[ordinal],
                projection.missing_mask[ordinal],
                projection.stale_mask[ordinal],
                projection.source_availability_mask[ordinal],
            ) == (0.0, 0, 0, 0)
            assert projection.feature_source_labels[ordinal] is None
            assert projection.feature_source_receipt_sha256s[ordinal] is None

    digest = hashlib.sha256()
    digest.update(_MODEL_VECTOR_HASH_DOMAIN)
    digest.update(bytes.fromhex(FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256))
    digest.update(struct.pack(">I", 446))
    for value in projection.model_vector:
        digest.update(struct.pack(">f", value))
    assert digest.hexdigest() == projection.model_vector_sha256


def test_logical_claim_validator_rejects_one_slot_drift(evidence: Evidence) -> None:
    projection = _validate(evidence).logical_projection
    claim = {
        "ordered_feature_names": projection.ordered_feature_names,
        "feature_values": projection.feature_values,
        "missing_mask": projection.missing_mask,
        "stale_mask": projection.stale_mask,
        "source_availability_mask": projection.source_availability_mask,
        "profile_selection_mask": projection.profile_selection_mask,
        "enabled_slot_ordinals": projection.enabled_slot_ordinals,
        "model_vector": projection.model_vector,
    }
    validate_profiled_model_logical_projection_claim_v1(projection, **claim)
    bad = list(projection.feature_values)
    bad[ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals[0]] += 1.0
    claim["feature_values"] = bad
    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_CLAIM_MISMATCH",
    ):
        validate_profiled_model_logical_projection_claim_v1(projection, **claim)

    forged_values = list(projection.feature_values)
    forged_values[ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1.enabled_slot_ordinals[0]] += 1.0
    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_LOGICAL_PROJECTION_INVARIANT_INVALID",
    ):
        replace(projection, feature_values=tuple(forged_values))


def test_stable_lineage_binding_supports_exact_later_enrichment(
    evidence: Evidence,
) -> None:
    validation = _validate(evidence)
    binding = validation.lineage_binding

    assert binding["durable_snapshot_id"] == evidence.record["durable_snapshot_id"]
    assert binding["record_sha256"] == evidence.record["record_sha256"]
    assert binding["profile_sha256"] == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
    assert binding["logical_model_vector_sha256"] == (
        validation.logical_projection.model_vector_sha256
    )
    assert binding["logical_enabled_slot_ordinals"] == list(
        validation.logical_projection.enabled_slot_ordinals
    )
    assert binding["logical_projection_sha256"] == (
        validation.logical_projection.logical_projection_sha256
    )
    assert all(value is False for value in binding["authorization"].values())


def test_artifact_hash_and_order_drift_are_rejected(evidence: Evidence) -> None:
    bad_hash = replace(evidence.transformed, artifact_sha256="0" * 64)
    with pytest.raises(ProfiledModelFeatureSnapshotRecordV1Error):
        _validate(evidence, transformed=bad_hash)

    artifact = copy.deepcopy(evidence.transformed.contract)
    artifact["ordered_features"][0], artifact["ordered_features"][1] = (
        artifact["ordered_features"][1],
        artifact["ordered_features"][0],
    )
    artifact_json = _canonical_bytes(artifact).decode("ascii")
    ordered = artifact["ordered_features"]
    bad_order = replace(
        evidence.transformed,
        ordered_feature_names=tuple(item["feature_name"] for item in ordered),
        ordered_feature_values=tuple(item["value_float32"] for item in ordered),
        ordered_receipt_material_sha256s=tuple(
            item["composite_derivation_receipt_material_sha256"] for item in ordered
        ),
        artifact_sha256=hashlib.sha256(artifact_json.encode("ascii")).hexdigest(),
        artifact_json=artifact_json,
    )
    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_TRANSFORM_RESULT_RECOMPUTE_MISMATCH",
    ):
        _validate(evidence, transformed=bad_order)


def test_capture_scalar_and_capture_hash_tamper_are_rejected(evidence: Evidence) -> None:
    tampered = copy.deepcopy(evidence.contract)
    tampered["timeframes"][0]["rows"][0]["ohlcv"]["close"] += 0.25
    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_TRANSFORM_RECOMPUTE_INVALID",
    ):
        _validate(evidence, contract=tampered)

    rehashed = copy.deepcopy(tampered)
    forged_root = _rehash_capture_contract(rehashed)
    assert forged_root != evidence.contract["capture_set_sha256"]
    with pytest.raises(ProfiledModelFeatureSnapshotRecordV1Error):
        _validate(evidence, contract=rehashed)


@pytest.mark.parametrize(
    ("transform_available_at", "generated_at"),
    [
        ("2026-07-21T12:00:00.950000Z", RECORD_GENERATED_AT),
        (TRANSFORM_AVAILABLE_AT, "2026-07-21T12:00:00.750000Z"),
        (TRANSFORM_AVAILABLE_AT, "2026-07-21T12:00:00.950000Z"),
    ],
)
def test_future_or_reversed_publication_clock_fails_closed(
    evidence: Evidence,
    transform_available_at: str,
    generated_at: str,
) -> None:
    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_PUBLICATION_CLOCK_ORDER_INVALID",
    ):
        build_profiled_model_feature_snapshot_record_v1(
            transform_result=evidence.transformed,
            capture_set_contract=evidence.contract,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=evidence.source_entries,
            transform_available_at=transform_available_at,
            generated_at=generated_at,
        )


def test_unfinished_or_not_yet_available_latest_candle_fails_closed(
    evidence: Evidence,
) -> None:
    candidate = copy.deepcopy(evidence.contract)
    candidate["timestamps"]["decision_time"] = "2026-07-21T12:00:00.015000Z"
    candidate["timestamps"]["generated_at"] = "2026-07-21T12:00:00.010000Z"
    _rehash_capture_contract(candidate)

    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_TRANSFORM_RECOMPUTE_INVALID",
    ):
        build_profiled_model_feature_snapshot_record_v1(
            transform_result=evidence.transformed,
            capture_set_contract=candidate,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=evidence.source_entries,
            transform_available_at=TRANSFORM_AVAILABLE_AT,
            generated_at=RECORD_GENERATED_AT,
        )


def test_source_provenance_is_required_and_cannot_be_substituted(
    evidence: Evidence,
) -> None:
    with pytest.raises(
        ProfiledModelFeatureSnapshotRecordV1Error,
        match="PROFILED_MODEL_RECORD_EXACT_SOURCE_PROVENANCE_ENTRIES_REQUIRED",
    ):
        build_profiled_model_feature_snapshot_record_v1(
            transform_result=evidence.transformed,
            capture_set_contract=evidence.contract,
            capture_set_store=evidence.capture_store,
            artifact_store=evidence.artifact_store,
            source_provenance_ledger=evidence.source_ledger,
            source_provenance_entries=cast(Any, (evidence.source_entries[0],)),
            transform_available_at=TRANSFORM_AVAILABLE_AT,
            generated_at=RECORD_GENERATED_AT,
        )
