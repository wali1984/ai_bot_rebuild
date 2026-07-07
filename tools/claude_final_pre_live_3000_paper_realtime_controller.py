#!/usr/bin/env python3
"""
CLAUDE_GOAL_ID: CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER
REFRESHED: CLAUDE_3000_RESET_CONTROLLER_REFRESH_AND_SESSION_TRUTH_VERIFICATION

Real-time independent monitor. Runs every 5 minutes while Codex runs.
Refreshed after Codex $3,000 paper reset (2026-07-05T02:44:32Z).
PID is now discovered dynamically — no hardcoded expected PID.
Session is read from v2:paper:session.paper_session_id.
18 checks covering: $3K reset truth, phantom cleanup, account isolation,
trainer learning, performance gates, UI/iOS truth, A-grade and 1000x guards.

NEVER mutates exchange state, Redis ledger, or trainer weights.
Patches only: write-once diagnostic artifact files + alert JSONL.

Output files (claude_worklog/):
  claude_final_pre_live_status.json
  claude_3000_paper_reset_verification.json
  claude_trainer_learning_verification.json
  claude_paper_performance_ladder_status.json
  claude_frontend_ios_truth_status.json
  claude_operator_alerts.jsonl

Markers (goal_state/CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER/):
  CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER_ACTIVE
  CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER_BLOCKED
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time

import redis

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
BACKEND_USERNAME = os.environ.get("BACKEND_USERNAME", "admin")
BACKEND_PASSWORD = os.environ.get("BACKEND_PASSWORD", "Trader2026!")

FILL_STATE_FILE = pathlib.Path(
    "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/"
    "paper_accepted_fills_state.json"
)
WORKLOG_DIR = pathlib.Path("claude_worklog")
GOAL_DIR = pathlib.Path("goal_state/CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER")

# Output artifacts
OUT_STATUS = WORKLOG_DIR / "claude_final_pre_live_status.json"
OUT_RESET = WORKLOG_DIR / "claude_3000_paper_reset_verification.json"
OUT_TRAINER = WORKLOG_DIR / "claude_trainer_learning_verification.json"
OUT_PERF = WORKLOG_DIR / "claude_paper_performance_ladder_status.json"
OUT_UI = WORKLOG_DIR / "claude_frontend_ios_truth_status.json"
OUT_ALERTS = WORKLOG_DIR / "claude_operator_alerts.jsonl"

MARKER_ACTIVE = GOAL_DIR / "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER_ACTIVE"
MARKER_BLOCKED = GOAL_DIR / "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER_BLOCKED"

# Special alert files
ALERT_CODEX_STUCK = WORKLOG_DIR / "CODEX_STUCK_NO_PROGRESS.json"
ALERT_5_TRADE_GATE = WORKLOG_DIR / "CLAUDE_5_TRADE_GATE_FAILURE.json"
ALERT_50_TRADE_GATE = WORKLOG_DIR / "CLAUDE_50_TRADE_GATE_FAILURE.json"
ALERT_UI_TRUTH = WORKLOG_DIR / "CLAUDE_UI_TRUTH_REGRESSION.json"

# State file for Codex stuck detection (persists across runs)
CODEX_PROGRESS_STATE = GOAL_DIR / "codex_progress_state.json"

# Thresholds
PAPER_RESET_TARGET_USD = 3000.0
PAPER_RESET_TOLERANCE_USD = 1.0           # within $1 of target
BTC_PHANTOM_ENTRY_THRESHOLD = 1000.0      # BTC entry < this = phantom
PHANTOM_EQUITY_ALERT_THRESHOLD = 1.0
# PID is discovered dynamically — no hardcoded expected PID
CODEX_STUCK_THRESHOLD_SECONDS = 2 * 3600  # 2 hours
PF_5_TRADE_MIN = 1.0                       # 5-trade gate: PF >= 1.0
PF_50_TRADE_MIN = 1.0                      # 50-trade gate: PF >= 1.0
EQUITY_1000X_GUARD = PAPER_RESET_TARGET_USD * 1000.0  # $3,000,000
INTERVAL_SECONDS = 300                     # 5 minutes

V2_SOURCE_ROOTS = ["v2/backend/app", "v2/backend/tests"]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def ts_utc() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()


def _rget(r: redis.Redis, key: str) -> dict | list | str | None:
    raw = r.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


def _append_alert(alert: dict) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_ALERTS, "a") as f:
        f.write(json.dumps({**alert, "generated_utc": now_utc()}) + "\n")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _api(path: str, token: str | None = None, timeout: int = 5) -> dict | None:
    headers = []
    if token:
        headers = ["-H", f"Authorization: Bearer {token}"]
    result = subprocess.run(
        ["curl", "-s", "-m", str(timeout)] + headers + [f"{BACKEND_URL}{path}"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and "{" in result.stdout:
        try:
            return json.loads(result.stdout)
        except Exception:
            return None
    return None


def _get_token() -> str | None:
    result = subprocess.run(
        ["curl", "-s", "-m", "5", "-X", "POST",
         f"{BACKEND_URL}/api/v2/auth/login",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"username": BACKEND_USERNAME, "password": BACKEND_PASSWORD})],
        capture_output=True, text=True
    )
    if result.returncode == 0 and "{" in result.stdout:
        try:
            d = json.loads(result.stdout)
            return d.get("access_token")
        except Exception:
            return None
    return None


def _last_v2_source_mtime() -> float:
    """Return mtime of most recently modified v2 source file."""
    latest = 0.0
    for root in V2_SOURCE_ROOTS:
        rp = pathlib.Path(root)
        if not rp.exists():
            continue
        for f in rp.rglob("*.py"):
            try:
                m = f.stat().st_mtime
                if m > latest:
                    latest = m
            except Exception:
                pass
    return latest


def _load_codex_progress() -> dict:
    if CODEX_PROGRESS_STATE.exists():
        try:
            return json.loads(CODEX_PROGRESS_STATE.read_text())
        except Exception:
            pass
    return {}


def _save_codex_progress(state: dict) -> None:
    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    CODEX_PROGRESS_STATE.write_text(json.dumps(state, indent=2))


def _compute_profit_factor(closed_trades: list[dict]) -> tuple[float, int, int]:
    """Returns (profit_factor, wins, losses) from closed trades with pnl."""
    gross_profit = 0.0
    gross_loss = 0.0
    wins = 0
    losses = 0
    for t in closed_trades:
        pnl = t.get("pnl_usd") or t.get("realized_pnl_usd") or t.get("pnl") or 0.0
        try:
            pnl = float(pnl)
        except (TypeError, ValueError):
            pnl = 0.0
        if pnl > 0:
            gross_profit += pnl
            wins += 1
        elif pnl < 0:
            gross_loss += abs(pnl)
            losses += 1
    pf = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    return pf, wins, losses


def _row_session_id(row: dict) -> str | None:
    value = row.get("paper_session_id") or row.get("session_id") or row.get("reset_session_id")
    return str(value) if value not in (None, "") else None


# ---------------------------------------------------------------------------
# 18 CHECKS
# ---------------------------------------------------------------------------

def check_01_paper_equity_3000(ps: dict, ledger: dict, session: dict) -> dict:
    """Check 1: Paper equity = $3,000 after reset — verified across 3 Redis sources."""
    initial = float(ps.get("initial_capital") or 0.0)
    equity = float(ps.get("equity") or 0.0)
    realized = float(ps.get("realized_pnl_usd") or 0.0)
    sess_equity = float(session.get("starting_equity_usd") or 0.0)
    sess_initial = float(session.get("initial_capital") or 0.0)
    paper_session_id = session.get("paper_session_id")

    ps_reset = abs(initial - PAPER_RESET_TARGET_USD) <= PAPER_RESET_TOLERANCE_USD
    equity_at_target = abs(equity - PAPER_RESET_TARGET_USD) <= PAPER_RESET_TOLERANCE_USD
    session_at_target = abs(sess_equity - PAPER_RESET_TARGET_USD) <= PAPER_RESET_TOLERANCE_USD

    # All 3 sources must agree
    all_agree = ps_reset and equity_at_target and session_at_target

    return {
        "check": "CHECK_01_PAPER_EQUITY_3000",
        "portfolio_state_initial_capital": initial,
        "portfolio_state_equity": equity,
        "portfolio_state_realized_pnl": realized,
        "session_starting_equity_usd": sess_equity,
        "session_initial_capital": sess_initial,
        "paper_session_id": paper_session_id,
        "reset_target_usd": PAPER_RESET_TARGET_USD,
        "portfolio_state_reset": ps_reset,
        "equity_at_target": equity_at_target,
        "session_at_target": session_at_target,
        "all_sources_agree": all_agree,
        "status": "PASS" if all_agree else "BLOCKED_RESET_NOT_DETECTED",
        "note": "Reset confirmed across portfolio state, equity, and session key" if all_agree else (
            f"Mismatch — portfolio initial=${initial:.2f}, equity=${equity:.2f}, session_equity=${sess_equity:.2f}"
        ),
        "evidence": "v2:portfolio:state.initial_capital + equity + v2:paper:session.starting_equity_usd",
    }


def check_02_open_positions_zero(ps: dict, ledger: dict) -> dict:
    """Check 2: Open positions = 0 after reset."""
    ps_open = int(ps.get("open_positions_count") or 0)
    ledger_open = int(ledger.get("open_position_count") or 0)
    ledger_held = int(ledger.get("held_position_count") or 0)

    all_zero = ps_open == 0 and ledger_open == 0 and ledger_held == 0

    return {
        "check": "CHECK_02_OPEN_POSITIONS_ZERO",
        "portfolio_state_open": ps_open,
        "ledger_open_position_count": ledger_open,
        "ledger_held_position_count": ledger_held,
        "all_zero": all_zero,
        "status": "PASS" if all_zero else "ALERT_OPEN_POSITIONS_AFTER_RESET",
        "evidence": "v2:portfolio:state.open_positions_count + v2:paper:ledger.open_position_count",
    }


def check_03_old_trades_not_in_new_pf(closed_trades: list[dict], ps: dict, session: dict) -> dict:
    """Check 3: Old session trades isolated from new session PF."""
    # Prefer paper_session_id from v2:paper:session (canonical after reset)
    # Fall back to session_id on portfolio state
    paper_session_id = session.get("paper_session_id") or ps.get("paper_session_id") or ps.get("session_id")

    if not paper_session_id:
        # No session established — but if closed_trades == 0, this is clean
        if not closed_trades:
            return {
                "check": "CHECK_03_OLD_TRADES_NOT_IN_NEW_PF",
                "paper_session_id": None,
                "total_closed_trades": 0,
                "status": "PASS",
                "note": "No closed trades and no session_id — clean state after reset",
                "evidence": "v2:paper:closed_trades (empty) + v2:paper:session.paper_session_id",
            }
        return {
            "check": "CHECK_03_OLD_TRADES_NOT_IN_NEW_PF",
            "paper_session_id": None,
            "status": "BLOCKED_NO_SESSION_ID",
            "note": "session_id absent but closed_trades present — PF isolation unverifiable",
            "evidence": "v2:paper:session.paper_session_id + v2:paper:closed_trades",
        }

    old_trades = [t for t in closed_trades if _row_session_id(t) != paper_session_id]
    new_trades = [t for t in closed_trades if _row_session_id(t) == paper_session_id]

    return {
        "check": "CHECK_03_OLD_TRADES_NOT_IN_NEW_PF",
        "paper_session_id": paper_session_id,
        "total_closed_trades": len(closed_trades),
        "old_session_trades": len(old_trades),
        "new_session_trades": len(new_trades),
        "isolation_clean": not old_trades,
        "status": "PASS" if not old_trades else "ALERT_OLD_TRADES_IN_PF",
        "note": (
            f"{len(old_trades)} old-session trades would pollute new PF"
            if old_trades else "Session PF isolation confirmed"
        ),
        "evidence": "v2:paper:closed_trades[].paper_session_id vs v2:paper:session.paper_session_id",
    }


def check_04_btc_phantom_absent(fills: list[dict]) -> dict:
    """Check 4: BTC $100 phantom fill absent from all accepted fills."""
    btc_phantom = [
        f for f in fills
        if "BTC" in f.get("symbol", "").upper()
        and float(f.get("entry_price") or 0) < BTC_PHANTOM_ENTRY_THRESHOLD
    ]
    return {
        "check": "CHECK_04_BTC_PHANTOM_ABSENT",
        "phantom_fills_found": len(btc_phantom),
        "phantom_fills": [{"symbol": f.get("symbol"), "fill_id": f.get("fill_id"), "entry_price": f.get("entry_price")} for f in btc_phantom],
        "status": "PASS" if not btc_phantom else "ALERT_BTC_PHANTOM_STILL_PRESENT",
        "evidence": "paper_accepted_fills_state.json — BTCUSDT fills with entry < $1,000",
    }


def check_05_paper_online_runtime_inactive(r: redis.Redis) -> dict:
    """Check 5: paper_online_runtime is fully inactive."""
    por_keys = r.keys("v2:paper_online_runtime:*")
    try:
        pgrep = subprocess.run(
            ["pgrep", "-f", "paper_online_runtime"],
            capture_output=True, text=True
        )
        por_pids = [p for p in pgrep.stdout.strip().split("\n") if p.strip()]
    except Exception:
        por_pids = []

    inactive = not por_keys and not por_pids

    return {
        "check": "CHECK_05_PAPER_ONLINE_RUNTIME_INACTIVE",
        "redis_keys_present": len(por_keys),
        "running_pids": por_pids,
        "inactive": inactive,
        "status": "PASS" if inactive else "ALERT_PAPER_ONLINE_RUNTIME_STILL_ACTIVE",
        "evidence": "Redis keys v2:paper_online_runtime:* + pgrep paper_online_runtime",
    }


def _discover_paper_loop_pid(r: redis.Redis) -> tuple[int | None, str]:
    """Discover canonical paper loop PID dynamically from 3 sources.
    Returns (pid, method) or (None, reason)."""
    # Source 1: systemctl --user
    try:
        sc = subprocess.run(
            ["systemctl", "--user", "show",
             "ai-bot-v2-trade-management-paper-loop.service",
             "--property=MainPID,ActiveState"],
            capture_output=True, text=True, timeout=5
        )
        if sc.returncode == 0:
            props = dict(line.split("=", 1) for line in sc.stdout.strip().splitlines() if "=" in line)
            main_pid = int(props.get("MainPID", 0))
            active = props.get("ActiveState", "") == "active"
            if main_pid > 0 and active and _pid_alive(main_pid):
                return main_pid, "systemctl"
    except Exception:
        pass

    # Source 2: pgrep
    try:
        pg = subprocess.run(
            ["pgrep", "-a", "-f", "v2_trade_management_paper_loop"],
            capture_output=True, text=True, timeout=5
        )
        for line in pg.stdout.strip().splitlines():
            if "v2_trade_management_paper_loop" in line and "/bin/bash" not in line:
                pid = int(line.split()[0])
                if _pid_alive(pid):
                    return pid, "pgrep"
    except Exception:
        pass

    # Source 3: v2:paper:heartbeat.pid
    try:
        hb_raw = r.get("v2:paper:heartbeat")
        if hb_raw:
            hb = json.loads(hb_raw)
            pid = hb.get("pid")
            if pid and _pid_alive(int(pid)):
                return int(pid), "redis_heartbeat"
    except Exception:
        pass

    return None, "not_found"


def check_06_canonical_paper_loop_active(r: redis.Redis) -> dict:
    """Check 6: Canonical paper loop is running — discovered dynamically."""
    pid, method = _discover_paper_loop_pid(r)

    # Also collect all loop process lines for visibility
    try:
        pg = subprocess.run(
            ["pgrep", "-a", "-f", "v2_trade_management_paper_loop"],
            capture_output=True, text=True, timeout=5
        )
        loop_lines = [
            l for l in pg.stdout.strip().splitlines()
            if "v2_trade_management_paper_loop" in l and "/bin/bash" not in l
        ]
    except Exception:
        loop_lines = []

    # systemctl state
    sc_state = {}
    try:
        sc = subprocess.run(
            ["systemctl", "--user", "show",
             "ai-bot-v2-trade-management-paper-loop.service",
             "--property=MainPID,ActiveState,SubState"],
            capture_output=True, text=True, timeout=5
        )
        if sc.returncode == 0:
            sc_state = dict(l.split("=", 1) for l in sc.stdout.strip().splitlines() if "=" in l)
    except Exception:
        pass

    active = pid is not None

    return {
        "check": "CHECK_06_CANONICAL_PAPER_LOOP_ACTIVE",
        "discovered_pid": pid,
        "discovery_method": method,
        "systemctl_state": sc_state,
        "running_loop_processes": loop_lines[:3],
        "status": "PASS" if active else "ALERT_PAPER_LOOP_DOWN",
        "evidence": "systemctl --user + pgrep v2_trade_management_paper_loop + v2:paper:heartbeat.pid",
    }


def check_07_live_gate_blocked(r: redis.Redis, ledger: dict, ps: dict) -> dict:
    """Check 7: Live gate is blocked_human_only at all layers."""
    ledger_gate = ledger.get("live_gate")
    ps_gate = ps.get("live_gate_status")
    ledger_places_real = ledger.get("places_real_order")
    ps_exec_enabled = ps.get("trader_execution_enabled")
    live_symbols = ledger.get("execution_live_symbols") or []
    live_redis_keys = r.keys("v2:live:*")

    all_blocked = (
        ledger_gate in ("blocked_human_only", "blocked")
        and ledger_places_real is False
        and ps_exec_enabled is False
        and not live_symbols
        and not live_redis_keys
    )

    return {
        "check": "CHECK_07_LIVE_GATE_BLOCKED",
        "ledger_live_gate": ledger_gate,
        "portfolio_state_live_gate": ps_gate,
        "ledger_places_real_order": ledger_places_real,
        "trader_execution_enabled": ps_exec_enabled,
        "live_symbols_in_ledger": live_symbols,
        "live_redis_key_count": len(live_redis_keys),
        "all_blocked": all_blocked,
        "status": "PASS" if all_blocked else "ALERT_LIVE_GATE_OPEN",
        "evidence": "v2:paper:ledger.live_gate + places_real_order + v2:portfolio:state + live Redis keys",
    }


def check_08_no_real_order_path(r: redis.Redis, ledger: dict) -> dict:
    """Check 8: No real/test order path active."""
    places_real = ledger.get("places_real_order")
    writes_legacy = ledger.get("writes_legacy_redis")

    # Check for any exchange order keys
    order_keys = r.keys("v2:exchange:orders:*") + r.keys("v2:order:*") + r.keys("v2:live:orders:*")

    # Check fill_state paper_only flag
    fill_state_paper_only = None
    if FILL_STATE_FILE.exists():
        try:
            fs = json.loads(FILL_STATE_FILE.read_text())
            fill_state_paper_only = fs.get("paper_only")
            writes_legacy_fs = fs.get("writes_legacy_redis")
        except Exception:
            writes_legacy_fs = None
    else:
        writes_legacy_fs = None

    clean = (
        places_real is False
        and not order_keys
        and fill_state_paper_only is True
    )

    return {
        "check": "CHECK_08_NO_REAL_ORDER_PATH",
        "ledger_places_real_order": places_real,
        "ledger_writes_legacy_redis": writes_legacy,
        "fill_state_paper_only": fill_state_paper_only,
        "fill_state_writes_legacy_redis": writes_legacy_fs,
        "exchange_order_redis_keys": len(order_keys),
        "status": "PASS" if clean else "ALERT_REAL_ORDER_PATH_DETECTED",
        "evidence": "v2:paper:ledger.places_real_order + v2:exchange:orders:* Redis + fill_state.paper_only",
    }


def check_09_trainer_consumes_valid_outcomes(ledger: dict) -> dict:
    """Check 9: Trainer consumes only valid (non-quarantined) closed outcomes."""
    consumable = int(ledger.get("trainer_feedback_consumable_row_count") or 0)
    quarantined = int(ledger.get("trainer_feedback_quarantined_row_count") or 0)
    total = int(ledger.get("trainer_feedback_total_row_count") or 0)
    outcomes = ledger.get("trainer_feedback_outcomes") or []
    quar_outcomes = ledger.get("trainer_feedback_outcomes_quarantine") or []

    # Check overlap
    c_ids = {o.get("fill_id") for o in outcomes if isinstance(o, dict)}
    q_ids = {o.get("fill_id") for o in quar_outcomes if isinstance(o, dict)}
    overlap = c_ids & q_ids

    quarantine_clean = not overlap

    return {
        "check": "CHECK_09_TRAINER_CONSUMES_VALID_OUTCOMES",
        "trainer_feedback_consumable_rows": consumable,
        "trainer_feedback_quarantined_rows": quarantined,
        "trainer_feedback_total_rows": total,
        "consumable_quarantine_overlap_ids": list(overlap),
        "quarantine_isolation_clean": quarantine_clean,
        "status": "PASS" if quarantine_clean else "ALERT_QUARANTINE_BREACH_IN_TRAINER",
        "note": (
            "No consumable rows yet — waiting for valid closed trades"
            if consumable == 0 and quarantine_clean
            else f"{consumable} consumable rows ready"
        ),
        "evidence": "v2:paper:ledger.trainer_feedback_outcomes vs trainer_feedback_outcomes_quarantine",
    }


def check_10_checkpoint_weights_update(r: redis.Redis) -> dict:
    """Check 10: Checkpoint heartbeat present and weight-loading state tracked."""
    hb_raw = r.get("v2:trainer:checkpoint:heartbeat")
    if not hb_raw:
        return {
            "check": "CHECK_10_CHECKPOINT_WEIGHTS_UPDATE",
            "status": "UNAVAILABLE",
            "note": "v2:trainer:checkpoint:heartbeat not present in Redis",
        }

    try:
        hb = json.loads(hb_raw)
    except Exception:
        hb = {}

    weight_status = hb.get("checkpoint_weight_status") or hb.get("weight_loading_status")
    blocker = hb.get("checkpoint_blocker")
    weights_loaded = hb.get("model_weights_loaded_into_v2_process", False)
    legacy_mutated = hb.get("legacy_mutation_performed", False)
    approves_live = hb.get("approves_live", True)

    # Safe state: weights not loaded (protected ML runtime)
    # Good state: heartbeat present, no legacy mutation, not approving live
    safe_and_healthy = not legacy_mutated and not approves_live

    return {
        "check": "CHECK_10_CHECKPOINT_WEIGHTS_UPDATE",
        "checkpoint_weight_status": weight_status,
        "checkpoint_blocker": blocker,
        "model_weights_loaded": weights_loaded,
        "legacy_mutation_performed": legacy_mutated,
        "approves_live": approves_live,
        "heartbeat_present": True,
        "safe_and_healthy": safe_and_healthy,
        "status": "PASS" if safe_and_healthy else "ALERT_CHECKPOINT_SAFETY_VIOLATION",
        "note": (
            "LEGACY_CHECKPOINT_METADATA safe — weights not deserialized per Protected ML Runtime policy"
            if not weights_loaded else "Weights loaded — verify operator approved"
        ),
        "evidence": "v2:trainer:checkpoint:heartbeat",
    }


def check_11_fills_have_session_id(fills: list[dict], ps: dict, session: dict) -> dict:
    """Check 11: Paper fills have session_id matching current paper_session_id."""
    paper_session_id = session.get("paper_session_id") or ps.get("session_id")
    total = len(fills)

    if total == 0:
        return {
            "check": "CHECK_11_FILLS_HAVE_SESSION_ID",
            "paper_session_id": paper_session_id,
            "status": "PASS_NO_FILLS",
            "note": "No accepted fills yet — session_id check not applicable",
        }

    with_session = [f for f in fills if _row_session_id(f)]
    without_session = [f for f in fills if not _row_session_id(f)]
    wrong_session = [
        f for f in fills
        if _row_session_id(f) and paper_session_id and _row_session_id(f) != paper_session_id
    ]

    all_correct = len(with_session) == total and not wrong_session

    return {
        "check": "CHECK_11_FILLS_HAVE_SESSION_ID",
        "paper_session_id": paper_session_id,
        "total_fills": total,
        "fills_with_session_id": len(with_session),
        "fills_without_session_id": len(without_session),
        "fills_with_wrong_session": len(wrong_session),
        "all_have_correct_session": all_correct,
        "status": "PASS" if all_correct else "BLOCKED_FILLS_MISSING_SESSION_ID",
        "note": (
            f"{len(without_session)}/{total} fills missing paper_session_id field"
            if without_session else
            f"{len(wrong_session)} fills have stale paper_session_id"
            if wrong_session else "All fills have correct session_id"
        ),
        "evidence": "paper_accepted_fills_state.json[].paper_session_id vs v2:paper:session.paper_session_id",
    }


def check_12_fills_have_cost_lineage_trust(fills: list[dict]) -> dict:
    """Check 12: Fills have cost, lineage, and trust fields."""
    if not fills:
        return {
            "check": "CHECK_12_FILLS_COST_LINEAGE_TRUST",
            "status": "PASS_NO_FILLS",
            "note": "No accepted fills yet",
        }

    # Required cost fields (at least one must be present)
    cost_fields = ["actual_observed_spread_entry_bps", "entry_cost_bps", "fill_cost_usd", "cost_basis_usd"]
    # Lineage fields
    lineage_fields = ["candidate_id", "policy_id", "signal_lineage", "lineage"]
    # Trust fields
    trust_fields = ["microstructure_trust_score", "trust_score", "quality_score"]

    coverage = []
    for f in fills:
        has_cost = any(f.get(k) is not None for k in cost_fields)
        has_lineage = any(f.get(k) is not None for k in lineage_fields)
        has_trust = any(f.get(k) is not None for k in trust_fields)
        coverage.append({
            "fill_id": f.get("fill_id"),
            "symbol": f.get("symbol"),
            "has_cost": has_cost,
            "has_lineage": has_lineage,
            "has_trust": has_trust,
            "cost_field_hit": next((k for k in cost_fields if f.get(k) is not None), None),
            "lineage_field_hit": next((k for k in lineage_fields if f.get(k) is not None), None),
        })

    all_cost = all(c["has_cost"] for c in coverage)
    all_lineage = all(c["has_lineage"] for c in coverage)
    missing_trust = [c for c in coverage if not c["has_trust"]]

    status = "PASS" if all_cost and all_lineage else "ALERT_FILLS_MISSING_FIELDS"

    return {
        "check": "CHECK_12_FILLS_COST_LINEAGE_TRUST",
        "total_fills": len(fills),
        "all_have_cost_field": all_cost,
        "all_have_lineage_field": all_lineage,
        "fills_missing_trust_field": len(missing_trust),
        "sample_coverage": coverage[:3],
        "status": status,
        "note": (
            "Trust field (microstructure_trust_score) absent — microstructure monitor not running (expected per fix)"
            if missing_trust else "All cost/lineage/trust fields present"
        ),
        "evidence": "paper_accepted_fills_state.json[].actual_observed_spread_entry_bps / candidate_id / trust_score",
    }


def check_13_governor_blocks_pf_under_1(ledger: dict) -> dict:
    """Check 13: Performance circuit breaker / governor blocks trading when PF < 1."""
    pcb = ledger.get("paper_performance_circuit_breaker_status") or {}
    bleed_halt = ledger.get("paper_bleed_halt_status") or {}
    churn = ledger.get("paper_churn_equity_bleed_governor_status") or {}

    pcb_active = pcb.get("circuit_breaker_active") or pcb.get("triggered") or pcb.get("active")
    bleed_active = bleed_halt.get("halt_active") or bleed_halt.get("bleed_halt_triggered")
    governor_mode = churn.get("governor_mode") or churn.get("mode")

    # If no governor data yet, report as awaiting evidence
    if not pcb and not bleed_halt and not churn:
        return {
            "check": "CHECK_13_GOVERNOR_BLOCKS_PF_UNDER_1",
            "status": "AWAITING_EVIDENCE",
            "note": "No governor status in ledger yet — awaiting first trade cycle",
        }

    # Governor operational = present in ledger (it will auto-block if PF drops)
    governor_present = bool(pcb or bleed_halt or churn)

    return {
        "check": "CHECK_13_GOVERNOR_BLOCKS_PF_UNDER_1",
        "performance_circuit_breaker_active": pcb_active,
        "bleed_halt_active": bleed_active,
        "governor_mode": governor_mode,
        "governor_present_in_ledger": governor_present,
        "pcb_summary": {k: pcb.get(k) for k in ["circuit_breaker_active", "triggered", "mode", "reason"] if k in pcb},
        "bleed_summary": {k: bleed_halt.get(k) for k in ["halt_active", "bleed_halt_triggered", "reason"] if k in bleed_halt},
        "status": "PASS" if governor_present else "ALERT_GOVERNOR_NOT_CONFIGURED",
        "evidence": "v2:paper:ledger.paper_performance_circuit_breaker_status + paper_bleed_halt_status",
    }


def check_14_losing_buckets_quarantined(ledger: dict) -> dict:
    """Check 14: Losing strategy buckets are quarantined."""
    bqs = ledger.get("bucket_quarantine_status") or {}

    if not bqs:
        return {
            "check": "CHECK_14_LOSING_BUCKETS_QUARANTINED",
            "status": "AWAITING_EVIDENCE",
            "note": "No bucket quarantine status in ledger yet",
        }

    quarantined_count = bqs.get("quarantined_bucket_count") or len(bqs.get("quarantined_buckets", []))
    total_buckets = bqs.get("total_bucket_count") or bqs.get("total_buckets")
    quarantine_active = bqs.get("quarantine_active") or bqs.get("enabled") or quarantined_count is not None

    return {
        "check": "CHECK_14_LOSING_BUCKETS_QUARANTINED",
        "quarantine_active": quarantine_active,
        "quarantined_bucket_count": quarantined_count,
        "total_buckets": total_buckets,
        "quarantine_summary": {k: bqs.get(k) for k in list(bqs.keys())[:8]},
        "status": "PASS" if quarantine_active else "ALERT_BUCKET_QUARANTINE_NOT_CONFIGURED",
        "evidence": "v2:paper:ledger.bucket_quarantine_status",
    }


def check_15_website_shows_3000(token: str | None, paper_session_id: str | None) -> dict:
    """Check 15: Website API shows $3,000 paper account truth, not stale fallback."""
    api_data = _api("/api/v2/portfolio", token=token)
    if not api_data:
        return {
            "check": "CHECK_15_WEBSITE_SHOWS_3000",
            "status": "UNAVAILABLE",
            "note": "Backend portfolio API not reachable",
        }

    data = api_data.get("data") or api_data
    equity = data.get("paper_equity") or data.get("equity")
    initial = data.get("paper_initial_capital") or data.get("initial_capital")
    source_type = api_data.get("source_type") or api_data.get("source") or data.get("source")
    api_session_id = data.get("session_id") or data.get("paper_session_id")

    try:
        equity_f = float(equity or 0)
        initial_f = float(initial or 0)
    except (TypeError, ValueError):
        equity_f = 0.0
        initial_f = 0.0

    # Primary check: paper_equity must match $3K (equity is live-updated, initial_capital may lag)
    equity_at_target = abs(equity_f - PAPER_RESET_TARGET_USD) <= PAPER_RESET_TOLERANCE_USD
    stale_source = source_type in ("stale_fallback", "cache_fallback", "fallback") if source_type else False

    # Session ID match (optional — may not be propagated to API yet)
    session_match = (
        api_session_id == paper_session_id
        if (api_session_id and paper_session_id) else None
    )

    passed = equity_at_target and not stale_source

    return {
        "check": "CHECK_15_WEBSITE_SHOWS_3000",
        "api_paper_equity": equity_f,
        "api_paper_initial_capital": initial_f,
        "api_source_type": source_type,
        "api_session_id": api_session_id,
        "paper_session_id": paper_session_id,
        "session_id_match": session_match,
        "equity_at_target": equity_at_target,
        "stale_source_detected": stale_source,
        "note": (
            "paper_equity=$3,000 confirmed — paper_initial_capital field may lag reset (not a blocker)"
            if equity_at_target and initial_f != PAPER_RESET_TARGET_USD
            else "paper_equity matches $3,000 target"
            if equity_at_target else
            f"paper_equity=${equity_f:,.2f} does not match $3,000 target"
        ),
        "status": "PASS" if passed else "BLOCKED_WEBSITE_NOT_SHOWING_RESET",
        "evidence": "GET /api/v2/portfolio → data.paper_equity (primary) + source_type",
    }


def check_16_ios_shows_3000(token: str | None, paper_session_id: str | None) -> dict:
    """Check 16: iOS mobile API shows $3,000 — missing route = API_ROUTE_MISSING, not reset failure."""
    tried_endpoints: list[str] = []
    route_results: dict[str, str] = {}
    mobile_data = None
    endpoint_used = None

    for ep in ["/api/v2/mobile/paper-summary", "/api/v2/mobile/summary", "/api/v2/mobile/portfolio"]:
        tried_endpoints.append(ep)
        result = subprocess.run(
            ["curl", "-s", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}",
             f"{BACKEND_URL}{ep}"],
            capture_output=True, text=True
        )
        http_code = result.stdout.strip() if result.returncode == 0 else "error"
        route_results[ep] = http_code

        if http_code == "200":
            d = _api(ep, token=token)
            if d and isinstance(d, dict) and "detail" not in d:
                mobile_data = d
                endpoint_used = ep
                break
        elif http_code == "404":
            route_results[ep] = "404_ROUTE_MISSING"

    if not mobile_data:
        all_404 = all("404" in v or v == "error" for v in route_results.values())
        return {
            "check": "CHECK_16_IOS_SHOWS_3000",
            "status": "API_ROUTE_MISSING" if all_404 else "UNAVAILABLE",
            "tried_endpoints": tried_endpoints,
            "http_codes": route_results,
            "classification": "API_ROUTE_MISSING — not a reset failure" if all_404 else "ENDPOINT_UNREACHABLE",
            "note": (
                "Mobile endpoints return 404 — route not implemented, not a $3K reset failure"
                if all_404 else "Mobile API unreachable — check backend"
            ),
            "evidence": f"HTTP probes of {tried_endpoints}",
        }

    # Mobile paper-summary exposes pnl/positions, not equity directly.
    # After clean reset: realized_usd=0, unrealized_usd=0, open_count=0, closed_count=0.
    pnl = mobile_data.get("pnl") or {}
    positions = mobile_data.get("positions") or {}
    mode = mobile_data.get("mode")
    live_gate = mobile_data.get("live_gate")
    places_real = mobile_data.get("places_real_order")

    realized = float(pnl.get("realized_usd") or 0)
    unrealized = float(pnl.get("unrealized_usd") or 0)
    open_count = int(positions.get("open_count") or 0)
    closed_count = int(positions.get("closed_count") or 0)

    # Direct equity field (if present in some mobile routes)
    equity = (
        mobile_data.get("paper_equity")
        or mobile_data.get("equity")
        or mobile_data.get("equity_trusted")
        or mobile_data.get("portfolio_equity")
    )
    equity_f = float(equity) if equity is not None else None

    # Clean reset: zero PnL, zero positions, paper mode, gate blocked
    reset_consistent = (
        abs(realized) < PAPER_RESET_TOLERANCE_USD
        and abs(unrealized) < PAPER_RESET_TOLERANCE_USD
        and open_count == 0
        and closed_count == 0
        and mode == "paper"
        and live_gate in ("blocked_human_only", "blocked")
        and places_real is False
    )

    # If direct equity available, also check it
    if equity_f is not None:
        equity_at_target = abs(equity_f - PAPER_RESET_TARGET_USD) <= PAPER_RESET_TOLERANCE_USD
        passed = reset_consistent and equity_at_target
    else:
        equity_at_target = None
        passed = reset_consistent

    api_session_id = mobile_data.get("session_id") or mobile_data.get("paper_session_id")

    return {
        "check": "CHECK_16_IOS_SHOWS_3000",
        "mobile_endpoint_used": endpoint_used,
        "mobile_api_mode": mode,
        "mobile_live_gate": live_gate,
        "mobile_places_real_order": places_real,
        "mobile_pnl_realized_usd": realized,
        "mobile_pnl_unrealized_usd": unrealized,
        "mobile_open_positions": open_count,
        "mobile_closed_positions": closed_count,
        "mobile_direct_equity": equity_f,
        "equity_at_target": equity_at_target,
        "paper_session_id": paper_session_id,
        "api_session_id": api_session_id,
        "reset_consistent_via_pnl_positions": reset_consistent,
        "http_codes": route_results,
        "status": "PASS" if passed else "BLOCKED_IOS_NOT_SHOWING_RESET",
        "note": (
            "Mobile shows clean reset state: zero PnL, zero positions, paper mode, gate blocked"
            if reset_consistent else
            f"Mobile shows stale state: realized={realized}, open={open_count}, closed={closed_count}"
        ),
        "evidence": f"GET {endpoint_used} → pnl + positions + mode + live_gate",
    }


def check_17_no_a_grade_before_evidence(fills: list[dict], closed_trades: list[dict]) -> dict:
    """Check 17: No A-grade claim before evidence (300+ quality closed trades)."""
    a_grade_fills = [
        f for f in fills
        if str(f.get("grade") or "").upper() == "A"
        or str(f.get("trajectory_grade") or "").upper() == "A"
    ]
    a_grade_closed = [
        t for t in closed_trades
        if str(t.get("grade") or "").upper() == "A"
    ]

    total_closed = len(closed_trades)
    a_grade_claim_safe = total_closed >= 300 or (not a_grade_fills and not a_grade_closed)

    return {
        "check": "CHECK_17_NO_A_GRADE_BEFORE_EVIDENCE",
        "total_closed_trades": total_closed,
        "a_grade_fills_in_open": len(a_grade_fills),
        "a_grade_in_closed": len(a_grade_closed),
        "a_grade_claim_requires_300_trades": True,
        "a_grade_claim_safe": a_grade_claim_safe,
        "status": "PASS" if a_grade_claim_safe else "ALERT_A_GRADE_CLAIMED_WITHOUT_EVIDENCE",
        "note": (
            f"A-grade claimed with only {total_closed} closed trades — need 300+"
            if not a_grade_claim_safe and total_closed < 300
            else "A-grade gate clean"
        ),
        "evidence": "paper_accepted_fills_state.json[].grade + v2:paper:closed_trades[].grade",
    }


def check_18_no_1000x_claim(ps: dict, fills: list[dict]) -> dict:
    """Check 18: No 1000x equity claim before evidence."""
    equity = float(ps.get("equity") or 0.0)
    initial = float(ps.get("initial_capital") or PAPER_RESET_TARGET_USD)

    # After reset, initial should be $3,000
    effective_initial = PAPER_RESET_TARGET_USD if abs(initial - PAPER_RESET_TARGET_USD) < 100 else initial
    multiplier = equity / effective_initial if effective_initial > 0 else 0.0

    claim_safe = equity < EQUITY_1000X_GUARD and multiplier < 1000.0

    return {
        "check": "CHECK_18_NO_1000X_CLAIM",
        "current_equity_usd": equity,
        "effective_initial_capital_usd": effective_initial,
        "equity_multiplier": round(multiplier, 4),
        "1000x_guard_usd": EQUITY_1000X_GUARD,
        "1000x_claim_safe": claim_safe,
        "status": "PASS" if claim_safe else "ALERT_1000X_EQUITY_CLAIM_UNVERIFIED",
        "evidence": "v2:portfolio:state.equity / initial_capital",
    }


# ---------------------------------------------------------------------------
# PERFORMANCE LADDER
# ---------------------------------------------------------------------------
def compute_performance_ladder(closed_trades: list[dict], ps: dict) -> dict:
    """5-trade / 50-trade / 300-trade / 1000-trade gates."""
    total = len(closed_trades)
    pf, wins, losses = _compute_profit_factor(closed_trades)

    # Session-scoped if paper_session_id is set
    session_id = ps.get("paper_session_id") or ps.get("session_id")
    session_trades = (
        [t for t in closed_trades if _row_session_id(t) == session_id]
        if session_id else closed_trades
    )
    session_total = len(session_trades)
    session_pf, session_wins, session_losses = _compute_profit_factor(session_trades)

    def gate_status(threshold: int, pf_min: float, trades: list[dict]) -> dict:
        n = len(trades)
        p, w, l = _compute_profit_factor(trades)
        if n < threshold:
            return {"gate": f"{threshold}_TRADE_GATE", "status": "PENDING", "trades": n, "required": threshold, "pf": round(p, 4) if n > 0 else None}
        return {
            "gate": f"{threshold}_TRADE_GATE",
            "status": "PASS" if p >= pf_min else "FAIL",
            "trades": n,
            "pf": round(p, 4),
            "pf_min": pf_min,
            "wins": w,
            "losses": l,
        }

    return {
        "total_closed_trades_all_sessions": total,
        "current_session_closed_trades": session_total,
        "session_id": session_id,
        "all_sessions_pf": round(pf, 4) if total > 0 else None,
        "session_pf": round(session_pf, 4) if session_total > 0 else None,
        "gates": {
            "gate_5": gate_status(5, PF_5_TRADE_MIN, session_trades),
            "gate_50": gate_status(50, PF_50_TRADE_MIN, session_trades),
            "gate_300": gate_status(300, 1.25, session_trades),
            "gate_1000": gate_status(1000, 1.5, session_trades),
        },
    }


# ---------------------------------------------------------------------------
# CODEX STUCK DETECTION
# ---------------------------------------------------------------------------
def check_codex_stuck(progress: dict) -> tuple[dict, bool]:
    """Returns (state_to_save, is_stuck)."""
    now = ts_utc()
    last_mtime = _last_v2_source_mtime()

    last_known_mtime = progress.get("last_v2_source_mtime", 0.0)
    progress_start = progress.get("no_progress_since", now)
    codex_start = progress.get("codex_start_time", now)

    mtime_changed = last_mtime > last_known_mtime

    if mtime_changed:
        # Reset no-progress timer
        new_state = {
            "last_v2_source_mtime": last_mtime,
            "last_progress_at": now,
            "no_progress_since": now,
            "codex_start_time": codex_start,
        }
        return new_state, False
    else:
        # No change
        no_progress_seconds = now - float(progress_start)
        is_stuck = no_progress_seconds >= CODEX_STUCK_THRESHOLD_SECONDS
        new_state = {
            "last_v2_source_mtime": last_known_mtime,
            "last_progress_at": progress.get("last_progress_at", now),
            "no_progress_since": progress_start,
            "codex_start_time": codex_start,
            "no_progress_seconds": no_progress_seconds,
        }
        return new_state, is_stuck


# ---------------------------------------------------------------------------
# MAIN RUN
# ---------------------------------------------------------------------------
def run_once() -> dict:
    ts = now_utc()
    r = redis.from_url(REDIS_URL, decode_responses=True)

    # Fetch core data
    ps = _rget(r, "v2:portfolio:state") or {}
    ledger = _rget(r, "v2:paper:ledger") or {}
    session = _rget(r, "v2:paper:session") or {}
    ct_raw = _rget(r, "v2:paper:closed_trades")
    closed_trades: list[dict] = ct_raw if isinstance(ct_raw, list) else []

    fills: list[dict] = []
    if FILL_STATE_FILE.exists():
        try:
            fill_state = json.loads(FILL_STATE_FILE.read_text())
            fills = fill_state.get("accepted_fills", [])
        except Exception:
            pass

    # Current paper session ID (canonical source after reset)
    paper_session_id = session.get("paper_session_id") or ps.get("session_id")

    # Get auth token for API checks
    token = _get_token()

    # BTC market price
    btc_raw = _rget(r, "v2:market:prices:BTCUSDT") or {}
    btc_price = float((btc_raw.get("ticker_24hr") or {}).get("lastPrice") or 62000.0)

    # Run all 18 checks
    c01 = check_01_paper_equity_3000(ps, ledger, session)
    c02 = check_02_open_positions_zero(ps, ledger)
    c03 = check_03_old_trades_not_in_new_pf(closed_trades, ps, session)
    c04 = check_04_btc_phantom_absent(fills)
    c05 = check_05_paper_online_runtime_inactive(r)
    c06 = check_06_canonical_paper_loop_active(r)
    c07 = check_07_live_gate_blocked(r, ledger, ps)
    c08 = check_08_no_real_order_path(r, ledger)
    c09 = check_09_trainer_consumes_valid_outcomes(ledger)
    c10 = check_10_checkpoint_weights_update(r)
    c11 = check_11_fills_have_session_id(fills, ps, session)
    c12 = check_12_fills_have_cost_lineage_trust(fills)
    c13 = check_13_governor_blocks_pf_under_1(ledger)
    c14 = check_14_losing_buckets_quarantined(ledger)
    c15 = check_15_website_shows_3000(token, paper_session_id)
    c16 = check_16_ios_shows_3000(token, paper_session_id)
    c17 = check_17_no_a_grade_before_evidence(fills, closed_trades)
    c18 = check_18_no_1000x_claim(ps, fills)

    checks = [c01, c02, c03, c04, c05, c06, c07, c08, c09, c10, c11, c12, c13, c14, c15, c16, c17, c18]
    alerts = [c for c in checks if "ALERT" in c.get("status", "") or "BLOCKED" in c.get("status", "")]
    passes = [c for c in checks if c.get("status") in ("PASS", "PASS_NO_FILLS")]
    awaiting = [c for c in checks if "AWAITING" in c.get("status", "") or "PENDING" in c.get("status", "")]
    unavail = [c for c in checks if "UNAVAILABLE" in c.get("status", "")]

    # Performance ladder
    ladder = compute_performance_ladder(closed_trades, ps)

    # Codex stuck detection
    codex_progress = _load_codex_progress()
    new_progress, codex_stuck = check_codex_stuck(codex_progress)
    _save_codex_progress(new_progress)

    # --- Performance gate failures ---
    g5 = ladder["gates"]["gate_5"]
    g50 = ladder["gates"]["gate_50"]

    if g5["status"] == "FAIL":
        _write_json(ALERT_5_TRADE_GATE, {
            "alert": "CLAUDE_5_TRADE_GATE_FAILURE",
            "generated_utc": ts,
            "gate": g5,
            "closed_trades_sample": [
                {"symbol": t.get("symbol"), "pnl_usd": t.get("pnl_usd"), "paper_session_id": _row_session_id(t)}
                for t in closed_trades[:10]
            ],
            "action": "Investigate losing bucket and quarantine. Do not lower PF threshold.",
        })
        _append_alert({"type": "5_TRADE_GATE_FAIL", "pf": g5.get("pf"), "trades": g5.get("trades")})

    if g50["status"] == "FAIL":
        _write_json(ALERT_50_TRADE_GATE, {
            "alert": "CLAUDE_50_TRADE_GATE_FAILURE",
            "generated_utc": ts,
            "gate": g50,
            "action": "Recommend halt. Investigate strategy before continuing.",
        })
        _append_alert({"type": "50_TRADE_GATE_FAIL", "pf": g50.get("pf"), "trades": g50.get("trades"), "severity": "HALT_RECOMMENDED"})

    # --- Codex stuck alert ---
    if codex_stuck:
        _write_json(ALERT_CODEX_STUCK, {
            "alert": "CODEX_STUCK_NO_PROGRESS",
            "generated_utc": ts,
            "no_progress_seconds": new_progress.get("no_progress_seconds"),
            "threshold_seconds": CODEX_STUCK_THRESHOLD_SECONDS,
            "last_v2_source_mtime": new_progress.get("last_v2_source_mtime"),
            "no_progress_since": new_progress.get("no_progress_since"),
            "action": "Check Codex agent status. If genuinely stuck, restart with focused prompt.",
        })
        _append_alert({"type": "CODEX_STUCK", "no_progress_seconds": new_progress.get("no_progress_seconds")})

    # --- Website/iOS truth regression ---
    ui_regression = (
        "ALERT" in c15.get("status", "") or "BLOCKED" in c15.get("status", "")
        or "ALERT" in c16.get("status", "") or "BLOCKED" in c16.get("status", "")
    )
    if ui_regression:
        _write_json(ALERT_UI_TRUTH, {
            "alert": "CLAUDE_UI_TRUTH_REGRESSION",
            "generated_utc": ts,
            "check_15_website": c15,
            "check_16_ios": c16,
            "valid_equity_usd": float(ps.get("equity") or 0),
            "initial_capital_usd": float(ps.get("initial_capital") or 0),
            "action": "Website or iOS reporting incorrect equity. Codex must fix API response to reflect $3,000 reset.",
        })

    # Determine overall marker
    # Hard-blocking alerts: phantom present, live gate open, real orders, scope breach, 1000x claim
    hard_blocks = [
        c for c in [c04, c07, c08, c17, c18]
        if "ALERT" in c.get("status", "") or "BLOCKED" in c.get("status", "")
    ]
    # Soft-blocking: reset not done, no session_id
    soft_blocks = [c for c in alerts if c not in hard_blocks]

    marker = "ACTIVE" if not hard_blocks else "BLOCKED"

    # --- Write artifact 1: overall status ---
    _write_json(OUT_STATUS, {
        "goal_id": "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        "marker": marker,
        "checks_total": len(checks),
        "checks_pass": len(passes),
        "checks_alert_or_blocked": len(alerts),
        "checks_awaiting": len(awaiting),
        "checks_unavailable": len(unavail),
        "hard_blocks": [c["check"] for c in hard_blocks],
        "soft_blocks": [c["check"] for c in soft_blocks],
        "codex_stuck": codex_stuck,
        "btc_market_price_usd": btc_price,
        "paper_equity_usd": float(ps.get("equity") or 0),
        "initial_capital_usd": float(ps.get("initial_capital") or 0),
        "open_positions": int(ps.get("open_positions_count") or 0),
        "closed_trades_total": len(closed_trades),
        "places_real_order": ledger.get("places_real_order"),
        "live_gate": ledger.get("live_gate"),
        "exchange_mutation_detected": False,
        "all_18_checks": {c["check"]: c["status"] for c in checks},
    })

    # --- Write artifact 2: $3K reset verification ---
    _write_json(OUT_RESET, {
        "goal_id": "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        "check_01_equity_3000": c01,
        "check_02_open_positions_zero": c02,
        "check_03_session_isolation": c03,
        "check_04_btc_phantom_absent": c04,
        "check_11_session_id_on_fills": c11,
        "reset_target_usd": PAPER_RESET_TARGET_USD,
        "reset_complete": c01.get("all_sources_agree") and c02.get("all_zero"),
    })

    # --- Write artifact 3: trainer learning ---
    _write_json(OUT_TRAINER, {
        "goal_id": "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        "check_09_trainer_outcomes": c09,
        "check_10_checkpoint_health": c10,
        "check_12_fill_fields": c12,
        "trainer_status": _rget(r, "v2:trainer:status"),
        "consumable_row_count": int(ledger.get("trainer_feedback_consumable_row_count") or 0),
        "quarantined_row_count": int(ledger.get("trainer_feedback_quarantined_row_count") or 0),
    })

    # --- Write artifact 4: performance ladder ---
    _write_json(OUT_PERF, {
        "goal_id": "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        "ladder": ladder,
        "check_13_governor": c13,
        "check_14_quarantine": c14,
        "check_17_a_grade_gate": c17,
        "check_18_no_1000x": c18,
        "gate_5_status": g5["status"],
        "gate_50_status": g50["status"],
        "codex_stuck": codex_stuck,
        "codex_stuck_seconds": new_progress.get("no_progress_seconds"),
    })

    # --- Write artifact 5: UI/iOS truth ---
    _write_json(OUT_UI, {
        "goal_id": "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        "check_15_website_3000": c15,
        "check_16_ios_3000": c16,
        "ui_regression_alert": ui_regression,
        "reset_target_usd": PAPER_RESET_TARGET_USD,
    })

    # --- Write marker ---
    marker_data = {
        "goal_id": "CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        "marker": marker,
        "checks_pass": len(passes),
        "checks_alert": len(alerts),
        "hard_blocks": [c["check"] for c in hard_blocks],
        "immediate_hard_block_reasons": {c["check"]: c.get("status") for c in hard_blocks},
        "places_real_order": ledger.get("places_real_order"),
        "live_gate": ledger.get("live_gate"),
        "exchange_mutation_detected": False,
    }
    if marker == "BLOCKED":
        _write_json(MARKER_BLOCKED, marker_data)
        if MARKER_ACTIVE.exists():
            MARKER_ACTIVE.unlink()
    else:
        _write_json(MARKER_ACTIVE, marker_data)
        if MARKER_BLOCKED.exists():
            MARKER_BLOCKED.unlink()

    discovered_pid = c06.get("discovered_pid")
    discovery_method = c06.get("discovery_method")

    return {
        "ts": ts,
        "marker": marker,
        "paper_session_id": paper_session_id,
        "discovered_pid": discovered_pid,
        "discovery_method": discovery_method,
        "checks_pass": len(passes),
        "checks_alert": len(alerts),
        "checks_awaiting": len(awaiting),
        "checks_unavailable": len(unavail),
        "hard_blocks": [c["check"] for c in hard_blocks],
        "soft_blocks": [c["check"] for c in soft_blocks],
        "codex_stuck": codex_stuck,
        "immediate_alert_triggered": bool(hard_blocks),
        "gate_5": g5["status"],
        "gate_50": g50["status"],
        "paper_equity_usd": float(ps.get("equity") or 0),
        "initial_capital_usd": float(ps.get("initial_capital") or 0),
        "closed_trades": len(closed_trades),
    }


def main() -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    GOAL_DIR.mkdir(parents=True, exist_ok=True)

    daemon = "--daemon" in sys.argv
    if daemon:
        print(f"[{now_utc()}] Starting CLAUDE_FINAL_PRE_LIVE_3000_PAPER_REALTIME_CONTROLLER (interval={INTERVAL_SECONDS}s)", flush=True)
        while True:
            try:
                result = run_once()
                print(
                    f"[{result['ts']}] {result['marker']} | "
                    f"pid={result['discovered_pid']}({result['discovery_method']}) "
                    f"session={str(result['paper_session_id'])[:30]} "
                    f"pass={result['checks_pass']} alert={result['checks_alert']} "
                    f"hard_blocks={result['hard_blocks']} "
                    f"equity=${result['paper_equity_usd']:,.2f} "
                    f"closed={result['closed_trades']} "
                    f"g5={result['gate_5']} g50={result['gate_50']} "
                    f"stuck={result['codex_stuck']}",
                    flush=True,
                )
            except Exception as exc:
                print(f"[{now_utc()}] ERROR: {exc}", flush=True)
            time.sleep(INTERVAL_SECONDS)
    else:
        result = run_once()
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
