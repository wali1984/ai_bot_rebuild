"""P0.2E GPU training loop parity check (paper-only, lazy torch).

This module does NOT import torch at module-import time. The lazy
import is gated inside ``run_gpu_training_or_classify_blocker`` so
that any importer of v2.backend.app.services.rl_core.* still passes
the forbidden-import scan and never pulls torch into the FastAPI
process tree by accident.

Behavior:

- If torch is unavailable, returns classification
  ``GPU_TRAINING_BLOCKED_TORCH_UNAVAILABLE`` with explicit blockers.
- If torch is importable but CUDA is unavailable, returns
  ``GPU_TRAINING_BLOCKED_CUDA_UNAVAILABLE``.
- If CUDA is available, builds a tiny CPU-init linear policy
  (26 -> 16 -> 5), moves it to CUDA, runs one paper-only
  forward + cross-entropy loss + backward + optimizer step, then
  returns metrics.

No exchange mutation. No Redis writes. No checkpoint write. No live
trading. live_gate stays blocked_human_only.
"""
from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from v2.backend.app.services.market_state_integrity import (
    build_market_state_envelope_from_snapshot,
)

from .observation_builder import build_observation_from_snapshot
from .policy import (
    ACTION_COUNT,
    ACTION_LABELS,
    HEDGE_ACTION_CLASSIFICATION,
    HEDGE_ACTION_INDEX,
    POLICY_HIDDEN_DIM,
    POLICY_OBSERVATION_DIM,
)

STATUS_GPU_READY_TINY_STEP_RAN = "GPU_TRAINING_TINY_PAPER_STEP_RAN"
STATUS_BLOCKED_TORCH = "GPU_TRAINING_BLOCKED_TORCH_UNAVAILABLE"
STATUS_BLOCKED_CUDA = "GPU_TRAINING_BLOCKED_CUDA_UNAVAILABLE"
STATUS_BLOCKED_GPU_ERROR = "GPU_TRAINING_BLOCKED_GPU_RUNTIME_ERROR"

MISSING_FULL_PARITY_BLOCKERS = (
    "full_ppo_clip_loss_MISSING",
    "full_gae_advantage_estimation_MISSING",
    "lagrangian_safety_state_MISSING",
    "recurrent_feature_extractor_MISSING",
    "regime_observer_head_MISSING",
    "checkpoint_promotion_to_v2_PENDING_OPERATOR_APPROVAL",
)


