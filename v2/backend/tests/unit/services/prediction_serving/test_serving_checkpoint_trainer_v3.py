from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from v2.backend.app.services.prediction_serving.serving_checkpoint_trainer_v3 import (
    _publish_immutable_checkpoint,
    decision_group_balance,
    train_serving_checkpoint_v3,
)
from v2.backend.tests.unit.services.prediction_serving.test_serving_training_artifact_v2 import (
    ArtifactFixture,
    _build_artifacts,
)


def test_decision_group_balance_equalizes_cross_sectional_clusters() -> None:
    rows = [
        {"decision_time": "2026-07-27T10:00:01Z"},
        {"decision_time": "2026-07-27T10:00:20Z"},
        {"decision_time": "2026-07-27T10:00:59Z"},
        {"decision_time": "2026-07-27T10:01:01Z"},
    ]

    weights, report = decision_group_balance(rows)

    assert sum(weights[:3]) == pytest.approx(weights[3])
    assert sum(weights) == pytest.approx(len(rows))
    assert report["unique_decision_groups"] == 2
    assert report["unbalanced_cross_sectional_effective_groups_kish"] == pytest.approx(
        1.6
    )
    assert report["balanced_row_effective_sample_size_kish"] == pytest.approx(3.0)
    assert report["effective_independent_training_groups"] == pytest.approx(2.0)
    assert report["effective_independent_sample_size_kish"] == pytest.approx(2.0)
    assert report["group_aggregate_weight_equalized"] is True


def test_decision_group_balance_rejects_missing_point_in_time_clock() -> None:
    with pytest.raises(ValueError, match="TRAINING_DECISION_TIME_MALFORMED"):
        decision_group_balance([{"decision_time": None}])


def test_balanced_effective_groups_are_not_rejected_by_preweight_cluster_size() -> None:
    rows = [
        {"decision_time": "2026-07-27T10:00:01Z"}
        for _ in range(1_000)
    ]
    rows.extend(
        {"decision_time": f"2026-07-27T{10 + minute // 60:02d}:{minute % 60:02d}:01Z"}
        for minute in range(1, 100)
    )

    weights, report = decision_group_balance(rows)

    assert report["unique_decision_groups"] == 100
    assert report["unbalanced_cross_sectional_effective_groups_kish"] < 2.0
    assert report["balanced_row_effective_sample_size_kish"] > 100.0
    assert report["effective_independent_training_groups"] == pytest.approx(100.0)
    assert sum(weights[:1_000]) == pytest.approx(weights[1_000])


def test_authenticated_training_is_deterministic_and_nonactivating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import torch

    artifacts: ArtifactFixture = _build_artifacts(tmp_path / "artifacts", monkeypatch)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    first_bundle, first_report, first_path = train_serving_checkpoint_v3(
        dataset_path=artifacts.dataset_path,
        manifest_path=artifacts.manifest_path,
        parity_path=artifacts.parity_path,
        build_receipt_path=artifacts.receipt_path,
        output_dir=(tmp_path / "models-a").resolve(),
    )
    second_bundle, second_report, second_path = train_serving_checkpoint_v3(
        dataset_path=artifacts.dataset_path,
        manifest_path=artifacts.manifest_path,
        parity_path=artifacts.parity_path,
        build_receipt_path=artifacts.receipt_path,
        output_dir=(tmp_path / "models-b").resolve(),
    )

    assert first_bundle.checkpoint_id == second_bundle.checkpoint_id
    assert (
        first_bundle.model_parameter_fingerprint
        == second_bundle.model_parameter_fingerprint
    )
    assert first_bundle.weight_sha256 == second_bundle.weight_sha256
    assert first_path.read_bytes() == second_path.read_bytes()
    assert hashlib.sha256(first_path.read_bytes()).hexdigest() == first_bundle.weight_sha256
    assert first_bundle.generated_at == max(
        row["label_available_at"] for row in artifacts.dataset["rows"]
    )
    assert first_report["generated_at_semantics"] == (
        "LATEST_AUTHENTICATED_LABEL_AVAILABLE_AT"
    )
    assert first_report["training_artifact_authentication"] == second_report[
        "training_artifact_authentication"
    ]
    assert first_report["training_artifact_authentication"][
        "build_receipt_file_sha256"
    ] == hashlib.sha256(artifacts.receipt_path.read_bytes()).hexdigest()
    assert first_report["activation_eligible"] is False
    assert first_bundle.checkpoint_promotable is False
    assert first_bundle.live_eligible is False


def test_immutable_checkpoint_publish_is_idempotent_and_rejects_collision(
    tmp_path: Path,
) -> None:
    target = tmp_path / "checkpoint.pt"
    _publish_immutable_checkpoint(checkpoint_bytes=b"same", target_path=target)
    _publish_immutable_checkpoint(checkpoint_bytes=b"same", target_path=target)

    with pytest.raises(ValueError, match="CHECKPOINT_ID_COLLISION_WITH_DIFFERENT_BYTES"):
        _publish_immutable_checkpoint(checkpoint_bytes=b"different", target_path=target)

    assert target.read_bytes() == b"same"
