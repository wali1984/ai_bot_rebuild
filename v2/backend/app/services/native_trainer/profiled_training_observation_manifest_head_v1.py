"""Local staging contracts for externally witnessed trainer manifest heads.

This module deliberately stops before authority.  It creates immutable,
content-addressed, independently authenticated head, consumption-epoch, page,
and completion *candidates*.  A coherent rollback or fork of the complete
local CAS is not detectable here.  A future independent durable witness must
perform compare-and-append and acknowledge full consumption before any
optimizer, model, checkpoint, prediction, paper, live, order, execution, or
runtime authority can be granted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, Protocol, cast, runtime_checkable

from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (
    feature_ledger_fixed_observation_high_water,
    label_archive_fixed_observation_high_water,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    MAX_PROFILED_OBSERVATION_PAGE_ROWS,
    MIN_PROFILED_OBSERVATION_HMAC_KEY_BYTES,
    PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS,
    AuthenticatedProfiledTrainingObservationManifestV1,
    ProfiledTrainingObservationManifestV1Error,
    authenticate_profiled_training_observation_inventory_page_v1,
    authenticate_profiled_training_observation_manifest_v1,
)

PROFILED_OBSERVATION_HEAD_CANDIDATE_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_manifest_head_candidate_v1"
)
PROFILED_OBSERVATION_PRIOR_HIGH_WATER_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_prior_high_water_reproduction_receipt_v1"
)
PROFILED_OBSERVATION_EPOCH_CANDIDATE_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_full_consumption_epoch_candidate_v1"
)
PROFILED_OBSERVATION_PAGE_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_consumption_page_receipt_v1"
)
PROFILED_OBSERVATION_COMPLETION_CANDIDATE_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_full_consumption_completion_candidate_v1"
)
PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_external_witness_event_v1"
)
PROFILED_OBSERVATION_WITNESS_RECEIPT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_external_witness_append_receipt_v1"
)
PROFILED_OBSERVATION_LOCAL_STAGING_STATUS: Final = "LOCAL_STAGING_ONLY"
PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION: Final = (
    "COHERENT_LOCAL_CAS_ROLLBACK_OR_FORK_IS_NOT_DETECTABLE_EXTERNAL_WITNESS_REQUIRED"
)

PROFILED_OBSERVATION_HEAD_AUTH_ALGORITHM: Final = "HMAC-SHA256"
PROFILED_OBSERVATION_HEAD_AUTH_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-manifest-head-candidate/v1"
)
PROFILED_OBSERVATION_EPOCH_AUTH_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-consumption-epoch/v1"
)
PROFILED_OBSERVATION_PAGE_AUTH_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-consumption-page/v1"
)
PROFILED_OBSERVATION_COMPLETION_AUTH_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-consumption-completion/v1"
)
PROFILED_OBSERVATION_REPRODUCTION_AUTH_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-prior-high-water-reproduction/v1"
)
PROFILED_OBSERVATION_EPOCH_KEY_COMMITMENT_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-epoch-key-commitment/v1"
)

PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256: Final = hashlib.sha256(
    b"profiled_training_observation_manifest_head_v1:GENESIS"
).hexdigest()
PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256: Final = hashlib.sha256(
    b"profiled_training_observation_completion_v1:GENESIS"
).hexdigest()
PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256: Final = hashlib.sha256(
    b"profiled_training_observation_page_transition_v1:GENESIS"
).hexdigest()
PROFILED_OBSERVATION_ORDERED_PAGE_ROOT_GENESIS_SHA256: Final = hashlib.sha256(
    b"profiled_training_observation_ordered_page_root_v1:GENESIS"
).hexdigest()

MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES: Final = 4 * 1024 * 1024
MAX_PROFILED_OBSERVATION_CONSUMPTION_PAGES: Final = 250_000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$", re.ASCII)
_HEAD_TOKEN = object()
_EPOCH_TOKEN = object()
_PAGE_RECEIPT_TOKEN = object()
_COMPLETION_TOKEN = object()


class ProfiledTrainingObservationManifestHeadV1Error(RuntimeError):
    """A local head/consumption candidate failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingObservationManifestHeadV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _identifier(value: object, *, reason: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(reason)
    return cast(str, value)


def _canonical_json(value: object, *, reason: str) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(reason) from exc
    if not encoded or len(encoded.encode("ascii")) > MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES:
        _fail(reason)
    return encoded


def _strict_json(raw: bytes, *, reason: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES:
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
        text = raw.decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(reason) from exc
    if type(value) is not dict or _canonical_json(value, reason=reason) != text:
        _fail(reason)
    return cast(dict[str, Any], value)


def _key(value: object, *, reason: str) -> bytes:
    if not isinstance(value, bytes | bytearray | memoryview):
        _fail(reason)
    key = bytes(value)
    if len(key) < MIN_PROFILED_OBSERVATION_HMAC_KEY_BYTES:
        _fail(reason)
    return key


def _clock(value: object, *, reason: str) -> datetime:
    if type(value) is not str or value != value.strip() or not value:
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    normalized = parsed.astimezone(UTC)
    canonical = normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if value != canonical:
        _fail(reason)
    return normalized


def _auth_tag(*, domain: str, role: str, payload: Mapping[str, Any], key: bytes) -> str:
    encoded = _canonical_json(dict(payload), reason="PROFILED_HEAD_AUTH_PAYLOAD_INVALID")
    return hmac.new(
        key,
        domain.encode("ascii") + b"\0" + role.encode("ascii") + b"\0" + encoded.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _epoch_key_commitment(*, key: bytes, key_id: str) -> str:
    return hashlib.sha256(
        PROFILED_OBSERVATION_EPOCH_KEY_COMMITMENT_DOMAIN.encode("ascii")
        + b"\0"
        + key_id.encode("ascii")
        + b"\0"
        + key
    ).hexdigest()


def _authority_false() -> dict[str, bool]:
    return {
        "external_monotonic_manifest_head_verified": False,
        "full_consumption_external_ack_verified": False,
        "optimizer_admission_authorized": False,
        "checkpoint_write_authorized": False,
        "model_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
        "execution_authorized": False,
        "runtime_wired": False,
    }


def _authority_is_false(material: Mapping[str, Any]) -> bool:
    return all(material.get(name) is False for name in _authority_false())


def _exact_store(value: object) -> ImmutableSourcePayloadStore:
    if type(value) is not ImmutableSourcePayloadStore:
        _fail("PROFILED_HEAD_IMMUTABLE_STORE_EXACT_TYPE_REQUIRED")
    store = cast(ImmutableSourcePayloadStore, value)
    if not store.root_path.is_absolute() or ".." in store.root_path.parts:
        _fail("PROFILED_HEAD_IMMUTABLE_STORE_ROOT_INVALID")
    return store


def _put_event(store: ImmutableSourcePayloadStore, material: Mapping[str, Any]) -> tuple[str, int]:
    payload = _canonical_json(dict(material), reason="PROFILED_HEAD_EVENT_JSON_INVALID").encode(
        "ascii"
    )
    try:
        address = store.put(payload)
        readback = store.get(
            address.payload_sha256,
            expected_byte_count=address.payload_byte_count,
        )
    except SourcePayloadStoreError as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(
            f"PROFILED_HEAD_CAS_WRITE_FAILED:{type(exc).__name__}:{exc}"
        ) from exc
    if readback != payload:
        _fail("PROFILED_HEAD_CAS_POSTCOMMIT_READBACK_MISMATCH")
    return address.payload_sha256, address.payload_byte_count


def _get_event(
    store: ImmutableSourcePayloadStore,
    payload_sha256: str,
    payload_byte_count: int,
) -> dict[str, Any]:
    if not _valid_sha256(payload_sha256):
        _fail("PROFILED_HEAD_CAS_SHA256_INVALID")
    if (
        type(payload_byte_count) is not int
        or not 0 < payload_byte_count <= MAX_PROFILED_OBSERVATION_HEAD_EVENT_BYTES
    ):
        _fail("PROFILED_HEAD_CAS_BYTE_COUNT_INVALID")
    try:
        raw = store.get(payload_sha256, expected_byte_count=payload_byte_count)
    except SourcePayloadStoreError as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(
            f"PROFILED_HEAD_CAS_READ_FAILED:{type(exc).__name__}:{exc}"
        ) from exc
    return _strict_json(raw, reason="PROFILED_HEAD_EVENT_JSON_INVALID")


def _manifest_summary(
    summary: AuthenticatedProfiledTrainingObservationManifestV1,
) -> dict[str, Any]:
    if type(summary) is not AuthenticatedProfiledTrainingObservationManifestV1:
        _fail("PROFILED_HEAD_AUTHENTICATED_MANIFEST_EXACT_TYPE_REQUIRED")
    return {
        "schema_version": "profiled_training_observation_authenticated_scalar_summary_v1",
        "manifest_path": str(summary.manifest_path),
        "manifest_file_name": summary.manifest_path.name,
        "manifest_file_device": summary.manifest_file_device,
        "manifest_file_inode": summary.manifest_file_inode,
        "manifest_file_byte_count": summary.manifest_file_byte_count,
        "manifest_id": summary.manifest_id,
        "metadata_sha256": summary.metadata_sha256,
        "metadata_auth_tag": summary.metadata_auth_tag,
        "observation_time": summary.observation_time,
        "retrospective_cutoff_at": summary.retrospective_cutoff_at,
        "factory_wall_clock_observed_at": summary.factory_wall_clock_observed_at,
        "manifest_auth_algorithm": summary.auth_algorithm,
        "manifest_auth_domain": summary.auth_domain,
        "manifest_auth_key_id": summary.auth_key_id,
        "observation_context_sha256": summary.observation_context_sha256,
        "feature_ledger_path": summary.feature_ledger_path,
        "feature_ledger_path_sha256": summary.feature_ledger_path_sha256,
        "feature_ledger_high_water_sha256": summary.feature_ledger_high_water_sha256,
        "feature_ledger_verified_records": summary.feature_ledger_verified_records,
        "feature_ledger_prefix_head_sequence": summary.feature_ledger_prefix_head_sequence,
        "feature_ledger_archive_chain_sha256": summary.feature_ledger_archive_chain_sha256,
        "feature_ledger_ordered_receipts_sha256": summary.feature_ledger_ordered_receipts_sha256,
        "label_archive_path": summary.label_archive_path,
        "label_archive_path_sha256": summary.label_archive_path_sha256,
        "label_archive_high_water_sha256": summary.label_archive_high_water_sha256,
        "label_archive_verified_rows": summary.label_archive_verified_rows,
        "label_archive_prefix_head_sequence": summary.label_archive_prefix_head_sequence,
        "label_archive_archive_chain_sha256": summary.label_archive_archive_chain_sha256,
        "label_archive_ordered_receipts_sha256": summary.label_archive_ordered_receipts_sha256,
        "entry_chain_genesis_sha256": summary.entry_chain_genesis_sha256,
        "entry_chain_head_sha256": summary.entry_chain_head_sha256,
        "ordered_entry_identities_sha256": summary.ordered_entry_identities_sha256,
        "total_profiled_samples": summary.total_profiled_samples,
        "admitted_example_count": summary.admitted_example_count,
        "label_unavailable_count": summary.label_unavailable_count,
        "ledger_exclusion_count": summary.ledger_exclusion_count,
        "ledger_exclusion_inventory_sha256": summary.ledger_exclusion_inventory_sha256,
        "full_manifest_authentication_verified": True,
        "full_entry_inventory_verified": True,
        **_authority_false(),
    }


def _validate_manifest_summary(material: object) -> dict[str, Any]:
    if type(material) is not dict:
        _fail("PROFILED_HEAD_MANIFEST_SUMMARY_INVALID")
    summary = cast(dict[str, Any], material)
    total = summary.get("total_profiled_samples")
    admitted = summary.get("admitted_example_count")
    unavailable = summary.get("label_unavailable_count")
    hash_fields = (
        "manifest_id",
        "metadata_sha256",
        "metadata_auth_tag",
        "observation_context_sha256",
        "feature_ledger_path_sha256",
        "feature_ledger_high_water_sha256",
        "feature_ledger_archive_chain_sha256",
        "feature_ledger_ordered_receipts_sha256",
        "label_archive_path_sha256",
        "label_archive_high_water_sha256",
        "label_archive_archive_chain_sha256",
        "label_archive_ordered_receipts_sha256",
        "entry_chain_genesis_sha256",
        "entry_chain_head_sha256",
        "ordered_entry_identities_sha256",
        "ledger_exclusion_inventory_sha256",
    )
    if (
        summary.get("schema_version")
        != "profiled_training_observation_authenticated_scalar_summary_v1"
        or not all(_valid_sha256(summary.get(name)) for name in hash_fields)
        or type(total) is not int
        or type(admitted) is not int
        or type(unavailable) is not int
        or min(total, admitted, unavailable) < 0
        or total != admitted + unavailable
        or summary.get("manifest_file_name")
        != f"profiled_training_observation_{summary.get('manifest_id')}.sqlite3"
        or summary.get("full_manifest_authentication_verified") is not True
        or summary.get("full_entry_inventory_verified") is not True
        or not _authority_is_false(summary)
        or summary.get("retrospective_cutoff_at") != summary.get("observation_time")
    ):
        _fail("PROFILED_HEAD_MANIFEST_SUMMARY_INVALID")
    _clock(summary.get("observation_time"), reason="PROFILED_HEAD_MANIFEST_CUTOFF_INVALID")
    _clock(
        summary.get("factory_wall_clock_observed_at"),
        reason="PROFILED_HEAD_MANIFEST_FACTORY_CLOCK_INVALID",
    )
    return summary


def _keys_and_ids(
    *,
    manifest_key: object,
    manifest_key_id: object,
    head_key: object,
    head_key_id: object,
    epoch_key: object,
    epoch_key_id: object,
) -> tuple[bytes, str, bytes, str, bytes, str]:
    manifest = _key(manifest_key, reason="PROFILED_HEAD_MANIFEST_HMAC_KEY_INVALID")
    head = _key(head_key, reason="PROFILED_HEAD_HMAC_KEY_INVALID")
    epoch = _key(epoch_key, reason="PROFILED_EPOCH_HMAC_KEY_INVALID")
    manifest_id = _identifier(manifest_key_id, reason="PROFILED_HEAD_MANIFEST_KEY_ID_INVALID")
    head_id = _identifier(head_key_id, reason="PROFILED_HEAD_KEY_ID_INVALID")
    epoch_id = _identifier(epoch_key_id, reason="PROFILED_EPOCH_KEY_ID_INVALID")
    if len({manifest, head, epoch}) != 3 or len({manifest_id, head_id, epoch_id}) != 3:
        _fail("PROFILED_HEAD_ROLE_KEY_REUSE_FORBIDDEN")
    return manifest, manifest_id, head, head_id, epoch, epoch_id


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationExternalWitnessEventV1:
    """Bytes returned by an external witness; integrity is not authority."""

    schema_version: str
    witness_id: str
    namespace: str
    sequence: int
    previous_event_sha256: str
    event_sha256: str
    event_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != PROFILED_OBSERVATION_WITNESS_EVENT_V1_SCHEMA_VERSION
            or _IDENTIFIER_RE.fullmatch(self.witness_id) is None
            or _IDENTIFIER_RE.fullmatch(self.namespace) is None
            or type(self.sequence) is not int
            or self.sequence <= 0
            or not _valid_sha256(self.previous_event_sha256)
            or not _valid_sha256(self.event_sha256)
            or type(self.event_bytes) is not bytes
            or hashlib.sha256(self.event_bytes).hexdigest() != self.event_sha256
        ):
            _fail("PROFILED_HEAD_WITNESS_EVENT_CONTRACT_INVALID")


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationExternalWitnessAppendReceiptV1:
    """Opaque append receipt contract for a future independent witness."""

    schema_version: str
    witness_id: str
    namespace: str
    sequence: int
    previous_event_sha256: str
    event_sha256: str
    accepted_at: str
    receipt_sha256: str
    receipt_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.schema_version != PROFILED_OBSERVATION_WITNESS_RECEIPT_V1_SCHEMA_VERSION
            or _IDENTIFIER_RE.fullmatch(self.witness_id) is None
            or _IDENTIFIER_RE.fullmatch(self.namespace) is None
            or type(self.sequence) is not int
            or self.sequence <= 0
            or not _valid_sha256(self.previous_event_sha256)
            or not _valid_sha256(self.event_sha256)
            or not _valid_sha256(self.receipt_sha256)
            or type(self.receipt_bytes) is not bytes
            or hashlib.sha256(self.receipt_bytes).hexdigest() != self.receipt_sha256
        ):
            _fail("PROFILED_HEAD_WITNESS_RECEIPT_CONTRACT_INVALID")
        _clock(self.accepted_at, reason="PROFILED_HEAD_WITNESS_RECEIPT_CLOCK_INVALID")


@runtime_checkable
class ProfiledTrainingObservationExternalWitnessV1(Protocol):
    """Independent monotonic compare-and-append service boundary."""

    def read_latest(
        self, *, namespace: str
    ) -> ProfiledTrainingObservationExternalWitnessEventV1 | None: ...

    def compare_and_append(
        self,
        *,
        namespace: str,
        expected_sequence: int,
        expected_event_sha256: str,
        event_bytes: bytes,
    ) -> ProfiledTrainingObservationExternalWitnessAppendReceiptV1: ...

    def read_event(
        self, *, namespace: str, sequence: int
    ) -> ProfiledTrainingObservationExternalWitnessEventV1: ...


@dataclass(frozen=True, slots=True)
class LocalProfiledTrainingObservationHeadCandidateV1:
    staging_store_root: Path
    candidate_event_sha256: str
    candidate_event_byte_count: int
    candidate_id: str
    namespace: str
    revision: int
    previous_head_event_sha256: str
    previous_completion_candidate_sha256: str
    manifest_id: str
    observation_time: str
    manifest_auth_key_id: str
    head_auth_key_id: str
    epoch_auth_key_id: str
    epoch_auth_key_commitment_sha256: str
    allowed_consumer_lane: str
    local_status: str
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
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _manifest_key_sha256: str = field(repr=False, compare=False)
    _head_key_sha256: str = field(repr=False, compare=False)
    _epoch_key_sha256: str = field(repr=False, compare=False)
    _material: dict[str, Any] = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _HEAD_TOKEN
            or not self.staging_store_root.is_absolute()
            or not all(
                _valid_sha256(value)
                for value in (
                    self.candidate_event_sha256,
                    self.candidate_id,
                    self.previous_head_event_sha256,
                    self.previous_completion_candidate_sha256,
                    self.manifest_id,
                    self._manifest_key_sha256,
                    self._head_key_sha256,
                    self._epoch_key_sha256,
                    self.epoch_auth_key_commitment_sha256,
                )
            )
            or self.candidate_event_byte_count <= 0
            or self.revision <= 0
            or self.local_status != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
            or self.full_manifest_authentication_verified is not True
            or self.full_entry_inventory_verified is not True
            or not _authority_is_false(self._material)
        ):
            _fail("PROFILED_HEAD_CANDIDATE_RESULT_INVALID")


