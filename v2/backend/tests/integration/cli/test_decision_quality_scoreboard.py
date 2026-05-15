from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import decision_quality_scoreboard as worker


def test_decision_quality_scoreboard_does_not_claim_99_accuracy_without_sample(tmp_path: Path) -> None:
    comparator = tmp_path / "comparator.json"
    comparator.write_text(
        json.dumps(
            {
                "comparisons": [
                    {
                        "comparator_result": "LEGACY_ALLOW_V2_BLOCK",
                        "expected_move_after_cost_bps": None,
                        "feature_freshness_state": "CURRENT",
                        "disagreement_reasons": ["expected_edge_missing"],
                    }
                ]
            }
        )
    )
    outcome = tmp_path / "outcome.json"
    outcome.write_text(json.dumps({"outcome_status": "OUTCOME_PENDING_SOURCE_LIMITED"}))
    paper_loss = tmp_path / "loss.json"
    paper_loss.write_text(json.dumps({"current_cumulative_paper_pnl": -49.12, "decision": "PAPER_LOSS_ATTRIBUTION_READY_SOURCE_LIMITED"}))
    paper_exec = tmp_path / "paper_exec.json"
    paper_exec.write_text(json.dumps({"current_paper_pnl": -49.12}))

    status = worker.run_once(
        worker.parse_args(
            [
                "--once",
                "--comparator-status-file",
                str(comparator),
                "--outcome-status-file",
                str(outcome),
                "--paper-loss-status-file",
                str(paper_loss),
                "--paper-exec-status-file",
                str(paper_exec),
            ]
        )
    )

    assert status["primary_metric_status"] == "EDGE_PENDING_INSUFFICIENT_SAMPLE"
    assert status["no_99_market_accuracy_claimed"] is True
    assert status["expected_edge_coverage"] == 0.0
    assert status["paper_loss_visible"]["current_cumulative_pnl"] == -49.12
    assert status["live_gate"] == "blocked_human_only"
