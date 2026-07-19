from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.native_trainer.feature_snapshot_cas_publication import (
    CAS_ARTIFACT_BINDING_SCHEMA_VERSION,
    CAS_ARTIFACT_EVIDENCE_CLASSIFICATION,
    CAS_ARTIFACT_IDENTITY_SCHEMA_VERSION,
    CAS_ARTIFACT_RETRY_SEMANTICS,
    CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION,
    NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
    NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
    FeatureSnapshotCasArtifact,
    FeatureSnapshotPublicationIntegrityError,
    FeatureSnapshotPublicationValidationError,
    canonical_feature_snapshot_bytes,
    create_feature_snapshot_cas_artifact,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadAddress,
    SourcePayloadIntegrityError,
)

BASE = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
OBSERVED = BASE + timedelta(minutes=1, seconds=1)
_RUN_ONCE_NOW_MS = 1_800_000_030_000


class _RunOnceFakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:  # noqa: ARG002
        self.store[key] = value
        return True

    def exists(self, key: str) -> int:
        return int(key in self.store)

    def hgetall(self, key: str) -> dict[str, str]:  # noqa: ARG002
        return {}

    def xrange(
        self,
        key: str,  # noqa: ARG002
        min: str = "-",  # noqa: A002, ARG002
        max: str = "+",  # noqa: A002, ARG002
    ) -> list[object]:
        return []

    def scan_iter(self, match: str | None = None, count: int = 500):  # noqa: ARG002
        if match is None:
            yield from tuple(self.store)
            return
        prefix = match.removesuffix("*")
        for key in tuple(self.store):
            if (match.endswith("*") and key.startswith(prefix)) or key == match:
                yield key


def _run_once_market_payload() -> dict[str, object]:
    return {
        "price": 100.0,
        "ticker_24hr": {
            "lastPrice": "100.0",
            "openPrice": "99.0",
            "highPrice": "101.0",
            "lowPrice": "98.0",
            "prevClosePrice": "99.0",
            "quoteVolume": "1000000",
        },
        "funding": {
            "lastFundingRate": "0.0001",
            "markPrice": "100.0",
            "indexPrice": "100.0",
        },
        "open_interest": {},
    }


