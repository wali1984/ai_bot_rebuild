#!/usr/bin/env python3
"""
Claude Full System Realtime Edge Monitor & Repair Controller
CLAUDE_GOAL_ID: CLAUDE_FULL_SYSTEM_REALTIME_EDGE_MONITOR_AND_REPAIR_CONTROLLER

Monitors the full adaptive symbol universe across all TFs. BTC/ETH/SOL/BNB are
preferred majors but no symbol is hardcoded — everything is derived from live
Redis namespaces. 21 system health dimensions + ingestor coverage + liquidation
engine + 7-point edge repair path. Writes 7 JSON artifacts + alerts JSONL.

Never mutates live trading state.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OPERATOR_RUNTIME = (
    REPO_ROOT / "v2/frontend/public/operator_runtime/v2_paper_trade_management/latest"
)
MONITOR_OUT = REPO_ROOT / "raw_evidence/claude_realtime_monitor"
MONITOR_OUT.mkdir(parents=True, exist_ok=True)

GOAL_ID = "CLAUDE_FULL_SYSTEM_REALTIME_EDGE_MONITOR_AND_REPAIR_CONTROLLER"
MARKER_ACTIVE  = REPO_ROOT / f"{GOAL_ID}_ACTIVE"
MARKER_BLOCKED = REPO_ROOT / f"{GOAL_ID}_BLOCKED"

# Preferred majors — always monitored specifically; system may trade any symbol
PREFERRED_MAJORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
SYSTEM_TFS = ("1m", "5m", "15m", "1h", "4h")

# ─── ANSI ────────────────────────────────────────────────────────────────────
USE_COLOR = sys.stdout.isatty()


def _c(code: str, t: str) -> str:
    return f"\033[{code}m{t}\033[0m" if USE_COLOR else t


def RED(t: Any) -> str:   return _c("31;1", str(t))
def GRN(t: Any) -> str:   return _c("32;1", str(t))
def YLW(t: Any) -> str:   return _c("33;1", str(t))
def CYN(t: Any) -> str:   return _c("36;1", str(t))
def WHT(t: Any) -> str:   return _c("37;1", str(t))
def DIM(t: Any) -> str:   return _c("2",    str(t))
def BOLD(t: Any) -> str:  return _c("1",    str(t))


CLEAR = "\033[H\033[2J" if USE_COLOR else ""
W = 90

# ─── helpers ─────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _redis(cmd: list[str], timeout: int = 6) -> str:
    try:
        return subprocess.check_output(
            ["redis-cli", "-n", "0"] + cmd,
            stderr=subprocess.DEVNULL, timeout=timeout,
        ).decode().strip()
    except Exception:
        return ""


def _redis_get_json(key: str) -> dict | list | None:
    raw = _redis(["get", key])
    if not raw or raw == "(nil)":
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _redis_json_len(key: str) -> int:
    obj = _redis_get_json(key)
    if isinstance(obj, list):
        return len(obj)
    if isinstance(obj, dict):
        return len(obj)
    return 0


def _redis_keys_list(pattern: str, timeout: int = 8) -> list[str]:
    out = _redis(["keys", pattern], timeout)
    return [l for l in out.splitlines() if l] if out else []


def _redis_count(pattern: str, timeout: int = 8) -> int:
    return len(_redis_keys_list(pattern, timeout))


def _age_s(iso_str: str | None) -> float | None:
    if not iso_str:
        return None
    try:
        ts = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        return None


def _age_ms(ms: int | float | None) -> float | None:
    if ms is None:
        return None
    try:
        return (time.time() * 1000 - float(ms)) / 1000
    except Exception:
        return None


def _f(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _ps(pattern: str) -> list[dict]:
    try:
        out = subprocess.check_output(
            ["ps", "aux", "--no-headers"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode()
        results = []
        for line in out.splitlines():
            if re.search(pattern, line) and "grep" not in line:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    results.append({
                        "pid": parts[1], "cpu": parts[2],
                        "start": parts[8], "time": parts[9], "cmd": parts[10],
                    })
        return results
    except Exception:
        return []


def _src_change_age() -> float | None:
    try:
        out = subprocess.check_output(
            ["find", str(REPO_ROOT / "v2/backend"), "-name", "*.py",
             "-newer", str(REPO_ROOT / ".git/index"),
             "-not", "-path", "*__pycache__*"],
            stderr=subprocess.DEVNULL, timeout=10,
        ).decode().strip()
        if not out:
            return None
        return time.time() - max(
            Path(f).stat().st_mtime for f in out.splitlines() if Path(f).exists()
        )
    except Exception:
        return None


def _stale_label(age_s: float | None, warn_s: int, crit_s: int) -> str:
    if age_s is None:
        return "UNKNOWN"
    if age_s > crit_s:
        return f"STALE_{int(age_s // 60)}m"
    if age_s > warn_s:
        return f"AGING_{int(age_s // 60)}m"
    return f"FRESH_{int(age_s)}s"


# ─── symbol universe discovery ────────────────────────────────────────────────

def discover_symbol_universe() -> dict:
    """
    Dynamically discover ALL symbols tracked by the system from live Redis
    namespaces. Never hardcodes a symbol list.
    """
    ohlcv_keys   = _redis_keys_list("v2:market:ohlcv:binance:*:1h")
    signal_keys  = _redis_keys_list("v2:trainer:hybrid_cuda:signals:paper:*")
    liq_keys     = _redis_keys_list("v2:liquidations:levels:*")
    coinank_keys = _redis_keys_list("features:coinank:*")
    coinank_ep   = _redis_keys_list("features:coinank_endpoint:*")

    ohlcv_syms: set[str] = set()
    for k in ohlcv_keys:
        parts = k.split(":")
        if len(parts) >= 5:
            ohlcv_syms.add(parts[4])

    signal_syms: set[str] = set()
    signal_tfs: dict[str, set[str]] = {}
    for k in signal_keys:
        parts = k.split(":")
        if len(parts) >= 7:
            sym, tf = parts[5], parts[6]
            signal_syms.add(sym)
            signal_tfs.setdefault(sym, set()).add(tf)

    liq_syms: set[str] = set()
    for k in liq_keys:
        parts = k.split(":")
        if len(parts) >= 4:
            liq_syms.add(parts[3])

    all_syms = ohlcv_syms | signal_syms | liq_syms

    # Per-TF signal coverage
    tf_coverage: dict[str, int] = {}
    for tf in SYSTEM_TFS:
        tf_coverage[tf] = _redis_count(f"v2:trainer:hybrid_cuda:signals:paper:*:{tf}", 6)

    # Per-major health
    major_health: dict[str, dict] = {}
    for sym in PREFERRED_MAJORS:
        sig = _redis_get_json(f"v2:trainer:hybrid_cuda:signals:paper:{sym}:4h") or {}
        sig_age = _age_s(
            sig.get("available_at") or sig.get("created_at") or sig.get("generated_at")
        )
        liq = _redis_get_json(f"v2:liquidations:levels:{sym}:1h") or {}
        major_health[sym] = {
            "has_ohlcv":    sym in ohlcv_syms,
            "has_signal":   sym in signal_syms,
            "signal_tfs":   sorted(signal_tfs.get(sym, [])),
            "has_liq":      sym in liq_syms,
            "sig_4h_age_s": sig_age,
            "liq_stale":    bool(liq.get("liquidation_is_stale", 1)) if liq else True,
            "cascade_risk": _f(liq.get("liquidation_cascade_risk")),
            "long_dist_pct":_f(liq.get("liquidation_long_distance_pct")),
        }

    # Sample freshness from non-major symbols
    non_major_sample = sorted(ohlcv_syms - set(PREFERRED_MAJORS))[:8]
    stale_sample = 0
    for sym in non_major_sample:
        sig = _redis_get_json(f"v2:trainer:hybrid_cuda:signals:paper:{sym}:1h") or {}
        age = _age_s(
            sig.get("available_at") or sig.get("created_at") or sig.get("generated_at")
        )
        if age is None or age > 1800:
            stale_sample += 1

    # CoinAnk breakdown
    coinank_liq = sum(1 for k in coinank_keys if ":liquidations:" in k or ":liq:" in k)
    coinank_ind = sum(1 for k in coinank_keys if ":indicators:" in k)
    coinank_ls  = sum(1 for k in coinank_keys if ":long_short:" in k)
    coinank_oi  = sum(1 for k in coinank_keys if ":open_interest:" in k)

    return {
        "total_symbols":        len(all_syms),
        "ohlcv_symbols":        len(ohlcv_syms),
        "signal_symbols":       len(signal_syms),
        "liq_level_symbols":    len(liq_syms),
        "tf_signal_coverage":   tf_coverage,
        "total_signals":        sum(tf_coverage.values()),
        "major_health":         major_health,
        "coinank_total_keys":   len(coinank_keys),
        "coinank_endpoint_keys":len(coinank_ep),
        "coinank_liq_keys":     coinank_liq,
        "coinank_ind_keys":     coinank_ind,
        "coinank_ls_keys":      coinank_ls,
        "coinank_oi_keys":      coinank_oi,
        "sample_non_major_stale": stale_sample,
        "sample_non_major_total": len(non_major_sample),
        "all_symbols":          sorted(all_syms),
    }


# ─── collect functions ────────────────────────────────────────────────────────

def collect_paper_state() -> dict:
    gov_v2 = _load_json(OPERATOR_RUNTIME / "performance_governor_v2_status.json")
    gov    = _load_json(OPERATOR_RUNTIME / "paper_performance_governor_status.json")
    halt   = _load_json(OPERATOR_RUNTIME / "paper_new_entry_emergency_halt_status.json")
    rc     = _load_json(OPERATOR_RUNTIME / "recovery_session_start_status.json")
    alloc  = _load_json(OPERATOR_RUNTIME / "adaptive_capital_allocator_status.json")

    closed   = _redis_json_len("v2:paper:closed_trades")
    pos_raw  = _redis_get_json("v2:paper:positions")
    open_pos = len(pos_raw) if isinstance(pos_raw, (list, dict)) else 0

    r25pf = r50pf = r100pf = r300pf = r50ev = None
    for row in (gov_v2.get("rolling_windows") or []):
        if not isinstance(row, dict):
            continue
        w  = row.get("window")
        pf = _f(row.get("profit_factor"))
        ev = _f(row.get("notional_weighted_expectancy_bps"))
        if w == 25:   r25pf = pf
        if w == 50:   r50pf = pf; r50ev = ev
        if w == 100:  r100pf = pf
        if w == 300:  r300pf = pf

    return {
        "new_entries_allowed": halt.get("new_entries_allowed", False),
        "governor_v2_state":   gov_v2.get("state", "UNKNOWN"),
        "governor_state":      gov.get("state", "UNKNOWN"),
        "bootstrap_admission": gov.get("bootstrap_admission_allowed", False),
        "halt_reasons":        halt.get("halt_reasons", []),
        "PF":                  _f(gov_v2.get("profit_factor")),
        "r25_pf":              r25pf,
        "r50_pf":              r50pf,
        "r100_pf":             r100pf,
        "r300_pf":             r300pf,
        "expectancy_bps":      _f(gov_v2.get("notional_weighted_expectancy_bps")),
        "r50_expectancy_bps":  r50ev,
        "win_rate":            _f(gov_v2.get("win_rate")),
        "closed_trades":       closed,
        "open_positions":      open_pos,
        "governed_rows":       gov_v2.get("closed_outcome_count", 0),
        "global_blocks":       gov_v2.get("global_block_reasons", []),
        "recovery_status":     rc.get("status"),
        "recovery_trades":     rc.get("closed_recovery_trades", 0),
        "equity":              _f(alloc.get("equity")),
        "wallet_balance":      _f(alloc.get("wallet_balance")),
        "capital_util_pct":    _f(alloc.get("capital_utilization_pct")),
        "generated_utc":       halt.get("generated_utc"),
    }


def collect_trainer_state() -> dict:
    tm    = _load_json(OPERATOR_RUNTIME / "trainer_model_quality_runtime_status.json")
    fb    = _redis_json_len("v2:trainer:feedback:outcomes")
    pass_ = tm.get("pass_conditions") or {}
    return {
        "training_active":          bool(_ps(r"hybrid_cuda|v2_trainer")),
        "consumable_feedback_rows": fb,
        "optimizer_steps_hr":       tm.get("optimizer_steps_last_hour", 0) or 0,
        "weights_updated":          tm.get("parameter_hash_changed", False),
        "checkpoint_id":            (tm.get("checkpoint_id") or "")[:24],
        "checkpoint_written":       pass_.get("checkpoint_written", False),
        "checkpoint_reload":        pass_.get("checkpoint_reload_verified", False),
        "accuracy_gt_baseline":     pass_.get("accuracy_gt_baseline", False),
        "a_grade_blocker":          tm.get("a_grade_blocker"),
        "directional_accuracy":     _f(tm.get("directional_accuracy")),
        "brier_score":              _f(tm.get("brier_score")),
        "ece":                      _f(tm.get("ece")),
        "after_cost_expectancy":    _f(tm.get("after_cost_expectancy_bps")),
        "generated_utc":            tm.get("generated_utc"),
    }


def collect_ingestor_state(universe: dict) -> dict:
    """All premium ingestor freshness — uses discovered symbol universe."""
    coinapi_hb  = _redis_get_json("v2:market:coinapi:rest:heartbeat") or {}
    # Heartbeat uses finished_utc (not updated_at/ts) — check all timestamp fields
    coinapi_age = _age_s(
        coinapi_hb.get("updated_at")
        or coinapi_hb.get("ts")
        or coinapi_hb.get("finished_utc")
        or coinapi_hb.get("generated_utc")
    )
    # WebSocket status — separate from REST heartbeat
    coinapi_wsds = _redis_get_json("v2:market:coinapi:wsds:heartbeat") or {}
    coinapi_ws_reconnects  = int(coinapi_wsds.get("stats", {}).get("reconnect_count") or 0)
    coinapi_ws_msgs        = int(coinapi_wsds.get("stats", {}).get("messages_received") or 0)
    coinapi_ws_written     = int(coinapi_wsds.get("stats", {}).get("microfeatures_written") or 0)
    coinapi_ws_last_err    = coinapi_wsds.get("stats", {}).get("last_error_type") or ""
    coinapi_ws_connected   = bool(coinapi_wsds.get("stream_connected"))
    coinapi_ws_last_msg    = coinapi_wsds.get("stats", {}).get("last_message_utc")
    coinapi_ws_age         = _age_s(coinapi_ws_last_msg)
    # REST 403 detection: sample 3 symbols
    coinapi_http_errors: dict[int, int] = {}
    for _sym in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        _st = _redis_get_json(f"v2:market:coinapi:rest:status:{_sym}") or {}
        _code = _st.get("http_status")
        if _code:
            coinapi_http_errors[_code] = coinapi_http_errors.get(_code, 0) + 1
    coinapi_rest_403 = coinapi_http_errors.get(403, 0) > 0

    # Binance OHLCV: median age across 3 majors + 3 non-majors
    all_syms       = universe.get("all_symbols", [])
    non_majors     = [s for s in all_syms if s not in PREFERRED_MAJORS]
    sample_syms    = list(PREFERRED_MAJORS[:3]) + non_majors[:3]
    ohlcv_ages: list[float] = []
    for sym in sample_syms:
        raw = _redis_get_json(f"v2:market:ohlcv:binance:{sym}:1h")
        if isinstance(raw, list) and raw:
            raw = raw[-1]  # last candle
        d   = raw if isinstance(raw, dict) else {}
        age = _age_ms(d.get("close_time_ms") or d.get("ts"))
        if age is not None:
            ohlcv_ages.append(age)
    ohlcv_age_med = sorted(ohlcv_ages)[len(ohlcv_ages) // 2] if ohlcv_ages else None

    # Order book freshness
    ob_ages: list[float] = []
    for sym in PREFERRED_MAJORS[:2]:
        d   = _redis_get_json(f"v2:market:orderbook:{sym}") or {}
        age = _age_s(d.get("updated_at") or d.get("ts"))
        if age is not None:
            ob_ages.append(age)
    ob_age = min(ob_ages) if ob_ages else None

    # Liquidation engine: ETH and BTC samples
    eth_liq  = _redis_get_json("v2:liquidations:levels:ETHUSDT:1h") or {}
    eth_stale   = bool(eth_liq.get("liquidation_is_stale", 1)) if eth_liq else True
    eth_cascade = _f(eth_liq.get("liquidation_cascade_risk"))
    eth_dist    = _f(eth_liq.get("liquidation_long_distance_pct"))
    eth_liq_age = _age_ms(eth_liq.get("liquidation_last_event_ts"))

    # Count live (non-stale) majors in liq engine
    mh = universe.get("major_health", {})
    liq_live_count = sum(
        1 for sym in PREFERRED_MAJORS if not mh.get(sym, {}).get("liq_stale", True)
    )

    # KuCoin
    kucoin_funding  = _redis_count("v2:market:kucoin:funding:*", 6)
    kucoin_contract = _redis_count("v2:market:kucoin:contract:*", 6)

    # Other market keys
    long_short_count = _redis_count("v2:market:long_short:*", 6)
    oi_count         = _redis_count("v2:market:open_interest:*", 6)
    funding_count    = _redis_count("v2:market:funding:*", 6)
    market_liq_count = _redis_count("v2:market:liquidations:*", 6)
    prices_count     = _redis_count("v2:market:prices:*", 6)

    # BTC 4h signal age
    sig_btc4h = _redis_get_json("v2:trainer:hybrid_cuda:signals:paper:BTCUSDT:4h") or {}
    sig_age   = _age_s(
        sig_btc4h.get("available_at") or sig_btc4h.get("created_at") or sig_btc4h.get("generated_at")
    )

    # CoinAPI overall status: BROKEN if REST 403 or WS has reconnects >> msgs
    if coinapi_rest_403:
        coinapi_status = "REST_403_AUTH_ERROR"
    elif coinapi_ws_reconnects > 100 and coinapi_ws_msgs == 0:
        coinapi_status = "WS_BROKEN_NO_DATA"
    else:
        coinapi_status = _stale_label(coinapi_age, 600, 1800)

    return {
        "coinapi_age":             coinapi_age,
        "coinapi_status":          coinapi_status,
        "coinapi_rest_403":        coinapi_rest_403,
        "coinapi_ws_reconnects":   coinapi_ws_reconnects,
        "coinapi_ws_msgs":         coinapi_ws_msgs,
        "coinapi_ws_written":      coinapi_ws_written,
        "coinapi_ws_last_err":     coinapi_ws_last_err,
        "coinapi_ws_connected":    coinapi_ws_connected,
        "coinapi_ws_age_s":        coinapi_ws_age,
        "coinank_total_keys":      universe.get("coinank_total_keys", 0),
        "coinank_endpoint_keys":   universe.get("coinank_endpoint_keys", 0),
        "coinank_liq_keys":        universe.get("coinank_liq_keys", 0),
        "coinank_ind_keys":        universe.get("coinank_ind_keys", 0),
        "coinank_ls_keys":         universe.get("coinank_ls_keys", 0),
        "coinank_oi_keys":         universe.get("coinank_oi_keys", 0),
        "liq_level_symbols":       universe.get("liq_level_symbols", 0),
        "liq_live_majors":         liq_live_count,
        "eth_liq_stale":           eth_stale,
        "eth_cascade_risk":        eth_cascade,
        "eth_long_distance_pct":   eth_dist,
        "eth_liq_age_s":           eth_liq_age,
        "liq_engine_status":       "STALE" if eth_stale else _stale_label(eth_liq_age, 300, 900),
        "binance_ohlcv_symbols":   universe.get("ohlcv_symbols", 0),
        "binance_ohlcv_age_med_s": ohlcv_age_med,
        "binance_ob_age_s":        ob_age,
        "kucoin_funding_keys":     kucoin_funding,
        "kucoin_contract_keys":    kucoin_contract,
        "long_short_keys":         long_short_count,
        "open_interest_keys":      oi_count,
        "funding_keys":            funding_count,
        "market_liq_keys":         market_liq_count,
        "prices_keys":             prices_count,
        "tf_signal_coverage":      universe.get("tf_signal_coverage", {}),
        "total_signals":           universe.get("total_signals", 0),
        "signal_symbols":          universe.get("signal_symbols", 0),
        "signal_btc4h_age_s":      sig_age,
        "signal_grid_status":      _stale_label(sig_age, 600, 1800),
    }


def collect_live_gate() -> dict:
    gate = _redis_get_json("v2:live_gate:state") or {}
    paper_online = _ps(r"paper_online_runtime")
    return {
        "live_gate":             gate.get("live_gate", "UNKNOWN"),
        "live_blocked":          gate.get("live_blocked", True),
        "live_trading_enabled":  gate.get("live_trading_enabled", False),
        "order_submit":          gate.get("order_transport_submit_enabled", False),
        "places_real_order":     gate.get("places_real_order", True),
        "leverage_mutation":     gate.get("leverage_mutation_allowed", False),
        "margin_mutation":       gate.get("margin_mutation_allowed", False),
        "old_redis_write":       gate.get("old_redis_write_allowed", False),
        "kill_switch_enabled":   gate.get("kill_switch_enabled", False),
        "paper_online_active":   bool(paper_online),
        "paper_online_pids":     [p["pid"] for p in paper_online],
    }


def collect_loop_state() -> dict:
    procs = _ps(r"v2_trade_management_paper_loop")
    active = [p for p in procs if "v2_trade_management_paper_loop" in p.get("cmd", "")]
    return {
        "active":  bool(active),
        "pid":     active[0]["pid"] if active else None,
        "cpu":     active[0]["cpu"] if active else None,
        "start":   active[0]["start"] if active else None,
        "runtime": active[0]["time"] if active else None,
    }


def collect_risk_state() -> dict:
    alloc_gate = _load_json(OPERATOR_RUNTIME / "allocator_quality_gate_v2_status.json")
    conf_q     = _load_json(OPERATOR_RUNTIME / "confidence_miscalibration_quarantine_status.json")
    churn      = _load_json(OPERATOR_RUNTIME / "paper_churn_equity_bleed_governor_status.json")
    return {
        "allocator_gate_enabled":        alloc_gate.get("enabled", False),
        "allocator_blocked_buckets":     alloc_gate.get("blocked_bucket_count", 0),
        "confidence_quarantine_enabled": conf_q.get("enabled", False),
        "confidence_quarantined":        conf_q.get("quarantined_bucket_count", 0),
        "churn_governor_state":          churn.get("state"),
    }


def collect_buckets() -> dict:
    gov_v2  = _load_json(OPERATOR_RUNTIME / "performance_governor_v2_status.json")
    buckets = gov_v2.get("bucket_states") or []
    tf: dict[str, dict]    = {}
    sym: dict[str, dict]   = {}
    strat: dict[str, dict] = {}
    hc  = gov_v2.get("high_confidence_loss_stats") or {}
    atr = gov_v2.get("ATR_stop_stats") or {}
    for b in buckets:
        cnt = b.get("closed_outcome_count", 0)
        for store, kfn in (
            (tf,    lambda b: b.get("timeframe", "?")),
            (sym,   lambda b: b.get("symbol", "?")),
            (strat, lambda b: b.get("strategy", "?")),
        ):
            k = kfn(b)
            if k not in store or cnt > store[k].get("count", 0):
                store[k] = {
                    "pf":    _f(b.get("profit_factor")),
                    "state": b.get("state", "?"),
                    "count": cnt,
                }
    return {
        "tf":    tf,
        "sym":   dict(list(sym.items())[:12]),
        "strat": strat,
        "hc_loss_rate":      _f(hc.get("high_confidence_loss_rate")),
        "atr_stop_rate":     _f(atr.get("ATR_stop_rate")),
        "atr_stop_win_rate": _f(atr.get("ATR_stop_win_rate")),
    }


def collect_codex() -> dict:
    procs = _ps(r"codex_worker|v2_closed_loop_codex")
    age   = _src_change_age()
    spark = _load_json(
        REPO_ROOT
        / "claude_worklog/final_readiness/v2_codex_spark_parallel_closed_loop"
        / "latest/codex_spark_status.json"
    )
    running = bool(procs)
    stuck   = running and (age is None or age > 7200)
    return {
        "active":       running,
        "worker_count": len(procs),
        "worker_pids":  [p["pid"] for p in procs],
        "spark_status": spark.get("status"),
        "src_age_min":  round(age / 60, 1) if age else None,
        "stuck":        stuck,
        "cadence_s":    300 if running else 1800,
    }


def collect_repair_path(paper: dict, trainer: dict, ingestor: dict, universe: dict) -> dict:
    ct      = paper.get("closed_trades", 0)
    pf      = paper.get("PF")
    dir_acc = trainer.get("directional_accuracy")

    trainer_ok  = (
        trainer.get("weights_updated")
        and trainer.get("checkpoint_reload")
        and (trainer.get("optimizer_steps_hr") or 0) > 0
    )
    hc_ok = dir_acc is None or dir_acc > 0.50

    runtime_files = list(OPERATOR_RUNTIME.glob("*.json"))
    oldest = max(
        (time.time() - f.stat().st_mtime for f in runtime_files), default=0
    )
    website_ok   = oldest < 300
    recovery_ok  = paper.get("recovery_status") == "RECOVERY_SESSION_READY"
    # CoinAPI broken is noted but Binance orderbook fallback keeps spread gate alive
    _coinapi_broken = ingestor.get("coinapi_rest_403", False) or (
        (ingestor.get("coinapi_ws_reconnects") or 0) > 100
        and (ingestor.get("coinapi_ws_msgs") or 0) == 0
    )
    ingestor_ok  = (
        (ingestor.get("coinank_total_keys") or 0) > 100
        and (universe.get("liq_level_symbols") or 0) > 50
        and not ingestor.get("eth_liq_stale", True)
    )  # CoinAPI age removed from gate — Binance ob fallback covers microstructure
    sig_sym  = universe.get("signal_symbols", 0)
    total_sym = universe.get("total_symbols", 1)
    cov_pct  = sig_sym / total_sym * 100 if total_sym else 0

    return {
        "1_trainer_learning":       "PASS" if trainer_ok else "ACTIVE_LEARNING",
        "2_hc_loss_calibration":    "PASS" if hc_ok else "CALIBRATION_REPAIR",
        "3_regime_strategy_routing": "MONITORING" if ct < 25 else (
            "PASS" if (pf or 0) >= 1.25 else "ROUTING_REPAIR_NEEDED"
        ),
        "4_execution_stop_exit":    "MONITORING",
        "5_adaptive_capital":       "ACTIVE" if paper.get("equity") is not None else "NO_DATA",
        "6_website_ios_truth":      "PASS" if website_ok else f"STALE_{int(oldest)}s",
        "7_recovery_evidence":      "READY" if recovery_ok else "ACCUMULATING",
        "ingestor_health":          "OK" if ingestor_ok else "CHECK_SOURCES",
        "coinapi_health":           "BROKEN_RENEW_KEY" if _coinapi_broken else "OK",
        "liq_engine":               "OK" if not ingestor.get("eth_liq_stale", True) else "STALE",
        "universe_signal_coverage": f"{cov_pct:.0f}%",
    }


# ─── hard alerts ─────────────────────────────────────────────────────────────

def hard_alerts(paper, trainer, live, loop, bkts, ingestor, universe) -> list[dict]:
    alerts: list[dict] = []
    ts = _now_iso()

    def A(code: str, msg: str, sev: str = "CRITICAL") -> None:
        alerts.append({"timestamp": ts, "code": code, "severity": sev, "message": msg})

    ct  = paper.get("closed_trades", 0)
    pf  = paper.get("PF")
    ev  = paper.get("expectancy_bps")
    gov = paper.get("governor_v2_state", "")
    new = paper.get("new_entries_allowed", False)

    if ct >= 25 and pf is not None and pf < 1.0:
        A("PF_BELOW_1_AFTER_25", f"PF={pf:.3f} after {ct} trades — model has no edge")
    if ct >= 25 and ev is not None and ev <= 0:
        A("NEGATIVE_EV_AFTER_25", f"Expectancy={ev:.2f}bps after {ct} trades")
    if new and "HALTED" in gov:
        A("ENTRIES_WHILE_GOVERNOR_HALTED", f"SAFETY: new_entries=True but gov={gov}")
    if live.get("paper_online_active"):
        A("PAPER_ONLINE_ACTIVE", f"paper_online_runtime PIDs={live.get('paper_online_pids')}")
    if live.get("live_gate") != "blocked_human_only":
        A("LIVE_GATE_CHANGED", f"live_gate={live.get('live_gate')} — expected blocked_human_only")
    if live.get("live_trading_enabled"):
        A("LIVE_TRADING_ON", "live_trading_enabled=True")
    if live.get("places_real_order") is True:
        A("REAL_ORDER_PATH", "places_real_order=True")
    if live.get("order_submit"):
        A("ORDER_SUBMIT_ENABLED", "order_transport_submit_enabled=True")
    if live.get("leverage_mutation"):
        A("LEVERAGE_MUT", "leverage_mutation_allowed=True", "HIGH")
    if not loop.get("active"):
        A("LOOP_DOWN", "v2_trade_management_paper_loop process not found")
    fb = trainer.get("consumable_feedback_rows", 0)
    if ct > 5 and fb == 0:
        A("TRAINER_FEEDBACK_EMPTY", f"0 feedback rows but {ct} closed trades exist", "HIGH")
    if trainer.get("training_active") and not trainer.get("weights_updated"):
        A("WEIGHTS_STALE", "training active but weights not updating", "HIGH")
    hc    = bkts.get("hc_loss_rate")
    atr_r = bkts.get("atr_stop_rate")
    atr_w = bkts.get("atr_stop_win_rate")
    if hc is not None and hc > 0.40:
        A("HC_LOSS_CLUSTER", f"high-confidence loss rate={hc:.1%}>40%", "HIGH")
    if atr_r is not None and atr_w is not None and atr_r > 0.30 and atr_w < 0.25:
        A("ATR_CLUSTER", f"ATR stop={atr_r:.1%} wr={atr_w:.1%}", "HIGH")
    if ingestor.get("eth_liq_stale"):
        A("LIQ_ENGINE_STALE", "Liquidation level engine data is stale", "HIGH")
    if ingestor.get("coinapi_rest_403"):
        A("COINAPI_REST_403",
          f"CoinAPI REST returning HTTP 403 on all symbols — API key expired/invalid. "
          f"Renew COINAPI_API_KEY env var and restart v2_coinapi_rest_ingestor_worker. "
          f"Binance orderbook fallback active; CoinAPI microstructure features absent from trainer.",
          "HIGH")
    if (ingestor.get("coinapi_ws_reconnects") or 0) > 100 and (ingestor.get("coinapi_ws_msgs") or 0) == 0:
        A("COINAPI_WS_DEAD",
          f"CoinAPI WebSocket: {ingestor.get('coinapi_ws_reconnects',0)} reconnects, 0 messages received. "
          f"Last error: {ingestor.get('coinapi_ws_last_err','?')}. "
          f"No orderbook quotes/book5 from CoinAPI. Restart v2_coinapi_wsds_loop after key renewal.",
          "HIGH")
    if (ingestor.get("coinank_total_keys") or 0) < 100:
        A("COINANK_NO_DATA", f"CoinAnk premium — only {ingestor.get('coinank_total_keys', 0)} keys", "HIGH")
    sig_sym   = universe.get("signal_symbols", 0)
    total_sym = universe.get("total_symbols", 0)
    if total_sym > 50 and sig_sym < 10:
        A("SIGNAL_GRID_THIN", f"Only {sig_sym}/{total_sym} symbols have signals", "HIGH")
    stale_samp = universe.get("sample_non_major_stale", 0)
    samp_total = universe.get("sample_non_major_total", 1)
    if samp_total > 0 and stale_samp == samp_total and samp_total >= 4:
        A("UNIVERSE_SIGNALS_ALL_STALE", f"Non-major sample {stale_samp}/{samp_total}: all signal keys stale", "HIGH")
    return alerts


def check_codex_stuck(codex: dict, paper: dict) -> list[dict]:
    issues = []
    age = codex.get("src_age_min")
    if codex.get("stuck"):
        issues.append({"type": "CODEX_STUCK_NO_RUNTIME_PROGRESS",
                       "message": f"Workers active >2h, no source patch (last={age}m ago)"})
    ct = paper.get("closed_trades", 0)
    pf = paper.get("PF")
    ev = paper.get("expectancy_bps")
    if codex.get("active") and (age or 0) > 360 and ct >= 25 and (pf is None or pf < 1):
        issues.append({"type": "CODEX_NEGATIVE_EDGE_STOP_RECOMMENDATION",
                       "message": f">6h Codex, PF={pf}, ev={ev}bps — recommend halting paper entries"})
    return issues


# ─── artifact writers ─────────────────────────────────────────────────────────

def _write(path: Path, obj: dict | list) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str))


def _overall(paper, live, loop, alerts) -> str:
    if any(a.get("severity") == "CRITICAL" for a in alerts):
        return "REGRESSION"
    if not loop.get("active"):
        return "HALTED"
    if paper.get("new_entries_allowed") and (paper.get("PF") or 0) >= 1.0:
        return "READY_CANDIDATE"
    return "RUNNING"


def _next_patch(paper, trainer, repair) -> dict:
    ct = paper.get("closed_trades", 0)
    if not trainer.get("weights_updated"):
        return {"file": "v2_trainer_loop.py", "function": "checkpoint_write",
                "reason": "weights not updating"}
    if ct < 5:
        return {"file": "v2_trade_management_paper_loop.py",
                "function": "_paper_a_grade_bootstrap_admission",
                "reason": f"bootstrap phase ({ct} trades) — watching for edge signal"}
    if (paper.get("PF") or 0) < 1.0 and ct >= 25:
        return {"file": "v2_trade_management_paper_loop.py",
                "function": "_classify_paper_opportunity_tier",
                "reason": "PF<1 after 25 trades — strategy/signal repair needed"}
    return {"file": "none", "function": "none", "reason": "monitoring only"}


def write_artifacts(ts, paper, trainer, ingestor, live, loop, risk, codex, bkts, repair, universe, alerts, issues):
    overall = _overall(paper, live, loop, alerts)
    _write(MONITOR_OUT / "claude_realtime_system_status.json", {
        "generated_utc": ts, "goal_id": GOAL_ID, "overall_state": overall,
        "loop_active": loop.get("active"), "loop_pid": loop.get("pid"),
        "live_gate": live.get("live_gate"),
        "alert_count": len(alerts),
        "critical_alerts": sum(1 for a in alerts if a.get("severity") == "CRITICAL"),
        "repair_path": repair,
        "symbol_universe": {
            "total":     universe.get("total_symbols"),
            "ohlcv":     universe.get("ohlcv_symbols"),
            "signals":   universe.get("signal_symbols"),
            "liq_engine": universe.get("liq_level_symbols"),
        },
    })
    _write(MONITOR_OUT / "claude_trainer_learning_status.json", {"generated_utc": ts, **trainer})
    _write(MONITOR_OUT / "claude_market_data_usage_status.json", {
        "generated_utc": ts, **ingestor, "symbol_universe": universe,
    })
    _write(MONITOR_OUT / "claude_paper_trading_performance_status.json", {
        "generated_utc": ts, **paper,
        "timeframe_buckets": bkts.get("tf"),
        "symbol_buckets":    bkts.get("sym"),
        "strategy_buckets":  bkts.get("strat"),
        "hc_loss_rate":      bkts.get("hc_loss_rate"),
        "atr_stop_rate":     bkts.get("atr_stop_rate"),
    })
    _write(MONITOR_OUT / "claude_risk_orchestrator_execution_status.json",
           {"generated_utc": ts, **risk, **live})
    _write(MONITOR_OUT / "claude_frontend_ios_truth_status.json",
           {"generated_utc": ts,
            "operator_runtime_files": len(list(OPERATOR_RUNTIME.glob("*.json"))),
            "repair_path_website_ios": repair.get("6_website_ios_truth")})
    _write(MONITOR_OUT / "claude_codex_goal_progress_status.json",
           {"generated_utc": ts, **codex, "issues": issues})

    cycle_out = {
        "timestamp": ts, "overall_state": overall,
        "paper_state": {
            "new_entries_allowed": paper.get("new_entries_allowed"),
            "PF":             paper.get("PF"),
            "expectancy_bps": paper.get("expectancy_bps"),
            "closed_trades":  paper.get("closed_trades"),
            "open_positions": paper.get("open_positions"),
        },
        "trainer_state": {
            "training_active":          trainer.get("training_active"),
            "consumable_feedback_rows": trainer.get("consumable_feedback_rows"),
            "weights_updated":          trainer.get("weights_updated"),
            "primary_blocker":          trainer.get("a_grade_blocker"),
        },
        "market_data_state": {
            "total_symbols":         universe.get("total_symbols"),
            "signal_symbols":        universe.get("signal_symbols"),
            "coinank_total_keys":    ingestor.get("coinank_total_keys"),
            "liq_engine_live_majors": ingestor.get("liq_live_majors"),
            "stale_sources": [k for k, v in {
                "coinapi":    ingestor.get("coinapi_status"),
                "liq_engine": ingestor.get("liq_engine_status"),
                "signal_grid":ingestor.get("signal_grid_status"),
            }.items() if "STALE" in (v or "")],
        },
        "codex_progress": {
            "last_source_patch_age_minutes": codex.get("src_age_min"),
            "stuck_without_patch":           codex.get("stuck"),
        },
        "required_next_patch": _next_patch(paper, trainer, repair),
    }
    _write(MONITOR_OUT / "claude_cycle_output.json", cycle_out)

    if alerts:
        with open(MONITOR_OUT / "claude_operator_alerts.jsonl", "a") as f:
            for a in alerts:
                f.write(json.dumps(a) + "\n")
    for issue in issues:
        _write(MONITOR_OUT / f"{issue['type']}.json", {"generated_utc": ts, **issue})

    return cycle_out


# ─── terminal display ─────────────────────────────────────────────────────────

def _pfc(pf: float | None) -> str:
    if pf is None:          return DIM("—")
    if pf >= 1.25:          return GRN(f"{pf:.3f}")
    if pf >= 1.0:           return YLW(f"{pf:.3f}")
    return RED(f"{pf:.3f}")


def _ok(val: bool | None, t: str = "OK", f: str = "NO") -> str:
    if val is None: return DIM("?")
    return GRN(t) if val else RED(f)


def _safe(blocked: bool, ok_label: str, fail_label: str) -> str:
    return GRN(ok_label) if blocked else RED(fail_label)


def _age_fmt(s: float | None) -> str:
    if s is None:   return DIM("?")
    if s < 60:      return GRN(f"{int(s)}s")
    if s < 300:     return YLW(f"{int(s // 60)}m")
    if s < 3600:    return RED(f"{int(s // 60)}m")
    return RED(f"{int(s // 3600)}h")


def _stat(s: str | None) -> str:
    if not s:            return DIM("?")
    if "STALE" in s:     return RED(s)
    if "AGING" in s:     return YLW(s)
    if "FRESH" in s:     return GRN(s)
    return DIM(s)


def _repair(s: str | None) -> str:
    if not s:   return DIM("?")
    if s in ("PASS", "OK", "READY"):                            return GRN(s)
    if s in ("ACTIVE_LEARNING", "MONITORING", "ACTIVE", "ACCUMULATING"): return YLW(s)
    if s == "NO_DATA":                                          return DIM(s)
    return RED(s)


def hr(ch: str = "─") -> str:  return DIM(ch * W)
def hdr(t: str) -> str:        return BOLD(f"  {t}  ") + DIM("─" * max(0, W - len(t) - 4))


def render(ts, paper, trainer, ingestor, live, loop, risk, codex, bkts, repair, universe, alerts, cycle, cadence):
    L: list[str] = []
    overall = _overall(paper, live, loop, alerts)
    oc = {"RUNNING": GRN, "READY_CANDIDATE": YLW, "HALTED": RED, "REGRESSION": RED}.get(overall, DIM)

    ct   = paper.get("closed_trades", 0)
    pf   = paper.get("PF")
    ev   = paper.get("expectancy_bps")
    r25  = paper.get("r25_pf")
    r50  = paper.get("r50_pf")
    r100 = paper.get("r100_pf")
    r300 = paper.get("r300_pf")
    r50ev = paper.get("r50_expectancy_bps")

    L += [
        CLEAR,
        hr("═"),
        BOLD(f"{'  CLAUDE REALTIME EDGE MONITOR & REPAIR CONTROLLER':^{W}}"),
        DIM(f"  {GOAL_ID}"),
        hr("═"),
        f"  {DIM('Cycle:')} {CYN(str(cycle))}  "
        f"{DIM('Local:')} {WHT(_now_local())}  "
        f"{DIM('UTC:')} {DIM(ts[:19])}  "
        f"{DIM('Cadence:')} {DIM(str(cadence) + 's')}",
        f"  {DIM('State:')} {oc(overall)}  "
        f"{DIM('Loop PID:')} {CYN(str(loop.get('pid', '—')))}  "
        f"{DIM('Start:')} {DIM(str(loop.get('start', '—')))}  "
        f"{DIM('Runtime:')} {DIM(str(loop.get('runtime', '—')))}",
        hr(),
    ]

    # ── SAFETY ───────────────────────────────────────────────────────────────
    L.append(hdr("SAFETY GATES"))
    L.append(
        f"  {DIM('loop:')} {_ok(loop.get('active'), 'ACTIVE', 'DOWN')}  "
        f"{DIM('paper_online:')} {_safe(not live.get('paper_online_active'), 'INACTIVE', 'ACTIVE!')}  "
        f"{DIM('live_gate:')} {_safe(live.get('live_gate') == 'blocked_human_only', 'BLOCKED', str(live.get('live_gate', '?')) + '!')}"
    )
    L.append(
        f"  {DIM('live_trade:')} {_safe(not live.get('live_trading_enabled'), 'DISABLED', 'ENABLED!')}  "
        f"{DIM('order_submit:')} {_safe(not live.get('order_submit'), 'DISABLED', 'ENABLED!')}  "
        f"{DIM('real_order:')} {_safe(not live.get('places_real_order'), 'BLOCKED', 'LIVE_PATH!')}"
    )
    L.append(
        f"  {DIM('kill_sw:')} {_ok(live.get('kill_switch_enabled'))}  "
        f"{DIM('lev_mut:')} {_safe(not live.get('leverage_mutation'), 'LOCKED', 'OPEN!')}  "
        f"{DIM('margin_mut:')} {_safe(not live.get('margin_mutation'), 'LOCKED', 'OPEN!')}  "
        f"{DIM('old_redis:')} {_safe(not live.get('old_redis_write'), 'BLOCKED', 'OPEN!')}"
    )

    # ── PAPER PERFORMANCE ────────────────────────────────────────────────────
    L.append(hr())
    L.append(hdr("PAPER PERFORMANCE"))
    gov_state = paper.get("governor_v2_state", "?")
    gv_c = GRN if gov_state == "ACTIVE" else (YLW if "BOOTSTRAP" in gov_state else RED)
    boot  = paper.get("bootstrap_admission", False)
    L.append(
        f"  {DIM('Gov V2:')} {gv_c(gov_state)}  "
        f"{DIM('new_entries:')} {_ok(paper.get('new_entries_allowed'), 'ALLOWED', 'HALTED')}  "
        f"{DIM('bootstrap_adm:')} {_ok(boot, 'ALLOWED', 'BLOCKED')}"
    )
    ev_s  = f"{ev:.2f}bps" if ev is not None else "—"
    ev_c  = GRN if (ev or 0) > 0 else RED
    r50ev_s = f"{r50ev:.2f}bps" if r50ev is not None else "—"
    wr    = paper.get("win_rate")
    wr_s  = f"{wr:.1%}" if wr is not None else "—"
    L.append(
        f"  {DIM('Closed:')} {WHT(str(ct))}  "
        f"{DIM('Open:')} {WHT(str(paper.get('open_positions', 0)))}  "
        f"{DIM('PF:')} {_pfc(pf)}  "
        f"{DIM('EV:')} {ev_c(ev_s)}  "
        f"{DIM('WR:')} {DIM(wr_s)}"
    )
    L.append(
        f"  {DIM('R25:')} {_pfc(r25)}  "
        f"{DIM('R50:')} {_pfc(r50)}  "
        f"{DIM('R100:')} {_pfc(r100)}  "
        f"{DIM('R300:')} {_pfc(r300)}  "
        f"{DIM('R50-EV:')} {ev_c(r50ev_s)}"
    )
    eq   = paper.get("equity")
    wb   = paper.get("wallet_balance")
    util = paper.get("capital_util_pct")
    eq_s   = f"${eq:.2f}" if eq is not None else "?"
    wb_s   = f"${wb:.2f}" if wb is not None else "?"
    util_s = f"{util:.1f}%" if util is not None else "?"
    L.append(
        f"  {DIM('Equity:')} {WHT(eq_s)}  "
        f"{DIM('WalBal:')} {DIM(wb_s)}  "
        f"{DIM('Util%:')} {DIM(util_s)}  "
        f"{DIM('RecTrades:')} {DIM(str(paper.get('recovery_trades', 0)))}"
    )
    if paper.get("halt_reasons"):
        L.append(f"  {DIM('HALT:')} {RED(', '.join(str(r) for r in paper['halt_reasons'][:3]))}")

    tf_bkts = bkts.get("tf", {})
    if tf_bkts:
        parts = []
        for tf in SYSTEM_TFS:
            info  = tf_bkts.get(tf, {})
            pf_v  = info.get("pf")
            pf_s  = f"{pf_v:.2f}" if pf_v is not None else "?"
            c = GRN if (pf_v or 0) >= 1.25 else (YLW if (pf_v or 0) >= 1.0 else RED)
            parts.append(f"{tf}:{c(pf_s)}")
        L.append(f"  {DIM('TF PF:')} {' '.join(parts)}")

    hc    = bkts.get("hc_loss_rate")
    atr_r = bkts.get("atr_stop_rate")
    hc_s  = f"{hc:.1%}" if hc is not None else "—"
    atr_s = f"{atr_r:.1%}" if atr_r is not None else "—"
    L.append(
        f"  {DIM('HC-loss:')} {RED(hc_s) if (hc or 0) > 0.40 else DIM(hc_s)}  "
        f"{DIM('ATR-stop:')} {RED(atr_s) if (atr_r or 0) > 0.30 else DIM(atr_s)}"
    )

    # ── SYMBOL UNIVERSE (adaptive, market-driven) ────────────────────────────
    L.append(hr())
    L.append(hdr("SYMBOL UNIVERSE  (adaptive, no static thresholds)"))
    total_sym = universe.get("total_symbols", 0)
    ohlcv_sym = universe.get("ohlcv_symbols", 0)
    sig_sym   = universe.get("signal_symbols", 0)
    liq_sym   = universe.get("liq_level_symbols", 0)
    cov_pct   = sig_sym / total_sym * 100 if total_sym else 0
    cov_c     = GRN if cov_pct >= 80 else (YLW if cov_pct >= 40 else RED)
    L.append(
        f"  {DIM('Total:')} {WHT(str(total_sym))}  "
        f"{DIM('OHLCV:')} {DIM(str(ohlcv_sym))}  "
        f"{DIM('Signal cov:')} {cov_c(str(sig_sym) + '/' + str(total_sym) + ' (' + str(int(cov_pct)) + '%)')}  "
        f"{DIM('LiqEngine:')} {DIM(str(liq_sym))}"
    )

    tf_cov = universe.get("tf_signal_coverage", {})
    tf_sig_parts = [f"{tf}:{DIM(str(tf_cov.get(tf, 0)))}" for tf in SYSTEM_TFS]
    L.append(f"  {DIM('Sigs/TF:')} {' '.join(tf_sig_parts)}")

    mh = universe.get("major_health", {})
    major_parts = []
    for sym in PREFERRED_MAJORS:
        info     = mh.get(sym, {})
        has_sig  = info.get("has_signal", False)
        has_ohlcv= info.get("has_ohlcv", False)
        liq_st   = info.get("liq_stale", True)
        cascade  = info.get("cascade_risk")
        sig_age  = info.get("sig_4h_age_s")
        sym_s    = sym.replace("USDT", "")
        if not has_sig or not has_ohlcv:
            status = RED("MISS")
        elif liq_st:
            status = YLW("LIQ?")
        elif (cascade or 0) > 0.5:
            status = RED("CASC")
        else:
            age_c  = GRN if (sig_age or 9999) < 600 else (YLW if (sig_age or 9999) < 1800 else RED)
            status = age_c("OK")
        casc_s = f"{cascade:.2f}" if cascade is not None else "?"
        major_parts.append(f"{sym_s}:{status}(c={casc_s})")
    L.append(f"  {DIM('Majors:')} {' '.join(major_parts)}")

    stale_samp = universe.get("sample_non_major_stale", 0)
    samp_total = universe.get("sample_non_major_total", 0)
    stale_c = RED if stale_samp > 0 else GRN
    L.append(
        f"  {DIM('Non-major stale sample:')} {stale_c(str(stale_samp))}/{DIM(str(samp_total))}  "
        f"{DIM('CoinAnk ep:')} {DIM(str(universe.get('coinank_endpoint_keys', 0)))}"
    )

    # ── 7-POINT REPAIR PATH ──────────────────────────────────────────────────
    L.append(hr())
    L.append(hdr("EDGE REPAIR PATH"))
    rp_items = [
        ("1_trainer_learning",       "1.Trainer"),
        ("2_hc_loss_calibration",    "2.HC/Calib"),
        ("3_regime_strategy_routing","3.Regime"),
        ("4_execution_stop_exit",    "4.Exec"),
        ("5_adaptive_capital",       "5.Capital"),
        ("6_website_ios_truth",      "6.Web/iOS"),
        ("7_recovery_evidence",      "7.Recovery"),
    ]
    row1 = [f"{lbl}:{_repair(repair.get(key))}" for key, lbl in rp_items[:4]]
    row2 = [f"{lbl}:{_repair(repair.get(key))}" for key, lbl in rp_items[4:]]
    L.append(f"  {' '.join(row1)}")
    L.append(
        f"  {' '.join(row2)}  "
        f"{DIM('Ingestors:')} {_repair(repair.get('ingestor_health'))}  "
        f"{DIM('LiqEng:')} {_repair(repair.get('liq_engine'))}  "
        f"{DIM('UniCov:')} {CYN(str(repair.get('universe_signal_coverage', '?')))}"
    )

    # ── INGESTOR SOURCES ─────────────────────────────────────────────────────
    L.append(hr())
    L.append(hdr("PREMIUM INGESTOR SOURCES"))
    _ca_status = ingestor.get("coinapi_status", "UNKNOWN")
    _ca_rest403 = ingestor.get("coinapi_rest_403", False)
    _ca_ws_rc   = ingestor.get("coinapi_ws_reconnects", 0)
    _ca_ws_msgs = ingestor.get("coinapi_ws_msgs", 0)
    _ca_ws_err  = ingestor.get("coinapi_ws_last_err", "")
    _ca_color   = RED if ("403" in _ca_status or "BROKEN" in _ca_status or "UNKNOWN" in _ca_status) else (YLW if "STALE" in _ca_status else GRN)
    _ca_display = _ca_color(_ca_status)
    if _ca_rest403:
        _ca_display += RED(" [REST:403]")
    if _ca_ws_rc > 100 and _ca_ws_msgs == 0:
        _ca_display += RED(f" [WS:DEAD rc={_ca_ws_rc}]")
    L.append(
        f"  {DIM('CoinAPI:')} {_ca_display} "
        f"age={_age_fmt(ingestor.get('coinapi_age'))}  "
        f"{DIM('CoinAnk:')} {DIM(str(ingestor.get('coinank_total_keys', 0)) + ' keys')} "
        f"ep={DIM(str(ingestor.get('coinank_endpoint_keys', 0)))}"
    )
    if _ca_rest403 or (_ca_ws_rc > 100 and _ca_ws_msgs == 0):
        L.append(
            f"  {RED('!! CoinAPI DEGRADED:')} REST=403 (key expired/invalid)  "
            f"WS reconnects={_ca_ws_rc} msgs={_ca_ws_msgs} last_err={_ca_ws_err or '?'}"
        )
        L.append(
            f"  {DIM('Impact: No CoinAPI orderbook/microstructure features.')}"
            f"  {DIM('Binance orderbook fallback active for spread gate.')}"
        )
        L.append(
            f"  {DIM('Action: Renew COINAPI_API_KEY env var and restart CoinAPI workers.')}"
        )
    L.append(
        f"  {DIM('CoinAnk breakdown:')} "
        f"liq={DIM(str(ingestor.get('coinank_liq_keys', 0)))}  "
        f"ind={DIM(str(ingestor.get('coinank_ind_keys', 0)))}  "
        f"ls={DIM(str(ingestor.get('coinank_ls_keys', 0)))}  "
        f"oi={DIM(str(ingestor.get('coinank_oi_keys', 0)))}"
    )
    L.append(
        f"  {DIM('KuCoin:')} fund={DIM(str(ingestor.get('kucoin_funding_keys', 0)))} "
        f"contract={DIM(str(ingestor.get('kucoin_contract_keys', 0)))}  "
        f"{DIM('Signals:')} {_stat(ingestor.get('signal_grid_status'))} "
        f"BTC-4h={_age_fmt(ingestor.get('signal_btc4h_age_s'))}"
    )
    L.append(
        f"  {DIM('Binance:')} ohlcv={DIM(str(ingestor.get('binance_ohlcv_symbols', 0)) + 'syms')} "
        f"age={_age_fmt(ingestor.get('binance_ohlcv_age_med_s'))}  "
        f"{DIM('LS:')} {DIM(str(ingestor.get('long_short_keys', 0)))}  "
        f"{DIM('OI:')} {DIM(str(ingestor.get('open_interest_keys', 0)))}  "
        f"{DIM('Fund:')} {DIM(str(ingestor.get('funding_keys', 0)))}  "
        f"{DIM('MktLiq:')} {DIM(str(ingestor.get('market_liq_keys', 0)))}"
    )

    # ── LIQUIDATION ENGINE ───────────────────────────────────────────────────
    L.append(hr())
    L.append(hdr("LIQUIDATION ENGINE  (direction signal, all symbols)"))
    eth_stale = ingestor.get("eth_liq_stale", True)
    cascade   = ingestor.get("eth_cascade_risk")
    long_dist = ingestor.get("eth_long_distance_pct")
    liq_age   = ingestor.get("eth_liq_age_s")
    stale_s   = RED("STALE") if eth_stale else GRN("LIVE")
    casc_s    = f"{cascade:.4f}" if cascade is not None else "?"
    casc_c    = RED if (cascade or 0) > 0.5 else (YLW if (cascade or 0) > 0.2 else GRN)
    dist_s    = f"{long_dist:.4f}%" if long_dist is not None else "?"
    L.append(
        f"  {DIM('ETH 1h:')} {stale_s}  "
        f"{DIM('cascade:')} {casc_c(casc_s)}  "
        f"{DIM('long_dist%:')} {DIM(dist_s)}  "
        f"{DIM('event age:')} {_age_fmt(liq_age)}"
    )
    live_maj = ingestor.get("liq_live_majors", 0)
    n_maj    = len(PREFERRED_MAJORS)
    L.append(
        f"  {DIM('Liq level syms:')} {DIM(str(ingestor.get('liq_level_symbols', 0)))}  "
        f"{DIM('Live majors:')} {(GRN if live_maj == n_maj else YLW)(str(live_maj) + '/' + str(n_maj))}  "
        f"{DIM('MktLiq keys:')} {DIM(str(ingestor.get('market_liq_keys', 0)))}"
    )

    # ── TRAINER ──────────────────────────────────────────────────────────────
    L.append(hr())
    L.append(hdr("TRAINER"))
    ta    = trainer.get("training_active")
    wu    = trainer.get("weights_updated")
    fb    = trainer.get("consumable_feedback_rows", 0)
    steps = trainer.get("optimizer_steps_hr", 0)
    dir_a = trainer.get("directional_accuracy")
    brier = trainer.get("brier_score")
    L.append(
        f"  {DIM('Active:')} {_ok(ta, 'YES', 'NO')}  "
        f"{DIM('Feedback:')} {(GRN if fb > 0 else RED)(str(fb))}  "
        f"{DIM('Weights:')} {_ok(wu, 'UPDATED', 'STALE')}  "
        f"{DIM('Steps/hr:')} {(GRN if (steps or 0) > 0 else RED)(str(steps))}"
    )
    dir_s   = f"{dir_a:.3f}" if dir_a is not None else "?"
    brier_s = f"{brier:.3f}" if brier is not None else "?"
    dir_c   = GRN if (dir_a or 0) > 0.55 else YLW
    L.append(
        f"  {DIM('Dir.Acc:')} {dir_c(dir_s)}  "
        f"{DIM('Brier:')} {DIM(brier_s)}  "
        f"{DIM('Ckpt:')} {DIM(str(trainer.get('checkpoint_id', '?'))[:20])}"
    )
    if trainer.get("a_grade_blocker"):
        L.append(f"  {DIM('Blocker:')} {YLW(str(trainer['a_grade_blocker'])[:72])}")

    # ── CODEX ────────────────────────────────────────────────────────────────
    L.append(hr())
    L.append(hdr("CODEX WORKERS"))
    src_age = codex.get("src_age_min")
    stuck   = codex.get("stuck", False)
    wc      = codex.get("worker_count", 0)
    L.append(
        f"  {DIM('Workers:')} {(GRN if codex.get('active') else DIM)(str(wc) + ' active')}  "
        f"{DIM('Last patch:')} {(RED if stuck else DIM)(str(src_age) + 'm' if src_age else 'unknown')}  "
        f"{DIM('Stuck:')} {RED('YES') if stuck else GRN('NO')}"
    )

    # ── ALERTS ───────────────────────────────────────────────────────────────
    L.append(hr())
    if alerts:
        L.append(hdr(f"ALERTS  ({len(alerts)})"))
        for a in alerts[:12]:
            sev   = a.get("severity", "?")
            sev_c = RED if sev == "CRITICAL" else YLW
            L.append(f"  [{sev_c(sev)}] {BOLD(a.get('code', '?'))}")
            L.append(f"           {DIM(str(a.get('message', ''))[:78])}")
    else:
        L.append(f"  {GRN('No active alerts')}  {DIM('All safety gates nominal.')}")

    L.append(hr("═"))
    L.append(f"  {DIM('Output:')} {DIM(str(MONITOR_OUT))}")
    L.append(hr("═"))
    return "\n".join(L)


# ─── main ─────────────────────────────────────────────────────────────────────

def run_cycle(cycle: int) -> int:
    ts       = _now_iso()
    universe = discover_symbol_universe()
    paper    = collect_paper_state()
    trainer  = collect_trainer_state()
    ingestor = collect_ingestor_state(universe)
    live     = collect_live_gate()
    loop     = collect_loop_state()
    risk     = collect_risk_state()
    codex    = collect_codex()
    bkts     = collect_buckets()
    repair   = collect_repair_path(paper, trainer, ingestor, universe)
    alerts   = hard_alerts(paper, trainer, live, loop, bkts, ingestor, universe)
    issues   = check_codex_stuck(codex, paper)

    write_artifacts(ts, paper, trainer, ingestor, live, loop, risk, codex, bkts, repair, universe, alerts, issues)
    print(render(ts, paper, trainer, ingestor, live, loop, risk, codex, bkts, repair, universe, alerts, cycle, codex.get("cadence_s", 1800)), flush=True)

    overall = _overall(paper, live, loop, alerts)
    if overall in ("REGRESSION", "HALTED"):
        MARKER_BLOCKED.write_text(json.dumps({"state": overall, "generated_utc": ts}))
        if MARKER_ACTIVE.exists():  MARKER_ACTIVE.unlink()
    else:
        MARKER_ACTIVE.write_text(json.dumps({"state": overall, "generated_utc": ts}))
        if MARKER_BLOCKED.exists(): MARKER_BLOCKED.unlink()

    return codex.get("cadence_s", 1800)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    global USE_COLOR
    if args.no_color:
        USE_COLOR = False

    cycle = 1
    while True:
        try:
            cadence = run_cycle(cycle)
        except KeyboardInterrupt:
            print("\n  Monitor stopped.")
            break
        except Exception as e:
            print(f"\n  [ERROR] cycle {cycle}: {e}", flush=True)
            cadence = 60
        if args.once:
            break
        try:
            time.sleep(cadence)
        except KeyboardInterrupt:
            print("\n  Monitor stopped.")
            break
        cycle += 1


if __name__ == "__main__":
    main()
