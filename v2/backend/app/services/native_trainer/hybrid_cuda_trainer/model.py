"""Lazy-torch PPO/MASA model for V2 paper/shadow CUDA training."""
from __future__ import annotations

import ast
import hashlib
import importlib
import json
import math
import os
import random
import struct
import tempfile
import zipfile
from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Sequence

from .confidence import (
    CONFIDENCE_HEAD_ACTION_INDEX,
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    calibrate_confidence,
    normalize_calibration_state,
    resolve_confidence_temperature,
    softmax,
    unfitted_calibration_state,
)
from .config import ACTION_COUNT, ACTION_LABELS, MODEL_SOURCE
from .masa import V2MASAAdapter
from .tensor_builder import FeatureTensorRecord

TRAINER_CUDA_MEMORY_CAP_BYTES = 12 * 1024 * 1024 * 1024
TRAINER_CUDA_MEMORY_CAP_FRACTION = 0.75

_WEIGHT_BLOB_REQUIRED_METADATA_KEYS = frozenset(
    {
        "__format_version",
        "__input_dim",
        "__seed",
        "__torch_available",
        "__confidence_head_schema_version",
        "__confidence_head_actions_json",
        "__confidence_calibration_state_json",
    }
)
_WEIGHT_BLOB_FEATURE_ABI_KEY = "__checkpoint_feature_abi_binding_v4_json"
_WEIGHT_BLOB_FALLBACK_KEY = "fallback::weights"

# Immutable parser/allocation bounds for explicitly declared v4 checkpoint
# artifacts. They are process-integrity constraints, not market thresholds.
MAX_V4_NPZ_MEMBER_COUNT = 512
MAX_V4_NPZ_MEMBER_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_V4_NPZ_AGGREGATE_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_V4_NPZ_COMPRESSION_RATIO = 200
MAX_V4_NPY_HEADER_BYTES = 64 * 1024
MAX_V4_NPY_DIMENSIONS = 8


def _checkpoint_feature_abi_v4_module() -> Any:
    """Import the optional registry-bound contract only after explicit opt-in."""

    return importlib.import_module(
        "v2.backend.app.services.native_trainer.checkpoint_feature_abi_binding_v4"
    )


def _npy_descr_itemsize(descr: object) -> int:
    if type(descr) is not str or not descr:
        raise ValueError("checkpoint_npy_dtype_invalid")
    text = descr
    if text[0] in "<>=|":
        text = text[1:]
    if len(text) < 2 or text[0] not in "?biufcSU":
        raise ValueError("checkpoint_npy_dtype_invalid")
    try:
        width = int(text[1:])
    except ValueError as exc:
        raise ValueError("checkpoint_npy_dtype_invalid") from exc
    if width <= 0:
        raise ValueError("checkpoint_npy_dtype_invalid")
    if text[0] == "U":
        width *= 4
    if width > MAX_V4_NPZ_MEMBER_UNCOMPRESSED_BYTES:
        raise ValueError("checkpoint_npy_dtype_allocation_bound_exceeded")
    return width


def _strict_npy_header(stream: BinaryIO, *, member_size: int) -> None:
    magic = stream.read(8)
    if len(magic) != 8 or magic[:6] != b"\x93NUMPY":
        raise ValueError("checkpoint_npy_magic_invalid")
    version = (magic[6], magic[7])
    if version == (1, 0):
        raw_length = stream.read(2)
        if len(raw_length) != 2:
            raise ValueError("checkpoint_npy_header_truncated")
        header_length = struct.unpack("<H", raw_length)[0]
        prefix_bytes = 10
        encoding = "latin1"
    elif version in {(2, 0), (3, 0)}:
        raw_length = stream.read(4)
        if len(raw_length) != 4:
            raise ValueError("checkpoint_npy_header_truncated")
        header_length = struct.unpack("<I", raw_length)[0]
        prefix_bytes = 12
        encoding = "utf-8" if version == (3, 0) else "latin1"
    else:
        raise ValueError("checkpoint_npy_version_unsupported")
    if (
        header_length <= 0
        or header_length > MAX_V4_NPY_HEADER_BYTES
        or prefix_bytes + header_length > member_size
    ):
        raise ValueError("checkpoint_npy_header_size_invalid")
    raw_header = stream.read(header_length)
    if len(raw_header) != header_length:
        raise ValueError("checkpoint_npy_header_truncated")
    try:
        header = ast.literal_eval(raw_header.decode(encoding))
    except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError("checkpoint_npy_header_invalid") from exc
    if type(header) is not dict or frozenset(header) != {
        "descr",
        "fortran_order",
        "shape",
    }:
        raise ValueError("checkpoint_npy_header_fields_invalid")
    if type(header["fortran_order"]) is not bool:
        raise ValueError("checkpoint_npy_fortran_order_invalid")
    shape = header["shape"]
    if type(shape) is not tuple or len(shape) > MAX_V4_NPY_DIMENSIONS:
        raise ValueError("checkpoint_npy_shape_invalid")
    element_count = 1
    for dimension in shape:
        if type(dimension) is not int or dimension < 0:
            raise ValueError("checkpoint_npy_shape_invalid")
        if dimension and element_count > (
            MAX_V4_NPZ_MEMBER_UNCOMPRESSED_BYTES // dimension
        ):
            raise ValueError("checkpoint_npy_shape_allocation_bound_exceeded")
        element_count *= dimension
    itemsize = _npy_descr_itemsize(header["descr"])
    if element_count > (
        MAX_V4_NPZ_MEMBER_UNCOMPRESSED_BYTES // itemsize
    ):
        raise ValueError("checkpoint_npy_shape_allocation_bound_exceeded")
    expected_size = prefix_bytes + header_length + (element_count * itemsize)
    if expected_size != member_size:
        raise ValueError("checkpoint_npy_payload_size_mismatch")


def _strict_npz_member_keys(source: BinaryIO) -> tuple[str, ...]:
    """Preflight a declared-v4 NPZ completely before any NumPy access."""

    source.seek(0)
    try:
        with zipfile.ZipFile(source, mode="r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_V4_NPZ_MEMBER_COUNT:
                raise ValueError("checkpoint_npz_member_count_invalid")
            member_names = [info.filename for info in infos]
            if len(member_names) != len(set(member_names)):
                raise ValueError("checkpoint_npz_duplicate_zip_members")
            aggregate_uncompressed = 0
            aggregate_compressed = 0
            keys: list[str] = []
            allowed_flag_bits = 0x08 | 0x800
            allowed_compression = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
            for info in infos:
                name = info.filename
                if (
                    type(name) is not str
                    or not name.isascii()
                    or name.startswith("/")
                    or "/" in name
                    or "\\" in name
                    or not name.endswith(".npy")
                    or len(name) <= 4
                ):
                    raise ValueError("checkpoint_npz_zip_member_name_invalid")
                if (
                    info.is_dir()
                    or info.flag_bits & 0x1
                    or info.flag_bits & ~allowed_flag_bits
                    or info.compress_type not in allowed_compression
                ):
                    raise ValueError("checkpoint_npz_zip_member_flags_invalid")
                if (
                    info.file_size <= 0
                    or info.file_size > MAX_V4_NPZ_MEMBER_UNCOMPRESSED_BYTES
                    or info.compress_size <= 0
                ):
                    raise ValueError("checkpoint_npz_member_size_invalid")
                if (
                    info.file_size
                    > info.compress_size * MAX_V4_NPZ_COMPRESSION_RATIO
                ):
                    raise ValueError("checkpoint_npz_compression_ratio_exceeded")
                aggregate_uncompressed += info.file_size
                aggregate_compressed += info.compress_size
                if (
                    aggregate_uncompressed
                    > MAX_V4_NPZ_AGGREGATE_UNCOMPRESSED_BYTES
                    or aggregate_uncompressed
                    > aggregate_compressed * MAX_V4_NPZ_COMPRESSION_RATIO
                ):
                    raise ValueError("checkpoint_npz_aggregate_size_invalid")
                with archive.open(info, mode="r") as member:
                    _strict_npy_header(member, member_size=info.file_size)
                keys.append(name[:-4])
            if len(keys) != len(set(keys)):
                raise ValueError("checkpoint_npz_duplicate_keys")
            return tuple(keys)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError("checkpoint_npz_zip_invalid") from exc
    finally:
        source.seek(0)


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("checkpoint_npz_json_duplicate_key")
        parsed[key] = value
    return parsed


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"checkpoint_npz_json_constant_forbidden:{value}")


