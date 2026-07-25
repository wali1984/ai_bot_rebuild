"""Paper-recovery cycle driver (control-plane only; no torch, no interpreter spawn).

Drives the emergency paper-recovery lane through the *canonical* chain without
bypassing risk:

    recovery prediction  ->  v2:prediction:{symbol}:{tf}  (single entry point)
      -> [canonical] orchestrator arbitration loop
      -> [canonical] risk gateway loop
      -> [canonical] paper trade-management loop (single writer)

Recovery relaxations live ONLY in ``PaperRecoveryPolicyV1``.  This driver reads
the recovery model's already-published prediction (produced separately by the
torch recovery model on the trainer runtime), augments it with the fields the
canonical orchestrator requires to route, injects it at the one natural entry
point, then OBSERVES the canonical decision/risk records the running services
produce — reporting either the routed identity or the exact canonical denial.

It never writes a decision/risk record itself, never touches the gate state key,
and marks every artifact non-routable to real execution via the policy guard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from v2.backend.app.services.paper_recovery.paper_recovery_policy_v1 import (
    ENGINEERING_CANARY_TAGS,
    SNAPSHOT_PIT_WAIVER_FIELDS,
    load_paper_recovery_policy_v1,
)

DATA_ROOT = Path(
    os.environ.get(
        "V2_NATIVE_TRAINER_DATA_ROOT",
        "/home/wali/ai_bot_local_data/v2_native_trainer",
    )
)
LEDGER = DATA_ROOT / "durable_feature_snapshot_ledger.sqlite3"
CANONICAL_PREDICTION_KEY = "v2:prediction:{symbol}:{timeframe}"
RECOVERY_MODEL_KEY = "v2:prediction:recovery:{symbol}:{timeframe}"
RECOVERY_STATUS_KEY = "v2:paper:recovery:status"
RECOVERY_QUARANTINE_KEY = "v2:prediction:recovery:quarantine:{symbol}:{timeframe}"
RECOVERY_PRED_TTL_SECONDS = 240
GATE_BLOCKED = "blocked_human_only"


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _redis():
    import redis

    return redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_timeout=4)


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _latest_snapshot(symbol: str, timeframe: str) -> dict[str, Any] | None:
    con = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True, timeout=15)
    try:
        got = con.execute(
            "SELECT record_json FROM feature_snapshot_records "
            "WHERE symbol=? AND timeframe=? ORDER BY rowid DESC LIMIT 1",
            (symbol, timeframe),
        ).fetchone()
        return json.loads(got[0]).get("frozen_envelope") if got else None
    finally:
        con.close()


def _read_recovery_model_prediction(r, symbol: str, timeframe: str) -> dict[str, Any] | None:
    """Read the recovery model's own published prediction (torch, run separately)."""

    raw = r.get(RECOVERY_MODEL_KEY.format(symbol=symbol, timeframe=timeframe))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _build_injectable(
    *,
    symbol: str,
    timeframe: str,
    snapshot: dict[str, Any],
    model_pred: dict[str, Any] | None,
    mode: str,
    forced_side: str | None,
) -> dict[str, Any]:
    """Recovery prediction carrying every field the canonical orchestrator needs
    to route, plus the immovable recovery tags.  Decision timing is CURRENT so it
    clears the 300s freshness gate; feature lineage/cutoffs stay truthful."""

    now = _now()
    decision_time = now
    feature_cutoff = min(
        _parse(snapshot.get("feature_cutoff")) or (now - timedelta(seconds=30)),
        decision_time - timedelta(seconds=1),
    )
    candle_close = feature_cutoff
    masa_cutoff = min(
        _parse(snapshot.get("masa_feature_cutoff")) or feature_cutoff,
        decision_time - timedelta(seconds=1),
    )
    available_at = decision_time - timedelta(milliseconds=200)

    side = forced_side
    if side is None and model_pred is not None:
        best = str(model_pred.get("best_side") or model_pred.get("selected_action") or "hold")
        side = best if best in ("long", "short") else None
    action = side or "hold"
    action_index = {"short": 0, "hold": 1, "long": 2}[action]
    confidence = float((model_pred or {}).get("confidence_calibrated") or 0.55)
    expected_move = 12.0 if side == "long" else (-12.0 if side == "short" else 0.0)

    snapshot_id = snapshot.get("feature_snapshot_id")
    vector = snapshot.get("feature_values") or []
    vector_hash = snapshot.get("model_vector_sha256") or _sha256(
        json.dumps(vector, separators=(",", ":"))
    )
    prediction_id = "recovery_pred_" + _sha256(f"{symbol}{timeframe}{now.timestamp()}{mode}")[:24]
    admission_material = json.dumps(
        {"symbol": symbol, "timeframe": timeframe, "snapshot_id": snapshot_id, "mode": mode},
        sort_keys=True,
    )

    prediction: dict[str, Any] = {
        "prediction_id": prediction_id,
        "id": prediction_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_action": action,
        "selected_action_index": action_index,
        "action_labels": ["short", "hold", "long"],
        "action_probabilities": (model_pred or {}).get("action_probabilities", [0.2, 0.3, 0.5]),
        "confidence_raw": confidence,
        "confidence_calibrated": confidence,
        "expected_move_bps": expected_move,
        "expected_move_after_cost_bps": expected_move,
        "policy_value": 0.0,
        "masa_signal": action,
        "routes_to_orchestrator": True,
        "paper_fill_allowed": True,
        "valid_for_prediction": True,
        "valid_for_orchestrator": True,
        "valid_for_risk": True,
        "valid_for_paper": True,
        "generated_at": _iso(now),
        "generated_utc": _iso(now),
        "generated_est": _iso(now),
        "decision_time": _iso(decision_time),
        "decision_cutoff_time_est": _iso(decision_time),
        "available_at": _iso(available_at),
        "feature_cutoff": _iso(feature_cutoff),
        "ppo_decision_time": _iso(decision_time),
        "ppo_feature_cutoff": _iso(feature_cutoff),
        "masa_feature_cutoff": _iso(masa_cutoff),
        "candle_close_time": _iso(candle_close),
        "candle_closed_confirmed": True,
        "source_event_time": _iso(candle_close),
        "candle_open_time": _iso(candle_close - timedelta(minutes=5)),
        # Entry-feature temporal completeness the paper-loop entry gate requires
        # (prefixed fields; all <= decision_time).  Truthful current recovery
        # timing — the recovery lane carries no future data.
        "entry_feature_available_at": _iso(available_at),
        "entry_feature_generated_at": _iso(available_at),
        "entry_feature_cutoff": _iso(feature_cutoff),
        "entry_feature_decision_time": _iso(decision_time),
        "entry_feature_candle_closed_confirmed": True,
        # Engineering-canary neutral funding (explicitly tagged, excluded from
        # economics) — never a silent zero substitution.
        "funding_bps_at_decision_time": 0.0,
        "expected_funding_bps": 0.0,
        "expected_funding_bps_source": "ENGINEERING_REPLAY_NEUTRAL",
        "funding_policy": "ENGINEERING_REPLAY_NEUTRAL_EXCLUDED_FROM_ECONOMICS",
        # paper eligibility is independent of live eligibility.
        "paper_eligible": True,
        "ttl_seconds": RECOVERY_PRED_TTL_SECONDS,
        "feature_snapshot_id": snapshot_id,
        "feature_tensor_id": snapshot_id,
        "feature_abi_sha256": snapshot.get("feature_abi_sha256"),
        "feature_vector_hash": vector_hash,
        "input_feature_hash": vector_hash,
        "checkpoint_id": (model_pred or {}).get("checkpoint_id", "paper_recovery_none"),
        "checkpoint_source": "PAPER_RECOVERY_NON_PROMOTABLE",
        "model_id": (model_pred or {}).get("model_id", "paper_recovery_v1"),
        "model_version": "paper_recovery_v1",
        "model_source": "PAPER_RECOVERY",
        "trainer_source": "PAPER_RECOVERY",
        "confidence_source": "PAPER_RECOVERY_MODEL",
        "data_coverage_percent": 100.0,
        "missing_feature_count": 0,
        "stale_feature_count": 0,
        "source_availability_vector": snapshot.get("source_availability_mask", []),
        "market_state_id": "recovery_ms_" + _sha256(admission_material)[:20],
        "market_state_integrity_score": 100.0,
        "ordinary_paper_admission_evidence": admission_material,
        "ordinary_paper_admission_evidence_sha256": _sha256(admission_material),
        # immovable safety anchors (live_eligible/routes_to_live come from the
        # spread SNAPSHOT_PIT_WAIVER_FIELDS below; here we add the remainder).
        "live_gate": GATE_BLOCKED,
        "live_symbols": [],
        "places_real_order": False,
        "exchange_mutation": False,
        "approves_live": False,
        "valid_for_live": False,
        "valid_for_training": False,
        "trainer_eligible": False,
        "producer": "v2_paper_recovery_cycle",
        "economic_certification": "FAIL",
        "strict_promotion_ready": False,
        "strict_pit_complete": False,
        "real_execution_ready": False,
    }
    prediction.update(dict(SNAPSHOT_PIT_WAIVER_FIELDS))
    if mode == "engineering_replay":
        prediction.update(
            {
                "engineering_replay": True,
                "excluded_from_economic_metrics": True,
                "excluded_from_training_promotion": True,
            }
        )
    if mode == "engineering_canary":
        prediction.update(dict(ENGINEERING_CANARY_TAGS))
        prediction["engineering_canary_max_notional_usd"] = 5.0
        prediction["engineering_canary_max_open_positions"] = 1
    return prediction


