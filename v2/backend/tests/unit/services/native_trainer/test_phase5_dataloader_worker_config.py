"""Phase 5 — MASA/PPO worker scaling tests.

Validates:
 - compute_dataloader_workers() caps at MAX_DATALOADER_WORKERS (4)
 - compute_dataloader_workers() returns 0 below MIN_ROWS_FOR_MULTIWORKER (256)
 - PERSISTENT_WORKERS is always False (zombie-prevention invariant)
 - prefetch_factor is PREFETCH_FACTOR (2), not the old value of 4
 - dataloader_config() never sets persistent_workers=True
 - dataloader_config() sets pin_memory=True only when workers > 0
 - ppo_trainer module imports the worker config module (not inline)

Root cause of Phase 5 audit finding:
    Prior code had persistent_workers=True and uncapped worker count
    (max(1, min(32, cpu_count-2))), spawning 18 zombie pt_data_worker
    processes under PID 1037427.  Fixed 2026-06-17.
"""
from __future__ import annotations

import importlib
import inspect
import os
import textwrap

import pytest

from app.services.native_trainer.dataloader_worker_config import (
    MAX_DATALOADER_WORKERS,
    MIN_ROWS_FOR_MULTIWORKER,
    PERSISTENT_WORKERS,
    PREFETCH_FACTOR,
    compute_dataloader_workers,
    dataloader_config,
)


# ── Constants ─────────────────────────────────────────────────────────────────

def test_persistent_workers_constant_is_false() -> None:
    assert PERSISTENT_WORKERS is False, (
        "PERSISTENT_WORKERS must be False — True leaves zombie pt_data_worker processes "
        "when DataLoader is recreated per training call (Phase 5 audit finding)"
    )


def test_max_workers_cap_is_4() -> None:
    assert MAX_DATALOADER_WORKERS == 4


def test_prefetch_factor_is_2_not_4() -> None:
    # Old code used prefetch_factor=4; the new cap is 2 to reduce memory pressure.
    assert PREFETCH_FACTOR == 2


def test_min_rows_threshold_is_256() -> None:
    assert MIN_ROWS_FOR_MULTIWORKER == 256


# ── compute_dataloader_workers() ──────────────────────────────────────────────

def test_workers_zero_below_threshold() -> None:
    assert compute_dataloader_workers(cpu_count=32, row_count=0) == 0
    assert compute_dataloader_workers(cpu_count=32, row_count=255) == 0


def test_workers_zero_at_exactly_threshold_minus_1() -> None:
    assert compute_dataloader_workers(cpu_count=16, row_count=MIN_ROWS_FOR_MULTIWORKER - 1) == 0


def test_workers_nonzero_at_threshold() -> None:
    result = compute_dataloader_workers(cpu_count=4, row_count=MIN_ROWS_FOR_MULTIWORKER)
    assert result >= 1


def test_workers_capped_at_4_on_high_cpu_count() -> None:
    # 32-core machine would previously spawn 30 workers — now capped at 4.
    assert compute_dataloader_workers(cpu_count=32, row_count=1000) == 4
    assert compute_dataloader_workers(cpu_count=128, row_count=1000) == 4


def test_workers_at_least_1_on_low_cpu_count() -> None:
    assert compute_dataloader_workers(cpu_count=1, row_count=1000) == 1
    assert compute_dataloader_workers(cpu_count=2, row_count=1000) == 1


def test_workers_scales_with_cpu_count() -> None:
    # On a quad-core: cpu_count//4 = 1, min(4,1) = 1
    assert compute_dataloader_workers(cpu_count=4, row_count=1000) == 1
    # On an 8-core: cpu_count//4 = 2, min(4,2) = 2
    assert compute_dataloader_workers(cpu_count=8, row_count=1000) == 2
    # On a 16-core: cpu_count//4 = 4, min(4,4) = 4
    assert compute_dataloader_workers(cpu_count=16, row_count=1000) == 4


def test_workers_default_cpu_count_is_safe(monkeypatch) -> None:
    # Even if os.cpu_count() returns None, must return >= 1 above threshold.
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    result = compute_dataloader_workers(row_count=1000)
    assert 1 <= result <= MAX_DATALOADER_WORKERS


