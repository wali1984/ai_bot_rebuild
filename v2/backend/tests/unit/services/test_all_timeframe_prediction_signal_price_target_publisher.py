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
        self.lists: dict[str, list[str]] = {}

    def get(self, key: str) -> str | None:
        return self.payloads.get(key)

    def set(self, key: str, value: str) -> None:
        self.payloads[key] = value

    def rpush(self, key: str, value: str) -> None:
        self.lists.setdefault(key, []).append(value)


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
                        "actual_observed_spread_entry_bps": 1.0,
                        "expected_slippage_bps": 1.0,
                        "fee_bps": 2.0,
                        "expected_funding_bps": 0.5,
                        "target_notional_usd": 100.0,
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
    assert row["expected_long_net_edge_bps"] == -24.5
    assert row["expected_short_net_edge_bps"] == 15.5
    assert row["expected_long_net_pnl_usd"] == -0.245
    assert row["expected_short_net_pnl_usd"] == 0.155
    assert row["long_expected_gross_pnl_usd"] == -0.2
    assert row["long_expected_cost_usd"] == 0.045
    assert row["long_expected_net_pnl_usd"] == -0.245
    assert row["short_expected_gross_pnl_usd"] == 0.2
    assert row["short_expected_cost_usd"] == 0.045
    assert row["short_expected_net_pnl_usd"] == 0.155
    assert row["best_side"] == "short"
    assert row["best_side_expected_net_pnl_usd"] == 0.155
    assert row["selected_action"] == "hold"
    assert row["hold_no_trade_reason"] == "MODEL_SELECTED_HOLD_DESPITE_DIRECTIONAL_EXPECTED_MOVE"
    assert row["why_best_side_rejected"] == "selected_hold_best_side_short_net_edge_15.500000bps"
    assert (
        row["paper_non_actionable_diagnostic_reason"]
        == "HOLD_ACTION_WITH_DIRECTIONAL_EXPECTED_MOVE_ZERO_AFTER_COST_EDGE"
    )


def test_publish_v2_keys_appends_guardian_pit_observation_without_live_mutation() -> None:
    redis = FakeRedis({})
    store = publisher.V2KeyValueStore(redis)
    prediction_row = {
        "prediction_id": "pred-pit-1",
        "prediction_redis_key": "v2:prediction:BTCUSDT:1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "status": "PRESENT_CURRENT",
        "selected_action": "long",
        "decision_time": "2026-07-09T20:40:00Z",
        "feature_cutoff": "2026-07-09T20:39:59Z",
        "available_at": "2026-07-09T20:39:58Z",
        "generated_est": "2026-07-09T16:40:00-04:00",
        "feature_vector_hash": "hash-pit-1",
        "prediction_temporal_block_reasons": [],
    }

    audit = publisher.publish_v2_keys(
        store,
        {"prediction_rows": [prediction_row], "stale_threshold_seconds": 900},
        {"published_signals": []},
    )

    rows = redis.lists[publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY]
    assert audit["guardian_pit_observation_appends"] == 1
    assert audit["guardian_pit_observation_list_key"] == publisher.GUARDIAN_PIT_OBSERVATION_LIST_KEY
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["schema_version"] == "v2_guardian_pit_prediction_observation_append_v1"
    assert payload["prediction_id"] == "pred-pit-1"
    assert payload["decision_time"] == "2026-07-09T20:40:00Z"
    assert payload["feature_cutoff"] == "2026-07-09T20:39:59Z"
    assert payload["available_at"] == "2026-07-09T20:39:58Z"
    assert payload["counts_as_a_grade_evidence"] is False
    assert payload["counts_as_a_plus"] is False
    assert payload["places_real_order"] is False
    assert payload["routes_to_live"] is False
    assert payload["test_order_submitted"] is False
