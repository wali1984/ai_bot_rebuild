from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import paper_shadow_outcome_observer as worker


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload))
    return path


def test_shadow_observer_marks_no_trade_correct_when_blocked_intent_fails_costs(
    tmp_path: Path,
) -> None:
    requests = _write_json(
        tmp_path / "requests.json",
        [
            {
                "event_id": "evt_1",
                "intent_id": "intent_1",
                "risk_decision_id": "risk_1",
                "prediction_id": "pred_1",
                "feature_snapshot_id": "fs_1",
                "symbol": "BTCUSDT",
                "side": "long",
                "entry_reference_price": 100.0,
                "event_ts": "2026-01-01T00:00:00Z",
                "expected_move_after_cost_bps": 8.0,
                "fee_bps": 4.0,
                "spread_bps": 0.0,
                "slippage_bps": 2.0,
                "funding_risk_bps": 0.0,
                "block_reason": "EDGE_AFTER_COSTS_MISSING_BLOCK",
            }
        ],
    )
    prices = _write_json(
        tmp_path / "prices.json",
        [
            {
                "symbol": "BTCUSDT",
                "time": "2026-01-01T00:05:00Z",
                "high": 100.03,
                "low": 99.99,
                "close": 100.02,
            },
            {
                "symbol": "BTCUSDT",
                "time": "2026-01-01T00:30:00Z",
                "high": 100.04,
                "low": 99.98,
                "close": 100.01,
            },
            {
                "symbol": "BTCUSDT",
                "time": "2026-01-01T01:00:00Z",
                "high": 100.05,
                "low": 99.97,
                "close": 100.0,
            },
        ],
    )

    status = worker.run_once(
        worker.parse_args(
            [
                "--once",
                "--requests-file",
                str(requests),
                "--price-samples-file",
                str(prices),
            ]
        )
    )

    assert status["outcome_status"] == "NO_TRADE_DECISIONS_CORRECT_SO_FAR"
    assert status["no_trade_correct_count"] == 1
    assert status["false_block_count"] == 0
    assert status["allowed_paper_fill_count"] == 0
    assert status["exchange_action_taken"] is False
    assert status["old_redis_write_performed"] is False
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []


def test_shadow_observer_flags_false_block_when_blocked_intent_beats_costs(
    tmp_path: Path,
) -> None:
    requests = _write_json(
        tmp_path / "requests.json",
        [
            {
                "event_id": "evt_2",
                "intent_id": "intent_2",
                "risk_decision_id": "risk_2",
                "symbol": "BTCUSDT",
                "side": "short",
                "entry_reference_price": 100.0,
                "event_ts": "2026-01-01T00:00:00Z",
                "cost_bps": 6.0,
                "block_reason": "CONFIDENCE_TOO_LOW_BLOCK",
            }
        ],
    )
    prices = _write_json(
        tmp_path / "prices.json",
        [
            {
                "symbol": "BTCUSDT",
                "time": "2026-01-01T00:15:00Z",
                "high": 100.1,
                "low": 98.8,
                "close": 99.0,
            }
        ],
    )

    status = worker.run_once(
        worker.parse_args(
            [
                "--once",
                "--requests-file",
                str(requests),
                "--price-samples-file",
                str(prices),
            ]
        )
    )

    assert status["outcome_status"] == "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED"
    assert status["false_block_count"] == 1
    assert status["no_trade_correct_count"] == 0
    assert status["latest_observation"]["would_have_beaten_costs"] is True
    assert status["false_block_reason_counts"] == {"CONFIDENCE_TOO_LOW_BLOCK": 1}
    assert status["recommended_next_action"] == "EXPECTED_MOVE_MODEL_REVIEW_REQUIRED_KEEP_FILL_GATE_STRICT"


