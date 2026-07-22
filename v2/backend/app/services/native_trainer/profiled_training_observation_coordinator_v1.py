"""Crash-resuming caller for one profiled publisher observation cycle.

The caller orders local status verification, immutable manifest construction,
local head staging, independent witness anchoring, and complete inventory-page
receipts.  Positive admitted inventory cannot advance to a newer publisher
cycle until an exact signed completion acknowledgement is durably anchored.
That proof authorizes corpus admission only; optimizer execution,
checkpoint/model writes, prediction, paper/live trading, orders, execution,
and trainer-runtime wiring remain outside this caller.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NoReturn, TypeVar, cast

from v2.backend.app.services.native_trainer import (
    profiled_optimizer_external_completion_authorization_runtime_v1 as completion_runtime_module,
)
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_base_publisher_cycle_status_v1 import (
    read_verified_profiled_base_publisher_cycle_status_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    ProfiledTrainingExternalWitnessRuntimeResultV1,
    ProfiledTrainingExternalWitnessRuntimeV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    LocalProfiledTrainingObservationCompletionCandidateV1,
    LocalProfiledTrainingObservationConsumptionEpochV1,
    LocalProfiledTrainingObservationHeadCandidateV1,
    LocalProfiledTrainingObservationPageReceiptV1,
    read_local_profiled_training_observation_completion_candidate_v1,
    read_local_profiled_training_observation_consumption_epoch_v1,
    read_local_profiled_training_observation_head_candidate_v1,
    read_local_profiled_training_observation_page_receipt_v1,
    stage_profiled_training_observation_completion_candidate_v1,
    stage_profiled_training_observation_consumption_epoch_v1,
    stage_profiled_training_observation_head_candidate_v1,
    stage_profiled_training_observation_page_receipt_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    MAX_PROFILED_OBSERVATION_PAGE_ROWS,
    AuthenticatedProfiledTrainingObservationManifestV1,
    authenticate_profiled_training_observation_manifest_v1,
    build_profiled_training_observation_manifest_v1,
)

from .profiled_training_observation_coordinator_state_v1 import (
    MIN_PROFILED_OBSERVATION_COORDINATOR_HMAC_KEY_BYTES,
    PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED,
    PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED,
    PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED,
    PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED,
    PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED,
    PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED,
    PROFILED_OBSERVATION_COORDINATOR_PREPARED,
    ProfiledTrainingObservationCoordinatorCursorV1,
    ProfiledTrainingObservationCoordinatorStateStoreV1,
)

ProfiledOptimizerCompletionAuthorizationRuntimeResultV1 = (
    completion_runtime_module.ProfiledOptimizerCompletionAuthorizationRuntimeResultV1
)
ProfiledOptimizerCompletionAuthorizationRuntimeV1 = (
    completion_runtime_module.ProfiledOptimizerCompletionAuthorizationRuntimeV1
)

PROFILED_TRAINING_OBSERVATION_COORDINATOR_V1_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_v1"
)
PROFILED_TRAINING_OBSERVATION_COORDINATOR_RESULT_V2_SCHEMA_VERSION: Final = (
    "profiled_training_observation_coordinator_v2"
)
PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS: Final = (
    "WAITING_EXTERNAL_WITNESS_CONFIGURATION"
)
PROFILED_COORDINATOR_LOCAL_COMPLETION: Final = "LOCAL_COMPLETION_STAGED"
PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION: Final = (
    "WAITING_COMPLETION_AUTHORIZATION_CONFIGURATION"
)
PROFILED_COORDINATOR_COMPLETION_AUTHORIZED: Final = "COMPLETION_AUTHORIZATION_ANCHORED"
PROFILED_COORDINATOR_NO_NEW_CYCLE: Final = "NO_NEW_PUBLISHER_CYCLE"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_RESULT_TOKEN = object()
_T = TypeVar("_T")
_RESULT_CLASSIFICATIONS: Final = {
    PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS,
    PROFILED_COORDINATOR_LOCAL_COMPLETION,
    PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION,
    PROFILED_COORDINATOR_COMPLETION_AUTHORIZED,
    PROFILED_COORDINATOR_NO_NEW_CYCLE,
}


class ProfiledTrainingObservationCoordinatorV1Error(RuntimeError):
    """The ordered profiled observation caller failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingObservationCoordinatorV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _absolute_path(value: Path, *, reason: str) -> Path:
    if not isinstance(value, Path) or not value.is_absolute():
        _fail(reason)
    normalized = Path(os.path.normpath(str(value)))
    if normalized != value or "\x00" in str(value):
        _fail(reason)
    return value