@dataclass(frozen=True)
class GPUTrainingResult:
    status: str
    gpu_visible: bool
    torch_version: Optional[str]
    cuda_version: Optional[str]
    device_count: int
    device_name: Optional[str]
    observation_dim: int
    action_count: int
    loss_before: Optional[float]
    loss_after: Optional[float]
    grad_norm_max: Optional[float]
    weight_artifact_written: bool
    missing_full_parity_blockers: tuple[str, ...]
    run_id: str
    generated_utc: str


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_gpu_training_or_classify_blocker(
    snapshot: dict,
    *,
    seed: int = 0xC0DE_2E,
    steps: int = 4,
    lr: float = 0.05,
    allow_weight_artifact_write: bool = False,
) -> GPUTrainingResult:
    """Run a tiny GPU paper-only training step or classify a blocker.

    Lazy-imports torch only inside this function so module-import
    stays torch-free.
    """
    now = _utc_iso()
    try:
        torch = importlib.import_module("torch")
    except Exception:
        return GPUTrainingResult(
            status=STATUS_BLOCKED_TORCH,
            gpu_visible=False,
            torch_version=None,
            cuda_version=None,
            device_count=0,
            device_name=None,
            observation_dim=POLICY_OBSERVATION_DIM,
            action_count=ACTION_COUNT,
            loss_before=None,
            loss_after=None,
            grad_norm_max=None,
            weight_artifact_written=False,
            missing_full_parity_blockers=MISSING_FULL_PARITY_BLOCKERS,
            run_id="gpu_blocked_no_torch",
            generated_utc=now,
        )
    try:
        cuda_ok = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count()) if cuda_ok else 0
        device_name = torch.cuda.get_device_name(0) if cuda_ok else None
        cuda_version = getattr(torch.version, "cuda", None)
        torch_version = torch.__version__
    except Exception as exc:
        return GPUTrainingResult(
            status=STATUS_BLOCKED_GPU_ERROR,
            gpu_visible=False,
            torch_version=getattr(torch, "__version__", None),
            cuda_version=None,
            device_count=0,
            device_name=None,
            observation_dim=POLICY_OBSERVATION_DIM,
            action_count=ACTION_COUNT,
            loss_before=None,
            loss_after=None,
            grad_norm_max=None,
            weight_artifact_written=False,
            missing_full_parity_blockers=MISSING_FULL_PARITY_BLOCKERS + (f"runtime_error:{type(exc).__name__}",),
            run_id="gpu_blocked_runtime_error",
            generated_utc=now,
        )
    if not cuda_ok or device_count == 0:
        return GPUTrainingResult(
            status=STATUS_BLOCKED_CUDA,
            gpu_visible=False,
            torch_version=torch_version,
            cuda_version=cuda_version,
            device_count=device_count,
            device_name=device_name,
            observation_dim=POLICY_OBSERVATION_DIM,
            action_count=ACTION_COUNT,
            loss_before=None,
            loss_after=None,
            grad_norm_max=None,
            weight_artifact_written=False,
            missing_full_parity_blockers=MISSING_FULL_PARITY_BLOCKERS,
            run_id="gpu_blocked_no_cuda",
            generated_utc=now,
        )
    obs = build_observation_from_snapshot(
        snapshot,
        market_state_envelope=build_market_state_envelope_from_snapshot(snapshot),
    )
    if len(obs.tensor) != POLICY_OBSERVATION_DIM:
        return GPUTrainingResult(
            status=STATUS_BLOCKED_GPU_ERROR,
            gpu_visible=True,
            torch_version=torch_version,
            cuda_version=cuda_version,
            device_count=device_count,
            device_name=device_name,
            observation_dim=POLICY_OBSERVATION_DIM,
            action_count=ACTION_COUNT,
            loss_before=None,
            loss_after=None,
            grad_norm_max=None,
            weight_artifact_written=False,
            missing_full_parity_blockers=MISSING_FULL_PARITY_BLOCKERS + ("observation_dim_mismatch",),
            run_id="gpu_blocked_obs_dim_mismatch",
            generated_utc=now,
        )
    try:
        torch.manual_seed(seed)
        device = torch.device("cuda")
        net = torch.nn.Sequential(
            torch.nn.Linear(POLICY_OBSERVATION_DIM, POLICY_HIDDEN_DIM),
            torch.nn.Tanh(),
            torch.nn.Linear(POLICY_HIDDEN_DIM, ACTION_COUNT),
        ).to(device)
        opt = torch.optim.SGD(net.parameters(), lr=lr)
        ce = torch.nn.CrossEntropyLoss()
        x = torch.tensor([list(obs.tensor)], dtype=torch.float32, device=device)
        targets = torch.tensor([1], dtype=torch.long, device=device)  # "long" action target
        with torch.no_grad():
            logits0 = net(x)
            loss_before_t = ce(logits0, targets).item()
        max_grad = 0.0
        loss_after_t = loss_before_t
        for _ in range(max(1, int(steps))):
            opt.zero_grad(set_to_none=True)
            logits = net(x)
            loss = ce(logits, targets)
            loss.backward()
            for p in net.parameters():
                if p.grad is not None:
                    gn = float(p.grad.detach().abs().max().item())
                    if gn > max_grad:
                        max_grad = gn
            opt.step()
            loss_after_t = float(loss.item())
        run_id = "gpu_tiny_step_" + hashlib.sha256(
            f"{seed}|{steps}|{lr}|{device_name}".encode()
        ).hexdigest()[:32]
        return GPUTrainingResult(
            status=STATUS_GPU_READY_TINY_STEP_RAN,
            gpu_visible=True,
            torch_version=torch_version,
            cuda_version=cuda_version,
            device_count=device_count,
            device_name=device_name,
            observation_dim=POLICY_OBSERVATION_DIM,
            action_count=ACTION_COUNT,
            loss_before=float(loss_before_t),
            loss_after=float(loss_after_t),
            grad_norm_max=float(max_grad),
            weight_artifact_written=False,
            missing_full_parity_blockers=MISSING_FULL_PARITY_BLOCKERS,
            run_id=run_id,
            generated_utc=now,
        )
    except Exception as exc:
        return GPUTrainingResult(
            status=STATUS_BLOCKED_GPU_ERROR,
            gpu_visible=True,
            torch_version=torch_version,
            cuda_version=cuda_version,
            device_count=device_count,
            device_name=device_name,
            observation_dim=POLICY_OBSERVATION_DIM,
            action_count=ACTION_COUNT,
            loss_before=None,
            loss_after=None,
            grad_norm_max=None,
            weight_artifact_written=False,
            missing_full_parity_blockers=MISSING_FULL_PARITY_BLOCKERS + (f"runtime_error:{type(exc).__name__}",),
            run_id="gpu_blocked_runtime_error",
            generated_utc=now,
        )


def gpu_training_invariants_snapshot() -> dict:
    return {
        "action_labels": list(ACTION_LABELS),
        "hedge_action_classification": HEDGE_ACTION_CLASSIFICATION,
        "imports_torch_at_module_level": False,
        "imports_numpy": False,
        "writes_model_artifact_by_default": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "missing_full_parity_blockers": list(MISSING_FULL_PARITY_BLOCKERS),
    }
