from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from v2.backend.app.services.native_trainer import profiled_pit_replay_importer_v1 as importer
from v2.backend.app.services.native_trainer.durable_canonical_5m_label_archive import (
    DurableCanonical5mLabelArchive,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    build_archive_record,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger import (
    DurableFeatureSnapshotLedger,
)


def _clock() -> str:
    return datetime(2026, 7, 1, tzinfo=UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def test_importer_checkpoints_only_after_archived_rows_are_readable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_sample = object()
    batch = SimpleNamespace(
        training_observed_at=_clock(),
        scanned_start_sequence=1,
        scanned_end_sequence=1,
        scanned_record_count=1,
        samples=(source_sample,),
        exclusions=(),
        high_water_sha256="a" * 64,
        has_remaining_strict_rows=True,
    )
    record = build_archive_record(
        snapshot_id="profiled_pit_replay_v1_test",
        symbol="BTCUSDT",
        timeframe="5m",
        feature_cutoff=_clock(),
        decision_time=_clock(),
        available_at=_clock(),
        mtf_snapshot_id="feature_snapshot_v3_" + ("b" * 64),
        features={"close": 100.0},
    )
    appended: list[dict[str, object]] = []
    monkeypatch.setattr(importer, "load_profiled_training_ledger_v1", lambda **_kwargs: batch)
    monkeypatch.setattr(
        importer,
        "_label_high_water",
        lambda **_kwargs: {"high_water_sha256": "c" * 64},
    )
    monkeypatch.setattr(
        importer,
        "build_profiled_training_label_binding_v1",
        lambda **_kwargs: ({"label": "bound"}, ()),
    )
    monkeypatch.setattr(
        importer,
        "project_profiled_training_sample_to_replay_snapshot_v1",
        lambda **_kwargs: record,
    )
    monkeypatch.setattr(
        importer,
        "append_snapshot",
        lambda value, **_kwargs: (
            appended.append(dict(value)) or SimpleNamespace(already_present=False)
        ),
    )

    result = importer.import_next_profiled_pit_replay_shard_v1(
        ledger=DurableFeatureSnapshotLedger(tmp_path / "source.sqlite3"),
        trusted_immutable_cost_store_root=tmp_path,
        label_archive=DurableCanonical5mLabelArchive(tmp_path / "labels.sqlite3"),
        challenger_archive_root=tmp_path / "challenger-archive",
        checkpoint_root=tmp_path / "checkpoint",
        training_observed_at=_clock(),
        source_shard_rows=1,
    )

    checkpoint = json.loads((tmp_path / "checkpoint" / "checkpoint.json").read_text())
    assert appended == [record]
    assert result.rows_imported == 1
    assert result.checkpoint_last_completed_sequence == 1
    assert checkpoint["last_completed_sequence"] == 1
    assert checkpoint["completed_shards"][0]["record_content_sha256s"] == [
        record["content_sha256"]
    ]
