import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

_redis_client_cache = None

def _get_redis():
    global _redis_client_cache
    if _redis_client_cache is None:
        try:
            import redis as _redis_mod
            _redis_client_cache = _redis_mod.Redis()
        except Exception:
            pass
    return _redis_client_cache


@dataclass
class RiskResult:
    ok: bool
    code: str
    severity: str
    meta: Dict[str, Any]


def is_risk_add_action(action: str, margin_usd: float = 0.0) -> bool:
    act = str(action or "").upper()

    # FIX I: CLOSE/REDUCE/PARTIAL/PROTECTIVE actions are NOT risk-adding
    # even when margin_usd > 0 (informational field, not actual margin addition).
    _REDUCE_TOKENS = ("CLOSE", "PARTIAL", "REDUCE", "DECREASE", "EXIT",
                       "TAKE_PROFIT", "STOP_LOSS", "TP_", "SL_", "SET_TAKE",
                       "SET_STOP", "HOLD", "NONE", "WAIT", "HEARTBEAT")
    # Composite flips (close+open) are risk-adding even though they include CLOSE_* tokens.
    _is_composite_flip = ("CLOSE" in act) and (("OPEN_" in act) or ("AND_OPEN_" in act) or ("FLIP" in act) or ("CLOSE_AND" in act))
    if any(tok in act for tok in _REDUCE_TOKENS) and not _is_composite_flip:
        return False

    return bool(
        act.startswith("OPEN")
        or act.startswith("INCREASE")
        or act.startswith("ADD_")
        or act.startswith("ADD_TO_")
        or "CLOSE_AND" in act
        or _is_composite_flip
        or margin_usd > 0
    )


def _extract_timeframe(signal: Dict[str, Any]) -> Optional[str]:
    tf = signal.get("timeframe") or signal.get("tf") or signal.get("interval")
    if not tf and isinstance(signal.get("metadata"), dict):
        meta = signal.get("metadata") or {}
        tf = meta.get("timeframe") or meta.get("tf") or meta.get("interval")
    tf = str(tf or "").strip()
    if tf and tf != "?":
        return tf
    return None


def _extract_signal_id(signal: Dict[str, Any]) -> Optional[str]:
    sid = signal.get("signal_id") or signal.get("id")
    if not sid and isinstance(signal.get("metadata"), dict):
        meta = signal.get("metadata") or {}
        sid = meta.get("signal_id") or meta.get("id")
    sid = str(sid or "").strip()
    return sid or None


def _symbol_bucket(symbol: str) -> str:
    sym = str(symbol or "").upper().strip()
    if sym in {"BTCUSDT", "ETHUSDT"}:
        return "major"
    try:
        from config import SYMBOL_LEVERAGE_CONFIG
    except Exception:
        SYMBOL_LEVERAGE_CONFIG = {}
    try:
        lev_cfg = SYMBOL_LEVERAGE_CONFIG.get(sym) or {}
        max_lev = float(lev_cfg.get("max_leverage") or 0.0)
    except Exception:
        max_lev = 0.0
    if max_lev and max_lev <= 15:
        return "meme"
    return "alt"


# ── Staleness guard constant (seconds) ───────────────────────────────────────
PORTFOLIO_STALE_THRESHOLD_S = 300  # 5 min; equity writer runs every ~60s

# ── Liq-buffer thresholds (single source of truth) ──────────────────────────
LIQ_MIN_THRESHOLDS = {"major": 1.3, "alt": 1.6, "meme": 2.0}


def get_liq_min_for_bucket(bucket: str) -> float:
    """Return minimum liquidation distance % for a symbol bucket."""
    return float(LIQ_MIN_THRESHOLDS.get(bucket, LIQ_MIN_THRESHOLDS["alt"]))


