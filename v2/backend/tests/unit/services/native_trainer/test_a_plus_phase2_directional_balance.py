from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.a_plus_phase2_directional_balance import (
    FEEDBACK_KEY,
    GOAL_ID,
    TRAINER_METRICS_KEY,
    build_a_plus_phase2_directional_balance_artifacts,
    write_a_plus_phase2_directional_balance_artifacts,
)


class FakeRedis:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads

    def get(self, key: str) -> str | None:
        value = self.payloads.get(key)
        if value is None:
            return None
        return json.dumps(value)

    def scan_iter(self, match: str | None = None, count: int | None = None):
        del count
        prefix = str(match or "").replace("*", "")
        for key in sorted(self.payloads):
            if key.startswith(prefix):
                yield key


def _row(side: str, pnl_bps: float, *, confidence: float = 0.70) -> dict[str, Any]:
    return {
        "paper_session_id": "paper_session_1",
        "trainer_consumable": True,
        "side": side,
        "action": side.lower(),
        "selected_action": side.lower(),
        "realized_net_pnl_bps": pnl_bps,
        "realized_pnl_usd": pnl_bps / 100.0,
        "confidence_calibrated": confidence,
        "trainer_feedback_id": f"fb_{side}_{pnl_bps}",
    }


def _metrics(*, class_weighted: bool = True) -> dict[str, Any]:
    weights = [1.0, 1.6, 0.5, 0.25, 0.25, 0.25, 0.25] if class_weighted else [1.0] * 7
    return {
        "checkpoint": {"checkpoint_id": "ckpt_current"},
        "training": {
            "action_distribution": {"0": 2, "1": 12, "2": 24, "3": 0, "4": 0, "5": 0, "6": 0},
            "metrics": {
                "action_class_weights": weights,
                "policy_bias_class_balance_nudge": [1.0, -0.25, -0.75, 0.0, 0.0, 0.0, 0.0],
                "policy_bias_nudge_strategy": "present_label_class_balance_no_majority_reinforcement",
                "target_long_fraction": 0.315789,
                "target_short_fraction": 0.631579,
                "long_label_present": True,
                "short_label_present": True,
                "single_direction_expected_move_guard_active": False,
                "single_direction_policy_action_guard_active": False,
            },
        },
    }


def _payloads(*, class_weighted: bool = True) -> dict[str, Any]:
    return {
        FEEDBACK_KEY: [
            _row("LONG", 20.0),
            _row("LONG", -4.0),
            _row("SHORT", 30.0),
            _row("SHORT", -5.0),
        ],
        TRAINER_METRICS_KEY: _metrics(class_weighted=class_weighted),
        "v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:1h": {
            "checkpoint_id": "ckpt_current",
            "selected_action": "long",
        },
        "v2:trainer:hybrid_cuda:signals:paper:ETHUSDT:1h": {
            "checkpoint_id": "ckpt_current",
            "selected_action": "short",
        },
    }


def test_phase2_directional_balance_artifacts_ready_with_side_gates() -> None:
    artifacts = build_a_plus_phase2_directional_balance_artifacts(
        redis_client=FakeRedis(_payloads()),
        generated_utc="2026-07-06T12:00:00Z",
    )

    directional = artifacts["directional_balance_repair_status.json"]
    calibration = artifacts["long_short_calibration_status.json"]
    side_bucket = artifacts["side_bucket_performance_status.json"]

    assert directional["status"] == "DIRECTIONAL_BALANCE_REPAIR_READY"
    assert directional["pass_conditions"]["class_weighted_loss_active"] is True
    assert directional["pass_conditions"]["signal_long_and_short_present"] is True
    assert directional["pass_conditions"]["no_side_trades_with_non_positive_expectancy"] is True
    assert directional["current_signal_distribution"]["current_checkpoint"] == {"LONG": 1, "SHORT": 1}
    assert directional["behavioral_proof_negative_expectancy_block"]["allowed"] is False
    assert any(
        "SIDE_BUCKET_EXPECTANCY_NON_POSITIVE" in reason
        for reason in directional["behavioral_proof_negative_expectancy_block"]["reasons"]
    )
    assert calibration["status"] == "LONG_SHORT_CALIBRATION_READY"
    assert set(calibration["confidence_floors"]) == {"LONG", "SHORT"}
    assert side_bucket["status"] == "SIDE_BUCKET_GATE_READY"
    assert side_bucket["side_gate_evaluations"]["LONG"]["allowed"] is True
    assert side_bucket["side_gate_evaluations"]["SHORT"]["allowed"] is True


def test_phase2_directional_balance_blocks_when_class_weight_evidence_missing(tmp_path: Path) -> None:
    status = write_a_plus_phase2_directional_balance_artifacts(
        redis_client=FakeRedis(_payloads(class_weighted=False)),
        repo_root=tmp_path,
        goal_dir=tmp_path / "goal_state" / GOAL_ID,
        public_dir=tmp_path / "public" / "latest",
        generated_utc="2026-07-06T12:00:00Z",
    )

    assert status["status"] == "BLOCKED_DIRECTIONAL_BALANCE_EVIDENCE_INCOMPLETE"
    assert status["places_real_order"] is False
    assert status["exchange_leverage_mutated"] is False
    assert "class_weighted_loss_active" in status["missing_evidence"]
    payload = json.loads(
        (tmp_path / "goal_state" / GOAL_ID / "directional_balance_repair_status.json").read_text()
    )
    assert payload["class_weighted_loss"]["active"] is False
    assert (tmp_path / "public" / "latest" / "side_bucket_performance_status.json").exists()
