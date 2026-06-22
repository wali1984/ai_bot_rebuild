"""DataLoader worker configuration for the PPO CUDA trainer.

Separated into a pure module so the worker-count formula can be unit-tested
without importing PyTorch or the full trainer stack.

Rules enforced here:
    - persistent_workers is ALWAYS False; DataLoader is recreated per training
      call, so True would leave zombie pt_data_worker processes.
    - Worker count is capped at MAX_DATALOADER_WORKERS (4).  RTX 5080
      saturates the memory bus quickly; uncapped counts spawned 18+ zombies
      under PID 1037427 on 2026-06-17.
    - Below MIN_ROWS_FOR_MULTIWORKER rows the overhead of worker startup
      outweighs the benefit — use workers=0 (in-process) instead.
"""
from __future__ import annotations

import os

MAX_DATALOADER_WORKERS: int = 4
MIN_ROWS_FOR_MULTIWORKER: int = 256
PREFETCH_FACTOR: int = 2
PERSISTENT_WORKERS: bool = False  # must never be True


def compute_dataloader_workers(*, cpu_count: int | None = None, row_count: int = 0) -> int:
    """Return the number of DataLoader workers to use.

    Args:
        cpu_count: physical CPU count (defaults to os.cpu_count()).
        row_count: number of training rows in this batch.

    Returns:
        Worker count in [0, MAX_DATALOADER_WORKERS].
        Returns 0 when row_count < MIN_ROWS_FOR_MULTIWORKER (use in-process).
    """
    if row_count < MIN_ROWS_FOR_MULTIWORKER:
        return 0
    cpus = cpu_count if cpu_count is not None else (os.cpu_count() or 4)
    return max(1, min(MAX_DATALOADER_WORKERS, max(cpus // 4, 1)))


def dataloader_config(*, cpu_count: int | None = None, row_count: int = 0) -> dict:
    """Return the full DataLoader constructor kwargs for the PPO trainer.

    The returned dict is safe to pass as **kwargs to torch.utils.data.DataLoader.
    persistent_workers is always False (see module docstring).
    """
    workers = compute_dataloader_workers(cpu_count=cpu_count, row_count=row_count)
    cfg: dict = {
        "num_workers": workers,
        "persistent_workers": PERSISTENT_WORKERS,
        "pin_memory": workers > 0,
    }
    if workers > 0:
        cfg["prefetch_factor"] = PREFETCH_FACTOR
    return cfg