def extract_liq_distance(signal: Dict[str, Any]) -> Optional[float]:
    """Extract liquidation distance % from a signal/winner dict.

    Checks pos_liq_distance_pct (leverage-derived, preferred for safety gates),
    then explicit keys, metadata.liquidation_proximity, leverage fallback,
    and dq_fallback. Returns None if no source available.
    """
    liq: Optional[float] = None

    # 0. Preferred: pos_liq_distance_pct (leverage-derived with haircut)
    try:
        if "pos_liq_distance_pct" in signal:
            liq = float(signal["pos_liq_distance_pct"])
    except Exception:
        pass

    # 1. Explicit top-level keys
    if liq is None:
        for key in ("liq_distance_pct", "liquidation_distance_pct", "min_liq_distance_pct"):
            try:
                if key in signal:
                    liq = float(signal[key])
                    break
            except Exception:
                pass

    # 2. Nested metadata.liquidation_proximity
    if liq is None and isinstance(signal.get("metadata"), dict):
        try:
            prox = signal["metadata"].get("liquidation_proximity") or {}
            if isinstance(prox, dict) and prox.get("distance_pct") is not None:
                liq = float(prox["distance_pct"])
        except Exception:
            pass

    # 3. Fallback: derive from leverage (100 / lev)
    if liq is None:
        try:
            lev = signal.get("leverage") or signal.get("recommended_leverage")
            if lev is None and isinstance(signal.get("metadata"), dict):
                lev = signal["metadata"].get("leverage")
            lev = float(lev) if lev is not None else 0.0
        except Exception:
            lev = 0.0
        if lev > 0:
            try:
                liq = max(0.0, 100.0 / lev)
            except Exception:
                pass

    # 4. dq_fallback: clamp to min_liq when data-quality source is ok
    #    (needs symbol for bucket lookup — caller can pass pre-resolved bucket)
    #    Handled in check_liq_buffer instead to keep this function stateless.

    return liq


def check_liq_buffer(
    symbol: str,
    signal: Dict[str, Any],
    bucket: Optional[str] = None,
) -> Dict[str, Any]:
    """Single-source liq-buffer check used by both ORCH-09 and precheck.

    Returns dict with keys:
      ok       : bool  — True if buffer is sufficient
      bucket   : str   — symbol bucket (major/alt/meme)
      liq      : float | None — computed liq distance %
      min_liq  : float — threshold for this bucket
      reason   : str   — 'OK', 'LIQ_NONE', 'LIQ_TOO_LOW'
    """
    if bucket is None:
        bucket = _symbol_bucket(symbol)
    min_liq = get_liq_min_for_bucket(bucket)

    liq = extract_liq_distance(signal)

    # dq_fallback: if data-quality source ok, clamp liq to min_liq
    dq_fallback_used = False
    dq_source_ok = False
    if isinstance(signal.get("metadata"), dict):
        dq_fallback_used = bool(signal["metadata"].get("dq_fallback_used"))
        dq_source_ok = bool(signal["metadata"].get("dq_source_ok"))
    dq_fallback_used = bool(signal.get("dq_fallback_used") or dq_fallback_used)
    dq_source_ok = bool(signal.get("dq_source_ok") or dq_source_ok)
    if dq_fallback_used and dq_source_ok:
        try:
            if liq is None or float(liq) < float(min_liq):
                liq = float(min_liq)
        except Exception:
            pass

    if liq is None:
        return {"ok": False, "bucket": bucket, "liq": None, "min_liq": min_liq, "reason": "LIQ_NONE"}
    if liq < min_liq:
        return {"ok": False, "bucket": bucket, "liq": liq, "min_liq": min_liq, "reason": "LIQ_TOO_LOW"}
    return {"ok": True, "bucket": bucket, "liq": liq, "min_liq": min_liq, "reason": "OK"}


