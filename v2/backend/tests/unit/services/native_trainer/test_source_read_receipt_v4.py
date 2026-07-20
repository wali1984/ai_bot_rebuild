from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    PROVENANCE_CANONICAL_V3,
    FeatureSnapshotValidationError,
    build_feature_snapshot_record,
)
from v2.backend.app.services.native_trainer.source_read_receipt_v4 import (
    MAX_SOURCE_PAYLOAD_BYTES,
    SOURCE_FINALITY_EVIDENCE_V4_SCHEMA_VERSION,
    SOURCE_READ_EVIDENCE_V4_SCHEMA_VERSION,
    SOURCE_READ_RECEIPT_V4_DOWNSTREAM_STATUS,
    SOURCE_READ_RECEIPT_V4_EVIDENCE_CLASSIFICATION,
    SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
    SourceReadReceiptV4,
    SourceReadReceiptV4ValidationError,
    build_source_read_receipt_v4,
    validate_source_read_receipt_v4,
)

BASE = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _kwargs(*, websocket: bool = True) -> dict[str, Any]:
    economic_close = BASE + timedelta(seconds=59, milliseconds=999)
    producer_event = (
        economic_close + timedelta(milliseconds=105) if websocket else economic_close
    )
    ingested = producer_event + timedelta(milliseconds=127)
    available = ingested
    consumer_observed = available + timedelta(milliseconds=250)
    return {
        "source_label": "ohlcv_closed:binance:BTCUSDT:1m",
        "payload_type": "EXACT_CANONICAL_CLOSED_OHLCV_WINDOW_BYTES",
        "payload_sha256": "a" * 64,
        "payload_byte_count": 12_345,
        "economic_event_time": _utc(economic_close),
        "producer_event_time": _utc(producer_event),
        "ingested_at": _utc(ingested),
        "available_at": _utc(available),
        "consumer_observed_at": _utc(consumer_observed),
        "feature_cutoff": _utc(economic_close),
        "read_locator_type": "FILE_CONTENT_ADDRESS",
        "read_locator": "sha256/aa/" + ("a" * 64),
        "read_locator_version": "atomic-batch-" + ("b" * 64),
        "finality_type": "CLOSED_INTERVAL",
        "finality_cutoff": _utc(economic_close),
        "finality_verified_at": _utc(available),
        "finality_verifier": "trainer-ohlcv-closed-window-adapter-v1",
    }


def _build(*, websocket: bool = True, **overrides: Any) -> SourceReadReceiptV4:
    kwargs = _kwargs(websocket=websocket)
    kwargs.update(overrides)
    return build_source_read_receipt_v4(**kwargs)


def _assert_builder_rejects(reason: str, **overrides: Any) -> None:
    with pytest.raises(SourceReadReceiptV4ValidationError) as exc_info:
        _build(**overrides)
    assert reason in exc_info.value.reasons


def _assert_validator_rejects(receipt: object, reason: str) -> None:
    with pytest.raises(SourceReadReceiptV4ValidationError) as exc_info:
        validate_source_read_receipt_v4(receipt)
    assert reason in exc_info.value.reasons


def test_truthful_wss_clock_order_keeps_producer_event_after_close() -> None:
    artifact = _build(websocket=True)
    receipt = artifact.receipt

    assert receipt["economic_event_time"] == receipt["feature_cutoff"]
    assert receipt["economic_event_time"] == receipt["finality_evidence"][
        "finality_cutoff"
    ]
    assert receipt["producer_event_time"] > receipt["economic_event_time"]
    assert receipt["producer_event_time"] > receipt["feature_cutoff"]
    assert receipt["producer_event_time"] > receipt["finality_evidence"][
        "finality_cutoff"
    ]
    assert receipt["producer_event_time"] <= receipt["ingested_at"]
    assert receipt["ingested_at"] <= receipt["available_at"]
    assert receipt["available_at"] <= receipt["consumer_observed_at"]


def test_truthful_rest_clock_order_allows_producer_event_equal_close() -> None:
    receipt = _build(websocket=False).receipt

    assert receipt["producer_event_time"] == receipt["economic_event_time"]
    assert receipt["economic_event_time"] == receipt["feature_cutoff"]
    assert receipt["ingested_at"] == receipt["available_at"]