def _native_ms(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _v3_us(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _native_snapshot_id(snapshot_without_id: dict[str, object]) -> str:
    """Exact ABI of ``v2_feature_pipeline_native_loop._snapshot_id``."""

    encoded = json.dumps(snapshot_without_id, sort_keys=True).encode()
    return f"v2_fsnap_{hashlib.sha256(encoded).hexdigest()}"


def _canonical_object_sha256(value: dict[str, object]) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _rederive_artifact_identity(binding: dict[str, Any]) -> str:
    identity = {
        "schema_version": CAS_ARTIFACT_IDENTITY_SCHEMA_VERSION,
        "feature_snapshot_id": binding["feature_snapshot_id"],
        "artifact_serialization_sha256": binding["artifact_serialization_sha256"],
        "artifact_serialization_byte_count": binding["artifact_serialization_byte_count"],
        "artifact_serialization_schema_version": (CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION),
        "producer_worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "symbol": binding["symbol"],
        "timeframe": binding["timeframe"],
    }
    identity_sha256 = _canonical_object_sha256(identity)
    binding["artifact_identity_sha256"] = identity_sha256
    record_id = "feature_snapshot_cas_artifact_v1_" + identity_sha256
    binding["artifact_record_id"] = record_id
    return record_id


def _rehash_artifact_binding(binding: dict[str, Any]) -> tuple[str, str]:
    material = {key: value for key, value in binding.items() if key != "artifact_binding_sha256"}
    binding_sha256 = _canonical_object_sha256(material)
    binding["artifact_binding_sha256"] = binding_sha256
    binding_json = json.dumps(
        binding,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return binding_sha256, binding_json


def _persist_rehashed_artifact_binding(
    store: ImmutableSourcePayloadStore,
    binding: dict[str, Any],
) -> tuple[str, str, SourcePayloadAddress]:
    binding_sha256, binding_json = _rehash_artifact_binding(binding)
    binding_bytes = binding_json.encode("ascii")
    binding_cas_sha256 = hashlib.sha256(binding_bytes).hexdigest()
    binding_cas_address = store.put(
        binding_bytes,
        expected_sha256=binding_cas_sha256,
        expected_byte_count=len(binding_bytes),
    )
    return binding_sha256, binding_json, binding_cas_address


def _reidentify(snapshot: dict[str, object]) -> str:
    snapshot.pop("feature_snapshot_id", None)
    snapshot_id = _native_snapshot_id(snapshot)
    snapshot["feature_snapshot_id"] = snapshot_id
    return snapshot_id


def _snapshot(**overrides: object) -> dict[str, object]:
    candle_open = BASE
    candle_close = BASE + timedelta(seconds=59, milliseconds=999)
    source_event = BASE + timedelta(minutes=1)
    ingested = source_event + timedelta(milliseconds=1)
    snapshot: dict[str, object] = {
        "schema_version": NATIVE_FEATURE_SNAPSHOT_SCHEMA_VERSION,
        "worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "features": {"close": 60_000.0, "rsi_14": 52.25},
        "candle_closed_confirmed": True,
        "candle_open_time": _native_ms(candle_open),
        "candle_close_time": _native_ms(candle_close),
        "event_time": _native_ms(source_event),
        "ingested_at": _native_ms(ingested),
        "source_available_at": _native_ms(ingested),
        "feature_cutoff": _native_ms(candle_close),
        "generated_at": _native_ms(ingested + timedelta(milliseconds=1)),
        "source": "binance_wss",
        "is_backfilled": False,
        "source_sequence_id": str(int(source_event.timestamp() * 1_000)),
        "raw_payload_hash": "a" * 64,
        "exact_source_clock_valid": True,
        "exact_source_clock_rejection_reasons": [],
        # The producer must remain held until this bridge creates independent
        # post-CAS evidence.  These null/false fields are not clock aliases.
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
    }
    snapshot.update(overrides)
    _reidentify(snapshot)
    return snapshot


def _snapshot_for_timeframe(timeframe: str) -> dict[str, object]:
    durations = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
    }
    candle_close = BASE + durations[timeframe] - timedelta(milliseconds=1)
    source_event = candle_close + timedelta(milliseconds=1)
    ingested = source_event + timedelta(milliseconds=1)
    generated = ingested + timedelta(milliseconds=1)
    snapshot = _snapshot(
        timeframe=timeframe,
        candle_close_time=_native_ms(candle_close),
        event_time=_native_ms(source_event),
        ingested_at=_native_ms(ingested),
        source_available_at=_native_ms(ingested),
        feature_cutoff=_native_ms(candle_close),
        generated_at=_native_ms(generated),
        source_sequence_id=str(int(source_event.timestamp() * 1_000)),
    )
    return snapshot


def _publish(
    tmp_path: Path,
    snapshot: dict[str, object] | None = None,
    *,
    store: ImmutableSourcePayloadStore | None = None,
) -> tuple[FeatureSnapshotCasArtifact, bytes, ImmutableSourcePayloadStore]:
    bound_snapshot = snapshot or _snapshot()
    payload = canonical_feature_snapshot_bytes(bound_snapshot)
    payload_store = store or ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    result = create_feature_snapshot_cas_artifact(
        source_payload_store=payload_store,
        artifact_snapshot_bytes=payload,
        expected_feature_snapshot_id=str(bound_snapshot["feature_snapshot_id"]),
        expected_symbol=str(bound_snapshot["symbol"]),
        expected_timeframe=str(bound_snapshot["timeframe"]),
    )
    return result, payload, payload_store


def test_native_snapshot_fixture_round_trips_derived_artifact_and_clocks(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    # Proves compatibility with the producer's ID algorithm independently of
    # the bridge helper/validator.
    material = dict(snapshot)
    feature_snapshot_id = str(material.pop("feature_snapshot_id"))
    assert feature_snapshot_id == _native_snapshot_id(material)

    result, payload, store = _publish(tmp_path, snapshot)
    binding = result.artifact_binding
    digest = hashlib.sha256(payload).hexdigest()

    assert binding["schema_version"] == CAS_ARTIFACT_BINDING_SCHEMA_VERSION
    assert binding["evidence_classification"] == (CAS_ARTIFACT_EVIDENCE_CLASSIFICATION)
    assert binding["artifact_retry_semantics"] == CAS_ARTIFACT_RETRY_SEMANTICS
    assert binding["consumer_admission_eligible"] is False
    assert binding["point_in_time_evidence"] is False
    assert binding["trainer_evidence"] is False
    assert binding["ledger_source_evidence"] is False
    assert binding["source_transport_bytes_verified"] is False
    assert result.evidence_classification == CAS_ARTIFACT_EVIDENCE_CLASSIFICATION
    assert result.consumer_admission_eligible is False
    assert result.point_in_time_evidence is False
    assert result.trainer_evidence is False
    assert result.ledger_source_evidence is False
    assert not hasattr(result, "source_read_receipt")
    assert binding["feature_snapshot_id"] == feature_snapshot_id
    assert binding["artifact_serialization_sha256"] == digest
    assert binding["artifact_serialization_byte_count"] == len(payload)
    assert binding["artifact_serialization_schema_version"] == (
        CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION
    )
    assert binding["artifact_serialization_origin"] == (
        "DERIVED_FROM_PARSED_NATIVE_SNAPSHOT_MAPPING_NOT_SOURCE_TRANSPORT_BYTES"
    )
    assert binding["producer_worker_id"] == NATIVE_FEATURE_SNAPSHOT_WORKER_ID
    assert binding["symbol"] == "BTCUSDT"
    assert binding["timeframe"] == "1m"
    assert binding["feature_cutoff"] == "2026-07-18T12:00:59.999000Z"
    assert binding["source_event_time"] == "2026-07-18T12:01:00.000000Z"
    assert "event_time" not in binding
    assert binding["source_ingested_at"] == "2026-07-18T12:01:00.001000Z"
    assert binding["source_available_at"] == "2026-07-18T12:01:00.001000Z"
    assert "cas_postcommit_observed_at" not in binding
    assert "cas_postcommit_observation_scope" not in binding
    assert not hasattr(result, "cas_postcommit_observed_at")
    assert binding["cas_address"]["payload_sha256"] == digest
    assert binding["cas_address"]["payload_byte_count"] == len(payload)
    assert binding["cas_address"]["relative_path"] == (f"sha256/{digest[:2]}/{digest}")
    assert Path(binding["cas_address"]["absolute_path"]) == store.path_for(digest)
    assert store.get(digest, expected_byte_count=len(payload)) == payload
    binding_bytes = result.artifact_binding_json.encode("ascii")
    binding_digest = hashlib.sha256(binding_bytes).hexdigest()
    assert result.artifact_binding_cas_address.payload_sha256 == binding_digest
    assert result.artifact_binding_cas_address.payload_byte_count == len(binding_bytes)
    assert (
        store.get(
            binding_digest,
            expected_byte_count=len(binding_bytes),
        )
        == binding_bytes
    )
    assert not any("source_read_receipt" in key for key in binding)


def test_actual_run_once_output_uses_trusted_key_context_and_stays_non_consumable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    producer = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = _RunOnceFakeRedis()
    latest_key = "v2:features:latest:BTCUSDT:1m"
    index_key = "v2:features:snapshots"
    close_ms = producer._expected_latest_finalized_close_ms(  # noqa: SLF001
        decision_ms=_RUN_ONCE_NOW_MS,
        timeframe="1m",
    )
    open_ms = close_ms - 60_000 + 1
    event_ms = close_ms + 100
    ingested_ms = event_ms + 100
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_run_once_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        [
            {
                "candle_open_time": open_ms,
                "candle_close_time": close_ms,
                "event_time": event_ms,
                "ingested_at": ingested_ms,
                "available_at": ingested_ms,
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "timeframe": "1m",
                "source": "binance_wss",
                "is_backfilled": False,
                "is_closed": True,
                "feature_eligible": True,
                "source_sequence_id": str(event_ms),
                "raw_payload_hash": "b" * 64,
                "open": "99.0",
                "high": "101.0",
                "low": "98.0",
                "close": "100.0",
                "volume": "1000",
            }
        ]
    )
    monkeypatch.setattr(producer, "_connect_redis", lambda: fake)
    monkeypatch.setattr(producer.time, "time", lambda: _RUN_ONCE_NOW_MS / 1000.0)
    monkeypatch.setattr(
        producer,
        "_utc_iso",
        lambda: producer._ms_to_utc_iso(_RUN_ONCE_NOW_MS),  # noqa: SLF001
    )

    heartbeat = producer.run_once(
        ("BTCUSDT",),
        "1m",
        write_trainer_snapshot=False,
    )

    assert heartbeat["snapshots_built"] == 1
    assert latest_key in heartbeat["v2_features_keys_written"]
    assert index_key in heartbeat["v2_features_keys_written"]
    raw_redis_bytes = fake.store[latest_key].encode("utf-8")
    snapshot = json.loads(raw_redis_bytes)
    artifact_bytes = canonical_feature_snapshot_bytes(snapshot)
    # The artifact serialization is intentionally new evidence, not a claim
    # that the producer's Redis transport bytes were captured exactly.
    assert artifact_bytes != raw_redis_bytes

    trusted_prefix, expected_symbol, expected_timeframe = latest_key.rsplit(":", 2)
    assert trusted_prefix == "v2:features:latest"
    trusted_snapshot_ids = json.loads(fake.store[index_key])
    assert len(trusted_snapshot_ids) == 1
    expected_snapshot_id = trusted_snapshot_ids[0]
    assert isinstance(expected_snapshot_id, str)
    result = create_feature_snapshot_cas_artifact(
        source_payload_store=ImmutableSourcePayloadStore(tmp_path / "artifacts"),
        artifact_snapshot_bytes=artifact_bytes,
        expected_feature_snapshot_id=expected_snapshot_id,
        expected_symbol=expected_symbol,
        expected_timeframe=expected_timeframe,
    )

    binding = result.artifact_binding
    assert binding["feature_snapshot_id"] == expected_snapshot_id
    assert binding["symbol"] == expected_symbol
    assert binding["timeframe"] == expected_timeframe
    assert binding["source_event_time"] != binding["feature_cutoff"]
    assert "event_time" not in binding
    assert binding["consumer_admission_eligible"] is False
    assert binding["point_in_time_evidence"] is False
    assert binding["trainer_evidence"] is False
    assert binding["ledger_source_evidence"] is False
    assert binding["source_transport_bytes_verified"] is False


def test_binding_is_persisted_only_after_artifact_put_and_exact_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    payload = canonical_feature_snapshot_bytes(snapshot)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    original_put = ImmutableSourcePayloadStore.put
    original_get = ImmutableSourcePayloadStore.get
    artifact_digest = hashlib.sha256(payload).hexdigest()
    state = {
        "artifact_put": False,
        "artifact_get": False,
        "binding_put": False,
        "binding_get": False,
    }

    def observed_put(self: ImmutableSourcePayloadStore, exact: bytes, **kwargs: object):
        result = original_put(self, exact, **kwargs)
        if exact == payload:
            state["artifact_put"] = True
        else:
            assert state["artifact_get"] is True
            state["binding_put"] = True
        return result

    def observed_get(self: ImmutableSourcePayloadStore, digest: str, **kwargs: object):
        result = original_get(self, digest, **kwargs)
        if digest == artifact_digest:
            assert state["artifact_put"] is True
            assert result == payload
            state["artifact_get"] = True
        else:
            assert state["binding_put"] is True
            state["binding_get"] = True
        return result

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", observed_put)
    monkeypatch.setattr(ImmutableSourcePayloadStore, "get", observed_get)

    create_feature_snapshot_cas_artifact(
        source_payload_store=store,
        artifact_snapshot_bytes=payload,
        expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )

    assert state == {
        "artifact_put": True,
        "artifact_get": True,
        "binding_put": True,
        "binding_get": True,
    }


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("schema_version", "v2_native_feature_snapshot_v1", "schema_mismatch"),
        ("worker_id", "legacy_feature_worker", "worker_mismatch"),
    ],
)
def test_schema_downgrade_and_wrong_worker_fail_before_cas_write(
    tmp_path: Path,
    field: str,
    value: str,
    reason: str,
) -> None:
    snapshot = _snapshot()
    snapshot[field] = value
    _reidentify(snapshot)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    with pytest.raises(FeatureSnapshotPublicationValidationError, match=reason):
        create_feature_snapshot_cas_artifact(
            source_payload_store=store,
            artifact_snapshot_bytes=canonical_feature_snapshot_bytes(snapshot),
            expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
        )

    assert list((store.root_path / "sha256").iterdir()) == []


