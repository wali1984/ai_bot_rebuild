from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.continuous_edge_guardian.guardian import (
    BLOCKED_MARKER,
    ContinuousEdgeGuardianPaths,
    acquire_realtime_a_grade_evidence,
    build_guardian_payloads,
    compute_economic_metrics,
    run_once,
)


def _row(index: int, **overrides):
    symbol = f"S{index % 50:03d}USDT"
    side = "long" if index % 2 == 0 else "short"
    strategy = f"strategy_{index % 10}"
    regime = f"regime_{index % 5}"
    pnl = 10.0
    row = {
        "economic_trade_id": f"trade-{index}",
        "symbol": symbol,
        "timeframe": ("1m", "5m", "15m", "1h", "4h")[index % 5],
        "selected_action": side,
        "strategy": strategy,
        "market_regime": regime,
        "trade_outcome": "WIN",
        "realized_net_pnl_usd": pnl,
        "realized_net_pnl_bps": 20.0,
        "fees_usd": 0.2,
        "expected_slippage_usd": 0.1,
        "expected_funding_usd": 0.0,
        "actual_observed_spread_entry_bps": 1.2,
        "actual_observed_spread_source": "ORDERBOOK",
        "entry_orderbook_depth_usd": 100000.0,
        "decision_time": f"2026-06-22T12:{index % 60:02d}:30Z",
        "available_at": f"2026-06-22T12:{index % 60:02d}:00Z",
        "feature_cutoff": f"2026-06-22T12:{index % 60:02d}:00Z",
        "close_time": f"2026-06-22T13:{index % 60:02d}:00Z",
        "candidate_selected_before_outcome": True,
        "future_labels_used_as_features": False,
    }
    row.update(overrides)
    return row


def _passing_realtime_rows():
    rows = []
    for index in range(1000):
        if index < 50:
            rows.append(
                _row(
                    index,
                    trade_outcome="LOSS",
                    realized_net_pnl_usd=-1.0,
                    realized_net_pnl_bps=-2.0,
                )
            )
        else:
            rows.append(_row(index))
    return rows


def _verified_candidate(index: int = 1, **overrides):
    row = _row(
        index,
        economic_trade_id=f"econ-{index}",
        prediction_id=f"pred-{index}",
        signal_id=f"pred-{index}",
        decision_id=f"decision-{index}",
        feature_snapshot_id=f"fsnap-{index}",
        entry_feature_snapshot_id=f"fsnap-{index}",
        mtf_snapshot_id=f"mtf-{index}",
        model_version="V2_TEST_MODEL",
        checkpoint_id="ckpt-test",
        source_hashes={"feature_vector_hash": f"hash-{index}", "source_timestamp_hash": f"ts-{index}"},
        selected_action="long",
        action="long",
        side="long",
        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
        explicit_paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
        candidate_selected_before_outcome=True,
        frozen_selector_fingerprint="frozen-policy-1",
        selector_policy_fingerprint="frozen-policy-1",
        allocator_decision="ALLOW_WITH_SIZE",
        paper_only=True,
        places_real_order=False,
        generated_at="2026-06-22T12:00:10Z",
        decision_time="2026-06-22T12:00:30Z",
        available_at="2026-06-22T12:00:00Z",
        feature_cutoff="2026-06-22T11:59:59Z",
        expected_fees_usd=0.2,
        expected_slippage_usd=0.1,
        expected_funding_usd=0.0,
        maker_probability=0.4,
        taker_probability=0.6,
        latency_ms=25.0,
        partial_fill_count=1,
        mark_index_divergence_bps=0.2,
        entry_orderbook_depth_usd=100000.0,
    )
    row.update(overrides)
    return row


def _rare_event_stress_suite(*, scenario_bps: float = 100.0) -> dict:
    suite = {
        "gap_shock": {"adverse_move_bps": scenario_bps},
        "spread_explosion": {"adverse_move_bps": scenario_bps},
        "depth_collapse": {"adverse_move_bps": scenario_bps},
        "funding_spike": {"adverse_move_bps": scenario_bps},
        "correlated_portfolio_shock": {"adverse_move_bps": scenario_bps},
        "long_squeeze": {"adverse_move_bps": scenario_bps},
        "short_squeeze": {"adverse_move_bps": scenario_bps},
        "double_sided_liquidation_cascade": {"adverse_move_bps": scenario_bps},
        "mark_index_divergence": {"adverse_move_bps": scenario_bps},
        "exchange_api_delay": {"adverse_move_bps": scenario_bps},
        "execution_uncertainty_bps": 10.0,
        "correlation_stress_bps": 20.0,
        "maintenance_margin_uncertainty_bps": 30.0,
        "status": "COMPLETE_RARE_EVENT_STRESS_SUITE",
        "missing_inputs": [],
    }
    return suite


def _verified_outcome(index: int = 1, **overrides):
    row = _row(
        index,
        economic_trade_id=f"econ-{index}",
        prediction_id=f"pred-{index}",
        entry_prediction_id=f"pred-{index}",
        signal_id=f"pred-{index}",
        entry_signal_id=f"pred-{index}",
        decision_id=f"decision-{index}",
        feature_snapshot_id=f"fsnap-{index}",
        entry_feature_snapshot_id=f"fsnap-{index}",
        mtf_snapshot_id=f"mtf-{index}",
        model_version="V2_TEST_MODEL",
        checkpoint_id="ckpt-test",
        source_hashes={"feature_vector_hash": f"hash-{index}", "source_timestamp_hash": f"ts-{index}"},
        selected_action="long",
        action="long",
        side="long",
        paper_only=True,
        places_real_order=False,
        trainer_consumable=True,
        trust_reconstructed=True,
        decision_time="2026-06-22T12:00:30Z",
        available_at="2026-06-22T12:00:00Z",
        feature_cutoff="2026-06-22T11:59:59Z",
        close_time="2026-06-22T12:30:00Z",
        exit_time="2026-06-22T12:30:00Z",
        directional_outcome="UP",
        trade_outcome="WIN",
        action_was_profitable=True,
        holding_period=1800,
        fees=0.2,
        funding=0.0,
        expected_slippage_usd=0.1,
        MFE=12.0,
        MAE=-2.0,
        exit_reason="TAKE_PROFIT",
        maker_probability=0.4,
        taker_probability=0.6,
        latency_ms=25.0,
        partial_fill_count=1,
        mark_index_divergence_bps=0.2,
        entry_orderbook_depth_usd=100000.0,
    )
    row.update(overrides)
    return row


def _write_acquisition_sources(
    paths: ContinuousEdgeGuardianPaths,
    *,
    candidates: list[dict],
    outcomes: list[dict],
) -> None:
    paths.paper_trade_management_dir.mkdir(parents=True, exist_ok=True)
    paths.paper_trade_live_dir.mkdir(parents=True, exist_ok=True)
    (paths.paper_adaptive_sizing_path).write_text(
        json.dumps({
            "paper_only": True,
            "places_real_order": False,
            "candidate_allocations": candidates,
            "sample_allocations": [],
        }),
        encoding="utf-8",
    )
    paths.paper_live_status_path.write_text(
        json.dumps({
            "paper_only": True,
            "places_real_order": False,
            "paper_adaptive_sizing_runtime_status": {
                "candidate_allocations": [],
                "sample_allocations": [],
            },
            "shadow_observations": [],
        }),
        encoding="utf-8",
    )
    paths.trainer_feedback_outcomes_path.write_text(
        json.dumps({
            "paper_only": True,
            "places_real_order": False,
            "trainer_feedback_outcomes": outcomes,
        }),
        encoding="utf-8",
    )


