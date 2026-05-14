"""
Adaptive Market-Condition Gate (Feb 2026)
=========================================
Replaces ALL timer-based anti-churn workarounds with real-time, data-driven gates
that read from the 500+ features in unified_features:{symbol}:{tf} Redis hashes.

Instead of "wait 30 minutes" or "max 3 trades/hour", decisions are based on:
  - Spread width → too expensive to trade? BLOCK
  - ATR / volatility → has the move already been captured? BLOCK
  - Orderbook depth → enough liquidity to execute? BLOCK/SIZE_REDUCE
  - Orderbook imbalance → is the book against us? DELAY
  - Fast-move score → chasing a spike? DELAY
  - Trend strength (ADX) → is there a trend to capture? REQUIRE for entries
  - Funding rate extremes → crowded trade? WARN
  - Spoof/churn score → manipulated book? BLOCK

Usage:
    from risk.adaptive_gate import AdaptiveGate
    gate = AdaptiveGate(redis_client)
    verdict = gate.evaluate(symbol, side, action_type, notional_usd)
    if not verdict.allow:
        logger.warning(f"ADAPTIVE_GATE_BLOCK | {verdict.code} | {verdict.reason}")
"""

import time
import os
import logging
import json
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

logger = logging.getLogger("adaptive_gate")


@dataclass
class GateVerdict:
    """Result of adaptive gate evaluation."""
    allow: bool = True
    code: str = "PASS"
    reason: str = ""
    sizing_mult: float = 1.0      # 0.0-1.0 — scale position size down
    delay_seconds: float = 0.0    # how long to delay execution (0=immediate)
    meta: Dict[str, Any] = field(default_factory=dict)


