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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.live_gate.runtime_execution_state import (
    LIVE_GATE_BLOCKED,
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
)
from v2.backend.app.services.market_state_integrity.scoring import score_market_state

V2_REDIS_PREFIX = "v2:"
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_orchestrator_arbitration/live/latest/v2_orchestrator_arbitration_live_status.json"
)
MAX_PREDICTION_AGE_SECONDS = 300


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


def _scan_predictions(r) -> list[dict]:
    if r is None:
        return []
    by_prediction_id: dict[str, dict] = {}
    out_without_id: list[dict] = []
    for key in r.scan_iter(match=f"{V2_REDIS_PREFIX}prediction:*"):
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
            age = _prediction_age_seconds(data)
            ttl = _finite_float(r.ttl(key), -1.0)
            if age is None or age > MAX_PREDICTION_AGE_SECONDS:
                continue
            if ttl == 0:
                continue
            data = dict(data)
            data["source_redis_key"] = key
            existing = by_prediction_id.get(prediction_id)
            if existing is None or _prediction_source_rank(key) > _prediction_source_rank(
                str(existing.get("source_redis_key") or "")
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
    payload["source_redis_key"] = key
    return payload


def _prediction_integrity_input(r, prediction: dict[str, Any]) -> dict[str, Any]:
    feature = _load_latest_feature_row(r, prediction)
    if feature is None:
        return dict(prediction)
    merged = dict(prediction)
    for key in (
        "features",
        "generated_at",
        "feature_freshness_state",
        "missing_feature_count",
        "missing_feature_flags",
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
    return merged


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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
    side_for_action = {"long": "long", "short": "short", "close": "flat", "hold": "flat", "hedge": "flat"}
    sel = side_for_action.get(p.get("selected_action", "hold"), "flat")
    if sel == "flat":
        sel = "long" if (p.get("expected_move_bps") or 0) >= 0 else "short"
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
    model_version = _first_text(
        p.get("model_version"),
        p.get("model_id"),
        p.get("checkpoint_id"),
        p.get("trainer_source"),
    ) or "v2_orchestrator_unknown_model"
    source = _first_text(p.get("trainer_source"), p.get("source")) or "V2_NATIVE_PREDICTION"
    confidence_raw = max(0.0, min(1.0, _finite_float(p.get("confidence_raw"), 0.0)))
    confidence_calibrated = max(0.0, min(1.0, _finite_float(p.get("confidence_calibrated"), confidence_raw)))
    expected_move_after_cost = _finite_float(p.get("expected_move_after_cost_bps"), 0.0)
    proposal = {
        "proposal_id": prediction_id,
        "symbol": symbol,
        "side": sel,
        "confidence_calibrated": confidence_calibrated,
        "expected_move_after_cost_bps": expected_move_after_cost,
        "generated_utc": generated_utc,
        "source": source,
        "freshness_seconds": 5.0,
        "model_version": model_version,
    }
    signal = {
        "signal_id": prediction_id,
        "symbol": symbol,
        "timeframe": p.get("timeframe"),
        "side": sel,
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_calibrated,
        "expected_move_after_cost_bps": expected_move_after_cost,
        "source_prediction_id": prediction_id,
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "generated_utc": generated_utc,
        "freshness_seconds": 5.0,
        "model_version": model_version,
        "trainer_source": p.get("trainer_source"),
        "model_id": p.get("model_id"),
        "checkpoint_id": p.get("checkpoint_id"),
    }
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
    move = _finite_float(prediction.get("expected_move_after_cost_bps"), 0.0)
    if move < _HPPM_MIN_EXPECTED_MOVE_AFTER_COST_BPS:
        reasons.append(
            f"HPPM_LOW_EXPECTED_MOVE:{move:.1f}bps<{_HPPM_MIN_EXPECTED_MOVE_AFTER_COST_BPS}"
        )
    coverage = _finite_float(prediction.get("data_coverage_percent"), 0.0)
    if coverage < _HPPM_MIN_DATA_COVERAGE_PCT:
        reasons.append(
            f"HPPM_LOW_DATA_COVERAGE:{coverage:.1f}%<{_HPPM_MIN_DATA_COVERAGE_PCT}"
        )
    action = str(prediction.get("selected_action") or "").lower()
    if action in ("hold", "flat", ""):
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
        integrity_block_reasons = (
            ["MARKET_STATE_INTEGRITY_REJECTED_FOR_ORCHESTRATOR"]
            if not integrity.get("valid_for_orchestrator")
            else []
        )
        # Only gate out predictions that are EXPLICITLY set to False by an
        # upstream publisher. Missing / None means the publisher hasn't
        # annotated this prediction yet; in that case fall through to the
        # market-state integrity check which is the authoritative quality gate.
        gate_explicitly_blocked = p.get("paper_fill_allowed") is False
        if gate_explicitly_blocked or integrity_block_reasons:
            # Gate blocked this prediction; do not arbitrate, but surface
            # block reasons so downstream consumers can diagnose.
            reasons = list(p.get("paper_fill_gate_block_reasons") or [])
            reasons.extend(integrity_block_reasons)
            reasons.extend(integrity.get("reject_reasons") or [])
            if gate_explicitly_blocked and not integrity_block_reasons:
                reasons.append("PAPER_FILL_ALLOWED_EXPLICITLY_FALSE")
            held_by_gate.append({
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "prediction_id": p.get("prediction_id"),
                "signal_id": f"held_signal_{p.get('prediction_id')}",
                "orchestrator_decision_id": f"held_decision_{p.get('prediction_id')}",
                "risk_decision_id": None,
                "risk_state": "NOT_ROUTED_TO_RISK_GATEWAY_BECAUSE_PAPER_FILL_GATE_BLOCKED",
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
                "checkpoint_blocker": p.get("checkpoint_blocker"),
                "decision": "HELD_BY_PAPER_FILL_GATE",
                "places_real_order": False,
                "generated_utc": p.get("generated_utc"),
            })
            continue

        # High-precision paper mode gate (item 6): apply additional quality
        # thresholds when V2_HIGH_PRECISION_PAPER_MODE=1.
        hppm_reasons = _hppm_gate(p) if _high_precision_paper_mode_active() else []
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
    keys_written: list[str] = []
    if r is not None:
        proposals_payload = [
            {
                "proposal_id": pr.proposal_id,
                "symbol": pr.symbol,
                "side": pr.side,
                "confidence_calibrated": pr.confidence_calibrated,
                "expected_move_after_cost_bps": pr.expected_move_after_cost_bps,
                "source": pr.source,
                "freshness_seconds": pr.freshness_seconds,
                "model_version": pr.model_version,
                "generated_utc": pr.generated_utc,
            }
            for pr in proposals
        ]
        bucket_winners = [
            {
                "symbol": w.symbol,
                "side": w.side,
                "winner_proposal_id": w.winner.proposal_id,
                "winner_confidence_calibrated": w.winner.confidence_calibrated,
                "winner_expected_move_after_cost_bps": w.winner.expected_move_after_cost_bps,
                "winner_freshness_seconds": w.winner.freshness_seconds,
                "winner_model_version": w.winner.model_version,
                "considered_proposal_ids": list(w.considered_proposal_ids),
                "score": w.score,
            }
            for w in arb.bucket_winners
        ]
        decisions_payload = {
            "schema_version": "v2_orchestrator_decisions_v2",
            "generated_utc": _utc_iso(),
            "considered_count": arb.considered_count,
            "bucket_winners": bucket_winners,
            "stale_proposal_ids": list(arb.stale_proposal_ids),
            "deconflict_reason": getattr(deconflict, "conflict_reason", None),
            "deconflict_selected_side": getattr(deconflict, "selected_side", None),
            "deconflict_selected_signal_id": getattr(deconflict, "selected_signal_id", None),
            "held_by_paper_fill_gate": held_by_gate,
            "held_by_paper_fill_gate_count": len(held_by_gate),
            "skipped_malformed_predictions": skipped_malformed[:200],
            "skipped_malformed_prediction_count": len(skipped_malformed),
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
        # Paper signals — bucket winners are GUARANTEED to be from
        # paper_fill_allowed=True predictions (predictions with
        # paper_fill_allowed=False are excluded from arbitration above).
        # Propagate paper_fill_allowed=True and enrichment fields so
        # v2_trade_management_paper_loop can record accepted paper fills.
        sig_payload = [
            {
                "signal_id": (signal_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("signal_id")
                or f"sig_{w['winner_proposal_id']}",
                "side": w["side"],
                "symbol": w["symbol"],
                "timeframe": (signal_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("timeframe"),
                "winner_proposal_id": w["winner_proposal_id"],
                "prediction_id": w["winner_proposal_id"],
                "source_prediction_id": w["winner_proposal_id"],
                "risk_decision_id": f"rd_{w['winner_proposal_id']}",
                "orchestrator_decision_id": f"dec_{w['winner_proposal_id']}",
                "expected_move_after_cost_bps": w["winner_expected_move_after_cost_bps"],
                "confidence_calibrated": w["winner_confidence_calibrated"],
                "model_version": w.get("winner_model_version"),
                "trainer_source": (signal_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("trainer_source"),
                "model_id": (signal_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("model_id"),
                "checkpoint_id": (signal_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("checkpoint_id"),
                "feature_snapshot_id": (signal_by_prediction_id.get(str(w["winner_proposal_id"])) or {}).get("feature_snapshot_id"),
                "paper_fill_allowed": True,
                "paper_fill_gate_status": "PAPER_FILL_ALLOWED_BY_ORCHESTRATOR_GATE",
                "paper_fill_gate_block_reasons": [],
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
            for w in bucket_winners
        ]
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
        "bucket_winners_count": len(arb.bucket_winners),
        "stale_proposal_count": len(arb.stale_proposal_ids),
        "deconflict_reason": getattr(deconflict, "conflict_reason", None),
        "deconflict_selected_side": getattr(deconflict, "selected_side", None),
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
