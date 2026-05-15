from __future__ import annotations

from typing import Any, Mapping

from v2.backend.app.services.legacy_v2_observatory_common import (
    LIVE_GATE_STATUS,
    nested_get,
    safety_footer,
    utc_now,
)


def build_legacy_signal_outcome_observer_status(
    *,
    comparator_status: Mapping[str, Any],
    paper_status: Mapping[str, Any],
) -> dict[str, Any]:
    latest = nested_get(comparator_status, "latest_comparison", {})
    price = nested_get(paper_status, "market_feed.last_price") or nested_get(
        paper_status, "risk_runtime_payload.last_price"
    )
    expected_after_cost = latest.get("expected_move_after_cost_bps") if isinstance(latest, Mapping) else None
    observation = {
        "observation_id": f"obs_{latest.get('comparison_id', 'missing')}",
        "comparison_id": latest.get("comparison_id"),
        "legacy_prediction_id": latest.get("legacy_prediction_id"),
        "legacy_signal_id": latest.get("legacy_signal_id"),
        "v2_prediction_id": latest.get("v2_prediction_id"),
        "symbol": latest.get("symbol"),
        "side": latest.get("side"),
        "entry_reference_price": price,
        "event_ts": utc_now(),
        "horizon_5m": "PENDING_OR_SOURCE_LIMITED",
        "horizon_15m": "PENDING_OR_SOURCE_LIMITED",
        "horizon_30m": "PENDING_OR_SOURCE_LIMITED",
        "horizon_1h": "PENDING_OR_SOURCE_LIMITED",
        "expected_move_after_cost_bps": expected_after_cost,
        "realized_return_bps": None,
        "max_favorable_excursion_bps": None,
        "max_adverse_excursion_bps": None,
        "would_have_beaten_fees": "PENDING_OUTCOME",
        "would_have_beaten_slippage": "PENDING_OUTCOME",
        "would_have_hit_stop": "PENDING_OUTCOME",
        "would_have_hit_take_profit": "PENDING_OUTCOME",
        "direction_correct": "PENDING_OUTCOME",
        "after_cost_correct": "MISSING_EVIDENCE"
        if expected_after_cost is None
        else "PENDING_OUTCOME",
        "no_trade_correct": "PENDING_OUTCOME_OR_EDGE_MISSING",
        "block_reason": latest.get("v2_block_reason"),
    }
    status = {
        "worker_id": "legacy_signal_outcome_observer",
        "generated_at": utc_now(),
        "read_only_status": "READ_ONLY_REFERENCE_ONLY",
        "observations_total": 1,
        "pending_observations": 1,
        "completed_observations": 0,
        "observations": [observation],
        "latest_observation": observation,
        "after_cost_correct_count": 0,
        "no_trade_correct_count": 0,
        "outcome_status": "OUTCOME_PENDING_SOURCE_LIMITED",
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
    }
    status.update(safety_footer())
    return status
