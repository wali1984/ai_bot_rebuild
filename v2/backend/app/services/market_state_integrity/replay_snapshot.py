from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def build_replay_snapshot(
    *,
    decision_id: str,
    prediction: dict[str, Any] | None = None,
    risk_decision: dict[str, Any] | None = None,
    orchestrator_decision: dict[str, Any] | None = None,
    paper_candidate: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prediction = prediction or {}
    integrity = integrity or {}
    return {
        "decision_id": decision_id,
        "prediction_id": prediction.get("prediction_id") or (paper_candidate or {}).get("prediction_id"),
        "decision_time_est": prediction.get("generated_est") or prediction.get("generated_utc"),
        "symbol": prediction.get("symbol") or (paper_candidate or {}).get("symbol"),
        "timeframe": prediction.get("timeframe") or (paper_candidate or {}).get("timeframe"),
        "all_tf_candle_timestamps": prediction.get("all_tf_candle_timestamps") or [],
        "all_source_event_times": prediction.get("all_source_event_times") or [],
        "feature_vector_hash": prediction.get("feature_vector_hash") or stable_hash(prediction.get("features") or {}),
        "feature_names": prediction.get("feature_names") or [],
        "missing_mask_hash": prediction.get("missing_mask_hash") or stable_hash(prediction.get("missing_feature_flags") or []),
        "stale_mask_hash": prediction.get("stale_mask_hash") or stable_hash(prediction.get("stale_feature_flags") or []),
        "market_state_id": integrity.get("market_state_id") or prediction.get("market_state_id"),
        "market_state_integrity_score": integrity.get("market_state_integrity_score") or prediction.get("market_state_integrity_score"),
        "masa_prediction_timestamp": prediction.get("masa_prediction_timestamp") or prediction.get("generated_utc"),
        "ppo_observation_timestamp": prediction.get("ppo_observation_timestamp") or prediction.get("generated_utc"),
        "ppo_action": prediction.get("ppo_selected_action") or prediction.get("selected_action"),
        "masa_forecast": {
            "direction_probability": prediction.get("masa_direction_probability"),
            "expected_move_bps": prediction.get("masa_expected_move_bps") or prediction.get("expected_move_bps"),
            "confidence": prediction.get("masa_confidence") or prediction.get("confidence_calibrated"),
        },
        "risk_decision": risk_decision or {},
        "orchestrator_decision": orchestrator_decision or {},
        "paper_live_candidate": paper_candidate or {},
        "execution_result": (paper_candidate or {}).get("decision"),
        "strategy_router": {
            "selected_mode": (paper_candidate or {}).get("strategy_selected_mode") or prediction.get("strategy_selected_mode"),
            "allowed_actions": (paper_candidate or {}).get("strategy_allowed_actions") or prediction.get("strategy_allowed_actions") or [],
            "action_mask": (paper_candidate or {}).get("strategy_action_mask") or prediction.get("strategy_action_mask") or {},
            "size_multiplier": (paper_candidate or {}).get("strategy_size_multiplier") or prediction.get("strategy_size_multiplier"),
            "confidence": (paper_candidate or {}).get("strategy_router_confidence") or prediction.get("strategy_router_confidence"),
            "block_reason": (paper_candidate or {}).get("strategy_router_block_reason") or prediction.get("strategy_router_block_reason"),
            "reason_codes": (paper_candidate or {}).get("strategy_reason_codes") or prediction.get("strategy_reason_codes") or [],
            "regime_labels": (paper_candidate or {}).get("strategy_regime_labels") or prediction.get("strategy_regime_labels") or [],
            "explanation": (paper_candidate or {}).get("strategy_explanation") or prediction.get("strategy_explanation") or {},
        },
        "data_quality_scores": integrity,
        "source_lineage": integrity.get("source_lineage") or {},
    }