def test_workers_never_exceed_4_regardless_of_cpu_count() -> None:
    for cpu in [4, 8, 16, 32, 64, 128, 256]:
        result = compute_dataloader_workers(cpu_count=cpu, row_count=10000)
        assert result <= MAX_DATALOADER_WORKERS, (
            f"cpu_count={cpu} produced {result} workers, expected <= {MAX_DATALOADER_WORKERS}"
        )


# ── dataloader_config() ───────────────────────────────────────────────────────

def test_config_persistent_workers_always_false() -> None:
    for rows in [0, 100, 256, 1000, 10000]:
        cfg = dataloader_config(cpu_count=16, row_count=rows)
        assert cfg["persistent_workers"] is False, (
            f"persistent_workers must be False for row_count={rows}"
        )


def test_config_pin_memory_false_when_no_workers() -> None:
    cfg = dataloader_config(cpu_count=16, row_count=0)
    assert cfg["pin_memory"] is False
    assert cfg["num_workers"] == 0


def test_config_pin_memory_true_when_workers_present() -> None:
    cfg = dataloader_config(cpu_count=16, row_count=1000)
    assert cfg["num_workers"] > 0
    assert cfg["pin_memory"] is True


def test_config_prefetch_factor_absent_when_no_workers() -> None:
    cfg = dataloader_config(cpu_count=16, row_count=0)
    assert "prefetch_factor" not in cfg


def test_config_prefetch_factor_is_2_when_workers_present() -> None:
    cfg = dataloader_config(cpu_count=16, row_count=1000)
    assert cfg.get("prefetch_factor") == 2


# ── ppo_trainer source-level invariants ──────────────────────────────────────

def test_ppo_trainer_imports_worker_config_module() -> None:
    ppo_mod = importlib.import_module(
        "app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer"
    )
    src = inspect.getsource(ppo_mod)
    assert "dataloader_worker_config" in src, (
        "ppo_trainer.py must import from dataloader_worker_config — "
        "inline config is the source of the zombie worker bug"
    )


def test_ppo_trainer_does_not_hardcode_persistent_workers_true() -> None:
    ppo_mod = importlib.import_module(
        "app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer"
    )
    src = inspect.getsource(ppo_mod)
    assert "persistent_workers=True" not in src, (
        "ppo_trainer.py must not set persistent_workers=True (zombie-worker risk)"
    )


def test_ppo_trainer_deletes_loader_in_finally() -> None:
    ppo_mod = importlib.import_module(
        "app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer"
    )
    src = inspect.getsource(ppo_mod)
    assert "del loader" in src, (
        "ppo_trainer.py must explicitly 'del loader' in finally block to release workers promptly"
    )


def test_ppo_trainer_does_not_set_large_worker_count_inline() -> None:
    ppo_mod = importlib.import_module(
        "app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer"
    )
    src = inspect.getsource(ppo_mod)
    # The old code was: max(1, min(32, (os.cpu_count() or 4) - 2))
    assert "min(32" not in src, (
        "ppo_trainer.py must not inline a worker cap of 32 — use compute_dataloader_workers()"
    )


# ── Zombie-prevention integration assertion ───────────────────────────────────

def test_no_persistent_workers_means_no_zombie_accumulation() -> None:
    """
    Invariant: if persistent_workers is False and del loader is called,
    workers terminate when the DataLoader is released.
    This test encodes the invariant at the module-config level.
    """
    cfg = dataloader_config(cpu_count=16, row_count=1000)
    assert cfg["persistent_workers"] is False
    # When persistent_workers=False, PyTorch sends shutdown signals to workers
    # as soon as the DataLoader object is __del__'d or goes out of scope.
    # The 'del loader' in ppo_trainer.py ensures this happens before the
    # next training call, preventing zombie accumulation.
    # The 18 zombie processes observed under PID 1037427 on 2026-06-17
    # were caused by persistent_workers=True on DataLoaders that were GC'd.
