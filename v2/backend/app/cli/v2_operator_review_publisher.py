"""V2 native codex/operator review status publisher.

Aggregates operator decisions, standing approvals, orchestrator proposals,
risk gateway decisions, and paper fill gate state into a single operator
decisions payload.

Writes:
  v2:operator:review:status  (TTL=600s)
  v2/frontend/public/operator_runtime/v2_operator_review/latest/
    v2_operator_review_status.json

No live trading, no order placement, no old Redis writes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

V2_REDIS_PREFIX = "v2:"
TTL_S = 600
PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_operator_review/latest/"
    "v2_operator_review_status.json"
)
APPROVALS_DIR = Path("claude_worklog/approvals")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        r.ping()
        return r
    except Exception:
        return None


def _load_approvals() -> list[dict]:
    """Load standing approval files from worklog/approvals/."""
    approvals = []
    if not APPROVALS_DIR.exists():
        return approvals
    for p in sorted(APPROVALS_DIR.glob("*.md")):
        approvals.append({
            "filename": p.name,
            "scope": p.stem.replace("_", " ").replace("-", " "),
            "type": (
                "STANDING_APPROVAL" if "STANDING" in p.name.upper()
                else "OPERATOR_ACCEPT" if "ACCEPT" in p.name.upper()
                else "APPROVAL_REQUEST" if "REQUEST" in p.name.upper()
                else "APPROVED"
            ),
        })
    return approvals


def _safe_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def run_once(write_redis: bool = True) -> dict:
    r = _connect_redis()
    now_utc = _utc_iso()

    approvals = _load_approvals()

    orchestrator_hb = None
    orchestrator_proposals: list[dict] = []
    risk_latest = None
    risk_decisions: list[dict] = []
    paper_ledger = None
    paper_intents: list[dict] = []

    if r:
        orchestrator_hb = _safe_json(r.get("v2:orchestrator:heartbeat"))
        raw_proposals = _safe_json(r.get("v2:orchestrator:proposals"))
        if isinstance(raw_proposals, list):
            orchestrator_proposals = raw_proposals[:5]

        risk_latest = _safe_json(r.get("v2:risk:gateway:latest"))
        raw_risk = _safe_json(r.get("v2:risk:gateway:decisions"))
        if isinstance(raw_risk, list):
            risk_decisions = raw_risk[:5]

        paper_ledger = _safe_json(r.get("v2:paper:ledger"))
        raw_intents = _safe_json(r.get("v2:paper:intents"))
        if isinstance(raw_intents, list):
            paper_intents = raw_intents[:5]

    # Determine current decisions state
    predictions_seen = orchestrator_hb.get("predictions_seen", 0) if orchestrator_hb else 0
    proposals_arbitrated = orchestrator_hb.get("proposals_arbitrated", 0) if orchestrator_hb else 0
    held_count = orchestrator_hb.get("predictions_held_by_paper_fill_gate", 0) if orchestrator_hb else 0

    accepted_count = paper_ledger.get("accepted_count", 0) if paper_ledger else 0
    blocked_count = paper_ledger.get("blocked_count", 0) if paper_ledger else 0

    latest_risk_action = risk_latest.get("risk_action", "unknown") if risk_latest else "no_risk_data"
    live_blocked = risk_latest.get("live_blocked", True) if risk_latest else True

    classification = (
        "OPERATOR_REVIEW_OK" if r and orchestrator_hb
        else "OPERATOR_REVIEW_NO_DATA"
    )

    payload = {
        "schema_version": "v2_native_operator_review_v1",
        "classification": classification,
        "generated_utc": now_utc,
        # Live gate / safety state
        "live_gate_status": "blocked_human_only",
        "trader_execution_enabled": False,
        "live_symbols": [],
        # Standing approvals
        "standing_approvals": approvals,
        "standing_approval_count": len(approvals),
        # Orchestrator
        "orchestrator": {
            "worker_id": orchestrator_hb.get("worker_id") if orchestrator_hb else None,
            "predictions_seen": predictions_seen,
            "proposals_arbitrated": proposals_arbitrated,
            "predictions_held_by_paper_fill_gate": held_count,
            "started_at": orchestrator_hb.get("started_at") if orchestrator_hb else None,
            "finished_at": orchestrator_hb.get("finished_at") if orchestrator_hb else None,
        },
        "recent_proposals": orchestrator_proposals,
        # Risk Gateway
        "risk_gateway": {
            "latest_decision_id": risk_latest.get("decision_id") if risk_latest else None,
            "latest_risk_action": latest_risk_action,
            "live_blocked": live_blocked,
            "input_action": risk_latest.get("input_decision_action") if risk_latest else None,
            "reason_code": risk_latest.get("input_decision_reason_code") if risk_latest else None,
        },
        "recent_risk_decisions": risk_decisions,
        # Paper fill gate
        "paper_fill_gate": {
            "accepted_count": accepted_count,
            "blocked_count": blocked_count,
            "held_by_paper_fill_gate_count": held_count,
            "shadow_observation_count": paper_ledger.get("shadow_observation_count", 0) if paper_ledger else 0,
        },
        "recent_paper_intents": paper_intents,
        "live_safety": {
            "live_gate_status": "blocked_human_only",
            "live_symbols": [],
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }

    if write_redis and r:
        try:
            r.setex(
                f"{V2_REDIS_PREFIX}operator:review:status",
                TTL_S,
                json.dumps(payload),
            )
        except Exception as exc:
            payload["redis_write_error"] = str(exc)

    PAYLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAYLOAD_PATH.write_text(json.dumps(payload, indent=2))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 operator review status publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args()

    write_redis = not args.no_redis

    if args.loop:
        while True:
            try:
                result = run_once(write_redis=write_redis)
                print(
                    f"v2_operator_review_written classification={result['classification']}"
                    f" approvals={result['standing_approval_count']}"
                    f" proposals_seen={result['orchestrator']['predictions_seen']}"
                    f" risk_action={result['risk_gateway']['latest_risk_action']}"
                )
            except Exception as exc:
                print(f"v2_operator_review_error: {exc}", file=sys.stderr)
            time.sleep(args.interval_seconds)
    else:
        result = run_once(write_redis=write_redis)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