@dataclass(frozen=True, slots=True)
class LocalProfiledTrainingObservationConsumptionEpochV1:
    staging_store_root: Path
    epoch_event_sha256: str
    epoch_event_byte_count: int
    epoch_id: str
    consumer_lane: str
    head_candidate_event_sha256: str
    head_revision: int
    manifest_id: str
    observation_time: str
    manifest_auth_key_id: str
    head_auth_key_id: str
    epoch_auth_key_id: str
    page_size: int
    total_profiled_samples: int
    admitted_example_count: int
    label_unavailable_count: int
    terminal_entry_chain_sha256: str
    local_status: str
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    optimizer_admission_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _material: dict[str, Any] = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _EPOCH_TOKEN
            or not all(
                _valid_sha256(value)
                for value in (
                    self.epoch_event_sha256,
                    self.epoch_id,
                    self.head_candidate_event_sha256,
                    self.manifest_id,
                    self.terminal_entry_chain_sha256,
                )
            )
            or self.head_revision <= 0
            or not 0 < self.page_size <= MAX_PROFILED_OBSERVATION_PAGE_ROWS
            or self.total_profiled_samples
            != self.admitted_example_count + self.label_unavailable_count
            or self.local_status != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
            or not _authority_is_false(self._material)
        ):
            _fail("PROFILED_EPOCH_CANDIDATE_RESULT_INVALID")


@dataclass(frozen=True, slots=True)
class LocalProfiledTrainingObservationPageReceiptV1:
    staging_store_root: Path
    page_receipt_event_sha256: str
    page_receipt_event_byte_count: int
    page_receipt_id: str
    epoch_id: str
    page_sequence: int
    page_start_ordinal: int
    page_end_ordinal: int
    scanned_entry_count: int
    admitted_entry_count: int
    label_unavailable_count: int
    cumulative_scanned_entry_count: int
    cumulative_admitted_entry_count: int
    cumulative_label_unavailable_count: int
    page_start_previous_entry_chain_sha256: str
    page_end_entry_chain_sha256: str
    previous_page_transition_sha256: str
    page_transition_sha256: str
    ordered_page_root_sha256: str
    has_more_manifest_entries: bool
    verified_at: str
    local_status: str
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    optimizer_admission_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _material: dict[str, Any] = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _PAGE_RECEIPT_TOKEN
            or not all(
                _valid_sha256(value)
                for value in (
                    self.page_receipt_event_sha256,
                    self.page_receipt_id,
                    self.epoch_id,
                    self.page_start_previous_entry_chain_sha256,
                    self.page_end_entry_chain_sha256,
                    self.previous_page_transition_sha256,
                    self.page_transition_sha256,
                    self.ordered_page_root_sha256,
                )
            )
            or self.page_sequence <= 0
            or self.scanned_entry_count <= 0
            or self.scanned_entry_count != self.admitted_entry_count + self.label_unavailable_count
            or self.cumulative_scanned_entry_count
            != self.cumulative_admitted_entry_count + self.cumulative_label_unavailable_count
            or type(self.has_more_manifest_entries) is not bool
            or self.local_status != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
            or not _authority_is_false(self._material)
        ):
            _fail("PROFILED_PAGE_RECEIPT_RESULT_INVALID")
        _clock(self.verified_at, reason="PROFILED_PAGE_RECEIPT_CLOCK_INVALID")


