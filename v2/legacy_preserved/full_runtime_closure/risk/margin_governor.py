"""
risk/margin_governor.py — Unified Margin Governor.

Enforces four invariants for ALL execution paths (orchestrator, trader, hedge engines):

  I1: Account-level:  totalInitialMargin / equity  <=  GOV_MAX_ACCOUNT_MARGIN_PCT
  I2: Symbol-level:   initialMargin(sym) / equity  <=  GOV_MAX_SYMBOL_MARGIN_PCT
  I3: Protective hedges get elevated caps + net-exposure-aware margin
  I4: When breached  →  verdict = DELEVERAGE (reduce-only mode)

Usage:
    from risk.margin_governor import MarginGovernor, GovernorVerdict

    gov = MarginGovernor(redis_client)
    verdict = gov.evaluate(
        account_id="primary",
        symbol="1000BONKUSDT",
        action="ADD_HEDGE_LONG",
        proposed_margin_usd=12.0,
    )
    if verdict.action == "BLOCK":
        # reject the proposal
    elif verdict.action == "DELEVERAGE":
        # convert to reduce instruction
    else:
        # ALLOW — proceed

Kill-switch:  config.MARGIN_GOVERNOR_ENABLED  (default: True)
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

# ─── helpers ────────────────────────────────────────────────────────────

def _cfg(key: str, default):
    if config is not None:
        val = getattr(config, key, None)
        if val is not None:
            return val
    return default


def _safe_float(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        out = float(v)
        return default if out != out else out
    except Exception:
        return default


# ─── public dataclass ──────────────────────────────────────────────────

class GovernorVerdict:
    """Result of a governor evaluation."""
    __slots__ = (
        "action",          # "ALLOW", "BLOCK", "DELEVERAGE"
        "code",            # machine-readable code e.g. "GOV_ACCOUNT_MARGIN_BREACH"
        "reason",          # human-readable reason
        "meta",            # diagnostic dict
        "suggested_action",  # when DELEVERAGE: suggested action to convert to
    )

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    DELEVERAGE = "DELEVERAGE"

    def __init__(
        self,
        action: str = "ALLOW",
        code: str = "",
        reason: str = "",
        meta: Optional[Dict[str, Any]] = None,
        suggested_action: str = "",
    ):
        self.action = action
        self.code = code
        self.reason = reason
        self.meta = meta or {}
        self.suggested_action = suggested_action

    @property
    def allowed(self) -> bool:
        return self.action == self.ALLOW

    def __repr__(self) -> str:
        return f"GovernorVerdict({self.action}, code={self.code!r})"


# ─── action classification helpers ─────────────────────────────────────

_RISK_ADD_TOKENS = frozenset({
    "OPEN_LONG", "OPEN_SHORT", "OPEN_HEDGE_LONG", "OPEN_HEDGE_SHORT",
    "ADD_HEDGE_LONG", "ADD_HEDGE_SHORT", "INCREASE_LONG", "INCREASE_SHORT",
    "CLOSE_AND_LONG", "CLOSE_AND_SHORT",
})

_RISK_REDUCE_TOKENS = frozenset({
    "CLOSE_LONG", "CLOSE_SHORT", "PARTIAL_CLOSE_LONG", "PARTIAL_CLOSE_SHORT",
    "DECREASE_LONG", "DECREASE_SHORT", "REDUCE_LONG", "REDUCE_SHORT",
    "EXIT_LONG", "EXIT_SHORT",
})


def is_risk_add(action: str) -> bool:
    """Return True if action ADDS risk (including hedge adds)."""
    a = str(action or "").upper().strip()
    if a in _RISK_ADD_TOKENS:
        return True
    if any(tok in a for tok in ("OPEN_", "ADD_", "INCREASE_")):
        return True
    if a.startswith("CLOSE_AND_"):
        return True  # flips are entry-type
    return False


def is_risk_reduce(action: str) -> bool:
    a = str(action or "").upper().strip()
    if a in _RISK_REDUCE_TOKENS:
        return True
    if any(tok in a for tok in ("CLOSE_", "REDUCE_", "DECREASE_", "PARTIAL_CLOSE", "EXIT_")):
        if not a.startswith("CLOSE_AND_"):
            return True
    return False


def is_hedge_action(action: str) -> bool:
    a = str(action or "").upper().strip()
    return "HEDGE" in a


# ─── core governor ─────────────────────────────────────────────────────

class MarginGovernor:
    """
    Stateless margin governor — call ``evaluate()`` on every risk-add attempt.

    Reads account state from Redis key ``wma:account_margin:{account_id}``
    and per-symbol margin from ``positions:live:{symbol}`` hashes.
    """

    def __init__(self, redis_client=None):
        self.redis = redis_client

    # ── dynamic protective cap ────────────────────────────────────────

    def _compute_dynamic_protective_cap(self, symbol: str, action: str) -> float:
        """
        Compute a data-driven protective symbol-margin cap instead of a static
        percentage.  The cap adapts based on:
          - Market regime (trending → wider cap, ranging → tighter)
          - Orderbook depth & imbalance
          - Volatility / ATR
          - Liquidation cluster distance
          - Feature alignment across TFs

        Returns a fraction (e.g. 0.12 = 12% of equity).
        """
        base_cap = float(_cfg("GOV_MAX_SYMBOL_MARGIN_PCT", 0.06))
        min_cap = base_cap
        max_cap = 0.25

        if not self.redis or not symbol:
            return max(min_cap, float(_cfg("GOV_MAX_SYMBOL_MARGIN_PCT_PROTECTIVE", 0.15)))

        score = 0.0
        signals = 0

        try:
            raw_regime = self.redis.get(f"regime:{symbol}")
            if raw_regime:
                _rv = raw_regime.decode("utf-8") if isinstance(raw_regime, (bytes, bytearray)) else str(raw_regime)
                _rd = json.loads(_rv) if isinstance(_rv, str) else {}
                if isinstance(_rd, dict):
                    move_regime = str(_rd.get("move_regime", "")).upper()
                    trend_dir = str(_rd.get("trend_direction", "")).upper()
                    vol_score = _safe_float(_rd.get("volatility_score"), 0.5)
                    tf_align = _safe_float(_rd.get("tf_alignment"), 0.0)
                    liq_risk = _safe_float(_rd.get("liq_risk"), 0.5)
                    liquidity = _safe_float(_rd.get("liquidity_score"), 0.5)

                    is_hedge_long = "LONG" in str(action or "").upper()
                    is_hedge_short = "SHORT" in str(action or "").upper()
                    trend_aligned = (
                        (is_hedge_long and trend_dir in ("LONG", "UP", "BULLISH"))
                        or (is_hedge_short and trend_dir in ("SHORT", "DOWN", "BEARISH"))
                    )

                    if move_regime in ("FAST", "IMPULSE", "TRENDING", "BREAKOUT"):
                        score += 0.8 if trend_aligned else 0.4
                    elif move_regime in ("RANGE", "NORMAL", "CALM"):
                        score += 0.3
                    else:
                        score += 0.2
                    signals += 1

                    if tf_align > 0.6:
                        score += 0.3
                    elif tf_align > 0.3:
                        score += 0.15
                    signals += 1

                    # High vol = MORE reason to hedge (protective)
                    if vol_score < 0.7:
                        score += 0.15
                    else:
                        score += 0.25  # High vol bonus: hedging is protective
                    signals += 1

                    if liq_risk < 0.4:
                        score += 0.2
                    signals += 1

                    if liquidity > 0.5:
                        score += 0.2
                    signals += 1
        except Exception:
            pass

        try:
            for tf in ("15m", "5m", "1h"):
                raw = self.redis.hgetall(f"unified_features:{symbol}:{tf}")
                if not raw:
                    continue
                feat = {}
                for k, v in raw.items():
                    _k = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)
                    _v = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
                    feat[_k] = _v

                adx = None
                for fk in ("adx_14", "adx", "ind_ta_ADX_14"):
                    if fk in feat:
                        try:
                            adx = float(feat[fk])
                            break
                        except Exception:
                            pass
                if adx is not None:
                    if adx > 30:
                        score += 0.3
                    elif adx > 20:
                        score += 0.15
                    signals += 1

                atr_pct = None
                for fk in ("atr_pct", "atr_14", "ind_ta_ATR_14"):
                    if fk in feat:
                        try:
                            atr_pct = float(feat[fk])
                            break
                        except Exception:
                            pass
                if atr_pct is not None and atr_pct > 0:
                    # All ATR levels get score — high ATR means more reason to hedge
                    if atr_pct < 3.0:
                        score += 0.15
                    elif atr_pct < 6.0:
                        score += 0.15  # Same as low — vol is not a penalty
                    else:
                        score += 0.20  # High ATR = strong case for hedging
                    signals += 1

                liq_dist = None
                for fk in ("liquidation_distance_pct", "liquidation_long_distance_pct", "liquidation_short_distance_pct"):
                    if fk in feat:
                        try:
                            liq_dist = abs(float(feat[fk]))
                            break
                        except Exception:
                            pass
                if liq_dist is not None and liq_dist > 5.0:
                    score += 0.2
                    signals += 1

                break
        except Exception:
            pass

        try:
            ob_raw = self.redis.get(f"orderbook:depth:{symbol}")
            if ob_raw:
                _ob = ob_raw.decode("utf-8") if isinstance(ob_raw, (bytes, bytearray)) else str(ob_raw)
                _obd = json.loads(_ob) if isinstance(_ob, str) else {}
                if isinstance(_obd, dict):
                    bid_depth = _safe_float(_obd.get("bid_depth_usd") or _obd.get("bid_total"), 0)
                    ask_depth = _safe_float(_obd.get("ask_depth_usd") or _obd.get("ask_total"), 0)
                    total_depth = bid_depth + ask_depth
                    if total_depth > 100000:
                        score += 0.2
                    elif total_depth > 50000:
                        score += 0.1
                    signals += 1
        except Exception:
            pass

        if signals == 0:
            return max(min_cap, float(_cfg("GOV_MAX_SYMBOL_MARGIN_PCT_PROTECTIVE", 0.15)))

        dynamic_cap = min_cap + (max_cap - min_cap) * min(1.0, score / 2.0)
        result = max(min_cap, min(max_cap, dynamic_cap))
        return result

    # ── public API ────────────────────────────────────────────────────

    def evaluate(
        self,
        account_id: str,
        symbol: str,
        action: str,
        proposed_margin_usd: float = 0.0,
        *,
        # Caller can pass pre-fetched data to avoid extra Redis reads
        equity: Optional[float] = None,
        total_initial_margin: Optional[float] = None,
        margin_balance: Optional[float] = None,
        symbol_margin_usd: Optional[float] = None,
        margin_ratio_pct: Optional[float] = None,
        margin_used_pct: Optional[float] = None,
        source: str = "",
        is_protective: bool = False,
    ) -> GovernorVerdict:
        """
        Evaluate whether the proposed action should be allowed.

        Returns GovernorVerdict with action=ALLOW/BLOCK/DELEVERAGE.
        """
        enabled = bool(_cfg("MARGIN_GOVERNOR_ENABLED", True))
        if not enabled:
            return GovernorVerdict(GovernorVerdict.ALLOW)

        action_upper = str(action or "").upper().strip()

        # Reduces always pass — they are risk-reducing
        if is_risk_reduce(action_upper):
            return GovernorVerdict(GovernorVerdict.ALLOW)

        # HOLDs always pass
        if action_upper in ("HOLD", "NONE", "WAIT", "HEARTBEAT", "NOOP"):
            return GovernorVerdict(GovernorVerdict.ALLOW)

        # Only gate risk-adds
        if not is_risk_add(action_upper):
            return GovernorVerdict(GovernorVerdict.ALLOW)

        # ── Fetch account state ──────────────────────────────────────
        acct_state = self._get_account_state(
            account_id,
            equity_override=equity,
            total_im_override=total_initial_margin,
            mb_override=margin_balance,
            mr_override=margin_ratio_pct,
            mu_override=margin_used_pct,
        )

        eq = acct_state["equity"]
        total_im = acct_state["total_initial_margin"]
        mu_pct = acct_state["margin_used_pct"]
        mr_pct = acct_state["margin_ratio_pct"]

        # If no equity data at all, fail-open (can't evaluate)
        if eq <= 0.0:
            logger.debug(
                "MARGIN_GOVERNOR_SKIP | account=%s | reason=no_equity_data",
                account_id,
            )
            return GovernorVerdict(GovernorVerdict.ALLOW, meta={"reason": "no_equity_data"})

        # ── Fetch per-symbol margin ──────────────────────────────────
        sym_margin = symbol_margin_usd
        if sym_margin is None:
            sym_margin = self._get_symbol_margin(account_id, symbol)

        # ── I1: Account-level margin cap ─────────────────────────────
        max_account_pct = float(_cfg("GOV_MAX_ACCOUNT_MARGIN_PCT", 0.55))

        # Fix N (Feb 2026): Protective hedges get elevated ACCOUNT cap.
        # A hedge leg opposes an existing directional leg, REDUCING net risk.
        # Blocking hedges at the same cap as speculative entries leaves the
        # account exposed to unhedged downside — contrary to hedge-first.
        if is_protective:
            protective_acct_cap = float(_cfg("GOV_MAX_ACCOUNT_MARGIN_PCT_PROTECTIVE", 0.60))
            effective_account_cap = max(max_account_pct, protective_acct_cap)
        else:
            effective_account_cap = max_account_pct

        # For hedge legs, compute NET additional margin.
        # A LONG hedge against a SHORT (or vice versa) reduces net exposure.
        # Net add = max(0, proposed - opposite_leg_margin_for_this_symbol).
        effective_proposed = proposed_margin_usd
        if is_protective and sym_margin > 0:
            # Hedge offsets existing leg → net addition is much smaller
            effective_proposed = max(0.0, proposed_margin_usd - sym_margin * 0.5)
            if effective_proposed != proposed_margin_usd:
                logger.info(
                    "MARGIN_GOVERNOR_HEDGE_NET | symbol=%s | gross=$%.2f | "
                    "net=$%.2f | existing_sym_margin=$%.2f",
                    symbol, proposed_margin_usd, effective_proposed, sym_margin,
                )

        current_account_pct = total_im / eq if eq > 0 else 0.0
        projected_account_pct = (total_im + effective_proposed) / eq if eq > 0 else 0.0

        # Also check via MU from Binance (more reliable real-time)
        mu_threshold = float(_cfg("GOV_MAX_ACCOUNT_MU_PCT", 50.0))
        mu_breach = mu_pct > mu_threshold if mu_pct > 0 else False

        i1_breach_current = current_account_pct > effective_account_cap
        i1_breach_projected = projected_account_pct > effective_account_cap

        # ── I2: Symbol-level margin cap ──────────────────────────────
        max_symbol_pct = float(_cfg("GOV_MAX_SYMBOL_MARGIN_PCT", 0.06))

        # Fix M (Feb 2026): Protective hedges get a higher symbol cap.
        # Hedges are risk-REDUCING (they offset an existing directional leg).
        # Blocking protective hedges at the same cap as speculative entries
        # leaves the account exposed to unhedged downside — contrary to the
        # hedge-first contract.
        if is_protective:
            protective_symbol_cap = self._compute_dynamic_protective_cap(symbol, action)
            effective_symbol_cap = max(max_symbol_pct, protective_symbol_cap)
        else:
            effective_symbol_cap = max_symbol_pct

        current_symbol_pct = sym_margin / eq if (eq > 0 and sym_margin > 0) else 0.0
        # Use net-exposure-aware proposed for symbol too
        projected_symbol_pct = (sym_margin + effective_proposed) / eq if eq > 0 else 0.0

        i2_breach_current = current_symbol_pct > effective_symbol_cap
        i2_breach_projected = projected_symbol_pct > effective_symbol_cap


        # ── I3: Protective hedges: elevated caps + net margin (Fix M+N) ──

        # ── I4: Determine verdict ────────────────────────────────────
        meta = {
            "equity": round(eq, 2),
            "total_initial_margin": round(total_im, 2),
            "margin_used_pct": round(mu_pct, 2),
            "margin_ratio_pct": round(mr_pct, 2),
            "current_account_pct": round(current_account_pct * 100, 2),
            "projected_account_pct": round(projected_account_pct * 100, 2),
            "max_account_pct": round(effective_account_cap * 100, 2),
            "symbol": symbol,
            "symbol_margin_usd": round(sym_margin, 2),
            "current_symbol_pct": round(current_symbol_pct * 100, 2),
            "projected_symbol_pct": round(projected_symbol_pct * 100, 2),
            "max_symbol_pct": round(effective_symbol_cap * 100, 2),
            "proposed_margin_usd": round(proposed_margin_usd, 2),
            "effective_proposed_usd": round(effective_proposed, 2),
            "is_protective": is_protective,
            "source": source,
            "mu_breach": mu_breach,
            "mu_threshold_pct": mu_threshold,
        }

        # Current breach → DELEVERAGE mode (system should be reducing, not adding)
        if i1_breach_current or mu_breach:
            code = "GOV_ACCOUNT_MARGIN_DELEVERAGE"
            reason = (
                f"Account margin already at {current_account_pct*100:.1f}% "
                f"(cap={effective_account_cap*100:.0f}%) "
                f"MU={mu_pct:.1f}% (cap={mu_threshold:.0f}%)"
            )
            logger.warning(
                "MARGIN_GOVERNOR_%s | account=%s | symbol=%s | action=%s | "
                "account_margin=%.1f%% | MU=%.1f%% | cap=%.0f%%/%.0f%% | "
                "proposed_margin=$%.2f | source=%s | is_protective=%s",
                "DELEVERAGE", account_id, symbol, action_upper,
                current_account_pct * 100, mu_pct, effective_account_cap * 100,
                mu_threshold, proposed_margin_usd, source, is_protective,
            )

            # Enrich meta with market context for downstream consumers
            try:
                if self.redis and symbol:
                    raw_regime = self.redis.get(f"regime:{symbol}")
                    if raw_regime:
                        _rv = raw_regime.decode("utf-8") if isinstance(raw_regime, (bytes, bytearray)) else str(raw_regime)
                        _rd = json.loads(_rv)
                        meta["market_regime"] = str(_rd.get("move_regime", "UNKNOWN"))
                        meta["trend_direction"] = str(_rd.get("trend_direction", "NEUTRAL"))
                        meta["tf_alignment"] = float(_rd.get("tf_alignment", 0.0))
            except Exception:
                pass

            # ── Phase 4: ICG market-aware deferral ───────────────────
            # If positions are in favorable trends and margin isn't in
            # HARD EMERGENCY territory, downgrade to BLOCK instead of DELEVERAGE.
            _is_hard_emergency = mu_pct >= 85.0 or current_account_pct >= 0.85
            if not _is_hard_emergency and symbol:
                try:
                    from risk.intelligent_close_guard import evaluate_close as _gov_icg_eval
                    _gov_icg = _gov_icg_eval(
                        self.redis, symbol, "LONG",
                        close_reason=f"GOV_DELEVERAGE MU={mu_pct:.1f}%",
                        is_hard_emergency=False,
                    )
                    if _gov_icg.should_defer:
                        logger.info(
                            "MARGIN_GOVERNOR_ICG_DEFER | sym=%s | hold_score=%.3f | "
                            "MU=%.1f%% | downgrade DELEVERAGE → BLOCK (positions in favorable trend)",
                            symbol, _gov_icg.hold_score, mu_pct,
                        )
                        meta["icg_hold_score"] = round(_gov_icg.hold_score, 3)
                        meta["icg_deferred"] = True
                        return GovernorVerdict(
                            GovernorVerdict.BLOCK,
                            code="GOV_ACCOUNT_MARGIN_BLOCK_ICG_DEFERRED",
                            reason=f"{reason} | ICG deferred (hold={_gov_icg.hold_score:.3f})",
                            meta=meta,
                        )
                except Exception as _gov_icg_err:
                    logger.debug("GOV_ICG_ERR | %s | %s", symbol, _gov_icg_err)

            # Determine conversion: if it's a hedge add, suggest partial close of worst leg
            suggested = ""
            if is_hedge_action(action_upper):
                suggested = self._suggest_deleverage_action(account_id, symbol, action_upper)

            return GovernorVerdict(
                GovernorVerdict.DELEVERAGE,
                code=code,
                reason=reason,
                meta=meta,
                suggested_action=suggested,
            )

        # Projected breach → BLOCK (can't add more)
        if i1_breach_projected:
            code = "GOV_ACCOUNT_MARGIN_BLOCK"
            reason = (
                f"Projected account margin {projected_account_pct*100:.1f}% "
                f"would exceed cap {effective_account_cap*100:.0f}%"
            )
            logger.warning(
                "MARGIN_GOVERNOR_BLOCK | account=%s | symbol=%s | action=%s | "
                "projected=%.1f%% | cap=%.0f%% | proposed=$%.2f (net=$%.2f) | source=%s | protective=%s",
                account_id, symbol, action_upper,
                projected_account_pct * 100, effective_account_cap * 100,
                proposed_margin_usd, effective_proposed, source, is_protective,
            )
            return GovernorVerdict(
                GovernorVerdict.BLOCK,
                code=code,
                reason=reason,
                meta=meta,
            )

        # I2: Symbol-level breach (current)
        if i2_breach_current:
            # Protective hedges REDUCE directional risk. The existing margin is
            # already committed; blocking the hedge leaves the position fully
            # exposed.  Allow the hedge if net addition is small.
            if is_protective and effective_proposed <= proposed_margin_usd * 0.25:
                logger.info(
                    "MARGIN_GOVERNOR_I2_PROTECTIVE_BYPASS | sym=%s | action=%s | "
                    "sym_pct=%.1f%% | cap=%.0f%% | net_add=$%.2f | proposed=$%.2f",
                    symbol, action_upper, current_symbol_pct * 100,
                    effective_symbol_cap * 100, effective_proposed, proposed_margin_usd,
                )
            else:
                code = "GOV_SYMBOL_MARGIN_DELEVERAGE"
                reason = (
                    f"Symbol {symbol} margin at {current_symbol_pct*100:.1f}% "
                    f"of equity (cap={max_symbol_pct*100:.0f}%)"
                )
                logger.warning(
                    "MARGIN_GOVERNOR_DELEVERAGE | account=%s | symbol=%s | action=%s | "
                    "sym_margin=%.1f%% | cap=%.0f%% | proposed=$%.2f | source=%s",
                    account_id, symbol, action_upper,
                    current_symbol_pct * 100, max_symbol_pct * 100,
                    proposed_margin_usd, source,
                )

                # ── Phase 4: ICG deferral for symbol-level breach ────────
                _icg_side = "SHORT" if "SHORT" in action_upper else "LONG"
                _sym_hard = mu_pct >= 85.0 or current_account_pct >= 0.85
                if not _sym_hard and symbol:
                    try:
                        from risk.intelligent_close_guard import evaluate_close as _sym_icg_eval
                        _sym_icg = _sym_icg_eval(
                            self.redis, symbol, _icg_side,
                            close_reason=f"GOV_SYMBOL_DELEVERAGE sym_pct={current_symbol_pct*100:.1f}%",
                            is_hard_emergency=False,
                        )
                        if _sym_icg.should_defer:
                            logger.info(
                                "MARGIN_GOVERNOR_SYM_ICG_DEFER | sym=%s | hold_score=%.3f | "
                                "sym_pct=%.1f%% | downgrade DELEVERAGE → BLOCK",
                                symbol, _sym_icg.hold_score, current_symbol_pct * 100,
                            )
                            meta["icg_hold_score"] = round(_sym_icg.hold_score, 3)
                            meta["icg_deferred"] = True
                            return GovernorVerdict(
                                GovernorVerdict.BLOCK,
                                code="GOV_SYMBOL_MARGIN_BLOCK_ICG_DEFERRED",
                                reason=f"{reason} | ICG deferred (hold={_sym_icg.hold_score:.3f})",
                                meta=meta,
                            )
                    except Exception as _sym_icg_err:
                        logger.debug("GOV_SYM_ICG_ERR | %s | %s", symbol, _sym_icg_err)

                suggested = self._suggest_deleverage_action(account_id, symbol, action_upper)
                return GovernorVerdict(
                    GovernorVerdict.DELEVERAGE,
                    code=code,
                    reason=reason,
                    meta=meta,
                    suggested_action=suggested,
                )

        # I2: Symbol-level breach (projected)
        if i2_breach_projected:
            if is_protective and effective_proposed <= proposed_margin_usd * 0.25:
                logger.info(
                    "MARGIN_GOVERNOR_I2_PROJ_PROTECTIVE_BYPASS | sym=%s | action=%s | "
                    "proj_pct=%.1f%% | cap=%.0f%% | net_add=$%.2f",
                    symbol, action_upper, projected_symbol_pct * 100,
                    effective_symbol_cap * 100, effective_proposed,
                )
            else:
                code = "GOV_SYMBOL_MARGIN_BLOCK"
                reason = (
                    f"Symbol {symbol} projected margin {projected_symbol_pct*100:.1f}% "
                    f"would exceed cap {max_symbol_pct*100:.0f}%"
                )
                logger.warning(
                    "MARGIN_GOVERNOR_BLOCK | account=%s | symbol=%s | action=%s | "
                    "projected_sym=%.1f%% | cap=%.0f%% | proposed=$%.2f | source=%s",
                    account_id, symbol, action_upper,
                    projected_symbol_pct * 100, max_symbol_pct * 100,
                    proposed_margin_usd, source,
                )
                return GovernorVerdict(
                    GovernorVerdict.BLOCK,
                    code=code,
                    reason=reason,
                    meta=meta,
                )

        # All clear
        return GovernorVerdict(GovernorVerdict.ALLOW, meta=meta)

    # ── private: account state ────────────────────────────────────────

    def _get_account_state(
        self,
        account_id: str,
        *,
        equity_override: Optional[float] = None,
        total_im_override: Optional[float] = None,
        mb_override: Optional[float] = None,
        mr_override: Optional[float] = None,
        mu_override: Optional[float] = None,
    ) -> Dict[str, float]:
        """Fetch equity, initial margin, MU, MR from Redis or overrides."""
        state = {
            "equity": _safe_float(equity_override),
            "total_initial_margin": _safe_float(total_im_override),
            "margin_balance": _safe_float(mb_override),
            "margin_ratio_pct": _safe_float(mr_override),
            "margin_used_pct": _safe_float(mu_override),
        }

        # Try Redis snapshot from trader: wma:account_margin:{account_id}
        if self.redis:
            try:
                raw = self.redis.get(f"wma:account_margin:{account_id}")
                if raw:
                    snap_str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    snap = json.loads(snap_str)
                    if state["margin_ratio_pct"] <= 0:
                        state["margin_ratio_pct"] = _safe_float(snap.get("margin_ratio_pct"))
                    if state["margin_used_pct"] <= 0:
                        state["margin_used_pct"] = _safe_float(snap.get("margin_used_pct"))
                    if state["margin_balance"] <= 0:
                        state["margin_balance"] = _safe_float(snap.get("margin_balance"))
                    if state["equity"] <= 0:
                        state["equity"] = _safe_float(snap.get("margin_balance"))
                    # Derive total_initial_margin from MU + equity
                    if state["total_initial_margin"] <= 0 and state["margin_used_pct"] > 0 and state["equity"] > 0:
                        state["total_initial_margin"] = state["equity"] * (state["margin_used_pct"] / 100.0)
            except Exception as e:
                logger.debug("MARGIN_GOVERNOR_REDIS_ERR | key=wma:account_margin:%s | err=%s", account_id, e)

        # Try portfolio:equity:{account_id} as secondary source
        if self.redis and state["equity"] <= 0:
            try:
                raw = self.redis.get(f"portfolio:equity:{account_id}")
                if raw:
                    snap_str = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    eq_snap = json.loads(snap_str)
                    state["equity"] = _safe_float(
                        eq_snap.get("equity_usd")
                        or eq_snap.get("margin_balance_usd")
                        or eq_snap.get("wallet_balance_usd")
                    )
                    if state["total_initial_margin"] <= 0:
                        state["total_initial_margin"] = _safe_float(eq_snap.get("used_margin_usd") or eq_snap.get("initial_margin_usd"))
                    if state["margin_used_pct"] <= 0:
                        mu_raw = _safe_float(eq_snap.get("margin_util") or eq_snap.get("margin_utilization"))
                        if mu_raw > 0:
                            state["margin_used_pct"] = mu_raw * 100.0 if mu_raw < 1.0 else mu_raw
            except Exception as e:
                logger.debug("MARGIN_GOVERNOR_REDIS_ERR | key=portfolio:equity:%s | err=%s", account_id, e)

        return state

    # ── private: per-symbol margin ────────────────────────────────────

    def _get_symbol_margin(self, account_id: str, symbol: str) -> float:
        """Sum both LONG and SHORT legs' initial margin for a symbol."""
        if not self.redis or not symbol:
            return 0.0

        total = 0.0

        # Try positions:live:{symbol} (has "long" and "short" JSON sub-objects)
        try:
            raw = self.redis.hgetall(f"positions:live:{symbol}")
            if raw:
                for field_key in (b"long", b"short", "long", "short"):
                    val = raw.get(field_key)
                    if not val:
                        continue
                    val_str = val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else str(val)
                    try:
                        leg = json.loads(val_str)
                        im = _safe_float(leg.get("initialMargin") or leg.get("margin_used"))
                        if im > 0:
                            total += im
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("MARGIN_GOVERNOR_SYMBOL_ERR | symbol=%s | err=%s", symbol, e)

        # Fallback: positions:live:{account_id}:{symbol}
        if total <= 0:
            try:
                raw = self.redis.hgetall(f"positions:live:{account_id}:{symbol}")
                if raw:
                    def _d(v):
                        return v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)
                    im = _safe_float(_d(raw.get(b"initial_margin_usd") or raw.get("initial_margin_usd") or b"0"))
                    if im > 0:
                        total = im
            except Exception:
                pass

        return total

    # ── private: suggest deleverage action ────────────────────────────

    def _suggest_deleverage_action(self, account_id: str, symbol: str, original_action: str) -> str:
        """
        When DELEVERAGE verdict, suggest what action to convert to.

        Strategy:
        - For hedge adds: convert to partial close of the LARGER leg
          (harvests PnL or reduces exposure)
        - For regular opens: suggest nothing (just block)
        """
        if not is_hedge_action(original_action):
            return ""

        if not self.redis:
            return ""

        try:
            raw = self.redis.hgetall(f"positions:live:{symbol}")
            if not raw:
                return ""

            long_margin = 0.0
            short_margin = 0.0
            for field_key in (b"long", "long"):
                val = raw.get(field_key)
                if val:
                    val_str = val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else str(val)
                    leg = json.loads(val_str)
                    long_margin = _safe_float(leg.get("initialMargin") or leg.get("margin_used"))
                    break
            for field_key in (b"short", "short"):
                val = raw.get(field_key)
                if val:
                    val_str = val.decode("utf-8") if isinstance(val, (bytes, bytearray)) else str(val)
                    leg = json.loads(val_str)
                    short_margin = _safe_float(leg.get("initialMargin") or leg.get("margin_used"))
                    break

            # Suggest closing the larger leg partially
            if long_margin > short_margin and long_margin > 0:
                return "PARTIAL_CLOSE_LONG"
            elif short_margin > 0:
                return "PARTIAL_CLOSE_SHORT"
        except Exception:
            pass

        return ""

    # ── convenience: check multiple symbols ──────────────────────────

    def check_portfolio_deleverage_needed(self, account_id: str) -> Optional[GovernorVerdict]:
        """
        Check if the account needs immediate deleveraging (periodic enforcer).

        Returns DELEVERAGE verdict if account exceeds caps, None if OK.
        """
        enabled = bool(_cfg("MARGIN_GOVERNOR_ENABLED", True))
        if not enabled:
            return None

        state = self._get_account_state(account_id)
        eq = state["equity"]
        total_im = state["total_initial_margin"]
        mu_pct = state["margin_used_pct"]

        if eq <= 0:
            return None

        max_account_pct = float(_cfg("GOV_MAX_ACCOUNT_MARGIN_PCT", 0.55))
        mu_threshold = float(_cfg("GOV_MAX_ACCOUNT_MU_PCT", 50.0))

        current_pct = total_im / eq if eq > 0 else 0.0
        mu_breach = mu_pct > mu_threshold if mu_pct > 0 else False

        if current_pct > max_account_pct or mu_breach:
            # Find worst offender symbol
            worst_symbol = ""
            worst_margin = 0.0

            if self.redis:
                try:
                    sym_set = self.redis.smembers(f"positions:live:symbols:{account_id}")
                    if sym_set:
                        for sym_raw in sym_set:
                            sym = sym_raw.decode("utf-8") if isinstance(sym_raw, (bytes, bytearray)) else str(sym_raw)
                            sm = self._get_symbol_margin(account_id, sym)
                            if sm > worst_margin:
                                worst_margin = sm
                                worst_symbol = sym
                except Exception:
                    pass

            return GovernorVerdict(
                GovernorVerdict.DELEVERAGE,
                code="GOV_PORTFOLIO_DELEVERAGE_NEEDED",
                reason=(
                    f"Account margin {current_pct*100:.1f}% (cap={max_account_pct*100:.0f}%) "
                    f"MU={mu_pct:.1f}% (cap={mu_threshold:.0f}%)"
                ),
                meta={
                    "equity": round(eq, 2),
                    "total_initial_margin": round(total_im, 2),
                    "current_pct": round(current_pct * 100, 2),
                    "mu_pct": round(mu_pct, 2),
                    "worst_symbol": worst_symbol,
                    "worst_margin_usd": round(worst_margin, 2),
                },
            )

        return None
