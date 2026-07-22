"""Single-writer runtime caller for durable profiled witness head appends.

This module owns the ordering between the local head candidate, durable journal,
and pinned remote client.  It deliberately stops after a signed remote head is
durably anchored.  It grants no completion, optimizer, checkpoint, prediction,
paper, live, order, execution, or trainer-runtime authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, NoReturn

from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    FeatureSnapshotLedgerError,
    FeatureSnapshotWriterLease,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
    SourcePayloadStoreError,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_client_v1 import (
    PinnedProfiledTrainingExternalWitnessClientV1,
    ProfiledTrainingExternalWitnessWireTransportV1,
)
from v2.backend.app.services.native_trainer.profiled_training_external_witness_journal_v1 import (
    PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED,
    ProfiledTrainingExternalWitnessJournalRecordV1,
    ProfiledTrainingExternalWitnessJournalV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (
    LocalProfiledTrainingObservationHeadCandidateV1,
)

PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION: Final = (
    "profiled_training_external_witness_runtime_result_v1"
)

# Pending recovery work is bounded even if a damaged or abandoned deployment
# accumulated many independent namespaces.  A successful candidate call may
# make at most one additional append attempt after those recoveries.  This is a
# network-count safety ceiling, not an elapsed-time deadline or a market,
# sample, risk, leverage, margin, or model threshold.
MAX_PROFILED_WITNESS_RUNTIME_PENDING_RECOVERIES: Final = 4_096

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_RESULT_TOKEN = object()


class ProfiledTrainingExternalWitnessRuntimeV1Error(RuntimeError):
    """The ordered witness runtime caller failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise ProfiledTrainingExternalWitnessRuntimeV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class ProfiledTrainingExternalWitnessRuntimeResultV1:
    """Data-only proof that one head is now durably journal-anchored."""

    schema_version: str
    operation_id: str
    witness_id: str
    witness_public_key_sha256: str
    namespace: str
    expected_sequence: int
    anchored_sequence: int
    event_sha256: str
    recovered_operation_ids: tuple[str, ...]
    network_append_attempt_count: int
    candidate_dispatched_after_recovery: bool
    candidate_was_recovered: bool
    journal_operation_count: int
    journal_transition_count: int
    journal_anchored_count: int
    journal_pending_count: int
    signed_head_durably_anchored: bool
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
            self._construction_token is not _RESULT_TOKEN
            or self.schema_version != PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION
            or not _valid_sha256(self.operation_id)
            or _IDENTIFIER_RE.fullmatch(self.witness_id) is None
            or not _valid_sha256(self.witness_public_key_sha256)
            or _IDENTIFIER_RE.fullmatch(self.namespace) is None
            or type(self.expected_sequence) is not int
            or self.expected_sequence < 0
            or type(self.anchored_sequence) is not int
            or self.anchored_sequence != self.expected_sequence + 1
            or not _valid_sha256(self.event_sha256)
            or type(self.recovered_operation_ids) is not tuple
            or len(set(self.recovered_operation_ids)) != len(self.recovered_operation_ids)
            or any(not _valid_sha256(value) for value in self.recovered_operation_ids)
            or type(self.network_append_attempt_count) is not int
            or self.network_append_attempt_count
            != len(self.recovered_operation_ids) + int(self.candidate_dispatched_after_recovery)
            or type(self.candidate_dispatched_after_recovery) is not bool
            or type(self.candidate_was_recovered) is not bool
            or self.candidate_was_recovered != (self.operation_id in self.recovered_operation_ids)
            or (self.candidate_was_recovered and self.candidate_dispatched_after_recovery)
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
            or self.signed_head_durably_anchored is not True
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
            _fail("PROFILED_WITNESS_RUNTIME_RESULT_CONTRACT_INVALID")


