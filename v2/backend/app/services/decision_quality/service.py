from __future__ import annotations

from typing import Any, Mapping

from v2.backend.app.services.legacy_v2_observatory_common import (
    LIVE_GATE_STATUS,
    as_list,
    nested_get,
    safety_footer,
    utc_now,
)


def _coverage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def build_decision_quality_scoreboard_status(
    *,
    comparator_status: Mapping[str, Any],
    outcome_status: Mapping[str, Any],
    paper_loss_status: Mapping[str, Any] | None = None,
    paper_exec_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    comparisons = as_list(comparator_status.get("comparisons"))
    total = len(comparisons)
    allowed = [
        item
        for item in comparisons
        if isinstance(item, Mapping) and item.get("comparator_result") in {"BOTH_ALLOW", "LEGACY_BLOCK_V2_ALLOW"}
    ]
    blocked = [
        item
        for item in comparisons
        if isinstance(item, Mapping) and item.get("comparator_result") in {"LEGACY_ALLOW_V2_BLOCK", "BOTH_BLOCK"}
    ]
    edge_present = [
        item
        for item in comparisons
        if isinstance(item, Mapping) and item.get("expected_move_after_cost_bps") is not None
    ]
    trainer_source_present = [
        item
        for item in comparisons
        if isinstance(item, Mapping) and "trainer_source_missing" not in as_list(item.get("disagreement_reasons"))
    ]
    feature_current = [
        item
        for item in comparisons
        if isinstance(item, Mapping) and item.get("feature_freshness_state") == "CURRENT"
    ]
    paper_loss_status = paper_loss_status or {}
    paper_exec_status = paper_exec_status or {}
    status = {
        "worker_id": "decision_quality_scoreboard",
        "generated_at": utc_now(),
        "sample_windows": {
            "1h": "quick_safety_only",
            "6h": "short_run_quality",
            "24h": "preliminary_edge",
            "7d": "meaningful_paper_edge",
        },
        "minimum_sample_policy": {
            "minimum_allowed_trade_count_for_edge_claim": 30,
            "if_below_minimum": "EDGE_PENDING_INSUFFICIENT_SAMPLE",
            "raw_win_rate_alone_is_not_used": True,
        },
        "directional_accuracy": "PENDING_OUTCOME",
        "after_cost_accuracy": "PENDING_OUTCOME",
        "allow_precision": "INSUFFICIENT_ALLOWED_TRADE_SAMPLE",
        "block_precision": "PENDING_OUTCOME",
        "no_trade_correct_rate": "PENDING_OUTCOME",
        "expected_edge_coverage": _coverage(len(edge_present), total),
        "trainer_source_coverage": _coverage(len(trainer_source_present), total),
        "feature_freshness_coverage": _coverage(len(feature_current), total),
        "confidence_calibration_error": "MISSING_NATIVE_OUTCOME_SAMPLE",
        "precision_by_confidence_bucket": {},
        "precision_by_symbol": {},
        "precision_by_timeframe": {},
        "precision_by_source": {},
        "precision_by_reason_code": {},
        "false_allow_count": 0,
        "false_block_count": 0,
        "stale_feature_block_count": sum(
            1
            for item in comparisons
            if isinstance(item, Mapping) and "stale_features" in as_list(item.get("disagreement_reasons"))
        ),
        "edge_missing_block_count": sum(
            1
            for item in comparisons
            if isinstance(item, Mapping) and "expected_edge_missing" in as_list(item.get("disagreement_reasons"))
        ),
        "fee_bleed_prevented": "SOURCE_LIMITED_POST_FILTER_NO_UNSAFE_FILLS",
        "candidate_trade_count": total,
        "allowed_paper_fill_count": len(allowed),
        "blocked_shadow_count": len(blocked),
        "primary_metrics": {
            "after_cost_precision_on_allowed_trades": "INSUFFICIENT_ALLOWED_TRADE_SAMPLE",
            "no_bad_fill_rate": "PENDING_OUTCOME",
            "no_trade_correct_rate": "PENDING_OUTCOME",
            "expected_value_after_costs": "PENDING_OUTCOME",
            "calibration_by_bucket": "PENDING_OUTCOME",
        },
        "primary_metric_status": "EDGE_PENDING_INSUFFICIENT_SAMPLE",
        "target_definitions": {
            "no_live_mutation_safety": "99%+",
            "no_unsafe_fill_safety": "99%+",
            "block_correctness_missing_stale_edge_negative": "95%+",
            "allowed_trade_after_cost_precision_warn_below": 0.55,
            "allowed_trade_after_cost_precision_good_above": 0.65,
            "allowed_trade_after_cost_precision_excellent_above": 0.75,
            "market_prediction_accuracy_99_claimed": False,
        },
        "paper_loss_visible": {
            "current_cumulative_pnl": paper_loss_status.get("current_cumulative_paper_pnl")
            or nested_get(paper_loss_status, "pnl_waterfall.current_cumulative_paper_pnl_usdt")
            or nested_get(paper_loss_status, "summary.current_cumulative_paper_pnl")
            or paper_exec_status.get("current_paper_pnl"),
            "classification": paper_loss_status.get("decision")
            or paper_loss_status.get("classification")
            or "SOURCE_LIMITED",
        },
        "no_99_market_accuracy_claimed": True,
        "outcome_status": outcome_status.get("outcome_status"),
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
    }
    status.update(safety_footer())
    return status
