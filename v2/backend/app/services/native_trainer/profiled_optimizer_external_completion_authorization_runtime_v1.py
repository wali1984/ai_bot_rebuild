"""Crash-recovering runtime for profiled completion authorization.

The runtime owns the ordering between exact local completion evidence, the
append-only authorization journal, and the pinned remote client.  It can grant
only admission of one exact outcome-supervised corpus after a signed response
is independently verified and durably anchored.  It owns no optimizer step,
checkpoint/model write, prediction, trading, order, or execution authority.
"""

from __future__ import annotations

import hmac
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, NoReturn

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FeatureSnapshotLedgerError,
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_runtime_v1 import (
    ProfiledTrainingExternalWitnessRuntimeResultV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    LocalProfiledTrainingObservationCompletionCandidateV1,
    LocalProfiledTrainingObservationPageReceiptV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    AuthenticatedProfiledTrainingObservationManifestV1,
)

from .profiled_optimizer_external_completion_authorization_client_v1 import (
    PinnedProfiledOptimizerCompletionAuthorizationClientV1,
)
from .profiled_optimizer_external_completion_authorization_journal_v1 import (
    AUTHORIZATION_ANCHORED,
    REQUEST_PREPARED,
    ProfiledOptimizerCompletionAuthorizationJournalRecordV1,
    ProfiledOptimizerCompletionAuthorizationJournalV1,
)
from .profiled_optimizer_external_completion_request_v1 import (
    PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES,
    prepare_profiled_optimizer_external_completion_request_v1,
)

PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RUNTIME_V1_SCHEMA_VERSION: Final = (
    "profiled_optimizer_completion_authorization_runtime_v1"
)

# This bounds network work after a damaged or abandoned deployment.  It is a
# resource ceiling only, never a market, sample, risk, leverage, or model gate.
MAX_PROFILED_OPTIMIZER_AUTHORIZATION_PENDING_RECOVERIES: Final = 4_096

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_RESULT_TOKEN = object()


