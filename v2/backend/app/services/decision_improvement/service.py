from __future__ import annotations

from typing import Any, Mapping

from v2.backend.app.services.legacy_v2_observatory_common import LIVE_GATE_STATUS, safety_footer, utc_now


def build_decision_improvement_recommendations(
    *,
    scoreboard_status: Mapping[str, Any],
    paper_loss_status: Mapping[str, Any] | None = None,
    trainer_status: Mapping[str, Any] | None = None,
    paper_edge_status: Mapping[str, Any] | None = None,
    symbol_status: Mapping[str, Any] | None = None,
    risk_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    tasks = [
        {
            "task_id": "claude_v2_paper_edge_recovery_and_cost_aware_trade_selection",
            "priority": "P0",
            "reason": "Paper loss attribution found fee/slippage/churn loss and missing edge-after-cost evidence.",
            "required_result": "Confidence alone cannot permit paper fills; missing expected edge blocks and records shadow observation.",
        },
        {
            "task_id": "claude_add_per_fill_trainer_source_and_feature_freshness",
            "priority": "P0",
            "reason": "Per-fill trainer source and feature freshness are missing from paper events.",
            "required_result": "Every intent/fill/block carries trainer_source and feature_freshness_state.",
        },
        {
            "task_id": "claude_add_shadow_outcome_learning_for_blocked_intents",
            "priority": "P1",
            "reason": "Post-filter no-fill state is safe but cannot prove edge without outcome observations.",
            "required_result": "Blocked intents collect 5m/15m/30m/1h after-cost outcomes without paper fees.",
        },
        {
            "task_id": "claude_map_legacy_protective_behaviors_to_v2_paper",
            "priority": "P1",
            "reason": "Legacy closure includes churn, lifecycle, TP/stop, reduce-only, and adaptive gate behavior not silently droppable.",
            "required_result": "Each protective behavior is implemented in paper-only form or emitted as an explicit blocker.",
        },
    ]
    status = {
        "worker_id": "v2_decision_improvement_recommender",
        "generated_at": utc_now(),
        "recommendation_basis": [
            "legacy_v2_decision_comparator",
            "legacy_signal_outcome_observer",
            "decision_quality_scoreboard",
            "paper_loss_attribution",
            "trainer_bridge",
            "paper_edge_recovery",
            "symbol_universe",
            "risk_gateway",
        ],
        "next_tasks": tasks,
        "claude_task_ready": tasks[0]["task_id"],
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "does_not_approve_live": True,
        "does_not_approve_legacy_shutdown": True,
    }
    status.update(safety_footer())
    return status
