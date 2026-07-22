"""Authenticated crash cursor for profiled observation coordination.

The immutable manifest/head/epoch/page/completion artifacts are already stored
in SQLite or content-addressed storage.  This module persists only the exact
addresses needed to resume their ordered construction.  Each state snapshot is
HMAC-authenticated, chained to its predecessor, durably stored in immutable
CAS, and selected through an atomically replaced authenticated pointer.

The pointer is intentionally local and therefore retains the explicit local
rollback limitation.  External monotonicity belongs to the independent witness
journal.  No state in this module grants optimizer, checkpoint, model,
prediction, paper, live, order, execution, or runtime authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FeatureSnapshotLedgerError,
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    ProfiledTrainingExternalWitnessRuntimeResultV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256,
    PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256,
    PROFILED_OBSERVATION_ORDERED_PAGE_ROOT_GENESIS_SHA256,
    PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256,
    LocalProfiledTrainingObservationCompletionCandidateV1,
    LocalProfiledTrainingObservationConsumptionEpochV1,
    LocalProfiledTrainingObservationHeadCandidateV1,
    LocalProfiledTrainingObservationPageReceiptV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    ProfiledTrainingObservationManifestBuildV1,
)

PROFILED_OBSERVATION_COORDINATOR_STATE_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_state_v1"
)
PROFILED_OBSERVATION_COORDINATOR_POINTER_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_pointer_v1"
)
PROFILED_OBSERVATION_COORDINATOR_INTEGRITY_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_integrity_v1"
)
PROFILED_OBSERVATION_COORDINATOR_STATE_AUTH_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-coordinator-state/v1"
)
PROFILED_OBSERVATION_COORDINATOR_POINTER_AUTH_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-coordinator-pointer/v1"
)
PROFILED_OBSERVATION_COORDINATOR_KEY_COMMITMENT_DOMAIN: Final = (
    "v2/native-trainer/profiled-observation-coordinator-key-commitment/v1"
)
PROFILED_OBSERVATION_COORDINATOR_GENESIS_STATE_EVENT_SHA256: Final = hashlib.sha256(
    b"v2/native-trainer/profiled-observation-coordinator-state-genesis/v1"
).hexdigest()
PROFILED_OBSERVATION_COORDINATOR_LOCAL_ROLLBACK_LIMITATION: Final = (
    "AUTHENTICATED_LOCAL_POINTER_CAN_BE_ROLLED_BACK_BY_HOST_ADMIN;"
    "INDEPENDENT_WITNESS_JOURNAL_IS_REQUIRED_FOR_EXTERNAL_MONOTONICITY"
)

PROFILED_OBSERVATION_COORDINATOR_PREPARED: Final = "PREPARED"
PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED: Final = "MANIFEST_STAGED"
PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED: Final = "HEAD_STAGED"
PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED: Final = "HEAD_ANCHORED"
PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED: Final = "EPOCH_STAGED"
PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED: Final = "PAGE_STAGED"
PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED: Final = "LOCAL_COMPLETION_STAGED"

# Serialization and crash-journal resource bounds only. They do not select
# markets, samples, regimes, leverage, margin, risk, or optimizer behavior.
MIN_PROFILED_OBSERVATION_COORDINATOR_HMAC_KEY_BYTES: Final = 32
MAX_PROFILED_OBSERVATION_COORDINATOR_STATE_BYTES: Final = 128 * 1024
MAX_PROFILED_OBSERVATION_COORDINATOR_POINTER_BYTES: Final = 16 * 1024
MAX_PROFILED_OBSERVATION_COORDINATOR_TRANSITIONS: Final = 1_000_000

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_CURSOR_TOKEN = object()
_INTEGRITY_TOKEN = object()

_PHASE_RANK: Final = {
    PROFILED_OBSERVATION_COORDINATOR_PREPARED: 0,
    PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED: 1,
    PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED: 2,
    PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED: 3,
    PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED: 4,
    PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED: 5,
    PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED: 6,
}

_AUTHORITY_FIELDS: Final = (
    "external_monotonic_manifest_head_verified",
    "full_consumption_external_ack_verified",
    "optimizer_admission_authorized",
    "checkpoint_write_authorized",
    "model_write_authorized",
    "prediction_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "order_submission_authorized",
    "execution_authorized",
    "runtime_wired",
)

_STATE_FIELDS: Final = {
    "schema_version",
    "state_auth_key_id",
    "namespace",
    "consumer_lane",
    "transition_sequence",
    "previous_state_event_sha256",
    "cycle_id",
    "publisher_status_sha256",
    "phase",
    "observation_time",
    "factory_wall_clock_observed_at",
    "manifest_auth_key_id",
    "manifest_auth_key_commitment_sha256",
    "head_auth_key_id",
    "head_auth_key_commitment_sha256",
    "epoch_auth_key_id",
    "epoch_auth_key_commitment_sha256",
    "state_auth_key_commitment_sha256",
    "manifest_path",
    "manifest_id",
    "total_profiled_samples",
    "admitted_example_count",
    "label_unavailable_count",
    "head_event_sha256",
    "head_event_byte_count",
    "head_revision",
    "witness_operation_id",
    "witness_id",
    "witness_public_key_sha256",
    "witness_anchored_sequence",
    "witness_event_sha256",
    "signed_head_durably_anchored",
    "epoch_event_sha256",
    "epoch_event_byte_count",
    "epoch_id",
    "page_receipt_event_sha256",
    "page_receipt_event_byte_count",
    "page_sequence",
    "page_end_ordinal",
    "page_has_more_manifest_entries",
    "page_transition_sha256",
    "ordered_page_root_sha256",
    "completion_event_sha256",
    "completion_event_byte_count",
    "completion_id",
    "prior_completed_head_event_sha256",
    "prior_completed_head_event_byte_count",
    "prior_completed_completion_event_sha256",
    "prior_completed_completion_event_byte_count",
    "local_rollback_limitation",
    *_AUTHORITY_FIELDS,
    "state_id",
    "state_auth_tag",
}

_POINTER_FIELDS: Final = {
    "schema_version",
    "state_auth_key_id",
    "namespace",
    "consumer_lane",
    "state_event_sha256",
    "state_event_byte_count",
    "transition_sequence",
    "cycle_id",
    "pointer_id",
    "pointer_auth_tag",
}


class ProfiledTrainingObservationCoordinatorStateV1Error(RuntimeError):
    """The local coordinator cursor failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingObservationCoordinatorStateV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _sha256(value: object, *, reason: str) -> str:
    if not _valid_sha256(value):
        _fail(reason)
    return cast(str, value)


