"""
risk/risk_budget_allocator.py — Global Risk Budget Allocator.

Uses global breadth signals + portfolio state to determine a risk allocation
state that adjusts ONLY soft caps:

  - risk_mult          : notional scaling multiplier (0.0 .. 1.6)
  - max_risk_symbols   : temporary soft cap for concurrent open-risk symbols
  - cadence_min_sec    : minimum seconds between new opens
  - hedge_policy       : HEDGE_FIRST | NORMAL

States:
  LOCKDOWN        → reduce-only (stress/margin/drawdown breach)
  DEFENSIVE       → conservative (mixed signals, liq risk)
  BASELINE        → normal ops (aligned, healthy)
  EXPAND          → scale up (strong breadth, low entropy/vol/risk)
  MOMENTUM_SHOCK  → selective (fast move + breadth, may be volatile)

**Hard constraints (liq buffer, margin caps, drawdown breakers, leverage caps,
staleness gates, stress/shock emergency) are NEVER bypassed.**

Feature-flagged via config.RISK_BUDGET_ALLOCATOR_ENABLED (default: False).

Redis output key: ``risk_budget:state:{account_id}`` with TTL.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

try:
    import config
except ImportError:
    config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Allocator states ─────────────────────────────────────────────────
STATE_LOCKDOWN = "LOCKDOWN"
STATE_DEFENSIVE = "DEFENSIVE"
STATE_BASELINE = "BASELINE"
STATE_EXPAND = "EXPAND"
STATE_MOMENTUM_SHOCK = "MOMENTUM_SHOCK"

# ── Default parameters (overridden by config) ────────────────────────
_DEFAULTS = {
    # Input thresholds (truth-table conditions)
    "BREADTH_STRENGTH_MIN": 0.70,
    "BREADTH_ENTROPY_MAX": 0.30,
    "BREADTH_CORR_MAX": 0.75,
    "BREADTH_VOL_MAX": 0.65,
    "FAST_MOVE_SCORE_THRESHOLD": 0.60,
    "LIQ_RISK_MAX": 0.60,
    "MARGIN_UTIL_MAX": 0.55,
    "DRAWDOWN_MAX_PCT": 6.0,
    # Output ranges per state
    "LOCKDOWN_RISK_MULT": 0.0,
    "LOCKDOWN_MAX_SYMS": 0,
    "LOCKDOWN_CADENCE_SEC": 999999,
    "DEFENSIVE_RISK_MULT_LO": 0.65,
    "DEFENSIVE_RISK_MULT_HI": 0.90,
    "DEFENSIVE_MAX_SYMS_LO": 6,
    "DEFENSIVE_MAX_SYMS_HI": 10,
    "DEFENSIVE_CADENCE_SEC_LO": 30,
    "DEFENSIVE_CADENCE_SEC_HI": 90,
    "BASELINE_RISK_MULT": 1.0,
    "BASELINE_MAX_SYMS_LO": 8,
    "BASELINE_MAX_SYMS_HI": 12,
    "BASELINE_CADENCE_SEC_LO": 20,
    "BASELINE_CADENCE_SEC_HI": 60,
    "EXPAND_RISK_MULT_LO": 1.25,
    "EXPAND_RISK_MULT_HI": 1.60,
    "EXPAND_MAX_SYMS_LO": 10,
    "EXPAND_MAX_SYMS_HI": 12,
    "EXPAND_CADENCE_SEC_LO": 10,
    "EXPAND_CADENCE_SEC_HI": 30,
    "MOMENTUM_SHOCK_RISK_MULT_LO": 0.8,
    "MOMENTUM_SHOCK_RISK_MULT_HI": 1.2,
    "MOMENTUM_SHOCK_MAX_SYMS_LO": 6,
    "MOMENTUM_SHOCK_MAX_SYMS_HI": 12,
    "MOMENTUM_SHOCK_CADENCE_SEC_LO": 60,
    "MOMENTUM_SHOCK_CADENCE_SEC_HI": 120,
    "MOMENTUM_HEDGE_FIRST_BREADTH_VOL_MIN": 0.50,
}


def _cfg(key: str, default=None):
    """Read from config with safe fallback."""
    if config is not None:
        full_key = f"RBA_{key}"
        val = getattr(config, full_key, None)
        if val is not None:
            return val
    if default is not None:
        return default
    return _DEFAULTS.get(key, 0.0)


def _interp(lo: float, hi: float, factor: float) -> float:
    """Linear interpolation: factor 0→lo, factor 1→hi."""
    factor = max(0.0, min(1.0, float(factor)))
    return lo + (hi - lo) * factor


class RiskBudgetAllocation:
    """Immutable result of the risk budget allocator."""

    __slots__ = (
        "state", "risk_mult", "max_risk_symbols", "cadence_min_sec",
        "hedge_policy", "reason", "breadth_snapshot", "updated_ts_ms",
    )

    def __init__(
        self,
        state: str,
        risk_mult: float,
        max_risk_symbols: int,
        cadence_min_sec: int,
        hedge_policy: str,
        reason: str = "",
        breadth_snapshot: Optional[Dict[str, Any]] = None,
        updated_ts_ms: int = 0,
    ):
        self.state = state
        self.risk_mult = risk_mult
        self.max_risk_symbols = max_risk_symbols
        self.cadence_min_sec = cadence_min_sec
        self.hedge_policy = hedge_policy
        self.reason = reason
        self.breadth_snapshot = breadth_snapshot or {}
        self.updated_ts_ms = updated_ts_ms or int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "risk_mult": round(self.risk_mult, 4),
            "max_risk_symbols": int(self.max_risk_symbols),
            "cadence_min_sec": int(self.cadence_min_sec),
            "hedge_policy": self.hedge_policy,
            "reason": self.reason,
            "breadth_snapshot": self.breadth_snapshot,
            "updated_ts_ms": int(self.updated_ts_ms),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RiskBudgetAllocation":
        return cls(
            state=str(d.get("state") or STATE_BASELINE),
            risk_mult=float(d.get("risk_mult") or 1.0),
            max_risk_symbols=int(d.get("max_risk_symbols") or 5),
            cadence_min_sec=int(d.get("cadence_min_sec") or 60),
            hedge_policy=str(d.get("hedge_policy") or "NORMAL"),
            reason=str(d.get("reason") or ""),
            breadth_snapshot=d.get("breadth_snapshot"),
            updated_ts_ms=int(d.get("updated_ts_ms") or 0),
        )

    def __repr__(self) -> str:
        return (
            f"RiskBudgetAllocation(state={self.state}, risk_mult={self.risk_mult:.2f}, "
            f"max_syms={self.max_risk_symbols}, cadence={self.cadence_min_sec}s, "
            f"hedge={self.hedge_policy})"
        )


def compute_risk_budget(
    breadth: Dict[str, Any],
    *,
    portfolio_stress: bool = False,
    margin_util_pct: float = 0.0,
    drawdown_pct: float = 0.0,
    move_regime: str = "NORMAL",
    fast_move_score: float = 0.0,
    liq_risk_global: float = 0.0,
    liq_imbalance_extreme: bool = False,
) -> RiskBudgetAllocation:
    """Determine risk budget allocation from global breadth + portfolio state.

    Parameters
    ----------
    breadth : dict
        Output of ``risk.global_breadth.compute_global_breadth()``.
    portfolio_stress : bool
        True if portfolio stress state is active.
    margin_util_pct : float
        Current margin utilization 0..100 (percent).
    drawdown_pct : float
        Current portfolio drawdown (positive = loss, e.g. 5 = 5% DD).
    move_regime : str
        Global move regime (CALM/NORMAL/FAST/IMPULSE).
    fast_move_score : float
        Global fast move score (max across symbols).
    liq_risk_global : float
        Average liq_risk across symbols (0..1).
    liq_imbalance_extreme : bool
        True if liq_imbalance flipped AND strengthened (extreme imbalance).

    Returns
    -------
    RiskBudgetAllocation
    """
    now_ms = int(time.time() * 1000)

    # Extract breadth fields (safe defaults)
    b_strength = float(breadth.get("breadth_strength") or 0.0)
    b_entropy = float(breadth.get("breadth_entropy") or 1.0)
    b_corr = float(breadth.get("breadth_corr") or 0.0)
    b_vol = float(breadth.get("breadth_vol") or 0.0)
    b_fast = float(breadth.get("breadth_fast_move") or fast_move_score)

    # ── Derive boolean conditions (truth-table inputs) ────────────────
    # S = safe (no stress)
    S = not portfolio_stress
    # M = margin OK
    M = margin_util_pct <= float(_cfg("MARGIN_UTIL_MAX", 75.0))
    # D = drawdown OK
    D = drawdown_pct <= float(_cfg("DRAWDOWN_MAX_PCT", 20.0))
    # B = breadth strong
    B = b_strength >= float(_cfg("BREADTH_STRENGTH_MIN", 0.70))
    # E = low entropy (consensus)
    E = b_entropy <= float(_cfg("BREADTH_ENTROPY_MAX", 0.30))
    # C = correlation not fragile
    C = b_corr <= float(_cfg("BREADTH_CORR_MAX", 0.75))
    # V = vol manageable
    V = b_vol <= float(_cfg("BREADTH_VOL_MAX", 0.65))
    # F = fast/impulse move
    F = (
        move_regime in ("FAST", "IMPULSE")
        or b_fast >= float(_cfg("FAST_MOVE_SCORE_THRESHOLD", 0.60))
    )
    # L = liq risk manageable
    L = (
        liq_risk_global <= float(_cfg("LIQ_RISK_MAX", 0.60))
        and not liq_imbalance_extreme
    )

    # ── State determination (truth-table) ─────────────────────────────

    # LOCKDOWN: stress OR margin breach OR drawdown breach
    if not S or not M or not D:
        reasons = []
        if not S:
            reasons.append("PORTFOLIO_STRESS")
        if not M:
            reasons.append(f"MARGIN_UTIL={margin_util_pct:.1f}%")
        if not D:
            reasons.append(f"DRAWDOWN={drawdown_pct:.1f}%")
        return RiskBudgetAllocation(
            state=STATE_LOCKDOWN,
            risk_mult=float(_cfg("LOCKDOWN_RISK_MULT", 0.0)),
            max_risk_symbols=int(_cfg("LOCKDOWN_MAX_SYMS", 0)),
            cadence_min_sec=int(_cfg("LOCKDOWN_CADENCE_SEC", 999999)),
            hedge_policy="HEDGE_FIRST",
            reason="|".join(reasons),
            breadth_snapshot=breadth,
            updated_ts_ms=now_ms,
        )

    # MOMENTUM_SHOCK: F AND B AND L AND S AND M (vol may be high)
    if F and B and L:
        # Scale by breadth_strength (how strong the consensus)
        quality = b_strength  # 0.70..1.0 → factor 0..1
        quality_factor = max(0.0, min(1.0, (quality - 0.70) / 0.30))
        risk_mult = _interp(
            float(_cfg("MOMENTUM_SHOCK_RISK_MULT_LO", 0.8)),
            float(_cfg("MOMENTUM_SHOCK_RISK_MULT_HI", 1.2)),
            quality_factor,
        )
        max_syms = int(_interp(
            float(_cfg("MOMENTUM_SHOCK_MAX_SYMS_LO", 6)),
            float(_cfg("MOMENTUM_SHOCK_MAX_SYMS_HI", 12)),
            quality_factor,
        ))
        cadence = int(_interp(
            float(_cfg("MOMENTUM_SHOCK_CADENCE_SEC_HI", 120)),
            float(_cfg("MOMENTUM_SHOCK_CADENCE_SEC_LO", 60)),
            quality_factor,
        ))
        # Hedge-first on alts during momentum (majors can be NORMAL); threshold is tunable via RBA_*.
        _vol_hf_thr = float(_cfg("MOMENTUM_HEDGE_FIRST_BREADTH_VOL_MIN", 0.50))
        hp = "HEDGE_FIRST" if b_vol > _vol_hf_thr else "NORMAL"
        return RiskBudgetAllocation(
            state=STATE_MOMENTUM_SHOCK,
            risk_mult=risk_mult,
            max_risk_symbols=max_syms,
            cadence_min_sec=cadence,
            hedge_policy=hp,
            reason=f"FAST_MOVE|breadth_strength={b_strength:.2f}|vol={b_vol:.2f}",
            breadth_snapshot=breadth,
            updated_ts_ms=now_ms,
        )

    # EXPAND: B AND E AND V AND L AND S AND M AND D (all green)
    if B and E and V and L:
        # Scale by combined quality: breadth_strength × (1 - entropy) × (1 - vol)
        quality = b_strength * (1.0 - b_entropy) * (1.0 - b_vol)
        quality_factor = max(0.0, min(1.0, quality / 0.30))  # 0.30 = decent threshold
        risk_mult = _interp(
            float(_cfg("EXPAND_RISK_MULT_LO", 1.25)),
            float(_cfg("EXPAND_RISK_MULT_HI", 1.60)),
            quality_factor,
        )
        max_syms = int(_interp(
            float(_cfg("EXPAND_MAX_SYMS_LO", 10)),
            float(_cfg("EXPAND_MAX_SYMS_HI", 12)),
            quality_factor,
        ))
        cadence = int(_interp(
            float(_cfg("EXPAND_CADENCE_SEC_HI", 45)),
            float(_cfg("EXPAND_CADENCE_SEC_LO", 20)),
            quality_factor,
        ))
        return RiskBudgetAllocation(
            state=STATE_EXPAND,
            risk_mult=risk_mult,
            max_risk_symbols=max_syms,
            cadence_min_sec=cadence,
            hedge_policy="NORMAL",
            reason=f"ALL_GREEN|quality={quality:.3f}|breadth={b_strength:.2f}",
            breadth_snapshot=breadth,
            updated_ts_ms=now_ms,
        )

    # BASELINE: S AND M AND D AND B AND L (entropy/corr/vol neutral)
    if B and L:
        return RiskBudgetAllocation(
            state=STATE_BASELINE,
            risk_mult=float(_cfg("BASELINE_RISK_MULT", 1.0)),
            max_risk_symbols=int(_interp(
                float(_cfg("BASELINE_MAX_SYMS_LO", 8)),
                float(_cfg("BASELINE_MAX_SYMS_HI", 12)),
                b_strength,
            )),
            cadence_min_sec=int(_interp(
                float(_cfg("BASELINE_CADENCE_SEC_HI", 90)),
                float(_cfg("BASELINE_CADENCE_SEC_LO", 45)),
                b_strength,
            )),
            hedge_policy="NORMAL",
            reason=f"BASELINE|breadth={b_strength:.2f}|entropy={b_entropy:.2f}",
            breadth_snapshot=breadth,
            updated_ts_ms=now_ms,
        )

    # DEFENSIVE: fallback (NOT B OR NOT E OR NOT L)
    # Scale by how bad things are
    penalty = 0.0
    reasons = []
    if not B:
        penalty += 0.3
        reasons.append(f"LOW_BREADTH={b_strength:.2f}")
    if not L:
        penalty += 0.4
        reasons.append(f"HIGH_LIQ_RISK={liq_risk_global:.2f}")
    if b_entropy > 0.60:
        penalty += 0.2
        reasons.append(f"HIGH_ENTROPY={b_entropy:.2f}")
    penalty = min(1.0, penalty)

    risk_mult = _interp(
        float(_cfg("DEFENSIVE_RISK_MULT_LO", 0.5)),
        float(_cfg("DEFENSIVE_RISK_MULT_HI", 0.8)),
        1.0 - penalty,
    )
    max_syms = int(_interp(
        float(_cfg("DEFENSIVE_MAX_SYMS_LO", 6)),
        float(_cfg("DEFENSIVE_MAX_SYMS_HI", 10)),
        1.0 - penalty,
    ))
    cadence = int(_interp(
        float(_cfg("DEFENSIVE_CADENCE_SEC_HI")),
        float(_cfg("DEFENSIVE_CADENCE_SEC_LO")),
        1.0 - penalty,
    ))
    hp = "HEDGE_FIRST" if F else "NORMAL"

    return RiskBudgetAllocation(
        state=STATE_DEFENSIVE,
        risk_mult=risk_mult,
        max_risk_symbols=max_syms,
        cadence_min_sec=cadence,
        hedge_policy=hp,
        reason="|".join(reasons) if reasons else "DEFENSIVE_DEFAULT",
        breadth_snapshot=breadth,
        updated_ts_ms=now_ms,
    )


def _apply_safety_knobs(alloc: RiskBudgetAllocation) -> RiskBudgetAllocation:
    """Clamp allocator output by safety knobs from config (blast-radius caps)."""
    try:
        max_mult = float(getattr(config, "RISK_BUDGET_MAX_MULT", 1.25))
        max_syms = int(getattr(config, "RISK_BUDGET_MAX_OPEN_SYMBOLS", 6))
        min_cadence = int(getattr(config, "RISK_BUDGET_MIN_CADENCE_SEC", 45))
        alloc.risk_mult = min(alloc.risk_mult, max_mult)
        if alloc.state != STATE_LOCKDOWN:  # LOCKDOWN stays at 0
            alloc.max_risk_symbols = min(alloc.max_risk_symbols, max_syms)
            alloc.cadence_min_sec = max(alloc.cadence_min_sec, min_cadence)
    except Exception:
        pass
    return alloc


def apply_reversal_override(
    alloc: RiskBudgetAllocation,
    reversal_active: bool = False,
) -> RiskBudgetAllocation:
    """If reversal detector is active, force DEFENSIVE-level caps."""
    if not reversal_active:
        return alloc
    try:
        rev_mult = float(getattr(config, "REVERSAL_DEFENSIVE_MULT", 0.70))
        lockdown_on_shock = bool(getattr(config, "REVERSAL_LOCKDOWN_ON_SHOCK", True))
        # If currently EXPAND / MOMENTUM_SHOCK and reversal fires → LOCKDOWN or DEFENSIVE
        if alloc.state == STATE_MOMENTUM_SHOCK and lockdown_on_shock:
            alloc.state = STATE_LOCKDOWN
            alloc.risk_mult = 0.0
            alloc.max_risk_symbols = 0
            alloc.cadence_min_sec = 999999
            alloc.hedge_policy = "HEDGE_FIRST"
            alloc.reason = f"REVERSAL_LOCKDOWN|{alloc.reason}"
        elif alloc.state in (STATE_EXPAND, STATE_BASELINE, STATE_MOMENTUM_SHOCK):
            alloc.state = STATE_DEFENSIVE
            alloc.risk_mult = min(alloc.risk_mult, rev_mult)
            alloc.cadence_min_sec = max(alloc.cadence_min_sec, 120)
            alloc.hedge_policy = "HEDGE_FIRST"
            alloc.reason = f"REVERSAL_OVERRIDE|{alloc.reason}"
    except Exception:
        pass
    return alloc


# ── Redis convenience ────────────────────────────────────────────────

def cache_allocation(
    redis_client,
    account_id: str,
    allocation: RiskBudgetAllocation,
    ttl_sec: int = 300,
) -> bool:
    """Write allocation to Redis for consumption by orchestrator/trader."""
    if not redis_client:
        return False
    try:
        key = f"risk_budget:state:{account_id}"
        redis_client.setex(
            key,
            max(10, ttl_sec),
            json.dumps(allocation.to_dict(), separators=(",", ":")),
        )
        return True
    except Exception as e:
        logger.debug("[RBA_CACHE_ERROR] %s: %s", account_id, e)
        return False


def read_cached_allocation(
    redis_client,
    account_id: str,
) -> Optional[RiskBudgetAllocation]:
    """Read cached allocation from Redis. Returns None if missing/stale."""
    if not redis_client:
        return None
    try:
        raw = redis_client.get(f"risk_budget:state:{account_id}")
        if not raw:
            return None
        val = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        data = json.loads(val)
        if not isinstance(data, dict):
            return None
        alloc = RiskBudgetAllocation.from_dict(data)
        # Staleness check
        stale_ms = 600_000  # 10 minutes (prediction cycles can be 2-3min apart)
        try:
            stale_ms = int(float(getattr(config, "RBA_STALE_SEC", 120)) * 1000)
        except Exception:
            pass
        if alloc.updated_ts_ms > 0 and (int(time.time() * 1000) - alloc.updated_ts_ms) > stale_ms:
            return None
        return alloc
    except Exception:
        return None


# ── Soft-cap application helper (for orchestrator/trainer) ───────────

def maybe_symbol_hedge_normal_override(
    redis_client,
    symbol: str,
    alloc: RiskBudgetAllocation,
    winner: Optional[Dict[str, Any]] = None,
) -> RiskBudgetAllocation:
    """Selective NORMAL hedge_policy under MOMENTUM_SHOCK when symbol conflicts with breadth.

    Does not apply to LOCKDOWN or other states. Never weakens hard risk limits.
    """
    try:
        enabled = bool(getattr(config, "RBA_SYMBOL_NORMAL_WHEN_CONFLICT_ENABLED", False))
    except Exception:
        enabled = False
    if not enabled or redis_client is None or alloc is None:
        return alloc
    if alloc.state != STATE_MOMENTUM_SHOCK:
        return alloc
    if str(alloc.hedge_policy).upper() != "HEDGE_FIRST":
        return alloc

    sym_u = str(symbol or "").upper().strip()
    if not sym_u:
        return alloc

    min_cf = float(getattr(config, "RBA_SYMBOL_NORMAL_TF_CONFLICT_MIN", 0.58))
    cf = 0.0
    if winner:
        try:
            cf = float(
                winner.get("tf_conflict_score")
                or winner.get("conflict_score")
                or 0.0
            )
        except Exception:
            cf = 0.0

    if cf < min_cf:
        try:
            from trading.redesign_v2_helpers import _decode_map as _uf_dm

            raw = redis_client.hgetall(f"unified_features:{sym_u}:5m") or {}
            ufd = _uf_dm(raw)
            for key in ("tf_conflict_score", "conflict_score"):
                if key in ufd:
                    try:
                        cf = max(cf, float(ufd.get(key) or 0.0))
                    except Exception:
                        pass
        except Exception:
            pass

    breadth_dir = 0
    try:
        from risk.global_breadth import read_cached_breadth

        br = read_cached_breadth(redis_client, "5m") or {}
        breadth_dir = int(br.get("breadth_dir") or 0)
    except Exception:
        breadth_dir = 0

    pred_dir = ""
    try:
        from trading.redesign_v2_helpers import _decode_map as _pred_dm

        pr = redis_client.hgetall(f"prediction:{sym_u}:multi") or {}
        pd = _pred_dm(pr)
        pred_dir = str(pd.get("direction") or "").upper()
    except Exception:
        pred_dir = ""

    disagree = False
    try:
        if getattr(config, "RBA_SYMBOL_NORMAL_WHEN_BREADTH_DISAGREE_ENABLED", True):
            disagree = (pred_dir == "LONG" and breadth_dir < 0) or (
                pred_dir == "SHORT" and breadth_dir > 0
            )
    except Exception:
        disagree = (pred_dir == "LONG" and breadth_dir < 0) or (
            pred_dir == "SHORT" and breadth_dir > 0
        )

    if cf < min_cf and not disagree:
        return alloc

    return RiskBudgetAllocation(
        state=alloc.state,
        risk_mult=alloc.risk_mult,
        max_risk_symbols=alloc.max_risk_symbols,
        cadence_min_sec=alloc.cadence_min_sec,
        hedge_policy="NORMAL",
        reason=str(alloc.reason or "") + "|SYM_HEDGE_NORMAL_OVR",
        breadth_snapshot=dict(alloc.breadth_snapshot or {}),
        updated_ts_ms=int(alloc.updated_ts_ms or 0),
    )


def apply_risk_budget_to_sizing(
    margin_usd: float,
    allocation: Optional[RiskBudgetAllocation],
    *,
    is_major: bool = False,
) -> float:
    """Apply risk_mult to proposed margin. Returns adjusted margin_usd.

    NEVER increases margin beyond 1.6× original. Returns 0.0 for LOCKDOWN.
    """
    if allocation is None:
        return margin_usd  # Feature disabled → passthrough

    mult = float(allocation.risk_mult)

    # Hard safety clamp: never more than config cap (default 1.25)
    _max_mult = 1.6
    try:
        _max_mult = float(getattr(config, "RISK_BUDGET_MAX_MULT", 1.25))
    except Exception:
        pass
    mult = max(0.0, min(_max_mult, mult))

    # LOCKDOWN → 0.0 (reduce-only)
    if allocation.state == STATE_LOCKDOWN:
        return 0.0

    # For MOMENTUM_SHOCK, majors get full mult, alts get 0.8× mult
    if allocation.state == STATE_MOMENTUM_SHOCK and not is_major:
        mult = min(mult, 0.8)

    return max(0.0, margin_usd * mult)
