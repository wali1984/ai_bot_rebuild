from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.cli.v2_cuda_trainer_false_negative_reduction_actionability import main
from v2.backend.app.services.native_trainer.cuda_false_negative_actionability import (
    GO_BLOCKED,
    GO_READY,
    FalseNegativeActionabilityPaths,
    build_false_negative_actionability,
    write_false_negative_actionability_artifacts,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import LIVE_GATE_BLOCKED


def _window(after_cost: float | None, *, drawdown: float = 4.0, favorable: float = 18.0) -> dict[str, object]:
    return {
        "status": "OUTCOME_READY" if after_cost is not None else "INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_WINDOW",
        "after_cost_return_bps": after_cost,
        "drawdown_bps": drawdown if after_cost is not None else None,
        "max_favorable_bps": favorable if after_cost is not None else None,
    }


def _row(
    prediction_id: str,
    *,
    classification: str,
    realized: float,
    symbol: str = "BTCUSDT",
    confidence: float = 0.51,
    coverage: float = 52.0,
    missing: int = 32,
    risk_id: str | None = None,
) -> dict[str, object]:
    risk_id = risk_id if risk_id is not None else f"rd_{prediction_id}"
    return {
        "prediction_id": prediction_id,
        "symbol": symbol,
        "timeframe": "1m",
        "selected_action": "hedge_reserved_fail_closed",
        "counterfactual_side": "long",
        "expected_move_after_cost_bps": 8.0,
        "confidence_calibrated": confidence,
        "paper_fill_allowed": False,
        "paper_fill_gate_status": "PAPER_SHADOW_GATE_BLOCKED",
        "paper_fill_gate_block_reasons": ["risk_denied"],
        "orchestrator_decision_id": f"dec_{prediction_id}",
        "orchestrator_action": "abstain",
        "orchestrator_reason": "abstain_freshness_missing",
        "risk_decision_id": risk_id,
        "risk_action": "deny",
        "risk_reason": "deny_orchestrator_abstained",
        "paper_intent_id": prediction_id,
        "paper_ledger_id": f"pt_{prediction_id}",
        "paper_ledger_action": "record_deny",
        "paper_ledger_reason": "mirror_deny_orchestrator_abstained",
        "data_coverage_percent": coverage,
        "missing_feature_count": missing,
        "stale_feature_count": 0,
        "outcome_windows": {
            "1m": _window(4.0),
            "5m": _window(realized),
            "15m": _window(max(realized, 16.0)),
            "1h": _window(None),
        },
        "primary_outcome_window": "5m",
        "realized_after_cost_return_bps": realized,
        "classification": classification,
        "false_negative": classification == "false_negative",
        "false_positive": classification == "false_positive",
        "correct_no_trade": classification == "correct_no_trade",
        "correct_trade": classification == "correct_trade",
    }


def _source_payload(*, missing_lineage: bool = False) -> dict[str, object]:
    rows = [
        _row("fn_1", classification="false_negative", realized=24.0, symbol="BTCUSDT"),
        _row("fn_2", classification="false_negative", realized=14.0, symbol="ETHUSDT", coverage=42.0, missing=41),
        _row("cnt_1", classification="correct_no_trade", realized=-9.0, symbol="SOLUSDT", coverage=75.0, missing=0),
        _row("fp_1", classification="false_positive", realized=-18.0, symbol="XRPUSDT", coverage=80.0, missing=0),
    ]
    if missing_lineage:
        rows[0]["risk_decision_id"] = None
    return {
        "go_no_go": "V2_NATIVE_CUDA_TRAINER_EDGE_CALIBRATION_AND_OUTCOME_BURN_IN_READY",
        "generated_est": "2026-06-04T17:25:23-04:00",
        "live_readiness": {"live_gate": LIVE_GATE_BLOCKED, "live_symbols": [], "execution_live_symbols": []},
        "outcome_mining": {
            "outcome_sample_count": len(rows),
            "classification_counts": {"false_negative": 2, "correct_no_trade": 1, "false_positive": 1},
            "rows": rows,
        },
        "edge_recompute": {
            "new_cuda_trainer": {
                "sample_count": len(rows),
                "after_cost_expectancy_bps": 2.75,
                "after_cost_ci_lower_bps": -15.0,
            },
            "false_positive_count": 1,
            "false_negative_count": 2,
            "drawdown": {"max_drawdown_bps": 12.0, "observations": len(rows)},
            "recommendations": [
                "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
                "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
                "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
            ],
        },
    }


def _paths(tmp_path: Path) -> FalseNegativeActionabilityPaths:
    return FalseNegativeActionabilityPaths(
        repo_root=tmp_path,
        worklog_dir=tmp_path / "claude_worklog/final_readiness/v2_cuda_trainer_false_negative_reduction_and_actionability/latest",
        public_dir=tmp_path / "v2/frontend/public/v2_cuda_trainer_false_negative_reduction_and_actionability/latest",
        source_payload_path=tmp_path / "source.json",
    )


def test_false_negative_actionability_builds_required_ready_artifacts(tmp_path: Path) -> None:
    result = build_false_negative_actionability(_source_payload(), generated_est="2026-06-04T18:00:00-04:00")
    written = write_false_negative_actionability_artifacts(paths=_paths(tmp_path), result=result)

    assert written.go_no_go == GO_READY
    required = {
        "GO_NO_GO.md",
        "V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_REPORT.md",
        "v2_cuda_false_negative_attribution_status.json",
        "v2_cuda_threshold_actionability_simulation.json",
        "v2_cuda_strategy_assisted_recovery_status.json",
        "v2_cuda_paper_actionability_overlay_status.json",
        "v2_cuda_edge_after_actionability_overlay_status.json",
        "operator_dashboard_payload.json",
    }
    public_dir = tmp_path / "v2/frontend/public/v2_cuda_trainer_false_negative_reduction_and_actionability/latest"
    assert required == {path.name for path in public_dir.iterdir()}
    assert (public_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip() == GO_READY

    payload = json.loads((public_dir / "operator_dashboard_payload.json").read_text(encoding="utf-8"))
    attribution = payload["false_negative_attribution"]
    simulation = payload["threshold_actionability_simulation"]
    overlay = payload["paper_actionability_overlay"]
    edge = payload["edge_after_actionability_overlay"]

    assert attribution["false_negative_count"] == 2
    assert attribution["lineage_complete"] is True
    assert attribution["root_cause_counts"]["RISK_GATE_BLOCKED"] == 2
    assert attribution["root_cause_counts"]["TRAINER_ACTION_TOO_CONSERVATIVE"] == 2
    assert all(row["risk_decision"]["risk_decision_id"] for row in attribution["rows"])
    assert simulation["paper_only"] is True
    assert simulation["runtime_thresholds_changed"] is False
    assert simulation["thresholds_auto_accepted"] is False
    assert len(simulation["simulations"]) == 7
    assert overlay["overlay_source"] == "paper_shadow_actionability_experiment"
    assert overlay["risk_bypass"] is False
    assert overlay["risk_fail_closed_preserved"] is True
    assert overlay["live_symbols"] == []
    assert edge["edge_proven"] is False
    assert edge["primary_recommendation"] == "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"
    assert payload["live_readiness"]["live_ready"] is False
    assert payload["live_readiness"]["canary_ready"] is False
    assert payload["live_readiness"]["live_symbols"] == []
    assert payload["live_readiness"]["execution_live_symbols"] == []

    rendered = json.dumps(payload, sort_keys=True)
    assert "LIVE_READY" not in rendered
    assert "CANARY_READY" not in rendered
    assert len(written.paths_written) == 2 * len(required)


def test_false_negative_actionability_blocks_when_lineage_missing() -> None:
    result = build_false_negative_actionability(
        _source_payload(missing_lineage=True),
        generated_est="2026-06-04T18:00:00-04:00",
    )

    assert result.go_no_go == GO_BLOCKED
    attribution = result.artifacts["v2_cuda_false_negative_attribution_status.json"]
    assert attribution["status"] == "FALSE_NEGATIVE_ATTRIBUTION_BLOCKED"
    assert attribution["lineage_complete"] is False
    assert result.operator_dashboard_payload["live_switch"]["enabled"] is False


def test_false_negative_actionability_cli_writes_outputs(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source.json"
    source.write_text(json.dumps(_source_payload()), encoding="utf-8")

    code = main(["--repo-root", str(tmp_path), "--source-payload", str(source)])

    assert code == 0
    stdout = json.loads(capsys.readouterr().out)
    assert stdout["go_no_go"] == GO_READY
    assert stdout["live_gate"] == LIVE_GATE_BLOCKED
    assert stdout["live_symbols"] == []
    assert stdout["execution_live_symbols"] == []
    assert stdout["risk_bypass"] is False
    assert stdout["thresholds_auto_accepted"] is False
    public_dir = tmp_path / "v2/frontend/public/v2_cuda_trainer_false_negative_reduction_and_actionability/latest"
    assert (public_dir / "operator_dashboard_payload.json").exists()
