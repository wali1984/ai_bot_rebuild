"""Prediction publisher and decision-lineage adapter for the hybrid trainer."""
from __future__ import annotations

import dataclasses
import copy
import hashlib
import json
import math
import os
import secrets
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    OrchestratorDecisionRecord,
)
from v2.backend.app.domain.risk_gateway.record import (
    RISK_DECISION_ACTION_DENY,
    RISK_DECISION_REASON_DENY_DEFAULT,
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
from v2.backend.app.services.market_state_integrity.replay_snapshot import build_replay_snapshot
from v2.backend.app.services.market_state_integrity.scoring import score_market_state
from v2.backend.app.services.market_state_integrity.trust import (
    attach_runtime_trust_metadata,
    build_market_state_envelope_from_snapshot,
    coerce_market_state_envelope,
    mark_runtime_trust_denied,
    validate_prediction_trust_contract,
)
from v2.backend.app.services.native_trainer.current_cycle_evidence import (
    process_instance_id as local_process_instance_id,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    DURABLE_RECEIPT_LINEAGE_FIELDS,
    EVENT_PUBLISHED,
    BehaviorReceiptArchiveError,
    archive_behavior_receipt,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    append_lifecycle_event as append_behavior_receipt_lifecycle_event,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    append_snapshot,
    build_archive_record_from_prediction_payload,
)
from v2.backend.app.services.orchestrator_decision.service import (
    assemble_orchestrator_decision_record,
)
from v2.backend.app.services.ordinary_paper_admission import (
    microstructure_trust_evidence_rejection_reasons,
)
from v2.backend.app.services.paper_execution_ledger.service import (
    assemble_paper_execution_ledger_entry,
)
from v2.backend.app.services.risk_gateway.service import assemble_risk_decision_record
from v2.backend.app.services.trainer_prediction_output.service import (
    assemble_prediction_record,
)

from .checkpoint import CheckpointManifest
from .confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_HEAD_SCHEMA_VERSION,
    CONFIDENCE_LABEL_SEMANTICS,
)
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
    PAPER_SIGNAL_LINEAGE_KEY,
    PAPER_SIGNAL_TIMEFRAME_KEY_TEMPLATE,
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
from .on_policy_behavior import (
    ADAPTIVE_ON_POLICY_LANE_FORMULA,
    ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION,
    BEHAVIOR_POLICY_LINEAGE_FIELDS,
    ON_POLICY_ACTION_SOURCE,
    ON_POLICY_DISTRIBUTION_CONTRACT,
    ON_POLICY_SAMPLING_MODE,
    U53_DENOMINATOR,
    behavior_receipt_rejection_reasons,
    build_positive_edge_behavior_receipt,
    canonical_sha256,
    exact_cost_provenance_rejection_reasons,
)
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
BEHAVIOR_POLICY_SAMPLING_MODE = "DETERMINISTIC_ARGMAX_ALIGNMENT"
BEHAVIOR_POLICY_DISTRIBUTION_CONTRACT = "EXPECTED_MOVE_ALIGNED_POLICY_V1"
PPO_ON_POLICY_INELIGIBLE_REASON = "DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED"
ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION = (
    "v2_native_trainer_ordinary_paper_scale_free_admission_v1"
)
ORDINARY_PAPER_QUALITY_FORMULA = (
    "(coverage_percent/100)*calibrated_profit_probability*"
    "(abs(after_cost_edge_bps)/(abs(after_cost_edge_bps)+round_trip_cost_bps))"
)
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


def _prediction_id(
    symbol: str,
    timeframe: str,
    tensor_id: str,
    model_id: str,
    *,
    behavior_nonce: str | None = None,
) -> str:
    material = f"{symbol}|{timeframe}|{tensor_id}|{model_id}"
    if behavior_nonce:
        material += f"|{behavior_nonce}"
    h = hashlib.sha256(material.encode()).hexdigest()[:32]
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
        "legacy_min_edge_after_cost_bps_telemetry_only": min_edge,
        "legacy_static_edge_threshold_controls_paper_admission": False,
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
    trust_row = dict(example.trust_row or {})
    row_classification = str(example.row_classification or "").strip().upper()
    explicitly_trainer_consumable = bool(
        row_classification == "TRAINABLE"
        and trust_row.get("accepted_for_training") is True
        and trust_row.get("valid_for_training") is True
        and trust_row.get("trainer_consumable") is True
    )
    row = {
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "prediction_id": prediction_id,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "features": dict(zip(tensor.feature_names, tensor.values)),
        "feature_names": list(tensor.feature_names),
        "generated_at": _est_iso(),
        "feature_freshness_state": "STALE" if tensor.stale_feature_names else "CURRENT",
        # Trainer consumption is a categorical trust decision.  Coverage is
        # retained as telemetry, but no numeric coverage floor may manufacture
        # trust for a row the PIT/data gate did not explicitly accept.
        "trainer_consumable": explicitly_trainer_consumable,
        "trainer_consumable_evidence_source": (
            "EXPLICIT_TRAINABLE_ROW_AND_TRUST_FLAGS"
            if explicitly_trainer_consumable
            else "EXPLICIT_TRUST_EVIDENCE_MISSING_OR_REJECTED"
        ),
        "row_classification": row_classification,
        "missing_feature_count": len(tensor.missing_feature_names),
        "missing_feature_names": list(tensor.missing_feature_names),
        "stale_feature_count": len(tensor.stale_feature_names),
        "stale_feature_names": list(tensor.stale_feature_names),
    }
    if not _has_explicit_market_state_trust_evidence(trust_row):
        return row
    if isinstance(trust_row.get("features"), dict):
        row["features"] = dict(trust_row["features"])
    row["generated_at"] = trust_row.get("generated_at") or trust_row.get("generated_utc") or row["generated_at"]
    row["feature_freshness_state"] = trust_row.get("feature_freshness_state") or row["feature_freshness_state"]
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
    behavior_policy_fields: Mapping[str, Any] | None = None,
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
        "behavior_policy_sampling_mode": BEHAVIOR_POLICY_SAMPLING_MODE,
        "behavior_policy_distribution_contract": (
            BEHAVIOR_POLICY_DISTRIBUTION_CONTRACT
        ),
        "ppo_on_policy_entry_fields_present": False,
        "ppo_on_policy_ineligible_reason": PPO_ON_POLICY_INELIGIBLE_REASON,
        "expected_move_bps": model_output.expected_move_bps,
        "confidence_raw": model_output.confidence_raw,
        "confidence_calibrated": model_output.confidence_calibrated,
        "confidence_calibration": dict(model_output.calibration),
        "policy_value": model_output.policy_value,
        "model_source": MODEL_SOURCE,
        "model_version": MODEL_SOURCE,
        "model_id": model_output.model_id,
        "checkpoint_id": checkpoint.checkpoint_id if checkpoint else "v2_hybrid_checkpoint_manifest_pending",
    }
    if behavior_policy_fields:
        for field in BEHAVIOR_POLICY_LINEAGE_FIELDS:
            if field in behavior_policy_fields:
                value = behavior_policy_fields[field]
                if isinstance(value, dict):
                    prediction[field] = dict(value)
                elif isinstance(value, list):
                    prediction[field] = list(value)
                else:
                    prediction[field] = value
    return build_replay_snapshot(decision_id=str(decision_id), prediction=prediction), reasons


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ordinary_paper_quality_evidence(
    *,
    data_coverage_percent: Any,
    confidence_probability: Any,
    expected_after_cost_bps: Any,
    round_trip_cost_bps: Any,
    selected_action: Any,
) -> tuple[dict[str, Any], list[str]]:
    """Return a scale-free paper sizing weight and structural rejections.

    Exact zero is treated as a no-information boundary, not a market-performance
    threshold.  Every finite positive value remains admissible and contributes
    continuously to the weight.  Scaling edge and cost by the same positive
    factor therefore cannot create an admission cliff or change the weight.
    """

    coverage = _finite_float(data_coverage_percent)
    probability = _finite_float(confidence_probability)
    edge = _finite_float(expected_after_cost_bps)
    cost = _finite_float(round_trip_cost_bps)
    action = str(selected_action or "").strip().lower()
    reasons: list[str] = []
    if coverage is None:
        reasons.append("ordinary_paper_coverage_nonfinite_or_missing")
    elif coverage <= 0.0 or coverage > 100.0:
        reasons.append("ordinary_paper_coverage_outside_positive_percent_range")
    if probability is None:
        reasons.append("ordinary_paper_probability_nonfinite_or_missing")
    elif probability <= 0.0 or probability > 1.0:
        reasons.append("ordinary_paper_probability_outside_positive_unit_interval")
    if cost is None:
        reasons.append("ordinary_paper_round_trip_cost_nonfinite_or_missing")
    elif cost <= 0.0:
        reasons.append("ordinary_paper_round_trip_cost_not_positive")
    if edge is None:
        reasons.append("ordinary_paper_after_cost_edge_nonfinite_or_missing")
    elif edge == 0.0:
        reasons.append("ordinary_paper_after_cost_edge_zero")
    if action not in {"long", "short"}:
        reasons.append("ordinary_paper_action_not_directional")
    elif edge is not None and edge != 0.0:
        if (action == "long" and edge < 0.0) or (
            action == "short" and edge > 0.0
        ):
            reasons.append("ordinary_paper_after_cost_edge_direction_mismatch")

    relative_edge_quality: float | None = None
    weight: float | None = None
    if not reasons:
        assert coverage is not None
        assert probability is not None
        assert edge is not None
        assert cost is not None
        relative_edge_quality = abs(edge) / (abs(edge) + cost)
        weight = (coverage / 100.0) * probability * relative_edge_quality
        if not math.isfinite(weight) or not 0.0 < weight <= 1.0:
            reasons.append("ordinary_paper_quality_weight_invalid")
            weight = None
    return (
        {
            "ordinary_paper_quality_schema_version": (
                ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION
            ),
            "paper_quality_sizing_formula": ORDINARY_PAPER_QUALITY_FORMULA,
            "paper_quality_coverage_component": (
                coverage / 100.0 if coverage is not None else None
            ),
            "paper_quality_calibrated_probability_component": probability,
            "paper_quality_relative_after_cost_edge_component": (
                relative_edge_quality
            ),
            "paper_quality_sizing_weight": weight,
            "paper_quality_zero_boundary_semantics": (
                "EXACT_ZERO_IS_STRUCTURAL_NO_INFORMATION_AND_BLOCKS;"
                "EVERY_FINITE_POSITIVE_VALUE_IS_CONTINUOUSLY_WEIGHTED"
            ),
            "paper_quality_market_static_threshold_used": False,
            "paper_quality_paper_only": True,
            "paper_quality_routes_to_live": False,
            "paper_quality_places_real_order": False,
        },
        sorted(set(reasons)),
    )