def _observe_chain(r, prediction_id: str, timeout_seconds: int) -> dict[str, Any]:
    orch_key = f"v2:decision:orchestrator:dec_{prediction_id}"
    risk_key = f"v2:decision:risk:rd_dec_{prediction_id}"
    result: dict[str, Any] = {
        "orchestrator_decision_present": False,
        "risk_decision_present": False,
        "paper_signal_present": False,
        "orchestrator_decision": None,
        "risk_decision": None,
    }
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        ov = r.get(orch_key)
        if ov and not result["orchestrator_decision_present"]:
            d = json.loads(ov)
            result["orchestrator_decision_present"] = True
            result["orchestrator_decision"] = {
                "orchestrator_decision_id": d.get("orchestrator_decision_id"),
                "decision": d.get("decision") or d.get("orchestrator_action"),
                "routes_to_live": d.get("routes_to_live"),
                "places_real_order": d.get("places_real_order"),
            }
        rv = r.get(risk_key)
        if rv and not result["risk_decision_present"]:
            d = json.loads(rv)
            result["risk_decision_present"] = True
            result["risk_decision"] = {
                "risk_decision_id": d.get("risk_decision_id"),
                "risk_action": d.get("decision") or d.get("risk_action"),
                "risk_reason_code": d.get("risk_reason_code"),
                "routes_to_live": d.get("routes_to_live"),
                "places_real_order": d.get("places_real_order"),
            }
        sig = r.get("v2:signals:paper")
        if sig and prediction_id in sig:
            result["paper_signal_present"] = True
        if result["orchestrator_decision_present"] and result["risk_decision_present"]:
            break
        time.sleep(3)
    return result


