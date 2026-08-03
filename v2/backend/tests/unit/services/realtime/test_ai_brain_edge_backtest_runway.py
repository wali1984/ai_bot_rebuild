"""ai_brain realtime snapshot folds edge / backtest / A-grade-runway blocks.

These blocks ride the existing ai_brain WebSocket resource so every field updates
in realtime with no refresh/loading gap. Read-only; backtest is never A+ evidence.
"""
from __future__ import annotations

import json

from app.services.realtime.operator_snapshot import _ai_brain_edge_backtest_runway


class _FakeRedis:
    def __init__(self, data: dict[str, str]) -> None:
        self._d = data

    def get(self, key: str):
        return self._d.get(key)


def _fake() -> _FakeRedis:
    trainer = {
        "cuda_cpu_resource_utilization": {
            "policy_backtest": {
                "win_rate": 0.99,
                "profit_factor_proxy": 201.0,
                "expectancy_after_cost_bps": 36.0,
                "rows_evaluated": 16384,
                "evidence_class": "BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE",
            }
        },
        "learning_metrics": {
            "ppo_entropy": 0.54,
            "validation_supervised_loss": 0.79,
            "loss_after": 0.18,
            "train_val_generalization_gap": 0.61,
            "overfit_gap_warning": True,
        },
        "parallel_environment_rollout": {"reward_avg_bps": 9.2, "reward_max_bps": 957.0, "reward_min_bps": -393.0},
        "trusted_replay_examples_built": 1328,
        "online_learning_status": "WEIGHTS_UPDATING",
        "last_successful_weight_update_at": "2026-07-11T21:53:38Z",
    }
    cf = {"existing_counterfactual_rows": 3198, "pending_rows": 1522}
    ef = {"status": "ACTIVE"}
    gate = {
        "status": "A_GRADE_HALTED_PERFORMANCE",
        "a_grade_new_entries_allowed": False,
        "failure_reasons": [
            {"reason": "INSUFFICIENT_REALTIME_A_GRADE_CLOSED_ECONOMIC_TRADES", "observed": 0, "required": 1000}
        ],
    }
    burn = {"A_grade_rows": 0, "near_A_grade_rows": 101, "source_rows": {"closed_rows": 31}}
    pes = {"candidate_count": 571, "accepted_count": 0, "action_counts": {"BLOCK_LOSS_PROBABILITY_TOO_HIGH": 529}}
    return _FakeRedis(
        {
            "v2:trainer:hybrid_cuda:status": json.dumps(trainer),
            "v2:trainer:feedback:counterfactual_status": json.dumps(cf),
            "v2:edge_factory:replay_status": json.dumps(ef),
            "v2:continuous_edge_guardian:a_grade_execution_gate": json.dumps(gate),
            "v2:paper:a_grade_gate_burndown_status": json.dumps(burn),
            "v2:paper:preemptive_edge_control_status": json.dumps(pes),
        }
    )


def test_ai_brain_folds_edge_backtest_and_runway() -> None:
    out = _ai_brain_edge_backtest_runway(_fake())
    assert out["edge"]["policy_entropy"] == 0.54
    assert out["edge"]["rollout_reward_avg_bps"] == 9.2
    assert out["edge"]["online_learning_status"] == "WEIGHTS_UPDATING"

    bt = out["backtest_replay"]
    assert bt["available"] is True
    assert bt["win_rate"] == 0.99
    assert bt["train_val_generalization_gap"] == 0.61
    assert bt["overfit_gap_warning"] is True
    assert bt["continuous_replay_active"] is True
    assert bt["counterfactual_rows"] == 3198
    assert bt["backtest_is_a_plus_evidence"] is False

    rw = out["a_grade_runway"]
    assert rw["gate_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert rw["A_grade_rows"] == 0
    assert rw["near_A_grade_rows"] == 101
    assert rw["closed_rows"] == 31
    assert rw["preemptive_candidate_count"] == 571
    assert rw["requirements"][0]["required"] == 1000


def test_ai_brain_edge_backtest_runway_degrades_without_data() -> None:
    out = _ai_brain_edge_backtest_runway(_FakeRedis({}))
    assert out["backtest_replay"]["available"] is False
    assert out["backtest_replay"]["backtest_is_a_plus_evidence"] is False
    assert out["edge"]["policy_entropy"] is None
    assert out["a_grade_runway"]["A_grade_rows"] is None