@pytest.mark.parametrize(
    ("expected_id", "expected_symbol", "expected_timeframe", "reason"),
    [
        ("v2_fsnap_" + "f" * 64, "BTCUSDT", "1m", "expected_id_mismatch"),
        (None, "ETHUSDT", "1m", "expected_symbol_mismatch"),
        (None, "BTCUSDT", "5m", "expected_timeframe_mismatch"),
    ],
)
def test_cross_context_id_symbol_and_timeframe_are_rejected(
    tmp_path: Path,
    expected_id: str | None,
    expected_symbol: str,
    expected_timeframe: str,
    reason: str,
) -> None:
    snapshot = _snapshot()
    with pytest.raises(FeatureSnapshotPublicationValidationError, match=reason):
        create_feature_snapshot_cas_artifact(
            source_payload_store=ImmutableSourcePayloadStore(tmp_path / "payloads"),
            artifact_snapshot_bytes=canonical_feature_snapshot_bytes(snapshot),
            expected_feature_snapshot_id=(expected_id or str(snapshot["feature_snapshot_id"])),
            expected_symbol=expected_symbol,
            expected_timeframe=expected_timeframe,
        )


@pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "4h"])
def test_exact_native_timeframe_allowlist_is_accepted(
    tmp_path: Path,
    timeframe: str,
) -> None:
    snapshot = _snapshot_for_timeframe(timeframe)
    result, _payload, _store = _publish(tmp_path, snapshot)
    assert result.artifact_binding["timeframe"] == timeframe