class ProfiledOptimizerCompletionAuthorizationRuntimeV1Error(RuntimeError):
    """The ordered completion-authorization runtime failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledOptimizerCompletionAuthorizationRuntimeV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _fresh_authorization_challenge() -> bytes:
    return secrets.token_bytes(PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES)


@dataclass(frozen=True, slots=True)
class ProfiledOptimizerCompletionAuthorizationRuntimeResultV1:
    """Proof that one exact admission authorization is durably anchored."""

    schema_version: str
    operation_id: str
    request_sha256: str
    idempotency_key: str
    witness_id: str
    witness_public_key_sha256: str
    authorization_namespace: str
    expected_authorization_sequence: int
    authorization_sequence: int
    previous_authorization_event_sha256: str
    authorization_envelope_sha256: str
    manifest_id: str
    completion_event_sha256: str
    recovered_operation_ids: tuple[str, ...]
    network_authorization_attempt_count: int
    request_dispatched_after_recovery: bool
    request_was_recovered: bool
    request_was_already_anchored: bool
    journal_operation_count: int
    journal_transition_count: int
    journal_anchored_count: int
    journal_pending_count: int
    request_durably_prepared: bool
    signed_authorization_durably_anchored: bool
    external_monotonic_manifest_head_verified: bool
    full_consumption_external_ack_verified: bool
    profiled_optimizer_admission_authorized: bool
    optimizer_execution_authorized: bool = False
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
        disposition_count = sum(
            1
            for value in (
                self.request_dispatched_after_recovery,
                self.request_was_recovered,
                self.request_was_already_anchored,
            )
            if value is True
        )
        if (
            self._construction_token is not _RESULT_TOKEN
            or self.schema_version
            != PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RUNTIME_V1_SCHEMA_VERSION
            or not all(
                _valid_sha256(value)
                for value in (
                    self.operation_id,
                    self.request_sha256,
                    self.idempotency_key,
                    self.witness_public_key_sha256,
                    self.previous_authorization_event_sha256,
                    self.authorization_envelope_sha256,
                    self.manifest_id,
                    self.completion_event_sha256,
                )
            )
            or type(self.witness_id) is not str
            or _IDENTIFIER_RE.fullmatch(self.witness_id) is None
            or type(self.authorization_namespace) is not str
            or _IDENTIFIER_RE.fullmatch(self.authorization_namespace) is None
            or type(self.expected_authorization_sequence) is not int
            or self.expected_authorization_sequence < 0
            or type(self.authorization_sequence) is not int
            or self.authorization_sequence != self.expected_authorization_sequence + 1
            or type(self.recovered_operation_ids) is not tuple
            or len(set(self.recovered_operation_ids)) != len(
                self.recovered_operation_ids
            )
            or any(not _valid_sha256(value) for value in self.recovered_operation_ids)
            or type(self.network_authorization_attempt_count) is not int
            or self.network_authorization_attempt_count
            != len(self.recovered_operation_ids)
            + (1 if self.request_dispatched_after_recovery is True else 0)
            or any(
                type(value) is not bool
                for value in (
                    self.request_dispatched_after_recovery,
                    self.request_was_recovered,
                    self.request_was_already_anchored,
                )
            )
            or disposition_count != 1
            or self.request_was_recovered
            != (self.operation_id in self.recovered_operation_ids)
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.journal_operation_count,
                    self.journal_transition_count,
                    self.journal_anchored_count,
                    self.journal_pending_count,
                )
            )
            or self.journal_operation_count < 1
            or self.journal_anchored_count < 1
            or self.journal_anchored_count > self.journal_operation_count
            or self.journal_transition_count
            != self.journal_operation_count + self.journal_anchored_count
            or self.journal_pending_count != 0
            or self.request_durably_prepared is not True
            or self.signed_authorization_durably_anchored is not True
            or self.external_monotonic_manifest_head_verified is not True
            or self.full_consumption_external_ack_verified is not True
            or self.profiled_optimizer_admission_authorized is not True
            or any(
                type(value) is not bool or value
                for value in (
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
            )
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_RESULT_INVALID")


class ProfiledOptimizerCompletionAuthorizationRuntimeV1:
    """Single-writer durable-prepare, dispatch, and signed-anchor runtime."""

    __slots__ = ("_challenge_source", "_client", "_journal", "_writer_lease")

    def __init__(
        self,
        *,
        journal: ProfiledOptimizerCompletionAuthorizationJournalV1,
        client: PinnedProfiledOptimizerCompletionAuthorizationClientV1,
        challenge_source: Callable[[], bytes] = _fresh_authorization_challenge,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> None:
        if type(journal) is not ProfiledOptimizerCompletionAuthorizationJournalV1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_JOURNAL_EXACT_TYPE_REQUIRED")
        if type(client) is not PinnedProfiledOptimizerCompletionAuthorizationClientV1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_CLIENT_EXACT_TYPE_REQUIRED")
        if not callable(challenge_source):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_CHALLENGE_SOURCE_INVALID")
        if writer_lease is not None:
            try:
                FeatureSnapshotWriterLease.require_exact(writer_lease, journal.path)
            except FeatureSnapshotLedgerError as exc:
                raise ProfiledOptimizerCompletionAuthorizationRuntimeV1Error(
                    "PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_WRITER_LEASE_INVALID"
                ) from exc
        self._journal = journal
        self._client = client
        self._challenge_source = challenge_source
        self._writer_lease = writer_lease

    @property
    def journal(self) -> ProfiledOptimizerCompletionAuthorizationJournalV1:
        return self._journal

    @property
    def client(self) -> PinnedProfiledOptimizerCompletionAuthorizationClientV1:
        return self._client

    def _recover_pending_held(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> tuple[ProfiledOptimizerCompletionAuthorizationJournalRecordV1, ...]:
        report = self._journal.verify_integrity(writer_lease=writer_lease)
        if report.pending_count > MAX_PROFILED_OPTIMIZER_AUTHORIZATION_PENDING_RECOVERIES:
            _fail(
                "PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_PENDING_RECOVERY_RESOURCE_LIMIT_EXCEEDED"
            )
        pending = self._journal.load_pending_requests(
            witness_id=self._client.witness_id,
            witness_public_key_bytes=self._client.witness_public_key_bytes,
            writer_lease=writer_lease,
        )
        if len(pending) != report.pending_count:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_PENDING_COUNT_CHANGED")
        anchored: list[ProfiledOptimizerCompletionAuthorizationJournalRecordV1] = []
        for record in pending:
            verified = self._client.dispatch_prepared_authorization(record.prepared)
            durable = self._journal.commit_authorization_anchored(
                operation_id=record.operation_id,
                authorization_envelope_bytes=verified.authorization_envelope_bytes,
                witness_public_key_bytes=self._client.witness_public_key_bytes,
                writer_lease=writer_lease,
            )
            if (
                durable.state != AUTHORIZATION_ANCHORED
                or durable.verified is None
                or durable.verified != verified
                or not hmac.compare_digest(
                    durable.verified.authorization_envelope_bytes,
                    verified.authorization_envelope_bytes,
                )
            ):
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_RECOVERY_NOT_ANCHORED")
            anchored.append(durable)
        return tuple(anchored)

    def recover_pending_authorizations(
        self,
    ) -> tuple[ProfiledOptimizerCompletionAuthorizationJournalRecordV1, ...]:
        """Retry every durable pending request once, in journal order."""

        with self._journal.writer_lease(self._writer_lease) as held:
            self._journal.initialize(writer_lease=held)
            recovered = self._recover_pending_held(writer_lease=held)
            if self._journal.verify_integrity(writer_lease=held).pending_count != 0:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_PENDING_REMAINS")
            return recovered

    @staticmethod
    def _require_exact_record_binding(
        *,
        record: ProfiledOptimizerCompletionAuthorizationJournalRecordV1,
        authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
        completion: LocalProfiledTrainingObservationCompletionCandidateV1,
        final_page: LocalProfiledTrainingObservationPageReceiptV1,
        completion_staging_store: ImmutableSourcePayloadStore,
        manifest_head_anchor: ProfiledTrainingExternalWitnessRuntimeResultV1,
    ) -> None:
        prepared = record.prepared
        rebuilt = prepare_profiled_optimizer_external_completion_request_v1(
            authenticated_manifest=authenticated_manifest,
            completion=completion,
            final_page=final_page,
            completion_staging_store=completion_staging_store,
            manifest_head_anchor=manifest_head_anchor,
            authorization_namespace=manifest_head_anchor.namespace,
            expected_authorization_sequence=prepared.expected_authorization_sequence,
            expected_previous_authorization_event_sha256=(
                prepared.expected_previous_authorization_event_sha256
            ),
            authorization_challenge=prepared.authorization_challenge,
        )
        if rebuilt != prepared or not hmac.compare_digest(
            rebuilt.request_bytes,
            prepared.request_bytes,
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_RECORD_BINDING_MISMATCH")

    def authorize_completion(
        self,
        *,
        authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
        completion: LocalProfiledTrainingObservationCompletionCandidateV1,
        final_page: LocalProfiledTrainingObservationPageReceiptV1,
        completion_staging_store: ImmutableSourcePayloadStore,
        manifest_head_anchor: ProfiledTrainingExternalWitnessRuntimeResultV1,
    ) -> ProfiledOptimizerCompletionAuthorizationRuntimeResultV1:
        """Authorize exactly one completion after durable prepare and recovery."""

        if type(authenticated_manifest) is not AuthenticatedProfiledTrainingObservationManifestV1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_MANIFEST_EXACT_TYPE_REQUIRED")
        if type(completion) is not LocalProfiledTrainingObservationCompletionCandidateV1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_COMPLETION_EXACT_TYPE_REQUIRED")
        if type(final_page) is not LocalProfiledTrainingObservationPageReceiptV1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_FINAL_PAGE_EXACT_TYPE_REQUIRED")
        if type(completion_staging_store) is not ImmutableSourcePayloadStore:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_STAGING_STORE_EXACT_TYPE_REQUIRED")
        authenticated_manifest.__post_init__()
        completion.__post_init__()
        final_page.__post_init__()
        if type(manifest_head_anchor) is not ProfiledTrainingExternalWitnessRuntimeResultV1:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_HEAD_ANCHOR_EXACT_TYPE_REQUIRED")
        manifest_head_anchor.__post_init__()
        authorization_namespace = manifest_head_anchor.namespace
        if authenticated_manifest.admitted_example_count <= 0:
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_ZERO_ADMITTED_FORBIDDEN")
        if (
            manifest_head_anchor.witness_id != self._client.witness_id
            or manifest_head_anchor.witness_public_key_sha256
            != self._client.witness_public_key_sha256
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_HEAD_WITNESS_MISMATCH")
        if (
            completion_staging_store.root_path != completion.staging_store_root
            or completion_staging_store.root_path != final_page.staging_store_root
            or completion.manifest_id != authenticated_manifest.manifest_id
            or completion.head_candidate_event_sha256
            != manifest_head_anchor.event_sha256
            or completion.head_revision != manifest_head_anchor.anchored_sequence
        ):
            _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_LOCAL_BINDING_MISMATCH")
        with self._journal.writer_lease(self._writer_lease) as held:
            self._journal.initialize(writer_lease=held)
            initial = self._journal.load_request_for_completion(
                witness_id=self._client.witness_id,
                authorization_namespace=authorization_namespace,
                completion_event_sha256=completion.completion_event_sha256,
                witness_public_key_bytes=self._client.witness_public_key_bytes,
                writer_lease=held,
            )
            if initial is not None:
                self._require_exact_record_binding(
                    record=initial,
                    authenticated_manifest=authenticated_manifest,
                    completion=completion,
                    final_page=final_page,
                    completion_staging_store=completion_staging_store,
                    manifest_head_anchor=manifest_head_anchor,
                )
            recovered = self._recover_pending_held(writer_lease=held)
            recovered_ids = tuple(record.operation_id for record in recovered)
            record = self._journal.load_request_for_completion(
                witness_id=self._client.witness_id,
                authorization_namespace=authorization_namespace,
                completion_event_sha256=completion.completion_event_sha256,
                witness_public_key_bytes=self._client.witness_public_key_bytes,
                writer_lease=held,
            )
            if initial is None and record is not None:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_COMPLETION_IDENTITY_CHANGED")
            dispatched = False
            if record is None:
                head = self._journal.latest_authorization_head(
                    witness_id=self._client.witness_id,
                    authorization_namespace=authorization_namespace,
                    witness_public_key_bytes=self._client.witness_public_key_bytes,
                    writer_lease=held,
                )
                if head.pending_operation_id is not None:
                    _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_PENDING_HEAD_REMAINS")
                try:
                    challenge = self._challenge_source()
                except Exception as exc:
                    raise ProfiledOptimizerCompletionAuthorizationRuntimeV1Error(
                        "PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_CHALLENGE_SOURCE_FAILED:"
                        f"{type(exc).__name__}"
                    ) from exc
                if (
                    type(challenge) is not bytes
                    or len(challenge)
                    != PROFILED_OPTIMIZER_COMPLETION_CHALLENGE_BYTES
                ):
                    _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_CHALLENGE_INVALID")
                prepared = prepare_profiled_optimizer_external_completion_request_v1(
                    authenticated_manifest=authenticated_manifest,
                    completion=completion,
                    final_page=final_page,
                    completion_staging_store=completion_staging_store,
                    manifest_head_anchor=manifest_head_anchor,
                    authorization_namespace=authorization_namespace,
                    expected_authorization_sequence=(
                        head.expected_authorization_sequence
                    ),
                    expected_previous_authorization_event_sha256=(
                        head.expected_previous_authorization_event_sha256
                    ),
                    authorization_challenge=challenge,
                )
                record = self._journal.persist_prepared_request(
                    prepared=prepared,
                    witness_public_key_bytes=self._client.witness_public_key_bytes,
                    writer_lease=held,
                )
                if record.state != REQUEST_PREPARED:
                    _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_NEW_REQUEST_NOT_PENDING")
                verified = self._client.dispatch_prepared_authorization(record.prepared)
                record = self._journal.commit_authorization_anchored(
                    operation_id=record.operation_id,
                    authorization_envelope_bytes=verified.authorization_envelope_bytes,
                    witness_public_key_bytes=self._client.witness_public_key_bytes,
                    writer_lease=held,
                )
                dispatched = True
            if record.state != AUTHORIZATION_ANCHORED or record.verified is None:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_REQUEST_NOT_ANCHORED")
            self._require_exact_record_binding(
                record=record,
                authenticated_manifest=authenticated_manifest,
                completion=completion,
                final_page=final_page,
                completion_staging_store=completion_staging_store,
                manifest_head_anchor=manifest_head_anchor,
            )
            report = self._journal.verify_integrity(writer_lease=held)
            if report.pending_count != 0:
                _fail("PROFILED_OPTIMIZER_AUTHORIZATION_RUNTIME_PENDING_REMAINS")
            verified = record.verified
            return ProfiledOptimizerCompletionAuthorizationRuntimeResultV1(
                schema_version=(
                    PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RUNTIME_V1_SCHEMA_VERSION
                ),
                operation_id=record.operation_id,
                request_sha256=record.prepared.request_sha256,
                idempotency_key=record.prepared.idempotency_key,
                witness_id=record.prepared.witness_id,
                witness_public_key_sha256=record.prepared.witness_public_key_sha256,
                authorization_namespace=record.prepared.authorization_namespace,
                expected_authorization_sequence=(
                    record.prepared.expected_authorization_sequence
                ),
                authorization_sequence=verified.authorization_sequence,
                previous_authorization_event_sha256=(
                    verified.previous_authorization_event_sha256
                ),
                authorization_envelope_sha256=(
                    verified.authorization_envelope_sha256
                ),
                manifest_id=record.prepared.manifest_id,
                completion_event_sha256=record.prepared.completion_event_sha256,
                recovered_operation_ids=recovered_ids,
                network_authorization_attempt_count=(
                    len(recovered_ids) + int(dispatched)
                ),
                request_dispatched_after_recovery=dispatched,
                request_was_recovered=record.operation_id in recovered_ids,
                request_was_already_anchored=(
                    initial is not None and initial.state == AUTHORIZATION_ANCHORED
                ),
                journal_operation_count=report.operation_count,
                journal_transition_count=report.transition_count,
                journal_anchored_count=report.anchored_count,
                journal_pending_count=report.pending_count,
                request_durably_prepared=True,
                signed_authorization_durably_anchored=True,
                external_monotonic_manifest_head_verified=(
                    verified.external_monotonic_manifest_head_verified
                ),
                full_consumption_external_ack_verified=(
                    verified.full_consumption_external_ack_verified
                ),
                profiled_optimizer_admission_authorized=(
                    verified.profiled_optimizer_admission_authorized
                ),
                _construction_token=_RESULT_TOKEN,
            )


__all__ = (
    "MAX_PROFILED_OPTIMIZER_AUTHORIZATION_PENDING_RECOVERIES",
    "PROFILED_OPTIMIZER_COMPLETION_AUTHORIZATION_RUNTIME_V1_SCHEMA_VERSION",
    "ProfiledOptimizerCompletionAuthorizationRuntimeResultV1",
    "ProfiledOptimizerCompletionAuthorizationRuntimeV1",
    "ProfiledOptimizerCompletionAuthorizationRuntimeV1Error",
)
