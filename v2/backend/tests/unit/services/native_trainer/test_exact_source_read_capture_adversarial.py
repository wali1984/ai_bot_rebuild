from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FEATURE_REQUIREMENT_POLICY_ID,
    PROVENANCE_CANONICAL_V3,
    SOURCE_READ_RECEIPT_SCHEMA_VERSION,
    FeatureSnapshotValidationError,
    build_feature_snapshot_record,
    canonical_json,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.exact_source_read_capture import (
    EXACT_SOURCE_CAPTURE_DOWNSTREAM_STATUS,
    EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION,
    EXACT_SOURCE_CAPTURE_SCHEMA_VERSION,
    SOURCE_ADAPTER_ATTESTATION_STATUS,
    SOURCE_ADAPTER_CANDIDATE_EVIDENCE_CLASSIFICATION,
    SOURCE_ADAPTER_CANDIDATE_IDENTITY_SCHEMA_VERSION,
    SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION,
    SOURCE_KIND_FUNDING_SNAPSHOT,
    SOURCE_KIND_LIQUIDATION_AGGREGATE,
    SOURCE_KIND_LIQUIDATION_EVENT,
    SOURCE_KIND_OHLCV_CLOSED_INTERVAL,
    SOURCE_KIND_OPEN_INTEREST_SNAPSHOT,
    SOURCE_KIND_ORDERBOOK_SNAPSHOT,
    SOURCE_KIND_PAPER_POSITION_STATE,
    ExactSourceReadCaptureIntegrityError,
    ExactSourceReadCaptureValidationError,
    capture_exact_source_read,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadCollisionError,
)

BASE = datetime(2026, 7, 19, tzinfo=UTC)


def _utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _capture_kwargs(
    tmp_path: Path,
    *,
    source_kind: str = SOURCE_KIND_OHLCV_CLOSED_INTERVAL,
    store: ImmutableSourcePayloadStore | None = None,
    payload: bytes = b'{"exact":"source bytes", "spacing":true}\n',
) -> dict[str, Any]:
    event = BASE + timedelta(seconds=59, milliseconds=999)
    is_interval = source_kind == SOURCE_KIND_OHLCV_CLOSED_INTERVAL
    finality_types = {
        SOURCE_KIND_OHLCV_CLOSED_INTERVAL: "CLOSED_INTERVAL",
        SOURCE_KIND_ORDERBOOK_SNAPSHOT: "VERSIONED_SNAPSHOT",
        SOURCE_KIND_FUNDING_SNAPSHOT: "VERSIONED_SNAPSHOT",
        SOURCE_KIND_OPEN_INTEREST_SNAPSHOT: "VERSIONED_SNAPSHOT",
        SOURCE_KIND_LIQUIDATION_EVENT: "IMMUTABLE_EVENT",
        SOURCE_KIND_LIQUIDATION_AGGREGATE: "VERSIONED_SNAPSHOT",
        SOURCE_KIND_PAPER_POSITION_STATE: "VERSIONED_SNAPSHOT",
    }
    labels = {
        SOURCE_KIND_OHLCV_CLOSED_INTERVAL: "ohlcv_closed:1m",
        SOURCE_KIND_ORDERBOOK_SNAPSHOT: "orderbook",
        SOURCE_KIND_FUNDING_SNAPSHOT: "funding",
        SOURCE_KIND_OPEN_INTEREST_SNAPSHOT: "open_interest",
        SOURCE_KIND_LIQUIDATION_EVENT: "liquidation_event",
        SOURCE_KIND_LIQUIDATION_AGGREGATE: "liquidation_aggregate",
        SOURCE_KIND_PAPER_POSITION_STATE: "paper_position_state",
    }
    return {
        "source_payload_store": store or ImmutableSourcePayloadStore(tmp_path / "source-payloads"),
        "exact_source_payload_bytes": payload,
        "source_kind": source_kind,
        "source_label": labels[source_kind],
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "event_time": _utc(event),
        "ingested_at": _utc(event + timedelta(milliseconds=11)),
        "available_at": _utc(event + timedelta(milliseconds=22)),
        "consumer_observed_at": _utc(event + timedelta(milliseconds=44)),
        "feature_cutoff": _utc(event),
        "decision_time": _utc(event + timedelta(milliseconds=55)),
        "source_finality_confirmed": True,
        "read_locator_type": "REDIS_VERSIONED_VALUE",
        "read_locator": "v2:market:source:BTCUSDT:1m",
        "read_locator_version": "generation:0000000000000001",
        "finality_type": finality_types[source_kind],
        "finality_cutoff": _utc(event),
        "finality_verified_at": _utc(event + timedelta(milliseconds=33)),
        "finality_verifier": "trainer-source-finality-adapter-v1",
        "interval_open_time": _utc(BASE) if is_interval else None,
        "interval_close_time": _utc(event) if is_interval else None,
    }


