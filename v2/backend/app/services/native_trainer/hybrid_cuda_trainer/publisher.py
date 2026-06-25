"""Prediction publisher and decision-lineage adapter for the hybrid trainer."""
from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import datetime, timezone
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
    feature_snapshot = {
        "feature_snapshot_id": example.tensor.feature_snapshot_id,
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "features": dict(trust_row.get("features") or {}),
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
    integrity = _market_state_fields_from_example(example, prediction_id)
    trust_row = dict(example.trust_row or {})
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
        "missing_feature_count": len(tensor.missing_feature_names),
        "stale_feature_count": len(tensor.stale_feature_names),
        "missing_feature_names": list(tensor.missing_feature_names),
        "stale_feature_names": list(tensor.stale_feature_names),
        "source_availability_vector": list(tensor.source_availability_vector),
        "feature_names": list(tensor.feature_names),
        "source_labels": list(tensor.source_labels),
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
                archived = append_snapshot(archive_record)
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
        self.io.set_json(REDIS_HEARTBEAT_KEY, heartbeat)
        self.io.set_json(REDIS_STATUS_KEY, status)
        self.io.set_json(REDIS_METRICS_KEY, metrics)

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
        signal_payload["trust_gate_result"] = lineage_contract.to_dict()
        if not lineage_contract.allowed:
            signal_payload = mark_runtime_trust_denied(signal_payload, lineage_contract)
        self.io.set_json(ORCHESTRATOR_DECISIONS_KEY, orchestrator_dict)
        self.io.set_json(RISK_DECISIONS_KEY, risk_dict)
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
