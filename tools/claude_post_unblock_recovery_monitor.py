#!/usr/bin/env python3
"""
CLAUDE_GOAL_ID: CLAUDE_POST_DATA_UNRELIABLE_UNBLOCK_RECOVERY_MONITOR

Read-only runtime monitor. No patching. 10-minute interval.
Tracks post-DATA_UNRELIABLE-fix recovery for V2 paper trading.

Trigger rules:
  - 5 new closed trades: auto-run guardian verifier
  - 6 hours with 0 new closed trades: write no-trade supply diagnostic
  - Any regression (DATA_UNRELIABLE back, live gate change, real orders): write regression alert

Usage:
  python3 tools/claude_post_unblock_recovery_monitor.py          # single run
  python3 tools/claude_post_unblock_recovery_monitor.py --daemon # 10-min loop
"""
import json
import os
import pathlib
import subprocess
import sys
import time
import datetime as dt

import redis as redis_lib

BASE = pathlib.Path(__file__).resolve().parent.parent
LIVE_STATUS_PATH = (
    BASE
    / "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest"
    / "v2_trade_management_paper_live_status.json"
)
OUT_DIR = BASE / "claude_worklog"
STATUS_PATH = OUT_DIR / "claude_post_unblock_recovery_monitor_status.json"
REGRESSION_PATH = OUT_DIR / "claude_post_unblock_recovery_regression_alert.json"
REDIS_SNAPSHOT_DIR = OUT_DIR / "post_unblock_redis_snapshots"

# Post-fix baseline: one old SYNUSDT trade existed before the fix.
# New trades start accumulating when closed_trade_count > POST_FIX_BASELINE.
POST_FIX_BASELINE_CLOSED_TRADES = 1
POST_FIX_PID = 2423003
POST_FIX_UTC = "2026-07-03T04:51:32Z"
G13_G14_TRIGGER_THRESHOLD = 5  # New closed trades needed before G13/G14 eval

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
DAEMON_INTERVAL_SECONDS = 600  # 10 minutes
NO_TRADE_DIAGNOSTIC_THRESHOLD_SECONDS = 6 * 3600  # 6 hours
NO_TRADE_DIAGNOSTIC_PATH = OUT_DIR / "claude_post_unblock_no_trade_supply_diagnostic.json"
POST_FIX_EPOCH = dt.datetime(2026, 7, 3, 4, 51, 32, tzinfo=dt.timezone.utc)

REDIS_SNAPSHOT_KEYS = {
    "closed_trades": "v2:paper:closed_trades",
    "heartbeat": "v2:paper:heartbeat",
    "portfolio_state": "v2:portfolio:state",
    "governor_status": "v2:paper:churn_equity_bleed_governor_status",
    "a_grade_gate_burndown": "v2:paper:a_grade_gate_burndown_status",
}


def _redis_client() -> redis_lib.Redis:
    return redis_lib.from_url(REDIS_URL, decode_responses=True)


def _check_pid_alive(pid: int) -> bool:
    return pathlib.Path(f"/proc/{pid}").exists()


def _check_paper_online_runtime_inactive() -> bool:
    result = subprocess.run(
        ["pgrep", "-f", "paper_online_runtime"],
        capture_output=True,
        text=True,
    )
    return result.returncode != 0  # True means no matching process (good)


def _get_live_status() -> dict:
    try:
        return json.loads(LIVE_STATUS_PATH.read_text())
    except Exception as exc:
        return {"_error": str(exc)}


def _get_redis_snapshots() -> dict:
    snapshots: dict[str, object] = {}
    try:
        r = _redis_client()
        for label, key in REDIS_SNAPSHOT_KEYS.items():
            raw = r.get(key)
            if raw is None:
                snapshots[label] = None
                continue
            try:
                snapshots[label] = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                snapshots[label] = raw
    except Exception as exc:
        snapshots["_redis_error"] = str(exc)
    return snapshots


