"""Lazy-torch PPO/MASA model for V2 paper/shadow CUDA training."""
from __future__ import annotations

import hashlib
import importlib
import math
import os
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .config import ACTION_COUNT, ACTION_LABELS, MODEL_SOURCE
from .confidence import calibrate_confidence, resolve_confidence_temperature, softmax
from .masa import V2MASAAdapter
from .tensor_builder import FeatureTensorRecord

TRAINER_CUDA_MEMORY_CAP_BYTES = 12 * 1024 * 1024 * 1024
TRAINER_CUDA_MEMORY_CAP_FRACTION = 0.75


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

    def __init__(self, *, input_dim: int, seed: int = 0xC0DE_55) -> None:
        self.input_dim = int(input_dim)
        self.seed = int(seed)
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
        self._torch = None
        self._net = None
        self._device = "cpu"
        # The attention flag is part of the architecture identity so enabling it
        # starts a fresh checkpoint lineage (the checkpoint manager handles the
        # input-shape/arch change as a graceful fresh init). When attention is off
        # or cannot activate, preserve the legacy identity so compatible checkpoints
        # remain loadable.
        arch_identity = f"{input_dim}|{seed}|{self.hidden_size}|{self.residual_block_count}"
        if self.attention_encoder_enabled:
            arch_identity += f"|attn=1x{self.attention_heads}"
        if self.temporal_encoder_enabled:
            arch_identity += f"|temporal={self.temporal_encoder}x{self.temporal_hidden}"
        self._model_id = "v2_hybrid_policy_" + hashlib.sha256(
            arch_identity.encode()
        ).hexdigest()[:24]
        self._fallback_weights = self._make_fallback_weights()
        self._masa = V2MASAAdapter()
        self._init_torch_if_available()

    @property
    def model_id(self) -> str:
        return self._model_id

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
                ) -> None:
                    super().__init__()
                    # GRU temporal encoder over a no-lookahead window. Additive; only
                    # built + applied when enabled AND the input is a 3D window, so the
                    # 2D single-frame path is byte-identical to the prior model.
                    self.temporal_enabled = bool(temporal_enabled)
                    if self.temporal_enabled:
                        self.temporal_gru = torch.nn.GRU(
                            input_dim, int(temporal_hidden), num_layers=1, batch_first=True
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
                    self.confidence_head = torch.nn.Linear(hidden, 1)
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
                            gru_out, _ = self.temporal_gru(window)
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
                        "confidence": torch.sigmoid(self.confidence_head(h).squeeze(-1)),
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
            "masa_auxiliary_head": True,
            "masa_adapter_blend": True,
            "action_count": ACTION_COUNT,
        }

    def save_weight_blob(self, path: Path) -> dict[str, Any]:
        """Persist local model weights in an explicit npz tensor format."""
        np = importlib.import_module("numpy")
        target = Path(path)
        if target.suffix != ".npz":
            raise ValueError("weight blob path must use .npz")
        target.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "__format_version": np.array(["v2_hybrid_policy_npz_v1"]),
            "__input_dim": np.array([self.input_dim], dtype=np.int64),
            "__seed": np.array([self.seed], dtype=np.int64),
            "__torch_available": np.array([1 if self.torch_available else 0], dtype=np.int64),
        }
        if self._torch is not None and self._net is not None:
            for name, tensor in self._net.state_dict().items():
                payload[f"torch::{name}"] = tensor.detach().cpu().numpy()
        else:
            payload["fallback::weights"] = np.asarray(self._fallback_weights, dtype=np.float64)
        tmp: Path | None = None
        try:
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
        np = importlib.import_module("numpy")
        source = Path(path)
        if source.suffix != ".npz":
            raise ValueError("weight blob path must use .npz")
        if not source.exists():
            raise FileNotFoundError(str(source))
        with np.load(source, allow_pickle=False) as data:
            input_dim_values = data.get("__input_dim")
            if input_dim_values is not None and int(input_dim_values[0]) != self.input_dim:
                raise ValueError("checkpoint input_dim does not match model")
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
                        raise ValueError(f"non_finite_tensor_in_checkpoint: {name}")
                    restored[name] = self._torch.as_tensor(array, dtype=existing.dtype, device=self._device)
                self._net.load_state_dict(restored, strict=True)
                self._net.eval()
                return {
                    "weight_file_path": str(source),
                    "weight_file_format": "npz",
                    "model_state_restored": True,
                    "restored_tensor_count": len(restored),
                }
            fallback = data.get("fallback::weights")
            if fallback is None:
                raise ValueError("checkpoint has no fallback weights for CPU fallback model")
            if not bool(np.isfinite(fallback).all()):
                raise ValueError("non_finite_tensor_in_checkpoint: fallback::weights")
            values = [float(v) for v in fallback.tolist()]
            if len(values) != len(self._fallback_weights):
                raise ValueError("fallback checkpoint length does not match model")
            self._fallback_weights = values
            return {
                "weight_file_path": str(source),
                "weight_file_format": "npz",
                "model_state_restored": True,
                "restored_tensor_count": 1,
            }

    def forward(self, tensor: FeatureTensorRecord | Sequence[float]) -> ModelForwardResult:
        if isinstance(tensor, FeatureTensorRecord):
            vector = [self._finite_feature_value(value) for value in tensor.model_vector]
            coverage = tensor.data_coverage_percent
            missing_count = len(tensor.missing_feature_names)
            stale_count = len(tensor.stale_feature_names)
            total_features = len(tensor.feature_names) or None
        else:
            vector = [self._finite_feature_value(v) for v in tensor]
            coverage = 100.0
            missing_count = 0
            stale_count = 0
            total_features = None
        if len(vector) != self.input_dim:
            raise ValueError(f"model input dim mismatch: expected {self.input_dim}, got {len(vector)}")
        if self._torch is not None and self._net is not None:
            return self._forward_torch(vector, coverage, missing_count, stale_count, total_features)
        return self._forward_fallback(vector, coverage, missing_count, stale_count, total_features)

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
    ) -> ModelForwardResult:
        torch = self._torch
        assert torch is not None and self._net is not None
        self._net.eval()
        with torch.no_grad():
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
            confidence_head_t = torch.clamp(
                torch.nan_to_num(out["confidence"][0], nan=0.0, posinf=1.0, neginf=0.0),
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
            confidence_head = float(confidence_head_t.detach().cpu().item())
            masa_head = float(masa_head_t.detach().cpu().item())
            probs, selected = self._expected_move_aligned_policy(raw_probs, expected)
        raw = max(probs[selected], confidence_head)
        calibration = calibrate_confidence(
            raw_probability=raw,
            data_coverage_percent=coverage,
            missing_feature_count=missing_count,
            stale_feature_count=stale_count,
            total_feature_count=total_features,
            temperature=resolve_confidence_temperature(),
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
            selected_action=ACTION_LABELS[selected],
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
        raw = probs[selected]
        calibration = calibrate_confidence(
            raw_probability=raw,
            data_coverage_percent=coverage,
            missing_feature_count=missing_count,
            stale_feature_count=stale_count,
            total_feature_count=total_features,
            temperature=resolve_confidence_temperature(),
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
