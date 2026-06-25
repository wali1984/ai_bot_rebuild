"""V2 paper shadow-outcome metrics CLI (paper/shadow only).

Bounded one-shot (or --loop) tool that reads V2-owned shadow and
held-by-gate rows, computes no-trade outcome metrics (missed move,
missed move after cost, direction consistency, no-trade-correct vs
false-block classification), and writes per-symbol outcome rows under
``v2:paper:shadow_outcome:{symbol}`` plus a heartbeat at
``v2:paper:shadow_outcome:heartbeat``.

NEVER places, cancels, or modifies any exchange entry. NEVER changes
leverage or margin. NEVER writes old Redis keys. NEVER opens the
strict paper-fill gate. NEVER counts a shadow row as an accepted
position or a fill. NEVER affects the PnL ledger. NEVER imports
torch. NEVER deserializes pickle.

Allowed Redis writes:
- ``v2:paper:shadow_outcome:{symbol}``
- ``v2:paper:shadow_outcome:heartbeat``
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from v2.backend.app.services.paper_shadow_outcome_metrics.service import (
    LABEL_HELD,
    LABEL_SHADOW,
    ShadowOutcome,
    build_heartbeat_payload,
    build_shadow_outcome,
    build_shadow_outcome_summary,
    write_heartbeat_to_redis,
    write_outcome_to_redis,
)

V2_REDIS_PREFIX = "v2:"
GO_READY = "V2_SHADOW_OBSERVATION_OUTCOME_METRICS_READY"
GO_BLOCKED = "V2_SHADOW_OBSERVATION_OUTCOME_METRICS_BLOCKED"

WORKLOG_STATUS = Path(
    "claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics/latest/shadow_outcome_metrics_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_shadow_observation_outcome_metrics/latest/operator_dashboard_payload.json"
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _connect_redis():
    try:
        import redis  # type: ignore

        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _read_json_list(r, key: str) -> list[dict]:
    if r is None:
        return []
    try:
        raw = r.get(key)
    except Exception:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def _read_json_dict(r, key: str) -> dict:
    if r is None:
        return {}
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _prediction_for_symbol(r, symbol: str) -> dict | None:
    if r is None:
        return None
    try:
        raw = r.get(f"{V2_REDIS_PREFIX}prediction:{symbol}:1m")
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _collect_shadow_rows(r) -> list[dict]:
    rows = _read_json_list(r, f"{V2_REDIS_PREFIX}paper:shadow_observations")
    return [row for row in rows if (row.get("decision") or "") == "SHADOW_OBSERVATION_ONLY"]


def _collect_held_rows(r) -> list[dict]:
    return _read_json_list(r, f"{V2_REDIS_PREFIX}paper:intents_held_by_paper_fill_gate")


def _outcome_from_shadow_row(r, row: dict) -> ShadowOutcome:
    block_reason = (
        row.get("shadow_observation_reason")
        or row.get("paper_fill_block_reason")
        or row.get("paper_opportunity_tier_reason")
        or "UPSTREAM_PAPER_FILL_GATE_DENIED"
    )
    return build_shadow_outcome(
        redis_client=r,
        symbol=str(row.get("symbol") or ""),
        side=row.get("side"),
        decision_label=LABEL_SHADOW,
        block_reason=str(block_reason),
        shadow_entry_price=row.get("entry_price"),
        shadow_entry_price_source=row.get("entry_price_source"),
        shadow_entry_price_utc=row.get("entry_price_utc"),
        prediction=_prediction_for_symbol(r, str(row.get("symbol") or "")),
    )


def _outcome_from_held_row(r, row: dict) -> ShadowOutcome:
    reasons = row.get("paper_fill_gate_block_reasons") or []
    block_reason = (
        ";".join(str(x) for x in reasons) if reasons else (row.get("paper_fill_gate_status") or None)
    )
    return build_shadow_outcome(
        redis_client=r,
        symbol=str(row.get("symbol") or ""),
        side=row.get("selected_action_upstream"),
        decision_label=LABEL_HELD,
        block_reason=block_reason,
        shadow_entry_price=row.get("entry_price"),
        shadow_entry_price_source=row.get("entry_price_source"),
        shadow_entry_price_utc=row.get("entry_price_utc"),
        prediction=_prediction_for_symbol(r, str(row.get("symbol") or "")),
    )


def _build_status_payload(outcomes: list[ShadowOutcome]) -> dict:
    summary = build_shadow_outcome_summary(outcomes)
    return {
        "schema_version": "v2_shadow_observation_outcome_metrics_status_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": GO_READY,
        "outcome_count": len(outcomes),
        "shadow_horizon_ready_count": summary["horizon_ready_count"],
        "shadow_horizon_pending_count": summary["horizon_pending_count"],
        "classified_shadow_outcome_count": summary["classified_outcome_count"],
        "shadow_no_trade_correct_count": summary["no_trade_correct_count"],
        "shadow_false_block_candidate_count": summary["false_block_candidate_count"],
        "shadow_neutral_or_inside_threshold_count": summary[
            "neutral_or_inside_threshold_count"
        ],
        "shadow_unclassified_outcome_count": summary["unclassified_outcome_count"],
        "shadow_no_trade_correct_rate": summary["no_trade_correct_rate"],
        "shadow_false_block_candidate_rate": summary["false_block_candidate_rate"],
        "shadow_outcome_summary": summary,
        "outcomes": [o.as_payload() for o in outcomes],
        "allowed_redis_writes": [
            "v2:paper:shadow_outcome:{symbol}",
            "v2:paper:shadow_outcome:heartbeat",
        ],
        "counted_as_accepted_position": False,
        "counted_as_fill": False,
        "affects_pnl_ledger": False,
        "opens_paper_fill_gate": False,
        "no_synthetic_price": True,
        "no_legacy_redis_read": True,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "approves_real": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def _write_status_files(payload: dict, worklog: Path, publics: Iterable[Path]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    worklog.parent.mkdir(parents=True, exist_ok=True)
    worklog.write_text(body, encoding="utf-8")
    for p in publics:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def run_once(
    redis_client=None,
    *,
    out_worklog: Path | None = None,
    out_public: Path | None = None,
) -> dict:
    r = redis_client if redis_client is not None else _connect_redis()
    shadow_rows = _collect_shadow_rows(r)
    held_rows = _collect_held_rows(r)
    outcomes: list[ShadowOutcome] = []
    for row in shadow_rows:
        outcomes.append(_outcome_from_shadow_row(r, row))
    for row in held_rows:
        outcomes.append(_outcome_from_held_row(r, row))
    for outcome in outcomes:
        write_outcome_to_redis(r, outcome)
    heartbeat = build_heartbeat_payload(outcomes=outcomes)
    write_heartbeat_to_redis(r, heartbeat)
    payload = _build_status_payload(outcomes)
    if out_worklog is not None:
        _write_status_files(
            payload,
            out_worklog,
            (out_public,) if out_public is not None else (),
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_paper_shadow_outcome_metrics")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out-worklog", type=Path, default=WORKLOG_STATUS)
    parser.add_argument("--out-public", type=Path, default=PUBLIC_DASHBOARD)
    args = parser.parse_args(argv)
    if args.once == args.loop:
        args.once = True
        args.loop = False
    if args.once:
        payload = run_once(out_worklog=args.out_worklog, out_public=args.out_public)
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "outcome_count": payload["outcome_count"],
                    "counted_as_accepted_position": payload["counted_as_accepted_position"],
                    "affects_pnl_ledger": payload["affects_pnl_ledger"],
                    "writes_legacy_redis": payload["writes_legacy_redis"],
                    "writes_exchange_orders": payload["writes_exchange_orders"],
                },
                sort_keys=True,
            )
        )
        return 0
    # --loop: run on a fixed cadence until interrupted.
    while True:
        run_once(out_worklog=args.out_worklog, out_public=args.out_public)
        try:
            time.sleep(max(5, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
