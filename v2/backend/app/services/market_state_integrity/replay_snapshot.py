from __future__ import annotations

import hashlib
import json
from typing import Any

from .trust import TRUST_SCHEMA_VERSION


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
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "decision_id": decision_id,
        "prediction_id": prediction.get("prediction_id") or (paper_candidate or {}).get("prediction_id"),
        "signal_id": prediction.get("signal_id") or (paper_candidate or {}).get("signal_id"),
        "decision_time_est": prediction.get("generated_est") or prediction.get("generated_utc"),
        "decision_time": prediction.get("decision_time") or prediction.get("generated_est") or prediction.get("generated_utc"),
        "generated_at": prediction.get("generated_at") or prediction.get("generated_est") or prediction.get("generated_utc"),
        "available_at": prediction.get("available_at") or prediction.get("source_available_time"),
        "symbol": prediction.get("symbol") or (paper_candidate or {}).get("symbol"),
        "timeframe": prediction.get("timeframe") or (paper_candidate or {}).get("timeframe"),
        "selected_action": (
            prediction.get("selected_action")
            or prediction.get("ppo_selected_action")
            or prediction.get("action")
        ),
        "model_version": prediction.get("model_version") or prediction.get("model_source") or prediction.get("model_id"),
        "model_id": prediction.get("model_id"),
        "checkpoint_id": prediction.get("checkpoint_id"),
        "replay_snapshot_id": prediction.get("replay_snapshot_id") or decision_id,
        "mtf_snapshot_id": prediction.get("mtf_snapshot_id"),
        "mtf_snapshot_valid": prediction.get("mtf_snapshot_valid"),
        "feature_snapshot_id": prediction.get("feature_snapshot_id"),
        "feature_cutoff": prediction.get("feature_cutoff"),
        "source_hashes": dict(prediction.get("source_hashes") or {}),
        "feature_snapshot": prediction.get("feature_snapshot") or {},
        "masa_generated_at": prediction.get("masa_generated_at")
        or prediction.get("masa_prediction_timestamp")
        or prediction.get("generated_at")
        or prediction.get("generated_est")
        or prediction.get("generated_utc"),
        "masa_feature_cutoff": prediction.get("masa_feature_cutoff") or prediction.get("feature_cutoff"),
        "masa_forecast_horizon": prediction.get("masa_forecast_horizon")
        or prediction.get("forecast_horizon")
        or prediction.get("timeframe"),
        "masa_symbol": prediction.get("masa_symbol") or prediction.get("symbol"),
        "masa_timeframe": prediction.get("masa_timeframe") or prediction.get("timeframe"),
        "ppo_observation_time": prediction.get("ppo_observation_time")
        or prediction.get("ppo_observation_timestamp")
        or prediction.get("generated_at")
        or prediction.get("generated_est")
        or prediction.get("generated_utc"),
        "ppo_feature_cutoff": prediction.get("ppo_feature_cutoff") or prediction.get("feature_cutoff"),
        "ppo_symbol": prediction.get("ppo_symbol") or prediction.get("symbol"),
        "ppo_timeframe": prediction.get("ppo_timeframe") or prediction.get("timeframe"),
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
