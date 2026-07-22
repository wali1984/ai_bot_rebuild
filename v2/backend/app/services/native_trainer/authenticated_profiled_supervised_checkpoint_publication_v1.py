from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.authenticated_profiled_base_checkpoint_lineage_v1 import (  # noqa: E501
    AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
    AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION,
    AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE,
    AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION,
    AuthenticatedProfiledBaseCheckpointLineageV1,
    AuthenticatedProfiledBaseCheckpointLineageV1Error,
    revalidate_authenticated_profiled_base_checkpoint_lineage_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (
    AuthenticatedProfiledOptimizerCorpusV1,
    AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_supervised_optimizer_execution_v1 import (  # noqa: E501
    AuthenticatedProfiledSupervisedOptimizerExecutionV1,
    AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
    execute_authenticated_profiled_supervised_optimizer_v1,
    revalidate_authenticated_profiled_supervised_optimizer_publication_boundary_v1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    CheckpointManifest,
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (
    VERIFIED_SERVING_LINEAGE,
    CheckpointLifecycleLeaseReceipt,
    require_active_checkpoint_lifecycle_lease,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)

AUTHENTICATED_PROFILED_LINEAGE_BOUND_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_lineage_bound_optimizer_execution_v1"
)
AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_STATUS: Final = (
    "DURABLE_AUTHENTICATED_PROFILED_NON_SERVING_CANDIDATE_VERIFIED"
)
AUTHENTICATED_PROFILED_EXISTING_PUBLICATION_V1_STATUS: Final = (
    "EXISTING_AUTHENTICATED_PROFILED_NON_SERVING_CANDIDATE_VERIFIED"
)
_DOWNSTREAM_AUTHORITY_FALSE: Final = {
    "prediction_authorized": False,
    "serving_authorized": False,
    "serving_activation_authorized": False,
    "serving_promotion_authorized": False,
    "ppo_training_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}
_BOUND_TOKEN = object()
_BOUND_SEAL_KEY = secrets.token_bytes(32)
_BOUND_SEAL_DOMAIN: Final = (
    b"authenticated_profiled_lineage_bound_optimizer_execution_v1\0"
)
_PUBLICATION_TOKEN = object()
_PUBLICATION_SEAL_KEY = secrets.token_bytes(32)
_PUBLICATION_SEAL_DOMAIN: Final = (
    b"authenticated_profiled_supervised_checkpoint_publication_v1\0"
)


class AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(RuntimeError):
    """A lineage-bound non-serving publication failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and all(character in "0123456789abcdef" for character in cast(str, value))
    )


def _canonical_json(value: object, *, reason: str) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        _fail(reason)
    if not encoded:
        _fail(reason)
    return encoded


def _strict_json_object(payload: bytes, *, reason: str) -> dict[str, Any]:
    if type(payload) is not bytes or not payload:
        _fail(reason)

    def reject_constant(_value: str) -> NoReturn:
        _fail(reason)

    try:
        value = json.loads(payload.decode("ascii"), parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError):
        _fail(reason)
    if type(value) is not dict or _canonical_json(value, reason=reason) != payload:
        _fail(reason)
    return cast(dict[str, Any], value)


def _checkpoint_evidence_sha256(value: object) -> str:
    if type(value) is not dict:
        _fail("PROFILED_SUPERVISED_PUBLICATION_CHECKPOINT_EVIDENCE_INVALID")
    try:
        return stable_sha256(value)
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_PUBLICATION_CHECKPOINT_EVIDENCE_INVALID"
        ) from exc


def _bound_material(values: dict[str, Any]) -> dict[str, Any]:
    names = (
        "schema_version",
        "base_checkpoint_lineage_binding_sha256",
        "execution_idempotency_key",
        "execution_authorization_inventory_equality_sha256",
        "corpus_contract_sha256",
        "base_model_parameter_fingerprint",
        "candidate_model_parameter_fingerprint",
        "optimizer_implementation_artifact_sha256",
        "optimizer_configuration_artifact_sha256",
        "execution_environment_artifact_sha256",
        "training_result_artifact_sha256",
        "base_checkpoint_lineage_verified_before_execution",
        "base_checkpoint_lineage_reverified_after_execution",
        "checkpoint_write_authorized",
        "serving_authorized",
        "trading_authorized",
    )
    return {name: values[name] for name in names}


def _bound_seal(material: dict[str, Any], *, owner_ids: tuple[int, ...]) -> bytes:
    return hmac.new(
        _BOUND_SEAL_KEY,
        _BOUND_SEAL_DOMAIN
        + _canonical_json(
            {"material": material, "owner_ids": list(owner_ids)},
            reason="PROFILED_SUPERVISED_PUBLICATION_BOUND_SEAL_INVALID",
        ),
        hashlib.sha256,
    ).digest()


def _publication_seal(
    material: dict[str, Any], *, owner_ids: tuple[int, ...]
) -> bytes:
    return hmac.new(
        _PUBLICATION_SEAL_KEY,
        _PUBLICATION_SEAL_DOMAIN
        + _canonical_json(
            {"material": material, "owner_ids": list(owner_ids)},
            reason="PROFILED_SUPERVISED_PUBLICATION_RESULT_SEAL_INVALID",
        ),
        hashlib.sha256,
    ).digest()


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledLineageBoundOptimizerExecutionV1:
    schema_version: str
    base_checkpoint_lineage_binding_sha256: str
    execution_idempotency_key: str
    execution_authorization_inventory_equality_sha256: str
    corpus_contract_sha256: str
    base_model_parameter_fingerprint: str
    candidate_model_parameter_fingerprint: str
    optimizer_implementation_artifact_sha256: str
    optimizer_configuration_artifact_sha256: str
    execution_environment_artifact_sha256: str
    training_result_artifact_sha256: str
    lineage_bound_execution_sha256: str
    base_checkpoint_lineage_verified_before_execution: bool
    base_checkpoint_lineage_reverified_after_execution: bool
    checkpoint_write_authorized: bool
    serving_authorized: bool
    trading_authorized: bool
    execution: AuthenticatedProfiledSupervisedOptimizerExecutionV1 = field(
        repr=False,
        compare=False,
    )
    base_lineage: AuthenticatedProfiledBaseCheckpointLineageV1 = field(
        repr=False,
        compare=False,
    )
    _base_checkpoint_manager_owner: V2HybridCheckpointManager = field(
        repr=False,
        compare=False,
    )
    _base_model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _candidate_model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _seal_mac: bytes = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        material = _bound_material(
            {name: getattr(self, name) for name in _bound_material_names()}
        )
        if (
            self._construction_token is not _BOUND_TOKEN
            or self.schema_version
            != AUTHENTICATED_PROFILED_LINEAGE_BOUND_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION
            or type(self.execution)
            is not AuthenticatedProfiledSupervisedOptimizerExecutionV1
            or type(self.base_lineage) is not AuthenticatedProfiledBaseCheckpointLineageV1
            or type(self._base_checkpoint_manager_owner)
            is not V2HybridCheckpointManager
            or type(self._base_model_owner) is not V2HybridPolicyModel
            or type(self._candidate_model_owner) is not V2HybridPolicyModel
            or not all(
                _valid_sha256(value)
                for value in (
                    self.base_checkpoint_lineage_binding_sha256,
                    self.execution_idempotency_key,
                    self.execution_authorization_inventory_equality_sha256,
                    self.corpus_contract_sha256,
                    self.base_model_parameter_fingerprint,
                    self.candidate_model_parameter_fingerprint,
                    self.optimizer_implementation_artifact_sha256,
                    self.optimizer_configuration_artifact_sha256,
                    self.execution_environment_artifact_sha256,
                    self.training_result_artifact_sha256,
                    self.lineage_bound_execution_sha256,
                )
            )
            or self.lineage_bound_execution_sha256 != stable_sha256(material)
            or self.base_checkpoint_lineage_binding_sha256
            != self.base_lineage.base_checkpoint_lineage_binding_sha256
            or self.execution_idempotency_key
            != self.execution.execution_idempotency_key
            or self.execution_authorization_inventory_equality_sha256
            != self.execution.execution_authorization_inventory_equality_sha256
            or self.corpus_contract_sha256 != self.execution.corpus_contract_sha256
            or self.base_model_parameter_fingerprint
            != self.execution.base_model_parameter_fingerprint
            or self.base_model_parameter_fingerprint
            != self.base_lineage.model_parameter_fingerprint
            or self.candidate_model_parameter_fingerprint
            != self.execution.candidate_model_parameter_fingerprint
            or self.optimizer_implementation_artifact_sha256
            != self.execution.optimizer_implementation_artifact_sha256
            or self.optimizer_configuration_artifact_sha256
            != self.execution.optimizer_configuration_artifact_sha256
            or self.execution_environment_artifact_sha256
            != self.execution.execution_environment_artifact_sha256
            or self.training_result_artifact_sha256
            != self.execution.training_result_artifact_sha256
            or model_parameter_fingerprint(self._base_model_owner)
            != self.base_model_parameter_fingerprint
            or model_parameter_fingerprint(self._candidate_model_owner)
            != self.candidate_model_parameter_fingerprint
            or any(
                value is not expected
                for value, expected in (
                    (self.base_checkpoint_lineage_verified_before_execution, True),
                    (self.base_checkpoint_lineage_reverified_after_execution, True),
                    (self.checkpoint_write_authorized, False),
                    (self.serving_authorized, False),
                    (self.trading_authorized, False),
                )
            )
            or not hmac.compare_digest(
                self._seal_mac,
                _bound_seal(
                    material,
                    owner_ids=(
                        id(self.execution),
                        id(self.base_lineage),
                        id(self._base_checkpoint_manager_owner),
                        id(self._base_model_owner),
                        id(self._candidate_model_owner),
                    ),
                ),
            )
        ):
            _fail("PROFILED_SUPERVISED_PUBLICATION_BOUND_EXECUTION_INVALID")
        try:
            self.execution.__post_init__()
            self.base_lineage.__post_init__()
        except (
            AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
            AuthenticatedProfiledBaseCheckpointLineageV1Error,
        ) as exc:
            raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
                "PROFILED_SUPERVISED_PUBLICATION_BOUND_OWNER_REVALIDATION_FAILED"
            ) from exc

    @property
    def candidate_model(self) -> V2HybridPolicyModel:
        self.__post_init__()
        return self._candidate_model_owner

    def __reduce_ex__(self, _protocol: int) -> NoReturn:
        _fail("PROFILED_SUPERVISED_PUBLICATION_BOUND_EXECUTION_COPY_FORBIDDEN")


def _bound_material_names() -> tuple[str, ...]:
    return (
        "schema_version",
        "base_checkpoint_lineage_binding_sha256",
        "execution_idempotency_key",
        "execution_authorization_inventory_equality_sha256",
        "corpus_contract_sha256",
        "base_model_parameter_fingerprint",
        "candidate_model_parameter_fingerprint",
        "optimizer_implementation_artifact_sha256",
        "optimizer_configuration_artifact_sha256",
        "execution_environment_artifact_sha256",
        "training_result_artifact_sha256",
        "base_checkpoint_lineage_verified_before_execution",
        "base_checkpoint_lineage_reverified_after_execution",
        "checkpoint_write_authorized",
        "serving_authorized",
        "trading_authorized",
    )


def execute_lineage_bound_authenticated_profiled_supervised_optimizer_v1(
    *,
    base_lineage: AuthenticatedProfiledBaseCheckpointLineageV1,
    base_checkpoint_manager: V2HybridCheckpointManager,
    before_corpus: AuthenticatedProfiledOptimizerCorpusV1,
    after_corpus: AuthenticatedProfiledOptimizerCorpusV1,
    execution_authorization: (
        AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1
    ),
    base_model: V2HybridPolicyModel,
    trainer: V2HybridPPOTrainer,
    validation_fraction: float,
    optimizer_input_byte_budget: int,
    state_resource_budget_bytes: int,
    checkpoint_serialization_byte_budget: int,
    clock: Callable[[], datetime | str],
) -> AuthenticatedProfiledLineageBoundOptimizerExecutionV1:
    """Verify the exact parent before and after the one-step optimizer call."""

    try:
        revalidate_authenticated_profiled_base_checkpoint_lineage_v1(
            lineage=base_lineage,
            base_model=base_model,
            base_checkpoint_manager=base_checkpoint_manager,
        )
    except AuthenticatedProfiledBaseCheckpointLineageV1Error as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_PUBLICATION_PREEXECUTION_BASE_INVALID",
            *exc.reasons,
        ) from exc
    execution = execute_authenticated_profiled_supervised_optimizer_v1(
        before_corpus=before_corpus,
        after_corpus=after_corpus,
        execution_authorization=execution_authorization,
        base_model=base_model,
        trainer=trainer,
        validation_fraction=validation_fraction,
        optimizer_input_byte_budget=optimizer_input_byte_budget,
        state_resource_budget_bytes=state_resource_budget_bytes,
        checkpoint_serialization_byte_budget=checkpoint_serialization_byte_budget,
        clock=clock,
    )
    try:
        revalidate_authenticated_profiled_base_checkpoint_lineage_v1(
            lineage=base_lineage,
            base_model=base_model,
            base_checkpoint_manager=base_checkpoint_manager,
        )
        revalidate_authenticated_profiled_supervised_optimizer_publication_boundary_v1(
            execution=execution,
            base_model=base_model,
            candidate_model=execution.candidate_model,
        )
    except (
        AuthenticatedProfiledBaseCheckpointLineageV1Error,
        AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
    ) as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_PUBLICATION_POSTEXECUTION_LINEAGE_INVALID"
        ) from exc
    values: dict[str, Any] = {
        "schema_version": (
            AUTHENTICATED_PROFILED_LINEAGE_BOUND_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION
        ),
        "base_checkpoint_lineage_binding_sha256": (
            base_lineage.base_checkpoint_lineage_binding_sha256
        ),
        "execution_idempotency_key": execution.execution_idempotency_key,
        "execution_authorization_inventory_equality_sha256": (
            execution.execution_authorization_inventory_equality_sha256
        ),
        "corpus_contract_sha256": execution.corpus_contract_sha256,
        "base_model_parameter_fingerprint": execution.base_model_parameter_fingerprint,
        "candidate_model_parameter_fingerprint": (
            execution.candidate_model_parameter_fingerprint
        ),
        "optimizer_implementation_artifact_sha256": (
            execution.optimizer_implementation_artifact_sha256
        ),
        "optimizer_configuration_artifact_sha256": (
            execution.optimizer_configuration_artifact_sha256
        ),
        "execution_environment_artifact_sha256": (
            execution.execution_environment_artifact_sha256
        ),
        "training_result_artifact_sha256": execution.training_result_artifact_sha256,
        "lineage_bound_execution_sha256": "0" * 64,
        "base_checkpoint_lineage_verified_before_execution": True,
        "base_checkpoint_lineage_reverified_after_execution": True,
        "checkpoint_write_authorized": False,
        "serving_authorized": False,
        "trading_authorized": False,
        "execution": execution,
        "base_lineage": base_lineage,
        "_base_checkpoint_manager_owner": base_checkpoint_manager,
        "_base_model_owner": base_model,
        "_candidate_model_owner": execution.candidate_model,
        "_seal_mac": b"placeholder",
        "_construction_token": _BOUND_TOKEN,
    }
    values["lineage_bound_execution_sha256"] = stable_sha256(_bound_material(values))
    material = _bound_material(values)
    values["_seal_mac"] = _bound_seal(
        material,
        owner_ids=(
            id(execution),
            id(base_lineage),
            id(base_checkpoint_manager),
            id(base_model),
            id(execution.candidate_model),
        ),
    )
    return AuthenticatedProfiledLineageBoundOptimizerExecutionV1(**values)


def _manager_roots(
    *,
    bound_execution: AuthenticatedProfiledLineageBoundOptimizerExecutionV1,
    candidate_checkpoint_manager: V2HybridCheckpointManager,
) -> tuple[Path, Path]:
    if (
        type(bound_execution) is not AuthenticatedProfiledLineageBoundOptimizerExecutionV1
        or type(candidate_checkpoint_manager) is not V2HybridCheckpointManager
    ):
        _fail("PROFILED_SUPERVISED_PUBLICATION_MANAGER_INPUT_TYPES_INVALID")
    candidate_directory = candidate_checkpoint_manager.model_dir.resolve()
    if candidate_directory.name != "non_serving_training_candidates":
        _fail("PROFILED_SUPERVISED_PUBLICATION_CANDIDATE_STORE_REQUIRED")
    checkpoint_root = candidate_directory.parent
    base_manager = bound_execution._base_checkpoint_manager_owner
    base_directory = base_manager.model_dir.resolve()
    if bound_execution.base_lineage.lineage_kind not in {
        VERIFIED_SERVING_LINEAGE,
        AUTHENTICATED_PROFILED_SUPERVISED_GENESIS_BASE_LINEAGE,
    }:
        _fail("PROFILED_SUPERVISED_PUBLICATION_BASE_LINEAGE_INVALID")
    if base_directory != checkpoint_root:
        _fail("PROFILED_SUPERVISED_PUBLICATION_SERVING_BASE_STORE_INVALID")
    return checkpoint_root, candidate_directory


def _partition_digest(
    execution: AuthenticatedProfiledSupervisedOptimizerExecutionV1,
) -> str:
    return stable_sha256(
        {
            "domain": (
                "v2/native-trainer/authenticated-profiled-supervised-publication/"
                "partition/v1"
            ),
            "corpus_contract_sha256": execution.corpus_contract_sha256,
            "execution_authorization_inventory_equality_sha256": (
                execution.execution_authorization_inventory_equality_sha256
            ),
            "ordered_optimizer_training_rows_sha256": (
                execution.ordered_optimizer_training_rows_sha256
            ),
            "ordered_validation_rows_sha256": execution.ordered_validation_rows_sha256,
            "optimizer_training_row_count": execution.optimizer_training_row_count,
            "validation_row_count": execution.validation_row_count,
        }
    )


def _publication_idempotency_key(
    bound_execution: AuthenticatedProfiledLineageBoundOptimizerExecutionV1,
) -> str:
    execution = bound_execution.execution
    return stable_sha256(
        {
            "domain": (
                "v2/native-trainer/authenticated-profiled-supervised-publication/"
                "idempotency/v1"
            ),
            "base_checkpoint_lineage_binding_sha256": (
                bound_execution.base_checkpoint_lineage_binding_sha256
            ),
            "execution_idempotency_key": execution.execution_idempotency_key,
            "corpus_contract_sha256": execution.corpus_contract_sha256,
            "execution_authorization_inventory_equality_sha256": (
                execution.execution_authorization_inventory_equality_sha256
            ),
            "base_model_parameter_fingerprint": (
                execution.base_model_parameter_fingerprint
            ),
            "candidate_model_parameter_fingerprint": (
                execution.candidate_model_parameter_fingerprint
            ),
            "optimizer_implementation_artifact_sha256": (
                execution.optimizer_implementation_artifact_sha256
            ),
            "optimizer_configuration_artifact_sha256": (
                execution.optimizer_configuration_artifact_sha256
            ),
            "execution_environment_artifact_sha256": (
                execution.execution_environment_artifact_sha256
            ),
            "training_result_artifact_sha256": (
                execution.training_result_artifact_sha256
            ),
            "lineage_kind": AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
        }
    )


def _publication_contract(
    *,
    bound_execution: AuthenticatedProfiledLineageBoundOptimizerExecutionV1,
    publication_idempotency_key: str,
    training_partition_digest: str,
) -> dict[str, Any]:
    execution = bound_execution.execution
    checkpoint = execution.checkpoint_candidate
    optimizer_evidence = _strict_json_object(
        execution.training_result_artifact_json_bytes,
        reason="PROFILED_SUPERVISED_PUBLICATION_TRAINING_RESULT_INVALID",
    )
    return {
        "schema_version": (
            AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION
        ),
        "ledger_disposition": AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION,
        "lineage_kind": AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
        "publication_idempotency_key": publication_idempotency_key,
        "base_checkpoint_lineage_binding_sha256": (
            bound_execution.base_checkpoint_lineage_binding_sha256
        ),
        "execution_idempotency_key": execution.execution_idempotency_key,
        "manifest_id": execution.manifest_id,
        "completion_event_sha256": execution.completion_event_sha256,
        "corpus_contract_sha256": execution.corpus_contract_sha256,
        "execution_authorization_inventory_equality_sha256": (
            execution.execution_authorization_inventory_equality_sha256
        ),
        "external_authorization_envelope_sha256": (
            checkpoint.external_authorization_envelope_sha256
        ),
        "witness_id": checkpoint.witness_id,
        "witness_namespace": checkpoint.witness_namespace,
        "witness_public_key_sha256": checkpoint.witness_public_key_sha256,
        "witness_sequence": checkpoint.witness_sequence,
        "witness_previous_event_sha256": checkpoint.witness_previous_event_sha256,
        "witness_accepted_at": checkpoint.witness_accepted_at,
        "base_checkpoint_id": bound_execution.base_lineage.checkpoint_id,
        "base_checkpoint_weight_sha256": (
            bound_execution.base_lineage.checkpoint_weight_sha256
        ),
        "base_checkpoint_evidence_digest": (
            bound_execution.base_lineage.checkpoint_evidence_digest
        ),
        "base_checkpoint_generation": bound_execution.base_lineage.checkpoint_generation,
        "base_checkpoint_semantic_digest": (
            bound_execution.base_lineage.checkpoint_semantic_digest
        ),
        "base_checkpoint_causal_record_digest": (
            bound_execution.base_lineage.checkpoint_causal_record_digest
        ),
        "base_model_parameter_fingerprint": execution.base_model_parameter_fingerprint,
        "candidate_model_parameter_fingerprint": (
            execution.candidate_model_parameter_fingerprint
        ),
        "base_nonparameter_model_state_sha256": (
            execution.base_nonparameter_model_state_sha256
        ),
        "candidate_nonparameter_model_state_sha256": (
            execution.candidate_nonparameter_model_state_sha256
        ),
        "ordered_optimizer_training_rows_sha256": (
            execution.ordered_optimizer_training_rows_sha256
        ),
        "ordered_validation_rows_sha256": execution.ordered_validation_rows_sha256,
        "optimizer_training_row_count": execution.optimizer_training_row_count,
        "validation_row_count": execution.validation_row_count,
        "optimizer_steps_completed": execution.optimizer_steps_completed,
        "learning_mode": execution.learning_mode,
        "training_partition_digest": training_partition_digest,
        "code_release_sha": execution.code_release_sha,
        "optimizer_implementation_artifact_sha256": (
            execution.optimizer_implementation_artifact_sha256
        ),
        "optimizer_configuration_artifact_sha256": (
            execution.optimizer_configuration_artifact_sha256
        ),
        "execution_environment_artifact_sha256": (
            execution.execution_environment_artifact_sha256
        ),
        "training_result_artifact_sha256": execution.training_result_artifact_sha256,
        "optimizer_evidence": optimizer_evidence,
        "optimizer_state_persisted": execution.optimizer_state_persisted,
        "optimizer_state_contract": (
            "STATELESS_ADAMW_RECREATED_PER_AUTHENTICATED_ONE_STEP_EXECUTION"
        ),
        "anomaly_free_optimizer_cycle": execution.anomaly_free_optimizer_cycle,
        "base_checkpoint_lineage_verified": True,
        "stable_execution_evidence_bound": True,
        "non_serving_candidate_only": True,
        "checkpoint_write_authorized": True,
        **_DOWNSTREAM_AUTHORITY_FALSE,
    }


def _preflight_publication_conflicts(
    *,
    candidate_checkpoint_manager: V2HybridCheckpointManager,
    publication_contract: dict[str, Any],
) -> None:
    """Reject a reused execution/key conflict before any durable mutation."""

    try:
        manifests = candidate_checkpoint_manager.manifests(
            allowed_lineage_kinds=frozenset(
                {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
            ),
            require_weight_blob=True,
        )
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_PUBLICATION_PREFLIGHT_SCAN_FAILED"
        ) from exc
    if candidate_checkpoint_manager._manifest_scan_errors:
        _fail("PROFILED_SUPERVISED_PUBLICATION_PREFLIGHT_SCAN_INVALID")
    publication_idempotency_key = publication_contract["publication_idempotency_key"]
    execution_idempotency_key = publication_contract["execution_idempotency_key"]
    witness_id = publication_contract["witness_id"]
    witness_namespace = publication_contract["witness_namespace"]
    witness_sequence = publication_contract["witness_sequence"]
    matching_publication: list[CheckpointManifest] = []
    same_witness_history: list[tuple[int, int]] = []
    for manifest in manifests:
        observed = manifest.checkpoint_evidence.get(
            "authenticated_profiled_supervised_publication"
        )
        if type(observed) is not dict:
            _fail("PROFILED_SUPERVISED_PUBLICATION_EXISTING_EVIDENCE_INVALID")
        if (
            observed.get("witness_id") == witness_id
            and observed.get("witness_namespace") == witness_namespace
        ):
            observed_sequence = observed.get("witness_sequence")
            if type(observed_sequence) is not int or observed_sequence <= 0:
                _fail("PROFILED_SUPERVISED_PUBLICATION_WITNESS_HISTORY_INVALID")
            same_witness_history.append(
                (manifest.checkpoint_generation, observed_sequence)
            )
        same_publication = (
            observed.get("publication_idempotency_key")
            == publication_idempotency_key
        )
        same_execution = (
            observed.get("execution_idempotency_key") == execution_idempotency_key
        )
        if same_execution and not same_publication:
            _fail("PROFILED_SUPERVISED_PUBLICATION_EXECUTION_IDENTITY_CONFLICT")
        if not same_publication:
            continue
        matching_publication.append(manifest)
        if (
            observed != publication_contract
            or manifest.parent_checkpoint_id
            != publication_contract["base_checkpoint_id"]
            or manifest.parent_policy_fingerprint
            != publication_contract["base_model_parameter_fingerprint"]
            or manifest.model_parameter_fingerprint
            != publication_contract["candidate_model_parameter_fingerprint"]
            or manifest.training_partition_digest
            != publication_contract["training_partition_digest"]
            or manifest.consumed_ppo_update_keys
        ):
            _fail("PROFILED_SUPERVISED_PUBLICATION_IDEMPOTENCY_CONFLICT")
        verification = candidate_checkpoint_manager.verify_manifest_artifact(manifest)
        if verification.get("checkpoint_artifact_verified") is not True:
            _fail("PROFILED_SUPERVISED_PUBLICATION_EXISTING_ARTIFACT_INVALID")
    if len(matching_publication) > 1:
        _fail("PROFILED_SUPERVISED_PUBLICATION_IDEMPOTENCY_AMBIGUOUS")
    ordered_witness_history = tuple(sorted(same_witness_history))
    if any(
        current_sequence <= previous_sequence
        for (_, previous_sequence), (_, current_sequence) in zip(
            ordered_witness_history,
            ordered_witness_history[1:],
            strict=False,
        )
    ):
        _fail("PROFILED_SUPERVISED_PUBLICATION_WITNESS_HISTORY_NON_MONOTONIC")
    if not matching_publication and any(
        published_sequence >= witness_sequence
        for _, published_sequence in ordered_witness_history
    ):
        _fail("PROFILED_SUPERVISED_PUBLICATION_WITNESS_SEQUENCE_NOT_SUCCESSOR")


def _recovery_contract_valid(
    *,
    manifest: CheckpointManifest,
    contract: object,
) -> bool:
    if type(contract) is not dict:
        return False
    material = cast(dict[str, Any], contract)
    required_sha256 = (
        "publication_idempotency_key",
        "base_checkpoint_lineage_binding_sha256",
        "execution_idempotency_key",
        "manifest_id",
        "completion_event_sha256",
        "corpus_contract_sha256",
        "execution_authorization_inventory_equality_sha256",
        "external_authorization_envelope_sha256",
        "witness_public_key_sha256",
        "witness_previous_event_sha256",
        "base_checkpoint_weight_sha256",
        "base_checkpoint_evidence_digest",
        "base_checkpoint_semantic_digest",
        "base_checkpoint_causal_record_digest",
        "base_model_parameter_fingerprint",
        "candidate_model_parameter_fingerprint",
        "base_nonparameter_model_state_sha256",
        "candidate_nonparameter_model_state_sha256",
        "ordered_optimizer_training_rows_sha256",
        "ordered_validation_rows_sha256",
        "training_partition_digest",
        "optimizer_implementation_artifact_sha256",
        "optimizer_configuration_artifact_sha256",
        "execution_environment_artifact_sha256",
        "training_result_artifact_sha256",
    )
    witness_id = material.get("witness_id")
    witness_namespace = material.get("witness_namespace")
    code_release_sha = material.get("code_release_sha")
    return bool(
        material.get("schema_version")
        == AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION
        and manifest.checkpoint_evidence.get("checkpoint_role")
        == AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE
        and manifest.checkpoint_evidence.get("ledger_disposition")
        == AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION
        and material.get("ledger_disposition")
        == AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION
        and material.get("lineage_kind")
        == AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE
        and all(_valid_sha256(material.get(name)) for name in required_sha256)
        and type(witness_id) is str
        and bool(witness_id)
        and witness_id.isascii()
        and type(witness_namespace) is str
        and bool(witness_namespace)
        and witness_namespace.isascii()
        and type(material.get("witness_sequence")) is int
        and material["witness_sequence"] > 0
        and type(code_release_sha) is str
        and len(code_release_sha) == 40
        and all(character in "0123456789abcdef" for character in code_release_sha)
        and type(material.get("base_checkpoint_generation")) is int
        and 0
        < material["base_checkpoint_generation"]
        < manifest.checkpoint_generation
        and type(material.get("optimizer_training_row_count")) is int
        and material["optimizer_training_row_count"] > 0
        and type(material.get("validation_row_count")) is int
        and material["validation_row_count"] >= 0
        and material.get("optimizer_steps_completed") == 1
        and material.get("learning_mode") == "outcome_supervised"
        and material.get("optimizer_state_persisted") is False
        and material.get("anomaly_free_optimizer_cycle") is True
        and material.get("base_checkpoint_lineage_verified") is True
        and material.get("stable_execution_evidence_bound") is True
        and material.get("non_serving_candidate_only") is True
        and material.get("checkpoint_write_authorized") is True
        and all(
            material.get(name) is expected
            for name, expected in _DOWNSTREAM_AUTHORITY_FALSE.items()
        )
        and manifest.lineage_kind
        == AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE
        and manifest.parent_checkpoint_id == material.get("base_checkpoint_id")
        and manifest.parent_policy_fingerprint
        == material.get("base_model_parameter_fingerprint")
        and manifest.model_parameter_fingerprint
        == material.get("candidate_model_parameter_fingerprint")
        and manifest.training_partition_digest
        == material.get("training_partition_digest")
        and not manifest.consumed_ppo_update_keys
    )


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledExistingPublicationV1:
    schema_version: str
    status: str
    manifest_id: str
    completion_event_sha256: str
    external_authorization_envelope_sha256: str
    witness_id: str
    witness_namespace: str
    witness_public_key_sha256: str
    witness_sequence: int
    publication_idempotency_key: str
    base_checkpoint_id: str
    candidate_checkpoint_id: str
    candidate_checkpoint_weight_sha256: str
    candidate_checkpoint_evidence_digest: str
    candidate_checkpoint_generation: int
    candidate_model_parameter_fingerprint: str
    already_published: bool
    checkpoint_artifact_verified: bool
    checkpoint_write_authorized: bool
    serving_authorized: bool
    trading_authorized: bool
    _checkpoint_manifest_owner: CheckpointManifest = field(repr=False, compare=False)
    _manager_owner: V2HybridCheckpointManager = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        manifest = self._checkpoint_manifest_owner
        manager = self._manager_owner
        contract = (
            manifest.checkpoint_evidence.get(
                "authenticated_profiled_supervised_publication"
            )
            if type(manifest) is CheckpointManifest
            else None
        )
        try:
            verification = manager.verify_manifest_artifact(manifest)
        except Exception as exc:
            raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
                "PROFILED_SUPERVISED_EXISTING_PUBLICATION_REVALIDATION_FAILED"
            ) from exc
        if (
            self._construction_token is not _PUBLICATION_TOKEN
            or self.schema_version
            != AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION
            or self.status != AUTHENTICATED_PROFILED_EXISTING_PUBLICATION_V1_STATUS
            or not _recovery_contract_valid(manifest=manifest, contract=contract)
            or not all(
                _valid_sha256(value)
                for value in (
                    self.manifest_id,
                    self.completion_event_sha256,
                    self.external_authorization_envelope_sha256,
                    self.witness_public_key_sha256,
                    self.publication_idempotency_key,
                    self.candidate_checkpoint_weight_sha256,
                    self.candidate_checkpoint_evidence_digest,
                    self.candidate_model_parameter_fingerprint,
                )
            )
            or any(
                type(value) is not str or not value or Path(value).name != value
                for value in (
                    self.base_checkpoint_id,
                    self.candidate_checkpoint_id,
                )
            )
            or type(contract) is not dict
            or contract.get("manifest_id") != self.manifest_id
            or contract.get("completion_event_sha256")
            != self.completion_event_sha256
            or contract.get("external_authorization_envelope_sha256")
            != self.external_authorization_envelope_sha256
            or contract.get("witness_id") != self.witness_id
            or contract.get("witness_namespace") != self.witness_namespace
            or contract.get("witness_public_key_sha256")
            != self.witness_public_key_sha256
            or contract.get("witness_sequence") != self.witness_sequence
            or contract.get("publication_idempotency_key")
            != self.publication_idempotency_key
            or contract.get("base_checkpoint_id") != self.base_checkpoint_id
            or manifest.parent_checkpoint_id != self.base_checkpoint_id
            or manifest.checkpoint_id != self.candidate_checkpoint_id
            or manifest.weight_file_sha256
            != self.candidate_checkpoint_weight_sha256
            or manifest.checkpoint_evidence_digest
            != self.candidate_checkpoint_evidence_digest
            or manifest.checkpoint_generation != self.candidate_checkpoint_generation
            or manifest.model_parameter_fingerprint
            != self.candidate_model_parameter_fingerprint
            or verification.get("checkpoint_artifact_verified") is not True
            or self.already_published is not True
            or self.checkpoint_artifact_verified is not True
            or self.checkpoint_write_authorized is not False
            or self.serving_authorized is not False
            or self.trading_authorized is not False
        ):
            _fail("PROFILED_SUPERVISED_EXISTING_PUBLICATION_RESULT_INVALID")


def find_authenticated_profiled_supervised_publication_for_completion_v1(
    *,
    candidate_checkpoint_manager: V2HybridCheckpointManager,
    manifest_id: str,
    completion_event_sha256: str,
    external_authorization_envelope_sha256: str,
    witness_id: str,
    witness_namespace: str,
    witness_public_key_sha256: str,
    witness_sequence: int,
) -> AuthenticatedProfiledExistingPublicationV1 | None:
    """Recover one verified publication without re-running its optimizer."""

    if (
        type(candidate_checkpoint_manager) is not V2HybridCheckpointManager
        or not all(
            _valid_sha256(value)
            for value in (
                manifest_id,
                completion_event_sha256,
                external_authorization_envelope_sha256,
                witness_public_key_sha256,
            )
        )
        or type(witness_id) is not str
        or not witness_id
        or not witness_id.isascii()
        or type(witness_namespace) is not str
        or not witness_namespace
        or not witness_namespace.isascii()
        or type(witness_sequence) is not int
        or witness_sequence <= 0
    ):
        _fail("PROFILED_SUPERVISED_EXISTING_PUBLICATION_LOOKUP_INVALID")
    try:
        manifests = candidate_checkpoint_manager.manifests(
            allowed_lineage_kinds=frozenset(
                {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
            ),
            require_weight_blob=True,
        )
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_EXISTING_PUBLICATION_SCAN_FAILED"
        ) from exc
    exact: list[tuple[CheckpointManifest, dict[str, Any]]] = []
    same_witness_history: list[tuple[int, int]] = []
    for manifest in manifests:
        contract = manifest.checkpoint_evidence.get(
            "authenticated_profiled_supervised_publication"
        )
        if not _recovery_contract_valid(manifest=manifest, contract=contract):
            _fail("PROFILED_SUPERVISED_EXISTING_PUBLICATION_EVIDENCE_INVALID")
        typed_contract = cast(dict[str, Any], contract)
        if (
            typed_contract.get("witness_id") == witness_id
            and typed_contract.get("witness_namespace") == witness_namespace
        ):
            same_witness_history.append(
                (
                    manifest.checkpoint_generation,
                    cast(int, typed_contract["witness_sequence"]),
                )
            )
        identity_overlap = bool(
            typed_contract.get("completion_event_sha256")
            == completion_event_sha256
            or typed_contract.get("manifest_id") == manifest_id
            or typed_contract.get("external_authorization_envelope_sha256")
            == external_authorization_envelope_sha256
        )
        is_exact = bool(
            typed_contract.get("manifest_id") == manifest_id
            and typed_contract.get("completion_event_sha256")
            == completion_event_sha256
            and typed_contract.get("external_authorization_envelope_sha256")
            == external_authorization_envelope_sha256
            and typed_contract.get("witness_id") == witness_id
            and typed_contract.get("witness_namespace") == witness_namespace
            and typed_contract.get("witness_public_key_sha256")
            == witness_public_key_sha256
            and typed_contract.get("witness_sequence") == witness_sequence
        )
        if identity_overlap and not is_exact:
            _fail("PROFILED_SUPERVISED_EXISTING_PUBLICATION_IDENTITY_CONFLICT")
        if is_exact:
            verification = candidate_checkpoint_manager.verify_manifest_artifact(
                manifest
            )
            if verification.get("checkpoint_artifact_verified") is not True:
                _fail("PROFILED_SUPERVISED_EXISTING_PUBLICATION_ARTIFACT_INVALID")
            exact.append((manifest, typed_contract))
    ordered_witness_history = tuple(sorted(same_witness_history))
    if any(
        current_sequence <= previous_sequence
        for (_, previous_sequence), (_, current_sequence) in zip(
            ordered_witness_history,
            ordered_witness_history[1:],
            strict=False,
        )
    ):
        _fail("PROFILED_SUPERVISED_PUBLICATION_WITNESS_HISTORY_NON_MONOTONIC")
    if len(exact) > 1:
        _fail("PROFILED_SUPERVISED_EXISTING_PUBLICATION_AMBIGUOUS")
    if not exact:
        if any(
            published_sequence >= witness_sequence
            for _, published_sequence in ordered_witness_history
        ):
            _fail("PROFILED_SUPERVISED_PUBLICATION_WITNESS_SEQUENCE_NOT_SUCCESSOR")
        return None
    manifest, contract = exact[0]
    return AuthenticatedProfiledExistingPublicationV1(
        schema_version=(
            AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION
        ),
        status=AUTHENTICATED_PROFILED_EXISTING_PUBLICATION_V1_STATUS,
        manifest_id=manifest_id,
        completion_event_sha256=completion_event_sha256,
        external_authorization_envelope_sha256=(
            external_authorization_envelope_sha256
        ),
        witness_id=witness_id,
        witness_namespace=witness_namespace,
        witness_public_key_sha256=witness_public_key_sha256,
        witness_sequence=witness_sequence,
        publication_idempotency_key=contract["publication_idempotency_key"],
        base_checkpoint_id=contract["base_checkpoint_id"],
        candidate_checkpoint_id=manifest.checkpoint_id,
        candidate_checkpoint_weight_sha256=manifest.weight_file_sha256,
        candidate_checkpoint_evidence_digest=manifest.checkpoint_evidence_digest,
        candidate_checkpoint_generation=manifest.checkpoint_generation,
        candidate_model_parameter_fingerprint=(
            manifest.model_parameter_fingerprint
        ),
        already_published=True,
        checkpoint_artifact_verified=True,
        checkpoint_write_authorized=False,
        serving_authorized=False,
        trading_authorized=False,
        _checkpoint_manifest_owner=manifest,
        _manager_owner=candidate_checkpoint_manager,
        _construction_token=_PUBLICATION_TOKEN,
    )


def _publication_result_material(values: dict[str, Any]) -> dict[str, Any]:
    names = (
        "schema_version",
        "status",
        "publication_idempotency_key",
        "publication_completed_at",
        "lineage_bound_execution_sha256",
        "execution_idempotency_key",
        "base_checkpoint_lineage_binding_sha256",
        "base_checkpoint_id",
        "base_checkpoint_weight_sha256",
        "base_checkpoint_evidence_digest",
        "base_checkpoint_generation",
        "base_model_parameter_fingerprint",
        "candidate_checkpoint_id",
        "candidate_checkpoint_weight_sha256",
        "candidate_checkpoint_weight_size_bytes",
        "candidate_checkpoint_evidence_digest",
        "candidate_checkpoint_generation",
        "candidate_checkpoint_semantic_digest",
        "candidate_checkpoint_causal_record_digest",
        "candidate_model_parameter_fingerprint",
        "training_partition_digest",
        "lineage_kind",
        "ledger_disposition",
        "base_checkpoint_lineage_verified",
        "execution_release_revalidated",
        "stable_execution_evidence_bound",
        "checkpoint_write_authorized",
        "checkpoint_write_completed",
        "candidate_checkpoint_artifact_verified",
        "durable_publication_receipt_written",
        "durable_execution_receipt_written",
        "non_serving_candidate_only",
        "idempotent_publication_key_bound",
        *_DOWNSTREAM_AUTHORITY_FALSE,
    )
    return {name: values[name] for name in names}


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledSupervisedCheckpointPublicationV1:
    schema_version: str
    status: str
    publication_idempotency_key: str
    publication_completed_at: str
    lineage_bound_execution_sha256: str
    execution_idempotency_key: str
    base_checkpoint_lineage_binding_sha256: str
    base_checkpoint_id: str
    base_checkpoint_weight_sha256: str
    base_checkpoint_evidence_digest: str
    base_checkpoint_generation: int
    base_model_parameter_fingerprint: str
    candidate_checkpoint_id: str
    candidate_checkpoint_weight_sha256: str
    candidate_checkpoint_weight_size_bytes: int
    candidate_checkpoint_evidence_digest: str
    candidate_checkpoint_generation: int
    candidate_checkpoint_semantic_digest: str
    candidate_checkpoint_causal_record_digest: str
    candidate_model_parameter_fingerprint: str
    training_partition_digest: str
    lineage_kind: str
    ledger_disposition: str
    publication_receipt_sha256: str
    base_checkpoint_lineage_verified: bool
    execution_release_revalidated: bool
    stable_execution_evidence_bound: bool
    checkpoint_write_authorized: bool
    checkpoint_write_completed: bool
    candidate_checkpoint_artifact_verified: bool
    durable_publication_receipt_written: bool
    durable_execution_receipt_written: bool
    non_serving_candidate_only: bool
    idempotent_publication_key_bound: bool
    prediction_authorized: bool
    serving_authorized: bool
    serving_activation_authorized: bool
    serving_promotion_authorized: bool
    ppo_training_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    exchange_access_authorized: bool
    deployment_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _checkpoint_manifest_owner: CheckpointManifest = field(repr=False, compare=False)
    _bound_execution_owner: AuthenticatedProfiledLineageBoundOptimizerExecutionV1 = (
        field(repr=False, compare=False)
    )
    _candidate_checkpoint_manager_owner: V2HybridCheckpointManager = field(
        repr=False,
        compare=False,
    )
    _seal_mac: bytes = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        material = _publication_result_material(
            {name: getattr(self, name) for name in _publication_result_material_names()}
        )
        manifest = self._checkpoint_manifest_owner
        bound_execution = self._bound_execution_owner
        manager = self._candidate_checkpoint_manager_owner
        try:
            bound_execution.__post_init__()
            _manager_roots(
                bound_execution=bound_execution,
                candidate_checkpoint_manager=manager,
            )
            revalidate_authenticated_profiled_base_checkpoint_lineage_v1(
                lineage=bound_execution.base_lineage,
                base_model=bound_execution._base_model_owner,
                base_checkpoint_manager=(
                    bound_execution._base_checkpoint_manager_owner
                ),
            )
            revalidate_authenticated_profiled_supervised_optimizer_publication_boundary_v1(  # noqa: E501
                execution=bound_execution.execution,
                base_model=bound_execution._base_model_owner,
                candidate_model=bound_execution._candidate_model_owner,
            )
            verification = manager.verify_manifest_artifact(manifest)
            manifests = manager.manifests(
                input_dim=bound_execution.execution.model_input_dim,
                model_id=bound_execution.execution.model_id,
                allowed_lineage_kinds=frozenset(
                    {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
                ),
                require_weight_blob=True,
            )
        except Exception as exc:
            raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
                "PROFILED_SUPERVISED_PUBLICATION_RESULT_REVALIDATION_FAILED"
            ) from exc
        expected_contract = _publication_contract(
            bound_execution=bound_execution,
            publication_idempotency_key=self.publication_idempotency_key,
            training_partition_digest=self.training_partition_digest,
        )
        exact_manifests = tuple(
            item
            for item in manifests
            if item.checkpoint_id == self.candidate_checkpoint_id
        )
        required_verification = (
            "checkpoint_artifact_verified",
            "latest_checkpoint_loadable",
            "verification_is_non_mutating",
            "weight_file_sha256_verified",
            "model_parameter_fingerprint_verified",
            "checkpoint_evidence_verified",
            "checkpoint_identity_verified",
        )
        if (
            self._construction_token is not _PUBLICATION_TOKEN
            or self.schema_version
            != AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION
            or self.status
            != AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_STATUS
            or not all(
                _valid_sha256(value)
                for value in (
                    self.publication_idempotency_key,
                    self.lineage_bound_execution_sha256,
                    self.execution_idempotency_key,
                    self.base_checkpoint_lineage_binding_sha256,
                    self.base_checkpoint_weight_sha256,
                    self.base_checkpoint_evidence_digest,
                    self.base_model_parameter_fingerprint,
                    self.candidate_checkpoint_weight_sha256,
                    self.candidate_checkpoint_evidence_digest,
                    self.candidate_checkpoint_semantic_digest,
                    self.candidate_checkpoint_causal_record_digest,
                    self.candidate_model_parameter_fingerprint,
                    self.training_partition_digest,
                    self.publication_receipt_sha256,
                )
            )
            or self.publication_receipt_sha256 != stable_sha256(material)
            or self.base_checkpoint_generation <= 0
            or self.candidate_checkpoint_generation <= self.base_checkpoint_generation
            or self.candidate_checkpoint_weight_size_bytes <= 0
            or self.lineage_kind
            != AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE
            or self.ledger_disposition
            != AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION
            or type(manifest) is not CheckpointManifest
            or type(bound_execution)
            is not AuthenticatedProfiledLineageBoundOptimizerExecutionV1
            or type(manager) is not V2HybridCheckpointManager
            or bound_execution.lineage_bound_execution_sha256
            != self.lineage_bound_execution_sha256
            or bound_execution.execution.execution_idempotency_key
            != self.execution_idempotency_key
            or bound_execution.base_checkpoint_lineage_binding_sha256
            != self.base_checkpoint_lineage_binding_sha256
            or manifest.checkpoint_id != self.candidate_checkpoint_id
            or manifest.weight_file_sha256 != self.candidate_checkpoint_weight_sha256
            or manifest.weight_file_size_bytes
            != self.candidate_checkpoint_weight_size_bytes
            or manifest.checkpoint_evidence_digest
            != self.candidate_checkpoint_evidence_digest
            or _checkpoint_evidence_sha256(manifest.checkpoint_evidence)
            != self.candidate_checkpoint_evidence_digest
            or manifest.checkpoint_generation != self.candidate_checkpoint_generation
            or manifest.checkpoint_semantic_digest
            != self.candidate_checkpoint_semantic_digest
            or manifest.checkpoint_causal_record_digest
            != self.candidate_checkpoint_causal_record_digest
            or manifest.model_parameter_fingerprint
            != self.candidate_model_parameter_fingerprint
            or manifest.parent_checkpoint_id != self.base_checkpoint_id
            or manifest.parent_policy_fingerprint
            != self.base_model_parameter_fingerprint
            or manifest.lineage_kind != self.lineage_kind
            or manifest.training_partition_digest != self.training_partition_digest
            or manifest.consumed_ppo_update_keys
            or manifest.checkpoint_evidence.get(
                "authenticated_profiled_supervised_publication"
            )
            != expected_contract
            or manager._manifest_scan_errors
            or len(exact_manifests) != 1
            or exact_manifests[0] != manifest
            or any(
                verification.get(name) is not True
                for name in required_verification
            )
            or verification.get("model_state_restored") is not False
            or any(
                value is not True
                for value in (
                    self.base_checkpoint_lineage_verified,
                    self.execution_release_revalidated,
                    self.stable_execution_evidence_bound,
                    self.checkpoint_write_completed,
                    self.candidate_checkpoint_artifact_verified,
                    self.durable_publication_receipt_written,
                    self.non_serving_candidate_only,
                    self.idempotent_publication_key_bound,
                )
            )
            or self.checkpoint_write_authorized is not False
            or self.durable_execution_receipt_written is not False
            or any(
                getattr(self, name) is not expected
                for name, expected in _DOWNSTREAM_AUTHORITY_FALSE.items()
            )
            or type(self._seal_mac) is not bytes
            or not hmac.compare_digest(
                self._seal_mac,
                _publication_seal(
                    material,
                    owner_ids=(id(bound_execution), id(manager), id(manifest)),
                ),
            )
        ):
            _fail("PROFILED_SUPERVISED_PUBLICATION_RESULT_INVALID")

    @property
    def checkpoint_manifest(self) -> CheckpointManifest:
        self.__post_init__()
        return deepcopy(self._checkpoint_manifest_owner)

    def __reduce_ex__(self, _protocol: int) -> NoReturn:
        _fail("PROFILED_SUPERVISED_PUBLICATION_RESULT_COPY_OR_PICKLE_FORBIDDEN")


def _publication_result_material_names() -> tuple[str, ...]:
    return (
        "schema_version",
        "status",
        "publication_idempotency_key",
        "publication_completed_at",
        "lineage_bound_execution_sha256",
        "execution_idempotency_key",
        "base_checkpoint_lineage_binding_sha256",
        "base_checkpoint_id",
        "base_checkpoint_weight_sha256",
        "base_checkpoint_evidence_digest",
        "base_checkpoint_generation",
        "base_model_parameter_fingerprint",
        "candidate_checkpoint_id",
        "candidate_checkpoint_weight_sha256",
        "candidate_checkpoint_weight_size_bytes",
        "candidate_checkpoint_evidence_digest",
        "candidate_checkpoint_generation",
        "candidate_checkpoint_semantic_digest",
        "candidate_checkpoint_causal_record_digest",
        "candidate_model_parameter_fingerprint",
        "training_partition_digest",
        "lineage_kind",
        "ledger_disposition",
        "base_checkpoint_lineage_verified",
        "execution_release_revalidated",
        "stable_execution_evidence_bound",
        "checkpoint_write_authorized",
        "checkpoint_write_completed",
        "candidate_checkpoint_artifact_verified",
        "durable_publication_receipt_written",
        "durable_execution_receipt_written",
        "non_serving_candidate_only",
        "idempotent_publication_key_bound",
        *_DOWNSTREAM_AUTHORITY_FALSE,
    )


def publish_authenticated_profiled_supervised_checkpoint_v1(
    *,
    bound_execution: AuthenticatedProfiledLineageBoundOptimizerExecutionV1,
    candidate_checkpoint_manager: V2HybridCheckpointManager,
    lifecycle_lease: CheckpointLifecycleLeaseReceipt,
) -> AuthenticatedProfiledSupervisedCheckpointPublicationV1:
    """Write and verify one distinct non-serving profiled checkpoint lineage."""

    bound_execution.__post_init__()
    _manager_roots(
        bound_execution=bound_execution,
        candidate_checkpoint_manager=candidate_checkpoint_manager,
    )
    execution = bound_execution.execution
    base_lineage = bound_execution.base_lineage
    base_manager = bound_execution._base_checkpoint_manager_owner
    base_model = bound_execution._base_model_owner
    candidate_model = bound_execution._candidate_model_owner
    try:
        require_active_checkpoint_lifecycle_lease(
            lifecycle_lease,
            model_dir=base_manager.model_dir,
            owner_role="AUTHENTICATED_PROFILED_TRAINER",
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_PUBLICATION_LIFECYCLE_LEASE_INVALID"
        ) from exc
    try:
        base_manifest = revalidate_authenticated_profiled_base_checkpoint_lineage_v1(
            lineage=base_lineage,
            base_model=base_model,
            base_checkpoint_manager=base_manager,
        )
        revalidate_authenticated_profiled_supervised_optimizer_publication_boundary_v1(
            execution=execution,
            base_model=base_model,
            candidate_model=candidate_model,
        )
    except (
        AuthenticatedProfiledBaseCheckpointLineageV1Error,
        AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
    ) as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_PUBLICATION_PREWRITE_REVALIDATION_FAILED"
        ) from exc
    publication_idempotency_key = _publication_idempotency_key(bound_execution)
    training_partition_digest = _partition_digest(execution)
    publication_contract = _publication_contract(
        bound_execution=bound_execution,
        publication_idempotency_key=publication_idempotency_key,
        training_partition_digest=training_partition_digest,
    )
    _preflight_publication_conflicts(
        candidate_checkpoint_manager=candidate_checkpoint_manager,
        publication_contract=publication_contract,
    )
    checkpoint_evidence = {
        "checkpoint_role": AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
        "ledger_disposition": AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION,
        "authenticated_profiled_supervised_publication": publication_contract,
    }
    base_fingerprint = model_parameter_fingerprint(base_model)
    candidate_fingerprint = model_parameter_fingerprint(candidate_model)
    try:
        candidate_manifest = candidate_checkpoint_manager.write_checkpoint(
            model=candidate_model,
            input_dim=execution.model_input_dim,
            device=candidate_model.device,
            cuda_active=candidate_model.cuda_active,
            lineage_kind=AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
            parent_checkpoint_id=base_manifest.checkpoint_id,
            parent_policy_fingerprint=execution.base_model_parameter_fingerprint,
            consumed_ppo_update_keys=(),
            training_partition_digest=training_partition_digest,
            checkpoint_evidence=checkpoint_evidence,
        )
        verification = candidate_checkpoint_manager.verify_manifest_artifact(
            candidate_manifest
        )
        post_base_manifest = (
            revalidate_authenticated_profiled_base_checkpoint_lineage_v1(
                lineage=base_lineage,
                base_model=base_model,
                base_checkpoint_manager=base_manager,
            )
        )
        revalidate_authenticated_profiled_supervised_optimizer_publication_boundary_v1(
            execution=execution,
            base_model=base_model,
            candidate_model=candidate_model,
        )
        lineage_manifests = candidate_checkpoint_manager.manifests(
            input_dim=execution.model_input_dim,
            model_id=execution.model_id,
            allowed_lineage_kinds=frozenset(
                {AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE}
            ),
            require_weight_blob=True,
        )
    except (
        AuthenticatedProfiledBaseCheckpointLineageV1Error,
        AuthenticatedProfiledSupervisedOptimizerExecutionV1Error,
    ) as exc:
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            "PROFILED_SUPERVISED_PUBLICATION_POSTWRITE_REVALIDATION_FAILED"
        ) from exc
    except Exception as exc:
        if (
            model_parameter_fingerprint(base_model) != base_fingerprint
            or model_parameter_fingerprint(candidate_model) != candidate_fingerprint
        ):
            raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
                "PROFILED_SUPERVISED_PUBLICATION_MODEL_MUTATED_DURING_FAILURE"
            ) from exc
        raise AuthenticatedProfiledSupervisedCheckpointPublicationV1Error(
            f"PROFILED_SUPERVISED_PUBLICATION_CHECKPOINT_WRITE_FAILED:{type(exc).__name__}"
        ) from exc
    required_true = (
        "checkpoint_artifact_verified",
        "latest_checkpoint_loadable",
        "verification_is_non_mutating",
        "weight_file_sha256_verified",
        "model_parameter_fingerprint_verified",
        "checkpoint_evidence_verified",
        "checkpoint_identity_verified",
    )
    idempotency_matches = tuple(
        manifest
        for manifest in lineage_manifests
        if (
            type(
                manifest.checkpoint_evidence.get(
                    "authenticated_profiled_supervised_publication"
                )
            )
            is dict
            and manifest.checkpoint_evidence[
                "authenticated_profiled_supervised_publication"
            ].get("publication_idempotency_key")
            == publication_idempotency_key
        )
    )
    if (
        any(verification.get(name) is not True for name in required_true)
        or verification.get("model_state_restored") is not False
        or post_base_manifest != base_manifest
        or len(idempotency_matches) != 1
        or idempotency_matches[0] != candidate_manifest
        or candidate_manifest.lineage_kind
        != AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE
        or candidate_manifest.parent_checkpoint_id != base_manifest.checkpoint_id
        or candidate_manifest.parent_policy_fingerprint
        != execution.base_model_parameter_fingerprint
        or candidate_manifest.model_parameter_fingerprint
        != execution.candidate_model_parameter_fingerprint
        or candidate_manifest.consumed_ppo_update_keys
        or candidate_manifest.training_partition_digest != training_partition_digest
        or candidate_manifest.checkpoint_evidence.get(
            "authenticated_profiled_supervised_publication"
        )
        != publication_contract
        or model_parameter_fingerprint(base_model) != base_fingerprint
        or model_parameter_fingerprint(candidate_model) != candidate_fingerprint
    ):
        _fail("PROFILED_SUPERVISED_PUBLICATION_POSTWRITE_VERIFICATION_FAILED")
    values: dict[str, Any] = {
        "schema_version": (
            AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_SCHEMA_VERSION
        ),
        "status": AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_STATUS,
        "publication_idempotency_key": publication_idempotency_key,
        "publication_completed_at": candidate_manifest.generated_utc,
        "lineage_bound_execution_sha256": (
            bound_execution.lineage_bound_execution_sha256
        ),
        "execution_idempotency_key": execution.execution_idempotency_key,
        "base_checkpoint_lineage_binding_sha256": (
            base_lineage.base_checkpoint_lineage_binding_sha256
        ),
        "base_checkpoint_id": base_manifest.checkpoint_id,
        "base_checkpoint_weight_sha256": base_lineage.checkpoint_weight_sha256,
        "base_checkpoint_evidence_digest": base_lineage.checkpoint_evidence_digest,
        "base_checkpoint_generation": base_lineage.checkpoint_generation,
        "base_model_parameter_fingerprint": execution.base_model_parameter_fingerprint,
        "candidate_checkpoint_id": candidate_manifest.checkpoint_id,
        "candidate_checkpoint_weight_sha256": candidate_manifest.weight_file_sha256,
        "candidate_checkpoint_weight_size_bytes": (
            candidate_manifest.weight_file_size_bytes
        ),
        "candidate_checkpoint_evidence_digest": (
            candidate_manifest.checkpoint_evidence_digest
        ),
        "candidate_checkpoint_generation": candidate_manifest.checkpoint_generation,
        "candidate_checkpoint_semantic_digest": (
            candidate_manifest.checkpoint_semantic_digest
        ),
        "candidate_checkpoint_causal_record_digest": (
            candidate_manifest.checkpoint_causal_record_digest
        ),
        "candidate_model_parameter_fingerprint": (
            execution.candidate_model_parameter_fingerprint
        ),
        "training_partition_digest": training_partition_digest,
        "lineage_kind": AUTHENTICATED_PROFILED_SUPERVISED_CANDIDATE_LINEAGE,
        "ledger_disposition": AUTHENTICATED_PROFILED_SUPERVISED_LEDGER_DISPOSITION,
        "publication_receipt_sha256": "0" * 64,
        "base_checkpoint_lineage_verified": True,
        "execution_release_revalidated": True,
        "stable_execution_evidence_bound": True,
        "checkpoint_write_authorized": False,
        "checkpoint_write_completed": True,
        "candidate_checkpoint_artifact_verified": True,
        "durable_publication_receipt_written": True,
        "durable_execution_receipt_written": False,
        "non_serving_candidate_only": True,
        "idempotent_publication_key_bound": True,
        **_DOWNSTREAM_AUTHORITY_FALSE,
        "_checkpoint_manifest_owner": candidate_manifest,
        "_bound_execution_owner": bound_execution,
        "_candidate_checkpoint_manager_owner": candidate_checkpoint_manager,
        "_seal_mac": b"placeholder",
        "_construction_token": _PUBLICATION_TOKEN,
    }
    values["publication_receipt_sha256"] = stable_sha256(
        _publication_result_material(values)
    )
    values["_seal_mac"] = _publication_seal(
        _publication_result_material(values),
        owner_ids=(id(bound_execution), id(candidate_checkpoint_manager), id(candidate_manifest)),
    )
    return AuthenticatedProfiledSupervisedCheckpointPublicationV1(**values)


__all__ = (
    "AUTHENTICATED_PROFILED_EXISTING_PUBLICATION_V1_STATUS",
    "AUTHENTICATED_PROFILED_LINEAGE_BOUND_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_SUPERVISED_CHECKPOINT_PUBLICATION_V1_STATUS",
    "AuthenticatedProfiledExistingPublicationV1",
    "AuthenticatedProfiledLineageBoundOptimizerExecutionV1",
    "AuthenticatedProfiledSupervisedCheckpointPublicationV1",
    "AuthenticatedProfiledSupervisedCheckpointPublicationV1Error",
    "execute_lineage_bound_authenticated_profiled_supervised_optimizer_v1",
    "find_authenticated_profiled_supervised_publication_for_completion_v1",
    "publish_authenticated_profiled_supervised_checkpoint_v1",
)