@pytest.mark.parametrize("timeframe", ["2m", "30m", "2h", "1d", "1w"])
def test_non_native_timeframes_fail_before_cas_write(
    tmp_path: Path,
    timeframe: str,
) -> None:
    snapshot = _snapshot(timeframe=timeframe)
    store = ImmutableSourcePayloadStore(tmp_path / "artifacts")

    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="feature_snapshot_timeframe_invalid",
    ):
        create_feature_snapshot_cas_artifact(
            source_payload_store=store,
            artifact_snapshot_bytes=canonical_feature_snapshot_bytes(snapshot),
            expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
            expected_symbol="BTCUSDT",
            expected_timeframe=timeframe,
        )

    assert list((store.root_path / "sha256").iterdir()) == []


def test_mutated_content_cannot_reuse_native_snapshot_id(tmp_path: Path) -> None:
    snapshot = _snapshot()
    original_id = str(snapshot["feature_snapshot_id"])
    snapshot["features"] = {"close": 1.0, "rsi_14": 99.0}

    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="content_id_mismatch",
    ):
        create_feature_snapshot_cas_artifact(
            source_payload_store=ImmutableSourcePayloadStore(tmp_path / "payloads"),
            artifact_snapshot_bytes=canonical_feature_snapshot_bytes(snapshot),
            expected_feature_snapshot_id=original_id,
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
        )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b"\xffnot-utf8",
    ],
)
def test_duplicate_nonfinite_and_non_utf8_json_fail_closed(
    tmp_path: Path,
    payload: bytes,
) -> None:
    with pytest.raises(FeatureSnapshotPublicationValidationError):
        create_feature_snapshot_cas_artifact(
            source_payload_store=ImmutableSourcePayloadStore(tmp_path / "payloads"),
            artifact_snapshot_bytes=payload,
            expected_feature_snapshot_id="v2_fsnap_" + "a" * 64,
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
        )


def test_semantically_equal_noncanonical_json_bytes_are_rejected(tmp_path: Path) -> None:
    snapshot = _snapshot()
    noncanonical = json.dumps(snapshot, sort_keys=True).encode()
    assert noncanonical != canonical_feature_snapshot_bytes(snapshot)

    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="bytes_not_canonical_json",
    ):
        create_feature_snapshot_cas_artifact(
            source_payload_store=ImmutableSourcePayloadStore(tmp_path / "payloads"),
            artifact_snapshot_bytes=noncanonical,
            expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
        )


def test_estimate_alias_cannot_replace_missing_exact_event_clock(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.pop("event_time")
    snapshot["source_event_time_est"] = _native_ms(BASE + timedelta(minutes=1))
    _reidentify(snapshot)

    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="event_time_invalid",
    ):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize(
    "bad_clock",
    [
        "2026-07-18T12:01:00.000000Z",
        "2026-07-18T08:01:00.000-04:00",
        "2026-07-18T12:01:00Z",
        "2026-07-18 12:01:00.000",
    ],
)
def test_noncanonical_native_clock_text_is_rejected(
    tmp_path: Path,
    bad_clock: str,
) -> None:
    snapshot = _snapshot(event_time=bad_clock)
    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="event_time_(not_canonical_utc|timezone_required)",
    ):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize(
    "field",
    [
        "candle_open_time",
        "candle_close_time",
        "event_time",
        "ingested_at",
        "source_available_at",
        "feature_cutoff",
        "generated_at",
    ],
)
def test_all_native_epoch_clocks_must_be_positive(
    tmp_path: Path,
    field: str,
) -> None:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    snapshot = _snapshot(**{field: _native_ms(epoch)})
    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="native_epoch_clock_not_positive",
    ):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize("sequence", ["0", "-1", "00", "not-a-sequence", 0, None])