def restore_pinned_profiled_training_external_witness_client_v1(
    *,
    journal: ProfiledTrainingExternalWitnessJournalV1,
    transport: ProfiledTrainingExternalWitnessWireTransportV1,
    witness_id: str,
    witness_public_key_bytes: bytes,
    expected_witness_public_key_sha256: str,
    close_transport_on_close: bool = False,
    writer_lease: FeatureSnapshotWriterLease | None = None,
) -> PinnedProfiledTrainingExternalWitnessClientV1:
    """Initialize the journal and authenticate its latest signed heads.

    The returned client constructor reverifies every restored envelope with the
    separately pinned Ed25519 key.  Reading bytes from local CAS does not make
    them trusted by itself.
    """

    if type(journal) is not ProfiledTrainingExternalWitnessJournalV1:
        _fail("PROFILED_WITNESS_RUNTIME_JOURNAL_EXACT_TYPE_REQUIRED")
    with journal.writer_lease(writer_lease) as held:
        journal.initialize(writer_lease=held)
        persisted_heads = journal.persisted_signed_head_envelopes_by_namespace(writer_lease=held)
        return PinnedProfiledTrainingExternalWitnessClientV1(
            transport=transport,
            witness_id=witness_id,
            witness_public_key_bytes=witness_public_key_bytes,
            expected_witness_public_key_sha256=expected_witness_public_key_sha256,
            trusted_head_envelope_bytes_by_namespace=persisted_heads,
            close_transport_on_close=close_transport_on_close,
        )