def _identifier(value: object, *, reason: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _positive_integer(value: object, *, reason: str, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        _fail(reason)
    return value


def _clock(value: object, *, reason: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if canonical != value:
        _fail(reason)
    return value


def _absolute_path(value: Path, *, reason: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        _fail(reason)
    normalized = Path(os.path.normpath(str(value)))
    if normalized != value or "\x00" in str(value):
        _fail(reason)
    return value


def _key(value: bytes | bytearray | memoryview) -> bytes:
    if type(value) not in {bytes, bytearray, memoryview}:
        _fail("PROFILED_COORDINATOR_STATE_HMAC_KEY_INVALID")
    material = bytes(value)
    if len(material) < MIN_PROFILED_OBSERVATION_COORDINATOR_HMAC_KEY_BYTES:
        _fail("PROFILED_COORDINATOR_STATE_HMAC_KEY_INVALID")
    return material


def _key_commitment(*, role: str, key_id: str, key: bytes) -> str:
    role_text = _identifier(role, reason="PROFILED_COORDINATOR_KEY_ROLE_INVALID")
    key_id_text = _identifier(key_id, reason="PROFILED_COORDINATOR_ROLE_KEY_ID_INVALID")
    if type(key) is not bytes or len(key) < MIN_PROFILED_OBSERVATION_COORDINATOR_HMAC_KEY_BYTES:
        _fail("PROFILED_COORDINATOR_ROLE_KEY_INVALID")
    return hashlib.sha256(
        PROFILED_OBSERVATION_COORDINATOR_KEY_COMMITMENT_DOMAIN.encode("ascii")
        + b"\0"
        + role_text.encode("ascii")
        + b"\0"
        + key_id_text.encode("ascii")
        + b"\0"
        + key
    ).hexdigest()


def _canonical_json_bytes(value: object, *, maximum_bytes: int, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ProfiledTrainingObservationCoordinatorStateV1Error(reason) from exc
    if not encoded or len(encoded) > maximum_bytes:
        _fail(reason)
    return encoded


def _strict_json(raw: bytes, *, maximum_bytes: int, reason: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > maximum_bytes:
        _fail(reason)

    def reject_constant(value: str) -> NoReturn:
        _fail(f"{reason}:NONFINITE:{value}")

    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if type(name) is not str or name in result:
                _fail(f"{reason}:DUPLICATE_OR_INVALID_KEY")
            result[name] = value
        return result

    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=reject_duplicate,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProfiledTrainingObservationCoordinatorStateV1Error(reason) from exc
    if (
        type(value) is not dict
        or _canonical_json_bytes(value, maximum_bytes=maximum_bytes, reason=reason) != raw
    ):
        _fail(reason)
    return cast(dict[str, Any], value)


def _stable_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        _canonical_json_bytes(
            dict(value),
            maximum_bytes=MAX_PROFILED_OBSERVATION_COORDINATOR_STATE_BYTES,
            reason="PROFILED_COORDINATOR_STATE_CANONICALIZATION_FAILED",
        )
    ).hexdigest()


def _auth_tag(*, domain: str, role: str, payload: Mapping[str, Any], key: bytes) -> str:
    message = (
        domain.encode("ascii")
        + b"\0"
        + role.encode("ascii")
        + b"\0"
        + _canonical_json_bytes(
            dict(payload),
            maximum_bytes=MAX_PROFILED_OBSERVATION_COORDINATOR_STATE_BYTES,
            reason="PROFILED_COORDINATOR_STATE_AUTH_CANONICALIZATION_FAILED",
        )
    )
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _authority_false() -> dict[str, bool]:
    return {name: False for name in _AUTHORITY_FIELDS}


def _authority_is_false(material: Mapping[str, Any]) -> bool:
    return all(
        type(material.get(name)) is bool and material.get(name) is False
        for name in _AUTHORITY_FIELDS
    )


def _optional_address(
    material: Mapping[str, Any],
    *,
    sha_name: str,
    count_name: str,
    required: bool,
    reason: str,
) -> tuple[str | None, int | None]:
    sha = material.get(sha_name)
    count = material.get(count_name)
    if sha is None and count is None and not required:
        return None, None
    if not _valid_sha256(sha) or type(count) is not int or count <= 0:
        _fail(reason)
    return cast(str, sha), count


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationCoordinatorCursorV1:
    state_event_sha256: str
    state_event_byte_count: int
    transition_sequence: int
    previous_state_event_sha256: str
    cycle_id: str
    publisher_status_sha256: str
    namespace: str
    consumer_lane: str
    phase: str
    observation_time: str
    factory_wall_clock_observed_at: str
    manifest_auth_key_id: str
    manifest_auth_key_commitment_sha256: str
    head_auth_key_id: str
    head_auth_key_commitment_sha256: str
    epoch_auth_key_id: str
    epoch_auth_key_commitment_sha256: str
    state_auth_key_commitment_sha256: str
    manifest_path: Path | None
    manifest_id: str | None
    total_profiled_samples: int | None
    admitted_example_count: int | None
    label_unavailable_count: int | None
    head_event_sha256: str | None
    head_event_byte_count: int | None
    head_revision: int | None
    witness_operation_id: str | None
    witness_id: str | None
    witness_public_key_sha256: str | None
    witness_anchored_sequence: int | None
    witness_event_sha256: str | None
    signed_head_durably_anchored: bool
    epoch_event_sha256: str | None
    epoch_event_byte_count: int | None
    epoch_id: str | None
    page_receipt_event_sha256: str | None
    page_receipt_event_byte_count: int | None
    page_sequence: int | None
    page_end_ordinal: int | None
    page_has_more_manifest_entries: bool | None
    page_transition_sha256: str | None
    ordered_page_root_sha256: str | None
    completion_event_sha256: str | None
    completion_event_byte_count: int | None
    completion_id: str | None
    prior_completed_head_event_sha256: str | None
    prior_completed_head_event_byte_count: int | None
    prior_completed_completion_event_sha256: str | None
    prior_completed_completion_event_byte_count: int | None
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
            self._construction_token is not _CURSOR_TOKEN
            or not _valid_sha256(self.state_event_sha256)
            or self.state_event_byte_count <= 0
            or self.transition_sequence <= 0
            or not _valid_sha256(self.previous_state_event_sha256)
            or not _valid_sha256(self.cycle_id)
            or not _valid_sha256(self.publisher_status_sha256)
            or not all(
                _valid_sha256(value)
                for value in (
                    self.state_auth_key_commitment_sha256,
                    self.manifest_auth_key_commitment_sha256,
                    self.head_auth_key_commitment_sha256,
                    self.epoch_auth_key_commitment_sha256,
                )
            )
            or self.phase not in _PHASE_RANK
            or not _authority_is_false(self._material)
        ):
            _fail("PROFILED_COORDINATOR_CURSOR_RESULT_INVALID")


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationCoordinatorIntegrityV1:
    schema_version: str
    transition_count: int
    current_transition_sequence: int
    current_state_event_sha256: str
    current_cycle_id: str
    current_phase: str
    complete_chain_verified: bool
    external_monotonic_manifest_head_verified: bool = False
    full_consumption_external_ack_verified: bool = False
    optimizer_admission_authorized: bool = False
    checkpoint_write_authorized: bool = False
    model_write_authorized: bool = False
    prediction_authorized: bool = False
    paper_trading_authorized: bool = False
    live_execution_authorized: bool = False
    order_submission_authorized: bool = False
    execution_authorized: bool = False
    runtime_wired: bool = False
    _construction_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._construction_token is not _INTEGRITY_TOKEN
            or self.schema_version != PROFILED_OBSERVATION_COORDINATOR_INTEGRITY_V1_SCHEMA_VERSION
            or self.transition_count <= 0
            or self.current_transition_sequence != self.transition_count
            or not _valid_sha256(self.current_state_event_sha256)
            or not _valid_sha256(self.current_cycle_id)
            or self.current_phase not in _PHASE_RANK
            or self.complete_chain_verified is not True
            or any(
                type(value) is not bool or value
                for value in (
                    self.external_monotonic_manifest_head_verified,
                    self.full_consumption_external_ack_verified,
                    self.optimizer_admission_authorized,
                    self.checkpoint_write_authorized,
                    self.model_write_authorized,
                    self.prediction_authorized,
                    self.paper_trading_authorized,
                    self.live_execution_authorized,
                    self.order_submission_authorized,
                    self.execution_authorized,
                    self.runtime_wired,
                )
            )
        ):
            _fail("PROFILED_COORDINATOR_INTEGRITY_RESULT_INVALID")


class ProfiledTrainingObservationCoordinatorStateStoreV1:
    """Single-writer authenticated pointer into immutable state snapshots."""

    __slots__ = (
        "_consumer_lane",
        "_epoch_auth_key_commitment_sha256",
        "_epoch_auth_key_id",
        "_hmac_key",
        "_head_auth_key_commitment_sha256",
        "_head_auth_key_id",
        "_lease_target_path",
        "_manifest_auth_key_commitment_sha256",
        "_manifest_auth_key_id",
        "_namespace",
        "_pointer_path",
        "_state_auth_key_commitment_sha256",
        "_state_auth_key_id",
        "_store",
    )

    def __init__(
        self,
        *,
        pointer_path: Path,
        immutable_store: ImmutableSourcePayloadStore,
        namespace: str,
        consumer_lane: str,
        state_auth_key_id: str,
        state_hmac_key: bytes | bytearray | memoryview,
        manifest_auth_key_id: str,
        manifest_hmac_key: bytes | bytearray | memoryview,
        head_auth_key_id: str,
        head_hmac_key: bytes | bytearray | memoryview,
        epoch_auth_key_id: str,
        epoch_hmac_key: bytes | bytearray | memoryview,
    ) -> None:
        self._pointer_path = _absolute_path(
            pointer_path,
            reason="PROFILED_COORDINATOR_POINTER_PATH_INVALID",
        )
        if type(immutable_store) is not ImmutableSourcePayloadStore:
            _fail("PROFILED_COORDINATOR_STATE_CAS_EXACT_TYPE_REQUIRED")
        self._store = immutable_store
        self._namespace = _identifier(
            namespace,
            reason="PROFILED_COORDINATOR_NAMESPACE_INVALID",
        )
        self._consumer_lane = _identifier(
            consumer_lane,
            reason="PROFILED_COORDINATOR_CONSUMER_LANE_INVALID",
        )
        role_ids = (
            _identifier(
                state_auth_key_id,
                reason="PROFILED_COORDINATOR_STATE_AUTH_KEY_ID_INVALID",
            ),
            _identifier(
                manifest_auth_key_id,
                reason="PROFILED_COORDINATOR_MANIFEST_AUTH_KEY_ID_INVALID",
            ),
            _identifier(
                head_auth_key_id,
                reason="PROFILED_COORDINATOR_HEAD_AUTH_KEY_ID_INVALID",
            ),
            _identifier(
                epoch_auth_key_id,
                reason="PROFILED_COORDINATOR_EPOCH_AUTH_KEY_ID_INVALID",
            ),
        )
        role_keys = (
            _key(state_hmac_key),
            _key(manifest_hmac_key),
            _key(head_hmac_key),
            _key(epoch_hmac_key),
        )
        if len(set(role_ids)) != 4 or len(set(role_keys)) != 4:
            _fail("PROFILED_COORDINATOR_ROLE_KEY_REUSE_FORBIDDEN")
        self._state_auth_key_id = role_ids[0]
        self._manifest_auth_key_id = role_ids[1]
        self._head_auth_key_id = role_ids[2]
        self._epoch_auth_key_id = role_ids[3]
        self._hmac_key = role_keys[0]
        self._state_auth_key_commitment_sha256 = _key_commitment(
            role="state",
            key_id=role_ids[0],
            key=role_keys[0],
        )
        self._manifest_auth_key_commitment_sha256 = _key_commitment(
            role="manifest",
            key_id=role_ids[1],
            key=role_keys[1],
        )
        self._head_auth_key_commitment_sha256 = _key_commitment(
            role="head",
            key_id=role_ids[2],
            key=role_keys[2],
        )
        self._epoch_auth_key_commitment_sha256 = _key_commitment(
            role="epoch",
            key_id=role_ids[3],
            key=role_keys[3],
        )
        self._lease_target_path = self._pointer_path.with_name(
            self._pointer_path.name + ".lease-target"
        )

    @property
    def pointer_path(self) -> Path:
        return self._pointer_path

    @property
    def immutable_store(self) -> ImmutableSourcePayloadStore:
        return self._store

    @property
    def lease_target_path(self) -> Path:
        return self._lease_target_path

    @contextmanager
    def writer_lease(
        self,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> Iterator[FeatureSnapshotWriterLease]:
        acquired_here = writer_lease is None
        try:
            held = (
                FeatureSnapshotWriterLease.acquire(self._lease_target_path)
                if writer_lease is None
                else FeatureSnapshotWriterLease.require_exact(
                    writer_lease,
                    self._lease_target_path,
                )
            )
        except FeatureSnapshotLedgerError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_WRITER_LEASE_INVALID"
            ) from exc
        try:
            yield held
            FeatureSnapshotWriterLease.require_exact(held, self._lease_target_path)
        except FeatureSnapshotLedgerError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_WRITER_LEASE_INVALID"
            ) from exc
        finally:
            if acquired_here:
                held.release()

    def _require_lease(self, writer_lease: FeatureSnapshotWriterLease) -> None:
        try:
            FeatureSnapshotWriterLease.require_exact(writer_lease, self._lease_target_path)
        except FeatureSnapshotLedgerError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_WRITER_LEASE_INVALID"
            ) from exc

    def _validate_state_material(self, material: dict[str, Any]) -> None:
        if set(material) != _STATE_FIELDS:
            _fail("PROFILED_COORDINATOR_STATE_FIELDS_INVALID")
        auth_tag = material.get("state_auth_tag")
        state_id = material.get("state_id")
        signed = {name: value for name, value in material.items() if name != "state_auth_tag"}
        unsigned = {name: value for name, value in signed.items() if name != "state_id"}
        if (
            material.get("schema_version")
            != PROFILED_OBSERVATION_COORDINATOR_STATE_V1_SCHEMA_VERSION
            or material.get("state_auth_key_id") != self._state_auth_key_id
            or material.get("namespace") != self._namespace
            or material.get("consumer_lane") != self._consumer_lane
            or not _valid_sha256(state_id)
            or state_id != _stable_sha256(unsigned)
            or not _valid_sha256(auth_tag)
            or not hmac.compare_digest(
                cast(str, auth_tag),
                _auth_tag(
                    domain=PROFILED_OBSERVATION_COORDINATOR_STATE_AUTH_DOMAIN,
                    role="coordinator-state",
                    payload=signed,
                    key=self._hmac_key,
                ),
            )
            or material.get("local_rollback_limitation")
            != PROFILED_OBSERVATION_COORDINATOR_LOCAL_ROLLBACK_LIMITATION
            or not _authority_is_false(material)
        ):
            _fail("PROFILED_COORDINATOR_STATE_AUTHENTICATION_INVALID")
        sequence = _positive_integer(
            material.get("transition_sequence"),
            reason="PROFILED_COORDINATOR_TRANSITION_SEQUENCE_INVALID",
        )
        if sequence > MAX_PROFILED_OBSERVATION_COORDINATOR_TRANSITIONS:
            _fail("PROFILED_COORDINATOR_TRANSITION_RESOURCE_LIMIT_EXCEEDED")
        previous = _sha256(
            material.get("previous_state_event_sha256"),
            reason="PROFILED_COORDINATOR_PREVIOUS_STATE_EVENT_INVALID",
        )
        if (
            sequence == 1
            and previous != PROFILED_OBSERVATION_COORDINATOR_GENESIS_STATE_EVENT_SHA256
        ):
            _fail("PROFILED_COORDINATOR_GENESIS_PREDECESSOR_INVALID")
        if sequence > 1 and previous == PROFILED_OBSERVATION_COORDINATOR_GENESIS_STATE_EVENT_SHA256:
            _fail("PROFILED_COORDINATOR_NON_GENESIS_PREDECESSOR_INVALID")
        cycle_id = _sha256(material.get("cycle_id"), reason="PROFILED_COORDINATOR_CYCLE_ID_INVALID")
        publisher_status_sha256 = _sha256(
            material.get("publisher_status_sha256"),
            reason="PROFILED_COORDINATOR_PUBLISHER_STATUS_SHA256_INVALID",
        )
        observation = _clock(
            material.get("observation_time"),
            reason="PROFILED_COORDINATOR_OBSERVATION_TIME_INVALID",
        )
        factory = _clock(
            material.get("factory_wall_clock_observed_at"),
            reason="PROFILED_COORDINATOR_FACTORY_CLOCK_INVALID",
        )
        if datetime.fromisoformat(observation.replace("Z", "+00:00")) > datetime.fromisoformat(
            factory.replace("Z", "+00:00")
        ):
            _fail("PROFILED_COORDINATOR_OBSERVATION_AFTER_FACTORY_CLOCK")
        expected_cycle_id = _stable_sha256(
            {
                "schema_version": ("profiled_training_observation_coordinator_cycle_identity_v1"),
                "namespace": self._namespace,
                "consumer_lane": self._consumer_lane,
                "publisher_status_sha256": publisher_status_sha256,
                "observation_time": observation,
                "factory_wall_clock_observed_at": factory,
            }
        )
        if cycle_id != expected_cycle_id:
            _fail("PROFILED_COORDINATOR_CYCLE_ID_BINDING_INVALID")
        expected_role_bindings = {
            "state_auth_key_id": self._state_auth_key_id,
            "state_auth_key_commitment_sha256": (self._state_auth_key_commitment_sha256),
            "manifest_auth_key_id": self._manifest_auth_key_id,
            "manifest_auth_key_commitment_sha256": (self._manifest_auth_key_commitment_sha256),
            "head_auth_key_id": self._head_auth_key_id,
            "head_auth_key_commitment_sha256": self._head_auth_key_commitment_sha256,
            "epoch_auth_key_id": self._epoch_auth_key_id,
            "epoch_auth_key_commitment_sha256": self._epoch_auth_key_commitment_sha256,
        }
        if any(material.get(name) != value for name, value in expected_role_bindings.items()):
            _fail("PROFILED_COORDINATOR_ROLE_KEY_BINDING_MISMATCH")
        phase = material.get("phase")
        if phase not in _PHASE_RANK:
            _fail("PROFILED_COORDINATOR_PHASE_INVALID")
        rank = _PHASE_RANK[cast(str, phase)]
        prior_head = _optional_address(
            material,
            sha_name="prior_completed_head_event_sha256",
            count_name="prior_completed_head_event_byte_count",
            required=False,
            reason="PROFILED_COORDINATOR_PRIOR_HEAD_ADDRESS_INVALID",
        )
        prior_completion = _optional_address(
            material,
            sha_name="prior_completed_completion_event_sha256",
            count_name="prior_completed_completion_event_byte_count",
            required=False,
            reason="PROFILED_COORDINATOR_PRIOR_COMPLETION_ADDRESS_INVALID",
        )
        if (prior_head[0] is None) != (prior_completion[0] is None):
            _fail("PROFILED_COORDINATOR_PRIOR_COMPLETION_PAIR_INVALID")

        manifest_fields = (
            material.get("manifest_path"),
            material.get("manifest_id"),
            material.get("total_profiled_samples"),
            material.get("admitted_example_count"),
            material.get("label_unavailable_count"),
        )
        if rank < _PHASE_RANK[PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED]:
            if any(value is not None for value in manifest_fields):
                _fail("PROFILED_COORDINATOR_PREMATURE_MANIFEST_FIELDS")
        else:
            path_raw = material.get("manifest_path")
            if type(path_raw) is not str:
                _fail("PROFILED_COORDINATOR_MANIFEST_PATH_INVALID")
            _absolute_path(Path(path_raw), reason="PROFILED_COORDINATOR_MANIFEST_PATH_INVALID")
            _sha256(material.get("manifest_id"), reason="PROFILED_COORDINATOR_MANIFEST_ID_INVALID")
            total = _positive_integer(
                material.get("total_profiled_samples"),
                reason="PROFILED_COORDINATOR_MANIFEST_COUNTS_INVALID",
                allow_zero=True,
            )
            admitted = _positive_integer(
                material.get("admitted_example_count"),
                reason="PROFILED_COORDINATOR_MANIFEST_COUNTS_INVALID",
                allow_zero=True,
            )
            unavailable = _positive_integer(
                material.get("label_unavailable_count"),
                reason="PROFILED_COORDINATOR_MANIFEST_COUNTS_INVALID",
                allow_zero=True,
            )
            if total != admitted + unavailable:
                _fail("PROFILED_COORDINATOR_MANIFEST_COUNTS_INVALID")

        head_required = rank >= _PHASE_RANK[PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED]
        head_address = _optional_address(
            material,
            sha_name="head_event_sha256",
            count_name="head_event_byte_count",
            required=head_required,
            reason="PROFILED_COORDINATOR_HEAD_ADDRESS_INVALID",
        )
        head_revision = material.get("head_revision")
        if head_required:
            _positive_integer(head_revision, reason="PROFILED_COORDINATOR_HEAD_REVISION_INVALID")
        elif head_address[0] is not None or head_revision is not None:
            _fail("PROFILED_COORDINATOR_PREMATURE_HEAD_FIELDS")

        witness_fields = (
            material.get("witness_operation_id"),
            material.get("witness_id"),
            material.get("witness_public_key_sha256"),
            material.get("witness_anchored_sequence"),
            material.get("witness_event_sha256"),
        )
        anchor_required = rank >= _PHASE_RANK[PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED]
        if anchor_required:
            _sha256(witness_fields[0], reason="PROFILED_COORDINATOR_WITNESS_OPERATION_INVALID")
            _identifier(witness_fields[1], reason="PROFILED_COORDINATOR_WITNESS_ID_INVALID")
            _sha256(witness_fields[2], reason="PROFILED_COORDINATOR_WITNESS_KEY_INVALID")
            anchored_sequence = _positive_integer(
                witness_fields[3],
                reason="PROFILED_COORDINATOR_WITNESS_SEQUENCE_INVALID",
            )
            _sha256(witness_fields[4], reason="PROFILED_COORDINATOR_WITNESS_EVENT_INVALID")
            if (
                anchored_sequence != cast(int, head_revision)
                or witness_fields[4] != material.get("head_event_sha256")
                or material.get("signed_head_durably_anchored") is not True
            ):
                _fail("PROFILED_COORDINATOR_WITNESS_HEAD_BINDING_INVALID")
        elif (
            any(value is not None for value in witness_fields)
            or material.get("signed_head_durably_anchored") is not False
        ):
            _fail("PROFILED_COORDINATOR_PREMATURE_WITNESS_FIELDS")

        epoch_required = rank >= _PHASE_RANK[PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED]
        epoch_address = _optional_address(
            material,
            sha_name="epoch_event_sha256",
            count_name="epoch_event_byte_count",
            required=epoch_required,
            reason="PROFILED_COORDINATOR_EPOCH_ADDRESS_INVALID",
        )
        if epoch_required:
            _sha256(material.get("epoch_id"), reason="PROFILED_COORDINATOR_EPOCH_ID_INVALID")
        elif epoch_address[0] is not None or material.get("epoch_id") is not None:
            _fail("PROFILED_COORDINATOR_PREMATURE_EPOCH_FIELDS")

        page_required = rank >= _PHASE_RANK[PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED]
        if rank == _PHASE_RANK[PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED]:
            page_required = cast(int, material["total_profiled_samples"]) > 0
        page_address = _optional_address(
            material,
            sha_name="page_receipt_event_sha256",
            count_name="page_receipt_event_byte_count",
            required=page_required,
            reason="PROFILED_COORDINATOR_PAGE_ADDRESS_INVALID",
        )
        page_scalars = (
            material.get("page_sequence"),
            material.get("page_end_ordinal"),
            material.get("page_has_more_manifest_entries"),
            material.get("page_transition_sha256"),
            material.get("ordered_page_root_sha256"),
        )
        if page_required:
            _positive_integer(page_scalars[0], reason="PROFILED_COORDINATOR_PAGE_CURSOR_INVALID")
            end_ordinal = _positive_integer(
                page_scalars[1],
                reason="PROFILED_COORDINATOR_PAGE_CURSOR_INVALID",
            )
            if type(page_scalars[2]) is not bool or end_ordinal > cast(
                int, material["total_profiled_samples"]
            ):
                _fail("PROFILED_COORDINATOR_PAGE_CURSOR_INVALID")
            _sha256(
                page_scalars[3],
                reason="PROFILED_COORDINATOR_PAGE_TRANSITION_INVALID",
            )
            _sha256(
                page_scalars[4],
                reason="PROFILED_COORDINATOR_PAGE_ROOT_INVALID",
            )
        elif page_address[0] is not None or any(value is not None for value in page_scalars):
            _fail("PROFILED_COORDINATOR_PREMATURE_PAGE_FIELDS")

        completion_required = phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
        completion_address = _optional_address(
            material,
            sha_name="completion_event_sha256",
            count_name="completion_event_byte_count",
            required=completion_required,
            reason="PROFILED_COORDINATOR_COMPLETION_ADDRESS_INVALID",
        )
        if completion_required:
            _sha256(
                material.get("completion_id"),
                reason="PROFILED_COORDINATOR_COMPLETION_ID_INVALID",
            )
            if page_required and material.get("page_has_more_manifest_entries") is not False:
                _fail("PROFILED_COORDINATOR_COMPLETION_BEFORE_TERMINAL_PAGE")
        elif completion_address[0] is not None or material.get("completion_id") is not None:
            _fail("PROFILED_COORDINATOR_PREMATURE_COMPLETION_FIELDS")

    def _cursor_from_event(
        self,
        *,
        event_sha256: str,
        event_byte_count: int,
        raw: bytes,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        if hashlib.sha256(raw).hexdigest() != event_sha256 or len(raw) != event_byte_count:
            _fail("PROFILED_COORDINATOR_STATE_CAS_ADDRESS_MISMATCH")
        material = _strict_json(
            raw,
            maximum_bytes=MAX_PROFILED_OBSERVATION_COORDINATOR_STATE_BYTES,
            reason="PROFILED_COORDINATOR_STATE_JSON_INVALID",
        )
        self._validate_state_material(material)
        path_raw = material["manifest_path"]
        return ProfiledTrainingObservationCoordinatorCursorV1(
            state_event_sha256=event_sha256,
            state_event_byte_count=event_byte_count,
            transition_sequence=cast(int, material["transition_sequence"]),
            previous_state_event_sha256=cast(str, material["previous_state_event_sha256"]),
            cycle_id=cast(str, material["cycle_id"]),
            publisher_status_sha256=cast(str, material["publisher_status_sha256"]),
            namespace=self._namespace,
            consumer_lane=self._consumer_lane,
            phase=cast(str, material["phase"]),
            observation_time=cast(str, material["observation_time"]),
            factory_wall_clock_observed_at=cast(
                str,
                material["factory_wall_clock_observed_at"],
            ),
            manifest_auth_key_id=cast(str, material["manifest_auth_key_id"]),
            manifest_auth_key_commitment_sha256=cast(
                str,
                material["manifest_auth_key_commitment_sha256"],
            ),
            head_auth_key_id=cast(str, material["head_auth_key_id"]),
            head_auth_key_commitment_sha256=cast(
                str,
                material["head_auth_key_commitment_sha256"],
            ),
            epoch_auth_key_id=cast(str, material["epoch_auth_key_id"]),
            epoch_auth_key_commitment_sha256=cast(
                str,
                material["epoch_auth_key_commitment_sha256"],
            ),
            state_auth_key_commitment_sha256=cast(
                str,
                material["state_auth_key_commitment_sha256"],
            ),
            manifest_path=None if path_raw is None else Path(cast(str, path_raw)),
            manifest_id=cast(str | None, material["manifest_id"]),
            total_profiled_samples=cast(int | None, material["total_profiled_samples"]),
            admitted_example_count=cast(int | None, material["admitted_example_count"]),
            label_unavailable_count=cast(int | None, material["label_unavailable_count"]),
            head_event_sha256=cast(str | None, material["head_event_sha256"]),
            head_event_byte_count=cast(int | None, material["head_event_byte_count"]),
            head_revision=cast(int | None, material["head_revision"]),
            witness_operation_id=cast(str | None, material["witness_operation_id"]),
            witness_id=cast(str | None, material["witness_id"]),
            witness_public_key_sha256=cast(
                str | None,
                material["witness_public_key_sha256"],
            ),
            witness_anchored_sequence=cast(int | None, material["witness_anchored_sequence"]),
            witness_event_sha256=cast(str | None, material["witness_event_sha256"]),
            signed_head_durably_anchored=cast(
                bool,
                material["signed_head_durably_anchored"],
            ),
            epoch_event_sha256=cast(str | None, material["epoch_event_sha256"]),
            epoch_event_byte_count=cast(int | None, material["epoch_event_byte_count"]),
            epoch_id=cast(str | None, material["epoch_id"]),
            page_receipt_event_sha256=cast(
                str | None,
                material["page_receipt_event_sha256"],
            ),
            page_receipt_event_byte_count=cast(
                int | None,
                material["page_receipt_event_byte_count"],
            ),
            page_sequence=cast(int | None, material["page_sequence"]),
            page_end_ordinal=cast(int | None, material["page_end_ordinal"]),
            page_has_more_manifest_entries=cast(
                bool | None,
                material["page_has_more_manifest_entries"],
            ),
            page_transition_sha256=cast(
                str | None,
                material["page_transition_sha256"],
            ),
            ordered_page_root_sha256=cast(
                str | None,
                material["ordered_page_root_sha256"],
            ),
            completion_event_sha256=cast(str | None, material["completion_event_sha256"]),
            completion_event_byte_count=cast(
                int | None,
                material["completion_event_byte_count"],
            ),
            completion_id=cast(str | None, material["completion_id"]),
            prior_completed_head_event_sha256=cast(
                str | None,
                material["prior_completed_head_event_sha256"],
            ),
            prior_completed_head_event_byte_count=cast(
                int | None,
                material["prior_completed_head_event_byte_count"],
            ),
            prior_completed_completion_event_sha256=cast(
                str | None,
                material["prior_completed_completion_event_sha256"],
            ),
            prior_completed_completion_event_byte_count=cast(
                int | None,
                material["prior_completed_completion_event_byte_count"],
            ),
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
            _construction_token=_CURSOR_TOKEN,
        )

    def _pointer_bytes(
        self,
        *,
        event_sha256: str,
        event_byte_count: int,
        transition_sequence: int,
        cycle_id: str,
    ) -> bytes:
        unsigned = {
            "schema_version": PROFILED_OBSERVATION_COORDINATOR_POINTER_V1_SCHEMA_VERSION,
            "state_auth_key_id": self._state_auth_key_id,
            "namespace": self._namespace,
            "consumer_lane": self._consumer_lane,
            "state_event_sha256": event_sha256,
            "state_event_byte_count": event_byte_count,
            "transition_sequence": transition_sequence,
            "cycle_id": cycle_id,
        }
        signed = {**unsigned, "pointer_id": _stable_sha256(unsigned)}
        pointer = {
            **signed,
            "pointer_auth_tag": _auth_tag(
                domain=PROFILED_OBSERVATION_COORDINATOR_POINTER_AUTH_DOMAIN,
                role="coordinator-pointer",
                payload=signed,
                key=self._hmac_key,
            ),
        }
        return (
            _canonical_json_bytes(
                pointer,
                maximum_bytes=MAX_PROFILED_OBSERVATION_COORDINATOR_POINTER_BYTES,
                reason="PROFILED_COORDINATOR_POINTER_JSON_INVALID",
            )
            + b"\n"
        )

    def _atomic_write_pointer(self, payload: bytes) -> None:
        path = self._pointer_path
        temporary: Path | None = None
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if path.is_symlink():
                _fail("PROFILED_COORDINATOR_POINTER_SYMLINK_FORBIDDEN")
            temporary = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temporary, flags, 0o600)
            try:
                offset = 0
                while offset < len(payload):
                    offset += os.write(descriptor, payload[offset:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path)
            temporary = None
            parent_fd = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
            )
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
            observed = os.lstat(path)
            if (
                not stat.S_ISREG(observed.st_mode)
                or stat.S_ISLNK(observed.st_mode)
                or observed.st_uid != os.geteuid()
                or observed.st_nlink != 1
                or stat.S_IMODE(observed.st_mode) & 0o022
                or path.read_bytes() != payload
            ):
                _fail("PROFILED_COORDINATOR_POINTER_POSTCOMMIT_INVALID")
        except ProfiledTrainingObservationCoordinatorStateV1Error:
            raise
        except OSError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_POINTER_WRITE_FAILED"
            ) from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def _load_held(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1 | None:
        self._require_lease(writer_lease)
        try:
            observed = os.lstat(self._pointer_path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_POINTER_READ_FAILED"
            ) from exc
        if (
            not stat.S_ISREG(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or observed.st_uid != os.geteuid()
            or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) & 0o022
            or not 1 < observed.st_size <= MAX_PROFILED_OBSERVATION_COORDINATOR_POINTER_BYTES + 1
        ):
            _fail("PROFILED_COORDINATOR_POINTER_FILE_INVALID")
        try:
            framed = self._pointer_path.read_bytes()
        except OSError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_POINTER_READ_FAILED"
            ) from exc
        if not framed.endswith(b"\n") or b"\r" in framed:
            _fail("PROFILED_COORDINATOR_POINTER_FRAMING_INVALID")
        pointer = _strict_json(
            framed[:-1],
            maximum_bytes=MAX_PROFILED_OBSERVATION_COORDINATOR_POINTER_BYTES,
            reason="PROFILED_COORDINATOR_POINTER_JSON_INVALID",
        )
        if set(pointer) != _POINTER_FIELDS:
            _fail("PROFILED_COORDINATOR_POINTER_FIELDS_INVALID")
        auth_tag = pointer.get("pointer_auth_tag")
        signed = {name: value for name, value in pointer.items() if name != "pointer_auth_tag"}
        unsigned = {name: value for name, value in signed.items() if name != "pointer_id"}
        if (
            pointer.get("schema_version")
            != PROFILED_OBSERVATION_COORDINATOR_POINTER_V1_SCHEMA_VERSION
            or pointer.get("state_auth_key_id") != self._state_auth_key_id
            or pointer.get("namespace") != self._namespace
            or pointer.get("consumer_lane") != self._consumer_lane
            or pointer.get("pointer_id") != _stable_sha256(unsigned)
            or not _valid_sha256(auth_tag)
            or not hmac.compare_digest(
                cast(str, auth_tag),
                _auth_tag(
                    domain=PROFILED_OBSERVATION_COORDINATOR_POINTER_AUTH_DOMAIN,
                    role="coordinator-pointer",
                    payload=signed,
                    key=self._hmac_key,
                ),
            )
        ):
            _fail("PROFILED_COORDINATOR_POINTER_AUTHENTICATION_INVALID")
        event_sha = _sha256(
            pointer.get("state_event_sha256"),
            reason="PROFILED_COORDINATOR_POINTER_STATE_SHA256_INVALID",
        )
        event_count = _positive_integer(
            pointer.get("state_event_byte_count"),
            reason="PROFILED_COORDINATOR_POINTER_STATE_BYTE_COUNT_INVALID",
        )
        try:
            raw = self._store.get(event_sha, expected_byte_count=event_count)
        except SourcePayloadStoreError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_POINTER_STATE_CAS_INVALID"
            ) from exc
        cursor = self._cursor_from_event(
            event_sha256=event_sha,
            event_byte_count=event_count,
            raw=raw,
        )
        if (
            pointer.get("transition_sequence") != cursor.transition_sequence
            or pointer.get("cycle_id") != cursor.cycle_id
        ):
            _fail("PROFILED_COORDINATOR_POINTER_STATE_BINDING_MISMATCH")
        return cursor

    def load(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1 | None:
        with self.writer_lease(writer_lease) as held:
            return self._load_held(writer_lease=held)

    def _publish_state(
        self,
        material: dict[str, Any],
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        self._require_lease(writer_lease)
        unsigned = dict(material)
        signed = {**unsigned, "state_id": _stable_sha256(unsigned)}
        sealed = {
            **signed,
            "state_auth_tag": _auth_tag(
                domain=PROFILED_OBSERVATION_COORDINATOR_STATE_AUTH_DOMAIN,
                role="coordinator-state",
                payload=signed,
                key=self._hmac_key,
            ),
        }
        raw = _canonical_json_bytes(
            sealed,
            maximum_bytes=MAX_PROFILED_OBSERVATION_COORDINATOR_STATE_BYTES,
            reason="PROFILED_COORDINATOR_STATE_JSON_INVALID",
        )
        self._validate_state_material(sealed)
        try:
            address = self._store.put(raw)
        except SourcePayloadStoreError as exc:
            raise ProfiledTrainingObservationCoordinatorStateV1Error(
                "PROFILED_COORDINATOR_STATE_CAS_WRITE_FAILED"
            ) from exc
        pointer = self._pointer_bytes(
            event_sha256=address.payload_sha256,
            event_byte_count=address.payload_byte_count,
            transition_sequence=cast(int, sealed["transition_sequence"]),
            cycle_id=cast(str, sealed["cycle_id"]),
        )
        self._atomic_write_pointer(pointer)
        readback = self._load_held(writer_lease=writer_lease)
        if readback is None or readback.state_event_sha256 != address.payload_sha256:
            _fail("PROFILED_COORDINATOR_STATE_POSTCOMMIT_READBACK_MISMATCH")
        return readback

    @staticmethod
    def _empty_artifact_fields() -> dict[str, Any]:
        return {
            "manifest_path": None,
            "manifest_id": None,
            "total_profiled_samples": None,
            "admitted_example_count": None,
            "label_unavailable_count": None,
            "head_event_sha256": None,
            "head_event_byte_count": None,
            "head_revision": None,
            "witness_operation_id": None,
            "witness_id": None,
            "witness_public_key_sha256": None,
            "witness_anchored_sequence": None,
            "witness_event_sha256": None,
            "signed_head_durably_anchored": False,
            "epoch_event_sha256": None,
            "epoch_event_byte_count": None,
            "epoch_id": None,
            "page_receipt_event_sha256": None,
            "page_receipt_event_byte_count": None,
            "page_sequence": None,
            "page_end_ordinal": None,
            "page_has_more_manifest_entries": None,
            "page_transition_sha256": None,
            "ordered_page_root_sha256": None,
            "completion_event_sha256": None,
            "completion_event_byte_count": None,
            "completion_id": None,
        }

    def begin_or_resume(
        self,
        *,
        publisher_status_sha256: str,
        observation_time: str,
        factory_wall_clock_observed_at: str,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        status_sha = _sha256(
            publisher_status_sha256,
            reason="PROFILED_COORDINATOR_PUBLISHER_STATUS_SHA256_INVALID",
        )
        observation = _clock(
            observation_time,
            reason="PROFILED_COORDINATOR_OBSERVATION_TIME_INVALID",
        )
        factory = _clock(
            factory_wall_clock_observed_at,
            reason="PROFILED_COORDINATOR_FACTORY_CLOCK_INVALID",
        )
        if datetime.fromisoformat(observation.replace("Z", "+00:00")) > datetime.fromisoformat(
            factory.replace("Z", "+00:00")
        ):
            _fail("PROFILED_COORDINATOR_OBSERVATION_AFTER_FACTORY_CLOCK")
        with self.writer_lease(writer_lease) as held:
            current = self._load_held(writer_lease=held)
            if current is not None:
                if current.observation_time == observation:
                    if current.publisher_status_sha256 != status_sha:
                        _fail("PROFILED_COORDINATOR_SAME_CUTOFF_BINDING_CONFLICT")
                    return current
                if current.phase != PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED:
                    _fail("PROFILED_COORDINATOR_INFLIGHT_CYCLE_MUST_RESUME")
                if datetime.fromisoformat(
                    observation.replace("Z", "+00:00")
                ) < datetime.fromisoformat(current.observation_time.replace("Z", "+00:00")):
                    _fail("PROFILED_COORDINATOR_OBSERVATION_ROLLBACK")
                if status_sha == current.publisher_status_sha256:
                    _fail("PROFILED_COORDINATOR_STATUS_REUSED_FOR_DIFFERENT_CUTOFF")
                previous_event = current.state_event_sha256
                transition_sequence = current.transition_sequence + 1
                prior_head_sha = current.head_event_sha256
                prior_head_count = current.head_event_byte_count
                prior_completion_sha = current.completion_event_sha256
                prior_completion_count = current.completion_event_byte_count
            else:
                previous_event = PROFILED_OBSERVATION_COORDINATOR_GENESIS_STATE_EVENT_SHA256
                transition_sequence = 1
                prior_head_sha = prior_head_count = None
                prior_completion_sha = prior_completion_count = None
            if transition_sequence > MAX_PROFILED_OBSERVATION_COORDINATOR_TRANSITIONS:
                _fail("PROFILED_COORDINATOR_TRANSITION_RESOURCE_LIMIT_EXCEEDED")
            cycle_identity = {
                "schema_version": "profiled_training_observation_coordinator_cycle_identity_v1",
                "namespace": self._namespace,
                "consumer_lane": self._consumer_lane,
                "publisher_status_sha256": status_sha,
                "observation_time": observation,
                "factory_wall_clock_observed_at": factory,
            }
            material = {
                "schema_version": PROFILED_OBSERVATION_COORDINATOR_STATE_V1_SCHEMA_VERSION,
                "state_auth_key_id": self._state_auth_key_id,
                "namespace": self._namespace,
                "consumer_lane": self._consumer_lane,
                "transition_sequence": transition_sequence,
                "previous_state_event_sha256": previous_event,
                "cycle_id": _stable_sha256(cycle_identity),
                "publisher_status_sha256": status_sha,
                "phase": PROFILED_OBSERVATION_COORDINATOR_PREPARED,
                "observation_time": observation,
                "factory_wall_clock_observed_at": factory,
                "state_auth_key_commitment_sha256": (self._state_auth_key_commitment_sha256),
                "manifest_auth_key_id": self._manifest_auth_key_id,
                "manifest_auth_key_commitment_sha256": (self._manifest_auth_key_commitment_sha256),
                "head_auth_key_id": self._head_auth_key_id,
                "head_auth_key_commitment_sha256": (self._head_auth_key_commitment_sha256),
                "epoch_auth_key_id": self._epoch_auth_key_id,
                "epoch_auth_key_commitment_sha256": (self._epoch_auth_key_commitment_sha256),
                **self._empty_artifact_fields(),
                "prior_completed_head_event_sha256": prior_head_sha,
                "prior_completed_head_event_byte_count": prior_head_count,
                "prior_completed_completion_event_sha256": prior_completion_sha,
                "prior_completed_completion_event_byte_count": prior_completion_count,
                "local_rollback_limitation": (
                    PROFILED_OBSERVATION_COORDINATOR_LOCAL_ROLLBACK_LIMITATION
                ),
                **_authority_false(),
            }
            return self._publish_state(material, writer_lease=held)

    def _advance(
        self,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
        *,
        phase: str,
        updates: Mapping[str, Any],
        writer_lease: FeatureSnapshotWriterLease,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        self._require_lease(writer_lease)
        if type(current) is not ProfiledTrainingObservationCoordinatorCursorV1:
            _fail("PROFILED_COORDINATOR_CURRENT_CURSOR_EXACT_TYPE_REQUIRED")
        observed = self._load_held(writer_lease=writer_lease)
        if observed is None or observed.state_event_sha256 != current.state_event_sha256:
            _fail("PROFILED_COORDINATOR_CURRENT_CURSOR_NOT_LATEST")
        if phase not in _PHASE_RANK:
            _fail("PROFILED_COORDINATOR_PHASE_INVALID")
        if current.transition_sequence >= MAX_PROFILED_OBSERVATION_COORDINATOR_TRANSITIONS:
            _fail("PROFILED_COORDINATOR_TRANSITION_RESOURCE_LIMIT_EXCEEDED")
        unsigned = {
            name: value
            for name, value in current._material.items()
            if name not in {"state_id", "state_auth_tag"}
        }
        if any(name not in unsigned for name in updates):
            _fail("PROFILED_COORDINATOR_STATE_UPDATE_FIELD_INVALID")
        material = {
            **unsigned,
            **dict(updates),
            "transition_sequence": current.transition_sequence + 1,
            "previous_state_event_sha256": current.state_event_sha256,
            "phase": phase,
        }
        return self._publish_state(material, writer_lease=writer_lease)

    def persist_manifest(
        self,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
        *,
        build: ProfiledTrainingObservationManifestBuildV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        if type(build) is not ProfiledTrainingObservationManifestBuildV1:
            _fail("PROFILED_COORDINATOR_MANIFEST_BUILD_EXACT_TYPE_REQUIRED")
        if (
            current.phase != PROFILED_OBSERVATION_COORDINATOR_PREPARED
            or build.observation_time != current.observation_time
            or build.factory_wall_clock_observed_at != current.factory_wall_clock_observed_at
            or build.checkpoint_write_authorized is not False
            or build.runtime_wired is not False
        ):
            _fail("PROFILED_COORDINATOR_MANIFEST_BUILD_BINDING_INVALID")
        with self.writer_lease(writer_lease) as held:
            return self._advance(
                current,
                phase=PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED,
                updates={
                    "manifest_path": str(build.manifest_path),
                    "manifest_id": build.manifest_id,
                    "total_profiled_samples": build.total_profiled_samples,
                    "admitted_example_count": build.admitted_examples,
                    "label_unavailable_count": build.label_unavailable_samples,
                },
                writer_lease=held,
            )

    def persist_head(
        self,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
        *,
        head: LocalProfiledTrainingObservationHeadCandidateV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        if type(head) is not LocalProfiledTrainingObservationHeadCandidateV1:
            _fail("PROFILED_COORDINATOR_HEAD_EXACT_TYPE_REQUIRED")
        expected_previous_head = (
            current.prior_completed_head_event_sha256
            or PROFILED_OBSERVATION_HEAD_GENESIS_EVENT_SHA256
        )
        expected_previous_completion = (
            current.prior_completed_completion_event_sha256
            or PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
        )
        if (
            current.phase != PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED
            or head.namespace != current.namespace
            or head.allowed_consumer_lane != current.consumer_lane
            or head.manifest_id != current.manifest_id
            or head.observation_time != current.observation_time
            or head.previous_head_event_sha256 != expected_previous_head
            or head.previous_completion_candidate_sha256 != expected_previous_completion
            or head.manifest_auth_key_id != current.manifest_auth_key_id
            or head.head_auth_key_id != current.head_auth_key_id
            or head.epoch_auth_key_id != current.epoch_auth_key_id
        ):
            _fail("PROFILED_COORDINATOR_HEAD_BINDING_INVALID")
        with self.writer_lease(writer_lease) as held:
            return self._advance(
                current,
                phase=PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED,
                updates={
                    "head_event_sha256": head.candidate_event_sha256,
                    "head_event_byte_count": head.candidate_event_byte_count,
                    "head_revision": head.revision,
                },
                writer_lease=held,
            )

    def persist_head_anchor(
        self,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
        *,
        result: ProfiledTrainingExternalWitnessRuntimeResultV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        if type(result) is not ProfiledTrainingExternalWitnessRuntimeResultV1:
            _fail("PROFILED_COORDINATOR_WITNESS_RESULT_EXACT_TYPE_REQUIRED")
        if (
            current.phase != PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
            or result.namespace != current.namespace
            or result.event_sha256 != current.head_event_sha256
            or result.anchored_sequence != current.head_revision
            or result.signed_head_durably_anchored is not True
            or result.journal_pending_count != 0
            or any(getattr(result, name) is not False for name in _AUTHORITY_FIELDS)
        ):
            _fail("PROFILED_COORDINATOR_WITNESS_RESULT_BINDING_INVALID")
        with self.writer_lease(writer_lease) as held:
            return self._advance(
                current,
                phase=PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED,
                updates={
                    "witness_operation_id": result.operation_id,
                    "witness_id": result.witness_id,
                    "witness_public_key_sha256": result.witness_public_key_sha256,
                    "witness_anchored_sequence": result.anchored_sequence,
                    "witness_event_sha256": result.event_sha256,
                    "signed_head_durably_anchored": True,
                },
                writer_lease=held,
            )

    def persist_epoch(
        self,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
        *,
        epoch: LocalProfiledTrainingObservationConsumptionEpochV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        if type(epoch) is not LocalProfiledTrainingObservationConsumptionEpochV1:
            _fail("PROFILED_COORDINATOR_EPOCH_EXACT_TYPE_REQUIRED")
        if (
            current.phase != PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED
            or epoch.consumer_lane != current.consumer_lane
            or epoch.head_candidate_event_sha256 != current.head_event_sha256
            or epoch.head_revision != current.head_revision
            or epoch.manifest_id != current.manifest_id
            or epoch.observation_time != current.observation_time
            or epoch.manifest_auth_key_id != current.manifest_auth_key_id
            or epoch.head_auth_key_id != current.head_auth_key_id
            or epoch.epoch_auth_key_id != current.epoch_auth_key_id
            or epoch.total_profiled_samples != current.total_profiled_samples
            or epoch.admitted_example_count != current.admitted_example_count
            or epoch.label_unavailable_count != current.label_unavailable_count
        ):
            _fail("PROFILED_COORDINATOR_EPOCH_BINDING_INVALID")
        with self.writer_lease(writer_lease) as held:
            return self._advance(
                current,
                phase=PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED,
                updates={
                    "epoch_event_sha256": epoch.epoch_event_sha256,
                    "epoch_event_byte_count": epoch.epoch_event_byte_count,
                    "epoch_id": epoch.epoch_id,
                },
                writer_lease=held,
            )

    def persist_page(
        self,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
        *,
        page: LocalProfiledTrainingObservationPageReceiptV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        if type(page) is not LocalProfiledTrainingObservationPageReceiptV1:
            _fail("PROFILED_COORDINATOR_PAGE_EXACT_TYPE_REQUIRED")
        if current.phase == PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED:
            expected_sequence = 1
            expected_start_ordinal = 1
            expected_previous_receipt = PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256
            expected_previous_transition = PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256
            expected_previous_root = PROFILED_OBSERVATION_ORDERED_PAGE_ROOT_GENESIS_SHA256
        elif current.phase == PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED:
            if current.page_has_more_manifest_entries is not True:
                _fail("PROFILED_COORDINATOR_PAGE_AFTER_TERMINAL_FORBIDDEN")
            expected_sequence = cast(int, current.page_sequence) + 1
            expected_start_ordinal = cast(int, current.page_end_ordinal) + 1
            expected_previous_receipt = cast(str, current.page_receipt_event_sha256)
            expected_previous_transition = cast(str, current.page_transition_sha256)
            expected_previous_root = cast(str, current.ordered_page_root_sha256)
        else:
            _fail("PROFILED_COORDINATOR_PAGE_PHASE_INVALID")
        if (
            page.epoch_id != current.epoch_id
            or page.page_sequence != expected_sequence
            or page.page_start_ordinal != expected_start_ordinal
            or page.page_end_ordinal < expected_start_ordinal
            or page.cumulative_scanned_entry_count != page.page_end_ordinal
            or page.page_end_ordinal > cast(int, current.total_profiled_samples)
            or page._material.get("previous_page_receipt_event_sha256") != expected_previous_receipt
            or page.previous_page_transition_sha256 != expected_previous_transition
            or page._material.get("previous_ordered_page_root_sha256") != expected_previous_root
        ):
            _fail("PROFILED_COORDINATOR_PAGE_BINDING_INVALID")
        with self.writer_lease(writer_lease) as held:
            return self._advance(
                current,
                phase=PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED,
                updates={
                    "page_receipt_event_sha256": page.page_receipt_event_sha256,
                    "page_receipt_event_byte_count": page.page_receipt_event_byte_count,
                    "page_sequence": page.page_sequence,
                    "page_end_ordinal": page.page_end_ordinal,
                    "page_has_more_manifest_entries": page.has_more_manifest_entries,
                    "page_transition_sha256": page.page_transition_sha256,
                    "ordered_page_root_sha256": page.ordered_page_root_sha256,
                },
                writer_lease=held,
            )

    def persist_completion(
        self,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
        *,
        completion: LocalProfiledTrainingObservationCompletionCandidateV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorCursorV1:
        if type(completion) is not LocalProfiledTrainingObservationCompletionCandidateV1:
            _fail("PROFILED_COORDINATOR_COMPLETION_EXACT_TYPE_REQUIRED")
        zero_inventory = current.total_profiled_samples == 0
        valid_phase = (
            current.phase == PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED
            if zero_inventory
            else current.phase == PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED
            and current.page_has_more_manifest_entries is False
        )
        if zero_inventory:
            expected_page_count = 0
            expected_final_receipt = PROFILED_OBSERVATION_COMPLETION_GENESIS_SHA256
            expected_final_transition = PROFILED_OBSERVATION_PAGE_TRANSITION_GENESIS_SHA256
            expected_ordered_root = PROFILED_OBSERVATION_ORDERED_PAGE_ROOT_GENESIS_SHA256
        else:
            expected_page_count = cast(int, current.page_sequence)
            expected_final_receipt = cast(str, current.page_receipt_event_sha256)
            expected_final_transition = cast(str, current.page_transition_sha256)
            expected_ordered_root = cast(str, current.ordered_page_root_sha256)
        if (
            not valid_phase
            or completion.epoch_id != current.epoch_id
            or completion.consumer_lane != current.consumer_lane
            or completion.head_candidate_event_sha256 != current.head_event_sha256
            or completion.head_revision != current.head_revision
            or completion.manifest_id != current.manifest_id
            or completion.consumed_entry_count != current.total_profiled_samples
            or completion.admitted_entry_count != current.admitted_example_count
            or completion.label_unavailable_count != current.label_unavailable_count
            or completion.full_consumption_locally_verified is not True
            or completion.page_count != expected_page_count
            or completion._material.get("final_page_receipt_event_sha256") != expected_final_receipt
            or completion.final_page_transition_sha256 != expected_final_transition
            or completion.ordered_page_root_sha256 != expected_ordered_root
        ):
            _fail("PROFILED_COORDINATOR_COMPLETION_BINDING_INVALID")
        with self.writer_lease(writer_lease) as held:
            return self._advance(
                current,
                phase=PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED,
                updates={
                    "completion_event_sha256": completion.completion_event_sha256,
                    "completion_event_byte_count": completion.completion_event_byte_count,
                    "completion_id": completion.completion_id,
                },
                writer_lease=held,
            )

    @staticmethod
    def _validate_adjacent_states(
        prior: ProfiledTrainingObservationCoordinatorCursorV1,
        current: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> None:
        if (
            prior.transition_sequence + 1 != current.transition_sequence
            or current.previous_state_event_sha256 != prior.state_event_sha256
        ):
            _fail("PROFILED_COORDINATOR_STATE_CHAIN_SEQUENCE_GAP")
        if prior.cycle_id != current.cycle_id:
            if (
                prior.phase != PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
                or current.phase != PROFILED_OBSERVATION_COORDINATOR_PREPARED
                or current.publisher_status_sha256 == prior.publisher_status_sha256
                or datetime.fromisoformat(current.observation_time.replace("Z", "+00:00"))
                <= datetime.fromisoformat(prior.observation_time.replace("Z", "+00:00"))
                or current.prior_completed_head_event_sha256 != prior.head_event_sha256
                or current.prior_completed_head_event_byte_count != prior.head_event_byte_count
                or current.prior_completed_completion_event_sha256 != prior.completion_event_sha256
                or current.prior_completed_completion_event_byte_count
                != prior.completion_event_byte_count
            ):
                _fail("PROFILED_COORDINATOR_CROSS_CYCLE_TRANSITION_INVALID")
            role_fields = (
                "state_auth_key_id",
                "state_auth_key_commitment_sha256",
                "manifest_auth_key_id",
                "manifest_auth_key_commitment_sha256",
                "head_auth_key_id",
                "head_auth_key_commitment_sha256",
                "epoch_auth_key_id",
                "epoch_auth_key_commitment_sha256",
                "namespace",
                "consumer_lane",
            )
            if any(prior._material[name] != current._material[name] for name in role_fields):
                _fail("PROFILED_COORDINATOR_CROSS_CYCLE_ROLE_BINDING_CHANGED")
            return

        allowed_predecessors = {
            PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED: {
                PROFILED_OBSERVATION_COORDINATOR_PREPARED
            },
            PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED: {
                PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED
            },
            PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED: {
                PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
            },
            PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED: {
                PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED
            },
            PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED: {
                PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED,
                PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED,
            },
            PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED: {
                PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED,
                PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED,
            },
        }
        if prior.phase not in allowed_predecessors.get(current.phase, set()):
            _fail("PROFILED_COORDINATOR_SAME_CYCLE_PHASE_TRANSITION_INVALID")
        if current.phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED:
            expected_prior_phase = (
                PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED
                if current.total_profiled_samples == 0
                else PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED
            )
            if prior.phase != expected_prior_phase:
                _fail("PROFILED_COORDINATOR_COMPLETION_PREDECESSOR_INVALID")

        allowed_updates = {
            PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED: {
                "manifest_path",
                "manifest_id",
                "total_profiled_samples",
                "admitted_example_count",
                "label_unavailable_count",
            },
            PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED: {
                "head_event_sha256",
                "head_event_byte_count",
                "head_revision",
            },
            PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED: {
                "witness_operation_id",
                "witness_id",
                "witness_public_key_sha256",
                "witness_anchored_sequence",
                "witness_event_sha256",
                "signed_head_durably_anchored",
            },
            PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED: {
                "epoch_event_sha256",
                "epoch_event_byte_count",
                "epoch_id",
            },
            PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED: {
                "page_receipt_event_sha256",
                "page_receipt_event_byte_count",
                "page_sequence",
                "page_end_ordinal",
                "page_has_more_manifest_entries",
                "page_transition_sha256",
                "ordered_page_root_sha256",
            },
            PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED: {
                "completion_event_sha256",
                "completion_event_byte_count",
                "completion_id",
            },
        }[current.phase]
        always_changed = {
            "transition_sequence",
            "previous_state_event_sha256",
            "phase",
            "state_id",
            "state_auth_tag",
        }
        immutable_fields = _STATE_FIELDS - allowed_updates - always_changed
        if any(prior._material[name] != current._material[name] for name in immutable_fields):
            _fail("PROFILED_COORDINATOR_SAME_CYCLE_IMMUTABLE_FIELD_CHANGED")

    def verify_integrity(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> ProfiledTrainingObservationCoordinatorIntegrityV1 | None:
        with self.writer_lease(writer_lease) as held:
            current = self._load_held(writer_lease=held)
            if current is None:
                return None
            observed = current
            count = 1
            while observed.transition_sequence > 1:
                if count >= MAX_PROFILED_OBSERVATION_COORDINATOR_TRANSITIONS:
                    _fail("PROFILED_COORDINATOR_TRANSITION_RESOURCE_LIMIT_EXCEEDED")
                try:
                    raw = self._store.get(observed.previous_state_event_sha256)
                except SourcePayloadStoreError as exc:
                    raise ProfiledTrainingObservationCoordinatorStateV1Error(
                        "PROFILED_COORDINATOR_STATE_CHAIN_CAS_INVALID"
                    ) from exc
                prior = self._cursor_from_event(
                    event_sha256=observed.previous_state_event_sha256,
                    event_byte_count=len(raw),
                    raw=raw,
                )
                if prior.transition_sequence != observed.transition_sequence - 1:
                    _fail("PROFILED_COORDINATOR_STATE_CHAIN_SEQUENCE_GAP")
                self._validate_adjacent_states(prior, observed)
                observed = prior
                count += 1
            if (
                observed.previous_state_event_sha256
                != PROFILED_OBSERVATION_COORDINATOR_GENESIS_STATE_EVENT_SHA256
                or count != current.transition_sequence
            ):
                _fail("PROFILED_COORDINATOR_STATE_CHAIN_GENESIS_INVALID")
            return ProfiledTrainingObservationCoordinatorIntegrityV1(
                schema_version=PROFILED_OBSERVATION_COORDINATOR_INTEGRITY_V1_SCHEMA_VERSION,
                transition_count=count,
                current_transition_sequence=current.transition_sequence,
                current_state_event_sha256=current.state_event_sha256,
                current_cycle_id=current.cycle_id,
                current_phase=current.phase,
                complete_chain_verified=True,
                _construction_token=_INTEGRITY_TOKEN,
            )


__all__ = (
    "MAX_PROFILED_OBSERVATION_COORDINATOR_STATE_BYTES",
    "MAX_PROFILED_OBSERVATION_COORDINATOR_TRANSITIONS",
    "MIN_PROFILED_OBSERVATION_COORDINATOR_HMAC_KEY_BYTES",
    "PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED",
    "PROFILED_OBSERVATION_COORDINATOR_GENESIS_STATE_EVENT_SHA256",
    "PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED",
    "PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED",
    "PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED",
    "PROFILED_OBSERVATION_COORDINATOR_LOCAL_ROLLBACK_LIMITATION",
    "PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED",
    "PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED",
    "PROFILED_OBSERVATION_COORDINATOR_POINTER_V1_SCHEMA_VERSION",
    "PROFILED_OBSERVATION_COORDINATOR_PREPARED",
    "PROFILED_OBSERVATION_COORDINATOR_STATE_V1_SCHEMA_VERSION",
    "ProfiledTrainingObservationCoordinatorCursorV1",
    "ProfiledTrainingObservationCoordinatorIntegrityV1",
    "ProfiledTrainingObservationCoordinatorStateStoreV1",
    "ProfiledTrainingObservationCoordinatorStateV1Error",
)