@dataclass(frozen=True, slots=True)
class LocalProfiledTrainingObservationCompletionCandidateV1:
    staging_store_root: Path
    completion_event_sha256: str
    completion_event_byte_count: int
    completion_id: str
    epoch_id: str
    consumer_lane: str
    head_candidate_event_sha256: str
    head_revision: int
    manifest_id: str
    page_count: int
    consumed_entry_count: int
    admitted_entry_count: int
    label_unavailable_count: int
    terminal_entry_chain_sha256: str
    final_page_transition_sha256: str
    ordered_page_root_sha256: str
    local_status: str
    full_consumption_locally_verified: bool
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    optimizer_admission_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _material: dict[str, Any] = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _COMPLETION_TOKEN
            or not all(
                _valid_sha256(value)
                for value in (
                    self.completion_event_sha256,
                    self.completion_id,
                    self.epoch_id,
                    self.head_candidate_event_sha256,
                    self.manifest_id,
                    self.terminal_entry_chain_sha256,
                    self.final_page_transition_sha256,
                    self.ordered_page_root_sha256,
                )
            )
            or min(
                self.page_count,
                self.consumed_entry_count,
                self.admitted_entry_count,
                self.label_unavailable_count,
            )
            < 0
            or self.consumed_entry_count != self.admitted_entry_count + self.label_unavailable_count
            or self.full_consumption_locally_verified is not True
            or self.local_status != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
            or not _authority_is_false(self._material)
        ):
            _fail("PROFILED_COMPLETION_CANDIDATE_RESULT_INVALID")


def _seal(
    unsigned: Mapping[str, Any],
    *,
    identity_field: str,
    auth_field: str,
    domain: str,
    role: str,
    key: bytes,
) -> dict[str, Any]:
    identity = stable_sha256(dict(unsigned))
    signed = {**dict(unsigned), identity_field: identity}
    return {
        **signed,
        auth_field: _auth_tag(domain=domain, role=role, payload=signed, key=key),
    }


def _verify_seal(
    material: Mapping[str, Any],
    *,
    identity_field: str,
    auth_field: str,
    domain: str,
    role: str,
    key: bytes,
    reason: str,
) -> None:
    supplied_tag = material.get(auth_field)
    signed = {name: value for name, value in material.items() if name != auth_field}
    supplied_identity = signed.pop(identity_field, None)
    expected_identity = stable_sha256(signed)
    signed_with_identity = {**signed, identity_field: supplied_identity}
    expected_tag = _auth_tag(
        domain=domain,
        role=role,
        payload=signed_with_identity,
        key=key,
    )
    if (
        supplied_identity != expected_identity
        or not _valid_sha256(supplied_tag)
        or not hmac.compare_digest(expected_tag, cast(str, supplied_tag))
    ):
        _fail(reason)


