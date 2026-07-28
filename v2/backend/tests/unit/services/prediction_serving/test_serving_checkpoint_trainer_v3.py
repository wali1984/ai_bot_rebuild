from __future__ import annotations

import pytest

from v2.backend.app.services.prediction_serving.serving_checkpoint_trainer_v3 import (
    decision_group_balance,
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
