import json

import pytest

from app.api.v2 import trainer


class _FakeRedis:
    def __init__(self, payloads: dict[str, object]):
        self.payloads = {
            key: value if isinstance(value, str) else json.dumps(value)
            for key, value in payloads.items()
        }

    def get(self, key: str):
        return self.payloads.get(key)


@pytest.mark.asyncio
async def test_paper_exploration_bridge_exposes_compact_guardian_row_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guardian_reasons = [
        {
            "reason": "INSUFFICIENT_REALTIME_A_GRADE_CLOSED_ECONOMIC_TRADES",
            "observed": 0,
            "required": 1000,
        }
    ]
    redis = _FakeRedis(
        {
            trainer.PAPER_EXPLORATION_BRIDGE_KEYS["supply_status"]: {
                "status": "ACTIVE",
                "live_gate": "blocked_human_only",
            },
            trainer.PAPER_EXPLORATION_BRIDGE_KEYS[
                "materialization_queue_status"
            ]: {
                "schema_version": "paper_exploration_materialization_queue_status_v1",
                "generated_utc": "2026-07-12T00:43:27.354Z",
                "queued_count": 1,
                "active_count": 1,
                "guardian_status": "A_GRADE_HALTED_PERFORMANCE",
                "guardian_new_entries_allowed": False,
                "guardian_block_reasons": guardian_reasons,
                "active_rows": [
                    {
                        "queue_id": "paper_exploration_materialize_hyp-bridge",
                        "candidate_id": "hyp-bridge",
                        "symbol": "AVAXUSDT",
                        "timeframe": "15m",
                        "side": "short",
                        "guardian_status": "A_GRADE_HALTED_PERFORMANCE",
                        "guardian_new_entries_allowed": False,
                        "guardian_block_reasons": guardian_reasons,
                        "continuous_edge_guardian_status": (
                            "A_GRADE_HALTED_PERFORMANCE"
                        ),
                        "continuous_edge_guardian_new_entries_allowed": False,
                        "continuous_edge_guardian_block_reasons": guardian_reasons,
                        "entry_feature_snapshot": {"large": "omitted"},
                        "paper_only": True,
                        "routes_to_live": False,
                        "places_real_order": False,
                        "order_submitted": False,
                        "test_order_submitted": False,
                        "leverage_mutated": False,
                        "margin_mutated": False,
                    }
                ],
                "rejected_after_queue_rows": [
                    {
                        "queue_id": "paper_exploration_materialize_hyp-rejected",
                        "symbol": "SOLUSDT",
                        "materialization_no_fill_reason": (
                            "ALL_ROWS_TRUE_PERFORMANCE_CIRCUIT_BLOCKED"
                        ),
                        "guardian_status": "A_GRADE_HALTED_PERFORMANCE",
                        "guardian_new_entries_allowed": False,
                        "paper_only": True,
                        "routes_to_live": False,
                        "places_real_order": False,
                    }
                ],
            },
            trainer.PAPER_EXPLORATION_BRIDGE_KEYS["materialization_status"]: {
                "status": "ACTIVE"
            },
            trainer.PAPER_EXPLORATION_COUNTERFACTUAL_KEY: [],
        }
    )
    monkeypatch.setattr(trainer, "get_redis", lambda: redis)

    payload = await trainer.get_paper_exploration_bridge_truth()

    queue = payload["materialization_queue_status"]
    assert "active_rows" not in queue
    assert "rejected_after_queue_rows" not in queue
    assert queue["active_rows_total_count"] == 1
    assert queue["active_rows_sample_count"] == 1
    assert queue["active_rows_omitted_from_main_payload"] is True
    active_sample = queue["active_rows_sample"][0]
    assert active_sample["queue_id"] == "paper_exploration_materialize_hyp-bridge"
    assert active_sample["guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert active_sample["guardian_new_entries_allowed"] is False
    assert active_sample["guardian_block_reasons"] == guardian_reasons
    assert active_sample["continuous_edge_guardian_block_reasons"] == guardian_reasons
    assert active_sample["paper_only"] is True
    assert active_sample["routes_to_live"] is False
    assert active_sample["places_real_order"] is False
    assert active_sample["order_submitted"] is False
    assert active_sample["test_order_submitted"] is False
    assert active_sample["leverage_mutated"] is False
    assert active_sample["margin_mutated"] is False
    assert "entry_feature_snapshot" not in active_sample

    rejected_sample = queue["rejected_after_queue_rows_sample"][0]
    assert rejected_sample["materialization_no_fill_reason"] == (
        "ALL_ROWS_TRUE_PERFORMANCE_CIRCUIT_BLOCKED"
    )
    assert rejected_sample["guardian_status"] == "A_GRADE_HALTED_PERFORMANCE"
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


@pytest.mark.asyncio
async def test_trainer_adaptation_diagnosis_explains_unproven_a_grade_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _FakeRedis(
        {
            trainer.TRAINER_HYBRID_CUDA_STATUS_KEY: {
                "online_learning_status": "WEIGHTS_UPDATING",
                "effective_trainer_mode": "REPLAY_AND_ONLINE_LEARNING",
                "learning_metrics": {
                    "ppo_entropy": 0.96,
                    "train_val_generalization_gap": 3.2,
                    "validation_supervised_loss": 6.7,
                    "loss_after": 2.4,
                    "checkpoint_promotion_reason": (
                        "VALIDATION_IMPROVED_WITH_OVERFIT_GAP_ADVISORY"
                    ),
                    "checkpoint_promoted_this_cycle": True,
                    "entropy_coefficient": 0.01,
                    "supervised_entropy_bonus": 0.0,
                },
            },
            trainer.A_GRADE_GATE_BURNDOWN_STATUS_KEY: {
                "status": "A_GRADE_GATE_ACTIVE_BLOCKED_SOURCE_OWNED",
                "A_grade_rows": 0,
                "near_A_grade_rows": 23,
                "guardian_status": "A_GRADE_HALTED_PERFORMANCE",
                "guardian_new_entries_allowed": False,
                "closest_gap_reason": "NO_STRICT_A_GRADE_SUPPLY",
            },
            trainer.PREEMPTIVE_EDGE_CONTROL_STATUS_KEY: {
                "candidate_count": 2,
                "accepted_count": 0,
            },
            trainer.PREEMPTIVE_CANDIDATE_DECISION_MATRIX_KEY: {
                "rows": [
                    {
                        "pre_trade_loss_probability": 0.92,
                        "expected_edge_after_cost_bps": -1.0,
                        "recent_bucket_profit_factor": 0.03,
                        "block_reasons": [
                            "GUARDIAN_HALTED_OR_MISSING",
                            "EXPECTED_EDGE_AFTER_COST_NON_POSITIVE",
                        ],
                    },
                    {
                        "pre_trade_loss_probability": 0.91,
                        "expected_edge_after_cost_bps": 0.0,
                        "recent_bucket_profit_factor": 0.2,
                        "block_reasons": ["NEGATIVE_BUCKET_HEALTH"],
                    },
                ]
            },
            trainer.PAPER_EXPLORATION_BRIDGE_KEYS["supply_status"]: {
                "fresh_strategy_supply_rows": 565,
                "fresh_exploration_candidates": 3,
                "materialized_positions_last_cycle": 0,
            },
            trainer.PAPER_EXPLORATION_BRIDGE_KEYS[
                "materialization_queue_status"
            ]: {
                "queued_count": 3,
                "active_count": 3,
                "same_cycle_materialized_count": 0,
                "rejected_after_queue_count": 0,
                "exact_no_fill_reason": (
                    "PAPER_EXPLORATION_ACTIVE_REVALIDATION_IN_PROGRESS"
                ),
            },
            trainer.CONTINUOUS_EDGE_GUARDIAN_EXECUTION_GATE_KEY: {
                "status": "A_GRADE_HALTED_PERFORMANCE",
                "a_grade_new_entries_allowed": False,
            },
        }
    )
    monkeypatch.setattr(trainer, "get_redis", lambda: redis)

    payload = await trainer.get_trainer_adaptation_diagnosis()

    assert payload["schema_version"] == "trainer_adaptation_diagnosis_v1"
    assert payload["status"] == "A_GRADE_ADAPTATION_NOT_PROVEN"
    assert payload["learning_active"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["paper_only"] is True
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False
    assert payload["order_submitted"] is False
    assert payload["test_order_submitted"] is False
    assert payload["leverage_mutated"] is False
    assert payload["margin_mutated"] is False

    finding_ids = {finding["id"] for finding in payload["findings"]}
    assert "PPO_ENTROPY_HIGH_POLICY_NOT_CONVERGED" in finding_ids
    assert "TRAIN_VAL_GENERALIZATION_GAP_HIGH" in finding_ids
    assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in finding_ids
    assert "BUCKET_PROFIT_FACTOR_BELOW_A_GRADE_STANDARD" in finding_ids
    assert "A_GRADE_SUPPLY_ZERO" in finding_ids
    assert "PAPER_OUTCOME_FEEDER_STARVED_BY_TRUE_GATES" in finding_ids
    assert "GUARDIAN_HALTED_PERFORMANCE" in finding_ids
    assert payload["trainer"]["ppo_entropy"] == pytest.approx(0.96)
    assert payload["preemptive"]["loss_probability"]["p50"] == pytest.approx(0.92)
    assert payload["a_grade"]["A_grade_rows"] == 0
    assert payload["a_grade"]["guardian_new_entries_allowed"] is False
