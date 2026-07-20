from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from v2.backend.app.services.native_trainer import (
    feature_snapshot_publication_ledger_v4 as ledger_module,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    feature_abi_contract,
    feature_requirement_classes_for_names,
)
from v2.backend.app.services.native_trainer.feature_snapshot_cas_publication import (
    NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
    NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
    FeatureSnapshotCasArtifact,
    canonical_feature_snapshot_bytes,
    create_feature_snapshot_cas_artifact,
)
from v2.backend.app.services.native_trainer.feature_snapshot_publication_ledger_v4 import (
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_DOWNSTREAM_STATUS,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_GENESIS_SHA256,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME,
    FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION,
    INCOMPLETE_FALLBACK_ABI_ORIGIN,
    NATIVE_MODEL_ABI_ORIGIN,
    SOURCE_SCOPE_INCOMPLETENESS_REASONS,
    UNRESOLVED_SOURCE_LABEL,
    FeatureSnapshotPublicationAppendResultV4,
    FeatureSnapshotPublicationLedgerEntryV4,
    FeatureSnapshotPublicationLedgerV4,
    FeatureSnapshotPublicationLedgerV4ConflictError,
    FeatureSnapshotPublicationLedgerV4Error,
    FeatureSnapshotPublicationLedgerV4IntegrityError,
    FeatureSnapshotPublicationLedgerV4ValidationError,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TrainerSourceProvenanceLedgerV4,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "1m"
BASE_MS = 1_700_000_000_000
REDIS_TIME = (1_700_010_000, 123_456)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MODEL_FEATURE_NAMES = tuple(name for name, _source in FEATURE_SPEC)
_MODEL_REQUIREMENTS = feature_requirement_classes_for_names(_MODEL_FEATURE_NAMES)
_REQUIRED_MODEL_FEATURE_NAMES = tuple(
    name
    for name, requirement in zip(_MODEL_FEATURE_NAMES, _MODEL_REQUIREMENTS, strict=True)
    if requirement == "REQUIRED"
)
_OPTIONAL_MODEL_FEATURE_NAMES = tuple(
    name
    for name, requirement in zip(_MODEL_FEATURE_NAMES, _MODEL_REQUIREMENTS, strict=True)
    if requirement == "OPTIONAL_EVENT_DEPENDENT"
)
_EXPECTED_MODEL_ABI_SHA256 = "e81b6dd95bfba930d67e694941f21a6d4ab5432142c25595848148c8bb42ddf9"
_REQUIRED_THEN_OPTIONAL_ABI_SHA256 = (
    "568ca431be3eedbfb31cc0ad1e039bd4927f2b66ab5784574394ddd2cb88b620"
)


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


def _source_rows() -> list[dict[str, Any]]:
    # The P0-B adapter derives this 71-row minimum from the active TA contract.
    return [_canonical_rest(0), *(_canonical_wss(index) for index in range(1, 71))]


def _native_ms(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _native_ms_from_epoch(value: int) -> str:
    return _native_ms(_EPOCH + timedelta(milliseconds=value))


def _native_snapshot_id(snapshot_without_id: dict[str, object]) -> str:
    encoded = json.dumps(snapshot_without_id, sort_keys=True).encode()
    return f"v2_fsnap_{hashlib.sha256(encoded).hexdigest()}"


def _reidentify(snapshot: dict[str, object]) -> None:
    snapshot.pop("feature_snapshot_id", None)
    snapshot["feature_snapshot_id"] = _native_snapshot_id(snapshot)


def _source_ledger(tmp_path: Path) -> tuple[TrainerSourceProvenanceLedgerV4, Any, datetime]:
    tmp_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    rows = _source_rows()
    payload = json.dumps(rows, ensure_ascii=True, indent=2).encode("ascii")
    observed_at = _EPOCH + timedelta(milliseconds=cast(int, rows[-1]["candle_close_time"]) + 500)
    capture_root = tmp_path / "capture"
    capture_root.mkdir(mode=0o700)
    capture = capture_canonical_closed_ohlcv_atomic_receipts(
        _FakeClient([b"string", payload, 600_000, REDIS_TIME]),
        ImmutableSourcePayloadStore(capture_root / "source-cas"),
        expected_symbol=SYMBOL,
        expected_timeframe=TIMEFRAME,
        consumer_clock=lambda: observed_at,
    )
    recorded_at = observed_at + timedelta(seconds=1)
    source_ledger = TrainerSourceProvenanceLedgerV4(tmp_path / "source-ledger")
    result = source_ledger.append_atomic_capture(
        capture,
        trainer_run_id="trainer-run-p0d",
        trainer_cycle_id="trainer-cycle-p0d",
        ledger_clock=lambda: recorded_at,
    )
    return source_ledger, result, recorded_at


def _snapshot_for_source(source_result: Any, **overrides: object) -> dict[str, object]:
    last = source_result.entry.record["ordered_rows"][-1]
    snapshot: dict[str, object] = {
        "schema_version": NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
        "worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "features": {"close": 102.0, "rsi_14": 52.25, "fear_greed_score": None},
        "candle_closed_confirmed": True,
        "candle_open_time": _native_ms_from_epoch(last["candle_open_time_ms"]),
        "candle_close_time": _native_ms_from_epoch(last["candle_close_time_ms"]),
        "event_time": _native_ms_from_epoch(last["producer_event_time_ms"]),
        "ingested_at": _native_ms_from_epoch(last["ingested_at_ms"]),
        "source_available_at": _native_ms_from_epoch(last["available_at_ms"]),
        "feature_cutoff": _native_ms_from_epoch(last["candle_close_time_ms"]),
        "generated_at": _native_ms_from_epoch(last["available_at_ms"] + 1),
        "source": last["source"],
        "is_backfilled": False,
        "source_sequence_id": last["source_sequence_id"],
        "raw_payload_hash": last["raw_payload_hash"],
        "exact_source_clock_valid": True,
        "exact_source_clock_rejection_reasons": [],
        "available_at": None,
        "feature_available_at": None,
        "exact_feature_availability_valid": False,
        "exact_feature_availability_rejection_reasons": ["FEATURE_PUBLICATION_RECEIPT_REQUIRED"],
        "required_model_feature_pit_coverage_valid": False,
        "required_model_feature_pit_rejection_reasons": [
            "REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED"
        ],
        "ohlcv_history_payload_receipts_valid": False,
        "ohlcv_history_payload_receipt_rejection_reasons": [
            "IMMUTABLE_OHLCV_HISTORY_PAYLOAD_RECEIPTS_REQUIRED"
        ],
        "trainer_consumable": False,
        "valid_for_prediction": False,
        "valid_for_paper": False,
        "missing_feature_flags": ["fear_greed_score"],
        "stale_feature_flags": [],
    }
    snapshot.update(overrides)
    _reidentify(snapshot)
    return snapshot


def _declared_native_snapshot_for_source(
    source_result: Any,
    **overrides: object,
) -> dict[str, object]:
    snapshot = _snapshot_for_source(
        source_result,
        features={name: float(index + 1) for index, name in enumerate(_MODEL_FEATURE_NAMES)},
        missing_feature_flags=[],
        feature_requirement_policy_id="v2_hybrid_feature_requirements_v1",
        model_feature_abi_slot_count=len(_MODEL_FEATURE_NAMES),
        required_model_feature_count=len(_REQUIRED_MODEL_FEATURE_NAMES),
        required_model_feature_fields=list(_REQUIRED_MODEL_FEATURE_NAMES),
        required_model_feature_missing_fields=[],
        required_model_feature_value_contract_valid=True,
        optional_event_dependent_feature_count=len(_OPTIONAL_MODEL_FEATURE_NAMES),
        optional_event_dependent_feature_fields=list(_OPTIONAL_MODEL_FEATURE_NAMES),
        optional_event_dependent_feature_present_fields=sorted(_OPTIONAL_MODEL_FEATURE_NAMES),
        optional_event_dependent_feature_missing_fields=[],
    )
    snapshot.update(overrides)
    _reidentify(snapshot)
    return snapshot


def _publish_artifact(
    tmp_path: Path,
    snapshot: dict[str, object],
) -> FeatureSnapshotCasArtifact:
    root = tmp_path / "artifact-store"
    root.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    store = ImmutableSourcePayloadStore(root)
    payload = canonical_feature_snapshot_bytes(snapshot)
    return create_feature_snapshot_cas_artifact(
        source_payload_store=store,
        artifact_snapshot_bytes=payload,
        expected_feature_snapshot_id=cast(str, snapshot["feature_snapshot_id"]),
        expected_symbol=cast(str, snapshot["symbol"]),
        expected_timeframe=cast(str, snapshot["timeframe"]),
    )


def _harness(
    tmp_path: Path,
) -> tuple[
    FeatureSnapshotPublicationLedgerV4,
    Any,
    FeatureSnapshotCasArtifact,
    datetime,
]:
    source_ledger, source_result, source_recorded_at = _source_ledger(tmp_path)
    artifact = _publish_artifact(
        tmp_path / "artifact",
        _snapshot_for_source(source_result),
    )
    ledger = FeatureSnapshotPublicationLedgerV4(
        tmp_path / "publication-ledger",
        source_provenance_ledger=source_ledger,
    )
    return ledger, source_result, artifact, source_recorded_at + timedelta(seconds=1)


def _append(
    ledger: FeatureSnapshotPublicationLedgerV4,
    source_result: Any,
    artifact: FeatureSnapshotCasArtifact,
    recorded_at: datetime,
) -> FeatureSnapshotPublicationAppendResultV4:
    return ledger.append_incomplete_artifact_publication(
        artifact,
        source_ledger_sequence=source_result.entry.ledger_sequence,
        source_ledger_entry_sha256=source_result.entry.entry_sha256,
        ledger_clock=lambda: recorded_at,
    )


def _assert_downstream_false(value: object) -> None:
    for field_name in ledger_module._DOWNSTREAM_FLAG_FIELDS:
        assert getattr(value, field_name) is False


def _rewrite_record_and_head(
    ledger: FeatureSnapshotPublicationLedgerV4,
    record: dict[str, Any],
) -> None:
    record["publication_identity_sha256"] = ledger_module._publication_identity(
        record["source_provenance_binding"],
        record["feature_artifact_binding"],
    )
    record["publication_replay_identity_sha256"] = ledger_module._stable_sha256(
        ledger_module._replay_material_from_record(record)
    )
    material = {key: value for key, value in record.items() if key != "entry_sha256"}
    record["entry_sha256"] = ledger_module._stable_sha256(material)
    framed = ledger_module._canonical_json(record).encode("ascii") + b"\n"
    ledger.path.write_bytes(framed)
    ledger.path.chmod(0o600)
    head = ledger_module._head_material(
        raw_prefix=framed,
        sequence=1,
        entry_sha256=record["entry_sha256"],
    )
    ledger.head_path.write_text(
        ledger_module._canonical_json(head, max_bytes=ledger_module.MAX_HEAD_BYTES) + "\n",
        encoding="ascii",
    )
    ledger.head_path.chmod(0o600)


def test_append_binds_p0c_suffix_artifact_vector_clocks_and_fail_closed_flags(
    tmp_path: Path,
) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)

    result = _append(ledger, source_result, artifact, recorded_at)

    assert result.disposition == "APPENDED"
    assert result.incomplete_artifact_publication_ledger_recorded is True
    assert result.durable_postcommit_readback_verified is True
    _assert_downstream_false(result)
    _assert_downstream_false(result.entry)
    record = result.entry.record
    assert record["schema_version"] == FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_SCHEMA_VERSION
    assert record["evidence_classification"] == (
        FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_EVIDENCE_CLASSIFICATION
    )
    assert record["downstream_status"] == (FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_DOWNSTREAM_STATUS)
    assert record["ledger_sequence"] == 1
    assert record["previous_entry_sha256"] == (
        FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_GENESIS_SHA256
    )
    assert record["source_scope_incompleteness_reasons"] == list(
        SOURCE_SCOPE_INCOMPLETENESS_REASONS
    )
    source = record["source_provenance_binding"]
    assert source["source_ledger_sequence"] == source_result.entry.ledger_sequence
    assert source["source_ledger_entry_sha256"] == source_result.entry.entry_sha256
    assert source["source_replay_identity_sha256"] == (source_result.entry.replay_identity_sha256)
    assert source["selected_row_count"] == 71
    assert len(source["ordered_source_read_receipt_sha256s"]) == 71
    assert source["selected_candle_ids"][-1] == source["latest_candle"]["candle_id"]
    published = record["feature_artifact_binding"]
    assert published["artifact_record_id"] == artifact.artifact_record_id
    assert published["artifact_binding_sha256"] == artifact.artifact_binding_sha256
    assert published["feature_snapshot_id"] == artifact.artifact_binding["feature_snapshot_id"]
    assert published["artifact_serialization_sha256"] == artifact.cas_address.payload_sha256
    vector = record["feature_vector_binding"]
    assert vector["abi_origin"] == INCOMPLETE_FALLBACK_ABI_ORIGIN
    assert vector["ordered_feature_names"] == ["close", "fear_greed_score", "rsi_14"]
    assert vector["ordered_feature_values"] == [102.0, 0.0, 52.25]
    assert vector["missing_mask"] == [0, 1, 0]
    assert vector["stale_mask"] == [0, 0, 0]
    assert vector["source_availability_mask"] == [0, 0, 0]
    assert vector["ordered_feature_requirement_classes"] == [
        "REQUIRED",
        "OPTIONAL_EVENT_DEPENDENT",
        "REQUIRED",
    ]
    assert vector["ordered_resolved_source_labels"] == [UNRESOLVED_SOURCE_LABEL] * 3
    assert vector["per_field_root_receipt_sha256s"] == [None, None, None]
    assert vector["per_field_available_at"] == [None, None, None]
    assert vector["feature_source_evidence_complete"] is False
    assert vector["feature_available_at_complete"] is False
    derivation = record["derivation_binding"]
    assert derivation["producer_code_sha256"] is None
    assert derivation["producer_configuration_sha256"] is None
    assert derivation["feature_transform_sha256"] is None
    assert derivation["derivation_identity_complete"] is False
    temporal = record["temporal_binding"]
    assert temporal["feature_available_at"] is None
    assert temporal["publication_completed_at"] is None
    assert temporal["decision_time"] is None
    assert temporal["execution_time"] is None
    assert temporal["available_at_feature_cutoff_decision_order_applicable"] is False
    assert temporal["available_at_feature_cutoff_decision_order_verified"] is False
    assert ledger.path.name == FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_FILENAME
    assert ledger.head_path.name == FEATURE_SNAPSHOT_PUBLICATION_LEDGER_V4_HEAD_FILENAME
    assert stat.S_IMODE(ledger.root.stat().st_mode) == 0o700
    assert stat.S_IMODE(ledger.path.stat().st_mode) == 0o600
    assert ledger.read_entries() == (result.entry,)


def test_exact_replay_with_later_clock_is_idempotent(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    first = _append(ledger, source_result, artifact, recorded_at)

    replay = _append(
        ledger,
        source_result,
        artifact,
        recorded_at + timedelta(minutes=5),
    )

    assert replay.disposition == "EXACT_REPLAY"
    assert replay.entry == first.entry
    assert len(ledger.read_entries()) == 1


def test_latest_candle_mismatch_fails_before_ledger_append(tmp_path: Path) -> None:
    source_ledger, source_result, recorded_at = _source_ledger(tmp_path)
    snapshot = _snapshot_for_source(source_result, raw_payload_hash="b" * 64)
    artifact = _publish_artifact(tmp_path / "artifact", snapshot)
    ledger = FeatureSnapshotPublicationLedgerV4(
        tmp_path / "publication-ledger",
        source_provenance_ledger=source_ledger,
    )

    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4ValidationError,
        match="latest_candle_not_exact_p0c_tail",
    ):
        _append(ledger, source_result, artifact, recorded_at + timedelta(seconds=1))
    assert not ledger.path.exists()


def test_wrong_source_sequence_or_hash_fails_closed(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    with pytest.raises(FeatureSnapshotPublicationLedgerV4ValidationError):
        ledger.append_incomplete_artifact_publication(
            artifact,
            source_ledger_sequence=2,
            source_ledger_entry_sha256=source_result.entry.entry_sha256,
            ledger_clock=lambda: recorded_at,
        )
    with pytest.raises(FeatureSnapshotPublicationLedgerV4ConflictError):
        ledger.append_incomplete_artifact_publication(
            artifact,
            source_ledger_sequence=1,
            source_ledger_entry_sha256="f" * 64,
            ledger_clock=lambda: recorded_at,
        )


def test_factory_authentication_and_frozen_public_results(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    result = _append(ledger, source_result, artifact, recorded_at)

    with pytest.raises(FeatureSnapshotPublicationLedgerV4IntegrityError, match="factory"):
        FeatureSnapshotPublicationLedgerEntryV4(
            schema_version=result.entry.schema_version,
            ledger_sequence=result.entry.ledger_sequence,
            previous_entry_sha256=result.entry.previous_entry_sha256,
            publication_identity_sha256=result.entry.publication_identity_sha256,
            publication_replay_identity_sha256=result.entry.publication_replay_identity_sha256,
            source_ledger_sequence=result.entry.source_ledger_sequence,
            source_ledger_entry_sha256=result.entry.source_ledger_entry_sha256,
            artifact_record_id=result.entry.artifact_record_id,
            feature_snapshot_id=result.entry.feature_snapshot_id,
            entry_sha256=result.entry.entry_sha256,
            entry_json=result.entry.entry_json,
            _source_ledger=ledger.source_provenance_ledger,
            _owned_store=ImmutableSourcePayloadStore(ledger.store_root),
            _expected_owned_store_root=ledger.store_root,
            _construction_token=object(),
        )
    with pytest.raises(FeatureSnapshotPublicationLedgerV4IntegrityError, match="factory"):
        FeatureSnapshotPublicationAppendResultV4(
            entry=result.entry,
            disposition="APPENDED",
            _construction_token=object(),
        )
    with pytest.raises(FrozenInstanceError):
        result.entry.live_execution_authorized = True  # type: ignore[misc]
    with pytest.raises(ValueError):
        replace(result.entry, live_execution_authorized=True)
    with pytest.raises(ValueError):
        replace(result, trainer_admission_granted=True)


def test_public_dataclass_flags_are_present_once_and_init_false() -> None:
    entry_fields = tuple(item.name for item in fields(FeatureSnapshotPublicationLedgerEntryV4))
    result_fields = tuple(item.name for item in fields(FeatureSnapshotPublicationAppendResultV4))
    for flag in ledger_module._DOWNSTREAM_FLAG_FIELDS:
        assert entry_fields.count(flag) == 1
        assert result_fields.count(flag) == 1
        assert FeatureSnapshotPublicationLedgerEntryV4.__dataclass_fields__[flag].init is False
        assert FeatureSnapshotPublicationAppendResultV4.__dataclass_fields__[flag].init is False


@pytest.mark.parametrize(
    "mutator",
    [
        lambda record: record["feature_vector_binding"]["ordered_feature_values"].__setitem__(
            0, 999.0
        ),
        lambda record: record["feature_vector_binding"]["missing_mask"].__setitem__(0, 1),
        lambda record: record["feature_vector_binding"][
            "ordered_resolved_source_labels"
        ].__setitem__(0, "forged-source"),
        lambda record: record["feature_vector_binding"].__setitem__(
            "abi_origin", NATIVE_MODEL_ABI_ORIGIN
        ),
        lambda record: record["derivation_binding"].__setitem__("producer_code_sha256", "a" * 64),
    ],
)
def test_coherently_rehashed_nested_vector_or_derivation_tampering_fails(
    tmp_path: Path,
    mutator: Any,
) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    result = _append(ledger, source_result, artifact, recorded_at)
    record = deepcopy(result.entry.record)
    mutator(record)
    vector = record["feature_vector_binding"]
    vector["ordered_values_sha256"] = ledger_module._stable_sha256(
        {
            "ordered_feature_names": vector["ordered_feature_names"],
            "ordered_feature_values": vector["ordered_feature_values"],
        }
    )
    vector["mask_vectors_sha256"] = ledger_module._stable_sha256(
        {
            "missing_mask": vector["missing_mask"],
            "stale_mask": vector["stale_mask"],
            "source_availability_mask": vector["source_availability_mask"],
        }
    )
    vector["per_field_bindings_sha256"] = ledger_module._stable_sha256(
        {
            "ordered_resolved_source_labels": vector["ordered_resolved_source_labels"],
            "per_field_root_receipt_sha256s": vector["per_field_root_receipt_sha256s"],
            "per_field_available_at": vector["per_field_available_at"],
        }
    )
    vector_material = {
        key: value for key, value in vector.items() if key != "vector_binding_sha256"
    }
    vector["vector_binding_sha256"] = ledger_module._stable_sha256(vector_material)
    derivation = record["derivation_binding"]
    derivation_material = {
        key: value for key, value in derivation.items() if key != "derivation_binding_sha256"
    }
    derivation["derivation_binding_sha256"] = ledger_module._stable_sha256(derivation_material)
    _rewrite_record_and_head(ledger, record)

    with pytest.raises(FeatureSnapshotPublicationLedgerV4IntegrityError):
        ledger.read_entries()


def test_coherent_source_binding_tamper_fails_against_fresh_p0c(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    result = _append(ledger, source_result, artifact, recorded_at)
    record = deepcopy(result.entry.record)
    source = record["source_provenance_binding"]
    source["trainer_cycle_id"] = "forged-cycle"
    source_material = {
        key: value for key, value in source.items() if key != "source_scope_binding_sha256"
    }
    source["source_scope_binding_sha256"] = ledger_module._stable_sha256(source_material)
    _rewrite_record_and_head(ledger, record)

    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="fresh_read_mismatch",
    ):
        ledger.read_entries()


def test_coherent_artifact_projection_and_temporal_tamper_fails_owned_copy(
    tmp_path: Path,
) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    result = _append(ledger, source_result, artifact, recorded_at)
    record = deepcopy(result.entry.record)
    projected = record["feature_artifact_binding"]
    projected["generated_at"] = record["ledger_recorded_at"]
    projection_material = {
        key: value
        for key, value in projected.items()
        if key != "artifact_binding_projection_sha256"
    }
    projected["artifact_binding_projection_sha256"] = ledger_module._stable_sha256(
        projection_material
    )
    record["temporal_binding"] = ledger_module._temporal_binding(
        artifact_binding=projected,
        source_binding=record["source_provenance_binding"],
        ledger_recorded_at=record["ledger_recorded_at"],
    )
    _rewrite_record_and_head(ledger, record)

    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="owned_artifact_projection_mismatch",
    ):
        ledger.read_entries()


def test_duplicate_json_key_is_rejected_even_with_rewritten_head(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    result = _append(ledger, source_result, artifact, recorded_at)
    raw = ledger.path.read_bytes()
    needle = b'{"consumer_eligible":false,'
    assert needle in raw
    tampered = raw.replace(
        needle,
        b'{"consumer_eligible":false,"consumer_eligible":false,',
        1,
    )
    ledger.path.write_bytes(tampered)
    ledger.path.chmod(0o600)
    head = ledger_module._head_material(
        raw_prefix=tampered,
        sequence=1,
        entry_sha256=result.entry.entry_sha256,
    )
    ledger.head_path.write_text(
        ledger_module._canonical_json(head, max_bytes=ledger_module.MAX_HEAD_BYTES) + "\n",
        encoding="ascii",
    )
    ledger.head_path.chmod(0o600)

    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="duplicate_json_key",
    ):
        ledger.read_entries()


def test_owned_artifact_cas_mutation_or_hardlink_fails_closed(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    result = _append(ledger, source_result, artifact, recorded_at)
    address = result.entry.record["feature_artifact_binding"][
        "ledger_owned_artifact_content_cas_address"
    ]
    object_path = ledger.store_root / address["relative_path"]
    object_path.chmod(0o600)
    object_path.write_bytes(b"forged")
    object_path.chmod(0o400)

    with pytest.raises(FeatureSnapshotPublicationLedgerV4IntegrityError):
        ledger.read_entries()

    # Restore via a clean harness and prove link-count validation separately.
    second = tmp_path / "hardlink-case"
    second.mkdir()
    ledger2, source2, artifact2, at2 = _harness(second)
    result2 = _append(ledger2, source2, artifact2, at2)
    address2 = result2.entry.record["feature_artifact_binding"][
        "ledger_owned_artifact_content_cas_address"
    ]
    object2 = ledger2.store_root / address2["relative_path"]
    os.link(object2, object2.with_name(object2.name + ".hardlink"))
    with pytest.raises(FeatureSnapshotPublicationLedgerV4IntegrityError):
        ledger2.read_entries()


def test_external_artifact_cas_is_required_during_append_but_owned_afterward(
    tmp_path: Path,
) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    content = artifact.source_payload_store.path_for(artifact.cas_address.payload_sha256)
    content.unlink()
    with pytest.raises(FeatureSnapshotPublicationLedgerV4ValidationError):
        _append(ledger, source_result, artifact, recorded_at)

    fresh_root = tmp_path / "owned-case"
    fresh_root.mkdir()
    ledger2, source2, artifact2, at2 = _harness(fresh_root)
    result2 = _append(ledger2, source2, artifact2, at2)
    shutil.rmtree(artifact2.source_payload_store.root_path)
    # Durable reads rely on the separately pinned P0-D CAS, not the deleted
    # artifact producer's store.
    assert ledger2.read_entries()[0].entry_sha256 == result2.entry.entry_sha256


def test_truncated_ledger_and_head_mismatch_fail_closed(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    _append(ledger, source_result, artifact, recorded_at)
    raw = ledger.path.read_bytes()
    ledger.path.write_bytes(raw[:-1])
    ledger.path.chmod(0o600)
    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="truncated_or_partial_tail",
    ):
        ledger.read_entries()

    second = tmp_path / "head-case"
    second.mkdir()
    ledger2, source2, artifact2, at2 = _harness(second)
    _append(ledger2, source2, artifact2, at2)
    head = json.loads(ledger2.head_path.read_text(encoding="ascii"))
    head["ledger_sha256"] = "0" * 64
    material = {key: value for key, value in head.items() if key != "head_sha256"}
    head["head_sha256"] = ledger_module._stable_sha256(material)
    ledger2.head_path.write_text(
        ledger_module._canonical_json(head, max_bytes=ledger_module.MAX_HEAD_BYTES) + "\n",
        encoding="ascii",
    )
    ledger2.head_path.chmod(0o600)
    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="head_ledger_binding_invalid",
    ):
        ledger2.read_entries()


def test_exact_pending_tail_recovery_requires_exact_replay(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    first = _append(ledger, source_result, artifact, recorded_at)
    ledger.head_path.unlink()

    recovered = _append(
        ledger,
        source_result,
        artifact,
        recorded_at + timedelta(seconds=10),
    )

    assert recovered.disposition == "RECOVERED_EXACT_PENDING_APPEND"
    assert recovered.entry.entry_sha256 == first.entry.entry_sha256
    assert len(ledger.read_entries()) == 1


def test_concurrent_exact_appends_produce_one_committed_entry(tmp_path: Path) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)

    def append(index: int) -> str:
        return _append(
            ledger,
            source_result,
            artifact,
            recorded_at + timedelta(seconds=index),
        ).disposition

    with ThreadPoolExecutor(max_workers=8) as executor:
        dispositions = list(executor.map(append, range(8)))

    assert dispositions.count("APPENDED") == 1
    assert dispositions.count("EXACT_REPLAY") == 7
    assert len(ledger.read_entries()) == 1


def test_lock_inode_replacement_during_critical_section_fails_closed(
    tmp_path: Path,
) -> None:
    ledger, _source_result, _artifact, _recorded_at = _harness(tmp_path)

    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="feature_publication_v4_lock_changed",
    ):
        with ledger._exclusive_lock():
            ledger.lock_path.unlink()
            ledger.lock_path.write_bytes(b"")
            ledger.lock_path.chmod(0o600)


@pytest.mark.parametrize("unsafe_name", ["lock", "ledger", "head"])
def test_symlink_and_hardlink_control_files_fail_closed(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    ledger, source_result, artifact, recorded_at = _harness(tmp_path)
    ledger.root.mkdir(mode=0o700)
    target = ledger.root / "target"
    target.write_text("x", encoding="ascii")
    target.chmod(0o600)
    selected = {
        "lock": ledger.lock_path,
        "ledger": ledger.path,
        "head": ledger.head_path,
    }[unsafe_name]
    if unsafe_name == "lock":
        selected.symlink_to(target)
    else:
        os.link(target, selected)

    with pytest.raises(FeatureSnapshotPublicationLedgerV4Error):
        _append(ledger, source_result, artifact, recorded_at)


def test_root_path_and_mode_bounds_fail_closed(tmp_path: Path) -> None:
    source_ledger, _source_result, _at = _source_ledger(tmp_path)
    with pytest.raises(FeatureSnapshotPublicationLedgerV4ValidationError):
        FeatureSnapshotPublicationLedgerV4(
            Path("relative-ledger"),
            source_provenance_ledger=source_ledger,
        )
    too_deep = Path("/").joinpath(*(f"p{index}" for index in range(130)))
    with pytest.raises(FeatureSnapshotPublicationLedgerV4ValidationError):
        FeatureSnapshotPublicationLedgerV4(
            too_deep,
            source_provenance_ledger=source_ledger,
        )

    ledger, source_result, artifact, recorded_at = _harness(tmp_path / "mode-case")
    ledger.root.mkdir(mode=0o700)
    ledger.root.chmod(0o755)
    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="private_owner_mode_required",
    ):
        _append(ledger, source_result, artifact, recorded_at)


def test_ledger_size_bound_fails_before_unbounded_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger, _source_result, _artifact, _recorded_at = _harness(tmp_path)
    ledger.root.mkdir(mode=0o700)
    ledger.path.write_bytes(b"x" * 1025)
    ledger.path.chmod(0o600)
    monkeypatch.setattr(ledger_module, "MAX_LEDGER_BYTES", 1024)

    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="file_size_invalid",
    ):
        ledger.read_entries()