class ProfiledTrainingExternalWitnessRuntimeV1:
    """Crash-recovering, one-attempt-per-call witness head coordinator."""

    __slots__ = ("_client", "_journal", "_writer_lease")

    def __init__(
        self,
        *,
        journal: ProfiledTrainingExternalWitnessJournalV1,
        client: PinnedProfiledTrainingExternalWitnessClientV1,
        writer_lease: FeatureSnapshotWriterLease | None = None,
    ) -> None:
        if type(journal) is not ProfiledTrainingExternalWitnessJournalV1:
            _fail("PROFILED_WITNESS_RUNTIME_JOURNAL_EXACT_TYPE_REQUIRED")
        if type(client) is not PinnedProfiledTrainingExternalWitnessClientV1:
            _fail("PROFILED_WITNESS_RUNTIME_CLIENT_EXACT_TYPE_REQUIRED")
        if writer_lease is not None:
            try:
                FeatureSnapshotWriterLease.require_exact(writer_lease, journal.path)
            except FeatureSnapshotLedgerError as exc:
                raise ProfiledTrainingExternalWitnessRuntimeV1Error(
                    "PROFILED_WITNESS_RUNTIME_WRITER_LEASE_INVALID"
                ) from exc
        self._journal = journal
        self._client = client
        self._writer_lease = writer_lease

    @property
    def journal(self) -> ProfiledTrainingExternalWitnessJournalV1:
        return self._journal

    @property
    def client(self) -> PinnedProfiledTrainingExternalWitnessClientV1:
        return self._client

    def _recover_pending_held(
        self,
        *,
        writer_lease: FeatureSnapshotWriterLease,
    ) -> tuple[ProfiledTrainingExternalWitnessJournalRecordV1, ...]:
        report = self._journal.verify_integrity(writer_lease=writer_lease)
        if report.pending_count > MAX_PROFILED_WITNESS_RUNTIME_PENDING_RECOVERIES:
            _fail("PROFILED_WITNESS_RUNTIME_PENDING_RECOVERY_RESOURCE_LIMIT_EXCEEDED")
        pending = self._journal.load_pending_appends(
            client=self._client,
            writer_lease=writer_lease,
        )
        if len(pending) != report.pending_count:
            _fail("PROFILED_WITNESS_RUNTIME_PENDING_COUNT_CHANGED")
        anchored: list[ProfiledTrainingExternalWitnessJournalRecordV1] = []
        for record in pending:
            # Exactly one remote attempt is made for this persisted request in
            # this invocation.  An ambiguous result propagates and leaves the
            # operation pending for the next exact-idempotency retry.
            receipt = self._client.dispatch_prepared_append(record.prepared)
            durable = self._journal.commit_head_anchored(
                client=self._client,
                operation_id=record.operation_id,
                append_receipt=receipt,
                writer_lease=writer_lease,
            )
            if durable.state != PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED:
                _fail("PROFILED_WITNESS_RUNTIME_RECOVERY_NOT_ANCHORED")
            anchored.append(durable)
        return tuple(anchored)

    def recover_pending_appends(
        self,
    ) -> tuple[ProfiledTrainingExternalWitnessJournalRecordV1, ...]:
        """Retry every durable pending request once, in journal order."""

        with self._journal.writer_lease(self._writer_lease) as held:
            self._journal.initialize(writer_lease=held)
            recovered = self._recover_pending_held(writer_lease=held)
            if self._journal.verify_integrity(writer_lease=held).pending_count != 0:
                _fail("PROFILED_WITNESS_RUNTIME_PENDING_REMAINS_AFTER_RECOVERY")
            return recovered

    def anchor_head_candidate(
        self,
        *,
        head_candidate: LocalProfiledTrainingObservationHeadCandidateV1,
    ) -> ProfiledTrainingExternalWitnessRuntimeResultV1:
        """Recover older requests, then durably append one exact head candidate."""

        if type(head_candidate) is not LocalProfiledTrainingObservationHeadCandidateV1:
            _fail("PROFILED_WITNESS_RUNTIME_HEAD_CANDIDATE_EXACT_TYPE_REQUIRED")
        head_candidate.__post_init__()
        with self._journal.writer_lease(self._writer_lease) as held:
            self._journal.initialize(writer_lease=held)
            recovered = self._recover_pending_held(writer_lease=held)
            recovered_ids = tuple(record.operation_id for record in recovered)
            try:
                staging_store = ImmutableSourcePayloadStore(head_candidate.staging_store_root)
                event_bytes = staging_store.get(
                    head_candidate.candidate_event_sha256,
                    expected_byte_count=head_candidate.candidate_event_byte_count,
                )
            except SourcePayloadStoreError as exc:
                raise ProfiledTrainingExternalWitnessRuntimeV1Error(
                    "PROFILED_WITNESS_RUNTIME_HEAD_CANDIDATE_CAS_INVALID"
                ) from exc
            prepared = self._client.prepare_compare_and_append(
                namespace=head_candidate.namespace,
                expected_sequence=head_candidate.revision - 1,
                expected_event_sha256=head_candidate.previous_head_event_sha256,
                event_bytes=event_bytes,
            )
            record = self._journal.persist_prepared_append(
                client=self._client,
                prepared=prepared,
                head_candidate=head_candidate,
                writer_lease=held,
            )
            dispatched = False
            if record.state != PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED:
                receipt = self._client.dispatch_prepared_append(record.prepared)
                record = self._journal.commit_head_anchored(
                    client=self._client,
                    operation_id=record.operation_id,
                    append_receipt=receipt,
                    writer_lease=held,
                )
                dispatched = True
            if record.state != PROFILED_WITNESS_JOURNAL_HEAD_ANCHORED:
                _fail("PROFILED_WITNESS_RUNTIME_CANDIDATE_NOT_ANCHORED")
            receipt = record.append_receipt
            if receipt is None:
                _fail("PROFILED_WITNESS_RUNTIME_ANCHORED_RECEIPT_MISSING")
            report = self._journal.verify_integrity(writer_lease=held)
            if report.pending_count != 0:
                _fail("PROFILED_WITNESS_RUNTIME_PENDING_REMAINS_AFTER_SUCCESS")
            return ProfiledTrainingExternalWitnessRuntimeResultV1(
                schema_version=PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION,
                operation_id=record.operation_id,
                witness_id=record.prepared.witness_id,
                witness_public_key_sha256=(record.prepared.witness_public_key_sha256),
                namespace=record.prepared.namespace,
                expected_sequence=record.prepared.expected_sequence,
                anchored_sequence=receipt.sequence,
                event_sha256=record.prepared.event_sha256,
                recovered_operation_ids=recovered_ids,
                network_append_attempt_count=len(recovered_ids) + int(dispatched),
                candidate_dispatched_after_recovery=dispatched,
                candidate_was_recovered=record.operation_id in recovered_ids,
                journal_operation_count=report.operation_count,
                journal_transition_count=report.transition_count,
                journal_anchored_count=report.anchored_count,
                journal_pending_count=report.pending_count,
                signed_head_durably_anchored=True,
                _construction_token=_RESULT_TOKEN,
            )


__all__ = (
    "MAX_PROFILED_WITNESS_RUNTIME_PENDING_RECOVERIES",
    "PROFILED_WITNESS_RUNTIME_RESULT_V1_SCHEMA_VERSION",
    "ProfiledTrainingExternalWitnessRuntimeResultV1",
    "ProfiledTrainingExternalWitnessRuntimeV1",
    "ProfiledTrainingExternalWitnessRuntimeV1Error",
    "restore_pinned_profiled_training_external_witness_client_v1",
)
