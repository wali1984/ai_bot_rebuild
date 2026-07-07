#!/usr/bin/env python3
"""
CLAUDE_GOAL_ID: CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER_AND_NO_AUDIT_GUARD

Real-time controller, independent verifier, and anti-drift guard.
Monitors Codex, runtime state, and paper session health every 5 min (active) or 30 min (idle).

NEVER patches live execution or exchange mutation code.
MAY patch: website/iOS/runtime truth, paper-only monitor defects.

Recovery priority order (for Codex agents):
  1. hard-stop paper bleed
  2. fix trainer learning proof
  3. fix high-confidence wrong trades
  4. fix regime/strategy routing
  5. fix exits and execution
  6. fix adaptive capital/leverage/margin simulation
  7. prepare real trader dry-run packet
  8. fix website and iOS truth
  9. collect recovery evidence
  10. A-grade bootstrap + live operator approval

Output artifacts (claude_worklog/):
  claude_realtime_recovery_status.json
  claude_codex_progress_watch.json
  claude_paper_performance_watch.json
  claude_trainer_learning_watch.json
  claude_real_trader_readiness_watch.json
  claude_website_ios_truth_watch.json
  claude_operator_alerts.jsonl

Markers (goal_state/CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER/):
  CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER_ACTIVE
  CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER_BLOCKED
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

WORKLOG_DIR = pathlib.Path("claude_worklog")
GOAL_DIR = pathlib.Path("goal_state/CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER")

OUT_STATUS   = WORKLOG_DIR / "claude_realtime_recovery_status.json"
OUT_CODEX    = WORKLOG_DIR / "claude_codex_progress_watch.json"
OUT_PERF     = WORKLOG_DIR / "claude_paper_performance_watch.json"
OUT_TRAINER  = WORKLOG_DIR / "claude_trainer_learning_watch.json"
OUT_TRADER   = WORKLOG_DIR / "claude_real_trader_readiness_watch.json"
OUT_UI       = WORKLOG_DIR / "claude_website_ios_truth_watch.json"
OUT_ALERTS   = WORKLOG_DIR / "claude_operator_alerts.jsonl"

MARKER_ACTIVE  = GOAL_DIR / "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER_ACTIVE"
MARKER_BLOCKED = GOAL_DIR / "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER_BLOCKED"
CODEX_STATE    = GOAL_DIR / "codex_runtime_state.json"

# Thresholds
PF_MIN_AFTER_5_TRADES    = 1.0
EXPECTANCY_MIN_AFTER_5   = 0.0      # bps after cost
TRADES_FOR_EVAL          = 5
PREDICTION_STALE_SECONDS = 300      # 5 min — signal grid stale
MARKET_STALE_SECONDS     = 60       # 1 min — market data stale
CODEX_STUCK_SECONDS      = 2 * 3600 # 2 h
CADENCE_ACTIVE_SECONDS   = 300      # 5 min when Codex active
CADENCE_IDLE_SECONDS     = 1800     # 30 min when Codex idle
CODEX_IDLE_THRESHOLD_S   = 3600     # 1 h with no patch/test/runtime = idle

V2_SOURCE_ROOTS = ["v2/backend/app", "v2/backend/tests"]
TEST_ROOTS      = ["v2/backend/tests"]


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def now_ts() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()

def _rget(r: redis.Redis, key: str) -> dict | list | str | None:
    raw = r.get(key)
    if not raw:
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

def _append_alert(alert_type: str, detail: dict) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"alert_type": alert_type, "generated_utc": now_utc(), **detail}
    with open(OUT_ALERTS, "a") as f:
        f.write(json.dumps(entry) + "\n")

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False

def _api_get(path: str, token: str | None = None, timeout: int = 6) -> dict | None:
    headers = ["-H", f"Authorization: Bearer {token}"] if token else []
    r = subprocess.run(
        ["curl", "-s", "-m", str(timeout)] + headers + [f"{BACKEND_URL}{path}"],
        capture_output=True, text=True
    )
    if r.returncode == 0 and "{" in r.stdout:
        try:
            return json.loads(r.stdout)
        except Exception:
            return None
    return None

def _get_token() -> str | None:
    r = subprocess.run(
        ["curl", "-s", "-m", "5", "-X", "POST",
         f"{BACKEND_URL}/api/v2/auth/login",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"username": BACKEND_USERNAME, "password": BACKEND_PASSWORD})],
        capture_output=True, text=True
    )
    if r.returncode == 0 and "{" in r.stdout:
        try:
            return json.loads(r.stdout).get("access_token")
        except Exception:
            return None
    return None

def _discover_paper_loop_pid(r: redis.Redis) -> tuple[int | None, str]:
    """Discover canonical paper loop PID from systemctl → pgrep → heartbeat."""
    try:
        sc = subprocess.run(
            ["systemctl", "--user", "show",
             "ai-bot-v2-trade-management-paper-loop.service",
             "--property=MainPID,ActiveState"],
            capture_output=True, text=True, timeout=5
        )
        if sc.returncode == 0:
            props = dict(l.split("=", 1) for l in sc.stdout.strip().splitlines() if "=" in l)
            pid = int(props.get("MainPID", 0))
            if pid > 0 and props.get("ActiveState") == "active" and _pid_alive(pid):
                return pid, "systemctl"
    except Exception:
        pass
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
    try:
        hb = _rget(r, "v2:paper:heartbeat") or {}
        pid = hb.get("pid")
        if pid and _pid_alive(int(pid)):
            return int(pid), "redis_heartbeat"
    except Exception:
        pass
    return None, "not_found"

def _last_mtime(roots: list[str]) -> float:
    latest = 0.0
    for root in roots:
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

def _compute_performance(trades: list[dict]) -> dict:
    """Compute PF, expectancy, win rate from closed trades."""
    n = len(trades)
    if n == 0:
        return {"trade_count": 0, "pf": None, "expectancy_usd": None,
                "win_rate_pct": None, "gross_profit": 0.0, "gross_loss": 0.0,
                "wins": 0, "losses": 0}
    gross_p = gross_l = 0.0
    wins = losses = breakeven = 0
    for t in trades:
        pnl = float(t.get("realized_pnl_usd") or t.get("pnl_usd") or t.get("pnl") or 0)
        if pnl > 0:
            gross_p += pnl; wins += 1
        elif pnl < 0:
            gross_l += abs(pnl); losses += 1
        else:
            breakeven += 1
    pf = gross_p / gross_l if gross_l > 0 else (float("inf") if gross_p > 0 else 0.0)
    exp = (gross_p - gross_l) / n
    wr = wins / n * 100.0
    return {
        "trade_count": n, "pf": round(pf, 4) if pf != float("inf") else "inf",
        "expectancy_usd": round(exp, 4), "win_rate_pct": round(wr, 2),
        "gross_profit": round(gross_p, 4), "gross_loss": round(gross_l, 4),
        "wins": wins, "losses": losses, "breakeven": breakeven,
    }

def _load_codex_state() -> dict:
    if CODEX_STATE.exists():
        try:
            return json.loads(CODEX_STATE.read_text())
        except Exception:
            pass
    return {}

def _save_codex_state(state: dict) -> None:
    GOAL_DIR.mkdir(parents=True, exist_ok=True)
    CODEX_STATE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# MONITORING SECTIONS
# ---------------------------------------------------------------------------

def watch_paper_performance(r: redis.Redis, ps: dict, ledger: dict, session: dict) -> dict:
    """Paper PF, expectancy, win rate, bleed, admission, governor."""
    ct_raw = _rget(r, "v2:paper:closed_trades")
    closed_trades = ct_raw if isinstance(ct_raw, list) else []

    paper_session_id = session.get("paper_session_id") or ps.get("session_id")
    equity = float(ps.get("equity") or 0)
    initial = float(ps.get("initial_capital") or 3000.0)
    realized = float(ps.get("realized_pnl_usd") or 0)
    unrealized = float(ps.get("unrealized_pnl_usd") or 0)
    open_cnt = int(ps.get("open_positions_count") or 0)

    perf = _compute_performance(closed_trades)

    # Bleed halt / governor
    bleed = ledger.get("paper_bleed_halt_status") or {}
    new_entries_allowed = bleed.get("new_entries_allowed")
    halt_reason = bleed.get("halt_reason")
    governor_state = bleed.get("source_state") or bleed.get("status")

    # Circuit breaker
    pcb = ledger.get("paper_performance_circuit_breaker_status") or {}
    pcb_triggered = pcb.get("circuit_breaker_active") or pcb.get("triggered")

    # Admission
    adm = ledger.get("paper_runtime_admission_status") or {}
    accepted = int(adm.get("accepted_count") or 0)
    blocked = int(adm.get("blocked_count") or 0)

    # Strategy router
    sr = ledger.get("strategy_router_report") or {}
    mode_counts = sr.get("mode_counts") or {}

    # Entry gate top block
    ega = ledger.get("paper_audit_entry_gate_status") or {}
    block_counts = ega.get("block_reason_counts") or {}
    top_blocks = sorted(block_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Hard alert checks (require >= 5 trades)
    hard_alerts: list[str] = []
    n = perf["trade_count"]
    if n >= TRADES_FOR_EVAL:
        pf = perf["pf"]
        exp = perf["expectancy_usd"]
        if pf not in (None, "inf") and float(pf) < PF_MIN_AFTER_5_TRADES:
            hard_alerts.append(f"PF_UNDER_1_AFTER_{n}_TRADES: pf={pf}")
            _append_alert("PF_UNDER_1", {"pf": pf, "trade_count": n})
        if exp is not None and float(exp) <= EXPECTANCY_MIN_AFTER_5:
            hard_alerts.append(f"EXPECTANCY_NON_POSITIVE_AFTER_{n}_TRADES: exp={exp}")
            _append_alert("EXPECTANCY_NON_POSITIVE", {"expectancy_usd": exp, "trade_count": n})
        if new_entries_allowed and pf not in (None, "inf") and float(pf) < PF_MIN_AFTER_5_TRADES:
            hard_alerts.append("NEW_ENTRIES_OPEN_WHILE_PF_UNDER_1")
            _append_alert("NEW_ENTRIES_WHILE_PF_UNDER_1", {"new_entries_allowed": new_entries_allowed, "pf": pf})

    if new_entries_allowed and (halt_reason == "HALTED_PERFORMANCE" or pcb_triggered):
        hard_alerts.append("NEW_ENTRIES_OPEN_WHILE_HALTED_PERFORMANCE")
        _append_alert("NEW_ENTRIES_WHILE_HALTED", {"halt_reason": halt_reason, "pcb": pcb_triggered})

    if perf["trade_count"] > 0:
        ledger_fb = int(ledger.get("trainer_feedback_total_row_count") or 0)
        if ledger_fb == 0:
            hard_alerts.append(f"TRAINER_FEEDBACK_ZERO_WITH_{perf['trade_count']}_CLOSED_TRADES")
            _append_alert("TRAINER_FEEDBACK_EMPTY", {
                "closed_trades": perf["trade_count"], "feedback_rows": 0
            })

    return {
        "paper_session_id": paper_session_id,
        "equity_usd": equity,
        "initial_capital_usd": initial,
        "realized_pnl_usd": realized,
        "unrealized_pnl_usd": unrealized,
        "open_positions": open_cnt,
        "closed_trades": perf["trade_count"],
        "performance": perf,
        "new_entries_allowed": new_entries_allowed,
        "governor_state": governor_state,
        "halt_reason": halt_reason,
        "pcb_triggered": pcb_triggered,
        "strategy_router_mode_counts": mode_counts,
        "entry_gate_accepted": accepted,
        "entry_gate_blocked": blocked,
        "top_entry_gate_blocks": top_blocks,
        "hard_alerts": hard_alerts,
    }


def watch_trainer_learning(r: redis.Redis, ledger: dict) -> dict:
    """Trainer feedback rows, weight updates, checkpoint, prediction freshness."""
    trainer_status = r.get("v2:trainer:status") or "UNKNOWN"
    hb = _rget(r, "v2:trainer:checkpoint:heartbeat") or {}
    ev = _rget(r, "v2:trainer:checkpoint:evidence") or {}

    # Feedback counts from ledger
    fb_total = int(ledger.get("trainer_feedback_total_row_count") or 0)
    fb_consumable = int(ledger.get("trainer_feedback_consumable_row_count") or 0)
    fb_quarantined = int(ledger.get("trainer_feedback_quarantined_row_count") or 0)

    # Weight update tracking
    wu = r.get("v2:trainer:weight_update:last") or r.get("v2:trainer:weight_update")
    wu_data: dict = {}
    if wu:
        try:
            wu_data = json.loads(wu)
        except Exception:
            wu_data = {"raw": wu[:200]}

    # Candidate count from checkpoint (proxy for cycle count)
    candidate_count = int(hb.get("candidate_count") or ev.get("candidate_count") or 0)
    checkpoint_id = hb.get("checkpoint_loading", {}).get("checkpoint_id") if isinstance(hb.get("checkpoint_loading"), dict) else None
    checkpoint_generated = ev.get("generated_utc") or hb.get("generated_utc")

    # Prediction grid freshness
    sig_keys = r.keys("v2:signals:paper:*")
    sig_stale = 0
    sig_fresh = 0
    sig_age_max = 0.0
    now = dt.datetime.now(dt.timezone.utc)
    for key in sig_keys[:50]:  # sample 50
        try:
            d = json.loads(r.get(key) or "{}")
            gen = d.get("generated_utc") or d.get("timestamp")
            if gen:
                sig_time = dt.datetime.fromisoformat(gen.replace("Z", "+00:00"))
                age = (now - sig_time).total_seconds()
                if age > sig_age_max:
                    sig_age_max = age
                if age > PREDICTION_STALE_SECONDS:
                    sig_stale += 1
                else:
                    sig_fresh += 1
        except Exception:
            pass

    # CUDA trainer signal keys
    cuda_keys = r.keys("v2:trainer:hybrid_cuda:signals:paper:*")

    # Market data freshness (BTC)
    btc_raw = _rget(r, "v2:market:prices:BTCUSDT") or {}
    btc_price = float((btc_raw.get("ticker_24hr") or {}).get("lastPrice") or 0)
    btc_age_s = None
    btc_stale = False
    # BTC ticker doesn't carry timestamp separately — check via orderbook
    ob_raw = _rget(r, "v2:market:orderbook:BTCUSDT") or {}
    ob_ts = ob_raw.get("timestamp") or ob_raw.get("updated_at")
    if ob_ts:
        try:
            ob_time = dt.datetime.fromisoformat(str(ob_ts).replace("Z", "+00:00"))
            btc_age_s = (now - ob_time).total_seconds()
            btc_stale = btc_age_s > MARKET_STALE_SECONDS
        except Exception:
            pass

    # Hard alert: weights not updating
    hard_alerts: list[str] = []
    if not wu and candidate_count > 100:
        hard_alerts.append("TRAINER_WEIGHTS_NOT_UPDATING_AFTER_CYCLES")
        _append_alert("TRAINER_WEIGHTS_NOT_UPDATING", {
            "candidate_count": candidate_count, "weight_update_key": "absent"
        })

    # Trainer blocked?
    if "BLOCKED" in str(trainer_status).upper():
        hard_alerts.append(f"TRAINER_BLOCKED: {trainer_status}")

    return {
        "trainer_status": trainer_status,
        "feedback_total": fb_total,
        "feedback_consumable": fb_consumable,
        "feedback_quarantined": fb_quarantined,
        "weight_update_last": wu_data or None,
        "candidate_count": candidate_count,
        "checkpoint_id": checkpoint_id,
        "checkpoint_heartbeat_utc": checkpoint_generated,
        "checkpoint_weight_status": hb.get("checkpoint_weight_status"),
        "approves_live": hb.get("approves_live"),
        "trainer_online_mode": hb.get("trainer_online_mode") or ev.get("trainer_online_mode"),
        "signal_keys_total": len(sig_keys),
        "cuda_signal_keys": len(cuda_keys),
        "signal_fresh_sample": sig_fresh,
        "signal_stale_sample": sig_stale,
        "signal_max_age_seconds": round(sig_age_max, 1),
        "btc_price_usd": btc_price,
        "btc_orderbook_age_seconds": btc_age_s,
        "btc_data_stale": btc_stale,
        "hard_alerts": hard_alerts,
    }


def watch_real_trader_readiness(r: redis.Redis, ledger: dict, ps: dict) -> dict:
    """Real trader gate, live readiness checks, no mutation confirmation."""
    live_gate = ledger.get("live_gate") or ps.get("live_gate_status")
    places_real = ledger.get("places_real_order")
    trader_exec = ps.get("trader_execution_enabled")
    account_mode = ps.get("account_mode")

    live_keys = r.keys("v2:live:*")
    order_keys = r.keys("v2:exchange:orders:*") + r.keys("v2:order:*") + r.keys("v2:live:orders:*")
    rt_readiness = r.get("v2:real_trader:readiness")

    # Check for leverage/margin mutation markers
    leverage_keys = r.keys("v2:risk:leverage_changed:*") + r.keys("v2:live:leverage:*")
    margin_keys   = r.keys("v2:risk:margin_changed:*") + r.keys("v2:live:margin:*")

    hard_alerts: list[str] = []
    if live_gate not in ("blocked_human_only", "blocked"):
        hard_alerts.append(f"LIVE_GATE_NOT_BLOCKED: {live_gate}")
        _append_alert("LIVE_GATE_CHANGED", {"live_gate": live_gate})
    if places_real:
        hard_alerts.append("PLACES_REAL_ORDER_TRUE")
        _append_alert("REAL_ORDER_DETECTED", {"places_real_order": places_real})
    if order_keys:
        hard_alerts.append(f"EXCHANGE_ORDER_KEYS_PRESENT: {len(order_keys)}")
        _append_alert("EXCHANGE_ORDER_KEYS", {"keys": [str(k) for k in order_keys[:5]]})
    if leverage_keys:
        hard_alerts.append(f"LEVERAGE_MUTATION_KEYS: {len(leverage_keys)}")
        _append_alert("LEVERAGE_MUTATION", {"keys": [str(k) for k in leverage_keys[:5]]})
    if margin_keys:
        hard_alerts.append(f"MARGIN_MUTATION_KEYS: {len(margin_keys)}")
        _append_alert("MARGIN_MUTATION", {"keys": [str(k) for k in margin_keys[:5]]})

    return {
        "live_gate": live_gate,
        "places_real_order": places_real,
        "trader_execution_enabled": trader_exec,
        "account_mode": account_mode,
        "live_redis_key_count": len(live_keys),
        "exchange_order_key_count": len(order_keys),
        "leverage_mutation_key_count": len(leverage_keys),
        "margin_mutation_key_count": len(margin_keys),
        "real_trader_readiness_key": rt_readiness,
        "readiness_gate": "NOT_READY_PAPER_ONLY",
        "hard_alerts": hard_alerts,
    }


def watch_website_ios(ps: dict, session: dict, token: str | None) -> dict:
    """Website API + mobile iOS truth check."""
    paper_session_id = session.get("paper_session_id")
    target_equity = float(session.get("starting_equity_usd") or 3000.0)
    current_equity = float(ps.get("equity") or 0)

    # Website API
    api_d = _api_get("/api/v2/portfolio", token=token) or {}
    api_data = api_d.get("data") or api_d
    api_equity = float(api_data.get("paper_equity") or api_data.get("equity") or 0)
    api_source = api_d.get("source_type")
    api_session = api_data.get("session_id") or api_data.get("paper_session_id")

    web_stale = api_equity > (current_equity + 1.0) and current_equity > 0
    web_ok = abs(api_equity - current_equity) < 1.0

    # Mobile iOS API
    mob_d = _api_get("/api/v2/mobile/paper-summary") or {}
    mob_pnl = mob_d.get("pnl") or {}
    mob_pos = mob_d.get("positions") or {}
    mob_mode = mob_d.get("mode")
    mob_gate = mob_d.get("live_gate")
    mob_places = mob_d.get("places_real_order")
    mob_session = mob_d.get("session_id") or mob_d.get("paper_session_id")

    mob_realized = float(mob_pnl.get("realized_usd") or 0)
    mob_open = int(mob_pos.get("open_count") or 0)
    mob_closed = int(mob_pos.get("closed_count") or 0)

    # iOS shows old session?
    ios_old_session = (mob_session is not None and paper_session_id is not None
                       and mob_session != paper_session_id)

    hard_alerts: list[str] = []
    if web_stale:
        hard_alerts.append(f"WEBSITE_SHOWS_STALE_EQUITY: api={api_equity:.2f} current={current_equity:.2f}")
        _append_alert("WEBSITE_STALE", {"api_equity": api_equity, "current_equity": current_equity})
    if ios_old_session:
        hard_alerts.append(f"IOS_SHOWS_OLD_SESSION: mob={mob_session} current={paper_session_id}")
        _append_alert("IOS_OLD_SESSION", {"mobile_session": mob_session, "current_session": paper_session_id})

    return {
        "website": {
            "api_equity": api_equity,
            "current_equity": current_equity,
            "source_type": api_source,
            "api_session_id": api_session,
            "equity_matches_current": web_ok,
            "stale_detected": web_stale,
            "status": "PASS" if web_ok else "STALE",
        },
        "ios": {
            "endpoint": "/api/v2/mobile/paper-summary",
            "mode": mob_mode,
            "live_gate": mob_gate,
            "places_real_order": mob_places,
            "pnl_realized_usd": mob_realized,
            "open_positions": mob_open,
            "closed_positions": mob_closed,
            "api_session_id": mob_session,
            "paper_session_id": paper_session_id,
            "old_session_detected": ios_old_session,
            "status": "PASS" if not ios_old_session else "OLD_SESSION",
        },
        "hard_alerts": hard_alerts,
    }


def watch_codex_progress(perf: dict) -> dict:
    """Codex last patch/test/runtime effect — detect stuck or no-audit drift."""
    state = _load_codex_state()
    now = now_ts()

    source_mtime = _last_mtime(V2_SOURCE_ROOTS)
    test_mtime   = _last_mtime(TEST_ROOTS)

    last_source  = float(state.get("last_source_mtime", 0))
    last_test    = float(state.get("last_test_mtime", 0))
    last_runtime = float(state.get("last_runtime_improvement_ts", 0))
    no_progress_since = float(state.get("no_progress_since", now))

    # Detect source change
    source_changed = source_mtime > last_source
    test_changed   = test_mtime > last_test

    # Runtime improvement: new closed trade OR new accepted fill OR equity change
    closed_now = perf.get("closed_trades", 0)
    last_closed = int(state.get("last_closed_trades", 0))
    runtime_improved = closed_now > last_closed

    any_progress = source_changed or test_changed or runtime_improved

    if any_progress:
        no_progress_since = now

    # Codex idle = no source patch in CODEX_IDLE_THRESHOLD_S
    codex_idle = (now - source_mtime) > CODEX_IDLE_THRESHOLD_S
    no_progress_seconds = now - no_progress_since
    codex_stuck = no_progress_seconds >= CODEX_STUCK_SECONDS

    # Update state
    new_state = {
        "last_source_mtime": max(source_mtime, last_source),
        "last_test_mtime": max(test_mtime, last_test),
        "last_runtime_improvement_ts": last_runtime if not runtime_improved else now,
        "last_closed_trades": closed_now,
        "no_progress_since": no_progress_since,
        "codex_idle": codex_idle,
    }
    _save_codex_state(new_state)

    if codex_stuck:
        _append_alert("CODEX_STUCK_NO_PROGRESS", {
            "no_progress_seconds": no_progress_seconds,
            "threshold_seconds": CODEX_STUCK_SECONDS,
        })

    def _fmt(ts: float) -> str:
        if ts <= 0:
            return "never"
        return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat(timespec="seconds")

    return {
        "last_source_patch_utc": _fmt(source_mtime),
        "last_test_mtime_utc": _fmt(test_mtime),
        "codex_idle": codex_idle,
        "codex_stuck": codex_stuck,
        "no_progress_seconds": round(no_progress_seconds, 0),
        "source_changed_this_cycle": source_changed,
        "test_changed_this_cycle": test_changed,
        "runtime_improved_this_cycle": runtime_improved,
        "cadence_seconds": CADENCE_ACTIVE_SECONDS if not codex_idle else CADENCE_IDLE_SECONDS,
        "hard_alerts": ["CODEX_STUCK_2H_NO_PATCH_TEST_RUNTIME"] if codex_stuck else [],
    }


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------
def run_once() -> dict:
    ts = now_utc()
    red = redis.from_url(REDIS_URL, decode_responses=True)

    ps      = _rget(red, "v2:portfolio:state") or {}
    ledger  = _rget(red, "v2:paper:ledger") or {}
    session = _rget(red, "v2:paper:session") or {}

    token = _get_token()

    paper_pid, pid_method = _discover_paper_loop_pid(red)

    # Run all watches
    w_perf    = watch_paper_performance(red, ps, ledger, session)
    w_trainer = watch_trainer_learning(red, ledger)
    w_trader  = watch_real_trader_readiness(red, ledger, ps)
    w_ui      = watch_website_ios(ps, session, token)
    w_codex   = watch_codex_progress(w_perf)

    # Collect all hard alerts
    all_hard = (
        w_perf["hard_alerts"]
        + w_trainer["hard_alerts"]
        + w_trader["hard_alerts"]
        + w_ui["hard_alerts"]
        + w_codex["hard_alerts"]
    )
    blocked = bool([a for a in all_hard if any(
        x in a for x in ["LIVE_GATE_NOT_BLOCKED", "REAL_ORDER", "MARGIN_MUT", "LEVERAGE_MUT", "NEW_ENTRIES_WHILE_HALTED"]
    )])
    marker = "BLOCKED" if blocked else "ACTIVE"

    # Recovery priority status
    priority_status = {
        "P1_stop_paper_bleed": "PASS" if w_perf["new_entries_allowed"] and not w_perf["halt_reason"] else "HALTED",
        "P2_trainer_learning": "BLOCKED" if "BLOCKED" in str(w_trainer["trainer_status"]).upper() else "ACTIVE",
        "P3_high_conf_wrong_trades": "MONITORING",
        "P4_regime_routing": f"blocked={w_perf['entry_gate_blocked']} accepted={w_perf['entry_gate_accepted']}",
        "P5_exits_execution": "MONITORING",
        "P6_adaptive_capital": "MONITORING",
        "P7_real_trader_dry_run": "NOT_STARTED",
        "P8_website_ios_truth": "PASS" if not w_ui["hard_alerts"] else "ALERT",
        "P9_recovery_evidence": f"closed_trades={w_perf['closed_trades']}",
        "P10_a_grade_live_approval": "BLOCKED_PENDING_RECOVERY",
    }

    # Write artifacts
    _write_json(OUT_PERF, {
        "goal_id": "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        **w_perf,
    })
    _write_json(OUT_TRAINER, {
        "goal_id": "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        **w_trainer,
    })
    _write_json(OUT_TRADER, {
        "goal_id": "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        **w_trader,
    })
    _write_json(OUT_UI, {
        "goal_id": "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        **w_ui,
    })
    _write_json(OUT_CODEX, {
        "goal_id": "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        **w_codex,
    })
    _write_json(OUT_STATUS, {
        "goal_id": "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER",
        "generated_utc": ts,
        "schema_version": "v1",
        "marker": marker,
        "paper_pid": paper_pid,
        "pid_discovery": pid_method,
        "paper_session_id": session.get("paper_session_id"),
        "equity_usd": float(ps.get("equity") or 0),
        "closed_trades": w_perf["closed_trades"],
        "open_positions": w_perf["open_positions"],
        "pf": w_perf["performance"]["pf"],
        "expectancy_usd": w_perf["performance"]["expectancy_usd"],
        "win_rate_pct": w_perf["performance"]["win_rate_pct"],
        "new_entries_allowed": w_perf["new_entries_allowed"],
        "governor_state": w_perf["governor_state"],
        "trainer_status": w_trainer["trainer_status"],
        "feedback_total": w_trainer["feedback_total"],
        "live_gate": w_trader["live_gate"],
        "places_real_order": w_trader["places_real_order"],
        "exchange_mutation_detected": bool(
            w_trader["exchange_order_key_count"]
            or w_trader["leverage_mutation_key_count"]
            or w_trader["margin_mutation_key_count"]
        ),
        "codex_idle": w_codex["codex_idle"],
        "codex_stuck": w_codex["codex_stuck"],
        "hard_alerts": all_hard,
        "priority_status": priority_status,
    })

    # Marker
    marker_data = {
        "goal_id": "CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER",
        "generated_utc": ts, "marker": marker,
        "hard_alerts": all_hard,
        "places_real_order": w_trader["places_real_order"],
        "live_gate": w_trader["live_gate"],
        "exchange_mutation_detected": False,
    }
    if blocked:
        _write_json(MARKER_BLOCKED, marker_data)
        if MARKER_ACTIVE.exists():
            MARKER_ACTIVE.unlink()
    else:
        _write_json(MARKER_ACTIVE, marker_data)
        if MARKER_BLOCKED.exists():
            MARKER_BLOCKED.unlink()

    return {
        "ts": ts, "marker": marker,
        "pid": paper_pid, "pid_method": pid_method,
        "session": session.get("paper_session_id", "?")[:35],
        "equity": float(ps.get("equity") or 0),
        "closed": w_perf["closed_trades"],
        "pf": w_perf["performance"]["pf"],
        "new_entries": w_perf["new_entries_allowed"],
        "trainer": w_trainer["trainer_status"],
        "live_gate": w_trader["live_gate"],
        "codex_idle": w_codex["codex_idle"],
        "codex_stuck": w_codex["codex_stuck"],
        "hard_alerts": all_hard,
        "cadence_s": w_codex["cadence_seconds"],
    }


def main() -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    GOAL_DIR.mkdir(parents=True, exist_ok=True)

    daemon = "--daemon" in sys.argv
    if daemon:
        print(f"[{now_utc()}] Starting CLAUDE_REALTIME_PRODUCTION_RECOVERY_CONTROLLER", flush=True)
        while True:
            try:
                r = run_once()
                print(
                    f"[{r['ts']}] {r['marker']} | "
                    f"pid={r['pid']}({r['pid_method']}) "
                    f"session={r['session']} "
                    f"equity=${r['equity']:,.2f} closed={r['closed']} pf={r['pf']} "
                    f"entries={r['new_entries']} trainer={r['trainer'][:30]} "
                    f"gate={r['live_gate']} "
                    f"codex_idle={r['codex_idle']} stuck={r['codex_stuck']} "
                    f"alerts={r['hard_alerts']}",
                    flush=True,
                )
                time.sleep(r["cadence_s"])
            except Exception as exc:
                print(f"[{now_utc()}] ERROR: {exc}", flush=True)
                time.sleep(CADENCE_ACTIVE_SECONDS)
    else:
        r = run_once()
        print(json.dumps(r, indent=2))


if __name__ == "__main__":
    main()