def _capture(tmp_path: Path, **overrides: Any):
    source_kind = overrides.pop("source_kind", SOURCE_KIND_OHLCV_CLOSED_INTERVAL)
    kwargs = _capture_kwargs(tmp_path, source_kind=source_kind)
    kwargs.update(overrides)
    return capture_exact_source_read(**kwargs)


def _assert_existing_ledger_rejects(
    candidate: dict[str, Any],
    *,
    expect_schema_mismatch: bool = True,
) -> None:
    cutoff = BASE + timedelta(seconds=59, milliseconds=999)
    with pytest.raises(FeatureSnapshotValidationError) as exc_info:
        build_feature_snapshot_record(
            provenance_classification=PROVENANCE_CANONICAL_V3,
            legacy_v1_snapshot_id=None,
            symbol="BTCUSDT",
            timeframe="1m",
            feature_snapshot_id="candidate-bypass-fixture",
            tensor_decision_time=_utc(BASE + timedelta(seconds=61)),
            temporal_rejection_reasons=[],
            ordered_feature_names=["open"],
            feature_values=[1.0],
            missing_mask=[0],
            stale_mask=[0],
            source_availability_mask=[1],
            ordered_feature_source_labels=[str(candidate["source_label"])],
            feature_source_receipt_sha256s=[str(candidate["adapter_candidate_binding_sha256"])],
            source_read_receipts=[candidate],
            feature_requirement_policy_id=FEATURE_REQUIREMENT_POLICY_ID,
            ordered_feature_requirement_classes=["REQUIRED"],
            original_tensor_id="candidate-bypass-tensor",
            source_lineage_material={},
            feature_cutoff=_utc(cutoff),
            masa_feature_cutoff=_utc(cutoff),
            ppo_feature_cutoff=_utc(cutoff),
            ppo_decision_time=_utc(BASE + timedelta(seconds=61, milliseconds=1)),
            generated_at=_utc(BASE + timedelta(seconds=60, milliseconds=500)),
        )
    assert "SOURCE_RECEIPT_FIELD_SET_MISMATCH" in exc_info.value.reasons
    if expect_schema_mismatch:
        assert "SOURCE_RECEIPT_SCHEMA_VERSION_MISMATCH" in exc_info.value.reasons


def _rebound_candidate_result(
    result: Any,
    *,
    field: str,
    value: str,
) -> Any:
    candidate = result.future_source_adapter_candidate
    candidate[field] = value
    identity_keys = (
        "capture_record_id",
        "capture_binding_sha256",
        "capture_binding_cas_address",
        "source_payload_cas_address",
        "source_kind",
        "source_label",
        "payload_type",
        "symbol",
        "timeframe",
        "payload_sha256",
        "payload_byte_count",
        "event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "decision_time",
        "interval_open_time",
        "interval_close_time",
        "source_finality_confirmed",
        "read_locator_type",
        "read_locator",
        "read_locator_version",
        "finality_type",
        "finality_cutoff",
        "finality_verified_at",
        "finality_verifier",
    )
    identity = {
        "schema_version": SOURCE_ADAPTER_CANDIDATE_IDENTITY_SCHEMA_VERSION,
        **{key: candidate[key] for key in identity_keys},
    }
    identity_sha256 = stable_sha256(identity)
    candidate["adapter_candidate_identity_sha256"] = identity_sha256
    candidate["adapter_candidate_id"] = f"trainer_source_adapter_candidate_v1_{identity_sha256}"
    candidate_material = {
        key: item for key, item in candidate.items() if key != "adapter_candidate_binding_sha256"
    }
    candidate["adapter_candidate_binding_sha256"] = stable_sha256(candidate_material)
    candidate_json = canonical_json(candidate)
    candidate_bytes = candidate_json.encode("ascii")
    candidate_address = result.source_payload_store.put(candidate_bytes)
    return replace(
        result,
        adapter_candidate_id=candidate["adapter_candidate_id"],
        adapter_candidate_binding_sha256=candidate["adapter_candidate_binding_sha256"],
        adapter_candidate_json=candidate_json,
        adapter_candidate_address=candidate_address,
    )