def _ordinary_payload_temporal_rejection_reasons(
    payload: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    decision = _strict_aware_utc(payload.get("decision_time"))
    clocks = {
        "feature_cutoff": _strict_aware_utc(payload.get("feature_cutoff")),
        "available_at": _strict_aware_utc(payload.get("available_at")),
        "candle_close_time": _strict_aware_utc(payload.get("candle_close_time")),
        "source_event_time": _strict_aware_utc(
            payload.get("source_event_time_est")
            or payload.get("source_event_time")
        ),
        "source_received_time": _strict_aware_utc(
            payload.get("source_received_time_est")
            or payload.get("source_received_time")
        ),
        "masa_feature_cutoff": _strict_aware_utc(
            payload.get("masa_feature_cutoff")
        ),
        "ppo_feature_cutoff": _strict_aware_utc(
            payload.get("ppo_feature_cutoff")
        ),
    }
    if decision is None:
        reasons.append("ordinary_paper_decision_time_invalid")
    for field_name, clock in clocks.items():
        if clock is None:
            reasons.append(f"ordinary_paper_{field_name}_invalid")
        elif decision is not None and clock > decision:
            reasons.append(f"ordinary_paper_{field_name}_after_decision")
    feature_cutoff = clocks["feature_cutoff"]
    candle_close = clocks["candle_close_time"]
    event = clocks["source_event_time"]
    received = clocks["source_received_time"]
    available = clocks["available_at"]
    if available is not None and decision is not None and available >= decision:
        reasons.append("ordinary_paper_available_at_not_before_decision")
    if (
        candle_close is not None
        and feature_cutoff is not None
        and candle_close > feature_cutoff
    ):
        reasons.append("ordinary_paper_candle_close_after_feature_cutoff")
    if (
        feature_cutoff is not None
        and available is not None
        and feature_cutoff > available
    ):
        reasons.append("ordinary_paper_feature_cutoff_after_available_at")
    if event is not None and received is not None and event > received:
        reasons.append("ordinary_paper_source_event_after_received")
    if received is not None and available is not None and received > available:
        reasons.append("ordinary_paper_source_received_after_available")

    for field_name in ("all_tf_candle_timestamps", "all_source_event_times"):
        values = payload.get(field_name)
        if not isinstance(values, list | tuple) or not values:
            reasons.append(f"ordinary_paper_{field_name}_missing")
            continue
        parsed = [_strict_aware_utc(value) for value in values]
        if any(value is None for value in parsed):
            reasons.append(f"ordinary_paper_{field_name}_invalid")
        elif decision is not None and any(value > decision for value in parsed):
            reasons.append(f"ordinary_paper_{field_name}_after_decision")
        elif field_name == "all_tf_candle_timestamps" and (
            feature_cutoff is not None
            and any(value > feature_cutoff for value in parsed)
        ):
            reasons.append(
                "ordinary_paper_all_tf_candle_timestamps_after_feature_cutoff"
            )
        elif field_name == "all_source_event_times" and (
            available is not None and any(value > available for value in parsed)
        ):
            reasons.append(
                "ordinary_paper_all_source_event_times_after_available_at"
            )
    return sorted(set(reasons))


def _ordinary_scale_free_payload_rejection_reasons(
    payload: Mapping[str, Any],
    *,
    require_replay_write: bool,
) -> list[str]:
    """Recompute ordinary PAPER eligibility from bound payload evidence.

    Self-attested admission booleans and legacy numeric thresholds are ignored.
    This helper is called again at lineage and risk handoff boundaries.
    """

    reasons: list[str] = []
    if payload.get("ordinary_paper_admission_schema_version") != (
        ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION
    ):
        reasons.append("ordinary_paper_admission_schema_invalid")
    if payload.get("on_policy_sampling_selected") is True:
        reasons.append("ordinary_paper_lane_is_sampled_exploration")
    for field_name in (
        "trust_row_accepted_for_training",
        "trust_row_valid_for_training",
        "trust_row_trainer_consumable",
        "candle_closed_confirmed",
        "mtf_snapshot_valid",
    ):
        if payload.get(field_name) is not True:
            reasons.append(f"ordinary_paper_{field_name}_not_proven")
    if str(payload.get("row_classification") or "").upper() != "TRAINABLE":
        reasons.append("ordinary_paper_row_not_trainable")
    if payload.get("training_trust_reject_reasons"):
        reasons.append("ordinary_paper_training_trust_rejected")
    if payload.get("backfilled") or payload.get("is_backfilled"):
        reasons.append("ordinary_paper_backfilled")
    for field_name in ("missing_feature_count", "stale_feature_count"):
        value = _finite_float(payload.get(field_name))
        if value is None or value != 0.0:
            reasons.append(f"ordinary_paper_{field_name}_not_zero")
    for field_name in ("missing_feature_names", "stale_feature_names"):
        if payload.get(field_name):
            reasons.append(f"ordinary_paper_{field_name}_not_empty")
    if str(payload.get("feature_freshness_state") or "").upper() != "CURRENT":
        reasons.append("ordinary_paper_feature_freshness_not_current")
    for field_name in (
        "missing_candle_count",
        "duplicate_event_count",
        "out_of_order_event_count",
    ):
        value = _finite_float(payload.get(field_name, 0))
        if value is None or value != 0.0:
            reasons.append(f"ordinary_paper_{field_name}_not_zero")

    quality, quality_reasons = _ordinary_paper_quality_evidence(
        data_coverage_percent=payload.get("data_coverage_percent"),
        confidence_probability=payload.get("confidence_calibrated"),
        expected_after_cost_bps=payload.get("expected_move_after_cost_bps"),
        round_trip_cost_bps=payload.get("round_trip_cost_bps"),
        selected_action=payload.get("selected_action"),
    )
    reasons.extend(quality_reasons)
    calibration = payload.get("confidence_calibration")
    calibrated_probability = _finite_float(payload.get("confidence_calibrated"))
    if not (
        payload.get("confidence_calibration_fitted") is True
        and isinstance(calibration, Mapping)
        and calibration.get("calibration_fitted") is True
        and calibration.get("probability_semantics_valid") is True
        and calibration.get("label_semantics") == CONFIDENCE_LABEL_SEMANTICS
        and calibration.get("confidence_head_schema_version")
        == CONFIDENCE_HEAD_SCHEMA_VERSION
        and tuple(calibration.get("confidence_head_actions") or ())
        == CONFIDENCE_HEAD_ACTIONS
        and calibration.get("selected_action_is_directional") is True
        and calibration.get("selected_action")
        == str(payload.get("selected_action") or "").strip().lower()
        and _is_sha256_hex(calibration.get("model_parameter_fingerprint"))
        and calibrated_probability is not None
        and 0.0 < calibrated_probability <= 1.0
    ):
        reasons.append("ordinary_paper_confidence_semantics_invalid")

    stored_quality = _finite_float(payload.get("paper_quality_sizing_weight"))
    recomputed_quality = quality.get("paper_quality_sizing_weight")
    if (
        stored_quality is None
        or recomputed_quality is None
        or not math.isclose(
            stored_quality,
            float(recomputed_quality),
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
    ):
        reasons.append("ordinary_paper_quality_weight_binding_invalid")
    reasons.extend(_ordinary_payload_temporal_rejection_reasons(payload))
    reasons.extend(
        f"ordinary_paper_exact_cost:{reason}"
        for reason in exact_cost_provenance_rejection_reasons(
            payload.get("exact_cost_provenance"),
            expected_symbol=payload.get("symbol"),
            expected_round_trip_cost_bps=payload.get("round_trip_cost_bps"),
            expected_decision_time=payload.get("decision_time"),
        )
    )
    if payload.get("replay_snapshot_ready") is not True or not isinstance(
        payload.get("replay_snapshot"), Mapping
    ):
        reasons.append("ordinary_paper_replay_snapshot_not_ready")
    if not str(payload.get("replay_snapshot_id") or "").strip():
        reasons.append("ordinary_paper_replay_snapshot_id_missing")
    if require_replay_write and (
        payload.get("replay_snapshot_write_success") is not True
        or not str(payload.get("replay_snapshot_key") or "").strip()
    ):
        reasons.append("ordinary_paper_replay_snapshot_write_not_proven")
    if require_replay_write:
        if payload.get("replay_snapshot_write_acknowledged") is not True:
            reasons.append("ordinary_paper_replay_snapshot_write_not_acknowledged")
        if payload.get("replay_snapshot_readback_verified") is not True:
            reasons.append("ordinary_paper_replay_snapshot_readback_not_verified")
        snapshot = payload.get("replay_snapshot")
        stored_snapshot_hash = str(
            payload.get("replay_snapshot_content_sha256") or ""
        )
        try:
            expected_snapshot_hash = (
                canonical_sha256(dict(snapshot))
                if isinstance(snapshot, Mapping)
                else ""
            )
        except (TypeError, ValueError):
            expected_snapshot_hash = ""
        if (
            not _is_sha256_hex(stored_snapshot_hash)
            or stored_snapshot_hash != expected_snapshot_hash
        ):
            reasons.append("ordinary_paper_replay_snapshot_hash_binding_invalid")
        replay_ttl = _finite_float(payload.get("replay_snapshot_ttl_seconds"))
        if replay_ttl is None or replay_ttl <= 0.0:
            reasons.append("ordinary_paper_replay_snapshot_expiry_not_proven")

    if payload.get("live_gate") != LIVE_GATE_BLOCKED:
        reasons.append("ordinary_paper_live_gate_not_blocked")
    if payload.get("live_symbols") != []:
        reasons.append("ordinary_paper_live_symbols_not_empty")
    if payload.get("exchange_mutation") is not False:
        reasons.append("ordinary_paper_exchange_mutation_not_false")
    if payload.get("trainer_direct_trading") is not False:
        reasons.append("ordinary_paper_trainer_direct_trading_not_false")

    contract_candidate = dict(payload)
    contract_candidate.update(
        {
            "prediction_eligible": True,
            "risk_eligible": True,
            "paper_eligible": True,
            "paper_fill_allowed": True,
            "routes_to_orchestrator": True,
        }
    )
    contract = validate_prediction_trust_contract(
        contract_candidate,
        require_replay_write=require_replay_write,
    )
    reasons.extend(
        f"ordinary_paper_runtime_trust:{reason}"
        for reason in contract.reject_reasons
    )
    return sorted(set(reasons))


def _is_sha256_hex(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _strict_aware_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(ZoneInfo("UTC"))


def _same_strict_utc(left: Any, right: Any) -> bool:
    left_clock = _strict_aware_utc(left)
    right_clock = _strict_aware_utc(right)
    return left_clock is not None and left_clock == right_clock


def _adaptive_sampling_plan_rejection_reasons(
    plan: Mapping[str, Any] | None,
    *,
    example: TrainingExample,
    decision_time: Any,
    feature_cutoff: Any,
    available_at: Any,
    candle_close_time: Any,
    cost_provenance: Mapping[str, Any] | None,
    checkpoint_id: str,
    checkpoint_weight_sha256: Any,
    checkpoint_evidence_digest: Any,
) -> list[str]:
    """Re-verify the selected lane row and its paper safety inputs.

    The planner output is content-addressed but not an authorization token.
    Recomputing both hashes and binding the selected audit row prevents a stale,
    unrelated, or margin-invalid plan from opening the exact paper lane.
    """

    if not isinstance(plan, Mapping):
        return ["adaptive_sampling_plan_missing"]
    row = dict(plan)
    reasons: list[str] = []
    if row.get("schema_version") != ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION:
        reasons.append("adaptive_sampling_plan_schema_invalid")
    if row.get("formula") != ADAPTIVE_ON_POLICY_LANE_FORMULA:
        reasons.append("adaptive_sampling_plan_formula_invalid")
    supplied_plan_hash = row.pop("plan_hash", None)
    try:
        recomputed_plan_hash = canonical_sha256(row)
    except (TypeError, ValueError):
        recomputed_plan_hash = None
    if not _is_sha256_hex(supplied_plan_hash) or supplied_plan_hash != recomputed_plan_hash:
        reasons.append("adaptive_sampling_plan_hash_invalid")

    margin = plan.get("paper_margin_inputs")
    freeze = plan.get("paper_entry_freeze_inputs")
    audits = plan.get("candidate_audit")
    if not isinstance(margin, Mapping):
        margin = {}
        reasons.append("adaptive_sampling_margin_evidence_missing")
    if not isinstance(freeze, Mapping):
        freeze = {}
        reasons.append("adaptive_sampling_freeze_evidence_missing")
    if not isinstance(audits, list):
        audits = []
        reasons.append("adaptive_sampling_candidate_audit_missing")

    input_material = {
        "schema_version": plan.get("schema_version"),
        "formula": plan.get("formula"),
        "carry_in": plan.get("carry_in"),
        "single_candidate_ordinary_credit_in": plan.get(
            "single_candidate_ordinary_credit_in"
        ),
        "paper_margin_inputs": dict(margin),
        "paper_entry_freeze_inputs": dict(freeze),
        "candidate_audit": list(audits),
    }
    try:
        recomputed_input_hash = canonical_sha256(input_material)
    except (TypeError, ValueError):
        recomputed_input_hash = None
    if (
        not _is_sha256_hex(plan.get("input_hash"))
        or plan.get("input_hash") != recomputed_input_hash
    ):
        reasons.append("adaptive_sampling_plan_input_hash_invalid")

    margin_base = _finite_float(margin.get("margin_base_usd"))
    free_margin = _finite_float(margin.get("free_margin_after_buffer_usd"))
    if margin.get("invariant_holds") is not True:
        reasons.append("adaptive_sampling_margin_invariant_not_proven")
    if margin_base is None or margin_base <= 0.0:
        reasons.append("adaptive_sampling_margin_base_not_positive")
    if free_margin is None or free_margin <= 0.0:
        reasons.append("adaptive_sampling_free_margin_not_positive")
    if margin.get("paper_only") is not True:
        reasons.append("adaptive_sampling_margin_not_paper_only")
    if margin.get("routes_to_live") is not False:
        reasons.append("adaptive_sampling_margin_live_route_not_false")
    if margin.get("places_real_order") is not False:
        reasons.append("adaptive_sampling_margin_real_order_not_false")
    if freeze.get("paper_new_entries_halted") is not False:
        reasons.append("adaptive_sampling_entry_freeze_not_clear")
    if freeze.get("new_entries_allowed") is not True:
        reasons.append("adaptive_sampling_new_entries_not_allowed")
    if freeze.get("paper_only") is not True:
        reasons.append("adaptive_sampling_entry_gate_not_paper_only")
    if freeze.get("routes_to_live") is not False:
        reasons.append("adaptive_sampling_entry_gate_live_route_not_false")
    if freeze.get("places_real_order") is not False:
        reasons.append("adaptive_sampling_entry_gate_real_order_not_false")
    if plan.get("safety_gate_passed") is not True or plan.get(
        "safety_rejection_reasons"
    ):
        reasons.append("adaptive_sampling_safety_gate_not_proven")
    if plan.get("market_static_sampling_threshold_used") is not False:
        reasons.append("adaptive_sampling_static_market_threshold_used")
    if plan.get("paper_only") is not True:
        reasons.append("adaptive_sampling_plan_not_paper_only")
    if plan.get("routes_to_live") is not False:
        reasons.append("adaptive_sampling_plan_live_route_not_false")
    if plan.get("places_real_order") is not False:
        reasons.append("adaptive_sampling_plan_real_order_not_false")

    selected_indices = plan.get("selected_indices")
    if not isinstance(selected_indices, list) or not selected_indices:
        reasons.append("adaptive_sampling_selected_indices_missing")
        selected_index_set: set[int] = set()
    elif any(type(index) is not int or index < 0 for index in selected_indices):
        reasons.append("adaptive_sampling_selected_indices_invalid")
        selected_index_set = set()
    else:
        selected_index_set = set(selected_indices)
    if type(plan.get("selected_sample_count")) is not int or int(
        plan.get("selected_sample_count") or 0
    ) != len(selected_index_set):
        reasons.append("adaptive_sampling_selected_count_invalid")

    expected_cost_hash = (
        cost_provenance.get("source_payload_sha256")
        if isinstance(cost_provenance, Mapping)
        else None
    )
    selected_matching_audits: list[Mapping[str, Any]] = []
    for audit in audits:
        if not isinstance(audit, Mapping) or audit.get("index") not in selected_index_set:
            continue
        if (
            str(audit.get("symbol") or "").upper() == example.symbol.upper()
            and str(audit.get("timeframe") or "") == example.timeframe
            and str(audit.get("feature_tensor_id") or "")
            == example.tensor.tensor_id
            and _same_strict_utc(audit.get("feature_cutoff"), feature_cutoff)
            and _same_strict_utc(audit.get("available_at"), available_at)
            and _same_strict_utc(audit.get("candle_close_time"), candle_close_time)
            and _same_strict_utc(audit.get("decision_time"), decision_time)
        ):
            selected_matching_audits.append(audit)
    if len(selected_matching_audits) != 1:
        reasons.append("adaptive_sampling_selected_row_binding_invalid")
    else:
        selected_audit = selected_matching_audits[0]
        if selected_audit.get("eligible") is not True or selected_audit.get(
            "rejection_reasons"
        ):
            reasons.append("adaptive_sampling_selected_row_not_eligible")
        if str(selected_audit.get("row_classification") or "").upper() != "TRAINABLE":
            reasons.append("adaptive_sampling_selected_row_not_trainable")
        if selected_audit.get("exact_cost_payload_hash") != expected_cost_hash:
            reasons.append("adaptive_sampling_selected_row_cost_binding_invalid")
        for field_name, expected in (
            ("checkpoint_id", checkpoint_id),
            ("checkpoint_weight_sha256", checkpoint_weight_sha256),
            ("checkpoint_evidence_digest", checkpoint_evidence_digest),
        ):
            if selected_audit.get(field_name) != expected:
                reasons.append(
                    f"adaptive_sampling_selected_row_{field_name}_binding_invalid"
                )
        if selected_audit.get("checkpoint_evidence_verified") is not True:
            reasons.append("adaptive_sampling_selected_row_checkpoint_not_verified")
        if selected_audit.get("checkpoint_identity_verified") is not True:
            reasons.append("adaptive_sampling_selected_row_checkpoint_identity_invalid")
    return sorted(set(reasons))


def _adaptive_row_integrity_rejection_reasons(
    example: TrainingExample,
    *,
    decision_time: Any,
) -> list[str]:
    """Evaluate categorical dirty-row/PIT facts without a market score floor."""

    trust = dict(example.trust_row or {})
    tensor = example.tensor
    reasons: list[str] = []
    if str(example.row_classification or "").upper() != "TRAINABLE":
        reasons.append("adaptive_row_not_trainable")
    for field_name in ("accepted_for_training", "valid_for_training", "trainer_consumable"):
        if trust.get(field_name) is not True:
            reasons.append(f"adaptive_row_{field_name}_not_proven")
    if trust.get("reject_reasons"):
        reasons.append("adaptive_row_trust_rejected")
    missing_mask = getattr(tensor, "missing_mask", None)
    stale_mask = getattr(tensor, "stale_mask", None)
    if not isinstance(missing_mask, (list, tuple)):
        reasons.append("adaptive_row_missing_mask_lineage_unavailable")
        missing_mask = ()
    if not isinstance(stale_mask, (list, tuple)):
        reasons.append("adaptive_row_stale_mask_lineage_unavailable")
        stale_mask = ()
    if tensor.missing_feature_names or any(missing_mask):
        reasons.append("adaptive_row_missing_features")
    if tensor.stale_feature_names or any(stale_mask):
        reasons.append("adaptive_row_stale_features")
    if int(trust.get("missing_feature_count") or 0) > 0 or trust.get(
        "missing_feature_names"
    ):
        reasons.append("adaptive_row_trust_reports_missing_features")
    if int(trust.get("stale_feature_count") or 0) > 0 or trust.get(
        "stale_feature_names"
    ):
        reasons.append("adaptive_row_trust_reports_stale_features")
    if str(trust.get("feature_freshness_state") or "").upper() != "CURRENT":
        reasons.append("adaptive_row_feature_freshness_not_current")
    freshness = str(trust.get("freshness_state") or "").upper()
    if freshness and freshness not in {"CURRENT", "FRESH"}:
        reasons.append("adaptive_row_source_freshness_not_current")
    if trust.get("backfilled") or trust.get("is_backfilled"):
        reasons.append("adaptive_row_backfilled")
    if trust.get("candle_closed_confirmed") is not True:
        reasons.append("adaptive_row_candle_finality_not_proven")
    if not str(trust.get("mtf_snapshot_id") or "").strip():
        reasons.append("adaptive_row_mtf_snapshot_missing")
    if trust.get("mtf_snapshot_valid") is not True:
        reasons.append("adaptive_row_mtf_snapshot_invalid")

    decision = _strict_aware_utc(decision_time)
    if decision is None:
        reasons.append("adaptive_row_decision_time_invalid")
    source_clocks = (
        trust.get("source_event_time_est") or trust.get("source_event_time"),
        trust.get("source_received_time_est") or trust.get("source_available_time"),
    )
    if any(_strict_aware_utc(value) is None for value in source_clocks):
        reasons.append("adaptive_row_source_clock_lineage_missing")
    elif decision is not None and any(
        _strict_aware_utc(value) > decision for value in source_clocks
    ):
        reasons.append("adaptive_row_source_clock_after_decision")
    for field_name in ("all_tf_candle_timestamps", "all_source_event_times"):
        clocks = trust.get(field_name)
        if not isinstance(clocks, list | tuple) or not clocks:
            reasons.append(f"adaptive_row_{field_name}_missing")
            continue
        parsed = [_strict_aware_utc(value) for value in clocks]
        if any(value is None for value in parsed):
            reasons.append(f"adaptive_row_{field_name}_invalid")
        elif decision is not None and any(value > decision for value in parsed):
            reasons.append(f"adaptive_row_{field_name}_after_decision")
    return sorted(set(reasons))


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

DECISION_TEMPORAL_LINEAGE_FIELDS = (
    "candle_closed_confirmed",
    "candle_open_time",
    "candle_close_time",
    "source_event_time_est",
    "source_received_time_est",
    "source_available_time",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
    "ppo_decision_time",
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
    served_policy_fingerprint: str | None = None,
    checkpoint_weight_sha256: str | None = None,
    checkpoint_evidence_digest: str | None = None,
    checkpoint_evidence_verified: bool = False,
    checkpoint_identity_verified: bool = False,
    cost_provenance: Mapping[str, Any] | None = None,
    behavior_sample_draw_u53: int | None = None,
    on_policy_sampling_selected: bool = False,
    on_policy_sampling_plan: Mapping[str, Any] | None = None,
    decision_time_utc: str | None = None,
    cycle_id: str | None = None,
    process_instance_id: str | None = None,
    candidate_policy_fingerprint: str | None = None,
) -> dict[str, Any]:
    tensor = example.tensor
    generated_utc = decision_time_utc or datetime.now(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    generated_est = _est_iso()
    trust_row = dict(example.trust_row or {})
    feature_cutoff = trust_row.get("feature_cutoff") or trust_row.get("decision_cutoff")
    feature_hash = trust_row.get("feature_vector_hash") or tensor.tensor_id
    sampling_selected = bool(
        on_policy_sampling_selected
        and served_policy_fingerprint not in (None, "")
    )
    checkpoint_id = (
        checkpoint.checkpoint_id
        if checkpoint
        else "v2_hybrid_checkpoint_manifest_pending"
    )
    draw_u53: int | None = None
    behavior_nonce: str | None = None
    if sampling_selected:
        draw_u53 = (
            secrets.randbelow(U53_DENOMINATOR)
            if behavior_sample_draw_u53 is None
            else behavior_sample_draw_u53
        )
        behavior_nonce = hashlib.sha256(
            (
                f"{served_policy_fingerprint}|{generated_utc}|{draw_u53}|"
                f"{tensor.tensor_id}"
            ).encode("utf-8")
        ).hexdigest()[:24]
    prediction_id = _prediction_id(
        example.symbol,
        example.timeframe,
        tensor.tensor_id,
        model_output.model_id,
        behavior_nonce=behavior_nonce,
    )
    signal_id = "sig_" + prediction_id
    cycle_identity_values = (
        cycle_id,
        process_instance_id,
        candidate_policy_fingerprint,
    )
    if any(value not in (None, "") for value in cycle_identity_values) and any(
        value in (None, "") for value in cycle_identity_values
    ):
        raise ValueError("prediction_current_cycle_identity_incomplete")
    behavior_receipt: dict[str, Any] | None = None
    behavior_receipt_rejections: list[str] = []
    effective_model_output = model_output
    behavior_policy_fields: dict[str, Any] = {
        "action_labels": list(ACTION_LABELS),
        "raw_action_logits": list(model_output.action_logits),
        "action_probabilities": list(model_output.action_probabilities),
        "selected_action_index": model_output.selected_action_index,
        "selected_action_probability": (
            list(model_output.action_probabilities)[model_output.selected_action_index]
            if 0 <= model_output.selected_action_index < len(model_output.action_probabilities)
            else None
        ),
        "policy_value": model_output.policy_value,
        "behavior_policy_sampling_mode": BEHAVIOR_POLICY_SAMPLING_MODE,
        "behavior_policy_distribution_contract": (
            BEHAVIOR_POLICY_DISTRIBUTION_CONTRACT
        ),
        "behavior_policy_receipt_write_success": False,
        "on_policy_action_receipt_valid": False,
        "ppo_on_policy_entry_fields_present": False,
        "ppo_on_policy_ineligible_reason": PPO_ON_POLICY_INELIGIBLE_REASON,
        "entry_policy_fields_source": "V2_NATIVE_CUDA_TRAINER_ENTRY_FORWARD_PASS",
        "on_policy_sampling_selected": sampling_selected,
        "on_policy_sampling_requested": bool(on_policy_sampling_selected),
        "on_policy_sampling_plan_hash": (
            on_policy_sampling_plan.get("plan_hash")
            if isinstance(on_policy_sampling_plan, Mapping)
            else None
        ),
        "on_policy_sampling_plan_input_hash": (
            on_policy_sampling_plan.get("input_hash")
            if isinstance(on_policy_sampling_plan, Mapping)
            else None
        ),
        "on_policy_sampling_lane": (
            "ADAPTIVE_BOUNDED_PAPER_EXPLORATION"
            if sampling_selected
            else "ORDINARY_DETERMINISTIC_NATIVE_POLICY"
        ),
        "on_policy_sampling_evidence_class": (
            "PAPER_EXPLORATION_LEARNING_ONLY"
            if sampling_selected
            else "NOT_ON_POLICY_SAMPLED"
        ),
        "on_policy_sampling_counts_as_a_plus_evidence": False,
        "on_policy_sampling_routes_to_live": False,
    }
    if draw_u53 is not None and served_policy_fingerprint is not None:
        try:
            behavior_receipt = build_positive_edge_behavior_receipt(
                prediction_id=prediction_id,
                model_output=model_output,
                symbol=example.symbol,
                timeframe=example.timeframe,
                checkpoint_id=checkpoint_id,
                checkpoint_weight_sha256=str(checkpoint_weight_sha256 or ""),
                checkpoint_evidence_digest=str(
                    checkpoint_evidence_digest or ""
                ),
                checkpoint_evidence_verified=checkpoint_evidence_verified,
                checkpoint_identity_verified=checkpoint_identity_verified,
                served_policy_fingerprint=served_policy_fingerprint,
                feature_tensor_id=tensor.tensor_id,
                feature_vector_hash=str(feature_hash),
                feature_cutoff=feature_cutoff,
                available_at=trust_row.get("available_at")
                or trust_row.get("source_available_time"),
                candle_close_time=trust_row.get("candle_close_time"),
                decision_time=generated_utc,
                candle_closed_confirmed=trust_row.get("candle_closed_confirmed"),
                round_trip_cost_bps=abs(float(round_trip_cost_bps)),
                cost_provenance=dict(cost_provenance or {}),
                draw_u53=draw_u53,
                sampling_plan_hash=str(
                    (on_policy_sampling_plan or {}).get("plan_hash") or ""
                ),
                sampling_plan_input_hash=str(
                    (on_policy_sampling_plan or {}).get("input_hash") or ""
                ),
            )
        except (TypeError, ValueError) as exc:
            behavior_receipt_rejections = [str(exc)]
        if behavior_receipt is not None:
            behavior_receipt_rejections = behavior_receipt_rejection_reasons(
                behavior_receipt,
                expected_prediction_id=prediction_id,
                expected_symbol=example.symbol,
                expected_timeframe=example.timeframe,
                expected_checkpoint_id=checkpoint_id,
                expected_feature_vector_hash=feature_hash,
                expected_policy_fingerprint=served_policy_fingerprint,
            )
        if behavior_receipt is not None and not behavior_receipt_rejections:
            sampled_action = str(behavior_receipt["selected_action"])
            base_confidence_calibration = (
                dict(model_output.calibration)
                if isinstance(model_output.calibration, Mapping)
                else {}
            )
            calibration_by_direction = base_confidence_calibration.get(
                "confidence_calibration_by_direction"
            )
            sampled_calibration_record = (
                calibration_by_direction.get(sampled_action)
                if isinstance(calibration_by_direction, Mapping)
                else None
            )
            if isinstance(sampled_calibration_record, Mapping):
                sampled_confidence_calibration = dict(sampled_calibration_record)
                sampled_confidence_calibration.update(
                    {
                        "confidence_raw_by_direction": base_confidence_calibration.get(
                            "confidence_raw_by_direction"
                        ),
                        "confidence_calibrated_by_direction": (
                            base_confidence_calibration.get(
                                "confidence_calibrated_by_direction"
                            )
                        ),
                        "confidence_calibration_by_direction": dict(
                            calibration_by_direction
                        ),
                    }
                )
                sampled_confidence_raw = _finite_float(
                    sampled_confidence_calibration.get("confidence_raw")
                )
                sampled_confidence_calibrated = _finite_float(
                    sampled_confidence_calibration.get("confidence_calibrated")
                )
            else:
                sampled_confidence_raw = None
                sampled_confidence_calibrated = None
                sampled_confidence_calibration = {
                    "calibration_fitted": False,
                    "probability_semantics_valid": False,
                    "calibration_reason": (
                        "SAMPLED_DIRECTION_CONFIDENCE_EVIDENCE_MISSING"
                    ),
                    "label_semantics": CONFIDENCE_LABEL_SEMANTICS,
                    "confidence_head_schema_version": (
                        CONFIDENCE_HEAD_SCHEMA_VERSION
                    ),
                    "confidence_head_actions": list(CONFIDENCE_HEAD_ACTIONS),
                    "selected_action": sampled_action,
                    "selected_action_is_directional": (
                        sampled_action in CONFIDENCE_HEAD_ACTIONS
                    ),
                }
            if (
                sampled_confidence_raw is None
                or sampled_confidence_calibrated is None
            ):
                sampled_confidence_raw = 0.0
                sampled_confidence_calibrated = 0.0
                sampled_confidence_calibration["calibration_fitted"] = False
                sampled_confidence_calibration["probability_semantics_valid"] = False
                sampled_confidence_calibration["calibration_reason"] = (
                    "SAMPLED_DIRECTION_CONFIDENCE_VALUE_INVALID"
                )
            effective_model_output = dataclasses.replace(
                model_output,
                action_probabilities=tuple(behavior_receipt["action_probabilities"]),
                selected_action_index=int(behavior_receipt["selected_action_index"]),
                selected_action=sampled_action,
                confidence_raw=sampled_confidence_raw,
                confidence_calibrated=sampled_confidence_calibrated,
                calibration=sampled_confidence_calibration,
            )
            behavior_policy_fields.update(
                {
                    "raw_action_probabilities": list(
                        behavior_receipt["raw_action_probabilities"]
                    ),
                    "action_probabilities": list(
                        behavior_receipt["action_probabilities"]
                    ),
                    "selected_action_index": behavior_receipt[
                        "selected_action_index"
                    ],
                    "selected_action_probability": behavior_receipt[
                        "selected_action_probability"
                    ],
                    "selected_action_log_prob": behavior_receipt[
                        "selected_action_log_prob"
                    ],
                    "policy_value": behavior_receipt["policy_value"],
                    "behavior_action_index": behavior_receipt[
                        "selected_action_index"
                    ],
                    "behavior_action": behavior_receipt["selected_action"],
                    "behavior_action_mask": list(
                        behavior_receipt["behavior_action_mask"]
                    ),
                    "behavior_action_source": ON_POLICY_ACTION_SOURCE,
                    "behavior_policy_sampling_mode": ON_POLICY_SAMPLING_MODE,
                    "behavior_policy_distribution_contract": (
                        ON_POLICY_DISTRIBUTION_CONTRACT
                    ),
                    "behavior_policy_fingerprint": served_policy_fingerprint,
                    "behavior_policy_checkpoint_hash": checkpoint_weight_sha256,
                    "behavior_policy_checkpoint_evidence_digest": (
                        checkpoint_evidence_digest
                    ),
                    "behavior_policy_checkpoint_evidence_verified": True,
                    "behavior_policy_checkpoint_identity_verified": True,
                    "behavior_policy_cost_provenance": dict(
                        behavior_receipt["cost_provenance"]
                    ),
                    "behavior_policy_cost_payload_hash": behavior_receipt[
                        "cost_source_payload_sha256"
                    ],
                    "behavior_policy_receipt": dict(behavior_receipt),
                    "behavior_policy_receipt_hash": behavior_receipt["receipt_hash"],
                    "on_policy_action_receipt_valid": True,
                    "ppo_on_policy_entry_fields_present": False,
                    "ppo_on_policy_ineligible_reason": None,
                }
            )
    if sampling_selected and behavior_receipt is None:
        # Exact sampling is fail-closed. Keep the original deterministic model
        # output available as an ordinary paper prediction, but never label it
        # as sampled or PPO-consumable when checkpoint/cost evidence is absent.
        sampling_selected = False
        behavior_policy_fields.update(
            {
                "on_policy_sampling_selected": False,
                "on_policy_sampling_lane": "ORDINARY_DETERMINISTIC_NATIVE_POLICY",
                "on_policy_sampling_evidence_class": "NOT_ON_POLICY_SAMPLED",
                "on_policy_action_receipt_valid": False,
                "ppo_on_policy_entry_fields_present": False,
                "ppo_on_policy_ineligible_reason": (
                    "EXACT_BEHAVIOR_RECEIPT_PRECONDITIONS_FAILED"
                ),
            }
        )
    selected_action = str(effective_model_output.selected_action or "hold").strip().lower()
    if selected_action == "long":
        expected_after_cost = float(
            effective_model_output.expected_move_bps - abs(round_trip_cost_bps)
        )
    elif selected_action == "short":
        expected_after_cost = float(
            effective_model_output.expected_move_bps + abs(round_trip_cost_bps)
        )
    else:
        expected_after_cost = 0.0
    directional_edge_aligned = (
        (selected_action == "long" and expected_after_cost > 0.0)
        or (selected_action == "short" and expected_after_cost < 0.0)
    )
    confidence_calibration = (
        dict(effective_model_output.calibration)
        if isinstance(effective_model_output.calibration, Mapping)
        else {}
    )
    confidence_probability = _finite_float(
        effective_model_output.confidence_calibrated
    )
    confidence_calibration_fitted = bool(
        confidence_calibration.get("calibration_fitted") is True
        and confidence_calibration.get("probability_semantics_valid") is True
        and confidence_calibration.get("label_semantics")
        == CONFIDENCE_LABEL_SEMANTICS
        and confidence_calibration.get("confidence_head_schema_version")
        == CONFIDENCE_HEAD_SCHEMA_VERSION
        and tuple(confidence_calibration.get("confidence_head_actions") or ())
        == CONFIDENCE_HEAD_ACTIONS
        and confidence_calibration.get("selected_action_is_directional") is True
        and confidence_calibration.get("selected_action") == selected_action
        and _is_sha256_hex(
            confidence_calibration.get("model_parameter_fingerprint")
        )
        and confidence_probability is not None
        and 0.0 <= confidence_probability <= 1.0
    )
    legacy_static_market_threshold_would_allow = bool(
        tensor.data_coverage_percent >= min_data_coverage_percent
        and confidence_calibration_fitted
        and confidence_probability is not None
        and confidence_probability >= min_confidence_calibrated
        and directional_edge_aligned
        and abs(expected_after_cost) >= min_edge_after_cost_bps
    )
    quality_evidence, ordinary_quality_rejection_reasons = (
        _ordinary_paper_quality_evidence(
            data_coverage_percent=tensor.data_coverage_percent,
            confidence_probability=confidence_probability,
            expected_after_cost_bps=expected_after_cost,
            round_trip_cost_bps=round_trip_cost_bps,
            selected_action=selected_action,
        )
    )
    ordinary_exact_cost_rejection_reasons = (
        exact_cost_provenance_rejection_reasons(
            cost_provenance,
            expected_symbol=example.symbol,
            expected_round_trip_cost_bps=abs(round_trip_cost_bps),
            expected_decision_time=generated_utc,
        )
    )
    block_reasons: list[str] = []
    if selected_action not in {"long", "short"}:
        block_reasons.append("action_not_directional")
    if not confidence_calibration_fitted:
        block_reasons.append(
            "confidence_calibration_unfitted_or_semantics_invalid"
        )
    if selected_action in {"long", "short"} and not directional_edge_aligned:
        block_reasons.append("expected_move_after_cost_direction_mismatch")
    action_diagnostics = action_policy_diagnostics(
        selected_action=selected_action,
        action_probabilities=effective_model_output.action_probabilities,
        expected_move_bps=effective_model_output.expected_move_bps,
        round_trip_cost_bps=round_trip_cost_bps,
        min_edge_after_cost_bps=min_edge_after_cost_bps,
    )
    integrity = _market_state_fields_from_example(example, prediction_id)
    # MASA and PPO consume the same immutable feature tensor in this publisher
    # path.  Preserve explicitly recorded cutoffs when present; otherwise the
    # tensor's canonical feature cutoff is the cutoff for each internal model.
    # Candle finality itself is never inferred here.
    masa_feature_cutoff = trust_row.get("masa_feature_cutoff") or feature_cutoff
    ppo_feature_cutoff = trust_row.get("ppo_feature_cutoff") or feature_cutoff
    provider_mask_context = _provider_mask_context(example, trust_row)
    premium_contexts = _prediction_premium_contexts(example, trust_row)
    trust_reject_reasons = [str(reason) for reason in (trust_row.get("reject_reasons") or []) if str(reason)]
    timestamp_source_hash_material = {
        "all_tf_candle_timestamps": list(trust_row.get("all_tf_candle_timestamps") or []),
        "all_source_event_times": list(trust_row.get("all_source_event_times") or []),
    }
    source_hashes = dict(trust_row.get("source_hashes") or {})
    microstructure_trust_evidence = (
        copy.deepcopy(dict(trust_row.get("microstructure_trust_evidence")))
        if isinstance(trust_row.get("microstructure_trust_evidence"), Mapping)
        else None
    )
    microstructure_trust_evidence_rejections = (
        microstructure_trust_evidence_rejection_reasons(
            microstructure_trust_evidence,
            expected_symbol=example.symbol,
            expected_timeframe=example.timeframe,
            expected_tensor_id=tensor.tensor_id,
            expected_feature_snapshot_id=tensor.feature_snapshot_id,
            expected_tensor_source_lineage_hash=tensor.source_lineage_hash,
            expected_ppo_decision_time=generated_utc,
        )
    )
    microstructure_trust_evidence_sha256 = (
        microstructure_trust_evidence.get("evidence_sha256")
        if microstructure_trust_evidence is not None
        else None
    )
    microstructure_trust_source_payload_sha256 = (
        microstructure_trust_evidence.get("source_payload_sha256")
        if microstructure_trust_evidence is not None
        else None
    )
    source_hashes.update(
        {
            "feature_vector_hash": feature_hash,
            "input_feature_hash": feature_hash,
            "feature_tensor_id": tensor.tensor_id,
            "tensor_source_lineage_hash": tensor.source_lineage_hash,
            "microstructure_trust_evidence_sha256": (
                microstructure_trust_evidence_sha256
            ),
            "microstructure_trust_source_payload_sha256": (
                microstructure_trust_source_payload_sha256
            ),
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
        model_output=effective_model_output,
        trust_row=trust_row,
        checkpoint=checkpoint,
        source_hashes=source_hashes,
        behavior_policy_fields=behavior_policy_fields,
    )
    replay_snapshot_id = None
    if isinstance(replay_snapshot, dict):
        replay_snapshot_id = replay_snapshot.get("decision_id") or replay_snapshot.get("replay_snapshot_id")
    for reason in replay_reasons:
        block_reasons.append(f"replay_snapshot:{reason}")
    for reason in behavior_receipt_rejections:
        block_reasons.append(f"on_policy_behavior_receipt:{reason}")
    if integrity["valid_for_prediction"] is not True:
        block_reasons.append("market_state_invalid_for_prediction")
    if integrity["valid_for_paper"] is not True:
        block_reasons.append("market_state_invalid_for_paper")
    for reason in trust_reject_reasons:
        block_reasons.append(f"training_trust:{reason}")
    for reason in integrity["market_state_reject_reasons"]:
        block_reasons.append(f"market_state:{reason}")
    ordinary_row_rejection_reasons = _adaptive_row_integrity_rejection_reasons(
        example,
        decision_time=generated_utc,
    )
    ordinary_admission_rejections = set(ordinary_quality_rejection_reasons)
    if sampling_selected:
        ordinary_admission_rejections.add(
            "ordinary_paper_lane_is_sampled_exploration"
        )
    if not confidence_calibration_fitted:
        ordinary_admission_rejections.add(
            "ordinary_paper_confidence_calibration_unfitted_or_semantics_invalid"
        )
    ordinary_admission_rejections.update(
        f"ordinary_paper_row_integrity:{reason}"
        for reason in ordinary_row_rejection_reasons
    )
    ordinary_admission_rejections.update(
        f"ordinary_paper_training_trust:{reason}"
        for reason in trust_reject_reasons
    )
    ordinary_admission_rejections.update(
        f"ordinary_paper_replay_snapshot:{reason}" for reason in replay_reasons
    )
    ordinary_admission_rejections.update(
        f"ordinary_paper_exact_cost:{reason}"
        for reason in ordinary_exact_cost_rejection_reasons
    )
    ordinary_admission_rejections.update(
        f"ordinary_paper_microstructure_trust_evidence:{reason}"
        for reason in microstructure_trust_evidence_rejections
    )
    ordinary_paper_admission_rejection_reasons = sorted(
        ordinary_admission_rejections
    )
    ordinary_paper_admission_safe = bool(
        not ordinary_paper_admission_rejection_reasons
    )
    ordinary_paper_fill_allowed = ordinary_paper_admission_safe
    block_reasons.extend(ordinary_paper_admission_rejection_reasons)
    adaptive_row_rejection_reasons = (
        _adaptive_row_integrity_rejection_reasons(
            example,
            decision_time=generated_utc,
        )
        if sampling_selected
        else []
    )
    adaptive_sampling_plan_rejection_reasons = (
        _adaptive_sampling_plan_rejection_reasons(
            on_policy_sampling_plan,
            example=example,
            decision_time=generated_utc,
            feature_cutoff=feature_cutoff,
            available_at=trust_row.get("available_at")
            or trust_row.get("source_available_time"),
            candle_close_time=trust_row.get("candle_close_time"),
            cost_provenance=cost_provenance,
            checkpoint_id=checkpoint_id,
            checkpoint_weight_sha256=checkpoint_weight_sha256,
            checkpoint_evidence_digest=checkpoint_evidence_digest,
        )
        if sampling_selected
        else []
    )
    for reason in adaptive_row_rejection_reasons:
        block_reasons.append(f"adaptive_row_integrity:{reason}")
    for reason in adaptive_sampling_plan_rejection_reasons:
        block_reasons.append(f"adaptive_sampling_plan:{reason}")
    sampling_plan_safe = bool(
        sampling_selected and not adaptive_sampling_plan_rejection_reasons
    )
    adaptive_immutable_paper_admission_safe = bool(
        sampling_selected
        and behavior_receipt is not None
        and not behavior_receipt_rejections
        and not adaptive_row_rejection_reasons
        and not adaptive_sampling_plan_rejection_reasons
        and not trust_reject_reasons
        and not replay_reasons
    )
    adaptive_paper_exploration_fill_allowed = bool(
        adaptive_immutable_paper_admission_safe
        and confidence_calibration_fitted
        and confidence_probability is not None
        and 0.0 <= confidence_probability <= 1.0
        and selected_action in {"long", "short"}
        and directional_edge_aligned
        and abs(expected_after_cost) > 0.0
    )
    ordinary_paper_gate_block_reasons = list(
        ordinary_paper_admission_rejection_reasons
    )
    if ordinary_paper_fill_allowed or adaptive_paper_exploration_fill_allowed:
        block_reasons = [
            reason
            for reason in block_reasons
            if reason
            not in {
                "market_state_invalid_for_prediction",
                "market_state_invalid_for_paper",
            }
            and not reason.startswith("market_state:")
            and (
                ordinary_paper_fill_allowed
                or not reason.startswith("ordinary_paper_")
            )
        ]
    paper_fill_allowed = bool(
        ordinary_paper_fill_allowed or adaptive_paper_exploration_fill_allowed
    )
    routes_to_orchestrator = bool(
        (
            ordinary_paper_fill_allowed
        )
        or adaptive_paper_exploration_fill_allowed
    )
    payload = {
        "prediction_id": prediction_id,
        "signal_id": signal_id,
        "generated_est": generated_est,
        "generated_utc": generated_utc,
        "generated_at": generated_utc,
        "status": "PRESENT_CURRENT",
        "cycle_id": cycle_id,
        "process_instance_id": process_instance_id,
        "candidate_policy_fingerprint": candidate_policy_fingerprint,
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "selected_action": effective_model_output.selected_action,
        "selected_action_index": effective_model_output.selected_action_index,
        "action_labels": list(ACTION_LABELS),
        "action_probabilities": list(effective_model_output.action_probabilities),
        **behavior_policy_fields,
        "on_policy_behavior_receipt_rejection_reasons": list(
            behavior_receipt_rejections
        ),
        **action_diagnostics,
        "expected_move_bps": effective_model_output.expected_move_bps,
        "expected_move_after_cost_bps": expected_after_cost,
        "round_trip_cost_bps": abs(float(round_trip_cost_bps)),
        "exact_cost_provenance": dict(cost_provenance or {}),
        "exact_cost_provenance_valid": not ordinary_exact_cost_rejection_reasons,
        "exact_cost_provenance_rejection_reasons": list(
            ordinary_exact_cost_rejection_reasons
        ),
        "confidence_raw": effective_model_output.confidence_raw,
        "confidence_calibrated": effective_model_output.confidence_calibrated,
        "confidence_calibration": confidence_calibration,
        "confidence_calibration_fitted": confidence_calibration_fitted,
        "confidence_label_semantics": confidence_calibration.get("label_semantics"),
        "confidence_head_schema_version": confidence_calibration.get(
            "confidence_head_schema_version"
        ),
        "confidence_head_actions": confidence_calibration.get(
            "confidence_head_actions"
        ),
        "confidence_head_action_index": confidence_calibration.get(
            "confidence_head_action_index"
        ),
        "confidence_raw_by_direction": confidence_calibration.get(
            "confidence_raw_by_direction"
        ),
        "confidence_model_parameter_fingerprint": confidence_calibration.get(
            "model_parameter_fingerprint"
        ),
        "confidence_source": (
            "CHECKPOINT_BOUND_PER_ACTION_PROFITABILITY_MODEL"
            if confidence_calibration_fitted
            else "UNFITTED_MODEL_CONFIDENCE_BLOCKED"
        ),
        "masa_confidence_source": "NOT_COMBINED_WITH_PROFITABILITY_CONFIDENCE",
        "ppo_confidence_source": "NOT_POLICY_SELECTION_PROBABILITY",
        "combined_confidence_source": "NONE_SELECTED_DIRECTIONAL_PROFITABILITY_HEAD_ONLY",
        "confidence_scale": (
            "0-1 probability selected directional action is profitable after explicit costs"
            if confidence_calibration_fitted
            else "unfitted fail-closed sentinel"
        ),
        **quality_evidence,
        "ordinary_paper_admission_schema_version": (
            ORDINARY_PAPER_ADMISSION_SCHEMA_VERSION
        ),
        "ordinary_paper_admission_mode": (
            "SCALE_FREE_CONTINUOUS_QUALITY_PAPER_ONLY"
        ),
        "ordinary_paper_admission_rejection_reasons": list(
            ordinary_paper_admission_rejection_reasons
        ),
        "legacy_static_thresholds_telemetry_only": {
            "min_data_coverage_percent": float(min_data_coverage_percent),
            "min_confidence_calibrated": float(min_confidence_calibrated),
            "min_edge_after_cost_bps": float(min_edge_after_cost_bps),
            "legacy_would_allow": legacy_static_market_threshold_would_allow,
            "controls_ordinary_paper_fill": False,
            "controls_ordinary_orchestrator_handoff": False,
            "controls_ordinary_risk_handoff": False,
        },
        "proof_only": False,
        "model_consumable": True,
        "paper_intent_consumable": True,
        "routeability_candidate": True,
        "policy_value": effective_model_output.policy_value,
        "masa_signal": effective_model_output.masa_signal,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "feature_tensor_id": tensor.tensor_id,
        "feature_cutoff": feature_cutoff,
        "available_at": trust_row.get("available_at") or trust_row.get("source_available_time"),
        "source_event_time": trust_row.get("source_event_time"),
        "source_event_time_est": trust_row.get("source_event_time_est"),
        "source_received_time": trust_row.get("source_received_time"),
        "source_received_time_est": trust_row.get("source_received_time_est"),
        "source_available_time": trust_row.get("source_available_time"),
        "candle_closed_confirmed": trust_row.get("candle_closed_confirmed"),
        "candle_open_time": trust_row.get("candle_open_time"),
        "candle_close_time": trust_row.get("candle_close_time"),
        "masa_feature_cutoff": masa_feature_cutoff,
        "ppo_feature_cutoff": ppo_feature_cutoff,
        "ppo_decision_time": generated_utc,
        "all_tf_candle_timestamps": list(trust_row.get("all_tf_candle_timestamps") or []),
        "all_source_event_times": list(trust_row.get("all_source_event_times") or []),
        "row_classification": str(example.row_classification or "").upper(),
        "trust_row_accepted_for_training": trust_row.get("accepted_for_training"),
        "trust_row_valid_for_training": trust_row.get("valid_for_training"),
        "trust_row_trainer_consumable": trust_row.get("trainer_consumable"),
        "training_trust_reject_reasons": list(trust_reject_reasons),
        "feature_freshness_state": trust_row.get("feature_freshness_state"),
        "freshness_state": trust_row.get("freshness_state"),
        "backfilled": bool(trust_row.get("backfilled")),
        "is_backfilled": bool(trust_row.get("is_backfilled")),
        "missing_candle_count": trust_row.get("missing_candle_count", 0),
        "duplicate_event_count": trust_row.get("duplicate_event_count", 0),
        "out_of_order_event_count": trust_row.get("out_of_order_event_count", 0),
        "feature_vector_hash": feature_hash,
        "source_hashes": source_hashes,
        "microstructure_trust_evidence": microstructure_trust_evidence,
        "microstructure_trust_evidence_sha256": (
            microstructure_trust_evidence_sha256
        ),
        "microstructure_trust_evidence_rejection_reasons": list(
            microstructure_trust_evidence_rejections
        ),
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
        "checkpoint_id": checkpoint_id,
        "checkpoint_manifest_path": checkpoint.path if checkpoint else None,
        "model_id": effective_model_output.model_id,
        "model_device": effective_model_output.device,
        "cuda_active": effective_model_output.cuda_active,
        "model_tensors_device_verified": (
            effective_model_output.model_tensors_device_verified
        ),
        "paper_fill_allowed": paper_fill_allowed,
        "ordinary_paper_fill_allowed": ordinary_paper_fill_allowed,
        "ordinary_paper_gate_block_reasons": ordinary_paper_gate_block_reasons,
        "adaptive_paper_exploration_fill_allowed": (
            adaptive_paper_exploration_fill_allowed
        ),
        "adaptive_paper_exploration_static_market_gate_bypassed": bool(
            adaptive_paper_exploration_fill_allowed
            and not legacy_static_market_threshold_would_allow
        ),
        "ordinary_paper_legacy_static_threshold_bypassed": bool(
            ordinary_paper_fill_allowed
            and not legacy_static_market_threshold_would_allow
        ),
        "adaptive_paper_exploration_immutable_safety_gate_passed": (
            adaptive_immutable_paper_admission_safe
            and sampling_plan_safe
        ),
        "adaptive_paper_exploration_row_integrity_rejection_reasons": list(
            adaptive_row_rejection_reasons
        ),
        "adaptive_paper_exploration_plan_rejection_reasons": list(
            adaptive_sampling_plan_rejection_reasons
        ),
        "adaptive_paper_exploration_legacy_integrity_score_bypassed": bool(
            adaptive_paper_exploration_fill_allowed
            and (
                integrity["valid_for_prediction"] is not True
                or integrity["valid_for_paper"] is not True
                or integrity["valid_for_orchestrator"] is not True
                or integrity["valid_for_risk"] is not True
            )
        ),
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
        "replay_snapshot_write_acknowledged": False,
        "replay_snapshot_readback_verified": False,
        "replay_snapshot_content_sha256": None,
        "replay_snapshot_ttl_seconds": None,
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


def trainer_status_publication_timing(
    *,
    expected_cycle_cadence_seconds: int,
    generated: datetime | None = None,
) -> dict[str, Any]:
    """Build the shared causal clock/TTL contract for one trainer cycle."""

    cadence_seconds = int(expected_cycle_cadence_seconds)
    if cadence_seconds <= 0:
        raise ValueError("trainer_status_cadence_must_be_positive")
    ttl_seconds = max(1, cadence_seconds * 3)
    observed = generated or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("trainer_status_publication_clock_must_be_aware")
    observed = observed.astimezone(timezone.utc)
    return {
        "generated_utc": observed.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "expires_at": (
            observed + timedelta(seconds=ttl_seconds)
        ).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "ttl_seconds": ttl_seconds,
        "expected_cycle_cadence_seconds": cadence_seconds,
    }


class V2HybridPredictionPublisher:
    def __init__(
        self,
        *,
        io: V2OnlyJsonIO | None = None,
        behavior_receipt_archive_root: Path | None = None,
        current_cycle_publication_ttl_seconds: int | None = None,
    ) -> None:
        self.io = io or V2OnlyJsonIO(client=None)
        self.behavior_receipt_archive_root = behavior_receipt_archive_root
        if (
            current_cycle_publication_ttl_seconds is not None
            and (
                isinstance(current_cycle_publication_ttl_seconds, bool)
                or int(current_cycle_publication_ttl_seconds) <= 0
            )
        ):
            raise ValueError("current_cycle_publication_ttl_must_be_positive")
        self.current_cycle_publication_ttl_seconds = (
            int(current_cycle_publication_ttl_seconds)
            if current_cycle_publication_ttl_seconds is not None
            else None
        )

    def _publish_current_cycle_json(
        self,
        *,
        key: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Require an ACK and exact readback for canonical current-cycle keys."""

        identity_values = (
            payload.get("cycle_id"),
            payload.get("process_instance_id"),
            payload.get("candidate_policy_fingerprint"),
        )
        current_cycle_claimed = any(
            value not in (None, "") for value in identity_values
        )
        current_cycle_identity_complete = all(
            value not in (None, "") for value in identity_values
        )
        if current_cycle_claimed and (
            not current_cycle_identity_complete
            or self.current_cycle_publication_ttl_seconds is None
        ):
            return {
                "key": key,
                "acknowledged": False,
                "readback_verified": False,
                "expiring_write": False,
                "publication_complete": False,
                "rejection_reason": (
                    "CURRENT_CYCLE_IDENTITY_INCOMPLETE"
                    if not current_cycle_identity_complete
                    else "CURRENT_CYCLE_TTL_REQUIRED"
                ),
            }
        if self.current_cycle_publication_ttl_seconds is None:
            acknowledged = self.io.set_json(key, dict(payload))
            return {
                "key": key,
                "acknowledged": bool(acknowledged),
                "readback_verified": None,
                "expiring_write": False,
                "publication_complete": bool(acknowledged),
            }
        acknowledged = self.io.set_json_expiring(
            key,
            dict(payload),
            ex=self.current_cycle_publication_ttl_seconds,
        )
        readback = self.io.get_json(key) if acknowledged else None
        try:
            readback_verified = bool(
                acknowledged
                and isinstance(readback, Mapping)
                and canonical_sha256(dict(readback))
                == canonical_sha256(dict(payload))
            )
        except (TypeError, ValueError):
            readback_verified = False
        return {
            "key": key,
            "acknowledged": bool(acknowledged),
            "readback_verified": readback_verified,
            "expiring_write": True,
            "ttl_seconds": self.current_cycle_publication_ttl_seconds,
            "publication_complete": bool(acknowledged and readback_verified),
        }

    def publish_prediction(self, payload: dict[str, Any]) -> bool:
        if not is_publishable(payload):
            return False
        caller_payload = payload
        payload = dict(payload)
        receipt = payload.get("behavior_policy_receipt")
        exact_directional_candidate = (
            isinstance(receipt, Mapping)
            and payload.get("on_policy_action_receipt_valid") is True
            and str(payload.get("selected_action") or "").lower()
            in {"long", "short"}
            and payload.get("paper_fill_allowed") is True
            and payload.get("routes_to_orchestrator") is True
        )
        if exact_directional_candidate:
            receipt_reasons = behavior_receipt_rejection_reasons(
                receipt,
                expected_prediction_id=payload.get("prediction_id"),
                expected_symbol=payload.get("symbol"),
                expected_timeframe=payload.get("timeframe"),
                expected_action=payload.get("selected_action"),
                expected_action_index=payload.get("selected_action_index"),
                expected_checkpoint_id=payload.get("checkpoint_id"),
                expected_checkpoint_weight_sha256=payload.get(
                    "behavior_policy_checkpoint_hash"
                ),
                expected_feature_tensor_id=payload.get("feature_tensor_id"),
                expected_feature_vector_hash=payload.get("feature_vector_hash"),
                expected_feature_cutoff=payload.get("feature_cutoff"),
                expected_available_at=payload.get("available_at"),
                expected_decision_time=payload.get("decision_time"),
                expected_policy_fingerprint=payload.get(
                    "behavior_policy_fingerprint"
                ),
                expected_sampling_plan_hash=payload.get(
                    "on_policy_sampling_plan_hash"
                ),
                expected_sampling_plan_input_hash=payload.get(
                    "on_policy_sampling_plan_input_hash"
                ),
            )
            receipt_hash = receipt.get("receipt_hash")
            receipt_key = (
                f"v2:trainer:hybrid_cuda:on_policy_receipt:{receipt_hash}"
                if receipt_hash
                else None
            )
            archive_written = False
            archive_error: str | None = None
            try:
                if receipt_reasons:
                    raise BehaviorReceiptArchiveError(
                        "RECEIPT_VALIDATION_FAILED_BEFORE_ARCHIVE"
                    )
                archived_receipt = archive_behavior_receipt(
                    receipt,
                    root=self.behavior_receipt_archive_root,
                )
                published_event = append_behavior_receipt_lifecycle_event(
                    receipt_hash=archived_receipt.receipt_hash,
                    event_type=EVENT_PUBLISHED,
                    binding={
                        "prediction_id": payload.get("prediction_id"),
                        "symbol": payload.get("symbol"),
                        "timeframe": payload.get("timeframe"),
                        "checkpoint_id": payload.get("checkpoint_id"),
                        **(
                            {"decision_time": payload.get("decision_time")}
                            if payload.get("decision_time") not in (None, "")
                            else {}
                        ),
                        "archive_content_sha256": (
                            archived_receipt.archive_content_sha256
                        ),
                    },
                    root=self.behavior_receipt_archive_root,
                )
                archive_written = True
                payload.update(
                    {
                        "behavior_policy_receipt_archive_schema_version": (
                            "v2_durable_behavior_receipt_archive_v1"
                        ),
                        "behavior_policy_receipt_archive_write_success": True,
                        "behavior_policy_receipt_archive_content_sha256": (
                            archived_receipt.archive_content_sha256
                        ),
                        "behavior_policy_receipt_archive_blob_path": str(
                            archived_receipt.blob_path
                        ),
                        "behavior_policy_receipt_archive_published_event_hash": (
                            published_event.event_hash
                        ),
                    }
                )
            except BehaviorReceiptArchiveError as exc:
                archive_error = str(exc)
                payload.update(
                    {
                        "behavior_policy_receipt_archive_write_success": False,
                        "behavior_policy_receipt_archive_error": archive_error,
                    }
                )
            receipt_written = bool(
                not receipt_reasons
                and receipt_key
                and archive_written
                and self.io.set_json_immutable(
                    receipt_key,
                    dict(receipt),
                    # The receipt must outlive the paper position and any
                    # delayed trainer replay.  A fixed TTL can erase the exact
                    # behavior proof before its finalized outcome exists.
                    ex=None,
                )
            )
            payload["behavior_policy_receipt_key"] = receipt_key
            payload["behavior_policy_receipt_write_success"] = receipt_written
            replay_snapshot = payload.get("replay_snapshot")
            if isinstance(replay_snapshot, dict):
                replay_snapshot["behavior_policy_receipt_key"] = receipt_key
                replay_snapshot[
                    "behavior_policy_receipt_write_success"
                ] = receipt_written
            if not receipt_written:
                reasons = list(payload.get("paper_fill_gate_block_reasons") or [])
                reasons.extend(
                    f"on_policy_behavior_receipt:{reason}"
                    for reason in receipt_reasons
                )
                if not receipt_reasons:
                    reasons.append(
                        "on_policy_behavior_receipt:immutable_write_failed"
                        if archive_error is None
                        else "on_policy_behavior_receipt:durable_archive_write_failed"
                    )
                payload["paper_fill_gate_block_reasons"] = sorted(set(reasons))
                payload["paper_fill_allowed"] = False
                payload["routes_to_orchestrator"] = False
                payload["prediction_eligible"] = False
                payload["risk_eligible"] = False
                payload["paper_eligible"] = False
                payload["ppo_on_policy_ineligible_reason"] = (
                    "IMMUTABLE_BEHAVIOR_POLICY_RECEIPT_NOT_DURABLE"
                )
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
                prediction_receipt = self._publish_current_cycle_json(
                    key=key,
                    payload=payload,
                )
                published = prediction_receipt["publication_complete"] is True
                if published:
                    # The following lineage/risk publication must evaluate the
                    # exact payload that was durably published, including any
                    # fail-closed archive or trust mutations made above.
                    caller_payload.update(payload)
                return published
            snapshot_key = f"v2:replay:snapshots:{payload['prediction_id']}"
            snapshot_ttl_seconds = 86_400
            try:
                snapshot_hash = canonical_sha256(dict(snapshot))
            except (TypeError, ValueError):
                payload["replay_snapshot_publication_error"] = (
                    "REPLAY_SNAPSHOT_NOT_CANONICALLY_HASHABLE"
                )
                caller_payload.update(payload)
                return False
            snapshot_acknowledged = self.io.set_json_expiring(
                snapshot_key,
                snapshot,
                ex=snapshot_ttl_seconds,
            )
            snapshot_readback = (
                self.io.get_json(snapshot_key) if snapshot_acknowledged else None
            )
            try:
                snapshot_readback_verified = bool(
                    snapshot_acknowledged
                    and isinstance(snapshot_readback, Mapping)
                    and canonical_sha256(dict(snapshot_readback)) == snapshot_hash
                )
            except (TypeError, ValueError):
                snapshot_readback_verified = False
            payload["replay_snapshot_write_acknowledged"] = bool(
                snapshot_acknowledged
            )
            payload["replay_snapshot_readback_verified"] = (
                snapshot_readback_verified
            )
            payload["replay_snapshot_content_sha256"] = snapshot_hash
            payload["replay_snapshot_ttl_seconds"] = snapshot_ttl_seconds
            if not snapshot_readback_verified:
                payload["replay_snapshot_write_success"] = False
                payload["replay_snapshot_publication_error"] = (
                    "REPLAY_SNAPSHOT_EXACT_READBACK_FAILED"
                )
                caller_payload.update(payload)
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
        prediction_receipt = self._publish_current_cycle_json(
            key=key,
            payload=payload,
        )
        published = prediction_receipt["publication_complete"] is True
        if published:
            # ``run_cycle`` passes this same object into ``publish_lineage``.
            # Propagate replay_snapshot_write_success/key/id back to it so the
            # risk contract cannot deny a snapshot that was actually written.
            caller_payload.update(payload)
        return published

    @staticmethod
    def status_publication_timing(
        *,
        expected_cycle_cadence_seconds: int,
        generated: datetime | None = None,
    ) -> dict[str, Any]:
        return trainer_status_publication_timing(
            expected_cycle_cadence_seconds=expected_cycle_cadence_seconds,
            generated=generated,
        )

    def publish_status(
        self,
        *,
        status: dict[str, Any],
        metrics: dict[str, Any],
        expected_cycle_cadence_seconds: int,
        publication_timing: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        timing = dict(publication_timing or self.status_publication_timing(
            expected_cycle_cadence_seconds=expected_cycle_cadence_seconds
        ))
        cadence_seconds = int(timing.get("expected_cycle_cadence_seconds") or 0)
        ttl_seconds = int(timing.get("ttl_seconds") or 0)
        generated_utc = str(timing.get("generated_utc") or "")
        expires_at = str(timing.get("expires_at") or "")
        if (
            cadence_seconds != int(expected_cycle_cadence_seconds)
            or cadence_seconds <= 0
            or ttl_seconds != cadence_seconds * 3
            or not generated_utc
            or not expires_at
        ):
            raise ValueError("trainer_status_publication_timing_invalid")
        cycle_id = str(status.get("cycle_id") or "")
        instance_id = str(status.get("process_instance_id") or "")
        envelope = status.get("current_cycle_learning_envelope")
        envelope_map = dict(envelope) if isinstance(envelope, Mapping) else {}
        envelope_bound = bool(
            cycle_id
            and instance_id == local_process_instance_id()
            and envelope_map.get("cycle_id") == cycle_id
            and envelope_map.get("process_instance_id") == instance_id
        )
        envelope_identity = {
            "cycle_id": cycle_id or None,
            "process_instance_id": instance_id or None,
            "checkpoint_id": envelope_map.get("checkpoint_id"),
            "candidate_policy_fingerprint": envelope_map.get(
                "candidate_policy_fingerprint"
            ),
            "envelope_sha256": (
                canonical_sha256(envelope_map) if envelope_map else None
            ),
        }
        heartbeat = {
            "generated_est": _est_iso(),
            "generated_utc": generated_utc,
            "expires_at": expires_at,
            "ttl_seconds": ttl_seconds,
            "expected_cycle_cadence_seconds": cadence_seconds,
            "cycle_id": cycle_id or None,
            "process_instance_id": instance_id or None,
            # ``process_instance_id`` includes a restart nonce and is opaque to
            # consumers.  Once it is proven equal to this process's identity,
            # report the PID from the process itself instead of parsing tokens.
            "process_id": os.getpid() if envelope_bound else None,
            "current_cycle_learning_envelope_identity": envelope_identity,
            "liveness_semantics": "ACTIVE_ONLY_UNTIL_EXPIRES_AT",
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
            "expires_at": expires_at,
            "ttl_seconds": ttl_seconds,
            "cycle_id": cycle_id or None,
            "process_instance_id": instance_id or None,
            "current_cycle_learning_envelope_identity": envelope_identity,
        }
        # First replace any earlier READY status with a short-lived BLOCKED
        # staging record.  Only the final write below can expose READY, and it
        # is attempted after every independent expiring prerequisite has been
        # acknowledged by Redis.
        staging_status = {
            **status,
            "runtime_readiness_status": "BLOCKED",
            "trainer_learning_ready": False,
            "status_publication_status": "PENDING",
            "runtime_readiness_blockers": list(
                dict.fromkeys(
                    [
                        *list(status.get("runtime_readiness_blockers") or ()),
                        "FINAL_STATUS_TTL_ACK_PENDING",
                    ]
                )
            ),
        }
        staging_status.pop("current_cycle_learning_envelope", None)
        staging_written = self.io.set_json_expiring(
            REDIS_STATUS_KEY,
            staging_status,
            ex=ttl_seconds,
        )
        heartbeat_written = self.io.set_json_expiring(
            REDIS_HEARTBEAT_KEY, heartbeat, ex=ttl_seconds
        )
        metrics_payload = {
            **metrics,
            "cycle_id": cycle_id or None,
            "process_instance_id": instance_id or None,
            "current_cycle_learning_envelope_identity": envelope_identity,
        }
        metrics_written = self.io.set_json_expiring(
            REDIS_METRICS_KEY, metrics_payload, ex=ttl_seconds
        )
        feature_status_written = self.io.set_json_expiring(
            "v2:trainer:feature_schema_status",
            feature_schema_status,
            ex=ttl_seconds,
        )
        prerequisite_writes = bool(
            envelope_bound
            and staging_written
            and heartbeat_written
            and metrics_written
            and feature_status_written
        )
        if not prerequisite_writes:
            blockers = list(status.get("runtime_readiness_blockers") or ())
            blockers.append("STATUS_PUBLICATION_FAILED")
            status["runtime_readiness_blockers"] = list(dict.fromkeys(blockers))
            status["runtime_readiness_status"] = "BLOCKED"
        publication_preview = {
            "schema_version": "v2_trainer_expiring_status_publication_v1",
            "publication_complete": prerequisite_writes,
            "component_results": {
                "blocked_staging_status": bool(staging_written),
                "heartbeat": bool(heartbeat_written),
                "metrics": bool(metrics_written),
                "feature_schema_status": bool(feature_status_written),
                # This field is true only in the payload submitted by the
                # final status write.  If that write is not acknowledged, the
                # BLOCKED staging record remains the externally visible truth.
                "status": bool(prerequisite_writes),
            },
            "generated_utc": generated_utc,
            "expires_at": expires_at,
            "ttl_seconds": ttl_seconds,
            "expected_cycle_cadence_seconds": cadence_seconds,
            "cycle_id": cycle_id or None,
            "process_instance_id": instance_id or None,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        status.update(
            {
                "status_payload_expires_at": expires_at,
                "status_payload_ttl_seconds": ttl_seconds,
                "expected_cycle_cadence_seconds": cadence_seconds,
                "cycle_id": cycle_id or None,
                "process_instance_id": instance_id or None,
                "current_cycle_learning_envelope_identity": envelope_identity,
                "status_publication_status": (
                    "ACTIVE" if prerequisite_writes else "FAILED"
                ),
                "status_publication_component_results": {
                    "heartbeat": bool(heartbeat_written),
                    "metrics": bool(metrics_written),
                    "feature_schema_status": bool(feature_status_written),
                    "blocked_staging_status": bool(staging_written),
                    "status": bool(prerequisite_writes),
                },
                "status_publication": publication_preview,
            }
        )
        status_written = bool(
            prerequisite_writes
            and self.io.set_json_expiring(
                REDIS_STATUS_KEY,
                status,
                ex=ttl_seconds,
            )
        )
        complete = bool(prerequisite_writes and status_written)
        status["status_publication_status"] = "ACTIVE" if complete else "FAILED"
        status["status_publication_component_results"]["status"] = bool(
            status_written
        )
        result = {
            "schema_version": "v2_trainer_expiring_status_publication_v1",
            "publication_complete": complete,
            "component_results": dict(
                status["status_publication_component_results"]
            ),
            "generated_utc": generated_utc,
            "expires_at": expires_at,
            "ttl_seconds": ttl_seconds,
            "expected_cycle_cadence_seconds": cadence_seconds,
            "cycle_id": cycle_id or None,
            "process_instance_id": instance_id or None,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        if complete:
            # The persisted final payload already contains the byte-equivalent
            # publication result built above.  Keep the returned object equal.
            status["status_publication"] = result
        else:
            blockers = list(status.get("runtime_readiness_blockers") or ())
            blockers.append("FINAL_STATUS_TTL_ACK_FAILED")
            status.update(
                {
                    "runtime_readiness_status": "BLOCKED",
                    "trainer_learning_ready": False,
                    "status_publication_status": "FAILED",
                    "runtime_readiness_blockers": list(dict.fromkeys(blockers)),
                    "status_publication": result,
                }
            )
        status["current_cycle_heartbeat_evidence"] = heartbeat
        return result

    def publish_lineage(
        self,
        *,
        prediction_payload: dict[str, Any],
        min_confidence_calibrated: float,
        min_data_coverage_percent: float,
        risk_caps_configured: bool,
    ) -> dict[str, Any]:
        prediction_record = to_trainer_prediction_record(prediction_payload)
        ordinary_scale_free_rejection_reasons = (
            _ordinary_scale_free_payload_rejection_reasons(
                prediction_payload,
                require_replay_write=True,
            )
        )
        ordinary_scale_free_admission = bool(
            not ordinary_scale_free_rejection_reasons
        )
        adaptive_exploration = bool(
            prediction_payload.get("adaptive_paper_exploration_fill_allowed")
            is True
            and prediction_payload.get("on_policy_sampling_selected") is True
            and prediction_payload.get("on_policy_sampling_routes_to_live") is False
            and prediction_payload.get(
                "adaptive_paper_exploration_immutable_safety_gate_passed"
            )
            is True
            and not prediction_payload.get(
                "adaptive_paper_exploration_row_integrity_rejection_reasons"
            )
            and not prediction_payload.get(
                "adaptive_paper_exploration_plan_rejection_reasons"
            )
            and prediction_payload.get("live_gate") == LIVE_GATE_BLOCKED
            and prediction_payload.get("live_symbols") == []
            and prediction_payload.get("exchange_mutation") is False
            and prediction_payload.get("trainer_direct_trading") is False
        )
        orchestrator_record = assemble_orchestrator_decision_record(
            prediction=prediction_record,
            # Both native trainer lanes are PAPER-only and revalidate their
            # immutable evidence independently.  Probability magnitude scales
            # paper quality; it is not an orchestrator admission threshold.
            low_confidence_threshold=0.0,
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
            record["cycle_id"] = prediction_payload.get("cycle_id")
            record["process_instance_id"] = prediction_payload.get(
                "process_instance_id"
            )
            record["candidate_policy_fingerprint"] = prediction_payload.get(
                "candidate_policy_fingerprint"
            )
            record["ordinary_scale_free_paper_admission_revalidated"] = (
                ordinary_scale_free_admission
            )
            record["adaptive_paper_exploration_revalidated_for_lineage"] = (
                adaptive_exploration
            )
            record["ordinary_scale_free_paper_admission_rejection_reasons"] = list(
                ordinary_scale_free_rejection_reasons
            )
            record["paper_quality_sizing_weight"] = prediction_payload.get(
                "paper_quality_sizing_weight"
            )
            record["paper_quality_sizing_formula"] = prediction_payload.get(
                "paper_quality_sizing_formula"
            )
            record["legacy_static_thresholds_telemetry_only"] = dict(
                prediction_payload.get("legacy_static_thresholds_telemetry_only")
                or {}
            )
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
            for field in DECISION_TEMPORAL_LINEAGE_FIELDS:
                if field in prediction_payload:
                    record[field] = prediction_payload.get(field)
            for field in BEHAVIOR_POLICY_LINEAGE_FIELDS:
                if field in prediction_payload:
                    record[field] = prediction_payload.get(field)
            for field in DURABLE_RECEIPT_LINEAGE_FIELDS:
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
            "paper_quality_sizing_weight": prediction_payload.get(
                "paper_quality_sizing_weight"
            ),
            "ordinary_scale_free_paper_admission_revalidated": (
                ordinary_scale_free_admission
            ),
            "adaptive_paper_exploration_revalidated_for_lineage": (
                adaptive_exploration
            ),
            "ordinary_scale_free_paper_admission_rejection_reasons": list(
                ordinary_scale_free_rejection_reasons
            ),
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
        signal_payload["cycle_id"] = prediction_payload.get("cycle_id")
        signal_payload["process_instance_id"] = prediction_payload.get(
            "process_instance_id"
        )
        signal_payload["candidate_policy_fingerprint"] = prediction_payload.get(
            "candidate_policy_fingerprint"
        )
        signal_payload["source_hashes"] = dict(prediction_payload.get("source_hashes") or {})
        signal_payload["feature_vector_hash"] = prediction_payload.get("feature_vector_hash")
        signal_payload["all_tf_candle_timestamps"] = list(prediction_payload.get("all_tf_candle_timestamps") or [])
        signal_payload["all_source_event_times"] = list(prediction_payload.get("all_source_event_times") or [])
        signal_payload["source_candle_timestamps"] = list(prediction_payload.get("source_candle_timestamps") or [])
        signal_payload["input_feature_hash"] = prediction_payload.get("input_feature_hash")
        signal_payload["replay_snapshot_key"] = prediction_payload.get("replay_snapshot_key")
        signal_payload["replay_snapshot_write_success"] = prediction_payload.get("replay_snapshot_write_success")
        # Entry-policy diagnostics come from the same forward pass, but this
        # policy selects through deterministic expected-move alignment rather
        # than a categorical draw.  Preserve the probability telemetry while
        # explicitly marking it ineligible for an on-policy PPO ratio.
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
        for field in BEHAVIOR_POLICY_LINEAGE_FIELDS:
            signal_payload[field] = prediction_payload.get(field)
        for field in DURABLE_RECEIPT_LINEAGE_FIELDS:
            signal_payload[field] = prediction_payload.get(field)
        signal_payload["trust_gate_result"] = lineage_contract.to_dict()
        for field in PROVIDER_LINEAGE_FIELDS:
            if field in prediction_payload:
                signal_payload[field] = prediction_payload.get(field)
        for field in DECISION_TEMPORAL_LINEAGE_FIELDS:
            if field in prediction_payload:
                signal_payload[field] = prediction_payload.get(field)
        if not lineage_contract.allowed:
            signal_payload = mark_runtime_trust_denied(signal_payload, lineage_contract)
        # These locally assembled records are trainer proposals for observability
        # and paper-signal handoff only.  The orchestrator and risk workers are the
        # sole owners of canonical decisions and their per-ID indexes.
        for preview_record in (orchestrator_dict, risk_dict, paper_entry_dict):
            preview_record["authoritative_decision"] = False
            preview_record["record_authority"] = (
                "TRAINER_NON_AUTHORITATIVE_PROPOSAL"
            )
            preview_record["proposal_source"] = TRAINER_SOURCE
        signal_payload["authoritative_decision"] = False
        signal_payload["record_authority"] = "TRAINER_NON_AUTHORITATIVE_PROPOSAL"
        signal_payload["proposal_source"] = TRAINER_SOURCE
        proposal_payloads = (
            (ORCHESTRATOR_DECISIONS_KEY, orchestrator_dict),
            (RISK_DECISIONS_KEY, risk_dict),
            (PAPER_LEDGER_KEY, paper_entry_dict),
            (PAPER_INTENTS_KEY, signal_payload),
            (
                PAPER_POSITIONS_KEY,
                {
                    "generated_est": _est_iso(),
                    "paper_shadow_only": True,
                    "authoritative_decision": False,
                    "record_authority": "TRAINER_NON_AUTHORITATIVE_PROPOSAL",
                    "cycle_id": prediction_payload.get("cycle_id"),
                    "process_instance_id": prediction_payload.get(
                        "process_instance_id"
                    ),
                    "candidate_policy_fingerprint": prediction_payload.get(
                        "candidate_policy_fingerprint"
                    ),
                },
            ),
            (
                PAPER_BLOCK_REASONS_KEY,
                {
                    "block_reasons": prediction_payload[
                        "paper_fill_gate_block_reasons"
                    ],
                    "authoritative_decision": False,
                    "record_authority": "TRAINER_NON_AUTHORITATIVE_PROPOSAL",
                    "cycle_id": prediction_payload.get("cycle_id"),
                    "process_instance_id": prediction_payload.get(
                        "process_instance_id"
                    ),
                    "candidate_policy_fingerprint": prediction_payload.get(
                        "candidate_policy_fingerprint"
                    ),
                },
            ),
            (PAPER_SIGNAL_LINEAGE_KEY, signal_payload),
            (
                PAPER_SIGNAL_KEY_TEMPLATE.format(
                    symbol=prediction_payload["symbol"]
                ),
                signal_payload,
            ),
            (
                PAPER_SIGNAL_TIMEFRAME_KEY_TEMPLATE.format(
                    symbol=prediction_payload["symbol"],
                    timeframe=prediction_payload["timeframe"],
                ),
                signal_payload,
            ),
        )
        proposal_receipts = [
            self._publish_current_cycle_json(key=key, payload=proposal_payload)
            for key, proposal_payload in proposal_payloads
        ]
        proposal_publication_complete = bool(
            proposal_receipts
            and all(
                receipt.get("publication_complete") is True
                for receipt in proposal_receipts
            )
        )
        publication_receipt = {
            "schema_version": (
                "v2_trainer_nonauthoritative_proposal_publication_receipt_v1"
            ),
            "cycle_id": prediction_payload.get("cycle_id"),
            "process_instance_id": prediction_payload.get(
                "process_instance_id"
            ),
            "checkpoint_id": prediction_payload.get("checkpoint_id"),
            "candidate_policy_fingerprint": prediction_payload.get(
                "candidate_policy_fingerprint"
            ),
            "publication_complete": proposal_publication_complete,
            "component_receipts": proposal_receipts,
            "publication_scope": (
                "TRAINER_NONAUTHORITATIVE_PROPOSALS_ONLY"
            ),
            "authoritative_orchestrator_consumption_attested": False,
            "authoritative_risk_consumption_attested": False,
            "authoritative_paper_consumption_attested": False,
            "counts_as_end_to_end_authoritative_lineage": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        if not proposal_publication_complete:
            failed_keys = [
                str(receipt.get("key") or "UNKNOWN")
                for receipt in proposal_receipts
                if receipt.get("publication_complete") is not True
            ]
            raise RuntimeError(
                "nonauthoritative_proposal_publication_incomplete:"
                + ",".join(failed_keys)
            )
        return {
            "cycle_id": prediction_payload.get("cycle_id"),
            "process_instance_id": prediction_payload.get("process_instance_id"),
            "checkpoint_id": prediction_payload.get("checkpoint_id"),
            "candidate_policy_fingerprint": prediction_payload.get(
                "candidate_policy_fingerprint"
            ),
            "publication_receipt": publication_receipt,
            "authoritative_consumer_lineage_complete": False,
            "trainer_prediction_record": {
                **dataclasses.asdict(prediction_record),
                "cycle_id": prediction_payload.get("cycle_id"),
                "process_instance_id": prediction_payload.get(
                    "process_instance_id"
                ),
                "candidate_policy_fingerprint": prediction_payload.get(
                    "candidate_policy_fingerprint"
                ),
            },
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
    adaptive_exploration = bool(
        prediction_payload.get("adaptive_paper_exploration_fill_allowed") is True
        and prediction_payload.get(
            "adaptive_paper_exploration_immutable_safety_gate_passed"
        )
        is True
        and prediction_payload.get("on_policy_sampling_routes_to_live") is False
        and not prediction_payload.get(
            "adaptive_paper_exploration_row_integrity_rejection_reasons"
        )
        and not prediction_payload.get(
            "adaptive_paper_exploration_plan_rejection_reasons"
        )
        and prediction_payload.get("live_gate") == LIVE_GATE_BLOCKED
        and prediction_payload.get("live_symbols") == []
        and prediction_payload.get("exchange_mutation") is False
        and prediction_payload.get("trainer_direct_trading") is False
    )
    ordinary_scale_free_rejection_reasons = (
        _ordinary_scale_free_payload_rejection_reasons(
            prediction_payload,
            require_replay_write=True,
        )
    )
    ordinary_scale_free_admission = not ordinary_scale_free_rejection_reasons
    calibration = prediction_payload.get("confidence_calibration")
    calibrated_probability = _finite_float(
        prediction_payload.get("confidence_calibrated")
    )
    calibration_ok = bool(
        prediction_payload.get("confidence_calibration_fitted") is True
        and isinstance(calibration, Mapping)
        and calibration.get("calibration_fitted") is True
        and calibration.get("probability_semantics_valid") is True
        and calibration.get("label_semantics") == CONFIDENCE_LABEL_SEMANTICS
        and calibration.get("confidence_head_schema_version")
        == CONFIDENCE_HEAD_SCHEMA_VERSION
        and tuple(calibration.get("confidence_head_actions") or ())
        == CONFIDENCE_HEAD_ACTIONS
        and calibration.get("selected_action_is_directional") is True
        and calibration.get("selected_action")
        == str(prediction_payload.get("selected_action") or "").strip().lower()
        and _is_sha256_hex(calibration.get("model_parameter_fingerprint"))
        and calibrated_probability is not None
        and 0.0 <= calibrated_probability <= 1.0
    )
    if tradable and (
        not risk_caps_configured
        or not (ordinary_scale_free_admission or adaptive_exploration)
        or not calibration_ok
    ):
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
        "go_no_go": (
            TRAINER_CORE_PAPER_SHADOW_GO_NO_GO
            if status.get("runtime_readiness_status") == "READY"
            else "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_BLOCKED"
        ),
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
