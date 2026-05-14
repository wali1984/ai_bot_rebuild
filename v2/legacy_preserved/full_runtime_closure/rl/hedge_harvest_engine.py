"""
Hedge Harvest Engine (No-Loss)
=============================

Goal:
- In a no-loss system, underwater legs cannot be closed. Equity growth must come from:
  - harvesting profits on green hedge legs during oscillations
  - optionally recycling *earned* profits into recovery adds (hedged-only) on strong reversals

This module emits:
- PARTIAL_CLOSE_{SIDE} (profit-only intent) for the *hedge leg* when it is sufficiently green
  and hedge ratio is above a target.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Import from config.py (single source of truth) with safe fallbacks
try:
    from config import (
        ENABLE_HEDGE_HARVEST as _cfg_hh_enabled,
        HEDGE_HARVEST_MIN_ROE_PCT as _cfg_hh_roe,
        HEDGE_HARVEST_LOG_VERBOSE as _cfg_hh_verbose,
    )
    HEDGE_HARVEST_ENABLED = _cfg_hh_enabled
    HEDGE_HARVEST_MIN_ROE_PCT = _cfg_hh_roe
    HEDGE_HARVEST_LOG_VERBOSE = _cfg_hh_verbose
except ImportError:
    HEDGE_HARVEST_ENABLED = os.getenv("ENABLE_HEDGE_HARVEST", "true").lower() in ("1", "true", "yes")
    HEDGE_HARVEST_MIN_ROE_PCT = float(os.getenv("HEDGE_HARVEST_MIN_ROE_PCT", "5.0"))
    HEDGE_HARVEST_LOG_VERBOSE = os.getenv("HEDGE_HARVEST_LOG_VERBOSE", "true").lower() in ("1", "true", "yes")


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except Exception:
        return float(default)


def _clamp01(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x > 1.0:
        x /= 100.0
    return max(0.0, min(1.0, x))


@dataclass
class HarvestDecision:
    should_harvest: bool
    close_side: Optional[str] = None
    close_fraction: float = 0.0
    reason: str = ""


class HedgeHarvestEngine:
    def __init__(self, redis_client: Any = None):
        self.redis = redis_client
        self._last_emit: Dict[str, float] = {}

    def decide(
        self,
        *,
        account_id: str,
        symbol: str,
        main_side: str,
        hedge_side: str,
        main_roe_pct: float,
        hedge_roe_pct: float,
        hedge_ratio: float,
        target_ratio: float,
        confidence: float,
        micro_ctx: Optional[Dict[str, Any]] = None,
        cooldown_sec: int = 90,
    ) -> HarvestDecision:
        aid = str(account_id or "").lower().strip()
        sym = str(symbol or "").upper().strip()
        if not aid or not sym:
            return HarvestDecision(False, reason="missing_account_or_symbol")

        # Cooldown per (account,symbol)
        now = time.time()
        key = f"{aid}:{sym}:harvest"
        last = float(self._last_emit.get(key, 0.0) or 0.0)
        if (now - last) < float(max(15, cooldown_sec)):
            return HarvestDecision(False, reason="cooldown")

        # Check if enabled
        if not HEDGE_HARVEST_ENABLED:
            return HarvestDecision(False, reason="disabled")
        
        # Harvest only if hedge is green enough and we're over-covered vs target.
        # Regime-aware: when regime favors the hedge direction (FAST/IMPULSE trending),
        # raise min ROE to keep hedge protection alive during large moves.
        min_roe = HEDGE_HARVEST_MIN_ROE_PCT
        try:
            if self.redis:
                import json as _jhr
                _hr_raw = self.redis.get(f"regime:{sym}")
                if _hr_raw:
                    _hr = _jhr.loads(_hr_raw.decode("utf-8") if isinstance(_hr_raw, (bytes, bytearray)) else str(_hr_raw))
                    _hr_move = str(_hr.get("move_regime", "")).upper()
                    _hr_trend = str(_hr.get("trend_direction", "")).upper()
                    _hr_side = str(hedge_side).upper()
                    _hr_aligned = (
                        (_hr_side == "LONG" and _hr_trend in ("LONG", "BULLISH", "UP"))
                        or (_hr_side == "SHORT" and _hr_trend in ("SHORT", "BEARISH", "DOWN"))
                    )
                    if _hr_aligned and _hr_move in ("FAST", "IMPULSE", "TRENDING", "BREAKOUT"):
                        _old_min = min_roe
                        _roe_mult = 1.5
                        try:
                            for _hr_tf in ("15m", "5m", "1h"):
                                _hr_feat_raw = self.redis.hgetall(f"unified_features:{sym}:{_hr_tf}")
                                if not _hr_feat_raw:
                                    continue
                                _hr_feat = {(k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)): (v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)) for k, v in _hr_feat_raw.items()}
                                _hr_adx = None
                                for _adxk in ("adx_14", "adx", "ind_ta_ADX_14"):
                                    if _adxk in _hr_feat:
                                        try: _hr_adx = float(_hr_feat[_adxk]); break
                                        except Exception: pass
                                _hr_atr = None
                                for _atrk in ("atr_pct", "atr_14", "ind_ta_ATR_14"):
                                    if _atrk in _hr_feat:
                                        try: _hr_atr = float(_hr_feat[_atrk]); break
                                        except Exception: pass
                                if _hr_adx is not None:
                                    if _hr_adx > 40: _roe_mult += 1.5
                                    elif _hr_adx > 25: _roe_mult += 0.8
                                    elif _hr_adx > 15: _roe_mult += 0.3
                                if _hr_atr is not None and _hr_atr > 0:
                                    if _hr_atr > 4.0: _roe_mult += 0.5
                                    elif _hr_atr > 2.0: _roe_mult += 0.3
                                break
                        except Exception:
                            pass
                        _roe_mult = max(1.5, min(4.0, _roe_mult))
                        min_roe = min_roe * _roe_mult
                        logger.info(
                            "[HEDGE_HARVEST] REGIME_ROE_RAISE | %s:%s | regime=%s trend=%s | "
                            "hedge_side=%s aligned=True | mult=%.2f | min_roe raised to %.1f%%",
                            aid, sym, _hr_move, _hr_trend, _hr_side, _roe_mult, min_roe,
                        )
        except Exception:
            pass
        if float(hedge_roe_pct) < min_roe:
            if HEDGE_HARVEST_LOG_VERBOSE:
                logger.debug(f"[HEDGE_HARVEST] {aid}:{sym} | SKIP | hedge_roe={hedge_roe_pct:.2f}% < min={min_roe}%")
            return HarvestDecision(False, reason=f"hedge_not_green_enough|roe={hedge_roe_pct:.2f}<{min_roe}")
        if float(hedge_ratio) <= float(target_ratio) * 1.05:
            if HEDGE_HARVEST_LOG_VERBOSE:
                logger.debug(f"[HEDGE_HARVEST] {aid}:{sym} | SKIP | ratio={hedge_ratio:.2f} <= target={target_ratio:.2f}*1.05")
            return HarvestDecision(False, reason="hedge_ratio_not_above_target")

        conf01 = _clamp01(confidence)

        # ── ICG GATE: defer harvest when hedge is protecting against an ongoing move ──
        try:
            if self.redis:
                from risk.intelligent_close_guard import evaluate_close as _hh_icg_eval
                _hh_icg = _hh_icg_eval(
                    self.redis, sym, str(hedge_side).upper(),
                    close_reason=f"HEDGE_HARVEST roe={hedge_roe_pct:.2f}%",
                    is_hard_emergency=False,
                )
                if _hh_icg.should_defer:
                    logger.info(
                        "[HEDGE_HARVEST] ICG_DEFER | %s:%s | hold_score=%.3f | "
                        "sources=%d | hedge is protecting ongoing move",
                        aid, sym, _hh_icg.hold_score, _hh_icg.data_sources_used,
                    )
                    return HarvestDecision(False, reason=f"icg_defer|hold={_hh_icg.hold_score:.3f}|sources={_hh_icg.data_sources_used}")
        except Exception as _hh_icg_err:
            logger.debug("[HEDGE_HARVEST] ICG_ERR | %s | %s", sym, _hh_icg_err)

        # Trainer alignment: suppress harvest when trainer predicts hedge leg will extend profit
        try:
            if self.redis:
                _pred_raw = self.redis.hgetall(f"prediction:{sym}:multi")
                if _pred_raw:
                    _pred = {(k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v) for k, v in _pred_raw.items()}
                    _pred_dir = str(_pred.get("direction", "")).upper()
                    _pred_conf = float(_pred.get("confidence", _pred.get("model_confidence", 0)) or 0)
                    _h_side_u = str(hedge_side).upper()
                    _trainer_favours_hedge = (
                        (_h_side_u == "LONG" and _pred_dir == "LONG") or
                        (_h_side_u == "SHORT" and _pred_dir == "SHORT")
                    )
                    if _trainer_favours_hedge and _pred_conf >= 0.70:
                        logger.info(
                            f"[HEDGE_HARVEST] TRAINER_SUPPRESS | {aid}:{sym} | trainer predicts "
                            f"{_pred_dir} conf={_pred_conf:.3f} aligns with hedge_side={_h_side_u} — letting it run"
                        )
                        return HarvestDecision(False, reason=f"trainer_favours_hedge|dir={_pred_dir}|conf={_pred_conf:.3f}")
        except Exception:
            pass

        # --------------------------------------------------------------------
        # Continuation-risk awareness (Phase 1 hardening; backward compatible)
        # --------------------------------------------------------------------
        # If microstructure suggests a high continuation regime, harvesting the hedge leg
        # tends to create "harvest → re-add" loops and hedge cages. We therefore damp
        # harvest size smoothly as continuation risk rises (no hard behavior flip unless
        # the implied harvest size becomes negligible).
        cont_risk = 0.0
        tox = 0.0
        if isinstance(micro_ctx, dict):
            try:
                # preferred explicit key
                cont_risk = float(micro_ctx.get("continuation_risk", micro_ctx.get("continuation_score", 0.0)) or 0.0)
            except Exception:
                cont_risk = 0.0
            try:
                tox = float(micro_ctx.get("toxicity", 0.0) or 0.0)
            except Exception:
                tox = 0.0
        cont_risk = max(0.0, min(1.0, float(cont_risk)))
        tox = max(0.0, min(1.0, float(tox)))
        # Close fraction scales smoothly with confidence and excess hedge ratio.
        excess = max(0.0, float(hedge_ratio) - float(target_ratio))
        # Map excess 0..0.5 -> 0..1
        excess01 = max(0.0, min(1.0, excess / 0.5))
        base = 0.10 + 0.25 * conf01  # 10%..35%
        frac = base * (0.50 + 0.50 * excess01)  # 50%..100% multiplier

        # Continuation/toxicity dampening: keep a runner in continuation regimes.
        # - When cont_risk=0.0 => no change
        # - When cont_risk=1.0 => reduce harvest size sharply (but not forcibly to zero)
        damp = (1.0 - (0.85 * cont_risk)) * (1.0 - (0.35 * tox))
        damp = max(0.0, min(1.0, float(damp)))
        frac = float(frac) * float(damp)
        frac = max(0.05, min(0.40, float(frac)))  # clamp to 5%..40%

        # If dampening makes the harvest too small to matter, skip to avoid churn.
        if float(frac) < 0.03:
            return HarvestDecision(False, reason=f"skip_small_after_damp|frac={frac:.3f}|cont={cont_risk:.2f}|tox={tox:.2f}")

        self._last_emit[key] = now
        reason = (
            f"harvest hedge_roe={hedge_roe_pct:.2f}% ratio={hedge_ratio:.2f} target={target_ratio:.2f} "
            f"conf={conf01:.2f} cont={cont_risk:.2f} tox={tox:.2f}"
        )
        logger.info(f"🌾 [HEDGE_HARVEST] TRIGGER | {aid}:{sym} | close_side={hedge_side} | frac={frac:.2%} | {reason}")
        return HarvestDecision(
            True,
            close_side=str(hedge_side).upper(),
            close_fraction=float(frac),
            reason=reason,
        )

    def build_signal(
        self,
        *,
        account_id: str,
        symbol: str,
        close_side: str,
        close_fraction: float,
        confidence: float,
        reason: str,
    ) -> Dict[str, Any]:
        side_u = str(close_side or "").upper()
        action = f"PARTIAL_CLOSE_{side_u}"
        return {
            "account_id": str(account_id or "").lower(),
            "symbol": str(symbol or "").upper(),
            "action": action,
            "action_name": action,
            "timeframe": "multi",
            "confidence": float(confidence),
            # Trader expects close_fraction for partial close mapping.
            "close_fraction": float(close_fraction),
            "action_category": "PROTECTIVE",
            "source": "hedge_harvest_engine",
            # For profit bank: mark as profit intent (still subject to trader net-profit checks).
            "profit_intent": True,
            # Hint to avoid treating as main-leg close.
            "hedge_intent": True,
            "reason": f"💰 {reason}",
        }

    def emit_proposal(
        self,
        *,
        account_id: str,
        symbol: str,
        close_side: str,
        close_fraction: float,
        confidence: float,
        reason: str,
    ) -> bool:
        """Emit a proposal to the orchestrator proposal bus."""
        if not self.redis:
            return False
        try:
            from rl.proposal_bus import emit_proposal
            signal = self.build_signal(
                account_id=account_id,
                symbol=symbol,
                close_side=close_side,
                close_fraction=close_fraction,
                confidence=confidence,
                reason=reason,
            )
            signal["event"] = "HEDGE_HARVEST_PROPOSAL"
            try:
                from risk.trainer_alignment import enrich_proposal_with_trainer
                enrich_proposal_with_trainer(self.redis, signal)
            except Exception:
                pass
            success = emit_proposal(self.redis, stream="proposals:hedge_harvest", proposal=signal)
            if success:
                logger.info(f"🌾 [HEDGE_HARVEST] PROPOSAL_EMITTED | {account_id}:{symbol} {close_side} | frac={close_fraction:.1%}")
            return success
        except Exception as e:
            logger.warning(f"[HEDGE_HARVEST] emit_proposal error: {e}")
            return False