def test_exact_bytes_are_content_addressed_and_candidate_is_not_ledger_v3(
    tmp_path: Path,
) -> None:
    payload = b' {"b":2,"a":1}\r\n\x00'
    result = _capture(tmp_path, exact_source_payload_bytes=payload)
    binding = result.artifact_binding
    candidate = result.future_source_adapter_candidate
    digest = hashlib.sha256(payload).hexdigest()

    assert result.evidence_classification == EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION
    assert binding["schema_version"] == EXACT_SOURCE_CAPTURE_SCHEMA_VERSION
    assert binding["evidence_classification"] == (EXACT_SOURCE_CAPTURE_EVIDENCE_CLASSIFICATION)
    assert binding["downstream_status"] == EXACT_SOURCE_CAPTURE_DOWNSTREAM_STATUS
    assert binding["payload_sha256"] == digest
    assert binding["payload_byte_count"] == len(payload)
    assert result.source_payload_address.payload_sha256 == digest
    assert result.source_payload_store.get(digest, expected_byte_count=len(payload)) == payload
    assert candidate["schema_version"] == SOURCE_ADAPTER_CANDIDATE_SCHEMA_VERSION
    assert candidate["schema_version"] != SOURCE_READ_RECEIPT_SCHEMA_VERSION
    assert candidate["evidence_classification"] == (
        SOURCE_ADAPTER_CANDIDATE_EVIDENCE_CLASSIFICATION
    )
    assert candidate["adapter_attestation_status"] == (SOURCE_ADAPTER_ATTESTATION_STATUS)
    assert candidate["target_ledger_receipt_schema_version"] == (SOURCE_READ_RECEIPT_SCHEMA_VERSION)
    assert candidate["payload_sha256"] == digest
    assert candidate["payload_byte_count"] == len(payload)
    assert candidate["read_locator"] == binding["read_locator"]
    assert candidate["read_locator_version"] == binding["read_locator_version"]
    assert candidate["consumer_observed_at"] == binding["consumer_observed_at"]
    assert candidate["capture_record_id"] == result.capture_record_id
    assert candidate["capture_binding_sha256"] == result.binding_sha256
    assert candidate["source_payload_cas_address"]["payload_sha256"] == digest
    assert candidate["capture_binding_cas_address"]["payload_sha256"] == (
        result.binding_address.payload_sha256
    )
    assert {
        "receipt_sha256",
        "read_evidence",
        "finality_evidence",
        "receipt_kind",
    }.isdisjoint(candidate)


def test_binding_and_api_emit_no_consumer_ready_or_postcommit_clock(
    tmp_path: Path,
) -> None:
    result = _capture(tmp_path)
    binding = result.artifact_binding
    candidate = result.future_source_adapter_candidate
    signature = inspect.signature(capture_exact_source_read)

    forbidden = {
        key
        for key in (*binding, *candidate)
        if "consumer_ready" in key
        or "admission_eligible" in key
        or "postcommit" in key
        or key.startswith("trainer_ready")
    }
    assert forbidden == set()
    assert "postcommit_observed_at" not in signature.parameters
    assert "consumer_observed_at" in signature.parameters
    assert signature.parameters["consumer_observed_at"].default is inspect.Parameter.empty
    assert "source_read_receipt_candidate" not in binding
    assert "receipt_sha256" not in candidate


