from typing import Any, Dict, List, Optional


def _extract_signal_dq_score(signal: Dict[str, Any]) -> Optional[float]:
    for key in ("dq_score", "data_quality", "dq_confidence"):
        try:
            if key in signal and signal.get(key) is not None:
                return float(signal.get(key))
        except Exception:
            pass
    meta = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
    try:
        if "dq_score" in meta and meta.get("dq_score") is not None:
            return float(meta.get("dq_score"))
    except Exception:
        pass
    scores = signal.get("_scores") if isinstance(signal.get("_scores"), dict) else {}
    try:
        if "data_quality" in scores and scores.get("data_quality") is not None:
            return float(scores.get("data_quality"))
    except Exception:
        pass
    return None


def _extract_signal_volatility_pct(signal: Dict[str, Any]) -> Optional[float]:
    vol = None
    try:
        vol = signal.get("volatility_pct")
    except Exception:
        vol = None
    if vol is None and isinstance(signal.get("metadata"), dict):
        try:
            vol = signal.get("metadata", {}).get("volatility_pct")
        except Exception:
            vol = None
    if vol is None:
        return None
    try:
        vol_f = float(vol)
    except Exception:
        return None
    if vol_f > 1.0:
        vol_f = vol_f / 100.0
    return float(vol_f)


def _extract_signal_drawdown_pct(signal: Dict[str, Any]) -> Optional[float]:
    dd_vals: List[float] = []
    meta = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
    structural = signal.get("structural_metrics") if isinstance(signal.get("structural_metrics"), dict) else {}
    if isinstance(meta, dict) and isinstance(meta.get("structural_metrics"), dict):
        structural = meta.get("structural_metrics")
    for key in ("dd_5d", "dd_10d"):
        try:
            val = structural.get(key)
        except Exception:
            val = None
        if val is None:
            continue
        try:
            dd_f = float(val)
        except Exception:
            continue
        dd_pct = abs(dd_f) * 100.0 if abs(dd_f) <= 1.0 else abs(dd_f)
        dd_vals.append(dd_pct)
    return max(dd_vals) if dd_vals else None


