from __future__ import annotations

from v2.backend.app.cli.v2_gen5_reconcile_dataset import _coverage_report


def _row(
    row_id: str,
    decision_time: str,
    split: str,
) -> dict[str, object]:
    return {
        "row_id": row_id,
        "decision_time": decision_time,
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "target_action": "long",
        "split": split,
        "missing_mask": [False],
        "cost_evidence_sha256": "a" * 64,
    }


def test_coverage_blocks_champion_when_regime_labels_are_unproven() -> None:
    dataset = {
        "dataset_id": "dataset-1",
        "dataset_sha256": "b" * 64,
        "ordered_feature_names": ["close"],
        "rows": [
            _row("row-1", "2026-07-22T00:00:00Z", "train"),
            _row("row-2", "2026-07-24T00:00:00Z", "validation"),
            _row("row-3", "2026-07-27T00:00:00Z", "holdout"),
        ],
    }
    manifest = {"manifest_id": "manifest-1", "manifest_sha256": "c" * 64}
    reconciliation = {"accepted": True, "imported_rich_binding_rows": 397}

    report = _coverage_report(
        dataset,
        manifest,
        reconciliation,
        reproducible=True,
    )

    assert report["materially_wider_time_coverage"] is True
    assert report["regime_coverage_proven"] is False
    assert report["champion_training_authorized"] is False
    assert report["training_blockers"] == ["REGIME_COVERAGE_UNPROVEN"]
    assert report["exchange_action_taken"] is False


def test_coverage_detects_decision_time_group_split_overlap() -> None:
    dataset = {
        "dataset_id": "dataset-1",
        "dataset_sha256": "b" * 64,
        "ordered_feature_names": ["market_regime_code"],
        "rows": [
            _row("row-1", "2026-07-22T00:00:00Z", "train"),
            _row("row-2", "2026-07-22T00:00:00Z", "validation"),
            _row("row-3", "2026-07-27T00:00:00Z", "holdout"),
        ],
    }
    manifest = {"manifest_id": "manifest-1", "manifest_sha256": "c" * 64}
    reconciliation = {"accepted": True, "imported_rich_binding_rows": 397}

    report = _coverage_report(
        dataset,
        manifest,
        reconciliation,
        reproducible=True,
    )

    assert report["decision_time_group_overlap_across_splits"] is True
    assert report["champion_training_authorized"] is False
    assert "DECISION_TIME_GROUP_SPLIT_OVERLAP" in report["training_blockers"]
