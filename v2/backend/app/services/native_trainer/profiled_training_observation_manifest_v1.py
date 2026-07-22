"""Authenticated fixed-observation inventory for profiled trainer examples.

The profiled ledger loader is intentionally a factory boundary: authenticating
one page reproduces the complete durable-ledger prefix twice.  Repeating that
work at trainer cadence would be O(total ledger) for every page.  This module
performs that expensive verification once, joins each authenticated 39-column
sample to finalized canonical 5m labels, and seals the resulting inventory in
an immutable, content-addressed SQLite manifest.

Runtime reopen is bounded.  It authenticates one metadata row and a keyset page
of per-entry HMACs, then directly reopens only the selected durable ledger
records through their append/postcommit evidence.  Finalized-label facts were
verified and hash-bound at the immutable observation clock; they are not
re-read from a later archive head during normal reopen.

The caller must pin the exact manifest identity and retrospective observation
cutoff.  That prevents accidental path rollback, but it is not a durable
monotonic "latest manifest" head; such an external head remains mandatory
before any optimizer can consume successive manifests.

The adapter returns outcome-supervised ``TrainingExample`` objects only.  It is
not wired to the resident trainer and grants no optimizer, checkpoint,
prediction, paper, live, order, or execution authority.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import math
import os
import re
import sqlite3
import stat
import struct
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    Canonical5mArchiveError,
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    canonical_json as canonical_label_json,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (
    label_archive_fixed_observation_high_water,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
    LOGICAL_ORDERED_FEATURE_NAMES,
    PHYSICAL_MODEL_FEATURE_COUNT,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    MAX_PROFILED_TRAINING_SCAN_ROWS,
    PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES,
    PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
    ProfiledTrainingLedgerLoaderV1Error,
    ProfiledTrainingLedgerSampleV1,
    load_profiled_training_ledger_fixed_observation_v1,
    reopen_profiled_training_ledger_sample_v1,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    target_action_from_net_edges,
    target_action_index,
)

PROFILED_OBSERVATION_MANIFEST_V1_SCHEMA_VERSION: Final = (
    "profiled_training_fixed_observation_manifest_v1"
)
PROFILED_OBSERVATION_ENTRY_V1_SCHEMA_VERSION: Final = "profiled_training_fixed_observation_entry_v1"
PROFILED_OBSERVATION_CONTEXT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_fixed_observation_context_v1"
)
PROFILED_OBSERVATION_LABEL_BINDING_V1_SCHEMA_VERSION: Final = (
    "profiled_training_finalized_label_binding_v1"
)
PROFILED_OBSERVATION_TENSOR_BINDING_V1_SCHEMA_VERSION: Final = (
    "profiled_training_example_tensor_binding_v1"
)
PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION: Final = (
    "profiled_training_example_adapter_postcommit_availability_v1"
)
PROFILED_OBSERVATION_AUTH_ALGORITHM: Final = "HMAC-SHA256"
PROFILED_OBSERVATION_AUTH_DOMAIN: Final = "v2/native-trainer/profiled-fixed-observation-manifest/v1"
PROFILED_OBSERVATION_AUTH_SEPARATOR: Final = (
    PROFILED_OBSERVATION_AUTH_DOMAIN.encode("ascii") + b"\0"
)
PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS: Final = hashlib.sha256(
    b"profiled_training_fixed_observation_entry_chain_v1:GENESIS"
).hexdigest()
PROFILED_OBSERVATION_LABEL_STATUS_ADMITTED: Final = "ADMITTED_FINALIZED_LABEL"
PROFILED_OBSERVATION_LABEL_STATUS_UNAVAILABLE: Final = "LABEL_NOT_AVAILABLE_AT_OBSERVATION"
PROFILED_OBSERVATION_RUNTIME_STATUS: Final = (
    "UNWIRED_BOUNDED_REOPEN_EXTERNAL_MONOTONIC_HEAD_REQUIRED_" "NO_OPTIMIZER_OR_SERVING_AUTHORITY"
)
PROFILED_OBSERVATION_ORDERED_DIGEST_SCHEMA_VERSION: Final = (
    "profiled_training_ordered_canonical_stream_digest_v1"
)
PROFILED_OBSERVATION_ORDERED_DIGEST_ALGORITHM: Final = (
    "SHA256_DOMAIN_NUL_UINT64_BE_LENGTH_CANONICAL_JSON_SEQUENCE_V1"
)
PROFILED_OBSERVATION_ENTRY_IDENTITY_DIGEST_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation/ordered-entry-identities/v1"
)
PROFILED_OBSERVATION_EXCLUSION_DIGEST_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation/ordered-ledger-exclusions/v1"
)
PROFILED_OBSERVATION_PAGE_ENTRY_DIGEST_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation/ordered-authenticated-page-entries/v1"
)

# Serialization/cryptographic resource limits, never market-selection gates.
MIN_PROFILED_OBSERVATION_HMAC_KEY_BYTES: Final = 32
MAX_PROFILED_OBSERVATION_PAGE_ROWS: Final = 4_096
MAX_PROFILED_OBSERVATION_VERIFY_STREAM_PAGE_ROWS: Final = 128
MAX_PROFILED_OBSERVATION_ENTRY_BYTES: Final = 512 * 1024
MAX_PROFILED_OBSERVATION_METADATA_BYTES: Final = 4 * 1024 * 1024

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_AUTH_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$", re.ASCII)
_MANIFEST_FILENAME_RE = re.compile(
    r"^profiled_training_observation_([0-9a-f]{64})\.sqlite3$",
    re.ASCII,
)
_MANIFEST_TEMP_FILENAME_RE = re.compile(
    r"^\.profiled_training_observation\.[1-9][0-9]{0,19}\."
    r"[0-9a-f]{32}\.tmp(?:-(?:journal|wal|shm))?$",
    re.ASCII,
)
_ENTRY_CHAIN_DOMAIN = b"profiled_training_fixed_observation_entry_chain_v1\0"
_FLOAT64_LABEL_DOMAIN = b"profiled_training_after_cost_label_float64_v1\0"

_DDL_STATEMENTS: Final = (
    """
    CREATE TABLE observation_manifest_metadata (
        singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
        manifest_id TEXT NOT NULL UNIQUE,
        metadata_json TEXT NOT NULL,
        metadata_sha256 TEXT NOT NULL,
        auth_tag TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE observation_manifest_entries (
        ordinal INTEGER PRIMARY KEY CHECK(ordinal > 0),
        ledger_sequence INTEGER NOT NULL UNIQUE CHECK(ledger_sequence > 0),
        durable_snapshot_id TEXT NOT NULL UNIQUE,
        label_status TEXT NOT NULL,
        observation_context_sha256 TEXT NOT NULL,
        entry_json TEXT NOT NULL,
        entry_sha256 TEXT NOT NULL UNIQUE,
        previous_entry_chain_sha256 TEXT NOT NULL,
        entry_chain_sha256 TEXT NOT NULL UNIQUE,
        auth_tag TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX observation_manifest_admitted_ordinal
    ON observation_manifest_entries(label_status, ordinal)
    """,
    """
    CREATE TRIGGER observation_manifest_metadata_no_update
    BEFORE UPDATE ON observation_manifest_metadata
    BEGIN SELECT RAISE(ABORT, 'observation_manifest_metadata_immutable'); END
    """,
    """
    CREATE TRIGGER observation_manifest_metadata_no_delete
    BEFORE DELETE ON observation_manifest_metadata
    BEGIN SELECT RAISE(ABORT, 'observation_manifest_metadata_immutable'); END
    """,
    """
    CREATE TRIGGER observation_manifest_entries_no_update
    BEFORE UPDATE ON observation_manifest_entries
    BEGIN SELECT RAISE(ABORT, 'observation_manifest_entries_immutable'); END
    """,
    """
    CREATE TRIGGER observation_manifest_entries_no_delete
    BEFORE DELETE ON observation_manifest_entries
    BEGIN SELECT RAISE(ABORT, 'observation_manifest_entries_immutable'); END
    """,
)
_SCHEMA_IDENTITY_SHA256: Final = stable_sha256(
    [" ".join(statement.split()) for statement in _DDL_STATEMENTS]
)
_EXPECTED_SCHEMA_OBJECTS: Final = {
    "observation_manifest_metadata": "table",
    "observation_manifest_entries": "table",
    "observation_manifest_admitted_ordinal": "index",
    "observation_manifest_metadata_no_update": "trigger",
    "observation_manifest_metadata_no_delete": "trigger",
    "observation_manifest_entries_no_update": "trigger",
    "observation_manifest_entries_no_delete": "trigger",
}
_EXPECTED_SCHEMA_SQL: Final = {
    name: " ".join(statement.split())
    for name, statement in zip(
        _EXPECTED_SCHEMA_OBJECTS,
        _DDL_STATEMENTS,
        strict=True,
    )
}

_BUILD_TOKEN = object()
_PAGE_TOKEN = object()
_EXAMPLE_TOKEN = object()
_AUTHENTICATED_MANIFEST_TOKEN = object()
_AUTHENTICATED_INVENTORY_PAGE_TOKEN = object()


class ProfiledTrainingObservationManifestV1Error(RuntimeError):
    """A fixed-observation manifest failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingObservationManifestV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _training_example_adapter_contract() -> dict[str, Any]:
    """Authenticated semantics that must change with any adapter revision."""

    return {
        "schema_version": PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION,
        "trust_row_available_at_source_field": "postcommit_readback_at",
        "trust_row_available_at_semantics": (
            "TRAINER_SAMPLE_DURABLY_AVAILABLE_AT_LEDGER_POSTCOMMIT_READBACK"
        ),
        "record_generated_at_must_not_exceed_decision_time": True,
        "postcommit_readback_at_must_exceed_decision_time": True,
        "postcommit_readback_at_must_exceed_record_generated_at": True,
        "label_available_at_must_exceed_decision_time": True,
        "future_labels_not_in_feature_tensor": True,
    }


def _canonical_json(value: object, *, reason: str, maximum_bytes: int) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise ProfiledTrainingObservationManifestV1Error(reason) from exc
    if not encoded or len(encoded.encode("ascii")) > maximum_bytes:
        _fail(reason)
    return encoded


def _strict_json(raw: str, *, reason: str, maximum_bytes: int) -> dict[str, Any]:
    if type(raw) is not str or not raw or len(raw.encode("utf-8")) > maximum_bytes:
        _fail(reason)

    def reject_constant(value: str) -> NoReturn:
        _fail(f"{reason}:NONFINITE:{value}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                _fail(f"{reason}:DUPLICATE_KEY")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (RecursionError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProfiledTrainingObservationManifestV1Error(reason) from exc
    if (
        type(value) is not dict
        or _canonical_json(
            value,
            reason=reason,
            maximum_bytes=maximum_bytes,
        )
        != raw
    ):
        _fail(reason)
    return cast(dict[str, Any], value)


def _clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    normalized = parsed.astimezone(UTC)
    canonical = normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        _fail(reason)
    return normalized


def _canonical_clock(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _factory_wall_clock_now() -> datetime:
    """Return the actual factory observation clock, never a replay cutoff."""

    return datetime.now(tz=UTC)


def _validated_key(value: object) -> bytes:
    if not isinstance(value, bytes | bytearray | memoryview):
        _fail("PROFILED_OBSERVATION_HMAC_KEY_MUST_BE_BYTES")
    key = bytes(value)
    if len(key) < MIN_PROFILED_OBSERVATION_HMAC_KEY_BYTES:
        _fail("PROFILED_OBSERVATION_HMAC_KEY_TOO_SHORT")
    return key


def _auth_tag(*, role: bytes, payload: str, key: bytes) -> str:
    return hmac.new(
        key,
        PROFILED_OBSERVATION_AUTH_SEPARATOR + role + b"\0" + payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _float64_label_sha256(value: object) -> str:
    if type(value) not in {int, float}:
        _fail("PROFILED_OBSERVATION_LABEL_VALUE_INVALID")
    try:
        numeric = float(cast(int | float, value))
        encoded = struct.pack(">d", numeric)
    except (OverflowError, struct.error, TypeError, ValueError):
        _fail("PROFILED_OBSERVATION_LABEL_VALUE_INVALID")
    if not math.isfinite(numeric):
        _fail("PROFILED_OBSERVATION_LABEL_VALUE_INVALID")
    return hashlib.sha256(_FLOAT64_LABEL_DOMAIN + encoded).hexdigest()


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()


class _OrderedCanonicalStreamDigest:
    """Constant-memory, order-sensitive digest for canonical JSON records."""

    __slots__ = ("_count", "_hasher")

    def __init__(self, *, domain: str) -> None:
        if type(domain) is not str or not domain.isascii() or not domain:
            _fail("PROFILED_OBSERVATION_ORDERED_DIGEST_DOMAIN_INVALID")
        self._hasher = hashlib.sha256()
        self._hasher.update(domain.encode("ascii") + b"\0")
        self._count = 0

    def append(self, value: Mapping[str, Any]) -> None:
        encoded = _canonical_json(
            dict(value),
            reason="PROFILED_OBSERVATION_ORDERED_DIGEST_ITEM_INVALID",
            maximum_bytes=MAX_PROFILED_OBSERVATION_ENTRY_BYTES,
        ).encode("ascii")
        self._hasher.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        self._hasher.update(encoded)
        self._count += 1

    @property
    def count(self) -> int:
        return self._count

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


def _exact_absolute_path(path: object, *, reason: str) -> Path:
    if type(path) is not type(Path()):
        _fail(reason)
    candidate = cast(Path, path)
    if not candidate.is_absolute() or ".." in candidate.parts or "\x00" in str(candidate):
        _fail(reason)
    return candidate


def _sample_binding(sample: ProfiledTrainingLedgerSampleV1) -> dict[str, Any]:
    material = {
        "schema_version": "profiled_training_manifest_sample_identity_v1",
        "ledger_sequence": sample.sequence,
        "durable_snapshot_id": sample.durable_snapshot_id,
        "record_sha256": sample.record_sha256,
        "frozen_envelope_sha256": sample.frozen_envelope_sha256,
        "symbol": sample.symbol,
        "timeframe": sample.timeframe,
        "feature_snapshot_id": sample.feature_snapshot_id,
        "decision_time": sample.decision_time,
        "feature_cutoff": sample.feature_cutoff,
        "record_generated_at": sample.generated_at,
        "record_generated_at_semantics": "PROFILED_ENRICHMENT_RECORD_MATERIALIZED",
        "trainer_sample_available_at": sample.postcommit_readback_at,
        "trainer_sample_available_at_source": "LEDGER_POSTCOMMIT_READBACK_RECEIPT",
        "parent_durable_snapshot_id": sample.parent_durable_snapshot_id,
        "parent_record_sha256": sample.parent_record_sha256,
        "parent_lineage_binding_sha256": sample.parent_lineage_binding_sha256,
        "cost_capture_binding_sha256": sample.cost_capture_binding_sha256,
        "cost_capture_artifact_sha256": sample.cost_capture_artifact_sha256,
        "cost_capture_receipt_sha256": sample.cost_capture_receipt_sha256,
        "cost_cas_object_inventory_sha256": sample.cost_cas_object_inventory_sha256,
        "auxiliary_feature_receipt_sha256s": list(sample.auxiliary_feature_receipt_sha256s),
        "expected_holding_horizon_seconds": (sample.expected_holding_horizon_seconds),
        "cost_evidence_available_at": sample.cost_evidence_available_at,
        "decision_reference_price": sample.decision_reference_price,
        "decision_reference_best_bid": sample.decision_reference_best_bid,
        "decision_reference_best_ask": sample.decision_reference_best_ask,
        "decision_reference_full_spread_bps": (sample.decision_reference_full_spread_bps),
        "decision_reference_price_source": sample.decision_reference_price_source,
        "decision_reference_price_available_at": (sample.decision_reference_price_available_at),
        "decision_reference_price_binding_sha256": (sample.decision_reference_price_binding_sha256),
        "decision_reference_price_payload_sha256": (sample.decision_reference_price_payload_sha256),
        "decision_reference_price_receipt_sha256": (sample.decision_reference_price_receipt_sha256),
        "physical_feature_values_sha256": stable_sha256(list(sample.physical_feature_values)),
        "auxiliary_label_values_sha256": stable_sha256(list(sample.auxiliary_label_values)),
        "logical_model_vector_sha256": sample.logical_model_vector_sha256,
        "logical_projection_sha256": sample.logical_projection_sha256,
        "logical_profile_selection_mask_sha256": (sample.logical_profile_selection_mask_sha256),
        "logical_enabled_slot_ordinals_sha256": (sample.logical_enabled_slot_ordinals_sha256),
        "append_transaction_id": sample.append_transaction_id,
        "append_receipt_sha256": sample.append_receipt_sha256,
        "postcommit_receipt_sha256": sample.postcommit_receipt_sha256,
        "postcommit_readback_at": sample.postcommit_readback_at,
        "ledger_high_water_sha256": sample.ledger_high_water_sha256,
    }
    return {**material, "sample_identity_sha256": stable_sha256(material)}


def _label_binding(
    *,
    sample: ProfiledTrainingLedgerSampleV1,
    archive: DurableCanonical5mLabelArchive,
    archive_integrity: Mapping[str, Any],
    archive_high_water: Mapping[str, Any],
    observation: datetime,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    try:
        strict_prior = observation - timedelta(microseconds=1)
    except OverflowError:
        _fail("PROFILED_OBSERVATION_CLOCK_INVALID")
    feature_cutoff = _clock(
        sample.feature_cutoff,
        reason="PROFILED_OBSERVATION_FEATURE_CUTOFF_INVALID",
    )
    cost_available = _clock(
        sample.cost_evidence_available_at,
        reason="PROFILED_OBSERVATION_COST_AVAILABLE_AT_INVALID",
    )
    reference_available = _clock(
        sample.decision_reference_price_available_at,
        reason="PROFILED_OBSERVATION_REFERENCE_AVAILABLE_AT_INVALID",
    )
    record_generated = _clock(
        sample.generated_at,
        reason="PROFILED_OBSERVATION_RECORD_GENERATED_AT_INVALID",
    )
    decision_clock = _clock(
        sample.decision_time,
        reason="PROFILED_OBSERVATION_DECISION_TIME_INVALID",
    )
    trainer_sample_available = _clock(
        sample.postcommit_readback_at,
        reason="PROFILED_OBSERVATION_SAMPLE_AVAILABLE_AT_INVALID",
    )
    if not (
        feature_cutoff <= record_generated
        and reference_available <= decision_clock
        and cost_available <= record_generated
        and record_generated <= decision_clock
        and decision_clock < trainer_sample_available < observation
    ):
        _fail("PROFILED_OBSERVATION_SAMPLE_TEMPORAL_ORDER_INVALID")
    try:
        rows, path_proof = archive.verified_label_path(
            symbol=sample.symbol,
            decision_time=sample.decision_time,
            training_observed_at=strict_prior,
            horizon_seconds=sample.expected_holding_horizon_seconds,
            archive_integrity_proof=archive_integrity,
            require_receipt_committed_by_observation=True,
        )
    except (Canonical5mArchiveError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise ProfiledTrainingObservationManifestV1Error(
            f"PROFILED_OBSERVATION_LABEL_PATH_READ_FAILED:{type(exc).__name__}"
        ) from exc
    if rows is None:
        range_proof = path_proof.get("range_proof")
        if isinstance(range_proof, Mapping) and (
            range_proof.get("archive_integrity_proof_reused") is True
            and range_proof.get("archive_integrity_proof_current") is False
        ):
            _fail("PROFILED_OBSERVATION_LABEL_INTEGRITY_PROOF_MOVED_DURING_BUILD")
        reasons = tuple(
            sorted(
                {str(reason) for reason in path_proof.get("rejection_reasons") or () if str(reason)}
            )
        )
        return None, reasons or ("PROFILED_OBSERVATION_LABEL_PATH_UNAVAILABLE",)
    range_proof = path_proof.get("range_proof")
    if (
        type(range_proof) is not dict
        or path_proof.get("status") != "VERIFIED_CANONICAL_5M_TRAINER_LABEL_PATH"
        or path_proof.get("pit_available_at_verified") is not True
        or path_proof.get("strictly_after_decision_verified") is not True
        or path_proof.get("horizon_endpoint_verified") is not True
        or range_proof.get("archive_integrity_proof_reused") is not True
        or range_proof.get("archive_integrity_proof_current") is not True
        or range_proof.get("canonical_payloads_verified") is not True
        or range_proof.get("content_sha256_verified") is not True
        or range_proof.get("append_transaction_precommit_receipts_verified") is not True
        or range_proof.get("postcommit_readback_receipts_verified") is not True
        or range_proof.get("record_chain_formula_verified") is not True
        or range_proof.get("pit_available_at_verified") is not True
        or range_proof.get("contiguous_path_verified") is not True
        or range_proof.get("receipt_commit_cutoff_required") is not True
        or not _valid_sha256(path_proof.get("label_path_sha256"))
        or not _valid_sha256(range_proof.get("range_sha256"))
    ):
        _fail("PROFILED_OBSERVATION_LABEL_PATH_PROOF_INVALID")
    if path_proof.get(
        "horizon_seconds"
    ) != sample.expected_holding_horizon_seconds or range_proof.get("end_close_time_ms") != rows[
        -1
    ].get("candle_close_time"):
        _fail("PROFILED_OBSERVATION_LABEL_HORIZON_BINDING_MISMATCH")
    epoch_delta = decision_clock - datetime(1970, 1, 1, tzinfo=UTC)
    decision_epoch_us = (
        epoch_delta.days * 86_400_000_000
        + epoch_delta.seconds * 1_000_000
        + epoch_delta.microseconds
    )
    expected_target_us = decision_epoch_us + sample.expected_holding_horizon_seconds * 1_000_000
    if (
        path_proof.get("horizon_target_time_epoch_us") != expected_target_us
        or path_proof.get("horizon_target_time_ms") != (expected_target_us + 999) // 1_000
    ):
        _fail("PROFILED_OBSERVATION_LABEL_HORIZON_TARGET_MISMATCH")
    entry_price = sample.decision_reference_price
    final_close = rows[-1].get("close")
    if type(entry_price) not in {int, float} or type(final_close) not in {int, float}:
        _fail("PROFILED_OBSERVATION_LABEL_PRICE_INVALID")
    entry_price = float(cast(int | float, entry_price))
    final_close = float(cast(int | float, final_close))
    if (
        not math.isfinite(entry_price)
        or not math.isfinite(final_close)
        or entry_price <= 0.0
        or final_close <= 0.0
    ):
        _fail("PROFILED_OBSERVATION_LABEL_PRICE_INVALID")
    fee_bps, spread_bps, slippage_bps, funding_bps = sample.auxiliary_label_values
    if (
        any(not math.isfinite(value) for value in sample.auxiliary_label_values)
        or fee_bps < 0.0
        or spread_bps < 0.0
        or slippage_bps < 0.0
    ):
        _fail("PROFILED_OBSERVATION_DIRECTIONAL_COST_INVALID")
    base_execution_cost_bps = 2.0 * fee_bps + spread_bps + 2.0 * slippage_bps
    long_round_trip_cost_bps = base_execution_cost_bps + funding_bps
    short_round_trip_cost_bps = base_execution_cost_bps - funding_bps
    raw_return_bps = ((final_close - entry_price) / entry_price) * 10_000.0
    long_net_bps = raw_return_bps - long_round_trip_cost_bps
    short_net_bps = -raw_return_bps - short_round_trip_cost_bps
    if any(
        not math.isfinite(value)
        for value in (
            base_execution_cost_bps,
            long_round_trip_cost_bps,
            short_round_trip_cost_bps,
            raw_return_bps,
            long_net_bps,
            short_net_bps,
        )
    ):
        _fail("PROFILED_OBSERVATION_DIRECTIONAL_COST_INVALID")
    target_action = target_action_from_net_edges(
        long_net_bps=long_net_bps,
        short_net_bps=short_net_bps,
    )
    action_index = target_action_index(target_action)
    if target_action == "long":
        chosen_directional_cost_bps: float | None = long_round_trip_cost_bps
        chosen_directional_net_bps = long_net_bps
        after_cost = long_net_bps
    elif target_action == "short":
        chosen_directional_cost_bps = short_round_trip_cost_bps
        chosen_directional_net_bps = short_net_bps
        after_cost = -short_net_bps
    else:
        chosen_directional_cost_bps = None
        chosen_directional_net_bps = 0.0
        after_cost = 0.0
    if type(action_index) is not int or action_index not in {0, 1, 2}:
        _fail("PROFILED_OBSERVATION_ACTION_LABEL_INVALID")
    label_value_sha256 = _float64_label_sha256(after_cost)
    label_available_at_ms = path_proof.get("label_available_at_ms")
    if type(label_available_at_ms) is not int or label_available_at_ms <= 0:
        _fail("PROFILED_OBSERVATION_LABEL_AVAILABLE_AT_INVALID")
    try:
        label_available_at = _canonical_clock(
            datetime.fromtimestamp(label_available_at_ms / 1_000.0, tz=UTC)
        )
    except (OSError, OverflowError, ValueError):
        _fail("PROFILED_OBSERVATION_LABEL_AVAILABLE_AT_INVALID")
    label_available = _clock(
        label_available_at,
        reason="PROFILED_OBSERVATION_LABEL_AVAILABLE_AT_INVALID",
    )
    decision = _clock(
        sample.decision_time,
        reason="PROFILED_OBSERVATION_DECISION_TIME_INVALID",
    )
    if not decision < label_available < observation:
        _fail("PROFILED_OBSERVATION_LABEL_TEMPORAL_ORDER_INVALID")
    candle_identities = [
        {
            "candle_id": row.get("candle_id"),
            "candle_open_time_ms": row.get("candle_open_time"),
            "candle_close_time_ms": row.get("candle_close_time"),
            "available_at_ms": row.get("available_at"),
            "raw_payload_hash": row.get("raw_payload_hash"),
            "content_sha256": hashlib.sha256(canonical_label_json(row).encode("utf-8")).hexdigest(),
        }
        for row in rows
    ]
    directional_cost_material = {
        "schema_version": "profiled_training_directional_cost_label_v1",
        "cost_capture_binding_sha256": sample.cost_capture_binding_sha256,
        "cost_capture_artifact_sha256": sample.cost_capture_artifact_sha256,
        "cost_capture_receipt_sha256": sample.cost_capture_receipt_sha256,
        "cost_cas_object_inventory_sha256": sample.cost_cas_object_inventory_sha256,
        "auxiliary_feature_receipt_sha256s": list(sample.auxiliary_feature_receipt_sha256s),
        "cost_evidence_available_at": sample.cost_evidence_available_at,
        "decision_reference_price": entry_price,
        "decision_reference_price_source": sample.decision_reference_price_source,
        "decision_reference_price_available_at": (sample.decision_reference_price_available_at),
        "decision_reference_price_binding_sha256": (sample.decision_reference_price_binding_sha256),
        "decision_reference_price_payload_sha256": (sample.decision_reference_price_payload_sha256),
        "decision_reference_price_receipt_sha256": (sample.decision_reference_price_receipt_sha256),
        "expected_holding_horizon_seconds": (sample.expected_holding_horizon_seconds),
        "fee_bps_per_side": fee_bps,
        "full_spread_bps": spread_bps,
        "expected_slippage_bps_per_side": slippage_bps,
        "signed_expected_funding_bps": funding_bps,
        "base_execution_cost_bps": base_execution_cost_bps,
        "long_round_trip_cost_bps": long_round_trip_cost_bps,
        "short_round_trip_cost_bps": short_round_trip_cost_bps,
        "raw_return_bps": raw_return_bps,
        "long_net_bps": long_net_bps,
        "short_net_bps": short_net_bps,
        "chosen_direction": target_action,
        "chosen_directional_round_trip_cost_bps": chosen_directional_cost_bps,
        "chosen_directional_net_bps": chosen_directional_net_bps,
        "funding_sign_semantics": "POSITIVE_VENUE_RATE_LONG_PAYS_SHORT_RECEIVES",
        "round_trip_formula": (
            "base=2*fee_per_side+full_spread+2*slippage_per_side;"
            "long=base+signed_funding;short=base-signed_funding"
        ),
    }
    directional_cost_evidence_sha256 = stable_sha256(directional_cost_material)
    material = {
        "schema_version": PROFILED_OBSERVATION_LABEL_BINDING_V1_SCHEMA_VERSION,
        "archive_path": str(archive.path),
        "archive_path_sha256": _path_sha256(archive.path),
        "archive_high_water_sha256": archive_high_water.get("high_water_sha256"),
        "observation_time": _canonical_clock(observation),
        "receipt_observation_strict_upper_bound": _canonical_clock(strict_prior),
        "decision_time": sample.decision_time,
        "label_available_at": label_available_at,
        "label_action_index": action_index,
        "label_target_action": target_action,
        "label_expected_move_after_cost_bps": after_cost,
        "label_expected_move_after_cost_bps_float64_sha256": label_value_sha256,
        "label_horizon_seconds": sample.expected_holding_horizon_seconds,
        "label_horizon_source": "AUTHENTICATED_CAUSAL_COST_BINDING",
        "label_horizon_target_time_epoch_us": path_proof.get("horizon_target_time_epoch_us"),
        "label_horizon_target_time_ms": path_proof.get("horizon_target_time_ms"),
        "label_final_candle_close_time_ms": rows[-1].get("candle_close_time"),
        "label_path_sha256": path_proof.get("label_path_sha256"),
        "label_range_sha256": range_proof.get("range_sha256"),
        "label_path_candle_count": len(rows),
        "label_path_candle_identities_sha256": stable_sha256(candle_identities),
        "label_append_receipt_sha256s": range_proof.get("append_receipt_sha256"),
        "label_postcommit_receipt_sha256s": range_proof.get("postcommit_readback_receipt_sha256"),
        "directional_cost_evidence": directional_cost_material,
        "directional_cost_evidence_sha256": directional_cost_evidence_sha256,
        "future_labels_not_in_feature_tensor": True,
        "auxiliary_cost_values_excluded_from_model_vector": True,
        "static_action_threshold_used": False,
    }
    if (
        not _valid_sha256(material["directional_cost_evidence_sha256"])
        or material["static_action_threshold_used"] is not False
    ):
        _fail("PROFILED_OBSERVATION_LABEL_BINDING_INVALID")
    return {
        **material,
        "label_binding_sha256": stable_sha256(material),
    }, ()


def _tensor_binding(
    *,
    sample: ProfiledTrainingLedgerSampleV1,
    label_binding: Mapping[str, Any],
) -> dict[str, Any]:
    lineage = {
        "schema_version": "profiled_training_example_lineage_v1",
        "sample_identity_sha256": _sample_binding(sample)["sample_identity_sha256"],
        "logical_projection_sha256": sample.logical_projection_sha256,
        "label_binding_sha256": label_binding.get("label_binding_sha256"),
        "feature_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "feature_registry_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    }
    source_lineage_hash = stable_sha256(lineage)
    tensor_identity = {
        "schema_version": PROFILED_OBSERVATION_TENSOR_BINDING_V1_SCHEMA_VERSION,
        "durable_snapshot_id": sample.durable_snapshot_id,
        "logical_model_vector_sha256": sample.logical_model_vector_sha256,
        "source_lineage_hash": source_lineage_hash,
    }
    tensor_id = "v2_profiled_observation_tensor_" + stable_sha256(tensor_identity)[:32]
    material = {
        **tensor_identity,
        "tensor_id": tensor_id,
        "feature_snapshot_id": sample.feature_snapshot_id,
        "logical_feature_count": LOGICAL_MODEL_FEATURE_COUNT,
        "logical_model_input_count": LOGICAL_MODEL_INPUT_COUNT,
        "logical_ordered_feature_names_sha256": stable_sha256(list(LOGICAL_ORDERED_FEATURE_NAMES)),
        "logical_profile_selection_mask_sha256": (sample.logical_profile_selection_mask_sha256),
        "logical_enabled_slot_ordinals_sha256": (sample.logical_enabled_slot_ordinals_sha256),
        "logical_projection_sha256": sample.logical_projection_sha256,
        "feature_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
        "feature_registry_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
        "source_lineage_hash": source_lineage_hash,
        "data_coverage_semantics": (
            "PROFILE_SELECTED_SLOTS_OVER_LOGICAL_ABI_DISABLED_SLOTS_ARE_NOT_MISSING"
        ),
    }
    return {**material, "tensor_binding_sha256": stable_sha256(material)}


def _entry_material(
    *,
    ordinal: int,
    sample: ProfiledTrainingLedgerSampleV1,
    observation_context_sha256: str,
    label_binding: Mapping[str, Any] | None,
    label_rejection_reasons: Sequence[str],
) -> dict[str, Any]:
    sample_binding = _sample_binding(sample)
    if label_binding is None:
        status = PROFILED_OBSERVATION_LABEL_STATUS_UNAVAILABLE
        tensor_binding = None
    else:
        status = PROFILED_OBSERVATION_LABEL_STATUS_ADMITTED
        tensor_binding = _tensor_binding(sample=sample, label_binding=label_binding)
    return {
        "schema_version": PROFILED_OBSERVATION_ENTRY_V1_SCHEMA_VERSION,
        "ordinal": ordinal,
        "observation_context_sha256": observation_context_sha256,
        "label_status": status,
        "sample_binding": sample_binding,
        "label_binding": dict(label_binding) if label_binding is not None else None,
        "label_rejection_reasons": sorted(set(str(item) for item in label_rejection_reasons)),
        "tensor_binding": tensor_binding,
        "training_example_adapter_available": label_binding is not None,
        "optimizer_admission_authorized": False,
        "checkpoint_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "runtime_wired": False,
    }


def _entry_chain(previous: str, entry_sha256: str) -> str:
    if not _valid_sha256(previous) or not _valid_sha256(entry_sha256):
        _fail("PROFILED_OBSERVATION_ENTRY_CHAIN_INPUT_INVALID")
    return hashlib.sha256(
        _ENTRY_CHAIN_DOMAIN + bytes.fromhex(previous) + bytes.fromhex(entry_sha256)
    ).hexdigest()


def _entry_row_auth_payload(
    *,
    ordinal: object,
    ledger_sequence: object,
    durable_snapshot_id: object,
    label_status: object,
    observation_context_sha256: object,
    entry_sha256: object,
    previous_entry_chain_sha256: object,
    entry_chain_sha256: object,
) -> str:
    """Canonical HMAC envelope for every security-relevant entry column."""

    return _canonical_json(
        {
            "schema_version": "profiled_training_observation_entry_row_auth_v1",
            "ordinal": ordinal,
            "ledger_sequence": ledger_sequence,
            "durable_snapshot_id": durable_snapshot_id,
            "label_status": label_status,
            "observation_context_sha256": observation_context_sha256,
            "entry_sha256": entry_sha256,
            "previous_entry_chain_sha256": previous_entry_chain_sha256,
            "entry_chain_sha256": entry_chain_sha256,
        },
        reason="PROFILED_OBSERVATION_ENTRY_ROW_AUTH_PAYLOAD_INVALID",
        maximum_bytes=MAX_PROFILED_OBSERVATION_ENTRY_BYTES,
    )


def _schema_objects(connection: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    return {
        str(row["name"]): (
            str(row["type"]),
            " ".join(str(row["sql"]).split()),
        )
        for row in connection.execute(
            "SELECT name, type, sql FROM sqlite_master " "WHERE name IN (?, ?, ?, ?, ?, ?, ?)",
            tuple(_EXPECTED_SCHEMA_OBJECTS),
        )
    }


def _validate_schema(connection: sqlite3.Connection) -> None:
    expected = {
        name: (_EXPECTED_SCHEMA_OBJECTS[name], _EXPECTED_SCHEMA_SQL[name])
        for name in _EXPECTED_SCHEMA_OBJECTS
    }
    if _schema_objects(connection) != expected:
        _fail("PROFILED_OBSERVATION_MANIFEST_SCHEMA_INVALID")
    metadata_columns = [
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(observation_manifest_metadata)")
    ]
    entry_columns = [
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(observation_manifest_entries)")
    ]
    if metadata_columns != [
        "singleton",
        "manifest_id",
        "metadata_json",
        "metadata_sha256",
        "auth_tag",
    ] or entry_columns != [
        "ordinal",
        "ledger_sequence",
        "durable_snapshot_id",
        "label_status",
        "observation_context_sha256",
        "entry_json",
        "entry_sha256",
        "previous_entry_chain_sha256",
        "entry_chain_sha256",
        "auth_tag",
    ]:
        _fail("PROFILED_OBSERVATION_MANIFEST_SCHEMA_COLUMNS_INVALID")


def _verify_metadata_row(
    row: sqlite3.Row,
    *,
    key: bytes,
    expected_auth_key_id: str | None,
    path: Path,
) -> dict[str, Any]:
    metadata_json = str(row["metadata_json"])
    metadata = _strict_json(
        metadata_json,
        reason="PROFILED_OBSERVATION_METADATA_JSON_INVALID",
        maximum_bytes=MAX_PROFILED_OBSERVATION_METADATA_BYTES,
    )
    metadata_sha256 = hashlib.sha256(metadata_json.encode("ascii")).hexdigest()
    supplied_tag = str(row["auth_tag"])
    expected_tag = _auth_tag(role=b"metadata", payload=metadata_json, key=key)
    if (
        metadata.get("schema_version") != PROFILED_OBSERVATION_MANIFEST_V1_SCHEMA_VERSION
        or metadata.get("schema_identity_sha256") != _SCHEMA_IDENTITY_SHA256
        or row["manifest_id"] != metadata.get("manifest_id")
        or row["metadata_sha256"] != metadata_sha256
        or not _valid_sha256(metadata.get("manifest_id"))
        or not _valid_sha256(supplied_tag)
        or not hmac.compare_digest(expected_tag, supplied_tag)
        or metadata.get("auth_algorithm") != PROFILED_OBSERVATION_AUTH_ALGORITHM
        or metadata.get("auth_domain") != PROFILED_OBSERVATION_AUTH_DOMAIN
        or type(metadata.get("auth_key_id")) is not str
        or _AUTH_KEY_ID_RE.fullmatch(metadata["auth_key_id"]) is None
        or (
            expected_auth_key_id is not None and metadata.get("auth_key_id") != expected_auth_key_id
        )
        or path.name != f"profiled_training_observation_{metadata.get('manifest_id')}.sqlite3"
    ):
        _fail("PROFILED_OBSERVATION_METADATA_AUTHENTICATION_INVALID")
    unsigned_for_id = {
        key_name: value for key_name, value in metadata.items() if key_name != "manifest_id"
    }
    if metadata["manifest_id"] != stable_sha256(unsigned_for_id):
        _fail("PROFILED_OBSERVATION_MANIFEST_ID_INVALID")
    if (
        metadata.get("runtime_status") != PROFILED_OBSERVATION_RUNTIME_STATUS
        or metadata.get("optimizer_admission_authorized") is not False
        or metadata.get("checkpoint_write_authorized") is not False
        or metadata.get("prediction_authorized") is not False
        or metadata.get("paper_trading_authorized") is not False
        or metadata.get("live_execution_authorized") is not False
        or metadata.get("runtime_wired") is not False
        or metadata.get("external_monotonic_manifest_head_verified") is not False
    ):
        _fail("PROFILED_OBSERVATION_METADATA_AUTHORITY_INVALID")
    total = metadata.get("total_profiled_samples")
    admitted = metadata.get("admitted_example_count")
    unavailable = metadata.get("label_unavailable_count")
    exclusions = metadata.get("ledger_exclusion_count")
    context = metadata.get("observation_context")
    adapter_contract = _training_example_adapter_contract()
    if (
        type(total) is not int
        or total < 0
        or type(admitted) is not int
        or type(unavailable) is not int
        or admitted < 0
        or unavailable < 0
        or total != admitted + unavailable
        or type(exclusions) is not int
        or exclusions < 0
        or type(context) is not dict
        or metadata.get("observation_context_sha256") != stable_sha256(context)
        or context.get("training_example_adapter_contract") != adapter_contract
        or context.get("training_example_adapter_contract_sha256")
        != stable_sha256(adapter_contract)
        or metadata.get("observation_time") != context.get("observation_time")
        or metadata.get("retrospective_cutoff_at") != metadata.get("observation_time")
        or context.get("retrospective_cutoff_at") != metadata.get("observation_time")
        or metadata.get("factory_wall_clock_observed_at")
        != context.get("factory_wall_clock_observed_at")
        or metadata.get("ordered_digest_schema_version")
        != PROFILED_OBSERVATION_ORDERED_DIGEST_SCHEMA_VERSION
        or metadata.get("ordered_digest_algorithm") != PROFILED_OBSERVATION_ORDERED_DIGEST_ALGORITHM
        or metadata.get("ordered_entry_identity_digest_domain")
        != PROFILED_OBSERVATION_ENTRY_IDENTITY_DIGEST_DOMAIN
        or metadata.get("ordered_entry_identity_count") != total
        or not _valid_sha256(metadata.get("ordered_entry_identities_sha256"))
        or metadata.get("ordered_ledger_exclusion_digest_domain")
        != PROFILED_OBSERVATION_EXCLUSION_DIGEST_DOMAIN
        or metadata.get("ordered_ledger_exclusion_count") != exclusions
        or not _valid_sha256(metadata.get("ledger_exclusion_inventory_sha256"))
        or metadata.get("entry_chain_genesis_sha256") != PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
        or not _valid_sha256(metadata.get("entry_chain_head_sha256"))
        or metadata.get("bounded_runtime_reopen") is not True
        or metadata.get("full_ledger_scan_required_on_runtime_reopen") is not False
        or metadata.get("label_archive_reopen_required_on_runtime_reopen") is not False
        or metadata.get("training_example_adapter_available") is not (admitted > 0)
        or type(metadata.get("source_page_size")) is not int
        or metadata.get("source_page_size") <= 0
        or type(metadata.get("maximum_resident_source_page_rows")) is not int
        or not 0
        <= metadata.get("maximum_resident_source_page_rows")
        <= metadata.get("source_page_size")
        or type(metadata.get("maximum_resident_entry_rows")) is not int
        or not 0 <= metadata.get("maximum_resident_entry_rows") <= 1
    ):
        _fail("PROFILED_OBSERVATION_METADATA_CONTRACT_INVALID")
    cutoff = _clock(
        metadata.get("observation_time"),
        reason="PROFILED_OBSERVATION_METADATA_CLOCK_INVALID",
    )
    factory_clock = _clock(
        metadata.get("factory_wall_clock_observed_at"),
        reason="PROFILED_OBSERVATION_METADATA_FACTORY_CLOCK_INVALID",
    )
    if cutoff > factory_clock:
        _fail("PROFILED_OBSERVATION_METADATA_CLOCK_ORDER_INVALID")
    return metadata


def _run_full_sqlite_check(connection: sqlite3.Connection) -> None:
    if str(connection.execute("PRAGMA quick_check(1)").fetchone()[0]) != "ok":
        _fail("PROFILED_OBSERVATION_MANIFEST_SQLITE_QUICK_CHECK_FAILED")


def _open_readonly(
    path: Path,
    *,
    full_database_check: bool,
) -> tuple[sqlite3.Connection, os.stat_result]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                _fail("PROFILED_OBSERVATION_MANIFEST_NOT_REGULAR_FILE")
            if before.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                _fail("PROFILED_OBSERVATION_MANIFEST_PERMISSIONS_UNSAFE")
        finally:
            os.close(descriptor)
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=60.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        after = os.stat(path, follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            connection.close()
            _fail("PROFILED_OBSERVATION_MANIFEST_CHANGED_WHILE_OPENING")
        if full_database_check:
            _run_full_sqlite_check(connection)
        _validate_schema(connection)
        return connection, before
    except ProfiledTrainingObservationManifestV1Error:
        raise
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise ProfiledTrainingObservationManifestV1Error(
            f"PROFILED_OBSERVATION_MANIFEST_OPEN_FAILED:{type(exc).__name__}"
        ) from exc


def _read_metadata(
    path: Path,
    *,
    key: bytes,
    expected_auth_key_id: str | None,
    full_database_check: bool,
) -> tuple[sqlite3.Connection, dict[str, Any]]:
    connection, _ = _open_readonly(
        path,
        full_database_check=full_database_check,
    )
    row = connection.execute(
        "SELECT manifest_id, metadata_json, metadata_sha256, auth_tag "
        "FROM observation_manifest_metadata WHERE singleton = 1"
    ).fetchone()
    if row is None:
        connection.close()
        _fail("PROFILED_OBSERVATION_METADATA_MISSING")
    metadata = _verify_metadata_row(
        row,
        key=key,
        expected_auth_key_id=expected_auth_key_id,
        path=path,
    )
    return connection, metadata


def _verify_entry_row(
    row: sqlite3.Row,
    *,
    key: bytes,
    observation_context_sha256: str,
    expected_previous_chain: str | None = None,
) -> dict[str, Any]:
    entry_json = str(row["entry_json"])
    entry = _strict_json(
        entry_json,
        reason="PROFILED_OBSERVATION_ENTRY_JSON_INVALID",
        maximum_bytes=MAX_PROFILED_OBSERVATION_ENTRY_BYTES,
    )
    entry_sha256 = hashlib.sha256(entry_json.encode("ascii")).hexdigest()
    previous = str(row["previous_entry_chain_sha256"])
    entry_chain = str(row["entry_chain_sha256"])
    supplied_tag = str(row["auth_tag"])
    expected_tag = _auth_tag(
        role=b"entry-row",
        payload=_entry_row_auth_payload(
            ordinal=row["ordinal"],
            ledger_sequence=row["ledger_sequence"],
            durable_snapshot_id=row["durable_snapshot_id"],
            label_status=row["label_status"],
            observation_context_sha256=row["observation_context_sha256"],
            entry_sha256=row["entry_sha256"],
            previous_entry_chain_sha256=row["previous_entry_chain_sha256"],
            entry_chain_sha256=row["entry_chain_sha256"],
        ),
        key=key,
    )
    sample_binding = entry.get("sample_binding")
    if (
        entry.get("schema_version") != PROFILED_OBSERVATION_ENTRY_V1_SCHEMA_VERSION
        or type(sample_binding) is not dict
        or entry.get("ordinal") != row["ordinal"]
        or sample_binding.get("ledger_sequence") != row["ledger_sequence"]
        or sample_binding.get("durable_snapshot_id") != row["durable_snapshot_id"]
        or entry.get("label_status") != row["label_status"]
        or entry.get("observation_context_sha256") != observation_context_sha256
        or row["observation_context_sha256"] != observation_context_sha256
        or row["entry_sha256"] != entry_sha256
        or not _valid_sha256(previous)
        or entry_chain != _entry_chain(previous, entry_sha256)
        or (expected_previous_chain is not None and previous != expected_previous_chain)
        or not _valid_sha256(supplied_tag)
        or not hmac.compare_digest(expected_tag, supplied_tag)
        or entry.get("optimizer_admission_authorized") is not False
        or entry.get("checkpoint_write_authorized") is not False
        or entry.get("prediction_authorized") is not False
        or entry.get("paper_trading_authorized") is not False
        or entry.get("live_execution_authorized") is not False
        or entry.get("runtime_wired") is not False
    ):
        _fail("PROFILED_OBSERVATION_ENTRY_AUTHENTICATION_INVALID")
    sample_unsigned = {
        key_name: value
        for key_name, value in sample_binding.items()
        if key_name != "sample_identity_sha256"
    }
    if sample_binding.get("sample_identity_sha256") != stable_sha256(sample_unsigned):
        _fail("PROFILED_OBSERVATION_SAMPLE_IDENTITY_INVALID")
    admitted = entry.get("label_status") == PROFILED_OBSERVATION_LABEL_STATUS_ADMITTED
    unavailable = entry.get("label_status") == PROFILED_OBSERVATION_LABEL_STATUS_UNAVAILABLE
    reasons = entry.get("label_rejection_reasons")
    if (
        not (admitted or unavailable)
        or type(reasons) is not list
        or any(type(reason) is not str or not reason for reason in reasons)
        or (admitted and reasons != [])
        or (admitted and type(entry.get("label_binding")) is not dict)
        or (admitted and type(entry.get("tensor_binding")) is not dict)
        or (admitted and entry.get("training_example_adapter_available") is not True)
        or (unavailable and not reasons)
        or (unavailable and entry.get("label_binding") is not None)
        or (unavailable and entry.get("tensor_binding") is not None)
        or (unavailable and entry.get("training_example_adapter_available") is not False)
    ):
        _fail("PROFILED_OBSERVATION_ENTRY_STATUS_INVALID")
    return entry


def _verify_complete_entry_stream(
    connection: sqlite3.Connection,
    *,
    metadata: Mapping[str, Any],
    key: bytes,
) -> None:
    """Authenticate the exact entry inventory, order, chain, and identities."""

    total = metadata.get("total_profiled_samples")
    admitted_expected = metadata.get("admitted_example_count")
    unavailable_expected = metadata.get("label_unavailable_count")
    context_sha256 = metadata.get("observation_context_sha256")
    if (
        type(total) is not int
        or total < 0
        or type(admitted_expected) is not int
        or type(unavailable_expected) is not int
        or not _valid_sha256(context_sha256)
    ):
        _fail("PROFILED_OBSERVATION_ENTRY_INVENTORY_METADATA_INVALID")
    previous_chain = PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
    after_ordinal = 0
    admitted = 0
    unavailable = 0
    identity_digest = _OrderedCanonicalStreamDigest(
        domain=PROFILED_OBSERVATION_ENTRY_IDENTITY_DIGEST_DOMAIN
    )
    while True:
        cursor = connection.execute(
            "SELECT ordinal, ledger_sequence, durable_snapshot_id, label_status, "
            "observation_context_sha256, entry_json, entry_sha256, "
            "previous_entry_chain_sha256, entry_chain_sha256, auth_tag "
            "FROM observation_manifest_entries WHERE ordinal > ? "
            "ORDER BY ordinal ASC LIMIT ?",
            (after_ordinal, MAX_PROFILED_OBSERVATION_VERIFY_STREAM_PAGE_ROWS),
        )
        page_row_count = 0
        for row in cursor:
            page_row_count += 1
            expected_ordinal = after_ordinal + 1
            if row["ordinal"] != expected_ordinal:
                _fail("PROFILED_OBSERVATION_ENTRY_ORDINAL_GAP")
            entry = _verify_entry_row(
                row,
                key=key,
                observation_context_sha256=cast(str, context_sha256),
                expected_previous_chain=previous_chain,
            )
            sample_binding = cast(dict[str, Any], entry["sample_binding"])
            identity_digest.append(
                {
                    "ordinal": expected_ordinal,
                    "ledger_sequence": sample_binding["ledger_sequence"],
                    "sample_identity_sha256": sample_binding["sample_identity_sha256"],
                    "label_status": entry["label_status"],
                    "entry_sha256": row["entry_sha256"],
                    "entry_chain_sha256": row["entry_chain_sha256"],
                }
            )
            if entry["label_status"] == PROFILED_OBSERVATION_LABEL_STATUS_ADMITTED:
                admitted += 1
            else:
                unavailable += 1
            previous_chain = str(row["entry_chain_sha256"])
            after_ordinal = expected_ordinal
        if page_row_count == 0:
            break
    if (
        after_ordinal != total
        or admitted != admitted_expected
        or unavailable != unavailable_expected
        or admitted + unavailable != total
        or identity_digest.count != total
        or previous_chain != metadata.get("entry_chain_head_sha256")
        or identity_digest.hexdigest() != metadata.get("ordered_entry_identities_sha256")
    ):
        _fail("PROFILED_OBSERVATION_ENTRY_INVENTORY_AUTHENTICATION_INVALID")


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationManifestBuildV1:
    manifest_path: Path
    manifest_id: str
    observation_time: str
    factory_wall_clock_observed_at: str
    total_profiled_samples: int
    admitted_examples: int
    label_unavailable_samples: int
    ledger_exclusions: int
    checkpoint_write_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _BUILD_TOKEN
            or not self.manifest_path.is_absolute()
            or not _valid_sha256(self.manifest_id)
            or self.total_profiled_samples
            != self.admitted_examples + self.label_unavailable_samples
            or self.checkpoint_write_authorized is not False
            or self.runtime_wired is not False
        ):
            _fail("PROFILED_OBSERVATION_BUILD_RESULT_INVALID")
        if _clock(
            self.observation_time,
            reason="PROFILED_OBSERVATION_BUILD_CUTOFF_INVALID",
        ) > _clock(
            self.factory_wall_clock_observed_at,
            reason="PROFILED_OBSERVATION_BUILD_WALL_CLOCK_INVALID",
        ):
            _fail("PROFILED_OBSERVATION_BUILD_CLOCK_ORDER_INVALID")


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledTrainingObservationManifestV1:
    """Immutable scalar result of authenticating one complete manifest.

    This result proves only local file, schema, metadata, HMAC, and complete
    entry-inventory integrity.  It deliberately does not claim that the
    manifest is the externally witnessed monotonic successor of any earlier
    manifest.
    """

    manifest_path: Path
    manifest_file_device: int
    manifest_file_inode: int
    manifest_file_byte_count: int
    manifest_id: str
    metadata_sha256: str
    metadata_auth_tag: str
    observation_time: str
    retrospective_cutoff_at: str
    factory_wall_clock_observed_at: str
    auth_algorithm: str
    auth_domain: str
    auth_key_id: str
    observation_context_sha256: str
    feature_ledger_path: str
    feature_ledger_path_sha256: str
    feature_ledger_high_water_sha256: str
    feature_ledger_verified_records: int
    feature_ledger_prefix_head_sequence: int
    feature_ledger_archive_chain_sha256: str
    feature_ledger_ordered_receipts_sha256: str
    label_archive_path: str
    label_archive_path_sha256: str
    label_archive_high_water_sha256: str
    label_archive_verified_rows: int
    label_archive_prefix_head_sequence: int
    label_archive_archive_chain_sha256: str
    label_archive_ordered_receipts_sha256: str
    entry_chain_genesis_sha256: str
    entry_chain_head_sha256: str
    ordered_entry_identities_sha256: str
    total_profiled_samples: int
    admitted_example_count: int
    label_unavailable_count: int
    ledger_exclusion_count: int
    ledger_exclusion_inventory_sha256: str
    full_manifest_authentication_verified: bool
    full_entry_inventory_verified: bool
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    optimizer_admission_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _authenticated_manifest_key_sha256: str = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        hashes = (
            self.manifest_id,
            self.metadata_sha256,
            self.metadata_auth_tag,
            self.observation_context_sha256,
            self.feature_ledger_path_sha256,
            self.feature_ledger_high_water_sha256,
            self.feature_ledger_archive_chain_sha256,
            self.feature_ledger_ordered_receipts_sha256,
            self.label_archive_path_sha256,
            self.label_archive_high_water_sha256,
            self.label_archive_archive_chain_sha256,
            self.label_archive_ordered_receipts_sha256,
            self.entry_chain_genesis_sha256,
            self.entry_chain_head_sha256,
            self.ordered_entry_identities_sha256,
            self.ledger_exclusion_inventory_sha256,
            self._authenticated_manifest_key_sha256,
        )
        false_authority = (
            self.external_monotonic_manifest_head_verified,
            self.full_consumption_external_ack_verified,
            self.optimizer_admission_authorized,
            self.checkpoint_write_authorized,
            self.model_write_authorized,
            self.prediction_authorized,
            self.paper_trading_authorized,
            self.live_execution_authorized,
            self.execution_authorized,
            self.runtime_wired,
        )
        if (
            self._construction_token is not _AUTHENTICATED_MANIFEST_TOKEN
            or not self.manifest_path.is_absolute()
            or self.manifest_path.name
            != f"profiled_training_observation_{self.manifest_id}.sqlite3"
            or self.manifest_file_device < 0
            or self.manifest_file_inode <= 0
            or self.manifest_file_byte_count <= 0
            or not all(_valid_sha256(value) for value in hashes)
            or self.auth_algorithm != PROFILED_OBSERVATION_AUTH_ALGORITHM
            or self.auth_domain != PROFILED_OBSERVATION_AUTH_DOMAIN
            or _AUTH_KEY_ID_RE.fullmatch(self.auth_key_id) is None
            or self.total_profiled_samples
            != self.admitted_example_count + self.label_unavailable_count
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.feature_ledger_verified_records,
                    self.feature_ledger_prefix_head_sequence,
                    self.label_archive_verified_rows,
                    self.label_archive_prefix_head_sequence,
                    self.total_profiled_samples,
                    self.admitted_example_count,
                    self.label_unavailable_count,
                    self.ledger_exclusion_count,
                )
            )
            or self.feature_ledger_prefix_head_sequence > self.feature_ledger_verified_records
            or self.label_archive_prefix_head_sequence != self.label_archive_verified_rows
            or self.full_manifest_authentication_verified is not True
            or self.full_entry_inventory_verified is not True
            or any(value is not False for value in false_authority)
        ):
            _fail("PROFILED_OBSERVATION_AUTHENTICATED_MANIFEST_RESULT_INVALID")
        observation = _clock(
            self.observation_time,
            reason="PROFILED_OBSERVATION_AUTHENTICATED_CUTOFF_INVALID",
        )
        if self.retrospective_cutoff_at != self.observation_time or observation > _clock(
            self.factory_wall_clock_observed_at,
            reason="PROFILED_OBSERVATION_AUTHENTICATED_FACTORY_CLOCK_INVALID",
        ):
            _fail("PROFILED_OBSERVATION_AUTHENTICATED_CLOCK_ORDER_INVALID")


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledTrainingObservationInventoryPageV1:
    """Bounded authenticated entry inventory page without sample reopening."""

    manifest_id: str
    observation_time: str
    auth_key_id: str
    requested_after_ordinal: int
    page_start_ordinal: int
    page_end_ordinal: int
    scanned_entry_count: int
    admitted_entry_count: int
    label_unavailable_count: int
    page_start_previous_entry_chain_sha256: str
    page_end_entry_chain_sha256: str
    ordered_page_entries_sha256: str
    next_after_ordinal: int
    has_more_manifest_entries: bool
    manifest_summary_bound: bool
    page_authentication_verified: bool
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    optimizer_admission_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        false_authority = (
            self.external_monotonic_manifest_head_verified,
            self.full_consumption_external_ack_verified,
            self.optimizer_admission_authorized,
            self.checkpoint_write_authorized,
            self.model_write_authorized,
            self.prediction_authorized,
            self.paper_trading_authorized,
            self.live_execution_authorized,
            self.execution_authorized,
            self.runtime_wired,
        )
        if (
            self._construction_token is not _AUTHENTICATED_INVENTORY_PAGE_TOKEN
            or not _valid_sha256(self.manifest_id)
            or _AUTH_KEY_ID_RE.fullmatch(self.auth_key_id) is None
            or any(
                not _valid_sha256(value)
                for value in (
                    self.page_start_previous_entry_chain_sha256,
                    self.page_end_entry_chain_sha256,
                    self.ordered_page_entries_sha256,
                )
            )
            or self.requested_after_ordinal < 0
            or self.page_start_ordinal
            != (
                self.requested_after_ordinal + 1
                if self.scanned_entry_count
                else self.requested_after_ordinal
            )
            or self.page_end_ordinal
            != (
                self.requested_after_ordinal + self.scanned_entry_count
                if self.scanned_entry_count
                else self.requested_after_ordinal
            )
            or self.next_after_ordinal != self.page_end_ordinal
            or self.scanned_entry_count != self.admitted_entry_count + self.label_unavailable_count
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.scanned_entry_count,
                    self.admitted_entry_count,
                    self.label_unavailable_count,
                )
            )
            or type(self.has_more_manifest_entries) is not bool
            or self.manifest_summary_bound is not True
            or self.page_authentication_verified is not True
            or any(value is not False for value in false_authority)
        ):
            _fail("PROFILED_OBSERVATION_AUTHENTICATED_INVENTORY_PAGE_INVALID")
        _clock(
            self.observation_time,
            reason="PROFILED_OBSERVATION_AUTHENTICATED_PAGE_CUTOFF_INVALID",
        )


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationExampleV1:
    ordinal: int
    sample_identity_sha256: str
    label_binding_sha256: str
    tensor_binding_sha256: str
    training_example: TrainingExample
    optimizer_admission_authorized: bool
    checkpoint_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _EXAMPLE_TOKEN
            or self.ordinal <= 0
            or not all(
                _valid_sha256(value)
                for value in (
                    self.sample_identity_sha256,
                    self.label_binding_sha256,
                    self.tensor_binding_sha256,
                )
            )
            or any(
                value is not False
                for value in (
                    self.optimizer_admission_authorized,
                    self.checkpoint_write_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_OBSERVATION_EXAMPLE_RESULT_INVALID")


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationPageV1:
    manifest_id: str
    observation_time: str
    factory_wall_clock_observed_at: str
    requested_after_ordinal: int
    next_after_ordinal: int
    has_more_manifest_entries: bool
    scanned_entry_count: int
    label_unavailable_scanned: int
    examples: tuple[ProfiledTrainingObservationExampleV1, ...]
    checkpoint_write_authorized: bool
    external_monotonic_manifest_head_verified: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _PAGE_TOKEN
            or not _valid_sha256(self.manifest_id)
            or self.requested_after_ordinal < 0
            or self.next_after_ordinal < self.requested_after_ordinal
            or type(self.has_more_manifest_entries) is not bool
            or type(self.scanned_entry_count) is not int
            or self.scanned_entry_count < 0
            or type(self.label_unavailable_scanned) is not int
            or not 0 <= self.label_unavailable_scanned <= self.scanned_entry_count
            or len(self.examples) + self.label_unavailable_scanned != self.scanned_entry_count
            or self.runtime_wired is not False
            or tuple(item.ordinal for item in self.examples)
            != tuple(sorted(item.ordinal for item in self.examples))
            or self.checkpoint_write_authorized is not False
            or self.external_monotonic_manifest_head_verified is not False
        ):
            _fail("PROFILED_OBSERVATION_PAGE_RESULT_INVALID")
        if _clock(
            self.observation_time,
            reason="PROFILED_OBSERVATION_PAGE_CUTOFF_INVALID",
        ) > _clock(
            self.factory_wall_clock_observed_at,
            reason="PROFILED_OBSERVATION_PAGE_WALL_CLOCK_INVALID",
        ):
            _fail("PROFILED_OBSERVATION_PAGE_CLOCK_ORDER_INVALID")


def _cleanup_stale_manifest_temporaries_locked(output_root: Path) -> int:
    """Remove only verified orphan temp inodes while the build lock is held."""

    root_descriptor = -1
    try:
        root_descriptor = os.open(
            output_root,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened_root = os.fstat(root_descriptor)
        path_root = os.stat(output_root, follow_symlinks=False)
        if (
            not stat.S_ISDIR(opened_root.st_mode)
            or opened_root.st_uid != os.geteuid()
            or stat.S_IMODE(opened_root.st_mode) & 0o022
            or (opened_root.st_dev, opened_root.st_ino)
            != (path_root.st_dev, path_root.st_ino)
        ):
            _fail("PROFILED_OBSERVATION_STALE_TEMP_ROOT_PROTECTION_INVALID")
        candidates = sorted(
            (
                name
                for name in os.listdir(root_descriptor)
                if _MANIFEST_TEMP_FILENAME_RE.fullmatch(name) is not None
            ),
            # SQLite sidecars precede their base temp database.
            key=lambda name: (name.endswith(".tmp"), name),
        )
        removed = 0
        for name in candidates:
            path_stat = os.stat(
                name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(path_stat.st_mode)
                or path_stat.st_uid != os.geteuid()
                or path_stat.st_nlink != 1
                or stat.S_IMODE(path_stat.st_mode) != 0o600
            ):
                _fail("PROFILED_OBSERVATION_STALE_TEMP_PROTECTION_INVALID")
            candidate_descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_descriptor,
            )
            try:
                opened = os.fstat(candidate_descriptor)
            finally:
                os.close(candidate_descriptor)
            if (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_uid,
                opened.st_mode,
                opened.st_nlink,
            ) != (
                path_stat.st_dev,
                path_stat.st_ino,
                path_stat.st_size,
                path_stat.st_uid,
                path_stat.st_mode,
                path_stat.st_nlink,
            ):
                _fail("PROFILED_OBSERVATION_STALE_TEMP_INODE_MOVED")
            final_stat = os.stat(
                name,
                dir_fd=root_descriptor,
                follow_symlinks=False,
            )
            if (
                final_stat.st_dev,
                final_stat.st_ino,
                final_stat.st_size,
                final_stat.st_uid,
                final_stat.st_mode,
                final_stat.st_nlink,
            ) != (
                path_stat.st_dev,
                path_stat.st_ino,
                path_stat.st_size,
                path_stat.st_uid,
                path_stat.st_mode,
                path_stat.st_nlink,
            ):
                _fail("PROFILED_OBSERVATION_STALE_TEMP_INODE_MOVED")
            os.unlink(name, dir_fd=root_descriptor)
            removed += 1
        if removed:
            os.fsync(root_descriptor)
        return removed
    except ProfiledTrainingObservationManifestV1Error:
        raise
    except OSError as exc:
        raise ProfiledTrainingObservationManifestV1Error(
            f"PROFILED_OBSERVATION_STALE_TEMP_CLEANUP_FAILED:{type(exc).__name__}"
        ) from exc
    finally:
        if root_descriptor >= 0:
            os.close(root_descriptor)


def build_profiled_training_observation_manifest_v1(
    *,
    ledger: DurableFeatureSnapshotLedger,
    trusted_immutable_cost_store_root: Path,
    label_archive: DurableCanonical5mLabelArchive,
    manifest_root: Path,
    training_observed_at: str,
    auth_key_id: str,
    hmac_key: bytes | bytearray | memoryview,
    scan_limit: int = MAX_PROFILED_TRAINING_SCAN_ROWS,
    prepared_factory_wall_clock_observed_at: str | None = None,
) -> ProfiledTrainingObservationManifestBuildV1:
    """Build one immutable manifest with bounded-memory source consumption.

    ``prepared_factory_wall_clock_observed_at`` is an optional crash-recovery
    input. A coordinator may durably record one wall-clock value before
    construction and replay that exact value after a crash. Ordinary callers
    leave it unset and retain the original direct wall-clock sampling behavior.
    """

    key = _validated_key(hmac_key)
    cost_root = _exact_absolute_path(
        trusted_immutable_cost_store_root,
        reason="PROFILED_OBSERVATION_COST_STORE_ROOT_INVALID",
    )
    output_root = _exact_absolute_path(
        manifest_root,
        reason="PROFILED_OBSERVATION_MANIFEST_ROOT_INVALID",
    )
    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_OBSERVATION_LEDGER_EXACT_TYPE_REQUIRED")
    if type(label_archive) is not DurableCanonical5mLabelArchive:
        _fail("PROFILED_OBSERVATION_LABEL_ARCHIVE_EXACT_TYPE_REQUIRED")
    if type(auth_key_id) is not str or _AUTH_KEY_ID_RE.fullmatch(auth_key_id) is None:
        _fail("PROFILED_OBSERVATION_AUTH_KEY_ID_INVALID")
    if type(scan_limit) is not int or not 0 < scan_limit <= MAX_PROFILED_TRAINING_SCAN_ROWS:
        _fail("PROFILED_OBSERVATION_SCAN_LIMIT_INVALID")
    observation = _clock(
        training_observed_at,
        reason="PROFILED_OBSERVATION_CLOCK_INVALID",
    )
    observation_text = _canonical_clock(observation)
    if prepared_factory_wall_clock_observed_at is None:
        factory_clock_raw = _factory_wall_clock_now()
        if (
            type(factory_clock_raw) is not datetime
            or factory_clock_raw.tzinfo is None
            or factory_clock_raw.utcoffset() is None
        ):
            _fail("PROFILED_OBSERVATION_FACTORY_WALL_CLOCK_INVALID")
        factory_clock_text = _canonical_clock(factory_clock_raw)
    else:
        if type(prepared_factory_wall_clock_observed_at) is not str:
            _fail("PROFILED_OBSERVATION_PREPARED_FACTORY_WALL_CLOCK_INVALID")
        prepared_factory_clock = _clock(
            prepared_factory_wall_clock_observed_at,
            reason="PROFILED_OBSERVATION_PREPARED_FACTORY_WALL_CLOCK_INVALID",
        )
        factory_clock_text = _canonical_clock(prepared_factory_clock)
    factory_clock = _clock(
        factory_clock_text,
        reason="PROFILED_OBSERVATION_FACTORY_WALL_CLOCK_INVALID",
    )
    if observation > factory_clock:
        _fail("PROFILED_OBSERVATION_RETROSPECTIVE_CUTOFF_AFTER_FACTORY_WALL_CLOCK")
    try:
        label_integrity = label_archive.verify_integrity()
    except Canonical5mArchiveError as exc:
        raise ProfiledTrainingObservationManifestV1Error(
            f"PROFILED_OBSERVATION_SOURCE_VERIFICATION_FAILED:{type(exc).__name__}:{exc}"
        ) from exc
    if label_integrity.get("archive_integrity_verified") is not True:
        _fail("PROFILED_OBSERVATION_LABEL_ARCHIVE_INTEGRITY_UNVERIFIED")
    try:
        label_high_water = label_archive_fixed_observation_high_water(
            archive=label_archive,
            integrity=label_integrity,
            observation_cutoff=observation,
            scan_limit=max(
                int(label_integrity.get("verified_rows") or 0),
                int(label_integrity.get("verified_append_receipts") or 0),
                1,
            ),
        )
    except Exception as exc:
        raise ProfiledTrainingObservationManifestV1Error(
            f"PROFILED_OBSERVATION_LABEL_HIGH_WATER_FAILED:{type(exc).__name__}"
        ) from exc

    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = output_root / ".profiled_training_observation_manifest_v1.lock"
    lock_descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    temporary = output_root / (
        f".profiled_training_observation.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    manifest_path: Path | None = None
    manifest_id: str | None = None
    admitted = 0
    unavailable = 0
    ordinal = 0
    previous_chain = PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
    context: dict[str, Any] | None = None
    observation_context_sha256: str | None = None
    entry_identity_digest = _OrderedCanonicalStreamDigest(
        domain=PROFILED_OBSERVATION_ENTRY_IDENTITY_DIGEST_DOMAIN
    )
    exclusion_digest = _OrderedCanonicalStreamDigest(
        domain=PROFILED_OBSERVATION_EXCLUSION_DIGEST_DOMAIN
    )
    try:
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
        _cleanup_stale_manifest_temporaries_locked(output_root)
        descriptor = os.open(
            temporary,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.close(descriptor)
        connection = sqlite3.connect(temporary, timeout=60.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            for statement in _DDL_STATEMENTS:
                connection.execute(statement)
            connection.execute("BEGIN IMMEDIATE")

            def bind_observation(high_water: Mapping[str, Any]) -> None:
                nonlocal context, observation_context_sha256
                if context is not None:
                    _fail("PROFILED_OBSERVATION_HIGH_WATER_CONSUMER_REENTERED")
                adapter_contract = _training_example_adapter_contract()
                context = {
                    "schema_version": PROFILED_OBSERVATION_CONTEXT_V1_SCHEMA_VERSION,
                    "observation_time": observation_text,
                    "retrospective_cutoff_at": observation_text,
                    "factory_wall_clock_observed_at": factory_clock_text,
                    "receipt_visibility_semantics": ("STRICTLY_BEFORE_RETROSPECTIVE_CUTOFF"),
                    "feature_ledger_path": str(ledger.path),
                    "feature_ledger_path_sha256": _path_sha256(ledger.path),
                    "feature_ledger_high_water": dict(high_water),
                    "feature_ledger_high_water_sha256": high_water.get("high_water_sha256"),
                    "label_archive_path": str(label_archive.path),
                    "label_archive_path_sha256": _path_sha256(label_archive.path),
                    "label_archive_high_water": label_high_water,
                    "label_archive_high_water_sha256": label_high_water.get("high_water_sha256"),
                    "trusted_cost_store_root": str(cost_root),
                    "trusted_cost_store_root_sha256": _path_sha256(cost_root),
                    "physical_model_feature_count": PHYSICAL_MODEL_FEATURE_COUNT,
                    "physical_enriched_feature_count": len(
                        PROFILED_TRAINING_PHYSICAL_ORDERED_FEATURE_NAMES
                    ),
                    "logical_model_feature_count": LOGICAL_MODEL_FEATURE_COUNT,
                    "logical_model_input_count": LOGICAL_MODEL_INPUT_COUNT,
                    "feature_registry_sha256": FEATURE_SOURCE_REGISTRY_V4_SHA256,
                    "feature_registry_abi_sha256": FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
                    "projection_schema_version": (PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION),
                    "projection_implementation_sha256": (
                        PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
                    ),
                    "projection_configuration_sha256": (
                        PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256
                    ),
                    "training_example_adapter_contract": adapter_contract,
                    "training_example_adapter_contract_sha256": stable_sha256(adapter_contract),
                }
                observation_context_sha256 = stable_sha256(context)

            def consume_page(
                samples: tuple[ProfiledTrainingLedgerSampleV1, ...],
                exclusions: tuple[Any, ...],
            ) -> None:
                nonlocal admitted, unavailable, ordinal, previous_chain
                if context is None or not _valid_sha256(observation_context_sha256):
                    _fail("PROFILED_OBSERVATION_CONTEXT_NOT_BOUND_BEFORE_PAGE")
                for exclusion in exclusions:
                    exclusion_digest.append(
                        {
                            "sequence": exclusion.sequence,
                            "durable_snapshot_id": exclusion.durable_snapshot_id,
                            "reason": exclusion.reason,
                        }
                    )
                for sample in samples:
                    ordinal += 1
                    label_binding, label_reasons = _label_binding(
                        sample=sample,
                        archive=label_archive,
                        archive_integrity=label_integrity,
                        archive_high_water=label_high_water,
                        observation=observation,
                    )
                    entry = _entry_material(
                        ordinal=ordinal,
                        sample=sample,
                        observation_context_sha256=cast(
                            str,
                            observation_context_sha256,
                        ),
                        label_binding=label_binding,
                        label_rejection_reasons=label_reasons,
                    )
                    entry_json = _canonical_json(
                        entry,
                        reason="PROFILED_OBSERVATION_ENTRY_JSON_INVALID",
                        maximum_bytes=MAX_PROFILED_OBSERVATION_ENTRY_BYTES,
                    )
                    entry_sha256 = hashlib.sha256(entry_json.encode("ascii")).hexdigest()
                    chain = _entry_chain(previous_chain, entry_sha256)
                    sample_binding = cast(dict[str, Any], entry["sample_binding"])
                    connection.execute(
                        "INSERT INTO observation_manifest_entries("
                        "ordinal, ledger_sequence, durable_snapshot_id, label_status, "
                        "observation_context_sha256, entry_json, entry_sha256, "
                        "previous_entry_chain_sha256, entry_chain_sha256, auth_tag"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            ordinal,
                            sample_binding["ledger_sequence"],
                            sample_binding["durable_snapshot_id"],
                            entry["label_status"],
                            observation_context_sha256,
                            entry_json,
                            entry_sha256,
                            previous_chain,
                            chain,
                            _auth_tag(
                                role=b"entry-row",
                                payload=_entry_row_auth_payload(
                                    ordinal=ordinal,
                                    ledger_sequence=sample_binding["ledger_sequence"],
                                    durable_snapshot_id=sample_binding["durable_snapshot_id"],
                                    label_status=entry["label_status"],
                                    observation_context_sha256=(observation_context_sha256),
                                    entry_sha256=entry_sha256,
                                    previous_entry_chain_sha256=previous_chain,
                                    entry_chain_sha256=chain,
                                ),
                                key=key,
                            ),
                        ),
                    )
                    entry_identity_digest.append(
                        {
                            "ordinal": ordinal,
                            "ledger_sequence": sample_binding["ledger_sequence"],
                            "sample_identity_sha256": sample_binding["sample_identity_sha256"],
                            "label_status": entry["label_status"],
                            "entry_sha256": entry_sha256,
                            "entry_chain_sha256": chain,
                        }
                    )
                    previous_chain = chain
                    if label_binding is None:
                        unavailable += 1
                    else:
                        admitted += 1

            try:
                scan = load_profiled_training_ledger_fixed_observation_v1(
                    ledger=ledger,
                    trusted_immutable_cost_store_root=cost_root,
                    training_observed_at=observation_text,
                    page_size=scan_limit,
                    observation_consumer=bind_observation,
                    page_consumer=consume_page,
                )
            except ProfiledTrainingLedgerLoaderV1Error as exc:
                raise ProfiledTrainingObservationManifestV1Error(
                    "PROFILED_OBSERVATION_SOURCE_VERIFICATION_FAILED:" f"{type(exc).__name__}:{exc}"
                ) from exc
            if (
                context is None
                or not _valid_sha256(observation_context_sha256)
                or scan.admitted_sample_count != ordinal
                or scan.exclusion_count != exclusion_digest.count
                or entry_identity_digest.count != ordinal
                or admitted + unavailable != ordinal
            ):
                _fail("PROFILED_OBSERVATION_STREAMING_SCAN_ACCOUNTING_INVALID")
            try:
                completion_integrity = label_archive.verify_integrity()
                completion_high_water = label_archive_fixed_observation_high_water(
                    archive=label_archive,
                    integrity=completion_integrity,
                    observation_cutoff=observation,
                    scan_limit=max(
                        int(completion_integrity.get("verified_rows") or 0),
                        int(completion_integrity.get("verified_append_receipts") or 0),
                        1,
                    ),
                )
            except Exception as exc:
                raise ProfiledTrainingObservationManifestV1Error(
                    "PROFILED_OBSERVATION_LABEL_COMPLETION_PROOF_FAILED:" f"{type(exc).__name__}"
                ) from exc
            if completion_high_water != label_high_water:
                _fail("PROFILED_OBSERVATION_LABEL_HIGH_WATER_MOVED_DURING_BUILD")
            metadata_without_id = {
                "schema_version": PROFILED_OBSERVATION_MANIFEST_V1_SCHEMA_VERSION,
                "schema_identity_sha256": _SCHEMA_IDENTITY_SHA256,
                "observation_context": context,
                "observation_context_sha256": observation_context_sha256,
                "observation_time": observation_text,
                "retrospective_cutoff_at": observation_text,
                "factory_wall_clock_observed_at": factory_clock_text,
                "total_profiled_samples": ordinal,
                "admitted_example_count": admitted,
                "label_unavailable_count": unavailable,
                "ledger_exclusion_count": exclusion_digest.count,
                "ledger_exclusion_inventory_sha256": exclusion_digest.hexdigest(),
                "ordered_entry_identities_sha256": entry_identity_digest.hexdigest(),
                "ordered_digest_schema_version": (
                    PROFILED_OBSERVATION_ORDERED_DIGEST_SCHEMA_VERSION
                ),
                "ordered_digest_algorithm": (PROFILED_OBSERVATION_ORDERED_DIGEST_ALGORITHM),
                "ordered_entry_identity_digest_domain": (
                    PROFILED_OBSERVATION_ENTRY_IDENTITY_DIGEST_DOMAIN
                ),
                "ordered_entry_identity_count": entry_identity_digest.count,
                "ordered_ledger_exclusion_digest_domain": (
                    PROFILED_OBSERVATION_EXCLUSION_DIGEST_DOMAIN
                ),
                "ordered_ledger_exclusion_count": exclusion_digest.count,
                "entry_chain_genesis_sha256": PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS,
                "entry_chain_head_sha256": previous_chain,
                "source_page_size": scan.source_page_size,
                "maximum_resident_source_page_rows": (scan.maximum_resident_page_row_count),
                "maximum_resident_entry_rows": 1 if ordinal else 0,
                "factory_memory_semantics": (
                    "KEYSET_SOURCE_PAGE_PLUS_ONE_ENTRY_NO_FULL_SAMPLE_OR_ENTRY_INVENTORY"
                ),
                "auth_algorithm": PROFILED_OBSERVATION_AUTH_ALGORITHM,
                "auth_domain": PROFILED_OBSERVATION_AUTH_DOMAIN,
                "auth_key_id": auth_key_id,
                "runtime_status": PROFILED_OBSERVATION_RUNTIME_STATUS,
                "external_monotonic_manifest_head_verified": False,
                "bounded_runtime_reopen": True,
                "full_ledger_scan_required_on_runtime_reopen": False,
                "label_archive_reopen_required_on_runtime_reopen": False,
                "training_example_adapter_available": admitted > 0,
                "optimizer_admission_authorized": False,
                "checkpoint_write_authorized": False,
                "prediction_authorized": False,
                "paper_trading_authorized": False,
                "live_execution_authorized": False,
                "runtime_wired": False,
            }
            manifest_id = stable_sha256(metadata_without_id)
            metadata = {**metadata_without_id, "manifest_id": manifest_id}
            metadata_json = _canonical_json(
                metadata,
                reason="PROFILED_OBSERVATION_METADATA_JSON_INVALID",
                maximum_bytes=MAX_PROFILED_OBSERVATION_METADATA_BYTES,
            )
            connection.execute(
                "INSERT INTO observation_manifest_metadata("
                "singleton, manifest_id, metadata_json, metadata_sha256, auth_tag"
                ") VALUES (1, ?, ?, ?, ?)",
                (
                    manifest_id,
                    metadata_json,
                    hashlib.sha256(metadata_json.encode("ascii")).hexdigest(),
                    _auth_tag(role=b"metadata", payload=metadata_json, key=key),
                ),
            )
            connection.commit()
            _validate_schema(connection)
        finally:
            connection.close()
        file_descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(file_descriptor)
        finally:
            os.close(file_descriptor)
        if manifest_id is None:
            _fail("PROFILED_OBSERVATION_MANIFEST_ID_NOT_FINALIZED")
        manifest_path = output_root / (f"profiled_training_observation_{manifest_id}.sqlite3")
        if manifest_path.exists():
            existing, existing_metadata = _read_metadata(
                manifest_path,
                key=key,
                expected_auth_key_id=auth_key_id,
                full_database_check=True,
            )
            try:
                if existing_metadata != metadata:
                    _fail("PROFILED_OBSERVATION_CONTENT_ADDRESS_CONFLICT")
                _verify_complete_entry_stream(
                    existing,
                    metadata=existing_metadata,
                    key=key,
                )
            finally:
                existing.rollback()
                existing.close()
        else:
            os.replace(temporary, manifest_path)
            directory_descriptor = os.open(
                output_root,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
            readback, readback_metadata = _read_metadata(
                manifest_path,
                key=key,
                expected_auth_key_id=auth_key_id,
                full_database_check=True,
            )
            try:
                if readback_metadata != metadata:
                    _fail("PROFILED_OBSERVATION_POSTCOMMIT_READBACK_MISMATCH")
                _verify_complete_entry_stream(
                    readback,
                    metadata=readback_metadata,
                    key=key,
                )
            finally:
                readback.rollback()
                readback.close()
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        os.close(lock_descriptor)
    if manifest_path is None or manifest_id is None:
        _fail("PROFILED_OBSERVATION_MANIFEST_FINALIZATION_INVALID")
    return ProfiledTrainingObservationManifestBuildV1(
        manifest_path=manifest_path,
        manifest_id=manifest_id,
        observation_time=observation_text,
        factory_wall_clock_observed_at=factory_clock_text,
        total_profiled_samples=ordinal,
        admitted_examples=admitted,
        label_unavailable_samples=unavailable,
        ledger_exclusions=exclusion_digest.count,
        checkpoint_write_authorized=False,
        runtime_wired=False,
        _construction_token=_BUILD_TOKEN,
    )


def _open_promotion_manifest_descriptor(path: Path) -> tuple[int, os.stat_result]:
    """Open one exact private manifest inode for promotion-grade authentication."""

    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        opened = os.fstat(descriptor)
        path_stat = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ProfiledTrainingObservationManifestV1Error(
            f"PROFILED_OBSERVATION_PROMOTION_PATH_OPEN_FAILED:{type(exc).__name__}"
        ) from exc
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_uid != os.geteuid()
        or opened.st_nlink != 1
        or stat.S_IMODE(opened.st_mode) != 0o600
        or (opened.st_dev, opened.st_ino, opened.st_size)
        != (path_stat.st_dev, path_stat.st_ino, path_stat.st_size)
    ):
        os.close(descriptor)
        _fail("PROFILED_OBSERVATION_PROMOTION_PATH_PROTECTION_INVALID")
    return descriptor, opened


def _require_authenticated_high_water(
    raw: object,
    *,
    expected_path: object,
    expected_path_sha256: object,
    kind: str,
) -> dict[str, Any]:
    if (
        type(raw) is not dict
        or type(expected_path) is not str
        or not expected_path
        or type(expected_path_sha256) is not str
    ):
        _fail(f"PROFILED_OBSERVATION_{kind}_HIGH_WATER_INVALID")
    high_water = cast(dict[str, Any], raw)
    unsigned = {name: value for name, value in high_water.items() if name != "high_water_sha256"}
    if (
        high_water.get("high_water_sha256") != stable_sha256(unsigned)
        or expected_path
        != high_water.get("ledger_path" if kind == "FEATURE_LEDGER" else "archive_path")
        or expected_path_sha256 != _path_sha256(Path(cast(str, expected_path)))
        or high_water.get("fixed_observation_prefix_only") is not True
        or high_water.get("later_valid_append_suffix_ignored") is not True
        or high_water.get(
            "full_ledger_integrity_verified_at_reproduction"
            if kind == "FEATURE_LEDGER"
            else "full_archive_integrity_verified_at_reproduction"
        )
        is not True
        or high_water.get("receipt_backed") is not True
        or high_water.get("postcommit_readback_verified") is not True
        or not _valid_sha256(high_water.get("archive_chain_sha256"))
        or not _valid_sha256(high_water.get("ordered_transaction_receipts_sha256"))
    ):
        _fail(f"PROFILED_OBSERVATION_{kind}_HIGH_WATER_INVALID")
    return high_water


def authenticate_profiled_training_observation_manifest_v1(
    *,
    manifest_path: Path,
    hmac_key: bytes | bytearray | memoryview,
    expected_auth_key_id: str,
    expected_manifest_id: str,
    expected_observation_time: str,
) -> AuthenticatedProfiledTrainingObservationManifestV1:
    """Fully authenticate one immutable manifest and return scalar bindings.

    The complete entry stream is checked in bounded pages.  The returned object
    is suitable input to a local head *candidate*, not evidence of an external
    monotonic append.
    """

    key = _validated_key(hmac_key)
    path = _exact_absolute_path(
        manifest_path,
        reason="PROFILED_OBSERVATION_MANIFEST_PATH_INVALID",
    )
    if (
        type(expected_auth_key_id) is not str
        or _AUTH_KEY_ID_RE.fullmatch(expected_auth_key_id) is None
    ):
        _fail("PROFILED_OBSERVATION_AUTH_KEY_ID_INVALID")
    if not _valid_sha256(expected_manifest_id):
        _fail("PROFILED_OBSERVATION_EXPECTED_MANIFEST_ID_INVALID")
    expected_observation = _canonical_clock(
        _clock(
            expected_observation_time,
            reason="PROFILED_OBSERVATION_EXPECTED_CUTOFF_INVALID",
        )
    )
    descriptor, opened = _open_promotion_manifest_descriptor(path)
    connection: sqlite3.Connection | None = None
    try:
        connection, metadata = _read_metadata(
            path,
            key=key,
            expected_auth_key_id=expected_auth_key_id,
            full_database_check=True,
        )
        if (
            metadata.get("manifest_id") != expected_manifest_id
            or metadata.get("observation_time") != expected_observation
        ):
            _fail("PROFILED_OBSERVATION_EXPECTED_MANIFEST_BINDING_MISMATCH")
        metadata_row = connection.execute(
            "SELECT metadata_sha256, auth_tag FROM observation_manifest_metadata "
            "WHERE singleton = 1"
        ).fetchone()
        if metadata_row is None:
            _fail("PROFILED_OBSERVATION_METADATA_MISSING")
        _verify_complete_entry_stream(connection, metadata=metadata, key=key)
        context = metadata.get("observation_context")
        if type(context) is not dict:
            _fail("PROFILED_OBSERVATION_AUTHENTICATED_CONTEXT_INVALID")
        feature_high_water = _require_authenticated_high_water(
            context.get("feature_ledger_high_water"),
            expected_path=context.get("feature_ledger_path"),
            expected_path_sha256=context.get("feature_ledger_path_sha256"),
            kind="FEATURE_LEDGER",
        )
        label_high_water = _require_authenticated_high_water(
            context.get("label_archive_high_water"),
            expected_path=context.get("label_archive_path"),
            expected_path_sha256=context.get("label_archive_path_sha256"),
            kind="LABEL_ARCHIVE",
        )
        feature_records = feature_high_water.get("verified_records")
        feature_head = feature_high_water.get("authenticated_prefix_head_sequence")
        label_rows = label_high_water.get("verified_rows")
        label_head = label_high_water.get("verified_max_sequence")
        if (
            type(feature_records) is not int
            or feature_records < 0
            or type(feature_head) is not int
            or not 0 <= feature_head <= feature_records
            or type(label_rows) is not int
            or label_rows < 0
            or type(label_head) is not int
            or label_head != label_rows
            or feature_high_water.get("training_observed_at") != metadata.get("observation_time")
            or label_high_water.get("training_observed_at") != metadata.get("observation_time")
        ):
            _fail("PROFILED_OBSERVATION_AUTHENTICATED_HIGH_WATER_COUNTS_INVALID")
        connection.rollback()
        connection.close()
        connection = None
        final_descriptor_stat = os.fstat(descriptor)
        final_path_stat = os.stat(path, follow_symlinks=False)
        stable_identity = (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_uid,
            opened.st_mode,
            opened.st_nlink,
            opened.st_mtime_ns,
            opened.st_ctime_ns,
        )
        if stable_identity != (
            final_descriptor_stat.st_dev,
            final_descriptor_stat.st_ino,
            final_descriptor_stat.st_size,
            final_descriptor_stat.st_uid,
            final_descriptor_stat.st_mode,
            final_descriptor_stat.st_nlink,
            final_descriptor_stat.st_mtime_ns,
            final_descriptor_stat.st_ctime_ns,
        ) or stable_identity != (
            final_path_stat.st_dev,
            final_path_stat.st_ino,
            final_path_stat.st_size,
            final_path_stat.st_uid,
            final_path_stat.st_mode,
            final_path_stat.st_nlink,
            final_path_stat.st_mtime_ns,
            final_path_stat.st_ctime_ns,
        ):
            _fail("PROFILED_OBSERVATION_PROMOTION_PATH_INODE_MOVED")
    except OSError as exc:
        raise ProfiledTrainingObservationManifestV1Error(
            f"PROFILED_OBSERVATION_PROMOTION_PATH_RECHECK_FAILED:{type(exc).__name__}"
        ) from exc
    finally:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        os.close(descriptor)
    return AuthenticatedProfiledTrainingObservationManifestV1(
        manifest_path=path,
        manifest_file_device=int(opened.st_dev),
        manifest_file_inode=int(opened.st_ino),
        manifest_file_byte_count=int(opened.st_size),
        manifest_id=cast(str, metadata["manifest_id"]),
        metadata_sha256=str(metadata_row["metadata_sha256"]),
        metadata_auth_tag=str(metadata_row["auth_tag"]),
        observation_time=cast(str, metadata["observation_time"]),
        retrospective_cutoff_at=cast(str, metadata["retrospective_cutoff_at"]),
        factory_wall_clock_observed_at=cast(str, metadata["factory_wall_clock_observed_at"]),
        auth_algorithm=cast(str, metadata["auth_algorithm"]),
        auth_domain=cast(str, metadata["auth_domain"]),
        auth_key_id=cast(str, metadata["auth_key_id"]),
        observation_context_sha256=cast(str, metadata["observation_context_sha256"]),
        feature_ledger_path=cast(str, context["feature_ledger_path"]),
        feature_ledger_path_sha256=cast(str, context["feature_ledger_path_sha256"]),
        feature_ledger_high_water_sha256=cast(str, feature_high_water["high_water_sha256"]),
        feature_ledger_verified_records=cast(int, feature_high_water["verified_records"]),
        feature_ledger_prefix_head_sequence=cast(
            int, feature_high_water["authenticated_prefix_head_sequence"]
        ),
        feature_ledger_archive_chain_sha256=cast(str, feature_high_water["archive_chain_sha256"]),
        feature_ledger_ordered_receipts_sha256=cast(
            str, feature_high_water["ordered_transaction_receipts_sha256"]
        ),
        label_archive_path=cast(str, context["label_archive_path"]),
        label_archive_path_sha256=cast(str, context["label_archive_path_sha256"]),
        label_archive_high_water_sha256=cast(str, label_high_water["high_water_sha256"]),
        label_archive_verified_rows=cast(int, label_high_water["verified_rows"]),
        label_archive_prefix_head_sequence=cast(int, label_high_water["verified_max_sequence"]),
        label_archive_archive_chain_sha256=cast(str, label_high_water["archive_chain_sha256"]),
        label_archive_ordered_receipts_sha256=cast(
            str, label_high_water["ordered_transaction_receipts_sha256"]
        ),
        entry_chain_genesis_sha256=cast(str, metadata["entry_chain_genesis_sha256"]),
        entry_chain_head_sha256=cast(str, metadata["entry_chain_head_sha256"]),
        ordered_entry_identities_sha256=cast(str, metadata["ordered_entry_identities_sha256"]),
        total_profiled_samples=cast(int, metadata["total_profiled_samples"]),
        admitted_example_count=cast(int, metadata["admitted_example_count"]),
        label_unavailable_count=cast(int, metadata["label_unavailable_count"]),
        ledger_exclusion_count=cast(int, metadata["ledger_exclusion_count"]),
        ledger_exclusion_inventory_sha256=cast(str, metadata["ledger_exclusion_inventory_sha256"]),
        full_manifest_authentication_verified=True,
        full_entry_inventory_verified=True,
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _authenticated_manifest_key_sha256=hashlib.sha256(key).hexdigest(),
        _construction_token=_AUTHENTICATED_MANIFEST_TOKEN,
    )


def authenticate_profiled_training_observation_inventory_page_v1(
    *,
    authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    hmac_key: bytes | bytearray | memoryview,
    after_ordinal: int = 0,
    limit: int = MAX_PROFILED_OBSERVATION_PAGE_ROWS,
) -> AuthenticatedProfiledTrainingObservationInventoryPageV1:
    """Authenticate one bounded inventory page against a full-auth summary."""

    if (
        type(authenticated_manifest) is not AuthenticatedProfiledTrainingObservationManifestV1
        or authenticated_manifest._construction_token is not _AUTHENTICATED_MANIFEST_TOKEN
    ):
        _fail("PROFILED_OBSERVATION_AUTHENTICATED_MANIFEST_EXACT_TYPE_REQUIRED")
    key = _validated_key(hmac_key)
    if hashlib.sha256(key).hexdigest() != (
        authenticated_manifest._authenticated_manifest_key_sha256
    ):
        _fail("PROFILED_OBSERVATION_AUTHENTICATED_MANIFEST_KEY_MISMATCH")
    if type(after_ordinal) is not int or after_ordinal < 0:
        _fail("PROFILED_OBSERVATION_AFTER_ORDINAL_INVALID")
    if type(limit) is not int or not 0 < limit <= MAX_PROFILED_OBSERVATION_PAGE_ROWS:
        _fail("PROFILED_OBSERVATION_PAGE_LIMIT_INVALID")
    if after_ordinal > authenticated_manifest.total_profiled_samples:
        _fail("PROFILED_OBSERVATION_AFTER_ORDINAL_OUTSIDE_MANIFEST")
    descriptor, opened = _open_promotion_manifest_descriptor(authenticated_manifest.manifest_path)
    connection: sqlite3.Connection | None = None
    try:
        if (
            int(opened.st_dev) != authenticated_manifest.manifest_file_device
            or int(opened.st_ino) != authenticated_manifest.manifest_file_inode
            or int(opened.st_size) != authenticated_manifest.manifest_file_byte_count
        ):
            _fail("PROFILED_OBSERVATION_AUTHENTICATED_MANIFEST_INODE_MISMATCH")
        connection, metadata = _read_metadata(
            authenticated_manifest.manifest_path,
            key=key,
            expected_auth_key_id=authenticated_manifest.auth_key_id,
            full_database_check=False,
        )
        if (
            metadata.get("manifest_id") != authenticated_manifest.manifest_id
            or metadata.get("observation_time") != authenticated_manifest.observation_time
            or metadata.get("entry_chain_head_sha256")
            != authenticated_manifest.entry_chain_head_sha256
            or metadata.get("ordered_entry_identities_sha256")
            != authenticated_manifest.ordered_entry_identities_sha256
            or metadata.get("total_profiled_samples")
            != authenticated_manifest.total_profiled_samples
        ):
            _fail("PROFILED_OBSERVATION_PAGE_MANIFEST_SUMMARY_MISMATCH")
        context_sha256 = cast(str, metadata["observation_context_sha256"])
        if after_ordinal == 0:
            previous_chain = PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
        else:
            anchor = connection.execute(
                "SELECT ordinal, ledger_sequence, durable_snapshot_id, label_status, "
                "observation_context_sha256, entry_json, entry_sha256, "
                "previous_entry_chain_sha256, entry_chain_sha256, auth_tag "
                "FROM observation_manifest_entries WHERE ordinal = ?",
                (after_ordinal,),
            ).fetchone()
            if anchor is None:
                _fail("PROFILED_OBSERVATION_CURSOR_ANCHOR_MISSING")
            _verify_entry_row(
                anchor,
                key=key,
                observation_context_sha256=context_sha256,
            )
            previous_chain = str(anchor["entry_chain_sha256"])
        page_start_previous_chain = previous_chain
        rows = list(
            connection.execute(
                "SELECT ordinal, ledger_sequence, durable_snapshot_id, label_status, "
                "observation_context_sha256, entry_json, entry_sha256, "
                "previous_entry_chain_sha256, entry_chain_sha256, auth_tag "
                "FROM observation_manifest_entries WHERE ordinal > ? "
                "ORDER BY ordinal ASC LIMIT ?",
                (after_ordinal, limit),
            )
        )
        expected_count = min(
            limit,
            authenticated_manifest.total_profiled_samples - after_ordinal,
        )
        if len(rows) != expected_count:
            _fail("PROFILED_OBSERVATION_ENTRY_INVENTORY_OMISSION")
        digest = _OrderedCanonicalStreamDigest(domain=PROFILED_OBSERVATION_PAGE_ENTRY_DIGEST_DOMAIN)
        admitted = 0
        unavailable = 0
        for expected_ordinal, row in enumerate(rows, start=after_ordinal + 1):
            if row["ordinal"] != expected_ordinal:
                _fail("PROFILED_OBSERVATION_ENTRY_ORDINAL_GAP")
            entry = _verify_entry_row(
                row,
                key=key,
                observation_context_sha256=context_sha256,
                expected_previous_chain=previous_chain,
            )
            sample_binding = cast(dict[str, Any], entry["sample_binding"])
            digest.append(
                {
                    "ordinal": expected_ordinal,
                    "ledger_sequence": row["ledger_sequence"],
                    "durable_snapshot_id": row["durable_snapshot_id"],
                    "sample_identity_sha256": sample_binding["sample_identity_sha256"],
                    "label_status": row["label_status"],
                    "entry_sha256": row["entry_sha256"],
                    "previous_entry_chain_sha256": row["previous_entry_chain_sha256"],
                    "entry_chain_sha256": row["entry_chain_sha256"],
                }
            )
            previous_chain = str(row["entry_chain_sha256"])
            if row["label_status"] == PROFILED_OBSERVATION_LABEL_STATUS_ADMITTED:
                admitted += 1
            else:
                unavailable += 1
        next_after = int(rows[-1]["ordinal"]) if rows else after_ordinal
        has_more = next_after < authenticated_manifest.total_profiled_samples
        if not has_more and previous_chain != authenticated_manifest.entry_chain_head_sha256:
            _fail("PROFILED_OBSERVATION_ENTRY_CHAIN_HEAD_MISMATCH")
        connection.rollback()
        connection.close()
        connection = None
        final_stat = os.stat(
            authenticated_manifest.manifest_path,
            follow_symlinks=False,
        )
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
        ) != (final_stat.st_dev, final_stat.st_ino, final_stat.st_size):
            _fail("PROFILED_OBSERVATION_PROMOTION_PATH_INODE_MOVED")
    finally:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        os.close(descriptor)
    return AuthenticatedProfiledTrainingObservationInventoryPageV1(
        manifest_id=authenticated_manifest.manifest_id,
        observation_time=authenticated_manifest.observation_time,
        auth_key_id=authenticated_manifest.auth_key_id,
        requested_after_ordinal=after_ordinal,
        page_start_ordinal=after_ordinal + 1 if rows else after_ordinal,
        page_end_ordinal=next_after,
        scanned_entry_count=len(rows),
        admitted_entry_count=admitted,
        label_unavailable_count=unavailable,
        page_start_previous_entry_chain_sha256=page_start_previous_chain,
        page_end_entry_chain_sha256=previous_chain,
        ordered_page_entries_sha256=digest.hexdigest(),
        next_after_ordinal=next_after,
        has_more_manifest_entries=has_more,
        manifest_summary_bound=True,
        page_authentication_verified=True,
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _construction_token=_AUTHENTICATED_INVENTORY_PAGE_TOKEN,
    )


def _example_from_authenticated_entry(
    *,
    entry: Mapping[str, Any],
    sample: ProfiledTrainingLedgerSampleV1,
) -> ProfiledTrainingObservationExampleV1:
    sample_binding = cast(dict[str, Any], entry["sample_binding"])
    label = entry.get("label_binding")
    tensor_binding = entry.get("tensor_binding")
    if (
        entry.get("label_status") != PROFILED_OBSERVATION_LABEL_STATUS_ADMITTED
        or type(label) is not dict
        or type(tensor_binding) is not dict
        or entry.get("training_example_adapter_available") is not True
    ):
        _fail("PROFILED_OBSERVATION_ADMITTED_ENTRY_BINDING_INVALID")
    label_unsigned = {key: value for key, value in label.items() if key != "label_binding_sha256"}
    directional_cost = label.get("directional_cost_evidence")
    tensor_unsigned = {
        key: value for key, value in tensor_binding.items() if key != "tensor_binding_sha256"
    }
    if (
        label.get("label_binding_sha256") != stable_sha256(label_unsigned)
        or tensor_binding.get("tensor_binding_sha256") != stable_sha256(tensor_unsigned)
        or label.get("decision_time") != sample.decision_time
        or label.get("archive_high_water_sha256") is None
        or label.get("label_expected_move_after_cost_bps_float64_sha256")
        != _float64_label_sha256(label.get("label_expected_move_after_cost_bps"))
        or label.get("label_horizon_seconds") != sample.expected_holding_horizon_seconds
        or label.get("label_horizon_source") != "AUTHENTICATED_CAUSAL_COST_BINDING"
        or type(directional_cost) is not dict
        or label.get("directional_cost_evidence_sha256") != stable_sha256(directional_cost)
        or directional_cost.get("cost_capture_binding_sha256") != sample.cost_capture_binding_sha256
        or directional_cost.get("cost_cas_object_inventory_sha256")
        != sample.cost_cas_object_inventory_sha256
        or directional_cost.get("expected_holding_horizon_seconds")
        != sample.expected_holding_horizon_seconds
        or directional_cost.get("decision_reference_price") != sample.decision_reference_price
        or directional_cost.get("decision_reference_price_source")
        != sample.decision_reference_price_source
        or directional_cost.get("decision_reference_price_binding_sha256")
        != sample.decision_reference_price_binding_sha256
        or directional_cost.get("decision_reference_price_payload_sha256")
        != sample.decision_reference_price_payload_sha256
        or directional_cost.get("decision_reference_price_receipt_sha256")
        != sample.decision_reference_price_receipt_sha256
        or label.get("auxiliary_cost_values_excluded_from_model_vector") is not True
        or tensor_binding.get("logical_model_vector_sha256") != sample.logical_model_vector_sha256
        or tensor_binding.get("logical_projection_sha256") != sample.logical_projection_sha256
        or tensor_binding.get("logical_feature_count") != LOGICAL_MODEL_FEATURE_COUNT
        or tensor_binding.get("logical_model_input_count") != LOGICAL_MODEL_INPUT_COUNT
        or tensor_binding.get("feature_registry_sha256") != FEATURE_SOURCE_REGISTRY_V4_SHA256
        or tensor_binding.get("feature_registry_abi_sha256")
        != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
    ):
        _fail("PROFILED_OBSERVATION_EXAMPLE_BINDING_INVALID")
    configured_sources = tuple(
        slot.configured_source_label for slot in FEATURE_SOURCE_REGISTRY_V4.slots
    )
    if len(configured_sources) != LOGICAL_MODEL_FEATURE_COUNT:
        _fail("PROFILED_OBSERVATION_CONFIGURED_SOURCE_ABI_INVALID")
    coverage = (
        100.0
        * sum(sample.logical_source_availability_mask)
        / len(sample.logical_source_availability_mask)
    )
    tensor = FeatureTensorRecord(
        tensor_id=cast(str, tensor_binding["tensor_id"]),
        symbol=sample.symbol,
        timeframe=sample.timeframe,
        feature_snapshot_id=sample.feature_snapshot_id,
        values=sample.logical_feature_values,
        missing_mask=sample.logical_missing_mask,
        stale_mask=sample.logical_stale_mask,
        source_availability=sample.logical_source_availability_mask,
        feature_names=sample.logical_feature_names,
        source_labels=configured_sources,
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=coverage,
        source_availability_vector=sample.logical_source_availability_mask,
        decision_time=sample.decision_time,
        source_lineage_hash=cast(str, tensor_binding["source_lineage_hash"]),
        temporal_rejection_reasons=(),
    )
    if tensor.model_vector != sample.logical_model_vector:
        _fail("PROFILED_OBSERVATION_TRAINING_EXAMPLE_MODEL_VECTOR_MISMATCH")
    label_available_at = cast(str, label["label_available_at"])
    decision = _clock(sample.decision_time, reason="PROFILED_OBSERVATION_DECISION_TIME_INVALID")
    record_generated = _clock(
        sample.generated_at,
        reason="PROFILED_OBSERVATION_RECORD_GENERATED_AT_INVALID",
    )
    trainer_sample_available = _clock(
        sample.postcommit_readback_at,
        reason="PROFILED_OBSERVATION_SAMPLE_AVAILABLE_AT_INVALID",
    )
    label_available = _clock(
        label_available_at,
        reason="PROFILED_OBSERVATION_LABEL_AVAILABLE_AT_INVALID",
    )
    if (
        label_available <= decision
        or record_generated > decision
        or trainer_sample_available <= decision
        or trainer_sample_available <= record_generated
    ):
        _fail("PROFILED_OBSERVATION_TRAINING_EXAMPLE_TIMING_INVALID")
    horizon_seconds = cast(int, label["label_horizon_seconds"])
    trust_row = {
        "row_source": "profiled_training_fixed_observation_manifest_v1",
        "training_example_adapter_contract_version": (
            PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION
        ),
        "training_example_adapter_contract_sha256": stable_sha256(
            _training_example_adapter_contract()
        ),
        "row_classification": "TRAINABLE",
        "learning_mode": "outcome_supervised",
        "update_lane": "PROFILED_OUTCOME_SUPERVISED_UNWIRED",
        "decision_time": sample.decision_time,
        "feature_cutoff": sample.feature_cutoff,
        "available_at": sample.postcommit_readback_at,
        "available_at_semantics": (
            "TRAINER_SAMPLE_DURABLY_AVAILABLE_AT_LEDGER_POSTCOMMIT_READBACK"
        ),
        "record_generated_at": sample.generated_at,
        "trainer_sample_available_at": sample.postcommit_readback_at,
        "trainer_sample_available_at_source": "LEDGER_POSTCOMMIT_READBACK_RECEIPT",
        "postcommit_readback_at": sample.postcommit_readback_at,
        "cost_evidence_available_at": sample.cost_evidence_available_at,
        "decision_reference_price_available_at": (sample.decision_reference_price_available_at),
        "decision_reference_price": sample.decision_reference_price,
        "decision_reference_price_source": sample.decision_reference_price_source,
        "decision_reference_price_binding_sha256": (sample.decision_reference_price_binding_sha256),
        "label_available_at": label_available_at,
        "outcome_available_at": label_available_at,
        "label_horizon_seconds": horizon_seconds,
        "outcome_horizon_seconds": horizon_seconds,
        "candle_closed_confirmed": True,
        "future_labels_not_in_feature_tensor": True,
        "profiled_sample_identity_sha256": sample_binding["sample_identity_sha256"],
        "profiled_label_binding_sha256": label["label_binding_sha256"],
        "profiled_tensor_binding_sha256": tensor_binding["tensor_binding_sha256"],
        "optimizer_admission_authorized": False,
        "checkpoint_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "runtime_wired": False,
    }
    example = TrainingExample(
        symbol=sample.symbol,
        timeframe=sample.timeframe,
        tensor=tensor,
        label_action_index=cast(int, label["label_action_index"]),
        label_expected_move_after_cost_bps=cast(
            float,
            label["label_expected_move_after_cost_bps"],
        ),
        payload_keys=(
            f"profiled_ledger:{sample.durable_snapshot_id}",
            f"canonical_label_path:{label['label_path_sha256']}",
        ),
        row_classification="TRAINABLE",
        trust_row=trust_row,
        decision_time=sample.decision_time,
        label_available_at=label_available_at,
        behavior_action_index=None,
        behavior_action=None,
    )
    if (
        example.label_timing_valid is not True
        or example.label_available_at != label_available_at
        or example.decision_time != sample.decision_time
    ):
        _fail("PROFILED_OBSERVATION_TRAINING_EXAMPLE_TIMING_INVALID")
    return ProfiledTrainingObservationExampleV1(
        ordinal=cast(int, entry["ordinal"]),
        sample_identity_sha256=cast(str, sample_binding["sample_identity_sha256"]),
        label_binding_sha256=cast(str, label["label_binding_sha256"]),
        tensor_binding_sha256=cast(str, tensor_binding["tensor_binding_sha256"]),
        training_example=example,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        runtime_wired=False,
        _construction_token=_EXAMPLE_TOKEN,
    )


def read_profiled_training_observation_page_v1(
    *,
    manifest_path: Path,
    ledger: DurableFeatureSnapshotLedger,
    trusted_immutable_cost_store_root: Path,
    hmac_key: bytes | bytearray | memoryview,
    expected_auth_key_id: str,
    expected_manifest_id: str,
    expected_observation_time: str,
    after_ordinal: int = 0,
    limit: int = MAX_PROFILED_OBSERVATION_PAGE_ROWS,
) -> ProfiledTrainingObservationPageV1:
    """Reopen one pinned historical page; never select a latest manifest."""

    key = _validated_key(hmac_key)
    path = _exact_absolute_path(
        manifest_path,
        reason="PROFILED_OBSERVATION_MANIFEST_PATH_INVALID",
    )
    cost_root = _exact_absolute_path(
        trusted_immutable_cost_store_root,
        reason="PROFILED_OBSERVATION_COST_STORE_ROOT_INVALID",
    )
    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_OBSERVATION_LEDGER_EXACT_TYPE_REQUIRED")
    if (
        type(expected_auth_key_id) is not str
        or _AUTH_KEY_ID_RE.fullmatch(expected_auth_key_id) is None
    ):
        _fail("PROFILED_OBSERVATION_AUTH_KEY_ID_INVALID")
    if not _valid_sha256(expected_manifest_id):
        _fail("PROFILED_OBSERVATION_EXPECTED_MANIFEST_ID_INVALID")
    expected_observation = _canonical_clock(
        _clock(
            expected_observation_time,
            reason="PROFILED_OBSERVATION_EXPECTED_CUTOFF_INVALID",
        )
    )
    if type(after_ordinal) is not int or after_ordinal < 0:
        _fail("PROFILED_OBSERVATION_AFTER_ORDINAL_INVALID")
    if type(limit) is not int or not 0 < limit <= MAX_PROFILED_OBSERVATION_PAGE_ROWS:
        _fail("PROFILED_OBSERVATION_PAGE_LIMIT_INVALID")
    connection, metadata = _read_metadata(
        path,
        key=key,
        expected_auth_key_id=expected_auth_key_id,
        full_database_check=False,
    )
    try:
        if (
            metadata.get("manifest_id") != expected_manifest_id
            or metadata.get("observation_time") != expected_observation
        ):
            _fail("PROFILED_OBSERVATION_EXPECTED_MANIFEST_BINDING_MISMATCH")
        context = metadata.get("observation_context")
        if (
            type(context) is not dict
            or metadata.get("observation_context_sha256") != stable_sha256(context)
            or context.get("feature_ledger_path") != str(ledger.path)
            or context.get("trusted_cost_store_root") != str(cost_root)
            or context.get("logical_model_feature_count") != LOGICAL_MODEL_FEATURE_COUNT
            or context.get("logical_model_input_count") != LOGICAL_MODEL_INPUT_COUNT
            or context.get("feature_registry_abi_sha256") != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
        ):
            _fail("PROFILED_OBSERVATION_REOPEN_CONTEXT_INVALID")
        high_water = context.get("feature_ledger_high_water")
        if type(high_water) is not dict:
            _fail("PROFILED_OBSERVATION_REOPEN_HIGH_WATER_MISSING")
        total_entries = metadata.get("total_profiled_samples")
        if type(total_entries) is not int or after_ordinal > total_entries:
            _fail("PROFILED_OBSERVATION_AFTER_ORDINAL_OUTSIDE_MANIFEST")
        if after_ordinal == 0:
            previous_chain = PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
        else:
            prior_row = connection.execute(
                "SELECT ordinal, ledger_sequence, durable_snapshot_id, label_status, "
                "observation_context_sha256, entry_json, entry_sha256, "
                "previous_entry_chain_sha256, entry_chain_sha256, auth_tag "
                "FROM observation_manifest_entries WHERE ordinal = ?",
                (after_ordinal,),
            ).fetchone()
            if prior_row is None:
                _fail("PROFILED_OBSERVATION_CURSOR_ANCHOR_MISSING")
            _verify_entry_row(
                prior_row,
                key=key,
                observation_context_sha256=cast(
                    str,
                    metadata["observation_context_sha256"],
                ),
            )
            previous_chain = str(prior_row["entry_chain_sha256"])
        rows = list(
            connection.execute(
                "SELECT ordinal, ledger_sequence, durable_snapshot_id, label_status, "
                "observation_context_sha256, entry_json, entry_sha256, "
                "previous_entry_chain_sha256, entry_chain_sha256, auth_tag "
                "FROM observation_manifest_entries WHERE ordinal > ? "
                "ORDER BY ordinal ASC LIMIT ?",
                (after_ordinal, limit),
            )
        )
        expected_row_count = min(limit, total_entries - after_ordinal)
        if len(rows) != expected_row_count:
            _fail("PROFILED_OBSERVATION_ENTRY_INVENTORY_OMISSION")
        examples: list[ProfiledTrainingObservationExampleV1] = []
        unavailable_scanned = 0
        for expected_ordinal, row in enumerate(rows, start=after_ordinal + 1):
            if row["ordinal"] != expected_ordinal:
                _fail("PROFILED_OBSERVATION_ENTRY_ORDINAL_GAP")
            entry = _verify_entry_row(
                row,
                key=key,
                observation_context_sha256=cast(
                    str,
                    metadata["observation_context_sha256"],
                ),
                expected_previous_chain=previous_chain,
            )
            previous_chain = str(row["entry_chain_sha256"])
            if entry["label_status"] == PROFILED_OBSERVATION_LABEL_STATUS_UNAVAILABLE:
                unavailable_scanned += 1
                continue
            sample_binding = cast(dict[str, Any], entry["sample_binding"])
            try:
                sample = reopen_profiled_training_ledger_sample_v1(
                    ledger=ledger,
                    trusted_immutable_cost_store_root=cost_root,
                    fixed_observation_high_water=high_water,
                    training_observed_at=cast(str, metadata["observation_time"]),
                    durable_snapshot_id=cast(
                        str,
                        sample_binding["durable_snapshot_id"],
                    ),
                    expected_sequence=cast(int, sample_binding["ledger_sequence"]),
                    expected_record_sha256=cast(str, sample_binding["record_sha256"]),
                )
            except ProfiledTrainingLedgerLoaderV1Error as exc:
                raise ProfiledTrainingObservationManifestV1Error(
                    f"PROFILED_OBSERVATION_DIRECT_SAMPLE_REOPEN_FAILED:{exc}"
                ) from exc
            if _sample_binding(sample) != sample_binding:
                _fail("PROFILED_OBSERVATION_DIRECT_SAMPLE_BINDING_MISMATCH")
            examples.append(_example_from_authenticated_entry(entry=entry, sample=sample))
        next_after = int(rows[-1]["ordinal"]) if rows else after_ordinal
        has_more = next_after < total_entries
        if not has_more and previous_chain != metadata.get("entry_chain_head_sha256"):
            _fail("PROFILED_OBSERVATION_ENTRY_CHAIN_HEAD_MISMATCH")
        connection.rollback()
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
    return ProfiledTrainingObservationPageV1(
        manifest_id=cast(str, metadata["manifest_id"]),
        observation_time=cast(str, metadata["observation_time"]),
        factory_wall_clock_observed_at=cast(
            str,
            metadata["factory_wall_clock_observed_at"],
        ),
        requested_after_ordinal=after_ordinal,
        next_after_ordinal=next_after,
        has_more_manifest_entries=has_more,
        scanned_entry_count=len(rows),
        label_unavailable_scanned=unavailable_scanned,
        examples=tuple(examples),
        checkpoint_write_authorized=False,
        external_monotonic_manifest_head_verified=False,
        runtime_wired=False,
        _construction_token=_PAGE_TOKEN,
    )


__all__ = [
    "AuthenticatedProfiledTrainingObservationInventoryPageV1",
    "AuthenticatedProfiledTrainingObservationManifestV1",
    "MAX_PROFILED_OBSERVATION_PAGE_ROWS",
    "MIN_PROFILED_OBSERVATION_HMAC_KEY_BYTES",
    "PROFILED_OBSERVATION_AUTH_ALGORITHM",
    "PROFILED_OBSERVATION_AUTH_DOMAIN",
    "PROFILED_OBSERVATION_ENTRY_V1_SCHEMA_VERSION",
    "PROFILED_OBSERVATION_LABEL_BINDING_V1_SCHEMA_VERSION",
    "PROFILED_OBSERVATION_LABEL_STATUS_ADMITTED",
    "PROFILED_OBSERVATION_LABEL_STATUS_UNAVAILABLE",
    "PROFILED_OBSERVATION_MANIFEST_V1_SCHEMA_VERSION",
    "PROFILED_OBSERVATION_ORDERED_DIGEST_ALGORITHM",
    "PROFILED_OBSERVATION_ORDERED_DIGEST_SCHEMA_VERSION",
    "PROFILED_OBSERVATION_RUNTIME_STATUS",
    "PROFILED_OBSERVATION_TRAINING_EXAMPLE_ADAPTER_CONTRACT_VERSION",
    "ProfiledTrainingObservationExampleV1",
    "ProfiledTrainingObservationManifestBuildV1",
    "ProfiledTrainingObservationManifestV1Error",
    "ProfiledTrainingObservationPageV1",
    "authenticate_profiled_training_observation_inventory_page_v1",
    "authenticate_profiled_training_observation_manifest_v1",
    "build_profiled_training_observation_manifest_v1",
    "read_profiled_training_observation_page_v1",
]
