from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli.v2_confidence_calibration_and_paper_actionability_improvement import main
from v2.backend.app.services.native_trainer.confidence_actionability_calibration import (
    GO_READY,
    ConfidenceActionabilityPaths,
    build_confidence_actionability,
    write_confidence_actionability_artifacts,
)


def _prediction(
    prediction_id: str,
    *,
    confidence: float,
    expected: float,
    allowed: bool,
    reasons: list[str] | None = None,
) -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "confidence_calibrated": confidence,
        "expected_move_after_cost_bps": expected,
        "paper_fill_allowed": allowed,
        "paper_fill_gate_block_reasons": reasons or [],
        "valid_for_paper": True,
        "valid_for_training": True,
        "market_state_integrity_score": 96.25,
        "data_coverage_percent": 76.0,
        "stale_feature_count": 0,
        "missing_feature_count": 12,
        "price_target_validation_status": "VALID",
    }


def _paths(tmp_path: Path) -> ConfidenceActionabilityPaths:
    public = tmp_path / "v2/frontend/public"
    return ConfidenceActionabilityPaths(
        repo_root=tmp_path,
        worklog_dir=tmp_path / "claude_worklog/final_readiness/v2_confidence_calibration_and_paper_actionability_improvement/latest",
        public_dir=public / "v2_confidence_calibration_and_paper_actionability_improvement/latest",
        prediction_source_path=public / "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        runtime_truth_path=public / "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json",
        portfolio_path=public / "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        outcome_observer_path=public / "operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json",
        explanation_path=public / "operator_runtime/v2_prediction_signal_explanations/latest/prediction_signal_explanations.json",
        paper_feedback_path=public / "operator_runtime/v2_paper_trade_management/latest/trainer_feedback_outcomes.json",
        bucket_quarantine_path=public / "operator_runtime/v2_paper_trade_management/latest/bucket_quarantine_status.json",
    )


def _source_payloads() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    prediction_source = {
        "generated_est": "2026-06-10T14:00:00-04:00",
        "prediction_rows": [
            _prediction("allowed_clean", confidence=0.552, expected=10.0, allowed=True),
            _prediction("allowed_weak", confidence=0.553, expected=-4.0, allowed=True),
            _prediction(
                "recoverable",
                confidence=0.541,
                expected=18.0,
                allowed=False,
                reasons=["confidence_below_threshold"],
            ),
            _prediction(
                "weak",
                confidence=0.529,
                expected=1.0,
                allowed=False,
                reasons=["confidence_below_threshold", "expected_move_after_cost_below_threshold"],
            ),
        ],
    }
    runtime_truth = {
        "live_gate": "enabled_operator_approved",
        "trader_state": "LIVE_ARMED_BALANCE_HOLD",
        "live_order_submit_allowed": False,
        "live_order_submit_blocker": "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
        "paper_accepted_fills": 2,
        "paper_open_positions_count": 1,
        "paper_equity": 10001.0,
        "paper_pnl": 1.0,
    }
    portfolio = {
        "accepted_fill_total": 2,
        "economic_fill_total": 2,
        "open_positions_count": 1,
        "equity": 10001.0,
        "total_pnl_usd": 1.0,
        "positions_by_symbol": [{"source_fill_ids": ["allowed_clean"]}],
    }
    outcome = {
        "observations_total": 2,
        "completed_observations": 2,
        "false_block_reason_counts": {"deny_low_confidence": 1},
        "observations": [
            {
                "prediction_id": "recoverable",
                "completed": True,
                "after_cost_correct": True,
                "no_trade_correct": False,
                "would_have_beaten_costs": True,
                "max_favorable_excursion_bps": 20.0,
                "max_adverse_excursion_bps": -3.0,
            },
            {
                "prediction_id": "weak",
                "completed": True,
                "after_cost_correct": False,
                "no_trade_correct": True,
                "would_have_beaten_costs": False,
                "max_favorable_excursion_bps": 2.0,
                "max_adverse_excursion_bps": -15.0,
            },
        ],
    }
    explanation = {"summary": {"explanation_rows": 2}}
    return prediction_source, runtime_truth, portfolio, outcome, explanation