def build_portfolio_snapshot(redis_client, account_id: str) -> Dict[str, Any]:
    acct = str(account_id or "primary").strip().lower()
    snap: Dict[str, Any] = {
        "account_id": acct,
        "equity": 0.0,
        "margin_util": 0.0,
        "free_margin_ratio": 0.0,
        "available_margin_usd": 0.0,
        "used_margin_usd": 0.0,
        "updated_ts_ms": 0,
        "open_positions": 0,
        "open_symbols": set(),
        "per_symbol_margin_usd": {},
        "bucket_margin": {"major": 0.0, "alt": 0.0, "meme": 0.0},
        "post_cascade_active": False,
        "portfolio_mode": None,
    }
    if not redis_client:
        return snap

    try:
        raw = redis_client.get(f"portfolio:equity:{acct}")
    except Exception:
        raw = None
    if raw:
        try:
            raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
            eq = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(eq, dict):
                snap["equity"] = float(
                    eq.get("equity_usd")
                    or eq.get("margin_balance_usd")
                    or eq.get("wallet_balance_usd")
                    or eq.get("wallet_balance")
                    or 0.0
                )
                try:
                    snap["margin_util"] = float(eq.get("margin_util") or eq.get("margin_utilization") or 0.0)
                except Exception:
                    pass
                try:
                    snap["free_margin_ratio"] = float(eq.get("free_margin_ratio") or 0.0)
                except Exception:
                    pass
                try:
                    snap["available_margin_usd"] = float(
                        eq.get("available_margin_usd")
                        or eq.get("available_balance_usd")
                        or 0.0
                    )
                except Exception:
                    pass
                try:
                    snap["updated_ts_ms"] = int(
                        eq.get("ts_ms") or eq.get("updated_ts_ms") or 0
                    )
                except Exception:
                    pass
                try:
                    snap["used_margin_usd"] = float(
                        eq.get("used_margin_usd")
                        or eq.get("initial_margin_usd")
                        or 0.0
                    )
                except Exception:
                    pass
                # ── Derive free_margin_ratio from available_margin/equity when not explicitly set ──
                if snap["free_margin_ratio"] <= 0.0 and snap["equity"] > 0.0:
                    try:
                        avail = float(eq.get("available_margin_usd") or eq.get("available_balance_usd") or 0.0)
                        if avail > 0.0:
                            snap["free_margin_ratio"] = min(1.0, avail / snap["equity"])
                    except Exception:
                        pass
                # Final fallback: derive from margin_util
                if snap["free_margin_ratio"] <= 0.0 and snap["equity"] > 0.0:
                    snap["free_margin_ratio"] = max(0.0, 1.0 - snap["margin_util"])
        except Exception:
            pass

    try:
        raw_map = redis_client.hgetall(f"portfolio:positions:{acct}") or {}
    except Exception:
        raw_map = {}

    for k, v in raw_map.items():
        try:
            ks = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
        except Exception:
            ks = str(k)
        if ":" not in ks:
            continue
        sym, _side = ks.rsplit(":", 1)
        sym_u = str(sym or "").upper().strip()
        try:
            vs = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else v
        except Exception:
            vs = v
        try:
            pos = json.loads(vs) if isinstance(vs, str) and vs.strip().startswith("{") else {}
        except Exception:
            pos = {}
        if not isinstance(pos, dict):
            continue
        try:
            sz = abs(float(pos.get("size", 0) or pos.get("positionAmt", 0) or pos.get("qty", 0) or 0))
        except Exception:
            sz = 0.0
        if sz <= 0:
            continue
        snap["open_symbols"].add(sym_u)
        try:
            m = float(pos.get("margin_used") or pos.get("initialMargin") or 0.0)
        except Exception:
            m = 0.0
        snap["per_symbol_margin_usd"].setdefault(sym_u, 0.0)
        snap["per_symbol_margin_usd"][sym_u] += abs(m)
        snap.setdefault("_per_sym_side_margin", {})
        snap["_per_sym_side_margin"].setdefault(sym_u, {"LONG": 0.0, "SHORT": 0.0})
        _s_up = str(_side).upper()
        if _s_up in ("LONG", "SHORT"):
            snap["_per_sym_side_margin"][sym_u][_s_up] += abs(m)

    snap["open_positions"] = len(snap["open_symbols"])
    _side_m = snap.get("_per_sym_side_margin", {})
    for sym_u, m in snap["per_symbol_margin_usd"].items():
        bucket = _symbol_bucket(sym_u)
        _sm = _side_m.get(sym_u, {})
        _long_m = float(_sm.get("LONG", 0.0))
        _short_m = float(_sm.get("SHORT", 0.0))
        if _long_m > 0 and _short_m > 0:
            _net_directional = max(_long_m, _short_m)
        else:
            _net_directional = m
        snap["bucket_margin"][bucket] = float(snap["bucket_margin"].get(bucket, 0.0)) + float(_net_directional)

    try:
        snap["post_cascade_active"] = bool(redis_client.get(f"wma:post_cascade:{acct}"))
    except Exception:
        snap["post_cascade_active"] = False

    return snap


