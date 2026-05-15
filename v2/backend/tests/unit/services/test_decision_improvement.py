from __future__ import annotations

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
