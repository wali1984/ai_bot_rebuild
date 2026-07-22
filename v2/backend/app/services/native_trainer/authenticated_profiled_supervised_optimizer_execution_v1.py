from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import platform
import random
import secrets
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, NoReturn, cast

from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_admission_v1 import (
    LocallyValidatedProfiledResearchExampleV1,
    validate_profiled_observation_example_for_local_research_v1,
)
from v2.backend.app.services.native_trainer.authenticated_profiled_optimizer_corpus_v1 import (
    AuthenticatedProfiledOptimizerCorpusRowV1,
    AuthenticatedProfiledOptimizerCorpusV1,
    AuthenticatedProfiledOptimizerCorpusV1Error,
    AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1,
    validate_authenticated_profiled_optimizer_execution_authorization_pair_v1,
)
from v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4 import (
    CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM,
    CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256,
    verify_deployed_checkpoint_feature_abi_binding_v4,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
    stable_sha256,
)
from v2.backend.app.services.native_trainer.feature_source_registry_v4 import (
    FEATURE_SOURCE_REGISTRY_V4,
    REQUIREMENT_OPTIONAL_EVENT_DEPENDENT,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    model_parameter_fingerprint,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    PROFILED_ADMISSION_SCOPE_LOCAL_RESEARCH,
    PPOTrainingResult,
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.profiled_model_feature_snapshot_record_v1 import (
    LOGICAL_MODEL_FEATURE_COUNT,
    LOGICAL_MODEL_INPUT_COUNT,
)
from v2.backend.app.services.native_trainer.profiled_supervised_checkpoint_inventory_v1 import (
    MAX_PROFILED_CHECKPOINT_SERIALIZATION_BYTES,
    MAX_PROFILED_CONFIGURATION_ARTIFACT_BYTES,
    MAX_PROFILED_ENVIRONMENT_ARTIFACT_BYTES,
    PROFILED_CHECKPOINT_FIXED_ACCOUNTING_BYTES,
    PROFILED_OPTIMIZER_ROW_ACCOUNTING_BYTES,
    PROFILED_STATE_ITEM_ACCOUNTING_BYTES,
    ProfiledSupervisedCheckpointInventoryV1,
    ProfiledSupervisedCheckpointInventoryV1Error,
    build_authenticated_profiled_supervised_checkpoint_inventory_v1,
    capture_profiled_supervised_optimization_state_snapshot_v1,
)
from v2.backend.app.services.native_trainer.profiled_training_observation_manifest_v1 import (
    AuthenticatedProfiledTrainingObservationManifestV1,
    ProfiledTrainingObservationExampleV1,
)

AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION: Final = (
    "authenticated_profiled_supervised_optimizer_execution_v1"
)
AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_STATUS: Final = (
    "AUTHENTICATED_OUTCOME_SUPERVISED_STEP_COMPLETED_IN_MEMORY_NO_WRITE_OR_RUNTIME_AUTHORITY"
)
PROFILED_SUPERVISED_OPTIMIZER_OBJECTIVE_LANE: Final = "OUTCOME_SUPERVISED_ONLY"
LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION: Final = (
    "locally_authenticated_profiled_research_optimizer_execution_v1"
)
LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_STATUS: Final = (
    "LOCAL_HMAC_AUTHENTICATED_NON_PROMOTABLE_RESEARCH_STEP_COMPLETED_IN_MEMORY"
)
LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN: Final = (
    "v2/native-trainer/local-profiled-research-optimizer-authorization/v1"
)

_SUCCESS_STATUSES: Final = frozenset(
    {
        "V2_NATIVE_RL_MASA_OUTCOME_SUPERVISED_CPU_TRAINING_STEP_RAN",
        "V2_NATIVE_RL_MASA_OUTCOME_SUPERVISED_CUDA_TRAINING_STEP_RAN",
    }
)
_SUPPORTED_TENSOR_DTYPES: Final = frozenset(
    {
        "bool",
        "int8",
        "uint8",
        "int16",
        "uint16",
        "bfloat16",
        "float16",
        "int32",
        "uint32",
        "float32",
        "int64",
        "uint64",
        "float64",
    }
)
_FLOAT_TENSOR_DTYPES: Final = frozenset({"bfloat16", "float16", "float32", "float64"})
_EXECUTION_ENVIRONMENT_KEYS: Final = (
    "PPO_ENT_COEF",
    "PPO_GAMMA",
    "PPO_LEARNING_RATE",
    "V2_TRAINER_ATTENTION_ENCODER",
    "V2_TRAINER_ATTENTION_HEADS",
    "V2_TRAINER_CPU_THREADS",
    "V2_TRAINER_DROPOUT",
    "V2_TRAINER_FAST_STEP_METRICS",
    "V2_TRAINER_HIDDEN_SIZE",
    "V2_TRAINER_LEARNING_RATE",
    "V2_TRAINER_RESIDUAL_BLOCKS",
    "V2_TRAINER_SUPERVISED_ENTROPY_BONUS",
    "V2_TRAINER_TAIL_CVAR_ALPHA",
    "V2_TRAINER_TAIL_CVAR_WEIGHT",
    "V2_TRAINER_TEMPORAL_ENCODER",
    "V2_TRAINER_TEMPORAL_HIDDEN",
    "V2_TRAINER_TEMPORAL_PROJ_DIM",
    "V2_TRAINER_TEMPORAL_SEQ_LEN",
    "V2_TRAINER_WEIGHT_DECAY",
)
_AUTHORITY_FALSE: Final = {
    "checkpoint_write_authorized": False,
    "model_write_authorized": False,
    "prediction_authorized": False,
    "serving_authorized": False,
    "ppo_training_authorized": False,
    "paper_trading_authorized": False,
    "live_execution_authorized": False,
    "exchange_access_authorized": False,
    "deployment_authorized": False,
    "order_submission_authorized": False,
    "execution_authorized": False,
    "runtime_wired": False,
}
_RESULT_TOKEN = object()
_LOCAL_RESEARCH_RESULT_TOKEN = object()
_FACTORY_SEAL_KEY = secrets.token_bytes(32)
_FACTORY_SEAL_DOMAIN: Final = (
    b"authenticated_profiled_supervised_optimizer_execution_factory_seal_v1\0"
)


class AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(RuntimeError):
    """An authenticated optimizer invocation failed closed."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = tuple(dict.fromkeys(str(reason) for reason in reasons))
        super().__init__(";".join(self.reasons))


def _fail(*reasons: str) -> NoReturn:
    raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(*reasons) from None


def _valid_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(cast(str, value)) == 64
        and all(character in "0123456789abcdef" for character in cast(str, value))
    )


def _canonical_json_bytes(value: object, *, reason: str) -> bytes:
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


def _clock(value: object, *, reason: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str:
        try:
            parsed = datetime.fromisoformat(cast(str, value).replace("Z", "+00:00"))
        except ValueError:
            _fail(reason)
    else:
        _fail(reason)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(reason)
    return parsed.astimezone(UTC)


def _canonical_clock(value: object, *, reason: str) -> str:
    return _clock(value, reason=reason).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class _StageClock:
    def __init__(
        self,
        *,
        source: Callable[[], datetime | str],
        lower_bound: str,
    ) -> None:
        if not callable(source):
            _fail("PROFILED_SUPERVISED_EXECUTION_CLOCK_CALLABLE_REQUIRED")
        self._source = source
        self._last = _clock(
            lower_bound,
            reason="PROFILED_SUPERVISED_EXECUTION_CLOCK_LOWER_BOUND_INVALID",
        )

    def next(self, *, reason: str) -> str:
        try:
            raw = self._source()
        except Exception as exc:
            raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(reason) from exc
        parsed = _clock(raw, reason=reason)
        if parsed <= self._last:
            _fail(reason)
        self._last = parsed
        return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


class _DeterministicTorchExecution:
    """Temporarily isolate and deterministically seed process RNG/backend state."""

    def __init__(self, *, model: V2HybridPolicyModel, seed: int) -> None:
        if (
            type(model) is not V2HybridPolicyModel
            or type(seed) is not int
            or not 0 <= seed < 2**63
            or model.torch is None
        ):
            _fail("PROFILED_SUPERVISED_EXECUTION_DETERMINISM_INPUT_INVALID")
        self._model = model
        self._torch = model.torch
        self._seed = seed
        self._python_state: object | None = None
        self._cpu_state: object | None = None
        self._cuda_states: object | None = None
        self._deterministic_enabled = False
        self._deterministic_warn_only = False
        self._cudnn_deterministic: bool | None = None
        self._cudnn_benchmark: bool | None = None
        self._float32_matmul_precision: str | None = None
        self._thread_count: int | None = None
        self._cuda_matmul_allow_tf32: bool | None = None
        self._cudnn_allow_tf32: bool | None = None
        self._cuda_matmul_fp32_precision: str | None = None
        self._cudnn_conv_fp32_precision: str | None = None
        self._flash_sdp_enabled: bool | None = None
        self._memory_efficient_sdp_enabled: bool | None = None
        self._math_sdp_enabled: bool | None = None
        self.restored = False

    def prepare_optimizer(self) -> None:
        """Reapply deterministic state after model construction mutates globals."""

        torch = self._torch
        torch.use_deterministic_algorithms(True, warn_only=False)
        cudnn = getattr(torch.backends, "cudnn", None)
        if cudnn is not None:
            cudnn.deterministic = True
            cudnn.benchmark = False
        random.seed(self._seed)
        torch.manual_seed(self._seed)
        if self._model.cuda_active:
            torch.cuda.manual_seed_all(self._seed)
            cuda_backend = getattr(torch.backends, "cuda", None)
            if cuda_backend is not None:
                enable_flash = getattr(cuda_backend, "enable_flash_sdp", None)
                enable_memory = getattr(
                    cuda_backend,
                    "enable_mem_efficient_sdp",
                    None,
                )
                enable_math = getattr(cuda_backend, "enable_math_sdp", None)
                if None in (enable_flash, enable_memory, enable_math):
                    _fail(
                        "PROFILED_SUPERVISED_EXECUTION_CUDA_DETERMINISTIC_SDP_"
                        "CONTROLS_UNAVAILABLE"
                    )
                if enable_flash is not None:
                    enable_flash(False)
                if enable_memory is not None:
                    enable_memory(False)
                if enable_math is not None:
                    enable_math(True)

    def __enter__(self) -> _DeterministicTorchExecution:
        torch = self._torch
        if self._model.cuda_active and os.getenv("CUBLAS_WORKSPACE_CONFIG") not in {
            ":16:8",
            ":4096:8",
        }:
            _fail("PROFILED_SUPERVISED_EXECUTION_CUDA_DETERMINISM_ENV_REQUIRED")
        try:
            self._python_state = random.getstate()
            self._cpu_state = torch.random.get_rng_state().clone()
            if self._model.cuda_active:
                self._cuda_states = tuple(value.clone() for value in torch.cuda.get_rng_state_all())
            self._deterministic_enabled = bool(torch.are_deterministic_algorithms_enabled())
            warn_only = getattr(
                torch,
                "is_deterministic_algorithms_warn_only_enabled",
                None,
            )
            self._deterministic_warn_only = bool(warn_only()) if warn_only else False
            self._float32_matmul_precision = torch.get_float32_matmul_precision()
            self._thread_count = int(torch.get_num_threads())
            cudnn = getattr(torch.backends, "cudnn", None)
            if cudnn is not None:
                self._cudnn_deterministic = bool(cudnn.deterministic)
                self._cudnn_benchmark = bool(cudnn.benchmark)
                self._cudnn_allow_tf32 = bool(cudnn.allow_tf32)
            cuda_matmul = getattr(getattr(torch.backends, "cuda", None), "matmul", None)
            if cuda_matmul is not None:
                self._cuda_matmul_allow_tf32 = bool(cuda_matmul.allow_tf32)
                fp32_precision = getattr(cuda_matmul, "fp32_precision", None)
                self._cuda_matmul_fp32_precision = (
                    str(fp32_precision) if fp32_precision is not None else None
                )
            cudnn_conv = getattr(cudnn, "conv", None) if cudnn is not None else None
            if cudnn_conv is not None:
                fp32_precision = getattr(cudnn_conv, "fp32_precision", None)
                self._cudnn_conv_fp32_precision = (
                    str(fp32_precision) if fp32_precision is not None else None
                )
            cuda_backend = getattr(torch.backends, "cuda", None)
            if cuda_backend is not None:
                flash_status = getattr(cuda_backend, "flash_sdp_enabled", None)
                memory_status = getattr(
                    cuda_backend,
                    "mem_efficient_sdp_enabled",
                    None,
                )
                self._flash_sdp_enabled = bool(flash_status()) if flash_status is not None else None
                self._memory_efficient_sdp_enabled = (
                    bool(memory_status()) if memory_status is not None else None
                )
                math_status = getattr(cuda_backend, "math_sdp_enabled", None)
                self._math_sdp_enabled = bool(math_status()) if math_status is not None else None
            self.prepare_optimizer()
        except Exception as exc:
            self._restore()
            raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
                "PROFILED_SUPERVISED_EXECUTION_DETERMINISM_SETUP_FAILED"
            ) from exc
        return self

    def _restore(self) -> None:
        if self.restored:
            return
        torch = self._torch
        if self._python_state is not None:
            random.setstate(self._python_state)
        if self._cpu_state is not None:
            torch.random.set_rng_state(self._cpu_state)
        if self._cuda_states is not None:
            torch.cuda.set_rng_state_all(list(self._cuda_states))
        torch.use_deterministic_algorithms(
            self._deterministic_enabled,
            warn_only=self._deterministic_warn_only,
        )
        cudnn = getattr(torch.backends, "cudnn", None)
        if cudnn is not None and self._cudnn_deterministic is not None:
            cudnn.deterministic = self._cudnn_deterministic
            cudnn.benchmark = bool(self._cudnn_benchmark)
            cudnn.allow_tf32 = bool(self._cudnn_allow_tf32)
        cuda_matmul = getattr(getattr(torch.backends, "cuda", None), "matmul", None)
        if cuda_matmul is not None and self._cuda_matmul_allow_tf32 is not None:
            if self._cuda_matmul_fp32_precision is not None:
                cuda_matmul.fp32_precision = self._cuda_matmul_fp32_precision
            cuda_matmul.allow_tf32 = self._cuda_matmul_allow_tf32
        cudnn_conv = getattr(cudnn, "conv", None) if cudnn is not None else None
        if cudnn_conv is not None and self._cudnn_conv_fp32_precision is not None:
            cudnn_conv.fp32_precision = self._cudnn_conv_fp32_precision
        cuda_backend = getattr(torch.backends, "cuda", None)
        if cuda_backend is not None:
            if self._flash_sdp_enabled is not None:
                enable_flash = getattr(cuda_backend, "enable_flash_sdp", None)
                if enable_flash is not None:
                    enable_flash(self._flash_sdp_enabled)
            if self._memory_efficient_sdp_enabled is not None:
                enable_memory = getattr(
                    cuda_backend,
                    "enable_mem_efficient_sdp",
                    None,
                )
                if enable_memory is not None:
                    enable_memory(self._memory_efficient_sdp_enabled)
            if self._math_sdp_enabled is not None:
                enable_math = getattr(cuda_backend, "enable_math_sdp", None)
                if enable_math is not None:
                    enable_math(self._math_sdp_enabled)
        if self._float32_matmul_precision is not None:
            torch.set_float32_matmul_precision(self._float32_matmul_precision)
        if self._thread_count is not None:
            torch.set_num_threads(self._thread_count)
        self.restored = True

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> bool:
        try:
            self._restore()
        except Exception as restore_exc:
            raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
                "PROFILED_SUPERVISED_EXECUTION_RNG_RESTORE_FAILED"
            ) from restore_exc
        return False


@dataclass(frozen=True, slots=True)
class _FactorySeal:
    mac: bytes = field(repr=False)


def _seal_bytes(material: Mapping[str, object], *, owner_ids: tuple[int, ...]) -> bytes:
    return hmac.new(
        _FACTORY_SEAL_KEY,
        _FACTORY_SEAL_DOMAIN
        + _canonical_json_bytes(
            {"material": dict(material), "owner_ids": list(owner_ids)},
            reason="PROFILED_SUPERVISED_EXECUTION_FACTORY_SEAL_ENCODING_FAILED",
        ),
        hashlib.sha256,
    ).digest()


def _nonparameter_model_state_artifact(model: V2HybridPolicyModel) -> bytes:
    if type(model) is not V2HybridPolicyModel:
        _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_OWNER_INVALID")
    snapshot = model._mutable_state_snapshot(  # noqa: SLF001
        include_model_parameters=False,
    )
    fallback_weights = snapshot.get("fallback_weights")
    calibration = snapshot.get("confidence_calibration_state")
    if (
        type(fallback_weights) is not tuple
        or not fallback_weights
        or any(type(value) is not float or not math.isfinite(value) for value in fallback_weights)
        or type(calibration) is not dict
        or type(snapshot.get("torch_training")) is not bool
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_NONPARAMETER_MODEL_STATE_INVALID")
    return _canonical_json_bytes(
        {
            "schema_version": "profiled_nonparameter_model_state_v1",
            "model_id": model.model_id,
            "confidence_calibration_state": calibration,
            "fallback_weights": list(fallback_weights),
            "torch_training": snapshot["torch_training"],
        },
        reason="PROFILED_SUPERVISED_EXECUTION_NONPARAMETER_MODEL_STATE_INVALID",
    )


def _model_architecture_material(model: V2HybridPolicyModel) -> dict[str, object]:
    return {
        "model_id": model.model_id,
        "input_dim": model.input_dim,
        "seed": model.seed,
        "hidden_size": model.hidden_size,
        "residual_block_count": model.residual_block_count,
        "dropout": model.dropout,
        "attention_encoder_enabled": model.attention_encoder_enabled,
        "attention_heads": model.attention_heads,
        "temporal_encoder_enabled": model.temporal_encoder_enabled,
        "temporal_encoder": model.temporal_encoder,
        "temporal_seq_len": model.temporal_seq_len,
        "temporal_hidden": model.temporal_hidden,
        "temporal_proj_dim": model.temporal_proj_dim,
        "device": model.device,
        "cuda_active": model.cuda_active,
        "feature_abi_declaration": model.checkpoint_feature_abi_declaration,
    }


def _isolated_candidate_runtime(
    *,
    base_model: V2HybridPolicyModel,
    base_trainer: V2HybridPPOTrainer,
) -> tuple[V2HybridPolicyModel, V2HybridPPOTrainer]:
    base_state = base_model._mutable_state_snapshot()  # noqa: SLF001
    try:
        candidate_model = V2HybridPolicyModel(
            input_dim=base_model.input_dim,
            seed=base_model.seed,
            checkpoint_feature_abi_binding=(base_model.checkpoint_feature_abi_declaration),
        )
        if candidate_model is base_model or _model_architecture_material(
            candidate_model
        ) != _model_architecture_material(base_model):
            _fail("PROFILED_SUPERVISED_EXECUTION_ISOLATED_MODEL_ARCHITECTURE_MISMATCH")
        candidate_model._restore_mutable_state_snapshot(base_state)  # noqa: SLF001
        if model_parameter_fingerprint(candidate_model) != model_parameter_fingerprint(
            base_model
        ) or _nonparameter_model_state_artifact(
            candidate_model
        ) != _nonparameter_model_state_artifact(base_model):
            _fail("PROFILED_SUPERVISED_EXECUTION_ISOLATED_MODEL_STATE_MISMATCH")
        candidate_trainer = V2HybridPPOTrainer(
            model=candidate_model,
            clip_epsilon=base_trainer.clip_epsilon,
            entropy_coefficient=base_trainer.entropy_coefficient,
            supervised_entropy_bonus=base_trainer.supervised_entropy_bonus,
            weight_decay=base_trainer.weight_decay,
            learning_rate=base_trainer.learning_rate,
            behavior_receipt_archive_root=base_trainer.behavior_receipt_archive_root,
            sampling_plan_key_resolver=base_trainer.sampling_plan_key_resolver,
            training_observed_at=base_trainer.training_observed_at,
        )
    except AuthenticatedProfiledSupervisedOptimizerExecutionV1Error:
        raise
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_ISOLATED_RUNTIME_CREATION_FAILED"
        ) from exc
    if (
        candidate_trainer is base_trainer
        or candidate_trainer.model is not candidate_model
        or candidate_trainer.gamma != base_trainer.gamma
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_ISOLATED_TRAINER_CONFIG_MISMATCH")
    return candidate_model, candidate_trainer


def _ordered_row_inventory_sha256(
    rows: Sequence[AuthenticatedProfiledOptimizerCorpusRowV1],
    *,
    domain: str,
) -> str:
    return stable_sha256(
        {
            "domain": domain,
            "ordered_row_inventory_sha256s": [row.row_inventory_sha256 for row in rows],
        }
    )


def _binary_mask(values: Sequence[float], *, reason: str) -> tuple[int, ...]:
    if any(type(value) is not float or value not in {0.0, 1.0} for value in values):
        _fail(reason)
    return tuple(int(value) for value in values)


def _selected_action_net_bps(row: AuthenticatedProfiledOptimizerCorpusRowV1) -> float:
    value = row.supervised_target.signed_expected_move_after_cost_bps
    action = row.supervised_target.target_action
    selected_net = value if action == "long" else -value if action == "short" else 0.0
    if not math.isfinite(selected_net) or selected_net < 0.0:
        _fail("PROFILED_SUPERVISED_EXECUTION_SELECTED_ACTION_NET_INVALID")
    return float(selected_net)


def _training_example(
    row: AuthenticatedProfiledOptimizerCorpusRowV1,
    *,
    execution_authorization_sha256: str,
) -> TrainingExample:
    row.__post_init__()
    if len(row.model_input) != LOGICAL_MODEL_INPUT_COUNT:
        _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_INPUT_DIMENSION_INVALID")
    width = LOGICAL_MODEL_FEATURE_COUNT
    values = tuple(row.model_input[:width])
    missing = _binary_mask(
        row.model_input[width : 2 * width],
        reason="PROFILED_SUPERVISED_EXECUTION_MISSING_MASK_INVALID",
    )
    stale = _binary_mask(
        row.model_input[2 * width : 3 * width],
        reason="PROFILED_SUPERVISED_EXECUTION_STALE_MASK_INVALID",
    )
    availability = _binary_mask(
        row.model_input[3 * width :],
        reason="PROFILED_SUPERVISED_EXECUTION_AVAILABILITY_MASK_INVALID",
    )
    if any(stale):
        _fail("PROFILED_SUPERVISED_EXECUTION_STALE_SAMPLE_FORBIDDEN")
    if any(type(value) is not float or not math.isfinite(value) for value in values):
        _fail("PROFILED_SUPERVISED_EXECUTION_FEATURE_VALUE_INVALID")
    optional_missing_names: list[str] = []
    for index, missing_value in enumerate(missing):
        if not missing_value:
            continue
        slot = FEATURE_SOURCE_REGISTRY_V4.slots[index]
        if (
            slot.requirement_class != REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
            or availability[index] != 0
            or values[index] != 0.0
        ):
            _fail("PROFILED_SUPERVISED_EXECUTION_DIRTY_REQUIRED_SAMPLE_FORBIDDEN")
        optional_missing_names.append(slot.feature_name)

    feature_names = tuple(slot.feature_name for slot in FEATURE_SOURCE_REGISTRY_V4.slots)
    source_labels = tuple(slot.configured_source_label for slot in FEATURE_SOURCE_REGISTRY_V4.slots)
    tensor = FeatureTensorRecord(
        tensor_id=row.tensor_binding_sha256,
        symbol=row.symbol,
        timeframe=row.timeframe,
        feature_snapshot_id=row.sample_identity_sha256,
        values=values,
        missing_mask=missing,
        stale_mask=stale,
        source_availability=availability,
        feature_names=feature_names,
        source_labels=source_labels,
        missing_feature_names=tuple(optional_missing_names),
        stale_feature_names=(),
        data_coverage_percent=(100.0 * sum(availability) / len(availability)),
        source_availability_vector=availability,
        decision_time=row.decision_time,
        source_lineage_hash=row.logical_projection_sha256,
        temporal_rejection_reasons=(),
    )
    if tensor.model_vector != row.model_input:
        _fail("PROFILED_SUPERVISED_EXECUTION_TENSOR_RECONSTRUCTION_MISMATCH")

    selected_action_net_bps = _selected_action_net_bps(row)
    raw_move = row.supervised_target.signed_expected_move_after_cost_bps
    directional_outcome = "UP" if raw_move > 0.0 else "DOWN" if raw_move < 0.0 else "FLAT"
    trust_row: dict[str, Any] = {
        "row_source": "authenticated_profiled_optimizer_corpus_v1",
        "row_classification": ("MISSING_MASKED" if optional_missing_names else "TRAINABLE"),
        "learning_mode": "outcome_supervised",
        "update_lane": "AUTHENTICATED_PROFILED_OUTCOME_SUPERVISED",
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "accepted_for_training": True,
        "producer_trainer_consumable_literal_true": True,
        "reject_reasons": [],
        "quarantined": False,
        "decision_time": row.decision_time,
        "feature_cutoff": row.model_feature_cutoff,
        "available_at": row.decision_feature_available_at,
        "source_available_time": row.source_feature_available_at,
        "record_generated_at": row.training_record_generated_at,
        "trainer_sample_available_at": row.trainer_sample_available_at,
        "label_available_at": row.label_available_at,
        "outcome_available_at": row.label_available_at,
        "candle_closed_confirmed": True,
        "future_labels_not_in_feature_tensor": True,
        "profiled_sample_identity_sha256": row.sample_identity_sha256,
        "profiled_label_binding_sha256": row.label_binding_sha256,
        "profiled_tensor_binding_sha256": row.tensor_binding_sha256,
        "profiled_row_inventory_sha256": row.row_inventory_sha256,
        "profiled_optimizer_execution_authorization_sha256": (execution_authorization_sha256),
        "optimizer_admission_authorized": True,
        "optimizer_execution_authorized": True,
        "optional_event_dependent_missing_mask_verified": bool(optional_missing_names),
        "missing_feature_names": optional_missing_names,
        "behavior_receipt_bound": False,
        "ppo_behavior_policy_terms_enabled": False,
        "outcome_targets": {
            "realized_net_pnl_bps": selected_action_net_bps,
            "directional_outcome": directional_outcome,
            "selected_action": row.supervised_target.target_action,
            "action_was_profitable": bool(selected_action_net_bps > 0.0),
        },
        "realized_after_cost_reward": selected_action_net_bps / 100.0,
        "uses_expected_move_as_realized_reward": False,
    }
    example = TrainingExample(
        symbol=row.symbol,
        timeframe=row.timeframe,
        tensor=tensor,
        label_action_index=row.supervised_target.action_index,
        label_expected_move_after_cost_bps=raw_move,
        payload_keys=(
            f"profiled_sample:{row.sample_identity_sha256}",
            f"profiled_label:{row.label_binding_sha256}",
        ),
        row_classification=("MISSING_MASKED" if optional_missing_names else "TRAINABLE"),
        trust_row=trust_row,
        decision_time=row.decision_time,
        label_available_at=row.label_available_at,
        behavior_action_index=None,
        behavior_action=None,
    )
    if (
        example.label_timing_valid is not True
        or example.decision_time != row.decision_time
        or example.label_available_at != row.label_available_at
        or example.behavior_action_index is not None
        or example.behavior_action is not None
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_TRAINING_EXAMPLE_INVALID")
    return example


def _local_research_training_example(
    *,
    candidate: ProfiledTrainingObservationExampleV1,
    validation: LocallyValidatedProfiledResearchExampleV1,
    execution_authorization_sha256: str,
) -> TrainingExample:
    """Adapt a validated manifest row to the public outcome-supervised API."""

    source = candidate.training_example
    tensor = source.tensor
    if (
        validation.ordinal != candidate.ordinal
        or validation.sample_identity_sha256 != candidate.sample_identity_sha256
        or validation.label_binding_sha256 != candidate.label_binding_sha256
        or validation.tensor_binding_sha256 != candidate.tensor_binding_sha256
        or len(tensor.model_vector) != LOGICAL_MODEL_INPUT_COUNT
        or len(tensor.values) != LOGICAL_MODEL_FEATURE_COUNT
        or any(tensor.stale_mask)
        or source.behavior_action_index is not None
        or source.behavior_action is not None
    ):
        _fail("PROFILED_LOCAL_RESEARCH_TRAINING_EXAMPLE_SOURCE_INVALID")
    optional_missing_names: list[str] = []
    for index, missing_value in enumerate(tensor.missing_mask):
        if not missing_value:
            continue
        slot = FEATURE_SOURCE_REGISTRY_V4.slots[index]
        if (
            slot.requirement_class != REQUIREMENT_OPTIONAL_EVENT_DEPENDENT
            or tensor.source_availability_vector[index] != 0
            or tensor.values[index] != 0.0
        ):
            _fail("PROFILED_LOCAL_RESEARCH_DIRTY_REQUIRED_SAMPLE_FORBIDDEN")
        optional_missing_names.append(slot.feature_name)
    action_index = source.label_action_index
    raw_move = source.label_expected_move_after_cost_bps
    if (
        type(action_index) is not int
        or action_index not in {0, 1, 2}
        or type(raw_move) is not float
        or not math.isfinite(raw_move)
    ):
        _fail("PROFILED_LOCAL_RESEARCH_OUTCOME_TARGET_INVALID")
    selected_action = {0: "hold", 1: "long", 2: "short"}[action_index]
    selected_action_net_bps = (
        raw_move if action_index == 1 else -raw_move if action_index == 2 else 0.0
    )
    if not math.isfinite(selected_action_net_bps) or selected_action_net_bps < 0.0:
        _fail("PROFILED_LOCAL_RESEARCH_SELECTED_ACTION_NET_INVALID")
    directional_outcome = (
        "UP" if raw_move > 0.0 else "DOWN" if raw_move < 0.0 else "FLAT"
    )
    row_inventory_sha256 = stable_sha256(
        {
            "domain": "v2/native-trainer/local-profiled-research-row/v1",
            "validation": _local_research_validation_material(validation),
            "execution_authorization_sha256": execution_authorization_sha256,
        }
    )
    trust_row: dict[str, Any] = {
        "row_source": "locally_authenticated_profiled_research_corpus_v1",
        "row_classification": (
            "MISSING_MASKED" if optional_missing_names else "TRAINABLE"
        ),
        "learning_mode": "outcome_supervised",
        "update_lane": "LOCAL_PROFILED_RESEARCH_OUTCOME_SUPERVISED_NON_PROMOTABLE",
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "accepted_for_training": True,
        "producer_trainer_consumable_literal_true": True,
        "reject_reasons": [],
        "quarantined": False,
        "decision_time": validation.decision_time,
        "feature_cutoff": validation.model_feature_cutoff,
        "available_at": validation.decision_feature_available_at,
        "source_available_time": validation.source_feature_available_at,
        "feature_generated_at": validation.feature_generated_at,
        "record_generated_at": validation.training_record_generated_at,
        "trainer_sample_available_at": validation.trainer_sample_available_at,
        "label_available_at": validation.label_available_at,
        "outcome_available_at": validation.label_available_at,
        "candle_closed_confirmed": True,
        "future_labels_not_in_feature_tensor": True,
        "profiled_sample_identity_sha256": validation.sample_identity_sha256,
        "profiled_label_binding_sha256": validation.label_binding_sha256,
        "profiled_tensor_binding_sha256": validation.tensor_binding_sha256,
        "profiled_row_inventory_sha256": row_inventory_sha256,
        "profiled_optimizer_execution_authorization_sha256": (
            execution_authorization_sha256
        ),
        "optimizer_admission_authorized": False,
        "optimizer_execution_authorized": True,
        "local_research_non_promotable": True,
        "external_witness_verified": False,
        "optional_event_dependent_missing_mask_verified": bool(
            optional_missing_names
        ),
        "missing_feature_names": optional_missing_names,
        "behavior_receipt_bound": False,
        "ppo_behavior_policy_terms_enabled": False,
        "outcome_targets": {
            "realized_net_pnl_bps": selected_action_net_bps,
            "directional_outcome": directional_outcome,
            "selected_action": selected_action,
            "action_was_profitable": bool(selected_action_net_bps > 0.0),
        },
        "realized_after_cost_reward": selected_action_net_bps / 100.0,
        "uses_expected_move_as_realized_reward": False,
    }
    example = TrainingExample(
        symbol=source.symbol,
        timeframe=source.timeframe,
        tensor=tensor,
        label_action_index=action_index,
        label_expected_move_after_cost_bps=raw_move,
        payload_keys=(
            f"profiled_sample:{validation.sample_identity_sha256}",
            f"profiled_label:{validation.label_binding_sha256}",
        ),
        row_classification=(
            "MISSING_MASKED" if optional_missing_names else "TRAINABLE"
        ),
        trust_row=trust_row,
        decision_time=validation.decision_time,
        label_available_at=validation.label_available_at,
        behavior_action_index=None,
        behavior_action=None,
    )
    if example.label_timing_valid is not True:
        _fail("PROFILED_LOCAL_RESEARCH_TRAINING_EXAMPLE_INVALID")
    return example


def _state_tensors(
    model: V2HybridPolicyModel,
    *,
    resource_budget_bytes: int,
) -> tuple[tuple[str, str, tuple[int, ...], bytes], ...]:
    if sys.byteorder != "little":
        _fail("PROFILED_SUPERVISED_EXECUTION_LITTLE_ENDIAN_HOST_REQUIRED")
    if not model.torch_available or model.net is None or model.torch is None:
        _fail("PROFILED_SUPERVISED_EXECUTION_TORCH_MODEL_REQUIRED")
    torch = model.torch
    result: list[tuple[str, str, tuple[int, ...], bytes]] = []
    try:
        items = sorted(model.net.state_dict().items())
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_UNAVAILABLE"
        ) from exc
    if not items:
        _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_EMPTY")
    accounted_payload_bytes = 0
    for name, tensor in items:
        dtype = str(tensor.dtype).removeprefix("torch.")
        if dtype not in _SUPPORTED_TENSOR_DTYPES:
            _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_DTYPE_UNSUPPORTED")
        tensor_payload_bytes = int(tensor.numel()) * int(tensor.element_size())
        accounted_payload_bytes += tensor_payload_bytes
        if accounted_payload_bytes > resource_budget_bytes:
            _fail("PROFILED_SUPERVISED_EXECUTION_STATE_BUDGET_EXCEEDED")
        detached = tensor.detach().cpu().contiguous()
        if dtype in _FLOAT_TENSOR_DTYPES and not bool(torch.isfinite(detached).all().item()):
            _fail("PROFILED_SUPERVISED_EXECUTION_NONFINITE_MODEL_STATE")
        if detached.numel() <= 0:
            _fail("PROFILED_SUPERVISED_EXECUTION_EMPTY_MODEL_TENSOR_FORBIDDEN")
        try:
            payload = detached.reshape(-1).view(torch.uint8).numpy().tobytes(order="C")
        except Exception as exc:
            raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
                "PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_ENCODING_FAILED"
            ) from exc
        result.append((str(name), dtype, tuple(int(value) for value in detached.shape), payload))
    return tuple(result)


def _model_state_accounted_bytes(model: V2HybridPolicyModel) -> tuple[int, int]:
    if not model.torch_available or model.net is None:
        _fail("PROFILED_SUPERVISED_EXECUTION_TORCH_MODEL_REQUIRED")
    try:
        items = tuple(sorted(model.net.state_dict().items()))
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_UNAVAILABLE"
        ) from exc
    if not items:
        _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_EMPTY")
    accounted = len(items) * PROFILED_STATE_ITEM_ACCOUNTING_BYTES
    payload_bytes = 0
    for name, tensor in items:
        dtype = str(tensor.dtype).removeprefix("torch.")
        if dtype not in _SUPPORTED_TENSOR_DTYPES or tensor.numel() <= 0:
            _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_INVALID")
        payload_count = int(tensor.numel()) * int(tensor.element_size())
        payload_bytes += payload_count
        accounted += (
            len(str(name).encode("ascii", errors="strict"))
            + len(dtype)
            + len(tuple(tensor.shape)) * 32
            + payload_count
        )
    return accounted, payload_bytes


def _authorize_exact_training_example(
    *,
    example: TrainingExample,
    expected_example: TrainingExample,
    row: AuthenticatedProfiledOptimizerCorpusRowV1,
    execution_authorization_sha256: str,
) -> str:
    row.__post_init__()
    if (
        example is not expected_example
        or example.tensor.model_vector != row.model_input
        or example.tensor.tensor_id != row.tensor_binding_sha256
        or example.tensor.feature_snapshot_id != row.sample_identity_sha256
        or example.label_action_index != row.supervised_target.action_index
        or example.label_expected_move_after_cost_bps
        != row.supervised_target.signed_expected_move_after_cost_bps
        or example.decision_time != row.decision_time
        or example.label_available_at != row.label_available_at
        or example.label_timing_valid is not True
        or example.behavior_action_index is not None
        or example.behavior_action is not None
        or type(example.trust_row) is not dict
        or example.trust_row.get("profiled_row_inventory_sha256") != row.row_inventory_sha256
        or example.trust_row.get("profiled_optimizer_execution_authorization_sha256")
        != execution_authorization_sha256
        or example.trust_row.get("ppo_behavior_policy_terms_enabled") is not False
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_EXAMPLE_REAUTHORIZATION_FAILED")
    return row.row_inventory_sha256


def _project_root() -> Path:
    source = Path(__file__).resolve()
    for candidate in source.parents:
        if (candidate / ".git").exists() and (
            candidate / "v2/backend/app/services/native_trainer"
        ).is_dir():
            return candidate
    _fail("PROFILED_SUPERVISED_EXECUTION_PROJECT_ROOT_UNAVAILABLE")


def _stable_source_file(path: Path) -> bytes:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
            _fail("PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_SOURCE_FILE_INVALID")
        payload = path.read_bytes()
        after = path.lstat()
    except AuthenticatedProfiledSupervisedOptimizerExecutionV1Error:
        raise
    except OSError as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_ARTIFACT_UNAVAILABLE"
        ) from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(payload) != before.st_size:
        _fail("PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_SOURCE_CHANGED_DURING_READ")
    return payload


def _source_artifact() -> bytes:
    """Bind every Python source file in the deployed application tree.

    A hand-maintained import list can silently omit a behavior-changing helper.
    The complete application source manifest plus the verified Git release below
    makes that class of omission impossible without changing the execution
    identity. Source bytes remain recoverable from the pinned commit, so the
    checkpoint stores their deterministic digest manifest rather than duplicating
    the full source tree.
    """

    project_root = _project_root()
    source_root = project_root / "v2/backend/app"
    descriptors: list[dict[str, object]] = []
    total_source_bytes = 0
    try:
        paths = tuple(sorted(source_root.rglob("*.py")))
    except OSError as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_ARTIFACT_UNAVAILABLE"
        ) from exc
    if not paths:
        _fail("PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_SOURCE_CLOSURE_EMPTY")
    for path in paths:
        payload = _stable_source_file(path)
        try:
            relative_path = path.relative_to(project_root).as_posix()
        except ValueError:
            _fail("PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_SOURCE_PATH_INVALID")
        total_source_bytes += len(payload)
        if total_source_bytes > MAX_PROFILED_CHECKPOINT_SERIALIZATION_BYTES:
            _fail("PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_SOURCE_CLOSURE_TOO_LARGE")
        descriptors.append(
            {
                "relative_path": relative_path,
                "byte_count": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return _canonical_json_bytes(
        {
            "schema_version": "profiled_supervised_optimizer_implementation_artifact_v2",
            "closure_scope": "ALL_PYTHON_SOURCE_UNDER_V2_BACKEND_APP",
            "ordered_source_files": descriptors,
            "source_file_count": len(descriptors),
            "total_source_bytes": total_source_bytes,
        },
        reason="PROFILED_SUPERVISED_EXECUTION_IMPLEMENTATION_ARTIFACT_INVALID",
    )


def _git_command(project_root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment.update({"GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C", "LANG": "C"})
    try:
        return subprocess.run(  # noqa: S603
            ("/usr/bin/git", "-C", str(project_root), *arguments),
            check=False,
            capture_output=True,
            env=environment,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_GIT_RELEASE_VERIFICATION_FAILED"
        ) from exc


def _verify_git_release_at_root(*, project_root: Path, expected_sha: str) -> str:
    if (
        not isinstance(project_root, Path)
        or not project_root.is_absolute()
        or len(expected_sha) != 40
        or any(character not in "0123456789abcdef" for character in expected_sha)
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_PINNED_CODE_RELEASE_REQUIRED")
    root_result = _git_command(project_root, "rev-parse", "--show-toplevel")
    head_result = _git_command(project_root, "rev-parse", "--verify", "HEAD^{commit}")
    if root_result.returncode != 0 or head_result.returncode != 0:
        _fail("PROFILED_SUPERVISED_EXECUTION_GIT_RELEASE_VERIFICATION_FAILED")
    try:
        observed_root = Path(root_result.stdout.decode("utf-8").strip()).resolve()
        observed_head = head_result.stdout.decode("ascii").strip()
    except (UnicodeError, OSError):
        _fail("PROFILED_SUPERVISED_EXECUTION_GIT_RELEASE_VERIFICATION_FAILED")
    if observed_root != project_root.resolve() or not hmac.compare_digest(
        observed_head,
        expected_sha,
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_PINNED_CODE_RELEASE_MISMATCH")
    status_result = _git_command(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        "v2/backend/app",
    )
    if status_result.returncode != 0:
        _fail("PROFILED_SUPERVISED_EXECUTION_GIT_RELEASE_VERIFICATION_FAILED")
    if status_result.stdout:
        _fail("PROFILED_SUPERVISED_EXECUTION_DEPLOYED_APPLICATION_TREE_DIRTY")
    return expected_sha


def _code_release_sha() -> str:
    value = os.getenv("AI_BOT_CODE_SHA", "")
    return _verify_git_release_at_root(project_root=_project_root(), expected_sha=value)


def _deterministic_seed(
    *,
    corpus_contract_sha256: str,
    execution_authorization_sha256: str,
    base_model_parameter_fingerprint: str,
    implementation_artifact_sha256: str,
    code_release_sha: str,
) -> tuple[int, str]:
    material_sha256 = stable_sha256(
        {
            "domain": "v2/native-trainer/profiled-supervised-deterministic-seed/v1",
            "corpus_contract_sha256": corpus_contract_sha256,
            "execution_authorization_sha256": execution_authorization_sha256,
            "base_model_parameter_fingerprint": base_model_parameter_fingerprint,
            "implementation_artifact_sha256": implementation_artifact_sha256,
            "code_release_sha": code_release_sha,
        }
    )
    return int(material_sha256[:16], 16) % (2**63), material_sha256


def _configuration_artifact(
    *,
    trainer: V2HybridPPOTrainer,
    model: V2HybridPolicyModel,
    corpus: AuthenticatedProfiledOptimizerCorpusV1,
    validation_fraction: float,
    split_metrics: Mapping[str, object],
    optimizer_input_byte_budget: int,
    optimizer_input_accounted_bytes: int,
    state_resource_budget_bytes: int,
    checkpoint_serialization_byte_budget: int,
    deterministic_seed_material_sha256: str,
    code_release_sha: str,
) -> bytes:
    material = {
        "schema_version": "profiled_supervised_optimizer_configuration_v1",
        "objective_lane": PROFILED_SUPERVISED_OPTIMIZER_OBJECTIVE_LANE,
        "parameter_mutation_contract": (
            "ADAMW_GRADIENT_STEP_PLUS_DECLARED_POST_STEP_RECOVERY_BIAS_NUDGES_"
            "AND_CONFIDENCE_CALIBRATION"
        ),
        "adamw_optimizer_steps": 1,
        "post_step_parameter_mutations_reported_in_result_artifact": True,
        "optimizer_state_persisted": False,
        "optimizer_state_persistence_reason": (
            "ADAMW_CREATED_PER_CALL_WITH_NO_DURABLE_OPTIMIZER_STATE_CONTRACT"
        ),
        "complete_authenticated_corpus_considered": True,
        "admitted_example_count": corpus.manifest_admitted_example_count,
        "validation_fraction_requested": validation_fraction,
        "chronological_label_purged_validation_performed": (
            split_metrics.get("validation_split_pit_safe") is True
        ),
        "validation_split_reason": split_metrics.get("validation_split_reason"),
        "validation_split_actual_training_rows": split_metrics.get(
            "validation_split_actual_training_rows"
        ),
        "validation_split_actual_validation_rows": split_metrics.get(
            "validation_split_actual_validation_rows"
        ),
        "optimizer_input_byte_budget": optimizer_input_byte_budget,
        "optimizer_input_accounted_bytes": optimizer_input_accounted_bytes,
        "state_resource_budget_bytes": state_resource_budget_bytes,
        "checkpoint_serialization_byte_budget": (checkpoint_serialization_byte_budget),
        "deterministic_seed_material_sha256": deterministic_seed_material_sha256,
        "torch_deterministic_algorithms_enforced": True,
        "process_rng_state_restored_after_execution": True,
        "code_release_sha": code_release_sha,
        "learning_rate": trainer.learning_rate,
        "weight_decay": trainer.weight_decay,
        "clip_epsilon": trainer.clip_epsilon,
        "entropy_coefficient": trainer.entropy_coefficient,
        "supervised_entropy_bonus": trainer.supervised_entropy_bonus,
        "gamma": trainer.gamma,
        "model_id": model.model_id,
        "model_input_dim": model.input_dim,
        "model_hidden_size": model.hidden_size,
        "model_residual_block_count": model.residual_block_count,
        "model_dropout": model.dropout,
        "attention_encoder_enabled": model.attention_encoder_enabled,
        "temporal_encoder_enabled": model.temporal_encoder_enabled,
        "temporal_encoder": model.temporal_encoder,
        "temporal_seq_len": model.temporal_seq_len,
        "base_checkpoint_id": None,
        "base_checkpoint_weight_sha256": None,
        "base_checkpoint_lineage_deferred_to_verified_publication_boundary": True,
        "feature_abi_binding_sha256": CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256,
        "behavior_receipt_bound": False,
        "ppo_behavior_policy_terms_enabled": False,
        "checkpoint_write_authorized": False,
        "model_write_authorized": False,
        "prediction_authorized": False,
        "paper_trading_authorized": False,
        "live_execution_authorized": False,
    }
    return _canonical_json_bytes(
        material,
        reason="PROFILED_SUPERVISED_EXECUTION_CONFIGURATION_ARTIFACT_INVALID",
    )


def _environment_artifact(
    *,
    model: V2HybridPolicyModel,
    code_release_sha: str,
    deterministic_seed_material_sha256: str,
    base_nonparameter_model_state_sha256: str,
    candidate_nonparameter_model_state_artifact_json_bytes: bytes,
) -> bytes:
    torch = model.torch
    env = {key: os.environ[key] for key in _EXECUTION_ENVIRONMENT_KEYS if key in os.environ}
    material = {
        "schema_version": "profiled_supervised_optimizer_execution_environment_v1",
        "python_implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "platform_system": platform.system(),
        "platform_machine": platform.machine(),
        "torch_version": str(getattr(torch, "__version__", "unknown")),
        "device": model.device,
        "cuda_active": model.cuda_active,
        "cuda_claim_verified": bool(model.cuda_active and model.model_tensors_device_verified()),
        "ai_bot_code_sha": code_release_sha,
        "deterministic_seed_material_sha256": deterministic_seed_material_sha256,
        "torch_deterministic_algorithms_enforced_during_execution": True,
        "cuda_flash_sdp_disabled_during_execution": bool(model.cuda_active),
        "cuda_memory_efficient_sdp_disabled_during_execution": bool(model.cuda_active),
        "cuda_math_sdp_enabled_during_execution": bool(model.cuda_active),
        "process_rng_state_restored_after_execution": True,
        "base_nonparameter_model_state_sha256": (base_nonparameter_model_state_sha256),
        "candidate_nonparameter_model_state": json.loads(
            candidate_nonparameter_model_state_artifact_json_bytes
        ),
        "trainer_environment_allowlist": list(_EXECUTION_ENVIRONMENT_KEYS),
        "trainer_environment_overrides": env,
    }
    return _canonical_json_bytes(
        material,
        reason="PROFILED_SUPERVISED_EXECUTION_ENVIRONMENT_ARTIFACT_INVALID",
    )


def _training_result_artifact(result: PPOTrainingResult) -> bytes:
    metrics = result.metrics
    material = {
        "schema_version": "profiled_supervised_optimizer_training_result_v1",
        "status": result.status,
        "device": result.device,
        "cuda_active": result.cuda_active,
        "cuda_claim_verified": result.cuda_claim_verified,
        "gpu_name": result.gpu_name,
        "vram_allocated_mb": result.vram_allocated_mb,
        "batch_size": result.batch_size,
        "training_steps": result.training_steps,
        "train_rows": result.train_rows,
        "validation_rows": result.validation_rows,
        "loss_before": result.loss_before,
        "loss_after": result.loss_after,
        "action_distribution": result.action_distribution,
        "learning_update_lane": metrics.get("learning_update_lane"),
        "optimizer_steps_this_cycle": metrics.get("optimizer_steps_this_cycle"),
        "parameter_hash_before": metrics.get("parameter_hash_before"),
        "parameter_hash_after": metrics.get("parameter_hash_after"),
        "weight_delta_norm": metrics.get("weight_delta_norm"),
        "ppo_objective_used": metrics.get("ppo_objective_used"),
        "outcome_supervised_update_used": metrics.get("outcome_supervised_update_used"),
        "ppo_clipped_surrogate_rows": metrics.get("ppo_clipped_surrogate_rows"),
        "outcome_supervised_batch_rows": metrics.get("outcome_supervised_batch_rows"),
        "tensor_nan_inf_count": metrics.get("tensor_nan_inf_count"),
        "optimizer_anomaly_counters_complete": metrics.get("optimizer_anomaly_counters_complete"),
        "anomaly_free_optimizer_cycle": metrics.get("anomaly_free_optimizer_cycle"),
        "training_cycle_rolled_back": metrics.get("training_cycle_rolled_back"),
        "training_cycle_abort_reason": metrics.get("training_cycle_abort_reason"),
        "validation_split_pit_safe": metrics.get("validation_split_pit_safe"),
        "validation_split_reason": metrics.get("validation_split_reason"),
        "feedback_head_nudge_applied": metrics.get("feedback_head_nudge_applied"),
        "expected_move_head_saturation_recovery_applied": metrics.get(
            "expected_move_head_saturation_recovery_applied"
        ),
        "expected_move_head_saturation_recovery_reason": metrics.get(
            "expected_move_head_saturation_recovery_reason"
        ),
        "confidence_calibration_fitted": metrics.get("confidence_calibration_fitted"),
        "confidence_calibration_reason": metrics.get("confidence_calibration_reason"),
        "confidence_calibration_row_digest": metrics.get("confidence_calibration_row_digest"),
        "confidence_calibration_model_parameter_fingerprint": metrics.get(
            "confidence_calibration_model_parameter_fingerprint"
        ),
        "confidence_calibration_checkpoint_bound": metrics.get(
            "confidence_calibration_checkpoint_bound"
        ),
        "confidence_calibration_external_state_used": metrics.get(
            "confidence_calibration_external_state_used"
        ),
    }
    return _canonical_json_bytes(
        material,
        reason="PROFILED_SUPERVISED_EXECUTION_TRAINING_RESULT_ARTIFACT_INVALID",
    )


def _execution_material(values: Mapping[str, object]) -> dict[str, object]:
    names = (
        "schema_version",
        "status",
        "execution_idempotency_key",
        "manifest_id",
        "completion_event_sha256",
        "corpus_contract_sha256",
        "execution_authorization_inventory_equality_sha256",
        "base_checkpoint_id",
        "base_checkpoint_weight_sha256",
        "model_id",
        "model_input_dim",
        "base_model_parameter_fingerprint",
        "candidate_model_parameter_fingerprint",
        "base_nonparameter_model_state_sha256",
        "candidate_nonparameter_model_state_sha256",
        "code_release_sha",
        "deterministic_seed_material_sha256",
        "training_observed_at",
        "before_input_inventory_verified_at",
        "before_state_captured_at",
        "optimizer_started_at",
        "optimizer_completed_at",
        "after_state_captured_at",
        "after_input_inventory_verified_at",
        "checkpoint_created_at",
        "admitted_example_count",
        "optimizer_training_row_count",
        "validation_row_count",
        "ordered_optimizer_training_rows_sha256",
        "ordered_validation_rows_sha256",
        "optimizer_steps_requested",
        "optimizer_steps_completed",
        "learning_mode",
        "device",
        "cuda_active",
        "cuda_claim_verified",
        "loss_before",
        "loss_after",
        "weight_delta_norm",
        "before_state_snapshot_sha256",
        "after_state_snapshot_sha256",
        "checkpoint_inventory_sha256",
        "checkpoint_bytes_sha256",
        "checkpoint_byte_count",
        "optimizer_implementation_artifact_sha256",
        "optimizer_configuration_artifact_sha256",
        "execution_environment_artifact_sha256",
        "training_result_artifact_sha256",
        "supervised_optimizer_input_authorized",
        "supervised_optimizer_execution_authorized",
        "optimizer_execution_authorized",
        "optimizer_execution_completed",
        "optimizer_execution_independently_observed",
        "base_checkpoint_lineage_deferred",
        "isolated_candidate_model_created",
        "base_model_unchanged",
        "process_rng_state_restored",
        "deterministic_algorithms_enforced",
        "public_authenticated_trainer_boundary_used",
        "optimizer_state_persisted",
        "corpus_revalidated_after_optimization",
        "model_state_changed",
        "anomaly_free_optimizer_cycle",
        "in_memory_checkpoint_candidate_created",
        "durable_execution_receipt_written",
        *_AUTHORITY_FALSE,
    )
    return {name: values[name] for name in names}


@dataclass(frozen=True, slots=True)
class AuthenticatedProfiledSupervisedOptimizerExecutionV1:
    schema_version: str
    status: str
    execution_idempotency_key: str
    manifest_id: str
    completion_event_sha256: str
    corpus_contract_sha256: str
    execution_authorization_inventory_equality_sha256: str
    base_checkpoint_id: str | None
    base_checkpoint_weight_sha256: str | None
    model_id: str
    model_input_dim: int
    base_model_parameter_fingerprint: str
    candidate_model_parameter_fingerprint: str
    base_nonparameter_model_state_sha256: str
    candidate_nonparameter_model_state_artifact_json_bytes: bytes = field(repr=False)
    candidate_nonparameter_model_state_sha256: str
    code_release_sha: str
    deterministic_seed_material_sha256: str
    training_observed_at: str
    before_input_inventory_verified_at: str
    before_state_captured_at: str
    optimizer_started_at: str
    optimizer_completed_at: str
    after_state_captured_at: str
    after_input_inventory_verified_at: str
    checkpoint_created_at: str
    admitted_example_count: int
    optimizer_training_row_count: int
    validation_row_count: int
    ordered_optimizer_training_rows_sha256: str
    ordered_validation_rows_sha256: str
    optimizer_steps_requested: int
    optimizer_steps_completed: int
    learning_mode: str
    device: str
    cuda_active: bool
    cuda_claim_verified: bool
    loss_before: float
    loss_after: float
    weight_delta_norm: float
    before_state_snapshot_sha256: str
    after_state_snapshot_sha256: str
    checkpoint_inventory_sha256: str
    checkpoint_bytes_sha256: str
    checkpoint_byte_count: int
    optimizer_implementation_artifact_sha256: str
    optimizer_configuration_artifact_sha256: str
    execution_environment_artifact_sha256: str
    training_result_artifact_json_bytes: bytes = field(repr=False)
    training_result_artifact_sha256: str
    in_memory_execution_receipt_sha256: str
    supervised_optimizer_input_authorized: bool
    supervised_optimizer_execution_authorized: bool
    optimizer_execution_authorized: bool
    optimizer_execution_completed: bool
    optimizer_execution_independently_observed: bool
    base_checkpoint_lineage_deferred: bool
    isolated_candidate_model_created: bool
    base_model_unchanged: bool
    process_rng_state_restored: bool
    deterministic_algorithms_enforced: bool
    public_authenticated_trainer_boundary_used: bool
    optimizer_state_persisted: bool
    corpus_revalidated_after_optimization: bool
    model_state_changed: bool
    anomaly_free_optimizer_cycle: bool
    in_memory_checkpoint_candidate_created: bool
    durable_execution_receipt_written: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    serving_authorized: bool
    ppo_training_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    exchange_access_authorized: bool
    deployment_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    checkpoint_candidate: ProfiledSupervisedCheckpointInventoryV1 = field(
        repr=False,
        compare=False,
    )
    _base_model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _base_trainer_owner: V2HybridPPOTrainer = field(repr=False, compare=False)
    _candidate_model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _trainer_owner: V2HybridPPOTrainer = field(repr=False, compare=False)
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.checkpoint_candidate) is not ProfiledSupervisedCheckpointInventoryV1
            or type(self._base_model_owner) is not V2HybridPolicyModel
            or type(self._base_trainer_owner) is not V2HybridPPOTrainer
            or type(self._candidate_model_owner) is not V2HybridPolicyModel
            or type(self._trainer_owner) is not V2HybridPPOTrainer
            or self._base_trainer_owner.model is not self._base_model_owner
            or self._trainer_owner.model is not self._candidate_model_owner
            or self._base_model_owner is self._candidate_model_owner
            or self._base_trainer_owner is self._trainer_owner
        ):
            _fail("PROFILED_SUPERVISED_EXECUTION_OWNER_TYPES_INVALID")
        try:
            self.checkpoint_candidate.__post_init__()
        except ProfiledSupervisedCheckpointInventoryV1Error as exc:
            raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
                "PROFILED_SUPERVISED_EXECUTION_CHECKPOINT_REVALIDATION_FAILED",
                *exc.reasons,
            ) from exc
        material = _execution_material(
            {name: getattr(self, name) for name in _execution_material_names()}
        )
        expected_receipt = stable_sha256(material)
        checkpoint = self.checkpoint_candidate
        hashes = (
            self.execution_idempotency_key,
            self.manifest_id,
            self.completion_event_sha256,
            self.corpus_contract_sha256,
            self.execution_authorization_inventory_equality_sha256,
            self.base_model_parameter_fingerprint,
            self.candidate_model_parameter_fingerprint,
            self.base_nonparameter_model_state_sha256,
            self.candidate_nonparameter_model_state_sha256,
            self.deterministic_seed_material_sha256,
            self.ordered_optimizer_training_rows_sha256,
            self.ordered_validation_rows_sha256,
            self.before_state_snapshot_sha256,
            self.after_state_snapshot_sha256,
            self.checkpoint_inventory_sha256,
            self.checkpoint_bytes_sha256,
            self.optimizer_implementation_artifact_sha256,
            self.optimizer_configuration_artifact_sha256,
            self.execution_environment_artifact_sha256,
            self.training_result_artifact_sha256,
            self.in_memory_execution_receipt_sha256,
        )
        clocks = tuple(
            _clock(value, reason="PROFILED_SUPERVISED_EXECUTION_RESULT_CLOCK_INVALID")
            for value in (
                checkpoint.witness_accepted_at,
                self.before_input_inventory_verified_at,
                self.before_state_captured_at,
                self.optimizer_started_at,
                self.optimizer_completed_at,
                self.after_state_captured_at,
                self.after_input_inventory_verified_at,
                self.checkpoint_created_at,
            )
        )
        training_observed_clock = _clock(
            self.training_observed_at,
            reason="PROFILED_SUPERVISED_EXECUTION_RESULT_CLOCK_INVALID",
        )
        if (
            self._construction_token is not _RESULT_TOKEN
            or self.schema_version
            != AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION
            or self.status != AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_STATUS
            or not all(_valid_sha256(value) for value in hashes)
            or self.base_checkpoint_id is not None
            or self.base_checkpoint_weight_sha256 is not None
            or len(self.code_release_sha) != 40
            or any(character not in "0123456789abcdef" for character in self.code_release_sha)
            or self.model_id != self._candidate_model_owner.model_id
            or self.model_input_dim != CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
            or self.model_input_dim != self._candidate_model_owner.input_dim
            or model_parameter_fingerprint(self._candidate_model_owner)
            != self.candidate_model_parameter_fingerprint
            or model_parameter_fingerprint(self._base_model_owner)
            != self.base_model_parameter_fingerprint
            or type(self.candidate_nonparameter_model_state_artifact_json_bytes) is not bytes
            or not self.candidate_nonparameter_model_state_artifact_json_bytes
            or hashlib.sha256(
                self.candidate_nonparameter_model_state_artifact_json_bytes
            ).hexdigest()
            != self.candidate_nonparameter_model_state_sha256
            or _nonparameter_model_state_artifact(self._candidate_model_owner)
            != self.candidate_nonparameter_model_state_artifact_json_bytes
            or hashlib.sha256(
                _nonparameter_model_state_artifact(self._base_model_owner)
            ).hexdigest()
            != self.base_nonparameter_model_state_sha256
            or self.manifest_id != checkpoint.manifest_id
            or self.completion_event_sha256 != checkpoint.completion_event_sha256
            or self.corpus_contract_sha256 != checkpoint.corpus_contract_sha256
            or self.execution_authorization_inventory_equality_sha256
            != checkpoint.execution_authorization_inventory_equality_sha256
            or self.before_state_snapshot_sha256 != checkpoint.before_state.state_snapshot_sha256
            or self.after_state_snapshot_sha256 != checkpoint.after_state.state_snapshot_sha256
            or self.checkpoint_inventory_sha256 != checkpoint.checkpoint_inventory_sha256
            or self.checkpoint_bytes_sha256 != checkpoint.checkpoint_bytes_sha256
            or self.checkpoint_byte_count != checkpoint.checkpoint_byte_count
            or self.optimizer_implementation_artifact_sha256
            != checkpoint.optimizer_implementation_artifact_sha256
            or self.optimizer_configuration_artifact_sha256
            != checkpoint.optimizer_configuration_artifact_sha256
            or self.execution_environment_artifact_sha256
            != checkpoint.execution_environment_artifact_sha256
            or type(self.training_result_artifact_json_bytes) is not bytes
            or not self.training_result_artifact_json_bytes
            or hashlib.sha256(self.training_result_artifact_json_bytes).hexdigest()
            != self.training_result_artifact_sha256
            or self.in_memory_execution_receipt_sha256 != expected_receipt
            or self.admitted_example_count <= 0
            or self.optimizer_training_row_count <= 0
            or self.optimizer_training_row_count + self.validation_row_count
            != self.admitted_example_count
            or self.optimizer_steps_requested != 1
            or self.optimizer_steps_completed != 1
            or self.learning_mode != "outcome_supervised"
            or not all(
                type(value) is float and math.isfinite(value)
                for value in (self.loss_before, self.loss_after, self.weight_delta_norm)
            )
            or self.weight_delta_norm <= 0.0
            or self.base_model_parameter_fingerprint == self.candidate_model_parameter_fingerprint
            or clocks != tuple(sorted(set(clocks)))
            or self.training_observed_at != self._trainer_owner.training_observed_at_iso
            or not clocks[0] < training_observed_clock < clocks[1]
            or any(
                value is not True
                for value in (
                    self.supervised_optimizer_input_authorized,
                    self.supervised_optimizer_execution_authorized,
                    self.optimizer_execution_authorized,
                    self.optimizer_execution_completed,
                    self.base_checkpoint_lineage_deferred,
                    self.isolated_candidate_model_created,
                    self.base_model_unchanged,
                    self.process_rng_state_restored,
                    self.deterministic_algorithms_enforced,
                    self.public_authenticated_trainer_boundary_used,
                    self.corpus_revalidated_after_optimization,
                    self.model_state_changed,
                    self.anomaly_free_optimizer_cycle,
                    self.in_memory_checkpoint_candidate_created,
                )
            )
            or self.optimizer_execution_independently_observed is not False
            or self.optimizer_state_persisted is not False
            or self.durable_execution_receipt_written is not False
            or any(
                getattr(self, name) is not expected for name, expected in _AUTHORITY_FALSE.items()
            )
            or type(self._factory_seal) is not _FactorySeal
            or not hmac.compare_digest(
                self._factory_seal.mac,
                _seal_bytes(
                    material,
                    owner_ids=(
                        id(self._base_model_owner),
                        id(self._base_trainer_owner),
                        id(self._candidate_model_owner),
                        id(self._trainer_owner),
                        id(self.checkpoint_candidate),
                    ),
                ),
            )
        ):
            _fail("PROFILED_SUPERVISED_EXECUTION_RESULT_INVALID")

    def __reduce_ex__(self, _protocol: int) -> NoReturn:
        _fail("PROFILED_SUPERVISED_EXECUTION_PICKLE_OR_COPY_FORBIDDEN")

    @property
    def candidate_model(self) -> V2HybridPolicyModel:
        """Return the isolated in-process model after revalidating its seal."""

        self.__post_init__()
        return self._candidate_model_owner


def _execution_material_names() -> tuple[str, ...]:
    return (
        "schema_version",
        "status",
        "execution_idempotency_key",
        "manifest_id",
        "completion_event_sha256",
        "corpus_contract_sha256",
        "execution_authorization_inventory_equality_sha256",
        "base_checkpoint_id",
        "base_checkpoint_weight_sha256",
        "model_id",
        "model_input_dim",
        "base_model_parameter_fingerprint",
        "candidate_model_parameter_fingerprint",
        "base_nonparameter_model_state_sha256",
        "candidate_nonparameter_model_state_sha256",
        "code_release_sha",
        "deterministic_seed_material_sha256",
        "training_observed_at",
        "before_input_inventory_verified_at",
        "before_state_captured_at",
        "optimizer_started_at",
        "optimizer_completed_at",
        "after_state_captured_at",
        "after_input_inventory_verified_at",
        "checkpoint_created_at",
        "admitted_example_count",
        "optimizer_training_row_count",
        "validation_row_count",
        "ordered_optimizer_training_rows_sha256",
        "ordered_validation_rows_sha256",
        "optimizer_steps_requested",
        "optimizer_steps_completed",
        "learning_mode",
        "device",
        "cuda_active",
        "cuda_claim_verified",
        "loss_before",
        "loss_after",
        "weight_delta_norm",
        "before_state_snapshot_sha256",
        "after_state_snapshot_sha256",
        "checkpoint_inventory_sha256",
        "checkpoint_bytes_sha256",
        "checkpoint_byte_count",
        "optimizer_implementation_artifact_sha256",
        "optimizer_configuration_artifact_sha256",
        "execution_environment_artifact_sha256",
        "training_result_artifact_sha256",
        "supervised_optimizer_input_authorized",
        "supervised_optimizer_execution_authorized",
        "optimizer_execution_authorized",
        "optimizer_execution_completed",
        "optimizer_execution_independently_observed",
        "base_checkpoint_lineage_deferred",
        "isolated_candidate_model_created",
        "base_model_unchanged",
        "process_rng_state_restored",
        "deterministic_algorithms_enforced",
        "public_authenticated_trainer_boundary_used",
        "optimizer_state_persisted",
        "corpus_revalidated_after_optimization",
        "model_state_changed",
        "anomaly_free_optimizer_cycle",
        "in_memory_checkpoint_candidate_created",
        "durable_execution_receipt_written",
        *_AUTHORITY_FALSE,
    )


def _validate_training_result(
    *,
    result: PPOTrainingResult,
    training_rows: Sequence[TrainingExample],
    validation_rows: Sequence[TrainingExample],
    base_parameter_fingerprint: str,
    authorization_sha256: str,
    authorized_row_identities: Sequence[str],
    split_metrics: Mapping[str, object],
) -> None:
    if type(result) is not PPOTrainingResult:
        _fail("PROFILED_SUPERVISED_EXECUTION_TRAINING_RESULT_EXACT_TYPE_REQUIRED")
    metrics = result.metrics
    if (
        result.status not in _SUCCESS_STATUSES
        or result.training_steps != 1
        or result.train_rows != len(training_rows)
        or result.validation_rows != len(validation_rows)
        or len(result.optimizer_training_examples) != len(training_rows)
        or len(result.validation_examples) != len(validation_rows)
        or any(
            actual is not expected
            for actual, expected in zip(
                result.optimizer_training_examples,
                training_rows,
                strict=True,
            )
        )
        or any(
            actual is not expected
            for actual, expected in zip(
                result.validation_examples,
                validation_rows,
                strict=True,
            )
        )
        or metrics.get("learning_update_lane") != "outcome_supervised"
        or metrics.get("ppo_objective_used") is not False
        or metrics.get("outcome_supervised_update_used") is not True
        or metrics.get("ppo_clipped_surrogate_rows") != 0
        or metrics.get("outcome_supervised_batch_rows") != len(training_rows)
        or metrics.get("optimizer_steps_this_cycle") != 1
        or metrics.get("parameter_hash_before") != base_parameter_fingerprint
        or metrics.get("authenticated_profiled_execution_authorization_sha256")
        != authorization_sha256
        or metrics.get("authenticated_profiled_row_identities") != list(authorized_row_identities)
        or metrics.get("complete_authenticated_corpus_considered") is not True
        or not _valid_sha256(metrics.get("parameter_hash_after"))
        or metrics.get("parameter_hash_after") == base_parameter_fingerprint
        or type(metrics.get("weight_delta_norm")) is not float
        or not math.isfinite(cast(float, metrics.get("weight_delta_norm")))
        or cast(float, metrics.get("weight_delta_norm")) <= 0.0
        or metrics.get("tensor_nan_inf_count") != 0
        or metrics.get("optimizer_anomaly_counters_complete") is not True
        or metrics.get("anomaly_free_optimizer_cycle") is not True
        or metrics.get("training_cycle_rolled_back") is not False
        or metrics.get("training_cycle_abort_reason") is not None
        or metrics.get("validation_split_pit_safe")
        is not split_metrics.get("validation_split_pit_safe")
        or metrics.get("validation_split_reason") != split_metrics.get("validation_split_reason")
        or metrics.get("validation_split_actual_training_rows") != len(training_rows)
        or metrics.get("validation_split_actual_validation_rows") != len(validation_rows)
        or (bool(validation_rows) and metrics.get("validation_split_pit_safe") is not True)
        or type(metrics.get("feedback_head_nudge_applied")) is not bool
        or type(metrics.get("expected_move_head_saturation_recovery_applied")) is not bool
        or type(metrics.get("expected_move_head_saturation_recovery_reason")) is not str
        or metrics.get("confidence_calibration_checkpoint_bound") is not True
        or metrics.get("confidence_calibration_external_state_used") is not False
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_TRAINING_RESULT_INVALID")


def _restore_failed_candidate_and_verify_base(
    *,
    base_model: V2HybridPolicyModel,
    base_parameter_fingerprint: str,
    base_nonparameter_state_artifact: bytes,
    candidate_model: V2HybridPolicyModel | None,
    rollback_state: dict[str, Any] | None,
) -> None:
    try:
        if candidate_model is not None:
            if rollback_state is None:
                _fail("PROFILED_SUPERVISED_EXECUTION_ROLLBACK_STATE_MISSING")
            candidate_model._restore_mutable_state_snapshot(  # noqa: SLF001
                rollback_state
            )
            if (
                model_parameter_fingerprint(candidate_model) != base_parameter_fingerprint
                or _nonparameter_model_state_artifact(candidate_model)
                != base_nonparameter_state_artifact
            ):
                _fail("PROFILED_SUPERVISED_EXECUTION_ROLLBACK_VERIFICATION_FAILED")
        if (
            model_parameter_fingerprint(base_model) != base_parameter_fingerprint
            or _nonparameter_model_state_artifact(base_model) != base_nonparameter_state_artifact
        ):
            _fail("PROFILED_SUPERVISED_EXECUTION_BASE_MODEL_MUTATED")
    except Exception as rollback_exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_FAILED_AND_ROLLBACK_FAILED"
        ) from rollback_exc


def execute_authenticated_profiled_supervised_optimizer_v1(
    *,
    before_corpus: AuthenticatedProfiledOptimizerCorpusV1,
    after_corpus: AuthenticatedProfiledOptimizerCorpusV1,
    execution_authorization: AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1,
    base_model: V2HybridPolicyModel,
    trainer: V2HybridPPOTrainer,
    validation_fraction: float,
    optimizer_input_byte_budget: int,
    state_resource_budget_bytes: int,
    checkpoint_serialization_byte_budget: int,
    clock: Callable[[], datetime | str] = _utc_now,
) -> AuthenticatedProfiledSupervisedOptimizerExecutionV1:
    """Run one isolated authenticated outcome-supervised optimizer step.

    The supplied base model is never optimized. An exact private clone is
    created under deterministic RNG/backend isolation. The result grants no
    write, serving, prediction, trading, exchange, or deployment authority.
    """

    if (
        type(before_corpus) is not AuthenticatedProfiledOptimizerCorpusV1
        or type(after_corpus) is not AuthenticatedProfiledOptimizerCorpusV1
        or type(execution_authorization)
        is not AuthenticatedProfiledSupervisedOptimizerExecutionAuthorizationV1
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_CORPUS_TYPES_INVALID")
    if type(base_model) is not V2HybridPolicyModel or type(trainer) is not V2HybridPPOTrainer:
        _fail("PROFILED_SUPERVISED_EXECUTION_TRAINER_TYPES_INVALID")
    if trainer.model is not base_model:
        _fail("PROFILED_SUPERVISED_EXECUTION_TRAINER_MODEL_OWNER_MISMATCH")
    try:
        validate_authenticated_profiled_optimizer_execution_authorization_pair_v1(
            authorization=execution_authorization,
            before=before_corpus,
            after=after_corpus,
        )
    except AuthenticatedProfiledOptimizerCorpusV1Error as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_AUTHORIZATION_REVALIDATION_FAILED",
            *exc.reasons,
        ) from exc
    if (
        type(validation_fraction) is not float
        or not math.isfinite(validation_fraction)
        or not 0.0 <= validation_fraction < 1.0
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_VALIDATION_FRACTION_INVALID")
    for value, reason in (
        (optimizer_input_byte_budget, "PROFILED_SUPERVISED_EXECUTION_INPUT_BUDGET_INVALID"),
        (state_resource_budget_bytes, "PROFILED_SUPERVISED_EXECUTION_STATE_BUDGET_INVALID"),
        (
            checkpoint_serialization_byte_budget,
            "PROFILED_SUPERVISED_EXECUTION_CHECKPOINT_BUDGET_INVALID",
        ),
    ):
        if (
            type(value) is not int
            or value <= 0
            or value > MAX_PROFILED_CHECKPOINT_SERIALIZATION_BYTES
        ):
            _fail(reason)

    if (
        base_model.input_dim != LOGICAL_MODEL_INPUT_COUNT
        or base_model.input_dim != CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
        or not base_model.torch_available
        or not base_model.model_tensors_device_verified()
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_CONTRACT_INVALID")
    declaration = base_model.checkpoint_feature_abi_declaration
    if declaration is None:
        _fail("PROFILED_SUPERVISED_EXECUTION_FEATURE_ABI_BINDING_REQUIRED")
    try:
        abi_verification = verify_deployed_checkpoint_feature_abi_binding_v4(
            declaration,
            checkpoint_input_dim=base_model.input_dim,
        )
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_SUPERVISED_EXECUTION_FEATURE_ABI_BINDING_INVALID"
        ) from exc
    if abi_verification.get("binding_sha256") != CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256:
        _fail("PROFILED_SUPERVISED_EXECUTION_FEATURE_ABI_BINDING_INVALID")

    row_count = before_corpus.manifest_admitted_example_count
    optimizer_input_accounted_bytes = row_count * (LOGICAL_MODEL_INPUT_COUNT * 4 + 4096)
    if optimizer_input_accounted_bytes > optimizer_input_byte_budget:
        _fail("PROFILED_SUPERVISED_EXECUTION_INPUT_BUDGET_EXCEEDED")
    state_accounted_bytes, state_payload_bytes = _model_state_accounted_bytes(base_model)
    if (
        state_accounted_bytes > state_resource_budget_bytes
        or state_payload_bytes > state_resource_budget_bytes
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_STATE_BUDGET_EXCEEDED")

    execution_authorization_sha256 = execution_authorization.inventory_equality_sha256
    examples = tuple(
        _training_example(
            row,
            execution_authorization_sha256=execution_authorization_sha256,
        )
        for row in before_corpus.rows
    )
    if len(examples) != row_count:
        _fail("PROFILED_SUPERVISED_EXECUTION_COMPLETE_CORPUS_REQUIRED")
    row_by_example_id = {
        id(example): row for example, row in zip(examples, before_corpus.rows, strict=True)
    }
    expected_example_by_row_id = {
        id(row): example for example, row in zip(examples, before_corpus.rows, strict=True)
    }
    authorized_row_identities = tuple(row.row_inventory_sha256 for row in before_corpus.rows)

    def authorize_example(example: TrainingExample) -> str:
        row = row_by_example_id.get(id(example))
        if row is None:
            _fail("PROFILED_SUPERVISED_EXECUTION_EXAMPLE_OWNER_MISMATCH")
        expected_example = expected_example_by_row_id[id(row)]
        return _authorize_exact_training_example(
            example=example,
            expected_example=expected_example,
            row=row,
            execution_authorization_sha256=execution_authorization_sha256,
        )

    implementation_artifact = _source_artifact()
    implementation_artifact_sha256 = hashlib.sha256(implementation_artifact).hexdigest()
    code_release_sha = _code_release_sha()
    conservative_checkpoint_preflight = (
        PROFILED_CHECKPOINT_FIXED_ACCOUNTING_BYTES
        + row_count * PROFILED_OPTIMIZER_ROW_ACCOUNTING_BYTES
        + state_accounted_bytes
        + len(implementation_artifact)
        + MAX_PROFILED_CONFIGURATION_ARTIFACT_BYTES
        + MAX_PROFILED_ENVIRONMENT_ARTIFACT_BYTES
    )
    if conservative_checkpoint_preflight > checkpoint_serialization_byte_budget:
        _fail("PROFILED_SUPERVISED_EXECUTION_CHECKPOINT_BUDGET_EXCEEDED")
    base_parameter_fingerprint = model_parameter_fingerprint(base_model)
    base_nonparameter_state_artifact = _nonparameter_model_state_artifact(base_model)
    base_nonparameter_state_sha256 = hashlib.sha256(base_nonparameter_state_artifact).hexdigest()
    deterministic_seed, deterministic_seed_material_sha256 = _deterministic_seed(
        corpus_contract_sha256=before_corpus.corpus_contract_sha256,
        execution_authorization_sha256=execution_authorization_sha256,
        base_model_parameter_fingerprint=base_parameter_fingerprint,
        implementation_artifact_sha256=implementation_artifact_sha256,
        code_release_sha=code_release_sha,
    )
    training_observed_at = trainer.training_observed_at_iso
    if _clock(
        training_observed_at,
        reason="PROFILED_SUPERVISED_EXECUTION_TRAINING_OBSERVED_AT_INVALID",
    ) < _clock(
        before_corpus.causal_clock_range.latest_label_available_at,
        reason="PROFILED_SUPERVISED_EXECUTION_LABEL_CLOCK_INVALID",
    ) or _clock(
        training_observed_at,
        reason="PROFILED_SUPERVISED_EXECUTION_TRAINING_OBSERVED_AT_INVALID",
    ) <= _clock(
        before_corpus.witness_accepted_at,
        reason="PROFILED_SUPERVISED_EXECUTION_WITNESS_CLOCK_INVALID",
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_TRAINING_OBSERVED_AT_INVALID")

    stage_clock = _StageClock(source=clock, lower_bound=before_corpus.witness_accepted_at)
    before_input_verified_at = stage_clock.next(
        reason="PROFILED_SUPERVISED_EXECUTION_BEFORE_INPUT_CLOCK_INVALID"
    )
    if _clock(
        training_observed_at,
        reason="PROFILED_SUPERVISED_EXECUTION_TRAINING_OBSERVED_AT_INVALID",
    ) >= _clock(
        before_input_verified_at,
        reason="PROFILED_SUPERVISED_EXECUTION_BEFORE_INPUT_CLOCK_INVALID",
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_TRAINING_OBSERVED_AT_INVALID")

    candidate_model: V2HybridPolicyModel | None = None
    candidate_trainer: V2HybridPPOTrainer | None = None
    rollback_state: dict[str, Any] | None = None
    try:
        deterministic_guard = _DeterministicTorchExecution(
            model=base_model,
            seed=deterministic_seed,
        )
        with deterministic_guard:
            candidate_model, candidate_trainer = _isolated_candidate_runtime(
                base_model=base_model,
                base_trainer=trainer,
            )
            deterministic_guard.prepare_optimizer()
            rollback_state = candidate_model._mutable_state_snapshot()  # noqa: SLF001
            before_model_tensors = _state_tensors(
                candidate_model,
                resource_budget_bytes=state_resource_budget_bytes,
            )
            before_state_captured_at = stage_clock.next(
                reason="PROFILED_SUPERVISED_EXECUTION_BEFORE_STATE_CLOCK_INVALID"
            )
            before_state = capture_profiled_supervised_optimization_state_snapshot_v1(
                stage="BEFORE_OPTIMIZATION",
                captured_at=before_state_captured_at,
                model_tensors=before_model_tensors,
                optimizer_tensors=(),
                resource_budget_bytes=state_resource_budget_bytes,
            )
            optimizer_started_at = stage_clock.next(
                reason="PROFILED_SUPERVISED_EXECUTION_OPTIMIZER_START_CLOCK_INVALID"
            )
            result = candidate_trainer.train_authenticated_profiled_outcome_supervised(
                examples,
                authorize_example=authorize_example,
                authorization_sha256=execution_authorization_sha256,
                steps=1,
                validation_fraction=validation_fraction,
            )
            optimizer_completed_at = stage_clock.next(
                reason="PROFILED_SUPERVISED_EXECUTION_OPTIMIZER_COMPLETION_CLOCK_INVALID"
            )
            training_rows = result.optimizer_training_examples
            validation_rows = result.validation_examples
            split_metrics = result.metrics
            _validate_training_result(
                result=result,
                training_rows=training_rows,
                validation_rows=validation_rows,
                base_parameter_fingerprint=base_parameter_fingerprint,
                authorization_sha256=execution_authorization_sha256,
                authorized_row_identities=authorized_row_identities,
                split_metrics=split_metrics,
            )
            if candidate_model.net is None or base_model.net is None:
                _fail("PROFILED_SUPERVISED_EXECUTION_TORCH_MODEL_REQUIRED")
            candidate_model.net.train(bool(base_model.net.training))
            after_model_tensors = _state_tensors(
                candidate_model,
                resource_budget_bytes=state_resource_budget_bytes,
            )
            after_state_captured_at = stage_clock.next(
                reason="PROFILED_SUPERVISED_EXECUTION_AFTER_STATE_CLOCK_INVALID"
            )
            after_state = capture_profiled_supervised_optimization_state_snapshot_v1(
                stage="AFTER_OPTIMIZATION",
                captured_at=after_state_captured_at,
                model_tensors=after_model_tensors,
                optimizer_tensors=(),
                resource_budget_bytes=state_resource_budget_bytes,
            )
            if (
                before_state.model_coordinate_inventory_sha256
                != after_state.model_coordinate_inventory_sha256
                or before_state.model_state_content_inventory_sha256
                == after_state.model_state_content_inventory_sha256
            ):
                _fail("PROFILED_SUPERVISED_EXECUTION_MODEL_STATE_CHANGE_INVALID")
            try:
                validate_authenticated_profiled_optimizer_execution_authorization_pair_v1(
                    authorization=execution_authorization,
                    before=before_corpus,
                    after=after_corpus,
                )
            except AuthenticatedProfiledOptimizerCorpusV1Error as exc:
                raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
                    "PROFILED_SUPERVISED_EXECUTION_AFTER_CORPUS_REVALIDATION_FAILED",
                    *exc.reasons,
                ) from exc
            after_input_verified_at = stage_clock.next(
                reason="PROFILED_SUPERVISED_EXECUTION_AFTER_INPUT_CLOCK_INVALID"
            )
            candidate_parameter_fingerprint = model_parameter_fingerprint(candidate_model)
            candidate_nonparameter_state_artifact = _nonparameter_model_state_artifact(
                candidate_model
            )
        if deterministic_guard.restored is not True:
            _fail("PROFILED_SUPERVISED_EXECUTION_RNG_RESTORE_UNVERIFIED")
        if (
            model_parameter_fingerprint(base_model) != base_parameter_fingerprint
            or _nonparameter_model_state_artifact(base_model) != base_nonparameter_state_artifact
        ):
            _fail("PROFILED_SUPERVISED_EXECUTION_BASE_MODEL_MUTATED")
        if candidate_model is None or candidate_trainer is None:
            _fail("PROFILED_SUPERVISED_EXECUTION_ISOLATED_RUNTIME_MISSING")

        training_corpus_rows = tuple(row_by_example_id[id(example)] for example in training_rows)
        validation_corpus_rows = tuple(
            row_by_example_id[id(example)] for example in validation_rows
        )
        configuration_artifact = _configuration_artifact(
            trainer=candidate_trainer,
            model=candidate_model,
            corpus=before_corpus,
            validation_fraction=validation_fraction,
            split_metrics=split_metrics,
            optimizer_input_byte_budget=optimizer_input_byte_budget,
            optimizer_input_accounted_bytes=optimizer_input_accounted_bytes,
            state_resource_budget_bytes=state_resource_budget_bytes,
            checkpoint_serialization_byte_budget=(checkpoint_serialization_byte_budget),
            deterministic_seed_material_sha256=(deterministic_seed_material_sha256),
            code_release_sha=code_release_sha,
        )
        candidate_nonparameter_state_sha256 = hashlib.sha256(
            candidate_nonparameter_state_artifact
        ).hexdigest()
        environment_artifact = _environment_artifact(
            model=candidate_model,
            code_release_sha=code_release_sha,
            deterministic_seed_material_sha256=deterministic_seed_material_sha256,
            base_nonparameter_model_state_sha256=(base_nonparameter_state_sha256),
            candidate_nonparameter_model_state_artifact_json_bytes=(
                candidate_nonparameter_state_artifact
            ),
        )
        checkpoint_created_at = stage_clock.next(
            reason="PROFILED_SUPERVISED_EXECUTION_CHECKPOINT_CLOCK_INVALID"
        )
        checkpoint_candidate = build_authenticated_profiled_supervised_checkpoint_inventory_v1(
            before_corpus=before_corpus,
            after_corpus=after_corpus,
            execution_authorization=execution_authorization,
            before_state=before_state,
            after_state=after_state,
            before_input_inventory_verified_at=before_input_verified_at,
            optimizer_started_at=optimizer_started_at,
            optimizer_completed_at=optimizer_completed_at,
            after_input_inventory_verified_at=after_input_verified_at,
            checkpoint_created_at=checkpoint_created_at,
            optimizer_implementation_artifact_bytes=implementation_artifact,
            optimizer_configuration_artifact_json_bytes=configuration_artifact,
            execution_environment_artifact_json_bytes=environment_artifact,
            serialization_byte_budget=checkpoint_serialization_byte_budget,
        )
        candidate_parameter_fingerprint = model_parameter_fingerprint(candidate_model)
        if candidate_parameter_fingerprint != result.metrics.get("parameter_hash_after"):
            _fail("PROFILED_SUPERVISED_EXECUTION_CANDIDATE_FINGERPRINT_MISMATCH")
        training_result_artifact = _training_result_artifact(result)
        training_result_sha256 = hashlib.sha256(training_result_artifact).hexdigest()
        idempotency_key = stable_sha256(
            {
                "domain": (
                    "v2/native-trainer/authenticated-profiled-supervised-execution/"
                    "idempotency/v1"
                ),
                "completion_event_sha256": before_corpus.completion_event_sha256,
                "corpus_contract_sha256": before_corpus.corpus_contract_sha256,
                "execution_authorization_inventory_equality_sha256": (
                    execution_authorization_sha256
                ),
                "base_model_parameter_fingerprint": base_parameter_fingerprint,
                "base_nonparameter_model_state_sha256": (base_nonparameter_state_sha256),
                "deterministic_seed_material_sha256": (deterministic_seed_material_sha256),
                "code_release_sha": code_release_sha,
                "optimizer_implementation_artifact_sha256": (
                    checkpoint_candidate.optimizer_implementation_artifact_sha256
                ),
                "optimizer_configuration_artifact_sha256": (
                    checkpoint_candidate.optimizer_configuration_artifact_sha256
                ),
            }
        )
        values: dict[str, Any] = {
            "schema_version": (
                AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION
            ),
            "status": AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_STATUS,
            "execution_idempotency_key": idempotency_key,
            "manifest_id": before_corpus.manifest_id,
            "completion_event_sha256": before_corpus.completion_event_sha256,
            "corpus_contract_sha256": before_corpus.corpus_contract_sha256,
            "execution_authorization_inventory_equality_sha256": (execution_authorization_sha256),
            "base_checkpoint_id": None,
            "base_checkpoint_weight_sha256": None,
            "model_id": candidate_model.model_id,
            "model_input_dim": candidate_model.input_dim,
            "base_model_parameter_fingerprint": base_parameter_fingerprint,
            "candidate_model_parameter_fingerprint": candidate_parameter_fingerprint,
            "base_nonparameter_model_state_sha256": (base_nonparameter_state_sha256),
            "candidate_nonparameter_model_state_artifact_json_bytes": (
                candidate_nonparameter_state_artifact
            ),
            "candidate_nonparameter_model_state_sha256": (candidate_nonparameter_state_sha256),
            "code_release_sha": code_release_sha,
            "deterministic_seed_material_sha256": (deterministic_seed_material_sha256),
            "training_observed_at": training_observed_at,
            "before_input_inventory_verified_at": before_input_verified_at,
            "before_state_captured_at": before_state_captured_at,
            "optimizer_started_at": optimizer_started_at,
            "optimizer_completed_at": optimizer_completed_at,
            "after_state_captured_at": after_state_captured_at,
            "after_input_inventory_verified_at": after_input_verified_at,
            "checkpoint_created_at": checkpoint_created_at,
            "admitted_example_count": len(examples),
            "optimizer_training_row_count": len(training_rows),
            "validation_row_count": len(validation_rows),
            "ordered_optimizer_training_rows_sha256": _ordered_row_inventory_sha256(
                training_corpus_rows,
                domain="v2/native-trainer/authenticated-profiled-supervised-execution/train-rows/v1",
            ),
            "ordered_validation_rows_sha256": _ordered_row_inventory_sha256(
                validation_corpus_rows,
                domain="v2/native-trainer/authenticated-profiled-supervised-execution/validation-rows/v1",
            ),
            "optimizer_steps_requested": 1,
            "optimizer_steps_completed": 1,
            "learning_mode": "outcome_supervised",
            "device": result.device,
            "cuda_active": result.cuda_active,
            "cuda_claim_verified": result.cuda_claim_verified,
            "loss_before": float(cast(float, result.loss_before)),
            "loss_after": float(cast(float, result.loss_after)),
            "weight_delta_norm": float(result.metrics["weight_delta_norm"]),
            "before_state_snapshot_sha256": before_state.state_snapshot_sha256,
            "after_state_snapshot_sha256": after_state.state_snapshot_sha256,
            "checkpoint_inventory_sha256": checkpoint_candidate.checkpoint_inventory_sha256,
            "checkpoint_bytes_sha256": checkpoint_candidate.checkpoint_bytes_sha256,
            "checkpoint_byte_count": checkpoint_candidate.checkpoint_byte_count,
            "optimizer_implementation_artifact_sha256": (
                checkpoint_candidate.optimizer_implementation_artifact_sha256
            ),
            "optimizer_configuration_artifact_sha256": (
                checkpoint_candidate.optimizer_configuration_artifact_sha256
            ),
            "execution_environment_artifact_sha256": (
                checkpoint_candidate.execution_environment_artifact_sha256
            ),
            "training_result_artifact_json_bytes": training_result_artifact,
            "training_result_artifact_sha256": training_result_sha256,
            "in_memory_execution_receipt_sha256": "0" * 64,
            "supervised_optimizer_input_authorized": True,
            "supervised_optimizer_execution_authorized": True,
            "optimizer_execution_authorized": True,
            "optimizer_execution_completed": True,
            "optimizer_execution_independently_observed": False,
            "base_checkpoint_lineage_deferred": True,
            "isolated_candidate_model_created": True,
            "base_model_unchanged": True,
            "process_rng_state_restored": True,
            "deterministic_algorithms_enforced": True,
            "public_authenticated_trainer_boundary_used": True,
            "optimizer_state_persisted": False,
            "corpus_revalidated_after_optimization": True,
            "model_state_changed": True,
            "anomaly_free_optimizer_cycle": True,
            "in_memory_checkpoint_candidate_created": True,
            "durable_execution_receipt_written": False,
            **_AUTHORITY_FALSE,
            "checkpoint_candidate": checkpoint_candidate,
            "_base_model_owner": base_model,
            "_base_trainer_owner": trainer,
            "_candidate_model_owner": candidate_model,
            "_trainer_owner": candidate_trainer,
            "_factory_seal": _FactorySeal(mac=b"placeholder"),
            "_construction_token": _RESULT_TOKEN,
        }
        receipt = stable_sha256(_execution_material(values))
        values["in_memory_execution_receipt_sha256"] = receipt
        material = _execution_material(values)
        values["_factory_seal"] = _FactorySeal(
            mac=_seal_bytes(
                material,
                owner_ids=(
                    id(base_model),
                    id(trainer),
                    id(candidate_model),
                    id(candidate_trainer),
                    id(checkpoint_candidate),
                ),
            )
        )
        return AuthenticatedProfiledSupervisedOptimizerExecutionV1(**values)
    except AuthenticatedProfiledSupervisedOptimizerExecutionV1Error:
        _restore_failed_candidate_and_verify_base(
            base_model=base_model,
            base_parameter_fingerprint=base_parameter_fingerprint,
            base_nonparameter_state_artifact=base_nonparameter_state_artifact,
            candidate_model=candidate_model,
            rollback_state=rollback_state,
        )
        raise
    except Exception as exc:
        _restore_failed_candidate_and_verify_base(
            base_model=base_model,
            base_parameter_fingerprint=base_parameter_fingerprint,
            base_nonparameter_state_artifact=base_nonparameter_state_artifact,
            candidate_model=candidate_model,
            rollback_state=rollback_state,
        )
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            f"PROFILED_SUPERVISED_EXECUTION_FAILED:{type(exc).__name__}"
        ) from exc


def _local_research_validation_material(
    validation: LocallyValidatedProfiledResearchExampleV1,
) -> dict[str, object]:
    return {
        "ordinal": validation.ordinal,
        "sample_identity_sha256": validation.sample_identity_sha256,
        "label_binding_sha256": validation.label_binding_sha256,
        "tensor_binding_sha256": validation.tensor_binding_sha256,
        "example_fingerprint_sha256": validation.example_fingerprint_sha256,
        "logical_model_vector_sha256": validation.logical_model_vector_sha256,
        "logical_projection_sha256": validation.logical_projection_sha256,
        "model_feature_cutoff": validation.model_feature_cutoff,
        "record_wide_evidence_cutoff": validation.record_wide_evidence_cutoff,
        "source_feature_available_at": validation.source_feature_available_at,
        "decision_feature_available_at": validation.decision_feature_available_at,
        "feature_generated_at": validation.feature_generated_at,
        "training_record_generated_at": validation.training_record_generated_at,
        "decision_time": validation.decision_time,
        "trainer_sample_available_at": validation.trainer_sample_available_at,
        "label_available_at": validation.label_available_at,
        "observation_time": validation.observation_time,
        "horizon_seconds": validation.horizon_seconds,
    }


def _local_research_result_material(values: Mapping[str, object]) -> dict[str, object]:
    names = (
        "schema_version",
        "status",
        "manifest_id",
        "manifest_metadata_sha256",
        "manifest_entry_chain_head_sha256",
        "manifest_ordered_entry_identities_sha256",
        "manifest_observation_time",
        "admitted_example_count",
        "ordered_example_fingerprints_sha256",
        "corpus_contract_sha256",
        "authorization_key_id",
        "authorization_tag",
        "authorization_receipt_sha256",
        "optimizer_implementation_artifact_sha256",
        "code_release_sha",
        "deterministic_seed_material_sha256",
        "base_model_parameter_fingerprint",
        "candidate_model_parameter_fingerprint",
        "training_result_artifact_sha256",
        "training_rows",
        "validation_rows",
        "loss_before",
        "loss_after",
        "weight_delta_norm",
        "optimizer_execution_completed",
        "complete_corpus_revalidated_after_optimization",
        "base_model_unchanged",
        "isolated_candidate_model_created",
        "process_rng_state_restored",
        "deterministic_algorithms_enforced",
        "local_research_non_promotable",
        "external_witness_verified",
        *_AUTHORITY_FALSE,
    )
    return {name: values[name] for name in names}


@dataclass(frozen=True, slots=True)
class LocallyAuthenticatedProfiledResearchOptimizerExecutionV1:
    schema_version: str
    status: str
    manifest_id: str
    manifest_metadata_sha256: str
    manifest_entry_chain_head_sha256: str
    manifest_ordered_entry_identities_sha256: str
    manifest_observation_time: str
    admitted_example_count: int
    ordered_example_fingerprints_sha256: str
    corpus_contract_sha256: str
    authorization_key_id: str
    authorization_tag: str
    authorization_receipt_sha256: str
    optimizer_implementation_artifact_sha256: str
    code_release_sha: str
    deterministic_seed_material_sha256: str
    base_model_parameter_fingerprint: str
    candidate_model_parameter_fingerprint: str
    training_result_artifact_sha256: str
    training_rows: int
    validation_rows: int
    loss_before: float
    loss_after: float
    weight_delta_norm: float
    optimizer_execution_completed: bool
    complete_corpus_revalidated_after_optimization: bool
    base_model_unchanged: bool
    isolated_candidate_model_created: bool
    process_rng_state_restored: bool
    deterministic_algorithms_enforced: bool
    local_research_non_promotable: bool
    external_witness_verified: bool
    checkpoint_write_authorized: bool
    model_write_authorized: bool
    prediction_authorized: bool
    serving_authorized: bool
    ppo_training_authorized: bool
    paper_trading_authorized: bool
    live_execution_authorized: bool
    exchange_access_authorized: bool
    deployment_authorized: bool
    order_submission_authorized: bool
    execution_authorized: bool
    runtime_wired: bool
    _base_model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _candidate_model_owner: V2HybridPolicyModel = field(repr=False, compare=False)
    _candidate_trainer_owner: V2HybridPPOTrainer = field(repr=False, compare=False)
    _factory_seal: _FactorySeal = field(repr=False, compare=False)
    _construction_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        material = _local_research_result_material(
            {name: getattr(self, name) for name in _local_research_result_material_names()}
        )
        hashes = (
            self.manifest_id,
            self.manifest_metadata_sha256,
            self.manifest_entry_chain_head_sha256,
            self.manifest_ordered_entry_identities_sha256,
            self.ordered_example_fingerprints_sha256,
            self.corpus_contract_sha256,
            self.authorization_tag,
            self.authorization_receipt_sha256,
            self.optimizer_implementation_artifact_sha256,
            self.deterministic_seed_material_sha256,
            self.base_model_parameter_fingerprint,
            self.candidate_model_parameter_fingerprint,
            self.training_result_artifact_sha256,
        )
        authority_values = tuple(getattr(self, name) for name in _AUTHORITY_FALSE)
        if (
            self._construction_token is not _LOCAL_RESEARCH_RESULT_TOKEN
            or self.schema_version
            != LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION
            or self.status
            != LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_STATUS
            or not all(_valid_sha256(value) for value in hashes)
            or type(self.code_release_sha) is not str
            or len(self.code_release_sha) != 40
            or any(value not in "0123456789abcdef" for value in self.code_release_sha)
            or type(self.authorization_key_id) is not str
            or not self.authorization_key_id
            or self.authorization_key_id != self.authorization_key_id.strip()
            or type(self.admitted_example_count) is not int
            or self.admitted_example_count <= 0
            or type(self.training_rows) is not int
            or self.training_rows <= 0
            or type(self.validation_rows) is not int
            or self.validation_rows < 0
            or self.training_rows + self.validation_rows != self.admitted_example_count
            or any(
                type(value) is not float or not math.isfinite(value)
                for value in (self.loss_before, self.loss_after, self.weight_delta_norm)
            )
            or self.weight_delta_norm <= 0.0
            or self.base_model_parameter_fingerprint
            == self.candidate_model_parameter_fingerprint
            or any(
                value is not True
                for value in (
                    self.optimizer_execution_completed,
                    self.complete_corpus_revalidated_after_optimization,
                    self.base_model_unchanged,
                    self.isolated_candidate_model_created,
                    self.process_rng_state_restored,
                    self.deterministic_algorithms_enforced,
                    self.local_research_non_promotable,
                )
            )
            or self.external_witness_verified is not False
            or any(value is not False for value in authority_values)
            or type(self._base_model_owner) is not V2HybridPolicyModel
            or type(self._candidate_model_owner) is not V2HybridPolicyModel
            or type(self._candidate_trainer_owner) is not V2HybridPPOTrainer
            or self._candidate_trainer_owner.model is not self._candidate_model_owner
            or not hmac.compare_digest(
                self._factory_seal.mac,
                _seal_bytes(
                    material,
                    owner_ids=(
                        id(self._base_model_owner),
                        id(self._candidate_model_owner),
                        id(self._candidate_trainer_owner),
                    ),
                ),
            )
        ):
            _fail("PROFILED_LOCAL_RESEARCH_EXECUTION_RESULT_INVALID")
        _clock(
            self.manifest_observation_time,
            reason="PROFILED_LOCAL_RESEARCH_OBSERVATION_TIME_INVALID",
        )

    @property
    def candidate_model(self) -> V2HybridPolicyModel:
        """Return the exact isolated in-process candidate owner."""

        self.__post_init__()
        return self._candidate_model_owner


def _local_research_result_material_names() -> tuple[str, ...]:
    return (
        "schema_version",
        "status",
        "manifest_id",
        "manifest_metadata_sha256",
        "manifest_entry_chain_head_sha256",
        "manifest_ordered_entry_identities_sha256",
        "manifest_observation_time",
        "admitted_example_count",
        "ordered_example_fingerprints_sha256",
        "corpus_contract_sha256",
        "authorization_key_id",
        "authorization_tag",
        "authorization_receipt_sha256",
        "optimizer_implementation_artifact_sha256",
        "code_release_sha",
        "deterministic_seed_material_sha256",
        "base_model_parameter_fingerprint",
        "candidate_model_parameter_fingerprint",
        "training_result_artifact_sha256",
        "training_rows",
        "validation_rows",
        "loss_before",
        "loss_after",
        "weight_delta_norm",
        "optimizer_execution_completed",
        "complete_corpus_revalidated_after_optimization",
        "base_model_unchanged",
        "isolated_candidate_model_created",
        "process_rng_state_restored",
        "deterministic_algorithms_enforced",
        "local_research_non_promotable",
        "external_witness_verified",
        *_AUTHORITY_FALSE,
    )


def execute_locally_authenticated_profiled_research_optimizer_v1(
    *,
    authenticated_manifest: AuthenticatedProfiledTrainingObservationManifestV1,
    candidates: tuple[ProfiledTrainingObservationExampleV1, ...],
    ledger: DurableFeatureSnapshotLedger,
    base_model: V2HybridPolicyModel,
    trainer: V2HybridPPOTrainer,
    authorization_key_id: str,
    authorization_hmac_key: bytes | bytearray | memoryview,
    validation_fraction: float,
    optimizer_input_byte_budget: int,
    state_resource_budget_bytes: int,
    checkpoint_serialization_byte_budget: int,
) -> LocallyAuthenticatedProfiledResearchOptimizerExecutionV1:
    """Run one isolated local-only optimizer step over an authenticated manifest.

    The external witness boundary is intentionally absent and is recorded as
    false.  The returned candidate is process-owned and still has no durable
    checkpoint, promotion, serving, prediction, paper, live, exchange, or
    order authority.
    """

    if type(authenticated_manifest) is not AuthenticatedProfiledTrainingObservationManifestV1:
        _fail("PROFILED_LOCAL_RESEARCH_MANIFEST_EXACT_TYPE_REQUIRED")
    authenticated_manifest.__post_init__()
    if (
        type(candidates) is not tuple
        or not candidates
        or len(candidates) != authenticated_manifest.admitted_example_count
        or any(type(item) is not ProfiledTrainingObservationExampleV1 for item in candidates)
        or authenticated_manifest.external_monotonic_manifest_head_verified is not False
        or authenticated_manifest.full_consumption_external_ack_verified is not False
        or authenticated_manifest.optimizer_admission_authorized is not False
        or authenticated_manifest.checkpoint_write_authorized is not False
    ):
        _fail("PROFILED_LOCAL_RESEARCH_MANIFEST_CORPUS_INVALID")
    if type(ledger) is not DurableFeatureSnapshotLedger:
        _fail("PROFILED_LOCAL_RESEARCH_LEDGER_EXACT_TYPE_REQUIRED")
    if (
        type(base_model) is not V2HybridPolicyModel
        or type(trainer) is not V2HybridPPOTrainer
        or trainer.model is not base_model
    ):
        _fail("PROFILED_LOCAL_RESEARCH_TRAINER_OWNER_INVALID")
    if (
        type(authorization_key_id) is not str
        or not authorization_key_id
        or authorization_key_id != authorization_key_id.strip()
        or any(value in authorization_key_id for value in "\r\n\x00")
    ):
        _fail("PROFILED_LOCAL_RESEARCH_AUTHORIZATION_KEY_ID_INVALID")
    try:
        authorization_key = bytes(authorization_hmac_key)
    except (TypeError, ValueError):
        _fail("PROFILED_LOCAL_RESEARCH_AUTHORIZATION_KEY_INVALID")
    if len(authorization_key) < 32:
        _fail("PROFILED_LOCAL_RESEARCH_AUTHORIZATION_KEY_INVALID")
    if (
        type(validation_fraction) is not float
        or not math.isfinite(validation_fraction)
        or not 0.0 <= validation_fraction < 1.0
    ):
        _fail("PROFILED_LOCAL_RESEARCH_VALIDATION_FRACTION_INVALID")
    for value, reason in (
        (optimizer_input_byte_budget, "PROFILED_LOCAL_RESEARCH_INPUT_BUDGET_INVALID"),
        (state_resource_budget_bytes, "PROFILED_LOCAL_RESEARCH_STATE_BUDGET_INVALID"),
        (
            checkpoint_serialization_byte_budget,
            "PROFILED_LOCAL_RESEARCH_CHECKPOINT_BUDGET_INVALID",
        ),
    ):
        if (
            type(value) is not int
            or value <= 0
            or value > MAX_PROFILED_CHECKPOINT_SERIALIZATION_BYTES
        ):
            _fail(reason)
    if (
        base_model.input_dim != LOGICAL_MODEL_INPUT_COUNT
        or base_model.input_dim != CHECKPOINT_FEATURE_ABI_BINDING_V4_MODEL_INPUT_DIM
        or not base_model.torch_available
        or not base_model.model_tensors_device_verified()
    ):
        _fail("PROFILED_LOCAL_RESEARCH_MODEL_CONTRACT_INVALID")
    declaration = base_model.checkpoint_feature_abi_declaration
    if declaration is None:
        _fail("PROFILED_LOCAL_RESEARCH_FEATURE_ABI_BINDING_REQUIRED")
    try:
        abi_verification = verify_deployed_checkpoint_feature_abi_binding_v4(
            declaration,
            checkpoint_input_dim=base_model.input_dim,
        )
    except Exception as exc:
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            "PROFILED_LOCAL_RESEARCH_FEATURE_ABI_BINDING_INVALID"
        ) from exc
    if abi_verification.get("binding_sha256") != CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256:
        _fail("PROFILED_LOCAL_RESEARCH_FEATURE_ABI_BINDING_INVALID")

    validations_before = tuple(
        validate_profiled_observation_example_for_local_research_v1(
            ledger=ledger,
            candidate=candidate,
            observation_time=authenticated_manifest.observation_time,
        )
        for candidate in candidates
    )
    if tuple(item.ordinal for item in validations_before) != tuple(
        sorted(item.ordinal for item in validations_before)
    ) or len({item.ordinal for item in validations_before}) != len(validations_before):
        _fail("PROFILED_LOCAL_RESEARCH_CORPUS_ORDER_INVALID")
    validation_material = tuple(
        _local_research_validation_material(item) for item in validations_before
    )
    corpus_contract = {
        "schema_version": "local_profiled_research_corpus_contract_v1",
        "manifest_id": authenticated_manifest.manifest_id,
        "manifest_metadata_sha256": authenticated_manifest.metadata_sha256,
        "manifest_observation_context_sha256": (
            authenticated_manifest.observation_context_sha256
        ),
        "manifest_entry_chain_head_sha256": (
            authenticated_manifest.entry_chain_head_sha256
        ),
        "manifest_ordered_entry_identities_sha256": (
            authenticated_manifest.ordered_entry_identities_sha256
        ),
        "manifest_observation_time": authenticated_manifest.observation_time,
        "manifest_total_profiled_samples": authenticated_manifest.total_profiled_samples,
        "manifest_admitted_example_count": authenticated_manifest.admitted_example_count,
        "manifest_label_unavailable_count": authenticated_manifest.label_unavailable_count,
        "validated_examples": list(validation_material),
        "external_witness_verified": False,
        "local_research_non_promotable": True,
    }
    corpus_contract_sha256 = stable_sha256(corpus_contract)
    ordered_example_fingerprints_sha256 = stable_sha256(
        [item.example_fingerprint_sha256 for item in validations_before]
    )
    authorization_material = {
        "domain": LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN,
        "schema_version": "local_profiled_research_optimizer_authorization_v1",
        "authorization_key_id": authorization_key_id,
        "corpus_contract_sha256": corpus_contract_sha256,
        "ordered_example_fingerprints_sha256": ordered_example_fingerprints_sha256,
        "manifest_id": authenticated_manifest.manifest_id,
        "manifest_observation_time": authenticated_manifest.observation_time,
        "admitted_example_count": len(candidates),
        "local_research_non_promotable": True,
        "external_witness_verified": False,
    }
    authorization_tag = hmac.new(
        authorization_key,
        LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN.encode("ascii")
        + b"\0"
        + _canonical_json_bytes(
            authorization_material,
            reason="PROFILED_LOCAL_RESEARCH_AUTHORIZATION_ENCODING_INVALID",
        ),
        hashlib.sha256,
    ).hexdigest()
    authorization_receipt_sha256 = stable_sha256(
        {**authorization_material, "authorization_tag": authorization_tag}
    )

    input_accounted_bytes = len(candidates) * (LOGICAL_MODEL_INPUT_COUNT * 4 + 4096)
    if input_accounted_bytes > optimizer_input_byte_budget:
        _fail("PROFILED_LOCAL_RESEARCH_INPUT_BUDGET_EXCEEDED")
    state_accounted_bytes, state_payload_bytes = _model_state_accounted_bytes(base_model)
    if (
        state_accounted_bytes > state_resource_budget_bytes
        or state_payload_bytes > state_resource_budget_bytes
    ):
        _fail("PROFILED_LOCAL_RESEARCH_STATE_BUDGET_EXCEEDED")
    implementation_artifact = _source_artifact()
    implementation_artifact_sha256 = hashlib.sha256(implementation_artifact).hexdigest()
    conservative_checkpoint_preflight = (
        PROFILED_CHECKPOINT_FIXED_ACCOUNTING_BYTES
        + len(candidates) * PROFILED_OPTIMIZER_ROW_ACCOUNTING_BYTES
        + state_accounted_bytes
        + len(implementation_artifact)
        + MAX_PROFILED_CONFIGURATION_ARTIFACT_BYTES
        + MAX_PROFILED_ENVIRONMENT_ARTIFACT_BYTES
    )
    if conservative_checkpoint_preflight > checkpoint_serialization_byte_budget:
        _fail("PROFILED_LOCAL_RESEARCH_CHECKPOINT_BUDGET_EXCEEDED")
    code_release_sha = _code_release_sha()
    base_parameter_fingerprint = model_parameter_fingerprint(base_model)
    base_nonparameter_state_artifact = _nonparameter_model_state_artifact(base_model)
    deterministic_seed, deterministic_seed_material_sha256 = _deterministic_seed(
        corpus_contract_sha256=corpus_contract_sha256,
        execution_authorization_sha256=authorization_receipt_sha256,
        base_model_parameter_fingerprint=base_parameter_fingerprint,
        implementation_artifact_sha256=implementation_artifact_sha256,
        code_release_sha=code_release_sha,
    )
    training_observed_at = _clock(
        trainer.training_observed_at_iso,
        reason="PROFILED_LOCAL_RESEARCH_TRAINING_OBSERVED_AT_INVALID",
    )
    latest_label_available_at = max(
        _clock(
            item.label_available_at,
            reason="PROFILED_LOCAL_RESEARCH_LABEL_AVAILABLE_AT_INVALID",
        )
        for item in validations_before
    )
    if training_observed_at <= _clock(
        authenticated_manifest.observation_time,
        reason="PROFILED_LOCAL_RESEARCH_OBSERVATION_TIME_INVALID",
    ) or training_observed_at <= latest_label_available_at:
        _fail("PROFILED_LOCAL_RESEARCH_TRAINING_OBSERVED_AT_INVALID")

    examples = tuple(
        _local_research_training_example(
            candidate=candidate,
            validation=validation,
            execution_authorization_sha256=authorization_receipt_sha256,
        )
        for candidate, validation in zip(candidates, validations_before, strict=True)
    )
    validation_by_example_id = {
        id(example): validation
        for example, validation in zip(examples, validations_before, strict=True)
    }

    def authorize_example(example: TrainingExample) -> str:
        validation = validation_by_example_id.get(id(example))
        if (
            validation is None
            or example.trust_row.get("profiled_sample_identity_sha256")
            != validation.sample_identity_sha256
            or example.trust_row.get("profiled_label_binding_sha256")
            != validation.label_binding_sha256
            or example.trust_row.get("profiled_tensor_binding_sha256")
            != validation.tensor_binding_sha256
            or example.trust_row.get(
                "profiled_optimizer_execution_authorization_sha256"
            )
            != authorization_receipt_sha256
            or example.trust_row.get("local_research_non_promotable") is not True
            or example.trust_row.get("external_witness_verified") is not False
        ):
            _fail("PROFILED_LOCAL_RESEARCH_EXAMPLE_OWNER_MISMATCH")
        return validation.example_fingerprint_sha256

    candidate_model: V2HybridPolicyModel | None = None
    candidate_trainer: V2HybridPPOTrainer | None = None
    rollback_state: dict[str, Any] | None = None
    try:
        deterministic_guard = _DeterministicTorchExecution(
            model=base_model,
            seed=deterministic_seed,
        )
        with deterministic_guard:
            candidate_model, candidate_trainer = _isolated_candidate_runtime(
                base_model=base_model,
                base_trainer=trainer,
            )
            deterministic_guard.prepare_optimizer()
            rollback_state = candidate_model._mutable_state_snapshot()  # noqa: SLF001
            result = candidate_trainer.train_profiled_outcome_supervised(
                examples,
                authorize_example=authorize_example,
                authorization_sha256=authorization_receipt_sha256,
                admission_scope=PROFILED_ADMISSION_SCOPE_LOCAL_RESEARCH,
                steps=1,
                validation_fraction=validation_fraction,
            )
        training_rows = result.optimizer_training_examples
        validation_rows = result.validation_examples
        _validate_training_result(
            result=result,
            training_rows=training_rows,
            validation_rows=validation_rows,
            base_parameter_fingerprint=base_parameter_fingerprint,
            authorization_sha256=authorization_receipt_sha256,
            authorized_row_identities=tuple(
                item.example_fingerprint_sha256 for item in validations_before
            ),
            split_metrics=result.metrics,
        )
        if (
            result.metrics.get("profiled_admission_scope")
            != PROFILED_ADMISSION_SCOPE_LOCAL_RESEARCH
            or result.metrics.get("local_research_non_promotable") is not True
            or result.metrics.get("external_witness_authenticated") is not False
        ):
            _fail("PROFILED_LOCAL_RESEARCH_TRAINING_SCOPE_INVALID")
        validations_after = tuple(
            validate_profiled_observation_example_for_local_research_v1(
                ledger=ledger,
                candidate=candidate,
                observation_time=authenticated_manifest.observation_time,
            )
            for candidate in candidates
        )
        if validations_after != validations_before:
            _fail("PROFILED_LOCAL_RESEARCH_CORPUS_REVALIDATION_FAILED")
        candidate_parameter_fingerprint = model_parameter_fingerprint(candidate_model)
        if (
            candidate_parameter_fingerprint == base_parameter_fingerprint
            or model_parameter_fingerprint(base_model) != base_parameter_fingerprint
            or _nonparameter_model_state_artifact(base_model)
            != base_nonparameter_state_artifact
            or deterministic_guard.restored is not True
        ):
            _fail("PROFILED_LOCAL_RESEARCH_MODEL_STATE_INVALID")
        training_result_artifact_sha256 = hashlib.sha256(
            _training_result_artifact(result)
        ).hexdigest()
        values: dict[str, Any] = {
            "schema_version": (
                LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION
            ),
            "status": LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_STATUS,
            "manifest_id": authenticated_manifest.manifest_id,
            "manifest_metadata_sha256": authenticated_manifest.metadata_sha256,
            "manifest_entry_chain_head_sha256": (
                authenticated_manifest.entry_chain_head_sha256
            ),
            "manifest_ordered_entry_identities_sha256": (
                authenticated_manifest.ordered_entry_identities_sha256
            ),
            "manifest_observation_time": authenticated_manifest.observation_time,
            "admitted_example_count": len(candidates),
            "ordered_example_fingerprints_sha256": (
                ordered_example_fingerprints_sha256
            ),
            "corpus_contract_sha256": corpus_contract_sha256,
            "authorization_key_id": authorization_key_id,
            "authorization_tag": authorization_tag,
            "authorization_receipt_sha256": authorization_receipt_sha256,
            "optimizer_implementation_artifact_sha256": (
                implementation_artifact_sha256
            ),
            "code_release_sha": code_release_sha,
            "deterministic_seed_material_sha256": (
                deterministic_seed_material_sha256
            ),
            "base_model_parameter_fingerprint": base_parameter_fingerprint,
            "candidate_model_parameter_fingerprint": (
                candidate_parameter_fingerprint
            ),
            "training_result_artifact_sha256": training_result_artifact_sha256,
            "training_rows": len(training_rows),
            "validation_rows": len(validation_rows),
            "loss_before": float(cast(float, result.loss_before)),
            "loss_after": float(cast(float, result.loss_after)),
            "weight_delta_norm": float(result.metrics["weight_delta_norm"]),
            "optimizer_execution_completed": True,
            "complete_corpus_revalidated_after_optimization": True,
            "base_model_unchanged": True,
            "isolated_candidate_model_created": True,
            "process_rng_state_restored": True,
            "deterministic_algorithms_enforced": True,
            "local_research_non_promotable": True,
            "external_witness_verified": False,
            **_AUTHORITY_FALSE,
            "_base_model_owner": base_model,
            "_candidate_model_owner": candidate_model,
            "_candidate_trainer_owner": candidate_trainer,
            "_factory_seal": _FactorySeal(mac=b"placeholder"),
            "_construction_token": _LOCAL_RESEARCH_RESULT_TOKEN,
        }
        material = _local_research_result_material(values)
        values["_factory_seal"] = _FactorySeal(
            mac=_seal_bytes(
                material,
                owner_ids=(id(base_model), id(candidate_model), id(candidate_trainer)),
            )
        )
        return LocallyAuthenticatedProfiledResearchOptimizerExecutionV1(**values)
    except AuthenticatedProfiledSupervisedOptimizerExecutionV1Error:
        _restore_failed_candidate_and_verify_base(
            base_model=base_model,
            base_parameter_fingerprint=base_parameter_fingerprint,
            base_nonparameter_state_artifact=base_nonparameter_state_artifact,
            candidate_model=candidate_model,
            rollback_state=rollback_state,
        )
        raise
    except Exception as exc:
        _restore_failed_candidate_and_verify_base(
            base_model=base_model,
            base_parameter_fingerprint=base_parameter_fingerprint,
            base_nonparameter_state_artifact=base_nonparameter_state_artifact,
            candidate_model=candidate_model,
            rollback_state=rollback_state,
        )
        raise AuthenticatedProfiledSupervisedOptimizerExecutionV1Error(
            f"PROFILED_LOCAL_RESEARCH_EXECUTION_FAILED:{type(exc).__name__}"
        ) from exc


def validate_locally_authenticated_profiled_research_execution_owner_v1(
    *,
    execution: LocallyAuthenticatedProfiledResearchOptimizerExecutionV1,
    candidate_model: V2HybridPolicyModel,
) -> None:
    if (
        type(execution) is not LocallyAuthenticatedProfiledResearchOptimizerExecutionV1
        or type(candidate_model) is not V2HybridPolicyModel
    ):
        _fail("PROFILED_LOCAL_RESEARCH_EXECUTION_OWNER_TYPES_INVALID")
    execution.__post_init__()
    if execution._candidate_model_owner is not candidate_model:
        _fail("PROFILED_LOCAL_RESEARCH_EXECUTION_OWNER_MISMATCH")


def revalidate_locally_authenticated_profiled_research_publication_boundary_v1(
    *,
    execution: LocallyAuthenticatedProfiledResearchOptimizerExecutionV1,
    base_model: V2HybridPolicyModel,
    candidate_model: V2HybridPolicyModel,
) -> None:
    """Recheck exact owners, policy bytes, source closure, and release pre-write."""

    if (
        type(execution) is not LocallyAuthenticatedProfiledResearchOptimizerExecutionV1
        or type(base_model) is not V2HybridPolicyModel
        or type(candidate_model) is not V2HybridPolicyModel
    ):
        _fail("PROFILED_LOCAL_RESEARCH_PUBLICATION_OWNER_TYPES_INVALID")
    execution.__post_init__()
    if (
        execution._base_model_owner is not base_model
        or execution._candidate_model_owner is not candidate_model
    ):
        _fail("PROFILED_LOCAL_RESEARCH_PUBLICATION_OWNER_MISMATCH")
    if (
        model_parameter_fingerprint(base_model)
        != execution.base_model_parameter_fingerprint
        or model_parameter_fingerprint(candidate_model)
        != execution.candidate_model_parameter_fingerprint
    ):
        _fail("PROFILED_LOCAL_RESEARCH_PUBLICATION_MODEL_DRIFT")
    if (
        hashlib.sha256(_source_artifact()).hexdigest()
        != execution.optimizer_implementation_artifact_sha256
        or _code_release_sha() != execution.code_release_sha
    ):
        _fail("PROFILED_LOCAL_RESEARCH_PUBLICATION_RELEASE_DRIFT")


def validate_authenticated_profiled_supervised_optimizer_execution_owner_v1(
    *,
    execution: AuthenticatedProfiledSupervisedOptimizerExecutionV1,
    candidate_model: V2HybridPolicyModel,
) -> None:
    """Revalidate the exact in-process candidate model owned by an execution."""

    if (
        type(execution) is not AuthenticatedProfiledSupervisedOptimizerExecutionV1
        or type(candidate_model) is not V2HybridPolicyModel
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_OWNER_TYPES_INVALID")
    execution.__post_init__()
    if execution._candidate_model_owner is not candidate_model:
        _fail("PROFILED_SUPERVISED_EXECUTION_CANDIDATE_MODEL_OWNER_MISMATCH")


def revalidate_authenticated_profiled_supervised_optimizer_publication_boundary_v1(
    *,
    execution: AuthenticatedProfiledSupervisedOptimizerExecutionV1,
    base_model: V2HybridPolicyModel,
    candidate_model: V2HybridPolicyModel,
) -> None:
    """Revalidate exact owners, source closure, and release before persistence."""

    if (
        type(execution) is not AuthenticatedProfiledSupervisedOptimizerExecutionV1
        or type(base_model) is not V2HybridPolicyModel
        or type(candidate_model) is not V2HybridPolicyModel
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_PUBLICATION_OWNER_TYPES_INVALID")
    execution.__post_init__()
    if execution._base_model_owner is not base_model:
        _fail("PROFILED_SUPERVISED_EXECUTION_BASE_MODEL_OWNER_MISMATCH")
    if execution._candidate_model_owner is not candidate_model:
        _fail("PROFILED_SUPERVISED_EXECUTION_CANDIDATE_MODEL_OWNER_MISMATCH")
    current_implementation_artifact_sha256 = hashlib.sha256(
        _source_artifact()
    ).hexdigest()
    if (
        current_implementation_artifact_sha256
        != execution.optimizer_implementation_artifact_sha256
        or _code_release_sha() != execution.code_release_sha
    ):
        _fail("PROFILED_SUPERVISED_EXECUTION_PUBLICATION_RELEASE_DRIFT")


__all__ = (
    "AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION",
    "AUTHENTICATED_PROFILED_SUPERVISED_OPTIMIZER_EXECUTION_V1_STATUS",
    "LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_SCHEMA_VERSION",
    "LOCALLY_AUTHENTICATED_PROFILED_RESEARCH_OPTIMIZER_EXECUTION_V1_STATUS",
    "LOCAL_PROFILED_RESEARCH_AUTHORIZATION_DOMAIN",
    "AuthenticatedProfiledSupervisedOptimizerExecutionV1",
    "AuthenticatedProfiledSupervisedOptimizerExecutionV1Error",
    "LocallyAuthenticatedProfiledResearchOptimizerExecutionV1",
    "execute_authenticated_profiled_supervised_optimizer_v1",
    "execute_locally_authenticated_profiled_research_optimizer_v1",
    "revalidate_authenticated_profiled_supervised_optimizer_publication_boundary_v1",
    "revalidate_locally_authenticated_profiled_research_publication_boundary_v1",
    "validate_authenticated_profiled_supervised_optimizer_execution_owner_v1",
    "validate_locally_authenticated_profiled_research_execution_owner_v1",
)
