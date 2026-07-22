"""Resident authenticated profiled trainer and non-serving publisher.

The coordinator remains the sole writer of observation/completion evidence.
This runtime reopens that immutable evidence and its independently signed
completion authorization, materializes the complete admitted corpus twice,
then holds the causal checkpoint lifecycle lease from exact base selection
through verified non-serving publication.  It never promotes, serves, predicts,
trades, or submits orders.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NoReturn

from v2.backend.app.services.native_trainer.authenticated_profiled_base_checkpoint_lineage_v1 import (  # noqa: E501
    AuthenticatedProfiledBaseCheckpointLineageV1,
    capture_authenticated_profiled_base_checkpoint_lineage_v1,
    ensure_authenticated_profiled_genesis_base_checkpoint_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (  # noqa: E501
    admit_authenticated_profiled_optimizer_manifest_batch_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (  # noqa: E501
    build_authenticated_profiled_optimizer_corpus_v1,
    validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_supervised_checkpoint_publication_v1 import (  # noqa: E501
    execute_lineage_bound_authenticated_profiled_supervised_optimizer_v1,
    find_authenticated_profiled_supervised_publication_for_completion_v1,
    publish_authenticated_profiled_supervised_checkpoint_v1,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (  # noqa: E501
    deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CheckpointManifest,
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (  # noqa: E501
    VERIFIED_SERVING_LINEAGE,
    checkpoint_lifecycle_lease,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.training_sample_identity import (  # noqa: E501
    manifest_paths,
    read_published_checkpoint_partition_manifest,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (  # noqa: E501
    LOGICAL_MODEL_INPUT_COUNT,
)
from v2.backend.app.services.native_trainer.profiled_optimizer_external_completion_authorization_journal_v1 import (  # noqa: E501
    AUTHORIZATION_ANCHORED,
    ProfiledOptimizerCompletionAuthorizationJournalRecordV1,
    ProfiledOptimizerCompletionAuthorizationJournalV1,
    ProfiledOptimizerCompletionAuthorizationJournalV1Error,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_coordinator_state_v1 import (  # noqa: E501
    PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED,
    ProfiledTrainingObservationCoordinatorCursorV1,
    ProfiledTrainingObservationCoordinatorStateStoreV1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_head_v1 import (  # noqa: E501
    LocalProfiledTrainingObservationCompletionCandidateV1,
    read_local_profiled_training_observation_completion_candidate_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (  # noqa: E501
    MAX_PROFILED_OBSERVATION_PAGE_ROWS,
)

AUTHENTICATED_PROFILED_RESIDENT_RUNTIME_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_resident_runtime_v1"
)
PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION: Final = "WAITING_FOR_AUTHENTICATED_LOCAL_COMPLETION"
PROFILED_RESIDENT_WAITING_EXTERNAL_AUTHORIZATION: Final = (
    "WAITING_FOR_EXTERNAL_COMPLETION_AUTHORIZATION"
)
PROFILED_RESIDENT_ALREADY_PUBLISHED: Final = "AUTHENTICATED_PROFILED_COMPLETION_ALREADY_PUBLISHED"
PROFILED_RESIDENT_PUBLICATION_COMPLETED: Final = (
    "AUTHENTICATED_PROFILED_NON_SERVING_PUBLICATION_COMPLETED"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,127}$", re.ASCII)
_CHECKPOINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$", re.ASCII)
_DOWNSTREAM_FALSE: Final = {
    "prediction_authorized": False,
    "serving_authorized": False,
    "serving_activation_authorized": False,
    "serving_promotion_authorized": False,
    "trading_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}


class AuthenticatedProfiledResidentRuntimeV1Error(RuntimeError):
    """The resident handoff, optimizer, or publication failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedProfiledResidentRuntimeV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _valid_checkpoint_id(value: object) -> bool:
    return type(value) is str and _CHECKPOINT_ID_RE.fullmatch(value) is not None


