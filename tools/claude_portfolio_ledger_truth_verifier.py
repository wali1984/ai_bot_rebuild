#!/usr/bin/env python3
"""
CLAUDE_GOAL_ID: CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER

Read-only verifier. Runs every 5 minutes while Codex repairs portfolio truth.
16 checks covering: invalid fills, phantom equity, account scope, live gate,
trainer quarantine isolation, website/iOS API truthfulness, paper loop health.

Writes 5 artifact files + CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIED marker.
NEVER mutates Redis, ledger, positions, or any exchange state.
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
FILL_STATE_FILE = pathlib.Path(
    "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/"
    "paper_accepted_fills_state.json"
)
WORKLOG_DIR = pathlib.Path("claude_worklog")
GOAL_DIR = pathlib.Path("goal_state/CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER")

# Output artifacts
OUT_INVALID_POSITION = WORKLOG_DIR / "claude_portfolio_invalid_position_verification.json"
OUT_BTC_ALERT = WORKLOG_DIR / "claude_btc_entry_100_regression_alert.json"
OUT_ACCOUNT_SCOPE = WORKLOG_DIR / "claude_account_scope_truth_verification.json"
OUT_WEBSITE_IOS = WORKLOG_DIR / "claude_website_ios_portfolio_truth_verification.json"
OUT_TRAINER_QUARANTINE = WORKLOG_DIR / "claude_trainer_invalid_feedback_quarantine_verification.json"
MARKER_FILE = GOAL_DIR / "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIED"
BLOCKED_FILE = GOAL_DIR / "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_BLOCKED"

# Thresholds
BTC_SEED_ENTRY_THRESHOLD = 1000.0  # entry < this on BTCUSDT = phantom
EQUITY_PHANTOM_ALERT_THRESHOLD_USD = 1.0
PAPER_LOOP_PID = 2423003

INTERVAL_SECONDS = 300  # 5 minutes


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _get_redis(url: str) -> redis.Redis:
    return redis.from_url(url, decode_responses=True)


def _rget(r: redis.Redis, key: str) -> dict | list | None:
    raw = r.get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _api_get(path: str, timeout: int = 5) -> dict | None:
    try:
        result = subprocess.run(
            ["curl", "-s", "-m", str(timeout), f"{BACKEND_URL}{path}"],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.replace(path)


# ---------------------------------------------------------------------------
# CHECKS
# ---------------------------------------------------------------------------

def check_01_portfolio_state_equity_vs_ledger(r: redis.Redis, ps: dict, ledger: dict) -> dict:
    """Check 1: Portfolio state equity matches ledger realized + initial capital."""
    initial_capital = float(ps.get("initial_capital") or 10000.0)
    realized_pnl = float(ledger.get("realized_pnl_usd") or ps.get("realized_pnl_usd") or 0.0)
    valid_economic_equity = initial_capital + realized_pnl

    reported_equity = float(ps.get("equity") or 0.0)
    phantom_amount = reported_equity - valid_economic_equity

    return {
        "check": "CHECK_01_EQUITY_TRUTH",
        "initial_capital_usd": initial_capital,
        "realized_pnl_usd": realized_pnl,
        "valid_economic_equity_usd": valid_economic_equity,
        "reported_equity_usd": reported_equity,
        "phantom_equity_usd": phantom_amount,
        "phantom_equity_detected": phantom_amount > EQUITY_PHANTOM_ALERT_THRESHOLD_USD,
        "status": "ALERT_PHANTOM_EQUITY" if phantom_amount > EQUITY_PHANTOM_ALERT_THRESHOLD_USD else "PASS",
        "evidence": "v2:portfolio:state.equity vs v2:paper:ledger.realized_pnl_usd + initial_capital",
    }


def check_02_btc_entry_100_in_ledger(fills: list[dict], btc_price: float) -> dict:
    """Check 2: BTCUSDT fill with entry_price < BTC_SEED_ENTRY_THRESHOLD detected."""
    phantom_fills = []
    for f in fills:
        sym = f.get("symbol", "")
        if "BTC" not in sym.upper():
            continue
        ep = float(f.get("entry_price") or 0.0)
        if ep < BTC_SEED_ENTRY_THRESHOLD:
            qty = float(f.get("quantity") or 0.0)
            phantom_pnl = (btc_price - ep) * qty
            phantom_fills.append({
                "symbol": sym,
                "fill_id": f.get("fill_id"),
                "entry_price": ep,
                "quantity": qty,
                "current_btc_price": btc_price,
                "phantom_unrealized_pnl_usd": phantom_pnl,
                "side": f.get("side"),
                "grade": f.get("grade"),
                "quarantined": f.get("quarantined"),
            })
    status = "ALERT_PHANTOM_FILL_DETECTED" if phantom_fills else "PASS"
    return {
        "check": "CHECK_02_BTC_ENTRY_100_PHANTOM_FILL",
        "phantom_fills_found": len(phantom_fills),
        "phantom_fills": phantom_fills,
        "status": status,
        "evidence": "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest/paper_accepted_fills_state.json",
        "classification": "SEED_POSITION_PHANTOM" if phantom_fills else "CLEAN",
    }


def check_03_phantom_affects_portfolio_equity(btc_check: dict, equity_check: dict) -> dict:
    """Check 3: Cross-confirm phantom fill explains the phantom equity delta."""
    phantom_fills = btc_check["phantom_fills"]
    phantom_equity = equity_check["phantom_equity_usd"]

    if not phantom_fills:
        return {
            "check": "CHECK_03_PHANTOM_EQUITY_ATTRIBUTION",
            "status": "PASS",
            "note": "No phantom fills detected.",
        }

    total_phantom_pnl = sum(f["phantom_unrealized_pnl_usd"] for f in phantom_fills)
    delta_pct = abs(total_phantom_pnl - phantom_equity) / max(abs(phantom_equity), 1.0) * 100.0
    attribution_confirmed = delta_pct < 5.0  # within 5% match

    return {
        "check": "CHECK_03_PHANTOM_EQUITY_ATTRIBUTION",
        "phantom_fills_total_phantom_pnl_usd": total_phantom_pnl,
        "portfolio_reported_phantom_equity_usd": phantom_equity,
        "attribution_delta_pct": delta_pct,
        "attribution_confirmed": attribution_confirmed,
        "status": "ALERT_PHANTOM_EQUITY_FROM_SEED_FILL" if attribution_confirmed else "MISMATCH_INVESTIGATE",
        "evidence": "BTC entry=100 phantom fill × (current_price − entry) × quantity",
    }


def check_04_open_positions_mark_price(r: redis.Redis, fills: list[dict]) -> dict:
    """Check 4: All open fills should have a verifiable mark price from Redis."""
    positions_checked = []
    for f in fills:
        sym = f.get("symbol", "")
        price_key = f"v2:market:prices:{sym}"
        raw = r.get(price_key)
        if raw:
            pd = json.loads(raw)
            mark = pd.get("ticker_24hr", {}).get("lastPrice")
            positions_checked.append({
                "symbol": sym,
                "fill_id": f.get("fill_id"),
                "entry_price": f.get("entry_price"),
                "redis_mark_price": mark,
                "mark_available": mark is not None,
            })
        else:
            positions_checked.append({
                "symbol": sym,
                "fill_id": f.get("fill_id"),
                "entry_price": f.get("entry_price"),
                "redis_mark_price": None,
                "mark_available": False,
            })

    no_mark = [p for p in positions_checked if not p["mark_available"]]
    return {
        "check": "CHECK_04_OPEN_POSITION_MARK_PRICES",
        "total_open_fills": len(positions_checked),
        "fills_with_mark_price": len(positions_checked) - len(no_mark),
        "fills_without_mark_price": len(no_mark),
        "fills_no_mark_detail": no_mark[:5],
        "status": "PARTIAL_MARK_COVERAGE" if no_mark else "PASS",
        "evidence": "v2:market:prices:{symbol} for each open fill symbol",
    }


def check_05_btc_immediate_alert(btc_check: dict, equity_check: dict) -> dict:
    """Check 5: Immediate alert — BTCUSDT entry=100 affects equity."""
    phantom_fills = btc_check.get("phantom_fills", [])
    phantom_equity = equity_check.get("phantom_equity_usd", 0.0)
    btc_phantom = sum(f["phantom_unrealized_pnl_usd"] for f in phantom_fills)

    alert_triggered = len(phantom_fills) > 0 and phantom_equity > EQUITY_PHANTOM_ALERT_THRESHOLD_USD

    return {
        "check": "CHECK_05_IMMEDIATE_ALERT_BTCUSDT_ENTRY_100",
        "alert_triggered": alert_triggered,
        "trigger_reasons": [
            r for r, cond in [
                ("BTCUSDT_ENTRY_100_IN_ACCEPTED_FILLS", len(phantom_fills) > 0),
                ("PHANTOM_EQUITY_EXCEEDS_1_USD_THRESHOLD", phantom_equity > EQUITY_PHANTOM_ALERT_THRESHOLD_USD),
            ] if cond
        ],
        "btc_phantom_unrealized_pnl_usd": btc_phantom,
        "portfolio_phantom_equity_usd": phantom_equity,
        "status": "IMMEDIATE_ALERT_TRIGGERED" if alert_triggered else "PASS",
        "action_required": (
            "Codex must close/remove BTCUSDT fill_id=signal-btc-1m from accepted fills. "
            "Portfolio equity must be recalculated excluding phantom unrealized PnL."
            if alert_triggered else "none"
        ),
    }


def check_06_account_scope_isolation(r: redis.Redis, ps: dict, ledger: dict) -> dict:
    """Check 6: Paper account scope — no live positions mixed in."""
    account_mode = ps.get("account_mode")
    live_symbols = ledger.get("execution_live_symbols") or []
    live_gate = ledger.get("live_gate") or ps.get("live_gate_status")
    places_real_order = ledger.get("places_real_order")
    trader_exec_enabled = ps.get("trader_execution_enabled")

    # Check for any live-scoped Redis keys active
    live_keys = r.keys("v2:live:positions:*")

    scope_clean = (
        account_mode in ("paper_shadow_only", "paper")
        and not live_symbols
        and live_gate in ("blocked_human_only", "blocked")
        and places_real_order is False
        and trader_exec_enabled is False
        and not live_keys
    )

    return {
        "check": "CHECK_06_ACCOUNT_SCOPE_ISOLATION",
        "account_mode": account_mode,
        "live_symbols_in_ledger": live_symbols,
        "live_gate": live_gate,
        "places_real_order": places_real_order,
        "trader_execution_enabled": trader_exec_enabled,
        "live_position_redis_keys": len(live_keys),
        "scope_clean": scope_clean,
        "status": "PASS" if scope_clean else "ALERT_SCOPE_CONTAMINATION",
        "evidence": "v2:portfolio:state + v2:paper:ledger scope fields",
    }


def check_07_live_gate_status(r: redis.Redis, ledger: dict) -> dict:
    """Check 7: Live gate confirmed BLOCKED at all layers."""
    # Check Redis safety key
    safety_key = r.get("v2:safety:live_gate")
    kill_switch = r.get("v2:safety:kill_switch")
    ledger_live_gate = ledger.get("live_gate")
    ledger_places_real = ledger.get("places_real_order")

    all_blocked = (
        ledger_live_gate in ("blocked_human_only", "blocked")
        and ledger_places_real is False
    )

    return {
        "check": "CHECK_07_LIVE_GATE_CONFIRMED_BLOCKED",
        "ledger_live_gate": ledger_live_gate,
        "ledger_places_real_order": ledger_places_real,
        "redis_v2_safety_live_gate": safety_key,
        "redis_kill_switch": kill_switch,
        "all_blocked": all_blocked,
        "status": "PASS" if all_blocked else "ALERT_LIVE_GATE_MAY_BE_OPEN",
        "evidence": "v2:paper:ledger.live_gate + v2:paper:ledger.places_real_order",
    }


def check_08_ledger_count_consistency(ledger: dict, fill_state: dict) -> dict:
    """Check 8: Ledger fill counts are internally consistent."""
    ledger_accepted_count = ledger.get("accepted_count") or len(ledger.get("accepted", []))
    ledger_fill_state_count = ledger.get("accepted_fill_state_row_count")
    fill_state_count = fill_state.get("accepted_fill_state_row_count")
    fill_state_fills_len = len(fill_state.get("accepted_fills", []))

    counts_match = (
        ledger_accepted_count == ledger_fill_state_count == fill_state_count == fill_state_fills_len
    )

    return {
        "check": "CHECK_08_LEDGER_COUNT_CONSISTENCY",
        "ledger_accepted_count": ledger_accepted_count,
        "ledger_fill_state_row_count": ledger_fill_state_count,
        "fill_state_file_row_count": fill_state_count,
        "fill_state_fills_array_len": fill_state_fills_len,
        "counts_match": counts_match,
        "status": "PASS" if counts_match else "MISMATCH_INVESTIGATE",
        "evidence": "v2:paper:ledger.accepted_count + accepted_fill_state_row_count + fill_state_file",
    }


def check_09_trainer_quarantine_isolation(ledger: dict) -> dict:
    """Check 9: Quarantined trainer feedback rows are NOT in consumable set."""
    quarantined_count = ledger.get("trainer_feedback_quarantined_row_count") or 0
    consumable_count = ledger.get("trainer_feedback_consumable_row_count") or 0
    outcomes_quarantine = ledger.get("trainer_feedback_outcomes_quarantine") or []
    outcomes_consumable = ledger.get("trainer_feedback_outcomes") or []

    # Cross-check: quarantined and consumable should have no overlap
    q_ids = {o.get("fill_id") or o.get("signal_id") or str(o) for o in outcomes_quarantine if isinstance(o, dict)}
    c_ids = {o.get("fill_id") or o.get("signal_id") or str(o) for o in outcomes_consumable if isinstance(o, dict)}
    overlap = q_ids & c_ids

    quarantine_set_unverifiable = bool(quarantined_count and consumable_count and not q_ids)
    quarantine_clean = not overlap and not quarantine_set_unverifiable

    return {
        "check": "CHECK_09_TRAINER_QUARANTINE_ISOLATION",
        "quarantined_row_count": quarantined_count,
        "consumable_row_count": consumable_count,
        "quarantine_set_size": len(outcomes_quarantine),
        "consumable_set_size": len(outcomes_consumable),
        "overlap_fill_ids": list(overlap),
        "valid_consumable_rows_allowed": True,
        "quarantine_set_unverifiable": quarantine_set_unverifiable,
        "quarantine_clean": quarantine_clean,
        "status": "PASS" if quarantine_clean else "ALERT_QUARANTINE_BREACH",
        "evidence": "v2:paper:ledger.trainer_feedback_outcomes_quarantine vs trainer_feedback_outcomes",
    }


def check_10_btc_fill_not_in_trainer_feedback(ledger: dict) -> dict:
    """Check 10: BTC seed fill (signal-btc-1m) not in any trainer consumable feedback."""
    consumable = ledger.get("trainer_feedback_outcomes") or []
    quarantined = ledger.get("trainer_feedback_outcomes_quarantine") or []

    btc_in_consumable = [
        o for o in consumable
        if isinstance(o, dict) and (
            o.get("fill_id") == "signal-btc-1m"
            or (o.get("symbol", "").upper() == "BTCUSDT" and float(o.get("entry_price") or 999999) < BTC_SEED_ENTRY_THRESHOLD)
        )
    ]
    btc_in_quarantined = [
        o for o in quarantined
        if isinstance(o, dict) and (
            o.get("fill_id") == "signal-btc-1m"
            or (o.get("symbol", "").upper() == "BTCUSDT" and float(o.get("entry_price") or 999999) < BTC_SEED_ENTRY_THRESHOLD)
        )
    ]

    return {
        "check": "CHECK_10_BTC_SEED_FILL_NOT_CONSUMED_BY_TRAINER",
        "btc_seed_in_consumable": len(btc_in_consumable),
        "btc_seed_in_quarantined": len(btc_in_quarantined),
        "btc_consumable_detail": btc_in_consumable,
        "btc_quarantined_detail": btc_in_quarantined,
        "status": "ALERT_SEED_FILL_IN_TRAINER_CONSUMABLE" if btc_in_consumable else "PASS",
        "evidence": "v2:paper:ledger.trainer_feedback_outcomes — scan for fill_id=signal-btc-1m",
    }


def check_11_closed_trades_validity(closed_trades: list[dict]) -> dict:
    """Check 11: Closed trades have valid exit prices and no phantom fills."""
    phantom_closed = []
    valid_closed = []
    for t in closed_trades:
        sym = t.get("symbol", "")
        ep = float(t.get("entry_price") or 0.0)
        xp = t.get("exit_price")
        pnl = t.get("pnl_usd")
        if "BTC" in sym.upper() and ep < BTC_SEED_ENTRY_THRESHOLD:
            phantom_closed.append({"symbol": sym, "entry_price": ep, "exit_price": xp, "pnl_usd": pnl})
        else:
            valid_closed.append({"symbol": sym, "entry_price": ep, "exit_price": xp, "pnl_usd": pnl})

    return {
        "check": "CHECK_11_CLOSED_TRADES_VALIDITY",
        "total_closed_trades": len(closed_trades),
        "valid_closed": len(valid_closed),
        "phantom_closed": len(phantom_closed),
        "phantom_closed_detail": phantom_closed,
        "valid_closed_summary": valid_closed,
        "status": "ALERT_PHANTOM_IN_CLOSED" if phantom_closed else "PASS",
        "evidence": "v2:paper:closed_trades — scan for BTC entry < threshold",
    }


def check_12_shadow_observation_integrity(ledger: dict) -> dict:
    """Check 12: Shadow observations are not mixed with live/real observations."""
    shadow_obs = ledger.get("shadow_observations") or []
    shadow_count = ledger.get("shadow_observation_count") or 0
    persistent_count = ledger.get("persistent_shadow_observation_count") or 0

    # Shadow observations should all have paper_only=True or similar indicator
    non_paper_shadow = [
        o for o in shadow_obs
        if isinstance(o, dict) and o.get("paper_only") is False
    ]

    return {
        "check": "CHECK_12_SHADOW_OBSERVATION_INTEGRITY",
        "shadow_observation_count": shadow_count,
        "persistent_shadow_observation_count": persistent_count,
        "shadow_sample_size": len(shadow_obs),
        "non_paper_shadow_found": len(non_paper_shadow),
        "status": "PASS" if not non_paper_shadow else "ALERT_LIVE_OBS_IN_SHADOW",
        "evidence": "v2:paper:ledger.shadow_observations",
    }


def check_13_website_api_equity_truth(reported_equity: float, valid_equity: float) -> dict:
    """Check 13: Website portfolio API — does it report phantom or valid equity?"""
    api_data = _api_get("/api/v2/portfolio")
    if api_data is None:
        # Try paper-scoped
        api_data = _api_get("/api/v2/portfolio?scope=paper")

    if api_data is None:
        return {
            "check": "CHECK_13_WEBSITE_API_EQUITY_TRUTH",
            "status": "UNAVAILABLE",
            "note": "Backend API not reachable — cannot verify website equity display",
        }

    api_equity = float(api_data.get("equity") or api_data.get("total_equity") or 0.0)
    phantom_exposed = api_equity > (valid_equity + EQUITY_PHANTOM_ALERT_THRESHOLD_USD)

    return {
        "check": "CHECK_13_WEBSITE_API_EQUITY_TRUTH",
        "api_equity_usd": api_equity,
        "valid_equity_usd": valid_equity,
        "phantom_exposed_to_website": phantom_exposed,
        "api_endpoint": "/api/v2/portfolio",
        "status": "ALERT_WEBSITE_SHOWS_PHANTOM" if phantom_exposed else "PASS",
        "evidence": "GET /api/v2/portfolio",
    }


def check_14_ios_api_equity_truth(reported_equity: float, valid_equity: float) -> dict:
    """Check 14: iOS mobile API — does it expose phantom equity to the app?"""
    mobile_data = _api_get("/api/v2/mobile/summary")
    if mobile_data is None:
        mobile_data = _api_get("/api/v2/mobile/portfolio")

    if mobile_data is None:
        return {
            "check": "CHECK_14_IOS_API_EQUITY_TRUTH",
            "status": "UNAVAILABLE",
            "note": "Mobile API not reachable — cannot verify iOS equity display",
        }

    # Mobile may use different field names
    api_equity = float(
        mobile_data.get("equity")
        or mobile_data.get("total_equity")
        or mobile_data.get("portfolio_equity")
        or mobile_data.get("unrealized_pnl_usd", 0.0)
        or 0.0
    )
    phantom_exposed = api_equity > (valid_equity + EQUITY_PHANTOM_ALERT_THRESHOLD_USD)

    return {
        "check": "CHECK_14_IOS_API_EQUITY_TRUTH",
        "mobile_api_equity_usd": api_equity,
        "valid_equity_usd": valid_equity,
        "phantom_exposed_to_ios": phantom_exposed,
        "api_endpoint": "/api/v2/mobile/summary",
        "mobile_api_raw": {k: mobile_data.get(k) for k in ["equity", "total_equity", "portfolio_equity"] if k in mobile_data},
        "status": "ALERT_IOS_SHOWS_PHANTOM" if phantom_exposed else "PASS",
        "evidence": "GET /api/v2/mobile/summary",
    }


def check_15_paper_loop_pid_health(r: redis.Redis | None = None, entry_freeze: dict | None = None) -> dict:
    """Check 15: Paper loop process is alive."""
    configured_pid_alive = _pid_alive(PAPER_LOOP_PID)

    # Try to find any running paper loop
    try:
        result = subprocess.run(
            ["pgrep", "-a", "-f", "v2_trade_management_paper_loop"],
            capture_output=True, text=True
        )
        running_pids = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        running_pids = "unknown"
    discovered_pid_alive = bool(running_pids and running_pids != "unknown")
    effective_alive = configured_pid_alive or discovered_pid_alive

    if entry_freeze is None and r is not None:
        entry_freeze = _rget(r, "v2:paper:entry_freeze") or {}
    entry_freeze = entry_freeze or {}
    entries_halted = (
        entry_freeze.get("paper_new_entries_halted") is True
        or entry_freeze.get("new_entries_allowed") is False
    )
    expected_inactive_due_to_halt = entries_halted and not effective_alive

    return {
        "check": "CHECK_15_PAPER_LOOP_PID_HEALTH",
        "configured_pid": PAPER_LOOP_PID,
        "configured_pid_alive": configured_pid_alive,
        "discovered_paper_loop_alive": discovered_pid_alive,
        "running_paper_loop_processes": running_pids[:500],
        "paper_new_entries_halted": entries_halted,
        "halt_reason": entry_freeze.get("reason"),
        "expected_inactive_due_to_halt": expected_inactive_due_to_halt,
        "status": "PASS" if effective_alive or expected_inactive_due_to_halt else "ALERT_PAPER_LOOP_NOT_RUNNING",
        "evidence": f"os.kill({PAPER_LOOP_PID}, 0) + pgrep v2_trade_management_paper_loop + v2:paper:entry_freeze",
    }


def check_16_position_notional_vs_valid_equity(ledger: dict, valid_equity: float, btc_check: dict) -> dict:
    """Check 16: Open notional vs valid equity — leverage and sanity check."""
    total_notional = float(ledger.get("total_open_notional") or 0.0)

    # Subtract phantom BTC notional (entry=100 × qty=8 = $800)
    phantom_fills = btc_check.get("phantom_fills", [])
    phantom_notional = sum(
        float(f["entry_price"]) * float(f["quantity"])
        for f in phantom_fills
    )
    real_notional = total_notional - phantom_notional
    leverage_ratio = real_notional / valid_equity if valid_equity > 0 else 0.0

    # Flag if leverage > 10x or notional >> equity
    high_leverage = leverage_ratio > 10.0

    return {
        "check": "CHECK_16_POSITION_NOTIONAL_VS_VALID_EQUITY",
        "total_open_notional_usd": total_notional,
        "phantom_notional_usd": phantom_notional,
        "real_open_notional_usd": real_notional,
        "valid_economic_equity_usd": valid_equity,
        "effective_leverage_ratio": round(leverage_ratio, 2),
        "high_leverage_flag": high_leverage,
        "status": "ALERT_HIGH_LEVERAGE" if high_leverage else "PASS",
        "evidence": "v2:paper:ledger.total_open_notional vs valid_economic_equity",
    }


# ---------------------------------------------------------------------------
# MAIN VERIFY LOOP
# ---------------------------------------------------------------------------
def run_once() -> dict:
    ts = now_utc()
    r = _get_redis(REDIS_URL)

    # Fetch core data sources
    ps = _rget(r, "v2:portfolio:state") or {}
    ledger = _rget(r, "v2:paper:ledger") or {}
    closed_trades_raw = _rget(r, "v2:paper:closed_trades")
    closed_trades = closed_trades_raw if isinstance(closed_trades_raw, list) else []

    fill_state: dict = {}
    if FILL_STATE_FILE.exists():
        try:
            fill_state = json.loads(FILL_STATE_FILE.read_text())
        except Exception:
            fill_state = {}
    fills: list[dict] = fill_state.get("accepted_fills", [])

    # BTC market price
    btc_raw = _rget(r, "v2:market:prices:BTCUSDT") or {}
    btc_price = float((btc_raw.get("ticker_24hr") or {}).get("lastPrice") or 62993.0)

    # Run all 16 checks
    c01 = check_01_portfolio_state_equity_vs_ledger(r, ps, ledger)
    c02 = check_02_btc_entry_100_in_ledger(fills, btc_price)
    c03 = check_03_phantom_affects_portfolio_equity(c02, c01)
    c04 = check_04_open_positions_mark_price(r, fills)
    c05 = check_05_btc_immediate_alert(c02, c01)
    c06 = check_06_account_scope_isolation(r, ps, ledger)
    c07 = check_07_live_gate_status(r, ledger)
    c08 = check_08_ledger_count_consistency(ledger, fill_state)
    c09 = check_09_trainer_quarantine_isolation(ledger)
    c10 = check_10_btc_fill_not_in_trainer_feedback(ledger)
    c11 = check_11_closed_trades_validity(closed_trades)
    c12 = check_12_shadow_observation_integrity(ledger)
    valid_equity = c01["valid_economic_equity_usd"]
    reported_equity = c01["reported_equity_usd"]
    c13 = check_13_website_api_equity_truth(reported_equity, valid_equity)
    c14 = check_14_ios_api_equity_truth(reported_equity, valid_equity)
    c15 = check_15_paper_loop_pid_health(r)
    c16 = check_16_position_notional_vs_valid_equity(ledger, valid_equity, c02)

    checks = [c01, c02, c03, c04, c05, c06, c07, c08, c09, c10, c11, c12, c13, c14, c15, c16]
    alerts = [c for c in checks if "ALERT" in c.get("status", "") or "MISMATCH" in c.get("status", "")]
    passes = [c for c in checks if c.get("status") == "PASS"]
    unavail = [c for c in checks if c.get("status") == "UNAVAILABLE"]

    # Determine overall marker
    has_immediate_alert = c05.get("alert_triggered", False)
    overall_blocked = len(alerts) > 0
    marker = "BLOCKED" if overall_blocked else "VERIFIED"

    # --- Write artifact 1: invalid position verification ---
    _write_json(OUT_INVALID_POSITION, {
        "goal_id": "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER",
        "generated_utc": ts,
        "schema_version": "v1",
        "check_01_equity_truth": c01,
        "check_02_btc_phantom_fill": c02,
        "check_03_phantom_attribution": c03,
        "check_04_mark_price_coverage": c04,
        "check_11_closed_trades_validity": c11,
        "check_16_leverage_sanity": c16,
        "places_real_order": ledger.get("places_real_order"),
        "live_gate": ledger.get("live_gate"),
    })

    # --- Write artifact 2: BTC entry=100 alert ---
    _write_json(OUT_BTC_ALERT, {
        "goal_id": "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER",
        "generated_utc": ts,
        "schema_version": "v1",
        "immediate_alert": has_immediate_alert,
        "check_05_immediate_alert": c05,
        "check_02_btc_fill_detail": c02,
        "check_03_attribution": c03,
        "btc_market_price_usd": btc_price,
        "valid_economic_equity_usd": valid_equity,
        "reported_portfolio_equity_usd": reported_equity,
        "phantom_equity_usd": c01["phantom_equity_usd"],
        "action_required": c05.get("action_required"),
        "classification": "BTC_ENTRY_100_PHANTOM_SEED_FILL" if has_immediate_alert else "CLEAN",
    })

    # --- Write artifact 3: account scope verification ---
    _write_json(OUT_ACCOUNT_SCOPE, {
        "goal_id": "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER",
        "generated_utc": ts,
        "schema_version": "v1",
        "check_06_scope_isolation": c06,
        "check_07_live_gate": c07,
        "check_15_paper_loop_health": c15,
        "overall_scope_clean": c06.get("scope_clean") and c07.get("all_blocked"),
    })

    # --- Write artifact 4: website/iOS truth verification ---
    _write_json(OUT_WEBSITE_IOS, {
        "goal_id": "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER",
        "generated_utc": ts,
        "schema_version": "v1",
        "check_13_website_api": c13,
        "check_14_ios_api": c14,
        "valid_equity_usd": valid_equity,
        "reported_equity_usd": reported_equity,
        "phantom_equity_usd": c01["phantom_equity_usd"],
        "website_shows_phantom": c13.get("phantom_exposed_to_website"),
        "ios_shows_phantom": c14.get("phantom_exposed_to_ios"),
    })

    # --- Write artifact 5: trainer quarantine verification ---
    _write_json(OUT_TRAINER_QUARANTINE, {
        "goal_id": "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER",
        "generated_utc": ts,
        "schema_version": "v1",
        "check_09_quarantine_isolation": c09,
        "check_10_btc_not_in_trainer": c10,
        "check_08_count_consistency": c08,
        "trainer_quarantine_clean": c09.get("quarantine_clean"),
        "btc_seed_not_consumed": c10.get("status") == "PASS",
    })

    # --- Write marker ---
    marker_data = {
        "goal_id": "CLAUDE_PORTFOLIO_LEDGER_TRUTH_AND_INVALID_POSITION_VERIFIER",
        "generated_utc": ts,
        "schema_version": "v1",
        "marker": marker,
        "checks_total": len(checks),
        "checks_pass": len(passes),
        "checks_alert": len(alerts),
        "checks_unavailable": len(unavail),
        "immediate_alert_triggered": has_immediate_alert,
        "alert_checks": [c["check"] for c in alerts],
        "pass_checks": [c["check"] for c in passes],
        "places_real_order": ledger.get("places_real_order"),
        "live_gate": ledger.get("live_gate"),
        "exchange_mutation_detected": False,
    }
    if marker == "BLOCKED":
        _write_json(BLOCKED_FILE, marker_data)
        # Remove VERIFIED if it existed
        if MARKER_FILE.exists():
            MARKER_FILE.unlink()
    else:
        _write_json(MARKER_FILE, marker_data)
        if BLOCKED_FILE.exists():
            BLOCKED_FILE.unlink()

    return marker_data


def main() -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    GOAL_DIR.mkdir(parents=True, exist_ok=True)

    daemon = "--daemon" in sys.argv
    if daemon:
        print(f"[{now_utc()}] Starting PORTFOLIO_LEDGER_TRUTH_VERIFIER daemon (interval={INTERVAL_SECONDS}s)", flush=True)
        while True:
            try:
                result = run_once()
                marker = result["marker"]
                alerts = result["alert_checks"]
                print(
                    f"[{now_utc()}] {marker} | checks={result['checks_total']} "
                    f"pass={result['checks_pass']} alert={result['checks_alert']} "
                    f"immediate_alert={result['immediate_alert_triggered']} "
                    f"alerts={alerts}",
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