def test_source_sequence_must_be_a_positive_canonical_epoch_ms_string(
    tmp_path: Path,
    sequence: object,
) -> None:
    snapshot = _snapshot(source_sequence_id=sequence)
    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="source_sequence_event_mismatch",
    ):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"ingested_at": _native_ms(BASE + timedelta(seconds=59, milliseconds=999))},
            "source_clock_order_invalid",
        ),
        (
            {"feature_cutoff": _native_ms(BASE + timedelta(seconds=59, milliseconds=998))},
            "feature_cutoff_not_candle_close",
        ),
        (
            {"source_available_at": _native_ms(BASE + timedelta(minutes=1, milliseconds=2))},
            "source_available_not_canonical_max",
        ),
        ({"source_sequence_id": "0"}, "source_sequence_event_mismatch"),
    ],
)
def test_invalid_exact_clock_order_cutoff_availability_and_sequence_fail_closed(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    snapshot = _snapshot(**changes)
    with pytest.raises(FeatureSnapshotPublicationValidationError, match=reason):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"available_at": _native_ms(OBSERVED)}, "available_at_self_attested"),
        (
            {"feature_available_at": _native_ms(OBSERVED)},
            "feature_available_at_self_attested",
        ),
        ({"exact_feature_availability_valid": True}, "availability_self_attested"),
        ({"trainer_consumable": True}, "trainer_consumable_self_attested"),
        (
            {"postcommit_observed_at": _native_ms(OBSERVED)},
            "reserved_artifact_fields",
        ),
    ],
)
def test_snapshot_cannot_self_attest_publication_or_consumer_availability(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    snapshot = _snapshot(**changes)
    with pytest.raises(FeatureSnapshotPublicationValidationError, match=reason):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize(
    "field",
    [
        "consumer_admission_eligible",
        "point_in_time_evidence",
        "trainer_evidence",
        "ledger_source_evidence",
        "source_transport_bytes_verified",
        "cas_put_completed",
        "cas_exact_readback_verified",
        "cas_exact_readback_sha256",
        "cas_exact_readback_byte_count",
        "cas_postcommit_observed_at",
        "cas_postcommit_observation_scope",
        "evidence_classification",
        "artifact_retry_semantics",
        "artifact_binding_sha256",
        "artifact_identity_sha256",
        "artifact_record_id",
        "artifact_binding_json",
        "artifact_binding_cas_address",
        "artifact_serialization_sha256",
        "artifact_serialization_byte_count",
        "cas_address",
        "producer_worker_id",
        "native_snapshot_schema_version",
        "source_event_time",
        "source_ingested_at",
        "source_read_receipt",
        "source_read_receipts",
        "publication_binding_v99",
        "artifact_future_attestation",
        "binding_cas_future_address",
        "cas_future_verification",
        "consumer_admission_future",
        "ledger_future_evidence",
        "point_in_time_future_evidence",
        "source_transport_future_verified",
        "trainer_admission_future",
        "trainer_receipt_future",
        "publication_future_attestation",
        "publication_admission_eligible",
        "evidence_future_classification",
        "evidence_classification_v2",
        "admission_eligible_v2",
        "retry_semantics_v2",
        "postcommit_observed_at_v2",
        "publication_record_id_v2",
        "source_payload_store_v2",
        "binding_address_v2",
        "identity_sha256_v2",
        "trainer_evidence_v2",
    ],
)
def test_native_snapshot_rejects_reserved_artifact_attestation_fields(
    tmp_path: Path,
    field: str,
) -> None:
    snapshot = _snapshot(**{field: "ATTACKER_SELF_ATTESTATION"})
    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="reserved_artifact_fields",
    ):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"required_model_feature_pit_coverage_valid": True},
            "required_feature_pit_hold_not_false",
        ),
        (
            {"required_model_feature_pit_coverage_valid": 0},
            "required_feature_pit_hold_not_false",
        ),
        (
            {
                "required_model_feature_pit_rejection_reasons": [
                    "REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED",
                    "ATTACKER_EXTRA_REASON",
                ]
            },
            "required_feature_pit_hold_reason_invalid",
        ),
        (
            {"ohlcv_history_payload_receipts_valid": True},
            "ohlcv_receipt_hold_not_false",
        ),
        (
            {"ohlcv_history_payload_receipts_valid": 0},
            "ohlcv_receipt_hold_not_false",
        ),
        (
            {"ohlcv_history_payload_receipt_rejection_reasons": []},
            "ohlcv_receipt_hold_reason_invalid",
        ),
        (
            {
                "exact_feature_availability_rejection_reasons": [
                    "FEATURE_PUBLICATION_RECEIPT_REQUIRED",
                    "ATTACKER_EXTRA_REASON",
                ]
            },
            "publication_receipt_hold_missing",
        ),
    ],
)
def test_current_producer_pit_holds_must_remain_literal_and_exact(
    tmp_path: Path,
    changes: dict[str, object],
    reason: str,
) -> None:
    snapshot = _snapshot(**changes)
    with pytest.raises(FeatureSnapshotPublicationValidationError, match=reason):
        _publish(tmp_path, snapshot)


