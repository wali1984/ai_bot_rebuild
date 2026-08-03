"""F-0013: trusted replay lane must consume labelable snapshots via a
persistent oldest-first cursor with an embargo frontier, never a bounded
newest-first scan (which only ever sees un-labelable too-new rows)."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    iter_manifest_records_from_offset,
)


def _write_manifest(root: Path, rows: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return manifest


class TestManifestOffsetWalker:
    def test_walks_oldest_first_and_reports_resumable_offsets(self, tmp_path):
        rows = [{"snapshot_id": f"s{i}", "created_at": f"2026-07-0{1+i}T00:00:00Z"} for i in range(5)]
        _write_manifest(tmp_path, rows)
        seen = list(iter_manifest_records_from_offset(tmp_path, start_offset=0))
        assert [r["snapshot_id"] for _, r in seen] == ["s0", "s1", "s2", "s3", "s4"]
        # resume from the offset after s1 -> s2 first
        offset_after_s1 = seen[1][0]
        resumed = list(iter_manifest_records_from_offset(tmp_path, start_offset=offset_after_s1))
        assert [r["snapshot_id"] for _, r in resumed] == ["s2", "s3", "s4"]

    def test_limit_respected(self, tmp_path):
        rows = [{"snapshot_id": f"s{i}"} for i in range(10)]
        _write_manifest(tmp_path, rows)
        seen = list(iter_manifest_records_from_offset(tmp_path, start_offset=0, limit=3))
        assert len(seen) == 3

    def test_corrupt_lines_skipped(self, tmp_path):
        manifest = tmp_path / "manifest.jsonl"
        tmp_path.mkdir(parents=True, exist_ok=True)
        manifest.write_text('{"snapshot_id": "a"}\nnot-json\n{"snapshot_id": "b"}\n', encoding="utf-8")
        seen = list(iter_manifest_records_from_offset(tmp_path, start_offset=0))
        assert [r["snapshot_id"] for _, r in seen] == ["a", "b"]

    def test_missing_manifest_yields_nothing(self, tmp_path):
        assert list(iter_manifest_records_from_offset(tmp_path / "nope", start_offset=0)) == []
