"""V2 orchestrator arbitration live loop (paper-only).

Consumes v2:prediction:*, runs the paper-only V2NativeProposalBus +
OrchestratorArbitrationService chain, emits:
- v2:orchestrator:proposals
- v2:orchestrator:decisions
- v2:signals:paper

Never writes legacy Redis. Never calls an exchange SDK.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.live_gate.runtime_execution_state import (
    LIVE_GATE_BLOCKED,
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
)
from v2.backend.app.services.market_state_integrity.scoring import score_market_state
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    BEHAVIOR_POLICY_LINEAGE_FIELDS,
    canonical_sha256,
)
from v2.backend.app.services.ordinary_paper_admission import (
    OrdinaryPaperAdmissionResult,
    assess_ordinary_paper_candidate,
    microstructure_admission_values,
)

V2_REDIS_PREFIX = "v2:"
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/live/latest/v2_orchestrator_arbitration_live_status.json"
)
MAX_PREDICTION_AGE_SECONDS = 300
PREDICTION_BY_ID_KEY_TEMPLATE = "v2:prediction_by_id:{prediction_id}"


def _runtime_default_symbol() -> str:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

    return resolve_symbols()[0]


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _live_context(r) -> dict[str, Any]:
    runtime = read_runtime_execution_state(redis_client=r)
    payload = runtime.get("payload") if isinstance(runtime.get("payload"), dict) else {}
    validation = runtime.get("validation") if isinstance(runtime.get("validation"), dict) else {}
    if validation.get("valid") and payload.get("live_gate") == LIVE_GATE_ENABLED:
        return {
            "live_gate": LIVE_GATE_ENABLED,
            "live_symbols": [str(symbol) for symbol in payload.get("live_symbols") or []],
            "execution_live_symbols": [
                str(symbol) for symbol in payload.get("execution_live_symbols") or []
            ],
            "runtime_validation": validation,
            "runtime_source": runtime.get("source"),
        }
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "runtime_validation": validation,
        "runtime_source": runtime.get("source"),
    }


def _safe_write(r, key: str, value: str, ex: int | None = None) -> bool:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            r.set(key, value, ex=int(ex))
        else:
            r.set(key, value)
        return True
    except Exception:
        return False


_PER_ID_ORCHESTRATOR_RECORD_TTL_SECONDS = 7200


def _read_json_key(r, key: str) -> dict[str, Any] | None:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = r.get(key)
        payload = json.loads(raw) if raw else None
    except (TypeError, ValueError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_per_id_orchestrator_decision_record(
    r,
    *,
    winner: dict[str, Any],
    generated_at: datetime,
) -> str:
    """Create one immutable orchestrator decision record.

    The arbitrator is the only producer allowed to own this namespace.  A
    repeated identical decision is idempotent; an ID collision with different
    identity/action is never overwritten and therefore cannot route to risk.
    """

    decision_id = str(winner.get("orchestrator_decision_id") or "")
    if r is None or not decision_id:
        return "WRITE_ERROR"
    key = f"{V2_REDIS_PREFIX}decision:orchestrator:{decision_id}"
    generated_utc = generated_at.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    expires_at = (
        generated_at.astimezone(timezone.utc)
        + timedelta(seconds=_PER_ID_ORCHESTRATOR_RECORD_TTL_SECONDS)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    side = str(winner.get("side") or "").lower()
    action = "proceed_long" if side == "long" else "proceed_short" if side == "short" else "hold"
    record = {
        "schema_version": "v2_per_id_orchestrator_decision_record_v1",
        "orchestrator_decision_id": decision_id,
        "decision_id": winner.get("decision_id"),
        "candidate_id": winner.get("winner_proposal_id"),
        "prediction_id": winner.get("prediction_id") or winner.get("winner_proposal_id"),
        "signal_id": winner.get("signal_id"),
        "symbol": winner.get("symbol"),
        "timeframe": winner.get("timeframe"),
        "side": side,
        "decision": action,
        "orchestrator_action": action,
        "status": "ORCHESTRATOR_DECISION_RECORDED",
        "route": "paper_to_risk_gateway",
        "reasons": ["ARBITRATION_BUCKET_WINNER"],
        "generated_utc": generated_utc,
        "created_at": generated_utc,
        "expires_at": expires_at,
        "producer": "v2_orchestrator_arbitration_loop",
        "routes_to_live": False,
        "places_real_order": False,
        "paper_only": True,
        "live_gate": LIVE_GATE_BLOCKED,
    }
    record.update(_copy_trust_envelope_fields(winner))
    # Reassert fields owned by this worker after copying upstream evidence.
    record.update(
        {
            "orchestrator_decision_id": decision_id,
            "prediction_id": winner.get("prediction_id")
            or winner.get("winner_proposal_id"),
            "signal_id": winner.get("signal_id"),
            "symbol": winner.get("symbol"),
            "timeframe": winner.get("timeframe"),
            "side": side,
            "decision": action,
            "orchestrator_action": action,
            "generated_utc": generated_utc,
            "created_at": generated_utc,
            "expires_at": expires_at,
            "producer": "v2_orchestrator_arbitration_loop",
            "routes_to_live": False,
            "places_real_order": False,
            "paper_only": True,
            "live_gate": LIVE_GATE_BLOCKED,
        }
    )
    try:
        created = r.set(
            key,
            json.dumps(record, sort_keys=True, default=str),
            ex=_PER_ID_ORCHESTRATOR_RECORD_TTL_SECONDS,
            nx=True,
        )
    except Exception:
        return "WRITE_ERROR"
    if created:
        return "CREATED"
    existing = _read_json_key(r, key)
    stable_fields = (
        "schema_version",
        "orchestrator_decision_id",
        "prediction_id",
        "signal_id",
        "symbol",
        "timeframe",
        "side",
        "decision",
        "orchestrator_action",
        "feature_snapshot_id",
        "market_state_id",
        "feature_vector_hash",
        "input_feature_hash",
        "ordinary_paper_admission_evidence_sha256",
        "checkpoint_generation",
        "paper_strategy_cohort_id",
        "feature_abi_sha256",
        "producer",
    )
    if existing and all(existing.get(field) == record.get(field) for field in stable_fields):
        return "EXISTING_IDENTICAL"
    return "CONFLICT"


def _bounded_scan(r, pattern: str, *, count: int = 1000, budget_seconds: float = 20.0):
    """SCAN with a large batch count + a hard time budget.

    ``scan_iter`` defaults to count=10, so matching a sparse pattern against a
    multi-million-key Redis costs ~keyspace/10 round trips -- hundreds of
    thousands -- which blows past the loop interval and effectively HANGS the
    orchestrator (observed: run_once stuck >2min, heartbeat TTL expired, no
    arbitration for hours). A large count cuts round trips ~100x and the time
    budget guarantees the scan can never hang the loop again.
    """
    deadline = time.time() + budget_seconds
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor, match=pattern, count=count)
        for key in batch:
            yield key
        if cursor == 0 or time.time() > deadline:
            break


def _scan_predictions(r) -> list[dict]:
    if r is None:
        return []
    by_prediction_id: dict[str, dict] = {}
    out_without_id: list[dict] = []
    for key in _bounded_scan(r, f"{V2_REDIS_PREFIX}prediction:*"):
        if ":rl_core:" in str(key):
            continue
        try:
            data = json.loads(r.get(key))
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict):
            prediction_id = _first_text(data.get("prediction_id"), data.get("id"))
            if not prediction_id:
                continue
            if data.get("status") == "MISSING_TF_PREDICTION":
                continue
            # Explicit False means the publisher decided this prediction must
            # not route to the orchestrator (RL-core sidecar, integrity reject,
            # or paper-fill fully blocked). Missing / None / True all pass here;
            # the main gate below re-evaluates with market-state integrity.
            if data.get("routes_to_orchestrator") is False:
                continue
            immutable_key = PREDICTION_BY_ID_KEY_TEMPLATE.format(
                prediction_id=prediction_id
            )
            try:
                immutable_raw = r.get(immutable_key)
                immutable_data = (
                    json.loads(immutable_raw) if immutable_raw else None
                )
                immutable_ttl = _finite_float(r.ttl(immutable_key), -1.0)
                immutable_matches_discovery = bool(
                    isinstance(immutable_data, dict)
                    and canonical_sha256(immutable_data) == canonical_sha256(data)
                )
            except (TypeError, ValueError):
                immutable_data = None
                immutable_ttl = -1.0
                immutable_matches_discovery = False
            if (
                not immutable_matches_discovery
                or not isinstance(immutable_data, dict)
                or immutable_ttl <= 0
            ):
                continue
            data = immutable_data
            age = _prediction_age_seconds(data)
            if age is None or age > MAX_PREDICTION_AGE_SECONDS:
                continue
            data = dict(data)
            data["source_redis_key"] = immutable_key
            data["source_prediction_current_key"] = str(key)
            data["source_prediction_observed_ttl_seconds"] = int(immutable_ttl)
            existing = by_prediction_id.get(prediction_id)
            if existing is None or _prediction_source_rank(key) > _prediction_source_rank(
                str(existing.get("source_prediction_current_key") or "")
            ):
                by_prediction_id[prediction_id] = data
    return list(by_prediction_id.values()) + out_without_id


def _load_latest_feature_row(r, prediction: dict[str, Any]) -> dict[str, Any] | None:
    if r is None:
        return None
    symbol = _first_text(prediction.get("symbol"))
    timeframe = _first_text(prediction.get("timeframe"), prediction.get("tf"))
    if not symbol or not timeframe:
        return None
    key = f"{V2_REDIS_PREFIX}features:latest:{symbol.upper()}:{timeframe}"
    try:
        raw = r.get(key)
        payload = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    prediction_snapshot_id = _first_text(
        prediction.get("feature_snapshot_id"), prediction.get("feature_tensor_id")
    )
    payload_snapshot_id = _first_text(
        payload.get("feature_snapshot_id"), payload.get("snapshot_id")
    )
    if not prediction_snapshot_id or payload_snapshot_id != prediction_snapshot_id:
        return None
    if str(payload.get("symbol") or symbol).upper() != symbol.upper():
        return None
    if str(payload.get("timeframe") or timeframe) != timeframe:
        return None
    prediction_hash = _first_text(
        prediction.get("feature_vector_hash"), prediction.get("input_feature_hash")
    )
    payload_hash = _first_text(
        payload.get("feature_vector_hash"), payload.get("input_feature_hash")
    )
    if prediction_hash and payload_hash and prediction_hash != payload_hash:
        return None
    decision_time = _parse_utc(
        _first_text(prediction.get("decision_time"), prediction.get("decision_time_est"))
    )
    available_at = _parse_utc(
        _first_text(payload.get("available_at"), payload.get("source_available_time"))
    )
    feature_cutoff = _parse_utc(
        _first_text(payload.get("feature_cutoff"), payload.get("source_event_time_est"))
    )
    if (
        decision_time is None
        or available_at is None
        or feature_cutoff is None
        or available_at > decision_time
        or feature_cutoff > decision_time
    ):
        return None
    payload["source_redis_key"] = key
    return payload


def _prediction_integrity_input(r, prediction: dict[str, Any]) -> dict[str, Any]:
    feature = _load_latest_feature_row(r, prediction)
    if feature is None:
        return dict(prediction)
    merged = dict(prediction)
    feature_contract_keys = (
        ()
        if prediction.get("serving_feature_abi_v2") is True
        else (
            "features",
            "feature_freshness_state",
            "missing_feature_count",
            "missing_feature_flags",
        )
    )
    for key in (*feature_contract_keys,
        "ohlcv_history_present",
        "orderbook_present",
        "placeholder_feature_count",
        "real_feature_count",
        "trainer_consumable",
        "external_v2_sources_present",
        # Candle completion and timing fields required for market state integrity scoring.
        # Without these the scoring receives None for candle_closed_confirmed and produces
        # CANDLE_COMPLETION_UNKNOWN + timing rejection for every prediction.
        "candle_closed_confirmed",
        "candle_close_time",
        "candle_open_time",
        "source_event_time_est",
        "source_received_time_est",
        "decision_cutoff_time_est",
    ):
        if key in feature:
            merged[key] = feature[key]
    merged["integrity_feature_snapshot_id"] = feature.get("feature_snapshot_id")
    merged["integrity_feature_redis_key"] = feature.get("source_redis_key")
    merged["integrity_feature_snapshot_exact_match"] = True
    return merged


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _prediction_temporal_rejection_reasons(prediction: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    decision_time = _parse_utc(
        _first_text(prediction.get("decision_time"), prediction.get("decision_time_est"))
    )
    available_at = _parse_utc(
        _first_text(prediction.get("available_at"), prediction.get("source_available_time"))
    )
    feature_cutoff = _parse_utc(
        _first_text(prediction.get("feature_cutoff"), prediction.get("source_event_time_est"))
    )
    candle_close_time = _parse_utc(prediction.get("candle_close_time"))
    masa_feature_cutoff = _parse_utc(prediction.get("masa_feature_cutoff"))
    ppo_decision_time = _parse_utc(prediction.get("ppo_decision_time"))
    if decision_time is None:
        reasons.append("DECISION_TIME_MISSING_OR_INVALID")
    if available_at is None:
        reasons.append("AVAILABLE_AT_MISSING_OR_INVALID")
    elif decision_time is not None and available_at > decision_time:
        reasons.append("FEATURE_AVAILABLE_AFTER_DECISION_TIME")
    if feature_cutoff is None:
        reasons.append("FEATURE_CUTOFF_MISSING_OR_INVALID")
    elif decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if prediction.get("candle_closed_confirmed") is not True:
        reasons.append("FINAL_CANDLE_NOT_CONFIRMED")
    if candle_close_time is None:
        reasons.append("CANDLE_CLOSE_TIME_MISSING_OR_INVALID")
    elif feature_cutoff is not None and candle_close_time > feature_cutoff:
        reasons.append("CANDLE_CLOSE_AFTER_FEATURE_CUTOFF")
    elif decision_time is not None and candle_close_time > decision_time:
        reasons.append("CANDLE_CLOSE_AFTER_DECISION_TIME")
    if masa_feature_cutoff is None:
        reasons.append("MASA_FEATURE_CUTOFF_MISSING_OR_INVALID")
    if ppo_decision_time is None:
        reasons.append("PPO_DECISION_TIME_MISSING_OR_INVALID")
    if (
        masa_feature_cutoff is not None
        and ppo_decision_time is not None
        and masa_feature_cutoff > ppo_decision_time
    ):
        reasons.append("MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME")
    if not _first_text(
        prediction.get("feature_snapshot_id"), prediction.get("feature_tensor_id")
    ):
        reasons.append("FEATURE_SNAPSHOT_ID_MISSING")
    return sorted(set(reasons))


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else default


def _prediction_source_rank(key: str) -> int:
    if ":rl_core:" in key:
        return 0
    if key.startswith(f"{V2_REDIS_PREFIX}prediction:"):
        return 2
    return 1


def _prediction_age_seconds(prediction: dict) -> float | None:
    raw = _first_text(
        prediction.get("generated_utc"),
        prediction.get("generated_at"),
        prediction.get("generated_est"),
        prediction.get("timestamp"),
        prediction.get("finished_at"),
    )
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


def _prediction_to_proposal_and_signal(p: dict) -> tuple[dict, dict] | None:
    """Convert a V2 prediction dict into the proposal + V2Signal shape
    expected by the orchestrator arbitration service."""
    selected_action = str(p.get("selected_action") or "hold").strip().lower()
    side_for_action = {"long": "long", "short": "short"}
    sel = side_for_action.get(selected_action)
    # HOLD/flat/close/hedge and unknown actions are decisions not to open a
    # directional position.  Never infer LONG/SHORT from a diagnostic move.
    if sel is None:
        return None
    symbol = str(p.get("symbol") or _runtime_default_symbol()).upper()
    prediction_id = _first_text(p.get("prediction_id"), p.get("id"))
    feature_snapshot_id = _first_text(p.get("feature_snapshot_id"), p.get("feature_tensor_id"))
    generated_utc = _first_text(
        p.get("generated_utc"),
        p.get("generated_at"),
        p.get("generated_est"),
        p.get("timestamp"),
        p.get("finished_at"),
    )
    if not prediction_id or not feature_snapshot_id or not generated_utc:
        return None
    freshness_seconds = _prediction_age_seconds(p)
    if freshness_seconds is None:
        return None
    model_version = _first_text(
        p.get("model_version"),
        p.get("model_id"),
        p.get("checkpoint_id"),
        p.get("trainer_source"),
    ) or "v2_orchestrator_unknown_model"
    source = _first_text(p.get("trainer_source"), p.get("source")) or "V2_NATIVE_PREDICTION"
    confidence_raw = max(0.0, min(1.0, _finite_float(p.get("confidence_raw"), 0.0)))
    confidence_calibrated = max(0.0, min(1.0, _finite_float(p.get("confidence_calibrated"), confidence_raw)))
    expected_move_after_cost_signed = _finite_float(
        p.get("expected_move_after_cost_bps"), 0.0
    )
    # Upstream edge is signed in market-return space: positive is favourable
    # to LONG and negative is favourable to SHORT.  Arbitration compares edge
    # in position-return space so equal/opposite long and short opportunities
    # receive equal scores.  Preserve the signed input separately for lineage.
    expected_move_after_cost_directional = (
        expected_move_after_cost_signed
        if sel == "long"
        else -expected_move_after_cost_signed
    )
    proposal = {
        "proposal_id": prediction_id,
        "symbol": symbol,
        "side": sel,
        "confidence_calibrated": confidence_calibrated,
        "expected_move_after_cost_bps": expected_move_after_cost_directional,
        "generated_utc": generated_utc,
        "source": source,
        "freshness_seconds": freshness_seconds,
        "model_version": model_version,
    }
    signal_id = _first_text(p.get("signal_id")) or prediction_id
    signal = {
        "signal_id": signal_id,
        "symbol": symbol,
        "timeframe": p.get("timeframe"),
        "side": sel,
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_calibrated,
        "expected_move_after_cost_bps": expected_move_after_cost_directional,
        "expected_move_after_cost_bps_signed": expected_move_after_cost_signed,
        "expected_move_after_cost_bps_directional": expected_move_after_cost_directional,
        "source_prediction_id": prediction_id,
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "generated_utc": generated_utc,
        "freshness_seconds": freshness_seconds,
        "model_version": model_version,
        "trainer_source": p.get("trainer_source"),
        "model_id": p.get("model_id"),
        "checkpoint_id": p.get("checkpoint_id"),
        "upstream_paper_fill_allowed": p.get("paper_fill_allowed") is True,
        "upstream_paper_fill_gate_status": p.get("paper_fill_gate_status"),
    }
    signal.update(_copy_trust_envelope_fields(p))
    signal["signal_id"] = signal_id
    signal["prediction_id"] = prediction_id
    signal["source_prediction_id"] = prediction_id
    signal["symbol"] = symbol
    signal["timeframe"] = p.get("timeframe")
    signal["selected_action"] = selected_action
    signal["model_version"] = model_version
    signal["checkpoint_id"] = p.get("checkpoint_id")
    signal["feature_snapshot_id"] = feature_snapshot_id
    # Paper-recovery engineering-canary: propagate the recovery markers + sealed
    # entry-feature/funding carrier fields from the prediction onto the paper
    # signal, so the single-use armed canary stays recognizable through
    # signal -> paper-loop intent (the paper loop indexes predictions FROM
    # signals, so an un-propagated marker is lost). Ordinary predictions carry
    # none of these markers, so ordinary signals are unaffected. This never
    # routes to live: the risk gateway + paper loop keep every live control.
    if p.get("engineering_canary") is True:
        for _canary_field in (
            "engineering_canary",
            "paper_recovery_only",
            "engineering_canary_max_notional_usd",
            "engineering_canary_max_open_positions",
            "entry_feature_available_at",
            "entry_feature_generated_at",
            "entry_feature_cutoff",
            "entry_feature_decision_time",
            "entry_feature_candle_closed_confirmed",
            "expected_funding_bps",
            "expected_funding_bps_source",
            "funding_policy",
            "paper_eligible",
        ):
            if p.get(_canary_field) is not None:
                signal[_canary_field] = p.get(_canary_field)
    return proposal, signal


# ---------------------------------------------------------------------------
# High-precision paper mode gate (item 6)
# ---------------------------------------------------------------------------

# Minimum thresholds required for a prediction to be arbitrated in
# high_precision_paper_mode.  These are conservative and can be tightened
# further once walk-forward evidence accumulates.
_HPPM_MIN_CONFIDENCE_CALIBRATED = 0.60
_HPPM_MIN_EXPECTED_MOVE_AFTER_COST_BPS = 5.0
_HPPM_MIN_DATA_COVERAGE_PCT = 80.0
_MICROSTRUCTURE_SHADOW_BLOCK_THRESHOLD = 0.45
_MICROSTRUCTURE_MIN_A_GRADE_TRUST_SCORE = 0.65
_MICROSTRUCTURE_SWEEP_BLOCK_THRESHOLD = 0.75
_MICROSTRUCTURE_BLOCK_ACTIONS = {"NO_TRADE", "SHADOW_ONLY", "CLOSE_OR_REDUCE_ONLY"}

_TRUST_ENVELOPE_FIELDS = (
    "decision_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "candle_closed_confirmed",
    "candle_open_time",
    "candle_close_time",
    "source_event_time_est",
    "source_received_time_est",
    "source_available_time",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
    "ppo_decision_time",
    "symbol",
    "timeframe",
    "selected_action",
    "model_version",
    "checkpoint_id",
    "source_hashes",
    "microstructure_trust_evidence",
    "microstructure_trust_evidence_sha256",
    "source_redis_key",
    "source_prediction_observed_ttl_seconds",
    "feature_vector_hash",
    "input_feature_hash",
    "all_tf_candle_timestamps",
    "all_source_event_times",
    "source_candle_timestamps",
    "replay_snapshot_id",
    "replay_snapshot_key",
    "replay_snapshot_write_success",
    "trust_gate_result",
    "microstructure_trust_score",
    "orderbook_trust_score",
    "orderbook_trust_tier",
    "microstructure_action",
    "orderbook_latency_ms",
    "book_sequence_gap",
    "book_depth_persistence_score",
    "book_cancel_pressure_score",
    "trade_tape_confirmation_score",
    "cross_venue_confirmation_score",
    "liquidation_zone_risk_score",
    "sweep_risk_score",
    "microstructure_gate_allows_a_grade",
    "orchestrator_microstructure_block_reasons",
    "source_availability",
    "serving_feature_abi_v2",
    "feature_abi_sha256",
    "feature_builder_sha256",
    "paper_strategy_cohort_id",
    "paper_cohort_checkpoint_id",
    "active_model_registry_generation",
    "checkpoint_generation",
    "entry_feature_snapshot_id",
    "entry_feature_available_at",
    "entry_feature_generated_at",
    "entry_feature_cutoff",
    "entry_feature_decision_time",
    "entry_feature_candle_closed_confirmed",
    "entry_feature_source",
    "entry_feature_snapshot",
    "exact_cost_provenance",
    "exact_cost_provenance_valid",
    "round_trip_cost_bps",
    "expected_funding_bps",
    "expected_funding_bps_source",
    "funding_bps_at_decision_time",
    "market_state_id",
    "ordinary_paper_admission_schema_version",
    "ordinary_paper_quality_schema_version",
    "ordinary_paper_admission_mode",
    "paper_quality_sizing_formula",
    "paper_quality_sizing_weight",
    "publisher_paper_quality_sizing_weight",
    "ordinary_paper_effective_sizing_weight",
    "ordinary_paper_effective_sizing_formula",
    "ordinary_paper_effective_sizing_factors",
    "ordinary_paper_raw_microstructure_action",
    "ordinary_paper_effective_microstructure_action",
    "ordinary_paper_legacy_microstructure_block_reasons",
    "ordinary_scale_free_paper_admission_revalidated",
    "ordinary_scale_free_paper_admission_rejection_reasons",
    "ordinary_paper_admission_evidence",
    "ordinary_paper_admission_evidence_sha256",
    *BEHAVIOR_POLICY_LINEAGE_FIELDS,
)


def _copy_trust_envelope_fields(source: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in _TRUST_ENVELOPE_FIELDS:
        value = source.get(field)
        if value in (None, ""):
            continue
        if isinstance(value, dict):
            out[field] = dict(value)
        elif isinstance(value, list):
            out[field] = list(value)
        else:
            out[field] = value
    source_hashes = source.get("source_hashes")
    if isinstance(source_hashes, dict) and source_hashes:
        out["source_hashes"] = dict(source_hashes)
    return out


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _microstructure_contexts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    contexts = [payload]
    trust_evidence = payload.get("microstructure_trust_evidence")
    trust_source = (
        trust_evidence.get("source_payload")
        if isinstance(trust_evidence, dict)
        else None
    )
    if isinstance(trust_source, dict):
        contexts.append(trust_source)
    for key in (
        "microstructure_context",
        "market_microstructure",
        "microstructure",
        "sweep_risk",
        "liquidation_context",
    ):
        value = payload.get(key)
        if isinstance(value, dict):
            contexts.append(value)
    return contexts


def _microstructure_value(payload: dict[str, Any], *keys: str) -> Any:
    for context in _microstructure_contexts(payload):
        for key in keys:
            value = context.get(key)
            if value not in (None, ""):
                return value
    return None


def _truthy_microstructure_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _microstructure_float(payload: dict[str, Any], *keys: str) -> float | None:
    value = _microstructure_value(payload, *keys)
    if value in (None, "") or isinstance(value, bool):
        return None
    parsed = _finite_float(value, default=None)
    return parsed if parsed is not None else None


def _ordinary_paper_assessment(
    redis_client,
    prediction: dict[str, Any],
    *,
    integrity: dict[str, Any],
) -> OrdinaryPaperAdmissionResult:
    replay_key = str(prediction.get("replay_snapshot_key") or "")
    replay_snapshot = _read_json_key(redis_client, replay_key) if replay_key else None
    try:
        replay_snapshot_ttl = redis_client.ttl(replay_key) if replay_key else None
    except Exception:
        replay_snapshot_ttl = None
    raw_market_reasons = [
        str(reason) for reason in integrity.get("reject_reasons") or [] if reason
    ]
    continuous_market_reasons = {
        "LATENCY_ABOVE_GATE",
        "MAJOR_SOURCE_DISAGREEMENT",
    }
    microstructure = microstructure_admission_values(prediction)
    return assess_ordinary_paper_candidate(
        prediction,
        market_state_integrity_score=integrity.get(
            "market_state_integrity_score"
        ),
        market_state_reject_reasons=[
            reason
            for reason in raw_market_reasons
            if reason not in continuous_market_reasons
        ],
        market_state_quality_reasons=[
            reason
            for reason in raw_market_reasons
            if reason in continuous_market_reasons
        ],
        microstructure_trust_score=microstructure.get(
            "microstructure_trust_score"
        ),
        sweep_risk_score=microstructure.get("sweep_risk_score"),
        microstructure_action=microstructure.get("microstructure_action"),
        book_sequence_gap=microstructure.get("book_sequence_gap"),
        feed_integrity_pass=microstructure.get("feed_integrity_pass"),
        latency_within_bound=microstructure.get("latency_within_bound"),
        sequence_gap_free=microstructure.get("sequence_gap_free"),
        sweep_direction_uncertain=microstructure.get(
            "sweep_direction_uncertain"
        ),
        microstructure_missing_components=microstructure.get(
            "microstructure_missing_components"
        ),
        legacy_microstructure_block_reasons=_microstructure_block_reasons(
            prediction
        ),
        replay_snapshot=replay_snapshot,
        replay_snapshot_observed_ttl_seconds=replay_snapshot_ttl,
    )


def _microstructure_block_reasons(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    action = str(_microstructure_value(payload, "microstructure_action") or "").upper()
    if action in _MICROSTRUCTURE_BLOCK_ACTIONS:
        reasons.append(f"MICROSTRUCTURE_ACTION_{action}")

    trust_score = _microstructure_float(
        payload,
        "microstructure_trust_score",
        "orderbook_trust_score",
    )
    adaptive_minimum = _microstructure_float(
        payload,
        "microstructure_adaptive_minimum",
        "adaptive_minimum",
    )
    if adaptive_minimum is None:
        adaptive_minimum = _MICROSTRUCTURE_MIN_A_GRADE_TRUST_SCORE
    if trust_score is not None and trust_score < _MICROSTRUCTURE_SHADOW_BLOCK_THRESHOLD:
        reasons.append("MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED")

    sequence_gap = _microstructure_value(payload, "book_sequence_gap", "sequence_gap_flag")
    if _truthy_microstructure_flag(sequence_gap):
        reasons.append("MICROSTRUCTURE_SEQUENCE_GAP")

    sweep_risk = _microstructure_float(payload, "sweep_risk_score", "sweep_risk")
    if sweep_risk is not None and sweep_risk >= _MICROSTRUCTURE_SWEEP_BLOCK_THRESHOLD:
        reasons.append("MICROSTRUCTURE_SWEEP_RISK_BLOCK")

    grade = str(
        _first_present(
            payload.get("candidate_grade"),
            payload.get("quality_grade"),
            payload.get("paper_grade"),
        )
        or ""
    ).upper()
    claims_a_grade = grade.startswith("A") or payload.get("a_grade_candidate") is True
    if claims_a_grade and (
        trust_score is None
        or trust_score < adaptive_minimum
        or action not in {"ALLOW", "REDUCE_SIZE"}
    ):
        reasons.append("MICROSTRUCTURE_A_GRADE_TRUST_MISSING_OR_LOW")

    return sorted(set(reasons))


def _high_precision_paper_mode_active() -> bool:
    """Return True when V2_HIGH_PRECISION_PAPER_MODE env var is set to 1/true."""
    return os.environ.get("V2_HIGH_PRECISION_PAPER_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


def _hppm_gate(prediction: dict[str, Any]) -> list[str]:
    """Return block reasons if prediction fails high-precision-paper-mode thresholds.

    Empty list means the prediction passes.  Only called when mode is active.
    """
    reasons: list[str] = []
    conf = _finite_float(prediction.get("confidence_calibrated"), 0.0)
    if conf < _HPPM_MIN_CONFIDENCE_CALIBRATED:
        reasons.append(
            f"HPPM_LOW_CONFIDENCE:{conf:.3f}<{_HPPM_MIN_CONFIDENCE_CALIBRATED}"
        )
    action = str(prediction.get("selected_action") or "").strip().lower()
    move_signed = _finite_float(prediction.get("expected_move_after_cost_bps"), 0.0)
    move_directional = -move_signed if action == "short" else move_signed
    if move_directional < _HPPM_MIN_EXPECTED_MOVE_AFTER_COST_BPS:
        reasons.append(
            "HPPM_LOW_EXPECTED_MOVE:"
            f"{move_directional:.1f}bps<{_HPPM_MIN_EXPECTED_MOVE_AFTER_COST_BPS}"
        )
    coverage = _finite_float(prediction.get("data_coverage_percent"), 0.0)
    if coverage < _HPPM_MIN_DATA_COVERAGE_PCT:
        reasons.append(
            f"HPPM_LOW_DATA_COVERAGE:{coverage:.1f}%<{_HPPM_MIN_DATA_COVERAGE_PCT}"
        )
    if action in ("hold", "flat", "close", "hedge", ""):
        reasons.append("HPPM_HOLD_ACTION_EXCLUDED")
    return reasons


def _per_symbol_missing_features(prediction: dict[str, Any]) -> dict[str, Any]:
    """Build per-symbol missing/stale feature attribution for diagnostics."""
    symbol = str(prediction.get("symbol") or "UNKNOWN").upper()
    return {
        "symbol": symbol,
        "missing_feature_count": int(prediction.get("missing_feature_count") or 0),
        "stale_feature_count": int(prediction.get("stale_feature_count") or 0),
        "missing_feature_names": list(prediction.get("missing_feature_names") or []),
        "stale_feature_names": list(prediction.get("stale_feature_names") or []),
        "data_coverage_percent": _finite_float(prediction.get("data_coverage_percent")),
        "feature_freshness_state": prediction.get("feature_freshness_state"),
    }


def _deconflict_telemetry_payload(
    result: Any,
    *,
    scope: str,
) -> dict[str, Any]:
    """Serialize deconfliction lineage without granting routing authority."""

    selected_signal = getattr(result, "selected_signal", None)
    return {
        "scope": scope,
        "telemetry_only": True,
        "controls_publication": False,
        "selected_side": getattr(result, "selected_side", None),
        "selected_signal_id": getattr(selected_signal, "signal_id", None),
        "selected_source_prediction_id": getattr(
            selected_signal,
            "source_prediction_id",
            None,
        ),
        "conflict_reason": getattr(result, "conflict_reason", None),
        "long_aggregate_confidence": getattr(
            result,
            "long_aggregate_confidence",
            0.0,
        ),
        "short_aggregate_confidence": getattr(
            result,
            "short_aggregate_confidence",
            0.0,
        ),
        "considered_count": getattr(result, "considered_count", 0),
    }


def _paper_recovery_market_state_waiver(prediction: dict) -> bool:
    """PaperRecoveryPolicyV1 Path-A waiver of the strict market-state continuity
    cliff — ONLY for paper-only, recovery-tagged predictions when recovery mode
    is explicitly enabled, and only when every immovable live-safety anchor is
    present on the prediction.  Never admits anything live-routable; the canonical
    orchestrator decision and the downstream risk gateway still evaluate it.
    """

    if prediction.get("paper_recovery_only") is not True:
        return False
    try:
        from v2.backend.app.services.paper_recovery.paper_recovery_policy_v1 import (
            load_paper_recovery_policy_v1,
        )

        policy = load_paper_recovery_policy_v1(os.environ)
    except Exception:
        return False
    if not policy.enabled:
        return False
    if not policy.is_symbol_allowed(str(prediction.get("symbol") or "")):
        return False
    # Immovable safety re-assertion — a waived recovery prediction can never be
    # routable to real execution.
    if (
        prediction.get("live_gate") != "blocked_human_only"
        or prediction.get("places_real_order") is not False
        or prediction.get("routes_to_live") is not False
        or prediction.get("live_eligible") is not False
    ):
        return False
    # Confirms the artifact is recovery-tagged (deny_live_route returns a reason
    # for exactly these artifacts).
    return policy.deny_live_route(prediction) is not None


def run_once() -> dict:
    from v2.backend.app.services.orchestrator_arbitration import (
        OrchestratorArbitrationService, Proposal, validate_signal,
        deconflict_signals,
    )
    started = _utc_iso()
    r = _connect_redis()
    live_context = _live_context(r)
    predictions = _scan_predictions(r)
    proposals = []
    signals = []
    signal_by_prediction_id: dict[str, dict[str, Any]] = {}
    held_by_gate: list[dict] = []
    skipped_malformed: list[dict] = []
    integrity_by_prediction_id: dict[str, dict[str, Any]] = {}
    for p in predictions:
        integrity = score_market_state(_prediction_integrity_input(r, p)).to_dict()
        if p.get("prediction_id"):
            integrity_by_prediction_id[str(p.get("prediction_id"))] = integrity
        ordinary_assessment = _ordinary_paper_assessment(
            r, p, integrity=integrity
        )
        if ordinary_assessment.claimed:
            p = {**p, **ordinary_assessment.transport_payload()}
        if ordinary_assessment.claimed and not ordinary_assessment.accepted:
            integrity_block_reasons = [
                "ORDINARY_SCALE_FREE_PAPER_ADMISSION_REVALIDATION_FAILED",
                *ordinary_assessment.rejection_reasons,
            ]
        elif (
            not ordinary_assessment.accepted
            and not integrity.get("valid_for_orchestrator")
        ):
            integrity_block_reasons = [
                "MARKET_STATE_INTEGRITY_REJECTED_FOR_ORCHESTRATOR"
            ]
        else:
            # The ordinary lane has independently revalidated immutable
            # structure and uses the positive score magnitude as a continuous
            # sizing factor.  The legacy 80-point cliff is telemetry only.
            integrity_block_reasons = []
        if integrity_block_reasons and _paper_recovery_market_state_waiver(p):
            # PaperRecoveryPolicyV1 Path-A waiver of the strict market-state
            # continuity cliff for paper-only recovery-tagged predictions.
            # Temporal / microstructure / route / risk gates below still apply.
            p = {**p, "paper_recovery_market_state_waiver": True}
            integrity_block_reasons = []
        temporal_block_reasons = _prediction_temporal_rejection_reasons(p)
        integrity_block_reasons.extend(temporal_block_reasons)
        microstructure_block_reasons = (
            []
            if ordinary_assessment.claimed
            else _microstructure_block_reasons(p)
        )
        route_gate_blocked = p.get("routes_to_orchestrator") is not True
        gate_explicitly_blocked = (
            p.get("paper_fill_allowed") is False or route_gate_blocked
        )
        selected_action = str(p.get("selected_action") or "hold").strip().lower()
        if (
            selected_action not in {"long", "short"}
            and not gate_explicitly_blocked
            and not integrity_block_reasons
            and not microstructure_block_reasons
        ):
            # A directional diagnostic attached to HOLD/flat/close must never
            # be promoted into a new position.  Surface it through the worker's
            # existing held-decision contract and do not publish a paper signal.
            reasons = list(p.get("paper_fill_gate_block_reasons") or [])
            reasons.extend(integrity_block_reasons)
            reasons.extend(integrity.get("reject_reasons") or [])
            reasons.extend(microstructure_block_reasons)
            if route_gate_blocked:
                reasons.append("ROUTES_TO_ORCHESTRATOR_NOT_EXPLICIT_TRUE")
            reasons.append(f"NON_ROUTEABLE_SELECTED_ACTION:{selected_action.upper()}")
            held_by_gate.append({
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "prediction_id": p.get("prediction_id"),
                "signal_id": f"held_signal_{p.get('prediction_id')}",
                "orchestrator_decision_id": f"held_decision_{p.get('prediction_id')}",
                "risk_decision_id": None,
                "risk_state": "NOT_ROUTED_TO_RISK_GATEWAY_BECAUSE_NON_ROUTEABLE_ACTION",
                "feature_snapshot_id": p.get("feature_snapshot_id"),
                "side": "flat",
                "selected_action": selected_action,
                "expected_move_after_cost_bps": p.get("expected_move_after_cost_bps"),
                "confidence_calibrated": p.get("confidence_calibrated"),
                "price_target": p.get("price_target"),
                "data_coverage_percent": p.get("data_coverage_percent"),
                "missing_feature_count": len(p.get("missing_feature_flags") or []),
                "stale_feature_count": len(p.get("stale_feature_flags") or []),
                "feature_freshness_state": p.get("feature_freshness_state"),
                "market_state_id": integrity.get("market_state_id"),
                "market_state_integrity_score": integrity.get("market_state_integrity_score"),
                "valid_for_paper": integrity.get("valid_for_paper"),
                "valid_for_live": integrity.get("valid_for_live"),
                "market_state_reject_reasons": integrity.get("reject_reasons"),
                "trainer_source": p.get("trainer_source"),
                "checkpoint_weight_status": p.get("checkpoint_weight_status"),
                "paper_fill_allowed": False,
                "paper_fill_gate_status": "HELD_NON_ROUTEABLE_ACTION",
                "paper_fill_gate_block_reasons": sorted(
                    set(str(reason) for reason in reasons if reason)
                ),
                "orchestrator_microstructure_block_reasons": microstructure_block_reasons,
                "checkpoint_blocker": p.get("checkpoint_blocker"),
                "decision": "HELD_BY_NON_ROUTEABLE_ACTION",
                "decision_reason_code": "non_routeable_selected_action",
                "routes_to_risk_gateway": False,
                "places_real_order": False,
                "generated_utc": p.get("generated_utc"),
            })
            held_by_gate[-1].update(_copy_trust_envelope_fields(p))
            # Reassert the fail-closed fields after copying upstream lineage.
            held_by_gate[-1]["side"] = "flat"
            held_by_gate[-1]["selected_action"] = selected_action
            held_by_gate[-1]["paper_fill_allowed"] = False
            continue
        # Routing is an explicit capability: missing/None is blocked just like
        # False.  Market-state integrity is an additional gate, not a substitute
        # for upstream route authorization.
        if gate_explicitly_blocked or integrity_block_reasons or microstructure_block_reasons:
            # Gate blocked this prediction; do not arbitrate, but surface
            # block reasons so downstream consumers can diagnose.
            reasons = list(p.get("paper_fill_gate_block_reasons") or [])
            reasons.extend(integrity_block_reasons)
            reasons.extend(integrity.get("reject_reasons") or [])
            reasons.extend(microstructure_block_reasons)
            if route_gate_blocked:
                reasons.append("ROUTES_TO_ORCHESTRATOR_NOT_EXPLICIT_TRUE")
            if gate_explicitly_blocked and not integrity_block_reasons:
                reasons.append("PAPER_FILL_ALLOWED_EXPLICITLY_FALSE")
            risk_state = "NOT_ROUTED_TO_RISK_GATEWAY_BECAUSE_PAPER_FILL_GATE_BLOCKED"
            decision = "HELD_BY_PAPER_FILL_GATE"
            if microstructure_block_reasons and not gate_explicitly_blocked and not integrity_block_reasons:
                risk_state = "NOT_ROUTED_TO_RISK_GATEWAY_BECAUSE_MICROSTRUCTURE_TRUST_BLOCKED"
                decision = "HELD_BY_MICROSTRUCTURE_TRUST_GATE"
            held_by_gate.append({
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "prediction_id": p.get("prediction_id"),
                "signal_id": f"held_signal_{p.get('prediction_id')}",
                "orchestrator_decision_id": f"held_decision_{p.get('prediction_id')}",
                "risk_decision_id": None,
                "risk_state": risk_state,
                "feature_snapshot_id": p.get("feature_snapshot_id"),
                "selected_action": p.get("selected_action"),
                "expected_move_after_cost_bps": p.get("expected_move_after_cost_bps"),
                "confidence_calibrated": p.get("confidence_calibrated"),
                "price_target": p.get("price_target"),
                "data_coverage_percent": p.get("data_coverage_percent"),
                "missing_feature_count": len(p.get("missing_feature_flags") or []),
                "stale_feature_count": len(p.get("stale_feature_flags") or []),
                "feature_freshness_state": p.get("feature_freshness_state"),
                "market_state_id": integrity.get("market_state_id"),
                "market_state_integrity_score": integrity.get("market_state_integrity_score"),
                "valid_for_paper": integrity.get("valid_for_paper"),
                "valid_for_live": integrity.get("valid_for_live"),
                "market_state_reject_reasons": integrity.get("reject_reasons"),
                "trainer_source": p.get("trainer_source"),
                "checkpoint_weight_status": p.get("checkpoint_weight_status"),
                "paper_fill_gate_status": p.get("paper_fill_gate_status"),
                "paper_fill_gate_block_reasons": sorted(set(str(reason) for reason in reasons if reason)),
                "orchestrator_microstructure_block_reasons": microstructure_block_reasons,
                "checkpoint_blocker": p.get("checkpoint_blocker"),
                "decision": decision,
                "paper_fill_allowed": False,
                "routes_to_risk_gateway": False,
                "places_real_order": False,
                "generated_utc": p.get("generated_utc"),
            })
            held_by_gate[-1].update(_copy_trust_envelope_fields(p))
            # Upstream lineage is evidence only and must not overwrite the
            # fail-closed decision made by this worker.
            held_by_gate[-1]["paper_fill_allowed"] = False
            held_by_gate[-1]["routes_to_risk_gateway"] = False
            held_by_gate[-1]["places_real_order"] = False
            continue

        # High-precision paper mode gate (item 6): apply additional quality
        # thresholds when V2_HIGH_PRECISION_PAPER_MODE=1.
        hppm_reasons = (
            _hppm_gate(p)
            if _high_precision_paper_mode_active()
            and not ordinary_assessment.accepted
            else []
        )
        if hppm_reasons:
            held_by_gate.append({
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "prediction_id": p.get("prediction_id"),
                "signal_id": f"hppm_held_{p.get('prediction_id')}",
                "orchestrator_decision_id": f"hppm_held_decision_{p.get('prediction_id')}",
                "risk_decision_id": None,
                "risk_state": "NOT_ROUTED_HIGH_PRECISION_PAPER_MODE_BLOCKED",
                "feature_snapshot_id": p.get("feature_snapshot_id"),
                "selected_action": p.get("selected_action"),
                "confidence_calibrated": p.get("confidence_calibrated"),
                "expected_move_after_cost_bps": p.get("expected_move_after_cost_bps"),
                "data_coverage_percent": p.get("data_coverage_percent"),
                "paper_fill_gate_block_reasons": hppm_reasons,
                "decision": "HELD_BY_HIGH_PRECISION_PAPER_MODE",
                "places_real_order": False,
                "generated_utc": p.get("generated_utc"),
            })
            continue

        pp = _prediction_to_proposal_and_signal(p)
        if pp is None:
            skipped_malformed.append({
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "prediction_id": p.get("prediction_id"),
                "reason": "MISSING_REQUIRED_ORCHESTRATOR_FIELDS",
                "has_generated_utc": bool(_first_text(p.get("generated_utc"), p.get("generated_at"), p.get("generated_est"))),
                "has_feature_snapshot_id": bool(_first_text(p.get("feature_snapshot_id"), p.get("feature_tensor_id"))),
            })
            continue
        prop_dict, sig_dict = pp
        try:
            proposals.append(Proposal(**prop_dict))
        except ValueError as exc:
            skipped_malformed.append({
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "prediction_id": p.get("prediction_id"),
                "reason": f"INVALID_PROPOSAL:{exc}",
            })
            continue
        try:
            validated_signal = validate_signal(sig_dict)
            signals.append(validated_signal)
            signal_by_prediction_id[str(prop_dict["proposal_id"])] = sig_dict
        except ValueError as exc:
            skipped_malformed.append({
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "prediction_id": p.get("prediction_id"),
                "reason": f"INVALID_SIGNAL:{exc}",
            })
            continue
    service = OrchestratorArbitrationService(max_age_seconds=300)
    arb = service.arbitrate(proposals)
    deconflict = deconflict_signals(signals)
    legacy_global_deconflict = _deconflict_telemetry_payload(
        deconflict,
        scope="GLOBAL_CROSS_SYMBOL_LEGACY_DIAGNOSTIC_ONLY",
    )
    signals_by_symbol: dict[str, list[Any]] = {}
    for signal in signals:
        symbol = str(getattr(signal, "symbol", "") or "").upper()
        if symbol:
            signals_by_symbol.setdefault(symbol, []).append(signal)
    deconflict_by_symbol = {
        symbol: _deconflict_telemetry_payload(
            deconflict_signals(signals_by_symbol[symbol]),
            scope="PER_SYMBOL_TELEMETRY_ONLY",
        )
        for symbol in sorted(signals_by_symbol)
    }
    keys_written: list[str] = []
    canonical_record_status_counts = {
        "CREATED": 0,
        "EXISTING_IDENTICAL": 0,
        "CONFLICT": 0,
        "WRITE_ERROR": 0,
    }
    canonical_record_blocked_winner_ids: list[str] = []
    bucket_winners: list[dict[str, Any]] = []
    if r is not None:
        proposals_payload = []
        for pr in proposals:
            lineage = signal_by_prediction_id.get(str(pr.proposal_id)) or {}
            directional_edge = float(pr.expected_move_after_cost_bps)
            signed_edge = _finite_float(
                lineage.get("expected_move_after_cost_bps_signed"),
                directional_edge if pr.side == "long" else -directional_edge,
            )
            row = {
                "proposal_id": pr.proposal_id,
                "symbol": pr.symbol,
                "side": pr.side,
                "confidence_calibrated": pr.confidence_calibrated,
                "expected_move_after_cost_bps": signed_edge,
                "expected_move_after_cost_bps_signed": signed_edge,
                "expected_move_after_cost_bps_directional": directional_edge,
                "source": pr.source,
                "freshness_seconds": pr.freshness_seconds,
                "model_version": pr.model_version,
                "generated_utc": pr.generated_utc,
            }
            row.update(_copy_trust_envelope_fields(lineage))
            row["proposal_id"] = pr.proposal_id
            row["symbol"] = pr.symbol
            row["side"] = pr.side
            row["model_version"] = pr.model_version
            proposals_payload.append(row)
        candidate_bucket_winners = []
        for w in arb.bucket_winners:
            lineage = signal_by_prediction_id.get(str(w.winner.proposal_id)) or {}
            decision_id = _first_text(lineage.get("decision_id")) or f"dec_{w.winner.proposal_id}"
            directional_edge = float(w.winner.expected_move_after_cost_bps)
            signed_edge = _finite_float(
                lineage.get("expected_move_after_cost_bps_signed"),
                directional_edge if w.side == "long" else -directional_edge,
            )
            row = {
                "symbol": w.symbol,
                "side": w.side,
                "winner_proposal_id": w.winner.proposal_id,
                "prediction_id": w.winner.proposal_id,
                "signal_id": lineage.get("signal_id") or f"sig_{w.winner.proposal_id}",
                "decision_id": decision_id,
                "orchestrator_decision_id": f"dec_{w.winner.proposal_id}",
                "winner_confidence_calibrated": w.winner.confidence_calibrated,
                "winner_expected_move_after_cost_bps": signed_edge,
                "winner_expected_move_after_cost_bps_signed": signed_edge,
                "winner_expected_move_after_cost_bps_directional": directional_edge,
                "winner_freshness_seconds": w.winner.freshness_seconds,
                "winner_model_version": w.winner.model_version,
                "considered_proposal_ids": list(w.considered_proposal_ids),
                "score": w.score,
            }
            row.update(_copy_trust_envelope_fields(lineage))
            row["symbol"] = w.symbol
            row["side"] = w.side
            row["winner_proposal_id"] = w.winner.proposal_id
            row["prediction_id"] = w.winner.proposal_id
            row["signal_id"] = lineage.get("signal_id") or f"sig_{w.winner.proposal_id}"
            row["decision_id"] = decision_id
            row["orchestrator_decision_id"] = f"dec_{w.winner.proposal_id}"
            row["winner_model_version"] = w.winner.model_version
            row["model_version"] = lineage.get("model_version") or w.winner.model_version
            candidate_bucket_winners.append(row)
        record_generated_at = datetime.now(timezone.utc)
        for row in candidate_bucket_winners:
            record_status = _write_per_id_orchestrator_decision_record(
                r,
                winner=row,
                generated_at=record_generated_at,
            )
            canonical_record_status_counts[record_status] = (
                canonical_record_status_counts.get(record_status, 0) + 1
            )
            if record_status in {"CREATED", "EXISTING_IDENTICAL"}:
                row["canonical_orchestrator_record_status"] = record_status
                row["canonical_orchestrator_record_producer"] = (
                    "v2_orchestrator_arbitration_loop"
                )
                bucket_winners.append(row)
                if record_status == "CREATED":
                    keys_written.append(
                        f"{V2_REDIS_PREFIX}decision:orchestrator:"
                        f"{row['orchestrator_decision_id']}"
                    )
            else:
                canonical_record_blocked_winner_ids.append(
                    str(row.get("winner_proposal_id") or "")
                )
                skipped_malformed.append(
                    {
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "prediction_id": row.get("prediction_id"),
                        "reason": (
                            "CANONICAL_ORCHESTRATOR_DECISION_RECORD_"
                            f"{record_status}"
                        ),
                    }
                )
        decisions_payload = {
            "schema_version": "v2_orchestrator_decisions_v2",
            "generated_utc": _utc_iso(),
            "considered_count": arb.considered_count,
            "bucket_winners": bucket_winners,
            "stale_proposal_ids": list(arb.stale_proposal_ids),
            # Preserve the historical cross-symbol fields as labelled
            # diagnostics only.  The per-symbol map is the accurate telemetry;
            # neither view filters winners or grants paper/live authority.
            "deconflict_reason": legacy_global_deconflict["conflict_reason"],
            "deconflict_selected_side": legacy_global_deconflict["selected_side"],
            "deconflict_selected_signal_id": legacy_global_deconflict[
                "selected_signal_id"
            ],
            "deconflict_selected_source_prediction_id": (
                legacy_global_deconflict["selected_source_prediction_id"]
            ),
            "deconflict_scope": "PER_SYMBOL_TELEMETRY_ONLY",
            "deconflict_scope_applies_to": "deconflict_by_symbol",
            "deconflict_by_symbol_scope": "PER_SYMBOL_TELEMETRY_ONLY",
            "deconflict_controls_publication": False,
            "deconflict_by_symbol": deconflict_by_symbol,
            "legacy_global_deconflict": legacy_global_deconflict,
            "legacy_global_deconflict_flat_fields_preserved": True,
            "legacy_global_deconflict_flat_fields_scope": (
                "GLOBAL_CROSS_SYMBOL_LEGACY_DIAGNOSTIC_ONLY"
            ),
            "held_by_paper_fill_gate": held_by_gate,
            "held_by_paper_fill_gate_count": len(held_by_gate),
            "skipped_malformed_predictions": skipped_malformed[:200],
            "skipped_malformed_prediction_count": len(skipped_malformed),
            "canonical_record_status_counts": canonical_record_status_counts,
            "canonical_record_blocked_winner_ids": canonical_record_blocked_winner_ids,
        }
        if _safe_write(
            r, f"{V2_REDIS_PREFIX}orchestrator:proposals",
            json.dumps(proposals_payload), ex=600,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}orchestrator:proposals")
        if _safe_write(
            r, f"{V2_REDIS_PREFIX}orchestrator:decisions",
            json.dumps(decisions_payload), ex=600,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}orchestrator:decisions")
        # Paper signals are proposals awaiting the binding risk gateway.  An
        # upstream paper gate can make a prediction eligible for arbitration,
        # but the orchestrator cannot grant fill permission.  The canonical
        # risk-decision id is deterministic and dereferences only after the
        # risk worker has evaluated the matching orchestrator decision.
        sig_payload = []
        for w in bucket_winners:
            lineage = signal_by_prediction_id.get(str(w["winner_proposal_id"])) or {}
            orchestrator_decision_id = (
                w.get("orchestrator_decision_id")
                or f"dec_{w['winner_proposal_id']}"
            )
            risk_decision_id = f"rd_{orchestrator_decision_id}"
            signed_edge = _finite_float(
                w.get("winner_expected_move_after_cost_bps_signed"),
                w["winner_expected_move_after_cost_bps"],
            )
            directional_edge = _finite_float(
                w.get("winner_expected_move_after_cost_bps_directional"),
                signed_edge if w["side"] == "long" else -signed_edge,
            )
            signal_row = {
                "signal_id": lineage.get("signal_id") or f"sig_{w['winner_proposal_id']}",
                "side": w["side"],
                "symbol": w["symbol"],
                "timeframe": lineage.get("timeframe"),
                "winner_proposal_id": w["winner_proposal_id"],
                "prediction_id": w["winner_proposal_id"],
                "source_prediction_id": w["winner_proposal_id"],
                "risk_decision_id": risk_decision_id,
                "orchestrator_decision_id": orchestrator_decision_id,
                "decision_id": w.get("decision_id") or lineage.get("decision_id") or f"dec_{w['winner_proposal_id']}",
                "expected_move_after_cost_bps": signed_edge,
                "expected_move_after_cost_bps_signed": signed_edge,
                "expected_move_after_cost_bps_directional": directional_edge,
                "confidence_calibrated": w["winner_confidence_calibrated"],
                "model_version": lineage.get("model_version") or w.get("winner_model_version"),
                "trainer_source": lineage.get("trainer_source"),
                "model_id": lineage.get("model_id"),
                "checkpoint_id": lineage.get("checkpoint_id"),
                "feature_snapshot_id": lineage.get("feature_snapshot_id"),
                "upstream_paper_fill_allowed": (
                    lineage.get("upstream_paper_fill_allowed") is True
                ),
                "upstream_paper_fill_gate_status": lineage.get(
                    "upstream_paper_fill_gate_status"
                ),
                "paper_fill_allowed": False,
                "paper_fill_gate_status": "RISK_PENDING",
                "paper_fill_gate_block_reasons": ["RISK_GATEWAY_DECISION_PENDING"],
                "risk_state": "PENDING_RISK_GATEWAY_DECISION",
                "routes_to_risk_gateway": True,
                "feature_freshness_state": "CURRENT",
                "market_state_id": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("market_state_id"),
                "market_state_integrity_score": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("market_state_integrity_score"),
                "valid_for_prediction": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("valid_for_prediction"),
                "valid_for_risk": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("valid_for_risk"),
                "valid_for_orchestrator": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("valid_for_orchestrator"),
                "valid_for_paper": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("valid_for_paper"),
                "valid_for_live": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("valid_for_live"),
                "market_state_reject_reasons": (integrity_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("reject_reasons"),
                "freshness_seconds": w.get("winner_freshness_seconds"),
                "live_gate": live_context["live_gate"],
                "live_symbols": live_context["live_symbols"],
                "execution_live_symbols": live_context["execution_live_symbols"],
                "places_real_order": False,
            }
            signal_row.update(_copy_trust_envelope_fields(lineage))
            signal_row["signal_id"] = lineage.get("signal_id") or f"sig_{w['winner_proposal_id']}"
            signal_row["side"] = w["side"]
            signal_row["symbol"] = w["symbol"]
            signal_row["timeframe"] = lineage.get("timeframe")
            signal_row["selected_action"] = lineage.get("selected_action")
            signal_row["winner_proposal_id"] = w["winner_proposal_id"]
            signal_row["prediction_id"] = w["winner_proposal_id"]
            signal_row["source_prediction_id"] = w["winner_proposal_id"]
            signal_row["risk_decision_id"] = risk_decision_id
            signal_row["orchestrator_decision_id"] = orchestrator_decision_id
            signal_row["decision_id"] = (
                w.get("decision_id")
                or lineage.get("decision_id")
                or signal_row["orchestrator_decision_id"]
            )
            signal_row["model_version"] = lineage.get("model_version") or w.get("winner_model_version")
            signal_row["checkpoint_id"] = lineage.get("checkpoint_id")
            signal_row["feature_snapshot_id"] = lineage.get("feature_snapshot_id")
            signal_row["expected_move_after_cost_bps"] = signed_edge
            signal_row["expected_move_after_cost_bps_signed"] = signed_edge
            signal_row["expected_move_after_cost_bps_directional"] = directional_edge
            signal_row["paper_fill_allowed"] = False
            sig_payload.append(signal_row)
        if _safe_write(
            r, f"{V2_REDIS_PREFIX}signals:paper",
            json.dumps(sig_payload), ex=600,
        ):
            keys_written.append(f"{V2_REDIS_PREFIX}signals:paper")
    classification = (
        "V2_ORCHESTRATOR_PRODUCTION_OK"
        if proposals else
        ("BLOCKED_BY_REDIS_UNAVAILABLE" if r is None else
         "NO_OPEN_GATE_PROPOSALS_PAPER_ONLY")
    )
    # Per-symbol missing-feature attribution (item 3): surface which symbols
    # have weak feature coverage so operators can diagnose stale predictions.
    per_symbol_feature_gaps = [
        _per_symbol_missing_features(p)
        for p in predictions
        if (int(p.get("missing_feature_count") or 0) > 0 or int(p.get("stale_feature_count") or 0) > 0)
    ]
    # Deduplicate by symbol — keep the worst coverage row per symbol.
    gap_by_symbol: dict[str, dict[str, Any]] = {}
    for row in per_symbol_feature_gaps:
        sym = row["symbol"]
        if sym not in gap_by_symbol or (row["missing_feature_count"] or 0) > (gap_by_symbol[sym]["missing_feature_count"] or 0):
            gap_by_symbol[sym] = row
    status = {
        "worker_id": "v2_orchestrator_arbitration_loop",
        "schema_version": "v2_orchestrator_arbitration_live_v1",
        "started_at": started,
        "finished_at": _utc_iso(),
        "predictions_seen": len(predictions),
        "proposals_arbitrated": len(proposals),
        "predictions_held_by_paper_fill_gate": len(held_by_gate),
        "held_by_paper_fill_gate": held_by_gate,
        "skipped_malformed_prediction_count": len(skipped_malformed),
        "skipped_malformed_predictions": skipped_malformed[:200],
        "bucket_winners_count": len(bucket_winners),
        "arbitration_bucket_winners_before_canonical_store": len(arb.bucket_winners),
        "canonical_record_status_counts": canonical_record_status_counts,
        "canonical_record_blocked_winner_ids": canonical_record_blocked_winner_ids,
        "stale_proposal_count": len(arb.stale_proposal_ids),
        "deconflict_reason": legacy_global_deconflict["conflict_reason"],
        "deconflict_selected_side": legacy_global_deconflict["selected_side"],
        "deconflict_selected_signal_id": legacy_global_deconflict[
            "selected_signal_id"
        ],
        "deconflict_selected_source_prediction_id": legacy_global_deconflict[
            "selected_source_prediction_id"
        ],
        "deconflict_scope": "PER_SYMBOL_TELEMETRY_ONLY",
        "deconflict_scope_applies_to": "deconflict_by_symbol",
        "deconflict_by_symbol_scope": "PER_SYMBOL_TELEMETRY_ONLY",
        "deconflict_controls_publication": False,
        "deconflict_by_symbol": deconflict_by_symbol,
        "legacy_global_deconflict": legacy_global_deconflict,
        "legacy_global_deconflict_flat_fields_preserved": True,
        "legacy_global_deconflict_flat_fields_scope": (
            "GLOBAL_CROSS_SYMBOL_LEGACY_DIAGNOSTIC_ONLY"
        ),
        "v2_orchestrator_keys_written": keys_written,
        "v2_orchestrator_keys_written_count": len(keys_written),
        "classification": classification,
        "live_gate": live_context["live_gate"],
        "live_symbols": live_context["live_symbols"],
        "execution_live_symbols": live_context["execution_live_symbols"],
        "live_gate_runtime_context": live_context,
        "high_precision_paper_mode": _high_precision_paper_mode_active(),
        "per_symbol_feature_gaps": list(gap_by_symbol.values()),
        "symbols_with_feature_gaps": sorted(gap_by_symbol),
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "cannot_bypass_risk_gateway": True,
        "writes_legacy_redis": False,
    }
    if r is not None:
        _safe_write(
            r, f"{V2_REDIS_PREFIX}orchestrator:heartbeat",
            json.dumps(status), ex=300,
        )
    return status


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_orchestrator_arbitration_loop")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            hb = run_once()
            write_payload(hb, args.out)
            time.sleep(max(5, int(args.interval_seconds)))
    hb = run_once()
    write_payload(hb, args.out)
    print(json.dumps({
        "classification": hb["classification"],
        "proposals_arbitrated": hb["proposals_arbitrated"],
        "bucket_winners_count": hb["bucket_winners_count"],
        "v2_orchestrator_keys_written_count": hb["v2_orchestrator_keys_written_count"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
