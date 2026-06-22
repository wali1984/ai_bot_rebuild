from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli.v2_paper_only_confidence_threshold_trial_and_outcome_monitor import main
from v2.backend.app.services.native_trainer.paper_confidence_threshold_trial import (
    GO_READY,
    PaperConfidenceTrialPaths,
    build_paper_confidence_threshold_trial,
    classify_trial_candidate,
    write_paper_confidence_trial_artifacts,
)


def _prediction(
    prediction_id: str,
    *,
    confidence: float,
    expected: float,
    allowed: bool = False,
    reasons: list[str] | None = None,
    stale: int = 0,
    valid_for_paper: bool = True,
) -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "confidence_calibrated": confidence,
        "expected_move_after_cost_bps": expected,
        "paper_fill_allowed": allowed,
        "paper_fill_gate_block_reasons": reasons or ["confidence_below_threshold"],
        "valid_for_training": True,
        "valid_for_prediction": True,
        "valid_for_risk": True,
        "valid_for_orchestrator": True,
        "valid_for_paper": valid_for_paper,
        "market_state_id": f"mstate_{prediction_id}",
        "market_state_integrity_score": 96.25,
        "feature_snapshot_id": f"snapshot_{prediction_id}",
        "data_coverage_percent": 76.0,
        "stale_feature_count": stale,
        "missing_feature_count": 12,
        "price_target": 60100.0,
        "price_target_validation_status": "VALID",
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "model_id": "test_model",
        "checkpoint_id": "test_checkpoint",
    }


def _paths(tmp_path: Path) -> PaperConfidenceTrialPaths:
    public = tmp_path / "v2/frontend/public"
    return PaperConfidenceTrialPaths(
        repo_root=tmp_path,
        worklog_dir=tmp_path / "claude_worklog/final_readiness/v2_paper_only_confidence_threshold_trial_and_outcome_monitor/latest",
        public_dir=public / "v2_paper_only_confidence_threshold_trial_and_outcome_monitor/latest",
        prediction_source_path=public / "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json",
        runtime_truth_path=public / "operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json",
        portfolio_path=public / "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        outcome_observer_path=public / "operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json",
        confidence_proposal_path=public / "v2_confidence_calibration_and_paper_actionability_improvement/latest/calibrated_confidence_threshold_proposal.json",
    )


def _payloads() -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    prediction_source = {
        "generated_est": "2026-06-10T16:00:00-04:00",
        "prediction_rows": [
            _prediction("recoverable", confidence=0.541, expected=18.0),
            _prediction(
                "weak",
                confidence=0.542,
                expected=2.0,
                reasons=["confidence_below_threshold", "expected_move_after_cost_below_threshold"],
            ),
            _prediction("stale", confidence=0.546, expected=20.0, stale=1),
            _prediction("already_allowed", confidence=0.552, expected=12.0, allowed=True, reasons=[]),
        ],
    }
    runtime_truth = {
        "live_gate": "enabled_operator_approved",
        "trader_state": "LIVE_ARMED_BALANCE_HOLD",
        "live_order_submit_allowed": False,
        "live_order_submit_blocker": "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
    }
    portfolio = {
        "accepted_fill_total": 4,
        "economic_fill_total": 4,
        "open_positions_count": 2,
        "equity": 10008.0,
        "total_pnl_usd": 8.0,
        "last_equity_update_est": "2026-06-10T16:00:00-04:00",
    }
    outcome = {
        "observations_total": 1,
        "completed_observations": 1,
        "observations": [
            {
                "prediction_id": "recoverable",
                "completed": True,
                "after_cost_correct": True,
                "would_have_beaten_costs": True,
            }
        ],
    }
    proposal = {
        "status": "PAPER_ONLY_TRIAL_PROPOSED_NEEDS_MONITOR",
        "recommended_paper_only_trial": {"paper_confidence_threshold": 0.54},
    }
    return prediction_source, runtime_truth, portfolio, outcome, proposal


def test_trial_candidate_guard_accepts_only_clean_confidence_blocks() -> None:
    ok, reasons = classify_trial_candidate(_prediction("recoverable", confidence=0.541, expected=18.0))
    assert ok is True
    assert reasons == []

    ok, reasons = classify_trial_candidate(
        _prediction(
            "weak",
            confidence=0.541,
            expected=2.0,
            reasons=["confidence_below_threshold", "expected_move_after_cost_below_threshold"],
        )
    )
    assert ok is False
    assert "OTHER_BLOCKER:expected_move_after_cost_below_threshold" in reasons
    assert "EXPECTED_MOVE_AFTER_COST_BELOW_TRIAL_FLOOR" in reasons


def test_paper_confidence_trial_builds_safe_artifacts(tmp_path: Path) -> None:
    prediction_source, runtime_truth, portfolio, outcome, proposal = _payloads()
    result = build_paper_confidence_threshold_trial(
        prediction_source=prediction_source,
        runtime_truth=runtime_truth,
        portfolio=portfolio,
        outcome_observer=outcome,
        confidence_proposal=proposal,
        generated_est="2026-06-10T16:00:00-04:00",
        apply_trial=False,
        run_paper_loop=False,
    )
    written = write_paper_confidence_trial_artifacts(
        paths=_paths(tmp_path),
        result=result,
        generated_est="2026-06-10T16:00:00-04:00",
    )
    assert written.go_no_go == GO_READY

    public_dir = tmp_path / "v2/frontend/public/v2_paper_only_confidence_threshold_trial_and_outcome_monitor/latest"
    required = {
        "GO_NO_GO.md",
        "V2_PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_AND_OUTCOME_MONITOR_REPORT.md",
        "paper_threshold_trial_config.json",
        "paper_actionability_before_after_status.json",
        "confidence_bucket_outcome_monitor.json",
        "paper_pnl_after_threshold_trial.json",
        "risk_orchestrator_paper_lineage_status.json",
        "operator_dashboard_payload.json",
    }
    assert required == {path.name for path in public_dir.iterdir()}

    dashboard = json.loads((public_dir / "operator_dashboard_payload.json").read_text(encoding="utf-8"))
    before_after = json.loads((public_dir / "paper_actionability_before_after_status.json").read_text(encoding="utf-8"))
    lineage = json.loads((public_dir / "risk_orchestrator_paper_lineage_status.json").read_text(encoding="utf-8"))

    assert dashboard["summary"]["trial_promoted_signal_count"] == 1
    assert dashboard["live"]["live_threshold_changed"] is False
    assert dashboard["safety"]["exchange_order_submitted"] is False
    assert before_after["paper_allowed_before"] == 1
    assert before_after["paper_allowed_after_simulated"] == 2
    assert lineage["complete_trial_lineage_count"] == 1
    assert lineage["risk_bypass"] is False


def test_paper_confidence_trial_cli_writes_outputs(tmp_path: Path, capsys) -> None:
    paths = _paths(tmp_path)
    prediction_source, runtime_truth, portfolio, outcome, proposal = _payloads()
    payloads = {
        paths.prediction_source_path: prediction_source,
        paths.runtime_truth_path: runtime_truth,
        paths.portfolio_path: portfolio,
        paths.outcome_observer_path: outcome,
        paths.confidence_proposal_path: proposal,
    }
    for path, payload in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    code = main(["--repo-root", str(tmp_path), "--monitor-only", "--skip-paper-loop"])

    assert code == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["go_no_go"] == GO_READY
    assert stdout["trial_promoted_signal_count"] == 1
    assert stdout["live_threshold_changed"] is False
    assert (paths.public_dir / "operator_dashboard_payload.json").exists()