@pytest.mark.parametrize("kind", ["truncated", "substituted"])
def test_cas_readback_truncation_and_equal_length_substitution_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    snapshot = _snapshot()
    payload = canonical_feature_snapshot_bytes(snapshot)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")

    def corrupt_get(
        _self: ImmutableSourcePayloadStore,
        _digest: str,
        **_kwargs: object,
    ) -> bytes:
        if kind == "truncated":
            return payload[:-1]
        return b"x" * len(payload)

    monkeypatch.setattr(ImmutableSourcePayloadStore, "get", corrupt_get)
    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match=("truncated" if kind == "truncated" else "sha256_mismatch"),
    ):
        create_feature_snapshot_cas_artifact(
            source_payload_store=store,
            artifact_snapshot_bytes=payload,
            expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
        )


def test_forged_cas_address_path_is_rejected_before_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    payload = canonical_feature_snapshot_bytes(snapshot)
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    original_put = ImmutableSourcePayloadStore.put
    get_called = False

    def forged_put(self: ImmutableSourcePayloadStore, exact: bytes, **kwargs: object):
        real = original_put(self, exact, **kwargs)
        return replace(real, relative_path="sha256/00/attacker-substitution")

    def forbidden_get(*_args: object, **_kwargs: object) -> bytes:
        nonlocal get_called
        get_called = True
        return payload

    monkeypatch.setattr(ImmutableSourcePayloadStore, "put", forged_put)
    monkeypatch.setattr(ImmutableSourcePayloadStore, "get", forbidden_get)
    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="relative_path_mismatch",
    ):
        create_feature_snapshot_cas_artifact(
            source_payload_store=store,
            artifact_snapshot_bytes=payload,
            expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
        )
    assert get_called is False


def test_wrong_cas_object_mode_propagates_fail_closed_on_republication(
    tmp_path: Path,
) -> None:
    first, payload, store = _publish(tmp_path)
    expected_feature_snapshot_id = first.artifact_binding["feature_snapshot_id"]
    path = store.path_for(first.cas_address.payload_sha256)
    os.chmod(path, 0o600)

    with pytest.raises(SourcePayloadIntegrityError, match="immutable_mode"):
        create_feature_snapshot_cas_artifact(
            source_payload_store=store,
            artifact_snapshot_bytes=payload,
            expected_feature_snapshot_id=expected_feature_snapshot_id,
            expected_symbol="BTCUSDT",
            expected_timeframe="1m",
        )


def test_equal_byte_retry_is_content_idempotent_without_observation_claim(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    store = ImmutableSourcePayloadStore(tmp_path / "source-payloads")
    first, _payload, _store = _publish(
        tmp_path,
        snapshot,
        store=store,
    )
    second, _payload, _store = _publish(
        tmp_path,
        snapshot,
        store=store,
    )

    assert first.artifact_record_id == second.artifact_record_id
    assert first.artifact_binding_sha256 == second.artifact_binding_sha256
    assert first.artifact_binding_cas_address == second.artifact_binding_cas_address
    assert first.cas_address == second.cas_address
    assert "cas_postcommit_observed_at" not in first.artifact_binding
    assert "cas_postcommit_observation_scope" not in second.artifact_binding
    assert first.artifact_binding["artifact_retry_semantics"] == (CAS_ARTIFACT_RETRY_SEMANTICS)
    assert second.consumer_admission_eligible is False
    assert second.point_in_time_evidence is False
    assert second.trainer_evidence is False
    assert second.ledger_source_evidence is False


def test_equal_artifact_bytes_across_cas_roots_have_root_bound_binding_address(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    payload = canonical_feature_snapshot_bytes(snapshot)
    first_store = ImmutableSourcePayloadStore(tmp_path / "first-cas")
    second_store = ImmutableSourcePayloadStore(tmp_path / "second-cas")

    first = create_feature_snapshot_cas_artifact(
        source_payload_store=first_store,
        artifact_snapshot_bytes=payload,
        expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
        expected_symbol=str(snapshot["symbol"]),
        expected_timeframe=str(snapshot["timeframe"]),
    )
    second = create_feature_snapshot_cas_artifact(
        source_payload_store=second_store,
        artifact_snapshot_bytes=payload,
        expected_feature_snapshot_id=str(snapshot["feature_snapshot_id"]),
        expected_symbol=str(snapshot["symbol"]),
        expected_timeframe=str(snapshot["timeframe"]),
    )

    assert first.artifact_snapshot_bytes == second.artifact_snapshot_bytes
    assert first.artifact_record_id == second.artifact_record_id
    assert first.cas_address == second.cas_address
    assert first.artifact_binding_cas_address != second.artifact_binding_cas_address
    assert first.artifact_binding["artifact_retry_semantics"] == (
        "STABLE_CONTENT_ID_AND_ARTIFACT_ADDRESS_FOR_EQUAL_DERIVED_BYTES;"
        "STABLE_BINDING_ADDRESS_WITHIN_SAME_CANONICAL_CAS_ROOT"
    )
    assert (
        first.artifact_binding["cas_address"]["absolute_path"]
        != (second.artifact_binding["cas_address"]["absolute_path"])
    )


def test_result_is_frozen_and_mapping_access_returns_independent_copies(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    with pytest.raises(FrozenInstanceError):
        result.artifact_record_id = "feature_snapshot_cas_artifact_v1_" + "0" * 64  # type: ignore[misc]

    first_binding = result.artifact_binding
    first_binding["symbol"] = "ETHUSDT"
    assert result.artifact_binding["symbol"] == "BTCUSDT"

    tampered_binding = result.artifact_binding
    tampered_binding["symbol"] = "ETHUSDT"
    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="artifact_binding_cas_address_mismatch",
    ):
        _ = replace(
            result,
            artifact_binding_json=json.dumps(
                tampered_binding,
                sort_keys=True,
                separators=(",", ":"),
            ),
        ).artifact_binding

    tamper_attempts = (
        lambda: replace(result, consumer_admission_eligible=True),
        lambda: replace(result, point_in_time_evidence=True),
        lambda: replace(result, trainer_evidence=True),
        lambda: replace(result, ledger_source_evidence=True),
    )
    for tamper in tamper_attempts:
        with pytest.raises(
            FeatureSnapshotPublicationIntegrityError,
            match="non_consumable_invariant_violated",
        ):
            tamper()

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="record_identity_mismatch",
    ):
        replace(
            result,
            artifact_record_id="feature_snapshot_cas_artifact_v1_" + "0" * 64,
        )
    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="artifact_binding_identity_mismatch",
    ):
        replace(result, artifact_binding_sha256="0" * 64)
    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="cas_content_crosslink_mismatch",
    ):
        replace(
            result,
            cas_address=replace(result.cas_address, payload_sha256="f" * 64),
        )


