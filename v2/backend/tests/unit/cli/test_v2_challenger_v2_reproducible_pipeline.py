from __future__ import annotations

from pathlib import Path

from v2.backend.app.cli import v2_challenger_v2_reproducible_pipeline as pipeline


def test_historical_challenger_dataset_fails_closed_without_indexed_5m_labels(
    tmp_path: Path,
) -> None:
    rows, manifest, rejections = pipeline._build_dataset(  # noqa: SLF001
        repo_root=tmp_path,
        scan_limit=250_000,
        replay_limit=50_000,
    )

    assert rows == []
    assert manifest["status"] == (
        "BLOCKED_DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED"
    )
    assert manifest["dataset_build_allowed"] is False
    assert manifest["snapshots_scanned"] == 0
    assert manifest["same_timeframe_label_fallback_used"] is False
    assert manifest["mutable_redis_history_used_for_historical_labels"] is False
    assert manifest["required_label_source"] == (
        "DURABLE_TIME_INDEXED_CANONICAL_FINALIZED_5M_CANDLE_ARCHIVE"
    )
    assert rejections == {"DURABLE_INDEXED_5M_LABEL_ARCHIVE_REQUIRED": 1}
