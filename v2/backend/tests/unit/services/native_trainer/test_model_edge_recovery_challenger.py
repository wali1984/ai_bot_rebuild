from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.services.native_trainer import model_edge_recovery_challenger as challenger
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    content_sha256 as archive_content_sha256,
)
from v2.backend.app.services.native_trainer.model_edge_recovery_challenger import (
    ACTION_SPECIFIC_COST_POLICY,
    CHAMPION_BASELINE,
    CHAMPION_CHALLENGER_STATUS_REDIS_KEY,
    MIN_TEMPORAL_EMBARGO_SECONDS,
    PAPER_CHALLENGER_TIER,
    POLICY_VERSION,
    SCHEMA_VERSION,
    ChallengerModel,
    DatasetFreeze,
    EdgeRecoveryRow,
    _explicit_cost_evidence,
    _row_reject_reasons,
    _split_rows,
    build_paper_challenger_signal,
    champion_challenger_status_from_result,
    evaluate_predictions,
    predict_rows,
    publish_champion_challenger_status,
    train_challenger_model,
)

BASE_TIME = datetime(2026, 6, 22, 0, 0, tzinfo=UTC)


def _iso(*, minutes: int, seconds: int = 0) -> str:
    return (
        (BASE_TIME + timedelta(minutes=minutes, seconds=seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


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
        "latest_unclosed_kline_excluded": True,
        "feature_freshness_state": "CURRENT",
        "features": {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "edge": 2.0,
            "fee_bps": 4.0,
            "expected_slippage_bps": 1.0,
            "expected_funding_bps": 2.0,
        },
    }
    snapshot.update(overrides)
    snapshot["content_sha256"] = archive_content_sha256(snapshot)
    return snapshot


def _row(
    index: int,
    value_bps: float,
    edge: float,
    *,
    symbol: str | None = None,
    timeframe: str = "1m",
    decision_minutes: int | None = None,
    total_cost_bps: float = 2.0,
) -> EdgeRecoveryRow:
    decision_minutes = index if decision_minutes is None else decision_minutes
    decision_time = BASE_TIME + timedelta(minutes=decision_minutes, seconds=1)
    long_net_bps = value_bps - total_cost_bps
    short_net_bps = -value_bps - total_cost_bps
    return EdgeRecoveryRow(
        sample_id=f"row-{index:03d}",
        snapshot_id=f"snap-{index:03d}",
        symbol=symbol or ("BTCUSDT" if index % 2 == 0 else "ETHUSDT"),
        timeframe=timeframe,
        decision_time=decision_time.isoformat(timespec="seconds").replace("+00:00", "Z"),
        feature_cutoff=(decision_time - timedelta(seconds=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        available_at=(decision_time - timedelta(seconds=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        label_available_at=(decision_time + timedelta(hours=4, seconds=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        raw_future_return_bps=value_bps,
        long_net_bps=long_net_bps,
        short_net_bps=short_net_bps,
        hold_net_bps=0.0,
        fee_bps=1.0,
        slippage_bps=1.0,
        funding_bps=max(0.0, total_cost_bps - 2.0),
        total_cost_bps=total_cost_bps,
        cost_evidence_source="features.fee_bps+features.expected_slippage_bps+features.expected_funding_bps",
        cost_evidence_hash=f"cost-evidence-{index:03d}",
        legacy_static_cost_bps_ignored=None,
        target_action=(
            "long"
            if long_net_bps > max(0.0, short_net_bps)
            else "short"
            if short_net_bps > max(0.0, long_net_bps)
            else "hold"
        ),
        features={"edge": edge, "noise": float(index % 7)},
    )


def test_dataset_freeze_prefers_newest_bounded_archive_window(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    observed: dict[str, object] = {}

    def newest_only_iterator(root, *, limit, newest_first):
        observed.update(
            {"root": root, "limit": limit, "newest_first": newest_first}
        )
        return iter(())

    monkeypatch.setattr(challenger, "iter_snapshots", newest_only_iterator)

    freeze = challenger.freeze_dataset_from_archive(
        archive_root=tmp_path,
        scan_limit=7,
    )

    assert freeze.rows == []
    assert observed == {
        "root": tmp_path,
        "limit": 7,
        "newest_first": True,
    }


def test_dataset_freeze_uses_bounded_label_range_when_cached_proof_is_stale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class _Archive:
        path = tmp_path / "labels.sqlite3"

        @staticmethod
        def integrity_proof_is_current(_proof: object) -> bool:
            return False

    snapshot = _trusted_snapshot(label_source=challenger.CANONICAL_5M_LABEL_SOURCE)
    seen_proofs: list[object] = []
    monkeypatch.setattr(
        challenger,
        "iter_snapshots",
        lambda _root, *, limit, newest_first: iter((snapshot,)),
    )
    monkeypatch.setattr(
        challenger,
        "snapshot_to_final_candle",
        lambda _snapshot: ({"symbol": "BTCUSDT", "timeframe": "1m"}, []),
    )
    monkeypatch.setattr(
        challenger,
        "_explicit_cost_evidence",
        lambda _snapshot: (
            {
                "fee_bps": 1.0,
                "slippage_bps": 1.0,
                "funding_bps": 0.0,
                "total_cost_bps": 2.0,
                "cost_evidence_source": "test",
                "cost_evidence_hash": "test-cost-hash",
            },
            [],
        ),
    )

    def bounded_label_read(*_args, **kwargs):
        seen_proofs.append(kwargs["archive_integrity_proof"])
        return (
            {
                "raw_future_return_bps": 5.0,
                "label_available_at": _iso(minutes=300),
                "max_future_horizon_seconds_consumed": 14_400,
                "future_horizon_available_at": {},
            },
            [],
        )

    monkeypatch.setattr(challenger, "_canonical_label_evidence", bounded_label_read)

    freeze = challenger.freeze_dataset_from_archive(
        archive_root=tmp_path,
        scan_limit=1,
        replay_limit=1,
        canonical_label_archive=_Archive(),
        canonical_label_integrity_proof={"archive_integrity_verified": True},
    )

    assert len(freeze.rows) == 1
    assert seen_proofs == [None]
    assert freeze.manifest["canonical_label_archive_integrity_verified"] is False


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
    assert "LATEST_UNCLOSED_KLINE_EXCLUSION_UNPROVEN" in _row_reject_reasons(
        _trusted_snapshot(latest_unclosed_kline_excluded=False)
    )
    assert "DECISION_TIME_MISSING_INVALID_OR_NAIVE" in _row_reject_reasons(
        _trusted_snapshot(decision_time="2026-06-22T00:01:00")
    )

    tampered = _trusted_snapshot()
    tampered_features = dict(tampered["features"])
    tampered_features["edge"] = 99.0
    tampered["features"] = tampered_features
    assert "CONTENT_SHA256_MISMATCH" in _row_reject_reasons(tampered)

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
    assert metrics["after_cost_expectancy_bps"] == pytest.approx(-2.0)
    assert metrics["expected_move_mae_bps"] == pytest.approx(10.0)
    assert metrics["expectancy_scope"] == (
        "explicit_action_specific_net_labels_directional_trades_only"
    )
    assert metrics["per_symbol"]["BTCUSDT"]["trade_count"] == 2
    assert metrics["per_timeframe"]["1m"]["trade_count"] == 4
    assert metrics["cost_source_distribution"]["total_cost_bps"]["mean"] == 2.0
    assert metrics["edge_claim_allowed"] is False


def test_train_challenger_model_selects_on_validation_and_holdout_beats_baseline() -> None:
    rows = [
        _row(
            i,
            18.0 if i % 4 in {0, 1} else -18.0,
            1.8 if i % 4 in {0, 1} else -1.8,
            decision_minutes=(i // 2) * 60,
        )
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

    assert model.target_transform == (
        "clipped_raw_future_return_bps_action_specific_net_evaluation"
    )
    assert model.target_clip_bps == pytest.approx(50.0)
    assert len(model.feature_names) <= 4
    assert model.validation_metrics["selection_validation_supply_floor"] == len(validation_rows)
    assert (
        model.validation_metrics["trade_count"]
        >= model.validation_metrics["selection_validation_supply_floor"]
    )
    assert model.validation_metrics["edge_claim_allowed"] is True
    assert model.feature_set_hash
    assert model.hyperparameter_grid_hash
    assert holdout_metrics["trade_count"] == len(holdout_rows)
    assert holdout_metrics["after_cost_expectancy_bps"] > 0.0
    assert holdout_metrics["directional_accuracy"] > CHAMPION_BASELINE["directional_accuracy"]
    assert holdout_metrics["expected_move_mae_bps"] < CHAMPION_BASELINE["expected_move_mae_bps"]
    assert holdout_metrics["false_positive_rate"] < CHAMPION_BASELINE["false_positive_rate"]
    assert holdout_metrics["after_cost_expectancy_clustered_lcb_bps"] > 0.0


def test_explicit_cost_evidence_fails_closed_and_ignores_underestimated_static_cost() -> None:
    features = dict(_trusted_snapshot()["features"])
    features["round_trip_cost_bps"] = 1.0
    evidence, reasons = _explicit_cost_evidence(_trusted_snapshot(features=features))

    assert reasons == []
    assert evidence is not None
    assert evidence["total_cost_bps"] == pytest.approx(7.0)
    assert evidence["legacy_static_cost_bps_ignored"] == pytest.approx(1.0)
    assert evidence["legacy_static_cost_was_under_explicit_total"] is True
    assert ACTION_SPECIFIC_COST_POLICY.startswith("explicit_pit_")
    assert len(str(evidence["cost_evidence_hash"])) == 64

    missing_features = dict(features)
    for name in ("fee_bps", "expected_slippage_bps", "expected_funding_bps"):
        missing_features.pop(name)
    missing, missing_reasons = _explicit_cost_evidence(_trusted_snapshot(features=missing_features))
    assert missing is None
    assert {
        "ACTION_SPECIFIC_FEE_EVIDENCE_MISSING_OR_INVALID",
        "ACTION_SPECIFIC_SLIPPAGE_EVIDENCE_MISSING_OR_INVALID",
        "ACTION_SPECIFIC_FUNDING_EVIDENCE_MISSING_OR_INVALID",
    }.issubset(missing_reasons)


def test_action_specific_labels_never_turn_directional_loss_into_sign_flipped_profit() -> None:
    loss_row = _row(0, 5.0, -1.0, total_cost_bps=10.0)

    short_metrics = evaluate_predictions(
        rows=[loss_row],
        predictions=[-20.0],
        threshold_bps=1.0,
    )
    hold_metrics = evaluate_predictions(
        rows=[loss_row],
        predictions=[0.0],
        threshold_bps=1.0,
    )

    assert loss_row.long_net_bps == pytest.approx(-5.0)
    assert loss_row.short_net_bps == pytest.approx(-15.0)
    assert short_metrics["after_cost_expectancy_bps"] == pytest.approx(-15.0)
    assert short_metrics["false_positive_count"] == 1
    assert short_metrics["edge_claim_allowed"] is False
    assert hold_metrics["trade_count"] == 0
    assert hold_metrics["after_cost_expectancy_bps"] is None


def test_evaluation_fails_closed_when_action_specific_cost_hash_is_absent() -> None:
    invalid = replace(_row(0, 10.0, 1.0), cost_evidence_hash="")

    metrics = evaluate_predictions(
        rows=[invalid],
        predictions=[5.0],
        threshold_bps=1.0,
    )

    assert metrics["after_cost_expectancy_bps"] is None
    assert metrics["edge_evidence_valid"] is False
    assert metrics["edge_claim_allowed"] is False
    assert metrics["row_contract_rejections_by_reason"] == {"ROW_COST_EVIDENCE_HASH_MISSING": 1}


def test_temporal_split_groups_repeated_decision_times_and_purges_all_label_overlap() -> None:
    rows = [
        _row(
            index,
            12.0 if index % 4 < 2 else -12.0,
            1.0 if index % 4 < 2 else -1.0,
            symbol="BTCUSDT" if index % 2 == 0 else "ETHUSDT",
            decision_minutes=(index // 2) * 60,
        )
        for index in range(120)
    ]
    rows[0] = replace(
        rows[0],
        label_available_at=(BASE_TIME + timedelta(hours=100))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    )

    train_rows, validation_rows, holdout_rows, manifest = _split_rows(rows)

    assert train_rows and validation_rows and holdout_rows
    assert manifest["split_pit_safe"] is True
    assert manifest["split_by_decision_time_group_not_row"] is True
    assert manifest["temporal_overlap"] is False
    assert manifest["label_overlap"] is False
    assert manifest["purge_embargo_seconds"] == MIN_TEMPORAL_EMBARGO_SECONDS
    assert manifest["training_rows_purged"] > 0
    assert rows[0] not in train_rows
    assert manifest["train_validation_decision_gap_seconds"] > MIN_TEMPORAL_EMBARGO_SECONDS
    assert manifest["validation_holdout_decision_gap_seconds"] > MIN_TEMPORAL_EMBARGO_SECONDS
    decision_groups = [
        {row.decision_time for row in partition}
        for partition in (train_rows, validation_rows, holdout_rows)
    ]
    assert not decision_groups[0] & decision_groups[1]
    assert not decision_groups[0] & decision_groups[2]
    assert not decision_groups[1] & decision_groups[2]


def test_temporal_split_rejects_naive_clock_instead_of_silently_normalizing() -> None:
    rows = [_row(index, 10.0, 1.0, decision_minutes=index * 60) for index in range(20)]
    rows[3] = replace(rows[3], decision_time="2026-06-22T03:00:01")

    train_rows, validation_rows, holdout_rows, manifest = _split_rows(rows)

    assert train_rows == []
    assert validation_rows == []
    assert holdout_rows == []
    assert manifest["split_pit_safe"] is False
    assert "SPLIT_DECISION_TIME_MISSING_INVALID_OR_NAIVE" in manifest["split_blocker_reasons"]


def test_clustered_lcb_uses_repeated_decision_time_and_symbol_clusters() -> None:
    rows: list[EdgeRecoveryRow] = []
    predictions: list[float] = []
    for group in range(12):
        raw = 18.0 if group % 2 == 0 else -18.0
        for symbol_index, symbol in enumerate(("BTCUSDT", "ETHUSDT")):
            index = group * 2 + symbol_index
            rows.append(
                _row(
                    index,
                    raw,
                    1.8 if raw > 0 else -1.8,
                    symbol=symbol,
                    decision_minutes=group * 60,
                )
            )
            predictions.append(5.0 if raw > 0 else -5.0)

    metrics = evaluate_predictions(
        rows=rows,
        predictions=predictions,
        threshold_bps=1.0,
    )

    assert metrics["decision_time_cluster_count"] == 12
    assert metrics["symbol_cluster_count"] == 2
    assert metrics["clustered_bootstrap_status"] == "PASS"
    assert metrics["after_cost_expectancy_clustered_lcb_bps"] == pytest.approx(16.0)
    assert metrics["edge_claim_allowed"] is True
    assert set(metrics["per_symbol"]) == {"BTCUSDT", "ETHUSDT"}


def test_positive_point_expectancy_does_not_claim_edge_when_clustered_lcb_is_nonpositive() -> None:
    rows: list[EdgeRecoveryRow] = []
    for group in range(20):
        raw = 12.0 if group < 15 else -18.0
        for symbol_index, symbol in enumerate(("BTCUSDT", "ETHUSDT")):
            rows.append(
                _row(
                    group * 2 + symbol_index,
                    raw,
                    1.0,
                    symbol=symbol,
                    decision_minutes=group * 60,
                )
            )

    metrics = evaluate_predictions(
        rows=rows,
        predictions=[5.0] * len(rows),
        threshold_bps=1.0,
    )

    assert metrics["after_cost_expectancy_bps"] > 0.0
    assert metrics["after_cost_expectancy_clustered_lcb_bps"] <= 0.0
    assert metrics["edge_evidence_valid"] is True
    assert metrics["edge_claim_allowed"] is False
    assert metrics["evaluation_blocker_reasons"] == ["CLUSTERED_EXPECTANCY_LCB_NOT_POSITIVE"]


def _forward_rows() -> list[EdgeRecoveryRow]:
    rows: list[EdgeRecoveryRow] = []
    for group in range(60):
        raw = 18.0 if group % 2 == 0 else -18.0
        for symbol_index, symbol in enumerate(("BTCUSDT", "ETHUSDT")):
            rows.append(
                _row(
                    group * 2 + symbol_index,
                    raw,
                    1.8 if raw > 0 else -1.8,
                    symbol=symbol,
                    decision_minutes=group * 60,
                )
            )
    return rows


def test_run_artifact_freezes_model_before_one_forward_holdout_and_stamps_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    rows = _forward_rows()
    freeze = DatasetFreeze(
        rows=rows,
        manifest={
            "trusted_replay_rows": len(rows),
            "snapshots_scanned": len(rows),
            "action_specific_cost_coverage_complete": True,
        },
        rejections_by_reason={},
    )
    monkeypatch.setattr(challenger, "freeze_dataset_from_archive", lambda **_kwargs: freeze)

    result = challenger.run_champion_challenger(
        repo_root=tmp_path,
        min_train_rows=10,
        min_validation_trades=4,
        min_holdout_trades=4,
        min_validation_supply_trades=4,
    )

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["policy_version"] == POLICY_VERSION
    assert result["status"] == "PASSED_PAPER_CHALLENGER_READY"
    assert result["dataset_freeze"]["split_pit_safe"] is True
    assert result["validity_contract"]["signed_net_label_inversion_allowed"] is False
    assert result["validity_contract"]["static_cost_fallback_allowed"] is False
    assert result["holdout_evaluation_contract"]["holdout_evaluation_count_this_run"] == 1
    assert result["holdout_evaluation_contract"]["model_unchanged_during_holdout"] is True
    assert result["edge_claim"]["allowed"] is True
    assert result["edge_claim"]["claimed_clustered_lcb_bps"] > 0.0
    assert result["paper_challenger_policy"]["enabled"] is True
    assert result["paper_challenger_policy"]["routes_to_live"] is False


def test_run_artifact_makes_no_edge_claim_when_cost_coverage_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    rows = _forward_rows()
    freeze = DatasetFreeze(
        rows=rows,
        manifest={
            "trusted_replay_rows": len(rows),
            "snapshots_scanned": len(rows) + 1,
            "action_specific_cost_coverage_complete": False,
            "missing_cost_snapshot_count": 1,
        },
        rejections_by_reason={"ACTION_SPECIFIC_FEE_EVIDENCE_MISSING_OR_INVALID": 1},
    )
    monkeypatch.setattr(challenger, "freeze_dataset_from_archive", lambda **_kwargs: freeze)

    result = challenger.run_champion_challenger(
        repo_root=tmp_path,
        min_train_rows=10,
        min_validation_trades=4,
        min_holdout_trades=4,
        min_validation_supply_trades=4,
    )

    assert result["status"] == "BLOCKED_INSUFFICIENT_TRUSTED_REPLAY_ROWS"
    assert "ACTION_SPECIFIC_COST_COVERAGE_INCOMPLETE" in result["blocker_reasons"]
    assert result["model"] is None
    assert result["untouched_holdout_metrics"] is None
    assert result["edge_claim"]["allowed"] is False
    assert result["edge_claim"]["claimed_after_cost_expectancy_bps"] is None
    assert result["paper_challenger_policy"]["enabled"] is False


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
    assert (
        build_paper_challenger_signal(
            model=model,
            snapshot=future_available,
            result_hash="result-hash",
        )
        is None
    )

    leaked_features = dict(_trusted_snapshot()["features"])
    leaked_features["future_return_15m_bps"] = 999.0
    assert (
        build_paper_challenger_signal(
            model=model,
            snapshot=_trusted_snapshot(features=leaked_features),
            result_hash="result-hash",
        )
        is None
    )


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