def test_shadow_observer_keeps_insufficient_sample_without_future_prices(
    tmp_path: Path,
) -> None:
    requests = _write_json(
        tmp_path / "requests.json",
        [
            {
                "event_id": "evt_3",
                "intent_id": "intent_3",
                "risk_decision_id": "risk_3",
                "symbol": "BTCUSDT",
                "side": "long",
                "entry_reference_price": 100.0,
                "event_ts": "2026-01-01T00:00:00Z",
                "cost_bps": 6.0,
                "block_reason": "EDGE_AFTER_COSTS_MISSING_BLOCK",
            }
        ],
    )

    status = worker.run_once(
        worker.parse_args(["--once", "--requests-file", str(requests)])
    )

    assert status["outcome_status"] == "EDGE_PENDING_INSUFFICIENT_SAMPLE"
    assert status["pending_observations"] == 1
    assert status["completed_observations"] == 0
    assert status["approves_live"] is False
    assert status["approves_legacy_shutdown"] is False
    assert status["recommended_next_action"] == "CONTINUE_SHADOW_OUTCOME_OBSERVATION"


def test_shadow_observer_captures_native_trainer_expected_move_from_paper_runtime(
    tmp_path: Path,
) -> None:
    paper_status = _write_json(
        tmp_path / "paper_status.json",
        {
            "current_risk_decision": {
                "risk_action": "deny",
                "risk_decision_id": "risk_4",
                "prediction_id": "pred_4",
                "feature_snapshot_id": "fs_4",
                "generated_at": "2026-01-01T00:00:00Z",
                "risk_reason_code": "deny_low_confidence",
            },
            "current_signal_lineage": {
                "execution_intent": {
                    "execution_intent_id": "intent_4",
                    "symbol": "BTCUSDT",
                    "side": "long",
                },
                "signal": {"symbol": "BTCUSDT", "side": "long"},
                "trainer_prediction": {
                    "prediction_id": "pred_4",
                    "feature_snapshot_id": "fs_4",
                    "expected_move_bridge_status": "NATIVE_EXPECTED_MOVE_PRESENT",
                    "raw_output": {
                        "side": "long",
                        "expected_move_bps": 20.0,
                    },
                },
            },
            "market_feed": {"last_price": 100.0},
            "last_paper_event": {
                "tick_id": "evt_4",
                "observed_price": 100.0,
                "generated_at": "2026-01-01T00:00:00Z",
                "paper_reason": "deny_low_confidence",
                "slippage_bps": 2.0,
            },
        },
    )
    empty_status = _write_json(tmp_path / "empty_status.json", {})

    status = worker.run_once(
        worker.parse_args(
            [
                "--once",
                "--worker-status-file",
                str(empty_status),
                "--paper-status-file",
                str(paper_status),
            ]
        )
    )

    latest = status["latest_observation"]
    assert latest["expected_move_bps"] == 20.0
    assert latest["expected_move_after_cost_bps"] == 14.0
    assert latest["cost_bps"] == 6.0
    assert latest["paper_fill_recorded"] is False
    assert status["exchange_action_taken"] is False
    assert status["old_redis_write_performed"] is False


def test_shadow_observer_rechecks_prior_pending_observations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prior_status = _write_json(
        tmp_path / "prior_status.json",
        {
            "observations": [
                {
                    "observation_id": "shadow_prior",
                    "event_id": "evt_prior",
                    "intent_id": "intent_prior",
                    "risk_decision_id": "risk_prior",
                    "symbol": "BTCUSDT",
                    "side": "long",
                    "entry_reference_price": 100.0,
                    "event_ts": "2026-01-01T00:00:00Z",
                    "cost_bps": 6.0,
                    "block_reason": "EDGE_AFTER_COSTS_MISSING_BLOCK",
                }
            ]
        },
    )
    prices = _write_json(
        tmp_path / "prices.json",
        [
            {
                "symbol": "BTCUSDT",
                "time": "2026-01-01T01:00:00Z",
                "high": 100.01,
                "low": 99.95,
                "close": 100.0,
            }
        ],
    )
    empty_status = _write_json(tmp_path / "empty_status.json", {})
    monkeypatch.setattr(worker, "PRIOR_STATUS_CANDIDATES", [prior_status])

    status = worker.run_once(
        worker.parse_args(
            [
                "--once",
                "--worker-status-file",
                str(empty_status),
                "--paper-status-file",
                str(empty_status),
                "--price-samples-file",
                str(prices),
            ]
        )
    )

    assert status["observations_total"] == 1
    assert status["completed_observations"] == 1
    assert status["outcome_status"] == "NO_TRADE_DECISIONS_CORRECT_SO_FAR"
    assert status["no_trade_correct_count"] == 1
    assert status["false_block_count"] == 0
