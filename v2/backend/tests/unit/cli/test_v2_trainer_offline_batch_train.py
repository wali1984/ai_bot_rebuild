"""Unit tests for the offline GPU-saturating batch trainer.

These cover the safety-critical seams without needing CUDA or the archive:
- the independent archive view must NOT expose the live replay cursors, so the
  running trainer's cursor is never advanced;
- saving must refuse to write into/around the live checkpoint directory;
- the GPU sampler degrades gracefully when nvidia-smi is unavailable.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.cli import v2_trainer_offline_batch_train as bt


def test_independent_archive_view_symlinks_data_but_omits_live_cursors(tmp_path: Path) -> None:
    real = tmp_path / "archive"
    real.mkdir()
    (real / "manifest.jsonl").write_text("{}\n", encoding="utf-8")
    (real / "blobs").mkdir()
    (real / "blobs" / "x.json").write_text("{}", encoding="utf-8")
    (real / "trusted_replay_cursor.json").write_text('{"offset": 999}', encoding="utf-8")
    (real / "trusted_replay_backfill_cursor.json").write_text('{"offset": 5}', encoding="utf-8")

    view = tmp_path / "view"
    bt.build_independent_archive_view(real, view)

    # Data is symlinked through.
    assert (view / "manifest.jsonl").exists()
    assert (view / "blobs").exists()
    # The live cursors are DELIBERATELY absent so the offline loader starts at 0
    # and writes its own cursor here, never advancing the live trainer's cursor.
    assert not (view / "trusted_replay_cursor.json").exists()
    assert not (view / "trusted_replay_backfill_cursor.json").exists()
    # The real cursor is untouched.
    assert (real / "trusted_replay_cursor.json").read_text(encoding="utf-8") == '{"offset": 999}'


def test_save_offline_weights_refuses_live_checkpoint_dir() -> None:
    class _Model:
        input_dim = 8

    with pytest.raises(ValueError, match="live checkpoint dir"):
        bt.save_offline_weights(_Model(), bt.LIVE_CHECKPOINT_DIR)


def test_save_offline_weights_refuses_paths_under_live_dir() -> None:
    class _Model:
        input_dim = 8

    with pytest.raises(ValueError, match="live checkpoint dir"):
        bt.save_offline_weights(_Model(), bt.LIVE_CHECKPOINT_DIR + "/nested")


def test_gpu_sampler_reports_gracefully_without_samples() -> None:
    sampler = bt.GpuUtilizationSampler(interval_s=0.1)
    report = sampler.report()
    assert report["samples"] == 0
    assert report["gpu_utilization_mean_pct"] is None


def test_run_batch_training_rejects_empty_examples() -> None:
    with pytest.raises(ValueError, match="at least one example"):
        bt.run_batch_training(
            [],
            epochs=1,
            steps_per_epoch=1,
            batch_size=8,
            learning_rate=1e-4,
            entropy_coefficient=0.01,
            weight_decay=0.02,
            dropout=0.1,
            validation_fraction=0.2,
            from_checkpoint=False,
        )


def test_default_offline_dir_is_not_the_live_dir() -> None:
    # Guard against a regression where the offline default points at live weights.
    assert bt.DEFAULT_OFFLINE_DIR != bt.LIVE_CHECKPOINT_DIR
    assert "offline" in bt.DEFAULT_OFFLINE_DIR
