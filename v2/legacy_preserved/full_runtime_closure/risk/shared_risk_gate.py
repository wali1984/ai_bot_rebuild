"""
risk/shared_risk_gate.py — Shared Risk Gate for all execution paths.

This module provides a single ``check_risk_gate()`` function that MUST be
called before any risk-adding execution, regardless of source:

  - Orchestrator proposals (already covered via _prepublish_feasibility_gate)
  - Trader-side adaptive hedges (_evaluate_adaptive_hedges)
  - URC recovery signals (routed through orchestrator — OK)
  - Any future internal execution paths

The gate reads the same Redis keys used by the orchestrator:
  - ``risk_budget:state:{account_id}``  — RBA cadence + max symbols
  - ``reversal:global``                 — reversal blocking
  - ``toxicity:{symbol}``              — microstructure toxicity
  - ``market:state:contract``          — data health + expand gate

Feature-flagged via config.SHARED_RISK_GATE_ENABLED (default: True).

Returns a RiskGateResult with pass/block decision and reason.
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


def _cfg(key: str, default):
    """Read config value with fallback."""
    if config is not None:
        val = getattr(config, key, None)
        if val is not None:
            return val
    return default


class RiskGateResult:
    """Result of a shared risk gate check."""
    __slots__ = ("passed", "block_code", "block_reason", "meta")

    def __init__(self, passed: bool = True, block_code: str = "",
                 block_reason: str = "", meta: Optional[Dict] = None):
        self.passed = passed
        self.block_code = block_code
        self.block_reason = block_reason
        self.meta = meta or {}


def check_risk_gate(
    redis_client,
    account_id: str,
    symbol: str,
    action: str,
    is_risk_add: bool = True,
    is_reduce: bool = False,
    hedge_intent: bool = False,
    source: str = "",
    last_open_ts: Optional[float] = None,
    margin_ratio_pct: Optional[float] = None,
    margin_used_pct: Optional[float] = None,
) -> RiskGateResult:
    """
    Shared risk gate — must pass before any risk-adding execution.

    Checks performed (in order):
      0. Emergency margin gate: block ALL risk-adds when account margin stressed
      1. Reversal gate: block risk-adds when global reversal active
      2. RBA cadence gate: enforce minimum time between opens
      3. RBA max-symbols gate: cap number of risk-bearing symbols
      4. Toxicity gate: block/reduce when microstructure is toxic
      5. Gross exposure check: block conflicting adds that increase gross

    Reduces and pure-close actions always pass (risk-reducing).

    Parameters
    ----------
    redis_client : Redis connection
    account_id : str — "primary" or "asjad"
    symbol : str — e.g. "BTCUSDT"
    action : str — action name
    is_risk_add : bool — True if this adds risk (open/increase)
    is_reduce : bool — True if this reduces risk (close/partial)
    hedge_intent : bool — True if this is a hedge action
    source : str — origin module name
    last_open_ts : float — timestamp of last open for this account (for cadence)
    margin_ratio_pct : float — Binance margin ratio % (maint_margin / margin_balance * 100)
    margin_used_pct : float — margin utilization % (initial_margin / margin_balance * 100)

    Returns
    -------
    RiskGateResult with .passed bool and .block_code if blocked
    """
    enabled = bool(_cfg("SHARED_RISK_GATE_ENABLED", True))
    if not enabled:
        return RiskGateResult(passed=True)

    # Reduces always pass (risk-reducing)
    if is_reduce and not is_risk_add:
        return RiskGateResult(passed=True)

    if not redis_client:
        return RiskGateResult(passed=True)

    action_upper = str(action or "").upper()

    # ── 0. Emergency account-level margin gate ────────────────────────
    # Blocks ALL risk-adds when the account is under margin stress.
    # Reads from caller-provided values first, then falls back to Redis.
    # Protective hedges (hedge_intent=True) get elevated thresholds because
    # they REDUCE net exposure even though they add gross margin.
    try:
        emg_enabled = bool(_cfg("EMERGENCY_MARGIN_GATE_ENABLED", True))
        if emg_enabled and is_risk_add:
            mr_pct = margin_ratio_pct
            mu_pct = margin_used_pct

            # Fallback: read from Redis snapshot written by the trader
            if (mr_pct is None or mu_pct is None) and redis_client:
                try:
                    snap_raw = redis_client.get(f"wma:account_margin:{account_id}")
                    if snap_raw:
                        snap_str = snap_raw.decode("utf-8") if isinstance(snap_raw, (bytes, bytearray)) else str(snap_raw)
                        snap = json.loads(snap_str)
                        if mr_pct is None:
                            mr_pct = float(snap.get("margin_ratio_pct", 0) or 0)
                        if mu_pct is None:
                            mu_pct = float(snap.get("margin_used_pct", 0) or 0)
                except Exception:
                    pass

            # Protective hedges get elevated caps — they reduce net exposure
            if hedge_intent:
                min_mr = float(_cfg("EMERGENCY_MARGIN_RATIO_MIN_PCT_PROTECTIVE", 50.0))
                max_mu = float(_cfg("EMERGENCY_MARGIN_USED_MAX_PCT_PROTECTIVE", 85.0))
            else:
                min_mr = float(_cfg("EMERGENCY_MARGIN_RATIO_MIN_PCT", 20.0))
                max_mu = float(_cfg("EMERGENCY_MARGIN_USED_MAX_PCT", 75.0))

            # Only gate when we have valid data (mr > 0 means Binance has positions)
            mr_breach = (mr_pct is not None and mr_pct > 0 and mr_pct >= min_mr)
            mu_breach = (mu_pct is not None and mu_pct > max_mu)

            if mr_breach or mu_breach:
                breach_reasons = []
                if mr_breach:
                    breach_reasons.append(f"margin_ratio={mr_pct:.1f}% >= {min_mr:.0f}%")
                if mu_breach:
                    breach_reasons.append(f"margin_used={mu_pct:.1f}% > {max_mu:.0f}%")
                reason_str = " AND ".join(breach_reasons)

                effective_label = "PROTECTIVE" if hedge_intent else "STANDARD"
                logger.warning(
                    "SHARED_RISK_GATE_BLOCK | account=%s | symbol=%s | action=%s | "
                    "code=EMERGENCY_MARGIN_BLOCK | %s | caps=%s | source=%s",
                    account_id, symbol, action_upper, reason_str, effective_label, source,
                )
                return RiskGateResult(
                    passed=False,
                    block_code="EMERGENCY_MARGIN_BLOCK",
                    block_reason=f"Emergency margin gate ({effective_label}): {reason_str}",
                    meta={
                        "margin_ratio_pct": mr_pct,
                        "margin_used_pct": mu_pct,
                        "threshold_min_mr": min_mr,
                        "threshold_max_mu": max_mu,
                        "hedge_intent": hedge_intent,
                        "caps_mode": effective_label,
                    },
                )
    except Exception as e:
        logger.debug("EMERGENCY_MARGIN_GATE_ERR | account=%s | err=%s", account_id, e)

    # ── 1. Reversal gate ────────────────────────────────────────────
    try:
        rev_raw = redis_client.get("reversal:global")
        if rev_raw:
            rev_str = rev_raw.decode("utf-8") if isinstance(rev_raw, (bytes, bytearray)) else str(rev_raw)
            rev_data = json.loads(rev_str)
            if rev_data.get("active") is True:
                # Allow reduces AND protective hedges, block other risk-adds
                if is_risk_add and not hedge_intent:
                    logger.warning(
                        "SHARED_RISK_GATE_BLOCK | account=%s | symbol=%s | action=%s | "
                        "code=REVERSAL_BLOCK | source=%s",
                        account_id, symbol, action_upper, source,
                    )
                    return RiskGateResult(
                        passed=False,
                        block_code="SHARED_REVERSAL_BLOCK",
                        block_reason=f"Global reversal active, risk-adds blocked",
                        meta={"reversal_triggers": rev_data.get("trigger_count", 0)},
                    )
                elif is_risk_add and hedge_intent:
                    logger.info(
                        "SHARED_RISK_GATE_HEDGE_BYPASS | account=%s | symbol=%s | action=%s | "
                        "reason=REVERSAL_HEDGE_EXEMPT | source=%s",
                        account_id, symbol, action_upper, source,
                    )
    except Exception:
        pass

    # ── 2. RBA cadence gate ──────────────────────────────────────────
    try:
        rba_raw = redis_client.get(f"risk_budget:state:{account_id}")
        if rba_raw and is_risk_add:
            rba_str = rba_raw.decode("utf-8") if isinstance(rba_raw, (bytes, bytearray)) else str(rba_raw)
            rba_data = json.loads(rba_str)
            cadence_sec = float(rba_data.get("cadence_min_sec", 0) or 0)

            if cadence_sec > 0 and last_open_ts is not None:
                elapsed = time.time() - last_open_ts
                if elapsed < cadence_sec:
                    logger.warning(
                        "SHARED_RISK_GATE_BLOCK | account=%s | symbol=%s | action=%s | "
                        "code=CADENCE_BLOCK | elapsed=%.1fs < %.0fs | source=%s",
                        account_id, symbol, action_upper, elapsed, cadence_sec, source,
                    )
                    return RiskGateResult(
                        passed=False,
                        block_code="SHARED_CADENCE_BLOCK",
                        block_reason=f"Cadence: {elapsed:.1f}s < {cadence_sec:.0f}s minimum",
                        meta={"elapsed": elapsed, "cadence_sec": cadence_sec,
                              "rba_state": rba_data.get("state", "UNKNOWN")},
                    )

            # ── 3. Max risk symbols gate ─────────────────────────────
            max_syms = int(rba_data.get("max_risk_symbols", 999) or 999)
            if max_syms < 999:
                try:
                    pos_raw = redis_client.hgetall(f"positions:{account_id}")
                    if pos_raw:
                        open_symbols = set()
                        for pk, pv in pos_raw.items():
                            try:
                                pk_s = pk.decode() if isinstance(pk, bytes) else str(pk)
                                pv_s = pv.decode() if isinstance(pv, bytes) else str(pv)
                                pd = json.loads(pv_s)
                                if isinstance(pd, dict):
                                    sz = float(pd.get("size") or pd.get("positionAmt") or 0)
                                    sym = pd.get("symbol") or pk_s.split(":")[0] if ":" in pk_s else pk_s.split("_")[0]
                                    if sz != 0:
                                        open_symbols.add(str(sym).upper())
                            except Exception:
                                pass

                        if symbol.upper() not in open_symbols and len(open_symbols) >= max_syms:
                            logger.warning(
                                "SHARED_RISK_GATE_BLOCK | account=%s | symbol=%s | action=%s | "
                                "code=MAX_SYMBOLS_BLOCK | open=%d >= max=%d | source=%s",
                                account_id, symbol, action_upper, len(open_symbols), max_syms, source,
                            )
                            return RiskGateResult(
                                passed=False,
                                block_code="SHARED_MAX_SYMBOLS_BLOCK",
                                block_reason=f"Open symbols {len(open_symbols)} >= max {max_syms}",
                                meta={"open_symbols": len(open_symbols), "max_symbols": max_syms,
                                      "rba_state": rba_data.get("state", "UNKNOWN")},
                            )
                except Exception:
                    pass
    except Exception:
        pass

    # ── 4. Toxicity gate ──────────────────────────────────────────────
    try:
        tox_raw = redis_client.get(f"toxicity:{symbol}")
        if tox_raw and is_risk_add:
            tox_str = tox_raw.decode("utf-8") if isinstance(tox_raw, (bytes, bytearray)) else str(tox_raw)
            tox_data = json.loads(tox_str)
            tox_score = float(tox_data.get("score", 0) or 0)
            extreme_threshold = float(_cfg("TOXICITY_EXTREME_THRESHOLD", 0.85))

            if tox_score >= extreme_threshold:
                logger.warning(
                    "SHARED_RISK_GATE_BLOCK | account=%s | symbol=%s | action=%s | "
                    "code=TOXICITY_EXTREME_BLOCK | score=%.3f >= %.3f | source=%s",
                    account_id, symbol, action_upper, tox_score, extreme_threshold, source,
                )
                return RiskGateResult(
                    passed=False,
                    block_code="SHARED_TOXICITY_EXTREME_BLOCK",
                    block_reason=f"Toxicity extreme: {tox_score:.3f} >= {extreme_threshold:.3f}",
                    meta={"toxicity_score": tox_score, "hint": tox_data.get("execution_hint", "UNKNOWN")},
                )
    except Exception:
        pass

    return RiskGateResult(passed=True)


def check_conflicting_add(
    redis_client,
    account_id: str,
    symbol: str,
    target_side: str,
    action: str,
    hedge_intent: bool = False,
    source: str = "",
) -> RiskGateResult:
    """
    Block adds that increase gross exposure on both sides simultaneously.

    If account holds LONG and signal is INCREASE_LONG (non-hedge), that's OK.
    If account holds SHORT and signal is INCREASE_LONG (non-hedge), BLOCK
    unless it's explicitly a hedge or flip action.

    This prevents accidental both-sides stacking that inflates gross exposure.
    """
    enabled = bool(_cfg("CONFLICTING_ADD_GATE_ENABLED", True))
    if not enabled:
        return RiskGateResult(passed=True)

    if not redis_client:
        return RiskGateResult(passed=True)

    # Hedges are explicitly dual-side — allowed
    if hedge_intent:
        return RiskGateResult(passed=True)

    # Flip actions are explicitly dual-side — allowed
    action_upper = str(action or "").upper()
    if "CLOSE_AND" in action_upper or "FLIP" in action_upper:
        return RiskGateResult(passed=True)

    target_upper = str(target_side or "").upper()
    if target_upper not in ("LONG", "SHORT"):
        return RiskGateResult(passed=True)

    opposite = "SHORT" if target_upper == "LONG" else "LONG"

    try:
        pos_raw = redis_client.hgetall(f"positions:{account_id}")
        if not pos_raw:
            return RiskGateResult(passed=True)

        has_opposite = False
        for pk, pv in pos_raw.items():
            try:
                pv_s = pv.decode() if isinstance(pv, bytes) else str(pv)
                pd = json.loads(pv_s)
                if not isinstance(pd, dict):
                    continue
                sym = str(pd.get("symbol") or "").upper()
                side = str(pd.get("side") or "").upper()
                sz = float(pd.get("size") or pd.get("positionAmt") or 0)
                if sym == symbol.upper() and side == opposite and sz != 0:
                    has_opposite = True
                    break
            except Exception:
                continue

        if has_opposite:
            # RBA state check: if DEFENSIVE or reversal active, block conflicting adds
            rba_state = "UNKNOWN"
            reversal_active = False
            try:
                rba_raw = redis_client.get(f"risk_budget:state:{account_id}")
                if rba_raw:
                    rba_s = rba_raw.decode() if isinstance(rba_raw, bytes) else str(rba_raw)
                    rba_d = json.loads(rba_s)
                    rba_state = str(rba_d.get("state", "UNKNOWN"))
            except Exception:
                pass
            try:
                rev_raw = redis_client.get("reversal:global")
                if rev_raw:
                    rev_s = rev_raw.decode() if isinstance(rev_raw, bytes) else str(rev_raw)
                    rev_d = json.loads(rev_s)
                    reversal_active = rev_d.get("active", False)
            except Exception:
                pass

            if rba_state in ("DEFENSIVE", "LOCKDOWN") or reversal_active:
                logger.warning(
                    "SHARED_RISK_GATE_BLOCK | account=%s | symbol=%s | action=%s | "
                    "code=CONFLICTING_ADD_BLOCK | target=%s opp=%s rba=%s rev=%s | source=%s",
                    account_id, symbol, action_upper, target_upper, opposite,
                    rba_state, reversal_active, source,
                )
                return RiskGateResult(
                    passed=False,
                    block_code="SAFETY_BLOCK_CONFLICTING_ADD",
                    block_reason=(
                        f"Conflicting add: hold {opposite}, adding {target_upper} "
                        f"while rba={rba_state} rev={reversal_active}"
                    ),
                    meta={"rba_state": rba_state, "reversal_active": reversal_active,
                          "target_side": target_upper, "opposite_side": opposite},
                )

    except Exception:
        pass

    return RiskGateResult(passed=True)
