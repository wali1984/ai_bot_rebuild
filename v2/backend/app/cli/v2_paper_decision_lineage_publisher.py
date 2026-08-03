"""V2 paper decision lineage publisher — aggregates paper decision lineage from
Redis (predictions -> proposals -> arbitration -> risk -> paper fill gate)
and writes a structured public JSON payload for the frontend.

Writes V2 namespace ONLY. No legacy Redis writes. No exchange mutation.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2_REDIS_PREFIX = "v2:"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAYLOAD_PATH = REPO_ROOT / (
    "v2/frontend/public/operator_runtime/v2_paper_decision_lineage/latest/v2_paper_decision_lineage.json"
)


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


def _get_json(r, key: str):
    try:
        raw = r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _scan_keys(r, pattern: str, cap: int = 5000) -> list:
    """Bounded cursor SCAN (never blocking KEYS) on the shared ~634K-key store."""
    keys: list = []
    try:
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor=cursor, match=pattern, count=1000)
            keys.extend(batch)
            if cursor == 0 or len(keys) >= cap:
                break
    except Exception:
        return keys
    return keys


def run_once() -> dict:
    r = _connect_redis()

    # Collect prediction keys (bounded SCAN + one pipelined TTL batch)
    prediction_keys = _scan_keys(r, f"{V2_REDIS_PREFIX}prediction:*:1m") if r else []
    prediction_count = len(prediction_keys)
    fresh_prediction_keys = []
    if r and prediction_keys:
        _pipe = r.pipeline()
        for _k in prediction_keys:
            _pipe.ttl(_k)
        fresh_prediction_keys = [k for k, ttl in zip(prediction_keys, _pipe.execute()) if (ttl or 0) > 0]

    # Sample predictions
    sample_predictions: list[dict] = []
    for k in sorted(fresh_prediction_keys)[:5]:
        try:
            raw = r.get(k) if r else None
            if raw:
                d = json.loads(raw)
                sample_predictions.append({
                    "symbol": d.get("symbol") or k.split(":")[2],
                    "timeframe": d.get("timeframe", "1m"),
                    "trainer_source": d.get("trainer_source"),
                    "checkpoint": d.get("checkpoint"),
                    "paper_fill_gate": d.get("paper_fill_gate"),
                    "routes_to_orchestrator": d.get("routes_to_orchestrator"),
                    "routes_to_risk_gateway": d.get("routes_to_risk_gateway"),
                    "trader_execution_enabled": d.get("trader_execution_enabled"),
                    "weights_loaded": d.get("weights_loaded"),
                })
        except Exception:
            continue

    # Orchestrator decisions
    orch_proposals = _get_json(r, f"{V2_REDIS_PREFIX}orchestrator:proposals") if r else None
    orch_decisions = _get_json(r, f"{V2_REDIS_PREFIX}orchestrator:decisions") if r else None
    orch_hb = _get_json(r, f"{V2_REDIS_PREFIX}orchestrator:heartbeat") if r else None

    # Risk gateway
    risk_decisions = _get_json(r, f"{V2_REDIS_PREFIX}risk:decisions") if r else None
    risk_gw = _get_json(r, f"{V2_REDIS_PREFIX}risk:gateway:status") if r else None

    # Paper ledger
    paper_ledger = _get_json(r, f"{V2_REDIS_PREFIX}paper:ledger") if r else None
    paper_signals = _get_json(r, f"{V2_REDIS_PREFIX}signals:paper") if r else None

    # Shadow outcomes
    shadow_outcome_keys = _scan_keys(r, f"{V2_REDIS_PREFIX}paper:shadow_outcome:*") if r else []

    lineage_pipeline = {
        "step_1_trainer_predictions": {
            "total_keys": prediction_count,
            "fresh_keys": len(fresh_prediction_keys),
            "status": "LIVE" if fresh_prediction_keys else "STALE",
            "sample": sample_predictions[:3],
        },
        "step_2_orchestrator_arbitration": {
            "proposals_present": bool(orch_proposals),
            "decisions_present": bool(orch_decisions),
            "predictions_seen": (orch_hb or {}).get("predictions_seen") if isinstance(orch_hb, dict) else None,
            "proposals_arbitrated": (orch_hb or {}).get("proposals_arbitrated") if isinstance(orch_hb, dict) else None,
            "held_by_gate": (orch_hb or {}).get("held_by_gate") if isinstance(orch_hb, dict) else None,
            "classification": (orch_hb or {}).get("classification") if isinstance(orch_hb, dict) else None,
        },
        "step_3_risk_gateway": {
            "decisions_present": bool(risk_decisions),
            "decisions_processed": (risk_gw or {}).get("decisions_processed_total") if isinstance(risk_gw, dict) else None,
            "latest_decision": (risk_gw or {}).get("latest") if isinstance(risk_gw, dict) else None,
            "places_real_order": (risk_gw or {}).get("places_real_order") if isinstance(risk_gw, dict) else False,
            "exchange_action_taken": (risk_gw or {}).get("exchange_action_taken") if isinstance(risk_gw, dict) else False,
        },
        "step_4_paper_fill_gate": {
            "paper_ledger_present": bool(paper_ledger),
            "accepted_count": (paper_ledger or {}).get("accepted_count", 0) if isinstance(paper_ledger, dict) else 0,
            "blocked_count": (paper_ledger or {}).get("blocked_count", 0) if isinstance(paper_ledger, dict) else 0,
            "held_by_paper_fill_gate_count": (paper_ledger or {}).get("held_by_paper_fill_gate_count", 0) if isinstance(paper_ledger, dict) else 0,
            "shadow_observation_count": (paper_ledger or {}).get("shadow_observation_count", 0) if isinstance(paper_ledger, dict) else 0,
        },
        "step_5_signals_and_outcomes": {
            "signals_present": bool(paper_signals),
            "signals_count": len(paper_signals) if isinstance(paper_signals, list) else 0,
            "shadow_outcome_symbols": len(shadow_outcome_keys),
            "sample_signals": (paper_signals or [])[:2] if isinstance(paper_signals, list) else [],
        },
    }

    # Compute lineage health
    steps_live = sum([
        bool(fresh_prediction_keys),
        bool(orch_hb),
        bool(risk_gw or risk_decisions),
        bool(paper_ledger),
    ])
    classification = (
        "PAPER_LINEAGE_FULL" if steps_live == 4
        else (f"PAPER_LINEAGE_PARTIAL_{steps_live}_OF_4" if steps_live >= 2
              else "PAPER_LINEAGE_DEGRADED")
    )

    return {
        "schema_version": "v2_paper_decision_lineage_v1",
        "worker_id": "v2_paper_decision_lineage_publisher",
        "generated_utc": _utc_iso(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "places_real_orders": False,
        "exchange_action_taken": False,
        "classification": classification,
        "steps_live": steps_live,
        "total_steps": 4,
        "lineage_pipeline": lineage_pipeline,
    }


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_paper_decision_lineage_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            # Never let one bad cycle crash the loop (Restart=always churn).
            try:
                payload = run_once()
                write_payload(payload, args.out)
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"error": "run_once_failed", "detail": str(exc)[:200]}))
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    print(json.dumps({
        "classification": payload["classification"],
        "steps_live": payload["steps_live"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
