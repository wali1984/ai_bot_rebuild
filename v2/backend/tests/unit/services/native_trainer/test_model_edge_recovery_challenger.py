from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from v2.backend.app.services.native_trainer.model_edge_recovery_challenger import (
    CHAMPION_CHALLENGER_STATUS_REDIS_KEY,
    CHAMPION_BASELINE,
    PAPER_CHALLENGER_TIER,
    ChallengerModel,
    EdgeRecoveryRow,
    _row_reject_reasons,
    build_paper_challenger_signal,
    champion_challenger_status_from_result,
    evaluate_predictions,
    publish_champion_challenger_status,
    predict_rows,
    train_challenger_model,
)


BASE_TIME = datetime(2026, 6, 22, 0, 0, tzinfo=timezone.utc)


def _iso(*, minutes: int, seconds: int = 0) -> str:
    return (BASE_TIME + timedelta(minutes=minutes, seconds=seconds)).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _trusted_snapshot(**overrides: object) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "snapshot_id": "snap-1",
        "feature_snapshot_id": "snap-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": _iso(minutes=0),
        "available_at": _iso(minutes=0, seconds=30),
        "decision_time": _iso(minutes=1),
        "generated_at": _iso(minutes=1),
        "mtf_snapshot_id": "mtf-1",
        "candle_open_time": _iso(minutes=-1),
        "candle_close_time": _iso(minutes=0),
        "candle_closed_confirmed": True,
        "feature_freshness_state": "CURRENT",
        "features": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "edge": 2.0,
        },
    }
    snapshot.update(overrides)
    return snapshot


def _row(index: int, value_bps: float, edge: float) -> EdgeRecoveryRow:
    return EdgeRecoveryRow(
        sample_id=f"row-{index:03d}",
        snapshot_id=f"snap-{index:03d}",
        symbol="BTCUSDT",
        timeframe="1m",
        decision_time=_iso(minutes=index, seconds=1),
        feature_cutoff=_iso(minutes=index),
        available_at=_iso(minutes=index),
        future_return_after_cost_bps=value_bps,
        target_action="long" if value_bps > 0 else "short",
        features={"edge": edge, "noise": float(index % 7)},
    )


def test_row_reject_reasons_enforce_point_in_time_guards() -> None:
    assert _row_reject_reasons(_trusted_snapshot()) == []

    assert "AVAILABLE_AT_AFTER_DECISION_TIME" in _row_reject_reasons(
        _trusted_snapshot(available_at=_iso(minutes=2))
    )
    assert "FEATURE_CUTOFF_AFTER_DECISION_TIME" in _row_reject_reasons(
        _trusted_snapshot(feature_cutoff=_iso(minutes=2))
    )
    assert "OPEN_CANDLE_REJECTED" in _row_reject_reasons(
        _trusted_snapshot(candle_closed_confirmed=False)
    )

    leaked_features = dict(_trusted_snapshot()["features"])
    leaked_features["future_return_15m_bps"] = 99.0
    assert "FUTURE_LABEL_PRESENT_IN_FEATURES" in _row_reject_reasons(
        _trusted_snapshot(features=leaked_features)
    )


def test_evaluate_predictions_reports_challenger_trade_edge() -> None:
    rows = [
        _row(0, 10.0, 1.0),
        _row(1, -10.0, -1.0),
        _row(2, 10.0, 1.0),
        _row(3, -10.0, -1.0),
    ]

    metrics = evaluate_predictions(
        rows=rows,
        predictions=[5.0, -5.0, -5.0, 5.0],
        threshold_bps=1.0,
    )

    assert metrics["trade_count"] == 4
    assert metrics["true_positive_count"] == 2
    assert metrics["false_positive_count"] == 2
    assert metrics["directional_accuracy"] == pytest.approx(0.5)
    assert metrics["false_positive_rate"] == pytest.approx(0.5)
    assert metrics["after_cost_expectancy_bps"] == pytest.approx(0.0)
    assert metrics["expected_move_mae_bps"] == pytest.approx(10.0)
    assert metrics["expectancy_scope"] == "directional_challenger_trades_only"


def test_train_challenger_model_selects_on_validation_and_holdout_beats_baseline() -> None:
    rows = [
        _row(i, 18.0 if i % 4 in {0, 1} else -18.0, 1.8 if i % 4 in {0, 1} else -1.8)
        for i in range(120)
    ]
    train_rows = rows[:80]
    validation_rows = rows[80:100]
    holdout_rows = rows[100:]

    model = train_challenger_model(
        train_rows=train_rows,
        validation_rows=validation_rows,
        ridge_lambdas=(0.1,),
        thresholds_bps=(0.0, 4.0, 8.0),
        min_validation_trades=10,
        max_features=4,
    )
    holdout_metrics = evaluate_predictions(
        rows=holdout_rows,
        predictions=predict_rows(model, holdout_rows),
        threshold_bps=model.threshold_bps,
    )

    assert model.target_transform == "clipped_future_return_after_cost_bps"
    assert model.target_clip_bps == pytest.approx(50.0)
    assert len(model.feature_names) <= 4
    assert model.validation_metrics["selection_validation_supply_floor"] == len(validation_rows)
    assert model.validation_metrics["trade_count"] >= model.validation_metrics["selection_validation_supply_floor"]
    assert holdout_metrics["trade_count"] == len(holdout_rows)
    assert holdout_metrics["after_cost_expectancy_bps"] > 0.0
    assert holdout_metrics["directional_accuracy"] > CHAMPION_BASELINE["directional_accuracy"]
    assert holdout_metrics["expected_move_mae_bps"] < CHAMPION_BASELINE["expected_move_mae_bps"]
    assert holdout_metrics["false_positive_rate"] < CHAMPION_BASELINE["false_positive_rate"]


