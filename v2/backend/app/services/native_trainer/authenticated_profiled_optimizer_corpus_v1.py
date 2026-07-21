"""Exact full-manifest corpus contract for the profiled supervised optimizer.

The only accepted source objects are factory-created
``AuthenticatedProfiledOptimizerAdmissionV1`` results.  Every admission is
revalidated, the complete manifest admitted count must be present exactly
once in ascending manifest ordinal order, and the resulting corpus binds the
manifest, completion, external witness, feature ABI, projection, sample,
label, tensor, model-vector, target, and causal-clock inventories.

Building a corpus authorizes only use of its immutable rows as supervised
optimizer input.  A separate before/after equality check can authorize a
supervised optimizer invocation over those exact rows.  Neither operation
runs an optimizer or authorizes checkpoint/model publication, prediction,
paper trading, live trading, order submission, generic trading execution, or
runtime wiring.  PPO behavior-policy terms remain unavailable because this
lane has no genuine behavior receipt contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import secrets
import struct
from dataclasses import dataclass, field, replace
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    PROFILED_OPTIMIZER_OBJECTIVE_LANE,
    AuthenticatedProfiledOptimizerAdmissionV1,
    AuthenticatedProfiledOptimizerAdmissionV1Error,
    AuthenticatedProfiledOutcomeSupervisedTargetV1,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256,
    FEATURE_SOURCE_REGISTRY_V4_SHA256,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
    LOGICAL_PROFILE_SELECTION_MASK,
    LOGICAL_PROFILE_SELECTION_MASK_SHA256,
)
from v2.backend.app.services.native_trainer.profiled_training_ledger_loader_v1 import (
    PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256,
    PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION,
)

AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_optimizer_corpus_v1"
)
AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_ROW_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_optimizer_corpus_row_v1"
)
AUTHENTICATED_PROFILED_OPTIMIZER_CAUSAL_CLOCK_RANGE_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_optimizer_causal_clock_range_v1"
)
AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_AUTHORIZATION_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_supervised_optimizer_execution_authorization_v1"
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_MODEL_VECTOR_FLOAT64_DOMAIN = b"authenticated_profiled_optimizer_model_input_float64_v1\0"
_LOGICAL_MODEL_VECTOR_DOMAIN = b"canonical_feature_model_vector_v3\0"
_LABEL_VALUE_DOMAIN = b"profiled_training_after_cost_label_float64_v1\0"
_ROW_INVENTORY_DOMAIN = "v2/native-trainer/profiled-optimizer-corpus-row/v1"
_ORDERED_INVENTORY_DOMAIN = "v2/native-trainer/profiled-optimizer-corpus-inventory/v1"
_CLOCK_INVENTORY_DOMAIN = "v2/native-trainer/profiled-optimizer-clock-inventory/v1"
_CORPUS_TOKEN = object()
_ROW_TOKEN = object()
_CLOCK_RANGE_TOKEN = object()
_EXECUTION_TOKEN = object()
_FACTORY_SEAL_TOKEN = object()
_FACTORY_SEAL_KEY = secrets.token_bytes(32)
_ROW_FACTORY_SEAL_DOMAIN = b"authenticated_profiled_optimizer_corpus_row_factory_seal_v1"
_CLOCK_RANGE_FACTORY_SEAL_DOMAIN = b"authenticated_profiled_optimizer_clock_range_factory_seal_v1"
_CORPUS_FACTORY_SEAL_DOMAIN = b"authenticated_profiled_optimizer_corpus_factory_seal_v1"
_EXECUTION_FACTORY_SEAL_DOMAIN = (
    b"authenticated_profiled_supervised_optimizer_execution_factory_seal_v1"
)


class AuthenticatedProfiledOptimizerCorpusV1Error(RuntimeError):
    """An admitted corpus or its immutable before/after inventory failed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedProfiledOptimizerCorpusV1Error(*reasons) from None


class _FactorySeal:
    """One-time factory seal that cannot be reused for changed material."""

    __slots__ = ("_digest", "_domain")

    def __init__(self, *, domain: bytes, construction_token: object) -> None:
        if construction_token is not _FACTORY_SEAL_TOKEN or type(domain) is not bytes:
            _fail("PROFILED_OPTIMIZER_CORPUS_FACTORY_SEAL_CONSTRUCTION_FORBIDDEN")
        object.__setattr__(self, "_domain", bytes(domain))
        object.__setattr__(self, "_digest", None)

    def __setattr__(self, _name: str, _value: object) -> NoReturn:
        _fail("PROFILED_OPTIMIZER_CORPUS_FACTORY_SEAL_IMMUTABLE")

    def validate_or_bind(self, *, domain: bytes, material: object, reason: str) -> None:
        if self._domain != domain:
            _fail(reason)
        expected = hmac.digest(
            _FACTORY_SEAL_KEY,
            domain + b"\0" + _canonical_bytes(material, reason=reason),
            "sha256",
        )
        current = self._digest
        if current is None:
            object.__setattr__(self, "_digest", expected)
        elif type(current) is not bytes or not hmac.compare_digest(current, expected):
            _fail(reason)


def _require_factory_seal(
    value: object,
    *,
    domain: bytes,
    material: object,
    reason: str,
) -> None:
    if type(value) is not _FactorySeal:
        _fail(reason)
    cast(_FactorySeal, value).validate_or_bind(
        domain=domain,
        material=material,
        reason=reason,
    )


def _valid_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


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
    if normalized.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _fail(reason)
    return normalized