def test_result_and_hashed_receipt_keep_every_downstream_flag_false() -> None:
    artifact = _build()
    receipt = artifact.receipt
    flag_names = (
        "durable_ledger_appended",
        "feature_snapshot_published",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    )

    assert artifact.schema_version == SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION
    assert receipt["schema_version"] == SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION
    assert receipt["evidence_classification"] == (
        SOURCE_READ_RECEIPT_V4_EVIDENCE_CLASSIFICATION
    )
    assert receipt["downstream_status"] == SOURCE_READ_RECEIPT_V4_DOWNSTREAM_STATUS
    assert all(getattr(artifact, name) is False for name in flag_names)
    assert all(receipt[name] is False for name in flag_names)


def test_read_and_finality_evidence_bind_every_source_clock_and_payload() -> None:
    receipt = _build().receipt
    read_evidence = receipt["read_evidence"]
    finality_evidence = receipt["finality_evidence"]

    assert read_evidence["schema_version"] == SOURCE_READ_EVIDENCE_V4_SCHEMA_VERSION
    assert finality_evidence["schema_version"] == (
        SOURCE_FINALITY_EVIDENCE_V4_SCHEMA_VERSION
    )
    for field_name in (
        "source_label",
        "payload_type",
        "payload_sha256",
        "payload_byte_count",
        "economic_event_time",
        "producer_event_time",
        "ingested_at",
        "available_at",
    ):
        assert read_evidence[field_name] == receipt[field_name]
        assert finality_evidence[field_name] == receipt[field_name]
    assert read_evidence["read_completed_at"] == receipt["consumer_observed_at"]
    assert finality_evidence["consumer_observed_at"] == receipt["consumer_observed_at"]
    assert finality_evidence["read_evidence_sha256"] == receipt["read_evidence_sha256"]
    assert finality_evidence["read_locator_sha256"] == receipt["read_locator_sha256"]


def test_equal_inputs_are_deterministic_and_validation_returns_frozen_copy() -> None:
    first = _build()
    second = _build()
    validated = validate_source_read_receipt_v4(copy.deepcopy(first.receipt))

    assert first.receipt_sha256 == second.receipt_sha256 == validated.receipt_sha256
    assert first.receipt_json == second.receipt_json == validated.receipt_json
    with pytest.raises(FrozenInstanceError):
        first.receipt_sha256 = "0" * 64  # type: ignore[misc]

    caller_copy = first.receipt
    caller_copy["producer_event_time"] = caller_copy["economic_event_time"]
    assert first.receipt["producer_event_time"] > first.receipt["economic_event_time"]


@pytest.mark.parametrize(
    ("field_name", "replacement_field", "delta", "reason"),
    [
        (
            "producer_event_time",
            "economic_event_time",
            timedelta(microseconds=-1),
            "SOURCE_PRODUCER_EVENT_TIME_BEFORE_ECONOMIC_EVENT_TIME",
        ),
        (
            "producer_event_time",
            "ingested_at",
            timedelta(microseconds=1),
            "SOURCE_PRODUCER_EVENT_TIME_AFTER_INGESTED_AT",
        ),
        (
            "ingested_at",
            "available_at",
            timedelta(microseconds=1),
            "SOURCE_INGESTED_AT_AFTER_AVAILABLE_AT",
        ),
        (
            "available_at",
            "consumer_observed_at",
            timedelta(microseconds=1),
            "SOURCE_AVAILABLE_AT_AFTER_CONSUMER_OBSERVED_AT",
        ),
        (
            "feature_cutoff",
            "economic_event_time",
            timedelta(microseconds=-1),
            "SOURCE_ECONOMIC_EVENT_TIME_AFTER_FEATURE_CUTOFF",
        ),
        (
            "feature_cutoff",
            "consumer_observed_at",
            timedelta(microseconds=1),
            "SOURCE_FEATURE_CUTOFF_AFTER_CONSUMER_OBSERVED_AT",
        ),
        (
            "finality_verified_at",
            "available_at",
            timedelta(microseconds=-1),
            "SOURCE_AVAILABLE_AT_AFTER_FINALITY_VERIFIED_AT",
        ),
        (
            "finality_verified_at",
            "consumer_observed_at",
            timedelta(microseconds=1),
            "SOURCE_FINALITY_VERIFIED_AT_AFTER_CONSUMER_OBSERVED_AT",
        ),
    ],
)
def test_builder_rejects_every_causal_clock_inversion(
    field_name: str,
    replacement_field: str,
    delta: timedelta,
    reason: str,
) -> None:
    kwargs = _kwargs()
    replacement = datetime.strptime(
        kwargs[replacement_field],
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ).replace(tzinfo=UTC)

    _assert_builder_rejects(reason, **{field_name: _utc(replacement + delta)})


