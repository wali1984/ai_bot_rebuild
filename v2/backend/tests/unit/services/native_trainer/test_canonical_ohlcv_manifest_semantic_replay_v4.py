from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    MAX_SUFFIX_MANIFEST_BYTES,
    CanonicalOhlcvAtomicReceiptCapture,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_manifest_semantic_replay_v4 import (
    CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_DOWNSTREAM_STATUS,
    CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_EVIDENCE_CLASSIFICATION,
    CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_SCHEMA_VERSION,
    CanonicalOhlcvManifestSemanticReplayV4Error,
    replay_canonical_ohlcv_manifest_semantics_v4,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_reader_v4 import (
    ImmutableSourcePayloadReaderV4,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    TIMEFRAME_DURATION_MS,
)
from v2.backend.tests.unit.services.native_trainer import (
    test_canonical_ohlcv_atomic_receipt_adapter as capture_support,
)

SYMBOL = capture_support.SYMBOL
TIMEFRAME = capture_support.TIMEFRAME

_FALSE_AUTHORITY_FIELDS = (
    "factory_capture_authenticated",
    "factory_receipt_authenticated",
    "factory_authorized",
    "upstream_producer_authenticated",
    "atomic_transport_authenticated",
    "transport_authenticated",
    "transport_authenticity_attested",
    "source_attestation_authenticated",
    "ledger_authorized",
    "ledger_receipt_emitted",
    "durable_ledger_appended",
    "durable_ledger_membership_verified",
    "dependency_authorized",
    "dependency_manifest_bound",
    "dependency_complete",
    "per_field_receipt_bound",
    "source_scope_complete",
    "feature_authorized",
    "feature_snapshot_authorized",
    "feature_snapshot_published",
    "feature_publication_receipt_emitted",
    "consumer_eligible",
    "trainer_admission_granted",
    "trainer_admission_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "runtime_wired",
)


def _decision_time(consumer_observed_at: str, *, delta_ms: int = 1_000) -> str:
    observed = datetime.strptime(
        consumer_observed_at,
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ).replace(tzinfo=UTC)
    return (
        (observed + timedelta(milliseconds=delta_ms))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _replay(
    capture: CanonicalOhlcvAtomicReceiptCapture,
    store: ImmutableSourcePayloadStore,
    *,
    manifest_address: SourcePayloadAddress | None = None,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    decision_time: str | None = None,
) -> dict[str, object]:
    result = replay_canonical_ohlcv_manifest_semantics_v4(
        cas_root=str(store.root_path),
        manifest_address=manifest_address or capture.suffix_manifest_address,
        expected_symbol=symbol,
        expected_timeframe=timeframe,
        decision_time=decision_time or _decision_time(capture.consumer_observed_at),
    )
    return dict(result)


def _put_bytes(store: ImmutableSourcePayloadStore, payload: bytes) -> SourcePayloadAddress:
    return store.put(
        payload,
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_byte_count=len(payload),
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _put_manifest(
    store: ImmutableSourcePayloadStore,
    manifest: dict[str, Any],
) -> SourcePayloadAddress:
    return _put_bytes(store, _canonical_bytes(manifest))


def _address_material(address: SourcePayloadAddress) -> dict[str, object]:
    return {
        "schema_version": address.schema_version,
        "payload_sha256": address.payload_sha256,
        "payload_byte_count": address.payload_byte_count,
        "relative_path": address.relative_path,
    }


def test_reopens_manifest_full_payload_and_every_selected_row_then_stays_audit_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    calls: list[str] = []
    original_read = ImmutableSourcePayloadReaderV4.read

    def recording_read(
        self: ImmutableSourcePayloadReaderV4,
        payload_sha256: str,
        *,
        expected_byte_count: int | None = None,
        address: SourcePayloadAddress | None = None,
    ) -> bytes:
        calls.append(payload_sha256)
        return original_read(
            self,
            payload_sha256,
            expected_byte_count=expected_byte_count,
            address=address,
        )

    monkeypatch.setattr(ImmutableSourcePayloadReaderV4, "read", recording_read)
    result = _replay(capture, store)

    assert calls[0] == capture.suffix_manifest_address.payload_sha256
    assert calls[1] == capture.full_source_payload_address.payload_sha256
    assert calls[2:] == [
        selected.source_payload_address.payload_sha256 for selected in capture.selected_candles
    ]
    assert len(calls) == capture.selected_row_count + 2
    assert result["schema_version"] == (CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_SCHEMA_VERSION)
    assert result["evidence_classification"] == (
        CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_EVIDENCE_CLASSIFICATION
    )
    assert result["downstream_status"] == (
        CANONICAL_OHLCV_MANIFEST_SEMANTIC_REPLAY_V4_DOWNSTREAM_STATUS
    )
    assert result["manifest_sha256"] == capture.suffix_manifest_address.payload_sha256
    assert result["full_source_payload_sha256"] == (
        capture.full_source_payload_address.payload_sha256
    )
    assert result["selected_row_count"] == capture.selected_row_count
    assert result["generated_at"] is None
    assert result["execution_time"] is None
    assert result["audit_only"] is True
    assert all(result[name] is False for name in _FALSE_AUTHORITY_FIELDS)
    for field_name in (
        "manifest_cas_reopened",
        "full_source_payload_cas_reopened",
        "every_selected_row_cas_reopened",
        "manifest_exact_canonical_json_verified",
        "content_addresses_recomputed",
        "exact_row_spans_recomputed",
        "committed_ohlcv_30_field_schema_replayed",
        "complete_contiguous_suffix_recomputed",
        "every_source_read_receipt_revalidated",
        "source_clocks_and_finality_recomputed",
        "decision_context_bound",
    ):
        assert result[field_name] is True
    assert len(cast(str, result["semantic_replay_sha256"])) == 64

    immutable = replay_canonical_ohlcv_manifest_semantics_v4(
        cas_root=str(store.root_path),
        manifest_address=capture.suffix_manifest_address,
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        decision_time=_decision_time(capture.consumer_observed_at),
    )
    with pytest.raises(TypeError):
        cast(Any, immutable)["trainer_admission_authorized"] = True


@pytest.mark.parametrize("kind", ["duplicate", "float", "nonfinite", "extra"])
def test_noncanonical_duplicate_float_nonfinite_and_extra_manifest_fields_fail_closed(
    tmp_path: Path,
    kind: str,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    manifest = capture.suffix_manifest
    if kind == "duplicate":
        payload = (
            b'{"atomic_batch_id":"attacker-duplicate",'
            + capture.suffix_manifest_json.encode("ascii")[1:]
        )
    elif kind == "float":
        manifest["source_pttl_ms"] = 600_000.0
        payload = _canonical_bytes(manifest)
    elif kind == "nonfinite":
        manifest["source_pttl_ms"] = float("nan")
        payload = json.dumps(
            manifest,
            ensure_ascii=True,
            allow_nan=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    else:
        manifest["attacker_extra_field"] = False
        payload = _canonical_bytes(manifest)
    forged_address = _put_bytes(store, payload)

    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_manifest_json_invalid",
    ):
        _replay(capture, store, manifest_address=forged_address)


def test_stale_tail_reuse_and_cross_symbol_or_timeframe_identity_fail_closed(
    tmp_path: Path,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    stale_decision = _decision_time(
        capture.consumer_observed_at,
        delta_ms=TIMEFRAME_DURATION_MS[TIMEFRAME],
    )
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_decision_suffix_stale_or_invalid",
    ):
        _replay(capture, store, decision_time=stale_decision)

    for symbol, timeframe in (("ETHUSDT", TIMEFRAME), (SYMBOL, "5m")):
        with pytest.raises(
            CanonicalOhlcvManifestSemanticReplayV4Error,
            match="canonical_ohlcv_manifest_replay_source_identity_invalid",
        ):
            _replay(capture, store, symbol=symbol, timeframe=timeframe)


def test_partial_row_cas_substitution_is_rejected_before_row_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    manifest = capture.suffix_manifest
    first = cast(dict[str, Any], cast(list[Any], manifest["selected_rows"])[0])
    full_payload = capture.exact_full_source_payload_bytes
    start = cast(int, first["byte_start"])
    end = cast(int, first["byte_end_exclusive"])
    partial_address = _put_bytes(store, full_payload[start : end - 1])
    first["source_payload_cas_address"] = _address_material(partial_address)
    forged_manifest_address = _put_manifest(store, manifest)
    calls: list[str] = []
    original_read = ImmutableSourcePayloadReaderV4.read

    def recording_read(
        self: ImmutableSourcePayloadReaderV4,
        payload_sha256: str,
        *,
        expected_byte_count: int | None = None,
        address: SourcePayloadAddress | None = None,
    ) -> bytes:
        calls.append(payload_sha256)
        return original_read(
            self,
            payload_sha256,
            expected_byte_count=expected_byte_count,
            address=address,
        )

    monkeypatch.setattr(ImmutableSourcePayloadReaderV4, "read", recording_read)
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_selected_row_address_invalid",
    ):
        _replay(capture, store, manifest_address=forged_manifest_address)
    assert partial_address.payload_sha256 not in calls


def test_valid_receipt_from_another_row_cannot_be_substituted(
    tmp_path: Path,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    manifest = capture.suffix_manifest
    rows = cast(list[dict[str, Any]], manifest["selected_rows"])
    rows[0]["source_read_receipt_v4"] = rows[1]["source_read_receipt_v4"]
    forged_manifest_address = _put_manifest(store, manifest)

    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_source_read_receipt_invalid",
    ):
        _replay(capture, store, manifest_address=forged_manifest_address)


def test_suffix_digest_and_exact_span_metadata_are_independently_recomputed(
    tmp_path: Path,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    manifest = capture.suffix_manifest
    manifest["binding_selection_sha256"] = "f" * 64
    forged_summary = _put_manifest(store, manifest)
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_suffix_summary_invalid",
    ):
        _replay(capture, store, manifest_address=forged_summary)

    manifest = capture.suffix_manifest
    first = cast(dict[str, Any], cast(list[Any], manifest["selected_rows"])[0])
    first["byte_start"] = cast(int, first["byte_start"]) + 1
    forged_span = _put_manifest(store, manifest)
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_selected_row_binding_invalid",
    ):
        _replay(capture, store, manifest_address=forged_span)


def test_exact_builtin_inputs_and_manifest_address_type_are_required(
    tmp_path: Path,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)

    class _String(str):
        pass

    class _Address(SourcePayloadAddress):
        pass

    decision = _decision_time(capture.consumer_observed_at)
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_cas_root_invalid",
    ):
        replay_canonical_ohlcv_manifest_semantics_v4(
            cas_root=_String(str(store.root_path)),
            manifest_address=capture.suffix_manifest_address,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            decision_time=decision,
        )
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_decision_context_invalid",
    ):
        replay_canonical_ohlcv_manifest_semantics_v4(
            cas_root=str(store.root_path),
            manifest_address=capture.suffix_manifest_address,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            decision_time=_String(decision),
        )
    source = capture.suffix_manifest_address
    polymorphic_address = _Address(
        schema_version=SOURCE_PAYLOAD_ADDRESS_SCHEMA_VERSION,
        payload_sha256=source.payload_sha256,
        payload_byte_count=source.payload_byte_count,
        relative_path=source.relative_path,
    )
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_manifest_address_invalid",
    ):
        replay_canonical_ohlcv_manifest_semantics_v4(
            cas_root=str(store.root_path),
            manifest_address=polymorphic_address,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            decision_time=decision,
        )


