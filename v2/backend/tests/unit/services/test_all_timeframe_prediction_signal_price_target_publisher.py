from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services import all_timeframe_prediction_signal_price_target_publisher as publisher


class FakeRedis:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = {
            key: json.dumps(value)
            for key, value in payloads.items()
        }

    def get(self, key: str) -> str | None:
        return self.payloads.get(key)


def test_runtime_paper_signal_row_missing_thesis_timeframe_is_shadow_blocked() -> None:
    store = publisher.V2KeyValueStore(
        FakeRedis(
            {
                "v2:signals:paper": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "long",
                        "prediction_id": "pred_missing_tf",
                        "confidence_calibrated": 0.8,
                        "expected_move_bps": 20.0,
                        "expected_move_after_cost_bps": 15.0,
                        "paper_fill_allowed": True,
                        "paper_fill_gate_block_reasons": [],
                    }
                ],
                "v2:risk:gateway:decisions": [
                    {
                        "prediction_id": "pred_missing_tf",
                        "risk_decision_id": "risk_missing_tf",
                        "orchestrator_decision_id": "orch_missing_tf",
                    }
                ],
                "v2:paper:intents": [
                    {
                        "intent_id": "intent_missing_tf",
                        "prediction_id": "pred_missing_tf",
                        "symbol": "BTCUSDT",
                        "paper_fill_allowed": True,
                    }
                ],
                "v2:paper:ledger": {
                    "generated_at": "2026-06-22T13:00:00Z",
                    "accepted": [],
                    "shadow_observations": [],
                },
                "v2:orchestrator:decisions": {"generated_at": "2026-06-22T13:00:00Z"},
                "v2:market:prices:BTCUSDT": {"last_price": 100.0},
            }
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["timeframe"] == publisher.UNKNOWN_THESIS_TIMEFRAME
    assert row["thesis_timeframe"] == publisher.UNKNOWN_THESIS_TIMEFRAME
    assert row["timeframe_attribution_status"] == "MISSING_THESIS_TIMEFRAME"
    assert row["paper_fill_allowed"] is False
    assert row["blocked_reason"] == publisher.MISSING_THESIS_TIMEFRAME_BLOCK_REASON
    assert publisher.MISSING_THESIS_TIMEFRAME_BLOCK_REASON in row["paper_fill_gate_block_reasons"]


def test_runtime_paper_signal_row_marks_hold_zeroed_after_cost_edge() -> None:
    store = publisher.V2KeyValueStore(
        FakeRedis(
            {
                "v2:signals:paper": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "1m",
                        "side": "hold",
                        "prediction_id": "pred_hold_zeroed",
                        "confidence_calibrated": 0.8,
                        "expected_move_bps": -20.0,
                        "expected_move_after_cost_bps": 0.0,
                        "paper_fill_allowed": False,
                        "paper_fill_gate_block_reasons": [
                            "NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION"
                        ],
                    }
                ],
                "v2:risk:gateway:decisions": [
                    {
                        "prediction_id": "pred_hold_zeroed",
                        "risk_decision_id": "risk_hold_zeroed",
                        "orchestrator_decision_id": "orch_hold_zeroed",
                    }
                ],
                "v2:paper:intents": [],
                "v2:paper:ledger": {
                    "generated_at": "2026-06-22T13:00:00Z",
                    "accepted": [],
                    "shadow_observations": [],
                },
                "v2:orchestrator:decisions": {"generated_at": "2026-06-22T13:00:00Z"},
                "v2:market:prices:BTCUSDT": {"last_price": 100.0},
            }
        )
    )

    rows = publisher.build_runtime_paper_signal_rows(store)

    assert len(rows) == 1
    row = rows[0]
    assert row["paper_fill_allowed"] is False
    assert row["selected_action_expected_move_bps_sign"] == "negative"
    assert row["hold_action_with_directional_expected_move_bps"] is True
    assert row["hold_action_directional_expected_move_bps"] == -20.0
    assert row["expected_move_after_cost_zeroed_by_hold_action"] is True
    assert (
        row["paper_non_actionable_diagnostic_reason"]
        == "HOLD_ACTION_WITH_DIRECTIONAL_EXPECTED_MOVE_ZERO_AFTER_COST_EDGE"
    )