def _identifier(value: object, *, reason: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        _fail(reason)
    return value


def _key(value: bytes | bytearray | memoryview, *, reason: str) -> bytes:
    if type(value) not in {bytes, bytearray, memoryview}:
        _fail(reason)
    material = bytes(value)
    if len(material) < MIN_PROFILED_OBSERVATION_COORDINATOR_HMAC_KEY_BYTES:
        _fail(reason)
    return material


def _current_utc() -> datetime:
    return datetime.now(UTC)


def _canonical_clock(value: object, *, reason: str) -> str:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        _fail(reason)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_clock_text(value: object) -> bool:
    if type(value) is not str or not value or value != value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return False
    return (
        parsed.tzinfo is not None
        and parsed.utcoffset() is not None
        and parsed.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
        == value
    )


def _require_nondecreasing_clock(*, previous: str, current: str) -> str:
    if not _canonical_clock_text(previous) or not _canonical_clock_text(current):
        _fail("PROFILED_COORDINATOR_PAGE_CLOCK_INVALID")
    previous_dt = datetime.fromisoformat(previous.replace("Z", "+00:00"))
    current_dt = datetime.fromisoformat(current.replace("Z", "+00:00"))
    if current_dt < previous_dt:
        _fail("PROFILED_COORDINATOR_PAGE_CLOCK_ROLLBACK")
    return current


def _required(value: _T | None, *, reason: str) -> _T:
    if value is None:
        _fail(reason)
    return value


@dataclass(frozen=True, slots=True)
class ProfiledTrainingObservationCoordinatorResultV1:
    schema_version: str
    classification: str
    cycle_id: str
    publisher_status_sha256: str
    observation_time: str
    phase: str
    transition_sequence: int
    state_transitions_committed: int
    publisher_status_read_this_invocation: bool
    new_cycle_started_this_invocation: bool
    witness_runtime_configured: bool
    witness_operations_recovered: int
    witness_network_append_attempts: int
    completion_authorization_runtime_configured: bool
    completion_authorization_operations_recovered: int
    completion_authorization_network_attempts: int
    completion_authorization_operation_id: str | None
    completion_authorization_request_sha256: str | None
    completion_authorization_witness_id: str | None
    completion_authorization_witness_public_key_sha256: str | None
    completion_authorization_namespace: str | None
    completion_authorization_sequence: int | None
    completion_authorization_envelope_sha256: str | None
    signed_completion_authorization_durably_anchored: bool
    page_receipts_staged_this_invocation: int
    manifest_id: str
    total_profiled_samples: int
    admitted_example_count: int
    label_unavailable_count: int
    head_revision: int
    signed_head_durably_anchored: bool
    full_consumption_locally_verified: bool
    complete_state_chain_verified: bool
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    optimizer_admission_authorized: bool
    optimizer_execution_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        admission_authority = (
            self.external_monotonic_manifest_head_verified,
            self.full_consumption_external_ack_verified,
            self.optimizer_admission_authorized,
        )
        downstream_authority = (
            self.optimizer_execution_authorized,
            self.checkpoint_write_authorized,
            self.model_write_authorized,
            self.prediction_authorized,
            self.paper_trading_authorized,
            self.live_execution_authorized,
            self.order_submission_authorized,
            self.execution_authorized,
            self.runtime_wired,
        )
        authorization_identity = (
            self.completion_authorization_operation_id,
            self.completion_authorization_request_sha256,
            self.completion_authorization_witness_public_key_sha256,
            self.completion_authorization_envelope_sha256,
        )
        authorization_identifiers = (
            self.completion_authorization_witness_id,
            self.completion_authorization_namespace,
        )
        if (
            self._construction_token is not _RESULT_TOKEN
            or self.schema_version
            != PROFILED_TRAINING_OBSERVATION_COORDINATOR_RESULT_V2_SCHEMA_VERSION
            or self.classification not in _RESULT_CLASSIFICATIONS
            or not _valid_sha256(self.cycle_id)
            or not _valid_sha256(self.publisher_status_sha256)
            or not _valid_sha256(self.manifest_id)
            or not _canonical_clock_text(self.observation_time)
            or type(self.transition_sequence) is not int
            or self.transition_sequence <= 0
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.state_transitions_committed,
                    self.witness_operations_recovered,
                    self.witness_network_append_attempts,
                    self.completion_authorization_operations_recovered,
                    self.completion_authorization_network_attempts,
                    self.page_receipts_staged_this_invocation,
                    self.total_profiled_samples,
                    self.admitted_example_count,
                    self.label_unavailable_count,
                )
            )
            or self.total_profiled_samples
            != self.admitted_example_count + self.label_unavailable_count
            or self.state_transitions_committed > self.transition_sequence
            or self.witness_network_append_attempts < self.witness_operations_recovered
            or self.witness_network_append_attempts - self.witness_operations_recovered > 1
            or self.completion_authorization_network_attempts
            < self.completion_authorization_operations_recovered
            or self.completion_authorization_network_attempts
            - self.completion_authorization_operations_recovered
            > 1
            or (
                not self.witness_runtime_configured
                and (
                    self.witness_operations_recovered != 0
                    or self.witness_network_append_attempts != 0
                )
            )
            or (
                not self.completion_authorization_runtime_configured
                and (
                    self.completion_authorization_operations_recovered != 0
                    or self.completion_authorization_network_attempts != 0
                )
            )
            or (
                self.completion_authorization_runtime_configured
                and not self.witness_runtime_configured
            )
            or (
                self.new_cycle_started_this_invocation
                and not self.publisher_status_read_this_invocation
            )
            or (
                self.page_receipts_staged_this_invocation > 0
                and self.total_profiled_samples == 0
            )
            or type(self.head_revision) is not int
            or self.head_revision <= 0
            or any(
                type(value) is not bool
                for value in (
                    self.publisher_status_read_this_invocation,
                    self.new_cycle_started_this_invocation,
                    self.witness_runtime_configured,
                    self.completion_authorization_runtime_configured,
                    self.signed_completion_authorization_durably_anchored,
                    self.signed_head_durably_anchored,
                    self.full_consumption_locally_verified,
                    self.complete_state_chain_verified,
                    *admission_authority,
                    *downstream_authority,
                )
            )
            or self.complete_state_chain_verified is not True
            or any(downstream_authority)
            or (
                self.signed_completion_authorization_durably_anchored
                and (
                    not self.completion_authorization_runtime_configured
                    or self.admitted_example_count <= 0
                    or not all(value is True for value in admission_authority)
                    or any(not _valid_sha256(value) for value in authorization_identity)
                    or any(
                        type(value) is not str
                        or _IDENTIFIER_RE.fullmatch(value) is None
                        for value in authorization_identifiers
                    )
                    or type(self.completion_authorization_sequence) is not int
                    or self.completion_authorization_sequence <= 0
                )
            )
            or (
                not self.signed_completion_authorization_durably_anchored
                and (
                    any(value is not False for value in admission_authority)
                    or any(value is not None for value in authorization_identity)
                    or any(value is not None for value in authorization_identifiers)
                    or self.completion_authorization_sequence is not None
                )
            )
        ):
            _fail("PROFILED_COORDINATOR_RESULT_INVALID")
        if self.classification == PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS:
            if (
                self.phase != PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED
                or self.witness_runtime_configured
                or self.signed_head_durably_anchored
                or self.full_consumption_locally_verified
                or self.witness_operations_recovered != 0
                or self.witness_network_append_attempts != 0
                or self.completion_authorization_runtime_configured
                or self.completion_authorization_operations_recovered != 0
                or self.completion_authorization_network_attempts != 0
                or self.page_receipts_staged_this_invocation != 0
            ):
                _fail("PROFILED_COORDINATOR_WAITING_RESULT_INVALID")
        else:
            if (
                self.phase != PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
                or self.signed_head_durably_anchored is not True
                or self.full_consumption_locally_verified is not True
            ):
                _fail("PROFILED_COORDINATOR_COMPLETION_RESULT_INVALID")
            if (
                self.classification == PROFILED_COORDINATOR_LOCAL_COMPLETION
                and (
                    self.state_transitions_committed <= 0
                    or self.admitted_example_count != 0
                    or self.signed_completion_authorization_durably_anchored
                )
            ):
                _fail("PROFILED_COORDINATOR_COMPLETION_RESULT_INVALID")
            if self.classification == (
                PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION
            ) and (
                self.admitted_example_count <= 0
                or self.completion_authorization_runtime_configured
                or self.signed_completion_authorization_durably_anchored
            ):
                _fail("PROFILED_COORDINATOR_COMPLETION_WAITING_RESULT_INVALID")
            if self.classification == PROFILED_COORDINATOR_COMPLETION_AUTHORIZED and (
                self.admitted_example_count <= 0
                or self.signed_completion_authorization_durably_anchored is not True
            ):
                _fail("PROFILED_COORDINATOR_COMPLETION_AUTHORIZED_RESULT_INVALID")
            if self.classification == PROFILED_COORDINATOR_NO_NEW_CYCLE and (
                not self.publisher_status_read_this_invocation
                or self.new_cycle_started_this_invocation
                or self.state_transitions_committed != 0
                or self.page_receipts_staged_this_invocation != 0
                or self.witness_network_append_attempts
                != self.witness_operations_recovered
                or self.completion_authorization_network_attempts
                != self.completion_authorization_operations_recovered
                or (
                    self.admitted_example_count > 0
                    and self.signed_completion_authorization_durably_anchored is not True
                )
            ):
                _fail("PROFILED_COORDINATOR_NOOP_RESULT_INVALID")


