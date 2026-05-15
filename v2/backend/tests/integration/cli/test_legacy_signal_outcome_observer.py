from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import legacy_signal_outcome_observer as worker


def test_signal_outcome_observer_keeps_after_cost_pending_without_future_data(tmp_path: Path) -> None:
    comparator = tmp_path / "comparator.json"
    comparator.write_text(
        json.dumps(
            {
                "latest_comparison": {
                    "comparison_id": "cmp_1",
                    "legacy_prediction_id": "legacy_pred_1",
                    "v2_prediction_id": "v2_pred_1",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "expected_move_after_cost_bps": None,
                    "v2_block_reason": ["missing_expected_move_after_costs"],
                }
            }
        )
    )
    paper = tmp_path / "paper.json"
    paper.write_text(json.dumps({"market_feed": {"last_price": 100.0}}))

    status = worker.run_once(
        worker.parse_args(
            [
                "--once",
                "--comparator-status-file",
                str(comparator),
                "--paper-status-file",
                str(paper),
            ]
        )
    )

    observation = status["latest_observation"]
    assert observation["after_cost_correct"] == "MISSING_EVIDENCE"
    assert observation["no_trade_correct"] == "PENDING_OUTCOME_OR_EDGE_MISSING"
    assert status["outcome_status"] == "OUTCOME_PENDING_SOURCE_LIMITED"
    assert status["exchange_action_taken"] is False