def test_build_paper_challenger_signal_is_b_grade_paper_only() -> None:
    model = ChallengerModel(
        feature_names=["edge"],
        means=[0.0],
        stds=[1.0],
        weights=[10.0],
        bias=0.0,
        ridge_lambda=0.1,
        threshold_bps=5.0,
        validation_metrics={"after_cost_expectancy_bps": 10.0},
    )

    signal = build_paper_challenger_signal(
        model=model,
        snapshot=_trusted_snapshot(),
        result_hash="result-hash",
    )

    assert signal is not None
    assert signal["side"] == "long"
    assert signal["paper_opportunity_tier"] == PAPER_CHALLENGER_TIER
    assert signal["paper_fill_allowed"] is False
    assert signal["paper_only"] is True
    assert signal["routes_to_live"] is False
    assert signal["places_real_order"] is False
    assert signal["live_symbols"] == []
    assert signal["counts_as_a_grade_evidence"] is False
    assert signal["a_grade_promotion_allowed"] is False


def test_build_paper_challenger_signal_fails_closed_on_dirty_current_snapshot() -> None:
    model = ChallengerModel(
        feature_names=["edge"],
        means=[0.0],
        stds=[1.0],
        weights=[10.0],
        bias=0.0,
        ridge_lambda=0.1,
        threshold_bps=5.0,
        validation_metrics={},
    )

    future_available = _trusted_snapshot(available_at=_iso(minutes=2))
    assert build_paper_challenger_signal(
        model=model,
        snapshot=future_available,
        result_hash="result-hash",
    ) is None

    leaked_features = dict(_trusted_snapshot()["features"])
    leaked_features["future_return_15m_bps"] = 999.0
    assert build_paper_challenger_signal(
        model=model,
        snapshot=_trusted_snapshot(features=leaked_features),
        result_hash="result-hash",
    ) is None


def test_champion_challenger_status_contract_is_paper_only_and_not_a_grade_promotion() -> None:
    result = {
        "generated_utc": _iso(minutes=10),
        "goal_id": "unit-goal",
        "status": "PASSED_PAPER_CHALLENGER_READY",
        "result_hash": "abcdef1234567890fedcba",
        "paper_challenger_policy": {
            "enabled": True,
            "paper_opportunity_tier": PAPER_CHALLENGER_TIER,
            "counts_as_a_grade_evidence": False,
            "a_grade_promotion_allowed": False,
        },
        "dataset_freeze": {"trusted_replay_rows": 300, "snapshots_scanned": 400},
        "row_counts": {"train": 210, "validation": 45, "untouched_holdout": 45},
        "model": {
            "model_source": "unit-model",
            "threshold_bps": 5.0,
            "feature_names": ["edge"],
            "validation_metrics": {"trade_count": 12},
        },
        "untouched_holdout_metrics": {"trade_count": 10, "after_cost_expectancy_bps": 7.5},
        "point_in_time_safety": {"future_labels_used_as_features": False},
    }

    status = champion_challenger_status_from_result(result, source="unit")

    assert status["status"] == "CHAMPION_CHALLENGER_EVALUATED_PAPER_READY"
    assert status["best_challenger_id"] == "model_edge_recovery:abcdef1234567890"
    assert status["promotion_allowed"] is False
    assert status["promotion_reason"].startswith("paper challenger passed holdout")
    assert status["backtests_processed"]["validation_trade_count"] == 12
    assert status["backtests_processed"]["untouched_holdout_trade_count"] == 10
    assert status["safety"]["paper_only"] is True
    assert status["safety"]["routes_to_live"] is False
    assert status["safety"]["places_real_order"] is False
    assert status["safety"]["a_grade_promotion_allowed"] is False


def test_publish_champion_challenger_status_writes_canonical_redis_key() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.rows: list[tuple[str, str, int | None]] = []

        def set(self, key: str, value: str, ex: int | None = None) -> bool:
            self.rows.append((key, value, ex))
            return True

    fake = FakeRedis()
    status = publish_champion_challenger_status(
        client=fake,
        result={
            "status": "BLOCKED_HOLDOUT_EDGE_NOT_PROVEN",
            "blocker_reasons": ["POSITIVE_AFTER_COST_EXPECTANCY_FAILED"],
            "result_hash": "1234",
            "paper_challenger_policy": {"enabled": False},
        },
    )

    assert status["status"] == "CHAMPION_CHALLENGER_EVALUATED_BLOCKED"
    assert status["best_challenger_id"] is None
    assert status["promotion_allowed"] is False
    assert fake.rows[0][0] == CHAMPION_CHALLENGER_STATUS_REDIS_KEY
    assert fake.rows[0][2] is not None and fake.rows[0][2] >= 60