def _run_guardian() -> dict:
    result = subprocess.run(
        ["python3", "scripts/verify_claude_guardian_completion.py"],
        capture_output=True,
        text=True,
        cwd=str(BASE),
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {
            "_raw_stdout": result.stdout[:2000],
            "_stderr": result.stderr[:500],
            "exit_code": result.returncode,
        }


def _build_no_trade_supply_diagnostic(live: dict, now_utc: str, elapsed_hours: float) -> dict:
    """
    Build the no-trade supply diagnostic required when 0 new closed trades after 6h.
    Identifies whether no-trade is legitimate (market conditions) or a pipeline bug.
    """
    admission = live.get("paper_runtime_admission_status", {})
    entry_gate = live.get("paper_audit_entry_gate_status", {})
    a_grade = live.get("paper_a_grade_gate_burndown_status", {})
    bucket_q = live.get("bucket_quarantine_status", {})
    bleed = live.get("paper_bleed_halt_status", {})
    regimes = live.get("strategy_router_regime_counts", {})

    # Aggregate block reasons with category labels
    block_counts: dict = entry_gate.get("block_reason_counts", {})
    cascade_risk_blocks = {k: v for k, v in block_counts.items() if "CASCADE_RISK" in k}
    cascade_no_data_blocks = {k: v for k, v in block_counts.items() if "NO_CASCADE_DATA" in k}
    expected_move_blocks = {k: v for k, v in block_counts.items() if "EXPECTED_MOVE" in k}
    micro_cap_blocks = {k: v for k, v in block_counts.items() if "MICRO_CAP" in k}
    operator_excluded = {k: v for k, v in block_counts.items() if "EXPLICITLY_EXCLUDED" in k}
    other_blocks = {k: v for k, v in block_counts.items()
                    if k not in cascade_risk_blocks and k not in cascade_no_data_blocks
                    and k not in expected_move_blocks and k not in micro_cap_blocks
                    and k not in operator_excluded}

    fill_blocks: dict = admission.get("paper_fill_block_reason_counts", {})

    # Dominant A-grade gate reasons
    a_grade_dominant = a_grade.get("dominant_current_runtime_reasons", {})
    a_grade_gate_status = a_grade.get("guardian_gate_status", {})

    # Unique symbols/TFs from cascade no-data blocks
    cascade_no_data_symbols: set[str] = set()
    cascade_no_data_tfs: set[str] = set()
    for key in cascade_no_data_blocks:
        parts = key.split(":")
        # format: REGIME_GATE_NO_CASCADE_DATA:side:mode:SYMBOL:TF
        if len(parts) >= 5:
            cascade_no_data_symbols.add(parts[3])
            cascade_no_data_tfs.add(parts[4])

    # Was the model producing long/short actions?
    side_counts: dict = admission.get("side_counts", {})
    action_counts: dict = admission.get("action_counts", {})
    model_producing_sides = (side_counts.get("long", 0) + side_counts.get("short", 0)) > 0

    # Classify the supply constraint
    total_cascade_no_data = sum(cascade_no_data_blocks.values())
    total_cascade_risk = sum(cascade_risk_blocks.values())
    total_expected_move = sum(expected_move_blocks.values())

    if total_cascade_no_data > 100:
        primary_constraint = "CASCADE_DATA_ABSENT_FOR_SHORTS"
        constraint_explanation = (
            f"WQ-R29-D2 requires cascade_risk >= 0.30 for SHORT trend entries. "
            f"{total_cascade_no_data} SHORT signals blocked because no cascade liquidation "
            f"data is present in Redis for {len(cascade_no_data_symbols)} symbols. "
            f"This is a data availability issue, not a code bug. "
            f"Cascade data populates from liquidation stream events."
        )
    elif total_expected_move > 50:
        primary_constraint = "MODEL_PREDICTS_ZERO_OR_NEGATIVE_EDGE"
        constraint_explanation = (
            f"{total_expected_move} signals blocked because model predicts 0 or negative "
            f"expected move after cost. Market conditions don't produce positive-edge setups. "
            f"This is legitimate — no code change needed."
        )
    elif total_cascade_risk > 20:
        primary_constraint = "CASCADE_RISK_BELOW_THRESHOLD"
        constraint_explanation = (
            f"{total_cascade_risk} SHORT signals blocked because cascade_risk < 0.30 "
            f"(WQ-R29-D2). Data exists but values are below the liquidation risk threshold."
        )
    else:
        primary_constraint = "MIXED_GATE_CONSTRAINTS"
        constraint_explanation = "Multiple gates each blocking a small number of signals."

    is_legitimate = primary_constraint in {
        "CASCADE_DATA_ABSENT_FOR_SHORTS",
        "MODEL_PREDICTS_ZERO_OR_NEGATIVE_EDGE",
        "CASCADE_RISK_BELOW_THRESHOLD",
    }

    return {
        "goal_id": "CLAUDE_POST_DATA_UNRELIABLE_UNBLOCK_RECOVERY_MONITOR",
        "diagnostic_type": "NO_TRADE_SUPPLY_DIAGNOSTIC",
        "generated_utc": now_utc,
        "elapsed_hours_since_fix": round(elapsed_hours, 2),
        "schema_version": "v1",

        "verdict": "LEGITIMATE_MARKET_GATE_CONSTRAINT" if is_legitimate else "PIPELINE_INVESTIGATION_REQUIRED",
        "primary_constraint": primary_constraint,
        "constraint_explanation": constraint_explanation,
        "patch_required": not is_legitimate,

        "supply_metrics": {
            "trend_signals_evaluating": regimes.get("TREND", 0),
            "intents_built": live.get("intents_built", 0),
            "intents_accepted": live.get("intents_accepted", 0),
            "intents_blocked": live.get("intents_blocked", 0),
            "open_positions": live.get("open_position_count", 0),
            "persistent_accepted_fill_count": admission.get("persistent_accepted_fill_count", 0),
            "shadow_observation_count": admission.get("shadow_observation_count", 0),
            "model_producing_sides": model_producing_sides,
            "side_counts": side_counts,
            "action_counts_missing": action_counts.get("missing", 0),
        },

        "gate_blocks": {
            "fill_gate_blocks": fill_blocks,
            "cost_gate_blocks": {
                k: v for k, v in admission.get("paper_pre_fill_market_evidence_rejection_counts", {}).items()
                if "COST" in k or "SLIPPAGE" in k or "SPREAD" in k
            },
            "temporal_stale_blocks": admission.get("paper_signal_temporal_rejection_counts", {}),
            "risk_gate_blocks": {
                "cascade_risk_below_threshold_count": total_cascade_risk,
                "cascade_no_data_count": total_cascade_no_data,
                "cascade_no_data_symbol_count": len(cascade_no_data_symbols),
                "cascade_no_data_symbols_sample": sorted(cascade_no_data_symbols)[:20],
                "cascade_no_data_timeframes": sorted(cascade_no_data_tfs),
            },
            "model_edge_blocks": {
                "expected_move_non_positive_count": block_counts.get("EXPECTED_MOVE_NON_POSITIVE:0.0bps", 0),
                "expected_move_unfavorable_long_count": sum(
                    v for k, v in expected_move_blocks.items() if "long" in k
                ),
                "expected_move_unfavorable_short_count": sum(
                    v for k, v in expected_move_blocks.items() if "short" in k
                ),
            },
            "micro_cap_blocks": micro_cap_blocks,
            "operator_excluded_blocks": operator_excluded,
            "other_entry_gate_blocks": other_blocks,
        },

        "allocator_blocks": {
            "a_grade_entries_allowed": a_grade_gate_status.get("a_grade_new_entries_allowed", False),
            "a_grade_dominant_reasons": a_grade_dominant,
            "a_grade_failure_count": len(a_grade_gate_status.get("failure_reasons", [])),
            "b_grade_lifecycle_supply_present": a_grade.get("b_grade_lifecycle_supply_present", False),
            "accepted_b_grade_lifecycle_rows": a_grade.get("accepted_b_grade_lifecycle_rows", 0),
            "allocator_pass_rows": a_grade.get("allocator_pass_rows", 0),
            "closest_gap_reason": a_grade.get("closest_gap_reason"),
        },

        "governor_blocks": {
            "quarantined_bucket_count": bucket_q.get("quarantined_bucket_count", 0),
            "blocked_bucket_keys": bucket_q.get("blocked_bucket_keys", []),
            "halt_active": bleed.get("halt_reason") is not None,
            "halt_reason": bleed.get("halt_reason"),
            "new_entries_allowed": bleed.get("new_entries_allowed", False),
        },

        "candidate_coverage": {
            "candidate_symbols_count": entry_gate.get("audit_symbol_block_count", 0),
            "blocked_symbols": entry_gate.get("blocked_symbols", []),
            "allowed_timeframes": entry_gate.get("allowed_entry_timeframes", []),
            "audit_timeframe_block_count": entry_gate.get("audit_timeframe_block_count", 0),
        },

        "regime_distribution": regimes,
        "data_quality_block_count": live.get("strategy_router_data_quality_block_count", 0),

        "safety_gates": {
            "live_gate": live.get("live_gate"),
            "places_real_order": live.get("places_real_order"),
            "approves_live": live.get("approves_live"),
        },

        "action_required": (
            "None — legitimate market/cascade-data constraint. "
            "CASCADE_DATA_ABSENT_FOR_SHORTS will self-resolve as liquidation events populate Redis. "
            "EXPECTED_MOVE_NON_POSITIVE will resolve when model detects market-condition edge. "
            "Do not lower gates. Do not patch. Monitor for 5+ new closed trades."
        ) if is_legitimate else (
            "Investigation required. Identify the pipeline stage where supply is incorrectly blocked."
        ),
    }


def run_once() -> dict:
    now_utc = dt.datetime.utcnow().isoformat() + "Z"
    live = _get_live_status()

    # ── Core safety checks ─────────────────────────────────────────────────
    pid_alive = _check_pid_alive(POST_FIX_PID)
    paper_online_inactive = _check_paper_online_runtime_inactive()

    data_unreliable_blocks = live.get("strategy_router_data_quality_block_count", -1)
    data_unreliable_clear = data_unreliable_blocks == 0

    regime_counts: dict = live.get("strategy_router_regime_counts", {})
    trend_evaluating = regime_counts.get("TREND", 0) > 0

    live_gate: str = live.get("live_gate", "UNKNOWN")
    places_real_order: bool = live.get("places_real_order", True)
    approves_live: bool = live.get("approves_live", True)
    classification: str = live.get("classification", "UNKNOWN")

    intents_accepted: int = live.get("intents_accepted", 0)
    intents_blocked: int = live.get("intents_blocked", 0)
    open_position_count: int = live.get("open_position_count", 0)

    # ── Trade accumulation ──────────────────────────────────────────────────
    total_closed: int = live.get("closed_trade_count", 0)
    new_closed_post_fix: int = max(0, total_closed - POST_FIX_BASELINE_CLOSED_TRADES)
    g13_g14_threshold_met = new_closed_post_fix >= G13_G14_TRIGGER_THRESHOLD

    # ── Guardian (only when threshold met) ─────────────────────────────────
    guardian_triggered = False
    guardian_result = None
    if g13_g14_threshold_met:
        guardian_triggered = True
        guardian_result = _run_guardian()

    # ── Redis snapshots ─────────────────────────────────────────────────────
    redis_snapshots = _get_redis_snapshots()
    REDIS_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_file = REDIS_SNAPSHOT_DIR / f"snapshot_{now_utc.replace(':', '-')}.json"
    snapshot_file.write_text(json.dumps(redis_snapshots, indent=2))

    # ── 6-hour no-trade supply diagnostic ──────────────────────────────────
    now_aware = dt.datetime.now(dt.timezone.utc)
    elapsed_seconds = (now_aware - POST_FIX_EPOCH).total_seconds()
    elapsed_hours = elapsed_seconds / 3600
    no_trade_diagnostic_triggered = (
        elapsed_seconds >= NO_TRADE_DIAGNOSTIC_THRESHOLD_SECONDS
        and new_closed_post_fix == 0
    )
    no_trade_diagnostic: dict | None = None
    if no_trade_diagnostic_triggered:
        no_trade_diagnostic = _build_no_trade_supply_diagnostic(live, now_utc, elapsed_hours)
        NO_TRADE_DIAGNOSTIC_PATH.write_text(json.dumps(no_trade_diagnostic, indent=2))

    # ── Regression detection ────────────────────────────────────────────────
    regressions: list[dict] = []

    if not pid_alive:
        regressions.append({
            "type": "PID_DEAD",
            "severity": "CRITICAL",
            "detail": f"Paper loop PID {POST_FIX_PID} no longer in /proc. Agent supervisor should auto-restart — check new PID.",
            "action": "Identify new PID via agent supervisor log, confirm fixed code still active.",
        })

    if not paper_online_inactive:
        regressions.append({
            "type": "PAPER_ONLINE_RUNTIME_ACTIVE",
            "severity": "HIGH",
            "detail": "paper_online_runtime process is running — duplicate paper entry owner.",
            "action": "Kill paper_online_runtime, confirm v2_trade_management_paper_loop sole owner.",
        })

    if not data_unreliable_clear:
        regressions.append({
            "type": "DATA_UNRELIABLE_REGRESSION",
            "severity": "HIGH",
            "detail": f"strategy_router_data_quality_block_count={data_unreliable_blocks} (expected 0).",
            "action": "Check strategy_router/service.py for revert. Check microstructure monitor deployment.",
            "redis_key": "v2:signals:paper:*",
            "source_file": "v2/backend/app/services/strategy_router/service.py",
        })

    if live_gate != "blocked_human_only":
        regressions.append({
            "type": "LIVE_GATE_CHANGED",
            "severity": "CRITICAL",
            "detail": f"live_gate={live_gate!r} (expected 'blocked_human_only').",
            "action": "Immediately inspect live gate config. Do not proceed until resolved.",
        })

    if places_real_order:
        regressions.append({
            "type": "REAL_ORDER_PATH_ACTIVE",
            "severity": "CRITICAL",
            "detail": "places_real_order=True. This must never be True in paper mode.",
            "action": "Halt. Inspect paper loop for live-mode code path activation.",
        })

    if approves_live:
        regressions.append({
            "type": "APPROVES_LIVE_TRUE",
            "severity": "CRITICAL",
            "detail": "approves_live=True. The paper loop should never approve live trading.",
            "action": "Halt. Inspect live approval gate in paper loop.",
        })

    # ── Build output ────────────────────────────────────────────────────────
    overall_status = (
        "REGRESSION"
        if regressions
        else ("G13_G14_EVAL_TRIGGERED" if guardian_triggered else "OK")
    )

    status = {
        "goal_id": "CLAUDE_POST_DATA_UNRELIABLE_UNBLOCK_RECOVERY_MONITOR",
        "generated_utc": now_utc,
        "schema_version": "v1",
        "overall_status": overall_status,

        "checks": {
            "1_paper_loop_pid_alive": pid_alive,
            "2_paper_online_runtime_inactive": paper_online_inactive,
            "3_data_unreliable_blocks_zero": data_unreliable_clear,
            "4_trend_signals_evaluating": trend_evaluating,
            "5_live_gate_blocked": live_gate == "blocked_human_only",
            "6_places_real_order_false": not places_real_order,
            "7_approves_live_false": not approves_live,
            "8_classification_ok": classification == "V2_TRADE_MANAGEMENT_PAPER_PRODUCTION_OK",
        },

        "metrics": {
            "paper_loop_pid": POST_FIX_PID,
            "data_unreliable_block_count": data_unreliable_blocks,
            "live_gate": live_gate,
            "places_real_order": places_real_order,
            "approves_live": approves_live,
            "classification": classification,
            "intents_accepted": intents_accepted,
            "intents_blocked": intents_blocked,
            "open_position_count": open_position_count,
            "regime_counts": regime_counts,
        },

        "trade_accumulation": {
            "total_closed_trades": total_closed,
            "post_fix_baseline_closed_trades": POST_FIX_BASELINE_CLOSED_TRADES,
            "new_closed_trades_post_fix": new_closed_post_fix,
            "g13_g14_trigger_threshold": G13_G14_TRIGGER_THRESHOLD,
            "g13_g14_threshold_met": g13_g14_threshold_met,
            "recovery_ladder_position": (
                "pre_5" if new_closed_post_fix < 5
                else "pre_50" if new_closed_post_fix < 50
                else "pre_300" if new_closed_post_fix < 300
                else "pre_1000"
            ),
        },

        "guardian": {
            "triggered": guardian_triggered,
            "trigger_reason": f">= {G13_G14_TRIGGER_THRESHOLD} new closed trades" if guardian_triggered else "not yet (< 5 new trades)",
            "result": guardian_result,
        },

        "no_trade_diagnostic": {
            "triggered": no_trade_diagnostic_triggered,
            "elapsed_hours_since_fix": round(elapsed_hours, 2),
            "threshold_hours": NO_TRADE_DIAGNOSTIC_THRESHOLD_SECONDS / 3600,
            "verdict": no_trade_diagnostic.get("verdict") if no_trade_diagnostic else None,
            "primary_constraint": no_trade_diagnostic.get("primary_constraint") if no_trade_diagnostic else None,
            "patch_required": no_trade_diagnostic.get("patch_required") if no_trade_diagnostic else None,
            "file": str(NO_TRADE_DIAGNOSTIC_PATH.relative_to(BASE)) if no_trade_diagnostic_triggered else None,
        },

        "regressions": regressions,
        "regression_count": len(regressions),

        "post_fix_reference": {
            "fix_pid": POST_FIX_PID,
            "fix_utc": POST_FIX_UTC,
            "fix_applied": "BUG_QUALITY_SCORE_OVERSTRICT in strategy_router/service.py:760 removed",
            "baseline_closed_trades": POST_FIX_BASELINE_CLOSED_TRADES,
        },

        "redis_snapshot_file": str(snapshot_file.relative_to(BASE)),
    }

    # Write status
    STATUS_PATH.write_text(json.dumps(status, indent=2))

    # Write regression alert if needed
    if regressions:
        alert = {
            "goal_id": "CLAUDE_POST_DATA_UNRELIABLE_UNBLOCK_RECOVERY_MONITOR",
            "generated_utc": now_utc,
            "severity": "REGRESSION",
            "regression_count": len(regressions),
            "regressions": regressions,
            "live_status_snapshot": {
                k: live.get(k)
                for k in [
                    "strategy_router_data_quality_block_count",
                    "live_gate",
                    "places_real_order",
                    "approves_live",
                    "closed_trade_count",
                    "classification",
                    "strategy_router_regime_counts",
                ]
            },
            "instruction": (
                "Do not patch unless root cause is confirmed. "
                "Read the regression detail and action fields. "
                "Do not lower gates. Do not reset paper loop. "
                "Identify the exact source file + function + Redis key."
            ),
        }
        REGRESSION_PATH.write_text(json.dumps(alert, indent=2))
    elif REGRESSION_PATH.exists():
        # Clear stale regression file if all clear
        REGRESSION_PATH.unlink()

    return status


def _print_summary(status: dict) -> None:
    t = status["trade_accumulation"]
    c = status["checks"]
    nd = status.get("no_trade_diagnostic", {})
    diag_str = ""
    if nd.get("triggered"):
        diag_str = f" | no_trade_diag={nd.get('verdict','?')}"
    print(
        f"[{status['generated_utc']}] "
        f"status={status['overall_status']} | "
        f"new_trades={t['new_closed_trades_post_fix']}/{t['g13_g14_trigger_threshold']} | "
        f"elapsed={nd.get('elapsed_hours_since_fix','?')}h | "
        f"pid={'OK' if c['1_paper_loop_pid_alive'] else 'DEAD'} | "
        f"data_unreliable={'CLEAR' if c['3_data_unreliable_blocks_zero'] else 'REGRESSION'} | "
        f"live_gate={'OK' if c['5_live_gate_blocked'] else 'CHANGED'} | "
        f"regressions={status['regression_count']}"
        f"{diag_str}",
        flush=True,
    )


if __name__ == "__main__":
    daemon = "--daemon" in sys.argv

    if daemon:
        print(
            f"[{dt.datetime.utcnow().isoformat()}Z] "
            f"CLAUDE_POST_UNBLOCK_RECOVERY_MONITOR starting daemon (interval={DAEMON_INTERVAL_SECONDS}s)",
            flush=True,
        )
        while True:
            try:
                status = run_once()
                _print_summary(status)
            except Exception as exc:
                print(
                    f"[{dt.datetime.utcnow().isoformat()}Z] ERROR in monitor run: {exc}",
                    flush=True,
                )
            time.sleep(DAEMON_INTERVAL_SECONDS)
    else:
        status = run_once()
        _print_summary(status)
        print(json.dumps(status, indent=2))
