from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.services.decision_improvement import (
    build_decision_improvement_recommendations,
)


def test_false_shadow_blocks_prioritize_expected_move_coverage_task() -> None:
    status = build_decision_improvement_recommendations(
        scoreboard_status={},
        shadow_outcome_status={
            "outcome_status": "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED",
            "false_block_count": 2,
            "false_block_reason_counts": {"missing_expected_move_after_costs": 2},
        },
    )

    assert (
        status["claude_task_ready"]
        == "claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks"
    )
    assert status["next_tasks"][0]["priority"] == "P0"
    assert status["shadow_false_block_count"] == 2
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["does_not_approve_live"] is True


def test_resolved_per_fill_fields_are_not_requeued() -> None:
    status = build_decision_improvement_recommendations(
        scoreboard_status={},
        paper_edge_status={
            "resolved_controls": [
                "missing_expected_move_after_cost_bps_blocks_fill",
                "missing_trainer_source_blocks_fill",
                "missing_feature_freshness_state_blocks_fill",
                "symbol_not_in_paper_symbols_blocks_fill",
                "confidence_alone_cannot_allow_fill",
            ]
        },
        shadow_outcome_status={"false_block_count": 0},
    )

    task_ids = [task["task_id"] for task in status["next_tasks"]]
    assert "claude_add_per_fill_trainer_source_and_feature_freshness" not in task_ids
    assert "claude_v2_paper_edge_recovery_and_cost_aware_trade_selection" not in task_ids
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []


def test_completed_expected_move_review_is_not_requeued_for_historical_false_blocks() -> None:
    status = build_decision_improvement_recommendations(
        scoreboard_status={},
        paper_edge_status={
            "resolved_controls": [
                "missing_expected_move_after_cost_bps_blocks_fill",
                "missing_trainer_source_blocks_fill",
                "missing_feature_freshness_state_blocks_fill",
                "symbol_not_in_paper_symbols_blocks_fill",
                "confidence_alone_cannot_allow_fill",
            ],
            "paper_pnl": {
                "expected_move_after_cost_false_block_model_review": {
                    "classification": "EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING"
                }
            },
        },
        shadow_outcome_status={
            "false_block_count": 15,
            "outcome_status": "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED",
        },
    )

    task_ids = [task["task_id"] for task in status["next_tasks"]]
    assert "claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks" not in task_ids
    assert status["shadow_false_block_count"] == 15
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []


def test_completed_shadow_learning_is_not_requeued() -> None:
    status = build_decision_improvement_recommendations(
        scoreboard_status={},
        paper_edge_status={
            "resolved_controls": [
                "missing_expected_move_after_cost_bps_blocks_fill",
                "missing_trainer_source_blocks_fill",
                "missing_feature_freshness_state_blocks_fill",
                "symbol_not_in_paper_symbols_blocks_fill",
                "confidence_alone_cannot_allow_fill",
            ],
            "paper_pnl": {
                "expected_move_after_cost_false_block_model_review": {
                    "classification": "EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING"
                }
            },
        },
        shadow_outcome_status={
            "false_block_count": 9,
            "outcome_status": "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED",
        },
        shadow_learning_status={
            "go_no_go": "SHADOW_OUTCOME_LEARNING_READY_EDGE_PENDING",
        },
    )

    task_ids = [task["task_id"] for task in status["next_tasks"]]
    assert "claude_add_shadow_outcome_learning_for_blocked_intents" not in task_ids
    assert status["claude_task_ready"] == "claude_map_legacy_protective_behaviors_to_v2_paper"
    assert status["shadow_learning_status"] == "SHADOW_OUTCOME_LEARNING_READY_EDGE_PENDING"
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []


def test_ready_protective_map_routes_to_remaining_gap_implementation() -> None:
    status = build_decision_improvement_recommendations(
        scoreboard_status={},
        paper_edge_status={
            "resolved_controls": [
                "missing_expected_move_after_cost_bps_blocks_fill",
                "missing_trainer_source_blocks_fill",
                "missing_feature_freshness_state_blocks_fill",
                "symbol_not_in_paper_symbols_blocks_fill",
                "confidence_alone_cannot_allow_fill",
            ],
            "paper_pnl": {
                "expected_move_after_cost_false_block_model_review": {
                    "classification": "EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING"
                }
            },
        },
        shadow_outcome_status={
            "false_block_count": 8,
            "outcome_status": "BLOCKED_INTENTS_BEAT_COSTS_MODEL_REVIEW_REQUIRED",
        },
        shadow_learning_status={
            "go_no_go": "SHADOW_OUTCOME_LEARNING_READY_EDGE_PENDING",
        },
        protective_behavior_status={
            "go_no_go": "LEGACY_PROTECTIVE_BEHAVIOR_TO_V2_PAPER_MAP_READY_EDGE_PENDING",
            "remaining_protective_behavior_gaps": [
                "minimum_hold_time",
                "dynamic_tp_simulation",
            ],
        },
    )

    task_ids = [task["task_id"] for task in status["next_tasks"]]
    assert "claude_map_legacy_protective_behaviors_to_v2_paper" not in task_ids
    assert (
        status["claude_task_ready"]
        == "claude_implement_v2_paper_remaining_protective_behavior_gaps"
    )
    assert status["remaining_protective_behavior_gaps"] == [
        "minimum_hold_time",
        "dynamic_tp_simulation",
    ]
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