def assert_risk(
    layer: str,
    phase: Dict[str, Any],
    portfolio: Dict[str, Any],
    signal: Dict[str, Any],
) -> RiskResult:
    layer_u = str(layer or "").upper()
    action = str(signal.get("action_name") or signal.get("action") or "").upper()
    symbol = str(signal.get("symbol") or "").upper().strip()
    margin_usd = float(signal.get("margin_usd") or signal.get("margin") or 0.0)
    action_category = str(signal.get("action_category") or signal.get("category") or "").upper()
    is_risk_add = is_risk_add_action(action, margin_usd)

    meta_blob = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
    risk_intent = str(signal.get("risk_intent") or meta_blob.get("risk_intent") or "").upper().strip()
    is_recovery_hedge = (risk_intent == "RECOVERY_HEDGE")
    if not is_recovery_hedge and "HEDGE" in action:
        is_recovery_hedge = True
    if is_recovery_hedge:
        is_risk_add = False

    # ORCH schema checks
    if layer_u == "ORCH":
        if not action:
            return RiskResult(False, "ORCH-01", "BLOCK", {"reason": "missing_action"})
        if not symbol:
            return RiskResult(False, "ORCH-02", "BLOCK", {"reason": "missing_symbol"})
        tf = _extract_timeframe(signal)
        if not tf:
            return RiskResult(False, "ORCH-03", "BLOCK", {"reason": "missing_tf"})
        sid = _extract_signal_id(signal)
        if not sid:
            return RiskResult(False, "ORCH-04", "BLOCK", {"reason": "missing_signal_id"})
        pm = str(portfolio.get("portfolio_mode") or "").upper()
        if pm == "EMERGENCY":
            return RiskResult(False, "ORCH-06", "BLOCK", {"reason": "portfolio_mode_emergency"})
        if bool(portfolio.get("post_cascade_active")):
            return RiskResult(False, "ORCH-07", "BLOCK", {"reason": "post_cascade_active"})

    equity = float(portfolio.get("equity") or 0.0)
    margin_util = float(portfolio.get("margin_util") or 0.0)
    free_margin_ratio = float(portfolio.get("free_margin_ratio") or 0.0)
    open_positions = int(portfolio.get("open_positions") or 0)
    open_symbols = portfolio.get("open_symbols") or set()

    max_mu = float(phase.get("max_mu") or 0.0)
    min_fmr = float(phase.get("min_free_margin_ratio") or 0.0)
    per_pos_pct = float(phase.get("per_pos_margin_pct") or 0.0)
    max_positions = int(phase.get("max_positions") or 0)

    if not equity or equity <= 0 or equity != equity:
        return RiskResult(False, "HALT-04", "HALT", {"reason": "equity_missing_or_nan"})

    if is_risk_add and action_category in {"OPEN_RISK", "OPEN", "ENTRY"}:
        tf = _extract_timeframe(signal)
        if not tf:
            return RiskResult(False, "MISSING_TF", "BLOCK", {"reason": "missing_tf_open_risk"})

    # Trader portfolio checks
    if layer_u == "TRADER":
        if str(portfolio.get("portfolio_mode") or "").upper() in ("STRESS", "EMERGENCY"):
            # Protective hedges bypass STRESS mode — they REDUCE net exposure
            if not is_recovery_hedge:
                return RiskResult(False, "TRD-02", "BLOCK", {"reason": "portfolio_mode_block"})

    if is_risk_add:
        # MU check (after)
        mu_after = margin_util
        if equity > 0:
            mu_after = margin_util + (margin_usd / equity)
        if max_mu > 0 and mu_after > max_mu:
            return RiskResult(
                False,
                "TRD-03" if layer_u == "TRADER" else "ORCH-08",
                "BLOCK",
                {"margin_util": mu_after, "max_mu": max_mu},
            )

        if min_fmr > 0 and free_margin_ratio < min_fmr:
            return RiskResult(
                False,
                "TRD-04" if layer_u == "TRADER" else "ORCH-08",
                "BLOCK",
                {"free_margin_ratio": free_margin_ratio, "min_free_margin_ratio": min_fmr},
            )

        is_new_symbol = symbol not in open_symbols
        if max_positions > 0 and is_new_symbol and open_positions >= max_positions:
            return RiskResult(
                False,
                "TRD-05" if layer_u == "TRADER" else "ORCH-08",
                "BLOCK",
                {"open_positions": open_positions, "max_positions": max_positions},
            )

        if equity > 0 and per_pos_pct > 0:
            per_symbol = float(portfolio.get("per_symbol_margin_usd", {}).get(symbol, 0.0)) + margin_usd
            cap = per_pos_pct * equity
            if per_symbol > cap:
                return RiskResult(
                    False,
                    "TRD-06" if layer_u == "TRADER" else "ORCH-08",
                    "BLOCK",
                    {"symbol_margin": per_symbol, "cap": cap},
                )

    # Liq buffer (skip for reduce-only)
    if not is_risk_add:
        return RiskResult(True, "OK", "ALLOW", {})

    # Liq buffer — delegated to shared helper (single source of truth)
    bucket = _symbol_bucket(symbol)
    _is_flip_action = ("CLOSE" in action and "OPEN" in action) or "FLIP" in action
    liq_check = check_liq_buffer(symbol, signal, bucket=bucket)
    if not liq_check["ok"]:
        if _is_flip_action:
            pass
        else:
            fail_code = "HALT-01" if layer_u == "TRADER" else "ORCH-09"
            fail_sev = "HALT" if layer_u == "TRADER" else "BLOCK"
            fail_meta = {"liq_distance_pct": liq_check["liq"], "min_liq": liq_check["min_liq"], "bucket": bucket}
            return RiskResult(False, fail_code, fail_sev, fail_meta)

    # Correlation bucket cap — data-driven using aggregate market regime
    _bucket_margin_add = margin_usd
    if _is_flip_action:
        _closing_sym_margin = float(portfolio.get("per_symbol_margin_usd", {}).get(symbol, 0.0))
        _bucket_margin_add = max(0.0, margin_usd - _closing_sym_margin)
    bucket_margin = float(portfolio.get("bucket_margin", {}).get(bucket, 0.0)) + _bucket_margin_add
    try:
        import os as _os
        _major_cap = float(_os.getenv("CORR_BUCKET_CAP_MAJOR", "0.05"))
        _alt_cap = float(_os.getenv("CORR_BUCKET_CAP_ALT", "0.08"))
        _meme_cap = float(_os.getenv("CORR_BUCKET_CAP_MEME", "0.04"))
    except Exception:
        _major_cap, _alt_cap, _meme_cap = 0.05, 0.08, 0.04
    _base_caps = {"major": _major_cap, "alt": _alt_cap, "meme": _meme_cap}
    _cap_mult = 1.0
    try:
        _rc = _get_redis()
        _regime_raw = _rc.get(f"regime:{symbol}") if _rc else None
        if _regime_raw:
            _rr = _regime_raw.decode() if isinstance(_regime_raw, (bytes, bytearray)) else str(_regime_raw)
            _rd = json.loads(_rr) if isinstance(_rr, str) else {}
            _mr = str(_rd.get("move_regime", "")).upper()
            if _mr in ("FAST", "IMPULSE"):
                _cap_mult = 2.5
            elif _mr in ("TRENDING",):
                _cap_mult = 2.0
            elif _mr in ("NORMAL",):
                _cap_mult = 1.5
    except Exception:
        pass
    cap_pct = float(_base_caps.get(bucket, 0.0)) * _cap_mult
    if equity > 0 and cap_pct > 0:
        cap = cap_pct * equity
        if bucket_margin > cap:
            if _is_flip_action:
                pass
            else:
                return RiskResult(False, "TRD-08" if layer_u == "TRADER" else "ORCH-09", "HALT" if layer_u == "TRADER" else "BLOCK", {"bucket": bucket, "bucket_margin": bucket_margin, "bucket_cap": cap})

    return RiskResult(True, "OK", "ALLOW", {})
