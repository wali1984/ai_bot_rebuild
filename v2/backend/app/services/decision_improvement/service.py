from __future__ import annotations

from typing import Any, Mapping

from v2.backend.app.services.legacy_v2_observatory_common import LIVE_GATE_STATUS, safety_footer, utc_now


def _nested_get(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def build_decision_improvement_recommendations(
    *,
    scoreboard_status: Mapping[str, Any],
    paper_loss_status: Mapping[str, Any] | None = None,
    trainer_status: Mapping[str, Any] | None = None,
    paper_edge_status: Mapping[str, Any] | None = None,
    shadow_outcome_status: Mapping[str, Any] | None = None,
    symbol_status: Mapping[str, Any] | None = None,
    risk_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    shadow_outcome_status = shadow_outcome_status or {}
    paper_edge_status = paper_edge_status or {}
    false_block_count = int(shadow_outcome_status.get("false_block_count") or 0)
    resolved_controls = set(paper_edge_status.get("resolved_controls") or [])
    expected_move_review = (
        paper_edge_status.get("expected_move_after_cost_false_block_model_review")
        or _nested_get(paper_edge_status, "paper_pnl", "expected_move_after_cost_false_block_model_review")
        or {}
    )
    expected_move_review_ready = (
        expected_move_review.get("classification")
        == "EXPECTED_MOVE_AFTER_COST_MODEL_REVIEW_READY_EDGE_PENDING"
        or expected_move_review.get("remediation_status")
        == "PAPER_EXPECTED_MOVE_COVERAGE_REMEDIATION_READY"
    )
    core_edge_controls = {
        "missing_expected_move_after_cost_bps_blocks_fill",
        "missing_trainer_source_blocks_fill",
        "missing_feature_freshness_state_blocks_fill",
        "symbol_not_in_paper_symbols_blocks_fill",
        "confidence_alone_cannot_allow_fill",
    }
    tasks = []
    if not core_edge_controls.issubset(resolved_controls):
        tasks.append(
            {
                "task_id": "claude_v2_paper_edge_recovery_and_cost_aware_trade_selection",
                "priority": "P0",
                "reason": "Paper loss attribution found fee/slippage/churn loss and missing edge-after-cost evidence.",
                "required_result": "Confidence alone cannot permit paper fills; missing expected edge blocks and records shadow observation.",
            }
        )
    tasks.extend(
        [
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
    )
    if not {
        "missing_trainer_source_blocks_fill",
        "missing_feature_freshness_state_blocks_fill",
    }.issubset(resolved_controls):
        tasks.insert(
            1,
            {
                "task_id": "claude_add_per_fill_trainer_source_and_feature_freshness",
                "priority": "P0",
                "reason": "Per-fill trainer source and feature freshness are missing or not yet enforced in current paper recovery evidence.",
                "required_result": "Every intent/fill/block carries trainer_source and feature_freshness_state.",
            },
        )
    if false_block_count > 0 and not expected_move_review_ready:
        tasks.insert(
            0,
            {
                "task_id": "claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks",
                "priority": "P0",
                "reason": (
                    f"Shadow outcome observer found {false_block_count} blocked intents that beat costs; "
                    "current false-block reasons show expected-move coverage/model review is required."
                ),
                "required_result": (
                    "Increase native or explicitly accepted expected_move_after_cost_bps coverage from trainer/feature evidence; "
                    "do not use future outcome labels to permit fills and do not loosen the strict paper fill gate."
                ),
            },
        )
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
            "paper_shadow_outcome_observer",
            "symbol_universe",
            "risk_gateway",
        ],
        "shadow_outcome_status": shadow_outcome_status.get("outcome_status"),
        "shadow_false_block_count": false_block_count,
        "shadow_false_block_reason_counts": shadow_outcome_status.get("false_block_reason_counts") or {},
        "next_tasks": tasks,
        "claude_task_ready": tasks[0]["task_id"],
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "does_not_approve_live": True,
        "does_not_approve_legacy_shutdown": True,
    }
    status.update(safety_footer())
    return status