def test_confidence_actionability_builds_paper_only_safe_artifacts(tmp_path: Path) -> None:
    prediction_source, runtime_truth, portfolio, outcome, explanation = _source_payloads()
    result = build_confidence_actionability(
        prediction_source=prediction_source,
        runtime_truth=runtime_truth,
        portfolio=portfolio,
        outcome_observer=outcome,
        explanation_payload=explanation,
        generated_est="2026-06-10T14:00:00-04:00",
    )
    written = write_confidence_actionability_artifacts(
        paths=_paths(tmp_path),
        result=result,
        generated_est="2026-06-10T14:00:00-04:00",
    )

    assert written.go_no_go == GO_READY
    public_dir = tmp_path / "v2/frontend/public/v2_confidence_calibration_and_paper_actionability_improvement/latest"
    required = {
        "GO_NO_GO.md",
        "V2_CONFIDENCE_CALIBRATION_AND_PAPER_ACTIONABILITY_IMPROVEMENT_REPORT.md",
        "confidence_gate_block_distribution.json",
        "confidence_bucket_outcome_analysis.json",
        "paper_actionability_candidate_recovery.json",
        "loss_adjusted_paper_actionability_status.json",
        "calibrated_confidence_threshold_proposal.json",
        "paper_only_threshold_simulation.json",
        "post_calibration_paper_monitor_status.json",
        "operator_dashboard_payload.json",
    }
    assert required == {path.name for path in public_dir.iterdir()}

    dashboard = json.loads((public_dir / "operator_dashboard_payload.json").read_text(encoding="utf-8"))
    proposal = json.loads((public_dir / "calibrated_confidence_threshold_proposal.json").read_text(encoding="utf-8"))
    recovery = json.loads((public_dir / "paper_actionability_candidate_recovery.json").read_text(encoding="utf-8"))
    loss_adjusted = json.loads((public_dir / "loss_adjusted_paper_actionability_status.json").read_text(encoding="utf-8"))

    assert dashboard["summary"]["under_confident_candidate_count"] == 1
    assert dashboard["summary"]["actionable_after_loss_adjustment_candidate_count"] == 1
    assert dashboard["summary"]["loss_quarantine_filtered_under_confident_candidate_count"] == 0
    assert dashboard["summary"]["current_allowed_clean_positive_edge_overlap"] == 1
    assert dashboard["summary"]["paper_threshold_auto_applied"] is False
    assert dashboard["summary"]["live_threshold_changed"] is False
    assert dashboard["live"]["live_order_submit_allowed"] is False
    assert proposal["live_threshold_change"] == "NO_CHANGE"
    assert proposal["paper_runtime_threshold_change"] == "NO_AUTO_CHANGE"
    assert recovery["paper_threshold_changed"] is False
    assert recovery["live_threshold_changed"] is False
    assert loss_adjusted["runtime_thresholds_changed"] is False
    assert loss_adjusted["live_threshold_changed"] is False


def test_confidence_actionability_filters_recovery_candidates_in_loss_quarantine() -> None:
    prediction_source, runtime_truth, portfolio, outcome, explanation = _source_payloads()
    prediction_source["prediction_rows"][2] = {
        **prediction_source["prediction_rows"][2],
        "selected_action": "short",
        "timeframe": "15m",
        "market_regime": "TREND",
        "strategy_id": "trend_mode",
    }
    paper_feedback = {
        "generated_utc": "2026-07-06T01:54:26Z",
        "trainer_feedback_outcomes": [
            {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "selected_action": "short",
                "confidence_calibrated": 0.62,
                "action_was_profitable": False,
            }
        ],
    }
    bucket_quarantine = {
        "status": "ACTIVE_WITH_QUARANTINES",
        "generated_utc": "2026-07-06T01:54:19Z",
        "blocked_bucket_keys": ["side:short", "timeframe:15m"],
    }

    result = build_confidence_actionability(
        prediction_source=prediction_source,
        runtime_truth=runtime_truth,
        portfolio=portfolio,
        outcome_observer=outcome,
        explanation_payload=explanation,
        paper_feedback_payload=paper_feedback,
        bucket_quarantine_status=bucket_quarantine,
        generated_est="2026-06-10T14:00:00-04:00",
    )

    recovery = result.artifacts["paper_actionability_candidate_recovery.json"]
    loss_adjusted = result.artifacts["loss_adjusted_paper_actionability_status.json"]
    dashboard = result.artifacts["operator_dashboard_payload.json"]

    assert recovery["under_confident_candidate_count"] == 1
    assert recovery["loss_quarantine_filtered_under_confident_candidate_count"] == 1
    assert recovery["actionable_after_loss_adjustment_candidate_count"] == 0
    assert recovery["candidate_rows_sample"] == []
    assert loss_adjusted["status"] == "LOSS_ADJUSTED_ACTIONABILITY_ACTIVE"
    assert loss_adjusted["high_confidence_feedback_loss_rows"] == 1
    assert loss_adjusted["loss_adjusted_under_confident_candidate_count"] == 1
    assert dashboard["summary"]["actionable_after_loss_adjustment_candidate_count"] == 0


def test_confidence_actionability_cli_writes_outputs(tmp_path: Path, capsys) -> None:
    paths = _paths(tmp_path)
    prediction_source, runtime_truth, portfolio, outcome, explanation = _source_payloads()
    payloads = {
        paths.prediction_source_path: prediction_source,
        paths.runtime_truth_path: runtime_truth,
        paths.portfolio_path: portfolio,
        paths.outcome_observer_path: outcome,
        paths.explanation_path: explanation,
    }
    for path, payload in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    code = main(["--repo-root", str(tmp_path)])

    assert code == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["go_no_go"] == GO_READY
    assert stdout["paper_threshold_auto_applied"] is False
    assert stdout["live_threshold_changed"] is False
    assert (paths.public_dir / "operator_dashboard_payload.json").exists()
