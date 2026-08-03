from __future__ import annotations

import hashlib
import json
import os
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_atomic_receipt_adapter as adapter_module,
)
from v2.backend.app.services.native_trainer.atomic_redis_source_reader import (
    MAX_SOURCE_PAYLOAD_BYTES,
    AtomicRedisSourceReadBatch,
    read_atomic_redis_sources,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS,
    CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION,
    CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
    CANONICAL_OHLCV_ROW_PAYLOAD_TYPE,
    CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
    CanonicalOhlcvAtomicCaptureIntegrityError,
    CanonicalOhlcvAtomicCaptureTransportError,
    CanonicalOhlcvAtomicCaptureValidationError,
    CanonicalOhlcvAtomicReceiptCapture,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.native_trainer.source_read_receipt_v4 import (
    SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "1m"
BASE_MS = 1_800_000_000_000
KEY = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
REDIS_TIME = (1_800_010_000, 123_456)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class _FakePipeline:
    def __init__(
        self,
        responses: list[object],
        *,
        events: list[str] | None = None,
        execute_failure: bool = False,
    ) -> None:
        self.responses = responses
        self.events = events
        self.execute_failure = execute_failure
        self.commands: list[tuple[object, ...]] = []
        self.reset_calls = 0
        self.close_calls = 0

    def type(self, key: str) -> _FakePipeline:
        self.commands.append(("TYPE", key))
        return self

    def getrange(self, key: str, start: int, end: int) -> _FakePipeline:
        self.commands.append(("GETRANGE", key, start, end))
        return self

    def pttl(self, key: str) -> _FakePipeline:
        self.commands.append(("PTTL", key))
        return self

    def time(self) -> _FakePipeline:
        self.commands.append(("TIME",))
        return self

    def execute(self) -> list[object]:
        if self.events is not None:
            self.events.append("execute")
        if self.execute_failure:
            raise RuntimeError("hostile transport detail")
        return list(self.responses)

    def reset(self) -> None:
        self.reset_calls += 1

    def close(self) -> None:
        self.close_calls += 1


class _FakeClient:
    def __init__(
        self,
        responses: list[object],
        *,
        events: list[str] | None = None,
        execute_failure: bool = False,
    ) -> None:
        self.pipeline_instance = _FakePipeline(
            responses,
            events=events,
            execute_failure=execute_failure,
        )
        self.transactions: list[bool] = []

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        self.transactions.append(transaction)
        return self.pipeline_instance


def _aligned_base() -> int:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    return (BASE_MS // duration) * duration


def _rest_source_row(open_time: int) -> list[object]:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    return [
        open_time,
        "100.0",
        "102.0",
        "99.0",
        "101.0",
        "12.0",
        open_time + duration - 1,
        "1206.0",
        10,
        "6.0",
        "603.0",
        "0",
    ]


def _canonical_rest(index: int) -> dict[str, Any]:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    open_time = _aligned_base() + index * duration
    close_time = open_time + duration - 1
    return canonical_from_binance_rest(
        _rest_source_row(open_time),
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        ingested_at=close_time + 200,
    ).to_dict()


def _canonical_wss(index: int) -> dict[str, Any]:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    open_time = _aligned_base() + index * duration
    close_time = open_time + duration - 1
    producer_event = close_time + 105
    message = {
        "E": producer_event,
        "k": {
            "s": SYMBOL,
            "i": TIMEFRAME,
            "t": open_time,
            "T": close_time,
            "o": "101.0",
            "h": "103.0",
            "l": "100.0",
            "c": "102.0",
            "v": "14.0",
            "q": "1428.0",
            "n": 12,
            "V": "7.0",
            "Q": "714.0",
            "B": "0",
            "x": True,
        },
    }
    return canonical_from_binance_wss(
        message,
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        ingested_at=producer_event + 127,
    ).to_dict()


def _rows_with_optional_prefix_gap(
    *,
    suffix_count: int = 71,
    prefix_gap: bool = True,
) -> list[dict[str, Any]]:
    if prefix_gap:
        prefix = [_canonical_rest(0), _canonical_rest(1)]
        first_suffix_index = 4
    else:
        prefix = []
        first_suffix_index = 0
    selected = [_canonical_rest(first_suffix_index)]
    selected.extend(
        _canonical_wss(index)
        for index in range(first_suffix_index + 1, first_suffix_index + suffix_count)
    )
    return [*prefix, *selected]


def _payload(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(rows, ensure_ascii=True, indent=2).encode("ascii")


def _datetime_ms(value: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=value)


def _observed_after(rows: list[dict[str, Any]], *, extra_ms: int = 500) -> datetime:
    return _datetime_ms(cast(int, rows[-1]["candle_close_time"]) + extra_ms)


def _client_for(
    payload: bytes,
    *,
    redis_type: bytes = b"string",
    pttl_ms: int = 600_000,
    events: list[str] | None = None,
    execute_failure: bool = False,
) -> _FakeClient:
    return _FakeClient(
        [redis_type, payload, pttl_ms, REDIS_TIME],
        events=events,
        execute_failure=execute_failure,
    )


def _capture(
    tmp_path: Path,
    *,
    rows: list[dict[str, Any]] | None = None,
    events: list[str] | None = None,
    observed_at: datetime | None = None,
) -> tuple[CanonicalOhlcvAtomicReceiptCapture, _FakeClient, ImmutableSourcePayloadStore]:
    source_rows = rows if rows is not None else _rows_with_optional_prefix_gap()
    payload = _payload(source_rows)
    client = _client_for(payload, events=events)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    def clock() -> datetime:
        if events is not None:
            events.append("clock")
        return observed_at or _observed_after(source_rows)

    result = capture_canonical_closed_ohlcv_atomic_receipts(
        client,
        store,
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        consumer_clock=clock,
    )
    return result, client, store


def test_atomic_exact_suffix_capture_binds_prefix_exclusion_spans_cas_and_receipts(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    rows = _rows_with_optional_prefix_gap()
    payload = _payload(rows)
    capture, client, store = _capture(tmp_path, rows=rows, events=events)

    assert client.transactions == [True]
    assert client.pipeline_instance.commands == [
        ("TYPE", KEY),
        ("GETRANGE", KEY, 0, MAX_SOURCE_PAYLOAD_BYTES),
        ("PTTL", KEY),
        ("TIME",),
    ]
    assert events == ["execute", "clock"]
    assert client.pipeline_instance.reset_calls == 1
    assert client.pipeline_instance.close_calls == 1
    assert capture.schema_version == CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION
    assert capture.evidence_classification == (
        CANONICAL_OHLCV_ATOMIC_CAPTURE_EVIDENCE_CLASSIFICATION
    )
    assert capture.downstream_status == CANONICAL_OHLCV_ATOMIC_CAPTURE_DOWNSTREAM_STATUS
    assert capture.source_key == KEY
    assert capture.source_key_sha256 == hashlib.sha256(KEY.encode("ascii")).hexdigest()
    assert capture.source_key_version == capture.atomic_batch_id
    assert capture.source_pttl_ms == 600_000
    assert capture.raw_row_count == 73
    assert capture.excluded_prefix_row_count == 2
    assert capture.excluded_prefix_gap_indices == (2,)
    assert capture.excluded_prefix_gap_missing_interval_counts == (2,)
    assert capture.selected_internal_gap_indices == ()
    assert capture.selected_source_start_index == 2
    assert capture.selected_source_end_index_exclusive == 73
    assert capture.selected_row_count == 71
    assert capture.full_window_binding.entire_contiguous_suffix_bound is True
    assert capture.full_window_binding.tail_missing_interval_count == 0
    assert capture.full_window_binding.latest_candle_matches_expected_cutoff is True
    assert capture.exact_full_source_payload_bytes == payload
    assert store.get(
        capture.full_source_payload_address.payload_sha256,
        expected_byte_count=len(payload),
    ) == payload

    selected = capture.selected_candles
    assert tuple(item.candle_id for item in selected) == capture.selected_candle_ids
    assert tuple(item.exact_payload_sha256 for item in selected) == (
        capture.selected_exact_payload_sha256s
    )
    for ordinal, item in enumerate(selected):
        exact_span = payload[item.byte_start : item.byte_end_exclusive]
        assert item.selected_ordinal == ordinal
        assert item.source_index == ordinal + 2
        assert exact_span == item._exact_payload_bytes
        assert exact_span.startswith(b"{") and exact_span.endswith(b"}")
        assert item.exact_payload_sha256 == hashlib.sha256(exact_span).hexdigest()
        assert item.exact_payload_byte_count == len(exact_span)
        assert store.get(
            item.source_payload_address.payload_sha256,
            expected_byte_count=item.exact_payload_byte_count,
        ) == exact_span
        receipt = item.source_read_receipt.receipt
        assert receipt["schema_version"] == SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION
        assert receipt["payload_type"] == CANONICAL_OHLCV_ROW_PAYLOAD_TYPE
        assert receipt["payload_sha256"] == item.exact_payload_sha256
        assert receipt["payload_byte_count"] == item.exact_payload_byte_count
        assert receipt["read_evidence"]["read_locator_type"] == (
            "REDIS_VERSIONED_VALUE"
        )
        assert receipt["read_evidence"]["read_locator"] == (
            f"{KEY}@bytes:{item.byte_start}-{item.byte_end_exclusive}"
        )
        assert receipt["read_evidence"]["read_locator_version"] == (
            capture.atomic_batch_id
        )
        assert receipt["feature_cutoff"] == receipt["economic_event_time"]
        assert receipt["finality_evidence"]["finality_cutoff"] == receipt[
            "economic_event_time"
        ]
        assert receipt["consumer_observed_at"] == capture.consumer_observed_at

    first_receipt = selected[0].source_read_receipt.receipt
    second_receipt = selected[1].source_read_receipt.receipt
    assert selected[0].source == "binance_rest"
    assert first_receipt["producer_event_time"] == first_receipt["economic_event_time"]
    assert selected[1].source == "binance_wss"
    assert second_receipt["producer_event_time"] > second_receipt["economic_event_time"]
    assert second_receipt["producer_event_time"] <= second_receipt["ingested_at"]
    assert second_receipt["ingested_at"] <= second_receipt["available_at"]

    manifest = capture.suffix_manifest
    assert manifest["schema_version"] == CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION
    assert manifest["source_key"] == KEY
    assert manifest["source_key_version"] == capture.atomic_batch_id
    assert manifest["atomic_batch_material_json"] == capture.atomic_batch_material_json
    assert manifest["selected_row_count"] == 71
    assert manifest["excluded_prefix_gap_indices"] == [2]
    assert manifest["selected_internal_gap_indices"] == []
    assert manifest["suffix_digest_sha256"] == capture.suffix_digest_sha256
    assert len(manifest["selected_rows"]) == 71
    manifest_bytes = capture.suffix_manifest_json.encode("ascii")
    assert store.get(
        capture.suffix_manifest_address.payload_sha256,
        expected_byte_count=len(manifest_bytes),
    ) == manifest_bytes


def test_every_capture_and_selected_downstream_flag_is_frozen_false(tmp_path: Path) -> None:
    capture, _, _ = _capture(tmp_path)
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

    assert all(getattr(capture, name) is False for name in flag_names)
    assert all(
        getattr(selected, name) is False
        for selected in capture.selected_candles
        for name in flag_names
    )
    assert all(
        receipt.receipt[name] is False
        for receipt in capture.source_read_receipts
        for name in flag_names
    )
    assert all(capture.suffix_manifest[name] is False for name in flag_names)
    with pytest.raises(FrozenInstanceError):
        capture.source_key = "tampered"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("redis_type", "payload", "pttl_ms", "error_type"),
    [
        (b"none", b"", -2, CanonicalOhlcvAtomicCaptureValidationError),
        (b"hash", b"", -1, CanonicalOhlcvAtomicCaptureIntegrityError),
        (b"string", b"", -1, CanonicalOhlcvAtomicCaptureValidationError),
    ],
)
def test_missing_wrong_type_and_empty_atomic_sources_fail_closed(
    tmp_path: Path,
    redis_type: bytes,
    payload: bytes,
    pttl_ms: int,
    error_type: type[Exception],
) -> None:
    client = _client_for(payload, redis_type=redis_type, pttl_ms=pttl_ms)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    with pytest.raises(error_type):
        capture_canonical_closed_ohlcv_atomic_receipts(
            client,
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: _datetime_ms(BASE_MS),
        )


def test_transport_failure_is_totalized_without_leaking_transport_detail(
    tmp_path: Path,
) -> None:
    client = _client_for(b"ignored", execute_failure=True)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(CanonicalOhlcvAtomicCaptureTransportError) as exc_info:
        capture_canonical_closed_ohlcv_atomic_receipts(
            client,
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
        )
    assert "hostile transport detail" not in str(exc_info.value)


@pytest.mark.parametrize("suffix_count", [1, 70])
def test_selected_suffix_shorter_than_derived_core_requirement_is_rejected(
    tmp_path: Path,
    suffix_count: int,
) -> None:
    rows = _rows_with_optional_prefix_gap(suffix_count=suffix_count)
    client = _client_for(_payload(rows))
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(
        CanonicalOhlcvAtomicCaptureValidationError,
        match="core_ta_minimum_coverage_unavailable",
    ):
        capture_canonical_closed_ohlcv_atomic_receipts(
            client,
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: _observed_after(rows),
        )


def test_gap_that_leaves_only_seventy_tail_rows_cannot_contaminate_selection(
    tmp_path: Path,
) -> None:
    rows = [_canonical_rest(0), _canonical_rest(1)]
    rows.extend(_canonical_wss(index) for index in range(4, 74))
    client = _client_for(_payload(rows))
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(
        CanonicalOhlcvAtomicCaptureValidationError,
        match="core_ta_minimum_coverage_unavailable",
    ):
        capture_canonical_closed_ohlcv_atomic_receipts(
            client,
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: _observed_after(rows),
        )


def test_duplicate_selected_candle_is_rejected_before_any_receipt(tmp_path: Path) -> None:
    rows = _rows_with_optional_prefix_gap(prefix_gap=False)
    rows[-1] = copy_row = dict(rows[-2])
    assert copy_row["candle_id"] == rows[-2]["candle_id"]
    client = _client_for(_payload(rows))
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(CanonicalOhlcvAtomicCaptureValidationError):
        capture_canonical_closed_ohlcv_atomic_receipts(
            client,
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: _observed_after(rows),
        )


@pytest.mark.parametrize("observation_shift_ms", [-1, 60_500])
def test_unfinished_or_stale_selected_tail_is_rejected(
    tmp_path: Path,
    observation_shift_ms: int,
) -> None:
    rows = _rows_with_optional_prefix_gap(prefix_gap=False)
    latest_close = cast(int, rows[-1]["candle_close_time"])
    observed = _datetime_ms(latest_close + observation_shift_ms)
    client = _client_for(_payload(rows))
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(CanonicalOhlcvAtomicCaptureValidationError):
        capture_canonical_closed_ohlcv_atomic_receipts(
            client,
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: observed,
        )


def test_selected_row_available_after_consumer_observation_is_rejected(
    tmp_path: Path,
) -> None:
    rows = _rows_with_optional_prefix_gap(prefix_gap=False)
    latest_close = cast(int, rows[-1]["candle_close_time"])
    client = _client_for(_payload(rows))
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(CanonicalOhlcvAtomicCaptureValidationError):
        capture_canonical_closed_ohlcv_atomic_receipts(
            client,
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: _datetime_ms(latest_close + 150),
        )


def test_atomic_batch_hash_or_payload_hash_tampering_fails_before_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _rows_with_optional_prefix_gap(prefix_gap=False)
    payload = _payload(rows)
    original_batch = read_atomic_redis_sources(_client_for(payload), (KEY,))
    tampered_batch = replace(original_batch, batch_material_sha256="0" * 64)
    monkeypatch.setattr(
        adapter_module,
        "read_atomic_redis_sources",
        lambda *_args, **_kwargs: tampered_batch,
    )
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(
        CanonicalOhlcvAtomicCaptureIntegrityError,
        match="atomic_batch_material_invalid",
    ):
        capture_canonical_closed_ohlcv_atomic_receipts(
            _client_for(payload),
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: _observed_after(rows),
        )

    source_result = original_batch.results[0]
    tampered_result = replace(source_result, payload_sha256="0" * 64)
    tampered_payload_batch = replace(original_batch, results=(tampered_result,))
    monkeypatch.setattr(
        adapter_module,
        "read_atomic_redis_sources",
        lambda *_args, **_kwargs: tampered_payload_batch,
    )
    with pytest.raises(
        CanonicalOhlcvAtomicCaptureIntegrityError,
        match="atomic_payload_evidence_invalid",
    ):
        capture_canonical_closed_ohlcv_atomic_receipts(
            _client_for(payload),
            store,
            expected_symbol=SYMBOL,
            expected_timeframe=TIMEFRAME,
            consumer_clock=lambda: _observed_after(rows),
        )


@pytest.mark.parametrize(
    ("target", "reason"),
    [
        ("full_payload", "full_payload_cas_readback_failed"),
        ("selected_row", "selected_row_cas_readback_failed"),
        ("suffix_manifest", "suffix_manifest_cas_readback_failed"),
    ],
)
def test_post_return_cas_corruption_is_detected_on_fresh_access(
    tmp_path: Path,
    target: str,
    reason: str,
) -> None:
    capture, _, store = _capture(tmp_path)
    if target == "full_payload":
        address = capture.full_source_payload_address
        original = capture.exact_full_source_payload_bytes
    elif target == "selected_row":
        selected = capture.selected_candles[0]
        address = selected.source_payload_address
        original = selected._exact_payload_bytes
    else:
        address = capture.suffix_manifest_address
        original = capture.suffix_manifest_json.encode("ascii")
    object_path = store.path_for(address.payload_sha256)
    corrupted = bytes([original[0] ^ 1]) + original[1:]
    assert len(corrupted) == address.payload_byte_count
    os.chmod(object_path, 0o600)
    object_path.write_bytes(corrupted)
    os.chmod(object_path, 0o400)

    with pytest.raises(
        CanonicalOhlcvAtomicCaptureIntegrityError,
        match=reason,
    ):
        _ = capture.source_read_receipts


def test_suffix_digest_and_per_candle_receipt_substitution_fail_closed(
    tmp_path: Path,
) -> None:
    capture, _, _ = _capture(tmp_path)
    with pytest.raises(
        CanonicalOhlcvAtomicCaptureIntegrityError,
        match="batch_material_invalid",
    ):
        replace(
            capture,
            atomic_server_time_seconds=capture.atomic_server_time_seconds + 1,
        )

    rebound = replace(
        capture.full_window_binding,
        selection_sha256="0" * 64,
    )
    with pytest.raises(CanonicalOhlcvAtomicCaptureIntegrityError):
        replace(capture, full_window_binding=rebound)

    with pytest.raises(
        CanonicalOhlcvAtomicCaptureIntegrityError,
        match="suffix_digest_binding_invalid",
    ):
        replace(capture, suffix_digest_sha256="0" * 64)

    selected = list(capture.selected_candles)
    selected[0] = replace(
        selected[0],
        source_read_receipt=selected[1].source_read_receipt,
    )
    with pytest.raises(CanonicalOhlcvAtomicCaptureIntegrityError):
        replace(capture, _selected_candles=tuple(selected))


def test_unwired_adapter_keeps_atomic_batch_and_selected_receipts_out_of_v3(
    tmp_path: Path,
) -> None:
    capture, _, _ = _capture(tmp_path)

    assert isinstance(capture.atomic_batch_id, str)
    assert isinstance(capture.atomic_batch_material_json, str)
    assert all(
        receipt.receipt["schema_version"] == SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION
        for receipt in capture.source_read_receipts
    )
    assert not hasattr(capture, "append_snapshot")
    assert not hasattr(capture, "publish")
    assert not hasattr(capture, "train")


def test_atomic_batch_dataclass_shape_is_retained_for_adversarial_fixture() -> None:
    rows = _rows_with_optional_prefix_gap(prefix_gap=False)
    batch = read_atomic_redis_sources(_client_for(_payload(rows)), (KEY,))

    assert type(batch) is AtomicRedisSourceReadBatch
    assert len(batch.results) == 1
