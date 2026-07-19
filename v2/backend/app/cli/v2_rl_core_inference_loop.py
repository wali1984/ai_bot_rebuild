"""V2 RL core inference loop (paper-only, V2 namespace).

Reads v2:features:latest:{symbol}:{tf}, runs P0.2A-G chain
(observation -> policy -> trainer output -> strict paper-fill gate),
writes labelled sidecar predictions at
v2:trainer:rl_core_prediction_sidecar:{symbol}:{tf}, v2:trainer:status,
and v2:trainer:heartbeat. It does not overwrite the native CUDA primary
prediction keys and does not publish untrusted sidecars into canonical
prediction namespaces. Never writes legacy keys.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

V2_REDIS_PREFIX = "v2:"
DEFAULT_TF = "1m"
SIDECAR_PREDICTION_KEY_TEMPLATE = (
    f"{V2_REDIS_PREFIX}trainer:rl_core_prediction_sidecar:{{symbol}}:{{timeframe}}"
)
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_rl_core/live/latest/v2_rl_core_live_status.json"
)
CHECKPOINT_EVIDENCE_KEY = f"{V2_REDIS_PREFIX}trainer:checkpoint:evidence"
DEFAULT_CHECKPOINT_WEIGHT_STATUS = "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
HYBRID_TRAINER_STATUS_KEY = f"{V2_REDIS_PREFIX}trainer:hybrid_cuda:status"
TRAINER_LEARNING_FRESHNESS_SECONDS = 30 * 60


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


def _read_feature_snapshot(r, symbol: str, tf: str) -> dict | None:
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}features:latest:{symbol}:{tf}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _read_json_key(r, key: str) -> dict:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return {}
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _trainer_learning_truth(r) -> dict:
    """Read the learning trainer's weight-update truth; fail-closed.

    The sidecar must never claim trainer health it cannot prove: learning is
    asserted only when the hybrid trainer reports WEIGHTS_UPDATING with a
    fresh last_successful_weight_update_at.
    """
    hybrid = _read_json_key(r, HYBRID_TRAINER_STATUS_KEY)
    status = str(hybrid.get("online_learning_status") or "")
    last_update_raw = hybrid.get("last_successful_weight_update_at")
    fresh = False
    if last_update_raw:
        try:
            parsed = datetime.fromisoformat(str(last_update_raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            fresh = (
                datetime.now(timezone.utc) - parsed
            ).total_seconds() <= TRAINER_LEARNING_FRESHNESS_SECONDS
        except ValueError:
            fresh = False
    return {
        "weights_updating": status == "WEIGHTS_UPDATING" and fresh,
        "online_learning_status": status or None,
        "last_successful_weight_update_at": last_update_raw,
        "weight_update_fresh": fresh,
        "source_key": HYBRID_TRAINER_STATUS_KEY,
    }


def _read_checkpoint_evidence(r) -> dict:
    if r is None:
        return {}
    try:
        raw = r.get(CHECKPOINT_EVIDENCE_KEY)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("live_gate") != "blocked_human_only":
        return {}
    if payload.get("live_symbols") not in ([], (), None):
        return {}
    return payload


def _checkpoint_evidence_summary(checkpoint_evidence: dict) -> dict:
    return {
        "active_checkpoint_id": checkpoint_evidence.get("active_checkpoint_id"),
        "active_checkpoint_source": checkpoint_evidence.get("active_checkpoint_source"),
        "active_checkpoint_weight_status": checkpoint_evidence.get(
            "active_checkpoint_weight_status"
        ),
        "active_checkpoint_blocker": checkpoint_evidence.get(
            "active_checkpoint_blocker"
        ),
        "selected_checkpoint_id": checkpoint_evidence.get("selected_checkpoint_id"),
        "selected_checkpoint_path": checkpoint_evidence.get("selected_checkpoint_path"),
        "candidate_count": checkpoint_evidence.get("candidate_count"),
        "checkpoint_evidence_status": checkpoint_evidence.get(
            "checkpoint_evidence_status"
        ),
        "legacy_checkpoint_metadata_status": checkpoint_evidence.get(
            "legacy_checkpoint_metadata_status"
        ),
        "legacy_checkpoint_weight_status": checkpoint_evidence.get(
            "legacy_checkpoint_weight_status"
        ),
        "legacy_checkpoint_blocker": checkpoint_evidence.get(
            "legacy_checkpoint_blocker"
        ),
        "native_checkpoint_status": checkpoint_evidence.get(
            "native_checkpoint_status"
        ),
        "native_checkpoint_load_status": checkpoint_evidence.get(
            "native_checkpoint_load_status"
        ),
        "native_model_weights_load_verified": bool(
            checkpoint_evidence.get("native_model_weights_load_verified")
        ),
        "safe_npz_weight_load_verified": bool(
            checkpoint_evidence.get("safe_npz_weight_load_verified")
        ),
        "model_weights_loaded_into_v2_process": bool(
            checkpoint_evidence.get("model_weights_loaded_into_v2_process")
        ),
        "model_weights_loaded_scope": checkpoint_evidence.get(
            "model_weights_loaded_scope"
        ),
        "weight_deserialization_performed": bool(
            checkpoint_evidence.get("weight_deserialization_performed", False)
        ),
        "pickle_deserialized": bool(
            checkpoint_evidence.get("pickle_deserialized", False)
        ),
    }


def run_once(symbols: tuple[str, ...], timeframe: str) -> dict:
    started = _utc_iso()
    from v2.backend.app.services.rl_core.trainer_output import (
        emit_trainer_output, validate_for_paper_fill_gate,
    )
    from v2.backend.app.services.market_state_integrity.trust import TrustGateRejectedError
    r = _connect_redis()
    checkpoint_evidence = _read_checkpoint_evidence(r)
    checkpoint_id = (
        checkpoint_evidence.get("active_checkpoint_id")
        or checkpoint_evidence.get("selected_checkpoint_id")
        or None
    )
    checkpoint_blocker = checkpoint_evidence.get("active_checkpoint_blocker")
    if checkpoint_id is None and not checkpoint_blocker:
        checkpoint_blocker = checkpoint_evidence.get("checkpoint_blocker") or DEFAULT_CHECKPOINT_WEIGHT_STATUS
    checkpoint_weight_status = (
        checkpoint_evidence.get("active_checkpoint_weight_status")
        or checkpoint_evidence.get("checkpoint_weight_status")
        or DEFAULT_CHECKPOINT_WEIGHT_STATUS
    )
    checkpoint_evidence_status = (
        checkpoint_evidence.get("checkpoint_evidence_status")
        or "CHECKPOINT_EVIDENCE_MISSING"
    )
    checkpoint_evidence_model_weights_load_verified = bool(
        checkpoint_evidence.get("native_model_weights_load_verified")
        or checkpoint_evidence.get("model_weights_loaded_into_v2_process")
    )
    trainer_online_mode = (
        checkpoint_evidence.get("trainer_online_mode")
        or "V2_NATIVE_RL_CORE_NO_LEGACY_CHECKPOINT_EVIDENCE"
    )
    keys_written: list[str] = []
    predictions: list[dict] = []
    blocked: list[str] = []
    trust_gate_rejections: list[dict] = []
    open_gate: list[str] = []
    for sym in symbols:
        snap = _read_feature_snapshot(r, sym, timeframe)
        if not snap:
            blocked.append(sym + ":MISSING_FEATURE_SNAPSHOT")
            continue
        try:
            rec = emit_trainer_output(
                snap,
                checkpoint_id=checkpoint_id,
                checkpoint_blocker=checkpoint_blocker,
            )
        except TrustGateRejectedError as exc:
            trust_gate_result = exc.trust_gate_result.to_dict()
            reject_reasons = [
                str(reason)
                for reason in trust_gate_result.get("reject_reasons", [])
            ]
            concise_reason = ",".join(reject_reasons) or str(exc)
            blocked.append(sym + ":TRUST_GATE_REJECTED:" + concise_reason)
            trust_gate_rejections.append(
                {
                    "symbol": sym,
                    "decision_id": exc.decision_id,
                    "message": str(exc),
                    **trust_gate_result,
                }
            )
            continue
        gate = validate_for_paper_fill_gate(rec)
        prediction = {
            "prediction_id": rec.prediction_id,
            "feature_snapshot_id": rec.feature_snapshot_id,
            "symbol": sym,
            "timeframe": timeframe,
            "trainer_source": rec.trainer_source,
            "checkpoint_id": rec.checkpoint_id,
            "checkpoint_blocker": rec.checkpoint_blocker,
            "checkpoint_evidence_status": checkpoint_evidence_status,
            "checkpoint_weight_status": checkpoint_weight_status,
            "trainer_online_mode": trainer_online_mode,
            "production_signal_only": True,
            "routes_to_orchestrator": False,
            "routes_to_risk_gateway": False,
            "trader_execution_enabled": False,
            "model_weights_loaded_into_v2_process": False,
            "rl_core_sidecar_loaded_active_native_checkpoint": False,
            "checkpoint_evidence_model_weights_load_verified": (
                checkpoint_evidence_model_weights_load_verified
            ),
            "active_trainer_checkpoint_id": checkpoint_evidence.get("active_checkpoint_id"),
            "active_trainer_checkpoint_source": checkpoint_evidence.get("active_checkpoint_source"),
            "expected_move_bps": rec.expected_move_bps,
            "expected_move_after_cost_bps": rec.expected_move_after_cost_bps,
            "confidence_raw": rec.confidence_raw,
            "confidence_calibrated": rec.confidence_calibrated,
            "feature_freshness_state": rec.feature_freshness_state,
            "selected_action": rec.selected_action,
            "policy_action_probabilities": list(rec.policy_action_probabilities),
            "hedge_action_classification": rec.hedge_action_classification,
            "paper_fill_gate_status": gate["paper_fill_gate_status"],
            "paper_fill_allowed": gate["paper_fill_allowed"],
            "paper_fill_gate_block_reasons": list(gate["paper_fill_gate_block_reasons"]),
            "generated_utc": rec.generated_utc,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        }
        predictions.append(prediction)
        if gate["paper_fill_allowed"]:
            open_gate.append(sym)
        else:
            blocked.append(sym + ":" + ",".join(gate["paper_fill_gate_block_reasons"]))
        if r is not None:
            sidecar_key = SIDECAR_PREDICTION_KEY_TEMPLATE.format(
                symbol=sym,
                timeframe=timeframe,
            )
            if _safe_write(r, sidecar_key, json.dumps(prediction), ex=600):
                keys_written.append(sidecar_key)
    trainer_learning_truth = _trainer_learning_truth(r)
    if predictions:
        # Never publish an OK trainer status while weight updates cannot be
        # proven fresh — inference health and learning health are different
        # claims (operator rule: TRAINER_INFERENCE_ONLY_NOT_LEARNING).
        if trainer_learning_truth["weights_updating"]:
            classification = "V2_NATIVE_RL_CORE_INFERENCE_SIDECAR_OK_TRAINER_LEARNING"
        else:
            classification = "TRAINER_INFERENCE_ONLY_NOT_LEARNING"
    elif r is None:
        classification = "BLOCKED_BY_REDIS_UNAVAILABLE"
    else:
        # Name the true dominant blocker; a trust-gate rejection must never
        # masquerade as a missing feature snapshot (snapshots can be CURRENT).
        trust_blocked = sum(1 for item in blocked if ":TRUST_GATE_REJECTED" in item)
        snapshot_blocked = sum(1 for item in blocked if ":MISSING_FEATURE_SNAPSHOT" in item)
        if trust_blocked and trust_blocked >= snapshot_blocked:
            classification = "BLOCKED_BY_MARKET_STATE_TRUST_GATE"
        elif snapshot_blocked:
            classification = "BLOCKED_BY_MISSING_FEATURE_SNAPSHOT"
        else:
            classification = "BLOCKED_NO_PREDICTIONS"
    status = {
        "worker_id": "v2_rl_core_inference_loop",
        "schema_version": "v2_rl_core_live_v1",
        "started_at": started,
        "finished_at": _utc_iso(),
        "symbols": list(symbols),
        "timeframe": timeframe,
        "predictions_count": len(predictions),
        "predictions_with_open_gate": open_gate,
        "predictions_blocked": blocked,
        "trust_gate_rejection_count": len(trust_gate_rejections),
        "trust_gate_rejections": trust_gate_rejections,
        "v2_prediction_keys_written": keys_written,
        "v2_prediction_keys_written_count": len(keys_written),
        "classification": classification,
        "role": "inference_sidecar",
        "trainer_weights_updating": trainer_learning_truth["weights_updating"],
        "trainer_online_learning_status": trainer_learning_truth[
            "online_learning_status"
        ],
        "trainer_last_successful_weight_update_at": trainer_learning_truth[
            "last_successful_weight_update_at"
        ],
        "trainer_learning_status_source": trainer_learning_truth["source_key"],
        "trainer_online_mode": trainer_online_mode,
        "production_signal_only": True,
        "market_data_mode": "REALTIME_PUBLIC_MARKET_DATA",
        "routes_to_orchestrator": False,
        "routes_to_risk_gateway": False,
        "trader_execution_enabled": False,
        "checkpoint_weight_status": checkpoint_weight_status,
        "checkpoint_evidence_status": checkpoint_evidence_status,
        "checkpoint_id": checkpoint_id,
        "checkpoint_blocker": checkpoint_blocker,
        "checkpoint_evidence_model_weights_load_verified": (
            checkpoint_evidence_model_weights_load_verified
        ),
        "checkpoint_evidence": _checkpoint_evidence_summary(checkpoint_evidence),
        "hedge_status": "HEDGE_FAIL_CLOSED_PAPER_HEDGE_ENGINE_PENDING_CODEX_PASS",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "writes_primary_prediction_keys": False,
        "primary_prediction_owner": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "sidecar_prediction_namespace": SIDECAR_PREDICTION_KEY_TEMPLATE,
    }
    if r is not None:
        _safe_write(r, f"{V2_REDIS_PREFIX}trainer:status", classification, ex=300)
        _safe_write(r, f"{V2_REDIS_PREFIX}trainer:heartbeat", json.dumps(status), ex=300)
    return status


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _resolve_runtime_symbols(raw_symbols: str | None, *, smoke_test: bool) -> tuple[str, ...]:
    return tuple(
        resolve_symbols(
            explicit=raw_symbols,
            smoke_test=smoke_test,
            include_baseline=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_rl_core_inference_loop")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Explicit comma-separated symbols. Omit for dynamic universe plus 25-symbol baseline.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set; never the default.",
    )
    parser.add_argument("--timeframe", default=DEFAULT_TF)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
            hb = run_once(symbols, args.timeframe)
            write_payload(hb, args.out)
            time.sleep(max(5, int(args.interval_seconds)))
    symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
    hb = run_once(symbols, args.timeframe)
    write_payload(hb, args.out)
    print(json.dumps({
        "classification": hb["classification"],
        "predictions_count": hb["predictions_count"],
        "predictions_with_open_gate": hb["predictions_with_open_gate"],
        "v2_prediction_keys_written_count": hb["v2_prediction_keys_written_count"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
