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
    assert report["effective_independent_sample_size_kish"] == pytest.approx(1.6)
    assert report["group_aggregate_weight_equalized"] is True


def test_decision_group_balance_rejects_missing_point_in_time_clock() -> None:
    with pytest.raises(ValueError, match="TRAINING_DECISION_TIME_MALFORMED"):
        decision_group_balance([{"decision_time": None}])