def test_native_declared_vector_preserves_tensor_builder_model_abi_order(
    tmp_path: Path,
) -> None:
    assert len(_MODEL_FEATURE_NAMES) == 446
    assert len(set(_MODEL_FEATURE_NAMES)) == 446
    assert len(_REQUIRED_MODEL_FEATURE_NAMES) == 384
    assert len(_OPTIONAL_MODEL_FEATURE_NAMES) == 62
    required_then_optional = _REQUIRED_MODEL_FEATURE_NAMES + _OPTIONAL_MODEL_FEATURE_NAMES
    first_divergence = next(
        index
        for index, (model_name, concatenated_name) in enumerate(
            zip(_MODEL_FEATURE_NAMES, required_then_optional, strict=True)
        )
        if model_name != concatenated_name
    )
    assert first_divergence == 134
    assert _MODEL_FEATURE_NAMES[134] == "last_liq_bps_24h"
    assert _MODEL_REQUIREMENTS[134] == "OPTIONAL_EVENT_DEPENDENT"
    assert required_then_optional[134] == "liquidation_is_stale"
    model_abi = feature_abi_contract(_MODEL_FEATURE_NAMES)
    concatenated_abi = feature_abi_contract(required_then_optional)
    assert ledger_module._stable_sha256(model_abi) == _EXPECTED_MODEL_ABI_SHA256
    assert ledger_module._stable_sha256(concatenated_abi) == _REQUIRED_THEN_OPTIONAL_ABI_SHA256

    source_ledger, source_result, source_recorded_at = _source_ledger(tmp_path)
    snapshot = _declared_native_snapshot_for_source(source_result)
    artifact = _publish_artifact(tmp_path / "artifact", snapshot)
    ledger = FeatureSnapshotPublicationLedgerV4(
        tmp_path / "publication-ledger",
        source_provenance_ledger=source_ledger,
    )
    result = _append(
        ledger,
        source_result,
        artifact,
        source_recorded_at + timedelta(seconds=1),
    )
    vector = result.entry.record["feature_vector_binding"]
    assert vector["abi_origin"] == NATIVE_MODEL_ABI_ORIGIN
    assert vector["feature_count"] == 446
    assert vector["ordered_feature_names"] == list(_MODEL_FEATURE_NAMES)
    assert vector["ordered_feature_names"][134] == "last_liq_bps_24h"
    assert vector["ordered_feature_requirement_classes"][134] == ("OPTIONAL_EVENT_DEPENDENT")
    assert vector["feature_abi"] == model_abi
    assert vector["feature_abi_sha256"] == _EXPECTED_MODEL_ABI_SHA256
    assert vector["feature_abi_sha256"] != _REQUIRED_THEN_OPTIONAL_ABI_SHA256
    assert vector["ordered_feature_names"] != list(required_then_optional)
    persisted = ledger.read_entries()
    assert len(persisted) == 1
    assert (
        persisted[0].record["feature_vector_binding"]["feature_abi_sha256"]
        == _EXPECTED_MODEL_ABI_SHA256
    )
    replay = _append(
        ledger,
        source_result,
        artifact,
        source_recorded_at + timedelta(minutes=5),
    )
    assert replay.disposition == "EXACT_REPLAY"
    assert replay.entry.entry_sha256 == result.entry.entry_sha256
    assert (
        replay.entry.record["feature_vector_binding"]["feature_abi_sha256"]
        == _EXPECTED_MODEL_ABI_SHA256
    )
    _assert_downstream_false(replay)
    _assert_downstream_false(replay.entry)


