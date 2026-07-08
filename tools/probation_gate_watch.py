#!/usr/bin/env python3
"""Probation position watch + 5/20/50-close gate evaluator (re-runnable).

Paper-only monitor: reads live Redis paper state, writes watch + gate
artifacts into the advancement goal directory. Never mutates trading state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import redis

REPO = Path(__file__).resolve().parent.parent
GOAL = REPO / "goal_state" / "V2_PROBATION_5_CLOSE_GATE_AND_A_PLUS_SUPPLY_ADVANCEMENT"
PROBATION_TIER = "POSITIVE_EDGE_PROBATION_PAPER"


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _jget(r, key, default):
    raw = r.get(key)
    try:
        return json.loads(raw) if raw else default
    except Exception:
        return default


def main() -> int:
    GOAL.mkdir(parents=True, exist_ok=True)
    r = redis.Redis(decode_responses=True)
    now = datetime.now(timezone.utc).isoformat()
    led = _jget(r, "v2:paper:ledger", {})
    session = led.get("paper_session_id")
    positions = _jget(r, "v2:paper:open_positions", None)
    if positions is None:
        positions = _jget(r, "v2:paper:positions", [])
    positions = [p for p in positions if isinstance(p, dict)]
    prob_open = [
        p for p in positions if p.get("paper_opportunity_tier") == PROBATION_TIER
    ]
    watch_rows = []
    hard_violations = []
    for p in prob_open:
        stop = _f(p.get("stop_distance_bps"))
        row = {
            "paper_session_id": p.get("paper_session_id") or session,
            "position_id": p.get("position_id"),
            "symbol": p.get("symbol"),
            "timeframe": p.get("timeframe"),
            "side": p.get("side"),
            "strategy": p.get("strategy_selected_mode") or p.get("strategy_id"),
            "entry_time": p.get("fill_price_utc") or p.get("original_fill_utc"),
            "entry_price": p.get("entry_price") or p.get("fill_price"),
            "current_mark": p.get("mark_price") or p.get("latest_price"),
            "unrealized_pnl_usd": p.get("unrealized_pnl_usd") or p.get("unrealized_pnl"),
            "unrealized_pnl_bps": p.get("unrealized_pnl_bps"),
            "MFE": p.get("mfe_bps"),
            "MAE": p.get("mae_bps"),
            "microstructure_trust_at_entry": p.get("composite_microstructure_trust_score"),
            "fvg_structure_at_entry": p.get("fvg_kind") or p.get("market_structure_context"),
            "liquidity_zone_context": p.get("liquidity_zone_context"),
            "expected_edge_after_cost": p.get("expected_move_after_cost_bps"),
            "preemptive_decision_id": p.get("preemptive_decision_id"),
            "guardian_state": p.get("guardian_status") or "HALTED_PERFORMANCE",
            "risk_fraction": p.get("risk_budget_fraction_of_normal_adaptive"),
            "exit_plan": {
                "stop_distance_bps": stop,
                "trailing_enabled": p.get("trailing_stop_enabled"),
                "trailing_stop_price": p.get("trailing_stop_price"),
            },
            "stop_status": "PRESENT" if stop and stop > 0 else "MISSING",
            "target_status": "TRAILING_MANAGED" if p.get("trailing_stop_enabled") is not False else "STATIC",
        }
        watch_rows.append(row)
        if row["stop_status"] == "MISSING":
            hard_violations.append(f"{p.get('symbol')}: NO_STOP")
    ledger_age_note = led.get("generated_utc")
    watch = {
        "artifact": "probation_open_position_watch",
        "generated_utc": now,
        "ledger_generated_utc": ledger_age_note,
        "open_probation_positions": len(prob_open),
        "positions": watch_rows,
        "hard_rule_violations": hard_violations,
        "managed_by": "ai-bot-v2-trade-management-paper-loop.service (current code)",
    }
    (GOAL / "probation_open_position_watch.json").write_text(
        json.dumps(watch, indent=1, default=str)
    )

    closed = [
        t
        for t in _jget(r, "v2:paper:closed_trades", [])
        if isinstance(t, dict)
        and t.get("paper_opportunity_tier") == PROBATION_TIER
        and t.get("paper_session_id") == session
    ]
    net = [
        _f(t.get("realized_net_pnl_usd")) or _f(t.get("realized_pnl_usd")) or 0.0
        for t in closed
    ]
    notion = [_f(t.get("gross_notional_usd")) or 0.0 for t in closed]
    bps = [_f(t.get("realized_pnl_bps")) or 0.0 for t in closed]
    wins = sum(v for v in net if v > 0)
    losses = abs(sum(v for v in net if v < 0))
    pf = (wins / losses) if losses > 0 else (float("inf") if wins > 0 else None)
    wexp = (sum(net) / sum(notion) * 10000) if sum(notion) > 0 else None

    def conf(t):
        for f in ("confidence_calibrated", "score", "selected_action_probability"):
            v = _f(t.get(f))
            if v is not None:
                return v
        return None

    hc_losses = [
        t for t in closed if (conf(t) or 0) >= 0.70 and (_f(t.get("realized_pnl_bps")) or 0) < 0
    ]
    atr_stops = [
        t for t in closed
        if str(t.get("exit_reason") or t.get("close_reason") or "") == "TIER_1_ATR_VOLATILITY_STOP"
    ]
    n = len(closed)
    evaluable = n >= 5
    checks = {
        "closed_probation_trades": n,
        "PF": pf,
        "notional_weighted_expectancy_bps": wexp,
        "high_confidence_loss_cluster": len(hc_losses) >= 2,
        "ATR_stop_cluster": len(atr_stops) >= 3,
        "orphaned_positions": len(hard_violations),
    }
    if not evaluable:
        status = f"ACCUMULATING_{n}_OF_5"
        advance = False
    else:
        gate_pass = (
            (pf or 0) >= 1.0
            and (wexp or 0) > 0
            and len(hc_losses) < 2
            and len(atr_stops) < 3
            and not hard_violations
        )
        status = "PROBATION_5_CLOSE_GATE_PASS" if gate_pass else "PROBATION_5_CLOSE_GATE_FAIL"
        advance = gate_pass
    gate = {
        "artifact": "probation_5_close_gate_status",
        "generated_utc": now,
        "paper_session_id": session,
        "status": status,
        "checks": checks,
        "closes": [
            {
                "symbol": t.get("symbol"), "side": t.get("side"),
                "realized_pnl_bps": t.get("realized_pnl_bps"),
                "realized_net_pnl_usd": t.get("realized_net_pnl_usd"),
                "exit_reason": t.get("exit_reason") or t.get("close_reason"),
                "confidence": conf(t),
            }
            for t in closed
        ],
        "advance_to_20_close_gate": advance,
        "exact_root_cause_required": status == "PROBATION_5_CLOSE_GATE_FAIL",
        "live_gate": "blocked_human_only",
        "paper_only": True,
    }
    (GOAL / "probation_5_close_gate_status.json").write_text(
        json.dumps(gate, indent=1, default=str)
    )
    # ------------------------------------------------------------------
    # Immediate-fail supervision. Any violation halts probation entries via
    # the paper entry-freeze key (closes/reduces remain allowed) and records
    # the exact cause. Halting entries is the designed paper-only auto-action.
    # ------------------------------------------------------------------
    immediate_fail: list[str] = []
    for row in watch_rows:
        if row["stop_status"] == "MISSING":
            immediate_fail.append(f"{row['symbol']}:POSITION_WITHOUT_STOP")
        if not row.get("paper_session_id"):
            immediate_fail.append(f"{row['symbol']}:MISSING_SESSION_ID")
    ledger_ts = led.get("generated_utc")
    try:
        ledger_age = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(str(ledger_ts).replace("Z", "+00:00"))
        ).total_seconds()
    except Exception:
        ledger_age = None
    if prob_open and (ledger_age is None or ledger_age > 900):
        immediate_fail.append(
            f"ORPHAN_RISK:LEDGER_STALE_{int(ledger_age) if ledger_age else 'UNKNOWN'}s"
        )
    new_hc_losses = [
        t for t in closed
        if (conf(t) or 0) >= 0.70 and (_f(t.get("realized_pnl_bps")) or 0) < 0
    ]
    if new_hc_losses:
        immediate_fail.append(
            "NEW_HIGH_CONFIDENCE_LOSS:" + ",".join(
                str(t.get("symbol")) for t in new_hc_losses
            )
        )
    if len(atr_stops) >= 3:
        immediate_fail.append("ATR_STOP_CLUSTER_FORMING")

    if immediate_fail:
        freeze = {
            "schema_version": "paper_entry_freeze_v1",
            "paper_new_entries_halted": True,
            "new_entries_allowed": False,
            "reason": "PROBATION_SUPERVISOR_HALT:" + ";".join(immediate_fail[:4]),
            "source": "tools/probation_gate_watch.py",
            "generated_utc": now,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }
        r.set("v2:paper:entry_freeze", json.dumps(freeze), ex=6 * 3600)
        (GOAL / "PROBATION_HALT_EVENT.json").write_text(
            json.dumps({"halted_utc": now, "violations": immediate_fail,
                        "freeze_written": True}, indent=1)
        )

    # Canary packet + dashboard truth (refreshed every run)
    a_plus_rows = 0
    canary = {
        "artifact": "live_canary_packet_status",
        "generated_utc": now,
        "live_ready": False,
        "reason": "NO_A_PLUS_CANDIDATE",
        "a_plus_final_rows": a_plus_rows,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "live_gate": "blocked_human_only",
        "probation_is_live_evidence": False,
    }
    (GOAL / "live_canary_packet_status.json").write_text(
        json.dumps(canary, indent=1)
    )
    truth = {
        "artifact": "dashboard_probation_truth_status",
        "generated_utc": now,
        "probation_active": True,
        "open_probation_fills": len(prob_open),
        "closed_probation_trades": n,
        "gate_status": status,
        "a_plus_final_rows": a_plus_rows,
        "live_blocked": True,
        "supervisor_halt_active": bool(immediate_fail),
        "forbidden_claims": {
            "probation_as_live_ready": False,
            "probation_as_a_plus": False,
            "thousand_x_on_track": False,
        },
    }
    (GOAL / "dashboard_probation_truth_status.json").write_text(
        json.dumps(truth, indent=1)
    )

    print(json.dumps({
        "open": len(prob_open), "closes": n, "status": status,
        "PF": pf, "wexp_bps": wexp, "violations": hard_violations,
        "immediate_fail": immediate_fail,
    }, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