def test_coordinated_rehash_cannot_detach_identity_from_cas_content(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    forged = result.artifact_binding
    forged["symbol"] = "ETHUSDT"
    forged["artifact_serialization_sha256"] = "f" * 64
    forged_identity = {
        "schema_version": CAS_ARTIFACT_IDENTITY_SCHEMA_VERSION,
        "feature_snapshot_id": forged["feature_snapshot_id"],
        "artifact_serialization_sha256": forged["artifact_serialization_sha256"],
        "artifact_serialization_byte_count": forged["artifact_serialization_byte_count"],
        "artifact_serialization_schema_version": (CAS_ARTIFACT_SERIALIZATION_SCHEMA_VERSION),
        "producer_worker_id": NATIVE_FEATURE_SNAPSHOT_WORKER_ID,
        "symbol": forged["symbol"],
        "timeframe": forged["timeframe"],
    }
    forged_identity_sha256 = _canonical_object_sha256(forged_identity)
    forged_record_id = "feature_snapshot_cas_artifact_v1_" + forged_identity_sha256
    forged["artifact_identity_sha256"] = forged_identity_sha256
    forged["artifact_record_id"] = forged_record_id
    (
        forged_binding_sha256,
        forged_json,
        forged_binding_cas_address,
    ) = _persist_rehashed_artifact_binding(
        store,
        forged,
    )

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="stored_bytes_identity_mismatch",
    ):
        replace(
            result,
            artifact_record_id=forged_record_id,
            artifact_binding_sha256=forged_binding_sha256,
            artifact_binding_json=forged_json,
            artifact_binding_cas_address=forged_binding_cas_address,
        )


def test_alternate_absolute_path_prefix_is_rejected_after_coherent_rehash(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    forged = result.artifact_binding
    forged_address = forged["cas_address"]
    forged_address["absolute_path"] = (
        "/attacker-controlled-cas-root/" + forged_address["relative_path"]
    )
    (
        forged_binding_sha256,
        forged_json,
        forged_binding_cas_address,
    ) = _persist_rehashed_artifact_binding(store, forged)

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="cas_absolute_path_mismatch",
    ):
        replace(
            result,
            artifact_binding_sha256=forged_binding_sha256,
            artifact_binding_json=forged_json,
            artifact_binding_cas_address=forged_binding_cas_address,
        )


def test_coherent_source_clock_sequence_and_raw_hash_mutation_rejects_unchanged_bytes(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    forged = result.artifact_binding
    forged_event = BASE + timedelta(minutes=1, milliseconds=10)
    forged_ingested = forged_event + timedelta(milliseconds=1)
    forged["source_event_time"] = _v3_us(forged_event)
    forged["source_ingested_at"] = _v3_us(forged_ingested)
    forged["source_available_at"] = _v3_us(forged_ingested)
    forged["generated_at"] = _v3_us(forged_ingested + timedelta(milliseconds=1))
    forged["source_sequence_id"] = str(int(forged_event.timestamp() * 1_000))
    forged["raw_payload_hash"] = "f" * 64
    (
        forged_binding_sha256,
        forged_json,
        forged_binding_cas_address,
    ) = _persist_rehashed_artifact_binding(store, forged)

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="stored_bytes_(identity|source_lineage)_mismatch",
    ):
        replace(
            result,
            artifact_binding_sha256=forged_binding_sha256,
            artifact_binding_json=forged_json,
            artifact_binding_cas_address=forged_binding_cas_address,
        )


def test_symbol_and_snapshot_identity_mutation_rejects_unchanged_bytes(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    forged = result.artifact_binding
    forged["symbol"] = "ETHUSDT"
    forged["feature_snapshot_id"] = "v2_fsnap_" + "f" * 64
    forged_record_id = _rederive_artifact_identity(forged)
    (
        forged_binding_sha256,
        forged_json,
        forged_binding_cas_address,
    ) = _persist_rehashed_artifact_binding(store, forged)

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="stored_bytes_identity_mismatch",
    ):
        replace(
            result,
            artifact_record_id=forged_record_id,
            artifact_binding_sha256=forged_binding_sha256,
            artifact_binding_json=forged_json,
            artifact_binding_cas_address=forged_binding_cas_address,
        )


