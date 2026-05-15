from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import legacy_v2_decision_comparator as worker


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_decision_comparator_marks_missing_edge_as_v2_block(tmp_path: Path) -> None:
    legacy = _write(
        tmp_path / "legacy.json",
        {
            "latest_prediction_id": "legacy_pred_1",
            "latest_symbol": "BTCUSDT",
            "latest_timeframe": "1m",
            "latest_confidence": 0.82,
            "latest_signal_reason": "legacy_signal_present",
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        },
    )
    paper = _write(
        tmp_path / "paper.json",
        {
            "trainer_prediction": {
                "prediction_id": "v2_pred_1",
                "symbol": "BTCUSDT",
                "confidence_calibrated": 0.8,
                "source_type": "V2_PAPER_TRAINER_WRAPPER",
            },
            "feature_snapshot": {
                "feature_snapshot_id": "fs_1",
                "freshness_state": "CURRENT",
            },
            "current_risk_decision": {
                "risk_action": "deny",
                "risk_reason_code": "deny_canary_profile_tightening",
                "canary_profile_tightening": {
                    "blockers": ["missing_expected_move_after_costs"],
                    "expected_move_bps": None,
                    "estimated_cost_bps": 6.0,
                },
            },
        },
    )
    trainer = _write(tmp_path / "trainer.json", {"prediction_id": "v2_pred_1"})
    symbol = _write(tmp_path / "symbol.json", {"paper_symbols": ["BTCUSDT"], "live_symbols": []})
    risk = _write(tmp_path / "risk.json", {"risk_action": "deny", "risk_reason_code": "deny_canary_profile_tightening"})
    paper_exec = _write(tmp_path / "paper_exec.json", {"paper_filter_estimated_cost_bps": 6.0})

    status = worker.run_once(
        worker.parse_args(
            [
                "--once",
                "--legacy-status-file",
                str(legacy),
                "--paper-status-file",
                str(paper),
                "--trainer-status-file",
                str(trainer),
                "--symbol-status-file",
                str(symbol),
                "--risk-status-file",
                str(risk),
                "--paper-exec-status-file",
                str(paper_exec),
            ]
        )
    )

    latest = status["latest_comparison"]
    assert latest["comparator_result"] == "LEGACY_ALLOW_V2_BLOCK"
    assert "expected_edge_missing" in latest["disagreement_reasons"]
    assert latest["expected_move_after_cost_bps"] is None
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