@pytest.mark.parametrize(
    "arbitrary_payload",
    [
        b"\x00\xffnot-json\x00",
        b'{"schema_version":"feature_source_consumer_read_receipt_v3"}',
        b"pickle-like-bytes:\x80\x04arbitrary",
    ],
)
def test_arbitrary_exact_bytes_cannot_bypass_existing_ledger_v3(
    tmp_path: Path,
    arbitrary_payload: bytes,
) -> None:
    result = _capture(tmp_path, exact_source_payload_bytes=arbitrary_payload)
    _assert_existing_ledger_rejects(result.future_source_adapter_candidate)


def test_shallow_schema_and_hash_masquerade_still_fails_ledger_v3(
    tmp_path: Path,
) -> None:
    result = _capture(tmp_path)
    candidate = result.future_source_adapter_candidate
    candidate["schema_version"] = SOURCE_READ_RECEIPT_SCHEMA_VERSION
    candidate["receipt_sha256"] = stable_sha256(candidate)

    _assert_existing_ledger_rejects(candidate, expect_schema_mismatch=False)


@pytest.mark.parametrize(
    ("source_kind", "expected_payload_type", "expected_finality_type"),
    [
        (
            SOURCE_KIND_OHLCV_CLOSED_INTERVAL,
            "EXACT_OHLCV_SOURCE_BYTES",
            "CLOSED_INTERVAL",
        ),
        (
            SOURCE_KIND_ORDERBOOK_SNAPSHOT,
            "EXACT_ORDERBOOK_SOURCE_BYTES",
            "VERSIONED_SNAPSHOT",
        ),
        (
            SOURCE_KIND_FUNDING_SNAPSHOT,
            "EXACT_FUNDING_SOURCE_BYTES",
            "VERSIONED_SNAPSHOT",
        ),
        (
            SOURCE_KIND_OPEN_INTEREST_SNAPSHOT,
            "EXACT_OPEN_INTEREST_SOURCE_BYTES",
            "VERSIONED_SNAPSHOT",
        ),
        (
            SOURCE_KIND_LIQUIDATION_EVENT,
            "EXACT_LIQUIDATION_EVENT_SOURCE_BYTES",
            "IMMUTABLE_EVENT",
        ),
        (
            SOURCE_KIND_LIQUIDATION_AGGREGATE,
            "EXACT_LIQUIDATION_AGGREGATE_SOURCE_BYTES",
            "VERSIONED_SNAPSHOT",
        ),
        (
            SOURCE_KIND_PAPER_POSITION_STATE,
            "EXACT_PAPER_POSITION_STATE_BYTES",
            "VERSIONED_SNAPSHOT",
        ),
    ],
)
def test_every_supported_source_kind_has_exact_payload_and_finality_type(
    tmp_path: Path,
    source_kind: str,
    expected_payload_type: str,
    expected_finality_type: str,
) -> None:
    result = _capture(tmp_path, source_kind=source_kind)
    binding = result.artifact_binding
    candidate = result.future_source_adapter_candidate

    assert binding["source_kind"] == source_kind
    assert binding["payload_type"] == expected_payload_type
    assert binding["finality_type"] == expected_finality_type
    assert candidate["source_kind"] == source_kind
    assert candidate["payload_type"] == expected_payload_type
    assert candidate["finality_type"] == expected_finality_type


def test_equal_complete_capture_retries_are_stable_in_same_store(tmp_path: Path) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    kwargs = _capture_kwargs(tmp_path, store=store)

    first = capture_exact_source_read(**kwargs)
    second = capture_exact_source_read(**kwargs)

    assert first.capture_record_id == second.capture_record_id
    assert first.binding_sha256 == second.binding_sha256
    assert first.source_payload_address == second.source_payload_address
    assert first.binding_address == second.binding_address
    assert first.binding_json == second.binding_json
    assert first.adapter_candidate_id == second.adapter_candidate_id
    assert first.adapter_candidate_binding_sha256 == (second.adapter_candidate_binding_sha256)
    assert first.adapter_candidate_address == second.adapter_candidate_address
    assert first.adapter_candidate_json == second.adapter_candidate_json


