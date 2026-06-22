"""Lazy-torch PPO/MASA model for V2 paper/shadow CUDA training."""
from __future__ import annotations

import hashlib
import importlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .config import ACTION_COUNT, ACTION_LABELS, MODEL_SOURCE
from .confidence import calibrate_confidence, softmax
from .masa import V2MASAAdapter
from .tensor_builder import FeatureTensorRecord


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
        self.hidden_size = 1024
        self.residual_block_count = 3
        self.dropout = 0.05
        self._torch = None
        self._net = None
        self._device = "cpu"
        self._model_id = "v2_hybrid_policy_" + hashlib.sha256(
            f"{input_dim}|{seed}".encode()
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

    def _init_torch_if_available(self) -> None:
        try:
            torch = importlib.import_module("torch")
        except Exception:
            return
        try:
            torch.manual_seed(self.seed)
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

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
                def __init__(self, input_dim: int, hidden: int, residual_blocks: int, dropout: float) -> None:
                    super().__init__()
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

                def forward(self, x):
                    x = torch.nan_to_num(x, nan=0.0, posinf=1_000_000.0, neginf=-1_000_000.0)
                    x = torch.sign(x) * torch.log1p(torch.clamp(torch.abs(x), max=1_000_000.0))
                    h = self.input_projection(x)
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
            ).to(device)
            self._device = str(next(self._net.parameters()).device)
        except Exception:
            self._torch = None
            self._net = None
            self._device = "cpu"

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
        tmp = target.with_suffix(target.suffix + ".tmp")
        with tmp.open("wb") as handle:
            np.savez_compressed(handle, **payload)
        tmp.replace(target)
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
        else:
            vector = [self._finite_feature_value(v) for v in tensor]
            coverage = 100.0
            missing_count = 0
            stale_count = 0
        if len(vector) != self.input_dim:
            raise ValueError(f"model input dim mismatch: expected {self.input_dim}, got {len(vector)}")
        if self._torch is not None and self._net is not None:
            return self._forward_torch(vector, coverage, missing_count, stale_count)
        return self._forward_fallback(vector, coverage, missing_count, stale_count)

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