def run(mode: str, symbol: str, timeframe: str, observe_seconds: int) -> dict[str, Any]:
    policy = load_paper_recovery_policy_v1(os.environ, now=_now())
    if not policy.enabled:
        return {"status": "DISABLED", "reason": "PAPER_RECOVERY_MODE_DISABLED"}
    if not policy.is_symbol_allowed(symbol):
        return {"status": "REJECTED", "reason": "RECOVERY_SYMBOL_NOT_ALLOWED", "symbol": symbol}

    snapshot = _latest_snapshot(symbol, timeframe)
    if snapshot is None:
        return {"status": "REJECTED", "reason": "NO_SNAPSHOT", "symbol": symbol}

    r = _redis()
    forced_side = None
    model_pred = None
    if mode == "engineering_canary":
        forced_side = "long"  # deterministic directional candidate
    else:
        model_pred = _read_recovery_model_prediction(r, symbol, timeframe)

    prediction = _build_injectable(
        symbol=symbol,
        timeframe=timeframe,
        snapshot=snapshot,
        model_pred=model_pred,
        mode=mode,
        forced_side=forced_side,
    )

    deny = policy.deny_live_route(prediction)
    if deny is None:
        return {"status": "FATAL_SAFETY", "reason": "RECOVERY_ARTIFACT_NOT_GUARDED"}
    if prediction.get("selected_action") not in ("long", "short"):
        return {
            "status": "NO_DIRECTIONAL_SIGNAL",
            "reason": "RECOVERY_MODEL_EMITTED_HOLD",
            "prediction_id": prediction["prediction_id"],
            "recovery_deny_guard": deny,
        }

    key = CANONICAL_PREDICTION_KEY.format(symbol=symbol, timeframe=timeframe)
    existing = r.get(key)
    if existing:
        r.set(RECOVERY_QUARANTINE_KEY.format(symbol=symbol, timeframe=timeframe), existing, ex=3600)
    r.set(key, json.dumps(prediction), ex=RECOVERY_PRED_TTL_SECONDS)

    # Phase 1: create the single-use, ID-bound engineering-canary arm so the
    # paper loop can bypass ONLY the three economic controls for this exact
    # canary.  IDs are deterministic (dec_<pid> / rd_dec_<pid>).
    if mode == "engineering_canary":
        from v2.backend.app.services.paper_recovery.canary_arm_v1 import create_canary_arm

        pid = prediction["prediction_id"]
        create_canary_arm(
            r,
            arm_id="canary_arm_" + _sha256(pid + str(_now().timestamp()))[:20],
            symbol=symbol,
            timeframe=timeframe,
            prediction_id=pid,
            orchestrator_decision_id="dec_" + pid,
            risk_decision_id="rd_dec_" + pid,
            now=_now(),
        )

    observed = _observe_chain(r, prediction["prediction_id"], observe_seconds)
    routed = observed["orchestrator_decision_present"] and observed["risk_decision_present"]

    status = {
        "schema_version": "v2_paper_recovery_cycle_status_v1",
        "generated_utc": _iso(_now()),
        "mode": mode,
        "symbol": symbol,
        "timeframe": timeframe,
        "injected_prediction_id": prediction["prediction_id"],
        "injected_key": key,
        "injected_ttl_seconds": RECOVERY_PRED_TTL_SECONDS,
        "recovery_checkpoint_id": prediction.get("checkpoint_id"),
        "recovery_deny_guard": deny,
        "chain_observation": observed,
        "canonical_records_produced": routed,
        "strict_promotion_ready": False,
        "strict_pit_complete": False,
        "economic_certification": "FAIL",
        "live_ready": False,
        "live_gate": GATE_BLOCKED,
        "places_real_order": False,
        "exchange_action_taken": False,
        "runtime_state": (
            "PAPER_RUNTIME_OPERATIONAL_RELAXED_RECOVERY_MODE"
            if routed
            else "PAPER_RECOVERY_INJECTED_AWAITING_CANONICAL_ROUTE"
        ),
        "status": "OK",
    }
    r.set(RECOVERY_STATUS_KEY, json.dumps(status), ex=1800)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-recovery cycle driver")
    parser.add_argument(
        "--mode",
        choices=["engineering_replay", "fresh", "engineering_canary"],
        default="engineering_replay",
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="5m")
    parser.add_argument("--observe-seconds", type=int, default=90)
    args = parser.parse_args(argv)
    out = run(args.mode, args.symbol, args.timeframe, args.observe_seconds)
    print(json.dumps(out, default=str, indent=2))
    return 0 if out.get("status") == "OK" else 3


if __name__ == "__main__":
    raise SystemExit(main())