class AdaptiveGate:
    """
    Real-time market-condition gate that replaces all timer-based anti-churn.
    
    Reads live features from Redis unified_features hashes and orderbook keys.
    All thresholds are data-driven, not time-driven.
    """

    def __init__(self, redis_client):
        self.redis = redis_client
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ts: Dict[str, float] = {}
        self._cache_ttl = 5.0  # 5s cache to avoid hammering Redis

        # Feature flags / policy controls (env-driven; defaults are conservative)
        def _env_bool(name: str, default: str) -> bool:
            return str(os.getenv(name, default) or default).lower() in ("1", "true", "yes", "on")

        self._spread_enabled = _env_bool("ADAPTIVE_GATE_SPREAD_ENABLED", "true")
        self._liquidity_enabled = _env_bool("ADAPTIVE_GATE_LIQUIDITY_ENABLED", "true")
        self._volatility_enabled = _env_bool("ADAPTIVE_GATE_VOLATILITY_ENABLED", "true")
        self._fast_move_enabled = _env_bool("ADAPTIVE_GATE_FAST_MOVE_ENABLED", "true")
        self._trend_enabled = _env_bool("ADAPTIVE_GATE_TREND_ENABLED", "true")
        self._imbalance_enabled = _env_bool("ADAPTIVE_GATE_IMBALANCE_ENABLED", "true")
        self._funding_enabled = _env_bool("ADAPTIVE_GATE_FUNDING_ENABLED", "true")
        self._manipulation_enabled = _env_bool("ADAPTIVE_GATE_MANIPULATION_ENABLED", "true")
        self._edge_fees_enabled = _env_bool("ADAPTIVE_GATE_EDGE_FEES_ENABLED", "true")

        # Soft override: allow some entry blocks as sizing reductions so the system can
        # actually trade on trainer outputs (instead of being permanently vetoed).
        self._entry_soft_override = _env_bool("ADAPTIVE_GATE_ENTRY_SOFT_OVERRIDE", "false")
        try:
            self._entry_soft_max_blocks = int(os.getenv("ADAPTIVE_GATE_ENTRY_SOFT_MAX_BLOCKS", "1") or 1)
        except Exception:
            self._entry_soft_max_blocks = 1
        hard_codes = os.getenv("ADAPTIVE_GATE_ENTRY_HARD_BLOCK_CODES", "MANIPULATION_HIGH,EDGE_TOO_SMALL") or ""
        self._entry_hard_block_codes = {c.strip().upper() for c in hard_codes.split(",") if c.strip()}
        # Configurable thresholds (env-overridable)
        try:
            self._fast_move_block_threshold = float(os.getenv("ADAPTIVE_GATE_FAST_MOVE_BLOCK_THRESHOLD", "0.75") or 0.75)
        except Exception:
            self._fast_move_block_threshold = 0.75
        try:
            self._trend_di_mult = float(os.getenv("ADAPTIVE_GATE_TREND_DI_MULT", "1.3") or 1.3)
        except Exception:
            self._trend_di_mult = 1.3
        # Minimum sizing multipliers applied when soft-overriding specific block codes.
        self._soft_block_penalty_mult = {
            "SPREAD_WIDE": 0.6,
            "LIQUIDITY_THIN": 0.5,
            "VOL_TOO_LOW": 0.5,
            "FAST_MOVE_CHASE": 0.4,
            "NO_TREND": 0.6,
            "TREND_AGAINST": 0.6,
            "IMBALANCE_AGAINST": 0.6,
            "FUNDING_EXTREME": 0.6,
        }

    # ── Public API ──────────────────────────────────────────────────────

    def evaluate(
        self,
        symbol: str,
        side: str,
        action_type: str,       # "open", "close", "increase", "hedge", "flip"
        notional_usd: float = 0.0,
        current_price: float = 0.0,
        entry_price: float = 0.0,
        model_confidence: float = 0.0,
        timeframe: str = "5m",
    ) -> GateVerdict:
        """
        Evaluate whether a trade should proceed based on live market conditions.
        
        Returns a GateVerdict with allow=True/False, sizing_mult, and reason codes.
        """
        sym = str(symbol).upper()
        tf = str(timeframe or "5m").lower().strip() or "5m"
        feat = self._get_features(sym, tf)
        if not feat:
            feat = self._get_features(sym, "5m")
        ob = self._get_orderbook(sym)
        conf = float(model_confidence or 0)

        # Collect all sub-gate verdicts
        checks = []

        # Only apply entry-blocking gates to risk-adding actions
        is_entry = action_type in ("open", "increase", "flip")
        is_protective = action_type in ("close", "hedge", "reduce")

        # 1. SPREAD GATE — is execution too expensive?
        if self._spread_enabled:
            checks.append(self._check_spread(feat, ob, sym, notional_usd, is_entry))

        # 2. LIQUIDITY GATE — is there enough depth to absorb us?
        if self._liquidity_enabled:
            checks.append(self._check_liquidity(feat, ob, sym, notional_usd, is_entry))

        # 3. VOLATILITY REGIME GATE — is the market too wild or too dead?
        if self._volatility_enabled:
            checks.append(self._check_volatility(feat, sym, is_entry))

        # 4. FAST-MOVE GATE — are we chasing a spike?
        if self._fast_move_enabled:
            checks.append(self._check_fast_move(feat, sym, is_entry))

        # 5. TREND STRENGTH GATE — is there an actual trend to capture?
        if is_entry and self._trend_enabled:
            checks.append(self._check_trend_strength(feat, sym, side))

        # 6. ORDERBOOK IMBALANCE GATE — is the book against our direction?
        if is_entry and self._imbalance_enabled:
            checks.append(self._check_imbalance(feat, ob, sym, side))

        # 7. FUNDING RATE GATE — are we entering a crowded trade?
        if is_entry and self._funding_enabled:
            checks.append(self._check_funding(feat, sym, side))

        # 8. SPOOF/MANIPULATION GATE — is the book being manipulated?
        if self._manipulation_enabled:
            checks.append(self._check_manipulation(feat, sym))

        # 9. EDGE-AFTER-FEES GATE — does expected move cover round-trip costs?
        if is_entry and self._edge_fees_enabled:
            checks.append(self._check_edge_after_fees(feat, ob, sym, notional_usd))

        # Aggregate: confidence-aware gating.
        # High-confidence trainer signals (>= 0.85) get a soft override for non-critical
        # blocks (e.g. TREND_AGAINST, NO_TREND, IMBALANCE_AGAINST) — these are converted
        # to sizing reductions instead of hard blocks. Only MANIPULATION_HIGH and
        # EDGE_TOO_SMALL remain hard blocks regardless of confidence.
        # Lower confidence signals use configurable soft override behavior.
        final = GateVerdict(allow=True, code="PASS", sizing_mult=1.0)
        blocked_reasons = []
        blocked_codes = []
        for v in checks:
            if not v.allow:
                blocked_reasons.append(f"{v.code}: {v.reason}")
                blocked_codes.append(str(v.code or "").upper())
            final.sizing_mult = min(final.sizing_mult, v.sizing_mult)
            final.delay_seconds = max(final.delay_seconds, v.delay_seconds)
            final.meta[v.code] = {
                "allow": v.allow,
                "sizing_mult": round(v.sizing_mult, 3),
                "reason": v.reason,
            }

        if blocked_reasons:
            # For protective actions, only block if EVERY gate says block (fail-open)
            if is_protective and len(blocked_reasons) < 3:
                final.allow = True
                final.code = "PASS_PROTECTIVE_OVERRIDE"
                final.reason = f"Protective action allowed despite: {'; '.join(blocked_reasons)}"
                final.sizing_mult = max(0.25, final.sizing_mult)
            _ag_hi_conf = 0.85
            try:
                _ag_adx = None
                for _agk in ("adx_14", "adx", "ind_ta_ADX_14"):
                    if feat and _agk in feat:
                        _ag_adx = float(feat[_agk]); break
                _ag_regime_raw = self.redis.get(f"regime:{sym}") if self.redis else None
                if _ag_regime_raw:
                    import json as _agj
                    _ag_rd = _agj.loads(_ag_regime_raw.decode("utf-8") if isinstance(_ag_regime_raw, (bytes, bytearray)) else str(_ag_regime_raw))
                    _ag_move = str(_ag_rd.get("move_regime", "")).upper()
                    if _ag_move in ("FAST", "IMPULSE", "TRENDING", "BREAKOUT"):
                        _ag_hi_conf -= 0.08
                    _ag_tfa = abs(float(_ag_rd.get("tf_alignment", 0) or 0))
                    if _ag_tfa > 0.5:
                        _ag_hi_conf -= 0.03
                if _ag_adx is not None and _ag_adx > 30:
                    _ag_hi_conf -= 0.04
                _ag_hi_conf = max(0.65, min(0.85, _ag_hi_conf))
            except Exception:
                pass
            if is_entry and conf >= _ag_hi_conf:
                hard_hit = any(c in self._entry_hard_block_codes for c in blocked_codes)
                if hard_hit:
                    final.allow = False
                    final.code = "ADAPTIVE_BLOCK"
                    final.reason = "; ".join(blocked_reasons)
                else:
                    final.allow = True
                    final.code = "PASS_HIGH_CONF_OVERRIDE"
                    final.reason = f"conf={conf:.3f} override ({len(blocked_reasons)} soft blocks): {'; '.join(blocked_reasons)}"
                    for c in blocked_codes:
                        pen = float(self._soft_block_penalty_mult.get(c, 0.65))
                        final.sizing_mult = min(final.sizing_mult, max(0.15, min(1.0, pen)))
            # Soft override for entries (configurable via env)
            elif is_entry and self._entry_soft_override:
                hard_hit = any(c in self._entry_hard_block_codes for c in (blocked_codes or []))
                too_many = len(blocked_reasons) > int(self._entry_soft_max_blocks)
                if hard_hit or too_many:
                    final.allow = False
                    final.code = "ADAPTIVE_BLOCK"
                    final.reason = "; ".join(blocked_reasons)
                else:
                    final.allow = True
                    final.code = "PASS_ENTRY_SOFT_OVERRIDE"
                    final.reason = f"Soft-allowed entry despite: {'; '.join(blocked_reasons)}"
                    for c in blocked_codes:
                        try:
                            pen = float(self._soft_block_penalty_mult.get(c, 0.65))
                        except Exception:
                            pen = 0.65
                        final.sizing_mult = min(final.sizing_mult, max(0.05, min(1.0, pen)))
            else:
                final.allow = False
                final.code = "ADAPTIVE_BLOCK"
                final.reason = "; ".join(blocked_reasons)

        return final

    def compute_adaptive_hold_score(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        unrealized_pnl_pct: float,
    ) -> Dict[str, Any]:
        """
        Instead of a fixed MIN_HOLD timer, compute whether the position should
        continue to be held based on live market data.
        
        Returns {"should_hold": bool, "reason": str, "urgency": float 0-1}
        """
        sym = str(symbol).upper()
        feat = self._get_features(sym, "5m")

        atr_pct = _feat(feat, "ind_ta_NATR_14", "5m")
        adx = _feat(feat, "ind_ta_ADX_14", "5m")
        # For hold decisions: use instantaneous score first (active spike matters more),
        # fall back to 1m rolling max as secondary signal
        fast_move_now = _safe_float(feat, "depth_fast_move_score")
        fast_move_1m = _safe_float(feat, "depth_fast_move_1m")
        fast_move = max(fast_move_now, fast_move_1m * 0.7)  # discount rolling max
        rsi = _feat(feat, "ind_ta_RSI_14", "5m")
        momentum = _feat(feat, "ind_ta_MOM_10", "5m")
        imbalance = _safe_float(feat, "depth_imbalance_5")

        reasons = []
        hold_score = 0.0  # positive = hold, negative = close

        # Strong trend + in profit → HOLD
        if adx > 25 and unrealized_pnl_pct > 0.5:
            hold_score += 2.0
            reasons.append(f"strong_trend ADX={adx:.1f}")

        # Momentum still favorable → HOLD
        if side == "LONG" and momentum > 0:
            hold_score += 1.0
            reasons.append(f"momentum_favorable={momentum:.2f}")
        elif side == "SHORT" and momentum < 0:
            hold_score += 1.0
            reasons.append(f"momentum_favorable={momentum:.2f}")

        # RSI not yet overbought/oversold → HOLD
        if side == "LONG" and rsi < 72:
            hold_score += 0.5
            reasons.append(f"RSI_not_overbought={rsi:.1f}")
        elif side == "SHORT" and rsi > 28:
            hold_score += 0.5
            reasons.append(f"RSI_not_oversold={rsi:.1f}")

        # Orderbook imbalance favors our direction → HOLD
        if side == "LONG" and imbalance > 0.1:
            hold_score += 0.5
            reasons.append(f"book_favors_long imbalance={imbalance:.2f}")
        elif side == "SHORT" and imbalance < -0.1:
            hold_score += 0.5
            reasons.append(f"book_favors_short imbalance={imbalance:.2f}")

        # Fast move AGAINST us → urgent exit signal
        if fast_move > 0.5:
            hold_score -= 1.5
            reasons.append(f"fast_move_against={fast_move:.2f}")

        # ATR says expected move is larger than current PnL → HOLD (room to run)
        if atr_pct > 0 and abs(unrealized_pnl_pct) < atr_pct * 1.5:
            hold_score += 1.0
            reasons.append(f"ATR_room_to_run NATR={atr_pct:.3f}")

        # Already captured > 2x ATR → consider exit
        if atr_pct > 0 and unrealized_pnl_pct > atr_pct * 2.0:
            hold_score -= 1.0
            reasons.append(f"captured_2x_ATR pnl={unrealized_pnl_pct:.2f}%>2*NATR={atr_pct*2:.3f}")

        should_hold = hold_score > 0
        urgency = max(0.0, min(1.0, -hold_score / 3.0)) if not should_hold else 0.0

        return {
            "should_hold": should_hold,
            "hold_score": round(hold_score, 2),
            "urgency": round(urgency, 2),
            "reason": "; ".join(reasons) if reasons else "no_data",
            "atr_pct": round(atr_pct, 4),
            "adx": round(adx, 1),
            "rsi": round(rsi, 1),
        }

    # ── Sub-gates ───────────────────────────────────────────────────────

    def _check_spread(self, feat, ob, sym, notional_usd, is_entry) -> GateVerdict:
        """Block when spread is too wide (execution cost too high)."""
        spread_bps = _safe_float(feat, "ob_ob_spread_bps")
        if spread_bps <= 0:
            spread_abs = _safe_float(feat, "depth_spread")
            mid = _safe_float(feat, "depth_mid_price") or _safe_float(ob, "mid_px")
            if mid > 0 and spread_abs > 0:
                spread_bps = (spread_abs / mid) * 10000.0

        if spread_bps <= 0:
            return GateVerdict(code="SPREAD", reason="no_spread_data")

        # Adaptive thresholds based on notional — larger orders need tighter spreads
        if notional_usd > 50000:
            max_spread = 3.0   # large order: need <3bps
        elif notional_usd > 10000:
            max_spread = 5.0   # medium: <5bps
        else:
            max_spread = 8.0   # small: <8bps

        if is_entry and spread_bps > max_spread:
            return GateVerdict(
                allow=False, code="SPREAD_WIDE",
                reason=f"spread={spread_bps:.1f}bps > max={max_spread:.0f}bps for ${notional_usd:.0f}",
                meta={"spread_bps": spread_bps, "max_spread_bps": max_spread},
            )

        # Partial size reduction when spread is elevated
        sizing = 1.0
        if spread_bps > max_spread * 0.6:
            sizing = max(0.3, 1.0 - (spread_bps - max_spread * 0.6) / (max_spread * 0.4))

        return GateVerdict(code="SPREAD", sizing_mult=sizing,
                           reason=f"spread={spread_bps:.1f}bps ok")

    def _check_liquidity(self, feat, ob, sym, notional_usd, is_entry) -> GateVerdict:
        """Block when orderbook depth is too thin for our size."""
        depth_usd = _safe_float(feat, "depth_bps_10_total_usd")
        if depth_usd <= 0:
            depth_usd = _safe_float(feat, "depth_total_usd") or _safe_float(ob, "total_depth")
        if depth_usd <= 0:
            depth_usd = _safe_float(feat, "orderbook_depth_usd")

        if depth_usd <= 0:
            return GateVerdict(code="LIQUIDITY", reason="no_depth_data")

        # Our order should be < 5% of visible depth to avoid impact
        impact_pct = (notional_usd / max(depth_usd, 1.0)) * 100.0 if notional_usd > 0 else 0

        if is_entry and impact_pct > 5.0:
            return GateVerdict(
                allow=False, code="LIQUIDITY_THIN",
                reason=f"impact={impact_pct:.1f}% of ${depth_usd:.0f} depth",
                meta={"depth_usd": depth_usd, "impact_pct": impact_pct},
            )

        # SIZE_REDUCE when impact > 2%
        sizing = 1.0
        if impact_pct > 2.0:
            sizing = max(0.2, 2.0 / impact_pct)

        quality = _safe_float(feat, "depth_quality_score")
        if quality > 0 and quality < 0.3:
            sizing = min(sizing, 0.5)

        return GateVerdict(code="LIQUIDITY", sizing_mult=sizing,
                           reason=f"depth=${depth_usd:.0f} impact={impact_pct:.1f}%")

    def _check_volatility(self, feat, sym, is_entry) -> GateVerdict:
        """
        Block entries in dead markets (no vol = no edge) or extreme vol (too risky).
        Allow exits always.
        """
        natr = _feat(feat, "ind_ta_NATR_14", "5m")
        vol_pct = _safe_float(feat, "volatility_pct") or _safe_float(feat, "ccxt_volatility_5m")

        if natr <= 0 and vol_pct <= 0:
            return GateVerdict(code="VOLATILITY", reason="no_vol_data")

        effective_vol = natr if natr > 0 else vol_pct

        # Dead market: NATR < 0.05% (5 bps over 14 periods) → no edge to capture
        if is_entry and effective_vol < 0.05:
            return GateVerdict(
                allow=False, code="VOL_TOO_LOW",
                reason=f"NATR={effective_vol:.4f}% — dead market, no edge",
                meta={"natr": natr, "vol_pct": vol_pct},
            )

        # High vol = opportunity. Only mildly reduce at EXTREME levels (>8%)
        # for unhedged entries. Hedged entries get FULL sizing.
        sizing = 1.0
        if effective_vol > 8.0:
            # Only extreme outliers get mild reduction (never below 0.6x)
            sizing = max(0.6, 1.0 / (effective_vol / 4.0))

        return GateVerdict(code="VOLATILITY", sizing_mult=sizing,
                           reason=f"NATR={effective_vol:.4f}%")

    def _check_fast_move(self, feat, sym, is_entry) -> GateVerdict:
        """Block entries during/after a fast price spike (chasing).
        
        Uses the instantaneous fast_move_score as primary signal.
        The rolling max fields (fast_move_1m/5m) are only used as a secondary
        signal for sizing reduction — they stay pinned high for minutes after
        a spike passes and would cause over-blocking if used for hard blocks.
        """
        fast_score = _safe_float(feat, "depth_fast_move_score")  # instantaneous (0 = no spike NOW)
        fast_1m = _safe_float(feat, "depth_fast_move_1m") or _safe_float(feat, "depth_fast_move_score_1m")
        fast_5m = _safe_float(feat, "depth_fast_move_5m") or _safe_float(feat, "depth_fast_move_score_5m")

        # PRIMARY: instantaneous score — this is the only signal that should BLOCK
        # Rolling max (1m/5m) are only used for sizing reduction since they stay
        # elevated well after the spike has passed
        if fast_score <= 0 and fast_1m <= 0 and fast_5m <= 0:
            return GateVerdict(code="FAST_MOVE", reason="no_fast_move_data")

        # Hard block ONLY during truly extreme spikes (>0.92)
        # Normal high vol (0.5-0.9) is opportunity, not risk
        _fm_block_thr = max(self._fast_move_block_threshold, 0.92)
        if is_entry and fast_score > _fm_block_thr:
            return GateVerdict(
                allow=False, code="FAST_MOVE_CHASE",
                reason=f"fast_move_NOW={fast_score:.2f} > {_fm_block_thr:.2f} — extreme spike in progress",
                meta={"fast_1m": fast_1m, "fast_5m": fast_5m, "score": fast_score},
            )

        # Sizing reduction: instantaneous score is primary, rolling max is secondary.
        # Rolling max (fast_1m) stays pinned at 1.0 for minutes after a spike,
        # so discount it heavily to avoid chronic 0.5x sizing on every trade.
        recent_heat = max(fast_score, fast_1m * 0.3)
        sizing = 1.0
        if recent_heat > 0.7:
            sizing = max(0.7, 1.0 - (recent_heat - 0.7) * 0.5)

        return GateVerdict(code="FAST_MOVE", sizing_mult=sizing,
                           reason=f"fast_move={fast_score:.2f} 1m_max={fast_1m:.2f} 5m_max={fast_5m:.2f}")

    def _check_trend_strength(self, feat, sym, side) -> GateVerdict:
        """Require minimum trend strength for directional entries."""
        adx = _feat(feat, "ind_ta_ADX_14", "5m")
        plus_di = _feat(feat, "ind_ta_PLUS_DI_14", "5m")
        minus_di = _feat(feat, "ind_ta_MINUS_DI_14", "5m")

        if adx <= 0:
            return GateVerdict(code="TREND", reason="no_ADX_data")

        # ADX < 12 = no trend → block entries (ranging market eats fees)
        if adx < 12:
            return GateVerdict(
                allow=False, code="NO_TREND",
                reason=f"ADX={adx:.1f} < 12 — ranging market, no edge",
                meta={"adx": adx, "plus_di": plus_di, "minus_di": minus_di},
            )

        # Check direction alignment if DI data available
        if plus_di > 0 and minus_di > 0:
            if side == "LONG" and minus_di > plus_di * self._trend_di_mult:
                return GateVerdict(
                    allow=False, code="TREND_AGAINST",
                    reason=f"LONG entry but -DI={minus_di:.1f} > +DI={plus_di:.1f} (mult={self._trend_di_mult:.1f})",
                    meta={"adx": adx, "plus_di": plus_di, "minus_di": minus_di},
                )
            if side == "SHORT" and plus_di > minus_di * self._trend_di_mult:
                return GateVerdict(
                    allow=False, code="TREND_AGAINST",
                    reason=f"SHORT entry but +DI={plus_di:.1f} > -DI={minus_di:.1f} (mult={self._trend_di_mult:.1f})",
                    meta={"adx": adx, "plus_di": plus_di, "minus_di": minus_di},
                )

        return GateVerdict(code="TREND", reason=f"ADX={adx:.1f} +DI={plus_di:.1f} -DI={minus_di:.1f}")

    def _check_imbalance(self, feat, ob, sym, side) -> GateVerdict:
        """Block entries when orderbook heavily stacked against our direction."""
        imb = _safe_float(feat, "depth_imbalance_5")
        if imb == 0:
            imb = _safe_float(ob, "imbalance")

        if imb == 0:
            return GateVerdict(code="IMBALANCE", reason="no_imbalance_data")

        # imbalance > 0 = bids dominate (bullish), < 0 = asks dominate (bearish)
        # Block LONG when strongly ask-dominated, SHORT when bid-dominated
        threshold = 0.35  # 35% imbalance against us

        if side == "LONG" and imb < -threshold:
            return GateVerdict(
                allow=False, code="IMBALANCE_AGAINST",
                reason=f"LONG entry but book ask-heavy imb={imb:.2f}",
                meta={"imbalance": imb},
            )
        if side == "SHORT" and imb > threshold:
            return GateVerdict(
                allow=False, code="IMBALANCE_AGAINST",
                reason=f"SHORT entry but book bid-heavy imb={imb:.2f}",
                meta={"imbalance": imb},
            )

        return GateVerdict(code="IMBALANCE", reason=f"imbalance={imb:.2f}")

    def _check_funding(self, feat, sym, side) -> GateVerdict:
        """Warn/reduce when funding rate is extreme (crowded trade)."""
        fr = _safe_float(feat, "funding_rate")
        if fr == 0:
            fr = _safe_float(feat, "coinank_fundingRate_indicator_data_0_fr")
        if fr == 0:
            fr = _safe_float(feat, "coinank_fundingRate_indicator_data_0_fundingRate")
        if fr == 0:
            fr = _safe_float(feat, "coinank_fr")

        if fr == 0:
            return GateVerdict(code="FUNDING", reason="no_funding_data")

        # Extreme positive funding → longs are crowded
        # Extreme negative funding → shorts are crowded
        sizing = 1.0
        reason = f"funding={fr:.6f}"

        if side == "LONG" and fr > 0.0005:  # >0.05%/8h = crowded longs
            sizing = max(0.3, 1.0 - (fr - 0.0005) / 0.001)
            reason = f"crowded_longs funding={fr:.6f}"
        elif side == "SHORT" and fr < -0.0005:
            sizing = max(0.3, 1.0 - (abs(fr) - 0.0005) / 0.001)
            reason = f"crowded_shorts funding={fr:.6f}"

        # Extremely crowded → block
        if side == "LONG" and fr > 0.001:
            return GateVerdict(
                allow=False, code="FUNDING_EXTREME",
                reason=f"LONG but funding={fr:.6f} — extremely crowded",
                meta={"funding_rate": fr},
            )
        if side == "SHORT" and fr < -0.001:
            return GateVerdict(
                allow=False, code="FUNDING_EXTREME",
                reason=f"SHORT but funding={fr:.6f} — extremely crowded",
                meta={"funding_rate": fr},
            )

        return GateVerdict(code="FUNDING", sizing_mult=sizing, reason=reason)

    def _check_manipulation(self, feat, sym) -> GateVerdict:
        """Block/reduce when book manipulation detected."""
        spoof = _safe_float(feat, "depth_spoof_score")
        churn = _safe_float(feat, "depth_churn_score")
        snapback = _safe_float(feat, "depth_snapback_score") or _safe_float(feat, "depth_snap_score")

        # Composite manipulation score
        manip = max(spoof, churn, snapback)

        if manip <= 0:
            return GateVerdict(code="MANIPULATION", reason="no_manipulation_data")

        if manip > 0.7:
            return GateVerdict(
                allow=False, code="MANIPULATION_HIGH",
                reason=f"manip={manip:.2f} (spoof={spoof:.2f} churn={churn:.2f} snap={snapback:.2f})",
                meta={"spoof": spoof, "churn": churn, "snapback": snapback},
            )

        sizing = 1.0
        if manip > 0.4:
            sizing = max(0.3, 1.0 - (manip - 0.4) / 0.6)

        return GateVerdict(code="MANIPULATION", sizing_mult=sizing,
                           reason=f"manip={manip:.2f}")

    def _check_edge_after_fees(self, feat, ob, sym, notional_usd) -> GateVerdict:
        """
        Block entries where expected price move < round-trip commission cost.
        
        Uses ATR (expected move) vs spread + taker fee (execution cost).
        """
        natr = _feat(feat, "ind_ta_NATR_14", "5m")
        spread_bps = _safe_float(feat, "ob_ob_spread_bps")
        if spread_bps <= 0:
            spread_abs = _safe_float(feat, "depth_spread")
            mid = _safe_float(feat, "depth_mid_price")
            if mid > 0 and spread_abs > 0:
                spread_bps = (spread_abs / mid) * 10000.0

        if natr <= 0 or spread_bps <= 0:
            return GateVerdict(code="EDGE_FEES", reason="insufficient_data")

        # Expected move = NATR (bps) over one period
        expected_move_bps = natr * 100  # NATR is %, convert to bps

        # Round-trip cost = 2 * taker fee + spread
        # Binance futures taker: ~4.5 bps (0.045%)
        taker_fee_bps = 4.5
        round_trip_cost_bps = 2 * taker_fee_bps + spread_bps

        try:
            from config import MIN_EDGE_AFTER_FEES_BPS
            min_edge = float(MIN_EDGE_AFTER_FEES_BPS)
        except Exception:
            min_edge = 8.0

        net_edge = expected_move_bps - round_trip_cost_bps

        # Adaptive minimum: for low-vol assets (BTC), require proportionally less
        # absolute edge — the leverage amplifies it. For high-vol assets, keep stricter.
        # Ratio: if expected_move > 3x cost, edge is healthy even if absolute bps is small
        cost_ratio = expected_move_bps / round_trip_cost_bps if round_trip_cost_bps > 0 else 0
        # If ATR > 1.4x cost, edge exists even if absolute bps < min_edge
        # BTC: 12.7/9.0 = 1.41x → passes (edge exists, just low absolute bps at low vol)
        # Dead market: 10/9 = 1.11x → fails (barely covers costs)
        if cost_ratio >= 1.4 and net_edge > 0:
            return GateVerdict(
                code="EDGE_FEES",
                sizing_mult=max(0.5, min(1.0, cost_ratio / 2.5)),  # scale size by edge quality
                reason=f"edge={net_edge:.1f}bps ok (ATR={expected_move_bps:.1f} - cost={round_trip_cost_bps:.1f}, ratio={cost_ratio:.2f}x)",
            )

        if net_edge < min_edge:
            return GateVerdict(
                allow=False, code="EDGE_TOO_SMALL",
                reason=f"edge={net_edge:.1f}bps < min={min_edge:.0f}bps "
                       f"(ATR={expected_move_bps:.1f}bps - cost={round_trip_cost_bps:.1f}bps)",
                meta={
                    "expected_move_bps": expected_move_bps,
                    "round_trip_cost_bps": round_trip_cost_bps,
                    "net_edge_bps": net_edge,
                    "natr_pct": natr,
                    "spread_bps": spread_bps,
                },
            )

        return GateVerdict(code="EDGE_FEES",
                           reason=f"edge={net_edge:.1f}bps ok (ATR={expected_move_bps:.1f} - cost={round_trip_cost_bps:.1f})")

    # ── Redis helpers ───────────────────────────────────────────────────

    def _get_features(self, symbol: str, tf: str = "5m") -> Dict[str, Any]:
        """Fetch unified_features from Redis with brief caching."""
        key = f"unified_features:{symbol}:{tf}"
        now = time.time()
        if key in self._cache and (now - self._cache_ts.get(key, 0)) < self._cache_ttl:
            return self._cache[key]
        try:
            if self.redis:
                raw = self.redis.hgetall(key)
                if raw:
                    data = {}
                    for k, v in raw.items():
                        k_str = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
                        v_str = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
                        data[k_str] = v_str
                    self._cache[key] = data
                    self._cache_ts[key] = now
                    return data
        except Exception as e:
            logger.debug(f"[ADAPTIVE_GATE] Redis read failed for {key}: {e}")
        return {}

    def _get_orderbook(self, symbol: str) -> Dict[str, Any]:
        """Fetch orderbook:top data from Redis."""
        key = f"orderbook:top:{symbol}"
        now = time.time()
        if key in self._cache and (now - self._cache_ts.get(key, 0)) < self._cache_ttl:
            return self._cache[key]
        try:
            if self.redis:
                raw = self.redis.get(key)
                if raw:
                    val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    data = json.loads(val)
                    self._cache[key] = data
                    self._cache_ts[key] = now
                    return data
                # Fallback to hash-based orderbook
                raw_h = self.redis.hgetall(f"orderbook:{symbol}")
                if raw_h:
                    data = {}
                    for k, v in raw_h.items():
                        k_str = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
                        v_str = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
                        data[k_str] = v_str
                    self._cache[key] = data
                    self._cache_ts[key] = now
                    return data
        except Exception as e:
            logger.debug(f"[ADAPTIVE_GATE] Orderbook read failed for {key}: {e}")
        return {}


def _safe_float(d: Dict, key: str, default: float = 0.0) -> float:
    """Safely extract a float from a dict (handles bytes, str, None)."""
    if not d:
        return default
    val = d.get(key)
    if val is None:
        return default
    try:
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8")
        return float(val)
    except (ValueError, TypeError):
        return default


def _feat(d: Dict, base_key: str, tf: str = "5m", default: float = 0.0) -> float:
    """
    Smart feature reader: tries multiple key patterns for unified_features.
    
    The Redis hash keys follow several conventions:
      - ind_ta_ADX_14_5m        (with timeframe suffix)
      - ind_ta_ADX_14           (without suffix)  
      - ind_ind_BTCUSDT_ta_ADX_14_5m  (with symbol prefix)
      - ob_ob_spread_bps        (orderbook — no suffix)
      - depth_total_usd         (depth — no suffix)
    """
    if not d:
        return default
    
    # Try exact key first
    val = _safe_float(d, base_key, None)
    if val is not None:
        return val
    
    # Try with timeframe suffix
    val = _safe_float(d, f"{base_key}_{tf}", None)
    if val is not None:
        return val
    
    return default
