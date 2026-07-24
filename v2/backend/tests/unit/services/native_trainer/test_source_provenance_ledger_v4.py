from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import shutil
import stat
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty
from typing import Any, cast

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from v2.backend.app.services.native_trainer import source_provenance_ledger_v4 as ledger_module
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION,
    CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION,
    CanonicalOhlcvAtomicReceiptCapture,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_DOWNSTREAM_STATUS,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_EVIDENCE_CLASSIFICATION,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_GENESIS_SHA256,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_NAMESPACE,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH,
    TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_SCHEMA_VERSION,
    TrainerSourceProvenanceAppendResultV4,
    TrainerSourceProvenanceLedgerEntryV4,
    TrainerSourceProvenanceLedgerV4,
    TrainerSourceProvenanceLedgerV4ConflictError,
    TrainerSourceProvenanceLedgerV4DurabilityError,
    TrainerSourceProvenanceLedgerV4Error,
    TrainerSourceProvenanceLedgerV4IntegrityError,
    TrainerSourceProvenanceLedgerV4ValidationError,
)
from v2.backend.app.services.native_trainer.source_read_receipt_v4 import (
    SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION,
    build_source_read_receipt_v4,
    validate_source_read_receipt_v4,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "1m"
SOURCE_KEY = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
BASE_MS = 1_700_000_000_000
REDIS_TIME = (1_700_010_000, 123_456)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class _FakePipeline:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def type(self, _key: str) -> _FakePipeline:
        return self

    def getrange(self, _key: str, _start: int, _end: int) -> _FakePipeline:
        return self

    def pttl(self, _key: str) -> _FakePipeline:
        return self

    def time(self) -> _FakePipeline:
        return self

    def execute(self) -> list[object]:
        return list(self.responses)

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.pipeline_instance = _FakePipeline(responses)

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        return self.pipeline_instance


def _aligned_base() -> int:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    return (BASE_MS // duration) * duration


def _rest_source_row(open_time: int, *, price_offset: int) -> list[object]:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    base = 100 + price_offset
    return [
        open_time,
        f"{base}.0",
        f"{base + 2}.0",
        f"{base - 1}.0",
        f"{base + 1}.0",
        "12.0",
        open_time + duration - 1,
        "1206.0",
        10,
        "6.0",
        "603.0",
        "0",
    ]


def _canonical_rest(index: int, *, price_offset: int) -> dict[str, Any]:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    open_time = _aligned_base() + index * duration
    close_time = open_time + duration - 1
    return canonical_from_binance_rest(
        _rest_source_row(open_time, price_offset=price_offset),
        symbol=SYMBOL,
        timeframe=TIMEFRAME,
        ingested_at=close_time + 200,
    ).to_dict()


def _canonical_wss(index: int, *, price_offset: int) -> dict[str, Any]:
    duration = TIMEFRAME_DURATION_MS[TIMEFRAME]
    open_time = _aligned_base() + index * duration
    close_time = open_time + duration - 1
    producer_event = close_time + 105
    base = 101 + price_offset
    message = {
        "E": producer_event,
        "k": {
            "s": SYMBOL,
            "i": TIMEFRAME,
            "t": open_time,
            "T": close_time,
            "o": f"{base}.0",
            "h": f"{base + 2}.0",
            "l": f"{base - 1}.0",
            "c": f"{base + 1}.0",
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


def _source_rows(*, price_offset: int = 0) -> list[dict[str, Any]]:
    # The core-TA dependency contract currently derives a 71-row lookback.
    # That count comes from the feature contract; it is not selected here.
    return [
        _canonical_rest(0, price_offset=price_offset),
        *(_canonical_wss(index, price_offset=price_offset) for index in range(1, 71)),
    ]


def _datetime_ms(value: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=value)


def _build_capture(
    root: Path,
    *,
    price_offset: int = 0,
) -> tuple[CanonicalOhlcvAtomicReceiptCapture, datetime]:
    root.mkdir(parents=True)
    rows = _source_rows(price_offset=price_offset)
    payload = json.dumps(rows, ensure_ascii=True, indent=2).encode("ascii")
    observed_at = _datetime_ms(cast(int, rows[-1]["candle_close_time"]) + 500)
    client = _FakeClient([b"string", payload, 600_000, REDIS_TIME])
    capture = capture_canonical_closed_ohlcv_atomic_receipts(
        client,
        ImmutableSourcePayloadStore(root / "source-cas"),
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        consumer_clock=lambda: observed_at,
    )
    return capture, observed_at + timedelta(seconds=1)


def _append(
    ledger: TrainerSourceProvenanceLedgerV4,
    capture: CanonicalOhlcvAtomicReceiptCapture,
    recorded_at: datetime,
    *,
    run_id: str = "trainer-run-a",
    cycle_id: str = "trainer-cycle-a",
) -> ledger_module.TrainerSourceProvenanceAppendResultV4:
    return ledger.append_atomic_capture(
        capture,
        trainer_run_id=run_id,
        trainer_cycle_id=cycle_id,
        ledger_clock=lambda: recorded_at,
    )


def _process_append(
    root: str,
    capture: CanonicalOhlcvAtomicReceiptCapture,
    recorded_at: datetime,
    cycle_id: str,
    output: Any,
) -> None:
    try:
        result = _append(
            TrainerSourceProvenanceLedgerV4(Path(root)),
            capture,
            recorded_at,
            cycle_id=cycle_id,
        )
        output.put(("ok", result.disposition, result.entry.ledger_sequence))
    except BaseException as exc:  # noqa: BLE001 - child must report all failures
        output.put(("error", type(exc).__name__, str(exc)))


def _assert_all_downstream_false(value: object) -> None:
    for field_name in ledger_module._DOWNSTREAM_FLAG_FIELDS:
        assert getattr(value, field_name) is False


def _write_private_raw_ledger(ledger: TrainerSourceProvenanceLedgerV4, raw: bytes) -> None:
    ledger.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    ledger.root.chmod(0o700)
    ledger.path.write_bytes(raw)
    ledger.path.chmod(0o600)


def _rewrite_single_record_and_head(
    ledger: TrainerSourceProvenanceLedgerV4,
    record: dict[str, Any],
) -> None:
    record["replay_identity_sha256"] = ledger_module._stable_sha256(
        ledger_module._replay_material_from_record(record)
    )
    material_without_hash = {key: value for key, value in record.items() if key != "entry_sha256"}
    record["entry_sha256"] = ledger_module._stable_sha256(material_without_hash)
    entry_json = ledger_module._canonical_json(record)
    framed = entry_json.encode("ascii") + b"\n"
    ledger.path.write_bytes(framed)
    ledger.path.chmod(0o600)
    head = ledger_module._head_material(
        raw_prefix=framed,
        sequence=1,
        entry_sha256=record["entry_sha256"],
    )
    ledger.head_path.write_text(
        ledger_module._canonical_json(head, max_bytes=64 * 1024) + "\n",
        encoding="ascii",
    )
    ledger.head_path.chmod(0o600)


def _owned_object_path(
    ledger: TrainerSourceProvenanceLedgerV4,
    address: dict[str, Any],
) -> Path:
    return ledger.store_root / cast(str, address["relative_path"])


def _address_for_exact_bytes(
    prototype: dict[str, Any],
    payload: bytes,
) -> dict[str, Any]:
    digest = hashlib.sha256(payload).hexdigest()
    return {
        "schema_version": prototype["schema_version"],
        "payload_sha256": digest,
        "payload_byte_count": len(payload),
        "relative_path": f"sha256/{digest[:2]}/{digest}",
    }


def _replace_exact_manifest_json(record: dict[str, Any], exact_json: str) -> None:
    material = cast(dict[str, Any], record["suffix_manifest"])
    payload = exact_json.encode("ascii")
    material["exact_manifest_json"] = exact_json
    material["exact_manifest_sha256"] = hashlib.sha256(payload).hexdigest()
    material["exact_manifest_byte_count"] = len(payload)
    material["manifest_cas_address"] = _address_for_exact_bytes(
        cast(dict[str, Any], material["manifest_cas_address"]),
        payload,
    )


def _replace_suffix_digest_json(record: dict[str, Any], exact_json: str) -> None:
    material = cast(dict[str, Any], record["suffix_manifest"])
    payload = exact_json.encode("ascii")
    material["suffix_digest_material_json"] = exact_json
    material["suffix_digest_sha256"] = hashlib.sha256(payload).hexdigest()


def test_append_binds_exact_source_manifest_receipts_clocks_and_unwired_status(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")

    result = _append(ledger, capture, recorded_at)

    assert result.disposition == "APPENDED"
    assert result.source_provenance_ledger_recorded is True
    assert result.durable_postcommit_readback_verified is True
    _assert_all_downstream_false(result)
    _assert_all_downstream_false(result.entry)
    _assert_all_downstream_false(capture)
    assert ledger.path.name == TRAINER_SOURCE_PROVENANCE_LEDGER_V4_FILENAME
    assert ledger.head_path.name == TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME
    assert ledger.path.read_bytes().endswith(b"\n")
    assert ledger.head_path.read_bytes().endswith(b"\n")

    record = result.entry.record
    assert record["schema_version"] == TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION
    assert record["evidence_classification"] == (
        TRAINER_SOURCE_PROVENANCE_LEDGER_V4_EVIDENCE_CLASSIFICATION
    )
    assert record["downstream_status"] == (TRAINER_SOURCE_PROVENANCE_LEDGER_V4_DOWNSTREAM_STATUS)
    assert record["ledger_sequence"] == 1
    assert record["previous_entry_sha256"] == (TRAINER_SOURCE_PROVENANCE_LEDGER_V4_GENESIS_SHA256)
    assert record["trainer_run_id"] == "trainer-run-a"
    assert record["trainer_cycle_id"] == "trainer-cycle-a"
    assert record["ledger_recorded_at"] == recorded_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    assert all(record[name] is False for name in ledger_module._DOWNSTREAM_FLAG_FIELDS)
    assert record["ledger_owned_store"] == ledger_module._owned_store_material()
    assert record["ledger_owned_store"]["schema_version"] == (
        TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_SCHEMA_VERSION
    )
    assert record["ledger_owned_store"]["namespace"] == (
        TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_NAMESPACE
    )
    assert record["ledger_owned_store"]["root_relative_path"] == (
        TRAINER_SOURCE_PROVENANCE_LEDGER_V4_STORE_ROOT_RELATIVE_PATH
    )
    assert ledger.store_root.is_dir()
    assert stat.S_IMODE(ledger.store_root.stat().st_mode) == 0o700

    source = record["source_capture"]
    assert source["capture_schema_version"] == CANONICAL_OHLCV_ATOMIC_CAPTURE_SCHEMA_VERSION
    assert source["source_key"] == SOURCE_KEY
    assert source["source_key_version"] == capture.atomic_batch_id
    assert source["atomic_batch_id"] == capture.atomic_batch_id
    assert source["atomic_batch_material_json"] == capture.atomic_batch_material_json
    assert source["atomic_batch_material_sha256"] == capture.atomic_batch_material_sha256
    assert source["consumer_observed_at"] == capture.consumer_observed_at
    assert (
        source["full_source_payload"]["payload_sha256"]
        == hashlib.sha256(capture.exact_full_source_payload_bytes).hexdigest()
    )
    assert source["full_source_payload"] == {
        "schema_version": capture.full_source_payload_address.schema_version,
        "payload_sha256": capture.full_source_payload_address.payload_sha256,
        "payload_byte_count": capture.full_source_payload_address.payload_byte_count,
        "relative_path": capture.full_source_payload_address.relative_path,
    }
    assert _owned_object_path(ledger, source["full_source_payload"]).is_file()

    manifest = record["suffix_manifest"]
    exact_manifest_bytes = capture.suffix_manifest_json.encode("ascii")
    assert manifest["schema_version"] == CANONICAL_OHLCV_SUFFIX_MANIFEST_SCHEMA_VERSION
    assert manifest["exact_manifest_json"] == capture.suffix_manifest_json
    assert manifest["exact_manifest_sha256"] == hashlib.sha256(exact_manifest_bytes).hexdigest()
    assert manifest["exact_manifest_byte_count"] == len(exact_manifest_bytes)
    assert manifest["manifest_cas_address"]["payload_sha256"] == (
        capture.suffix_manifest_address.payload_sha256
    )
    assert manifest["suffix_digest_sha256"] == capture.suffix_digest_sha256
    assert manifest["selected_candle_ids"] == list(capture.selected_candle_ids)

    rows = record["ordered_rows"]
    assert len(rows) == capture.selected_row_count == 71
    for ordinal, (persisted, selected) in enumerate(
        zip(rows, capture.selected_candles, strict=True)
    ):
        assert persisted["selected_ordinal"] == ordinal
        assert persisted["source_index"] == selected.source_index
        assert persisted["exact_payload_sha256"] == selected.exact_payload_sha256
        assert persisted["source_read_receipt_schema_version"] == (
            SOURCE_READ_RECEIPT_V4_SCHEMA_VERSION
        )
        receipt = validate_source_read_receipt_v4(json.loads(persisted["source_read_receipt_json"]))
        assert receipt.receipt_sha256 == persisted["source_read_receipt_sha256"]
        assert persisted["economic_event_time"] <= persisted["producer_event_time"]
        assert persisted["producer_event_time"] <= persisted["ingested_at"]
        assert persisted["ingested_at"] <= persisted["available_at"]
        assert persisted["available_at"] <= persisted["consumer_observed_at"]
        assert persisted["feature_cutoff"] == persisted["economic_event_time"]
        assert persisted["finality_cutoff"] == persisted["economic_event_time"]
    assert record["temporal_semantics"]["generated_at"] is None
    assert record["temporal_semantics"]["decision_time"] is None
    assert record["temporal_semantics"]["execution_time"] is None
    assert ledger.read_entries() == (result.entry,)


def test_dataclass_field_contract_has_each_authorization_flag_exactly_once() -> None:
    entry_names = tuple(item.name for item in fields(TrainerSourceProvenanceLedgerEntryV4))
    result_names = tuple(item.name for item in fields(TrainerSourceProvenanceAppendResultV4))
    assert entry_names == (
        "schema_version",
        "ledger_sequence",
        "previous_entry_sha256",
        "trainer_run_id",
        "trainer_cycle_id",
        "cycle_identity_sha256",
        "replay_identity_sha256",
        "entry_sha256",
        "entry_json",
        "_construction_token",
        "source_provenance_ledger_recorded",
        "durable_postcommit_readback_verified",
        "feature_snapshot_published",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    )
    assert result_names == (
        "entry",
        "disposition",
        "_construction_token",
        "source_provenance_ledger_recorded",
        "durable_postcommit_readback_verified",
        "feature_snapshot_published",
        "feature_publication_receipt_emitted",
        "consumer_eligible",
        "trainer_admission_granted",
        "prediction_authorized",
        "paper_trading_authorized",
        "live_execution_authorized",
    )
    assert entry_names.count("paper_trading_authorized") == 1
    assert result_names.count("paper_trading_authorized") == 1


def test_append_result_cannot_be_publicly_forged(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    authentic = _append(ledger, capture, recorded_at)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="append_result_factory_construction_required",
    ):
        TrainerSourceProvenanceAppendResultV4(
            entry=cast(Any, object()),
            disposition="APPENDED",
        )
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="append_result_factory_construction_required",
    ):
        TrainerSourceProvenanceAppendResultV4(
            entry=authentic.entry,
            disposition="APPENDED",
            _construction_token=object(),
        )

    assert authentic.source_provenance_ledger_recorded is True
    assert authentic.durable_postcommit_readback_verified is True


def test_fresh_read_succeeds_after_original_p0b_cas_is_deleted(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    upstream_store_root = capture._source_payload_store.root_path
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    appended = _append(ledger, capture, recorded_at)

    shutil.rmtree(upstream_store_root)

    fresh_entries = TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()
    assert len(fresh_entries) == 1
    assert fresh_entries[0].entry_sha256 == appended.entry.entry_sha256


def test_shared_reader_opens_existing_lock_read_only_and_takes_shared_flock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    appended = _append(ledger, capture, recorded_at)
    real_open = ledger_module.os.open
    real_flock = ledger_module.fcntl.flock
    lock_open_flags: list[int] = []
    lock_operations: list[int] = []

    def guarded_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if path == ledger_module.TRAINER_SOURCE_PROVENANCE_LEDGER_V4_LOCK_FILENAME:
            lock_open_flags.append(flags)
            assert flags & os.O_ACCMODE == os.O_RDONLY
            assert flags & os.O_CREAT == 0
        return real_open(path, flags, *args, **kwargs)

    def observed_flock(descriptor: int, operation: int) -> Any:
        lock_operations.append(operation)
        return real_flock(descriptor, operation)

    monkeypatch.setattr(ledger_module.os, "open", guarded_open)
    monkeypatch.setattr(ledger_module.fcntl, "flock", observed_flock)

    entries = TrainerSourceProvenanceLedgerV4(
        ledger.root
    ).read_entries_read_only()

    assert entries == (appended.entry,)
    assert len(lock_open_flags) == 1
    assert lock_operations == [ledger_module.fcntl.LOCK_SH, ledger_module.fcntl.LOCK_UN]


def test_missing_ledger_owned_full_source_cas_fails_closed(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    source_address = result.entry.record["source_capture"]["full_source_payload"]
    _owned_object_path(ledger, source_address).unlink()

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_full_source_cas_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_same_length_ledger_owned_cas_substitution_fails_closed(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    source_address = result.entry.record["source_capture"]["full_source_payload"]
    source_path = _owned_object_path(ledger, source_address)
    original = source_path.read_bytes()
    source_path.unlink()
    source_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    source_path.chmod(0o400)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_full_source_cas_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_ledger_owned_row_cas_hardlink_fails_closed(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    row_address = result.entry.record["ordered_rows"][0]["source_payload_cas_address"]
    row_path = _owned_object_path(ledger, row_address)
    os.link(row_path, tmp_path / "forbidden-row-hardlink")

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_row_cas_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_ledger_owned_source_cas_symlink_fails_closed(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    source_address = result.entry.record["source_capture"]["full_source_payload"]
    source_path = _owned_object_path(ledger, source_address)
    backup = tmp_path / "owned-source-backup"
    source_path.rename(backup)
    source_path.symlink_to(backup)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_full_source_cas_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("manifest_root_extra", "exact_manifest_fields_invalid"),
        ("manifest_row_extra", "exact_manifest_row_fields_invalid"),
        ("manifest_row_duplicate", "duplicate_json_key"),
        ("suffix_root_extra", "suffix_digest_fields_invalid"),
        ("suffix_row_extra", "suffix_digest_row_fields_invalid"),
        ("suffix_row_duplicate", "duplicate_json_key"),
    ],
)
def test_recomputed_outer_chain_rejects_nested_schema_forgery(
    tmp_path: Path,
    mutation: str,
    expected_reason: str,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    record = deepcopy(result.entry.record)
    manifest_record = cast(dict[str, Any], record["suffix_manifest"])

    if mutation.startswith("manifest_"):
        manifest_json = cast(str, manifest_record["exact_manifest_json"])
        if mutation == "manifest_row_duplicate":
            needle = '"selected_rows":[{'
            assert needle in manifest_json
            manifest_json = manifest_json.replace(
                needle,
                '"selected_rows":[{"selected_ordinal":999,',
                1,
            )
        else:
            manifest = cast(dict[str, Any], json.loads(manifest_json))
            if mutation == "manifest_root_extra":
                manifest["unexpected_nested_field"] = True
            else:
                manifest["selected_rows"][0]["unexpected_nested_field"] = True
            manifest_json = ledger_module._canonical_json(manifest)
        _replace_exact_manifest_json(record, manifest_json)
    else:
        suffix_json = cast(str, manifest_record["suffix_digest_material_json"])
        if mutation == "suffix_row_duplicate":
            needle = '"ordered_selected_rows":[{'
            assert needle in suffix_json
            suffix_json = suffix_json.replace(
                needle,
                '"ordered_selected_rows":[{"selected_ordinal":999,',
                1,
            )
        else:
            suffix = cast(dict[str, Any], json.loads(suffix_json))
            if mutation == "suffix_root_extra":
                suffix["unexpected_nested_field"] = True
            else:
                suffix["ordered_selected_rows"][0]["unexpected_nested_field"] = True
            suffix_json = ledger_module._canonical_json(suffix)
        _replace_suffix_digest_json(record, suffix_json)

    _rewrite_single_record_and_head(ledger, record)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match=expected_reason,
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_recomputed_chain_and_owned_manifest_cannot_rebind_only_nested_source_ttl(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    record = deepcopy(result.entry.record)
    source = cast(dict[str, Any], record["source_capture"])
    manifest_record = cast(dict[str, Any], record["suffix_manifest"])
    manifest = cast(
        dict[str, Any],
        json.loads(cast(str, manifest_record["exact_manifest_json"])),
    )
    assert source["source_pttl_ms"] == manifest["source_pttl_ms"] == 600_000

    manifest["source_pttl_ms"] = 612_345
    manifest_json = ledger_module._canonical_json(manifest)
    manifest_bytes = manifest_json.encode("ascii")
    manifest_address = ImmutableSourcePayloadStore(ledger.store_root).put(
        manifest_bytes,
        expected_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        expected_byte_count=len(manifest_bytes),
    )
    _replace_exact_manifest_json(record, manifest_json)
    manifest_record["manifest_cas_address"] = ledger_module._address_material(manifest_address)
    _rewrite_single_record_and_head(ledger, record)

    assert source["source_pttl_ms"] == 600_000
    assert (
        _owned_object_path(
            ledger,
            cast(dict[str, Any], manifest_record["manifest_cas_address"]),
        ).read_bytes()
        == manifest_bytes
    )
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="manifest_source_binding_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_recomputed_nested_and_outer_hashes_cannot_hide_shifted_source_span(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    record = deepcopy(result.entry.record)
    row = cast(dict[str, Any], record["ordered_rows"][0])
    new_start = cast(int, row["byte_start"]) + 1
    new_end = cast(int, row["byte_end_exclusive"]) + 1
    old_receipt = cast(dict[str, Any], json.loads(row["source_read_receipt_json"]))
    old_read = cast(dict[str, Any], old_receipt["read_evidence"])
    old_finality = cast(dict[str, Any], old_receipt["finality_evidence"])
    rebuilt_receipt = build_source_read_receipt_v4(
        source_label=cast(str, old_receipt["source_label"]),
        payload_type=cast(str, old_receipt["payload_type"]),
        payload_sha256=cast(str, old_receipt["payload_sha256"]),
        payload_byte_count=cast(int, old_receipt["payload_byte_count"]),
        economic_event_time=cast(str, old_receipt["economic_event_time"]),
        producer_event_time=cast(str, old_receipt["producer_event_time"]),
        ingested_at=cast(str, old_receipt["ingested_at"]),
        available_at=cast(str, old_receipt["available_at"]),
        consumer_observed_at=cast(str, old_receipt["consumer_observed_at"]),
        feature_cutoff=cast(str, old_receipt["feature_cutoff"]),
        read_locator_type=cast(str, old_read["read_locator_type"]),
        read_locator=f"{SOURCE_KEY}@bytes:{new_start}-{new_end}",
        read_locator_version=cast(str, old_read["read_locator_version"]),
        finality_type=cast(str, old_finality["finality_type"]),
        finality_cutoff=cast(str, old_finality["finality_cutoff"]),
        finality_verified_at=cast(str, old_finality["finality_verified_at"]),
        finality_verifier=cast(str, old_finality["verifier"]),
    )
    row["byte_start"] = new_start
    row["byte_end_exclusive"] = new_end
    row["source_read_receipt_sha256"] = rebuilt_receipt.receipt_sha256
    row["source_read_receipt_json"] = rebuilt_receipt.receipt_json

    manifest_record = cast(dict[str, Any], record["suffix_manifest"])
    manifest = cast(
        dict[str, Any],
        json.loads(cast(str, manifest_record["exact_manifest_json"])),
    )
    manifest_row = cast(dict[str, Any], manifest["selected_rows"][0])
    manifest_row["byte_start"] = new_start
    manifest_row["byte_end_exclusive"] = new_end
    manifest_row["source_read_receipt_v4"] = rebuilt_receipt.receipt

    suffix = cast(
        dict[str, Any],
        json.loads(cast(str, manifest_record["suffix_digest_material_json"])),
    )
    suffix_row = cast(dict[str, Any], suffix["ordered_selected_rows"][0])
    suffix_row["byte_start"] = new_start
    suffix_row["byte_end_exclusive"] = new_end
    suffix_row["source_read_receipt_sha256"] = rebuilt_receipt.receipt_sha256
    suffix_json = ledger_module._canonical_json(suffix)
    suffix_sha = hashlib.sha256(suffix_json.encode("ascii")).hexdigest()
    manifest["suffix_digest_material_json"] = suffix_json
    manifest["suffix_digest_sha256"] = suffix_sha
    manifest_record["suffix_digest_material_json"] = suffix_json
    manifest_record["suffix_digest_sha256"] = suffix_sha

    manifest_json = ledger_module._canonical_json(manifest)
    manifest_bytes = manifest_json.encode("ascii")
    manifest_address = ImmutableSourcePayloadStore(ledger.store_root).put(
        manifest_bytes,
        expected_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        expected_byte_count=len(manifest_bytes),
    )
    _replace_exact_manifest_json(record, manifest_json)
    manifest_record["manifest_cas_address"] = ledger_module._address_material(manifest_address)
    _rewrite_single_record_and_head(ledger, record)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_row_slice_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_second_entry_chains_to_first_and_same_capture_may_bind_new_cycle(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")

    first = _append(ledger, capture, recorded_at, cycle_id="cycle-1")
    second = _append(
        ledger,
        capture,
        recorded_at + timedelta(seconds=1),
        cycle_id="cycle-2",
    )

    assert second.entry.ledger_sequence == 2
    assert second.entry.previous_entry_sha256 == first.entry.entry_sha256
    entries = ledger.read_entries()
    assert [entry.ledger_sequence for entry in entries] == [1, 2]
    assert entries[1].previous_entry_sha256 == entries[0].entry_sha256


def test_append_reuses_owned_cas_proofs_only_inside_its_writer_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-commit readback rechecks the chain without rehashing its prefix."""

    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    first = _append(ledger, capture, recorded_at, cycle_id="cycle-1")
    calls: list[str] = []
    original = ledger_module._verify_record_owned_cas

    def tracked_verify(record: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        calls.append(cast(str, record["entry_sha256"]))
        original(record, *args, **kwargs)

    monkeypatch.setattr(ledger_module, "_verify_record_owned_cas", tracked_verify)
    second = _append(
        ledger,
        capture,
        recorded_at + timedelta(seconds=1),
        cycle_id="cycle-2",
    )

    # The writer verifies the committed prefix once and the new entry once.
    # The required post-commit readback still reparses/hash-chains both entries,
    # but uses only those two positive proofs while the same writer lock is held.
    assert calls == [first.entry.entry_sha256, second.entry.entry_sha256]


def test_writer_scoped_owned_cas_proof_does_not_survive_public_read(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    source_address = result.entry.record["source_capture"]["full_source_payload"]
    source_path = _owned_object_path(ledger, source_address)
    original = source_path.read_bytes()
    source_path.unlink()
    source_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    source_path.chmod(0o400)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_full_source_cas_invalid",
    ):
        ledger.read_entries()


def test_exact_replay_is_idempotent_and_does_not_append_bytes(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    first = _append(ledger, capture, recorded_at)
    before = ledger.path.read_bytes()

    replay = _append(ledger, capture, recorded_at + timedelta(hours=1))

    assert replay.disposition == "EXACT_REPLAY"
    assert replay.entry == first.entry
    assert ledger.path.read_bytes() == before
    assert len(ledger.read_entries()) == 1


def test_same_run_cycle_with_different_capture_is_conflicting_replay(
    tmp_path: Path,
) -> None:
    first_capture, recorded_at = _build_capture(tmp_path / "capture-a")
    second_capture, second_recorded_at = _build_capture(tmp_path / "capture-b", price_offset=7)
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, first_capture, recorded_at)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4ConflictError,
        match="conflicting_cycle_replay",
    ):
        _append(ledger, second_capture, second_recorded_at)
    assert len(ledger.read_entries()) == 1


@pytest.mark.parametrize(
    "invalid_capture",
    [
        {"schema_version": "feature_source_consumer_read_receipt_v3"},
        {"schema_version": TRAINER_SOURCE_PROVENANCE_LEDGER_V4_SCHEMA_VERSION},
        object(),
    ],
)
def test_only_factory_authenticated_p0b_capture_is_accepted(
    tmp_path: Path,
    invalid_capture: object,
) -> None:
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4ValidationError,
        match="p0b_capture_type_required",
    ):
        ledger.append_atomic_capture(
            cast(CanonicalOhlcvAtomicReceiptCapture, invalid_capture),
            trainer_run_id="run-a",
            trainer_cycle_id="cycle-a",
        )
    assert not ledger.path.exists()


def test_upstream_deletion_after_lock_before_authoritative_validation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    upstream_store_root = capture._source_payload_store.root_path
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    original_lock = ledger._exclusive_lock

    @contextmanager
    def delete_upstream_after_lock() -> Iterator[Any]:
        with original_lock() as root:
            shutil.rmtree(upstream_store_root)
            yield root

    monkeypatch.setattr(ledger, "_exclusive_lock", delete_upstream_after_lock)
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4ValidationError,
        match="p0b_capture_revalidation_failed",
    ):
        _append(ledger, capture, recorded_at)
    assert not ledger.path.exists()
    assert not ledger.head_path.exists()


def test_persisted_v3_entry_is_rejected_before_head_recovery(tmp_path: Path) -> None:
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _write_private_raw_ledger(
        ledger,
        b'{"schema_version":"trainer_source_provenance_ledger_entry_v3"}\n',
    )

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="entry_fields_invalid",
    ):
        ledger.read_entries()


def test_entry_byte_tamper_is_rejected_even_when_framing_remains_complete(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    raw = ledger.path.read_bytes()
    assert b'"trainer_run_id":"trainer-run-a"' in raw
    ledger.path.write_bytes(
        raw.replace(
            b'"trainer_run_id":"trainer-run-a"',
            b'"trainer_run_id":"trainer-run-b"',
            1,
        )
    )

    with pytest.raises(TrainerSourceProvenanceLedgerV4IntegrityError):
        ledger.read_entries()


def test_partial_tail_truncation_is_rejected(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    ledger.path.write_bytes(ledger.path.read_bytes()[:-1])

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="truncated_or_partial_tail",
    ):
        ledger.read_entries()


def test_complete_last_entry_truncation_is_detected_by_durable_head(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at, cycle_id="cycle-1")
    _append(
        ledger,
        capture,
        recorded_at + timedelta(seconds=1),
        cycle_id="cycle-2",
    )
    first_line = ledger.path.read_bytes().splitlines(keepends=True)[0]
    ledger.path.write_bytes(first_line)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="head_sequence_invalid",
    ):
        ledger.read_entries()


def test_head_tamper_is_rejected(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    head = json.loads(ledger.head_path.read_text(encoding="ascii"))
    head["ledger_byte_count"] += 1
    ledger.head_path.write_text(
        json.dumps(head, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="head_sha256_invalid",
    ):
        ledger.read_entries()


def test_cas_write_crash_precedes_ledger_and_retry_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    original_put = ImmutableSourcePayloadStore.put
    put_count = 0

    def crash_on_second_owned_put(
        self: ImmutableSourcePayloadStore,
        payload: bytes,
        *,
        expected_sha256: str | None = None,
        expected_byte_count: int | None = None,
    ) -> Any:
        nonlocal put_count
        put_count += 1
        if put_count == 2:
            raise SourcePayloadStoreError("simulated_owned_cas_crash")
        return original_put(
            self,
            payload,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
        )

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", crash_on_second_owned_put)
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4DurabilityError,
        match="owned_cas_put_failed",
    ):
        _append(ledger, capture, recorded_at)
    source_digest = hashlib.sha256(capture.exact_full_source_payload_bytes).hexdigest()
    assert (ledger.store_root / "sha256" / source_digest[:2] / source_digest).is_file()
    assert not ledger.path.exists()
    assert not ledger.head_path.exists()

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", original_put)
    retry = _append(ledger, capture, recorded_at)
    assert retry.disposition == "APPENDED"
    assert len(ledger.read_entries()) == 1


def test_complete_cas_pin_crash_before_ledger_retries_as_one_exact_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    original_append = ledger_module._append_fsync

    def crash_before_ledger(*_args: object, **_kwargs: object) -> None:
        raise TrainerSourceProvenanceLedgerV4DurabilityError("simulated_pre_ledger_crash")

    monkeypatch.setattr(ledger_module, "_append_fsync", crash_before_ledger)
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4DurabilityError,
        match="simulated_pre_ledger_crash",
    ):
        _append(ledger, capture, recorded_at)
    assert any((ledger.store_root / "sha256").glob("*/*"))
    assert not ledger.path.exists()
    assert not ledger.head_path.exists()

    monkeypatch.setattr(ledger_module, "_append_fsync", original_append)
    retry = _append(ledger, capture, recorded_at)
    assert retry.disposition == "APPENDED"
    assert len(ledger.read_entries()) == 1


def test_complete_append_crash_before_head_recovers_only_on_exact_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    original = ledger_module._write_head_atomic

    def fail_before_head(*_args: object, **_kwargs: object) -> None:
        raise TrainerSourceProvenanceLedgerV4DurabilityError("simulated_head_crash")

    monkeypatch.setattr(ledger_module, "_write_head_atomic", fail_before_head)
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4DurabilityError,
        match="simulated_head_crash",
    ):
        _append(ledger, capture, recorded_at)
    assert ledger.path.read_bytes().endswith(b"\n")
    assert not ledger.head_path.exists()

    monkeypatch.setattr(ledger_module, "_write_head_atomic", original)
    recovered = _append(ledger, capture, recorded_at + timedelta(minutes=1))
    assert recovered.disposition == "RECOVERED_EXACT_PENDING_APPEND"
    assert len(ledger.read_entries()) == 1


def test_pending_append_crash_rejects_different_run_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")

    def fail_before_head(*_args: object, **_kwargs: object) -> None:
        raise TrainerSourceProvenanceLedgerV4DurabilityError("simulated_head_crash")

    monkeypatch.setattr(ledger_module, "_write_head_atomic", fail_before_head)
    with pytest.raises(TrainerSourceProvenanceLedgerV4DurabilityError):
        _append(ledger, capture, recorded_at, cycle_id="cycle-a")

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4ConflictError,
        match="uncommitted_tail_conflict",
    ):
        _append(ledger, capture, recorded_at, cycle_id="cycle-b")


def test_partial_write_crash_never_becomes_recoverable_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")

    def partial_write(descriptor: int, payload: bytes) -> None:
        os.write(descriptor, payload[: len(payload) // 2])
        raise TrainerSourceProvenanceLedgerV4DurabilityError("simulated_partial_write")

    monkeypatch.setattr(ledger_module, "_write_all", partial_write)
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4DurabilityError,
        match="simulated_partial_write",
    ):
        _append(ledger, capture, recorded_at)
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="truncated_or_partial_tail",
    ):
        ledger.read_entries()


def test_postcommit_readback_failure_returns_no_false_success_and_retry_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    original = ledger_module._postcommit_readback

    def fail_readback(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise TrainerSourceProvenanceLedgerV4DurabilityError("simulated_postcommit_readback_crash")

    monkeypatch.setattr(ledger_module, "_postcommit_readback", fail_readback)
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4DurabilityError,
        match="simulated_postcommit_readback_crash",
    ):
        _append(ledger, capture, recorded_at)
    monkeypatch.setattr(ledger_module, "_postcommit_readback", original)

    replay = _append(ledger, capture, recorded_at + timedelta(minutes=1))
    assert replay.disposition == "EXACT_REPLAY"
    assert len(ledger.read_entries()) == 1


def test_append_fsync_head_publication_and_postcommit_readback_are_ordered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    events: list[str] = []
    original_append = ledger_module._append_fsync
    original_head = ledger_module._write_head_atomic
    original_readback = ledger_module._postcommit_readback

    def tracked_append(root: Any, payload: bytes) -> None:
        events.append("append_flush_fsync")
        original_append(root, payload)

    def tracked_head(
        root: Any,
        head: dict[str, object],
    ) -> None:
        events.append("durable_head_publish")
        original_head(root, head)

    def tracked_readback(
        root: Any,
        store: ImmutableSourcePayloadStore,
        *,
        expected_store_root: Path,
        expected_entry_json: str,
        expected_sequence: int,
    ) -> dict[str, Any]:
        events.append("postcommit_readback")
        return original_readback(
            root,
            store,
            expected_store_root=expected_store_root,
            expected_entry_json=expected_entry_json,
            expected_sequence=expected_sequence,
        )

    monkeypatch.setattr(ledger_module, "_append_fsync", tracked_append)
    monkeypatch.setattr(ledger_module, "_write_head_atomic", tracked_head)
    monkeypatch.setattr(ledger_module, "_postcommit_readback", tracked_readback)

    _append(ledger, capture, recorded_at)
    assert events == [
        "append_flush_fsync",
        "durable_head_publish",
        "postcommit_readback",
    ]


def test_recomputed_outer_hashes_cannot_hide_recorded_before_source_pit_violation(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    result = _append(ledger, capture, recorded_at)
    record = deepcopy(result.entry.record)
    consumer = datetime.strptime(
        record["source_capture"]["consumer_observed_at"],
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ).replace(tzinfo=UTC)
    record["ledger_recorded_at"] = (
        (consumer - timedelta(microseconds=1))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )
    material_without_hash = {key: value for key, value in record.items() if key != "entry_sha256"}
    record["entry_sha256"] = ledger_module._stable_sha256(material_without_hash)
    entry_json = ledger_module._canonical_json(record)
    framed = entry_json.encode("ascii") + b"\n"
    ledger.path.write_bytes(framed)
    head = ledger_module._head_material(
        raw_prefix=framed,
        sequence=1,
        entry_sha256=record["entry_sha256"],
    )
    ledger.head_path.write_text(
        ledger_module._canonical_json(head, max_bytes=64 * 1024) + "\n",
        encoding="ascii",
    )

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="recorded_before_source_read",
    ):
        ledger.read_entries()


def test_thread_contention_appends_once_and_replays_exactly(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _index: _append(ledger, capture, recorded_at),
                range(8),
            )
        )

    assert [result.disposition for result in results].count("APPENDED") == 1
    assert [result.disposition for result in results].count("EXACT_REPLAY") == 7
    assert len({result.entry.entry_sha256 for result in results}) == 1
    assert len(ledger.read_entries()) == 1


def test_interprocess_lock_serializes_distinct_concurrent_cycle_appends(
    tmp_path: Path,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    root = tmp_path / "ledger-v4"
    context = multiprocessing.get_context("fork")
    output = context.Queue()
    processes = [
        context.Process(
            target=_process_append,
            args=(str(root), capture, recorded_at, f"cycle-{index}", output),
        )
        for index in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    messages: list[tuple[str, object, object]] = []
    for _ in processes:
        try:
            messages.append(output.get(timeout=5))
        except Empty:
            pytest.fail("child append result missing")
    assert all(message[0] == "ok" for message in messages), messages
    assert all(message[1] == "APPENDED" for message in messages)

    ledger = TrainerSourceProvenanceLedgerV4(root)
    entries = ledger.read_entries()
    assert len(entries) == 4
    assert [entry.ledger_sequence for entry in entries] == [1, 2, 3, 4]
    assert entries[0].previous_entry_sha256 == (TRAINER_SOURCE_PROVENANCE_LEDGER_V4_GENESIS_SHA256)
    for previous, current in zip(entries[:-1], entries[1:], strict=True):
        assert current.previous_entry_sha256 == previous.entry_sha256


def test_noncanonical_or_duplicate_key_ledger_bytes_fail_closed(tmp_path: Path) -> None:
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _write_private_raw_ledger(
        ledger,
        b'{"schema_version":"v4", "schema_version":"v4"}\n',
    )
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="duplicate_json_key",
    ):
        ledger.read_entries()


@pytest.mark.parametrize(
    "unsafe_root",
    [
        Path("relative-ledger-v4"),
        Path.cwd() / "lexical-safe" / ".." / "ledger-v4",
    ],
)
def test_ledger_root_requires_lexical_absolute_nontraversing_path(
    unsafe_root: Path,
) -> None:
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4ValidationError,
        match="root_lexical_absolute_required",
    ):
        TrainerSourceProvenanceLedgerV4(unsafe_root)


@pytest.mark.parametrize("symlink_position", ["ancestor", "final"])
def test_ledger_root_rejects_ancestor_and_final_symlinks(
    tmp_path: Path,
    symlink_position: str,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    if symlink_position == "ancestor":
        linked_parent = tmp_path / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        root = linked_parent / "ledger-v4"
    else:
        real_root = real_parent / "real-ledger-v4"
        real_root.mkdir(mode=0o700)
        root = tmp_path / "linked-ledger-v4"
        root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="root_ancestor_or_final_open_failed",
    ):
        TrainerSourceProvenanceLedgerV4(root).read_entries()


def test_existing_world_readable_ledger_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "ledger-v4"
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="root_private_owner_mode_required",
    ):
        TrainerSourceProvenanceLedgerV4(root).read_entries()


def test_same_instance_rejects_wholesale_root_replacement(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    displaced = tmp_path / "displaced-ledger-v4"
    ledger.root.rename(displaced)
    ledger.root.mkdir(mode=0o700)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="root_instance_replaced",
    ):
        ledger.read_entries()


@pytest.mark.parametrize("path_attribute", ["path", "head_path", "lock_path"])
def test_ledger_artifact_hardlinks_are_rejected(
    tmp_path: Path,
    path_attribute: str,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    artifact = cast(Path, getattr(ledger, path_attribute))
    os.link(artifact, tmp_path / f"{path_attribute}-hardlink")

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="identity_invalid",
    ):
        ledger.read_entries()


@pytest.mark.parametrize("path_attribute", ["path", "head_path", "lock_path"])
def test_ledger_artifacts_require_owner_only_mode(
    tmp_path: Path,
    path_attribute: str,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    cast(Path, getattr(ledger, path_attribute)).chmod(0o644)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="identity_invalid",
    ):
        ledger.read_entries()


@pytest.mark.parametrize("path_attribute", ["path", "head_path", "lock_path"])
def test_ledger_artifact_symlinks_are_rejected(
    tmp_path: Path,
    path_attribute: str,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    artifact = cast(Path, getattr(ledger, path_attribute))
    backup = tmp_path / f"{path_attribute}-backup"
    artifact.rename(backup)
    artifact.symlink_to(backup)

    with pytest.raises(TrainerSourceProvenanceLedgerV4Error):
        ledger.read_entries()


def test_owned_cas_root_requires_owner_only_mode(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    ledger.store_root.chmod(0o755)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_cas_root_integrity_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_owned_cas_root_symlink_is_rejected(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    _append(ledger, capture, recorded_at)
    backup = tmp_path / "owned-cas-backup"
    ledger.store_root.rename(backup)
    ledger.store_root.symlink_to(backup, target_is_directory=True)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4IntegrityError,
        match="owned_cas_root_integrity_invalid",
    ):
        TrainerSourceProvenanceLedgerV4(ledger.root).read_entries()


def test_preexisting_head_temp_symlink_is_never_followed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    ledger.root.mkdir(mode=0o700)
    fixed_hex = "f" * 32

    class _FixedUuid:
        hex = fixed_hex

    monkeypatch.setattr(uuid, "uuid4", lambda: _FixedUuid())
    temp_name = (
        f".{TRAINER_SOURCE_PROVENANCE_LEDGER_V4_HEAD_FILENAME}."
        f"{os.getpid()}.{threading.get_ident()}.{fixed_hex}.tmp"
    )
    target = tmp_path / "symlink-target"
    target.write_bytes(b"must-not-change")
    (ledger.root / temp_name).symlink_to(target)

    with pytest.raises(
        TrainerSourceProvenanceLedgerV4DurabilityError,
        match="head_publish_failed",
    ):
        _append(ledger, capture, recorded_at)
    assert target.read_bytes() == b"must-not-change"


def test_run_cycle_ids_and_ledger_clock_are_strict(tmp_path: Path) -> None:
    capture, recorded_at = _build_capture(tmp_path / "capture")
    ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "ledger-v4")
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4ValidationError,
        match="run_id_invalid",
    ):
        _append(ledger, capture, recorded_at, run_id="../unsafe")
    with pytest.raises(
        TrainerSourceProvenanceLedgerV4ValidationError,
        match="recorded_before_source_read",
    ):
        _append(ledger, capture, recorded_at - timedelta(hours=1))
    assert not ledger.path.exists()