def _strict_npz_json(value: str) -> Any:
    parsed = json.loads(
        value,
        object_pairs_hook=_reject_duplicate_json_pairs,
        parse_constant=_reject_json_constant,
    )
    canonical = json.dumps(
        parsed,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if value != canonical:
        raise ValueError("checkpoint_npz_json_not_canonical")
    return parsed


def _strict_npz_scalar_text(data: Any, key: str) -> str:
    if key not in data.files:
        raise ValueError(f"checkpoint_npz_metadata_missing:{key}")
    values = data[key]
    if tuple(values.shape) != (1,) or values.dtype.kind != "U":
        raise ValueError(f"checkpoint_npz_metadata_scalar_text_invalid:{key}")
    return str(values[0])


def _strict_npz_scalar_int64(data: Any, key: str) -> int:
    if key not in data.files:
        raise ValueError(f"checkpoint_npz_metadata_missing:{key}")
    values = data[key]
    if tuple(values.shape) != (1,) or str(values.dtype) != "int64":
        raise ValueError(f"checkpoint_npz_metadata_scalar_int64_invalid:{key}")
    return int(values[0])


class ConfidenceHeadCheckpointIncompatibleError(ValueError):
    """A checkpoint cannot supply the action-conditioned confidence contract."""

# WI-1 Step 4c: process-lifetime rolling prediction-window registries. The resident
# runtime builds a FRESH V2HybridPolicyModel every cycle, so these must outlive model
# instances or the temporal encoder only ever sees a repeated single frame at predict
# time. Keyed by (input_dim, seq_len) -> {(symbol, timeframe): deque/frame-id}.
_TEMPORAL_PREDICT_BUFFERS: dict[tuple[int, int], dict[tuple[str, str], deque]] = {}
_TEMPORAL_PREDICT_LAST_ID: dict[tuple[int, int], dict[tuple[str, str], Any]] = {}


def reset_temporal_predict_registry() -> None:
    """Clear the process-lifetime prediction-window registries (tests/tools)."""
    _TEMPORAL_PREDICT_BUFFERS.clear()
    _TEMPORAL_PREDICT_LAST_ID.clear()


@dataclass(frozen=True)
class ModelForwardResult:
    model_id: str
    model_source: str
    action_logits: tuple[float, ...]
    action_probabilities: tuple[float, ...]
    selected_action_index: int
    selected_action: str
    expected_move_bps: float
    confidence_raw: float
    confidence_calibrated: float
    policy_value: float
    masa_signal: float
    calibration: dict
    device: str
    cuda_active: bool
    model_tensors_device_verified: bool


class V2HybridPolicyModel:
    """Shared encoder with PPO, value, expected-move, confidence, MASA heads."""

    def __init__(
        self,
        *,
        input_dim: int,
        seed: int = 0xC0DE_55,
        checkpoint_feature_abi_binding: object | None = None,
    ) -> None:
        if checkpoint_feature_abi_binding is None:
            # Preserve the pre-v4 constructor contract for every ordinary
            # runtime, including NumPy integer inputs.
            self.input_dim = int(input_dim)
        else:
            if type(input_dim) is not int or input_dim <= 0:
                raise ValueError("model_input_dim_must_be_builtin_positive_int")
            self.input_dim = input_dim
        self.seed = int(seed)
        self._checkpoint_feature_abi_binding_json: str | None = None
        if checkpoint_feature_abi_binding is not None:
            binding_module = _checkpoint_feature_abi_v4_module()
            verification = binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
                checkpoint_feature_abi_binding,
                checkpoint_input_dim=self.input_dim,
            )
            if (
                verification["binding_sha256"]
                != binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
            ):
                raise ValueError("checkpoint_feature_abi_binding_mismatch")
            self._checkpoint_feature_abi_binding_json = (
                binding_module.canonical_deployed_checkpoint_feature_abi_binding_v4_json()
            )
        # Legacy-trainer alignment: the legacy hybrid trainer saturated the RTX
        # GPU with a much larger encoder (LSTM 512x2 + attention backbone).
        # Width/depth are env-tunable so capacity can scale with the 1.7M-row
        # replay archive; an architecture change invalidates old weight blobs,
        # which the checkpoint manager handles as a graceful fresh init.
        self.hidden_size = max(128, int(os.getenv("V2_TRAINER_HIDDEN_SIZE", "1024") or 1024))
        self.residual_block_count = max(1, int(os.getenv("V2_TRAINER_RESIDUAL_BLOCKS", "3") or 3))
        # Dropout is env-tunable regularization. Raised from 0.05 -> 0.10 default to
        # counter the observed train/serve overfit gap (in-sample backtest edge that
        # collapses out-of-sample). Set V2_TRAINER_DROPOUT=0.05 to restore prior value.
        self.dropout = max(0.0, min(0.9, float(os.getenv("V2_TRAINER_DROPOUT", "0.10") or 0.10)))
        # Optional GPU-parallel multi-head attention encoder over the model_vector's
        # four blocks (values / missing_mask / stale_mask / source_availability). It
        # lets the policy learn quality-aware feature weighting (attend to reliable
        # features, down-weight missing/stale) -- partial legacy attention parity --
        # and adds GPU work per step. Off by default so the existing residual-MLP
        # path is byte-for-byte unchanged; only enabled when input_dim splits evenly
        # into the 4 blocks. Note: this is SPATIAL/quality attention, not temporal
        # memory (V2's input carries no time dimension yet).
        self.attention_encoder_enabled = (
            str(os.getenv("V2_TRAINER_ATTENTION_ENCODER", "") or "").strip().lower()
            in {"1", "true", "yes", "on"}
            and self.input_dim % 4 == 0
        )
        requested_attention_heads = max(1, int(os.getenv("V2_TRAINER_ATTENTION_HEADS", "4") or 4))
        self.attention_heads = (
            self._effective_attention_heads(self.input_dim, requested_attention_heads)
            if self.attention_encoder_enabled
            else requested_attention_heads
        )
        # Optional GRU TEMPORAL encoder over a no-lookahead window of recent frames.
        # Crypto is temporal and the single-frame input caps edge -- the offline
        # edge-proof (v2_trainer_temporal_edge_proof) showed a GRU over a 16-frame
        # window lifts win-rate 53%->60% and doubles Sortino vs the single frame.
        # Additive + arch-forked; OFF by default so the single-frame path is
        # byte-for-byte unchanged. The net accepts either a 2D (B,input_dim) single
        # frame or a 3D (B,T,input_dim) window; the temporal embedding is fused only
        # when enabled and a window is supplied.
        self.temporal_encoder = str(os.getenv("V2_TRAINER_TEMPORAL_ENCODER", "") or "").strip().lower()
        self.temporal_encoder_enabled = self.temporal_encoder in {"gru"}
        self.temporal_seq_len = max(2, int(os.getenv("V2_TRAINER_TEMPORAL_SEQ_LEN", "16") or 16))
        self.temporal_hidden = max(32, int(os.getenv("V2_TRAINER_TEMPORAL_HIDDEN", "256") or 256))
        self.temporal_proj_dim = max(32, int(os.getenv("V2_TRAINER_TEMPORAL_PROJ_DIM", "256") or 256))
        # WI-1 Step 4c: online per-(symbol,timeframe) rolling window of recent frames
        # for the PREDICTION path (training builds windows from the batch; live/paper
        # inference sees one frame at a time). Feeds the same no-lookahead (B,T,F)
        # window the GRU was trained on. Only populated when temporal is enabled; the
        # single-frame path is byte-identical. Deduped by frame id (cycles re-present
        # the same latest snapshot) so a repeated frame never double-fills the window.
        # PROCESS-LIFETIME registry, NOT per-instance: the resident runtime constructs
        # a FRESH model every cycle (runtime.run_hybrid_trainer_cycle), so an
        # instance-held buffer would reset each cycle and the GRU would only ever see
        # a degenerate repeated-frame window at prediction time (train/serve skew).
        # Keyed by (input_dim, seq_len) so different architectures never mix frames.
        self._temporal_predict_buffers = _TEMPORAL_PREDICT_BUFFERS.setdefault(
            (int(input_dim), int(self.temporal_seq_len)), {}
        )
        self._temporal_predict_last_id = _TEMPORAL_PREDICT_LAST_ID.setdefault(
            (int(input_dim), int(self.temporal_seq_len)), {}
        )
        self._torch = None
        self._net = None
        self._device = "cpu"
        # The attention flag is part of the architecture identity so enabling it
        # starts a fresh checkpoint lineage (the checkpoint manager handles the
        # input-shape/arch change as a graceful fresh init). When attention is off
        # or cannot activate, preserve the legacy identity so compatible checkpoints
        # remain loadable.
        arch_identity = f"{input_dim}|{seed}|{self.hidden_size}|{self.residual_block_count}"
        # The former scalar confidence head was not conditioned on the selected
        # action. Fork the architecture identity so its weights can never be
        # silently restored or broadcast into the directional per-action head.
        arch_identity += f"|confidence={CONFIDENCE_HEAD_SCHEMA_VERSION}"
        if self.attention_encoder_enabled:
            arch_identity += f"|attn=1x{self.attention_heads}"
        if self.temporal_encoder_enabled:
            arch_identity += f"|temporal={self.temporal_encoder}x{self.temporal_hidden}p{self.temporal_proj_dim}"
        if self._checkpoint_feature_abi_binding_json is not None:
            binding_module = _checkpoint_feature_abi_v4_module()
            arch_identity += (
                "|checkpoint_feature_abi="
                f"{binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256}"
            )
        self._model_id = "v2_hybrid_policy_" + hashlib.sha256(
            arch_identity.encode()
        ).hexdigest()[:24]
        self._fallback_weights = self._make_fallback_weights()
        self._confidence_calibration_state = unfitted_calibration_state(
            "MODEL_CHECKPOINT_CALIBRATION_NOT_LOADED"
        )
        self._masa = V2MASAAdapter()
        self._init_torch_if_available()

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def checkpoint_feature_abi_declaration(self) -> dict[str, object] | None:
        """Return the optional audit-only input ABI declared by this model.

        A declaration constrains checkpoint artifact compatibility only. It is
        not evidence about tensor values, resolved sources, receipts, clocks,
        trainer admission, or prediction authorization.
        """

        if self._checkpoint_feature_abi_binding_json is None:
            return None
        binding_module = _checkpoint_feature_abi_v4_module()
        verification = binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
            self._checkpoint_feature_abi_binding_json,
            checkpoint_input_dim=self.input_dim,
        )
        if (
            verification["binding_sha256"]
            != binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
        ):
            raise ValueError("checkpoint_feature_abi_binding_mismatch")
        return binding_module.deployed_checkpoint_feature_abi_binding_v4()

    @property
    def confidence_calibration_state(self) -> dict[str, Any]:
        return dict(self._confidence_calibration_state)

    def set_confidence_calibration_state(
        self,
        state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Bind a validated train-only calibration state to these weights."""
        normalized = normalize_calibration_state(state)
        if normalized.get("fitted") is True:
            if not self.torch_available:
                normalized = unfitted_calibration_state(
                    "CPU_FALLBACK_HAS_NO_PROFITABILITY_CONFIDENCE_HEAD"
                )
            else:
                try:
                    from .on_policy_behavior import (  # noqa: PLC0415
                        model_parameter_fingerprint,
                    )

                    actual_fingerprint = model_parameter_fingerprint(self)
                except Exception:
                    normalized = unfitted_calibration_state(
                        "MODEL_PARAMETER_FINGERPRINT_UNAVAILABLE"
                    )
                else:
                    claimed_fingerprint = normalized.get(
                        "model_parameter_fingerprint"
                    )
                    if (
                        claimed_fingerprint not in (None, "")
                        and claimed_fingerprint != actual_fingerprint
                    ):
                        normalized = unfitted_calibration_state(
                            "CHECKPOINT_CALIBRATION_MODEL_FINGERPRINT_MISMATCH"
                        )
                    else:
                        normalized["model_parameter_fingerprint"] = (
                            actual_fingerprint
                        )
        self._confidence_calibration_state = normalized
        return dict(normalized)

    @property
    def device(self) -> str:
        return self._device

    @property
    def cuda_active(self) -> bool:
        return self._device.startswith("cuda") and self.model_tensors_device_verified()

    @property
    def torch_available(self) -> bool:
        return self._torch is not None and self._net is not None

    @property
    def net(self) -> Any:
        return self._net

    @property
    def torch(self) -> Any:
        return self._torch

    @staticmethod
    def _effective_attention_heads(input_dim: int, requested_heads: int) -> int:
        if int(input_dim) % 4 != 0:
            return max(1, int(requested_heads))
        block_dim = int(input_dim) // 4
        heads = max(1, int(requested_heads))
        while heads > 1 and block_dim % heads != 0:
            heads -= 1
        return heads

    def _init_torch_if_available(self) -> None:
        try:
            torch = importlib.import_module("torch")
        except Exception:
            return
        try:
            torch.manual_seed(self.seed)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            if device.type == "cuda":
                self._apply_cuda_memory_cap(torch)
                # Legacy-trainer CUDA alignment (legacy_reference/rl/hybrid_trainer.py
                # GPUForcedPPO init): TF32 matmul via the PyTorch 2.9+ API with
                # legacy setters for older builds, cuDNN autotune for fixed input
                # shapes, flash/mem-efficient SDP, and more CPU threads for the
                # data-prep side that currently bottlenecks the GPU.
                try:
                    torch.set_float32_matmul_precision("high")
                    if hasattr(torch.backends.cuda.matmul, "fp32_precision"):
                        torch.backends.cuda.matmul.fp32_precision = "tf32"
                    if hasattr(torch.backends.cudnn, "conv") and hasattr(
                        torch.backends.cudnn.conv, "fp32_precision"
                    ):
                        torch.backends.cudnn.conv.fp32_precision = "tf32"
                    torch.backends.cuda.matmul.allow_tf32 = True
                    torch.backends.cudnn.allow_tf32 = True
                    torch.backends.cudnn.benchmark = True
                    torch.backends.cudnn.deterministic = False
                    if hasattr(torch.backends.cuda, "enable_flash_sdp"):
                        torch.backends.cuda.enable_flash_sdp(True)
                    if hasattr(torch.backends.cuda, "enable_mem_efficient_sdp"):
                        torch.backends.cuda.enable_mem_efficient_sdp(True)
                    torch.set_num_threads(
                        max(4, int(os.getenv("V2_TRAINER_CPU_THREADS", "8") or 8))
                    )
                except Exception:
                    pass

            class _ResidualBlock(torch.nn.Module):
                def __init__(self, hidden: int, dropout: float) -> None:
                    super().__init__()
                    self.net = torch.nn.Sequential(
                        torch.nn.Linear(hidden, hidden),
                        torch.nn.LayerNorm(hidden),
                        torch.nn.GELU(),
                        torch.nn.Dropout(dropout),
                        torch.nn.Linear(hidden, hidden),
                        torch.nn.LayerNorm(hidden),
                    )
                    self.activation = torch.nn.GELU()

                def forward(self, x):
                    return self.activation(x + self.net(x))

            class _HybridNet(torch.nn.Module):
                def __init__(
                    self,
                    input_dim: int,
                    hidden: int,
                    residual_blocks: int,
                    dropout: float,
                    attention_enabled: bool = False,
                    attention_heads: int = 4,
                    temporal_enabled: bool = False,
                    temporal_hidden: int = 256,
                    temporal_proj_dim: int = 256,
                ) -> None:
                    super().__init__()
                    # GRU temporal encoder over a no-lookahead window. Additive; only
                    # built + applied when enabled AND the input is a 3D window, so the
                    # 2D single-frame path is byte-identical to the prior model.
                    self.temporal_enabled = bool(temporal_enabled)
                    if self.temporal_enabled:
                        # Project each frame to a small dim BEFORE the GRU. GRU cost
                        # scales with input width, and full 1248-dim frames make it
                        # ~20x slower than single-frame (1.1 steps/s); a 256-d
                        # projection keeps the temporal signal while making the
                        # model trainable to convergence.
                        proj_dim = max(32, int(temporal_proj_dim))
                        self.temporal_input_proj = torch.nn.Sequential(
                            torch.nn.Linear(input_dim, proj_dim),
                            torch.nn.LayerNorm(proj_dim),
                            torch.nn.GELU(),
                        )
                        self.temporal_gru = torch.nn.GRU(
                            proj_dim, int(temporal_hidden), num_layers=1, batch_first=True
                        )
                        self.temporal_fuse = torch.nn.Sequential(
                            torch.nn.Linear(int(temporal_hidden), hidden),
                            torch.nn.LayerNorm(hidden),
                            torch.nn.GELU(),
                        )
                    # GPU-parallel multi-head attention over the 4 model_vector
                    # blocks (values/missing/stale/source). Additive pre-encoder;
                    # only built + applied when enabled, so the disabled path is
                    # identical to the prior residual-MLP model.
                    self.attention_enabled = bool(attention_enabled) and input_dim % 4 == 0
                    if self.attention_enabled:
                        self.block_count = 4
                        self.block_dim = input_dim // 4
                        heads = max(1, int(attention_heads))
                        while heads > 1 and self.block_dim % heads != 0:
                            heads -= 1
                        self.attn = torch.nn.MultiheadAttention(
                            self.block_dim, num_heads=heads, dropout=dropout, batch_first=True
                        )
                        self.attn_norm = torch.nn.LayerNorm(self.block_dim)
                        self.attn_ffn = torch.nn.Sequential(
                            torch.nn.Linear(self.block_dim, self.block_dim),
                            torch.nn.GELU(),
                            torch.nn.Dropout(dropout),
                            torch.nn.Linear(self.block_dim, self.block_dim),
                        )
                        self.attn_ffn_norm = torch.nn.LayerNorm(self.block_dim)
                    self.input_projection = torch.nn.Sequential(
                        torch.nn.Linear(input_dim, hidden),
                        torch.nn.LayerNorm(hidden),
                        torch.nn.GELU(),
                    )
                    self.residual_blocks = torch.nn.ModuleList(
                        [_ResidualBlock(hidden, dropout) for _ in range(max(1, int(residual_blocks)))]
                    )
                    self.encoder_norm = torch.nn.LayerNorm(hidden)
                    self.policy_head = torch.nn.Linear(hidden, ACTION_COUNT)
                    self.value_head = torch.nn.Linear(hidden, 1)
                    self.expected_move_head = torch.nn.Linear(hidden, 1)
                    self.confidence_head = torch.nn.Linear(
                        hidden,
                        len(CONFIDENCE_HEAD_ACTIONS),
                    )
                    self.masa_head = torch.nn.Linear(hidden, 1)

                @staticmethod
                def _normalize(x):
                    x = torch.nan_to_num(x, nan=0.0, posinf=1_000_000.0, neginf=-1_000_000.0)
                    return torch.sign(x) * torch.log1p(torch.clamp(torch.abs(x), max=1_000_000.0))

                def forward(self, x):
                    # Accept a 2D single frame (B, input_dim) or a 3D no-lookahead
                    # window (B, T, input_dim). Normalise once; the temporal encoder
                    # consumes the whole window, the single-frame path the last frame.
                    temporal_emb = None
                    if x.dim() == 3:
                        window = self._normalize(x)
                        if self.temporal_enabled:
                            gru_out, _ = self.temporal_gru(self.temporal_input_proj(window))
                            temporal_emb = gru_out[:, -1, :]
                        x = window[:, -1, :]
                    else:
                        x = self._normalize(x)
                    if self.attention_enabled:
                        b = x.shape[0]
                        seq = x.view(b, self.block_count, self.block_dim)
                        attn_out, _ = self.attn(seq, seq, seq, need_weights=False)
                        seq = self.attn_norm(seq + attn_out)
                        seq = self.attn_ffn_norm(seq + self.attn_ffn(seq))
                        x = seq.reshape(b, -1)
                    h = self.input_projection(x)
                    if temporal_emb is not None:
                        h = h + self.temporal_fuse(temporal_emb)
                    for block in self.residual_blocks:
                        h = block(h)
                    h = self.encoder_norm(h)
                    return {
                        "logits": self.policy_head(h),
                        "value": self.value_head(h).squeeze(-1),
                        "expected_move": 120.0 * torch.tanh(self.expected_move_head(h).squeeze(-1)),
                        "confidence_by_direction": torch.sigmoid(
                            self.confidence_head(h)
                        ),
                        "masa": torch.tanh(self.masa_head(h).squeeze(-1)),
                    }

            self._torch = torch
            self._net = _HybridNet(
                self.input_dim,
                hidden=self.hidden_size,
                residual_blocks=self.residual_block_count,
                dropout=self.dropout,
                attention_enabled=self.attention_encoder_enabled,
                attention_heads=self.attention_heads,
                temporal_enabled=self.temporal_encoder_enabled,
                temporal_hidden=self.temporal_hidden,
                temporal_proj_dim=self.temporal_proj_dim,
            ).to(device)
            self._device = str(next(self._net.parameters()).device)
        except Exception:
            self._torch = None
            self._net = None
            self._device = "cpu"

    @staticmethod
    def _apply_cuda_memory_cap(torch: Any) -> None:
        try:
            props = torch.cuda.get_device_properties(0)
            total_memory = float(getattr(props, "total_memory", 0.0) or 0.0)
            if total_memory <= 0.0:
                return
            fraction = min(TRAINER_CUDA_MEMORY_CAP_FRACTION, TRAINER_CUDA_MEMORY_CAP_BYTES / total_memory)
            fraction = max(0.01, min(TRAINER_CUDA_MEMORY_CAP_FRACTION, fraction))
            torch.cuda.set_per_process_memory_fraction(float(fraction), 0)
        except Exception:
            return

    def _make_fallback_weights(self) -> list[float]:
        rng = random.Random(self.seed)
        return [rng.gauss(0.0, 0.08) for _ in range(self.input_dim * ACTION_COUNT)]

    @staticmethod
    def _expected_move_aligned_policy(probs: Sequence[float], expected_move_bps: float) -> tuple[tuple[float, ...], int]:
        adjusted = [max(0.0, float(p)) for p in probs]
        if len(adjusted) != ACTION_COUNT:
            adjusted = [1.0 / ACTION_COUNT for _ in range(ACTION_COUNT)]
        raw_opening = adjusted[: min(3, ACTION_COUNT)]
        while len(raw_opening) < 3:
            raw_opening.append(0.0)
        policy_opening_index = max(range(3), key=lambda index: raw_opening[index])
        directional_strength = min(0.55, abs(float(expected_move_bps)) / 120.0)
        selected_index: int
        if expected_move_bps >= 4.0:
            adjusted[1] *= 1.0 + directional_strength
            adjusted[2] *= max(0.1, 1.0 - directional_strength)
            selected_index = 1 if policy_opening_index == 1 else 0
        elif expected_move_bps <= -4.0:
            adjusted[2] *= 1.0 + directional_strength
            adjusted[1] *= max(0.1, 1.0 - directional_strength)
            selected_index = 2 if policy_opening_index == 2 else 0
        else:
            adjusted[0] += 0.25
            adjusted[1] *= 0.75
            adjusted[2] *= 0.75
            selected_index = 0
        adjusted[selected_index] = max(adjusted[selected_index], max(adjusted[:3]) + 1e-6)
        total = sum(adjusted)
        if total <= 0:
            adjusted = [1.0 / ACTION_COUNT for _ in range(ACTION_COUNT)]
        else:
            adjusted = [p / total for p in adjusted]
        return tuple(float(p) for p in adjusted), int(selected_index)

    def model_tensors_device_verified(self) -> bool:
        if self._torch is None or self._net is None:
            return False
        try:
            devices = {str(p.device) for p in self._net.parameters()}
            return bool(devices) and devices == {self._device}
        except Exception:
            return False

    def architecture_status(self) -> dict[str, Any]:
        return {
            "shared_feature_encoder": True,
            "hidden_size": self.hidden_size,
            "residual_block_count": self.residual_block_count,
            "dropout": self.dropout,
            "ppo_policy_head": True,
            "value_head": True,
            "expected_move_head": True,
            "confidence_head": True,
            "confidence_head_action_conditioned": True,
            "confidence_head_schema_version": CONFIDENCE_HEAD_SCHEMA_VERSION,
            "confidence_head_action_labels": list(CONFIDENCE_HEAD_ACTIONS),
            "confidence_head_output_count": len(CONFIDENCE_HEAD_ACTIONS),
            "masa_auxiliary_head": True,
            "masa_adapter_blend": True,
            "action_count": ACTION_COUNT,
            # WI-1 temporal encoder truth for status/GUI surfaces (empty string
            # + enabled=False when the single-frame path is active).
            "temporal_encoder": self.temporal_encoder if self.temporal_encoder_enabled else "",
            "temporal_encoder_enabled": bool(self.temporal_encoder_enabled),
            "temporal_seq_len": int(self.temporal_seq_len) if self.temporal_encoder_enabled else 0,
            "input_dim": int(self.input_dim),
        }

    def _mutable_state_snapshot(
        self,
        *,
        include_model_parameters: bool = True,
    ) -> dict[str, Any]:
        state: dict[str, Any] = {
            "confidence_calibration_state": deepcopy(
                self._confidence_calibration_state
            ),
            "fallback_weights": tuple(self._fallback_weights),
            "torch_state": None,
            "torch_training": (
                bool(self._net.training) if self._net is not None else None
            ),
        }
        if (
            include_model_parameters
            and self._torch is not None
            and self._net is not None
        ):
            state["torch_state"] = {
                # Keep rollback state off the accelerator. Cloning a deployed
                # checkpoint-sized model on GPU can itself exhaust the device
                # before restoration begins.
                name: tensor.detach().cpu().clone()
                for name, tensor in self._net.state_dict().items()
            }
        return state

    def _restore_mutable_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        torch_state = snapshot.get("torch_state")
        if torch_state is not None:
            if self._net is None:
                raise RuntimeError("checkpoint_model_rollback_net_unavailable")
            self._net.load_state_dict(torch_state, strict=True)
            self._net.train(bool(snapshot.get("torch_training")))
        self._fallback_weights = list(snapshot["fallback_weights"])
        self._confidence_calibration_state = deepcopy(
            snapshot["confidence_calibration_state"]
        )

    def save_weight_blob(self, path: Path) -> dict[str, Any]:
        """Persist local model weights in an explicit npz tensor format."""
        np = importlib.import_module("numpy")
        target = Path(path)
        if target.suffix != ".npz":
            raise ValueError("weight blob path must use .npz")
        feature_abi_binding_json = self._checkpoint_feature_abi_binding_json
        # Saving mutates calibration metadata only; cloning all model tensors
        # here would duplicate the deployed model for no rollback benefit.
        state_before = self._mutable_state_snapshot(
            include_model_parameters=False,
        )
        tmp: Path | None = None
        try:
            # Revalidate calibration against the exact weights immediately
            # before persistence. Any later failure rolls this mutation back.
            self.set_confidence_calibration_state(
                self._confidence_calibration_state
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            payload: dict[str, Any] = {
                "__format_version": np.array(["v2_hybrid_policy_npz_v2"]),
                "__input_dim": np.array([self.input_dim], dtype=np.int64),
                "__seed": np.array([self.seed], dtype=np.int64),
                "__torch_available": np.array(
                    [1 if self.torch_available else 0], dtype=np.int64
                ),
                "__confidence_head_schema_version": np.array(
                    [CONFIDENCE_HEAD_SCHEMA_VERSION]
                ),
                "__confidence_head_actions_json": np.array(
                    [
                        json.dumps(
                            list(CONFIDENCE_HEAD_ACTIONS),
                            separators=(",", ":"),
                        )
                    ]
                ),
                "__confidence_calibration_state_json": np.array(
                    [
                        json.dumps(
                            self.confidence_calibration_state,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                    ]
                ),
            }
            if feature_abi_binding_json is not None:
                binding_module = _checkpoint_feature_abi_v4_module()
                verification = binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
                    feature_abi_binding_json,
                    checkpoint_input_dim=self.input_dim,
                )
                if (
                    verification["binding_sha256"]
                    != binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
                ):
                    raise ValueError("checkpoint_feature_abi_binding_mismatch")
                payload[_WEIGHT_BLOB_FEATURE_ABI_KEY] = np.array(
                    [feature_abi_binding_json]
                )
            if self._torch is not None and self._net is not None:
                for name, tensor in self._net.state_dict().items():
                    payload[f"torch::{name}"] = tensor.detach().cpu().numpy()
            else:
                payload[_WEIGHT_BLOB_FALLBACK_KEY] = np.asarray(
                    self._fallback_weights,
                    dtype=np.float64,
                )
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                tmp = Path(handle.name)
                np.savez_compressed(handle, **payload)
            tmp.replace(target)
        except Exception:
            self._restore_mutable_state_snapshot(state_before)
            raise
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
        return {
            "weight_file_path": str(target),
            "weight_file_format": "npz",
            "weight_file_size_bytes": int(target.stat().st_size),
        }

    def load_weight_blob(self, path: Path) -> dict[str, Any]:
        """Load local npz tensor weights without pickle or external deserialization."""
        source = Path(path)
        if source.suffix != ".npz":
            raise ValueError("weight blob path must use .npz")
        if not source.exists():
            raise FileNotFoundError(str(source))
        with source.open("rb") as stream:
            return self.load_weight_blob_stream(
                stream,
                source_label=str(source),
            )

    def load_weight_blob_stream(
        self,
        stream: BinaryIO,
        *,
        source_label: str,
    ) -> dict[str, Any]:
        """Load a no-pickle NPZ from the caller's already-open byte stream.

        Checkpoint admission uses this entry point after copying the source
        artifact into a private snapshot.  Keeping ownership of the stream in
        the caller ensures semantic verification and model mutation consume the
        exact same immutable byte copy instead of reopening a mutable path.
        """
        if self._checkpoint_feature_abi_binding_json is None:
            return self._load_legacy_weight_blob_stream(
                stream,
                source_label=source_label,
            )
        feature_abi_binding_json = self._checkpoint_feature_abi_binding_json
        member_keys = frozenset(_strict_npz_member_keys(stream))
        np = importlib.import_module("numpy")
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as data:
            format_version = _strict_npz_scalar_text(data, "__format_version")
            input_dim = _strict_npz_scalar_int64(data, "__input_dim")
            seed = _strict_npz_scalar_int64(data, "__seed")
            torch_available = _strict_npz_scalar_int64(
                data,
                "__torch_available",
            )
            if format_version != "v2_hybrid_policy_npz_v2":
                raise ValueError("checkpoint_npz_format_version_invalid")
            if input_dim != self.input_dim:
                raise ValueError("checkpoint input_dim does not match model")
            if torch_available not in (0, 1):
                raise ValueError("checkpoint_npz_torch_available_invalid")

            expected_metadata = set(_WEIGHT_BLOB_REQUIRED_METADATA_KEYS)
            if feature_abi_binding_json is not None:
                expected_metadata.add(_WEIGHT_BLOB_FEATURE_ABI_KEY)
                binding_json = _strict_npz_scalar_text(
                    data,
                    _WEIGHT_BLOB_FEATURE_ABI_KEY,
                )
                binding_module = _checkpoint_feature_abi_v4_module()
                feature_abi_verification = (
                    binding_module.verify_deployed_checkpoint_feature_abi_binding_v4(
                        binding_json,
                        checkpoint_input_dim=self.input_dim,
                    )
                )
                if (
                    binding_json != feature_abi_binding_json
                    or feature_abi_verification["binding_sha256"]
                    != binding_module.CHECKPOINT_FEATURE_ABI_BINDING_V4_SHA256
                ):
                    raise ValueError("checkpoint_feature_abi_binding_v4_mismatch")
            elif _WEIGHT_BLOB_FEATURE_ABI_KEY in member_keys:
                raise ValueError("checkpoint_feature_abi_binding_v4_unexpected")
            if seed != self.seed:
                raise ValueError("checkpoint seed does not match model")

            checkpoint_head_schema = _strict_npz_scalar_text(
                data,
                "__confidence_head_schema_version",
            )
            actions_json = _strict_npz_scalar_text(
                data,
                "__confidence_head_actions_json",
            )
            checkpoint_head_actions_raw = _strict_npz_json(actions_json)
            if type(checkpoint_head_actions_raw) is not list:
                raise ConfidenceHeadCheckpointIncompatibleError(
                    "CHECKPOINT_CONFIDENCE_HEAD_NOT_PER_DIRECTIONAL_ACTION_V1"
                )
            checkpoint_head_actions = tuple(checkpoint_head_actions_raw)
            if (
                checkpoint_head_schema != CONFIDENCE_HEAD_SCHEMA_VERSION
                or checkpoint_head_actions != CONFIDENCE_HEAD_ACTIONS
            ):
                raise ConfidenceHeadCheckpointIncompatibleError(
                    "CHECKPOINT_CONFIDENCE_HEAD_NOT_PER_DIRECTIONAL_ACTION_V1"
                )

            calibration_json = _strict_npz_scalar_text(
                data,
                "__confidence_calibration_state_json",
            )
            decoded_calibration = _strict_npz_json(calibration_json)
            if type(decoded_calibration) is not dict:
                raise ValueError("checkpoint_calibration_state_not_object")
            calibration_state = normalize_calibration_state(decoded_calibration)
            if calibration_state.get("fitted") is True and not calibration_state.get(
                "model_parameter_fingerprint"
            ):
                calibration_state = unfitted_calibration_state(
                    "CHECKPOINT_CALIBRATION_MODEL_FINGERPRINT_MISSING"
                )

            torch_keys = frozenset(
                key for key in member_keys if key.startswith("torch::")
            )
            fallback_present = _WEIGHT_BLOB_FALLBACK_KEY in member_keys
            if bool(torch_keys) == fallback_present:
                raise ValueError("checkpoint_npz_parameter_family_ambiguous")
            if torch_keys:
                if torch_available != 1 or self._torch is None or self._net is None:
                    raise ValueError("checkpoint_npz_torch_family_target_mismatch")
                state = self._net.state_dict()
                expected_torch_keys = frozenset(
                    f"torch::{name}" for name in state
                )
                if torch_keys != expected_torch_keys:
                    raise ValueError("checkpoint_npz_torch_key_set_mismatch")
                expected_keys = frozenset(expected_metadata) | expected_torch_keys
                if member_keys != expected_keys:
                    raise ValueError("checkpoint_npz_unexpected_keys")
                restored: dict[str, Any] = {}
                for name, existing in state.items():
                    array = data[f"torch::{name}"]
                    expected_dtype = str(existing.detach().cpu().numpy().dtype)
                    if tuple(array.shape) != tuple(existing.shape):
                        raise ValueError(f"shape mismatch for tensor: {name}")
                    if str(array.dtype) != expected_dtype:
                        raise ValueError(f"dtype mismatch for tensor: {name}")
                    if not bool(np.isfinite(array).all()):
                        raise ValueError(f"non_finite_tensor_in_checkpoint: {name}")
                    restored[name] = self._torch.as_tensor(
                        array,
                        dtype=existing.dtype,
                        device=self._device,
                    )
                pending_fallback: list[float] | None = None
            else:
                if torch_available != 0 or self._torch is not None or self._net is not None:
                    raise ValueError("checkpoint_npz_fallback_family_target_mismatch")
                expected_keys = frozenset(expected_metadata) | {
                    _WEIGHT_BLOB_FALLBACK_KEY
                }
                if member_keys != expected_keys:
                    raise ValueError("checkpoint_npz_unexpected_keys")
                fallback = data[_WEIGHT_BLOB_FALLBACK_KEY]
                if (
                    tuple(fallback.shape) != (len(self._fallback_weights),)
                    or str(fallback.dtype) != "float64"
                    or not bool(np.isfinite(fallback).all())
                ):
                    raise ValueError("checkpoint_npz_fallback_parameters_invalid")
                pending_fallback = [float(value) for value in fallback.tolist()]
                restored = {}

        state_before = self._mutable_state_snapshot()
        try:
            if restored:
                if self._net is None:
                    raise RuntimeError("checkpoint_model_net_unavailable")
                self._net.load_state_dict(restored, strict=True)
                self._net.eval()
                calibration_state = self.set_confidence_calibration_state(
                    calibration_state
                )
                restored_count = len(restored)
            else:
                if pending_fallback is None:
                    raise RuntimeError("checkpoint_fallback_payload_unavailable")
                self._fallback_weights = pending_fallback
                calibration_state = self.set_confidence_calibration_state(
                    unfitted_calibration_state(
                        "CPU_FALLBACK_HAS_NO_PROFITABILITY_CONFIDENCE_HEAD"
                    )
                )
                restored_count = 1
        except Exception:
            self._restore_mutable_state_snapshot(state_before)
            raise
        return {
            "weight_file_path": source_label,
            "weight_file_format": "npz",
            "model_state_restored": True,
            "restored_tensor_count": restored_count,
            "confidence_calibration_fitted": (
                calibration_state.get("fitted") is True
            ),
            "confidence_calibration_reason": calibration_state.get("reason"),
        }

    def _load_legacy_weight_blob_stream(
        self,
        stream: BinaryIO,
        *,
        source_label: str,
    ) -> dict[str, Any]:
        """Preserve the pre-v4 undeclared checkpoint contract exactly."""

        np = importlib.import_module("numpy")
        stream.seek(0)
        with np.load(stream, allow_pickle=False) as data:
            input_dim_values = data.get("__input_dim")
            if (
                input_dim_values is not None
                and int(input_dim_values[0]) != self.input_dim
            ):
                raise ValueError("checkpoint input_dim does not match model")
            head_schema_values = data.get("__confidence_head_schema_version")
            head_actions_values = data.get("__confidence_head_actions_json")
            checkpoint_head_schema = (
                str(head_schema_values[0])
                if head_schema_values is not None
                else None
            )
            try:
                checkpoint_head_actions = (
                    tuple(json.loads(str(head_actions_values[0])))
                    if head_actions_values is not None
                    else ()
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                checkpoint_head_actions = ()
            if (
                checkpoint_head_schema != CONFIDENCE_HEAD_SCHEMA_VERSION
                or checkpoint_head_actions != CONFIDENCE_HEAD_ACTIONS
            ):
                raise ConfidenceHeadCheckpointIncompatibleError(
                    "CHECKPOINT_CONFIDENCE_HEAD_NOT_PER_DIRECTIONAL_ACTION_V1"
                )

            calibration_values = data.get("__confidence_calibration_state_json")
            if calibration_values is None:
                calibration_state = unfitted_calibration_state(
                    "LEGACY_CHECKPOINT_CALIBRATION_STATE_MISSING"
                )
            else:
                try:
                    decoded_calibration = json.loads(str(calibration_values[0]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    decoded_calibration = unfitted_calibration_state(
                        "CHECKPOINT_CALIBRATION_STATE_JSON_INVALID"
                    )
                calibration_state = normalize_calibration_state(
                    decoded_calibration
                    if isinstance(decoded_calibration, dict)
                    else unfitted_calibration_state(
                        "CHECKPOINT_CALIBRATION_STATE_NOT_OBJECT"
                    )
                )
                if (
                    calibration_state.get("fitted") is True
                    and not calibration_state.get("model_parameter_fingerprint")
                ):
                    calibration_state = unfitted_calibration_state(
                        "CHECKPOINT_CALIBRATION_MODEL_FINGERPRINT_MISSING"
                    )
            if self._torch is not None and self._net is not None:
                state = self._net.state_dict()
                restored: dict[str, Any] = {}
                for name, existing in state.items():
                    key = f"torch::{name}"
                    if key not in data:
                        raise ValueError(f"missing tensor in checkpoint: {name}")
                    array = data[key]
                    if tuple(array.shape) != tuple(existing.shape):
                        raise ValueError(f"shape mismatch for tensor: {name}")
                    if not bool(np.isfinite(array).all()):
                        raise ValueError(
                            f"non_finite_tensor_in_checkpoint: {name}"
                        )
                    restored[name] = self._torch.as_tensor(
                        array,
                        dtype=existing.dtype,
                        device=self._device,
                    )
                self._net.load_state_dict(restored, strict=True)
                self._net.eval()
                calibration_state = self.set_confidence_calibration_state(
                    calibration_state
                )
                return {
                    "weight_file_path": source_label,
                    "weight_file_format": "npz",
                    "model_state_restored": True,
                    "restored_tensor_count": len(restored),
                    "confidence_calibration_fitted": (
                        calibration_state.get("fitted") is True
                    ),
                    "confidence_calibration_reason": calibration_state.get(
                        "reason"
                    ),
                }
            fallback = data.get(_WEIGHT_BLOB_FALLBACK_KEY)
            if fallback is None:
                raise ValueError(
                    "checkpoint has no fallback weights for CPU fallback model"
                )
            if not bool(np.isfinite(fallback).all()):
                raise ValueError(
                    "non_finite_tensor_in_checkpoint: fallback::weights"
                )
            values = [float(value) for value in fallback.tolist()]
            if len(values) != len(self._fallback_weights):
                raise ValueError("fallback checkpoint length does not match model")
            self._fallback_weights = values
            calibration_state = self.set_confidence_calibration_state(
                unfitted_calibration_state(
                    "CPU_FALLBACK_HAS_NO_PROFITABILITY_CONFIDENCE_HEAD"
                )
            )
            return {
                "weight_file_path": source_label,
                "weight_file_format": "npz",
                "model_state_restored": True,
                "restored_tensor_count": 1,
                "confidence_calibration_fitted": (
                    calibration_state.get("fitted") is True
                ),
                "confidence_calibration_reason": calibration_state.get("reason"),
            }

    def forward(self, tensor: FeatureTensorRecord | Sequence[float]) -> ModelForwardResult:
        window: list[list[float]] | None = None
        if isinstance(tensor, FeatureTensorRecord):
            vector = [self._finite_feature_value(value) for value in tensor.model_vector]
            coverage = tensor.data_coverage_percent
            missing_count = len(tensor.missing_feature_names)
            stale_count = len(tensor.stale_feature_names)
            total_features = len(tensor.feature_names) or None
            # Temporal (Step 4c): fold this frame into the per-symbol rolling window.
            # None when temporal is off -> byte-identical single-frame path.
            window = self._temporal_predict_window(tensor, vector)
        else:
            vector = [self._finite_feature_value(v) for v in tensor]
            coverage = 100.0
            missing_count = 0
            stale_count = 0
            total_features = None
        if len(vector) != self.input_dim:
            raise ValueError(f"model input dim mismatch: expected {self.input_dim}, got {len(vector)}")
        if self._torch is not None and self._net is not None:
            return self._forward_torch(
                vector, coverage, missing_count, stale_count, total_features, window=window
            )
        return self._forward_fallback(vector, coverage, missing_count, stale_count, total_features)

    def _temporal_predict_window(
        self, tensor: FeatureTensorRecord, vector: Sequence[float]
    ) -> list[list[float]] | None:
        """Maintain a no-lookahead rolling window of recent frames per (symbol, tf).

        Returns ``seq_len`` frames (oldest first, this frame last), left-padded with
        the oldest available frame when history is short -- mirroring the training
        windower (``temporal_windowing.build_example_windows``). Returns ``None`` when
        the temporal encoder is off so the caller keeps the exact single-frame tensor.

        The live loop re-presents the SAME latest snapshot across cycles until a new
        candle closes, so frames are deduped by ``feature_snapshot_id``/``tensor_id``:
        a repeated frame is not appended (the window already ends with it), keeping the
        window a true time series of distinct frames.
        """
        if not self.temporal_encoder_enabled:
            return None
        seq_len = int(self.temporal_seq_len)
        key = (
            str(getattr(tensor, "symbol", "") or "").upper(),
            str(getattr(tensor, "timeframe", "") or "").lower(),
        )
        frame_id = getattr(tensor, "feature_snapshot_id", None) or getattr(tensor, "tensor_id", None)
        buf = self._temporal_predict_buffers.get(key)
        if buf is None:
            buf = deque(maxlen=seq_len)
            self._temporal_predict_buffers[key] = buf
        frame = [float(v) for v in vector]
        last_id = self._temporal_predict_last_id.get(key)
        if not buf or frame_id is None or frame_id != last_id:
            buf.append(frame)
            self._temporal_predict_last_id[key] = frame_id
        frames = list(buf) or [frame]
        if len(frames) < seq_len:
            frames = [frames[0]] * (seq_len - len(frames)) + frames
        return frames

    @staticmethod
    def _finite_feature_value(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not math.isfinite(number):
            return 0.0
        return max(-1_000_000.0, min(1_000_000.0, number))

    def _forward_torch(
        self,
        vector: list[float],
        coverage: float,
        missing_count: int,
        stale_count: int,
        total_features: int | None = None,
        *,
        window: list[list[float]] | None = None,
    ) -> ModelForwardResult:
        torch = self._torch
        assert torch is not None and self._net is not None
        self._net.eval()
        with torch.no_grad():
            if window is not None:
                # (1, T, F) no-lookahead window -> the net's temporal (GRU) path,
                # which reduces to per-batch heads exactly like the single frame.
                x = torch.tensor([window], dtype=torch.float32, device=self._device)
            else:
                x = torch.tensor([vector], dtype=torch.float32, device=self._device)
            out = self._net(x)
            logits_t = torch.clamp(
                torch.nan_to_num(out["logits"][0], nan=0.0, posinf=30.0, neginf=-30.0),
                min=-30.0,
                max=30.0,
            )
            probs_t = torch.softmax(logits_t, dim=-1)
            logits = tuple(float(v) for v in logits_t.detach().cpu().tolist())
            raw_probs = tuple(float(v) for v in probs_t.detach().cpu().tolist())
            expected_t = torch.clamp(
                torch.nan_to_num(out["expected_move"][0], nan=0.0, posinf=120.0, neginf=-120.0),
                min=-120.0,
                max=120.0,
            )
            value_t = torch.clamp(
                torch.nan_to_num(out["value"][0], nan=0.0, posinf=10.0, neginf=-10.0),
                min=-10.0,
                max=10.0,
            )
            confidence_by_direction_t = torch.clamp(
                torch.nan_to_num(
                    out["confidence_by_direction"][0],
                    nan=0.0,
                    posinf=1.0,
                    neginf=0.0,
                ),
                min=0.0,
                max=1.0,
            )
            masa_head_t = torch.clamp(
                torch.nan_to_num(out["masa"][0], nan=0.0, posinf=1.0, neginf=-1.0),
                min=-1.0,
                max=1.0,
            )
            expected = float(expected_t.detach().cpu().item())
            value = float(value_t.detach().cpu().item())
            confidence_by_direction = tuple(
                float(value)
                for value in confidence_by_direction_t.detach().cpu().tolist()
            )
            masa_head = float(masa_head_t.detach().cpu().item())
            probs, selected = self._expected_move_aligned_policy(raw_probs, expected)
        # The confidence head is trained against selected-action realized
        # profitability after explicit costs.  Policy selection probability is
        # P(the policy selects an action), not P(the action is profitable), so
        # taking max(policy_probability, confidence_head) inflated and changed
        # the declared semantics.
        selected_action = ACTION_LABELS[selected]
        calibration_state = self.confidence_calibration_state
        temperature = resolve_confidence_temperature(calibration_state)
        checkpoint_calibration_metadata = {
            "checkpoint_calibration_sample": calibration_state.get("sample"),
            "checkpoint_calibration_fit_partition": calibration_state.get(
                "fit_partition"
            ),
            "checkpoint_calibration_validation_rows_used": calibration_state.get(
                "validation_rows_used"
            ),
            "checkpoint_calibration_row_digest": calibration_state.get("row_digest"),
            "model_parameter_fingerprint": calibration_state.get(
                "model_parameter_fingerprint"
            ),
        }
        confidence_calibration_by_direction: dict[str, dict[str, Any]] = {}
        for action, action_index in CONFIDENCE_HEAD_ACTION_INDEX.items():
            action_calibration = calibrate_confidence(
                raw_probability=confidence_by_direction[action_index],
                data_coverage_percent=coverage,
                missing_feature_count=missing_count,
                stale_feature_count=stale_count,
                total_feature_count=total_features,
                temperature=temperature,
                calibration_fitted=calibration_state.get("fitted") is True,
                calibration_reason=calibration_state.get("reason"),
            )
            action_calibration.update(
                {
                    "selected_action": action,
                    "selected_action_is_directional": True,
                    "confidence_head_action_index": action_index,
                    **checkpoint_calibration_metadata,
                }
            )
            confidence_calibration_by_direction[action] = action_calibration

        confidence_action_index = CONFIDENCE_HEAD_ACTION_INDEX.get(selected_action)
        selected_action_is_directional = confidence_action_index is not None
        if selected_action_is_directional:
            calibration = dict(confidence_calibration_by_direction[selected_action])
        else:
            calibration = calibrate_confidence(
                raw_probability=0.0,
                data_coverage_percent=coverage,
                missing_feature_count=missing_count,
                stale_feature_count=stale_count,
                total_feature_count=total_features,
                temperature=None,
                calibration_fitted=False,
                calibration_reason=(
                    "SELECTED_ACTION_NOT_DIRECTIONAL_CONFIDENCE_UNDEFINED"
                ),
            )
            calibration.update(checkpoint_calibration_metadata)
        raw = (
            confidence_by_direction[confidence_action_index]
            if confidence_action_index is not None
            else 0.0
        )
        calibration.update(
            {
                "selected_action": selected_action,
                "selected_action_is_directional": selected_action_is_directional,
                "confidence_head_action_index": confidence_action_index,
                "confidence_raw_by_direction": {
                    action: confidence_by_direction[index]
                    for index, action in enumerate(CONFIDENCE_HEAD_ACTIONS)
                },
                "confidence_calibrated_by_direction": {
                    action: action_calibration["confidence_calibrated"]
                    for action, action_calibration in (
                        confidence_calibration_by_direction.items()
                    )
                },
                "confidence_calibration_by_direction": (
                    confidence_calibration_by_direction
                ),
            }
        )
        masa = self._masa.evaluate(
            expected_move_bps=expected,
            action_probabilities=probs,
            data_coverage_percent=coverage,
        )
        return ModelForwardResult(
            model_id=self.model_id,
            model_source=MODEL_SOURCE,
            action_logits=logits,
            action_probabilities=probs,
            selected_action_index=selected,
            selected_action=selected_action,
            expected_move_bps=expected,
            confidence_raw=float(raw),
            confidence_calibrated=float(calibration["confidence_calibrated"]),
            policy_value=value,
            masa_signal=float(0.5 * masa_head + 0.5 * masa.masa_signal),
            calibration=calibration,
            device=self._device,
            cuda_active=self.cuda_active,
            model_tensors_device_verified=self.model_tensors_device_verified(),
        )

    def _forward_fallback(
        self,
        vector: list[float],
        coverage: float,
        missing_count: int,
        stale_count: int,
        total_features: int | None = None,
    ) -> ModelForwardResult:
        logits: list[float] = []
        for j in range(ACTION_COUNT):
            acc = 0.0
            for i, value in enumerate(vector):
                acc += float(value) * self._fallback_weights[j * self.input_dim + i]
            logits.append(math.tanh(acc / max(1, self.input_dim)) * 3.0)
        raw_probs = softmax(logits)
        expected = 120.0 * math.tanh((raw_probs[1] - raw_probs[2]) * 2.0)
        probs, selected = self._expected_move_aligned_policy(raw_probs, expected)
        # The algebraic CPU fallback has no profitability-confidence head.
        # Action probability cannot be relabelled as profitability probability,
        # even if a calibration state happened to be loaded alongside fallback
        # weights.
        raw = 0.0
        calibration = calibrate_confidence(
            raw_probability=raw,
            data_coverage_percent=coverage,
            missing_feature_count=missing_count,
            stale_feature_count=stale_count,
            total_feature_count=total_features,
            temperature=None,
            calibration_fitted=False,
            calibration_reason="CPU_FALLBACK_HAS_NO_PROFITABILITY_CONFIDENCE_HEAD",
        )
        masa = self._masa.evaluate(
            expected_move_bps=expected,
            action_probabilities=probs,
            data_coverage_percent=coverage,
        )
        return ModelForwardResult(
            model_id=self.model_id,
            model_source=MODEL_SOURCE,
            action_logits=tuple(float(v) for v in logits),
            action_probabilities=probs,
            selected_action_index=selected,
            selected_action=ACTION_LABELS[selected],
            expected_move_bps=float(expected),
            confidence_raw=float(raw),
            confidence_calibrated=float(calibration["confidence_calibrated"]),
            policy_value=float(sum(vector[: min(5, len(vector))]) / max(1, min(5, len(vector)))),
            masa_signal=masa.masa_signal,
            calibration=calibration,
            device="cpu",
            cuda_active=False,
            model_tensors_device_verified=False,
        )
