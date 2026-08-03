from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.prediction_serving.serving_dataset_v2 import (
    _chronological_split,
    build_serving_dataset_v2,
)


def test_chronological_split_never_divides_a_decision_time_group() -> None:
    rows = [
        {
            "row_id": f"row-{group:03d}-{member}",
            "decision_time": f"2026-07-01T{group // 60:02d}:{group % 60:02d}:00Z",
        }
        for group in range(60)
        for member in range(2)
    ]

    admitted, embargo_ids = _chronological_split(rows)

    groups_by_split = {
        split: {
            row["decision_time"] for row in admitted if row["split"] == split
        }
        for split in ("train", "validation", "holdout")
    }
    assert groups_by_split["train"].isdisjoint(groups_by_split["validation"])
    assert groups_by_split["train"].isdisjoint(groups_by_split["holdout"])
    assert groups_by_split["validation"].isdisjoint(groups_by_split["holdout"])
    assert len(embargo_ids) == 8
    assert len(admitted) + len(embargo_ids) == len(rows)
    assert sum(row["split"] == "train" for row in admitted) >= 80
    assert sum(row["split"] == "validation" for row in admitted) >= 10
    assert sum(row["split"] == "holdout" for row in admitted) >= 10


def test_real_authenticated_dataset_is_reproducible_and_pit_clean() -> None:
    repo = Path(__file__).resolve().parents[6]
    identity = repo / ".local_models/paper_provisional/admitted_114_identity.json"
    archive = Path(
        "/home/wali/ai_bot_local_data/v2_native_trainer/durable_feature_snapshot_archive"
    )
    if not identity.exists() or not archive.exists():
        return
    first = build_serving_dataset_v2(identity_manifest_path=identity, archive_root=archive)
    second = build_serving_dataset_v2(identity_manifest_path=identity, archive_root=archive)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    dataset, manifest, parity = first
    assert manifest["training_rows"] >= 80
    assert manifest["validation_rows"] >= 10
    assert manifest["holdout_rows"] >= 10
    assert manifest["duplicate_rows"] == 0
    assert manifest["future_time_rejections"] == 0
    assert manifest["finality_unproven"] == 0
    assert manifest["missing_cost_evidence"] == 0
    assert manifest["missing_label_evidence"] == 0
    assert all(sum(row["missing_mask"]) == 0 for row in dataset["rows"])
    assert parity["builder_match"] is True