def test_same_capture_has_stable_record_across_roots_but_root_bound_binding(
    tmp_path: Path,
) -> None:
    first = capture_exact_source_read(
        **_capture_kwargs(
            tmp_path,
            store=ImmutableSourcePayloadStore(tmp_path / "first"),
        )
    )
    second = capture_exact_source_read(
        **_capture_kwargs(
            tmp_path,
            store=ImmutableSourcePayloadStore(tmp_path / "second"),
        )
    )

    assert first.capture_record_id == second.capture_record_id
    assert first.source_payload_address == second.source_payload_address
    assert first.binding_sha256 != second.binding_sha256
    assert first.binding_address != second.binding_address
    assert first.adapter_candidate_id != second.adapter_candidate_id
    assert first.adapter_candidate_address != second.adapter_candidate_address


def test_same_payload_with_different_observation_retains_payload_address_only(
    tmp_path: Path,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    first = capture_exact_source_read(**_capture_kwargs(tmp_path, store=store))
    kwargs = _capture_kwargs(tmp_path, store=store)
    kwargs["consumer_observed_at"] = _utc(BASE + timedelta(seconds=60, milliseconds=45))
    second = capture_exact_source_read(**kwargs)

    assert first.source_payload_address == second.source_payload_address
    assert first.capture_record_id != second.capture_record_id
    assert first.binding_address != second.binding_address
    assert first.adapter_candidate_address != second.adapter_candidate_address


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_kind", "UNKNOWN"),
        ("source_label", "bad label"),
        ("symbol", "btcusdt"),
        ("symbol", "BTC-USDT"),
        ("timeframe", "60s"),
        ("timeframe", "1d"),
        ("read_locator_type", "REDIS_GET"),
        ("read_locator", "v2 key with spaces"),
        ("read_locator_version", ""),
        ("finality_type", "VERSIONED_SNAPSHOT"),
        ("finality_verifier", "bad verifier"),
        ("source_finality_confirmed", False),
        ("source_finality_confirmed", 1),
    ],
)
def test_typed_identity_and_finality_fields_fail_closed(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    kwargs = _capture_kwargs(tmp_path)
    kwargs[field] = value

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


@pytest.mark.parametrize(
    "field",
    [
        "event_time",
        "ingested_at",
        "available_at",
        "consumer_observed_at",
        "feature_cutoff",
        "decision_time",
        "finality_cutoff",
        "finality_verified_at",
    ],
)
def test_every_required_clock_rejects_missing_naive_and_noncanonical_values(
    tmp_path: Path,
    field: str,
) -> None:
    for invalid in (None, "2026-07-19T00:00:00", "2026-07-19T00:00:00Z"):
        kwargs = _capture_kwargs(tmp_path)
        kwargs[field] = invalid
        with pytest.raises(ExactSourceReadCaptureValidationError):
            capture_exact_source_read(**kwargs)


@pytest.mark.parametrize(
    "overflowing_clock",
    [
        "0001-01-01T00:00:00.000000+14:00",
        "9999-12-31T23:59:59.999999-14:00",
    ],
)
def test_timezone_normalization_overflow_fails_closed(
    tmp_path: Path,
    overflowing_clock: str,
) -> None:
    kwargs = _capture_kwargs(tmp_path)
    kwargs["event_time"] = overflowing_clock

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        ("event_time", "ingested_at"),
        ("ingested_at", "available_at"),
        ("event_time", "finality_cutoff"),
        ("finality_cutoff", "available_at"),
        ("available_at", "finality_verified_at"),
        ("finality_verified_at", "consumer_observed_at"),
        ("event_time", "feature_cutoff"),
        ("feature_cutoff", "decision_time"),
        ("consumer_observed_at", "decision_time"),
    ],
)
def test_inverted_or_future_clock_pairs_fail_closed(
    tmp_path: Path,
    earlier: str,
    later: str,
) -> None:
    kwargs = _capture_kwargs(
        tmp_path,
        source_kind=SOURCE_KIND_ORDERBOOK_SNAPSHOT,
    )
    kwargs[earlier] = _utc(BASE + timedelta(minutes=10))
    kwargs[later] = _utc(BASE + timedelta(minutes=9))
    # Keep unrelated downstream clocks beyond the injected pair so the
    # contract failure remains an inversion, not an accidental missing clock.
    if later != "decision_time":
        kwargs["decision_time"] = _utc(BASE + timedelta(minutes=20))

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interval_open_time", None),
        ("interval_close_time", None),
        ("interval_open_time", _utc(BASE + timedelta(microseconds=1))),
        ("interval_close_time", _utc(BASE + timedelta(minutes=1))),
        ("interval_close_time", _utc(BASE + timedelta(seconds=59, milliseconds=998))),
    ],
)
def test_closed_candle_requires_exact_aligned_closed_interval(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    kwargs = _capture_kwargs(tmp_path)
    kwargs[field] = value
    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


def test_unfinished_or_future_candle_is_rejected(tmp_path: Path) -> None:
    kwargs = _capture_kwargs(tmp_path)
    kwargs["decision_time"] = _utc(BASE + timedelta(seconds=30))

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        (
            "finality_verified_at",
            "exact_source_candle_finality_verified_at_not_post_close",
        ),
        ("available_at", "exact_source_candle_available_at_not_post_close"),
        (
            "consumer_observed_at",
            "exact_source_candle_consumer_observed_at_not_post_close",
        ),
    ],
)
def test_closed_candle_post_close_clocks_reject_equality(
    tmp_path: Path,
    field: str,
    reason: str,
) -> None:
    kwargs = _capture_kwargs(tmp_path)
    kwargs[field] = kwargs["interval_close_time"]

    with pytest.raises(ExactSourceReadCaptureValidationError, match=reason):
        capture_exact_source_read(**kwargs)