class ProfiledTrainingObservationCoordinatorV1:
    """Run or resume one exact publisher cycle under a durable cursor."""

    __slots__ = (
        "_completion_authorization_runtime",
        "_consumer_lane",
        "_epoch_auth_key_id",
        "_epoch_hmac_key",
        "_feature_ledger",
        "_head_auth_key_id",
        "_head_hmac_key",
        "_label_archive",
        "_manifest_auth_key_id",
        "_manifest_hmac_key",
        "_manifest_root",
        "_namespace",
        "_page_size",
        "_staging_store",
        "_state_store",
        "_status_path",
        "_trusted_cost_store_root",
        "_wall_clock",
        "_witness_runtime",
    )

    def __init__(
        self,
        *,
        state_store: ProfiledTrainingObservationCoordinatorStateStoreV1,
        status_path: Path,
        feature_ledger: DurableFeatureSnapshotLedger,
        label_archive: DurableCanonical5mLabelArchive,
        trusted_immutable_cost_store_root: Path,
        manifest_root: Path,
        staging_store: ImmutableSourcePayloadStore,
        namespace: str,
        consumer_lane: str,
        manifest_auth_key_id: str,
        manifest_hmac_key: bytes | bytearray | memoryview,
        head_auth_key_id: str,
        head_hmac_key: bytes | bytearray | memoryview,
        epoch_auth_key_id: str,
        epoch_hmac_key: bytes | bytearray | memoryview,
        page_size: int,
        witness_runtime: ProfiledTrainingExternalWitnessRuntimeV1 | None = None,
        completion_authorization_runtime: (
            ProfiledOptimizerCompletionAuthorizationRuntimeV1 | None
        ) = None,
        wall_clock: Callable[[], datetime] = _current_utc,
    ) -> None:
        if type(state_store) is not ProfiledTrainingObservationCoordinatorStateStoreV1:
            _fail("PROFILED_COORDINATOR_STATE_STORE_EXACT_TYPE_REQUIRED")
        if type(feature_ledger) is not DurableFeatureSnapshotLedger:
            _fail("PROFILED_COORDINATOR_FEATURE_LEDGER_EXACT_TYPE_REQUIRED")
        if type(label_archive) is not DurableCanonical5mLabelArchive:
            _fail("PROFILED_COORDINATOR_LABEL_ARCHIVE_EXACT_TYPE_REQUIRED")
        if type(staging_store) is not ImmutableSourcePayloadStore:
            _fail("PROFILED_COORDINATOR_STAGING_STORE_EXACT_TYPE_REQUIRED")
        if witness_runtime is not None and type(witness_runtime) is not (
            ProfiledTrainingExternalWitnessRuntimeV1
        ):
            _fail("PROFILED_COORDINATOR_WITNESS_RUNTIME_EXACT_TYPE_REQUIRED")
        if completion_authorization_runtime is not None and type(
            completion_authorization_runtime
        ) is not ProfiledOptimizerCompletionAuthorizationRuntimeV1:
            _fail(
                "PROFILED_COORDINATOR_COMPLETION_AUTHORIZATION_RUNTIME_EXACT_TYPE_REQUIRED"
            )
        if completion_authorization_runtime is not None and witness_runtime is None:
            _fail("PROFILED_COORDINATOR_COMPLETION_RUNTIME_REQUIRES_HEAD_RUNTIME")
        if completion_authorization_runtime is not None and witness_runtime is not None and (
            completion_authorization_runtime.client.witness_id
            != witness_runtime.client.witness_id
            or completion_authorization_runtime.client.witness_public_key_sha256
            != witness_runtime.client.witness_public_key_sha256
        ):
            _fail("PROFILED_COORDINATOR_COMPLETION_RUNTIME_WITNESS_MISMATCH")
        if type(page_size) is not int or not 0 < page_size <= MAX_PROFILED_OBSERVATION_PAGE_ROWS:
            _fail("PROFILED_COORDINATOR_PAGE_SIZE_INVALID")
        if not callable(wall_clock):
            _fail("PROFILED_COORDINATOR_WALL_CLOCK_INVALID")
        self._state_store = state_store
        self._status_path = _absolute_path(
            status_path,
            reason="PROFILED_COORDINATOR_STATUS_PATH_INVALID",
        )
        self._feature_ledger = feature_ledger
        self._label_archive = label_archive
        self._trusted_cost_store_root = _absolute_path(
            trusted_immutable_cost_store_root,
            reason="PROFILED_COORDINATOR_COST_STORE_ROOT_INVALID",
        )
        self._manifest_root = _absolute_path(
            manifest_root,
            reason="PROFILED_COORDINATOR_MANIFEST_ROOT_INVALID",
        )
        self._staging_store = staging_store
        self._namespace = _identifier(
            namespace,
            reason="PROFILED_COORDINATOR_NAMESPACE_INVALID",
        )
        self._consumer_lane = _identifier(
            consumer_lane,
            reason="PROFILED_COORDINATOR_CONSUMER_LANE_INVALID",
        )
        self._manifest_auth_key_id = _identifier(
            manifest_auth_key_id,
            reason="PROFILED_COORDINATOR_MANIFEST_AUTH_KEY_ID_INVALID",
        )
        self._manifest_hmac_key = _key(
            manifest_hmac_key,
            reason="PROFILED_COORDINATOR_MANIFEST_HMAC_KEY_INVALID",
        )
        self._head_auth_key_id = _identifier(
            head_auth_key_id,
            reason="PROFILED_COORDINATOR_HEAD_AUTH_KEY_ID_INVALID",
        )
        self._head_hmac_key = _key(
            head_hmac_key,
            reason="PROFILED_COORDINATOR_HEAD_HMAC_KEY_INVALID",
        )
        self._epoch_auth_key_id = _identifier(
            epoch_auth_key_id,
            reason="PROFILED_COORDINATOR_EPOCH_AUTH_KEY_ID_INVALID",
        )
        self._epoch_hmac_key = _key(
            epoch_hmac_key,
            reason="PROFILED_COORDINATOR_EPOCH_HMAC_KEY_INVALID",
        )
        self._page_size = page_size
        self._witness_runtime = witness_runtime
        self._completion_authorization_runtime = completion_authorization_runtime
        self._wall_clock = wall_clock
        state_store.require_runtime_binding(
            namespace=self._namespace,
            consumer_lane=self._consumer_lane,
            manifest_auth_key_id=self._manifest_auth_key_id,
            manifest_hmac_key=self._manifest_hmac_key,
            head_auth_key_id=self._head_auth_key_id,
            head_hmac_key=self._head_hmac_key,
            epoch_auth_key_id=self._epoch_auth_key_id,
            epoch_hmac_key=self._epoch_hmac_key,
        )

    def _clock_now(self) -> str:
        try:
            observed = self._wall_clock()
        except Exception as exc:
            raise ProfiledTrainingObservationCoordinatorV1Error(
                f"PROFILED_COORDINATOR_WALL_CLOCK_FAILED:{type(exc).__name__}"
            ) from exc
        return _canonical_clock(
            observed,
            reason="PROFILED_COORDINATOR_WALL_CLOCK_INVALID",
        )

    def _authenticate_manifest(
        self,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> AuthenticatedProfiledTrainingObservationManifestV1:
        return authenticate_profiled_training_observation_manifest_v1(
            manifest_path=cast(
                Path,
                _required(cursor.manifest_path, reason="PROFILED_COORDINATOR_MANIFEST_MISSING"),
            ),
            hmac_key=self._manifest_hmac_key,
            expected_auth_key_id=self._manifest_auth_key_id,
            expected_manifest_id=cast(
                str,
                _required(cursor.manifest_id, reason="PROFILED_COORDINATOR_MANIFEST_MISSING"),
            ),
            expected_observation_time=cursor.observation_time,
        )

    def _read_head(
        self,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> LocalProfiledTrainingObservationHeadCandidateV1:
        return read_local_profiled_training_observation_head_candidate_v1(
            staging_store=self._staging_store,
            candidate_event_sha256=cast(
                str,
                _required(cursor.head_event_sha256, reason="PROFILED_COORDINATOR_HEAD_MISSING"),
            ),
            candidate_event_byte_count=cast(
                int,
                _required(
                    cursor.head_event_byte_count,
                    reason="PROFILED_COORDINATOR_HEAD_MISSING",
                ),
            ),
            manifest_hmac_key=self._manifest_hmac_key,
            manifest_auth_key_id=self._manifest_auth_key_id,
            head_hmac_key=self._head_hmac_key,
            head_auth_key_id=self._head_auth_key_id,
            epoch_hmac_key=self._epoch_hmac_key,
            epoch_auth_key_id=self._epoch_auth_key_id,
            expected_namespace=self._namespace,
        )

    def _read_epoch(
        self,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> LocalProfiledTrainingObservationConsumptionEpochV1:
        return read_local_profiled_training_observation_consumption_epoch_v1(
            staging_store=self._staging_store,
            epoch_event_sha256=cast(
                str,
                _required(cursor.epoch_event_sha256, reason="PROFILED_COORDINATOR_EPOCH_MISSING"),
            ),
            epoch_event_byte_count=cast(
                int,
                _required(
                    cursor.epoch_event_byte_count,
                    reason="PROFILED_COORDINATOR_EPOCH_MISSING",
                ),
            ),
            epoch_hmac_key=self._epoch_hmac_key,
            epoch_auth_key_id=self._epoch_auth_key_id,
        )

    def _read_page(
        self,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> LocalProfiledTrainingObservationPageReceiptV1:
        return read_local_profiled_training_observation_page_receipt_v1(
            staging_store=self._staging_store,
            page_receipt_event_sha256=cast(
                str,
                _required(
                    cursor.page_receipt_event_sha256,
                    reason="PROFILED_COORDINATOR_PAGE_MISSING",
                ),
            ),
            page_receipt_event_byte_count=cast(
                int,
                _required(
                    cursor.page_receipt_event_byte_count,
                    reason="PROFILED_COORDINATOR_PAGE_MISSING",
                ),
            ),
            epoch_hmac_key=self._epoch_hmac_key,
            epoch_auth_key_id=self._epoch_auth_key_id,
        )

    def _read_completion(
        self,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> LocalProfiledTrainingObservationCompletionCandidateV1:
        return read_local_profiled_training_observation_completion_candidate_v1(
            staging_store=self._staging_store,
            completion_event_sha256=cast(
                str,
                _required(
                    cursor.completion_event_sha256,
                    reason="PROFILED_COORDINATOR_COMPLETION_MISSING",
                ),
            ),
            completion_event_byte_count=cast(
                int,
                _required(
                    cursor.completion_event_byte_count,
                    reason="PROFILED_COORDINATOR_COMPLETION_MISSING",
                ),
            ),
            epoch_hmac_key=self._epoch_hmac_key,
            epoch_auth_key_id=self._epoch_auth_key_id,
        )

    def _read_prior_cycle(
        self,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> tuple[
        LocalProfiledTrainingObservationHeadCandidateV1 | None,
        LocalProfiledTrainingObservationCompletionCandidateV1 | None,
    ]:
        addresses = (
            cursor.prior_completed_head_event_sha256,
            cursor.prior_completed_head_event_byte_count,
            cursor.prior_completed_completion_event_sha256,
            cursor.prior_completed_completion_event_byte_count,
        )
        if all(value is None for value in addresses):
            return None, None
        if any(value is None for value in addresses):
            _fail("PROFILED_COORDINATOR_PRIOR_CYCLE_ADDRESS_INCOMPLETE")
        prior_head = read_local_profiled_training_observation_head_candidate_v1(
            staging_store=self._staging_store,
            candidate_event_sha256=cast(str, addresses[0]),
            candidate_event_byte_count=cast(int, addresses[1]),
            manifest_hmac_key=self._manifest_hmac_key,
            manifest_auth_key_id=self._manifest_auth_key_id,
            head_hmac_key=self._head_hmac_key,
            head_auth_key_id=self._head_auth_key_id,
            epoch_hmac_key=self._epoch_hmac_key,
            epoch_auth_key_id=self._epoch_auth_key_id,
            expected_namespace=self._namespace,
        )
        prior_completion = read_local_profiled_training_observation_completion_candidate_v1(
            staging_store=self._staging_store,
            completion_event_sha256=cast(str, addresses[2]),
            completion_event_byte_count=cast(int, addresses[3]),
            epoch_hmac_key=self._epoch_hmac_key,
            epoch_auth_key_id=self._epoch_auth_key_id,
        )
        return prior_head, prior_completion

    def _authorize_local_completion(
        self,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    ) -> tuple[
        ProfiledTrainingExternalWitnessRuntimeResultV1,
        ProfiledOptimizerCompletionAuthorizationRuntimeResultV1,
    ]:
        if (
            cursor.phase != PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
            or cast(int, cursor.admitted_example_count) <= 0
            or self._witness_runtime is None
            or self._completion_authorization_runtime is None
        ):
            _fail("PROFILED_COORDINATOR_COMPLETION_AUTHORIZATION_PRECONDITION_INVALID")
        head = self._read_head(cursor)
        head_anchor = self._witness_runtime.anchor_head_candidate(head_candidate=head)
        if (
            head_anchor.operation_id != cursor.witness_operation_id
            or head_anchor.witness_id != cursor.witness_id
            or head_anchor.witness_public_key_sha256
            != cursor.witness_public_key_sha256
            or head_anchor.namespace != cursor.namespace
            or head_anchor.anchored_sequence != cursor.witness_anchored_sequence
            or head_anchor.anchored_sequence != cursor.head_revision
            or head_anchor.event_sha256 != cursor.witness_event_sha256
            or head_anchor.event_sha256 != cursor.head_event_sha256
            or head_anchor.signed_head_durably_anchored is not True
            or head_anchor.journal_pending_count != 0
        ):
            _fail("PROFILED_COORDINATOR_COMPLETION_HEAD_REAUTHENTICATION_FAILED")
        authenticated = self._authenticate_manifest(cursor)
        completion = self._read_completion(cursor)
        final_page = self._read_page(cursor)
        authorization = self._completion_authorization_runtime.authorize_completion(
            authenticated_manifest=authenticated,
            completion=completion,
            final_page=final_page,
            completion_staging_store=self._staging_store,
            manifest_head_anchor=head_anchor,
        )
        if (
            authorization.witness_id != cursor.witness_id
            or authorization.witness_public_key_sha256
            != cursor.witness_public_key_sha256
            or authorization.authorization_namespace != cursor.namespace
            or authorization.manifest_id != cursor.manifest_id
            or authorization.completion_event_sha256
            != cursor.completion_event_sha256
            or authorization.signed_authorization_durably_anchored is not True
            or authorization.journal_pending_count != 0
            or authorization.external_monotonic_manifest_head_verified is not True
            or authorization.full_consumption_external_ack_verified is not True
            or authorization.profiled_optimizer_admission_authorized is not True
            or any(
                getattr(authorization, name) is not False
                for name in (
                    "optimizer_execution_authorized",
                    "checkpoint_write_authorized",
                    "model_write_authorized",
                    "prediction_authorized",
                    "paper_trading_authorized",
                    "live_execution_authorized",
                    "order_submission_authorized",
                    "execution_authorized",
                    "runtime_wired",
                )
            )
        ):
            _fail("PROFILED_COORDINATOR_COMPLETION_AUTHORIZATION_BINDING_INVALID")
        return head_anchor, authorization

    def _result(
        self,
        *,
        cursor: ProfiledTrainingObservationCoordinatorCursorV1,
        classification: str,
        initial_transition_sequence: int,
        status_read: bool,
        new_cycle_started: bool,
        recovered_count: int,
        witness_network_attempts: int,
        completion_recovered_count: int,
        completion_network_attempts: int,
        completion_authorization: (
            ProfiledOptimizerCompletionAuthorizationRuntimeResultV1 | None
        ),
        pages_staged: int,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> ProfiledTrainingObservationCoordinatorResultV1:
        if completion_authorization is not None:
            if type(completion_authorization) is not (
                ProfiledOptimizerCompletionAuthorizationRuntimeResultV1
            ):
                _fail(
                    "PROFILED_COORDINATOR_COMPLETION_AUTHORIZATION_RESULT_EXACT_TYPE_REQUIRED"
                )
            completion_authorization.__post_init__()
        integrity = self._state_store.verify_integrity(writer_lease=writer_lease)
        if integrity is None or integrity.current_state_event_sha256 != cursor.state_event_sha256:
            _fail("PROFILED_COORDINATOR_FINAL_STATE_INTEGRITY_INVALID")
        if cursor.phase == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED:
            self._read_head(cursor)
            self._read_epoch(cursor)
            if cast(int, cursor.total_profiled_samples) > 0:
                self._read_page(cursor)
            completion = self._read_completion(cursor)
            local_completion = completion.full_consumption_locally_verified
        else:
            local_completion = False
        return ProfiledTrainingObservationCoordinatorResultV1(
            schema_version=(
                PROFILED_TRAINING_OBSERVATION_COORDINATOR_RESULT_V2_SCHEMA_VERSION
            ),
            classification=classification,
            cycle_id=cursor.cycle_id,
            publisher_status_sha256=cursor.publisher_status_sha256,
            observation_time=cursor.observation_time,
            phase=cursor.phase,
            transition_sequence=cursor.transition_sequence,
            state_transitions_committed=(
                cursor.transition_sequence - initial_transition_sequence
            ),
            publisher_status_read_this_invocation=status_read,
            new_cycle_started_this_invocation=new_cycle_started,
            witness_runtime_configured=self._witness_runtime is not None,
            witness_operations_recovered=recovered_count,
            witness_network_append_attempts=witness_network_attempts,
            completion_authorization_runtime_configured=(
                self._completion_authorization_runtime is not None
            ),
            completion_authorization_operations_recovered=(
                completion_recovered_count
            ),
            completion_authorization_network_attempts=(
                completion_network_attempts
            ),
            completion_authorization_operation_id=(
                None
                if completion_authorization is None
                else completion_authorization.operation_id
            ),
            completion_authorization_sequence=(
                None
                if completion_authorization is None
                else completion_authorization.authorization_sequence
            ),
            completion_authorization_request_sha256=(
                None
                if completion_authorization is None
                else completion_authorization.request_sha256
            ),
            completion_authorization_witness_id=(
                None
                if completion_authorization is None
                else completion_authorization.witness_id
            ),
            completion_authorization_witness_public_key_sha256=(
                None
                if completion_authorization is None
                else completion_authorization.witness_public_key_sha256
            ),
            completion_authorization_namespace=(
                None
                if completion_authorization is None
                else completion_authorization.authorization_namespace
            ),
            completion_authorization_envelope_sha256=(
                None
                if completion_authorization is None
                else completion_authorization.authorization_envelope_sha256
            ),
            signed_completion_authorization_durably_anchored=(
                completion_authorization is not None
                and completion_authorization.signed_authorization_durably_anchored
                is True
            ),
            page_receipts_staged_this_invocation=pages_staged,
            manifest_id=cast(
                str,
                _required(cursor.manifest_id, reason="PROFILED_COORDINATOR_MANIFEST_MISSING"),
            ),
            total_profiled_samples=cast(
                int,
                _required(
                    cursor.total_profiled_samples,
                    reason="PROFILED_COORDINATOR_MANIFEST_COUNTS_MISSING",
                ),
            ),
            admitted_example_count=cast(
                int,
                _required(
                    cursor.admitted_example_count,
                    reason="PROFILED_COORDINATOR_MANIFEST_COUNTS_MISSING",
                ),
            ),
            label_unavailable_count=cast(
                int,
                _required(
                    cursor.label_unavailable_count,
                    reason="PROFILED_COORDINATOR_MANIFEST_COUNTS_MISSING",
                ),
            ),
            head_revision=cast(
                int,
                _required(cursor.head_revision, reason="PROFILED_COORDINATOR_HEAD_MISSING"),
            ),
            signed_head_durably_anchored=cursor.signed_head_durably_anchored,
            full_consumption_locally_verified=local_completion,
            complete_state_chain_verified=integrity.complete_chain_verified,
            external_monotonic_manifest_head_verified=(
                completion_authorization is not None
                and completion_authorization.external_monotonic_manifest_head_verified
                is True
            ),
            full_consumption_external_ack_verified=(
                completion_authorization is not None
                and completion_authorization.full_consumption_external_ack_verified
                is True
            ),
            optimizer_admission_authorized=(
                completion_authorization is not None
                and completion_authorization.profiled_optimizer_admission_authorized
                is True
            ),
            optimizer_execution_authorized=False,
            checkpoint_write_authorized=False,
            model_write_authorized=False,
            prediction_authorized=False,
            paper_trading_authorized=False,
            live_execution_authorized=False,
            order_submission_authorized=False,
            execution_authorized=False,
            runtime_wired=False,
            _construction_token=_RESULT_TOKEN,
        )

    def run_once(self) -> ProfiledTrainingObservationCoordinatorResultV1:
        """Run one cycle to the strongest configured, durably verified phase."""

        recovered_count = 0
        if self._witness_runtime is not None:
            recovered_count = len(self._witness_runtime.recover_pending_appends())
        witness_network_attempts = recovered_count
        completion_recovered_count = 0
        completion_recovered_operation_ids: tuple[str, ...] = ()
        if self._completion_authorization_runtime is not None:
            completion_recovered = (
                self._completion_authorization_runtime.recover_pending_authorizations()
            )
            completion_recovered_operation_ids = tuple(
                record.operation_id for record in completion_recovered
            )
            completion_recovered_count = len(completion_recovered)
        completion_network_attempts = completion_recovered_count
        completion_authorization: (
            ProfiledOptimizerCompletionAuthorizationRuntimeResultV1 | None
        ) = None
        pages_staged = 0
        status_read = False
        new_cycle_started = False
        with self._state_store.writer_lease() as held:
            cursor = self._state_store.load(writer_lease=held)
            initial_transition_sequence = cursor.transition_sequence if cursor is not None else 0
            if (
                cursor is not None
                and cursor.phase
                == PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
                and cast(int, cursor.admitted_example_count) > 0
            ):
                if self._completion_authorization_runtime is None:
                    return self._result(
                        cursor=cursor,
                        classification=(
                            PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION
                        ),
                        initial_transition_sequence=initial_transition_sequence,
                        status_read=False,
                        new_cycle_started=False,
                        recovered_count=recovered_count,
                        witness_network_attempts=witness_network_attempts,
                        completion_recovered_count=0,
                        completion_network_attempts=0,
                        completion_authorization=None,
                        pages_staged=0,
                        writer_lease=held,
                    )
                head_reauthentication, completion_authorization = (
                    self._authorize_local_completion(cursor)
                )
                recovered_count += len(
                    head_reauthentication.recovered_operation_ids
                )
                witness_network_attempts += (
                    head_reauthentication.network_append_attempt_count
                )
                completion_recovered_count += len(
                    completion_authorization.recovered_operation_ids
                )
                completion_network_attempts += (
                    completion_authorization.network_authorization_attempt_count
                )
                if (
                    not completion_authorization.request_was_already_anchored
                    or completion_authorization.operation_id
                    in completion_recovered_operation_ids
                ):
                    return self._result(
                        cursor=cursor,
                        classification=PROFILED_COORDINATOR_COMPLETION_AUTHORIZED,
                        initial_transition_sequence=initial_transition_sequence,
                        status_read=False,
                        new_cycle_started=False,
                        recovered_count=recovered_count,
                        witness_network_attempts=witness_network_attempts,
                        completion_recovered_count=(
                            completion_recovered_count
                        ),
                        completion_network_attempts=(
                            completion_network_attempts
                        ),
                        completion_authorization=completion_authorization,
                        pages_staged=0,
                        writer_lease=held,
                    )
            if cursor is None or cursor.phase == (
                PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED
            ):
                status = read_verified_profiled_base_publisher_cycle_status_v1(
                    status_path=self._status_path
                )
                status_read = True
                if (
                    cursor is not None
                    and cursor.publisher_status_sha256 == status.status_sha256
                    and cursor.observation_time == status.cycle_completed_at
                ):
                    return self._result(
                        cursor=cursor,
                        classification=PROFILED_COORDINATOR_NO_NEW_CYCLE,
                        initial_transition_sequence=initial_transition_sequence,
                        status_read=status_read,
                        new_cycle_started=False,
                        recovered_count=recovered_count,
                        witness_network_attempts=witness_network_attempts,
                        completion_recovered_count=completion_recovered_count,
                        completion_network_attempts=completion_network_attempts,
                        completion_authorization=completion_authorization,
                        pages_staged=0,
                        writer_lease=held,
                    )
                cursor = self._state_store.begin_or_resume(
                    publisher_status_sha256=status.status_sha256,
                    observation_time=status.cycle_completed_at,
                    factory_wall_clock_observed_at=self._clock_now(),
                    writer_lease=held,
                )
                new_cycle_started = True
                completion_authorization = None

            if cursor.phase == PROFILED_OBSERVATION_COORDINATOR_PREPARED:
                build = build_profiled_training_observation_manifest_v1(
                    ledger=self._feature_ledger,
                    trusted_immutable_cost_store_root=self._trusted_cost_store_root,
                    label_archive=self._label_archive,
                    manifest_root=self._manifest_root,
                    training_observed_at=cursor.observation_time,
                    auth_key_id=self._manifest_auth_key_id,
                    hmac_key=self._manifest_hmac_key,
                    prepared_factory_wall_clock_observed_at=(
                        cursor.factory_wall_clock_observed_at
                    ),
                )
                cursor = self._state_store.persist_manifest(
                    cursor,
                    build=build,
                    writer_lease=held,
                )

            if cursor.phase == PROFILED_OBSERVATION_COORDINATOR_MANIFEST_STAGED:
                prior_head, prior_completion = self._read_prior_cycle(cursor)
                head = stage_profiled_training_observation_head_candidate_v1(
                    manifest_path=cast(Path, cursor.manifest_path),
                    expected_manifest_id=cast(str, cursor.manifest_id),
                    expected_observation_time=cursor.observation_time,
                    feature_ledger=self._feature_ledger,
                    label_archive=self._label_archive,
                    staging_store=self._staging_store,
                    namespace=self._namespace,
                    consumer_lane=self._consumer_lane,
                    manifest_hmac_key=self._manifest_hmac_key,
                    manifest_auth_key_id=self._manifest_auth_key_id,
                    head_hmac_key=self._head_hmac_key,
                    head_auth_key_id=self._head_auth_key_id,
                    epoch_hmac_key=self._epoch_hmac_key,
                    epoch_auth_key_id=self._epoch_auth_key_id,
                    previous_head_candidate=prior_head,
                    previous_completion_candidate=prior_completion,
                )
                cursor = self._state_store.persist_head(
                    cursor,
                    head=head,
                    writer_lease=held,
                )

            if cursor.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_STAGED:
                head = self._read_head(cursor)
                if self._witness_runtime is None:
                    return self._result(
                        cursor=cursor,
                        classification=PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS,
                        initial_transition_sequence=initial_transition_sequence,
                        status_read=status_read,
                        new_cycle_started=new_cycle_started,
                        recovered_count=0,
                        witness_network_attempts=0,
                        completion_recovered_count=(
                            completion_recovered_count
                        ),
                        completion_network_attempts=(
                            completion_network_attempts
                        ),
                        completion_authorization=None,
                        pages_staged=0,
                        writer_lease=held,
                    )
                witness_result = self._witness_runtime.anchor_head_candidate(
                    head_candidate=head
                )
                recovered_count += len(witness_result.recovered_operation_ids)
                witness_network_attempts += witness_result.network_append_attempt_count
                cursor = self._state_store.persist_head_anchor(
                    cursor,
                    result=witness_result,
                    writer_lease=held,
                )

            if cursor.phase == PROFILED_OBSERVATION_COORDINATOR_HEAD_ANCHORED:
                head = self._read_head(cursor)
                epoch = stage_profiled_training_observation_consumption_epoch_v1(
                    head_candidate=head,
                    staging_store=self._staging_store,
                    consumer_lane=self._consumer_lane,
                    page_size=self._page_size,
                    manifest_hmac_key=self._manifest_hmac_key,
                    manifest_auth_key_id=self._manifest_auth_key_id,
                    head_hmac_key=self._head_hmac_key,
                    head_auth_key_id=self._head_auth_key_id,
                    epoch_hmac_key=self._epoch_hmac_key,
                    epoch_auth_key_id=self._epoch_auth_key_id,
                )
                cursor = self._state_store.persist_epoch(
                    cursor,
                    epoch=epoch,
                    writer_lease=held,
                )

            if cursor.phase in {
                PROFILED_OBSERVATION_COORDINATOR_EPOCH_STAGED,
                PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED,
            }:
                epoch = self._read_epoch(cursor)
                authenticated = self._authenticate_manifest(cursor)
                previous_page = (
                    self._read_page(cursor)
                    if cursor.phase == PROFILED_OBSERVATION_COORDINATOR_PAGE_STAGED
                    else None
                )
                previous_verified_at = (
                    authenticated.factory_wall_clock_observed_at
                    if previous_page is None
                    else previous_page.verified_at
                )
                while cast(int, cursor.total_profiled_samples) > 0 and (
                    previous_page is None
                    or previous_page.has_more_manifest_entries is True
                ):
                    expected_after = (
                        0 if previous_page is None else previous_page.page_end_ordinal
                    )
                    verified_at = _require_nondecreasing_clock(
                        previous=previous_verified_at,
                        current=self._clock_now(),
                    )
                    page = stage_profiled_training_observation_page_receipt_v1(
                        epoch=epoch,
                        authenticated_manifest=authenticated,
                        staging_store=self._staging_store,
                        verified_at=verified_at,
                        manifest_hmac_key=self._manifest_hmac_key,
                        manifest_auth_key_id=self._manifest_auth_key_id,
                        head_hmac_key=self._head_hmac_key,
                        head_auth_key_id=self._head_auth_key_id,
                        epoch_hmac_key=self._epoch_hmac_key,
                        epoch_auth_key_id=self._epoch_auth_key_id,
                        previous_page_receipt=previous_page,
                        expected_after_ordinal=expected_after,
                    )
                    cursor = self._state_store.persist_page(
                        cursor,
                        page=page,
                        writer_lease=held,
                    )
                    pages_staged += 1
                    previous_page = page
                    previous_verified_at = page.verified_at
                completion = stage_profiled_training_observation_completion_candidate_v1(
                    epoch=epoch,
                    staging_store=self._staging_store,
                    epoch_hmac_key=self._epoch_hmac_key,
                    epoch_auth_key_id=self._epoch_auth_key_id,
                    final_page_receipt=previous_page,
                )
                cursor = self._state_store.persist_completion(
                    cursor,
                    completion=completion,
                    writer_lease=held,
                )

            if cursor.phase != PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED:
                _fail(f"PROFILED_COORDINATOR_UNHANDLED_PHASE:{cursor.phase}")
            classification = PROFILED_COORDINATOR_LOCAL_COMPLETION
            if cast(int, cursor.admitted_example_count) > 0:
                if self._completion_authorization_runtime is None:
                    classification = (
                        PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION
                    )
                else:
                    head_reauthentication, completion_authorization = (
                        self._authorize_local_completion(cursor)
                    )
                    recovered_count += len(
                        head_reauthentication.recovered_operation_ids
                    )
                    witness_network_attempts += (
                        head_reauthentication.network_append_attempt_count
                    )
                    completion_recovered_count += len(
                        completion_authorization.recovered_operation_ids
                    )
                    completion_network_attempts += (
                        completion_authorization.network_authorization_attempt_count
                    )
                    classification = PROFILED_COORDINATOR_COMPLETION_AUTHORIZED
            return self._result(
                cursor=cursor,
                classification=classification,
                initial_transition_sequence=initial_transition_sequence,
                status_read=status_read,
                new_cycle_started=new_cycle_started,
                recovered_count=recovered_count,
                witness_network_attempts=witness_network_attempts,
                completion_recovered_count=completion_recovered_count,
                completion_network_attempts=completion_network_attempts,
                completion_authorization=completion_authorization,
                pages_staged=pages_staged,
                writer_lease=held,
            )


__all__ = (
    "PROFILED_COORDINATOR_COMPLETION_AUTHORIZED",
    "PROFILED_COORDINATOR_LOCAL_COMPLETION",
    "PROFILED_COORDINATOR_NO_NEW_CYCLE",
    "PROFILED_COORDINATOR_WAITING_COMPLETION_AUTHORIZATION",
    "PROFILED_COORDINATOR_WAITING_EXTERNAL_WITNESS",
    "PROFILED_TRAINING_OBSERVATION_COORDINATOR_RESULT_V2_SCHEMA_VERSION",
    "PROFILED_TRAINING_OBSERVATION_COORDINATOR_V1_SCHEMA_VERSION",
    "ProfiledTrainingObservationCoordinatorResultV1",
    "ProfiledTrainingObservationCoordinatorV1",
    "ProfiledTrainingObservationCoordinatorV1Error",
)
