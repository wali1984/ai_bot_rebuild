"""V2 risk gateway live loop.

Consumes the live V2 orchestrator arbitration output from
``v2:orchestrator:decisions`` and stamps risk decisions with the same
domain service used by ``v2_risk_gateway_runtime_worker``. This is a
controller loop only: it writes V2 risk payloads and public status
artifacts, never exchange orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.composition.risk_gateway import build_risk_decision_evaluator
from v2.backend.app.services.live_gate.runtime_execution_state import (
    LIVE_GATE_BLOCKED,
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
)
from v2.backend.app.services.market_state_integrity import TrustGateResult
from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    DECISION_REASON_PROCEED_LONG,
    DECISION_REASON_PROCEED_SHORT,
    OrchestratorDecisionRecord,
)

V2_REDIS_PREFIX = "v2:"
LIVE_GATE_STATUS = LIVE_GATE_BLOCKED
PUBLIC_WORKER_ID = "v2_risk_gateway_runtime_worker"
LOOP_WORKER_ID = "v2_risk_gateway_live_loop"
REPO_ROOT = Path(__file__).resolve().parents[4]
_MICROSTRUCTURE_SHADOW_BLOCK_THRESHOLD = 0.45
_MICROSTRUCTURE_SWEEP_BLOCK_THRESHOLD = 0.75
_MICROSTRUCTURE_BLOCK_ACTIONS = {"NO_TRADE", "SHADOW_ONLY", "CLOSE_OR_REDUCE_ONLY"}
PUBLIC_STATUS_FILE = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest"
    / "v2_risk_gateway_runtime_worker_status.json"
)
LOCAL_STATUS_FILE = (
    REPO_ROOT
    / "v2/runtime/v2_risk_gateway_runtime_worker/latest"
    / "v2_risk_gateway_runtime_worker_status.json"
)
WORKLOG_STATUS_FILE = (
    REPO_ROOT
    / "claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers"
    / "v2_risk_gateway_runtime_worker_status.json"
)

_TRUST_ENVELOPE_FIELDS = (
    "signal_id",
    "decision_id",
    "orchestrator_decision_id",
    "feature_snapshot_id",
    "mtf_snapshot_id",
    "feature_cutoff",
    "decision_time",
    "available_at",
    "symbol",
    "timeframe",
    "selected_action",
    "model_version",
    "checkpoint_id",
    "source_hashes",
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
    "risk_microstructure_reject_reasons",
    "source_availability",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def _live_context(client) -> dict[str, Any]:
    runtime = read_runtime_execution_state(redis_client=client)
    payload = runtime.get("payload") if isinstance(runtime.get("payload"), dict) else {}
    validation = runtime.get("validation") if isinstance(runtime.get("validation"), dict) else {}
    if validation.get("valid") and payload.get("live_gate") == LIVE_GATE_ENABLED:
        return {
            "live_gate": LIVE_GATE_ENABLED,
            "live_symbols": [str(symbol) for symbol in payload.get("live_symbols") or []],
            "execution_live_symbols": [
                str(symbol) for symbol in payload.get("execution_live_symbols") or []
            ],
            "v2_live_gate_enabled": True,
            "runtime_validation": validation,
            "runtime_source": runtime.get("source"),
        }
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "v2_live_gate_enabled": False,
        "runtime_validation": validation,
        "runtime_source": runtime.get("source"),
    }


def _safe_set_v2(client, key: str, payload: Any, *, ex: int) -> bool:
    if client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
        return True
    except Exception:
        return False


def _read_json_key(client, key: str) -> dict[str, Any] | None:
    if client is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


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


def _microstructure_contexts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    contexts = [payload]
    for key in ("microstructure_context", "market_microstructure", "microstructure"):
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


def _finite_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _truthy_microstructure_flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _microstructure_reject_reasons(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    action = str(_microstructure_value(payload, "microstructure_action") or "").upper()
    if action in _MICROSTRUCTURE_BLOCK_ACTIONS:
        reasons.append(f"MICROSTRUCTURE_ACTION_{action}")
    trust_score = _finite_or_none(
        _microstructure_value(payload, "microstructure_trust_score", "orderbook_trust_score")
    )
    if trust_score is not None and trust_score < _MICROSTRUCTURE_SHADOW_BLOCK_THRESHOLD:
        reasons.append("MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED")
    sequence_gap = _microstructure_value(payload, "book_sequence_gap", "sequence_gap_flag")
    if _truthy_microstructure_flag(sequence_gap):
        reasons.append("MICROSTRUCTURE_SEQUENCE_GAP")
    sweep_risk = _finite_or_none(_microstructure_value(payload, "sweep_risk_score", "sweep_risk"))
    if sweep_risk is not None and sweep_risk >= _MICROSTRUCTURE_SWEEP_BLOCK_THRESHOLD:
        reasons.append("MICROSTRUCTURE_SWEEP_RISK_BLOCK")
    return sorted(set(reasons))


def _enrich_risk_payload(
    *,
    risk_record: Any,
    decision: OrchestratorDecisionRecord,
    winner: dict[str, Any],
) -> dict[str, Any]:
    payload = asdict(risk_record)
    payload.update(_copy_trust_envelope_fields(winner))
    payload["prediction_id"] = decision.prediction_id
    payload["feature_snapshot_id"] = decision.feature_snapshot_id
    payload["symbol"] = decision.symbol
    payload["decision_id"] = winner.get("decision_id") or decision.decision_id
    payload["orchestrator_decision_id"] = (
        winner.get("orchestrator_decision_id") or decision.decision_id
    )
    payload["selected_action"] = winner.get("selected_action") or winner.get("side")
    payload["model_version"] = winner.get("model_version") or winner.get("winner_model_version")
    return payload


def _winner_to_decision(winner: dict[str, Any], *, now_ms: int) -> OrchestratorDecisionRecord:
    symbol = str(winner.get("symbol") or "").upper()
    prediction_id = str(winner.get("winner_proposal_id") or f"missing_prediction_{symbol}")
    side = str(winner.get("side") or "flat").lower()
    freshness = float(winner.get("winner_freshness_seconds") or 0.0)
    confidence = float(winner.get("winner_confidence_calibrated") or 0.0)
    feature_snapshot_id = str(
        winner.get("feature_snapshot_id")
        or f"risk_gateway_live_feature_{symbol}_{prediction_id[-24:]}"
    )
    if freshness > 300.0:
        action = DECISION_ACTION_ABSTAIN
        reason = DECISION_REASON_ABSTAIN_FRESHNESS_STALE
        direction = "long" if side == "long" else "short" if side == "short" else "flat"
        freshness_flag = "stale"
    elif side == "long":
        action = DECISION_ACTION_OPEN_LONG
        reason = DECISION_REASON_PROCEED_LONG
        direction = "long"
        freshness_flag = "fresh"
    elif side == "short":
        action = DECISION_ACTION_OPEN_SHORT
        reason = DECISION_REASON_PROCEED_SHORT
        direction = "short"
        freshness_flag = "fresh"
    else:
        action = DECISION_ACTION_HOLD
        reason = DECISION_REASON_HOLD_FLAT_DIRECTION
        direction = "flat"
        freshness_flag = "fresh"
    return OrchestratorDecisionRecord(
        decision_id=f"dec_{prediction_id}"[:128],
        prediction_id=prediction_id[:128],
        feature_snapshot_id=feature_snapshot_id[:128],
        symbol=symbol,
        decision_ts_ms=now_ms,
        decision_action=action,
        decision_reason_code=reason,
        input_prediction_direction=direction,
        input_prediction_confidence_calibrated=max(0.0, min(1.0, confidence)),
        input_prediction_freshness_flag=freshness_flag,
        input_worker_health_status="HEALTHY",
        live_blocked=True,
    )


def _status_from_records(
    *,
    started_at: str,
    decisions_payload: dict[str, Any] | None,
    decision_records: list[OrchestratorDecisionRecord],
    risk_records: list[Any],
    risk_payloads: list[dict[str, Any]] | None,
    keys_written: list[str],
    redis_ok: bool,
    live_context: dict[str, Any],
) -> dict[str, Any]:
    latest = risk_records[-1] if risk_records else None
    latest_decision = decision_records[-1] if decision_records else None
    denials: dict[str, int] = {}
    for rec in risk_records:
        if rec.risk_action == "deny":
            denials[rec.risk_reason_code] = denials.get(rec.risk_reason_code, 0) + 1
    status = {
        "worker_id": PUBLIC_WORKER_ID,
        "runtime_loop_worker_id": LOOP_WORKER_ID,
        "schema_version": "v2_risk_gateway_live_loop_v1",
        "last_run_ts": _utc_iso(),
        "started_at": started_at,
        "finished_at": _utc_iso(),
        "runtime_evidence_status": "PRESENT" if risk_records else "MISSING_RUNTIME_EVIDENCE",
        "classification": "V2_RISK_GATEWAY_LIVE_OK" if risk_records else "NO_ORCHESTRATOR_WINNERS_PRESENT",
        "orchestrator_source_key": "v2:orchestrator:decisions",
        "orchestrator_generated_utc": (decisions_payload or {}).get("generated_utc"),
        "orchestrator_winners_seen": len((decisions_payload or {}).get("bucket_winners") or []),
        "decisions_processed_total": len(risk_records),
        "denials_breakdown": denials,
        "risk_decisions": risk_payloads if risk_payloads is not None else [asdict(rec) for rec in risk_records],
        "v2_risk_keys_written": keys_written,
        "v2_risk_keys_written_count": len(keys_written),
        "redis_ok": redis_ok,
        "live_gate": LIVE_GATE_BLOCKED,
        "current_gate_state": LIVE_GATE_BLOCKED,
        "current_gate_state_must_equal_blocked_human_only": True,
        "gate_always_blocked_invariant": True,
        "live_symbols": [],
        "execution_live_symbols": [],
        "live_blocked": True,
        "legacy_live_blocked": True,
        "legacy_live_blocked_label": "LEGACY_LIVE_PATH_BLOCKED_NOT_V2",
        "v2_live_gate_enabled": False,
        "live_gate_runtime_context": live_context,
        "fail_closed": True,
        "exchange_action_taken": False,
        "places_real_order": False,
        "writes_legacy_redis": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }
    latest_payload = risk_payloads[-1] if risk_payloads else None
    if latest is not None and latest_decision is not None:
        status.update({
            "last_decision_id": latest_decision.decision_id,
            "last_decision_ts": latest_decision.decision_ts_ms,
            "last_risk_decision_id": latest.risk_decision_id,
            "last_risk_decision_ts_ms": latest.risk_decision_ts_ms,
            "risk_action": latest.risk_action,
            "risk_reason_code": latest.risk_reason_code,
            "input_decision_action": latest.input_decision_action,
            "input_decision_reason_code": latest.input_decision_reason_code,
            "symbol": latest.symbol,
            "prediction_id": latest.prediction_id,
            "feature_snapshot_id": latest.feature_snapshot_id,
            "input_prediction_direction": latest_decision.input_prediction_direction,
            "input_prediction_confidence_calibrated": latest_decision.input_prediction_confidence_calibrated,
            "input_prediction_freshness_flag": latest_decision.input_prediction_freshness_flag,
            "input_worker_health_status": latest_decision.input_worker_health_status,
        })
        if latest_payload:
            for field in _TRUST_ENVELOPE_FIELDS:
                if field in latest_payload:
                    status[field] = latest_payload[field]
    return status


def _write_status_files(payload: dict[str, Any]) -> None:
    for path in (PUBLIC_STATUS_FILE, LOCAL_STATUS_FILE, WORKLOG_STATUS_FILE):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


_RISK_PROFILE_PROPOSAL_FILE = (
    REPO_ROOT
    / "v2/frontend/public/v2_exchange_filter_risk_profile_alignment_and_min_order_execution/latest"
    / "executable_minimum_conservative_risk_profile_proposal.json"
)


def _active_risk_profile_payload() -> dict[str, Any] | None:
    """Build the v2:risk:active_profile payload from the operator risk-profile artifact.

    Contract consumed by /api/v2/risk/status and the trader snapshot risk
    section: {profile_id, profile_name, fields{}}.
    """
    try:
        proposal = json.loads(_RISK_PROFILE_PROPOSAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    profile = proposal.get("profile")
    if not isinstance(profile, dict):
        return None
    fields = profile.get("risk_fields")
    if not isinstance(fields, dict):
        return None
    return {
        "profile_id": profile.get("profile_id") or "conservative_min_executable",
        "profile_name": profile.get("profile_name") or "conservative_min_executable",
        "fields": {
            **fields,
            "live_trading_enabled": False,
            "operator_acceptance_required": proposal.get("operator_acceptance_required", True),
        },
        "source_artifact": str(_RISK_PROFILE_PROPOSAL_FILE.relative_to(REPO_ROOT)),
        "published_by": LOOP_WORKER_ID,
        "published_at": _utc_iso(),
    }


def run_once(*, ttl_seconds: int = 300) -> dict[str, Any]:
    started = _utc_iso()
    client = _connect_redis()
    live_context = _live_context(client)
    payload = _read_json_key(client, f"{V2_REDIS_PREFIX}orchestrator:decisions")
    winners = (payload or {}).get("bucket_winners") or []
    if not isinstance(winners, list):
        winners = []
    evaluator = build_risk_decision_evaluator(now_ms_clock=_now_ms)
    now = _now_ms()
    decisions: list[OrchestratorDecisionRecord] = []
    risks: list[Any] = []
    risk_payloads: list[dict[str, Any]] = []
    for winner in winners:
        if not isinstance(winner, dict):
            continue
        microstructure_reject_reasons = _microstructure_reject_reasons(winner)
        winner_for_payload = dict(winner)
        winner_for_payload["risk_microstructure_reject_reasons"] = microstructure_reject_reasons
        try:
            decision = _winner_to_decision(winner_for_payload, now_ms=now)
            risk = evaluator(
                decision=decision,
                trust_gate_result=TrustGateResult(
                    accepted=False,
                    severity="reject",
                    reject_reasons=tuple(
                        ["live_trading_disabled", "market_state_envelope_missing"]
                        + microstructure_reject_reasons
                    ),
                    warnings=(),
                    data_quality_score=0.0,
                    future_leak_detected=False,
                    cutoff_mismatch_detected=False,
                    replay_required=True,
                    metrics={"source": LOOP_WORKER_ID},
                ),
            )
        except Exception:
            continue
        decisions.append(decision)
        risks.append(risk)
        risk_payloads.append(
            _enrich_risk_payload(
                risk_record=risk,
                decision=decision,
                winner=winner_for_payload,
            )
        )
    keys_written: list[str] = []
    if client is not None:
        active_profile = _active_risk_profile_payload()
        # When this cycle produced no winners, refresh the previous latest
        # decision instead of clobbering it with {} — an alive gateway with no
        # new winners is not an offline gateway.
        latest_payload: Any = risk_payloads[-1] if risk_payloads else None
        if latest_payload is None:
            previous_latest = _read_json_key(client, f"{V2_REDIS_PREFIX}risk:gateway:latest")
            latest_payload = previous_latest if isinstance(previous_latest, dict) and previous_latest else {}
        writes: list[tuple[str, Any]] = [
            (f"{V2_REDIS_PREFIX}risk:gateway:decisions", risk_payloads),
            (f"{V2_REDIS_PREFIX}risk:gateway:latest", latest_payload),
        ]
        if active_profile is not None:
            writes.append((f"{V2_REDIS_PREFIX}risk:active_profile", active_profile))
        for key, body in writes:
            if _safe_set_v2(client, key, body, ex=ttl_seconds):
                keys_written.append(key)
    status = _status_from_records(
        started_at=started,
        decisions_payload=payload,
        decision_records=decisions,
        risk_records=risks,
        risk_payloads=risk_payloads,
        keys_written=keys_written,
        redis_ok=client is not None,
        live_context=live_context,
    )
    if client is not None and _safe_set_v2(
        client, f"{V2_REDIS_PREFIX}risk:gateway:heartbeat", status, ex=ttl_seconds
    ):
        status["v2_risk_keys_written"].append(f"{V2_REDIS_PREFIX}risk:gateway:heartbeat")
        status["v2_risk_keys_written_count"] = len(status["v2_risk_keys_written"])
    _write_status_files(status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=LOOP_WORKER_ID)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    while True:
        status = run_once(ttl_seconds=int(args.v2_redis_ttl_seconds))
        if not args.loop:
            print(json.dumps({
                "classification": status["classification"],
                "decisions_processed_total": status["decisions_processed_total"],
                "risk_action": status.get("risk_action"),
                "risk_reason_code": status.get("risk_reason_code"),
                "v2_risk_keys_written_count": status["v2_risk_keys_written_count"],
            }, sort_keys=True))
            return 0 if status["decisions_processed_total"] else 2
        time.sleep(max(5, int(args.interval_seconds)))


if __name__ == "__main__":
    sys.exit(main())