def test_non_interval_source_rejects_candle_clocks(tmp_path: Path) -> None:
    kwargs = _capture_kwargs(
        tmp_path,
        source_kind=SOURCE_KIND_ORDERBOOK_SNAPSHOT,
    )
    kwargs["interval_open_time"] = _utc(BASE)

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


@pytest.mark.parametrize("payload", [None, "bytes", bytearray(b"bytes"), b""])
def test_payload_must_be_nonempty_exact_builtin_bytes(
    tmp_path: Path,
    payload: object,
) -> None:
    kwargs = _capture_kwargs(tmp_path)
    kwargs["exact_source_payload_bytes"] = payload

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


def test_store_payload_bound_is_enforced_before_publication(tmp_path: Path) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads", max_payload_bytes=4)
    kwargs = _capture_kwargs(tmp_path, store=store, payload=b"12345")

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


def test_binding_object_bound_is_enforced_before_payload_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads", max_payload_bytes=2_048)

    def forbidden_put(
        _self: ImmutableSourcePayloadStore,
        *_args: Any,
        **_kwargs: Any,
    ) -> SourcePayloadAddress:
        raise AssertionError("CAS put must not run when binding exceeds object bound")

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", forbidden_put)

    with pytest.raises(
        ExactSourceReadCaptureValidationError,
        match="exact_source_binding_size_limit_exceeded",
    ):
        capture_exact_source_read(**_capture_kwargs(tmp_path, store=store, payload=b"x"))


def test_adapter_candidate_bound_is_enforced_before_payload_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_store = ImmutableSourcePayloadStore(tmp_path / "root-a")
    baseline = capture_exact_source_read(
        **_capture_kwargs(tmp_path, store=baseline_store, payload=b"x")
    )
    binding_size = len(baseline.binding_json.encode("ascii"))
    candidate_size = len(baseline.adapter_candidate_json.encode("ascii"))
    assert candidate_size > binding_size

    store = ImmutableSourcePayloadStore(
        tmp_path / "root-b",
        max_payload_bytes=candidate_size - 1,
    )

    def forbidden_put(
        _self: ImmutableSourcePayloadStore,
        *_args: Any,
        **_kwargs: Any,
    ) -> SourcePayloadAddress:
        raise AssertionError("CAS put must not run when candidate exceeds object bound")

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", forbidden_put)

    with pytest.raises(
        ExactSourceReadCaptureValidationError,
        match="exact_source_adapter_candidate_size_limit_exceeded",
    ):
        capture_exact_source_read(**_capture_kwargs(tmp_path, store=store, payload=b"x"))