def test_closed_interval_finality_cutoff_must_equal_economic_close() -> None:
    economic = datetime.strptime(
        _kwargs()["economic_event_time"],
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ).replace(tzinfo=UTC)
    _assert_builder_rejects(
        "SOURCE_CLOSED_INTERVAL_FINALITY_CUTOFF_MISMATCH",
        finality_cutoff=_utc(economic + timedelta(microseconds=1)),
    )


@pytest.mark.parametrize(
    ("field_name", "value", "reason"),
    [
        (
            "economic_event_time",
            "2026-07-19T12:00:59.999Z",
            "SOURCE_RECEIPT_V4_ECONOMIC_EVENT_TIME_INVALID",
        ),
        (
            "producer_event_time",
            "2026-07-19T12:01:00.104000+00:00",
            "SOURCE_RECEIPT_V4_PRODUCER_EVENT_TIME_INVALID",
        ),
        ("ingested_at", "not-a-clock", "SOURCE_RECEIPT_V4_INGESTED_AT_INVALID"),
        ("available_at", "1969-12-31T23:59:59.999999Z", "SOURCE_RECEIPT_V4_AVAILABLE_AT_INVALID"),
    ],
)
def test_builder_rejects_noncanonical_or_invalid_clocks(
    field_name: str,
    value: str,
    reason: str,
) -> None:
    _assert_builder_rejects(reason, **{field_name: value})


def test_missing_ingested_at_and_ingested_binding_tampering_fail_closed() -> None:
    receipt = _build().receipt
    missing = copy.deepcopy(receipt)
    del missing["ingested_at"]
    _assert_validator_rejects(missing, "SOURCE_RECEIPT_V4_FIELD_SET_MISMATCH")

    tampered_read = copy.deepcopy(receipt)
    tampered_read["read_evidence"]["ingested_at"] = tampered_read[
        "producer_event_time"
    ]
    _assert_validator_rejects(
        tampered_read,
        "SOURCE_READ_EVIDENCE_V4_INGESTED_AT_BINDING_MISMATCH",
    )

    tampered_finality = copy.deepcopy(receipt)
    tampered_finality["finality_evidence"]["ingested_at"] = tampered_finality[
        "producer_event_time"
    ]
    _assert_validator_rejects(
        tampered_finality,
        "SOURCE_FINALITY_EVIDENCE_V4_INGESTED_AT_BINDING_MISMATCH",
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("receipt_hash", "SOURCE_RECEIPT_V4_SHA256_MISMATCH"),
        ("read_hash", "SOURCE_READ_EVIDENCE_V4_SHA256_MISMATCH"),
        ("finality_hash", "SOURCE_FINALITY_EVIDENCE_V4_SHA256_MISMATCH"),
        ("root_locator_hash", "SOURCE_RECEIPT_V4_LOCATOR_SHA256_MISMATCH"),
        ("read_locator_hash", "SOURCE_READ_EVIDENCE_V4_LOCATOR_SHA256_MISMATCH"),
        (
            "finality_read_hash",
            "SOURCE_FINALITY_EVIDENCE_V4_READ_SHA256_BINDING_MISMATCH",
        ),
        (
            "finality_locator_hash",
            "SOURCE_FINALITY_EVIDENCE_V4_LOCATOR_SHA256_BINDING_MISMATCH",
        ),
    ],
)
def test_every_hash_layer_rejects_tampering(mutation: str, reason: str) -> None:
    receipt = _build().receipt
    if mutation == "receipt_hash":
        receipt["receipt_sha256"] = "0" * 64
    elif mutation == "read_hash":
        receipt["read_evidence_sha256"] = "0" * 64
    elif mutation == "finality_hash":
        receipt["finality_evidence_sha256"] = "0" * 64
    elif mutation == "root_locator_hash":
        receipt["read_locator_sha256"] = "0" * 64
    elif mutation == "read_locator_hash":
        receipt["read_evidence"]["read_locator_sha256"] = "0" * 64
    elif mutation == "finality_read_hash":
        receipt["finality_evidence"]["read_evidence_sha256"] = "0" * 64
    else:
        receipt["finality_evidence"]["read_locator_sha256"] = "0" * 64

    _assert_validator_rejects(receipt, reason)