def test_invalid_declared_missing_vector_fails_without_weakening(tmp_path: Path) -> None:
    source_ledger, source_result, source_recorded_at = _source_ledger(tmp_path)
    snapshot = _declared_native_snapshot_for_source(
        source_result,
        required_model_feature_missing_fields=["close"],
        required_model_feature_value_contract_valid=False,
    )
    artifact = _publish_artifact(tmp_path / "artifact", snapshot)
    ledger = FeatureSnapshotPublicationLedgerV4(
        tmp_path / "publication-ledger",
        source_provenance_ledger=source_ledger,
    )
    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match="required_missing_declaration_mismatch",
    ):
        _append(
            ledger,
            source_result,
            artifact,
            source_recorded_at + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ("tamper", "error_reason"),
    [
        ("required_order_drift", "required_feature_declaration_mismatch"),
        ("optional_order_drift", "optional_feature_declaration_mismatch"),
        ("unknown_required_name", "required_feature_declaration_mismatch"),
        ("duplicate_required_name", "required_feature_names_invalid"),
        ("cross_class_duplicate", "declared_feature_names_not_unique"),
        ("required_count", "required_count_mismatch"),
        ("optional_count", "optional_count_mismatch"),
        ("abi_count", "declared_abi_count_mismatch"),
        ("policy", "requirement_policy_mismatch"),
        ("partial_declaration", "partial_requirement_declaration"),
    ],
)
def test_native_declaration_drift_and_tampering_fail_closed(
    tmp_path: Path,
    tamper: str,
    error_reason: str,
) -> None:
    source_ledger, source_result, source_recorded_at = _source_ledger(tmp_path)
    snapshot = _declared_native_snapshot_for_source(source_result)
    required = cast(list[str], snapshot["required_model_feature_fields"])
    optional = cast(list[str], snapshot["optional_event_dependent_feature_fields"])
    if tamper == "required_order_drift":
        required[0], required[1] = required[1], required[0]
    elif tamper == "optional_order_drift":
        optional[0], optional[1] = optional[1], optional[0]
    elif tamper == "unknown_required_name":
        required[0] = "unknown_native_model_feature"
    elif tamper == "duplicate_required_name":
        required[1] = required[0]
    elif tamper == "cross_class_duplicate":
        optional[0] = required[0]
    elif tamper == "required_count":
        snapshot["required_model_feature_count"] = len(required) + 1
    elif tamper == "optional_count":
        snapshot["optional_event_dependent_feature_count"] = len(optional) + 1
    elif tamper == "abi_count":
        snapshot["model_feature_abi_slot_count"] = len(_MODEL_FEATURE_NAMES) - 1
    elif tamper == "policy":
        snapshot["feature_requirement_policy_id"] = "tampered_requirement_policy"
    elif tamper == "partial_declaration":
        snapshot.pop("optional_event_dependent_feature_fields")
    else:  # pragma: no cover - the parameter table is code-owned above.
        raise AssertionError(f"unhandled test tamper: {tamper}")
    _reidentify(snapshot)
    artifact = _publish_artifact(tmp_path / "artifact", snapshot)
    ledger = FeatureSnapshotPublicationLedgerV4(
        tmp_path / "publication-ledger",
        source_provenance_ledger=source_ledger,
    )
    with pytest.raises(
        FeatureSnapshotPublicationLedgerV4IntegrityError,
        match=error_reason,
    ):
        _append(
            ledger,
            source_result,
            artifact,
            source_recorded_at + timedelta(seconds=1),
        )
    assert not ledger.path.exists()


def test_no_active_runtime_module_imports_unwired_p0d() -> None:
    repo = Path(__file__).resolve().parents[6]
    production_root = repo / "v2" / "backend" / "app"
    imports: list[Path] = []
    for path in production_root.rglob("*.py"):
        if path.name == "feature_snapshot_publication_ledger_v4.py":
            continue
        if "feature_snapshot_publication_ledger_v4" in path.read_text(
            encoding="utf-8", errors="strict"
        ):
            imports.append(path)
    assert imports == []