def test_invalid_metadata_creates_no_cas_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    def forbidden_put(
        _self: ImmutableSourcePayloadStore,
        *_args: Any,
        **_kwargs: Any,
    ) -> SourcePayloadAddress:
        raise AssertionError("CAS put must not run before metadata validation")

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", forbidden_put)
    kwargs = _capture_kwargs(tmp_path, store=store)
    kwargs["symbol"] = "bad"

    with pytest.raises(ExactSourceReadCaptureValidationError):
        capture_exact_source_read(**kwargs)


def test_payload_put_collision_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")

    def collision(
        _self: ImmutableSourcePayloadStore,
        *_args: Any,
        **_kwargs: Any,
    ) -> SourcePayloadAddress:
        raise SourcePayloadCollisionError("synthetic_collision")

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", collision)

    with pytest.raises(
        ExactSourceReadCaptureIntegrityError,
        match="exact_source_payload_cas_publication_failed",
    ):
        capture_exact_source_read(**_capture_kwargs(tmp_path, store=store))


@pytest.mark.parametrize(
    ("put_number", "expected_reason"),
    [
        (2, "exact_source_binding_cas_publication_failed"),
        (3, "exact_source_adapter_candidate_cas_publication_failed"),
    ],
)
def test_later_cas_object_collision_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    put_number: int,
    expected_reason: str,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    original_put = ImmutableSourcePayloadStore.put
    call_count = 0

    def collision_at_stage(
        self: ImmutableSourcePayloadStore,
        payload: bytes,
        **kwargs: Any,
    ) -> SourcePayloadAddress:
        nonlocal call_count
        call_count += 1
        if call_count == put_number:
            raise SourcePayloadCollisionError("synthetic_collision")
        return original_put(self, payload, **kwargs)

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", collision_at_stage)

    with pytest.raises(ExactSourceReadCaptureIntegrityError, match=expected_reason):
        capture_exact_source_read(**_capture_kwargs(tmp_path, store=store))


def test_fresh_payload_readback_corruption_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    original_get = ImmutableSourcePayloadStore.get
    payload = b"source-payload"
    digest = hashlib.sha256(payload).hexdigest()

    def corrupt_get(
        self: ImmutableSourcePayloadStore,
        payload_sha256: str,
        **kwargs: Any,
    ) -> bytes:
        value = original_get(self, payload_sha256, **kwargs)
        return b"corrupt" if payload_sha256 == digest else value

    monkeypatch.setattr(ImmutableSourcePayloadStore, "get", corrupt_get)
    kwargs = _capture_kwargs(tmp_path, store=store, payload=payload)

    with pytest.raises(
        ExactSourceReadCaptureIntegrityError,
        match="exact_source_payload_cas_exact_readback_mismatch",
    ):
        capture_exact_source_read(**kwargs)


@pytest.mark.parametrize(
    ("address_field", "expected_reason"),
    [
        ("binding_address", "exact_source_binding_cas_exact_readback_mismatch"),
        (
            "adapter_candidate_address",
            "exact_source_adapter_candidate_cas_exact_readback_mismatch",
        ),
    ],
)
def test_later_cas_fresh_readback_corruption_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    address_field: str,
    expected_reason: str,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    kwargs = _capture_kwargs(tmp_path, store=store)
    baseline = capture_exact_source_read(**kwargs)
    target_digest = getattr(baseline, address_field).payload_sha256
    original_get = ImmutableSourcePayloadStore.get

    def corrupt_get(
        self: ImmutableSourcePayloadStore,
        payload_sha256: str,
        **get_kwargs: Any,
    ) -> bytes:
        value = original_get(self, payload_sha256, **get_kwargs)
        return b"corrupt" if payload_sha256 == target_digest else value

    monkeypatch.setattr(ImmutableSourcePayloadStore, "get", corrupt_get)

    with pytest.raises(ExactSourceReadCaptureIntegrityError, match=expected_reason):
        capture_exact_source_read(**kwargs)