@pytest.mark.parametrize(
    ("field_name", "reason"),
    [
        ("source_label", "SOURCE_READ_EVIDENCE_V4_SOURCE_LABEL_BINDING_MISMATCH"),
        ("payload_type", "SOURCE_READ_EVIDENCE_V4_PAYLOAD_TYPE_BINDING_MISMATCH"),
        ("payload_sha256", "SOURCE_READ_EVIDENCE_V4_PAYLOAD_SHA256_BINDING_MISMATCH"),
        (
            "payload_byte_count",
            "SOURCE_READ_EVIDENCE_V4_PAYLOAD_BYTE_COUNT_BINDING_MISMATCH",
        ),
        (
            "economic_event_time",
            "SOURCE_READ_EVIDENCE_V4_ECONOMIC_EVENT_TIME_BINDING_MISMATCH",
        ),
        (
            "producer_event_time",
            "SOURCE_READ_EVIDENCE_V4_PRODUCER_EVENT_TIME_BINDING_MISMATCH",
        ),
        ("available_at", "SOURCE_READ_EVIDENCE_V4_AVAILABLE_AT_BINDING_MISMATCH"),
    ],
)
def test_read_evidence_payload_and_clock_bindings_reject_tampering(
    field_name: str,
    reason: str,
) -> None:
    receipt = _build().receipt
    if field_name == "payload_byte_count":
        receipt["read_evidence"][field_name] += 1
    elif field_name == "payload_sha256":
        receipt["read_evidence"][field_name] = "c" * 64
    else:
        receipt["read_evidence"][field_name] = "tampered"
    _assert_validator_rejects(receipt, reason)


@pytest.mark.parametrize(
    ("field_name", "reason"),
    [
        ("source_label", "SOURCE_FINALITY_EVIDENCE_V4_SOURCE_LABEL_BINDING_MISMATCH"),
        ("payload_type", "SOURCE_FINALITY_EVIDENCE_V4_PAYLOAD_TYPE_BINDING_MISMATCH"),
        (
            "payload_sha256",
            "SOURCE_FINALITY_EVIDENCE_V4_PAYLOAD_SHA256_BINDING_MISMATCH",
        ),
        (
            "payload_byte_count",
            "SOURCE_FINALITY_EVIDENCE_V4_PAYLOAD_BYTE_COUNT_BINDING_MISMATCH",
        ),
        (
            "producer_event_time",
            "SOURCE_FINALITY_EVIDENCE_V4_PRODUCER_EVENT_TIME_BINDING_MISMATCH",
        ),
        (
            "consumer_observed_at",
            "SOURCE_FINALITY_EVIDENCE_V4_CONSUMER_OBSERVED_AT_BINDING_MISMATCH",
        ),
    ],
)
def test_finality_evidence_payload_and_clock_bindings_reject_tampering(
    field_name: str,
    reason: str,
) -> None:
    receipt = _build().receipt
    if field_name == "payload_byte_count":
        receipt["finality_evidence"][field_name] += 1
    elif field_name == "payload_sha256":
        receipt["finality_evidence"][field_name] = "c" * 64
    else:
        receipt["finality_evidence"][field_name] = "tampered"
    _assert_validator_rejects(receipt, reason)


