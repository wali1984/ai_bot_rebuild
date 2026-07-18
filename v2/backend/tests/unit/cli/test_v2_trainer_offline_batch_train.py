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


def test_legacy_object_cache_is_never_deserialized_or_overwritten(
    monkeypatch, tmp_path: Path
) -> None:
    from v2.backend.app.services.native_trainer import (
        durable_feature_snapshot_archive as archive_mod,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import (
        data_loader as data_loader_mod,
    )

    malicious = b"\x80\x04cos\nsystem\n(S'forbidden'\ntR."
    cache = tmp_path / "legacy-cache.pkl"
    cache.write_bytes(malicious)
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "manifest.jsonl").write_text("{}\n", encoding="utf-8")

    example = object()

    class FakeLoader:
        def __init__(self, *, trusted_replay_archive_root):
            assert trusted_replay_archive_root != archive

        def load_training_examples(self, **_kwargs):
            return []

        def load_trusted_replay_examples(self, *, limit):
            return [example] if limit else []

    monkeypatch.setattr(archive_mod, "default_archive_root", lambda: archive)
    monkeypatch.setattr(data_loader_mod, "V2HybridTrainerDataLoader", FakeLoader)

    examples, meta = bt.load_or_build_examples(
        symbols=["BTCUSDT"],
        timeframes=["1m"],
        limit=1,
        cache_path=str(cache),
        rebuild_cache=False,
    )

    assert examples == [example]
    assert cache.read_bytes() == malicious
    assert meta["cache_hit"] is False
    assert meta["cache_read_attempted"] is False
    assert meta["cache_write_attempted"] is False
    assert meta["legacy_object_cache_ignored"] is True
    assert meta["legacy_object_cache_blocker"] == bt.LEGACY_OBJECT_CACHE_BLOCKER
    assert meta["external_object_deserialization_used"] is False


def test_offline_batch_module_has_no_unsafe_object_cache_api() -> None:
    source = Path(bt.__file__).read_text(encoding="utf-8")
    assert "import pickle" not in source
    assert "pickle.load(" not in source
    assert "pickle.loads(" not in source
    assert "pickle.dump(" not in source


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


def test_seed_offline_view_cursor_targets_recent_tail(tmp_path) -> None:
    """Regression: the offline view cursor started at byte 0 (oldest snapshots,
    weeks stale) so every cache rebuild reproduced the same ancient window and
    the flywheel never trained on new data (bit-identical H2L verdicts across
    rebuilds). The seed must land before-but-near the hours_back target."""
    import json as _json
    from datetime import datetime, timedelta, timezone

    from v2.backend.app.cli.v2_trainer_offline_batch_train import (
        seed_offline_view_cursor_near_tail,
    )

    manifest = tmp_path / "manifest.jsonl"
    now = datetime.now(tz=timezone.utc)
    lines = []
    total = 20000
    for i in range(total):  # oldest-first, spanning 48h -> now
        created = now - timedelta(hours=48.0 * (total - 1 - i) / (total - 1))
        lines.append(_json.dumps({
            "snapshot_id": f"snap_{i:06d}",
            "created_at": created.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "blob_path": "blobs/xx/yy/zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
        }))
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    meta = seed_offline_view_cursor_near_tail(tmp_path, hours_back=12.0)
    assert meta["seeded"] is True
    offset = meta["manifest_offset"]
    assert offset > manifest.stat().st_size * 0.5  # deep into the tail half
    cursor = _json.loads((tmp_path / "trusted_replay_cursor.json").read_text())
    assert cursor["manifest_offset"] == offset
    # The record just after the offset must still be OLDER than the target
    # (never overshoot: overshooting would skip labelable rows).
    with manifest.open("rb") as fh:
        fh.seek(offset)
        if offset:
            fh.readline()
        rec = _json.loads(fh.readline())
    assert rec["created_at"] < meta["seed_target_created_at"]


def test_seed_offline_view_cursor_skips_young_archive(tmp_path) -> None:
    """An archive younger than the window keeps offset 0 (nothing to seed)."""
    import json as _json
    from datetime import datetime, timezone

    from v2.backend.app.cli.v2_trainer_offline_batch_train import (
        seed_offline_view_cursor_near_tail,
    )

    manifest = tmp_path / "manifest.jsonl"
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    manifest.write_text(_json.dumps({"snapshot_id": "s1", "created_at": now}) + "\n")
    meta = seed_offline_view_cursor_near_tail(tmp_path, hours_back=12.0)
    assert meta["seeded"] is False
    assert not (tmp_path / "trusted_replay_cursor.json").exists()