def _compute_dynamic_max_positions(
    base_max: int,
    portfolio: Dict[str, Any],
    signal: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        from config import (
            DYNAMIC_MAX_POSITIONS_ENABLED,
            DYNAMIC_MAX_POSITIONS_BASE,
            DYNAMIC_MAX_POSITIONS_MIN,
            DYNAMIC_MAX_POSITIONS_CAP,
            DYNAMIC_MAX_POSITIONS_DD_SOFT_PCT,
            DYNAMIC_MAX_POSITIONS_DD_HARD_PCT,
            DYNAMIC_MAX_POSITIONS_MU_SOFT,
            DYNAMIC_MAX_POSITIONS_MU_HARD,
            DYNAMIC_MAX_POSITIONS_DQ_MED_SOFT,
            DYNAMIC_MAX_POSITIONS_DQ_MED_STRONG,
            DYNAMIC_MAX_POSITIONS_VOL_PCT,
            DYNAMIC_MAX_POSITIONS_VOL_BONUS,
        )
    except Exception:
        return None

    if not bool(DYNAMIC_MAX_POSITIONS_ENABLED):
        return None

    max_pos = int(DYNAMIC_MAX_POSITIONS_BASE or base_max or 0)
    reasons: List[str] = []
    metrics: Dict[str, Any] = {"base_max": int(max_pos)}

    dd_pct = _extract_signal_drawdown_pct(signal)
    if dd_pct is not None:
        metrics["dd_pct"] = dd_pct
        if dd_pct >= float(DYNAMIC_MAX_POSITIONS_DD_HARD_PCT):
            max_pos = min(max_pos, int(DYNAMIC_MAX_POSITIONS_MIN))
            reasons.append("dd_hard")
        elif dd_pct >= float(DYNAMIC_MAX_POSITIONS_DD_SOFT_PCT):
            max_pos = max(int(DYNAMIC_MAX_POSITIONS_MIN), int(max_pos) - 2)
            reasons.append("dd_soft")

    dq_score = _extract_signal_dq_score(signal)
    if dq_score is not None:
        dq_pct = dq_score * 100.0 if dq_score <= 1.0 else dq_score
        metrics["dq_score"] = dq_score
        metrics["dq_score_pct"] = dq_pct
        if dq_pct >= float(DYNAMIC_MAX_POSITIONS_DQ_MED_STRONG):
            max_pos += 2
            reasons.append("dq_strong")
        elif dq_pct >= float(DYNAMIC_MAX_POSITIONS_DQ_MED_SOFT):
            max_pos += 1
            reasons.append("dq_soft")

    vol_pct = _extract_signal_volatility_pct(signal)
    if vol_pct is not None:
        metrics["volatility_pct"] = vol_pct
        if vol_pct >= float(DYNAMIC_MAX_POSITIONS_VOL_PCT):
            max_pos += int(DYNAMIC_MAX_POSITIONS_VOL_BONUS)
            reasons.append("vol_high")

    try:
        mu = float(portfolio.get("margin_util") or 0.0)
    except Exception:
        mu = 0.0
    metrics["margin_util"] = mu
    if mu <= float(DYNAMIC_MAX_POSITIONS_MU_SOFT):
        max_pos += 1
        reasons.append("mu_soft")
    elif mu >= float(DYNAMIC_MAX_POSITIONS_MU_HARD):
        max_pos -= 1
        reasons.append("mu_hard")

    max_pos = max(int(DYNAMIC_MAX_POSITIONS_MIN), int(max_pos))
    max_pos = min(int(DYNAMIC_MAX_POSITIONS_CAP), int(max_pos))
    metrics["dynamic_max"] = int(max_pos)

    return {"max_positions": int(max_pos), "reasons": reasons, "metrics": metrics}


def _default_phases() -> List[Dict[str, Any]]:
    return [
        {
            "name": "P1",
            "min_equity": 1000.0,
            "max_mu": 0.50,
            "per_pos_margin_pct": 0.05,
            "max_positions": 6,
            "min_free_margin_ratio": 0.0,
        },
        {
            "name": "P1_5",
            "min_equity": 2000.0,
            "max_mu": 0.50,
            "per_pos_margin_pct": 0.05,
            "max_positions": 8,
            "min_free_margin_ratio": 0.0,
        },
        {
            "name": "P2",
            "min_equity": 3000.0,
            "max_mu": 0.50,
            "per_pos_margin_pct": 0.05,
            "max_positions": 10,
            "min_free_margin_ratio": 0.0,
        },
        {
            "name": "P3",
            "min_equity": 5000.0,
            "max_mu": 0.50,
            "per_pos_margin_pct": 0.05,
            "max_positions": 10,
            "min_free_margin_ratio": 0.0,
        },
        {
            "name": "P4",
            "min_equity": 10000.0,
            "max_mu": 0.50,
            "per_pos_margin_pct": 0.05,
            "max_positions": 10,
            "min_free_margin_ratio": 0.0,
        },
    ]


def get_ramp_phase(redis_client) -> Optional[str]:
    if not redis_client:
        return None
    try:
        raw = redis_client.get("wma:ramp_phase")
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        raw = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else raw
        return str(raw).strip()
    except Exception:
        return None


def _phase_from_override(override: Optional[str], phases: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not override:
        return None
    ov = str(override).strip().lower()
    mapping = {
        "2500": "P1",
        "2.5k": "P1",
        "p1": "P1",
        "phase1": "P1",
        "3500": "P1_5",
        "3.5k": "P1_5",
        "p1_5": "P1_5",
        "phase1.5": "P1_5",
        "5000": "P2",
        "5k": "P2",
        "p2": "P2",
        "phase2": "P2",
        "7500": "P3",
        "7.5k": "P3",
        "p3": "P3",
        "phase3": "P3",
        "10000": "P4",
        "10k": "P4",
        "p4": "P4",
        "phase4": "P4",
    }
    name = mapping.get(ov)
    if not name:
        name = ov.upper()
    for p in phases:
        if str(p.get("name") or "").upper() == name.upper():
            return p
    return None


def resolve_phase(equity: float, override: Optional[str] = None) -> Dict[str, Any]:
    try:
        from config import PHASES
    except Exception:
        PHASES = None

    phases = PHASES if isinstance(PHASES, list) and PHASES else _default_phases()

    ov_phase = _phase_from_override(override, phases)
    if ov_phase:
        return ov_phase

    eq = float(equity or 0.0)
    chosen = phases[0]
    for p in phases:
        try:
            if eq >= float(p.get("min_equity") or 0.0):
                chosen = p
        except Exception:
            continue
    return chosen


def get_phase_limits(phase_code: Optional[str]) -> Dict[str, Any]:
    try:
        from config import PHASES
    except Exception:
        PHASES = None

    default_phases = _default_phases()
    phases = PHASES if isinstance(PHASES, list) and PHASES else default_phases
    selected = _phase_from_override(phase_code, phases)
    if selected:
        if phases is not default_phases:
            for base in default_phases:
                if str(base.get("name") or "").upper() == str(selected.get("name") or "").upper():
                    merged = dict(base)
                    merged.update(selected)
                    return merged
        return selected
    if phase_code:
        for p in phases:
            if str(p.get("name") or "").upper() == str(phase_code).upper():
                if phases is not default_phases:
                    for base in default_phases:
                        if str(base.get("name") or "").upper() == str(p.get("name") or "").upper():
                            merged = dict(base)
                            merged.update(p)
                            return merged
                return p
    return default_phases[0] if default_phases else (phases[0] if phases else {})


def check_ramp_limits(
    phase: Dict[str, Any],
    portfolio: Dict[str, Any],
    signal: Dict[str, Any],
) -> Dict[str, Any]:
    """Shared ramp-limit guard for ORCH/TRADER.

    Returns: {"ok": bool, "reason": str, "meta": dict}
    """
    try:
        from risk.assertions import is_risk_add_action
    except Exception:
        def is_risk_add_action(_action: str, _margin_usd: float = 0.0) -> bool:
            return False

    action = str(signal.get("action_name") or signal.get("action") or "").upper()
    margin_usd = float(signal.get("margin_usd") or signal.get("margin") or 0.0)
    action_category = str(signal.get("action_category") or signal.get("category") or "").upper()
    is_risk_add = is_risk_add_action(action, margin_usd)
    if not is_risk_add:
        return {"ok": True, "reason": "OK", "meta": {"note": "not_risk_add"}}

    if action_category and action_category not in {"OPEN_RISK", "OPEN", "ENTRY"}:
        return {"ok": True, "reason": "OK", "meta": {"note": "non_open_category"}}

    equity = float(portfolio.get("equity") or 0.0)
    margin_util = float(portfolio.get("margin_util") or 0.0)
    free_margin_ratio = float(portfolio.get("free_margin_ratio") or 0.0)
    open_positions = int(portfolio.get("open_positions") or 0)
    open_symbols = portfolio.get("open_symbols") or set()
    symbol = str(signal.get("symbol") or "").upper().strip()

    max_mu = float(phase.get("max_mu") or 0.0)
    min_fmr = float(phase.get("min_free_margin_ratio") or 0.0)
    per_pos_pct = float(phase.get("per_pos_margin_pct") or 0.0)
    max_positions = int(phase.get("max_positions") or 0)

    dynamic = _compute_dynamic_max_positions(max_positions, portfolio, signal)
    if dynamic:
        try:
            max_positions = int(dynamic.get("max_positions") or max_positions)
        except Exception:
            max_positions = int(max_positions)

    if equity <= 0 or equity != equity:
        return {
            "ok": False,
            "reason": "RAMP_LIMIT",
            "meta": {"limit": "equity_missing_or_nan", "equity": equity},
        }

    mu_after = margin_util + (margin_usd / equity)
    if max_mu > 0 and mu_after > max_mu:
        return {
            "ok": False,
            "reason": "RAMP_LIMIT",
            "meta": {"limit": "max_mu", "mu_after": mu_after, "max_mu": max_mu},
        }

    if min_fmr > 0 and free_margin_ratio < min_fmr:
        return {
            "ok": False,
            "reason": "RAMP_LIMIT",
            "meta": {"limit": "min_free_margin_ratio", "free_margin_ratio": free_margin_ratio, "min_free_margin_ratio": min_fmr},
        }

    is_new_symbol = symbol not in open_symbols
    if max_positions > 0 and is_new_symbol and open_positions >= max_positions:
        return {
            "ok": False,
            "reason": "RAMP_LIMIT",
            "meta": {
                "limit": "max_positions",
                "open_positions": open_positions,
                "max_positions": max_positions,
                "dynamic_max_positions": dynamic.get("max_positions") if dynamic else None,
                "dynamic_reasons": dynamic.get("reasons") if dynamic else None,
                "dynamic_metrics": dynamic.get("metrics") if dynamic else None,
            },
        }

    if equity > 0 and per_pos_pct > 0 and symbol:
        per_symbol = float(portfolio.get("per_symbol_margin_usd", {}).get(symbol, 0.0)) + margin_usd
        cap = per_pos_pct * equity
        if per_symbol > cap:
            return {
                "ok": False,
                "reason": "RAMP_LIMIT",
                "meta": {"limit": "per_symbol_margin", "symbol_margin": per_symbol, "cap": cap},
            }

    return {
        "ok": True,
        "reason": "OK",
        "meta": {
            "note": "within_limits",
            "dynamic_max_positions": dynamic.get("max_positions") if dynamic else None,
            "dynamic_reasons": dynamic.get("reasons") if dynamic else None,
            "dynamic_metrics": dynamic.get("metrics") if dynamic else None,
        },
    }