def test_finality_type_final_flag_and_verifier_are_strict() -> None:
    _assert_builder_rejects(
        "SOURCE_FINALITY_EVIDENCE_V4_TYPE_INVALID",
        finality_type="VERSIONED_SNAPSHOT",
    )

    receipt = _build().receipt
    receipt["finality_evidence"]["event_final"] = False
    _assert_validator_rejects(receipt, "SOURCE_FINALITY_EVIDENCE_V4_NOT_FINAL")

    receipt = _build().receipt
    receipt["finality_evidence"]["verifier"] = "bad verifier with spaces"
    _assert_validator_rejects(receipt, "SOURCE_FINALITY_EVIDENCE_V4_VERIFIER_INVALID")


def test_extra_fields_mapping_subclasses_and_authorization_flip_fail_closed() -> None:
    receipt = _build().receipt
    receipt["unexpected"] = True
    _assert_validator_rejects(receipt, "SOURCE_RECEIPT_V4_FIELD_SET_MISMATCH")

    class DictSubclass(dict[str, Any]):
        pass

    _assert_validator_rejects(
        DictSubclass(_build().receipt),
        "SOURCE_RECEIPT_V4_NOT_EXACT_OBJECT",
    )

    receipt = _build().receipt
    receipt["trainer_admission_granted"] = True
    _assert_validator_rejects(
        receipt,
        "SOURCE_RECEIPT_V4_TRAINER_ADMISSION_GRANTED_MUST_BE_FALSE",
    )

    receipt = _build().receipt
    receipt["read_evidence"]["read_locator_type"] = []
    _assert_validator_rejects(
        receipt,
        "SOURCE_READ_EVIDENCE_V4_LOCATOR_TYPE_INVALID",
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"payload_byte_count": 0}, "SOURCE_RECEIPT_V4_PAYLOAD_BYTE_COUNT_INVALID"),
        (
            {"payload_byte_count": MAX_SOURCE_PAYLOAD_BYTES + 1},
            "SOURCE_RECEIPT_V4_PAYLOAD_BYTE_COUNT_INVALID",
        ),
        ({"payload_sha256": "A" * 64}, "SOURCE_RECEIPT_V4_PAYLOAD_SHA256_INVALID"),
        ({"read_locator": " bad "}, "SOURCE_READ_EVIDENCE_V4_LOCATOR_INVALID"),
        (
            {"read_locator_type": "REDIS_MUTABLE_VALUE"},
            "SOURCE_READ_EVIDENCE_V4_LOCATOR_TYPE_INVALID",
        ),
    ],
)
def test_resource_identity_and_locator_inputs_are_strict(
    overrides: dict[str, Any],
    reason: str,
) -> None:
    _assert_builder_rejects(reason, **overrides)


def test_v3_feature_snapshot_builder_mechanically_rejects_v4_receipt() -> None:
    receipt = _build().receipt
    economic_close = receipt["economic_event_time"]
    decision = _utc(BASE + timedelta(seconds=61))

    with pytest.raises(FeatureSnapshotValidationError) as exc_info:
        build_feature_snapshot_record(
            provenance_classification=PROVENANCE_CANONICAL_V3,
            legacy_v1_snapshot_id=None,
            symbol="BTCUSDT",
            timeframe="1m",
            feature_snapshot_id="v4-receipt-must-not-enter-v3",
            tensor_decision_time=decision,
            temporal_rejection_reasons=[],
            ordered_feature_names=["open"],
            feature_values=[100.0],
            missing_mask=[0],
            stale_mask=[0],
            source_availability_mask=[1],
            ordered_feature_source_labels=[receipt["source_label"]],
            feature_source_receipt_sha256s=[receipt["receipt_sha256"]],
            source_read_receipts=[receipt],
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=["REQUIRED"],
            original_tensor_id="v4-receipt-v3-rejection-fixture",
            source_lineage_material={"fixture": "v4-receipt-v3-rejection"},
            feature_cutoff=economic_close,
            masa_feature_cutoff=economic_close,
            ppo_feature_cutoff=economic_close,
            ppo_decision_time=decision,
            generated_at=_utc(BASE + timedelta(seconds=60, milliseconds=750)),
        )

    assert "SOURCE_RECEIPT_FIELD_SET_MISMATCH" in exc_info.value.reasons
    assert "SOURCE_RECEIPT_SCHEMA_VERSION_MISMATCH" in exc_info.value.reasons