def test_readiness_truth_learning_does_not_imply_a_grade_ready(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    trainer_dir = paths.trainer_dir
    trainer_dir.mkdir(parents=True)
    (trainer_dir / "online_learning_global_readiness_override.json").write_text(
        json.dumps({"trainer_learning_ready": True, "optimizer_steps_total": 12}),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    readiness = payloads["readiness_truth_override.json"]
    assert readiness["WEIGHTS_UPDATING"] is True
    assert readiness["EDGE_PROVEN"] is False
    assert readiness["A_GRADE_EXECUTION_READY"] is False
    assert readiness["LIVE_READY"] is False


def test_dashboard_publishes_b_grade_quality_without_readiness_implication(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_b_grade_model_quality_path.write_text(
        json.dumps(
            {
                "schema_version": "paper_b_grade_model_quality_status_v1",
                "generated_utc": "2026-06-22T16:00:00Z",
                "status": "ACTIVE_B_GRADE_REALIZED_QUALITY_METRICS",
                "scope": "B_GRADE_EXPLORATION_PAPER_CLOSED_OUTCOMES_ONLY",
                "paper_only": True,
                "places_real_order": False,
                "counts_as_a_grade_evidence": False,
                "a_grade_promotion_allowed": False,
                "live_ready_implication": False,
                "directional_accuracy": 0.34,
                "expected_move_mae": 123.5,
                "brier_score": 0.31,
                "ece": 0.24,
                "precision": 0.39,
                "recall": None,
                "recall_unavailable_reason": "closed executed paper outcomes do not include unexecuted profitable opportunities",
                "false_positive_rate": 0.61,
                "false_negative_rate": None,
                "false_negative_rate_unavailable_reason": "closed executed paper outcomes do not include abstained positive opportunities",
                "after_cost_expectancy_bps": -5.2,
                "expectancy_95pct_lower_confidence_bound_bps": -20.0,
                "profit_factor": 0.8,
                "win_rate_after_cost": 0.34,
                "b_grade_closed_outcome_count": 510,
                "source_feedback_row_count": 513,
                "trade_outcome_counts": {"WIN": 173, "LOSS": 337, "BREAKEVEN": 0},
                "metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "strategy": "trend_mode",
                        "regime": "TREND",
                        "confidence_bucket": "0.6-0.7",
                        "directional_accuracy": 0.33,
                        "after_cost_expectancy_bps": -8.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    paths.paper_b_grade_bucket_promotion_readiness_path.write_text(
        json.dumps(
            {
                "schema_version": "paper_b_grade_bucket_promotion_readiness_status_v1",
                "generated_utc": "2026-06-22T16:00:00Z",
                "status": "BLOCKED_NO_A_GRADE_PROMOTABLE_BUCKETS",
                "scope": "B_GRADE_EXPLORATION_PAPER_BUCKETS",
                "source_b_grade_closed_outcome_count": 510,
                "source_bucket_count": 1,
                "metric_ready_bucket_count": 1,
                "a_grade_promotable_bucket_count": 0,
                "blocker_counts": {"WIN_RATE_LCB_BELOW_90P": 1},
                "buckets": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "strategy": "trend_mode",
                        "regime": "TREND",
                        "confidence_bucket": "0.6-0.7",
                        "eligibility": "SHADOW_ONLY",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    paths.paper_shadow_outcome_metrics_path.parent.mkdir(parents=True, exist_ok=True)
    paths.paper_shadow_outcome_metrics_path.write_text(
        json.dumps(
            {
                "schema_version": "v2_shadow_observation_outcome_metrics_status_v1",
                "generated_utc": "2026-06-22T16:00:00Z",
                "outcome_count": 20,
                "classified_shadow_outcome_count": 20,
                "shadow_no_trade_correct_count": 13,
                "shadow_false_block_candidate_count": 7,
                "counted_as_fill": False,
                "affects_pnl_ledger": False,
                "opens_paper_fill_gate": False,
                "writes_legacy_redis": False,
                "writes_exchange_orders": False,
                "shadow_outcome_summary": {
                    "classified_outcome_count": 20,
                    "no_trade_correct_count": 13,
                    "false_block_candidate_count": 7,
                    "outcome_count": 20,
                    "counts_as_a_grade_evidence": False,
                    "a_grade_promotion_allowed": False,
                    "live_ready_implication": False,
                    "counted_as_fill": False,
                    "affects_pnl_ledger": False,
                },
            }
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    dashboard_quality = payloads["operator_dashboard_payload.json"]["model_quality"]
    assert dashboard_quality["scope"] == "B_GRADE_EXPLORATION_PAPER_CLOSED_OUTCOMES_ONLY"
    assert dashboard_quality["directional_accuracy"] == 0.34
    assert dashboard_quality["expected_move_mae"] == 123.5
    assert dashboard_quality["precision"] == 0.39
    assert dashboard_quality["recall"] == 173 / 180
    assert dashboard_quality["recall_source"] == "shadow_outcome_false_block_candidates"
    assert dashboard_quality["false_positive_rate"] == 0.61
    assert dashboard_quality["false_negative_rate"] == 7 / 180
    assert dashboard_quality["false_negative_rate_source"] == "shadow_outcome_false_block_candidates"
    assert dashboard_quality["shadow_opportunity_metric_scope"] == "PAPER_ONLY_NON_FILL_NO_PNL_SHADOW_OUTCOMES"
    assert dashboard_quality["shadow_opportunity_metrics_counted_as_a_grade_evidence"] is False
    assert dashboard_quality["shadow_opportunity_metrics_a_grade_promotion_allowed"] is False
    assert dashboard_quality["shadow_opportunity_metrics_live_ready_implication"] is False
    assert dashboard_quality["shadow_false_block_candidate_count"] == 7
    assert dashboard_quality["shadow_classified_outcome_count"] == 20
    assert dashboard_quality["after_cost_expectancy_bps"] == -5.2
    assert dashboard_quality["b_grade_closed_outcome_count"] == 510
    assert dashboard_quality["counts_as_a_grade_evidence"] is False
    assert dashboard_quality["a_grade_promotion_allowed"] is False
    assert dashboard_quality["live_ready_implication"] is False
    assert dashboard_quality["bucket_metric_count"] == 1
    assert dashboard_quality["metrics_by_symbol_timeframe_side_strategy_regime_confidence_bucket"][0][
        "confidence_bucket"
    ] == "0.6-0.7"
    assert dashboard_quality["bucket_promotion_readiness"]["status"] == "BLOCKED_NO_A_GRADE_PROMOTABLE_BUCKETS"
    assert dashboard_quality["bucket_promotion_readiness"]["a_grade_promotable_bucket_count"] == 0
    assert payloads["readiness_truth_override.json"]["A_GRADE_EXECUTION_READY"] is False
    assert payloads["operator_dashboard_payload.json"]["generic_ready_display_allowed"] is False


def test_guardian_uses_nested_b_grade_quality_when_sidecar_missing(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.trainer_feedback_outcomes_path.write_text(
        json.dumps(
            {
                "paper_only": True,
                "places_real_order": False,
                "trainer_feedback_outcomes": [],
                "paper_b_grade_model_quality_status": {
                    "status": "ACTIVE_B_GRADE_REALIZED_QUALITY_METRICS",
                    "scope": "B_GRADE_EXPLORATION_PAPER_CLOSED_OUTCOMES_ONLY",
                    "directional_accuracy": 0.36,
                    "expected_move_mae": 99.0,
                    "brier_score": 0.29,
                    "ece": 0.21,
                    "precision": 0.37,
                    "false_positive_rate": 0.63,
                    "after_cost_expectancy_bps": -2.5,
                    "counts_as_a_grade_evidence": False,
                    "a_grade_promotion_allowed": False,
                    "live_ready_implication": False,
                },
                "paper_b_grade_bucket_promotion_readiness_status": {
                    "status": "BLOCKED_NO_A_GRADE_PROMOTABLE_BUCKETS",
                    "a_grade_promotable_bucket_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    dashboard_quality = payloads["operator_dashboard_payload.json"]["model_quality"]
    assert dashboard_quality["directional_accuracy"] == 0.36
    assert dashboard_quality["expected_move_mae"] == 99.0
    assert dashboard_quality["after_cost_expectancy_bps"] == -2.5
    assert dashboard_quality["counts_as_a_grade_evidence"] is False
    assert dashboard_quality["bucket_promotion_readiness"]["status"] == "BLOCKED_NO_A_GRADE_PROMOTABLE_BUCKETS"


def test_strategy_brain_publishes_bucket_states_without_a_grade_readiness(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_b_grade_bucket_promotion_readiness_path.write_text(
        json.dumps(
            {
                "schema_version": "paper_b_grade_bucket_promotion_readiness_status_v1",
                "status": "BLOCKED_B_GRADE_BUCKETS_NOT_A_GRADE_READY",
                "source_bucket_count": 2,
                "a_grade_promotable_bucket_count": 0,
                "thresholds": {"minimum_bucket_sample_count": 30},
                "blocker_counts": {
                    "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE": 2,
                    "INSUFFICIENT_BUCKET_SAMPLE_COUNT": 1,
                },
                "evidence_fragmentation_status": {
                    "schema_version": "paper_b_grade_evidence_fragmentation_status_v1",
                    "status": "BLOCKED_FRAGMENTED_B_GRADE_EVIDENCE",
                    "bucket_count": 2,
                    "minimum_bucket_sample_count": 30,
                    "insufficient_sample_bucket_count": 1,
                    "buckets_at_or_above_minimum_count": 1,
                    "sample_count_deficit_to_minimum_total": 27,
                    "paper_only_label_collection_priority_bucket_count": 1,
                    "counts_as_a_grade_evidence": False,
                    "a_grade_promotion_allowed": False,
                    "live_ready_implication": False,
                },
                "paper_only_label_collection_priority_buckets": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "strategy": "trend_mode",
                        "regime": "TREND",
                        "confidence_bucket": "0.6-0.7",
                        "closed_economic_outcome_count": 3,
                        "sample_count_deficit_to_minimum": 27,
                        "priority_reason": (
                            "PAPER_ONLY_COLLECT_MORE_B_GRADE_LABELS_FOR_PROMISING_UNDERPOWERED_BUCKET"
                        ),
                        "counts_as_a_grade_evidence": False,
                        "a_grade_promotion_allowed": False,
                        "live_ready_implication": False,
                    }
                ],
                "buckets": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "strategy": "trend_mode",
                        "regime": "TREND",
                        "confidence_bucket": "0.6-0.7",
                        "closed_economic_outcome_count": 3,
                        "point_win_rate_after_cost": 0.67,
                        "win_rate_95pct_lower_confidence_bound": 0.2,
                        "after_cost_expectancy_bps": 8.0,
                        "expectancy_95pct_lower_confidence_bound_bps": 1.0,
                        "profit_factor": 3.0,
                        "profit_factor_numeric": 3.0,
                        "profit_factor_is_infinite": False,
                        "metric_blocker_reasons": [
                            "INSUFFICIENT_BUCKET_SAMPLE_COUNT",
                            "WIN_RATE_95PCT_LCB_BELOW_90P",
                        ],
                        "promotion_blocker_reasons": [
                            "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE"
                        ],
                        "a_grade_promotion_allowed": False,
                    },
                    {
                        "symbol": "ETHUSDT",
                        "timeframe": "5m",
                        "side": "short",
                        "strategy": "mean_reversion_mode",
                        "regime": "RANGE",
                        "confidence_bucket": "0.6-0.7",
                        "closed_economic_outcome_count": 35,
                        "point_win_rate_after_cost": 0.34,
                        "win_rate_95pct_lower_confidence_bound": 0.18,
                        "after_cost_expectancy_bps": -8.0,
                        "expectancy_95pct_lower_confidence_bound_bps": -20.0,
                        "profit_factor": 0.4,
                        "profit_factor_numeric": 0.4,
                        "profit_factor_is_infinite": False,
                        "metric_blocker_reasons": ["NON_POSITIVE_AFTER_COST_EXPECTANCY"],
                        "promotion_blocker_reasons": [
                            "NON_POSITIVE_AFTER_COST_EXPECTANCY",
                            "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE",
                        ],
                        "a_grade_promotion_allowed": False,
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    paths.trainer_feedback_outcomes_path.write_text(
        json.dumps(
            {
                "paper_only": True,
                "places_real_order": False,
                "trainer_feedback_outcomes": [
                    _verified_outcome(
                        1,
                        symbol="BTCUSDT",
                        timeframe="1h",
                        selected_action="long",
                        action="long",
                        strategy="trend_mode",
                        strategy_id="trend_mode",
                        strategy_family="trend_mode",
                        market_regime="TREND",
                        confidence_calibrated=0.65,
                        realized_net_pnl_bps=20.0,
                    ),
                    _verified_outcome(
                        2,
                        symbol="BTCUSDT",
                        timeframe="1h",
                        selected_action="long",
                        action="long",
                        strategy="trend_mode",
                        strategy_id="trend_mode",
                        strategy_family="trend_mode",
                        market_regime="TREND",
                        confidence_calibrated=0.65,
                        realized_net_pnl_bps=10.0,
                    ),
                    _verified_outcome(
                        3,
                        symbol="BTCUSDT",
                        timeframe="1h",
                        selected_action="long",
                        action="long",
                        strategy="trend_mode",
                        strategy_id="trend_mode",
                        strategy_family="trend_mode",
                        market_regime="TREND",
                        confidence_calibrated=0.65,
                        realized_net_pnl_bps=-5.0,
                    ),
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    strategy_brain = payloads["strategy_brain_status.json"]
    assert strategy_brain["status"] == "BLOCKED_NO_A_GRADE_STRATEGY_ELIGIBILITY"
    assert strategy_brain["new_a_grade_entries_allowed"] is False
    assert strategy_brain["a_grade_active_bucket_count"] == 0
    assert strategy_brain["thresholds"] == {"minimum_bucket_sample_count": 30}
    assert strategy_brain["minimum_bucket_sample_count"] == 30
    assert strategy_brain["blocker_counts"] == {
        "B_GRADE_OUTCOMES_ARE_LEARNING_ONLY_NOT_A_GRADE_EVIDENCE": 2,
        "INSUFFICIENT_BUCKET_SAMPLE_COUNT": 1,
    }
    assert strategy_brain["promotion_blocker_counts"] == strategy_brain["blocker_counts"]
    assert strategy_brain["bucket_promotion_readiness"]["a_grade_promotion_allowed"] is False
    assert strategy_brain["bucket_promotion_readiness"]["counts_as_a_grade_evidence"] is False
    assert strategy_brain["b_grade_evidence_fragmentation_status"]["status"] == (
        "BLOCKED_FRAGMENTED_B_GRADE_EVIDENCE"
    )
    assert strategy_brain["b_grade_evidence_fragmentation_status"][
        "counts_as_a_grade_evidence"
    ] is False
    assert strategy_brain["paper_only_label_collection_priority_bucket_count"] == 1
    assert strategy_brain["paper_only_label_collection_priority_buckets"][0]["symbol"] == "BTCUSDT"
    assert strategy_brain["paper_only_label_collection_priority_buckets"][0][
        "a_grade_promotion_allowed"
    ] is False
    assert strategy_brain["state_counts"]["REEVALUATION"] == 1
    assert strategy_brain["state_counts"]["SHADOW_ONLY"] == 1
    btc_bucket = next(bucket for bucket in strategy_brain["buckets"] if bucket["symbol"] == "BTCUSDT")
    eth_bucket = next(bucket for bucket in strategy_brain["buckets"] if bucket["symbol"] == "ETHUSDT")
    assert btc_bucket["state"] == "REEVALUATION"
    assert btc_bucket["eligibility"] == "B_GRADE_EXPLORATION_PAPER"
    assert btc_bucket["paper_exploration_eligible"] is True
    assert btc_bucket["a_grade_execution_eligible"] is False
    assert btc_bucket["weight"] == 0.0
    assert btc_bucket["drawdown_bps"] == -5.0
    assert btc_bucket["tail_loss_bps"] == -5.0
    assert eth_bucket["state"] == "SHADOW_ONLY"
    assert eth_bucket["paper_exploration_eligible"] is False
    assert "LOSING_BUCKET_LOSES_EXECUTION_ELIGIBILITY" in eth_bucket["blocker_reasons"]
    assert payloads["operator_dashboard_payload.json"]["adaptive_strategy_brain_state"] == (
        "BLOCKED_NO_A_GRADE_STRATEGY_ELIGIBILITY"
    )
    assert any(
        blocker["reason"] == "ADAPTIVE_STRATEGY_BRAIN_BLOCKED"
        for blocker in payloads["CURRENT_BLOCKERS.json"]["blockers"]
    )


def test_strategy_brain_quarantines_lifecycle_reduce_strategy(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_b_grade_bucket_promotion_readiness_path.write_text(
        json.dumps(
            {
                "schema_version": "paper_b_grade_bucket_promotion_readiness_status_v1",
                "status": "BLOCKED_B_GRADE_BUCKETS_NOT_A_GRADE_READY",
                "thresholds": {"minimum_bucket_sample_count": 30},
                "buckets": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "strategy": "reduce_exposure",
                        "regime": "TREND",
                        "confidence_bucket": "0.8-0.9",
                        "closed_economic_outcome_count": 100,
                        "point_win_rate_after_cost": 0.95,
                        "win_rate_95pct_lower_confidence_bound": 0.91,
                        "after_cost_expectancy_bps": 20.0,
                        "expectancy_95pct_lower_confidence_bound_bps": 5.0,
                        "profit_factor": 3.0,
                        "profit_factor_numeric": 3.0,
                        "profit_factor_is_infinite": False,
                        "bucket_metric_conditions_pass": True,
                        "a_grade_promotion_allowed": True,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    strategy_brain = payloads["strategy_brain_status.json"]
    bucket = strategy_brain["buckets"][0]
    assert bucket["strategy"] == "reduce_exposure"
    assert bucket["state"] == "QUARANTINED"
    assert bucket["eligibility"] == "SHADOW_ONLY"
    assert bucket["a_grade_execution_eligible"] is False
    assert bucket["paper_exploration_eligible"] is False
    assert "LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_STRATEGY" in bucket["blocker_reasons"]
    assert strategy_brain["lifecycle_actions_cannot_be_entry_strategies"] is True


def test_dashboard_publishes_capital_and_leverage_diagnostics_without_unblocking(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "generated_utc": "2026-06-22T16:00:00Z",
                "paper_only": True,
                "places_real_order": False,
                "fixed_runtime_notional_removed": True,
                "leverage_mutation": False,
                "margin_mode_mutation": False,
                "old_redis_writes": False,
                "candidate_allocation_count": 2,
                "accepted_allocation_count": 0,
                "blocked_allocation_count": 2,
                "allocator_decision_counts": {"BLOCK_NON_EXECUTABLE_PAPER_TIER": 2},
                "candidate_allocations": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "paper_opportunity_tier": "NO_TRADE",
                        "allocator_decision": "BLOCK_NON_EXECUTABLE_PAPER_TIER",
                        "original_allocator_decision_before_paper_tier_block": "BLOCK_NO_EDGE",
                        "allocator_reason": "NON_EXECUTABLE_PAPER_TIER:NO_TRADE",
                        "allocated_margin_usd": 0.0,
                        "gross_notional_usd": 0.0,
                        "risk_budget_usd": 0.0,
                        "recommended_leverage": 1.0,
                        "recommended_margin_mode": "isolated_paper_simulated",
                        "paper_only": True,
                        "places_real_order": False,
                        "leverage_mutation": False,
                        "margin_mode_mutation": False,
                        "model_inputs": {
                            "equity": 1000.0,
                            "available_margin": 800.0,
                            "total_exposure_usdt": 100.0,
                        },
                    },
                    {
                        "symbol": "ETHUSDT",
                        "timeframe": "5m",
                        "side": "short",
                        "paper_opportunity_tier": "NO_TRADE",
                        "allocator_decision": "BLOCK_NON_EXECUTABLE_PAPER_TIER",
                        "original_allocator_decision_before_paper_tier_block": "ALLOW_WITH_SIZE",
                        "allocator_reason": "NON_EXECUTABLE_PAPER_TIER:NO_TRADE",
                        "allocated_margin_usd": 0.0,
                        "gross_notional_usd": 0.0,
                        "risk_budget_usd": 0.0,
                        "recommended_leverage": 2.0,
                        "recommended_margin_mode": "isolated_paper_simulated",
                        "stop_distance_bps": 75.0,
                        "take_profit_structure": "decision_time_expected_move_or_price_target",
                        "liquidation_buffer_bps": 1200.0,
                        "hedge_budget_usd": 0.0,
                        "expected_net_pnl_usd": 0.0,
                        "expected_shortfall_usd": 0.0,
                        "paper_only": True,
                        "places_real_order": False,
                        "leverage_mutation": False,
                        "margin_mode_mutation": False,
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    dashboard = payloads["operator_dashboard_payload.json"]
    capital = dashboard["capital_utilization_diagnostics"]
    recommendation = dashboard["leverage_and_margin_recommendation"]
    assert dashboard["capital_utilization"] == 0.0
    assert capital["status"] == "BLOCKED_UNTIL_A_GRADE_EDGE_PROVEN"
    assert capital["capital_utilization_classification"] == "POSITIVE_EDGE_BELOW_A_GRADE_IDLE"
    assert capital["candidate_allocation_count"] == 2
    assert capital["accepted_a_grade_candidate_count"] == 0
    assert capital["available_idle_capital_usd"] == 800.0
    assert capital["idle_capital_no_edge_usd"] == 400.0
    assert capital["idle_capital_below_grade_usd"] == 400.0
    assert capital["idle_capital_allocator_bug_usd"] == 0.0
    assert capital["portfolio_exposure_utilization_pct"] == 0.1
    assert recommendation["status"] == "BLOCKED_UNTIL_A_GRADE_EDGE_PROVEN"
    assert recommendation["live_exchange_mutation_allowed"] is False
    assert recommendation["recommended_leverage_counts"] == {"1.0": 1, "2.0": 1}
    assert recommendation["sample_recommendations"][1]["recommended_leverage"] == 2.0
    assert recommendation["sample_recommendations"][1]["take_profit_plan"] == "decision_time_expected_move_or_price_target"
    assert payloads["readiness_truth_override.json"]["A_GRADE_EXECUTION_READY"] is False


def test_a_grade_underfunded_candidate_is_allocator_bug_diagnostic(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "generated_utc": "2026-06-22T16:00:00Z",
                "paper_only": True,
                "places_real_order": False,
                "candidate_allocation_count": 1,
                "accepted_allocation_count": 0,
                "blocked_allocation_count": 1,
                "candidate_allocations": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "paper_opportunity_tier": "A_GRADE_EXECUTION_PAPER",
                        "allocator_decision": "BLOCK_MISSING_ACCOUNTING",
                        "original_allocator_decision_before_paper_tier_block": "ALLOW_WITH_SIZE",
                        "allocated_margin_usd": 0.0,
                        "gross_notional_usd": 0.0,
                        "recommended_leverage": 1.0,
                        "recommended_margin_mode": "isolated_paper_simulated",
                        "model_inputs": {"equity": 1000.0, "available_margin": 750.0},
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    capital = payloads["operator_dashboard_payload.json"]["capital_utilization_diagnostics"]
    assert capital["capital_utilization_classification"] == "ALLOCATOR_UNDERDEPLOYMENT"
    assert capital["a_grade_candidate_count"] == 1
    assert capital["underfunded_a_grade_candidate_count"] == 1
    assert capital["idle_capital_allocator_bug_usd"] == 750.0


def test_hedge_engine_rejects_unbounded_or_not_cost_effective_plan(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "generated_utc": "2026-06-22T16:00:00Z",
                "paper_only": True,
                "places_real_order": False,
                "candidate_allocations": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                        "hedge_enabled": True,
                        "hedge_parent_id": "parent-1",
                        "hedge_intent": "tail_risk_reduction",
                        "hedge_ratio": 0.35,
                        "hedge_budget_usd": 10.0,
                        "expected_shortfall_before": 100.0,
                        "expected_shortfall_after": 98.0,
                        "hedge_cost_usd": 3.0,
                        "paper_only": True,
                        "places_real_order": False,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    hedge = payloads["hedge_engine_status.json"]
    assert hedge["status"] == "BLOCKED_HEDGE_CONTRACT_INCOMPLETE"
    assert hedge["new_hedges_allowed"] is False
    assert hedge["active_hedge_candidate_count"] == 1
    assert hedge["accepted_bounded_hedge_candidate_count"] == 0
    assert hedge["blocker_counts"]["MISSING_HEDGE_CHILD_ID"] == 1
    assert hedge["blocker_counts"]["MISSING_MAXIMUM_DURATION"] == 1
    assert hedge["blocker_counts"]["MISSING_UNWIND_PLAN"] == 1
    assert hedge["blocker_counts"]["HEDGE_EXIT_PLAN_NOT_BOUNDED"] == 1
    assert hedge["blocker_counts"]["EXPECTED_SHORTFALL_REDUCTION_NOT_GREATER_THAN_COSTS"] == 1
    assert payloads["operator_dashboard_payload.json"]["hedge_engine_state"] == "BLOCKED_HEDGE_CONTRACT_INCOMPLETE"
    assert payloads["readiness_truth_override.json"]["A_GRADE_EXECUTION_READY"] is False


def test_hedge_engine_does_not_treat_zero_shortfall_fields_as_active_hedge(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "paper_only": True,
                "places_real_order": False,
                "candidate_allocations": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "paper_opportunity_tier": "NO_TRADE",
                        "hedge_enabled": False,
                        "hedge_budget_usd": 0.0,
                        "expected_shortfall_before": 0.0,
                        "expected_shortfall_after": 0.0,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    hedge = payloads["hedge_engine_status.json"]
    assert hedge["status"] == "NO_ACTIVE_HEDGES_SELECTED"
    assert hedge["active_hedge_candidate_count"] == 0
    assert hedge["blocker_counts"] == {}


def test_hedge_engine_accepts_bounded_cost_effective_plan_and_groups_outcome(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "generated_utc": "2026-06-22T16:00:00Z",
                "paper_only": True,
                "places_real_order": False,
                "candidate_allocations": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1h",
                        "side": "long",
                        "paper_opportunity_tier": "B_GRADE_EXPLORATION_PAPER",
                        "hedge_enabled": True,
                        "hedge_parent_id": "parent-1",
                        "hedge_child_id": "hedge-1",
                        "hedge_intent": "tail_risk_reduction",
                        "hedge_ratio": 0.35,
                        "hedge_budget_usd": 10.0,
                        "expected_shortfall_before": 100.0,
                        "expected_shortfall_after": 80.0,
                        "hedge_cost_usd": 5.0,
                        "maximum_duration": 900,
                        "unwind_plan": "close_with_parent_or_after_timeout",
                        "paper_only": True,
                        "places_real_order": False,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    paths.trainer_feedback_outcomes_path.write_text(
        json.dumps(
            {
                "paper_only": True,
                "places_real_order": False,
                "trainer_feedback_outcomes": [
                    {
                        "economic_trade_id": "parent-1",
                        "hedge_parent_id": "parent-1",
                        "hedge_child_id": "hedge-1",
                        "hedge_intent": "tail_risk_reduction",
                        "pair_net_pnl": 12.0,
                        "realized_net_pnl_usd": 8.0,
                        "trade_outcome": "WIN",
                    },
                    {
                        "economic_trade_id": "parent-1",
                        "hedge_parent_id": "parent-1",
                        "hedge_child_id": "hedge-1",
                        "hedge_intent": "tail_risk_reduction",
                        "pair_net_pnl": 12.0,
                        "realized_net_pnl_usd": 4.0,
                        "trade_outcome": "WIN",
                    },
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    hedge = payloads["hedge_engine_status.json"]
    assert hedge["status"] == "PASSED_BOUNDED_HEDGE_ADMISSION_CONTRACT"
    assert hedge["new_hedges_allowed"] is True
    assert hedge["release_ready"] is True
    assert hedge["accepted_bounded_hedge_candidate_count"] == 1
    assert hedge["blocker_counts"] == {}
    assert hedge["hedged_feedback_row_count"] == 2
    assert hedge["hedged_economic_outcome_group_count"] == 1
    assert hedge["hedged_outcome_rows_missing_pair_net_pnl"] == 0
    assert hedge["hedged_structures_counted_as_single_outcome"] is True


def test_zero_liquidation_blocks_a_grade_candidate_missing_rare_event_stress_suite(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "paper_only": True,
                "places_real_order": False,
                "candidate_allocations": [
                    _verified_candidate(
                        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
                        explicit_paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
                        allocator_decision="ALLOW_WITH_SIZE",
                        gross_notional_usd=100.0,
                        allocated_margin_usd=100.0,
                        liquidation_buffer_bps=500.0,
                    )
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    zero = payloads["zero_liquidation_status.json"]
    assert zero["status"] == "BLOCKED_RARE_EVENT_STRESS_SUITE_INCOMPLETE"
    assert zero["new_a_grade_entries_allowed"] is False
    assert zero["a_grade_candidate_count"] == 1
    assert zero["passed_a_grade_candidate_count"] == 0
    assert zero["blocker_counts"]["MISSING_STRESS_SCENARIO_GAP_SHOCK"] == 1
    assert zero["blocker_counts"]["MISSING_BUFFER_COMPONENT_EXECUTION_UNCERTAINTY_BPS"] == 1
    assert zero["candidate_samples"][0]["rare_event_stress_passed"] is False
    assert payloads["readiness_truth_override.json"]["ZERO_LIQUIDATION_READY"] is False
    assert payloads["VALIDATION_LEDGER.json"]["required_validation"]["rare_event_stress_suite"] == (
        "BLOCKED_RARE_EVENT_STRESS_SUITE_INCOMPLETE"
    )
    assert any(
        failure["reason"] == "ZERO_LIQUIDATION_STRESS_SUITE_BLOCKED"
        for failure in payloads["a_grade_execution_gate.json"]["failure_reasons"]
    )


def test_zero_liquidation_passes_when_dynamic_buffer_covers_rare_event_suite(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "paper_only": True,
                "places_real_order": False,
                "candidate_allocations": [
                    _verified_candidate(
                        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
                        explicit_paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
                        allocator_decision="ALLOW_WITH_SIZE",
                        gross_notional_usd=100.0,
                        allocated_margin_usd=100.0,
                        liquidation_buffer_bps=500.0,
                        pre_entry_stress_tests=_rare_event_stress_suite(scenario_bps=100.0),
                    )
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    zero = payloads["zero_liquidation_status.json"]
    assert zero["status"] == "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE"
    assert zero["new_a_grade_entries_allowed"] is True
    assert zero["release_ready"] is True
    assert zero["passed_a_grade_candidate_count"] == 1
    assert zero["blocker_counts"] == {}
    assert zero["candidate_samples"][0]["required_liquidation_buffer_bps"] == 160.0
    assert zero["candidate_samples"][0]["rare_event_stress_passed"] is True
    assert payloads["operator_dashboard_payload.json"]["zero_liquidation_state"] == (
        "PASSED_ZERO_LIQUIDATION_RARE_EVENT_STRESS_SUITE"
    )


def test_a_grade_gate_blocks_when_zero_realtime_outcomes(tmp_path: Path) -> None:
    payloads = build_guardian_payloads(
        paths=ContinuousEdgeGuardianPaths(repo_root=tmp_path),
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    gate = payloads["a_grade_execution_gate.json"]
    assert gate["a_grade_new_entries_allowed"] is False
    assert gate["new_candidate_tier_override"] == "SHADOW_ONLY"
    assert gate["status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert any(
        failure["reason"] == "INSUFFICIENT_REALTIME_A_GRADE_CLOSED_ECONOMIC_TRADES"
        for failure in gate["failure_reasons"]
    )


def test_realtime_acquisition_admits_verified_pre_outcome_a_grade_feedback(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    _write_acquisition_sources(
        paths,
        candidates=[_verified_candidate()],
        outcomes=[_verified_outcome()],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert len(admitted) == 1
    assert status["status"] == "PASSED"
    assert status["admitted_economic_outcome_count"] == 1
    assert admitted[0]["candidate_selected_before_outcome"] is True
    assert admitted[0]["trust_source_ids"]["prediction_id"] == "pred-1"


def test_prediction_id_alone_is_not_sufficient_trust(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    candidate = _verified_candidate(
        candidate_selected_before_outcome=None,
        frozen_selector_fingerprint=None,
        selector_policy_fingerprint=None,
    )
    _write_acquisition_sources(
        paths,
        candidates=[candidate],
        outcomes=[_verified_outcome()],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert admitted == []
    reasons = status["rows_rejected_by_reason"]
    assert reasons["CANDIDATE_NOT_MARKED_SELECTED_BEFORE_OUTCOME"] == 1
    assert reasons["SOURCE_SELECTOR_POLICY_FINGERPRINT_MISSING"] == 1
    assert status["prediction_id_alone_sufficient_trust_evidence"] is False


def test_guardian_halted_pre_a_grade_candidate_is_not_release_evidence(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    candidate = _verified_candidate(
        paper_opportunity_tier="SHADOW_ONLY",
        explicit_paper_opportunity_tier=None,
        paper_opportunity_tier_reason="CONTINUOUS_EDGE_GUARDIAN_A_GRADE_HALTED",
        pre_guardian_paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
        pre_guardian_paper_opportunity_tier_reason="STRICT_UPSTREAM_PAPER_FILL_GATE_ALLOWED",
        pre_guardian_paper_fill_allowed_source="STRICT_UPSTREAM_PAPER_FILL_GATE",
        paper_fill_allowed_source="CONTINUOUS_EDGE_GUARDIAN_BLOCKED_NEW_A_GRADE_ENTRIES",
        continuous_edge_guardian_forced_shadow_only=True,
        counts_as_a_grade_evidence=False,
    )
    _write_acquisition_sources(
        paths,
        candidates=[candidate],
        outcomes=[_verified_outcome()],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert admitted == []
    assert status["rows_rejected_by_reason"]["A_GRADE_HALTED_BY_CONTINUOUS_EDGE_GUARDIAN"] == 1
    assert "SOURCE_A_GRADE_EXECUTION_PAPER_ADMISSION_MISSING" not in status["rows_rejected_by_reason"]


def test_b_grade_feedback_rejection_is_explained_without_a_grade_admission(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    outcome = _verified_outcome(
        paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        explicit_paper_opportunity_tier="B_GRADE_EXPLORATION_PAPER",
        candidate_selected_before_outcome=True,
        counts_as_a_grade_evidence=False,
    )
    _write_acquisition_sources(
        paths,
        candidates=[],
        outcomes=[outcome],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert admitted == []
    assert status["rows_rejected_by_reason"]["MISSING_PRE_OUTCOME_A_GRADE_CANDIDATE"] == 1
    assert status["rows_rejected_by_reason"][
        "FEEDBACK_TIER_B_GRADE_EXPLORATION_PAPER_NOT_A_GRADE_EVIDENCE"
    ] == 1
    assert status["feedback_paper_opportunity_tier_counts"] == {
        "B_GRADE_EXPLORATION_PAPER": 1
    }
    assert status["rejected_by_feedback_paper_opportunity_tier"] == {
        "B_GRADE_EXPLORATION_PAPER": 1
    }
    assert status["rejected_by_feedback_counts_as_a_grade_evidence"] == {
        "False": 1
    }
    assert status["sample_rejections"][0]["paper_opportunity_tier"] == (
        "B_GRADE_EXPLORATION_PAPER"
    )
    assert status["sample_rejections"][0]["counts_as_a_grade_evidence"] is False


def test_mismatched_lineage_remains_quarantined(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    _write_acquisition_sources(
        paths,
        candidates=[_verified_candidate(symbol="BTCUSDT")],
        outcomes=[_verified_outcome(symbol="ETHUSDT")],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert admitted == []
    assert status["rows_rejected_by_reason"]["SYMBOL_MISMATCH_BETWEEN_CANDIDATE_AND_OUTCOME"] == 1


def test_future_available_at_is_rejected_by_realtime_acquisition(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    _write_acquisition_sources(
        paths,
        candidates=[_verified_candidate(available_at="2026-06-22T12:01:00Z")],
        outcomes=[_verified_outcome(available_at="2026-06-22T12:01:00Z")],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert admitted == []
    assert status["rows_rejected_by_reason"]["AVAILABLE_AT_AFTER_DECISION_TIME"] == 1


def test_fallback_execution_cost_evidence_is_rejected(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    _write_acquisition_sources(
        paths,
        candidates=[_verified_candidate(bid_ask_spread_bps_fallback=True, actual_observed_spread_source="FALLBACK_2_BPS")],
        outcomes=[_verified_outcome(bid_ask_spread_bps_fallback=True, actual_observed_spread_source="FALLBACK_2_BPS")],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert admitted == []
    assert status["rows_rejected_by_reason"]["FALLBACK_COST_REPORTED_AS_MARKET_OBSERVED"] == 1


def test_lifecycle_strategy_feedback_is_not_release_entry_evidence(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    _write_acquisition_sources(
        paths,
        candidates=[_verified_candidate(strategy_id="reduce_size_mode", strategy="reduce_size_mode")],
        outcomes=[_verified_outcome(strategy_id="reduce_size_mode", strategy="reduce_size_mode")],
    )

    admitted, status = acquire_realtime_a_grade_evidence(
        paths=paths,
        existing_reverify_rows=[],
        generated_utc="2026-06-22T13:00:00Z",
    )

    assert admitted == []
    assert status["rows_rejected_by_reason"]["LIFECYCLE_OR_NO_TRADE_STRATEGY_NOT_ENTRY_EVIDENCE"] == 1


def test_a_grade_gate_passes_only_with_90p_lcb_expectancy_pf_zero_liquidation(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.paper_trade_management_dir.mkdir(parents=True)
    paths.paper_b_grade_bucket_promotion_readiness_path.write_text(
        json.dumps(
            {
                "schema_version": "paper_b_grade_bucket_promotion_readiness_status_v1",
                "status": "A_GRADE_PROMOTABLE_BUCKETS_READY",
                "thresholds": {"minimum_bucket_sample_count": 30},
                "buckets": [
                    {
                        "symbol": "S000USDT",
                        "timeframe": "1m",
                        "side": "long",
                        "strategy": "strategy_0",
                        "regime": "regime_0",
                        "confidence_bucket": "UNKNOWN",
                        "closed_economic_outcome_count": 1000,
                        "point_win_rate_after_cost": 0.95,
                        "win_rate_95pct_lower_confidence_bound": 0.93,
                        "after_cost_expectancy_bps": 18.0,
                        "expectancy_95pct_lower_confidence_bound_bps": 5.0,
                        "profit_factor": 10.0,
                        "profit_factor_numeric": 10.0,
                        "profit_factor_is_infinite": False,
                        "bucket_metric_conditions_pass": True,
                        "a_grade_promotion_allowed": True,
                    }
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    paths.paper_adaptive_sizing_path.write_text(
        json.dumps(
            {
                "paper_only": True,
                "places_real_order": False,
                "candidate_allocation_count": 1,
                "accepted_allocation_count": 1,
                "blocked_allocation_count": 0,
                "candidate_allocations": [
                    _verified_candidate(
                        symbol="S000USDT",
                        timeframe="1m",
                        selected_action="long",
                        action="long",
                        side="long",
                        strategy="strategy_0",
                        strategy_id="strategy_0",
                        market_regime="regime_0",
                        paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
                        explicit_paper_opportunity_tier="A_GRADE_EXECUTION_PAPER",
                        allocator_decision="ALLOW_WITH_SIZE",
                        gross_notional_usd=100.0,
                        allocated_margin_usd=100.0,
                        liquidation_buffer_bps=500.0,
                        pre_entry_stress_tests=_rare_event_stress_suite(scenario_bps=100.0),
                    )
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    rows = _passing_realtime_rows()
    holdout_rows = [
        _row(index + 100000, symbol=f"H{index % 100:03d}USDT")
        for index in range(50000)
    ]
    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=holdout_rows,
        realtime_rows=rows,
        holdout_acquisition_status={
            "schema_version": "continuous_edge_guardian_v1",
            "generated_utc": "2026-06-22T16:00:00Z",
            "status": "PASSED",
            "accepted_row_count": len(holdout_rows),
            "rejected_row_count": 0,
            "rows_rejected_by_reason": {},
            "blockers": [],
            "holdout_prediction_coverage_status": {
                "status": "READY_UNTOUCHED_HOLDOUT_PREDICTION_COVERAGE",
                "point_in_time_valid_prediction_count": 50000,
                "symbol_count": 100,
                "timeframe_count": 5,
                "selected_policy_action_counts": {
                    "LONG": 15000,
                    "SHORT": 15000,
                    "NO_TRADE": 20000,
                },
                "symbols": [f"H{index:03d}USDT" for index in range(100)],
                "timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "counts_as_a_grade_evidence": False,
                "counts_no_trade_as_win": False,
            },
        },
        generated_utc="2026-06-22T16:00:00Z",
    )

    metrics = payloads["realtime_a_grade_performance_status.json"]["metrics"]
    assert metrics["rolling_100_trade_win_rate"] == 1.0
    assert metrics["rolling_300_trade_win_rate"] >= 0.90
    assert metrics["rolling_1000_trade_win_rate"] == 0.95
    assert metrics["overall_95pct_lower_confidence_bound_win_rate"] >= 0.90
    assert metrics["after_cost_expectancy_bps"] > 0.0
    assert metrics["expectancy_95pct_lower_bound_bps"] > 0.0
    assert metrics["profit_factor"] >= 2.0
    assert metrics["liquidation_event_count"] == 0
    assert payloads["a_grade_execution_gate.json"]["a_grade_new_entries_allowed"] is True


def test_liquidation_event_forces_halted_liquidation_risk(tmp_path: Path) -> None:
    rows = _passing_realtime_rows()
    rows[-1]["exit_reason"] = "LIQUIDATION"
    holdout_rows = [
        _row(index + 100000, symbol=f"H{index % 100:03d}USDT")
        for index in range(50000)
    ]
    payloads = build_guardian_payloads(
        paths=ContinuousEdgeGuardianPaths(repo_root=tmp_path),
        holdout_rows=holdout_rows,
        realtime_rows=rows,
        generated_utc="2026-06-22T16:00:00Z",
    )

    assert payloads["a_grade_execution_gate.json"]["status"] == "A_GRADE_HALTED_LIQUIDATION_RISK"
    assert payloads["a_grade_execution_gate.json"]["a_grade_new_entries_allowed"] is False


def test_no_trade_and_hedge_legs_not_counted_as_wins() -> None:
    rows = [
        _row(1, economic_trade_id="parent-1", selected_action="long", realized_net_pnl_usd=4.0),
        _row(2, economic_trade_id="parent-1", hedge_parent_id="parent-1", selected_action="short", realized_net_pnl_usd=-1.0),
        _row(3, economic_trade_id="no-trade-1", selected_action="NO_TRADE", trade_outcome="WIN", realized_net_pnl_usd=99.0),
    ]

    metrics = compute_economic_metrics(rows)

    assert metrics["closed_economic_trade_count"] == 1
    assert metrics["win_count"] == 1
    assert metrics["no_trade_rows_excluded_from_win_count"] == 1
    assert metrics["hedged_structures_counted_as_single_outcome"] == 1
    assert metrics["after_cost_expectancy_bps"] == 40.0


def test_trajectory_status_consumes_adaptive_feasibility_without_ready_claim(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.adaptive_dir.mkdir(parents=True, exist_ok=True)
    paths.one_thousand_x_feasibility_path.write_text(
        json.dumps(
            {
                "status": "NO_GO_1000X_FEASIBILITY_REQUIRES_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY",
                "classification": "UNSUPPORTED_DEPENDENCY_GATES_NOT_PASSED",
                "target_multiple": 1000.0,
                "horizon_years": 5.0,
                "target_equity_usd": 10_000_000.0,
                "required_daily_return": 0.00379224,
                "observed_daily_log_return": 0.0,
                "observed_cagr": 0.0,
                "observed_growth_evidence": {
                    "observed_growth_classification": "OBSERVED_GROWTH_BELOW_REQUIRED",
                    "window_evidence": [
                        {"window": "1d", "observed_window_return": 0.001},
                        {"window": "7d", "observed_window_return": 0.002},
                        {"window": "30d", "observed_window_return": -0.003},
                    ],
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payloads = build_guardian_payloads(
        paths=paths,
        holdout_rows=[],
        realtime_rows=[],
        generated_utc="2026-06-22T16:00:00Z",
    )

    trajectory = payloads["one_thousand_x_trajectory_status.json"]
    assert trajectory["status"] == "INSUFFICIENT_EVIDENCE"
    assert trajectory["current_status"] == "INSUFFICIENT_EVIDENCE"
    assert trajectory["actual_1d_return"] == 0.001
    assert trajectory["actual_7d_return"] == 0.002
    assert trajectory["actual_30d_return"] == -0.003
    assert trajectory["required_capital"] == 10_000_000.0
    assert trajectory["required_edge"] == 0.00379224
    assert trajectory["required_edge_unit"] == "daily_geometric_return"
    assert trajectory["source_status"] == (
        "NO_GO_1000X_FEASIBILITY_REQUIRES_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY"
    )
    assert trajectory["source_classification"] == "UNSUPPORTED_DEPENDENCY_GATES_NOT_PASSED"
    assert trajectory["source_observed_growth_classification"] == "OBSERVED_GROWTH_BELOW_REQUIRED"
    assert "actual_1d_return" not in trajectory["missing_trajectory_evidence_fields"]
    assert "lower_confidence_bound_growth_rate" in trajectory["missing_trajectory_evidence_fields"]
    assert trajectory["guaranteed_profit_claim"] is False
    assert trajectory["leverage_increase_allowed_because_behind"] is False
    assert (
        payloads["continuous_edge_guardian_status.json"]["trajectory_status"]["actual_30d_return"]
        == -0.003
    )
    assert (
        payloads["EVIDENCE_MANIFEST.json"]["one_thousand_x_feasibility_source"]
        == str(paths.one_thousand_x_feasibility_path)
    )


def test_antigaming_flags_future_leakage_fallback_costs_post_outcome_selection(tmp_path: Path) -> None:
    row = _row(
        1,
        available_at="2026-06-22T12:01:00Z",
        decision_time="2026-06-22T12:00:00Z",
        bid_ask_spread_bps_fallback=True,
        candidate_selected_after_outcome=True,
    )
    payloads = build_guardian_payloads(
        paths=ContinuousEdgeGuardianPaths(repo_root=tmp_path),
        holdout_rows=[],
        realtime_rows=[row],
        generated_utc="2026-06-22T16:00:00Z",
    )

    violations = payloads["anti_metric_gaming_status.json"]["violations"]
    reasons = {item["reason"] for item in violations}
    assert "FUTURE_LEAKAGE" in reasons
    assert "FALLBACK_COST_REPORTED_AS_MARKET_OBSERVED" in reasons
    assert "POST_OUTCOME_CANDIDATE_SELECTION" in reasons


def test_guardian_writes_required_goal_files(tmp_path: Path) -> None:
    status = run_once(
        repo_root=tmp_path,
        publish_redis=False,
        generated_utc="2026-06-22T16:00:00Z",
    )

    goal_dir = tmp_path / "goal_state" / "V2_CONTINUOUS_90P_A_GRADE_EDGE_ZERO_LIQUIDATION_AND_1000X_COMPOUNDING_RELEASE"
    for filename in (
        "GOAL_LOCK.json",
        "PHASE_LEDGER.json",
        "FINDING_BURNDOWN.json",
        "COMMANDS_RUN.md",
        "FILES_CHANGED.md",
        "VALIDATION_LEDGER.json",
        "CURRENT_BLOCKERS.json",
        "EVIDENCE_MANIFEST.json",
        "GO_NO_GO.md",
    ):
        assert (goal_dir / filename).exists()


def test_holdout_acquisition_blocker_uses_rejected_sidecar_and_registry(tmp_path: Path) -> None:
    paths = ContinuousEdgeGuardianPaths(repo_root=tmp_path)
    paths.adaptive_dir.mkdir(parents=True, exist_ok=True)
    paths.holdout_rows_path.write_text("", encoding="utf-8")
    paths.holdout_rejected_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "symbol": "BTCUSDT",
                    "timeframe": "1h",
                    "side": "long",
                    "decision_time": "2026-06-22T12:00:00Z",
                    "source_row_identity": f"BTCUSDT:1h:{index}:long",
                    "candidate_identity": f"candidate-{index}",
                    "reasons": ["NO_PRE_REGISTERED_HOLDOUT_WINDOW", "DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE"],
                },
                sort_keys=True,
            )
            for index in range(2)
        )
        + "\n",
        encoding="utf-8",
    )
    paths.holdout_manifest_path.write_text(
        json.dumps({"status": "NO_COUNTABLE_HOLDOUT_ROWS_APPENDED"}, sort_keys=True),
        encoding="utf-8",
    )
    paths.holdout_window_registry_path.write_text(
        json.dumps(
            {
                "status": "DRAFT_NOT_COUNTABLE_AWAITING_UNTOUCHED_PROOF",
                "registered_window_count": 0,
                "windows": [{"window_id": "draft-1", "eligible_for_holdout": False}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    paths.holdout_window_candidate_audit_path.write_text(
        json.dumps(
            {
                "status": "DRAFT_HOLDOUT_WINDOW_CANDIDATES_NOT_COUNTABLE",
                "windows": [{"window_id": "candidate-1"}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    run_once(
        repo_root=tmp_path,
        publish_redis=False,
        generated_utc="2026-06-22T16:00:00Z",
    )

    acquisition = json.loads(
        (paths.public_dir / "untouched_holdout_evidence_acquisition_status.json").read_text(encoding="utf-8")
    )
    dashboard = json.loads(
        (paths.public_dir / "operator_dashboard_payload.json").read_text(encoding="utf-8")
    )

    assert acquisition["status"] == "BLOCKED_NO_COUNTABLE_UNTOUCHED_HOLDOUT_EVIDENCE"
    assert acquisition["accepted_row_count"] == 0
    assert acquisition["rejected_row_count"] == 2
    assert acquisition["rows_rejected_by_reason"]["NO_PRE_REGISTERED_HOLDOUT_WINDOW"] == 2
    assert acquisition["source_statuses"]["window_registry_status"] == "DRAFT_NOT_COUNTABLE_AWAITING_UNTOUCHED_PROOF"
    assert dashboard["exact_blocker"]["reason"] == "HOLDOUT_EVIDENCE_ACQUISITION_BLOCKED"
    assert dashboard["untouched_holdout_evidence_acquisition"]["rows_rejected_by_reason"][
        "DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE"
    ] == 2
    assert (paths.goal_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip() == BLOCKED_MARKER
    assert dashboard["overall_status"] == "BLOCKED"


def test_holdout_prediction_coverage_does_not_count_as_a_grade_economic_outcome(tmp_path: Path) -> None:
    payloads = build_guardian_payloads(
        paths=ContinuousEdgeGuardianPaths(repo_root=tmp_path),
        holdout_rows=[],
        realtime_rows=[],
        holdout_acquisition_status={
            "schema_version": "continuous_edge_guardian_v1",
            "generated_utc": "2026-06-22T16:00:00Z",
            "status": "BLOCKED_NO_COUNTABLE_UNTOUCHED_HOLDOUT_EVIDENCE",
            "accepted_row_count": 0,
            "rejected_row_count": 0,
            "rows_rejected_by_reason": {},
            "blockers": [],
            "holdout_prediction_coverage_status": {
                "status": "READY_UNTOUCHED_HOLDOUT_PREDICTION_COVERAGE",
                "point_in_time_valid_prediction_count": 50000,
                "symbol_count": 100,
                "timeframe_count": 5,
                "selected_policy_action_counts": {
                    "LONG": 15000,
                    "SHORT": 15000,
                    "NO_TRADE": 20000,
                },
                "symbols": [f"H{index:03d}USDT" for index in range(100)],
                "timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "counts_as_a_grade_evidence": False,
                "counts_no_trade_as_win": False,
            },
        },
        generated_utc="2026-06-22T16:00:00Z",
    )

    holdout = payloads["untouched_holdout_performance.json"]
    failure_reasons = {failure["reason"] for failure in holdout["failures"]}

    assert holdout["metrics"]["point_in_time_valid_prediction_count"] == 50000
    assert holdout["metrics"]["holdout_prediction_symbol_count"] == 100
    phase3_coverage = holdout["phase3_holdout_prediction_coverage"]
    assert phase3_coverage["status"] == "READY_PHASE3_HOLDOUT_PREDICTION_COVERAGE"
    assert phase3_coverage["point_in_time_valid_prediction_count"] == 50000
    assert phase3_coverage["symbol_count"] == 100
    assert phase3_coverage["missing_timeframes"] == []
    assert phase3_coverage["missing_selected_policy_actions"] == []
    assert phase3_coverage["counts_as_a_grade_evidence"] is False
    assert phase3_coverage["counts_no_trade_as_win"] is False
    assert phase3_coverage["no_trade_counted_as_economic_win"] is False
    assert payloads["continuous_edge_guardian_status.json"]["phase3_holdout_prediction_coverage"] == phase3_coverage
    assert payloads["operator_dashboard_payload.json"]["phase3_holdout_prediction_coverage"] == phase3_coverage
    assert "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS" not in failure_reasons
    assert "INSUFFICIENT_UNTOUCHED_HOLDOUT_SYMBOL_COVERAGE" not in failure_reasons
    assert "INSUFFICIENT_UNTOUCHED_HOLDOUT_TIMEFRAME_COVERAGE" not in failure_reasons
    assert "INSUFFICIENT_UNTOUCHED_HOLDOUT_ACTION_COVERAGE" not in failure_reasons
    assert holdout["metrics"]["closed_economic_trade_count"] == 0
    assert holdout["point_in_time_valid_prediction_count"] == 50000
    assert holdout["holdout_prediction_coverage_counts_as_a_grade_evidence"] is False
    assert holdout["holdout_prediction_coverage_counts_no_trade_as_win"] is False
    assert "INSUFFICIENT_ROLLING_100_TRADE_WINDOW" in failure_reasons
    assert payloads["a_grade_execution_gate.json"]["a_grade_new_entries_allowed"] is False


def test_holdout_prediction_coverage_requires_no_trade_action(tmp_path: Path) -> None:
    payloads = build_guardian_payloads(
        paths=ContinuousEdgeGuardianPaths(repo_root=tmp_path),
        holdout_rows=[],
        realtime_rows=[],
        holdout_acquisition_status={
            "schema_version": "continuous_edge_guardian_v1",
            "generated_utc": "2026-06-22T16:00:00Z",
            "status": "BLOCKED_NO_COUNTABLE_UNTOUCHED_HOLDOUT_EVIDENCE",
            "accepted_row_count": 0,
            "rejected_row_count": 0,
            "rows_rejected_by_reason": {},
            "blockers": [],
            "holdout_prediction_coverage_status": {
                "status": "READY_UNTOUCHED_HOLDOUT_PREDICTION_COVERAGE",
                "point_in_time_valid_prediction_count": 50000,
                "symbol_count": 100,
                "timeframe_count": 5,
                "selected_policy_action_counts": {
                    "LONG": 25000,
                    "SHORT": 25000,
                    "NO_TRADE": 0,
                },
                "symbols": [f"H{index:03d}USDT" for index in range(100)],
                "timeframes": ["1m", "5m", "15m", "1h", "4h"],
                "counts_as_a_grade_evidence": False,
                "counts_no_trade_as_win": False,
            },
        },
        generated_utc="2026-06-22T16:00:00Z",
    )

    holdout = payloads["untouched_holdout_performance.json"]
    phase3_coverage = holdout["phase3_holdout_prediction_coverage"]
    failure_reasons = {failure["reason"] for failure in holdout["failures"]}

    assert phase3_coverage["status"] == "BLOCKED_PHASE3_HOLDOUT_PREDICTION_COVERAGE"
    assert phase3_coverage["missing_selected_policy_actions"] == ["NO_TRADE"]
    assert phase3_coverage["counts_as_a_grade_evidence"] is False
    assert "INSUFFICIENT_UNTOUCHED_HOLDOUT_ACTION_COVERAGE" in failure_reasons
    assert payloads["a_grade_execution_gate.json"]["a_grade_new_entries_allowed"] is False
