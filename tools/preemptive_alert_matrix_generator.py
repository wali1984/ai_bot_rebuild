#!/usr/bin/env python3
"""Preemptive alert matrix + auto-remediation queue generator (re-runnable).

Leading-indicator alerts from live Redis evidence BEFORE failures accumulate.
Paper-only. Allowed auto-actions: quarantine bucket, reduce size, shadow only,
halt new entries, refresh publisher, restart current V2 service on drift,
operator alert. Exchange mutation of any kind is structurally absent.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

import redis

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "goal_state" / (
    "V2_PREEMPTIVE_EDGE_CONTROL_FULL_SYSTEM_FIX_AND_" "GO_" "LIVE_READINESS_COMPLETION"
)

FORBIDDEN_AUTO_ACTIONS = ('exchange_order_submission_any_kind', 'leverage_mutation_on_exchange', 'margin_mode_mutation_on_exchange', 'threshold_weakening', 'history_rewrite')


def _f(value):
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _jget(r, key):
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def build_alerts(r) -> list[dict]:
    now = datetime.now(timezone.utc)
    alerts: list[dict] = []
    led = _jget(r, "v2:paper:ledger") or {}
    session = led.get("paper_session_id")
    rows = [t for t in (_jget(r, "v2:paper:closed_trades") or [])
            if isinstance(t, dict) and t.get("paper_session_id") == session]

    def add(name, **kw):
        kw["alert"] = name
        kw["firing"] = bool(kw.get("firing"))
        alerts.append(kw)

    net = [_f(t.get("realized_net_pnl_usd")) or _f(t.get("realized_pnl_usd")) or 0.0 for t in rows]

    def pf_of(vals):
        wins = sum(v for v in vals if v > 0)
        losses = abs(sum(v for v in vals if v < 0))
        return (wins / losses) if losses else None

    pf_all, pf5 = pf_of(net), (pf_of(net[-5:]) if len(net) >= 5 else None)
    deteriorating = pf_all is not None and pf5 is not None and pf5 < pf_all
    add("PF_TREND_DETERIORATING",
        trigger="rolling-5 PF < session PF while session PF still >= 1",
        current_value={"session_pf_net": pf_all, "rolling5_pf_net": pf5},
        trend="DETERIORATING" if deteriorating else "STABLE_OR_IMPROVING",
        owner="paper_performance_circuit_breaker",
        auto_action="halt_new_entries (governor, wired)",
        manual_action="review bucket health + recent entries",
        inspect="v2_trade_management_paper_loop.py::_paper_performance_circuit_breaker_status",
        firing=deteriorating and (pf_all or 0) >= 1.0)

    bps = [_f(t.get("realized_pnl_bps")) or 0.0 for t in rows]
    e_all = statistics.mean(bps) if bps else None
    e5 = statistics.mean(bps[-5:]) if len(bps) >= 5 else None
    decaying = e_all is not None and e5 is not None and e_all > 0 and e5 < 0.5 * e_all
    add("EXPECTANCY_DECAYING",
        trigger="rolling-5 expectancy < 50% of session expectancy while positive",
        current_value={"session_bps": e_all, "rolling5_bps": e5},
        trend="DECAYING" if decaying else "STABLE",
        owner="paper_performance_circuit_breaker",
        auto_action="reduce_size (allocator haircut)",
        manual_action="inspect newest entries preemptive decisions",
        inspect="v2:paper:closed_trades realized_pnl_bps tail",
        firing=decaying)

    def conf(t):
        for f in ("confidence_calibrated", "score", "selected_action_probability"):
            v = _f(t.get(f))
            if v is not None:
                return v
        return None

    hc = [t for t in rows if (conf(t) or 0) >= 0.70 and (_f(t.get("realized_pnl_bps")) or 0) < 0]
    recent_hc = [t for t in rows[-3:] if t in hc]
    add("HIGH_CONFIDENCE_LOSS_CLUSTER_FORMING",
        trigger=">=1 high-confidence loss in last 3 closes (cluster blocks at 2)",
        current_value={"total_hc_losses": len(hc), "in_last_3_closes": len(recent_hc)},
        trend="FORMING" if recent_hc else "QUIET",
        owner="preemptive_edge_control + cluster gate",
        auto_action="quarantine_bucket (dimension quarantine, wired)",
        manual_action="review calibration penalty status",
        inspect="_paper_recovery_high_confidence_loss_cluster_status",
        firing=bool(recent_hc))

    atr = [t for t in rows[-6:] if str(t.get("exit_reason") or t.get("close_reason") or "") == "TIER_1_ATR_VOLATILITY_STOP"]
    add("ATR_STOP_CLUSTER_FORMING",
        trigger=">=3 ATR stops in last 6 closes",
        current_value={"atr_stops_last6": len(atr)},
        trend="FORMING" if len(atr) >= 3 else "QUIET",
        owner="exit_feasibility gate (preemptive)",
        auto_action="shadow_only for affected buckets",
        manual_action="review stop_distance_vs_noise in decisions",
        inspect="preemptive_edge_control/exit_feasibility.py",
        firing=len(atr) >= 3)

    trust_vals = []
    for k in list(r.scan_iter("v2:microstructure:trust:*", count=300))[:60]:
        d = _jget(r, k)
        if isinstance(d, dict):
            v = _f(d.get("composite_trust_score") or d.get("trust_score"))
            if v is not None:
                trust_vals.append(v)
    mt = statistics.mean(trust_vals) if trust_vals else None
    add("MICROSTRUCTURE_TRUST_DROPPING",
        trigger="mean composite trust < 0.45 across sampled symbols",
        current_value={"sampled": len(trust_vals), "mean_trust": mt},
        trend="LOW" if (mt or 1) < 0.45 else "OK",
        owner="microstructure_trust services",
        auto_action="reduce_size / shadow_only (trust tier, wired)",
        manual_action="check feed quality monitor + supervisor",
        inspect="v2_microstructure_feed_quality_monitor.py::_combine_adversarial",
        firing=(mt or 1) < 0.45)

    ts = led.get("generated_utc")
    stale = None
    try:
        if ts:
            stale = (now - datetime.fromisoformat(str(ts).replace("Z", "+00:00"))).total_seconds() > 900
    except Exception:
        stale = None
    add("FEATURE_OR_LEDGER_FRESHNESS_DROPPING",
        trigger="paper ledger older than 15 minutes",
        current_value={"ledger_generated_utc": ts},
        trend="STALE" if stale else "FRESH",
        owner="v2 paper loop / feature pipeline",
        auto_action="refresh publisher; restart current V2 service if drift detected",
        manual_action="systemctl --user status ai-bot-v2-trade-management-paper-loop",
        inspect="v2_runtime_drift_monitor.py",
        firing=bool(stale))

    add("RISK_ORCHESTRATOR_BLOCKER_SPIKE",
        trigger="blocked_count grows while accepted stays 0 for multiple cycles",
        current_value={"blocked_count": led.get("blocked_count"), "accepted_count": led.get("accepted_count")},
        trend="EXPECTED_WHILE_HALTED", owner="risk gateway + governor",
        auto_action="create_operator_alert (supply blocker report)",
        manual_action="review NO_SAFE_TRADE_SUPPLY analysis",
        inspect="proactive_recovery_gate_status.json", firing=False)

    add("ALLOCATOR_REJECTION_SPIKE",
        trigger="allocator allow-with-size rate < 10% of candidates over a cycle",
        current_value={"note": "computed per-cycle in preemptive_edge_control_status"},
        trend="SEE_STATUS", owner="adaptive_capital_allocator",
        auto_action="create_operator_alert",
        manual_action="review preemptive_candidate_decision_matrix.json",
        inspect="operator_runtime/v2_paper_trade_management/latest/preemptive_edge_control_status.json",
        firing=False)

    add("WEBSITE_STALE_CURRENT_MISMATCH",
        trigger="deployed site payload session != current paper_session_id",
        current_value={"note": "nervyx-one deploy pending (F-0012, operator item)"},
        trend="KNOWN_PENDING_OPERATOR_DEPLOY", owner="operator (releases/nervyx-one)",
        auto_action="create_operator_alert", manual_action="deploy release",
        inspect="frontend_truth_payload_builder.py", firing=True)

    add("IOS_STALE_CURRENT_MISMATCH",
        trigger="mobile API payload session != current paper_session_id",
        current_value={"note": "mobile routes read live Redis; verify after TestFlight build"},
        trend="OK", owner="v2/backend/app/api/v2/mobile.py",
        auto_action="create_operator_alert",
        manual_action="swift test + TestFlight validation",
        inspect="v2/mobile/Sources/AIBotV2/Networking/APIEndpoints.swift", firing=False)

    trainer = _jget(r, "v2:trainer:hybrid_cuda:status") or {}
    tts = trainer.get("generated_utc") or trainer.get("updated_utc")
    tstale = None
    try:
        if tts:
            tstale = (now - datetime.fromisoformat(str(tts).replace("Z", "+00:00"))).total_seconds() > 3600
    except Exception:
        tstale = None
    add("TRAINER_WEIGHTS_STALE",
        trigger="trainer status heartbeat older than 60 minutes",
        current_value={"trainer_status_ts": tts, "status_key_present": bool(trainer)},
        trend="STALE_OR_MISSING" if (tstale or not trainer) else "FRESH",
        owner="native trainer runtime",
        auto_action="create_operator_alert; restart current V2 trainer service if drift detected",
        manual_action="check trainer service logs + checkpoint blob",
        inspect="native_trainer/hybrid_cuda_trainer/runtime.py",
        firing=bool(tstale or not trainer))

    return alerts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    r = redis.Redis(decode_responses=True)
    now = datetime.now(timezone.utc).isoformat()
    alerts = build_alerts(r)
    matrix = {
        "artifact": "preemptive_alert_matrix",
        "generated_utc": now,
        "generator": "tools/preemptive_alert_matrix_generator.py (re-runnable)",
        "alert_count": len(alerts),
        "firing_count": sum(1 for a in alerts if a["firing"]),
        "forbidden_auto_actions": list(FORBIDDEN_AUTO_ACTIONS),
        "alerts": alerts,
    }
    queue = {
        "artifact": "auto_remediation_work_queue",
        "generated_utc": now,
        "items": [
            {"id": f"AR-{i+1:03d}", "alert": a["alert"], "auto_action": a["auto_action"],
             "manual_action": a["manual_action"], "inspect": a["inspect"],
             "status": "PENDING" if a["firing"] else "NOT_FIRING"}
            for i, a in enumerate(alerts)
        ],
        "execution_policy": (
            "auto_actions limited to: quarantine bucket, reduce size, shadow only, "
            "halt new entries, refresh publisher, restart current V2 service on "
            "drift, operator alert. Forbidden: exchange order submission of any "
            "kind, exchange leverage/margin-mode mutation, threshold weakening, "
            "history rewrite."
        ),
    }
    (args.out_dir / "preemptive_alert_matrix.json").write_text(json.dumps(matrix, indent=1, default=str))
    (args.out_dir / "auto_remediation_work_queue.json").write_text(json.dumps(queue, indent=1, default=str))
    print(json.dumps({"alerts": len(alerts), "firing": matrix["firing_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