def _clock(value: datetime | str, *, reason: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str and value and value == value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (OverflowError, ValueError):
            _fail(reason)
    else:
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    return parsed.astimezone(UTC)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledResidentRuntimeConfigV1:
    state_store: ProfiledTrainingObservationCoordinatorStateStoreV1
    completion_authorization_journal: ProfiledOptimizerCompletionAuthorizationJournalV1
    feature_ledger: DurableFeatureSnapshotLedger
    completion_staging_store: ImmutableSourcePayloadStore
    trusted_immutable_cost_store_root: Path
    repo_root: Path
    model_dir: Path
    namespace: str
    consumer_lane: str
    manifest_auth_key_id: str
    manifest_hmac_key: bytes = field(repr=False)
    head_auth_key_id: str
    head_hmac_key: bytes = field(repr=False)
    epoch_auth_key_id: str
    epoch_hmac_key: bytes = field(repr=False)
    witness_id: str
    witness_namespace: str
    witness_public_key_bytes: bytes
    expected_witness_public_key_sha256: str
    page_limit: int
    validation_fraction: float
    optimizer_input_byte_budget: int
    state_resource_budget_bytes: int
    checkpoint_serialization_byte_budget: int
    clock: Callable[[], datetime | str] = _utc_now

    def __post_init__(self) -> None:
        if (
            type(self.state_store) is not ProfiledTrainingObservationCoordinatorStateStoreV1
            or type(self.completion_authorization_journal)
            is not ProfiledOptimizerCompletionAuthorizationJournalV1
            or type(self.feature_ledger) is not DurableFeatureSnapshotLedger
            or type(self.completion_staging_store) is not ImmutableSourcePayloadStore
            or any(
                not isinstance(path, Path) or not path.is_absolute()
                for path in (
                    self.trusted_immutable_cost_store_root,
                    self.repo_root,
                    self.model_dir,
                )
            )
            or any(
                type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None
                for value in (
                    self.namespace,
                    self.consumer_lane,
                    self.manifest_auth_key_id,
                    self.head_auth_key_id,
                    self.epoch_auth_key_id,
                    self.witness_id,
                    self.witness_namespace,
                )
            )
            or any(
                type(key) is not bytes or len(key) < 32
                for key in (
                    self.manifest_hmac_key,
                    self.head_hmac_key,
                    self.epoch_hmac_key,
                )
            )
            or len(
                {
                    self.manifest_hmac_key,
                    self.head_hmac_key,
                    self.epoch_hmac_key,
                }
            )
            != 3
            or type(self.witness_public_key_bytes) is not bytes
            or len(self.witness_public_key_bytes) != 32
            or not _valid_sha256(self.expected_witness_public_key_sha256)
            or hashlib.sha256(self.witness_public_key_bytes).hexdigest()
            != self.expected_witness_public_key_sha256
            or type(self.page_limit) is not int
            or not 0 < self.page_limit <= MAX_PROFILED_OBSERVATION_PAGE_ROWS
            or type(self.validation_fraction) is not float
            or not math.isfinite(self.validation_fraction)
            or not 0.0 <= self.validation_fraction < 1.0
            or any(
                type(value) is not int or value <= 0
                for value in (
                    self.optimizer_input_byte_budget,
                    self.state_resource_budget_bytes,
                    self.checkpoint_serialization_byte_budget,
                )
            )
            or not callable(self.clock)
        ):
            _fail("PROFILED_RESIDENT_CONFIG_INVALID")
        try:
            V2HybridCheckpointManager(self.model_dir)._validate_model_dir()  # noqa: SLF001
        except Exception as exc:
            raise AuthenticatedProfiledResidentRuntimeV1Error(
                "PROFILED_RESIDENT_MODEL_DIR_INVALID"
            ) from exc


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledResidentRuntimeResultV1:
    """One cycle outcome, never a capability for a future checkpoint write.

    ``checkpoint_publication_completed`` records the historical write performed
    and verified inside this cycle. ``checkpoint_write_authorized`` is always
    false because returning this object grants no reusable write authority.
    """

    schema_version: str
    classification: str
    cycle_id: str | None
    state_event_sha256: str | None
    manifest_id: str | None
    completion_event_sha256: str | None
    external_authorization_envelope_sha256: str | None
    witness_namespace: str | None
    admitted_example_count: int
    base_checkpoint_id: str | None
    candidate_checkpoint_id: str | None
    candidate_checkpoint_generation: int | None
    optimizer_execution_completed: bool
    checkpoint_publication_completed: bool
    already_published: bool
    checkpoint_artifact_verified: bool
    resident_runtime_active: bool
    checkpoint_write_authorized: bool
    prediction_authorized: bool
    serving_authorized: bool
    serving_activation_authorized: bool
    serving_promotion_authorized: bool
    trading_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    exchange_access_authorized: bool
    deployment_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool

    def __post_init__(self) -> None:
        terminal = self.classification in {
            PROFILED_RESIDENT_ALREADY_PUBLISHED,
            PROFILED_RESIDENT_PUBLICATION_COMPLETED,
        }
        published_now = self.classification == PROFILED_RESIDENT_PUBLICATION_COMPLETED
        recovered = self.classification == PROFILED_RESIDENT_ALREADY_PUBLISHED
        if (
            self.schema_version != AUTHENTICATED_PROFILED_RESIDENT_RUNTIME_V1_SCHEMA_VERSION
            or self.classification
            not in {
                PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION,
                PROFILED_RESIDENT_WAITING_EXTERNAL_AUTHORIZATION,
                PROFILED_RESIDENT_ALREADY_PUBLISHED,
                PROFILED_RESIDENT_PUBLICATION_COMPLETED,
            }
            or type(self.admitted_example_count) is not int
            or self.admitted_example_count < 0
            or self.resident_runtime_active is not True
            or self.optimizer_execution_completed is not published_now
            or self.checkpoint_publication_completed is not published_now
            or self.already_published is not recovered
            or self.checkpoint_artifact_verified is not terminal
            or (
                terminal
                and (
                    self.admitted_example_count <= 0
                    or any(
                        not _valid_sha256(value)
                        for value in (
                            self.cycle_id,
                            self.state_event_sha256,
                            self.manifest_id,
                            self.completion_event_sha256,
                            self.external_authorization_envelope_sha256,
                        )
                    )
                    or not _valid_checkpoint_id(self.base_checkpoint_id)
                    or not _valid_checkpoint_id(self.candidate_checkpoint_id)
                    or type(self.witness_namespace) is not str
                    or _IDENTIFIER_RE.fullmatch(self.witness_namespace) is None
                )
            )
            or terminal
            != (
                self.candidate_checkpoint_id is not None
                and self.candidate_checkpoint_generation is not None
            )
            or (
                self.candidate_checkpoint_generation is not None
                and self.candidate_checkpoint_generation <= 0
            )
            or self.checkpoint_write_authorized is not False
            or any(
                getattr(self, name) is not expected for name, expected in _DOWNSTREAM_FALSE.items()
            )
        ):
            _fail("PROFILED_RESIDENT_RESULT_INVALID")
        for value in (
            self.cycle_id,
            self.state_event_sha256,
            self.manifest_id,
            self.completion_event_sha256,
            self.external_authorization_envelope_sha256,
        ):
            if value is not None and not _valid_sha256(value):
                _fail("PROFILED_RESIDENT_RESULT_IDENTITY_INVALID")
        for value in (self.base_checkpoint_id, self.candidate_checkpoint_id):
            if value is not None and not _valid_checkpoint_id(value):
                _fail("PROFILED_RESIDENT_RESULT_IDENTITY_INVALID")
        if self.witness_namespace is not None and (
            type(self.witness_namespace) is not str
            or _IDENTIFIER_RE.fullmatch(self.witness_namespace) is None
        ):
            _fail("PROFILED_RESIDENT_RESULT_IDENTITY_INVALID")


def _result(
    *,
    classification: str,
    cursor: ProfiledTrainingObservationCoordinatorCursorV1 | None,
    external_authorization_envelope_sha256: str | None = None,
    witness_namespace: str | None = None,
    admitted_example_count: int = 0,
    base_checkpoint_id: str | None = None,
    candidate_checkpoint_id: str | None = None,
    candidate_checkpoint_generation: int | None = None,
) -> AuthenticatedProfiledResidentRuntimeResultV1:
    published_now = classification == PROFILED_RESIDENT_PUBLICATION_COMPLETED
    recovered = classification == PROFILED_RESIDENT_ALREADY_PUBLISHED
    return AuthenticatedProfiledResidentRuntimeResultV1(
        schema_version=AUTHENTICATED_PROFILED_RESIDENT_RUNTIME_V1_SCHEMA_VERSION,
        classification=classification,
        cycle_id=None if cursor is None else cursor.cycle_id,
        state_event_sha256=(None if cursor is None else cursor.state_event_sha256),
        manifest_id=None if cursor is None else cursor.manifest_id,
        completion_event_sha256=(None if cursor is None else cursor.completion_event_sha256),
        external_authorization_envelope_sha256=(external_authorization_envelope_sha256),
        witness_namespace=witness_namespace,
        admitted_example_count=admitted_example_count,
        base_checkpoint_id=base_checkpoint_id,
        candidate_checkpoint_id=candidate_checkpoint_id,
        candidate_checkpoint_generation=candidate_checkpoint_generation,
        optimizer_execution_completed=published_now,
        checkpoint_publication_completed=published_now,
        already_published=recovered,
        checkpoint_artifact_verified=published_now or recovered,
        resident_runtime_active=True,
        checkpoint_write_authorized=False,
        **_DOWNSTREAM_FALSE,
    )


def _state_snapshot(
    config: AuthenticatedProfiledResidentRuntimeConfigV1,
) -> ProfiledTrainingObservationCoordinatorCursorV1 | None:
    config.state_store.require_runtime_binding(
        namespace=config.namespace,
        consumer_lane=config.consumer_lane,
        manifest_auth_key_id=config.manifest_auth_key_id,
        manifest_hmac_key=config.manifest_hmac_key,
        head_auth_key_id=config.head_auth_key_id,
        head_hmac_key=config.head_hmac_key,
        epoch_auth_key_id=config.epoch_auth_key_id,
        epoch_hmac_key=config.epoch_hmac_key,
    )
    integrity, cursor = config.state_store.load_verified_snapshot_read_only_v1()
    if cursor is None:
        if integrity is not None:
            _fail("PROFILED_RESIDENT_EMPTY_STATE_INTEGRITY_CONFLICT")
        return None
    if (
        integrity is None
        or integrity.current_state_event_sha256 != cursor.state_event_sha256
        or integrity.current_cycle_id != cursor.cycle_id
        or integrity.current_phase != cursor.phase
        or integrity.complete_chain_verified is not True
    ):
        _fail("PROFILED_RESIDENT_STATE_INTEGRITY_INVALID")
    return cursor


def _completion_and_authorization(
    *,
    config: AuthenticatedProfiledResidentRuntimeConfigV1,
    cursor: ProfiledTrainingObservationCoordinatorCursorV1,
) -> tuple[
    LocalProfiledTrainingObservationCompletionCandidateV1,
    ProfiledOptimizerCompletionAuthorizationJournalRecordV1 | None,
]:
    if (
        cursor.manifest_path is None
        or cursor.manifest_id is None
        or cursor.completion_event_sha256 is None
        or cursor.completion_event_byte_count is None
        or cursor.completion_id is None
        or cursor.signed_head_durably_anchored is not True
        or cursor.witness_id != config.witness_id
        or cursor.witness_public_key_sha256 != config.expected_witness_public_key_sha256
    ):
        _fail("PROFILED_RESIDENT_COMPLETION_STATE_BINDING_INVALID")
    try:
        completion = read_local_profiled_training_observation_completion_candidate_v1(
            staging_store=config.completion_staging_store,
            completion_event_sha256=cursor.completion_event_sha256,
            completion_event_byte_count=cursor.completion_event_byte_count,
            epoch_hmac_key=config.epoch_hmac_key,
            epoch_auth_key_id=config.epoch_auth_key_id,
        )
    except Exception as exc:
        raise AuthenticatedProfiledResidentRuntimeV1Error(
            "PROFILED_RESIDENT_COMPLETION_REOPEN_FAILED"
        ) from exc
    if (
        completion.completion_id != cursor.completion_id
        or completion.manifest_id != cursor.manifest_id
        or completion.completion_event_sha256 != cursor.completion_event_sha256
        or completion.consumed_entry_count != cursor.total_profiled_samples
        or completion.admitted_entry_count != cursor.admitted_example_count
        or completion.label_unavailable_count != cursor.label_unavailable_count
        or completion.full_consumption_locally_verified is not True
    ):
        _fail("PROFILED_RESIDENT_COMPLETION_IDENTITY_INVALID")
    try:
        record = (
            config.completion_authorization_journal.load_request_for_completion_read_only_v1(
                witness_id=config.witness_id,
                authorization_namespace=config.witness_namespace,
                completion_event_sha256=cursor.completion_event_sha256,
                witness_public_key_bytes=config.witness_public_key_bytes,
            )
        )
    except ProfiledOptimizerCompletionAuthorizationJournalV1Error as exc:
        if exc.reasons == (
            "PROFILED_OPTIMIZER_AUTHORIZATION_JOURNAL_READ_ONLY_FILE_MISSING",
        ):
            return completion, None
        raise AuthenticatedProfiledResidentRuntimeV1Error(
            "PROFILED_RESIDENT_AUTHORIZATION_JOURNAL_INVALID"
        ) from exc
    except Exception as exc:
        raise AuthenticatedProfiledResidentRuntimeV1Error(
            "PROFILED_RESIDENT_AUTHORIZATION_JOURNAL_INVALID"
        ) from exc
    if record is None:
        return completion, None
    record.__post_init__()
    verified = record.verified
    if (
        record.state != AUTHORIZATION_ANCHORED
        or verified is None
        or record.prepared.manifest_id != cursor.manifest_id
        or record.prepared.completion_event_sha256 != cursor.completion_event_sha256
        or record.prepared.completion_event_byte_count != cursor.completion_event_byte_count
        or record.prepared.witness_id != config.witness_id
        or record.prepared.authorization_namespace != config.witness_namespace
        or record.prepared.witness_public_key_sha256 != config.expected_witness_public_key_sha256
        or verified.manifest_id != cursor.manifest_id
        or verified.completion_event_sha256 != cursor.completion_event_sha256
        or verified.witness_id != config.witness_id
        or verified.namespace != config.witness_namespace
        or verified.witness_public_key_sha256 != config.expected_witness_public_key_sha256
        or verified.external_monotonic_manifest_head_verified is not True
        or verified.full_consumption_external_ack_verified is not True
        or verified.profiled_optimizer_admission_authorized is not True
    ):
        _fail("PROFILED_RESIDENT_AUTHORIZATION_IDENTITY_INVALID")
    return completion, record


def _existing_publication(
    *,
    config: AuthenticatedProfiledResidentRuntimeConfigV1,
    candidate_manager: V2HybridCheckpointManager,
    cursor: ProfiledTrainingObservationCoordinatorCursorV1,
    record: ProfiledOptimizerCompletionAuthorizationJournalRecordV1,
):
    verified = record.verified
    if verified is None or cursor.manifest_id is None or cursor.completion_event_sha256 is None:
        _fail("PROFILED_RESIDENT_AUTHORIZATION_IDENTITY_INVALID")
    return find_authenticated_profiled_supervised_publication_for_completion_v1(
        candidate_checkpoint_manager=candidate_manager,
        manifest_id=cursor.manifest_id,
        completion_event_sha256=cursor.completion_event_sha256,
        external_authorization_envelope_sha256=(verified.authorization_envelope_sha256),
        witness_id=config.witness_id,
        witness_namespace=config.witness_namespace,
        witness_public_key_sha256=config.expected_witness_public_key_sha256,
        witness_sequence=verified.authorization_sequence,
    )


def capture_active_or_genesis_profiled_base_lineage_v1(
    *,
    repo_root: Path,
    base_model: V2HybridPolicyModel,
    base_manager: V2HybridCheckpointManager,
) -> AuthenticatedProfiledBaseCheckpointLineageV1:
    """Resolve only the activated serving base, or create a safe genesis."""

    if not isinstance(repo_root, Path) or not repo_root.is_absolute():
        _fail("PROFILED_RESIDENT_REPO_ROOT_INVALID")
    try:
        activation_path = manifest_paths(repo_root)[-1]
        os.lstat(activation_path)
    except FileNotFoundError:
        activation_manifest = None
    except OSError as exc:
        raise AuthenticatedProfiledResidentRuntimeV1Error(
            "PROFILED_RESIDENT_SERVING_ACTIVATION_PATH_INVALID"
        ) from exc
    else:
        try:
            activation_manifest = read_published_checkpoint_partition_manifest(
                repo_root=repo_root
            )
        except Exception as exc:
            raise AuthenticatedProfiledResidentRuntimeV1Error(
                "PROFILED_RESIDENT_SERVING_ACTIVATION_MANIFEST_INVALID"
            ) from exc
    try:
        serving = base_manager.manifests(
            input_dim=base_model.input_dim,
            model_id=base_model.model_id,
            allowed_lineage_kinds=frozenset({VERIFIED_SERVING_LINEAGE}),
            require_weight_blob=True,
        )
    except Exception as exc:
        raise AuthenticatedProfiledResidentRuntimeV1Error(
            "PROFILED_RESIDENT_SERVING_BASE_SCAN_FAILED"
        ) from exc
    if activation_manifest is None:
        if serving:
            _fail("PROFILED_RESIDENT_SERVING_BASE_WITHOUT_ACTIVATION")
        return ensure_authenticated_profiled_genesis_base_checkpoint_v1(
            base_model=base_model,
            base_checkpoint_manager=base_manager,
        )
    binding = activation_manifest.get("checkpoint_binding")
    checkpoint_id = binding.get("checkpoint_id") if isinstance(binding, dict) else None
    exact = tuple(item for item in serving if item.checkpoint_id == checkpoint_id)
    if len(exact) != 1:
        _fail("PROFILED_RESIDENT_ACTIVE_SERVING_BASE_NOT_EXACTLY_RESOLVED")
    manifest: CheckpointManifest = exact[0]
    if (
        binding.get("checkpoint_evidence_digest") != manifest.checkpoint_evidence_digest
        or binding.get("training_partition_digest") != manifest.training_partition_digest
    ):
        _fail("PROFILED_RESIDENT_ACTIVE_SERVING_BASE_BINDING_INVALID")
    return capture_authenticated_profiled_base_checkpoint_lineage_v1(
        base_model=base_model,
        base_checkpoint_manager=base_manager,
        expected_checkpoint_id=manifest.checkpoint_id,
    )


def run_authenticated_profiled_resident_cycle_v1(
    config: AuthenticatedProfiledResidentRuntimeConfigV1,
) -> AuthenticatedProfiledResidentRuntimeResultV1:
    """Run, recover, or safely wait for one authenticated profiled completion."""

    if type(config) is not AuthenticatedProfiledResidentRuntimeConfigV1:
        _fail("PROFILED_RESIDENT_CONFIG_EXACT_TYPE_REQUIRED")
    config.__post_init__()
    cursor = _state_snapshot(config)
    if cursor is None or cursor.phase != PROFILED_OBSERVATION_COORDINATOR_LOCAL_COMPLETION_STAGED:
        return _result(
            classification=PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION,
            cursor=cursor,
        )
    completion, record = _completion_and_authorization(
        config=config,
        cursor=cursor,
    )
    if record is None:
        return _result(
            classification=PROFILED_RESIDENT_WAITING_EXTERNAL_AUTHORIZATION,
            cursor=cursor,
        )
    verified = record.verified
    if verified is None or cursor.manifest_path is None or cursor.manifest_id is None:
        _fail("PROFILED_RESIDENT_AUTHORIZATION_IDENTITY_INVALID")
    base_manager = V2HybridCheckpointManager(config.model_dir)
    candidate_manager = V2HybridCheckpointManager(
        config.model_dir / "non_serving_training_candidates"
    )

    with checkpoint_lifecycle_lease(
        config.model_dir,
        owner_role="AUTHENTICATED_PROFILED_TRAINER",
    ):
        existing = _existing_publication(
            config=config,
            candidate_manager=candidate_manager,
            cursor=cursor,
            record=record,
        )
        if existing is not None:
            return _result(
                classification=PROFILED_RESIDENT_ALREADY_PUBLISHED,
                cursor=cursor,
                external_authorization_envelope_sha256=(verified.authorization_envelope_sha256),
                witness_namespace=config.witness_namespace,
                admitted_example_count=completion.admitted_entry_count,
                base_checkpoint_id=existing.base_checkpoint_id,
                candidate_checkpoint_id=existing.candidate_checkpoint_id,
                candidate_checkpoint_generation=(existing.candidate_checkpoint_generation),
            )

    admission_inputs = {
        "manifest_path": cursor.manifest_path,
        "ledger": config.feature_ledger,
        "trusted_immutable_cost_store_root": (config.trusted_immutable_cost_store_root),
        "manifest_hmac_key": config.manifest_hmac_key,
        "manifest_auth_key_id": config.manifest_auth_key_id,
        "expected_manifest_id": cursor.manifest_id,
        "expected_observation_time": cursor.observation_time,
        "local_completion": completion,
        "completion_staging_store": config.completion_staging_store,
        "epoch_hmac_key": config.epoch_hmac_key,
        "epoch_auth_key_id": config.epoch_auth_key_id,
        "external_authorization_envelope": verified.authorization_envelope_bytes,
        "expected_witness_id": config.witness_id,
        "expected_witness_namespace": config.witness_namespace,
        "witness_public_key_bytes": config.witness_public_key_bytes,
        "expected_witness_public_key_sha256": (config.expected_witness_public_key_sha256),
        "expected_witness_sequence": verified.authorization_sequence,
        "expected_previous_witness_event_sha256": (verified.previous_authorization_event_sha256),
        "authorization_challenge": record.prepared.authorization_challenge,
        "page_limit": config.page_limit,
    }
    before_admissions = admit_authenticated_profiled_optimizer_manifest_batch_v1(**admission_inputs)
    after_admissions = admit_authenticated_profiled_optimizer_manifest_batch_v1(**admission_inputs)
    if (
        before_admissions is after_admissions
        or len(before_admissions) != completion.admitted_entry_count
        or len(after_admissions) != completion.admitted_entry_count
        or any(
            left is right
            for left, right in zip(
                before_admissions,
                after_admissions,
                strict=True,
            )
        )
    ):
        _fail("PROFILED_RESIDENT_INDEPENDENT_ADMISSION_MATERIALIZATION_INVALID")
    before_corpus = build_authenticated_profiled_optimizer_corpus_v1(before_admissions)
    after_corpus = build_authenticated_profiled_optimizer_corpus_v1(after_admissions)
    execution_authorization = (
        validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
            before=before_corpus,
            after=after_corpus,
        )
    )

    with checkpoint_lifecycle_lease(
        config.model_dir,
        owner_role="AUTHENTICATED_PROFILED_TRAINER",
    ) as lifecycle_lease:
        current_cursor = _state_snapshot(config)
        if current_cursor != cursor:
            _fail("PROFILED_RESIDENT_COORDINATOR_STATE_MOVED_DURING_MATERIALIZATION")
        current_completion, current_record = _completion_and_authorization(
            config=config,
            cursor=current_cursor,
        )
        current_verified = None if current_record is None else current_record.verified
        if (
            current_record is None
            or current_verified is None
            or current_completion.completion_id != completion.completion_id
            or current_completion.completion_event_sha256 != completion.completion_event_sha256
            or current_record.prepared.request_sha256 != record.prepared.request_sha256
            or current_verified.authorization_envelope_sha256
            != verified.authorization_envelope_sha256
            or current_verified.authorization_sequence != verified.authorization_sequence
        ):
            _fail("PROFILED_RESIDENT_AUTHORIZATION_MOVED_DURING_MATERIALIZATION")
        existing = _existing_publication(
            config=config,
            candidate_manager=candidate_manager,
            cursor=cursor,
            record=record,
        )
        if existing is not None:
            return _result(
                classification=PROFILED_RESIDENT_ALREADY_PUBLISHED,
                cursor=cursor,
                external_authorization_envelope_sha256=(verified.authorization_envelope_sha256),
                witness_namespace=config.witness_namespace,
                admitted_example_count=completion.admitted_entry_count,
                base_checkpoint_id=existing.base_checkpoint_id,
                candidate_checkpoint_id=existing.candidate_checkpoint_id,
                candidate_checkpoint_generation=(existing.candidate_checkpoint_generation),
            )
        base_model = V2HybridPolicyModel(
            input_dim=LOGICAL_MODEL_INPUT_COUNT,
            checkpoint_feature_abi_binding=deployed_checkpoint_feature_abi_binding_v4(),
        )
        base_lineage = capture_active_or_genesis_profiled_base_lineage_v1(
            repo_root=config.repo_root,
            base_model=base_model,
            base_manager=base_manager,
        )
        training_observed_at = _clock(
            config.clock(),
            reason="PROFILED_RESIDENT_TRAINING_OBSERVATION_CLOCK_INVALID",
        )
        witness_accepted_at = _clock(
            verified.accepted_at,
            reason="PROFILED_RESIDENT_WITNESS_ACCEPTED_CLOCK_INVALID",
        )
        if training_observed_at <= witness_accepted_at:
            _fail("PROFILED_RESIDENT_TRAINING_NOT_AFTER_WITNESS_ACCEPTANCE")
        trainer = V2HybridPPOTrainer(
            model=base_model,
            training_observed_at=training_observed_at,
        )
        bound_execution = execute_lineage_bound_authenticated_profiled_supervised_optimizer_v1(
            base_lineage=base_lineage,
            base_checkpoint_manager=base_manager,
            before_corpus=before_corpus,
            after_corpus=after_corpus,
            execution_authorization=execution_authorization,
            base_model=base_model,
            trainer=trainer,
            validation_fraction=config.validation_fraction,
            optimizer_input_byte_budget=config.optimizer_input_byte_budget,
            state_resource_budget_bytes=config.state_resource_budget_bytes,
            checkpoint_serialization_byte_budget=(config.checkpoint_serialization_byte_budget),
            clock=config.clock,
        )
        publication = publish_authenticated_profiled_supervised_checkpoint_v1(
            bound_execution=bound_execution,
            candidate_checkpoint_manager=candidate_manager,
            lifecycle_lease=lifecycle_lease,
        )
        return _result(
            classification=PROFILED_RESIDENT_PUBLICATION_COMPLETED,
            cursor=cursor,
            external_authorization_envelope_sha256=(verified.authorization_envelope_sha256),
            witness_namespace=config.witness_namespace,
            admitted_example_count=completion.admitted_entry_count,
            base_checkpoint_id=publication.base_checkpoint_id,
            candidate_checkpoint_id=publication.candidate_checkpoint_id,
            candidate_checkpoint_generation=(publication.candidate_checkpoint_generation),
        )


__all__ = (
    "AUTHENTICATED_PROFILED_RESIDENT_RUNTIME_V1_SCHEMA_VERSION",
    "PROFILED_RESIDENT_ALREADY_PUBLISHED",
    "PROFILED_RESIDENT_PUBLICATION_COMPLETED",
    "PROFILED_RESIDENT_WAITING_EXTERNAL_AUTHORIZATION",
    "PROFILED_RESIDENT_WAITING_LOCAL_COMPLETION",
    "AuthenticatedProfiledResidentRuntimeConfigV1",
    "AuthenticatedProfiledResidentRuntimeResultV1",
    "AuthenticatedProfiledResidentRuntimeV1Error",
    "capture_active_or_genesis_profiled_base_lineage_v1",
    "run_authenticated_profiled_resident_cycle_v1",
)