def _reproduce_prior_high_water(
    *,
    previous_summary: Mapping[str, Any],
    current_summary: Mapping[str, Any],
    feature_ledger: DurableFeatureSnapshotLedger,
    label_archive: DurableCanonical5mLabelArchive,
    namespace: str,
    prior_head_event_sha256: str,
    head_key_id: str,
    head_key: bytes,
) -> dict[str, Any]:
    if type(feature_ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_HEAD_FEATURE_LEDGER_EXACT_TYPE_REQUIRED")
    if type(label_archive) is not DurableCanonical5mLabelArchive:
        _fail("PROFILED_HEAD_LABEL_ARCHIVE_EXACT_TYPE_REQUIRED")
    source_paths = (
        str(feature_ledger.path),
        str(label_archive.path),
    )
    if (
        source_paths
        != (
            previous_summary.get("feature_ledger_path"),
            previous_summary.get("label_archive_path"),
        )
        or source_paths
        != (
            current_summary.get("feature_ledger_path"),
            current_summary.get("label_archive_path"),
        )
        or previous_summary.get("feature_ledger_path_sha256")
        != current_summary.get("feature_ledger_path_sha256")
        or previous_summary.get("label_archive_path_sha256")
        != current_summary.get("label_archive_path_sha256")
    ):
        _fail("PROFILED_HEAD_SOURCE_ROOT_OR_PATH_MIGRATION_FORBIDDEN")
    cutoff = _clock(
        previous_summary.get("observation_time"),
        reason="PROFILED_HEAD_PRIOR_CUTOFF_INVALID",
    )
    try:
        feature_before_report = feature_ledger.verify_integrity_streaming()
        feature_before = feature_ledger_fixed_observation_high_water(
            ledger=feature_ledger,
            report=feature_before_report,
            observation_cutoff=cutoff,
            scan_limit=max(feature_before_report.verified_records, 1),
        )
        label_before_integrity = label_archive.verify_integrity()
        label_before = label_archive_fixed_observation_high_water(
            archive=label_archive,
            integrity=label_before_integrity,
            observation_cutoff=cutoff,
            scan_limit=max(int(label_before_integrity.get("verified_rows") or 0), 1),
        )
        feature_after_report = feature_ledger.verify_integrity_streaming()
        feature_after = feature_ledger_fixed_observation_high_water(
            ledger=feature_ledger,
            report=feature_after_report,
            observation_cutoff=cutoff,
            scan_limit=max(feature_after_report.verified_records, 1),
        )
        label_after_integrity = label_archive.verify_integrity()
        label_after = label_archive_fixed_observation_high_water(
            archive=label_archive,
            integrity=label_after_integrity,
            observation_cutoff=cutoff,
            scan_limit=max(int(label_after_integrity.get("verified_rows") or 0), 1),
        )
    except Exception as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(
            f"PROFILED_HEAD_PRIOR_HIGH_WATER_REPRODUCTION_FAILED:{type(exc).__name__}:{exc}"
        ) from exc
    if feature_before != feature_after or label_before != label_after:
        _fail("PROFILED_HEAD_SOURCE_MOVED_DURING_PRIOR_HIGH_WATER_REPRODUCTION")
    expected_pairs = (
        (
            feature_before.get("high_water_sha256"),
            previous_summary.get("feature_ledger_high_water_sha256"),
        ),
        (
            feature_before.get("verified_records"),
            previous_summary.get("feature_ledger_verified_records"),
        ),
        (
            feature_before.get("authenticated_prefix_head_sequence"),
            previous_summary.get("feature_ledger_prefix_head_sequence"),
        ),
        (
            feature_before.get("archive_chain_sha256"),
            previous_summary.get("feature_ledger_archive_chain_sha256"),
        ),
        (
            feature_before.get("ordered_transaction_receipts_sha256"),
            previous_summary.get("feature_ledger_ordered_receipts_sha256"),
        ),
        (
            label_before.get("high_water_sha256"),
            previous_summary.get("label_archive_high_water_sha256"),
        ),
        (label_before.get("verified_rows"), previous_summary.get("label_archive_verified_rows")),
        (
            label_before.get("verified_max_sequence"),
            previous_summary.get("label_archive_prefix_head_sequence"),
        ),
        (
            label_before.get("archive_chain_sha256"),
            previous_summary.get("label_archive_archive_chain_sha256"),
        ),
        (
            label_before.get("ordered_transaction_receipts_sha256"),
            previous_summary.get("label_archive_ordered_receipts_sha256"),
        ),
    )
    if any(observed != expected for observed, expected in expected_pairs):
        _fail("PROFILED_HEAD_PRIOR_HIGH_WATER_REPRODUCTION_MISMATCH")
    unsigned = {
        "schema_version": PROFILED_OBSERVATION_PRIOR_HIGH_WATER_RECEIPT_V1_SCHEMA_VERSION,
        "mode": "REPRODUCED_PRIOR_FIXED_OBSERVATION_PREFIX",
        "namespace": namespace,
        "prior_head_event_sha256": prior_head_event_sha256,
        "prior_observation_time": previous_summary["observation_time"],
        "feature_ledger_high_water_sha256": feature_before["high_water_sha256"],
        "feature_ledger_verified_records": feature_before["verified_records"],
        "feature_ledger_prefix_head_sequence": feature_before["authenticated_prefix_head_sequence"],
        "feature_ledger_archive_chain_sha256": feature_before["archive_chain_sha256"],
        "feature_ledger_ordered_receipts_sha256": feature_before[
            "ordered_transaction_receipts_sha256"
        ],
        "label_archive_high_water_sha256": label_before["high_water_sha256"],
        "label_archive_verified_rows": label_before["verified_rows"],
        "label_archive_prefix_head_sequence": label_before["verified_max_sequence"],
        "label_archive_archive_chain_sha256": label_before["archive_chain_sha256"],
        "label_archive_ordered_receipts_sha256": label_before[
            "ordered_transaction_receipts_sha256"
        ],
        "head_auth_key_id": head_key_id,
        "local_status": PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        "full_prior_high_water_reproduction_verified": True,
        **_authority_false(),
    }
    return _seal(
        unsigned,
        identity_field="reproduction_receipt_id",
        auth_field="reproduction_auth_tag",
        domain=PROFILED_OBSERVATION_REPRODUCTION_AUTH_DOMAIN,
        role="prior-high-water-reproduction",
        key=head_key,
    )


def _genesis_reproduction_receipt(
    *, namespace: str, head_key_id: str, head_key: bytes
) -> dict[str, Any]:
    unsigned = {
        "schema_version": PROFILED_OBSERVATION_PRIOR_HIGH_WATER_RECEIPT_V1_SCHEMA_VERSION,
        "mode": "GENESIS_NO_PRIOR_HIGH_WATER",
        "namespace": namespace,
        "prior_head_event_sha256": PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
        "head_auth_key_id": head_key_id,
        "local_status": PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        "full_prior_high_water_reproduction_verified": False,
        **_authority_false(),
    }
    return _seal(
        unsigned,
        identity_field="reproduction_receipt_id",
        auth_field="reproduction_auth_tag",
        domain=PROFILED_OBSERVATION_REPRODUCTION_AUTH_DOMAIN,
        role="prior-high-water-reproduction",
        key=head_key,
    )


def _head_from_material(
    *,
    store: ImmutableSourcePayloadStore,
    event_sha256: str,
    event_byte_count: int,
    material: dict[str, Any],
    manifest_key: bytes,
    manifest_key_id: str,
    head_key: bytes,
    head_key_id: str,
    epoch_key: bytes,
    epoch_key_id: str,
) -> LocalProfiledTrainingObservationHeadCandidateV1:
    _verify_seal(
        material,
        identity_field="candidate_id",
        auth_field="head_auth_tag",
        domain=PROFILED_OBSERVATION_HEAD_AUTH_DOMAIN,
        role="manifest-head-candidate",
        key=head_key,
        reason="PROFILED_HEAD_CANDIDATE_AUTHENTICATION_INVALID",
    )
    summary = _validate_manifest_summary(material.get("manifest_summary"))
    try:
        reauthenticated_manifest = authenticate_profiled_training_observation_manifest_v1(
            manifest_path=Path(cast(str, summary["manifest_path"])),
            hmac_key=manifest_key,
            expected_auth_key_id=manifest_key_id,
            expected_manifest_id=cast(str, summary["manifest_id"]),
            expected_observation_time=cast(str, summary["observation_time"]),
        )
    except (ProfiledTrainingObservationManifestV1Error, TypeError, ValueError) as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(
            "PROFILED_HEAD_EMBEDDED_MANIFEST_REAUTHENTICATION_FAILED:" f"{type(exc).__name__}:{exc}"
        ) from exc
    if _manifest_summary(reauthenticated_manifest) != summary:
        _fail("PROFILED_HEAD_EMBEDDED_MANIFEST_SUMMARY_MISMATCH")
    expected_epoch_key_commitment = _epoch_key_commitment(
        key=epoch_key,
        key_id=epoch_key_id,
    )
    if material.get("epoch_auth_key_commitment_sha256") != expected_epoch_key_commitment:
        _fail("PROFILED_HEAD_EPOCH_KEY_COMMITMENT_MISMATCH")
    allowed_consumer_lane = _identifier(
        material.get("allowed_consumer_lane"),
        reason="PROFILED_HEAD_CONSUMER_LANE_INVALID",
    )
    reproduction = material.get("prior_high_water_reproduction_receipt")
    if type(reproduction) is not dict:
        _fail("PROFILED_HEAD_REPRODUCTION_RECEIPT_INVALID")
    _verify_seal(
        cast(dict[str, Any], reproduction),
        identity_field="reproduction_receipt_id",
        auth_field="reproduction_auth_tag",
        domain=PROFILED_OBSERVATION_REPRODUCTION_AUTH_DOMAIN,
        role="prior-high-water-reproduction",
        key=head_key,
        reason="PROFILED_HEAD_REPRODUCTION_RECEIPT_AUTHENTICATION_INVALID",
    )
    revision = material.get("revision")
    if (
        material.get("schema_version") != PROFILED_OBSERVATION_HEAD_CANDIDATE_V1_SCHEMA_VERSION
        or material.get("local_status") != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
        or material.get("local_rollback_limitation")
        != PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION
        or type(revision) is not int
        or revision <= 0
        or material.get("manifest_auth_key_id") != manifest_key_id
        or material.get("head_auth_key_id") != head_key_id
        or material.get("epoch_auth_key_id") != epoch_key_id
        or summary.get("manifest_auth_key_id") != manifest_key_id
        or material.get("manifest_id") != summary.get("manifest_id")
        or material.get("observation_time") != summary.get("observation_time")
        or material.get("full_manifest_authentication_verified") is not True
        or material.get("full_entry_inventory_verified") is not True
        or not _valid_sha256(material.get("previous_head_event_sha256"))
        or not _valid_sha256(material.get("previous_completion_candidate_sha256"))
        or not _authority_is_false(material)
        or reproduction.get("namespace") != material.get("namespace")
        or reproduction.get("prior_head_event_sha256") != material.get("previous_head_event_sha256")
        or reproduction.get("head_auth_key_id") != head_key_id
        or reproduction.get("local_status") != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
        or not _authority_is_false(reproduction)
    ):
        _fail("PROFILED_HEAD_CANDIDATE_CONTRACT_INVALID")
    namespace = _identifier(material.get("namespace"), reason="PROFILED_HEAD_NAMESPACE_INVALID")
    if revision == 1:
        if (
            material.get("previous_head_event_sha256")
            != PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
            or material.get("previous_completion_candidate_sha256")
            != PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
            or reproduction.get("mode") != "GENESIS_NO_PRIOR_HIGH_WATER"
            or reproduction.get("full_prior_high_water_reproduction_verified") is not False
        ):
            _fail("PROFILED_HEAD_GENESIS_CONTRACT_INVALID")
    elif (
        reproduction.get("mode") != "REPRODUCED_PRIOR_FIXED_OBSERVATION_PREFIX"
        or reproduction.get("full_prior_high_water_reproduction_verified") is not True
    ):
        _fail("PROFILED_HEAD_SUCCESSOR_REPRODUCTION_CONTRACT_INVALID")
    return LocalProfiledTrainingObservationHeadCandidateV1(
        staging_store_root=store.root_path,
        candidate_event_sha256=event_sha256,
        candidate_event_byte_count=event_byte_count,
        candidate_id=cast(str, material["candidate_id"]),
        namespace=namespace,
        revision=revision,
        previous_head_event_sha256=cast(str, material["previous_head_event_sha256"]),
        previous_completion_candidate_sha256=cast(
            str, material["previous_completion_candidate_sha256"]
        ),
        manifest_id=cast(str, material["manifest_id"]),
        observation_time=cast(str, material["observation_time"]),
        manifest_auth_key_id=manifest_key_id,
        head_auth_key_id=head_key_id,
        epoch_auth_key_id=epoch_key_id,
        epoch_auth_key_commitment_sha256=expected_epoch_key_commitment,
        allowed_consumer_lane=allowed_consumer_lane,
        local_status=cast(str, material["local_status"]),
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
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _manifest_key_sha256=hashlib.sha256(manifest_key).hexdigest(),
        _head_key_sha256=hashlib.sha256(head_key).hexdigest(),
        _epoch_key_sha256=hashlib.sha256(epoch_key).hexdigest(),
        _material=material,
        _construction_token=_HEAD_TOKEN,
    )


def read_local_profiled_training_observation_head_candidate_v1(
    *,
    staging_store: ImmutableSourcePayloadStore,
    candidate_event_sha256: str,
    candidate_event_byte_count: int,
    manifest_hmac_key: bytes | bytearray | memoryview,
    manifest_auth_key_id: str,
    head_hmac_key: bytes | bytearray | memoryview,
    head_auth_key_id: str,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
    expected_namespace: str,
) -> LocalProfiledTrainingObservationHeadCandidateV1:
    store = _exact_store(staging_store)
    manifest_key, manifest_key_id, head_key, head_key_id, epoch_key, epoch_key_id = _keys_and_ids(
        manifest_key=manifest_hmac_key,
        manifest_key_id=manifest_auth_key_id,
        head_key=head_hmac_key,
        head_key_id=head_auth_key_id,
        epoch_key=epoch_hmac_key,
        epoch_key_id=epoch_auth_key_id,
    )
    namespace = _identifier(expected_namespace, reason="PROFILED_HEAD_NAMESPACE_INVALID")
    material = _get_event(store, candidate_event_sha256, candidate_event_byte_count)
    result = _head_from_material(
        store=store,
        event_sha256=candidate_event_sha256,
        event_byte_count=candidate_event_byte_count,
        material=material,
        manifest_key=manifest_key,
        manifest_key_id=manifest_key_id,
        head_key=head_key,
        head_key_id=head_key_id,
        epoch_key=epoch_key,
        epoch_key_id=epoch_key_id,
    )
    if result.namespace != namespace:
        _fail("PROFILED_HEAD_EXPECTED_NAMESPACE_MISMATCH")
    return result


def _validated_prior_head(
    candidate: object,
    *,
    store: ImmutableSourcePayloadStore,
    manifest_key: bytes,
    manifest_key_id: str,
    head_key: bytes,
    head_key_id: str,
    epoch_key: bytes,
    epoch_key_id: str,
    namespace: str,
) -> LocalProfiledTrainingObservationHeadCandidateV1:
    if type(candidate) is not LocalProfiledTrainingObservationHeadCandidateV1:
        _fail("PROFILED_HEAD_PRIOR_CANDIDATE_EXACT_TYPE_REQUIRED")
    prior = cast(LocalProfiledTrainingObservationHeadCandidateV1, candidate)
    return read_local_profiled_training_observation_head_candidate_v1(
        staging_store=store,
        candidate_event_sha256=prior.candidate_event_sha256,
        candidate_event_byte_count=prior.candidate_event_byte_count,
        manifest_hmac_key=manifest_key,
        manifest_auth_key_id=manifest_key_id,
        head_hmac_key=head_key,
        head_auth_key_id=head_key_id,
        epoch_hmac_key=epoch_key,
        epoch_auth_key_id=epoch_key_id,
        expected_namespace=namespace,
    )


def stage_profiled_training_observation_head_candidate_v1(
    *,
    manifest_path: Path,
    expected_manifest_id: str,
    expected_observation_time: str,
    feature_ledger: DurableFeatureSnapshotLedger,
    label_archive: DurableCanonical5mLabelArchive,
    staging_store: ImmutableSourcePayloadStore,
    namespace: str,
    consumer_lane: str,
    manifest_hmac_key: bytes | bytearray | memoryview,
    manifest_auth_key_id: str,
    head_hmac_key: bytes | bytearray | memoryview,
    head_auth_key_id: str,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
    previous_head_candidate: LocalProfiledTrainingObservationHeadCandidateV1 | None = None,
    previous_completion_candidate: LocalProfiledTrainingObservationCompletionCandidateV1
    | None = None,
) -> LocalProfiledTrainingObservationHeadCandidateV1:
    """Stage a deterministic local head candidate; never call a witness."""

    store = _exact_store(staging_store)
    namespace_text = _identifier(namespace, reason="PROFILED_HEAD_NAMESPACE_INVALID")
    lane = _identifier(consumer_lane, reason="PROFILED_HEAD_CONSUMER_LANE_INVALID")
    manifest_key, manifest_key_id, head_key, head_key_id, epoch_key, epoch_key_id = _keys_and_ids(
        manifest_key=manifest_hmac_key,
        manifest_key_id=manifest_auth_key_id,
        head_key=head_hmac_key,
        head_key_id=head_auth_key_id,
        epoch_key=epoch_hmac_key,
        epoch_key_id=epoch_auth_key_id,
    )
    try:
        authenticated = authenticate_profiled_training_observation_manifest_v1(
            manifest_path=manifest_path,
            hmac_key=manifest_key,
            expected_auth_key_id=manifest_key_id,
            expected_manifest_id=expected_manifest_id,
            expected_observation_time=expected_observation_time,
        )
    except ProfiledTrainingObservationManifestV1Error as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(
            f"PROFILED_HEAD_MANIFEST_AUTHENTICATION_FAILED:{exc}"
        ) from exc
    summary = _manifest_summary(authenticated)
    if (
        type(feature_ledger) is not DurableFeatureSnapshotLedger
        or type(label_archive) is not DurableCanonical5mLabelArchive
        or str(feature_ledger.path) != summary["feature_ledger_path"]
        or str(label_archive.path) != summary["label_archive_path"]
    ):
        _fail("PROFILED_HEAD_CURRENT_SOURCE_PATH_BINDING_INVALID")
    if previous_head_candidate is None:
        if previous_completion_candidate is not None:
            _fail("PROFILED_HEAD_GENESIS_PREVIOUS_COMPLETION_FORBIDDEN")
        revision = 1
        previous_head_sha256 = PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
        previous_completion_sha256 = PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
        reproduction = _genesis_reproduction_receipt(
            namespace=namespace_text,
            head_key_id=head_key_id,
            head_key=head_key,
        )
    else:
        prior = _validated_prior_head(
            previous_head_candidate,
            store=store,
            manifest_key=manifest_key,
            manifest_key_id=manifest_key_id,
            head_key=head_key,
            head_key_id=head_key_id,
            epoch_key=epoch_key,
            epoch_key_id=epoch_key_id,
            namespace=namespace_text,
        )
        prior_summary = _validate_manifest_summary(prior._material["manifest_summary"])
        if prior.allowed_consumer_lane != lane:
            _fail("PROFILED_HEAD_CONSUMER_LANE_POLICY_MISMATCH")
        if summary["manifest_id"] == prior_summary["manifest_id"]:
            if summary != prior_summary:
                _fail("PROFILED_HEAD_REPLAY_MANIFEST_SUMMARY_CONFLICT")
            return prior
        current_cutoff = _clock(
            summary["observation_time"], reason="PROFILED_HEAD_CURRENT_CUTOFF_INVALID"
        )
        prior_cutoff = _clock(
            prior_summary["observation_time"], reason="PROFILED_HEAD_PRIOR_CUTOFF_INVALID"
        )
        if current_cutoff == prior_cutoff:
            _fail("PROFILED_HEAD_SAME_CUTOFF_DIFFERENT_MANIFEST_EQUIVOCATION")
        if current_cutoff < prior_cutoff:
            _fail("PROFILED_HEAD_MANIFEST_CUTOFF_ROLLBACK")
        if previous_completion_candidate is None:
            _fail("PROFILED_HEAD_PRIOR_FULL_CONSUMPTION_REQUIRED")
        completion = read_local_profiled_training_observation_completion_candidate_v1(
            staging_store=store,
            completion_event_sha256=previous_completion_candidate.completion_event_sha256,
            completion_event_byte_count=(previous_completion_candidate.completion_event_byte_count),
            epoch_hmac_key=epoch_key,
            epoch_auth_key_id=epoch_key_id,
        )
        if (
            completion.head_candidate_event_sha256 != prior.candidate_event_sha256
            or completion.head_revision != prior.revision
            or completion.manifest_id != prior.manifest_id
        ):
            _fail("PROFILED_HEAD_PRIOR_COMPLETION_BINDING_MISMATCH")
        if completion.consumer_lane != prior.allowed_consumer_lane:
            _fail("PROFILED_HEAD_PRIOR_COMPLETION_LANE_MISMATCH")
        if (
            summary["feature_ledger_path"] != prior_summary["feature_ledger_path"]
            or summary["feature_ledger_path_sha256"] != prior_summary["feature_ledger_path_sha256"]
            or summary["label_archive_path"] != prior_summary["label_archive_path"]
            or summary["label_archive_path_sha256"] != prior_summary["label_archive_path_sha256"]
        ):
            _fail("PROFILED_HEAD_SOURCE_ROOT_OR_PATH_MIGRATION_FORBIDDEN")
        for current_count, prior_count in (
            (
                summary["feature_ledger_verified_records"],
                prior_summary["feature_ledger_verified_records"],
            ),
            (
                summary["feature_ledger_prefix_head_sequence"],
                prior_summary["feature_ledger_prefix_head_sequence"],
            ),
            (
                summary["label_archive_verified_rows"],
                prior_summary["label_archive_verified_rows"],
            ),
            (
                summary["label_archive_prefix_head_sequence"],
                prior_summary["label_archive_prefix_head_sequence"],
            ),
        ):
            if current_count < prior_count:
                _fail("PROFILED_HEAD_SOURCE_HIGH_WATER_ROLLBACK")
        reproduction = _reproduce_prior_high_water(
            previous_summary=prior_summary,
            current_summary=summary,
            feature_ledger=feature_ledger,
            label_archive=label_archive,
            namespace=namespace_text,
            prior_head_event_sha256=prior.candidate_event_sha256,
            head_key_id=head_key_id,
            head_key=head_key,
        )
        revision = prior.revision + 1
        previous_head_sha256 = prior.candidate_event_sha256
        previous_completion_sha256 = completion.completion_event_sha256
    unsigned = {
        "schema_version": PROFILED_OBSERVATION_HEAD_CANDIDATE_V1_SCHEMA_VERSION,
        "namespace": namespace_text,
        "revision": revision,
        "previous_head_event_sha256": previous_head_sha256,
        "previous_completion_candidate_sha256": previous_completion_sha256,
        "manifest_id": summary["manifest_id"],
        "observation_time": summary["observation_time"],
        "manifest_auth_key_id": manifest_key_id,
        "head_auth_key_id": head_key_id,
        "epoch_auth_key_id": epoch_key_id,
        "epoch_auth_key_commitment_sha256": _epoch_key_commitment(
            key=epoch_key,
            key_id=epoch_key_id,
        ),
        "allowed_consumer_lane": lane,
        "manifest_summary": summary,
        "prior_high_water_reproduction_receipt": reproduction,
        "full_manifest_authentication_verified": True,
        "full_entry_inventory_verified": True,
        "local_status": PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        "local_rollback_limitation": PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION,
        **_authority_false(),
    }
    material = _seal(
        unsigned,
        identity_field="candidate_id",
        auth_field="head_auth_tag",
        domain=PROFILED_OBSERVATION_HEAD_AUTH_DOMAIN,
        role="manifest-head-candidate",
        key=head_key,
    )
    event_sha256, byte_count = _put_event(store, material)
    return _head_from_material(
        store=store,
        event_sha256=event_sha256,
        event_byte_count=byte_count,
        material=material,
        manifest_key=manifest_key,
        manifest_key_id=manifest_key_id,
        head_key=head_key,
        head_key_id=head_key_id,
        epoch_key=epoch_key,
        epoch_key_id=epoch_key_id,
    )


def _epoch_from_material(
    *,
    store: ImmutableSourcePayloadStore,
    event_sha256: str,
    event_byte_count: int,
    material: dict[str, Any],
    epoch_key: bytes,
    epoch_key_id: str,
) -> LocalProfiledTrainingObservationConsumptionEpochV1:
    _verify_seal(
        material,
        identity_field="epoch_id",
        auth_field="epoch_auth_tag",
        domain=PROFILED_OBSERVATION_EPOCH_AUTH_DOMAIN,
        role="full-consumption-epoch",
        key=epoch_key,
        reason="PROFILED_EPOCH_CANDIDATE_AUTHENTICATION_INVALID",
    )
    summary = _validate_manifest_summary(material.get("manifest_summary"))
    total = material.get("total_profiled_samples")
    admitted = material.get("admitted_example_count")
    unavailable = material.get("label_unavailable_count")
    page_size = material.get("page_size")
    if (
        material.get("schema_version") != PROFILED_OBSERVATION_EPOCH_CANDIDATE_V1_SCHEMA_VERSION
        or material.get("epoch_auth_key_id") != epoch_key_id
        or type(total) is not int
        or type(admitted) is not int
        or type(unavailable) is not int
        or total != admitted + unavailable
        or type(page_size) is not int
        or not 0 < page_size <= MAX_PROFILED_OBSERVATION_PAGE_ROWS
        or material.get("manifest_id") != summary.get("manifest_id")
        or material.get("observation_time") != summary.get("observation_time")
        or total != summary.get("total_profiled_samples")
        or admitted != summary.get("admitted_example_count")
        or unavailable != summary.get("label_unavailable_count")
        or material.get("terminal_entry_chain_sha256") != summary.get("entry_chain_head_sha256")
        or not _valid_sha256(material.get("head_candidate_event_sha256"))
        or type(material.get("head_revision")) is not int
        or material.get("head_revision") <= 0
        or material.get("local_status") != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
        or material.get("local_rollback_limitation")
        != PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION
        or not _authority_is_false(material)
    ):
        _fail("PROFILED_EPOCH_CANDIDATE_CONTRACT_INVALID")
    lane = _identifier(material.get("consumer_lane"), reason="PROFILED_EPOCH_LANE_INVALID")
    head_lane = _identifier(
        material.get("head_allowed_consumer_lane"),
        reason="PROFILED_EPOCH_HEAD_LANE_INVALID",
    )
    if lane != head_lane:
        _fail("PROFILED_EPOCH_HEAD_LANE_MISMATCH")
    return LocalProfiledTrainingObservationConsumptionEpochV1(
        staging_store_root=store.root_path,
        epoch_event_sha256=event_sha256,
        epoch_event_byte_count=event_byte_count,
        epoch_id=cast(str, material["epoch_id"]),
        consumer_lane=lane,
        head_candidate_event_sha256=cast(str, material["head_candidate_event_sha256"]),
        head_revision=cast(int, material["head_revision"]),
        manifest_id=cast(str, material["manifest_id"]),
        observation_time=cast(str, material["observation_time"]),
        manifest_auth_key_id=cast(str, material["manifest_auth_key_id"]),
        head_auth_key_id=cast(str, material["head_auth_key_id"]),
        epoch_auth_key_id=epoch_key_id,
        page_size=page_size,
        total_profiled_samples=total,
        admitted_example_count=admitted,
        label_unavailable_count=unavailable,
        terminal_entry_chain_sha256=cast(str, material["terminal_entry_chain_sha256"]),
        local_status=cast(str, material["local_status"]),
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _material=material,
        _construction_token=_EPOCH_TOKEN,
    )


def read_local_profiled_training_observation_consumption_epoch_v1(
    *,
    staging_store: ImmutableSourcePayloadStore,
    epoch_event_sha256: str,
    epoch_event_byte_count: int,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
) -> LocalProfiledTrainingObservationConsumptionEpochV1:
    store = _exact_store(staging_store)
    key = _key(epoch_hmac_key, reason="PROFILED_EPOCH_HMAC_KEY_INVALID")
    key_id = _identifier(epoch_auth_key_id, reason="PROFILED_EPOCH_KEY_ID_INVALID")
    material = _get_event(store, epoch_event_sha256, epoch_event_byte_count)
    return _epoch_from_material(
        store=store,
        event_sha256=epoch_event_sha256,
        event_byte_count=epoch_event_byte_count,
        material=material,
        epoch_key=key,
        epoch_key_id=key_id,
    )


def stage_profiled_training_observation_consumption_epoch_v1(
    *,
    head_candidate: LocalProfiledTrainingObservationHeadCandidateV1,
    staging_store: ImmutableSourcePayloadStore,
    consumer_lane: str,
    page_size: int,
    manifest_hmac_key: bytes | bytearray | memoryview,
    manifest_auth_key_id: str,
    head_hmac_key: bytes | bytearray | memoryview,
    head_auth_key_id: str,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
) -> LocalProfiledTrainingObservationConsumptionEpochV1:
    store = _exact_store(staging_store)
    lane = _identifier(consumer_lane, reason="PROFILED_EPOCH_LANE_INVALID")
    if type(page_size) is not int or not 0 < page_size <= MAX_PROFILED_OBSERVATION_PAGE_ROWS:
        _fail("PROFILED_EPOCH_PAGE_SIZE_INVALID")
    manifest_key, manifest_key_id, head_key, head_key_id, epoch_key, epoch_key_id = _keys_and_ids(
        manifest_key=manifest_hmac_key,
        manifest_key_id=manifest_auth_key_id,
        head_key=head_hmac_key,
        head_key_id=head_auth_key_id,
        epoch_key=epoch_hmac_key,
        epoch_key_id=epoch_auth_key_id,
    )
    head = _validated_prior_head(
        head_candidate,
        store=store,
        manifest_key=manifest_key,
        manifest_key_id=manifest_key_id,
        head_key=head_key,
        head_key_id=head_key_id,
        epoch_key=epoch_key,
        epoch_key_id=epoch_key_id,
        namespace=head_candidate.namespace,
    )
    summary = _validate_manifest_summary(head._material["manifest_summary"])
    if lane != head.allowed_consumer_lane:
        _fail("PROFILED_EPOCH_HEAD_LANE_MISMATCH")
    unsigned = {
        "schema_version": PROFILED_OBSERVATION_EPOCH_CANDIDATE_V1_SCHEMA_VERSION,
        "consumer_lane": lane,
        "head_allowed_consumer_lane": head.allowed_consumer_lane,
        "head_candidate_event_sha256": head.candidate_event_sha256,
        "head_revision": head.revision,
        "manifest_id": head.manifest_id,
        "observation_time": head.observation_time,
        "manifest_auth_key_id": manifest_key_id,
        "head_auth_key_id": head_key_id,
        "epoch_auth_key_id": epoch_key_id,
        "page_size": page_size,
        "total_profiled_samples": summary["total_profiled_samples"],
        "admitted_example_count": summary["admitted_example_count"],
        "label_unavailable_count": summary["label_unavailable_count"],
        "entry_chain_genesis_sha256": summary["entry_chain_genesis_sha256"],
        "terminal_entry_chain_sha256": summary["entry_chain_head_sha256"],
        "ordered_entry_identities_sha256": summary["ordered_entry_identities_sha256"],
        "manifest_summary": summary,
        "local_status": PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        "local_rollback_limitation": PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION,
        **_authority_false(),
    }
    material = _seal(
        unsigned,
        identity_field="epoch_id",
        auth_field="epoch_auth_tag",
        domain=PROFILED_OBSERVATION_EPOCH_AUTH_DOMAIN,
        role="full-consumption-epoch",
        key=epoch_key,
    )
    event_sha256, byte_count = _put_event(store, material)
    return _epoch_from_material(
        store=store,
        event_sha256=event_sha256,
        event_byte_count=byte_count,
        material=material,
        epoch_key=epoch_key,
        epoch_key_id=epoch_key_id,
    )


def _page_transition(previous: str, receipt_id: str) -> str:
    if not _valid_sha256(previous) or not _valid_sha256(receipt_id):
        _fail("PROFILED_PAGE_TRANSITION_INPUT_INVALID")
    return hashlib.sha256(
        b"profiled_training_observation_page_transition_v1\0"
        + bytes.fromhex(previous)
        + bytes.fromhex(receipt_id)
    ).hexdigest()


def _ordered_page_root(*, previous_root: str, page_entries_sha256: str, page_sequence: int) -> str:
    if (
        not _valid_sha256(previous_root)
        or not _valid_sha256(page_entries_sha256)
        or type(page_sequence) is not int
        or page_sequence <= 0
    ):
        _fail("PROFILED_PAGE_ROOT_INPUT_INVALID")
    return hashlib.sha256(
        b"profiled_training_observation_ordered_page_root_v1\0"
        + bytes.fromhex(previous_root)
        + page_sequence.to_bytes(8, "big", signed=False)
        + bytes.fromhex(page_entries_sha256)
    ).hexdigest()


def _page_receipt_from_material(
    *,
    store: ImmutableSourcePayloadStore,
    event_sha256: str,
    event_byte_count: int,
    material: dict[str, Any],
    epoch_key: bytes,
    epoch_key_id: str,
) -> LocalProfiledTrainingObservationPageReceiptV1:
    supplied_tag = material.get("page_auth_tag")
    signed = {name: value for name, value in material.items() if name != "page_auth_tag"}
    base = {
        name: value
        for name, value in signed.items()
        if name
        not in {
            "page_receipt_id",
            "page_transition_sha256",
            "ordered_page_root_sha256",
        }
    }
    if (
        material.get("page_receipt_id") != stable_sha256(base)
        or not _valid_sha256(supplied_tag)
        or not hmac.compare_digest(
            _auth_tag(
                domain=PROFILED_OBSERVATION_PAGE_AUTH_DOMAIN,
                role="consumption-page",
                payload=signed,
                key=epoch_key,
            ),
            cast(str, supplied_tag),
        )
    ):
        _fail("PROFILED_PAGE_RECEIPT_AUTHENTICATION_INVALID")
    integer_fields = (
        "page_sequence",
        "page_start_ordinal",
        "page_end_ordinal",
        "scanned_entry_count",
        "admitted_entry_count",
        "label_unavailable_count",
        "cumulative_scanned_entry_count",
        "cumulative_admitted_entry_count",
        "cumulative_label_unavailable_count",
    )
    if any(type(material.get(name)) is not int for name in integer_fields):
        _fail("PROFILED_PAGE_RECEIPT_COUNTS_INVALID")
    page_sequence = cast(int, material["page_sequence"])
    if (
        material.get("schema_version") != PROFILED_OBSERVATION_PAGE_RECEIPT_V1_SCHEMA_VERSION
        or material.get("epoch_auth_key_id") != epoch_key_id
        or page_sequence <= 0
        or cast(int, material["scanned_entry_count"]) <= 0
        or material.get("scanned_entry_count")
        != cast(int, material["admitted_entry_count"])
        + cast(int, material["label_unavailable_count"])
        or material.get("cumulative_scanned_entry_count")
        != cast(int, material["cumulative_admitted_entry_count"])
        + cast(int, material["cumulative_label_unavailable_count"])
        or material.get("page_end_ordinal")
        != cast(int, material["page_start_ordinal"])
        + cast(int, material["scanned_entry_count"])
        - 1
        or not all(
            _valid_sha256(material.get(name))
            for name in (
                "epoch_id",
                "ordered_page_entries_sha256",
                "page_start_previous_entry_chain_sha256",
                "page_end_entry_chain_sha256",
                "previous_page_receipt_event_sha256",
                "previous_page_transition_sha256",
                "previous_ordered_page_root_sha256",
                "page_transition_sha256",
                "ordered_page_root_sha256",
            )
        )
        or material.get("page_transition_sha256")
        != _page_transition(
            cast(str, material["previous_page_transition_sha256"]),
            cast(str, material["page_receipt_id"]),
        )
        or material.get("ordered_page_root_sha256")
        != _ordered_page_root(
            previous_root=cast(str, material["previous_ordered_page_root_sha256"]),
            page_entries_sha256=cast(str, material["ordered_page_entries_sha256"]),
            page_sequence=page_sequence,
        )
        or type(material.get("has_more_manifest_entries")) is not bool
        or material.get("local_status") != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
        or not _authority_is_false(material)
    ):
        _fail("PROFILED_PAGE_RECEIPT_CONTRACT_INVALID")
    verified_at = cast(str, material.get("verified_at"))
    _clock(verified_at, reason="PROFILED_PAGE_RECEIPT_CLOCK_INVALID")
    return LocalProfiledTrainingObservationPageReceiptV1(
        staging_store_root=store.root_path,
        page_receipt_event_sha256=event_sha256,
        page_receipt_event_byte_count=event_byte_count,
        page_receipt_id=cast(str, material["page_receipt_id"]),
        epoch_id=cast(str, material["epoch_id"]),
        page_sequence=page_sequence,
        page_start_ordinal=cast(int, material["page_start_ordinal"]),
        page_end_ordinal=cast(int, material["page_end_ordinal"]),
        scanned_entry_count=cast(int, material["scanned_entry_count"]),
        admitted_entry_count=cast(int, material["admitted_entry_count"]),
        label_unavailable_count=cast(int, material["label_unavailable_count"]),
        cumulative_scanned_entry_count=cast(int, material["cumulative_scanned_entry_count"]),
        cumulative_admitted_entry_count=cast(int, material["cumulative_admitted_entry_count"]),
        cumulative_label_unavailable_count=cast(
            int, material["cumulative_label_unavailable_count"]
        ),
        page_start_previous_entry_chain_sha256=cast(
            str, material["page_start_previous_entry_chain_sha256"]
        ),
        page_end_entry_chain_sha256=cast(str, material["page_end_entry_chain_sha256"]),
        previous_page_transition_sha256=cast(str, material["previous_page_transition_sha256"]),
        page_transition_sha256=cast(str, material["page_transition_sha256"]),
        ordered_page_root_sha256=cast(str, material["ordered_page_root_sha256"]),
        has_more_manifest_entries=cast(bool, material["has_more_manifest_entries"]),
        verified_at=verified_at,
        local_status=cast(str, material["local_status"]),
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _material=material,
        _construction_token=_PAGE_RECEIPT_TOKEN,
    )


def read_local_profiled_training_observation_page_receipt_v1(
    *,
    staging_store: ImmutableSourcePayloadStore,
    page_receipt_event_sha256: str,
    page_receipt_event_byte_count: int,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
) -> LocalProfiledTrainingObservationPageReceiptV1:
    store = _exact_store(staging_store)
    key = _key(epoch_hmac_key, reason="PROFILED_EPOCH_HMAC_KEY_INVALID")
    key_id = _identifier(epoch_auth_key_id, reason="PROFILED_EPOCH_KEY_ID_INVALID")
    material = _get_event(store, page_receipt_event_sha256, page_receipt_event_byte_count)
    return _page_receipt_from_material(
        store=store,
        event_sha256=page_receipt_event_sha256,
        event_byte_count=page_receipt_event_byte_count,
        material=material,
        epoch_key=key,
        epoch_key_id=key_id,
    )


def stage_profiled_training_observation_page_receipt_v1(
    *,
    epoch: LocalProfiledTrainingObservationConsumptionEpochV1,
    authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    staging_store: ImmutableSourcePayloadStore,
    verified_at: str,
    manifest_hmac_key: bytes | bytearray | memoryview,
    manifest_auth_key_id: str,
    head_hmac_key: bytes | bytearray | memoryview,
    head_auth_key_id: str,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
    previous_page_receipt: LocalProfiledTrainingObservationPageReceiptV1 | None = None,
    expected_after_ordinal: int | None = None,
    replay_page_receipt: LocalProfiledTrainingObservationPageReceiptV1 | None = None,
) -> LocalProfiledTrainingObservationPageReceiptV1:
    """Authenticate and stage the next contiguous bounded consumption page."""

    store = _exact_store(staging_store)
    manifest_key, manifest_key_id, head_key, head_key_id, epoch_key, epoch_key_id = _keys_and_ids(
        manifest_key=manifest_hmac_key,
        manifest_key_id=manifest_auth_key_id,
        head_key=head_hmac_key,
        head_key_id=head_auth_key_id,
        epoch_key=epoch_hmac_key,
        epoch_key_id=epoch_auth_key_id,
    )
    if type(epoch) is not LocalProfiledTrainingObservationConsumptionEpochV1:
        _fail("PROFILED_PAGE_EPOCH_EXACT_TYPE_REQUIRED")
    verified_epoch = read_local_profiled_training_observation_consumption_epoch_v1(
        staging_store=store,
        epoch_event_sha256=epoch.epoch_event_sha256,
        epoch_event_byte_count=epoch.epoch_event_byte_count,
        epoch_hmac_key=epoch_key,
        epoch_auth_key_id=epoch_key_id,
    )
    if (
        verified_epoch.manifest_auth_key_id != manifest_key_id
        or verified_epoch.head_auth_key_id != head_key_id
    ):
        _fail("PROFILED_PAGE_EPOCH_ROLE_KEY_BINDING_MISMATCH")
    if type(authenticated_manifest) is not AuthenticatedProfiledTrainingObservationManifestV1:
        _fail("PROFILED_PAGE_AUTHENTICATED_MANIFEST_EXACT_TYPE_REQUIRED")
    if _manifest_summary(authenticated_manifest) != _validate_manifest_summary(
        verified_epoch._material["manifest_summary"]
    ):
        _fail("PROFILED_PAGE_MANIFEST_SUMMARY_BINDING_MISMATCH")
    verified_clock = _clock(verified_at, reason="PROFILED_PAGE_VERIFIED_AT_INVALID")
    if verified_clock < _clock(
        authenticated_manifest.factory_wall_clock_observed_at,
        reason="PROFILED_PAGE_FACTORY_CLOCK_INVALID",
    ):
        _fail("PROFILED_PAGE_VERIFIED_BEFORE_MANIFEST_AUTHENTICATION")
    if previous_page_receipt is None:
        after_ordinal = 0
        page_sequence = 1
        previous_receipt_event_sha256 = PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256
        previous_transition = PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256
        previous_root = PROFILED_OBSERVATION_ORDERED_PAGE_ROOT_GENESIS_SHA256
        previous_end_chain = PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
        cumulative_scanned = 0
        cumulative_admitted = 0
        cumulative_unavailable = 0
    else:
        if type(previous_page_receipt) is not LocalProfiledTrainingObservationPageReceiptV1:
            _fail("PROFILED_PAGE_PRIOR_RECEIPT_EXACT_TYPE_REQUIRED")
        previous = read_local_profiled_training_observation_page_receipt_v1(
            staging_store=store,
            page_receipt_event_sha256=(previous_page_receipt.page_receipt_event_sha256),
            page_receipt_event_byte_count=(previous_page_receipt.page_receipt_event_byte_count),
            epoch_hmac_key=epoch_key,
            epoch_auth_key_id=epoch_key_id,
        )
        if previous.epoch_id != verified_epoch.epoch_id:
            _fail("PROFILED_PAGE_PRIOR_RECEIPT_EPOCH_MISMATCH")
        if previous.has_more_manifest_entries is not True:
            _fail("PROFILED_PAGE_RECEIPT_AFTER_TERMINAL_FORBIDDEN")
        after_ordinal = previous.page_end_ordinal
        page_sequence = previous.page_sequence + 1
        previous_receipt_event_sha256 = previous.page_receipt_event_sha256
        previous_transition = previous.page_transition_sha256
        previous_root = previous.ordered_page_root_sha256
        previous_end_chain = previous.page_end_entry_chain_sha256
        cumulative_scanned = previous.cumulative_scanned_entry_count
        cumulative_admitted = previous.cumulative_admitted_entry_count
        cumulative_unavailable = previous.cumulative_label_unavailable_count
    if page_sequence > MAX_PROFILED_OBSERVATION_CONSUMPTION_PAGES:
        _fail("PROFILED_PAGE_COUNT_BOUND_EXCEEDED")
    if expected_after_ordinal is not None and (
        type(expected_after_ordinal) is not int or expected_after_ordinal != after_ordinal
    ):
        _fail("PROFILED_PAGE_EXPECTED_CURSOR_GAP_OR_OVERLAP")
    if after_ordinal >= verified_epoch.total_profiled_samples:
        _fail("PROFILED_PAGE_NO_REMAINING_MANIFEST_ENTRIES")
    try:
        page = authenticate_profiled_training_observation_inventory_page_v1(
            authenticated_manifest=authenticated_manifest,
            hmac_key=manifest_key,
            after_ordinal=after_ordinal,
            limit=verified_epoch.page_size,
        )
    except ProfiledTrainingObservationManifestV1Error as exc:
        raise ProfiledTrainingObservationManifestHeadV1Error(
            f"PROFILED_PAGE_MANIFEST_PAGE_AUTHENTICATION_FAILED:{exc}"
        ) from exc
    if (
        page.scanned_entry_count <= 0
        or page.page_start_previous_entry_chain_sha256 != previous_end_chain
    ):
        _fail("PROFILED_PAGE_CONTIGUOUS_ENTRY_CHAIN_INVALID")
    base = {
        "schema_version": PROFILED_OBSERVATION_PAGE_RECEIPT_V1_SCHEMA_VERSION,
        "epoch_id": verified_epoch.epoch_id,
        "epoch_event_sha256": verified_epoch.epoch_event_sha256,
        "epoch_auth_key_id": epoch_key_id,
        "page_sequence": page_sequence,
        "page_start_ordinal": page.page_start_ordinal,
        "page_end_ordinal": page.page_end_ordinal,
        "scanned_entry_count": page.scanned_entry_count,
        "admitted_entry_count": page.admitted_entry_count,
        "label_unavailable_count": page.label_unavailable_count,
        "cumulative_scanned_entry_count": (cumulative_scanned + page.scanned_entry_count),
        "cumulative_admitted_entry_count": (cumulative_admitted + page.admitted_entry_count),
        "cumulative_label_unavailable_count": (
            cumulative_unavailable + page.label_unavailable_count
        ),
        "ordered_page_entries_sha256": page.ordered_page_entries_sha256,
        "page_start_previous_entry_chain_sha256": (page.page_start_previous_entry_chain_sha256),
        "page_end_entry_chain_sha256": page.page_end_entry_chain_sha256,
        "previous_page_receipt_event_sha256": previous_receipt_event_sha256,
        "previous_page_transition_sha256": previous_transition,
        "previous_ordered_page_root_sha256": previous_root,
        "has_more_manifest_entries": page.has_more_manifest_entries,
        "verified_at": verified_at,
        "local_status": PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        **_authority_false(),
    }
    receipt_id = stable_sha256(base)
    material_without_auth = {
        **base,
        "page_receipt_id": receipt_id,
        "page_transition_sha256": _page_transition(previous_transition, receipt_id),
        "ordered_page_root_sha256": _ordered_page_root(
            previous_root=previous_root,
            page_entries_sha256=page.ordered_page_entries_sha256,
            page_sequence=page_sequence,
        ),
    }
    material = {
        **material_without_auth,
        "page_auth_tag": _auth_tag(
            domain=PROFILED_OBSERVATION_PAGE_AUTH_DOMAIN,
            role="consumption-page",
            payload=material_without_auth,
            key=epoch_key,
        ),
    }
    # The receipt id intentionally excludes the derived transition/root fields.
    # Verify with the same rule before publishing rather than the generic seal.
    prospective_payload = _canonical_json(
        material,
        reason="PROFILED_HEAD_EVENT_JSON_INVALID",
    ).encode("ascii")
    event_sha256 = hashlib.sha256(prospective_payload).hexdigest()
    byte_count = len(prospective_payload)
    result = _page_receipt_from_material(
        store=store,
        event_sha256=event_sha256,
        event_byte_count=byte_count,
        material=material,
        epoch_key=epoch_key,
        epoch_key_id=epoch_key_id,
    )
    if replay_page_receipt is not None:
        replay = read_local_profiled_training_observation_page_receipt_v1(
            staging_store=store,
            page_receipt_event_sha256=replay_page_receipt.page_receipt_event_sha256,
            page_receipt_event_byte_count=(replay_page_receipt.page_receipt_event_byte_count),
            epoch_hmac_key=epoch_key,
            epoch_auth_key_id=epoch_key_id,
        )
        if (
            replay.epoch_id != result.epoch_id
            or replay.page_sequence != result.page_sequence
            or replay.page_start_ordinal != result.page_start_ordinal
        ):
            _fail("PROFILED_PAGE_REPLAY_BINDING_MISMATCH")
        if replay.page_receipt_event_sha256 != result.page_receipt_event_sha256:
            _fail("PROFILED_PAGE_CONFLICTING_REPLAY")
        return replay
    stored_sha256, stored_byte_count = _put_event(store, material)
    if (stored_sha256, stored_byte_count) != (event_sha256, byte_count):
        _fail("PROFILED_PAGE_CAS_ADDRESS_MISMATCH")
    return result


def _completion_from_material(
    *,
    store: ImmutableSourcePayloadStore,
    event_sha256: str,
    event_byte_count: int,
    material: dict[str, Any],
    epoch_key: bytes,
    epoch_key_id: str,
) -> LocalProfiledTrainingObservationCompletionCandidateV1:
    _verify_seal(
        material,
        identity_field="completion_id",
        auth_field="completion_auth_tag",
        domain=PROFILED_OBSERVATION_COMPLETION_AUTH_DOMAIN,
        role="full-consumption-completion",
        key=epoch_key,
        reason="PROFILED_COMPLETION_CANDIDATE_AUTHENTICATION_INVALID",
    )
    integer_fields = (
        "head_revision",
        "page_count",
        "consumed_entry_count",
        "admitted_entry_count",
        "label_unavailable_count",
    )
    if any(type(material.get(name)) is not int for name in integer_fields):
        _fail("PROFILED_COMPLETION_COUNTS_INVALID")
    if (
        material.get("schema_version")
        != PROFILED_OBSERVATION_COMPLETION_CANDIDATE_V1_SCHEMA_VERSION
        or material.get("epoch_auth_key_id") != epoch_key_id
        or cast(int, material["head_revision"]) <= 0
        or not 0 <= cast(int, material["page_count"]) <= MAX_PROFILED_OBSERVATION_CONSUMPTION_PAGES
        or material.get("consumed_entry_count")
        != cast(int, material["admitted_entry_count"])
        + cast(int, material["label_unavailable_count"])
        or not all(
            _valid_sha256(material.get(name))
            for name in (
                "epoch_id",
                "epoch_event_sha256",
                "head_candidate_event_sha256",
                "manifest_id",
                "terminal_entry_chain_sha256",
                "final_page_receipt_event_sha256",
                "final_page_transition_sha256",
                "ordered_page_root_sha256",
            )
        )
        or material.get("full_consumption_locally_verified") is not True
        or material.get("local_status") != PROFILED_OBSERVATION_LOCAL_STAGING_STATUS
        or material.get("local_rollback_limitation")
        != PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION
        or not _authority_is_false(material)
    ):
        _fail("PROFILED_COMPLETION_CANDIDATE_CONTRACT_INVALID")
    consumer_lane = _identifier(
        material.get("consumer_lane"),
        reason="PROFILED_COMPLETION_LANE_INVALID",
    )
    return LocalProfiledTrainingObservationCompletionCandidateV1(
        staging_store_root=store.root_path,
        completion_event_sha256=event_sha256,
        completion_event_byte_count=event_byte_count,
        completion_id=cast(str, material["completion_id"]),
        epoch_id=cast(str, material["epoch_id"]),
        consumer_lane=consumer_lane,
        head_candidate_event_sha256=cast(str, material["head_candidate_event_sha256"]),
        head_revision=cast(int, material["head_revision"]),
        manifest_id=cast(str, material["manifest_id"]),
        page_count=cast(int, material["page_count"]),
        consumed_entry_count=cast(int, material["consumed_entry_count"]),
        admitted_entry_count=cast(int, material["admitted_entry_count"]),
        label_unavailable_count=cast(int, material["label_unavailable_count"]),
        terminal_entry_chain_sha256=cast(str, material["terminal_entry_chain_sha256"]),
        final_page_transition_sha256=cast(str, material["final_page_transition_sha256"]),
        ordered_page_root_sha256=cast(str, material["ordered_page_root_sha256"]),
        local_status=cast(str, material["local_status"]),
        full_consumption_locally_verified=True,
        external_monotonic_manifest_head_verified=False,
        full_consumption_external_ack_verified=False,
        optimizer_admission_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _material=material,
        _construction_token=_COMPLETION_TOKEN,
    )


def read_local_profiled_training_observation_completion_candidate_v1(
    *,
    staging_store: ImmutableSourcePayloadStore,
    completion_event_sha256: str,
    completion_event_byte_count: int,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
) -> LocalProfiledTrainingObservationCompletionCandidateV1:
    store = _exact_store(staging_store)
    key = _key(epoch_hmac_key, reason="PROFILED_EPOCH_HMAC_KEY_INVALID")
    key_id = _identifier(epoch_auth_key_id, reason="PROFILED_EPOCH_KEY_ID_INVALID")
    material = _get_event(store, completion_event_sha256, completion_event_byte_count)
    return _completion_from_material(
        store=store,
        event_sha256=completion_event_sha256,
        event_byte_count=completion_event_byte_count,
        material=material,
        epoch_key=key,
        epoch_key_id=key_id,
    )


def stage_profiled_training_observation_completion_candidate_v1(
    *,
    epoch: LocalProfiledTrainingObservationConsumptionEpochV1,
    staging_store: ImmutableSourcePayloadStore,
    epoch_hmac_key: bytes | bytearray | memoryview,
    epoch_auth_key_id: str,
    final_page_receipt: LocalProfiledTrainingObservationPageReceiptV1 | None,
) -> LocalProfiledTrainingObservationCompletionCandidateV1:
    """Stage a local exact-consumption completion; no external ack is implied."""

    store = _exact_store(staging_store)
    key = _key(epoch_hmac_key, reason="PROFILED_EPOCH_HMAC_KEY_INVALID")
    key_id = _identifier(epoch_auth_key_id, reason="PROFILED_EPOCH_KEY_ID_INVALID")
    if type(epoch) is not LocalProfiledTrainingObservationConsumptionEpochV1:
        _fail("PROFILED_COMPLETION_EPOCH_EXACT_TYPE_REQUIRED")
    verified_epoch = read_local_profiled_training_observation_consumption_epoch_v1(
        staging_store=store,
        epoch_event_sha256=epoch.epoch_event_sha256,
        epoch_event_byte_count=epoch.epoch_event_byte_count,
        epoch_hmac_key=key,
        epoch_auth_key_id=key_id,
    )
    if verified_epoch.total_profiled_samples == 0:
        if final_page_receipt is not None:
            _fail("PROFILED_COMPLETION_ZERO_INVENTORY_PAGE_FORBIDDEN")
        page_count = 0
        consumed = admitted = unavailable = 0
        terminal_chain = PROFILED_OBSERVATION_ENTRY_CHAIN_GENESIS
        final_receipt_sha256 = PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
        final_transition = PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256
        ordered_root = PROFILED_OBSERVATION_ORDERED_PAGE_ROOT_GENESIS_SHA256
    else:
        if type(final_page_receipt) is not LocalProfiledTrainingObservationPageReceiptV1:
            _fail("PROFILED_COMPLETION_FINAL_PAGE_REQUIRED")
        final_page = read_local_profiled_training_observation_page_receipt_v1(
            staging_store=store,
            page_receipt_event_sha256=final_page_receipt.page_receipt_event_sha256,
            page_receipt_event_byte_count=(final_page_receipt.page_receipt_event_byte_count),
            epoch_hmac_key=key,
            epoch_auth_key_id=key_id,
        )
        if (
            final_page.epoch_id != verified_epoch.epoch_id
            or final_page.has_more_manifest_entries is not False
            or final_page.cumulative_scanned_entry_count != verified_epoch.total_profiled_samples
            or final_page.cumulative_admitted_entry_count != verified_epoch.admitted_example_count
            or final_page.cumulative_label_unavailable_count
            != verified_epoch.label_unavailable_count
            or final_page.page_end_ordinal != verified_epoch.total_profiled_samples
            or final_page.page_end_entry_chain_sha256 != verified_epoch.terminal_entry_chain_sha256
        ):
            _fail("PROFILED_COMPLETION_FINAL_PAGE_CONTRACT_INVALID")
        page_count = final_page.page_sequence
        consumed = final_page.cumulative_scanned_entry_count
        admitted = final_page.cumulative_admitted_entry_count
        unavailable = final_page.cumulative_label_unavailable_count
        terminal_chain = final_page.page_end_entry_chain_sha256
        final_receipt_sha256 = final_page.page_receipt_event_sha256
        final_transition = final_page.page_transition_sha256
        ordered_root = final_page.ordered_page_root_sha256
    unsigned = {
        "schema_version": PROFILED_OBSERVATION_COMPLETION_CANDIDATE_V1_SCHEMA_VERSION,
        "epoch_id": verified_epoch.epoch_id,
        "epoch_event_sha256": verified_epoch.epoch_event_sha256,
        "epoch_auth_key_id": key_id,
        "consumer_lane": verified_epoch.consumer_lane,
        "head_candidate_event_sha256": (verified_epoch.head_candidate_event_sha256),
        "head_revision": verified_epoch.head_revision,
        "manifest_id": verified_epoch.manifest_id,
        "page_count": page_count,
        "consumed_entry_count": consumed,
        "admitted_entry_count": admitted,
        "label_unavailable_count": unavailable,
        "terminal_entry_chain_sha256": terminal_chain,
        "final_page_receipt_event_sha256": final_receipt_sha256,
        "final_page_transition_sha256": final_transition,
        "ordered_page_root_sha256": ordered_root,
        "full_consumption_locally_verified": True,
        "local_status": PROFILED_OBSERVATION_LOCAL_STAGING_STATUS,
        "local_rollback_limitation": PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION,
        **_authority_false(),
    }
    material = _seal(
        unsigned,
        identity_field="completion_id",
        auth_field="completion_auth_tag",
        domain=PROFILED_OBSERVATION_COMPLETION_AUTH_DOMAIN,
        role="full-consumption-completion",
        key=key,
    )
    event_sha256, byte_count = _put_event(store, material)
    return _completion_from_material(
        store=store,
        event_sha256=event_sha256,
        event_byte_count=byte_count,
        material=material,
        epoch_key=key,
        epoch_key_id=key_id,
    )


__all__ = [
    "MAX_PROFILED_OBSERVATION_CONSUMPTION_PAGES",
    "LocalProfiledTrainingObservationCompletionCandidateV1",
    "LocalProfiledTrainingObservationConsumptionEpochV1",
    "LocalProfiledTrainingObservationHeadCandidateV1",
    "LocalProfiledTrainingObservationPageReceiptV1",
    "PROFILED_OBSERVATION_LOCAL_ROLLBACK_LIMITATION",
    "PROFILED_OBSERVATION_LOCAL_STAGING_STATUS",
    "ProfiledTrainingObservationExternalWitnessAppendReceiptV1",
    "ProfiledTrainingObservationExternalWitnessEventV1",
    "ProfiledTrainingObservationExternalWitnessV1",
    "ProfiledTrainingObservationManifestHeadV1Error",
    "read_local_profiled_training_observation_completion_candidate_v1",
    "read_local_profiled_training_observation_consumption_epoch_v1",
    "read_local_profiled_training_observation_head_candidate_v1",
    "read_local_profiled_training_observation_page_receipt_v1",
    "stage_profiled_training_observation_completion_candidate_v1",
    "stage_profiled_training_observation_consumption_epoch_v1",
    "stage_profiled_training_observation_head_candidate_v1",
    "stage_profiled_training_observation_page_receipt_v1",
]
