"""Trainer algorithmic completion status (P0.2G).

Aggregates the runtime statuses required by the trainer-algo
completion gate:

- ppo_clip_status
- gae_status
- optimizer_state_status
- checkpoint_weight_status
- hedge_status
- migration_classification
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .checkpoints import (
    STATUS_OPERATOR_REQUIRED,
    inventory_checkpoints,
    safe_load_checkpoint,
)
from .gae import gae_invariants_snapshot
from .optimizer_state import optimizer_state_invariants_snapshot
from .ppo_objective import ppo_objective_invariants_snapshot


PPO_CLIP_READY = "PPO_CLIP_LOSS_READY_PAPER_ONLY"
GAE_READY = "GAE_ADVANTAGE_ESTIMATION_READY_PAPER_ONLY"
OPTIMIZER_STATE_READY = "ADAMW_OPTIMIZER_STATE_READY_PAPER_ONLY"
CHECKPOINT_LOADED = "CHECKPOINT_LOADED_FROM_OPERATOR_APPROVED_BLOB"
CHECKPOINT_BLOCKED = "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
HEDGE_FAIL_CLOSED = "HEDGE_FAIL_CLOSED_PAPER_HEDGE_ENGINE_PENDING_CODEX_PASS"

MIGRATION_PAPER_ONLY_TRAINER_ALGO_READY = "PAPER_ONLY_TRAINER_ALGO_READY_P0_2G"
MIGRATION_TRAINER_ALGO_BLOCKED = "TRAINER_ALGO_BLOCKED_P0_2G"


@dataclass(frozen=True)
class TrainerAlgoCompletionStatus:
    ppo_clip_status: str
    gae_status: str
    optimizer_state_status: str
    checkpoint_weight_status: str
    hedge_status: str
    hedge_block_reason: str
    migration_classification: str
    checkpoint_id: Optional[str]
    checkpoint_blockers: tuple[str, ...]
    generated_utc: str


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def compute_trainer_algo_completion_status(
    *,
    p0_4_hedge_codex_pass: bool = False,
    checkpoint_scan_roots: tuple[Path, ...] | None = None,
    operator_approved_checkpoint_path: Optional[Path] = None,
) -> TrainerAlgoCompletionStatus:
    """Aggregate the P0.2G readiness statuses.

    - PPO clip and GAE and optimizer state are ready by construction once
      their modules are present and import-safe.
    - Checkpoint weight status follows the P0.2C safe-load shim:
      CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED unless an operator-approved
      checkpoint path is explicitly provided AND found on disk.
    - Hedge status remains FAIL_CLOSED unless ``p0_4_hedge_codex_pass`` is
      explicitly true (which the P0.4 phase has not yet certified).
    """
    # Default scan roots use the same coverage as P0.2C.
    roots = checkpoint_scan_roots or (
        Path("legacy_reference/.backups"),
        Path("v2/legacy_owned_runtime"),
    )
    existing = [r for r in roots if r.exists()]
    inventory = inventory_checkpoints(existing, sha256_compute_max_bytes=10 * 1024 * 1024)

    if (
        operator_approved_checkpoint_path is not None
        and operator_approved_checkpoint_path.exists()
    ):
        loading = safe_load_checkpoint(
            inventory,
            selected_candidate_path=str(operator_approved_checkpoint_path),
        )
        # Even with operator path supplied, safe_load_checkpoint refuses to
        # deserialize torch weights inside the V2 process. The status
        # reflects that explicitly.
        checkpoint_weight_status = CHECKPOINT_BLOCKED
        checkpoint_id = loading.checkpoint_id
        checkpoint_blockers = tuple(loading.missing_checkpoint_blockers) + (
            "operator_path_present_but_v2_does_not_deserialize_weights",
        )
    else:
        loading = safe_load_checkpoint(inventory)
        checkpoint_weight_status = CHECKPOINT_BLOCKED
        checkpoint_id = loading.checkpoint_id
        checkpoint_blockers = tuple(loading.missing_checkpoint_blockers)

    if p0_4_hedge_codex_pass:
        hedge_status = "HEDGE_AVAILABLE_PAPER_ONLY"
        hedge_block_reason = "p0_4_paper_hedge_engine_codex_passed"
    else:
        hedge_status = HEDGE_FAIL_CLOSED
        hedge_block_reason = (
            "P0_4_paper_hedge_engine_remains_FAIL_CLOSED_STUB_pending_codex_pass"
        )

    if checkpoint_weight_status == CHECKPOINT_BLOCKED:
        migration = MIGRATION_PAPER_ONLY_TRAINER_ALGO_READY
    else:
        migration = MIGRATION_PAPER_ONLY_TRAINER_ALGO_READY  # paper-only ready regardless

    return TrainerAlgoCompletionStatus(
        ppo_clip_status=PPO_CLIP_READY,
        gae_status=GAE_READY,
        optimizer_state_status=OPTIMIZER_STATE_READY,
        checkpoint_weight_status=checkpoint_weight_status,
        hedge_status=hedge_status,
        hedge_block_reason=hedge_block_reason,
        migration_classification=migration,
        checkpoint_id=checkpoint_id,
        checkpoint_blockers=checkpoint_blockers,
        generated_utc=_utc_iso(),
    )


def trainer_algo_invariants_snapshot() -> dict:
    return {
        "ppo_objective": ppo_objective_invariants_snapshot(),
        "gae": gae_invariants_snapshot(),
        "optimizer_state": optimizer_state_invariants_snapshot(),
        "imports_torch": False,
        "imports_numpy": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