def test_forged_payload_address_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    original_put = ImmutableSourcePayloadStore.put
    call_count = 0

    def forged_put(
        self: ImmutableSourcePayloadStore,
        payload: bytes,
        **kwargs: Any,
    ) -> SourcePayloadAddress:
        nonlocal call_count
        address = original_put(self, payload, **kwargs)
        call_count += 1
        if call_count == 1:
            return replace(address, payload_byte_count=address.payload_byte_count + 1)
        return address

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", forged_put)

    with pytest.raises(
        ExactSourceReadCaptureIntegrityError,
        match="exact_source_cas_address_mismatch",
    ):
        capture_exact_source_read(**_capture_kwargs(tmp_path, store=store))


@pytest.mark.parametrize("put_number", [2, 3])
def test_forged_later_cas_address_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    put_number: int,
) -> None:
    store = ImmutableSourcePayloadStore(tmp_path / "payloads")
    original_put = ImmutableSourcePayloadStore.put
    call_count = 0

    def forged_put(
        self: ImmutableSourcePayloadStore,
        payload: bytes,
        **kwargs: Any,
    ) -> SourcePayloadAddress:
        nonlocal call_count
        address = original_put(self, payload, **kwargs)
        call_count += 1
        if call_count == put_number:
            return replace(
                address,
                payload_byte_count=address.payload_byte_count + 1,
            )
        return address

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", forged_put)

    with pytest.raises(
        ExactSourceReadCaptureIntegrityError,
        match="exact_source_cas_address_mismatch",
    ):
        capture_exact_source_read(**_capture_kwargs(tmp_path, store=store))


def test_result_revalidates_payload_and_binding_on_every_access(tmp_path: Path) -> None:
    result = _capture(tmp_path)
    original_json = result.binding_json
    parsed = json.loads(original_json)
    parsed["symbol"] = "ETHUSDT"
    forged_json = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    object.__setattr__(result, "binding_json", forged_json)

    with pytest.raises(ExactSourceReadCaptureIntegrityError):
        _ = result.artifact_binding


@pytest.mark.parametrize(
    ("field", "value"),
    [("symbol", "ETHUSDT"), ("timeframe", "5m")],
)
def test_fully_rehashed_adapter_candidate_cannot_rebind_symbol_or_timeframe(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    result = _capture(tmp_path)

    with pytest.raises(
        ExactSourceReadCaptureIntegrityError,
        match="exact_source_adapter_candidate_capture_binding_mismatch",
    ):
        _rebound_candidate_result(result, field=field, value=value)


def test_dataclass_replace_cannot_forge_binding_hash(tmp_path: Path) -> None:
    result = _capture(tmp_path)

    with pytest.raises(ExactSourceReadCaptureIntegrityError):
        replace(result, binding_sha256="0" * 64)


def test_returned_adapter_candidate_and_binding_are_fresh_copies(tmp_path: Path) -> None:
    result = _capture(tmp_path)
    candidate = result.future_source_adapter_candidate
    binding = result.artifact_binding
    candidate["source_label"] = "forged"
    binding["symbol"] = "ETHUSDT"

    assert result.future_source_adapter_candidate["source_label"] == ("ohlcv_closed:1m")
    assert result.artifact_binding["symbol"] == "BTCUSDT"


def test_binding_itself_is_content_addressed_and_exactly_readable(tmp_path: Path) -> None:
    result = _capture(tmp_path)
    binding_bytes = result.binding_json.encode("ascii")
    binding_digest = hashlib.sha256(binding_bytes).hexdigest()

    assert result.binding_address.payload_sha256 == binding_digest
    assert result.binding_address.payload_byte_count == len(binding_bytes)
    assert (
        result.source_payload_store.get(
            binding_digest,
            expected_byte_count=len(binding_bytes),
        )
        == binding_bytes
    )


def test_adapter_candidate_is_content_addressed_and_exactly_readable(
    tmp_path: Path,
) -> None:
    result = _capture(tmp_path)
    candidate_bytes = result.adapter_candidate_json.encode("ascii")
    candidate_digest = hashlib.sha256(candidate_bytes).hexdigest()

    assert result.adapter_candidate_address.payload_sha256 == candidate_digest
    assert result.adapter_candidate_address.payload_byte_count == len(candidate_bytes)
    assert (
        result.source_payload_store.get(
            candidate_digest,
            expected_byte_count=len(candidate_bytes),
        )
        == candidate_bytes
    )
