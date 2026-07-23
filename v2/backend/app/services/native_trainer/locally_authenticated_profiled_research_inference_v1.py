"""Authenticated, quarantined inference for local profiled research candidates.

This boundary does not create a canonical prediction or PAPER signal. It
reopens one exact local-only checkpoint, verifies that the checkpoint was
produced by the clean source closure currently executing, freshly recomputes
one profiled feature record from its immutable evidence, and returns raw logits
with every downstream authority false.
"""

from __future__ import annotations

import hmac
import json
import math
import re
import threading
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.authenticated_ohlcv_profile_transform_v1 import (
    AuthenticatedOhlcvProfileTransformV1Result,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_resident_runtime_credentials_v1 import (  # noqa: E501
    AuthenticatedProfiledResidentLocalRoleCredentialsV1,
    AuthenticatedProfiledResidentRuntimeCredentialsV1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_supervised_optimizer_execution_v1 import (  # noqa: E501
    verify_current_profiled_optimizer_release_source_closure_v1,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (
    CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
    deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint_lifecycle import (  # noqa: E501
    LOCAL_PROFILED_RESEARCH_TRAINER_LEASE_OWNER_ROLE,
    checkpoint_lifecycle_lease,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    ACTION_LABELS,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.locally_authenticated_profiled_research_service_v1 import (  # noqa: E501
    LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE,
    LocallyAuthenticatedProfiledResearchServiceConfigV1,
    _verify_local_candidate_manifest,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (  # noqa: E501
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
    PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,
    validate_profiled_model_feature_snapshot_record_v1,
)
from v2.backend.app.services.native_trainer.source_provenance_ledger_v4 import (
    TrainerSourceProvenanceLedgerEntryV4,
    TrainerSourceProvenanceLedgerV4,
)

LOCAL_PROFILED_RESEARCH_INFERENCE_V1_SCHEMA_VERSION: Final = (
    "locally_authenticated_profiled_research_inference_v1"
)
LOCAL_PROFILED_RESEARCH_RAW_INFERENCE_V1_CLASSIFICATION: Final = (
    "LOCAL_PROFILED_RESEARCH_RAW_UNWIRED_HYPOTHESIS_V1"
)
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$", re.ASCII)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$", re.ASCII)
_HANDLE_FACTORY_TOKEN = object()
_RESULT_FACTORY_TOKEN = object()
_FALSE_AUTHORITY_FIELDS: Final = (
    "consumer_eligible",
    "trainer_admission_authorized",
    "prediction_authorized",
    "serving_authorized",
    "serving_activation_authorized",
    "serving_promotion_authorized",
    "paper_trading_authorized",
    "live_execution_authorized",
    "exchange_access_authorized",
    "deployment_authorized",
    "order_submission_authorized",
    "execution_authorized",
    "runtime_wired",
)
_HANDLE_SEALED_PUBLIC_FIELDS: Final = (
    "checkpoint_id",
    "checkpoint_generation",
    "checkpoint_generated_at",
    "checkpoint_weight_sha256",
    "checkpoint_evidence_digest",
    "checkpoint_semantic_digest",
    "checkpoint_causal_record_digest",
    "model_id",
    "input_dim",
    "model_parameter_fingerprint_sha256",
    "candidate_contract_sha256",
    "candidate_contract_json",
    "candidate_authorization_receipt_sha256",
    "candidate_code_release_sha",
    "candidate_manifest_observation_time",
    "current_release_verified",
    "current_source_closure_verified",
    "local_research_non_promotable",
    "external_witness_verified",
    *_FALSE_AUTHORITY_FIELDS,
)
_PROCESS_SOURCE_ORDER_LOCK = threading.Lock()
_PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR: dict[tuple[str, str, str, str], datetime] = {}


class LocallyAuthenticatedProfiledResearchInferenceV1Error(RuntimeError):
    """Stable fail-closed error without model, credential, or payload data."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise LocallyAuthenticatedProfiledResearchInferenceV1Error(*reasons) from None


def _clock(value: object, *, reason: str) -> tuple[str, datetime]:
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
    return canonical, normalized


def _utc_iso() -> str:
    return (
        datetime.now(UTC)
        .isoformat(timespec="microseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (OverflowError, TypeError, UnicodeError, ValueError) as exc:
        raise LocallyAuthenticatedProfiledResearchInferenceV1Error(
            "LOCAL_PROFILED_INFERENCE_CANONICAL_JSON_INVALID"
        ) from exc


def _json_object_material(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        field_name: list(field_value) if type(field_value) is tuple else field_value
        for field_name, field_value in value.items()
    }


def _handle_seal_material(
    *,
    public_values: Mapping[str, Any],
    model_owner: V2HybridPolicyModel,
) -> dict[str, Any]:
    if set(public_values) != set(_HANDLE_SEALED_PUBLIC_FIELDS):
        _fail("LOCAL_PROFILED_INFERENCE_HANDLE_SEAL_FIELDS_INVALID")
    return {
        "domain": "v2/native-trainer/local-profiled-research-inference-handle/v1",
        "public_fields": {name: public_values[name] for name in _HANDLE_SEALED_PUBLIC_FIELDS},
        "process_model_owner_id": id(model_owner),
    }


@dataclass(frozen=True, slots=True)
class LocallyAuthenticatedProfiledResearchRawInferenceV1:
    schema_version: str
    classification: str
    checkpoint_id: str
    checkpoint_generation: int
    checkpoint_generated_at: str
    checkpoint_weight_sha256: str
    model_id: str
    model_parameter_fingerprint: str
    candidate_contract_sha256: str
    candidate_authorization_receipt_sha256: str
    candidate_code_release_sha: str
    candidate_manifest_observation_time: str
    symbol: str
    timeframe: str
    durable_snapshot_id: str
    record_sha256: str
    frozen_envelope_sha256: str
    source_lineage_sha256: str
    lineage_binding_sha256: str
    feature_snapshot_id: str
    logical_model_vector_sha256: str
    logical_projection_sha256: str
    feature_cutoff: str
    record_generated_at: str
    source_decision_time: str
    hypothesis_generated_at: str
    tensor_id: str
    total_feature_count: int
    available_feature_count: int
    data_coverage_percent: float
    temporal_rejection_reasons: tuple[str, ...]
    raw_action_logits: tuple[float, ...]
    raw_action_logits_sha256: str
    selected_action_index: int
    selected_action: str
    model_device: str
    cuda_active: bool
    model_tensors_device_verified: bool
    confidence_calibrated: None
    profitability_probability: None
    hypothesis_binding_sha256: str
    local_research_non_promotable: bool = True
    external_witness_verified: bool = False
    consumer_eligible: bool = False
    trainer_admission_authorized: bool = False
    prediction_authorized: bool = False
    serving_authorized: bool = False
    serving_activation_authorized: bool = False
    serving_promotion_authorized: bool = False
    paper_trading_authorized: bool = False
    live_execution_authorized: bool = False
    exchange_access_authorized: bool = False
    deployment_authorized: bool = False
    order_submission_authorized: bool = False
    execution_authorized: bool = False
    runtime_wired: bool = False
    _factory_token: InitVar[object | None] = None

    def __post_init__(self, _factory_token: object | None) -> None:
        if _factory_token is not _RESULT_FACTORY_TOKEN:
            _fail("LOCAL_PROFILED_RAW_INFERENCE_FACTORY_REQUIRED")
        hashes = (
            self.checkpoint_weight_sha256,
            self.model_parameter_fingerprint,
            self.candidate_contract_sha256,
            self.candidate_authorization_receipt_sha256,
            self.record_sha256,
            self.frozen_envelope_sha256,
            self.source_lineage_sha256,
            self.lineage_binding_sha256,
            self.logical_model_vector_sha256,
            self.logical_projection_sha256,
            self.raw_action_logits_sha256,
            self.hypothesis_binding_sha256,
        )
        clocks = tuple(
            _clock(value, reason="LOCAL_PROFILED_RAW_INFERENCE_CLOCK_INVALID")[1]
            for value in (
                self.candidate_manifest_observation_time,
                self.checkpoint_generated_at,
                self.feature_cutoff,
                self.record_generated_at,
                self.source_decision_time,
                self.hypothesis_generated_at,
            )
        )
        expected_coverage = (
            100.0 * self.available_feature_count / self.total_feature_count
            if self.total_feature_count > 0
            else -1.0
        )
        if (
            self.schema_version != LOCAL_PROFILED_RESEARCH_INFERENCE_V1_SCHEMA_VERSION
            or self.classification != LOCAL_PROFILED_RESEARCH_RAW_INFERENCE_V1_CLASSIFICATION
            or _IDENTIFIER_RE.fullmatch(self.checkpoint_id) is None
            or type(self.checkpoint_generation) is not int
            or self.checkpoint_generation <= 0
            or any(_SHA256_RE.fullmatch(value) is None for value in hashes)
            or _SHA1_RE.fullmatch(self.candidate_code_release_sha) is None
            or not self.symbol
            or self.symbol != self.symbol.upper()
            or not self.timeframe
            or not self.durable_snapshot_id
            or not self.feature_snapshot_id
            or not self.tensor_id
            or not (clocks[0] < clocks[1] < clocks[2] <= clocks[3] <= clocks[4] <= clocks[5])
            or self.total_feature_count != LOGICAL_MODEL_FEATURE_COUNT
            or self.available_feature_count != 35
            or not math.isclose(
                self.data_coverage_percent,
                expected_coverage,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or self.temporal_rejection_reasons
            != (PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,)
            or len(self.raw_action_logits) != len(ACTION_LABELS)
            or any(not math.isfinite(value) for value in self.raw_action_logits)
            or self.raw_action_logits_sha256 != stable_sha256(list(self.raw_action_logits))
            or self.selected_action_index
            != max(
                range(len(self.raw_action_logits)),
                key=self.raw_action_logits.__getitem__,
            )
            or self.selected_action != ACTION_LABELS[self.selected_action_index]
            or not self.model_device
            or type(self.cuda_active) is not bool
            or self.model_tensors_device_verified is not True
            or self.confidence_calibrated is not None
            or self.profitability_probability is not None
            or self.local_research_non_promotable is not True
            or self.external_witness_verified is not False
            or any(getattr(self, name) is not False for name in _FALSE_AUTHORITY_FIELDS)
            or self.hypothesis_binding_sha256 != stable_sha256(self._material())
        ):
            _fail("LOCAL_PROFILED_RAW_INFERENCE_RESULT_INVALID")

    def _material(self) -> dict[str, Any]:
        return _json_object_material(
            {
                field_name: getattr(self, field_name)
                for field_name in self.__dataclass_fields__
                if field_name
                not in {
                    "_factory_token",
                    "hypothesis_binding_sha256",
                }
            }
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            **self._material(),
            "hypothesis_binding_sha256": self.hypothesis_binding_sha256,
        }


@dataclass(frozen=True, slots=True)
class LocallyAuthenticatedProfiledResearchInferenceHandleV1:
    checkpoint_id: str
    checkpoint_generation: int
    checkpoint_generated_at: str
    checkpoint_weight_sha256: str
    checkpoint_evidence_digest: str
    checkpoint_semantic_digest: str
    checkpoint_causal_record_digest: str
    model_id: str
    input_dim: int
    model_parameter_fingerprint_sha256: str
    candidate_contract_sha256: str
    candidate_contract_json: str = field(repr=False)
    candidate_authorization_receipt_sha256: str
    candidate_code_release_sha: str
    candidate_manifest_observation_time: str
    current_release_verified: bool
    current_source_closure_verified: bool
    local_research_non_promotable: bool
    external_witness_verified: bool
    consumer_eligible: bool
    trainer_admission_authorized: bool
    prediction_authorized: bool
    serving_authorized: bool
    serving_activation_authorized: bool
    serving_promotion_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    exchange_access_authorized: bool
    deployment_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _factory_seal: str = field(repr=False, compare=False)
    _factory_token: InitVar[object | None] = None

    def __post_init__(self, _factory_token: object | None) -> None:
        if _factory_token is not _HANDLE_FACTORY_TOKEN:
            _fail("LOCAL_PROFILED_INFERENCE_HANDLE_FACTORY_REQUIRED")
        self._validate_invariants()

    def _validate_invariants(self) -> None:
        try:
            contract = json.loads(self.candidate_contract_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            _fail("LOCAL_PROFILED_INFERENCE_HANDLE_CONTRACT_INVALID")
        if type(contract) is not dict:
            _fail("LOCAL_PROFILED_INFERENCE_HANDLE_CONTRACT_INVALID")
        contract = cast(dict[str, Any], contract)
        public_values = {name: getattr(self, name) for name in _HANDLE_SEALED_PUBLIC_FIELDS}
        expected_seal = stable_sha256(
            _handle_seal_material(
                public_values=public_values,
                model_owner=self._model_owner,
            )
        )
        hashes = (
            self.checkpoint_weight_sha256,
            self.checkpoint_evidence_digest,
            self.checkpoint_semantic_digest,
            self.checkpoint_causal_record_digest,
            self.model_parameter_fingerprint_sha256,
            self.candidate_contract_sha256,
            self.candidate_authorization_receipt_sha256,
            self._factory_seal,
        )
        manifest_clock = _clock(
            self.candidate_manifest_observation_time,
            reason="LOCAL_PROFILED_INFERENCE_HANDLE_CLOCK_INVALID",
        )[1]
        checkpoint_clock = _clock(
            self.checkpoint_generated_at,
            reason="LOCAL_PROFILED_INFERENCE_HANDLE_CLOCK_INVALID",
        )[1]
        if (
            _IDENTIFIER_RE.fullmatch(self.checkpoint_id) is None
            or type(self.checkpoint_generation) is not int
            or self.checkpoint_generation <= 0
            or any(_SHA256_RE.fullmatch(value) is None for value in hashes)
            or _SHA1_RE.fullmatch(self.candidate_code_release_sha) is None
            or not self.model_id
            or self.input_dim != LOGICAL_MODEL_INPUT_COUNT
            or self.input_dim != CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
            or manifest_clock >= checkpoint_clock
            or stable_sha256(contract) != self.candidate_contract_sha256
            or contract.get("candidate_policy_fingerprint")
            != self.model_parameter_fingerprint_sha256
            or contract.get("authorization_receipt_sha256")
            != self.candidate_authorization_receipt_sha256
            or contract.get("code_release_sha") != self.candidate_code_release_sha
            or contract.get("manifest_observation_time") != self.candidate_manifest_observation_time
            or contract.get("local_research_non_promotable") is not True
            or contract.get("external_witness_verified") is not False
            or any(contract.get(name) is not False for name in _FALSE_AUTHORITY_FIELDS[2:])
            or self.current_release_verified is not True
            or self.current_source_closure_verified is not True
            or self.local_research_non_promotable is not True
            or self.external_witness_verified is not False
            or any(getattr(self, name) is not False for name in _FALSE_AUTHORITY_FIELDS)
            or type(self._model_owner) is not V2HybridPolicyModel
            or self._model_owner.input_dim != self.input_dim
            or self._model_owner.model_id != self.model_id
            or model_parameter_fingerprint(self._model_owner)
            != self.model_parameter_fingerprint_sha256
            or not hmac.compare_digest(self._factory_seal, expected_seal)
        ):
            _fail("LOCAL_PROFILED_INFERENCE_HANDLE_INVALID")

    def infer_profiled_record_v1(
        self,
        *,
        record: Mapping[str, Any],
        transform_result: AuthenticatedOhlcvProfileTransformV1Result,
        capture_set_contract: Mapping[str, Any],
        capture_set_store: ImmutableSourcePayloadStore,
        artifact_store: ImmutableSourcePayloadStore,
        source_provenance_ledger: TrainerSourceProvenanceLedgerV4,
        source_provenance_entries: tuple[
            TrainerSourceProvenanceLedgerEntryV4,
            TrainerSourceProvenanceLedgerEntryV4,
        ],
    ) -> LocallyAuthenticatedProfiledResearchRawInferenceV1:
        """Freshly verify one immutable record and return quarantined logits."""

        self._validate_invariants()
        if type(record) is not dict:
            _fail("LOCAL_PROFILED_INFERENCE_RECORD_EXACT_DICT_REQUIRED")
        try:
            validation = validate_profiled_model_feature_snapshot_record_v1(
                record,
                transform_result=transform_result,
                capture_set_contract=capture_set_contract,
                capture_set_store=capture_set_store,
                artifact_store=artifact_store,
                source_provenance_ledger=source_provenance_ledger,
                source_provenance_entries=source_provenance_entries,
            )
        except Exception as exc:
            raise LocallyAuthenticatedProfiledResearchInferenceV1Error(
                "LOCAL_PROFILED_INFERENCE_RECORD_REVALIDATION_FAILED:" f"{type(exc).__name__}"
            ) from exc
        projection = validation.logical_projection
        projection.__post_init__()
        envelope = record.get("frozen_envelope")
        if type(envelope) is not dict:
            _fail("LOCAL_PROFILED_INFERENCE_RECORD_ENVELOPE_INVALID")
        envelope = cast(dict[str, Any], envelope)
        lineage_binding = validation.lineage_binding
        if (
            record.get("durable_snapshot_id") != validation.durable_snapshot_id
            or record.get("record_sha256") != validation.record_sha256
            or record.get("frozen_envelope_sha256") != validation.frozen_envelope_sha256
            or envelope.get("source_lineage_sha256") != validation.source_lineage_sha256
            or envelope.get("feature_snapshot_id") != validation.feature_snapshot_id
            or lineage_binding.get("logical_model_vector_sha256") != projection.model_vector_sha256
            or lineage_binding.get("logical_projection_sha256")
            != projection.logical_projection_sha256
            or envelope.get("temporal_rejection_reasons")
            != [PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON]
            or envelope.get("strict_training_eligible") is not False
        ):
            _fail("LOCAL_PROFILED_INFERENCE_RECORD_BINDING_INVALID")
        feature_cutoff, feature_clock = _clock(
            envelope.get("feature_cutoff"),
            reason="LOCAL_PROFILED_INFERENCE_FEATURE_CUTOFF_INVALID",
        )
        record_generated_at, generated_clock = _clock(
            envelope.get("generated_at"),
            reason="LOCAL_PROFILED_INFERENCE_RECORD_GENERATED_AT_INVALID",
        )
        source_decision_time, source_decision_clock = _clock(
            envelope.get("tensor_decision_time"),
            reason="LOCAL_PROFILED_INFERENCE_SOURCE_DECISION_TIME_INVALID",
        )
        checkpoint_clock = _clock(
            self.checkpoint_generated_at,
            reason="LOCAL_PROFILED_INFERENCE_CHECKPOINT_CLOCK_INVALID",
        )[1]
        _, inference_started_clock = _clock(
            _utc_iso(),
            reason="LOCAL_PROFILED_INFERENCE_START_CLOCK_INVALID",
        )
        if not (
            checkpoint_clock
            < feature_clock
            <= generated_clock
            <= source_decision_clock
            <= inference_started_clock
        ):
            _fail("LOCAL_PROFILED_INFERENCE_NOT_STRICTLY_POST_CHECKPOINT_PIT")
        configured_sources = tuple(
            slot.configured_source_label for slot in FEATURE_SOURCE_REGISTRY_V4.slots
        )
        available_feature_count = sum(projection.source_availability_mask)
        coverage = 100.0 * available_feature_count / len(projection.source_availability_mask)
        tensor_binding = {
            "domain": "v2/native-trainer/local-profiled-raw-inference-tensor/v1",
            "checkpoint_id": self.checkpoint_id,
            "durable_snapshot_id": validation.durable_snapshot_id,
            "record_sha256": validation.record_sha256,
            "lineage_binding_sha256": validation.lineage_binding_sha256,
            "logical_model_vector_sha256": projection.model_vector_sha256,
            "source_decision_time": source_decision_time,
        }
        tensor = FeatureTensorRecord(
            tensor_id=f"local_profiled_raw_{stable_sha256(tensor_binding)}",
            symbol=cast(str, envelope["symbol"]),
            timeframe=cast(str, envelope["timeframe"]),
            feature_snapshot_id=validation.feature_snapshot_id,
            values=projection.feature_values,
            missing_mask=projection.missing_mask,
            stale_mask=projection.stale_mask,
            source_availability=projection.source_availability_mask,
            feature_names=projection.ordered_feature_names,
            source_labels=configured_sources,
            missing_feature_names=tuple(
                name
                for name, flag in zip(
                    projection.ordered_feature_names,
                    projection.missing_mask,
                    strict=True,
                )
                if flag
            ),
            stale_feature_names=tuple(
                name
                for name, flag in zip(
                    projection.ordered_feature_names,
                    projection.stale_mask,
                    strict=True,
                )
                if flag
            ),
            data_coverage_percent=coverage,
            source_availability_vector=projection.source_availability_mask,
            decision_time=source_decision_time,
            source_lineage_hash=validation.lineage_binding_sha256,
            temporal_rejection_reasons=(PROFILED_MODEL_FEATURE_SNAPSHOT_RECORD_V1_UNWIRED_REASON,),
        )
        if (
            len(configured_sources) != LOGICAL_MODEL_FEATURE_COUNT
            or tensor.model_vector != projection.model_vector
            or available_feature_count != 35
            or tensor.data_coverage_percent == 100.0
        ):
            _fail("LOCAL_PROFILED_INFERENCE_TENSOR_BINDING_INVALID")
        candidate_pair = (
            self.checkpoint_id,
            self.candidate_contract_sha256,
            tensor.symbol,
            tensor.timeframe,
        )
        with _PROCESS_SOURCE_ORDER_LOCK:
            previous = _PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR.get(candidate_pair)
            if previous is not None and source_decision_clock <= previous:
                _fail("LOCAL_PROFILED_INFERENCE_SOURCE_ORDER_NOT_MONOTONIC")
            try:
                verify_current_profiled_optimizer_release_source_closure_v1(
                    expected_code_release_sha=self.candidate_code_release_sha,
                    expected_optimizer_implementation_artifact_sha256=cast(
                        str,
                        json.loads(self.candidate_contract_json).get(
                            "optimizer_implementation_artifact_sha256"
                        ),
                    ),
                )
            except Exception as exc:
                raise LocallyAuthenticatedProfiledResearchInferenceV1Error(
                    "LOCAL_PROFILED_INFERENCE_RELEASE_SOURCE_CLOSURE_REVALIDATION_FAILED:"
                    f"{type(exc).__name__}"
                ) from exc
            try:
                forward = self._model_owner.forward(tensor)
            except Exception as exc:
                raise LocallyAuthenticatedProfiledResearchInferenceV1Error(
                    "LOCAL_PROFILED_INFERENCE_MODEL_FORWARD_FAILED:" f"{type(exc).__name__}"
                ) from exc
            try:
                logits = tuple(float(value) for value in forward.action_logits)
                forward_model_id = forward.model_id
                selected_action_index = forward.selected_action_index
                selected_action = forward.selected_action
                model_device = forward.device
                cuda_active = forward.cuda_active
                model_tensors_device_verified = forward.model_tensors_device_verified
            except Exception as exc:
                raise LocallyAuthenticatedProfiledResearchInferenceV1Error(
                    "LOCAL_PROFILED_INFERENCE_MODEL_OUTPUT_INVALID:" f"{type(exc).__name__}"
                ) from exc
            if (
                forward_model_id != self.model_id
                or len(logits) != len(ACTION_LABELS)
                or any(not math.isfinite(value) for value in logits)
                or type(selected_action_index) is not int
                or not 0 <= selected_action_index < len(ACTION_LABELS)
                or selected_action_index != max(range(len(logits)), key=logits.__getitem__)
                or selected_action != ACTION_LABELS[selected_action_index]
                or type(model_device) is not str
                or not model_device
                or type(cuda_active) is not bool
                or model_tensors_device_verified is not True
            ):
                _fail("LOCAL_PROFILED_INFERENCE_MODEL_OUTPUT_INVALID")
            hypothesis_generated_at, hypothesis_clock = _clock(
                _utc_iso(),
                reason="LOCAL_PROFILED_INFERENCE_HYPOTHESIS_CLOCK_INVALID",
            )
            if not (source_decision_clock <= inference_started_clock <= hypothesis_clock):
                _fail("LOCAL_PROFILED_INFERENCE_HYPOTHESIS_CLOCK_ORDER_INVALID")
            _PROCESS_LAST_SOURCE_DECISION_BY_CANDIDATE_PAIR[candidate_pair] = source_decision_clock
        values: dict[str, Any] = {
            "schema_version": LOCAL_PROFILED_RESEARCH_INFERENCE_V1_SCHEMA_VERSION,
            "classification": (LOCAL_PROFILED_RESEARCH_RAW_INFERENCE_V1_CLASSIFICATION),
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_generation": self.checkpoint_generation,
            "checkpoint_generated_at": self.checkpoint_generated_at,
            "checkpoint_weight_sha256": self.checkpoint_weight_sha256,
            "model_id": self.model_id,
            "model_parameter_fingerprint": self.model_parameter_fingerprint_sha256,
            "candidate_contract_sha256": self.candidate_contract_sha256,
            "candidate_authorization_receipt_sha256": (self.candidate_authorization_receipt_sha256),
            "candidate_code_release_sha": self.candidate_code_release_sha,
            "candidate_manifest_observation_time": (self.candidate_manifest_observation_time),
            "symbol": tensor.symbol,
            "timeframe": tensor.timeframe,
            "durable_snapshot_id": validation.durable_snapshot_id,
            "record_sha256": validation.record_sha256,
            "frozen_envelope_sha256": validation.frozen_envelope_sha256,
            "source_lineage_sha256": validation.source_lineage_sha256,
            "lineage_binding_sha256": validation.lineage_binding_sha256,
            "feature_snapshot_id": validation.feature_snapshot_id,
            "logical_model_vector_sha256": projection.model_vector_sha256,
            "logical_projection_sha256": projection.logical_projection_sha256,
            "feature_cutoff": feature_cutoff,
            "record_generated_at": record_generated_at,
            "source_decision_time": source_decision_time,
            "hypothesis_generated_at": hypothesis_generated_at,
            "tensor_id": tensor.tensor_id,
            "total_feature_count": LOGICAL_MODEL_FEATURE_COUNT,
            "available_feature_count": available_feature_count,
            "data_coverage_percent": coverage,
            "temporal_rejection_reasons": tensor.temporal_rejection_reasons,
            "raw_action_logits": logits,
            "raw_action_logits_sha256": stable_sha256(list(logits)),
            "selected_action_index": selected_action_index,
            "selected_action": selected_action,
            "model_device": model_device,
            "cuda_active": cuda_active,
            "model_tensors_device_verified": model_tensors_device_verified,
            "confidence_calibrated": None,
            "profitability_probability": None,
            "local_research_non_promotable": True,
            "external_witness_verified": False,
            **{name: False for name in _FALSE_AUTHORITY_FIELDS},
        }
        return LocallyAuthenticatedProfiledResearchRawInferenceV1(
            **values,
            hypothesis_binding_sha256=stable_sha256(_json_object_material(values)),
            _factory_token=_RESULT_FACTORY_TOKEN,
        )


def _validated_local_research_key(
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
) -> bytes:
    if (
        type(credentials) is not AuthenticatedProfiledResidentRuntimeCredentialsV1
        or type(credentials.local_roles) is not AuthenticatedProfiledResidentLocalRoleCredentialsV1
    ):
        _fail("LOCAL_PROFILED_INFERENCE_CREDENTIAL_TYPES_INVALID")
    roles = credentials.local_roles
    role_keys = (
        roles.state_hmac_key,
        roles.manifest_hmac_key,
        roles.head_hmac_key,
        roles.epoch_hmac_key,
    )
    local_key = credentials.local_research_hmac_key
    if (
        type(local_key) is not bytes
        or len(local_key) < 32
        or any(type(value) is not bytes or len(value) < 32 for value in role_keys)
        or len({value for value in (*role_keys, local_key)}) != len(role_keys) + 1
    ):
        _fail("LOCAL_PROFILED_INFERENCE_CREDENTIAL_ROLE_SEPARATION_INVALID")
    return local_key


def open_locally_authenticated_profiled_research_inference_v1(
    *,
    config: LocallyAuthenticatedProfiledResearchServiceConfigV1,
    credentials: AuthenticatedProfiledResidentRuntimeCredentialsV1,
    expected_checkpoint_id: str,
) -> LocallyAuthenticatedProfiledResearchInferenceHandleV1:
    """Open one exact local checkpoint as a quarantined raw-inference handle."""

    if type(config) is not LocallyAuthenticatedProfiledResearchServiceConfigV1:
        _fail("LOCAL_PROFILED_INFERENCE_CONFIG_EXACT_TYPE_REQUIRED")
    if (
        type(expected_checkpoint_id) is not str
        or _IDENTIFIER_RE.fullmatch(expected_checkpoint_id) is None
    ):
        _fail("LOCAL_PROFILED_INFERENCE_CHECKPOINT_ID_INVALID")
    try:
        config.__post_init__()
        local_key = _validated_local_research_key(credentials)
        manager = V2HybridCheckpointManager(config.candidate_model_dir)
        with checkpoint_lifecycle_lease(
            config.model_dir,
            owner_role=LOCAL_PROFILED_RESEARCH_TRAINER_LEASE_OWNER_ROLE,
        ):
            manifests = manager.manifests(
                input_dim=LOGICAL_MODEL_INPUT_COUNT,
                allowed_lineage_kinds=frozenset({LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE}),
                require_weight_blob=True,
                verify_lineage_artifacts=False,
            )
            matches = tuple(
                manifest
                for manifest in manifests
                if manifest.checkpoint_id == expected_checkpoint_id
            )
            if len(matches) != 1:
                _fail("LOCAL_PROFILED_INFERENCE_EXACT_CHECKPOINT_NOT_SINGLETON")
            manifest = matches[0]
            contract = _verify_local_candidate_manifest(
                manager=manager,
                manifest=manifest,
                expected_auth_key_id=config.local_research_auth_key_id,
                authorization_hmac_key=local_key,
            )
            verify_current_profiled_optimizer_release_source_closure_v1(
                expected_code_release_sha=cast(str, contract.get("code_release_sha")),
                expected_optimizer_implementation_artifact_sha256=cast(
                    str,
                    contract.get("optimizer_implementation_artifact_sha256"),
                ),
            )
            model = V2HybridPolicyModel(
                input_dim=LOGICAL_MODEL_INPUT_COUNT,
                checkpoint_feature_abi_binding=(deployed_checkpoint_feature_abi_binding_v4()),
            )
            load = manager.load_latest_weights(
                model,
                allowed_lineage_kinds=frozenset({LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE}),
                expected_checkpoint_id=expected_checkpoint_id,
            )
        if type(contract) is not dict or type(load) is not dict:
            _fail("LOCAL_PROFILED_INFERENCE_CHECKPOINT_LOAD_POSTCONDITIONS_FAILED")
        restored_fingerprint = model_parameter_fingerprint(model)
        postconditions = (
            load.get("checkpoint_id") == expected_checkpoint_id,
            load.get("load_status") == "LOADED",
            load.get("latest_checkpoint_loadable") is True,
            load.get("model_state_restored") is True,
            load.get("checkpoint_evidence_verified") is True,
            load.get("checkpoint_identity_verified") is True,
            load.get("model_parameter_fingerprint_verified") is True,
            load.get("weight_file_sha256_verified") is True,
            load.get("private_checkpoint_copy_verified") is True,
            load.get("private_checkpoint_source_open_count") == 1,
            load.get("private_checkpoint_copy_sha256") == manifest.weight_file_sha256,
            load.get("private_checkpoint_copy_size_bytes") == manifest.weight_file_size_bytes,
            load.get("lineage_kind") == LOCAL_PROFILED_RESEARCH_CANDIDATE_LINEAGE,
            load.get("checkpoint_causal_store") == config.candidate_model_dir.name,
            load.get("checkpoint_generation") == manifest.checkpoint_generation,
            load.get("checkpoint_semantic_digest") == manifest.checkpoint_semantic_digest,
            load.get("checkpoint_causal_record_digest") == manifest.checkpoint_causal_record_digest,
            load.get("checkpoint_evidence_digest") == manifest.checkpoint_evidence_digest,
            load.get("model_parameter_fingerprint") == manifest.model_parameter_fingerprint,
            restored_fingerprint == manifest.model_parameter_fingerprint,
            model.model_id == manifest.model_id,
            model.input_dim == manifest.input_dim == LOGICAL_MODEL_INPUT_COUNT,
            getattr(model, "_net", None) is None or getattr(model._net, "training", None) is False,  # noqa: SLF001
        )
        if not all(postconditions):
            _fail("LOCAL_PROFILED_INFERENCE_CHECKPOINT_LOAD_POSTCONDITIONS_FAILED")
        contract_json = _canonical_json(contract)
        contract_sha256 = stable_sha256(contract)
        handle_values: dict[str, Any] = {
            "checkpoint_id": manifest.checkpoint_id,
            "checkpoint_generation": manifest.checkpoint_generation,
            "checkpoint_generated_at": manifest.generated_utc,
            "checkpoint_weight_sha256": cast(str, manifest.weight_file_sha256),
            "checkpoint_evidence_digest": cast(str, manifest.checkpoint_evidence_digest),
            "checkpoint_semantic_digest": cast(str, manifest.checkpoint_semantic_digest),
            "checkpoint_causal_record_digest": cast(
                str,
                manifest.checkpoint_causal_record_digest,
            ),
            "model_id": manifest.model_id,
            "input_dim": manifest.input_dim,
            "model_parameter_fingerprint_sha256": restored_fingerprint,
            "candidate_contract_sha256": contract_sha256,
            "candidate_contract_json": contract_json,
            "candidate_authorization_receipt_sha256": cast(
                str,
                contract.get("authorization_receipt_sha256"),
            ),
            "candidate_code_release_sha": cast(str, contract.get("code_release_sha")),
            "candidate_manifest_observation_time": cast(
                str,
                contract.get("manifest_observation_time"),
            ),
            "current_release_verified": True,
            "current_source_closure_verified": True,
            "local_research_non_promotable": True,
            "external_witness_verified": False,
            **{name: False for name in _FALSE_AUTHORITY_FIELDS},
        }
        seal = stable_sha256(
            _handle_seal_material(
                public_values=handle_values,
                model_owner=model,
            )
        )
        return LocallyAuthenticatedProfiledResearchInferenceHandleV1(
            **handle_values,
            _model_owner=model,
            _factory_seal=seal,
            _factory_token=_HANDLE_FACTORY_TOKEN,
        )
    except LocallyAuthenticatedProfiledResearchInferenceV1Error:
        raise
    except Exception as exc:
        raise LocallyAuthenticatedProfiledResearchInferenceV1Error(
            "LOCAL_PROFILED_INFERENCE_CHECKPOINT_OPEN_FAILED:" f"{type(exc).__name__}"
        ) from exc


__all__ = (
    "LOCAL_PROFILED_RESEARCH_INFERENCE_V1_SCHEMA_VERSION",
    "LOCAL_PROFILED_RESEARCH_RAW_INFERENCE_V1_CLASSIFICATION",
    "LocallyAuthenticatedProfiledResearchInferenceHandleV1",
    "LocallyAuthenticatedProfiledResearchInferenceV1Error",
    "LocallyAuthenticatedProfiledResearchRawInferenceV1",
    "open_locally_authenticated_profiled_research_inference_v1",
)