def test_fabricated_nonexistent_cas_object_fails_after_all_hashes_are_recomputed(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    fabricated_snapshot = json.loads(result.artifact_snapshot_bytes)
    fabricated_snapshot["features"]["close"] = 60_001.0
    fabricated_snapshot_id = _reidentify(fabricated_snapshot)
    fabricated_bytes = canonical_feature_snapshot_bytes(fabricated_snapshot)
    fabricated_sha256 = hashlib.sha256(fabricated_bytes).hexdigest()
    fabricated_byte_count = len(fabricated_bytes)
    fabricated_relative_path = f"sha256/{fabricated_sha256[:2]}/{fabricated_sha256}"
    fabricated_absolute_path = store.path_for(fabricated_sha256)
    assert not fabricated_absolute_path.exists()

    forged = result.artifact_binding
    forged["feature_snapshot_id"] = fabricated_snapshot_id
    forged["artifact_serialization_sha256"] = fabricated_sha256
    forged["artifact_serialization_byte_count"] = fabricated_byte_count
    forged["cas_exact_readback_sha256"] = fabricated_sha256
    forged["cas_exact_readback_byte_count"] = fabricated_byte_count
    forged_address = forged["cas_address"]
    forged_address["payload_sha256"] = fabricated_sha256
    forged_address["payload_byte_count"] = fabricated_byte_count
    forged_address["relative_path"] = fabricated_relative_path
    forged_address["absolute_path"] = fabricated_absolute_path.as_posix()
    forged_record_id = _rederive_artifact_identity(forged)
    forged_binding_sha256, forged_json = _rehash_artifact_binding(forged)
    fabricated_address = replace(
        result.cas_address,
        payload_sha256=fabricated_sha256,
        payload_byte_count=fabricated_byte_count,
        relative_path=fabricated_relative_path,
    )

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="cas_readback_verification_failed",
    ):
        replace(
            result,
            artifact_record_id=forged_record_id,
            artifact_binding_sha256=forged_binding_sha256,
            artifact_binding_json=forged_json,
            cas_address=fabricated_address,
            artifact_snapshot_bytes=fabricated_bytes,
        )


def test_persisted_coordinated_future_clock_rewrite_has_no_valid_surface(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    forged = result.artifact_binding
    forged_observed_at = "2036-07-15T12:01:01.000000Z"
    forged["cas_postcommit_observed_at"] = forged_observed_at
    (
        forged_binding_sha256,
        forged_json,
        forged_binding_cas_address,
    ) = _persist_rehashed_artifact_binding(
        store,
        forged,
    )
    assert store.get(
        forged_binding_cas_address.payload_sha256,
        expected_byte_count=forged_binding_cas_address.payload_byte_count,
    ) == forged_json.encode("ascii")
    assert forged["artifact_record_id"] == result.artifact_record_id

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="artifact_binding_key_contract_mismatch",
    ):
        replace(
            result,
            artifact_binding_sha256=forged_binding_sha256,
            artifact_binding_json=forged_json,
            artifact_binding_cas_address=forged_binding_cas_address,
        )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        replace(
            result,
            artifact_binding_sha256=forged_binding_sha256,
            artifact_binding_json=forged_json,
            artifact_binding_cas_address=forged_binding_cas_address,
            cas_postcommit_observed_at=forged_observed_at,
        )


def test_binding_json_bytes_and_typed_cas_address_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    result, _payload, _store = _publish(tmp_path)

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="artifact_binding_cas_address_mismatch",
    ):
        replace(
            result,
            artifact_binding_json=result.artifact_binding_json + " ",
        )
    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="artifact_binding_cas_address_mismatch",
    ):
        replace(
            result,
            artifact_binding_cas_address=replace(
                result.artifact_binding_cas_address,
                payload_sha256="f" * 64,
            ),
        )


def test_binding_cas_object_is_fresh_read_and_mode_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    result, _payload, store = _publish(tmp_path)
    binding_path = store.path_for(result.artifact_binding_cas_address.payload_sha256)
    os.chmod(binding_path, 0o600)

    with pytest.raises(
        FeatureSnapshotPublicationIntegrityError,
        match="artifact_binding_cas_readback_verification_failed",
    ):
        _ = result.artifact_binding


def test_public_abi_has_no_unverifiable_postcommit_clock_or_timestamp() -> None:
    signature = inspect.signature(create_feature_snapshot_cas_artifact)

    assert "postcommit_clock" not in signature.parameters
    assert "cas_postcommit_observed_at" not in FeatureSnapshotCasArtifact.__dataclass_fields__
    assert "cas_postcommit_observation_scope" not in FeatureSnapshotCasArtifact.__dataclass_fields__


def test_canonical_serializer_rejects_mapping_subclass_and_nonfinite_value() -> None:
    class AttackerDict(dict[str, object]):
        pass

    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="plain_dict_required",
    ):
        canonical_feature_snapshot_bytes(AttackerDict(_snapshot()))
    bad = _snapshot()
    bad["features"] = {"close": float("nan")}
    with pytest.raises(
        FeatureSnapshotPublicationValidationError,
        match="strict_json_invalid",
    ):
        canonical_feature_snapshot_bytes(bad)
