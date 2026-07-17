"""Prediction publisher and decision-lineage adapter for the hybrid trainer."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    DECISION_REASON_PROCEED_LONG,
    DECISION_REASON_PROCEED_SHORT,
    OrchestratorDecisionRecord,
)
from v2.backend.app.domain.risk_gateway.record import (
    RISK_DECISION_ACTION_ALLOW,
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_ALLOW_PROCEED_LONG,
    RISK_DECISION_REASON_ALLOW_PROCEED_SHORT,
    RISK_DECISION_REASON_DENY_DEFAULT,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_ABSTAINED,
    RISK_DECISION_REASON_DENY_ORCHESTRATOR_HELD,
    RiskDecisionRecord,
)
from v2.backend.app.domain.trainer_prediction_output import (
    PREDICTION_DIRECTION_FLAT,
    PREDICTION_DIRECTION_LONG,
    PREDICTION_DIRECTION_SHORT,
    PREDICTION_FRESHNESS_FRESH,
    PREDICTION_FRESHNESS_MISSING,
    PREDICTION_FRESHNESS_STALE,
)
from v2.backend.app.services.orchestrator_decision.service import (
    assemble_orchestrator_decision_record,
)
from v2.backend.app.services.paper_execution_ledger.service import (
    assemble_paper_execution_ledger_entry,
)
from v2.backend.app.services.market_state_integrity.scoring import score_market_state
from v2.backend.app.services.market_state_integrity.replay_snapshot import build_replay_snapshot
from v2.backend.app.services.market_state_integrity.trust import (
    attach_runtime_trust_metadata,
    build_market_state_envelope_from_snapshot,
    coerce_market_state_envelope,
    mark_runtime_trust_denied,
    validate_prediction_trust_contract,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    append_snapshot,
    build_archive_record_from_prediction_payload,
)
from v2.backend.app.services.risk_gateway.service import assemble_risk_decision_record
from v2.backend.app.services.trainer_prediction_output.service import (
    assemble_prediction_record,
)

from .checkpoint import CheckpointManifest
from .config import (
    ACTION_LABELS,
    CHECKPOINT_SOURCE,
    LIVE_GATE_BLOCKED,
    MODEL_SOURCE,
    ORCHESTRATOR_DECISIONS_KEY,
    PAPER_BLOCK_REASONS_KEY,
    PAPER_INTENTS_KEY,
    PAPER_LEDGER_KEY,
    PAPER_POSITIONS_KEY,
    PAPER_SIGNAL_KEY_TEMPLATE,
    PAPER_SIGNAL_TIMEFRAME_KEY_TEMPLATE,
    PAPER_SIGNAL_LINEAGE_KEY,
    PREDICTION_KEY_TEMPLATE,
    REDIS_HEARTBEAT_KEY,
    REDIS_METRICS_KEY,
    REDIS_STATUS_KEY,
    RISK_DECISIONS_KEY,
    TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
    TRAINER_SOURCE,
)
from .data_loader import TrainingExample
from .model import ModelForwardResult
from .safety import V2OnlyJsonIO, safety_scoreboard

REQUIRED_PREDICTION_FIELDS = (
    "prediction_id",
    "generated_est",
    "symbol",
    "timeframe",
    "selected_action",
    "selected_action_index",
    "action_probabilities",
    "expected_move_bps",
    "expected_move_after_cost_bps",
    "confidence_raw",
    "confidence_calibrated",
    "policy_value",
    "masa_signal",
    "feature_snapshot_id",
    "data_coverage_percent",
    "missing_feature_count",
    "stale_feature_count",
    "source_availability_vector",
    "trainer_source",
    "model_source",
    "checkpoint_source",
    "live_gate",
    "live_symbols",
    "market_state_id",
    "market_state_integrity_score",
    "valid_for_prediction",
    "valid_for_risk",
    "valid_for_orchestrator",
    "valid_for_paper",
)

PREMIUM_CONTEXT_SOURCE = "V2_HYBRID_CUDA_TRAINER_ENTRY_FEATURES"
_LIQUIDITY_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "liquidity_score",
    "orderbook_depth_usd",
    "depth_total_usd",
    "depth_usd",
    "bid_depth_usd",
    "ask_depth_usd",
    "depth_imbalance",
    "whale_bid_wall_notional_usd",
    "whale_ask_wall_notional_usd",
    "whale_total_wall_notional_usd",
    "nearest_bid_wall_distance_bps",
    "nearest_ask_wall_distance_bps",
)
_LIQUIDATION_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "nearest_liquidation_level_above",
    "nearest_liquidation_level_below",
    "liquidation_long_level",
    "liquidation_short_level",
    "liquidation_distance_pct",
    "liquidation_long_distance_pct",
    "liquidation_short_distance_pct",
    "liquidation_sweep_target_long_distance_bps",
    "liquidation_sweep_target_short_distance_bps",
    "liquidation_cascade_risk",
    "liquidation_pressure_direction",
    "liquidation_levels_count_long",
    "liquidation_levels_count_short",
    "liquidation_zones_count_long",
    "liquidation_zones_count_short",
    "liquidation_long_strength",
    "liquidation_short_strength",
    "liquidation_strength",
    "liquidation_volume",
    "last_liq_bps_24h",
)
_MICROSTRUCTURE_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "bid_ask_spread_bps",
    "spread_bps",
    "ob_spread_bps",
    "micro_price",
    "orderbook_imbalance",
    "depth_imbalance",
    "tape_imbalance",
    "order_flow_imbalance",
    "depth_vs_tape_divergence",
    "bid_depth_usd",
    "ask_depth_usd",
    "orderbook_depth_usd",
)
_OI_FUNDING_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "funding_rate",
    "expected_funding_bps",
    "funding_bps",
    "open_interest",
    "oi_change_pct",
    "open_interest_change_pct",
    "long_short_ratio",
    "long_account_ratio",
    "short_account_ratio",
)
_PUBLIC_INTEL_CONTEXT_VALUE_FIELDS: tuple[str, ...] = (
    "public_intel_score",
    "news_attention_score",
    "news_sentiment_score",
    "sentiment_score",
    "fear_greed_score",
    "fear_greed_context",
    "market_breadth_score",
    "social_momentum_score",
    "social_volume_velocity",
    "defillama_score",
    "defillama_liquidity_score",
    "defillama_tvl_momentum_score",
    "coingecko_liquidity_score",
    "coingecko_momentum_score",
    "surf_score",
    "surf_market_price_signal_score",
)
_PREMIUM_CONTEXT_REQUIREMENTS: tuple[tuple[str, tuple[str, ...], str, bool], ...] = (
    ("liquidity_context", _LIQUIDITY_CONTEXT_VALUE_FIELDS, "LIQUIDITY", True),
    ("liquidity_zone_context", _LIQUIDITY_CONTEXT_VALUE_FIELDS, "LIQUIDITY_ZONE", True),
    ("liquidation_distance_context", _LIQUIDATION_CONTEXT_VALUE_FIELDS, "LIQUIDATION", True),
    ("liquidation_context", _LIQUIDATION_CONTEXT_VALUE_FIELDS, "LIQUIDATION", True),
    ("microstructure_context", _MICROSTRUCTURE_CONTEXT_VALUE_FIELDS, "MICROSTRUCTURE", True),
    ("oi_funding_context", _OI_FUNDING_CONTEXT_VALUE_FIELDS, "OI_FUNDING", True),
    ("public_intel_context", _PUBLIC_INTEL_CONTEXT_VALUE_FIELDS, "PUBLIC_INTEL", False),
)

EXPLICIT_MARKET_STATE_TRUST_FIELDS = (
    "feature_cutoff",
    "decision_cutoff",
    "available_at",
    "source_available_time",
    "candle_closed_confirmed",
    "closed_candle",
    "candle_open_time",
    "candle_close_time",
    "source_event_time",
    "source_event_time_est",
    "source_received_time_est",
    "decision_time",
    "decision_time_est",
    "backfilled",
    "is_backfilled",
    "latency_ms",
    "price_disagreement_bps",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
    "decision_id",
    "mtf_snapshot_id",
    "mtf_snapshot_valid",
    "multi_timeframe_decision_snapshot",
)

_TOP_LEVEL_ENVELOPE_FIELDS = (
    "decision_time",
    "event_time",
    "available_at",
    "ingested_at",
    "feature_cutoff",
    "timeframe_cutoffs",
)


def _est_iso() -> str:
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.isoformat(timespec="seconds")


def _now_ms() -> int:
    return int(datetime.now(tz=ZoneInfo("UTC")).timestamp() * 1000)


def _prediction_id(symbol: str, timeframe: str, tensor_id: str, model_id: str) -> str:
    h = hashlib.sha256(f"{symbol}|{timeframe}|{tensor_id}|{model_id}".encode()).hexdigest()[:32]
    return "v2h_" + h


def direction_from_action(action: str) -> str:
    if action == "long":
        return PREDICTION_DIRECTION_LONG
    if action == "short":
        return PREDICTION_DIRECTION_SHORT
    return PREDICTION_DIRECTION_FLAT


def action_policy_diagnostics(
    *,
    selected_action: str,
    action_probabilities: Any,
    expected_move_bps: Any,
    round_trip_cost_bps: float,
    min_edge_after_cost_bps: float,
) -> dict[str, Any]:
    probabilities = list(action_probabilities or [])
    probability_by_action: dict[str, float] = {}
    for index, label in enumerate(ACTION_LABELS):
        value = probabilities[index] if index < len(probabilities) else None
        number = _finite_float(value)
        if number is not None:
            probability_by_action[str(label)] = number

    normalized_action = str(selected_action or "hold").strip().lower()
    selected_probability = probability_by_action.get(normalized_action)
    opening_candidates = {
        action: probability_by_action.get(action, 0.0)
        for action in ("hold", "long", "short")
    }
    opening_argmax_action = max(
        opening_candidates,
        key=lambda action: (opening_candidates[action], -ACTION_LABELS.index(action)),
    )
    expected_move = _finite_float(expected_move_bps)
    cost = abs(float(round_trip_cost_bps))
    min_edge = abs(float(min_edge_after_cost_bps))
    counterfactual_action: str | None = None
    counterfactual_after_cost: float | None = None
    if expected_move is not None:
        long_after_cost = expected_move - cost
        short_after_cost = expected_move + cost
        if long_after_cost >= min_edge:
            counterfactual_action = "long"
            counterfactual_after_cost = long_after_cost
        elif short_after_cost <= -min_edge:
            counterfactual_action = "short"
            counterfactual_after_cost = short_after_cost

    counterfactual_probability = (
        probability_by_action.get(counterfactual_action)
        if counterfactual_action is not None
        else None
    )
    selected_vs_counterfactual_gap = (
        selected_probability - counterfactual_probability
        if selected_probability is not None and counterfactual_probability is not None
        else None
    )
    selected_hold_with_directional_edge = (
        normalized_action == "hold" and counterfactual_action in {"long", "short"}
    )
    # Per-side net edge decomposition: separates "model sees no edge" from
    # "pipeline failed to emit a side". USD conversion happens downstream in
    # the allocator once notional is sized; bps is the publisher-level truth.
    expected_long_net_edge_bps = expected_move - cost if expected_move is not None else None
    expected_short_net_edge_bps = -expected_move - cost if expected_move is not None else None
    best_side: str | None = None
    best_side_net_edge_bps: float | None = None
    if expected_long_net_edge_bps is not None:
        if expected_long_net_edge_bps >= expected_short_net_edge_bps:
            best_side, best_side_net_edge_bps = "long", expected_long_net_edge_bps
        else:
            best_side, best_side_net_edge_bps = "short", expected_short_net_edge_bps
    hold_probability = probability_by_action.get("hold")
    no_side_reason: str | None = None
    why_best_side_rejected: str | None = None
    if normalized_action == "hold":
        if expected_move is None:
            no_side_reason = "EXPECTED_MOVE_MISSING"
            why_best_side_rejected = "NO_EXPECTED_MOVE_TO_EVALUATE"
        elif best_side_net_edge_bps is not None and best_side_net_edge_bps < min_edge:
            no_side_reason = "EDGE_BELOW_COST_MODEL_SEES_NO_EDGE"
            why_best_side_rejected = (
                f"best_side_{best_side}_net_edge_{best_side_net_edge_bps:.2f}bps_below_min_edge_{min_edge:.2f}bps"
            )
        elif hold_probability is not None and hold_probability > 0.99:
            no_side_reason = "POLICY_HOLD_COLLAPSED_DIRECTIONAL_PROBABILITY_DEGENERATE"
            why_best_side_rejected = (
                f"policy_hold_probability_{hold_probability:.6f}_despite_{best_side}_net_edge_"
                f"{best_side_net_edge_bps:.2f}bps"
            )
        else:
            no_side_reason = "POLICY_PREFERS_HOLD"
            why_best_side_rejected = f"hold_probability_{hold_probability}"
    return {
        "no_side_reason": no_side_reason,
        "expected_long_net_edge_bps": expected_long_net_edge_bps,
        "expected_short_net_edge_bps": expected_short_net_edge_bps,
        "expected_long_net_pnl_usd": None,
        "expected_short_net_pnl_usd": None,
        "per_side_usd_note": "usd_sized_downstream_by_allocator_from_bps_edge",
        "best_side": best_side,
        "best_side_net_edge_bps": best_side_net_edge_bps,
        "why_best_side_rejected": why_best_side_rejected,
        "action_probability_by_label": probability_by_action,
        "opening_policy_argmax_action": opening_argmax_action,
        "opening_policy_argmax_probability": opening_candidates.get(opening_argmax_action),
        "selected_action_probability": selected_probability,
        "counterfactual_directional_action_from_expected_move": counterfactual_action,
        "counterfactual_directional_expected_move_after_cost_bps": counterfactual_after_cost,
        "counterfactual_directional_action_probability": counterfactual_probability,
        "selected_vs_counterfactual_directional_action_probability_gap": selected_vs_counterfactual_gap,
        "selected_hold_with_directional_edge_after_cost": selected_hold_with_directional_edge,
        "selected_hold_directional_edge_diagnostic_reason": (
            "EXPECTED_MOVE_DIRECTIONAL_EDGE_BLOCKED_BY_SELECTED_HOLD"
            if selected_hold_with_directional_edge
            else None
        ),
    }


def _has_explicit_market_state_trust_evidence(row: dict[str, Any]) -> bool:
    return any(row.get(field) is not None for field in EXPLICIT_MARKET_STATE_TRUST_FIELDS)


def _risk_gate_kwargs_from_prediction_payload(prediction_payload: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"snapshot_evidence_required": True}

    embedded_envelope = prediction_payload.get("market_state_envelope")
    if isinstance(embedded_envelope, dict):
        kwargs["market_state_envelope"] = coerce_market_state_envelope(embedded_envelope)
    elif all(prediction_payload.get(field) is not None for field in _TOP_LEVEL_ENVELOPE_FIELDS):
        kwargs["market_state_envelope"] = build_market_state_envelope_from_snapshot(prediction_payload)

    trust_gate_result = prediction_payload.get("trust_gate_result")
    if isinstance(trust_gate_result, dict):
        normalized_trust_gate = dict(trust_gate_result)
        if "accepted" not in normalized_trust_gate and "allowed" in normalized_trust_gate:
            normalized_trust_gate["accepted"] = bool(normalized_trust_gate.get("allowed"))
        kwargs["trust_gate_result"] = normalized_trust_gate

    if prediction_payload.get("position_state") is not None:
        kwargs["position_state"] = str(prediction_payload.get("position_state"))

    if prediction_payload.get("execution_success_probability") is not None:
        kwargs["execution_success_probability"] = prediction_payload.get("execution_success_probability")

    masa_feature_cutoff = prediction_payload.get("masa_feature_cutoff")
    if masa_feature_cutoff is not None:
        kwargs["masa_prediction"] = {"feature_cutoff": masa_feature_cutoff}

    ppo_feature_cutoff = prediction_payload.get("ppo_feature_cutoff")
    if ppo_feature_cutoff is not None:
        kwargs["ppo_observation"] = {"feature_cutoff": ppo_feature_cutoff}

    if prediction_payload.get("replay_snapshot_id") is not None:
        kwargs["replay_snapshot_id"] = str(prediction_payload.get("replay_snapshot_id"))
    if prediction_payload.get("replay_snapshot_key") is not None:
        kwargs["replay_snapshot_key"] = str(prediction_payload.get("replay_snapshot_key"))
    if prediction_payload.get("mtf_snapshot_id") is not None:
        kwargs["mtf_snapshot_id"] = str(prediction_payload.get("mtf_snapshot_id"))
    if "mtf_snapshot_valid" in prediction_payload:
        kwargs["mtf_snapshot_valid"] = prediction_payload.get("mtf_snapshot_valid")

    return kwargs


def _market_state_row_from_example(example: TrainingExample, prediction_id: str) -> dict[str, Any]:
    tensor = example.tensor
    row = {
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "prediction_id": prediction_id,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "features": dict(zip(tensor.feature_names, tensor.values)),
        "feature_names": list(tensor.feature_names),
        "generated_at": _est_iso(),
        "feature_freshness_state": "STALE" if tensor.stale_feature_names else "CURRENT",
        "trainer_consumable": tensor.data_coverage_percent >= 20.0,
        "missing_feature_count": len(tensor.missing_feature_names),
        "missing_feature_names": list(tensor.missing_feature_names),
        "stale_feature_count": len(tensor.stale_feature_names),
        "stale_feature_names": list(tensor.stale_feature_names),
    }
    trust_row = dict(example.trust_row or {})
    if not _has_explicit_market_state_trust_evidence(trust_row):
        return row
    if isinstance(trust_row.get("features"), dict):
        row["features"] = dict(trust_row["features"])
    row["generated_at"] = trust_row.get("generated_at") or trust_row.get("generated_utc") or row["generated_at"]
    row["feature_freshness_state"] = trust_row.get("feature_freshness_state") or row["feature_freshness_state"]
    if trust_row.get("trainer_consumable") is not None:
        row["trainer_consumable"] = trust_row.get("trainer_consumable")
    if trust_row.get("missing_feature_count") is not None:
        row["missing_feature_count"] = trust_row.get("missing_feature_count")
    if trust_row.get("missing_feature_names") is not None:
        row["missing_feature_names"] = list(trust_row.get("missing_feature_names") or [])
    if trust_row.get("stale_feature_count") is not None:
        row["stale_feature_count"] = trust_row.get("stale_feature_count")
    if trust_row.get("stale_feature_names") is not None:
        row["stale_feature_names"] = list(trust_row.get("stale_feature_names") or [])
    for key in (
        "feature_cutoff",
        "available_at",
        "latency_ms",
        "candle_closed_confirmed",
        "candle_open_time",
        "candle_close_time",
        "source_event_time_est",
        "source_received_time_est",
        "source_available_time",
        "decision_time_est",
        "masa_feature_cutoff",
        "ppo_feature_cutoff",
        "all_tf_candle_timestamps",
        "all_source_event_times",
        "decision_id",
        "mtf_snapshot_id",
        "mtf_snapshot_valid",
        "mtf_snapshot_reject_reasons",
        "multi_timeframe_decision_snapshot",
        "price_disagreement_bps",
        "duplicate_event_count",
        "out_of_order_event_count",
        "missing_candle_count",
        "backfilled",
        "is_backfilled",
        "source_mode",
    ):
        if trust_row.get(key) is not None:
            row[key] = trust_row.get(key)
    return row


def _market_state_fields_from_example(example: TrainingExample, prediction_id: str) -> dict[str, Any]:
    score = score_market_state(_market_state_row_from_example(example, prediction_id)).to_dict()
    return {
        "market_state_id": score["market_state_id"],
        "market_state_integrity_score": score["market_state_integrity_score"],
        "valid_for_training": score["valid_for_training"],
        "valid_for_prediction": score["valid_for_prediction"],
        "valid_for_risk": score["valid_for_risk"],
        "valid_for_orchestrator": score["valid_for_orchestrator"],
        "valid_for_paper": score["valid_for_paper"],
        "valid_for_live": score["valid_for_live"],
        "decision_cutoff_time_est": score["decision_time_est"],
        "market_state_reject_reasons": list(score["reject_reasons"]),
        "market_state_score_components": {
            "data_freshness_score": score["data_freshness_score"],
            "candle_completion_score": score["candle_completion_score"],
            "tf_alignment_score": score["tf_alignment_score"],
            "missing_data_score": score["missing_data_score"],
            "source_disagreement_score": score["source_disagreement_score"],
            "latency_score": score["latency_score"],
            "backfill_score": score["backfill_score"],
            "execution_fill_quality_score": score["execution_fill_quality_score"],
        },
        "market_state_source_lineage": score["source_lineage"],
    }


def _trusted_replay_snapshot(
    *,
    prediction_id: str,
    signal_id: str,
    example: TrainingExample,
    model_output: ModelForwardResult,
    trust_row: dict[str, Any],
    checkpoint: CheckpointManifest | None,
    source_hashes: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    reasons: list[str] = []
    explicit_trust = _has_explicit_market_state_trust_evidence(trust_row)
    feature_cutoff = trust_row.get("feature_cutoff") or trust_row.get("decision_cutoff")
    all_tf_candle_timestamps = trust_row.get("all_tf_candle_timestamps") or []
    all_source_event_times = trust_row.get("all_source_event_times") or []
    feature_hash = trust_row.get("feature_vector_hash") or example.tensor.tensor_id
    masa_ts = trust_row.get("masa_prediction_timestamp") or "not_applicable_internal_model_forward"
    ppo_ts = trust_row.get("ppo_observation_timestamp") or "not_applicable_internal_model_forward"
    mtf_snapshot_id = trust_row.get("mtf_snapshot_id") or trust_row.get("decision_snapshot_id")
    decision_id = trust_row.get("decision_id") or prediction_id
    # Archive the tensor's OWN feature view alongside the trust-row features.
    # The trust row's flat dict only carries what the feature pipeline merged
    # (~380 fields) while the prediction tensor resolved the FULL FEATURE_SPEC
    # from live sources (fvg/vwap/cvd/structure/moralis/confluence/...): without
    # this merge those families are permanently absent from the replay archive,
    # so replay training examples show them 0%-populated even though the live
    # decision saw them. Trust-row values win on name collisions (raw values,
    # existing behaviour); the tensor view only fills names the pipeline lacked.
    tensor_feature_view = {
        name: value
        for name, value, missing in zip(
            example.tensor.feature_names, example.tensor.values, example.tensor.missing_mask
        )
        if not missing
    }
    feature_snapshot = {
        "feature_snapshot_id": example.tensor.feature_snapshot_id,
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "features": {**tensor_feature_view, **dict(trust_row.get("features") or {})},
        "feature_cutoff": feature_cutoff,
        "available_at": trust_row.get("available_at") or trust_row.get("source_available_time"),
        "generated_at": trust_row.get("generated_at") or trust_row.get("created_at"),
        "feature_freshness_state": trust_row.get("feature_freshness_state"),
        "trainer_consumable": trust_row.get("trainer_consumable"),
        "candle_closed_confirmed": trust_row.get("candle_closed_confirmed"),
        "candle_open_time": trust_row.get("candle_open_time"),
        "candle_close_time": trust_row.get("candle_close_time"),
        "source_event_time_est": trust_row.get("source_event_time_est"),
        "source_received_time_est": trust_row.get("source_received_time_est"),
        "source_available_time": trust_row.get("source_available_time"),
        "source_hashes": dict(source_hashes),
    }
    mtf_snapshot_valid = trust_row.get("mtf_snapshot_valid")
    mtf_snapshot_reject_reasons = list(trust_row.get("mtf_snapshot_reject_reasons") or [])
    if not explicit_trust:
        reasons.append("TRUST_ROW_MISSING")
    if not mtf_snapshot_id:
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    if mtf_snapshot_valid is not True:
        reasons.append("MTF_SNAPSHOT_INVALID")
    for reason in mtf_snapshot_reject_reasons:
        reasons.append(f"MTF_SNAPSHOT:{reason}")
    if not feature_cutoff:
        reasons.append("FEATURE_CUTOFF_MISSING")
    if not all_tf_candle_timestamps:
        reasons.append("ALL_TIMEFRAME_CANDLE_TIMESTAMPS_MISSING")
    if not all_source_event_times:
        reasons.append("SOURCE_EVENT_TIMES_MISSING")
    if not feature_hash:
        reasons.append("FEATURE_HASH_MISSING")
    if not decision_id:
        reasons.append("DECISION_ID_MISSING")
    prediction = {
        "prediction_id": prediction_id,
        "signal_id": signal_id,
        "decision_id": decision_id,
        "mtf_snapshot_id": mtf_snapshot_id,
        "mtf_snapshot_valid": mtf_snapshot_valid,
        "mtf_snapshot_reject_reasons": mtf_snapshot_reject_reasons,
        "multi_timeframe_decision_snapshot": trust_row.get("multi_timeframe_decision_snapshot"),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "feature_snapshot_id": example.tensor.feature_snapshot_id,
        "feature_snapshot": feature_snapshot,
        "feature_cutoff": feature_cutoff,
        "available_at": trust_row.get("available_at") or trust_row.get("source_available_time"),
        "source_available_time": trust_row.get("source_available_time"),
        "all_tf_candle_timestamps": list(all_tf_candle_timestamps),
        "all_source_event_times": list(all_source_event_times),
        "feature_vector_hash": feature_hash,
        "source_hashes": dict(source_hashes),
        "feature_names": list(example.tensor.feature_names),
        "missing_feature_flags": list(example.tensor.missing_feature_names),
        "stale_feature_flags": list(example.tensor.stale_feature_names),
        "feature_freshness_state": trust_row.get("feature_freshness_state"),
        "trainer_consumable": trust_row.get("trainer_consumable"),
        "candle_closed_confirmed": trust_row.get("candle_closed_confirmed"),
        "candle_open_time": trust_row.get("candle_open_time"),
        "candle_close_time": trust_row.get("candle_close_time"),
        "masa_prediction_timestamp": masa_ts,
        "ppo_observation_timestamp": ppo_ts,
        "ppo_selected_action": model_output.selected_action,
        "selected_action": model_output.selected_action,
        "action_probabilities": list(model_output.action_probabilities),
        "expected_move_bps": model_output.expected_move_bps,
        "confidence_calibrated": model_output.confidence_calibrated,
        "policy_value": model_output.policy_value,
        "model_source": MODEL_SOURCE,
        "model_version": MODEL_SOURCE,
        "model_id": model_output.model_id,
        "checkpoint_id": checkpoint.checkpoint_id if checkpoint else "v2_hybrid_checkpoint_manifest_pending",
    }
    return build_replay_snapshot(decision_id=str(decision_id), prediction=prediction), reasons


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _entry_feature_values(example: TrainingExample, trust_row: dict[str, Any]) -> dict[str, Any]:
    values = dict(zip(example.tensor.feature_names, example.tensor.values))
    if isinstance(trust_row.get("features"), dict):
        values.update(trust_row["features"])
    return values


def _missing_features_for_tokens(example: TrainingExample, trust_row: dict[str, Any], *tokens: str) -> list[str]:
    raw_missing = list(example.tensor.missing_feature_names)
    if isinstance(trust_row.get("missing_feature_names"), list):
        raw_missing.extend(str(item) for item in trust_row["missing_feature_names"])
    lowered = tuple(token.lower() for token in tokens)
    return sorted(
        {
            str(item)
            for item in raw_missing
            if any(token in str(item).lower() for token in lowered)
        }
    )


def _provider_mask_context(example: TrainingExample, trust_row: dict[str, Any]) -> dict[str, Any]:
    tensor = example.tensor
    provider_rows: list[dict[str, Any]] = []
    for index, (name, source) in enumerate(zip(tensor.feature_names, tensor.source_labels)):
        source_text = str(source)
        name_text = str(name)
        is_provider = (
            "altdata" in source_text
            or "moralis" in source_text
            or "coinglass" in source_text
            or "altdata" in name_text
            or "moralis" in name_text
            or "coinglass" in name_text
        )
        if not is_provider:
            continue
        missing = bool(tensor.missing_mask[index]) if index < len(tensor.missing_mask) else True
        stale = bool(tensor.stale_mask[index]) if index < len(tensor.stale_mask) else False
        available = int(tensor.source_availability[index]) if index < len(tensor.source_availability) else 0
        provider_rows.append(
            {
                "name": name_text,
                "source": source_text,
                "missing": missing,
                "stale": stale,
                "source_available": available,
            }
        )
    missing_names = [row["name"] for row in provider_rows if row["missing"]]
    stale_names = [row["name"] for row in provider_rows if row["stale"]]
    available_count = sum(1 for row in provider_rows if row["source_available"] > 0)
    feature_cutoff = (
        trust_row.get("altdata_feature_cutoff")
        or trust_row.get("provider_feature_cutoff")
        or trust_row.get("feature_cutoff")
        or trust_row.get("decision_cutoff")
    )
    return {
        "altdata_feature_cutoff": feature_cutoff if provider_rows else None,
        "provider_features_used": available_count,
        "provider_feature_count": len(provider_rows),
        "provider_missing": missing_names,
        "provider_stale": stale_names,
        "provider_source_availability": {
            row["name"]: row["source_available"] for row in provider_rows
        },
        "provider_missing_mask": {row["name"]: row["missing"] for row in provider_rows},
        "provider_stale_mask": {row["name"]: row["stale"] for row in provider_rows},
        "provider_source_availability_vector": [
            row["source_available"] for row in provider_rows
        ],
        "ppo_provider_feature_mask_count": len(provider_rows),
        "masa_provider_feature_mask_count": len(provider_rows),
    }


PROVIDER_LINEAGE_FIELDS = (
    "altdata_feature_cutoff",
    "provider_features_used",
    "provider_feature_count",
    "provider_missing",
    "provider_stale",
    "provider_source_availability",
    "provider_missing_mask",
    "provider_stale_mask",
    "provider_source_availability_vector",
    "ppo_provider_feature_mask_count",
    "masa_provider_feature_mask_count",
)


def _premium_context_from_features(
    *,
    example: TrainingExample,
    trust_row: dict[str, Any],
    feature_values: dict[str, Any],
    fields: tuple[str, ...],
    context_type: str,
    missing_tokens: tuple[str, ...],
) -> dict[str, Any]:
    values = {field: feature_values.get(field) for field in fields if feature_values.get(field) is not None}
    missing = _missing_features_for_tokens(example, trust_row, *missing_tokens)
    if not values and not missing:
        missing = list(fields)
    context: dict[str, Any] = {
        "source": PREMIUM_CONTEXT_SOURCE,
        "context_type": context_type,
        "feature_snapshot_id": example.tensor.feature_snapshot_id,
        "available_at": trust_row.get("available_at") or trust_row.get("source_available_time"),
        "feature_cutoff": trust_row.get("feature_cutoff") or trust_row.get("decision_cutoff"),
        "feature_freshness_state": trust_row.get("feature_freshness_state"),
        "missing_feature_names": missing,
        "missing_mask_applied": bool(missing),
    }
    context.update(values)
    if any(_finite_float(value) is not None for value in values.values()):
        context["status"] = "provided_by_entry_features"
    else:
        context["status"] = "explicitly_missing_from_entry_features"
        context["unavailable_reason"] = f"MISSING_{context_type}_FEATURES"
    return {key: value for key, value in context.items() if value not in (None, "", [], {})}


def _prediction_premium_contexts(example: TrainingExample, trust_row: dict[str, Any]) -> dict[str, Any]:
    feature_values = _entry_feature_values(example, trust_row)
    contexts = {
        "liquidity_context": _premium_context_from_features(
            example=example,
            trust_row=trust_row,
            feature_values=feature_values,
            fields=_LIQUIDITY_CONTEXT_VALUE_FIELDS,
            context_type="LIQUIDITY",
            missing_tokens=("liquid", "depth", "wall", "orderbook"),
        ),
        "liquidity_zone_context": _premium_context_from_features(
            example=example,
            trust_row=trust_row,
            feature_values=feature_values,
            fields=_LIQUIDITY_CONTEXT_VALUE_FIELDS,
            context_type="LIQUIDITY_ZONE",
            missing_tokens=("liquid", "depth", "wall", "orderbook"),
        ),
        "liquidation_distance_context": _premium_context_from_features(
            example=example,
            trust_row=trust_row,
            feature_values=feature_values,
            fields=_LIQUIDATION_CONTEXT_VALUE_FIELDS,
            context_type="LIQUIDATION",
            missing_tokens=("liquidation", "liq"),
        ),
        "liquidation_context": _premium_context_from_features(
            example=example,
            trust_row=trust_row,
            feature_values=feature_values,
            fields=_LIQUIDATION_CONTEXT_VALUE_FIELDS,
            context_type="LIQUIDATION",
            missing_tokens=("liquidation", "liq"),
        ),
        "microstructure_context": _premium_context_from_features(
            example=example,
            trust_row=trust_row,
            feature_values=feature_values,
            fields=_MICROSTRUCTURE_CONTEXT_VALUE_FIELDS,
            context_type="MICROSTRUCTURE",
            missing_tokens=("microstructure", "orderbook", "spread", "depth", "tape", "flow"),
        ),
        "oi_funding_context": _premium_context_from_features(
            example=example,
            trust_row=trust_row,
            feature_values=feature_values,
            fields=_OI_FUNDING_CONTEXT_VALUE_FIELDS,
            context_type="OI_FUNDING",
            missing_tokens=("funding", "open_interest", "long_short", "oi_"),
        ),
        "public_intel_context": _premium_context_from_features(
            example=example,
            trust_row=trust_row,
            feature_values=feature_values,
            fields=_PUBLIC_INTEL_CONTEXT_VALUE_FIELDS,
            context_type="PUBLIC_INTEL",
            missing_tokens=("public", "news", "sentiment", "breadth", "social", "fear_greed"),
        ),
    }
    sources: dict[str, str] = {}
    missing_contexts: list[str] = []
    compact_features: dict[str, Any] = {}
    for field, value_fields, _label, required_real_values in _PREMIUM_CONTEXT_REQUIREMENTS:
        context = contexts[field]
        has_values = any(_finite_float(context.get(name)) is not None for name in value_fields)
        if has_values:
            sources[field] = str(context.get("source") or PREMIUM_CONTEXT_SOURCE)
            compact_features.update({name: context[name] for name in value_fields if context.get(name) is not None})
        elif context.get("missing_mask_applied") is True:
            sources[field] = f"{context.get('source') or PREMIUM_CONTEXT_SOURCE}:explicit_missing_mask"
            if required_real_values:
                missing_contexts.append(field)
        else:
            missing_contexts.append(field)
    liquidation_context = contexts["liquidation_distance_context"]
    liquidation_ready = any(
        _finite_float(liquidation_context.get(name)) is not None
        for name in _LIQUIDATION_CONTEXT_VALUE_FIELDS
    )
    snapshot = {
        "feature_snapshot_id": example.tensor.feature_snapshot_id,
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "features": compact_features,
        "feature_cutoff": trust_row.get("feature_cutoff") or trust_row.get("decision_cutoff"),
        "available_at": trust_row.get("available_at") or trust_row.get("source_available_time"),
        "generated_at": trust_row.get("generated_at") or trust_row.get("created_at"),
        "feature_freshness_state": trust_row.get("feature_freshness_state"),
        "missing_feature_flags": list(example.tensor.missing_feature_names),
        "source": PREMIUM_CONTEXT_SOURCE,
    }
    return {
        **contexts,
        "entry_feature_snapshot_id": example.tensor.feature_snapshot_id,
        "entry_feature_snapshot": {key: value for key, value in snapshot.items() if value not in (None, "", [], {})},
        "premium_ingestor_context_sources": sources,
        "premium_ingestor_missing_contexts": sorted(set(missing_contexts)),
        "premium_ingestor_context_status": (
            "PREMIUM_CONTEXT_READY"
            if not missing_contexts
            else "PREMIUM_CONTEXT_PARTIAL_WITH_EXPLICIT_MASKS"
        ),
        "liquidation_engine_context_status": (
            "LIQUIDATION_ENGINE_CONTEXT_READY" if liquidation_ready else "LIQUIDATION_ENGINE_CONTEXT_MISSING"
        ),
    }


def build_prediction_payload(
    *,
    example: TrainingExample,
    model_output: ModelForwardResult,
    checkpoint: CheckpointManifest | None,
    round_trip_cost_bps: float,
    min_data_coverage_percent: float,
    min_confidence_calibrated: float,
    min_edge_after_cost_bps: float,
) -> dict[str, Any]:
    tensor = example.tensor
    generated_utc = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    generated_est = _est_iso()
    selected_action = str(model_output.selected_action or "hold").strip().lower()
    if selected_action == "long":
        expected_after_cost = float(model_output.expected_move_bps - abs(round_trip_cost_bps))
    elif selected_action == "short":
        expected_after_cost = float(model_output.expected_move_bps + abs(round_trip_cost_bps))
    else:
        expected_after_cost = 0.0
    directional_edge_aligned = (
        (selected_action == "long" and expected_after_cost > 0.0)
        or (selected_action == "short" and expected_after_cost < 0.0)
    )
    prediction_id = _prediction_id(
        example.symbol,
        example.timeframe,
        tensor.tensor_id,
        model_output.model_id,
    )
    signal_id = "sig_" + prediction_id
    paper_fill_allowed = (
        tensor.data_coverage_percent >= min_data_coverage_percent
        and model_output.confidence_calibrated >= min_confidence_calibrated
        and directional_edge_aligned
        and abs(expected_after_cost) >= min_edge_after_cost_bps
    )
    block_reasons: list[str] = []
    if selected_action not in {"long", "short"}:
        block_reasons.append("action_not_directional")
    if tensor.data_coverage_percent < min_data_coverage_percent:
        block_reasons.append("data_coverage_below_threshold")
    if model_output.confidence_calibrated < min_confidence_calibrated:
        block_reasons.append("confidence_below_threshold")
    if selected_action in {"long", "short"} and not directional_edge_aligned:
        block_reasons.append("expected_move_after_cost_direction_mismatch")
    if abs(expected_after_cost) < min_edge_after_cost_bps:
        block_reasons.append("expected_move_after_cost_below_threshold")
    action_diagnostics = action_policy_diagnostics(
        selected_action=selected_action,
        action_probabilities=model_output.action_probabilities,
        expected_move_bps=model_output.expected_move_bps,
        round_trip_cost_bps=round_trip_cost_bps,
        min_edge_after_cost_bps=min_edge_after_cost_bps,
    )
    integrity = _market_state_fields_from_example(example, prediction_id)
    trust_row = dict(example.trust_row or {})
    provider_mask_context = _provider_mask_context(example, trust_row)
    premium_contexts = _prediction_premium_contexts(example, trust_row)
    trust_reject_reasons = [str(reason) for reason in (trust_row.get("reject_reasons") or []) if str(reason)]
    feature_hash = trust_row.get("feature_vector_hash") or tensor.tensor_id
    timestamp_source_hash_material = {
        "all_tf_candle_timestamps": list(trust_row.get("all_tf_candle_timestamps") or []),
        "all_source_event_times": list(trust_row.get("all_source_event_times") or []),
    }
    source_hashes = dict(trust_row.get("source_hashes") or {})
    source_hashes.update(
        {
            "feature_vector_hash": feature_hash,
            "input_feature_hash": feature_hash,
            "feature_tensor_id": tensor.tensor_id,
            "feature_names_hash": hashlib.sha256(
                json.dumps(list(tensor.feature_names), sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "source_timestamp_hash": hashlib.sha256(
                json.dumps(timestamp_source_hash_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }
    )
    replay_snapshot, replay_reasons = _trusted_replay_snapshot(
        prediction_id=prediction_id,
        signal_id=signal_id,
        example=example,
        model_output=model_output,
        trust_row=trust_row,
        checkpoint=checkpoint,
        source_hashes=source_hashes,
    )
    replay_snapshot_id = None
    if isinstance(replay_snapshot, dict):
        replay_snapshot_id = replay_snapshot.get("decision_id") or replay_snapshot.get("replay_snapshot_id")
    for reason in replay_reasons:
        block_reasons.append(f"replay_snapshot:{reason}")
    if integrity["valid_for_prediction"] is not True:
        block_reasons.append("market_state_invalid_for_prediction")
    if integrity["valid_for_paper"] is not True:
        block_reasons.append("market_state_invalid_for_paper")
    for reason in trust_reject_reasons:
        block_reasons.append(f"training_trust:{reason}")
    for reason in integrity["market_state_reject_reasons"]:
        block_reasons.append(f"market_state:{reason}")
    paper_fill_allowed = (
        paper_fill_allowed
        and integrity["valid_for_prediction"] is True
        and integrity["valid_for_paper"] is True
        and str(example.row_classification).upper() != "MARKET_STATE_REJECTED"
        and not trust_reject_reasons
        and not replay_reasons
    )
    routes_to_orchestrator = (
        paper_fill_allowed
        and integrity["valid_for_orchestrator"] is True
        and integrity["valid_for_risk"] is True
    )
    payload = {
        "prediction_id": prediction_id,
        "signal_id": signal_id,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "generated_at": generated_utc,
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "selected_action": model_output.selected_action,
        "selected_action_index": model_output.selected_action_index,
        "action_labels": list(ACTION_LABELS),
        "action_probabilities": list(model_output.action_probabilities),
        **action_diagnostics,
        "expected_move_bps": model_output.expected_move_bps,
        "expected_move_after_cost_bps": expected_after_cost,
        "confidence_raw": model_output.confidence_raw,
        "confidence_calibrated": model_output.confidence_calibrated,
        "confidence_calibration": model_output.calibration,
        "confidence_source": "REAL_MODEL",
        "masa_confidence_source": "REAL_MODEL",
        "ppo_confidence_source": "REAL_MODEL",
        "combined_confidence_source": "REAL_MODEL",
        "confidence_scale": "0-1 probability",
        "proof_only": False,
        "model_consumable": True,
        "paper_intent_consumable": True,
        "routeability_candidate": True,
        "policy_value": model_output.policy_value,
        "masa_signal": model_output.masa_signal,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "feature_tensor_id": tensor.tensor_id,
        "feature_cutoff": trust_row.get("feature_cutoff") or trust_row.get("decision_cutoff"),
        "available_at": trust_row.get("available_at") or trust_row.get("source_available_time"),
        "all_tf_candle_timestamps": list(trust_row.get("all_tf_candle_timestamps") or []),
        "all_source_event_times": list(trust_row.get("all_source_event_times") or []),
        "feature_vector_hash": feature_hash,
        "source_hashes": source_hashes,
        "data_coverage_percent": tensor.data_coverage_percent,
        "missing_feature_count": (
            trust_row.get("missing_feature_count")
            if trust_row.get("missing_feature_lineage_source") == "feature_snapshot_decision_time_flags"
            else len(tensor.missing_feature_names)
        ),
        "stale_feature_count": (
            trust_row.get("stale_feature_count")
            if trust_row.get("missing_feature_lineage_source") == "feature_snapshot_decision_time_flags"
            else len(tensor.stale_feature_names)
        ),
        "missing_feature_names": (
            list(trust_row.get("missing_feature_names") or [])
            if trust_row.get("missing_feature_lineage_source") == "feature_snapshot_decision_time_flags"
            else list(tensor.missing_feature_names)
        ),
        "stale_feature_names": (
            list(trust_row.get("stale_feature_names") or [])
            if trust_row.get("missing_feature_lineage_source") == "feature_snapshot_decision_time_flags"
            else list(tensor.stale_feature_names)
        ),
        "missing_feature_lineage_source": trust_row.get("missing_feature_lineage_source")
        or "tensor_reconstruction_masks",
        "tensor_unreconstructed_feature_names": list(tensor.missing_feature_names),
        "tensor_unreconstructed_feature_count": len(tensor.missing_feature_names),
        "source_availability_vector": list(tensor.source_availability_vector),
        "feature_names": list(tensor.feature_names),
        "source_labels": list(tensor.source_labels),
        **provider_mask_context,
        **premium_contexts,
        "trainer_source": TRAINER_SOURCE,
        "model_source": MODEL_SOURCE,
        "model_version": MODEL_SOURCE,
        "checkpoint_source": CHECKPOINT_SOURCE,
        "checkpoint_id": checkpoint.checkpoint_id if checkpoint else "v2_hybrid_checkpoint_manifest_pending",
        "checkpoint_manifest_path": checkpoint.path if checkpoint else None,
        "model_id": model_output.model_id,
        "model_device": model_output.device,
        "cuda_active": model_output.cuda_active,
        "model_tensors_device_verified": model_output.model_tensors_device_verified,
        "paper_fill_allowed": paper_fill_allowed,
        "paper_fill_gate_status": "PAPER_SHADOW_GATE_OPEN" if paper_fill_allowed else "PAPER_SHADOW_GATE_BLOCKED",
        "paper_fill_gate_block_reasons": sorted(set(block_reasons)),
        "routes_to_orchestrator": routes_to_orchestrator,
        "routes_to_orchestrator_reason": "PAPER_FILL_ALLOWED"
        if routes_to_orchestrator
        else "PAPER_FILL_GATE_BLOCKED",
        **integrity,
        "replay_snapshot_required": True,
        "replay_snapshot_ready": not replay_reasons,
        "replay_snapshot_block_reasons": sorted(set(replay_reasons)),
        "replay_snapshot": replay_snapshot,
        "replay_snapshot_id": replay_snapshot_id,
        "replay_snapshot_key": f"v2:replay:snapshots:{prediction_id}",
        "replay_snapshot_write_success": False,
        "decision_id": trust_row.get("decision_id") or prediction_id,
        "mtf_snapshot_id": trust_row.get("mtf_snapshot_id"),
        "mtf_snapshot_valid": trust_row.get("mtf_snapshot_valid"),
        "decision_time": generated_utc,
        "feature_decision_time": trust_row.get("decision_time_est") or trust_row.get("decision_time"),
        "source_candle_timestamps": list(trust_row.get("all_tf_candle_timestamps") or []),
        "input_feature_hash": feature_hash,
        "prediction_eligible": paper_fill_allowed,
        "risk_eligible": routes_to_orchestrator,
        "paper_eligible": paper_fill_allowed,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "exchange_mutation": False,
        "trainer_direct_trading": False,
    }
    payload = attach_runtime_trust_metadata(
        payload,
        decision_id=payload.get("decision_id"),
        prediction_id=prediction_id,
        mtf_snapshot_id=payload.get("mtf_snapshot_id"),
        replay_snapshot_id=payload.get("replay_snapshot_id"),
    )
    contract = validate_prediction_trust_contract(payload)
    payload["trust_gate_result"] = contract.to_dict()
    if not contract.allowed:
        payload = mark_runtime_trust_denied(payload, contract)
        payload["paper_fill_gate_status"] = "PAPER_SHADOW_GATE_BLOCKED"
        payload["paper_fill_gate_block_reasons"] = sorted(
            set(payload.get("paper_fill_gate_block_reasons") or [])
            | {f"runtime_trust:{reason}" for reason in contract.reject_reasons}
        )
        payload["routes_to_orchestrator_reason"] = "TRUST_GATE_BLOCKED"
    return payload


def is_publishable(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if any(field not in payload for field in REQUIRED_PREDICTION_FIELDS):
        return False
    if payload["trainer_source"] != TRAINER_SOURCE:
        return False
    if payload["model_source"] != MODEL_SOURCE:
        return False
    if payload["live_gate"] != LIVE_GATE_BLOCKED:
        return False
    if payload["live_symbols"] != []:
        return False
    if payload.get("exchange_mutation") is not False:
        return False
    if payload.get("trainer_direct_trading") is not False:
        return False
    return True


def _requires_replay_snapshot_write(payload: dict[str, Any]) -> bool:
    return any(
        payload.get(field) is True
        for field in (
            "paper_fill_allowed",
            "routes_to_orchestrator",
            "prediction_eligible",
            "risk_eligible",
            "paper_eligible",
            "routed_to_paper",
            "pre_trade_allowed",
        )
    )


class V2HybridPredictionPublisher:
    def __init__(self, *, io: V2OnlyJsonIO | None = None) -> None:
        self.io = io or V2OnlyJsonIO(client=None)

    def publish_prediction(self, payload: dict[str, Any]) -> bool:
        if not is_publishable(payload):
            return False
        payload = dict(payload)
        archive_record = build_archive_record_from_prediction_payload(payload)
        if archive_record is not None:
            try:
                archived = append_snapshot(archive_record, update_checksum_manifest=False)
                payload["durable_feature_snapshot_archive_write_success"] = True
                payload["durable_feature_snapshot_archive_snapshot_id"] = archived.snapshot_id
                payload["durable_feature_snapshot_archive_content_sha256"] = archived.content_sha256
                payload["durable_feature_snapshot_archive_blob_path"] = str(archived.blob_path)
            except SnapshotArchiveError as exc:
                payload["durable_feature_snapshot_archive_write_success"] = False
                payload["durable_feature_snapshot_archive_error"] = str(exc)
                reasons = list(payload.get("paper_fill_gate_block_reasons") or [])
                reasons.append(f"durable_snapshot_archive:{type(exc).__name__}")
                payload["paper_fill_gate_block_reasons"] = sorted(set(str(reason) for reason in reasons))
                payload["paper_fill_allowed"] = False
                payload["routes_to_orchestrator"] = False
                payload["prediction_eligible"] = False
                payload["risk_eligible"] = False
                payload["paper_eligible"] = False
        if payload.get("replay_snapshot_required") is True:
            snapshot = payload.get("replay_snapshot")
            if not isinstance(snapshot, dict) or payload.get("replay_snapshot_ready") is not True:
                if _requires_replay_snapshot_write(payload):
                    return False
                contract = validate_prediction_trust_contract(payload)
                payload["trust_gate_result"] = contract.to_dict()
                key = PREDICTION_KEY_TEMPLATE.format(
                    symbol=payload["symbol"],
                    timeframe=payload["timeframe"],
                )
                return self.io.set_json(key, payload)
            snapshot_key = f"v2:replay:snapshots:{payload['prediction_id']}"
            if not self.io.set_json(snapshot_key, snapshot, ex=86400):  # 24h TTL
                return False
            payload["replay_snapshot_write_success"] = True
            payload["replay_snapshot_key"] = snapshot_key
            payload["replay_snapshot_id"] = (
                snapshot.get("decision_id")
                or snapshot.get("replay_snapshot_id")
                or payload.get("replay_snapshot_id")
            )
            contract = validate_prediction_trust_contract(payload)
            payload["trust_gate_result"] = contract.to_dict()
            if not contract.allowed:
                return False
        key = PREDICTION_KEY_TEMPLATE.format(
            symbol=payload["symbol"],
            timeframe=payload["timeframe"],
        )
        return self.io.set_json(key, payload)

    def publish_status(self, *, status: dict[str, Any], metrics: dict[str, Any]) -> None:
        heartbeat = {
            "generated_est": _est_iso(),
            "trainer_source": TRAINER_SOURCE,
            "paper_shadow_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        }
        feature_schema_status = {
            "schema_version": "v2_trainer_feature_schema_status_v1",
            "generated_est": _est_iso(),
            "status": status.get("feature_schema_status") or "UNKNOWN",
            "feature_dim": status.get("feature_dim"),
            "input_dim": status.get("input_dim"),
            "expected_input_dim": status.get("expected_input_dim"),
            "checkpoint_guard_active": status.get("checkpoint_guard_active") is True,
            "stale_checkpoints_rejected": status.get("stale_checkpoints_rejected") is True,
            "checkpoint_shape_guard": status.get("checkpoint_shape_guard"),
            "ppo_provider_feature_mask_count": status.get("ppo_provider_feature_mask_count"),
            "masa_provider_feature_mask_count": status.get("masa_provider_feature_mask_count"),
            "provider_feature_names": status.get("provider_feature_names") or [],
            "provider_missing_masks_required": True,
            "provider_stale_masks_required": True,
            "provider_source_availability_required": True,
            "paper_shadow_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
            "places_real_order": False,
        }
        self.io.set_json(REDIS_HEARTBEAT_KEY, heartbeat)
        self.io.set_json(REDIS_STATUS_KEY, status)
        self.io.set_json(REDIS_METRICS_KEY, metrics)
        self.io.set_json("v2:trainer:feature_schema_status", feature_schema_status)

    def publish_lineage(
        self,
        *,
        prediction_payload: dict[str, Any],
        min_confidence_calibrated: float,
        min_data_coverage_percent: float,
        risk_caps_configured: bool,
    ) -> dict[str, Any]:
        prediction_record = to_trainer_prediction_record(prediction_payload)
        orchestrator_record = assemble_orchestrator_decision_record(
            prediction=prediction_record,
            low_confidence_threshold=float(min_confidence_calibrated),
            now_ms_clock=_now_ms,
        )
        risk_record = native_risk_decision_from_orchestrator(
            orchestrator_record,
            prediction_payload=prediction_payload,
            min_data_coverage_percent=min_data_coverage_percent,
            risk_caps_configured=risk_caps_configured,
        )
        paper_entry = assemble_paper_execution_ledger_entry(
            decision=risk_record,
            now_ms_clock=_now_ms,
        )
        lineage_contract = validate_prediction_trust_contract(
            prediction_payload,
            require_replay_write=True,
        )
        decision_id = prediction_payload.get("decision_id") or orchestrator_record.decision_id
        prediction_id = prediction_record.prediction_id
        signal_id = str(prediction_payload.get("signal_id") or ("sig_" + prediction_id))
        mtf_snapshot_id = prediction_payload.get("mtf_snapshot_id")
        replay_snapshot_id = prediction_payload.get("replay_snapshot_id")
        orchestrator_dict = attach_runtime_trust_metadata(
            dataclasses.asdict(orchestrator_record),
            decision_id=decision_id,
            prediction_id=prediction_id,
            mtf_snapshot_id=mtf_snapshot_id,
            replay_snapshot_id=replay_snapshot_id,
        )
        risk_dict = attach_runtime_trust_metadata(
            dataclasses.asdict(risk_record),
            decision_id=decision_id,
            prediction_id=prediction_id,
            mtf_snapshot_id=mtf_snapshot_id,
            replay_snapshot_id=replay_snapshot_id,
        )
        paper_entry_dict = attach_runtime_trust_metadata(
            dataclasses.asdict(paper_entry),
            decision_id=decision_id,
            prediction_id=prediction_id,
            mtf_snapshot_id=mtf_snapshot_id,
            replay_snapshot_id=replay_snapshot_id,
        )
        for record in (orchestrator_dict, risk_dict, paper_entry_dict):
            record["signal_id"] = signal_id
            record["feature_snapshot_id"] = prediction_payload.get("feature_snapshot_id")
            record["feature_cutoff"] = prediction_payload.get("feature_cutoff")
            record["available_at"] = prediction_payload.get("available_at")
            record["decision_time"] = prediction_payload.get("decision_time")
            record["symbol"] = prediction_payload.get("symbol")
            record["timeframe"] = prediction_payload.get("timeframe")
            record["selected_action"] = prediction_payload.get("selected_action")
            record["model_version"] = prediction_payload.get("model_version") or prediction_payload.get("model_source")
            record["checkpoint_id"] = prediction_payload.get("checkpoint_id")
            record["source_hashes"] = dict(prediction_payload.get("source_hashes") or {})
            record["feature_vector_hash"] = prediction_payload.get("feature_vector_hash")
            record["all_tf_candle_timestamps"] = list(prediction_payload.get("all_tf_candle_timestamps") or [])
            record["all_source_event_times"] = list(prediction_payload.get("all_source_event_times") or [])
            record["source_candle_timestamps"] = list(prediction_payload.get("source_candle_timestamps") or [])
            record["input_feature_hash"] = prediction_payload.get("input_feature_hash")
            record["replay_snapshot_key"] = prediction_payload.get("replay_snapshot_key")
            record["replay_snapshot_write_success"] = prediction_payload.get("replay_snapshot_write_success")
            record["trust_gate_result"] = lineage_contract.to_dict()
            for field in PROVIDER_LINEAGE_FIELDS:
                if field in prediction_payload:
                    record[field] = prediction_payload.get(field)
        if not lineage_contract.allowed:
            orchestrator_dict = mark_runtime_trust_denied(orchestrator_dict, lineage_contract)
            risk_dict = mark_runtime_trust_denied(risk_dict, lineage_contract)
            paper_entry_dict = mark_runtime_trust_denied(paper_entry_dict, lineage_contract)
        paper_intent_id = "pei_" + risk_record.risk_decision_id
        signal_payload = {
            "signal_id": signal_id,
            "generated_est": _est_iso(),
            "prediction_id": prediction_record.prediction_id,
            "trainer_prediction_id": prediction_record.prediction_id,
            "risk_decision_id": risk_record.risk_decision_id,
            "orchestrator_decision_id": orchestrator_record.decision_id,
            "paper_intent_id": paper_intent_id,
            "paper_ledger_id": paper_entry_dict["paper_trade_id"],
            "symbol": prediction_payload["symbol"],
            "timeframe": prediction_payload["timeframe"],
            "selected_action": prediction_payload["selected_action"],
            "expected_move_after_cost_bps": prediction_payload["expected_move_after_cost_bps"],
            "confidence_calibrated": prediction_payload["confidence_calibrated"],
            "data_coverage_percent": prediction_payload["data_coverage_percent"],
            "paper_fill_result": paper_entry_dict["ledger_action"],
            "pnl_outcome": None,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        }
        signal_payload = attach_runtime_trust_metadata(
            signal_payload,
            decision_id=decision_id,
            prediction_id=prediction_id,
            mtf_snapshot_id=mtf_snapshot_id,
            replay_snapshot_id=replay_snapshot_id,
        )
        signal_payload["feature_snapshot_id"] = prediction_payload.get("feature_snapshot_id")
        signal_payload["feature_cutoff"] = prediction_payload.get("feature_cutoff")
        signal_payload["available_at"] = prediction_payload.get("available_at")
        signal_payload["decision_time"] = prediction_payload.get("decision_time")
        signal_payload["model_version"] = prediction_payload.get("model_version") or prediction_payload.get("model_source")
        signal_payload["checkpoint_id"] = prediction_payload.get("checkpoint_id")
        signal_payload["source_hashes"] = dict(prediction_payload.get("source_hashes") or {})
        signal_payload["feature_vector_hash"] = prediction_payload.get("feature_vector_hash")
        signal_payload["all_tf_candle_timestamps"] = list(prediction_payload.get("all_tf_candle_timestamps") or [])
        signal_payload["all_source_event_times"] = list(prediction_payload.get("all_source_event_times") or [])
        signal_payload["source_candle_timestamps"] = list(prediction_payload.get("source_candle_timestamps") or [])
        signal_payload["input_feature_hash"] = prediction_payload.get("input_feature_hash")
        signal_payload["replay_snapshot_key"] = prediction_payload.get("replay_snapshot_key")
        signal_payload["replay_snapshot_write_success"] = prediction_payload.get("replay_snapshot_write_success")
        # PPO on-policy lineage: entry-time policy outputs from the SAME
        # forward pass that produced selected_action. Never recomputed
        # post-hoc; downstream paper fills copy these so closed rows can
        # become on-policy PPO training rows (old_log_prob/old_value).
        _entry_action_probabilities = list(
            prediction_payload.get("action_probabilities") or []
        )
        _entry_selected_probability = _finite_float(
            prediction_payload.get("selected_action_probability")
        )
        signal_payload["action_labels"] = list(
            prediction_payload.get("action_labels") or list(ACTION_LABELS)
        )
        signal_payload["action_probabilities"] = _entry_action_probabilities
        signal_payload["selected_action_index"] = prediction_payload.get(
            "selected_action_index"
        )
        signal_payload["selected_action_probability"] = _entry_selected_probability
        signal_payload["selected_action_log_prob"] = (
            math.log(_entry_selected_probability)
            if _entry_selected_probability is not None
            and _entry_selected_probability > 0.0
            else None
        )
        signal_payload["policy_value"] = _finite_float(
            prediction_payload.get("policy_value")
        )
        signal_payload["entry_policy_fields_source"] = (
            "V2_NATIVE_CUDA_TRAINER_ENTRY_FORWARD_PASS"
        )
        signal_payload["trust_gate_result"] = lineage_contract.to_dict()
        for field in PROVIDER_LINEAGE_FIELDS:
            if field in prediction_payload:
                signal_payload[field] = prediction_payload.get(field)
        if not lineage_contract.allowed:
            signal_payload = mark_runtime_trust_denied(signal_payload, lineage_contract)
        self.io.set_json(ORCHESTRATOR_DECISIONS_KEY, orchestrator_dict)
        self.io.set_json(RISK_DECISIONS_KEY, risk_dict)
        # Per-ID immutable decision records + candidate/signal indexes.
        # Last-write-wins preview keys above stay for dashboards only; the
        # paper fill gate dereferences THESE by the exact IDs the signal
        # carries (operator mission 2026-07-10). TTL outlives the 900s signal
        # staleness window with margin.
        _decision_record_ttl = 2 * 60 * 60
        _decision_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=_decision_record_ttl)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        _decision_common = {
            "candidate_id": (
                signal_payload.get("candidate_id")
                or prediction_record.prediction_id
            ),
            "signal_id": signal_id,
            "prediction_id": prediction_record.prediction_id,
            "symbol": prediction_payload.get("symbol"),
            "timeframe": prediction_payload.get("timeframe"),
            "side": prediction_payload.get("selected_action"),
            "feature_vector_hash": prediction_payload.get("feature_vector_hash"),
            "feature_cutoff": prediction_payload.get("feature_cutoff"),
            "available_at": prediction_payload.get("available_at"),
            "decision_time": prediction_payload.get("decision_time"),
            "generated_utc": prediction_payload.get("generated_utc"),
            "expires_at": _decision_expires_at,
            "model_version": prediction_payload.get("model_version"),
            "checkpoint_hash": prediction_payload.get("checkpoint_id"),
            "provider_hashes": dict(prediction_payload.get("source_hashes") or {}),
            "routes_to_live": False,
            "places_real_order": False,
            "live_gate": LIVE_GATE_BLOCKED,
        }
        risk_per_id_record = {
            **risk_dict,
            **_decision_common,
            "schema_version": "v2_per_id_risk_decision_record_v1",
            "risk_decision_id": risk_record.risk_decision_id,
            "decision": risk_dict.get("risk_action") or risk_dict.get("decision"),
            "status": risk_dict.get("status") or risk_dict.get("risk_action"),
            "reasons": list(
                risk_dict.get("reasons")
                or risk_dict.get("risk_reasons")
                or []
            ),
            "max_loss_usd": risk_dict.get("max_loss_usd"),
            "liquidation_buffer_usd": risk_dict.get("liquidation_buffer_usd"),
            "position_limit": risk_dict.get("position_limit"),
        }
        orchestrator_per_id_record = {
            **orchestrator_dict,
            **_decision_common,
            "schema_version": "v2_per_id_orchestrator_decision_record_v1",
            "orchestrator_decision_id": orchestrator_record.decision_id,
            "decision": orchestrator_dict.get("orchestrator_action")
            or orchestrator_dict.get("decision"),
            "orchestrator_action": orchestrator_dict.get("orchestrator_action")
            or orchestrator_dict.get("decision_action")
            or orchestrator_dict.get("decision"),
            "status": orchestrator_dict.get("status")
            or orchestrator_dict.get("orchestrator_action"),
            "reasons": list(orchestrator_dict.get("reasons") or []),
            "route": orchestrator_dict.get("route") or "paper_only",
        }
        self.io.set_json(
            f"v2:decision:risk:{risk_record.risk_decision_id}",
            risk_per_id_record,
            ex=_decision_record_ttl,
        )
        # Legacy lineage surfaces stamp the same decision as
        # rd_{prediction_hash} (no dec_ segment); publish the identical
        # immutable record under that alias so every stamped id dereferences.
        if str(risk_record.risk_decision_id).startswith("rd_dec_"):
            _risk_alias_id = "rd_" + str(risk_record.risk_decision_id)[len("rd_dec_"):]
            self.io.set_json(
                f"v2:decision:risk:{_risk_alias_id}",
                {**risk_per_id_record, "alias_of": risk_record.risk_decision_id},
                ex=_decision_record_ttl,
            )
        self.io.set_json(
            f"v2:decision:orchestrator:{orchestrator_record.decision_id}",
            orchestrator_per_id_record,
            ex=_decision_record_ttl,
        )
        _decision_index = {
            "risk_decision_key": f"v2:decision:risk:{risk_record.risk_decision_id}",
            "orchestrator_decision_key": (
                f"v2:decision:orchestrator:{orchestrator_record.decision_id}"
            ),
            "risk_decision_id": risk_record.risk_decision_id,
            "orchestrator_decision_id": orchestrator_record.decision_id,
            "prediction_id": prediction_record.prediction_id,
            "signal_id": signal_id,
            "generated_utc": prediction_payload.get("generated_utc"),
            "expires_at": _decision_expires_at,
        }
        self.io.set_json(
            f"v2:decision:index:by_candidate:{_decision_common['candidate_id']}",
            _decision_index,
            ex=_decision_record_ttl,
        )
        self.io.set_json(
            f"v2:decision:index:by_signal:{signal_id}",
            _decision_index,
            ex=_decision_record_ttl,
        )
        self.io.set_json(PAPER_LEDGER_KEY, paper_entry_dict)
        self.io.set_json(PAPER_INTENTS_KEY, signal_payload)
        self.io.set_json(PAPER_POSITIONS_KEY, {"generated_est": _est_iso(), "paper_shadow_only": True})
        self.io.set_json(PAPER_BLOCK_REASONS_KEY, {"block_reasons": prediction_payload["paper_fill_gate_block_reasons"]})
        self.io.set_json(PAPER_SIGNAL_LINEAGE_KEY, signal_payload)
        self.io.set_json(
            PAPER_SIGNAL_KEY_TEMPLATE.format(symbol=prediction_payload["symbol"]),
            signal_payload,
        )
        self.io.set_json(
            PAPER_SIGNAL_TIMEFRAME_KEY_TEMPLATE.format(
                symbol=prediction_payload["symbol"],
                timeframe=prediction_payload["timeframe"],
            ),
            signal_payload,
        )
        return {
            "trainer_prediction_record": dataclasses.asdict(prediction_record),
            "orchestrator_decision_record": orchestrator_dict,
            "risk_decision_record": risk_dict,
            "paper_execution_ledger_entry": paper_entry_dict,
            "paper_signal_lineage": signal_payload,
        }


def to_trainer_prediction_record(payload: dict[str, Any]):
    direction = direction_from_action(str(payload["selected_action"]))
    if payload["missing_feature_count"] > 0:
        freshness = PREDICTION_FRESHNESS_MISSING
        age = None
    elif payload["stale_feature_count"] > 0:
        freshness = PREDICTION_FRESHNESS_STALE
        age = 0
    else:
        freshness = PREDICTION_FRESHNESS_FRESH
        age = 0
    feature_pairs = list(zip(payload.get("feature_names") or (), payload.get("source_availability_vector") or ()))
    top_pos = tuple(str(name) for name, avail in feature_pairs if avail)[:4]
    top_neg = tuple(str(name) for name in payload.get("missing_feature_names") or ())[:4]
    top_neg = tuple(name for name in top_neg if name not in top_pos)
    return assemble_prediction_record(
        prediction_id=payload["prediction_id"],
        feature_snapshot_id=str(payload["feature_snapshot_id"])[:128],
        symbol=payload["symbol"],
        model_version=MODEL_SOURCE,
        checkpoint_id=str(payload["checkpoint_id"])[:128],
        direction=direction,
        confidence_raw=float(payload["confidence_raw"]),
        confidence_calibrated=float(payload["confidence_calibrated"]),
        worker_id="v2_hybrid_cuda_trainer",
        worker_health_status="HEALTHY",
        freshness_flag=freshness,
        source_freshness_age_ms=age,
        top_positive_feature_codes=top_pos,
        top_negative_feature_codes=top_neg,
        now_ms_clock=_now_ms,
    )


def native_risk_decision_from_orchestrator(
    decision: OrchestratorDecisionRecord,
    *,
    prediction_payload: dict[str, Any],
    min_data_coverage_percent: float,
    risk_caps_configured: bool,
) -> RiskDecisionRecord:
    tradable = decision.decision_action in {
        DECISION_ACTION_OPEN_LONG,
        DECISION_ACTION_OPEN_SHORT,
    }
    data_coverage_ok = float(prediction_payload["data_coverage_percent"]) >= float(min_data_coverage_percent)
    calibration_ok = prediction_payload.get("confidence_calibrated") is not None
    if tradable and (not risk_caps_configured or not data_coverage_ok or not calibration_ok):
        return RiskDecisionRecord(
            risk_decision_id="rd_" + decision.decision_id,
            decision_id=decision.decision_id,
            prediction_id=decision.prediction_id,
            feature_snapshot_id=decision.feature_snapshot_id,
            symbol=decision.symbol,
            risk_decision_ts_ms=_now_ms(),
            risk_action=RISK_DECISION_ACTION_DENY,
            risk_reason_code=RISK_DECISION_REASON_DENY_DEFAULT,
            input_decision_action=decision.decision_action,
            input_decision_reason_code=decision.decision_reason_code,
            live_blocked=True,
        )
    return assemble_risk_decision_record(
        decision=decision,
        now_ms_clock=_now_ms,
        **_risk_gate_kwargs_from_prediction_payload(prediction_payload),
    )


def build_operator_dashboard_payload(
    *,
    predictions: list[dict[str, Any]],
    lineages: list[dict[str, Any]],
    status: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    generated_est = _est_iso()
    return {
        "schema_version": "v2_native_rl_masa_ppo_cuda_trainer_operator_dashboard_v1",
        "generated_est": generated_est,
        "generated_at": generated_est,
        "go_no_go": TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
        "safety_scoreboard": safety_scoreboard(),
        "trainer": status,
        "metrics": metrics,
        "prediction_count": len(predictions),
        "lineage_count": len(lineages),
        "predictions_by_symbol": predictions,
        "prediction_samples": predictions[:64],
        "lineage_samples": lineages,
        "lineage_sample_preview": lineages[:16],
        "live_switch": {
            "visible": True,
            "enabled": False,
            "disabled_reason": "LIVE_GATE=blocked_human_only; requires operator approval, risk caps, paper/canary edge acceptance, read-only permission probe, exchange mutation safety, live_symbols, and Codex final live PASS",
            "backend_live_enable_callable": False,
        },
    }


def dumps_pretty(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)