def test_exact_but_uninitialized_manifest_address_is_totalized(tmp_path: Path) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    uninitialized = object.__new__(SourcePayloadAddress)

    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_manifest_address_invalid",
    ):
        replay_canonical_ohlcv_manifest_semantics_v4(
            cas_root=str(store.root_path),
            manifest_address=uninitialized,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            decision_time=_decision_time(capture.consumer_observed_at),
        )


def test_manifest_address_is_detached_before_read_and_later_slot_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    source = capture.suffix_manifest_address
    caller_address = SourcePayloadAddress(
        schema_version=source.schema_version,
        payload_sha256=source.payload_sha256,
        payload_byte_count=source.payload_byte_count,
        relative_path=source.relative_path,
    )
    original_digest = source.payload_sha256
    original_count = source.payload_byte_count
    original_read = ImmutableSourcePayloadReaderV4.read
    mutated = False
    detached_mutated_after_read = False

    def mutate_after_snapshot(
        self: ImmutableSourcePayloadReaderV4,
        payload_sha256: str,
        *,
        expected_byte_count: int | None = None,
        address: SourcePayloadAddress | None = None,
    ) -> bytes:
        nonlocal detached_mutated_after_read, mutated
        manifest_call = not mutated
        if manifest_call:
            mutated = True
            object.__setattr__(caller_address, "payload_sha256", "f" * 64)
            object.__setattr__(caller_address, "payload_byte_count", 1)
            object.__setattr__(caller_address, "relative_path", f"sha256/ff/{'f' * 64}")
            assert address is not caller_address
        payload = original_read(
            self,
            payload_sha256,
            expected_byte_count=expected_byte_count,
            address=address,
        )
        if manifest_call:
            assert address is not None
            object.__setattr__(address, "payload_sha256", "e" * 64)
            object.__setattr__(address, "payload_byte_count", 2)
            object.__setattr__(address, "relative_path", f"sha256/ee/{'e' * 64}")
            detached_mutated_after_read = True
        return payload

    monkeypatch.setattr(ImmutableSourcePayloadReaderV4, "read", mutate_after_snapshot)
    result = replay_canonical_ohlcv_manifest_semantics_v4(
        cas_root=str(store.root_path),
        manifest_address=caller_address,
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        decision_time=_decision_time(capture.consumer_observed_at),
    )

    assert mutated is True
    assert detached_mutated_after_read is True
    assert caller_address.payload_sha256 == "f" * 64
    assert result["manifest_sha256"] == original_digest
    assert result["manifest_byte_count"] == original_count


