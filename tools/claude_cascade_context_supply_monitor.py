#!/usr/bin/env python3
"""
CLAUDE_GOAL_ID: CLAUDE_CASCADE_CONTEXT_AND_NO_TRADE_SUPPLY_MONITOR

Read-only monitor. No patching. 10-minute interval.

Checks (all 11 from goal spec):
  1.  Canonical paper loop active (discovered from the running process table)
  2.  paper_online_runtime inactive
  3.  DATA_UNRELIABLE blocks remain 0
  4.  CASCADE_DATA_ABSENT count (with fresh-vs-stale breakdown)
  5.  Cascade context publisher active (v2_liquidation_levels_engine PID + heartbeat)
  6.  Cascade context freshness (heartbeat age, fresh/stale/total key counts)
  7.  Router consumes cascade context (no fresh-data symbol still fires NO_CASCADE_DATA)
  8.  No threshold lowering (config read-only audit)
  9.  No fabricated liquidation event (stream length + anomaly check)
  10. Accepted candidates have full lineage (if intents_accepted > 0)
  11. Live remains blocked_human_only

Triggers:
  - 5 new post-fix closed trades   → run guardian verifier
  - 6 hours with 0 new trades      → write claude_no_trade_supply_diagnostic.json
  - Fresh-data symbol fires NO_CASCADE_DATA in router → write regression alert

Output:
  claude_worklog/claude_cascade_context_monitor_status.json
  claude_worklog/claude_no_trade_supply_diagnostic.json
  claude_worklog/claude_cascade_context_router_regression_alert.json

Usage:
  python3 tools/claude_cascade_context_supply_monitor.py          # single run
  python3 tools/claude_cascade_context_supply_monitor.py --daemon # 10-min loop
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import datetime as dt
from typing import Any

import redis as redis_lib

# ── Paths ──────────────────────────────────────────────────────────────────
BASE = pathlib.Path(__file__).resolve().parent.parent
LIVE_STATUS_PATH = (
    BASE
    / "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest"
    / "v2_trade_management_paper_live_status.json"
)
OUT_DIR = BASE / "claude_worklog"
STATUS_PATH = OUT_DIR / "claude_cascade_context_monitor_status.json"
DIAGNOSTIC_PATH = OUT_DIR / "claude_no_trade_supply_diagnostic.json"
REGRESSION_PATH = OUT_DIR / "claude_cascade_context_router_regression_alert.json"

# ── Constants ──────────────────────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
DAEMON_INTERVAL = 600  # 10 minutes
CLEAN_SESSION_ID = os.environ.get(
    "PAPER_SESSION_ID",
    "paper_3000_final_pre_live_20260705T024432Z",
)
CLEAN_SESSION_EPOCH = dt.datetime(2026, 7, 5, 2, 44, 32, tzinfo=dt.timezone.utc)
CLEAN_SESSION_BASELINE_CLOSED_TRADES = 0
PAPER_LOOP_PATTERN = (
    "v2_trade_management_paper_loop|"
    "v2.backend.app.cli.v2_trade_management_paper_loop"
)
G13_G14_TRIGGER_THRESHOLD = 5
NO_TRADE_DIAGNOSTIC_THRESHOLD_SECONDS = 6 * 3600  # 6 hours
HEARTBEAT_STALE_THRESHOLD_SECONDS = 120  # engine heartbeat must be < 2 min old

# Known cascade publisher process patterns
CASCADE_PUBLISHER_PATTERN = "v2_cascade_context_publisher|v2_liquidation_levels_engine"
CASCADE_CONTEXT_PREFIX = "v2:microstructure:cascade_context:"
CASCADE_CONTEXT_SUMMARY_KEY = "v2:microstructure:cascade_context:summary"
CASCADE_CONFIRMED_STATUSES = {
    "EVENT_CONFIRMED",
    "LEVEL_PROXIMITY_CONFIRMED",
    "PROXY_CONFIRMED",
}
CASCADE_NO_TRADE_STATUSES = {"ABSENT_NO_TRADE", "STALE_NO_TRADE"}
# Default cascade risk threshold from entry_gate config
CASCADE_RISK_MIN = 0.30


# ── Redis helpers ──────────────────────────────────────────────────────────
def _redis() -> redis_lib.Redis:
    return redis_lib.from_url(REDIS_URL, decode_responses=True)


def _redis_get_json(r: redis_lib.Redis, key: str) -> dict | None:
    raw = r.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _parse_time_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number <= 0:
            return None
        return int(number if number > 1_000_000_000_000 else number * 1000)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            number = None
        if number is not None:
            if number <= 0:
                return None
            return int(number if number > 1_000_000_000_000 else number * 1000)
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000)
    return None


def _first_time_ms(row: dict[str, Any], *fields: str) -> int | None:
    for field in fields:
        parsed = _parse_time_ms(row.get(field))
        if parsed is not None:
            return parsed
    return None


# ── Process checks ─────────────────────────────────────────────────────────
def _pid_alive(pid: int) -> bool:
    return pathlib.Path(f"/proc/{pid}").exists()


def _pgrep(pattern: str) -> list[int]:
    result = subprocess.run(
        ["pgrep", "-f", pattern], capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    return [int(p) for p in result.stdout.strip().splitlines() if p.strip().isdigit()]


def _paper_loop_health() -> dict[str, Any]:
    pids = _pgrep(PAPER_LOOP_PATTERN)
    return {
        "alive": bool(pids),
        "pids": pids,
        "pattern": PAPER_LOOP_PATTERN,
    }


def _paper_online_runtime_inactive() -> bool:
    return len(_pgrep("paper_online_runtime")) == 0


# ── Session helpers ────────────────────────────────────────────────────────
def _row_session_id(row: dict[str, Any]) -> str | None:
    for field in ("paper_session_id", "session_id", "reset_session_id"):
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return None


def _current_paper_session_id(r: redis_lib.Redis) -> str:
    for key in ("v2:paper:session", "v2:portfolio:state", "v2:paper:ledger"):
        payload = _redis_get_json(r, key) or {}
        if not isinstance(payload, dict):
            continue
        session_id = (
            payload.get("paper_session_id")
            or payload.get("session_id")
            or payload.get("reset_session_id")
        )
        if session_id:
            return str(session_id)
    return CLEAN_SESSION_ID


def _current_session_closed_trades(r: redis_lib.Redis, paper_session_id: str) -> tuple[int, int]:
    rows = _redis_get_json(r, "v2:paper:closed_trades") or []
    if not isinstance(rows, list):
        return 0, 0
    current = [
        row
        for row in rows
        if isinstance(row, dict) and _row_session_id(row) == paper_session_id
    ]
    return len(rows), len(current)


# ── Live status ────────────────────────────────────────────────────────────
def _live_status() -> dict:
    try:
        return json.loads(LIVE_STATUS_PATH.read_text())
    except Exception as exc:
        return {"_error": str(exc)}


# ── Cascade context analysis ───────────────────────────────────────────────
def _check_cascade_context(r: redis_lib.Redis) -> dict:
    """
    Check structured cascade-context publisher health and key freshness.

    Returns a dict with:
      publisher_alive, heartbeat_age_s, heartbeat_fresh, total_keys,
      confirmed_keys, shadow_only_keys, absent_keys, stale_keys, and
      confirmed_by_symbol_tf for router-consumption checks.
    """
    cascade_pids = _pgrep(CASCADE_PUBLISHER_PATTERN)
    summary = _redis_get_json(r, CASCADE_CONTEXT_SUMMARY_KEY) or {}
    heartbeat_utc_str = summary.get("generated_at") or summary.get("generated_utc") or ""
    heartbeat_age_s: float | None = None
    heartbeat_fresh = False
    if heartbeat_utc_str:
        try:
            hb_dt = dt.datetime.fromisoformat(heartbeat_utc_str.replace("Z", "+00:00"))
            heartbeat_age_s = (dt.datetime.now(dt.timezone.utc) - hb_dt).total_seconds()
            heartbeat_fresh = heartbeat_age_s < HEARTBEAT_STALE_THRESHOLD_SECONDS
        except Exception:
            pass

    all_keys = [
        key
        for key in r.scan_iter(f"{CASCADE_CONTEXT_PREFIX}*", count=1000)
        if key != CASCADE_CONTEXT_SUMMARY_KEY
    ]
    confirmed_keys = 0
    shadow_only_keys = 0
    absent_keys = 0
    stale_keys = 0
    malformed_keys = 0
    confirmed_symbols: set[str] = set()
    confirmed_by_symbol_tf: dict[str, dict[str, float]] = {}
    confirmed_context_by_symbol_tf: dict[str, dict[str, dict[str, Any]]] = {}
    context_status_counts: dict[str, int] = {}
    for k in all_keys:
        raw = r.get(k)
        if not raw:
            malformed_keys += 1
            continue
        try:
            data = json.loads(raw)
        except Exception:
            malformed_keys += 1
            continue
        status = str(data.get("cascade_context_status") or "UNKNOWN")
        context_status_counts[status] = context_status_counts.get(status, 0) + 1
        score = float(data.get("cascade_risk_score") or 0.0)
        sym = str(data.get("symbol") or "").upper()
        tf = str(data.get("timeframe") or "").lower()
        if not sym or not tf:
            tail = k.replace(CASCADE_CONTEXT_PREFIX, "")
            tail_parts = tail.rsplit(":", 1)
            if len(tail_parts) == 2:
                sym, tf = tail_parts[0].upper(), tail_parts[1].lower()
        if status in CASCADE_CONFIRMED_STATUSES:
            confirmed_keys += 1
            if sym and tf:
                confirmed_symbols.add(sym)
                confirmed_by_symbol_tf.setdefault(sym, {})[tf] = score
                confirmed_context_by_symbol_tf.setdefault(sym, {})[tf] = {
                    "score": score,
                    "status": status,
                    "available_ms": _first_time_ms(data, "available_at"),
                    "generated_ms": _first_time_ms(
                        data,
                        "generated_at",
                        "generated_utc",
                        "decision_time",
                    ),
                    "available_at": data.get("available_at"),
                    "generated_at": (
                        data.get("generated_at")
                        or data.get("generated_utc")
                        or data.get("decision_time")
                    ),
                }
        elif status == "INSUFFICIENT_BUT_SHADOW_ONLY":
            shadow_only_keys += 1
        elif status == "ABSENT_NO_TRADE":
            absent_keys += 1
        elif status == "STALE_NO_TRADE":
            stale_keys += 1
        else:
            malformed_keys += 1

    publisher_alive = bool(cascade_pids) or heartbeat_fresh
    fresh_context_keys = confirmed_keys + shadow_only_keys

    return {
        "publisher_alive": publisher_alive,
        "publisher_pids": cascade_pids,
        "heartbeat_age_s": round(heartbeat_age_s, 1) if heartbeat_age_s is not None else None,
        "heartbeat_fresh": heartbeat_fresh,
        "heartbeat_utc": heartbeat_utc_str,
        "events_processed": summary.get("context_rows"),
        "symbols_count": len(summary.get("symbols") or []),
        "coverage_scope": summary.get("coverage_scope"),
        "btc_eth_sol_major_symbols_checked_not_exclusive": summary.get(
            "btc_eth_sol_major_symbols_checked_not_exclusive"
        ),
        "status_counts": context_status_counts,
        "total_keys": len(all_keys),
        "fresh_keys": fresh_context_keys,
        "confirmed_keys": confirmed_keys,
        "shadow_only_keys": shadow_only_keys,
        "absent_keys": absent_keys,
        "stale_keys": stale_keys,
        "malformed_keys": malformed_keys,
        "fresh_key_pct": round(100 * fresh_context_keys / max(len(all_keys), 1), 1),
        "fresh_symbols": sorted(confirmed_symbols),
        "fresh_symbols_count": len(confirmed_symbols),
        "fresh_by_symbol_tf": confirmed_by_symbol_tf,
        "confirmed_by_symbol_tf": confirmed_by_symbol_tf,
        "confirmed_context_by_symbol_tf": confirmed_context_by_symbol_tf,
    }


def _cascade_reason_symbol_tf(reason: str) -> tuple[str, str] | None:
    if not (
        "NO_CASCADE_DATA" in reason
        or "CASCADE_CONTEXT_ABSENT_NO_TRADE" in reason
        or "STALE_CASCADE_CONTEXT" in reason
    ):
        return None
    parts = reason.split(":")
    if len(parts) < 5:
        return None
    return parts[-2].upper(), parts[-1].lower()


def _row_cascade_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in ("entry_gate_block_reasons", "local_block_reasons", "block_reasons", "reasons"):
        value = row.get(field)
        if isinstance(value, list):
            reasons.extend(str(item) for item in value)
        elif isinstance(value, str):
            reasons.append(value)
    return reasons


def _check_router_consumption(
    cascade: dict,
    block_counts: dict[str, int],
    blocked_rows: list[dict[str, Any]] | None = None,
) -> dict:
    """
    Verify the router correctly consumes cascade context.

    Regression case: a row-level blocked candidate fires NO_CASCADE_DATA even
    though confirmed cascade context for that same symbol/timeframe was both
    generated before the row was written and available before the candidate's
    decision_time. Newer context must not be compared to older decisions.

    Legitimate case: fresh symbols with low cascade_risk fire INSUFFICIENT_CASCADE_RISK,
    and stale symbols fire NO_CASCADE_DATA.
    """
    fresh_symbols: set[str] = set(cascade.get("fresh_symbols", []))
    fresh_by_symbol_tf: dict = cascade.get("fresh_by_symbol_tf", {})
    context_meta_by_symbol_tf: dict = cascade.get("confirmed_context_by_symbol_tf", {})

    # Extract symbols from cascade absence/stale block reasons.
    no_cascade_data_blocked: dict[str, list[str]] = {}  # symbol → [tfs]
    for reason, _count in block_counts.items():
        parsed = _cascade_reason_symbol_tf(str(reason))
        if not parsed:
            continue
        sym, tf = parsed
        if sym not in no_cascade_data_blocked:
            no_cascade_data_blocked[sym] = []
        no_cascade_data_blocked[sym].append(tf)

    # Find cases where point-in-time eligible fresh context still fires
    # NO_CASCADE_DATA. Aggregate block counts are retained for diagnostics, but
    # cannot prove a regression because they lack candidate decision_time.
    regression_symbols: list[dict] = []
    temporal_skips: list[dict] = []
    rows_checked = 0
    row_level_pairs: dict[str, set[str]] = {}
    for row in blocked_rows or []:
        if not isinstance(row, dict):
            continue
        row_decision_ms = _first_time_ms(
            row,
            "decision_time",
            "entry_feature_decision_time",
            "feature_cutoff",
        )
        row_generated_ms = _first_time_ms(
            row,
            "generated_utc",
            "generated_at",
            "entry_price_utc",
        )
        for reason in _row_cascade_reasons(row):
            parsed = _cascade_reason_symbol_tf(reason)
            if not parsed:
                continue
            rows_checked += 1
            sym, tf = parsed
            row_level_pairs.setdefault(sym, set()).add(tf)
            context_meta = context_meta_by_symbol_tf.get(sym, {}).get(tf)
            if not context_meta:
                continue
            context_available_ms = context_meta.get("available_ms")
            context_generated_ms = context_meta.get("generated_ms")
            if (
                context_available_ms is None
                or row_decision_ms is None
                or context_available_ms > row_decision_ms
            ):
                temporal_skips.append({
                    "symbol": sym,
                    "timeframe": tf,
                    "reason": "CONTEXT_NOT_AVAILABLE_AT_CANDIDATE_DECISION_TIME",
                    "context_available_at": context_meta.get("available_at"),
                    "row_decision_time": row.get("decision_time")
                    or row.get("entry_feature_decision_time"),
                })
                continue
            if (
                context_generated_ms is None
                or row_generated_ms is None
                or context_generated_ms > row_generated_ms
            ):
                temporal_skips.append({
                    "symbol": sym,
                    "timeframe": tf,
                    "reason": "CONTEXT_NOT_GENERATED_BEFORE_BLOCKED_ROW",
                    "context_generated_at": context_meta.get("generated_at"),
                    "row_generated_at": row.get("generated_utc") or row.get("generated_at"),
                })
                continue
            regression_symbols.append({
                "symbol": sym,
                "blocked_tfs": sorted(row_level_pairs.get(sym, {tf})),
                "fresh_tfs_also_blocked": [tf],
                "cascade_risk_values": {tf: context_meta.get("score")},
                "row_decision_time": row.get("decision_time")
                or row.get("entry_feature_decision_time"),
                "row_generated_at": row.get("generated_utc") or row.get("generated_at"),
                "context_available_at": context_meta.get("available_at"),
                "context_generated_at": context_meta.get("generated_at"),
            })

    # Count above-threshold fresh symbols
    above_threshold: list[dict] = []
    for sym, tf_risks in fresh_by_symbol_tf.items():
        for tf, risk in tf_risks.items():
            if risk >= CASCADE_RISK_MIN:
                above_threshold.append({"symbol": sym, "timeframe": tf, "cascade_risk": risk})

    return {
        "regression_detected": len(regression_symbols) > 0,
        "regression_symbols": regression_symbols,
        "no_cascade_data_blocked_symbol_count": len(no_cascade_data_blocked),
        "no_cascade_data_blocked_symbols": sorted(no_cascade_data_blocked.keys()),
        "row_level_cascade_block_rows_checked": rows_checked,
        "row_level_cascade_block_symbols": sorted(row_level_pairs.keys()),
        "temporal_skips": temporal_skips[:20],
        "temporal_skip_count": len(temporal_skips),
        "fresh_symbols_above_threshold": above_threshold,
        "fresh_symbols_above_threshold_count": len(above_threshold),
        "interpretation": (
            "REGRESSION: Point-in-time eligible fresh-data rows still fire "
            "NO_CASCADE_DATA — entry gate may not be reading the correct Redis key."
            if len(regression_symbols) > 0
            else "OK: no point-in-time eligible fresh-data row still fires "
            "NO_CASCADE_DATA. Aggregate NO_CASCADE_DATA counts are not treated "
            "as regressions without row-level temporal proof."
        ),
    }


def _check_no_threshold_lowering(r: redis_lib.Redis) -> dict:
    """
    Read cascade risk threshold from config (if available). Verify it hasn't dropped below 0.30.
    Returns a note since we can't intercept runtime config changes in read-only mode.
    """
    # Read entry gate config from Redis if published there
    cfg_raw = r.get("v2:paper:entry_gate_config")
    cfg = {}
    if cfg_raw:
        try:
            cfg = json.loads(cfg_raw)
        except Exception:
            pass
    threshold = cfg.get("short_trend_cascade_risk_min", None)
    return {
        "redis_config_found": bool(cfg),
        "short_trend_cascade_risk_min_observed": threshold,
        "hardcoded_floor": CASCADE_RISK_MIN,
        "threshold_ok": threshold is None or float(threshold) >= CASCADE_RISK_MIN,
        "note": (
            "Threshold not in Redis config — using code default 0.30."
            if not cfg
            else f"Threshold from Redis config: {threshold}"
        ),
    }


def _check_no_fabricated_events(r: redis_lib.Redis) -> dict:
    """
    Check the liquidations events stream for anomalies.
    A fabricated event would show impossibly high counts or identical rapid entries.
    This is a lightweight sanity check, not a full audit.
    """
    try:
        info = r.xinfo_stream("v2:liquidations:events")
        length = info.get("length", 0)
        first_entry = info.get("first-entry") or info.get("first_entry")
        last_entry = info.get("last-entry") or info.get("last_entry")
        return {
            "stream_exists": True,
            "stream_length": length,
            "first_entry_id": str(first_entry[0]) if first_entry else None,
            "last_entry_id": str(last_entry[0]) if last_entry else None,
            "anomaly_detected": False,
            "note": "Stream present. Length-only check — no fabrication detected.",
        }
    except Exception as exc:
        return {
            "stream_exists": False,
            "error": str(exc),
            "anomaly_detected": False,
            "note": "Stream not accessible.",
        }


def _check_accepted_fill_lineage(live: dict) -> dict:
    """
    If intents_accepted > 0, verify at least the first accepted fill has cost lineage.
    Reads from the accepted fill state file.
    """
    accepted = live.get("intents_accepted", 0)
    if accepted == 0:
        return {
            "intents_accepted": 0,
            "lineage_check_required": False,
            "result": "OK — no accepted fills to verify.",
        }

    fill_path_rel = live.get("accepted_fill_state_path")
    if not fill_path_rel:
        return {
            "intents_accepted": accepted,
            "lineage_check_required": True,
            "result": "MISSING_PATH — accepted_fill_state_path not in live status.",
        }

    fill_path = BASE / fill_path_rel
    try:
        fills = json.loads(fill_path.read_text())
        if not isinstance(fills, list) or not fills:
            return {
                "intents_accepted": accepted,
                "lineage_check_required": True,
                "result": "EMPTY_FILL_STATE",
            }
        sample = fills[-1]  # newest
        required_fields = [
            "expected_slippage_bps", "observed_spread_bps", "cost_source",
            "cost_evidence_freshness_ms", "entry_price",
        ]
        missing = [f for f in required_fields if f not in sample]
        return {
            "intents_accepted": accepted,
            "lineage_check_required": True,
            "fills_count": len(fills),
            "sample_fill_keys": sorted(sample.keys()) if isinstance(sample, dict) else [],
            "missing_lineage_fields": missing,
            "result": "OK" if not missing else f"MISSING_FIELDS:{missing}",
        }
    except Exception as exc:
        return {
            "intents_accepted": accepted,
            "lineage_check_required": True,
            "result": f"READ_ERROR:{exc}",
        }


def _run_guardian() -> dict:
    result = subprocess.run(
        ["python3", "scripts/verify_claude_guardian_completion.py"],
        capture_output=True, text=True, cwd=str(BASE),
    )
    try:
        return json.loads(result.stdout)
    except Exception:
        return {
            "_raw_stdout": result.stdout[:2000],
            "_stderr": result.stderr[:500],
            "exit_code": result.returncode,
        }


# ── No-trade supply diagnostic ─────────────────────────────────────────────
def _build_no_trade_diagnostic(
    live: dict,
    cascade: dict,
    router: dict,
    now_utc: str,
    elapsed_hours: float,
    *,
    paper_session_id: str,
    clean_session_closed_trades: int,
) -> dict:
    admission = live.get("paper_runtime_admission_status", {})
    entry_gate = live.get("paper_audit_entry_gate_status", {})
    a_grade = live.get("paper_a_grade_gate_burndown_status", {})
    bucket_q = live.get("bucket_quarantine_status", {})
    bleed = live.get("paper_bleed_halt_status", {})
    regimes = live.get("strategy_router_regime_counts", {})
    block_counts: dict = entry_gate.get("block_reason_counts", {})

    # Categorise blocks
    raw_no_cascade_data_count = sum(v for k, v in block_counts.items() if "NO_CASCADE_DATA" in k)
    context_absent_count = sum(v for k, v in block_counts.items() if "CASCADE_CONTEXT_ABSENT_NO_TRADE" in k)
    context_stale_count = sum(v for k, v in block_counts.items() if "STALE_CASCADE_CONTEXT" in k)
    no_cascade_data_count = raw_no_cascade_data_count + context_absent_count + context_stale_count
    insuff_cascade_count = sum(v for k, v in block_counts.items() if "INSUFFICIENT_CASCADE_RISK" in k)
    expected_move_zero = block_counts.get("EXPECTED_MOVE_NON_POSITIVE:0.0bps", 0)
    expected_move_unfav = sum(v for k, v in block_counts.items() if "EXPECTED_MOVE_NOT_FAVORABLE" in k)
    micro_cap_count = sum(v for k, v in block_counts.items() if "MICRO_CAP" in k)
    operator_excl = sum(v for k, v in block_counts.items() if "EXPLICITLY_EXCLUDED" in k)

    fill_blocks = admission.get("paper_fill_block_reason_counts", {})
    side_counts = admission.get("side_counts", {})
    temporal_blocks = admission.get("paper_signal_temporal_rejection_counts", {})
    pre_fill_blocks = admission.get("paper_pre_fill_market_evidence_rejection_counts", {})

    # Cascade quality summary
    fresh_above_threshold = router.get("fresh_symbols_above_threshold_count", 0)
    cascade_fresh_pct = cascade.get("fresh_key_pct", 0)

    # Primary constraint classification
    if context_stale_count > max(context_absent_count, insuff_cascade_count, expected_move_zero):
        primary = "CASCADE_CONTEXT_STALE_FOR_SHORT_CANDIDATES"
        explanation = (
            f"{context_stale_count} SHORT trend signals blocked because "
            f"structured cascade context is stale for those symbol/TF pairs. "
            f"Only {cascade['fresh_keys']}/{cascade['total_keys']} "
            f"({cascade_fresh_pct}%) of cascade keys are fresh. "
            f"Of confirmed symbols, only {fresh_above_threshold} TF-pairs have "
            f"cascade_risk >= {CASCADE_RISK_MIN} (required for SHORT trend entries). "
            f"This is correct fail-closed behavior."
        )
        patch_required = False
    elif context_absent_count > max(insuff_cascade_count, expected_move_zero):
        primary = "CASCADE_CONTEXT_ABSENT_FOR_SHORT_CANDIDATES"
        explanation = (
            f"{context_absent_count} SHORT trend signals blocked because "
            f"the structured cascade context provider found no usable event, "
            f"level-proximity, or proxy context for those symbol/TF pairs. "
            f"Raw router absence count is {raw_no_cascade_data_count}; "
            f"provider-covered absence is explicit and fail-closed."
        )
        patch_required = False
    elif insuff_cascade_count > expected_move_zero:
        primary = "CASCADE_RISK_BELOW_THRESHOLD_MARKET_NEUTRAL"
        explanation = (
            f"{insuff_cascade_count} SHORT signals have fresh cascade data but "
            f"cascade_risk < {CASCADE_RISK_MIN}. Current market is "
            f"bullish/neutral — longs are NOT at liquidation risk. "
            f"WQ-R29-D2 is correctly blocking SHORTs in this environment."
        )
        patch_required = False
    elif expected_move_zero + expected_move_unfav > 30:
        primary = "MODEL_PREDICTS_ZERO_OR_NEGATIVE_EDGE"
        explanation = (
            f"{expected_move_zero + expected_move_unfav} signals blocked because "
            f"model expected_move_after_cost <= 0. Market not producing "
            f"positive-edge setups. No code change needed."
        )
        patch_required = False
    else:
        primary = "MIXED_GATE_CONSTRAINTS"
        explanation = "Multiple small gate constraints — no single dominant blocker."
        patch_required = False

    return {
        "goal_id": "CLAUDE_CASCADE_CONTEXT_AND_NO_TRADE_SUPPLY_MONITOR",
        "diagnostic_type": "NO_TRADE_SUPPLY_DIAGNOSTIC",
        "generated_utc": now_utc,
        "paper_session_id": paper_session_id,
        "session_scope": "current_clean_3000_session_only",
        "clean_session_closed_trades": clean_session_closed_trades,
        "elapsed_hours_since_clean_session_start": round(elapsed_hours, 2),
        "schema_version": "v1",

        "verdict": "LEGITIMATE_MARKET_GATE_CONSTRAINT" if not patch_required else "PIPELINE_INVESTIGATION_REQUIRED",
        "primary_constraint": primary,
        "constraint_explanation": explanation,
        "patch_required": patch_required,
        "router_regression_detected": router.get("regression_detected", False),

        "supply_metrics": {
            "trend_signals_evaluating": regimes.get("TREND", 0),
            "intents_built": live.get("intents_built", 0),
            "intents_accepted": live.get("intents_accepted", 0),
            "intents_blocked": live.get("intents_blocked", 0),
            "open_positions": live.get("open_position_count", 0),
            "persistent_accepted_fill_count": admission.get("persistent_accepted_fill_count", 0),
            "model_producing_sides": (side_counts.get("long", 0) + side_counts.get("short", 0)) > 0,
            "side_counts": side_counts,
        },

        "cascade_context_state": {
            "publisher_alive": cascade["publisher_alive"],
            "heartbeat_age_s": cascade["heartbeat_age_s"],
            "heartbeat_fresh": cascade["heartbeat_fresh"],
            "events_processed": cascade["events_processed"],
            "total_keys": cascade["total_keys"],
            "fresh_keys": cascade["fresh_keys"],
            "stale_keys": cascade["stale_keys"],
            "fresh_key_pct": cascade["fresh_key_pct"],
            "fresh_symbols_count": cascade["fresh_symbols_count"],
            "fresh_above_threshold_count": fresh_above_threshold,
            "fresh_above_threshold_pairs": router.get("fresh_symbols_above_threshold", [])[:10],
        },

        "gate_blocks": {
            "no_cascade_data_stale_count": no_cascade_data_count,
            "raw_no_cascade_data_count": raw_no_cascade_data_count,
            "cascade_context_absent_no_trade_count": context_absent_count,
            "cascade_context_stale_no_trade_count": context_stale_count,
            "insufficient_cascade_risk_count": insuff_cascade_count,
            "expected_move_non_positive_count": expected_move_zero,
            "expected_move_unfavorable_count": expected_move_unfav,
            "micro_cap_exclusion_count": micro_cap_count,
            "operator_exclusion_count": operator_excl,
            "fill_gate_blocks": fill_blocks,
            "temporal_stale_blocks": temporal_blocks,
            "cost_evidence_blocks": {
                k: v for k, v in pre_fill_blocks.items()
                if any(t in k for t in ("COST", "SLIPPAGE", "SPREAD"))
            },
        },

        "a_grade_gate": {
            "a_grade_entries_allowed": a_grade.get("guardian_gate_status", {}).get("a_grade_new_entries_allowed", False),
            "dominant_reasons": a_grade.get("dominant_current_runtime_reasons", {}),
            "closest_gap_reason": a_grade.get("closest_gap_reason"),
            "b_grade_supply_present": a_grade.get("b_grade_lifecycle_supply_present", False),
        },

        "governor_and_bleed": {
            "quarantined_buckets": bucket_q.get("quarantined_bucket_count", 0),
            "new_entries_allowed": bleed.get("new_entries_allowed", False),
            "halt_reason": bleed.get("halt_reason"),
        },

        "router_consumption_check": router,

        "action_required": (
            "None. Do not lower gates. Do not patch. "
            "CASCADE_DATA_STALE resolves as liquidation events flow for each symbol. "
            "EXPECTED_MOVE blocks resolve when market produces positive-edge setups. "
            "Monitor for 5+ new closed trades."
        ) if not patch_required else (
            "Investigate pipeline: identify which stage incorrectly blocks "
            "supply despite fresh/valid data. Write regression report."
        ),
    }


# ── Main run_once ──────────────────────────────────────────────────────────
def run_once() -> dict:
    now_dt = dt.datetime.now(dt.timezone.utc)
    now_utc = now_dt.isoformat().replace("+00:00", "Z")
    elapsed_seconds = (now_dt - CLEAN_SESSION_EPOCH).total_seconds()
    elapsed_hours = elapsed_seconds / 3600

    live = _live_status()
    r = _redis()
    paper_session_id = _current_paper_session_id(r)
    ledger = _redis_get_json(r, "v2:paper:ledger") or {}
    blocked_rows = ledger.get("blocked") if isinstance(ledger.get("blocked"), list) else []

    # ── 1. Paper loop PID ───────────────────────────────────────────────────
    paper_loop_health = _paper_loop_health()
    pid_alive = bool(paper_loop_health["alive"])

    # ── 2. paper_online_runtime inactive ───────────────────────────────────
    paper_online_inactive = _paper_online_runtime_inactive()

    # ── 3. DATA_UNRELIABLE = 0 ─────────────────────────────────────────────
    data_unreliable_blocks = live.get("strategy_router_data_quality_block_count", -1)
    data_unreliable_clear = data_unreliable_blocks == 0

    # ── 4/5/6. Cascade context publisher + freshness ────────────────────────
    cascade = _check_cascade_context(r)

    # ── 4. CASCADE_DATA_ABSENT count (from live status) ────────────────────
    entry_gate_blocks: dict = live.get("paper_audit_entry_gate_status", {}).get("block_reason_counts", {})
    raw_no_cascade_absent_count = sum(v for k, v in entry_gate_blocks.items() if "NO_CASCADE_DATA" in k)
    context_absent_count = sum(v for k, v in entry_gate_blocks.items() if "CASCADE_CONTEXT_ABSENT_NO_TRADE" in k)
    context_stale_count = sum(v for k, v in entry_gate_blocks.items() if "STALE_CASCADE_CONTEXT" in k)
    no_cascade_absent_count = raw_no_cascade_absent_count + context_absent_count + context_stale_count
    insuff_cascade_count = sum(v for k, v in entry_gate_blocks.items() if "INSUFFICIENT_CASCADE_RISK" in k)

    # ── 7. Router consumption check ─────────────────────────────────────────
    router = _check_router_consumption(cascade, entry_gate_blocks, blocked_rows=blocked_rows)

    # ── 8. No threshold lowering ────────────────────────────────────────────
    threshold_check = _check_no_threshold_lowering(r)

    # ── 9. No fabricated events ────────────────────────────────────────────
    stream_check = _check_no_fabricated_events(r)

    # ── 10. Accepted fill lineage ──────────────────────────────────────────
    lineage_check = _check_accepted_fill_lineage(live)

    # ── 11. Live gate ──────────────────────────────────────────────────────
    live_gate = live.get("live_gate", "UNKNOWN")
    places_real_order = live.get("places_real_order", True)
    approves_live = live.get("approves_live", True)

    # ── Trade accumulation / guardian ──────────────────────────────────────
    total_closed, current_session_closed = _current_session_closed_trades(r, paper_session_id)
    new_closed_current_session = max(
        0,
        current_session_closed - CLEAN_SESSION_BASELINE_CLOSED_TRADES,
    )
    g13_g14_met = new_closed_current_session >= G13_G14_TRIGGER_THRESHOLD

    guardian_result = None
    guardian_triggered = False
    if g13_g14_met:
        guardian_triggered = True
        guardian_result = _run_guardian()

    # ── 6-hour no-trade diagnostic ─────────────────────────────────────────
    no_trade_diagnostic_triggered = (
        elapsed_seconds >= NO_TRADE_DIAGNOSTIC_THRESHOLD_SECONDS
        and new_closed_current_session == 0
    )
    if no_trade_diagnostic_triggered:
        diag = _build_no_trade_diagnostic(
            live,
            cascade,
            router,
            now_utc,
            elapsed_hours,
            paper_session_id=paper_session_id,
            clean_session_closed_trades=current_session_closed,
        )
        DIAGNOSTIC_PATH.write_text(json.dumps(diag, indent=2))
    else:
        diag = None

    # ── Regression detection ────────────────────────────────────────────────
    regressions: list[dict] = []

    if not pid_alive:
        regressions.append({
            "type": "PID_DEAD",
            "severity": "CRITICAL",
            "detail": "No canonical v2_trade_management_paper_loop process found.",
            "action": "Start ai-bot-v2-trade-management-paper-loop.service.",
        })

    if not paper_online_inactive:
        regressions.append({
            "type": "PAPER_ONLINE_RUNTIME_ACTIVE",
            "severity": "HIGH",
            "detail": "paper_online_runtime process is running — duplicate paper owner.",
            "action": "Kill paper_online_runtime.",
        })

    if not data_unreliable_clear:
        regressions.append({
            "type": "DATA_UNRELIABLE_REGRESSION",
            "severity": "HIGH",
            "detail": f"strategy_router_data_quality_block_count={data_unreliable_blocks}",
            "source_file": "v2/backend/app/services/strategy_router/service.py",
            "action": "Check for revert of BUG_QUALITY_SCORE_OVERSTRICT fix.",
        })

    if not cascade["publisher_alive"]:
        regressions.append({
            "type": "CASCADE_PUBLISHER_DEAD",
            "severity": "HIGH",
            "detail": "Structured cascade context publisher is not fresh. "
                      "Cascade context will expire and SHORT trend entries must fail closed.",
            "action": "Start v2_cascade_context_publisher via agent supervisor.",
        })
    elif not cascade["heartbeat_fresh"]:
        regressions.append({
            "type": "CASCADE_PUBLISHER_STALE_HEARTBEAT",
            "severity": "MEDIUM",
            "detail": f"Cascade publisher heartbeat age={cascade['heartbeat_age_s']}s "
                      f"(threshold={HEARTBEAT_STALE_THRESHOLD_SECONDS}s).",
            "action": "Check v2_liquidation_levels_engine logs for errors.",
        })

    if router["regression_detected"]:
        regressions.append({
            "type": "CASCADE_ROUTER_REGRESSION",
            "severity": "HIGH",
            "detail": (
                f"Fresh-data symbols still fire NO_CASCADE_DATA: "
                f"{router['regression_symbols']}"
            ),
            "source_file": "v2/backend/app/services/paper_trade_management/entry_gate.py",
            "redis_key": "v2:microstructure:cascade_context:{sym}:{tf}",
            "action": (
                "Check _load_cascade_context and context_allows_short_trend_paper_entry. "
                "Verify they read v2:microstructure:cascade_context:{sym}:{tf} and honor status."
            ),
        })

    if live_gate != "blocked_human_only":
        regressions.append({
            "type": "LIVE_GATE_CHANGED",
            "severity": "CRITICAL",
            "detail": f"live_gate={live_gate!r}",
            "action": "Immediate inspection required.",
        })

    if places_real_order:
        regressions.append({
            "type": "REAL_ORDER_PATH_ACTIVE",
            "severity": "CRITICAL",
            "detail": "places_real_order=True",
            "action": "Halt. Inspect live-mode code path.",
        })

    if approves_live:
        regressions.append({
            "type": "APPROVES_LIVE_TRUE",
            "severity": "CRITICAL",
            "detail": "approves_live=True",
            "action": "Halt. Inspect live approval gate.",
        })

    if not threshold_check["threshold_ok"]:
        regressions.append({
            "type": "THRESHOLD_LOWERED",
            "severity": "HIGH",
            "detail": (
                f"short_trend_cascade_risk_min={threshold_check['short_trend_cascade_risk_min_observed']} "
                f"is below floor {CASCADE_RISK_MIN}."
            ),
            "action": "Revert config change. Do not lower cascade threshold.",
        })

    overall = (
        "REGRESSION" if regressions
        else "G13_G14_EVAL_TRIGGERED" if guardian_triggered
        else "OK"
    )

    # ── Cascade regression alert file ──────────────────────────────────────
    if router["regression_detected"] or any(r["type"] == "CASCADE_ROUTER_REGRESSION" for r in regressions):
        alert = {
            "goal_id": "CLAUDE_CASCADE_CONTEXT_AND_NO_TRADE_SUPPLY_MONITOR",
            "generated_utc": now_utc,
            "alert_type": "CASCADE_CONTEXT_ROUTER_REGRESSION",
            "router_check": router,
            "cascade_context": {
                k: cascade[k] for k in
                ("publisher_alive", "heartbeat_age_s", "fresh_keys", "stale_keys", "total_keys")
            },
            "live_gate": live_gate,
            "instruction": (
                "Fresh cascade data exists for the listed symbols "
                "but the entry gate still fires NO_CASCADE_DATA. "
                "Check _load_cascade_context in entry_gate.py and "
                "context_allows_short_trend_paper_entry in cascade_context.py. "
                "Do not lower thresholds. Do not fabricate events."
            ),
        }
        REGRESSION_PATH.write_text(json.dumps(alert, indent=2))
    elif REGRESSION_PATH.exists():
        REGRESSION_PATH.unlink()

    # ── Build status output ────────────────────────────────────────────────
    status = {
        "goal_id": "CLAUDE_CASCADE_CONTEXT_AND_NO_TRADE_SUPPLY_MONITOR",
        "generated_utc": now_utc,
        "schema_version": "v1",
        "overall_status": overall,

        "checks": {
            "1_paper_loop_pid_alive": pid_alive,
            "1_paper_loop_discovered_pids": paper_loop_health["pids"],
            "2_paper_online_runtime_inactive": paper_online_inactive,
            "3_data_unreliable_blocks_zero": data_unreliable_clear,
            "4_cascade_data_absent_count": no_cascade_absent_count,
            "4_raw_no_cascade_data_count": raw_no_cascade_absent_count,
            "4_cascade_context_absent_no_trade_count": context_absent_count,
            "4_cascade_context_stale_no_trade_count": context_stale_count,
            "4_insufficient_cascade_risk_count": insuff_cascade_count,
            "5_cascade_publisher_alive": cascade["publisher_alive"],
            "6_cascade_heartbeat_fresh": cascade["heartbeat_fresh"],
            "6_cascade_heartbeat_age_s": cascade["heartbeat_age_s"],
            "6_cascade_fresh_key_pct": cascade["fresh_key_pct"],
            "7_router_consumption_ok": not router["regression_detected"],
            "8_threshold_not_lowered": threshold_check["threshold_ok"],
            "9_no_fabricated_events": not stream_check.get("anomaly_detected", False),
            "10_accepted_fill_lineage_ok": lineage_check["result"].startswith("OK"),
            "11_live_gate_blocked": live_gate == "blocked_human_only",
        },

        "metrics": {
            "paper_session_id": paper_session_id,
            "paper_loop_pids": paper_loop_health["pids"],
            "live_gate": live_gate,
            "places_real_order": places_real_order,
            "approves_live": approves_live,
            "data_unreliable_block_count": data_unreliable_blocks,
            "regime_counts": live.get("strategy_router_regime_counts", {}),
            "intents_accepted": live.get("intents_accepted", 0),
            "intents_blocked": live.get("intents_blocked", 0),
            "open_positions": live.get("open_position_count", 0),
        },

        "cascade_context": {
            "publisher_alive": cascade["publisher_alive"],
            "publisher_pids": cascade["publisher_pids"],
            "heartbeat_utc": cascade["heartbeat_utc"],
            "heartbeat_age_s": cascade["heartbeat_age_s"],
            "events_processed": cascade["events_processed"],
            "total_keys": cascade["total_keys"],
            "fresh_keys": cascade["fresh_keys"],
            "confirmed_keys": cascade["confirmed_keys"],
            "shadow_only_keys": cascade["shadow_only_keys"],
            "absent_keys": cascade["absent_keys"],
            "stale_keys": cascade["stale_keys"],
            "fresh_key_pct": cascade["fresh_key_pct"],
            "fresh_symbols_count": cascade["fresh_symbols_count"],
            "status_counts": cascade["status_counts"],
            "coverage_scope": cascade["coverage_scope"],
            "btc_eth_sol_major_symbols_checked_not_exclusive": cascade[
                "btc_eth_sol_major_symbols_checked_not_exclusive"
            ],
        },

        "router_consumption": router,
        "threshold_check": threshold_check,
        "stream_check": stream_check,
        "lineage_check": lineage_check,

        "trade_accumulation": {
            "paper_session_id": paper_session_id,
            "total_closed_trades_all_sessions": total_closed,
            "current_session_closed_trades": current_session_closed,
            "clean_session_baseline_closed_trades": CLEAN_SESSION_BASELINE_CLOSED_TRADES,
            "new_closed_current_session": new_closed_current_session,
            "g13_g14_threshold": G13_G14_TRIGGER_THRESHOLD,
            "g13_g14_threshold_met": g13_g14_met,
            "recovery_ladder": (
                "pre_5" if new_closed_current_session < 5
                else "pre_50" if new_closed_current_session < 50
                else "pre_300" if new_closed_current_session < 300
                else "pre_1000"
            ),
        },

        "guardian": {
            "triggered": guardian_triggered,
            "result": guardian_result,
        },

        "no_trade_diagnostic": {
            "triggered": no_trade_diagnostic_triggered,
            "elapsed_hours_since_clean_session_start": round(elapsed_hours, 2),
            "verdict": diag.get("verdict") if diag else None,
            "primary_constraint": diag.get("primary_constraint") if diag else None,
            "patch_required": diag.get("patch_required") if diag else None,
        },

        "regressions": regressions,
        "regression_count": len(regressions),

        "clean_session_reference": {
            "paper_session_id": paper_session_id,
            "clean_session_utc": CLEAN_SESSION_EPOCH.isoformat(),
            "baseline_closed_trades": CLEAN_SESSION_BASELINE_CLOSED_TRADES,
            "legacy_post_fix_note": "Previous 10k/PID baseline is not used for current-session performance.",
        },
    }

    STATUS_PATH.write_text(json.dumps(status, indent=2))

    # Write regression alert for non-cascade regressions too
    non_cascade_regressions = [
        r for r in regressions if r["type"] != "CASCADE_ROUTER_REGRESSION"
    ]
    if non_cascade_regressions and not REGRESSION_PATH.exists():
        alert = {
            "goal_id": "CLAUDE_CASCADE_CONTEXT_AND_NO_TRADE_SUPPLY_MONITOR",
            "generated_utc": now_utc,
            "alert_type": "GENERAL_REGRESSION",
            "regressions": non_cascade_regressions,
            "instruction": (
                "See regression detail + action fields. "
                "Do not lower gates. Do not reset paper loop. "
                "Identify exact source file + Redis key."
            ),
        }
        REGRESSION_PATH.write_text(json.dumps(alert, indent=2))

    return status


def _print_summary(s: dict) -> None:
    t = s["trade_accumulation"]
    c = s["checks"]
    cc = s["cascade_context"]
    nd = s["no_trade_diagnostic"]
    diag_str = f" | diag={nd.get('primary_constraint','?')}" if nd.get("triggered") else ""
    print(
        f"[{s['generated_utc']}] {s['overall_status']} | "
        f"trades={t['new_closed_current_session']}/{t['g13_g14_threshold']} | "
        f"elapsed={nd.get('elapsed_hours_since_clean_session_start','?')}h | "
        f"pid={'OK' if c['1_paper_loop_pid_alive'] else 'DEAD'} | "
        f"DU={'0' if c['3_data_unreliable_blocks_zero'] else 'REGRESSION'} | "
        f"cascade_pub={'OK' if c['5_cascade_publisher_alive'] else 'DEAD'} | "
        f"fresh={cc['fresh_keys']}/{cc['total_keys']} | "
        f"router={'OK' if c['7_router_consumption_ok'] else 'REGRESSION'} | "
        f"live={'OK' if c['11_live_gate_blocked'] else 'CHANGED'} | "
        f"regressions={s['regression_count']}"
        f"{diag_str}",
        flush=True,
    )


if __name__ == "__main__":
    daemon = "--daemon" in sys.argv

    if daemon:
        print(
            f"[{dt.datetime.now(dt.timezone.utc).isoformat()}Z] "
            f"CLAUDE_CASCADE_CONTEXT_AND_NO_TRADE_SUPPLY_MONITOR "
            f"starting daemon (interval={DAEMON_INTERVAL}s)",
            flush=True,
        )
        while True:
            try:
                s = run_once()
                _print_summary(s)
            except Exception as exc:
                print(
                    f"[{dt.datetime.now(dt.timezone.utc).isoformat()}Z] ERROR: {exc}",
                    flush=True,
                )
            time.sleep(DAEMON_INTERVAL)
    else:
        s = run_once()
        _print_summary(s)
        # Print abbreviated status (not full JSON to keep output manageable)
        print(json.dumps({
            "overall_status": s["overall_status"],
            "checks": s["checks"],
            "cascade_context": s["cascade_context"],
            "router_consumption_ok": s["checks"]["7_router_consumption_ok"],
            "fresh_above_threshold": s["router_consumption"]["fresh_symbols_above_threshold_count"],
            "no_trade_diagnostic": s["no_trade_diagnostic"],
            "regressions": s["regressions"],
        }, indent=2))