def _canonical_bytes(value: object, *, reason: str) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    except (OverflowError, RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise AuthenticatedProfiledOptimizerCorpusV1Error(reason) from exc


def _model_vector_float64_sha256(values: tuple[float, ...]) -> str:
    if type(values) is not tuple or len(values) != LOGICAL_MODEL_INPUT_COUNT:
        _fail("PROFILED_OPTIMIZER_CORPUS_MODEL_INPUT_DIMENSION_INVALID")
    digest = hashlib.sha256()
    digest.update(_MODEL_VECTOR_FLOAT64_DOMAIN)
    for value in values:
        if type(value) is not float or not math.isfinite(value):
            _fail("PROFILED_OPTIMIZER_CORPUS_MODEL_INPUT_VALUE_INVALID")
        digest.update(struct.pack(">d", value))
    return digest.hexdigest()


def _logical_model_vector_sha256(values: tuple[float, ...]) -> str:
    if type(values) is not tuple or len(values) != LOGICAL_MODEL_INPUT_COUNT:
        _fail("PROFILED_OPTIMIZER_CORPUS_LOGICAL_MODEL_INPUT_DIMENSION_INVALID")
    digest = hashlib.sha256()
    digest.update(_LOGICAL_MODEL_VECTOR_DOMAIN)
    digest.update(bytes.fromhex(FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256))
    digest.update(struct.pack(">I", LOGICAL_MODEL_FEATURE_COUNT))
    for value in values:
        if type(value) is not float or not math.isfinite(value):
            _fail("PROFILED_OPTIMIZER_CORPUS_LOGICAL_MODEL_INPUT_VALUE_INVALID")
        try:
            encoded = struct.pack(">f", value)
            canonical = struct.unpack(">f", encoded)[0]
        except (OverflowError, struct.error):
            _fail("PROFILED_OPTIMIZER_CORPUS_LOGICAL_MODEL_INPUT_VALUE_INVALID")
        if canonical != value:
            _fail("PROFILED_OPTIMIZER_CORPUS_LOGICAL_MODEL_INPUT_NOT_FLOAT32_CANONICAL")
        digest.update(encoded)
    return digest.hexdigest()


def _label_value_sha256(value: object) -> str:
    if type(value) is not float or not math.isfinite(value):
        _fail("PROFILED_OPTIMIZER_CORPUS_TARGET_VALUE_INVALID")
    return hashlib.sha256(_LABEL_VALUE_DOMAIN + struct.pack(">d", value)).hexdigest()


def _false_downstream_authority(values: tuple[bool, ...]) -> bool:
    return all(value is False for value in values)


def _corpus_factory_seal_value(value: object) -> object:
    if type(value) is AuthenticatedProfiledOutcomeSupervisedTargetV1:
        return {
            "target_sha256": cast(
                AuthenticatedProfiledOutcomeSupervisedTargetV1,
                value,
            ).target_sha256
        }
    row_type = globals().get("AuthenticatedProfiledOptimizerCorpusRowV1")
    if row_type is not None and type(value) is row_type:
        return {"row_inventory_sha256": cast(Any, value).row_inventory_sha256}
    clock_type = globals().get("AuthenticatedProfiledOptimizerCausalClockRangeV1")
    if clock_type is not None and type(value) is clock_type:
        return {"causal_clock_range_sha256": cast(Any, value).causal_clock_range_sha256}
    if type(value) is tuple:
        return [_corpus_factory_seal_value(item) for item in cast(tuple[object, ...], value)]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    _fail("PROFILED_OPTIMIZER_CORPUS_FACTORY_SEAL_MATERIAL_INVALID")


def _corpus_factory_seal_material(value: object) -> dict[str, object]:
    try:
        items = dataclass_fields(value)
    except TypeError:
        _fail("PROFILED_OPTIMIZER_CORPUS_FACTORY_SEAL_MATERIAL_INVALID")
    return {
        item.name: _corpus_factory_seal_value(getattr(value, item.name))
        for item in items
        if not item.name.startswith("_")
    }


def _validate_admission(admission: object) -> AuthenticatedProfiledOptimizerAdmissionV1:
    if type(admission) is not AuthenticatedProfiledOptimizerAdmissionV1:
        _fail("PROFILED_OPTIMIZER_CORPUS_ADMISSION_EXACT_TYPE_REQUIRED")
    result = cast(AuthenticatedProfiledOptimizerAdmissionV1, admission)
    try:
        result.__post_init__()
    except AuthenticatedProfiledOptimizerAdmissionV1Error as exc:
        raise AuthenticatedProfiledOptimizerCorpusV1Error(
            "PROFILED_OPTIMIZER_CORPUS_ADMISSION_REVALIDATION_FAILED",
            *exc.reasons,
        ) from exc
    return result


def _common_binding(admission: AuthenticatedProfiledOptimizerAdmissionV1) -> dict[str, Any]:
    return {
        "manifest_id": admission.manifest_id,
        "manifest_metadata_sha256": admission.manifest_metadata_sha256,
        "manifest_observation_context_sha256": (admission.manifest_observation_context_sha256),
        "manifest_entry_chain_head_sha256": admission.manifest_entry_chain_head_sha256,
        "manifest_ordered_entry_identities_sha256": (
            admission.manifest_ordered_entry_identities_sha256
        ),
        "manifest_total_profiled_samples": admission.manifest_total_profiled_samples,
        "manifest_admitted_example_count": admission.manifest_admitted_example_count,
        "manifest_label_unavailable_count": admission.manifest_label_unavailable_count,
        "completion_event_sha256": admission.completion_event_sha256,
        "completion_ordered_page_root_sha256": admission.completion_ordered_page_root_sha256,
        "completion_page_count": admission.completion_page_count,
        "completion_consumed_entry_count": admission.completion_consumed_entry_count,
        "completion_admitted_entry_count": admission.completion_admitted_entry_count,
        "completion_label_unavailable_count": admission.completion_label_unavailable_count,
        "external_authorization_envelope_sha256": (
            admission.external_authorization_envelope_sha256
        ),
        "witness_id": admission.witness_id,
        "witness_namespace": admission.witness_namespace,
        "witness_public_key_sha256": admission.witness_public_key_sha256,
        "witness_sequence": admission.witness_sequence,
        "witness_previous_event_sha256": admission.witness_previous_event_sha256,
        "witness_accepted_at": admission.witness_accepted_at,
        "feature_registry_sha256": admission.feature_registry_sha256,
        "feature_registry_abi_sha256": admission.feature_registry_abi_sha256,
        "logical_profile_selection_mask": list(admission.logical_profile_selection_mask),
        "logical_profile_selection_mask_sha256": (admission.logical_profile_selection_mask_sha256),
        "projection_schema_version": admission.projection_schema_version,
        "projection_implementation_sha256": admission.projection_implementation_sha256,
        "projection_configuration_sha256": admission.projection_configuration_sha256,
        "observation_time": admission.observation_time,
    }


def _row_material(
    *,
    ordinal: int,
    symbol: str,
    timeframe: str,
    sample_identity_sha256: str,
    label_binding_sha256: str,
    tensor_binding_sha256: str,
    logical_model_vector_sha256: str,
    logical_projection_sha256: str,
    model_input_float64_sha256: str,
    supervised_target_sha256: str,
    target_label_value_float64_sha256: str,
    model_feature_cutoff: str,
    record_wide_evidence_cutoff: str,
    source_feature_available_at: str,
    decision_feature_available_at: str,
    feature_generated_at: str,
    training_record_generated_at: str,
    decision_time: str,
    trainer_sample_available_at: str,
    label_available_at: str,
    observation_time: str,
) -> dict[str, Any]:
    return {
        "schema_version": AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_ROW_V1_SCHEMA_VERSION,
        "inventory_domain": _ROW_INVENTORY_DOMAIN,
        "ordinal": ordinal,
        "symbol": symbol,
        "timeframe": timeframe,
        "sample_identity_sha256": sample_identity_sha256,
        "label_binding_sha256": label_binding_sha256,
        "tensor_binding_sha256": tensor_binding_sha256,
        "logical_model_vector_sha256": logical_model_vector_sha256,
        "logical_projection_sha256": logical_projection_sha256,
        "model_input_float64_sha256": model_input_float64_sha256,
        "supervised_target_sha256": supervised_target_sha256,
        "target_label_value_float64_sha256": target_label_value_float64_sha256,
        "model_feature_cutoff": model_feature_cutoff,
        "record_wide_evidence_cutoff": record_wide_evidence_cutoff,
        "source_feature_available_at": source_feature_available_at,
        "decision_feature_available_at": decision_feature_available_at,
        "feature_generated_at": feature_generated_at,
        "training_record_generated_at": training_record_generated_at,
        "decision_time": decision_time,
        "trainer_sample_available_at": trainer_sample_available_at,
        "label_available_at": label_available_at,
        "observation_time": observation_time,
        "objective_lane": PROFILED_OPTIMIZER_OBJECTIVE_LANE,
        "outcome_supervised_objective_only": True,
        "behavior_receipt_bound": False,
        "ppo_behavior_policy_terms_enabled": False,
    }


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledOptimizerCorpusRowV1:
    schema_version: str
    ordinal: int
    symbol: str
    timeframe: str
    sample_identity_sha256: str
    label_binding_sha256: str
    tensor_binding_sha256: str
    logical_model_vector_sha256: str
    logical_projection_sha256: str
    model_input: tuple[float, ...] = field(repr=False)
    model_input_float64_sha256: str
    supervised_target: AuthenticatedProfiledOutcomeSupervisedTargetV1
    model_feature_cutoff: str
    record_wide_evidence_cutoff: str
    source_feature_available_at: str
    decision_feature_available_at: str
    feature_generated_at: str
    training_record_generated_at: str
    decision_time: str
    trainer_sample_available_at: str
    label_available_at: str
    observation_time: str
    row_inventory_sha256: str
    outcome_supervised_objective_only: bool
    behavior_receipt_bound: bool
    ppo_behavior_policy_terms_enabled: bool
    supervised_optimizer_input_authorized: bool
    supervised_optimizer_execution_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.supervised_target) is not AuthenticatedProfiledOutcomeSupervisedTargetV1:
            _fail("PROFILED_OPTIMIZER_CORPUS_TARGET_EXACT_TYPE_REQUIRED")
        try:
            self.supervised_target.__post_init__()
        except AuthenticatedProfiledOptimizerAdmissionV1Error as exc:
            raise AuthenticatedProfiledOptimizerCorpusV1Error(
                "PROFILED_OPTIMIZER_CORPUS_TARGET_REVALIDATION_FAILED",
                *exc.reasons,
            ) from exc
        hashes = (
            self.sample_identity_sha256,
            self.label_binding_sha256,
            self.tensor_binding_sha256,
            self.logical_model_vector_sha256,
            self.logical_projection_sha256,
            self.model_input_float64_sha256,
            self.supervised_target.target_sha256,
            self.supervised_target.label_value_float64_sha256,
            self.row_inventory_sha256,
        )
        clocks = tuple(
            _clock(value, reason="PROFILED_OPTIMIZER_CORPUS_ROW_CLOCK_INVALID")
            for value in (
                self.model_feature_cutoff,
                self.source_feature_available_at,
                self.decision_feature_available_at,
                self.feature_generated_at,
                self.training_record_generated_at,
                self.decision_time,
                self.trainer_sample_available_at,
                self.observation_time,
            )
        )
        record_wide = _clock(
            self.record_wide_evidence_cutoff,
            reason="PROFILED_OPTIMIZER_CORPUS_ROW_RECORD_WIDE_CUTOFF_INVALID",
        )
        label_available = _clock(
            self.label_available_at,
            reason="PROFILED_OPTIMIZER_CORPUS_ROW_LABEL_AVAILABLE_AT_INVALID",
        )
        material = _row_material(
            ordinal=self.ordinal,
            symbol=self.symbol,
            timeframe=self.timeframe,
            sample_identity_sha256=self.sample_identity_sha256,
            label_binding_sha256=self.label_binding_sha256,
            tensor_binding_sha256=self.tensor_binding_sha256,
            logical_model_vector_sha256=self.logical_model_vector_sha256,
            logical_projection_sha256=self.logical_projection_sha256,
            model_input_float64_sha256=self.model_input_float64_sha256,
            supervised_target_sha256=self.supervised_target.target_sha256,
            target_label_value_float64_sha256=(self.supervised_target.label_value_float64_sha256),
            model_feature_cutoff=self.model_feature_cutoff,
            record_wide_evidence_cutoff=self.record_wide_evidence_cutoff,
            source_feature_available_at=self.source_feature_available_at,
            decision_feature_available_at=self.decision_feature_available_at,
            feature_generated_at=self.feature_generated_at,
            training_record_generated_at=self.training_record_generated_at,
            decision_time=self.decision_time,
            trainer_sample_available_at=self.trainer_sample_available_at,
            label_available_at=self.label_available_at,
            observation_time=self.observation_time,
        )
        if (
            self._construction_token is not _ROW_TOKEN
            or self.schema_version != AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_ROW_V1_SCHEMA_VERSION
            or type(self.ordinal) is not int
            or self.ordinal <= 0
            or type(self.symbol) is not str
            or not self.symbol
            or type(self.timeframe) is not str
            or not self.timeframe
            or not all(_valid_sha256(value) for value in hashes)
            or self.model_input_float64_sha256 != _model_vector_float64_sha256(self.model_input)
            or self.logical_model_vector_sha256 != _logical_model_vector_sha256(self.model_input)
            or self.supervised_target.label_binding_sha256 != self.label_binding_sha256
            or self.supervised_target.label_available_at != self.label_available_at
            or self.supervised_target.label_value_float64_sha256
            != _label_value_sha256(self.supervised_target.signed_expected_move_after_cost_bps)
            or self.row_inventory_sha256 != stable_sha256(material)
            or clocks != tuple(sorted(clocks))
            or not clocks[0] <= record_wide <= clocks[5]
            or not clocks[5] < label_available < clocks[7]
            or self.outcome_supervised_objective_only is not True
            or self.behavior_receipt_bound is not False
            or self.ppo_behavior_policy_terms_enabled is not False
            or self.supervised_optimizer_input_authorized is not True
            or self.supervised_optimizer_execution_authorized is not False
            or not _false_downstream_authority(
                (
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
            _fail("PROFILED_OPTIMIZER_CORPUS_ROW_INVALID")
        _require_factory_seal(
            self._factory_seal,
            domain=_ROW_FACTORY_SEAL_DOMAIN,
            material=_corpus_factory_seal_material(self),
            reason="PROFILED_OPTIMIZER_CORPUS_ROW_FACTORY_SEAL_INVALID",
        )


def _build_row(
    admission: AuthenticatedProfiledOptimizerAdmissionV1,
) -> AuthenticatedProfiledOptimizerCorpusRowV1:
    target = replace(admission.supervised_target)
    material = _row_material(
        ordinal=admission.ordinal,
        symbol=admission.symbol,
        timeframe=admission.timeframe,
        sample_identity_sha256=admission.sample_identity_sha256,
        label_binding_sha256=admission.label_binding_sha256,
        tensor_binding_sha256=admission.tensor_binding_sha256,
        logical_model_vector_sha256=admission.logical_model_vector_sha256,
        logical_projection_sha256=admission.logical_projection_sha256,
        model_input_float64_sha256=admission.model_input_float64_sha256,
        supervised_target_sha256=target.target_sha256,
        target_label_value_float64_sha256=target.label_value_float64_sha256,
        model_feature_cutoff=admission.model_feature_cutoff,
        record_wide_evidence_cutoff=admission.record_wide_evidence_cutoff,
        source_feature_available_at=admission.source_feature_available_at,
        decision_feature_available_at=admission.decision_feature_available_at,
        feature_generated_at=admission.feature_generated_at,
        training_record_generated_at=admission.training_record_generated_at,
        decision_time=admission.decision_time,
        trainer_sample_available_at=admission.trainer_sample_available_at,
        label_available_at=admission.label_available_at,
        observation_time=admission.observation_time,
    )
    return AuthenticatedProfiledOptimizerCorpusRowV1(
        schema_version=AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_ROW_V1_SCHEMA_VERSION,
        ordinal=admission.ordinal,
        symbol=admission.symbol,
        timeframe=admission.timeframe,
        sample_identity_sha256=admission.sample_identity_sha256,
        label_binding_sha256=admission.label_binding_sha256,
        tensor_binding_sha256=admission.tensor_binding_sha256,
        logical_model_vector_sha256=admission.logical_model_vector_sha256,
        logical_projection_sha256=admission.logical_projection_sha256,
        model_input=admission.model_input,
        model_input_float64_sha256=admission.model_input_float64_sha256,
        supervised_target=target,
        model_feature_cutoff=admission.model_feature_cutoff,
        record_wide_evidence_cutoff=admission.record_wide_evidence_cutoff,
        source_feature_available_at=admission.source_feature_available_at,
        decision_feature_available_at=admission.decision_feature_available_at,
        feature_generated_at=admission.feature_generated_at,
        training_record_generated_at=admission.training_record_generated_at,
        decision_time=admission.decision_time,
        trainer_sample_available_at=admission.trainer_sample_available_at,
        label_available_at=admission.label_available_at,
        observation_time=admission.observation_time,
        row_inventory_sha256=stable_sha256(material),
        outcome_supervised_objective_only=True,
        behavior_receipt_bound=False,
        ppo_behavior_policy_terms_enabled=False,
        supervised_optimizer_input_authorized=True,
        supervised_optimizer_execution_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _factory_seal=_FactorySeal(
            domain=_ROW_FACTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_ROW_TOKEN,
    )


def _ordered_row_clock_material(
    rows: tuple[AuthenticatedProfiledOptimizerCorpusRowV1, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "ordinal": row.ordinal,
            "model_feature_cutoff": row.model_feature_cutoff,
            "record_wide_evidence_cutoff": row.record_wide_evidence_cutoff,
            "source_feature_available_at": row.source_feature_available_at,
            "decision_feature_available_at": row.decision_feature_available_at,
            "feature_generated_at": row.feature_generated_at,
            "training_record_generated_at": row.training_record_generated_at,
            "decision_time": row.decision_time,
            "trainer_sample_available_at": row.trainer_sample_available_at,
            "label_available_at": row.label_available_at,
            "observation_time": row.observation_time,
        }
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledOptimizerCausalClockRangeV1:
    schema_version: str
    earliest_model_feature_cutoff: str
    latest_model_feature_cutoff: str
    earliest_record_wide_evidence_cutoff: str
    latest_record_wide_evidence_cutoff: str
    earliest_source_feature_available_at: str
    latest_source_feature_available_at: str
    earliest_decision_feature_available_at: str
    latest_decision_feature_available_at: str
    earliest_feature_generated_at: str
    latest_feature_generated_at: str
    earliest_training_record_generated_at: str
    latest_training_record_generated_at: str
    earliest_decision_time: str
    latest_decision_time: str
    earliest_trainer_sample_available_at: str
    latest_trainer_sample_available_at: str
    earliest_label_available_at: str
    latest_label_available_at: str
    observation_time: str
    ordered_row_clock_inventory_sha256: str
    causal_clock_range_sha256: str
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        pairs = (
            (self.earliest_model_feature_cutoff, self.latest_model_feature_cutoff),
            (
                self.earliest_record_wide_evidence_cutoff,
                self.latest_record_wide_evidence_cutoff,
            ),
            (
                self.earliest_source_feature_available_at,
                self.latest_source_feature_available_at,
            ),
            (
                self.earliest_decision_feature_available_at,
                self.latest_decision_feature_available_at,
            ),
            (self.earliest_feature_generated_at, self.latest_feature_generated_at),
            (
                self.earliest_training_record_generated_at,
                self.latest_training_record_generated_at,
            ),
            (self.earliest_decision_time, self.latest_decision_time),
            (
                self.earliest_trainer_sample_available_at,
                self.latest_trainer_sample_available_at,
            ),
            (self.earliest_label_available_at, self.latest_label_available_at),
        )
        material = {
            key: value
            for key, value in self._as_material().items()
            if key != "causal_clock_range_sha256"
        }
        if (
            self._construction_token is not _CLOCK_RANGE_TOKEN
            or self.schema_version
            != AUTHENTICATED_PROFILED_OPTIMIZER_CAUSAL_CLOCK_RANGE_V1_SCHEMA_VERSION
            or not all(
                _clock(start, reason="PROFILED_OPTIMIZER_CORPUS_CLOCK_RANGE_INVALID")
                <= _clock(end, reason="PROFILED_OPTIMIZER_CORPUS_CLOCK_RANGE_INVALID")
                for start, end in pairs
            )
            or not _valid_sha256(self.ordered_row_clock_inventory_sha256)
            or self.causal_clock_range_sha256 != stable_sha256(material)
        ):
            _fail("PROFILED_OPTIMIZER_CORPUS_CAUSAL_CLOCK_RANGE_INVALID")
        _clock(
            self.observation_time,
            reason="PROFILED_OPTIMIZER_CORPUS_CLOCK_RANGE_OBSERVATION_INVALID",
        )
        _require_factory_seal(
            self._factory_seal,
            domain=_CLOCK_RANGE_FACTORY_SEAL_DOMAIN,
            material=_corpus_factory_seal_material(self),
            reason="PROFILED_OPTIMIZER_CORPUS_CLOCK_RANGE_FACTORY_SEAL_INVALID",
        )

    def _as_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "earliest_model_feature_cutoff": self.earliest_model_feature_cutoff,
            "latest_model_feature_cutoff": self.latest_model_feature_cutoff,
            "earliest_record_wide_evidence_cutoff": (self.earliest_record_wide_evidence_cutoff),
            "latest_record_wide_evidence_cutoff": self.latest_record_wide_evidence_cutoff,
            "earliest_source_feature_available_at": (self.earliest_source_feature_available_at),
            "latest_source_feature_available_at": self.latest_source_feature_available_at,
            "earliest_decision_feature_available_at": (self.earliest_decision_feature_available_at),
            "latest_decision_feature_available_at": (self.latest_decision_feature_available_at),
            "earliest_feature_generated_at": self.earliest_feature_generated_at,
            "latest_feature_generated_at": self.latest_feature_generated_at,
            "earliest_training_record_generated_at": (self.earliest_training_record_generated_at),
            "latest_training_record_generated_at": self.latest_training_record_generated_at,
            "earliest_decision_time": self.earliest_decision_time,
            "latest_decision_time": self.latest_decision_time,
            "earliest_trainer_sample_available_at": (self.earliest_trainer_sample_available_at),
            "latest_trainer_sample_available_at": self.latest_trainer_sample_available_at,
            "earliest_label_available_at": self.earliest_label_available_at,
            "latest_label_available_at": self.latest_label_available_at,
            "observation_time": self.observation_time,
            "ordered_row_clock_inventory_sha256": self.ordered_row_clock_inventory_sha256,
            "causal_clock_range_sha256": self.causal_clock_range_sha256,
        }


def _clock_range(
    rows: tuple[AuthenticatedProfiledOptimizerCorpusRowV1, ...],
) -> AuthenticatedProfiledOptimizerCausalClockRangeV1:
    ordered_clock_material = _ordered_row_clock_material(rows)
    ordered_clock_sha256 = stable_sha256(
        {
            "domain": _CLOCK_INVENTORY_DOMAIN,
            "ordered_rows": ordered_clock_material,
        }
    )
    material = {
        "schema_version": AUTHENTICATED_PROFILED_OPTIMIZER_CAUSAL_CLOCK_RANGE_V1_SCHEMA_VERSION,
        "earliest_model_feature_cutoff": min(row.model_feature_cutoff for row in rows),
        "latest_model_feature_cutoff": max(row.model_feature_cutoff for row in rows),
        "earliest_record_wide_evidence_cutoff": min(
            row.record_wide_evidence_cutoff for row in rows
        ),
        "latest_record_wide_evidence_cutoff": max(row.record_wide_evidence_cutoff for row in rows),
        "earliest_source_feature_available_at": min(
            row.source_feature_available_at for row in rows
        ),
        "latest_source_feature_available_at": max(row.source_feature_available_at for row in rows),
        "earliest_decision_feature_available_at": min(
            row.decision_feature_available_at for row in rows
        ),
        "latest_decision_feature_available_at": max(
            row.decision_feature_available_at for row in rows
        ),
        "earliest_feature_generated_at": min(row.feature_generated_at for row in rows),
        "latest_feature_generated_at": max(row.feature_generated_at for row in rows),
        "earliest_training_record_generated_at": min(
            row.training_record_generated_at for row in rows
        ),
        "latest_training_record_generated_at": max(
            row.training_record_generated_at for row in rows
        ),
        "earliest_decision_time": min(row.decision_time for row in rows),
        "latest_decision_time": max(row.decision_time for row in rows),
        "earliest_trainer_sample_available_at": min(
            row.trainer_sample_available_at for row in rows
        ),
        "latest_trainer_sample_available_at": max(row.trainer_sample_available_at for row in rows),
        "earliest_label_available_at": min(row.label_available_at for row in rows),
        "latest_label_available_at": max(row.label_available_at for row in rows),
        "observation_time": rows[0].observation_time,
        "ordered_row_clock_inventory_sha256": ordered_clock_sha256,
    }
    return AuthenticatedProfiledOptimizerCausalClockRangeV1(
        **material,
        causal_clock_range_sha256=stable_sha256(material),
        _factory_seal=_FactorySeal(
            domain=_CLOCK_RANGE_FACTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_CLOCK_RANGE_TOKEN,
    )


def _corpus_material(
    *,
    common: dict[str, Any],
    admitted_ordinals: tuple[int, ...],
    ordered_admitted_inventory_sha256: str,
    causal_clock_range_sha256: str,
) -> dict[str, Any]:
    return {
        "schema_version": AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_V1_SCHEMA_VERSION,
        "common_authenticated_binding": common,
        "admitted_ordinals": list(admitted_ordinals),
        "ordered_admitted_inventory_sha256": ordered_admitted_inventory_sha256,
        "causal_clock_range_sha256": causal_clock_range_sha256,
        "objective_lane": PROFILED_OPTIMIZER_OBJECTIVE_LANE,
        "full_manifest_admitted_inventory_bound": True,
        "ordered_unique_admitted_ordinals_verified": True,
        "outcome_supervised_objective_only": True,
        "behavior_receipt_bound": False,
        "ppo_behavior_policy_terms_enabled": False,
        "supervised_optimizer_input_authorized": True,
        "supervised_optimizer_execution_authorized": False,
        "optimizer_execution_authorized": False,
        "checkpoint_write_authorized": False,
        "model_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
        "execution_authorized": False,
        "runtime_wired": False,
    }


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledOptimizerCorpusV1:
    schema_version: str
    manifest_id: str
    manifest_metadata_sha256: str
    manifest_observation_context_sha256: str
    manifest_entry_chain_head_sha256: str
    manifest_ordered_entry_identities_sha256: str
    manifest_total_profiled_samples: int
    manifest_admitted_example_count: int
    manifest_label_unavailable_count: int
    completion_event_sha256: str
    completion_ordered_page_root_sha256: str
    completion_page_count: int
    completion_consumed_entry_count: int
    completion_admitted_entry_count: int
    completion_label_unavailable_count: int
    external_authorization_envelope_sha256: str
    witness_id: str
    witness_namespace: str
    witness_public_key_sha256: str
    witness_sequence: int
    witness_previous_event_sha256: str
    witness_accepted_at: str
    feature_registry_sha256: str
    feature_registry_abi_sha256: str
    logical_profile_selection_mask: tuple[int, ...] = field(repr=False)
    logical_profile_selection_mask_sha256: str
    projection_schema_version: str
    projection_implementation_sha256: str
    projection_configuration_sha256: str
    observation_time: str
    admitted_ordinals: tuple[int, ...]
    rows: tuple[AuthenticatedProfiledOptimizerCorpusRowV1, ...] = field(repr=False)
    ordered_admitted_inventory_sha256: str
    causal_clock_range: AuthenticatedProfiledOptimizerCausalClockRangeV1
    corpus_contract_sha256: str
    full_manifest_admitted_inventory_bound: bool
    ordered_unique_admitted_ordinals_verified: bool
    outcome_supervised_objective_only: bool
    behavior_receipt_bound: bool
    ppo_behavior_policy_terms_enabled: bool
    supervised_optimizer_input_authorized: bool
    supervised_optimizer_execution_authorized: bool
    optimizer_execution_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.rows) is not tuple or not self.rows:
            _fail("PROFILED_OPTIMIZER_CORPUS_ROWS_REQUIRED")
        for row in self.rows:
            if type(row) is not AuthenticatedProfiledOptimizerCorpusRowV1:
                _fail("PROFILED_OPTIMIZER_CORPUS_ROW_EXACT_TYPE_REQUIRED")
            row.__post_init__()
        if type(self.causal_clock_range) is not AuthenticatedProfiledOptimizerCausalClockRangeV1:
            _fail("PROFILED_OPTIMIZER_CORPUS_CLOCK_RANGE_EXACT_TYPE_REQUIRED")
        self.causal_clock_range.__post_init__()
        common = self._common_material()
        ordered_inventory = stable_sha256(
            {
                "domain": _ORDERED_INVENTORY_DOMAIN,
                "manifest_id": self.manifest_id,
                "manifest_admitted_example_count": self.manifest_admitted_example_count,
                "ordered_rows": [row.row_inventory_sha256 for row in self.rows],
            }
        )
        material = _corpus_material(
            common=common,
            admitted_ordinals=self.admitted_ordinals,
            ordered_admitted_inventory_sha256=self.ordered_admitted_inventory_sha256,
            causal_clock_range_sha256=self.causal_clock_range.causal_clock_range_sha256,
        )
        hash_fields = (
            self.manifest_id,
            self.manifest_metadata_sha256,
            self.manifest_observation_context_sha256,
            self.manifest_entry_chain_head_sha256,
            self.manifest_ordered_entry_identities_sha256,
            self.completion_event_sha256,
            self.completion_ordered_page_root_sha256,
            self.external_authorization_envelope_sha256,
            self.witness_public_key_sha256,
            self.witness_previous_event_sha256,
            self.feature_registry_sha256,
            self.feature_registry_abi_sha256,
            self.logical_profile_selection_mask_sha256,
            self.projection_implementation_sha256,
            self.projection_configuration_sha256,
            self.ordered_admitted_inventory_sha256,
            self.corpus_contract_sha256,
        )
        if (
            self._construction_token is not _CORPUS_TOKEN
            or self.schema_version != AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_V1_SCHEMA_VERSION
            or not all(_valid_sha256(value) for value in hash_fields)
            or any(
                type(value) is not int or value < 0
                for value in (
                    self.manifest_total_profiled_samples,
                    self.manifest_admitted_example_count,
                    self.manifest_label_unavailable_count,
                    self.completion_page_count,
                    self.completion_consumed_entry_count,
                    self.completion_admitted_entry_count,
                    self.completion_label_unavailable_count,
                )
            )
            or self.manifest_total_profiled_samples
            != self.manifest_admitted_example_count + self.manifest_label_unavailable_count
            or self.manifest_admitted_example_count <= 0
            or self.manifest_admitted_example_count != len(self.rows)
            or self.completion_consumed_entry_count != self.manifest_total_profiled_samples
            or self.completion_admitted_entry_count != self.manifest_admitted_example_count
            or self.completion_label_unavailable_count != self.manifest_label_unavailable_count
            or self.completion_page_count <= 0
            or type(self.witness_sequence) is not int
            or self.witness_sequence <= 0
            or type(self.witness_id) is not str
            or not self.witness_id
            or type(self.witness_namespace) is not str
            or not self.witness_namespace
            or type(self.admitted_ordinals) is not tuple
            or any(type(ordinal) is not int for ordinal in self.admitted_ordinals)
            or self.admitted_ordinals != tuple(row.ordinal for row in self.rows)
            or self.admitted_ordinals != tuple(sorted(set(self.admitted_ordinals)))
            or any(
                ordinal <= 0 or ordinal > self.manifest_total_profiled_samples
                for ordinal in self.admitted_ordinals
            )
            or any(row.observation_time != self.observation_time for row in self.rows)
            or self.feature_registry_sha256 != FEATURE_SOURCE_REGISTRY_V4_SHA256
            or self.feature_registry_abi_sha256 != FEATURE_SOURCE_REGISTRY_V4_ABI_SHA256
            or self.logical_profile_selection_mask != LOGICAL_PROFILE_SELECTION_MASK
            or self.logical_profile_selection_mask_sha256 != LOGICAL_PROFILE_SELECTION_MASK_SHA256
            or stable_sha256(list(self.logical_profile_selection_mask))
            != self.logical_profile_selection_mask_sha256
            or self.projection_schema_version != PROFILED_TRAINING_PROJECTION_V1_SCHEMA_VERSION
            or self.projection_implementation_sha256
            != PROFILED_TRAINING_PROJECTION_V1_IMPLEMENTATION_SHA256
            or self.projection_configuration_sha256
            != PROFILED_TRAINING_PROJECTION_V1_CONFIGURATION_SHA256
            or ordered_inventory != self.ordered_admitted_inventory_sha256
            or self.causal_clock_range != _clock_range(self.rows)
            or self.corpus_contract_sha256 != stable_sha256(material)
            or self.full_manifest_admitted_inventory_bound is not True
            or self.ordered_unique_admitted_ordinals_verified is not True
            or self.outcome_supervised_objective_only is not True
            or self.behavior_receipt_bound is not False
            or self.ppo_behavior_policy_terms_enabled is not False
            or self.supervised_optimizer_input_authorized is not True
            or self.supervised_optimizer_execution_authorized is not False
            or self.optimizer_execution_authorized is not False
            or not _false_downstream_authority(
                (
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
            _fail("PROFILED_OPTIMIZER_CORPUS_INVALID")
        witness_accepted = _clock(
            self.witness_accepted_at,
            reason="PROFILED_OPTIMIZER_CORPUS_WITNESS_ACCEPTED_AT_INVALID",
        )
        observation = _clock(
            self.observation_time,
            reason="PROFILED_OPTIMIZER_CORPUS_OBSERVATION_TIME_INVALID",
        )
        if observation >= witness_accepted:
            _fail("PROFILED_OPTIMIZER_CORPUS_WITNESS_CLOCK_ORDER_INVALID")
        _require_factory_seal(
            self._factory_seal,
            domain=_CORPUS_FACTORY_SEAL_DOMAIN,
            material=_corpus_factory_seal_material(self),
            reason="PROFILED_OPTIMIZER_CORPUS_FACTORY_SEAL_INVALID",
        )

    def _common_material(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "manifest_metadata_sha256": self.manifest_metadata_sha256,
            "manifest_observation_context_sha256": self.manifest_observation_context_sha256,
            "manifest_entry_chain_head_sha256": self.manifest_entry_chain_head_sha256,
            "manifest_ordered_entry_identities_sha256": (
                self.manifest_ordered_entry_identities_sha256
            ),
            "manifest_total_profiled_samples": self.manifest_total_profiled_samples,
            "manifest_admitted_example_count": self.manifest_admitted_example_count,
            "manifest_label_unavailable_count": self.manifest_label_unavailable_count,
            "completion_event_sha256": self.completion_event_sha256,
            "completion_ordered_page_root_sha256": self.completion_ordered_page_root_sha256,
            "completion_page_count": self.completion_page_count,
            "completion_consumed_entry_count": self.completion_consumed_entry_count,
            "completion_admitted_entry_count": self.completion_admitted_entry_count,
            "completion_label_unavailable_count": self.completion_label_unavailable_count,
            "external_authorization_envelope_sha256": (self.external_authorization_envelope_sha256),
            "witness_id": self.witness_id,
            "witness_namespace": self.witness_namespace,
            "witness_public_key_sha256": self.witness_public_key_sha256,
            "witness_sequence": self.witness_sequence,
            "witness_previous_event_sha256": self.witness_previous_event_sha256,
            "witness_accepted_at": self.witness_accepted_at,
            "feature_registry_sha256": self.feature_registry_sha256,
            "feature_registry_abi_sha256": self.feature_registry_abi_sha256,
            "logical_profile_selection_mask": list(self.logical_profile_selection_mask),
            "logical_profile_selection_mask_sha256": (self.logical_profile_selection_mask_sha256),
            "projection_schema_version": self.projection_schema_version,
            "projection_implementation_sha256": self.projection_implementation_sha256,
            "projection_configuration_sha256": self.projection_configuration_sha256,
            "observation_time": self.observation_time,
        }


def build_authenticated_profiled_optimizer_corpus_v1(
    admissions: tuple[AuthenticatedProfiledOptimizerAdmissionV1, ...],
) -> AuthenticatedProfiledOptimizerCorpusV1:
    """Build one complete immutable corpus from exact admitted results."""

    if type(admissions) is not tuple or not admissions:
        _fail("PROFILED_OPTIMIZER_CORPUS_ADMISSION_TUPLE_REQUIRED")
    validated = tuple(_validate_admission(admission) for admission in admissions)
    common = _common_binding(validated[0])
    if any(_common_binding(admission) != common for admission in validated[1:]):
        _fail("PROFILED_OPTIMIZER_CORPUS_COMMON_BINDING_MISMATCH")
    admitted_count = cast(int, common["manifest_admitted_example_count"])
    if len(validated) != admitted_count:
        _fail("PROFILED_OPTIMIZER_CORPUS_FULL_MANIFEST_ADMITTED_COUNT_MISMATCH")
    ordinals = tuple(admission.ordinal for admission in validated)
    if ordinals != tuple(sorted(set(ordinals))):
        _fail("PROFILED_OPTIMIZER_CORPUS_ADMITTED_ORDINAL_ORDER_INVALID")
    total = cast(int, common["manifest_total_profiled_samples"])
    if any(ordinal <= 0 or ordinal > total for ordinal in ordinals):
        _fail("PROFILED_OPTIMIZER_CORPUS_ADMITTED_ORDINAL_RANGE_INVALID")
    rows = tuple(_build_row(admission) for admission in validated)
    ordered_inventory_sha256 = stable_sha256(
        {
            "domain": _ORDERED_INVENTORY_DOMAIN,
            "manifest_id": common["manifest_id"],
            "manifest_admitted_example_count": admitted_count,
            "ordered_rows": [row.row_inventory_sha256 for row in rows],
        }
    )
    clock_range = _clock_range(rows)
    material = _corpus_material(
        common=common,
        admitted_ordinals=ordinals,
        ordered_admitted_inventory_sha256=ordered_inventory_sha256,
        causal_clock_range_sha256=clock_range.causal_clock_range_sha256,
    )
    return AuthenticatedProfiledOptimizerCorpusV1(
        schema_version=AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_V1_SCHEMA_VERSION,
        manifest_id=cast(str, common["manifest_id"]),
        manifest_metadata_sha256=cast(str, common["manifest_metadata_sha256"]),
        manifest_observation_context_sha256=cast(
            str, common["manifest_observation_context_sha256"]
        ),
        manifest_entry_chain_head_sha256=cast(str, common["manifest_entry_chain_head_sha256"]),
        manifest_ordered_entry_identities_sha256=cast(
            str, common["manifest_ordered_entry_identities_sha256"]
        ),
        manifest_total_profiled_samples=total,
        manifest_admitted_example_count=admitted_count,
        manifest_label_unavailable_count=cast(int, common["manifest_label_unavailable_count"]),
        completion_event_sha256=cast(str, common["completion_event_sha256"]),
        completion_ordered_page_root_sha256=cast(
            str, common["completion_ordered_page_root_sha256"]
        ),
        completion_page_count=cast(int, common["completion_page_count"]),
        completion_consumed_entry_count=cast(int, common["completion_consumed_entry_count"]),
        completion_admitted_entry_count=cast(int, common["completion_admitted_entry_count"]),
        completion_label_unavailable_count=cast(int, common["completion_label_unavailable_count"]),
        external_authorization_envelope_sha256=cast(
            str, common["external_authorization_envelope_sha256"]
        ),
        witness_id=cast(str, common["witness_id"]),
        witness_namespace=cast(str, common["witness_namespace"]),
        witness_public_key_sha256=cast(str, common["witness_public_key_sha256"]),
        witness_sequence=cast(int, common["witness_sequence"]),
        witness_previous_event_sha256=cast(str, common["witness_previous_event_sha256"]),
        witness_accepted_at=cast(str, common["witness_accepted_at"]),
        feature_registry_sha256=cast(str, common["feature_registry_sha256"]),
        feature_registry_abi_sha256=cast(str, common["feature_registry_abi_sha256"]),
        logical_profile_selection_mask=LOGICAL_PROFILE_SELECTION_MASK,
        logical_profile_selection_mask_sha256=cast(
            str, common["logical_profile_selection_mask_sha256"]
        ),
        projection_schema_version=cast(str, common["projection_schema_version"]),
        projection_implementation_sha256=cast(str, common["projection_implementation_sha256"]),
        projection_configuration_sha256=cast(str, common["projection_configuration_sha256"]),
        observation_time=cast(str, common["observation_time"]),
        admitted_ordinals=ordinals,
        rows=rows,
        ordered_admitted_inventory_sha256=ordered_inventory_sha256,
        causal_clock_range=clock_range,
        corpus_contract_sha256=stable_sha256(material),
        full_manifest_admitted_inventory_bound=True,
        ordered_unique_admitted_ordinals_verified=True,
        outcome_supervised_objective_only=True,
        behavior_receipt_bound=False,
        ppo_behavior_policy_terms_enabled=False,
        supervised_optimizer_input_authorized=True,
        supervised_optimizer_execution_authorized=False,
        optimizer_execution_authorized=False,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _factory_seal=_FactorySeal(
            domain=_CORPUS_FACTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_CORPUS_TOKEN,
    )


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1:
    schema_version: str
    corpus_contract_sha256: str
    manifest_id: str
    completion_event_sha256: str
    external_authorization_envelope_sha256: str
    witness_public_key_sha256: str
    admitted_example_count: int
    admitted_ordinals: tuple[int, ...]
    before_ordered_admitted_inventory_sha256: str
    after_ordered_admitted_inventory_sha256: str
    before_causal_clock_range_sha256: str
    after_causal_clock_range_sha256: str
    inventory_equality_sha256: str
    before_after_inventory_equality_verified: bool
    outcome_supervised_objective_only: bool
    behavior_receipt_bound: bool
    ppo_behavior_policy_terms_enabled: bool
    supervised_optimizer_input_authorized: bool
    supervised_optimizer_execution_authorized: bool
    optimizer_execution_authorized: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        material = self._material(include_identity=False)
        if (
            self._construction_token is not _EXECUTION_TOKEN
            or self.schema_version
            != AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_AUTHORIZATION_V1_SCHEMA_VERSION
            or not all(
                _valid_sha256(value)
                for value in (
                    self.corpus_contract_sha256,
                    self.manifest_id,
                    self.completion_event_sha256,
                    self.external_authorization_envelope_sha256,
                    self.witness_public_key_sha256,
                    self.before_ordered_admitted_inventory_sha256,
                    self.after_ordered_admitted_inventory_sha256,
                    self.before_causal_clock_range_sha256,
                    self.after_causal_clock_range_sha256,
                    self.inventory_equality_sha256,
                )
            )
            or type(self.admitted_example_count) is not int
            or self.admitted_example_count <= 0
            or type(self.admitted_ordinals) is not tuple
            or any(type(ordinal) is not int for ordinal in self.admitted_ordinals)
            or self.admitted_example_count != len(self.admitted_ordinals)
            or self.admitted_ordinals != tuple(sorted(set(self.admitted_ordinals)))
            or self.before_ordered_admitted_inventory_sha256
            != self.after_ordered_admitted_inventory_sha256
            or self.before_causal_clock_range_sha256 != self.after_causal_clock_range_sha256
            or self.inventory_equality_sha256 != stable_sha256(material)
            or self.before_after_inventory_equality_verified is not True
            or self.outcome_supervised_objective_only is not True
            or self.behavior_receipt_bound is not False
            or self.ppo_behavior_policy_terms_enabled is not False
            or self.supervised_optimizer_input_authorized is not True
            or self.supervised_optimizer_execution_authorized is not True
            or self.optimizer_execution_authorized is not True
            or not _false_downstream_authority(
                (
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
            _fail("PROFILED_OPTIMIZER_EXECUTION_AUTHORIZATION_INVALID")
        _require_factory_seal(
            self._factory_seal,
            domain=_EXECUTION_FACTORY_SEAL_DOMAIN,
            material=_corpus_factory_seal_material(self),
            reason="PROFILED_OPTIMIZER_EXECUTION_AUTHORIZATION_FACTORY_SEAL_INVALID",
        )

    def _material(self, *, include_identity: bool) -> dict[str, Any]:
        material = {
            "schema_version": self.schema_version,
            "corpus_contract_sha256": self.corpus_contract_sha256,
            "manifest_id": self.manifest_id,
            "completion_event_sha256": self.completion_event_sha256,
            "external_authorization_envelope_sha256": (self.external_authorization_envelope_sha256),
            "witness_public_key_sha256": self.witness_public_key_sha256,
            "admitted_example_count": self.admitted_example_count,
            "admitted_ordinals": list(self.admitted_ordinals),
            "before_ordered_admitted_inventory_sha256": (
                self.before_ordered_admitted_inventory_sha256
            ),
            "after_ordered_admitted_inventory_sha256": (
                self.after_ordered_admitted_inventory_sha256
            ),
            "before_causal_clock_range_sha256": self.before_causal_clock_range_sha256,
            "after_causal_clock_range_sha256": self.after_causal_clock_range_sha256,
            "before_after_inventory_equality_verified": (
                self.before_after_inventory_equality_verified
            ),
            "objective_lane": PROFILED_OPTIMIZER_OBJECTIVE_LANE,
            "outcome_supervised_objective_only": self.outcome_supervised_objective_only,
            "behavior_receipt_bound": self.behavior_receipt_bound,
            "ppo_behavior_policy_terms_enabled": self.ppo_behavior_policy_terms_enabled,
            "supervised_optimizer_input_authorized": (self.supervised_optimizer_input_authorized),
            "supervised_optimizer_execution_authorized": (
                self.supervised_optimizer_execution_authorized
            ),
            "optimizer_execution_authorized": self.optimizer_execution_authorized,
            "checkpoint_write_authorized": self.checkpoint_write_authorized,
            "model_write_authorized": self.model_write_authorized,
            "prediction_authorized": self.prediction_authorized,
            "paper_trading_authorized": self.paper_trading_authorized,
            "live_execution_authorized": self.live_execution_authorized,
            "order_submission_authorized": self.order_submission_authorized,
            "execution_authorized": self.execution_authorized,
            "runtime_wired": self.runtime_wired,
        }
        if include_identity:
            material["inventory_equality_sha256"] = self.inventory_equality_sha256
        return material


def validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1(
    *,
    before: AuthenticatedProfiledOptimizerCorpusV1,
    after: AuthenticatedProfiledOptimizerCorpusV1,
) -> AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1:
    """Authorize one supervised invocation only if both inventories are exact."""

    if (
        type(before) is not AuthenticatedProfiledOptimizerCorpusV1
        or type(after) is not AuthenticatedProfiledOptimizerCorpusV1
    ):
        _fail("PROFILED_OPTIMIZER_CORPUS_EQUALITY_EXACT_TYPE_REQUIRED")
    if before is after:
        _fail("PROFILED_OPTIMIZER_CORPUS_DISTINCT_BEFORE_AFTER_SNAPSHOTS_REQUIRED")
    before.__post_init__()
    after.__post_init__()
    if (
        before.rows is after.rows
        or before.causal_clock_range is after.causal_clock_range
        or any(
            before_row is after_row or before_row.supervised_target is after_row.supervised_target
            for before_row, after_row in zip(before.rows, after.rows, strict=False)
        )
    ):
        _fail("PROFILED_OPTIMIZER_CORPUS_DISTINCT_BEFORE_AFTER_SNAPSHOTS_REQUIRED")
    before_material = {
        "common": before._common_material(),
        "admitted_ordinals": list(before.admitted_ordinals),
        "ordered_admitted_inventory_sha256": before.ordered_admitted_inventory_sha256,
        "causal_clock_range_sha256": before.causal_clock_range.causal_clock_range_sha256,
        "corpus_contract_sha256": before.corpus_contract_sha256,
    }
    after_material = {
        "common": after._common_material(),
        "admitted_ordinals": list(after.admitted_ordinals),
        "ordered_admitted_inventory_sha256": after.ordered_admitted_inventory_sha256,
        "causal_clock_range_sha256": after.causal_clock_range.causal_clock_range_sha256,
        "corpus_contract_sha256": after.corpus_contract_sha256,
    }
    if not hmac.compare_digest(
        _canonical_bytes(
            before_material,
            reason="PROFILED_OPTIMIZER_CORPUS_BEFORE_INVENTORY_ENCODING_INVALID",
        ),
        _canonical_bytes(
            after_material,
            reason="PROFILED_OPTIMIZER_CORPUS_AFTER_INVENTORY_ENCODING_INVALID",
        ),
    ):
        _fail("PROFILED_OPTIMIZER_CORPUS_BEFORE_AFTER_INVENTORY_MISMATCH")
    material = {
        "schema_version": (
            AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_AUTHORIZATION_V1_SCHEMA_VERSION
        ),
        "corpus_contract_sha256": before.corpus_contract_sha256,
        "manifest_id": before.manifest_id,
        "completion_event_sha256": before.completion_event_sha256,
        "external_authorization_envelope_sha256": (before.external_authorization_envelope_sha256),
        "witness_public_key_sha256": before.witness_public_key_sha256,
        "admitted_example_count": before.manifest_admitted_example_count,
        "admitted_ordinals": list(before.admitted_ordinals),
        "before_ordered_admitted_inventory_sha256": (before.ordered_admitted_inventory_sha256),
        "after_ordered_admitted_inventory_sha256": after.ordered_admitted_inventory_sha256,
        "before_causal_clock_range_sha256": (before.causal_clock_range.causal_clock_range_sha256),
        "after_causal_clock_range_sha256": (after.causal_clock_range.causal_clock_range_sha256),
        "before_after_inventory_equality_verified": True,
        "objective_lane": PROFILED_OPTIMIZER_OBJECTIVE_LANE,
        "outcome_supervised_objective_only": True,
        "behavior_receipt_bound": False,
        "ppo_behavior_policy_terms_enabled": False,
        "supervised_optimizer_input_authorized": True,
        "supervised_optimizer_execution_authorized": True,
        "optimizer_execution_authorized": True,
        "checkpoint_write_authorized": False,
        "model_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
        "order_submission_authorized": False,
        "execution_authorized": False,
        "runtime_wired": False,
    }
    return AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1(
        schema_version=cast(str, material["schema_version"]),
        corpus_contract_sha256=before.corpus_contract_sha256,
        manifest_id=before.manifest_id,
        completion_event_sha256=before.completion_event_sha256,
        external_authorization_envelope_sha256=(before.external_authorization_envelope_sha256),
        witness_public_key_sha256=before.witness_public_key_sha256,
        admitted_example_count=before.manifest_admitted_example_count,
        admitted_ordinals=before.admitted_ordinals,
        before_ordered_admitted_inventory_sha256=(before.ordered_admitted_inventory_sha256),
        after_ordered_admitted_inventory_sha256=after.ordered_admitted_inventory_sha256,
        before_causal_clock_range_sha256=(before.causal_clock_range.causal_clock_range_sha256),
        after_causal_clock_range_sha256=(after.causal_clock_range.causal_clock_range_sha256),
        inventory_equality_sha256=stable_sha256(material),
        before_after_inventory_equality_verified=True,
        outcome_supervised_objective_only=True,
        behavior_receipt_bound=False,
        ppo_behavior_policy_terms_enabled=False,
        supervised_optimizer_input_authorized=True,
        supervised_optimizer_execution_authorized=True,
        optimizer_execution_authorized=True,
        checkpoint_write_authorized=False,
        model_write_authorized=False,
        prediction_authorized=False,
        paper_trading_authorized=False,
        live_execution_authorized=False,
        order_submission_authorized=False,
        execution_authorized=False,
        runtime_wired=False,
        _factory_seal=_FactorySeal(
            domain=_EXECUTION_FACTORY_SEAL_DOMAIN,
            construction_token=_FACTORY_SEAL_TOKEN,
        ),
        _construction_token=_EXECUTION_TOKEN,
    )


__all__ = (
    "AUTHENTICATED_PROFILED_OPTIMIZER_CAUSAL_CLOCK_RANGE_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_ROW_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_OPTIMIZER_CORPUS_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_AUTHORIZATION_V1_SCHEMA_VERSION",
    "AuthenticatedProfiledOptimizerCausalClockRangeV1",
    "AuthenticatedProfiledOptimizerCorpusRowV1",
    "AuthenticatedProfiledOptimizerCorpusV1",
    "AuthenticatedProfiledOptimizerCorpusV1Error",
    "AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1",
    "build_authenticated_profiled_optimizer_corpus_v1",
    "validate_authenticated_profiled_optimizer_corpus_inventory_equality_v1",
)