def test_cas_object_counts_are_bounded_before_each_corresponding_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    calls: list[str] = []
    original_read = ImmutableSourcePayloadReaderV4.read

    def recording_read(
        self: ImmutableSourcePayloadReaderV4,
        payload_sha256: str,
        *,
        expected_byte_count: int | None = None,
        address: SourcePayloadAddress | None = None,
    ) -> bytes:
        calls.append(payload_sha256)
        return original_read(
            self,
            payload_sha256,
            expected_byte_count=expected_byte_count,
            address=address,
        )

    monkeypatch.setattr(ImmutableSourcePayloadReaderV4, "read", recording_read)
    source = capture.suffix_manifest_address
    oversized_manifest = SourcePayloadAddress(
        schema_version=source.schema_version,
        payload_sha256=source.payload_sha256,
        payload_byte_count=MAX_SUFFIX_MANIFEST_BYTES + 1,
        relative_path=source.relative_path,
    )
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_manifest_address_invalid",
    ):
        replay_canonical_ohlcv_manifest_semantics_v4(
            cas_root=str(store.root_path),
            manifest_address=oversized_manifest,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            decision_time=_decision_time(capture.consumer_observed_at),
        )
    assert calls == []

    manifest = capture.suffix_manifest
    full_address = cast(dict[str, Any], manifest["full_source_payload_cas_address"])
    full_address["payload_byte_count"] = MAX_OHLCV_CLOSED_PAYLOAD_BYTES + 1
    oversized_full_manifest = _put_manifest(store, manifest)
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_full_payload_address_invalid",
    ):
        _replay(capture, store, manifest_address=oversized_full_manifest)
    assert calls == [oversized_full_manifest.payload_sha256]

    calls.clear()
    manifest = capture.suffix_manifest
    first = cast(dict[str, Any], cast(list[Any], manifest["selected_rows"])[0])
    row_address = cast(dict[str, Any], first["source_payload_cas_address"])
    exact_span_count = cast(int, first["byte_end_exclusive"]) - cast(int, first["byte_start"])
    row_address["payload_byte_count"] = exact_span_count - 1
    wrong_row_count_manifest = _put_manifest(store, manifest)
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_selected_row_address_invalid",
    ):
        _replay(capture, store, manifest_address=wrong_row_count_manifest)
    assert calls == [
        wrong_row_count_manifest.payload_sha256,
        capture.full_source_payload_address.payload_sha256,
    ]


def test_decision_before_capture_observation_fails_clock_binding(tmp_path: Path) -> None:
    capture, _, store = capture_support._capture(tmp_path)
    before = _decision_time(capture.consumer_observed_at, delta_ms=-1)
    with pytest.raises(
        CanonicalOhlcvManifestSemanticReplayV4Error,
        match="canonical_ohlcv_manifest_replay_consumer_clock_invalid",
    ):
        _replay(capture, store, decision_time=before)
