"""`trainer_online_learning_active` must reflect whether training is real.

The check historically read only `v2:trainer:hybrid_cuda:metrics`, which is
written solely by the persistent/online lane. That lane is gated on an external
witness service that is not configured, so the key never exists and the check
was permanently false -- blocking every trade -- while the continuous offline
lane was demonstrably training on the GPU.

The offline fallback must therefore pass on genuine recent training and fail on
anything that is not: stale cycles, point-in-time-dirty cycles, and cycles that
moved no weights.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from v2.backend.app.services.a_plus_trade_gate.service import (
    OFFLINE_TRAINER_EVIDENCE_MAX_AGE_SECONDS,
    _offline_training_evidence,
    _trainer_learning_check,
)

NOW = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)


def _report(**overrides: object) -> dict:
    report = {
        "total_gradient_steps": 300,
        "examples": 8192,
        "loss_first": 132.6,
        "loss_last": 18.5,
        "loss_improved": True,
        "point_in_time_safety": {
            "passed": True,
            "violation_count": 0,
            "evaluation_observed_at": (NOW - timedelta(minutes=5)).isoformat(),
        },
    }
    report.update(overrides)
    return report


def _online_metrics(**overrides: object) -> dict:
    metrics = {
        "online_learning_status": "WEIGHTS_UPDATING",
        "trusted_rows_loaded": 500,
        "last_successful_weight_update_at": NOW.isoformat(),
    }
    metrics.update(overrides)
    return {"training": {"metrics": metrics}}


# --------------------------------------------------------------------------- #
# Passing: real, recent, point-in-time-clean training.
# --------------------------------------------------------------------------- #
def test_recent_clean_offline_cycle_counts_as_learning() -> None:
    result = _trainer_learning_check(None, _report(), now=NOW)
    assert result["passed"] is True
    assert "offline_lane_training" in result["reason"]
    assert "optimizer_steps=300" in result["reason"]


def test_online_lane_still_wins_when_it_publishes() -> None:
    result = _trainer_learning_check(_online_metrics(), None, now=NOW)
    assert result["passed"] is True
    assert "online_learning_status=WEIGHTS_UPDATING" in result["reason"]


# --------------------------------------------------------------------------- #
# Failing: everything that is not evidence of healthy current training.
# --------------------------------------------------------------------------- #
def test_no_evidence_at_all_fails() -> None:
    result = _trainer_learning_check(None, None, now=NOW)
    assert result["passed"] is not True
    assert result["missing_evidence"] is True


def test_stale_cycle_is_not_evidence_of_learning_now() -> None:
    stale = _report()
    stale["point_in_time_safety"]["evaluation_observed_at"] = (
        NOW - timedelta(seconds=OFFLINE_TRAINER_EVIDENCE_MAX_AGE_SECONDS + 60)
    ).isoformat()
    assert _trainer_learning_check(None, stale, now=NOW)["passed"] is not True


@pytest.mark.parametrize("pit", [{"passed": False, "violation_count": 0}, {"passed": True, "violation_count": 3}])
def test_point_in_time_dirty_cycle_is_rejected(pit: dict) -> None:
    dirty = _report()
    pit = dict(pit)
    pit["evaluation_observed_at"] = (NOW - timedelta(minutes=5)).isoformat()
    dirty["point_in_time_safety"] = pit
    assert _trainer_learning_check(None, dirty, now=NOW)["passed"] is not True


@pytest.mark.parametrize("field", ["total_gradient_steps", "examples"])
def test_a_cycle_that_moved_nothing_is_rejected(field: str) -> None:
    empty = _report(**{field: 0})
    assert _trainer_learning_check(None, empty, now=NOW)["passed"] is not True


def test_missing_point_in_time_block_is_rejected() -> None:
    no_pit = _report()
    del no_pit["point_in_time_safety"]
    assert _offline_training_evidence(no_pit, now=NOW) is None


def test_missing_timestamp_is_rejected() -> None:
    undated = _report()
    del undated["point_in_time_safety"]["evaluation_observed_at"]
    assert _offline_training_evidence(undated, now=NOW) is None


def test_inactive_online_lane_falls_through_to_offline_evidence() -> None:
    idle = _online_metrics(online_learning_status="IDLE", trusted_rows_loaded=0)
    assert _trainer_learning_check(idle, _report(), now=NOW)["passed"] is True
    # ...and with no offline cycle it stays false rather than silently passing.
    assert _trainer_learning_check(idle, None, now=NOW)["passed"] is not True


# --------------------------------------------------------------------------- #
# side_bucket_positive is circular: a side needs positive realised expectancy
# to trade, but expectancy only moves by trading that side. It is observed in
# the paper learning lane -- but absence of evidence must never become
# permission, and genuine positives must not be relabelled.
# --------------------------------------------------------------------------- #
from v2.backend.app.services.a_plus_trade_gate.service import (  # noqa: E402
    APlusGateConfig,
    _side_bucket_check,
)

CFG = APlusGateConfig()


def _side(expectancy: float, trades: int = 80) -> dict:
    return {"sides": {"LONG": {"trade_count": trades, "expectancy_bps": expectancy}}}


def test_negative_expectancy_is_observed_not_enforced() -> None:
    result = _side_bucket_check(
        _side(-5.66), side="long", confidence_calibrated=0.8, config=CFG
    )
    assert result["passed"] is True
    # The real verdict survives for the operator/GUI.
    assert result["reason"].startswith("MONITOR_ONLY_OBSERVED:")
    assert "-5.66" in result["reason"]


@pytest.mark.parametrize(
    "performance", [None, {}, {"sides": {}}, {"sides": {"SHORT": {"trade_count": 5}}}]
)
def test_missing_side_evidence_still_fails_closed(performance: object) -> None:
    result = _side_bucket_check(
        performance, side="long", confidence_calibrated=0.8, config=CFG
    )
    assert result["passed"] is not True
    assert result["missing_evidence"] is True


def test_genuine_positive_expectancy_passes_on_its_own_merit() -> None:
    result = _side_bucket_check(
        _side(12.5), side="long", confidence_calibrated=0.8, config=CFG
    )
    assert result["passed"] is True
    # Not a monitor-only pass -- it earned it.
    assert "MONITOR_ONLY_OBSERVED" not in result["reason"]
    assert "expectancy_bps=12.50" in result["reason"]
