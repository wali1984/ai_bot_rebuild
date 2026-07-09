from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from v2.backend.app.cli.v2_a_plus_candidate_inventory import build_inventory


class FakeRedis:
    def __init__(self) -> None:
        self.data = {
            "v2:paper:preemptive_edge_control_status": {
                "candidate_count": 2,
                "accepted_count": 1,
            },
            "v2:live_gate:state": {"live_gate": "blocked_human_only"},
            "v2:paper:preemptive_candidate_decision_matrix": {
                "generated_utc": "2026-07-08T21:00:00Z",
                "candidate_count": 2,
                "rows": [
                    {
                        "candidate_id": "cand-good",
                        "symbol": "BTCUSDT",
                        "timeframe": "1m",
                        "side": "long",
                        "strategy_id": "trend",
                        "prediction_id": "pred-good",
                        "signal_id": "sig-good",
                        "preemptive_decision_id": "pec-good",
                        "preemptive_decision": "ALLOW",
                        "preemptive_action": "ALLOW_A_PLUS_CANDIDATE",
                        "pre_trade_loss_probability": 0.20,
                        "current_price": 65000.0,
                        "expected_move_after_cost_bps": 12.0,
                        "expected_net_pnl_usd": 3.5,
                        "expected_max_loss_usd": 1.2,
                        "expected_liquidation_buffer_usd": 25.0,
                        "risk_decision": "PASS",
                        "orchestrator_decision": "PASS",
                        "allocator_decision": "ALLOW_WITH_SIZE",
                        "microstructure_trust_state": "TRUSTED",
                        "live_dry_run_packet_complete": True,
                    },
                    {
                        "candidate_id": "cand-blocked",
                        "symbol": "ETHUSDT",
                        "timeframe": "5m",
                        "side": "short",
                        "strategy_id": "trend",
                        "prediction_id": "pred-blocked",
                        "signal_id": "sig-blocked",
                        "preemptive_decision_id": "pec-blocked",
                        "preemptive_decision": "NO_TRADE",
                        "preemptive_action": "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
                        "pre_trade_loss_probability": 0.91,
                        "current_price": 3200.0,
                        "expected_move_after_cost_bps": -1.0,
                        "expected_net_pnl_usd": 0.0,
                        "preemptive_block_reasons": ["EXPECTED_EDGE_NON_POSITIVE"],
                    },
                ],
            },
            "v2:prediction:BTCUSDT:1m": _prediction("BTCUSDT", "1m", "pred-good", "hash-good"),
            "v2:prediction:ETHUSDT:5m": _prediction("ETHUSDT", "5m", "pred-blocked", "hash-blocked"),
        }

    def get(self, key: str):
        value = self.data.get(key)
        return json.dumps(value) if value is not None else None

    def scan_iter(self, match: str, count: int = 500):
        del count
        for key in sorted(self.data):
            if fnmatch.fnmatch(key, match):
                yield key


def _prediction(symbol: str, timeframe: str, prediction_id: str, feature_hash: str) -> dict[str, object]:
    feature_names = [
        "funding_rate",
        "open_interest",
        "long_short_ratio",
        "ta_RSI",
        "orderbook_depth_usd",
        "trade_tape_confirmation_score",
        "bullish_fvg_present",
        "nearest_liquidity_above",
    ]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "prediction_id": prediction_id,
        "signal_id": f"sig-{prediction_id}",
        "feature_vector_hash": feature_hash,
        "feature_cutoff": "2026-07-08T20:59:00Z",
        "available_at": "2026-07-08T20:59:01Z",
        "decision_time": "2026-07-08T21:00:00Z",
        "current_price": 50000.0,
        "expected_move_after_cost_bps": 8.0,
        "confidence_raw": 0.84,
        "confidence_calibrated": 0.8,
        "feature_names": feature_names,
        "source_labels": [
            "v2:features:ta",
            "v2:market:orderbook",
            "v2:market:liquidation_levels",
            "v2:market:fvg",
        ],
        "entry_feature_snapshot": {
            "feature_cutoff": "2026-07-08T20:59:00Z",
            "available_at": "2026-07-08T20:59:01Z",
            "features": {name: 1.0 for name in feature_names},
        },
    }


def test_inventory_writes_required_outputs_and_classifies_blockers(tmp_path: Path) -> None:
    result = build_inventory(client=FakeRedis(), output_dir=tmp_path, max_prediction_keys=20)

    assert result["summary"]["total_candidate_count"] == 2
    assert result["summary"]["a_plus_candidate_count"] == 1
    assert result["summary"]["live_ready_candidate_count"] == 1
    assert result["rejection_matrix"]["unknown_rejection_reason_count"] == 0
    assert result["rejection_matrix"]["blocker_class_counts"]["EXPECTED_NET_EDGE_BLOCKER"] >= 1
    assert (tmp_path / "candidate_inventory.jsonl").exists()
    assert (tmp_path / "candidate_inventory_summary.json").exists()
    assert (tmp_path / "candidate_rejection_matrix.json").exists()
    assert (tmp_path / "a_plus_candidate_rows.jsonl").exists()
    assert (tmp_path / "near_a_plus_candidate_rows.jsonl").exists()

    good = result["a_plus_rows"][0]
    assert good["preemptive_decision_id"] == "pec-good"
    assert good["feature_vector_hash"] == "hash-good"
    assert good["allocator_decision_id"].startswith("allocsim_")
    assert good["allocator_decision"] == "PASS"
    assert good["recommended_leverage_source"] == "adaptive_simulation"
    assert good["recommended_margin_mode_source"] == "adaptive_simulation"
    assert good["current_price"] == 65000.0
    assert good["price_missing_reason"] is None
    assert good["expected_move"] == 12.0
    assert good["expected_gross_pnl_usd"] == 3.5
    assert good["expected_cost_usd"] == 0.0
    assert good["confidence_raw"] == 0.84
    assert good["confidence_calibrated"] == 0.8
    assert good["max_loss_usd"] == 1.2
    assert good["liquidation_buffer_usd"] == 25.0
    assert good["counts_as_probation"] is False
    assert good["counts_as_reconstructed"] is False

    blocked = next(row for row in result["rows"] if row["candidate_id"] == "cand-blocked")
    assert blocked["allocator_decision_id"].startswith("allocsim_")
    assert blocked["allocator_decision"] == "REJECT"
    assert "ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE" in blocked["allocator_block_reasons"]
    assert result["summary"]["allocator_decision_missing_count"] == 0
