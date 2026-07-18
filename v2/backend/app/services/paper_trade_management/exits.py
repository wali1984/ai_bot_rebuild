from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Mapping

from .accounting import coerce_float
from .position_state import PaperNetPosition, seconds_between


PAPER_EXIT_POLICY_VERSION = "PAPER_EXIT_AFTER_COST_TRAILING_FLOOR_V1"


def _env_float(name: str, default: float) -> float:
    """Read a float from the environment, falling back to ``default``.

    Used so an operator can activate an otherwise-disabled risk parameter via a
    systemd drop-in without a code change; malformed/empty values fall back to
    the safe default rather than raising.
    """
    try:
        raw = os.getenv(name)
        return float(raw) if raw is not None and raw != "" else float(default)
    except (TypeError, ValueError):
        return float(default)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _current_liquidation_distance_bps(
    position: PaperNetPosition,
    *,
    mark_price: float,
) -> float | None:
    """Return side-aware current mark distance to the canonical liq estimate.

    ``liquidation_buffer_bps`` is entry-relative and therefore cannot drive a
    current emergency exit.  A crossed or side-inconsistent estimate maps to
    zero distance so the protective tier fails closed.
    """
    mark = coerce_float(mark_price)
    liquidation_price = coerce_float(position.liquidation_price_estimate)
    if (
        mark is None
        or liquidation_price is None
        or not math.isfinite(mark)
        or not math.isfinite(liquidation_price)
        or mark <= 0.0
        or liquidation_price < 0.0
    ):
        return None
    if position.side == "long":
        distance = mark - liquidation_price
    elif position.side == "short":
        distance = liquidation_price - mark
    else:
        return None
    return max(0.0, distance / mark * 10000.0)


def _context_value(context: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        current: Any = context
        for part in key.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        if current is not None and current != "":
            return current
    return None


def _advanced_exit_context(
    position: PaperNetPosition,
    *,
    alpha_context: dict[str, Any] | None,
    model_context: dict[str, Any] | None,
) -> dict[str, Any]:
    sources = [
        alpha_context or {},
        (alpha_context or {}).get("advanced_indicator_context") or {},
        model_context or {},
        (model_context or {}).get("advanced_indicator_context") or {},
        position.liquidity_zone_context or {},
        position.microstructure_context or {},
    ]
    context: dict[str, Any] = {}
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for key in (
            "fvg_invalidated",
            "fvg_kind",
            "distance_to_fvg_bps",
            "session_vwap",
            "distance_to_vwap_bps",
            "vwap_slope",
            "cvd_slope",
            "choch_direction",
            "structure_invalidation",
            "session_high_sweep",
            "session_low_sweep",
            "fake_breakout_risk",
            "fake_breakdown_risk",
            "sweep_risk_long_side",
            "sweep_risk_short_side",
            "post_sweep_reversal_probability",
            "nearest_liquidity_above",
            "nearest_liquidity_below",
        ):
            value = _context_value(source, key)
            if value is not None and value != "":
                context.setdefault(key, value)
    side = str(position.side or "").lower()
    nearest_target = (
        _first_present(context.get("nearest_liquidity_above"), context.get("session_vwap"))
        if side == "long"
        else _first_present(context.get("nearest_liquidity_below"), context.get("session_vwap"))
    )
    return {
        **context,
        "advanced_indicator_exit_policy_version": "ADVANCED_MARKET_STRUCTURE_EXIT_V1",
        "nearest_liquidity_target": nearest_target,
        "paper_only": True,
        "places_real_order": False,
    }


def _advanced_exit_signal(position: PaperNetPosition, context: dict[str, Any]) -> dict[str, Any] | None:
    side = str(position.side or "").lower()
    choch = str(_first_present(context.get("choch_direction"), context.get("structure_invalidation")) or "").lower()
    fvg_kind = str(context.get("fvg_kind") or "").lower()
    distance_to_vwap = coerce_float(context.get("distance_to_vwap_bps"))
    cvd_slope = coerce_float(context.get("cvd_slope"))
    post_sweep_reversal = coerce_float(context.get("post_sweep_reversal_probability"))
    fake_breakout = coerce_float(_first_present(context.get("fake_breakout_risk"), context.get("sweep_risk_long_side")))
    fake_breakdown = coerce_float(_first_present(context.get("fake_breakdown_risk"), context.get("sweep_risk_short_side")))

    def _result(reason: str, tier: int = 1) -> dict[str, Any]:
        return {
            "should_close": True,
            "close_reason": reason,
            "tier": tier,
            "advanced_indicator_exit": True,
            "advanced_indicator_exit_context": context,
        }

    if context.get("fvg_invalidated") is True:
        if not fvg_kind or (side == "long" and fvg_kind == "bullish") or (side == "short" and fvg_kind == "bearish"):
            return _result("TIER_1_FVG_INVALIDATION_EXIT")
    if side == "long" and choch in {"down", "bear", "bearish", "short"}:
        return _result("TIER_1_STRUCTURE_INVALIDATION_EXIT")
    if side == "short" and choch in {"up", "bull", "bullish", "long"}:
        return _result("TIER_1_STRUCTURE_INVALIDATION_EXIT")
    if side == "long" and distance_to_vwap is not None and distance_to_vwap < 0 and cvd_slope is not None and cvd_slope < 0:
        return _result("TIER_1_VWAP_CVD_INVALIDATION_EXIT")
    if side == "short" and distance_to_vwap is not None and distance_to_vwap > 0 and cvd_slope is not None and cvd_slope > 0:
        return _result("TIER_1_VWAP_CVD_INVALIDATION_EXIT")
    if side == "long" and (context.get("session_high_sweep") is True or (fake_breakout or 0.0) >= 0.75) and (post_sweep_reversal or 0.0) >= 0.60:
        return _result("TIER_1_LIQUIDITY_SWEEP_REVERSAL_EXIT")
    if side == "short" and (context.get("session_low_sweep") is True or (fake_breakdown or 0.0) >= 0.75) and (post_sweep_reversal or 0.0) >= 0.60:
        return _result("TIER_1_LIQUIDITY_SWEEP_REVERSAL_EXIT")
    return None


def _trailing_stop_price_context(
    *,
    side: str,
    entry_price: float,
    mark_price: float,
    stop_price: float,
    exit_floor_bps: float,
) -> dict[str, Any]:
    if side == "short":
        paper_exit_pnl_bps = ((entry_price - stop_price) / entry_price) * 10000.0
        trailing_stop_gap_bps = max(0.0, ((mark_price - stop_price) / stop_price) * 10000.0)
    else:
        paper_exit_pnl_bps = ((stop_price - entry_price) / entry_price) * 10000.0
        trailing_stop_gap_bps = max(0.0, ((stop_price - mark_price) / stop_price) * 10000.0)
    trailing_stop_exit_floor_bps = max(0.0, float(exit_floor_bps))
    return {
        "paper_exit_price": stop_price,
        "paper_exit_price_source": "PAPER_TRAILING_STOP_PRICE",
        "paper_exit_pnl_bps": paper_exit_pnl_bps,
        "trailing_stop_exit_floor_bps": trailing_stop_exit_floor_bps,
        "trailing_stop_exit_floor_gap_bps": max(
            0.0,
            trailing_stop_exit_floor_bps - paper_exit_pnl_bps,
        ),
        "trailing_stop_mark_price": mark_price,
        "trailing_stop_gap_bps": trailing_stop_gap_bps,
    }


@dataclass(frozen=True)
class PaperExitConfig:
    stop_loss_bps: float = 80.0
    take_profit_bps: float = 120.0
    trailing_stop_bps: float = 50.0
    min_hold_seconds: int = 0
    max_hold_seconds: int = 6 * 60 * 60
    emergency_liquidation_distance_bps: float = 250.0
    dynamic_take_profit_bps: float = 90.0
    profit_lock_bps: float = 70.0
    # Profit-lock is intentionally tighter than the adaptive trail, so once a
    # trail is armed this keeps profit-lock from starving trailing-stop samples.
    defer_profit_lock_to_active_trailing_stop: bool = True
    # Take-profit is also static, so defer it only when a prior cycle already
    # armed the adaptive trail. Same-cycle TP closes remain eligible.
    defer_take_profit_to_active_trailing_stop: bool = True
    profit_bank_bps: float = 180.0
    # Profit-bank is a high-profit static tier. Defer it only after a prior
    # cycle armed the trail, so the active trail can produce outcome samples.
    defer_profit_bank_to_active_trailing_stop: bool = True
    confidence_decay_min: float = 0.42
    microstructure_reversal_score: float = 0.75
    drawdown_emergency_bps: float = 350.0
    # Trailing stop only fires when current net PnL exceeds this minimum.
    # Prevents trailing stop from converting a position that briefly moved in
    # favour then reversed into a fee-absorbed realized loss.
    # Set to the expected round-trip cost (fee + slippage) as the floor.
    min_profit_before_trailing_bps: float = 30.0
    # Additional after-cost buffer layered on top of the gross profit floor.
    # The effective trailing floor also incorporates observed spread when it is
    # higher, so trailing exits must clear modeled execution drag before firing.
    trailing_stop_min_after_cost_buffer_bps: float = 12.0
    trailing_stop_enabled: bool = True
    # HedgeLock: instead of closing on trailing stop, return a HEDGE_LOCK_TRIGGER
    # signal so the caller can open a counter-position. Requires operator approval
    # (allow_explicit_hedge=True in PaperLifecycleConfig). Default off.
    hedge_lock_enabled: bool = False
    # Minimum profitable excursion (bps) required before a hedge lock can trigger.
    # Position must have been in profit by at least this much before reversing.
    hedge_lock_min_excursion_bps: float = 25.0
    # Phase 7: volatility-adjusted stop using ATR-multiple.
    # When atr_bps > 0 in evaluate_exit(), the stop fires at atr_bps * atr_stop_multiplier.
    # Overrides stop_loss_bps when the ATR-derived stop is tighter.
    atr_stop_multiplier: float = 2.0
    # R29-D4: Wider ATR stop for trend_mode entries. TIER_3_MODEL_REVERSAL_NETTING
    # has WR=58% on trend SHORT vs TIER_1_ATR_VOLATILITY_STOP WR=0% (148 trades).
    # Widening from 2.0x to 3.0x gives the model reversal signal more runway to fire
    # before ATR stop cuts the trade. In cascade markets (post-R29-D2 regime gate),
    # adverse moves on trend SHORT are more likely to be noise before continuation.
    # None = use atr_stop_multiplier (backward compatible).
    atr_stop_multiplier_trend_mode: float | None = 3.0
    # ATR-scaled trailing distance. The effective trailing distance is the
    # wider of trailing_stop_bps and atr_bps * atr_trailing_stop_multiplier.
    atr_trailing_stop_multiplier: float = 1.5
    # A+ goal Phase 7: MFE breakeven protection. A position whose favorable
    # excursion reached mfe_breakeven_atr_multiple x ATR (or the bps floor when
    # ATR is unavailable) must not round-trip into a full ATR-stop loss. Once
    # armed, retracement back to the cost buffer closes at ~breakeven. This
    # covers the unprotected MFE band below the adaptive-trailing profit floor
    # (observed ATR-stop cluster: MFE 25-30bps, trail floor ~42bps, ATR stop
    # fired at -20 to -27bps).
    mfe_breakeven_protection_enabled: bool = True
    mfe_breakeven_atr_multiple: float = 2.0
    mfe_breakeven_min_mfe_bps: float = 20.0
    mfe_breakeven_cost_buffer_bps: float = 8.0
    # A+ goal Phase 7: regime-aware ATR stop scaling applied on top of the
    # strategy-mode multiplier. VOLATILE_EXPANSION widens the stop so noise
    # does not cluster ATR losses; RANGING tightens it because adverse moves
    # in a range are less likely to be noise before continuation.
    # Runtime regime strings are comma-joined token lists (e.g.
    # "HIGH_VOLATILITY,NO_TRADE,RISK_OFF"), so the lookup tokenizes and takes
    # the max scale across matched tokens; the map must therefore use the
    # taxonomy the runtime actually emits alongside the legacy keys.
    atr_stop_regime_scale: Mapping[str, float] = field(
        default_factory=lambda: {
            "VOLATILE_EXPANSION": 1.3,
            "LIQUIDITY_SWEEP": 1.3,
            "RANGING": 0.8,
            "HIGH_VOLATILITY": 1.3,
            "RISK_OFF": 1.15,
        }
    )
    # 2026-07-16 G13/G14 root cause: all 8 TIER_1 stop-outs fired at the static
    # 35bps floor with confidence 0.55-0.86 treated identically, and 7/8
    # reverted favorably after exit. The stop distance now scales with the
    # position's own calibrated confidence: effective multiplier =
    # atr_stop_multiplier * (1 + atr_stop_confidence_gain * (conf-0.5)/0.5),
    # so conf 0.85 earns ~2.4x the base runway while conf 0.55 keeps ~1.1x.
    atr_stop_confidence_gain: float = 2.0
    # Rolling median of (|realized gross pnl_bps| - atr_stop_bps) over recent
    # TIER_1 stop closes, computed by the runtime and passed in. Compensates
    # the 60s-cycle overshoot (observed 1.5-46bps) so the sized risk matches
    # the realized exit. None = no premium (cold start).
    atr_stop_overshoot_premium_bps: float | None = None
    # A+ goal Phase 8: compressed-volatility floor for the ATR-derived stop.
    # The 2026-07-05 cluster fired at ~19-21bps because entry ATR was 6.3-7.1bps,
    # so even the 3.0x trend multiplier sat inside round-trip cost (~11bps) plus
    # one candle of noise. The effective ATR stop distance is
    # max(scaled ATR stop, this floor); TIER_0 liquidation-distance and
    # drawdown-emergency guards remain the catastrophic ceiling.
    atr_stop_floor_bps: float = 35.0
    # A+ goal Phase 8: unconditional per-position catastrophic floor. LITUSDT
    # (2026-07-06 06:57Z) reached MAE 610bps with NO stop armed because
    # entry_atr_bps was None (ATR stop never evaluated), static stops are
    # disabled in the active runtime, and drawdown-emergency guards account
    # equity, not single positions. This floor fires regardless of ATR
    # availability or static-exit switches; 0 disables (tests only).
    catastrophic_floor_stop_bps: float = 150.0
    # 2026-07-17 (CG-F052): optional upper bound on the effective loss-cut
    # distance. effective_atr_stop_bps() has a floor but NO ceiling, so the
    # confidence/regime scaling produced 1000-2300bps stops on high-ATR symbols
    # that never fired, letting losers run all the way to the -150bps
    # catastrophic floor -- 16/16 catastrophic closes and the dominant driver of
    # the -12.3bps G13 / 0.745 PF G14. When >0, evaluate_exit cuts a loser at
    # this distance (TIER_1_ATR_CEILING_STOP) BEFORE the catastrophic floor.
    # It deliberately does NOT alter effective_atr_stop_bps (which the allocator
    # also consumes for sizing), so position sizing is unchanged and only the
    # realized loss magnitude shrinks. Default 0 = disabled (behavior unchanged);
    # activated via env PAPER_ATR_STOP_CEILING_BPS so enabling it is an explicit
    # operator opt-in (risk change, per the mandatory change protocol).
    atr_stop_ceiling_bps: float = field(
        default_factory=lambda: _env_float("PAPER_ATR_STOP_CEILING_BPS", 0.0)
    )
    # Phase 7: liquidity-aware TP — skip TP when ob_spread_bps exceeds this limit.
    # Wide spreads indicate poor fill quality; better to hold than take a spread-eaten TP.
    max_ob_spread_bps_for_tp: float = 20.0
    # Static threshold exits are kept available for unit tests and offline
    # experiments, but the active paper runtime disables them so exits are
    # driven by adaptive/model/market-state controls instead of fixed bps/hold
    # constants.
    static_stop_loss_enabled: bool = True
    static_take_profit_enabled: bool = True
    static_profit_lock_enabled: bool = True
    static_profit_bank_enabled: bool = True
    static_max_hold_enabled: bool = True


def effective_atr_stop_bps(
    *,
    atr_bps: float | None,
    confidence_calibrated: float | None,
    strategy_selected_mode: str | None,
    market_regime: str | None,
    config: PaperExitConfig | None = None,
) -> float:
    """The effective ATR stop distance the exit engine will enforce.

    Shared by evaluate_exit and the adaptive capital allocator so notional
    sizing (risk_budget / stop_distance) uses the SAME stop the exit engine
    fires at. Sizing with a tighter stop than the exit enforces made realized
    losses 2.0-4.8x the sized risk budget (2026-07-16 G13/G14 root cause).
    """
    cfg = config or PaperExitConfig()
    if atr_bps is None or atr_bps <= 0:
        stop = float(cfg.atr_stop_floor_bps) if cfg.atr_stop_floor_bps > 0 else float(cfg.catastrophic_floor_stop_bps)
    else:
        is_trend = (strategy_selected_mode or "").lower() == "trend_mode"
        mult = (
            cfg.atr_stop_multiplier_trend_mode
            if (is_trend and cfg.atr_stop_multiplier_trend_mode is not None)
            else cfg.atr_stop_multiplier
        )
        conf = coerce_float(confidence_calibrated)
        if conf is not None and conf > 0.5 and cfg.atr_stop_confidence_gain > 0:
            mult *= 1.0 + cfg.atr_stop_confidence_gain * min(1.0, (conf - 0.5) / 0.5)
        scale = 1.0
        regime_key = str(market_regime or "").upper()
        scale_map = cfg.atr_stop_regime_scale or {}
        if regime_key and scale_map:
            matched = []
            for token in (t.strip() for t in regime_key.split(",")):
                if not token:
                    continue
                try:
                    val = scale_map.get(token)
                    if val is not None:
                        matched.append(float(val))
                except (TypeError, ValueError):
                    continue
            if matched:
                scale = max(matched)
        stop = atr_bps * mult * scale
        if cfg.atr_stop_floor_bps > 0 and stop < cfg.atr_stop_floor_bps:
            stop = float(cfg.atr_stop_floor_bps)
    premium = coerce_float(cfg.atr_stop_overshoot_premium_bps)
    if premium is not None and premium > 0:
        stop += premium
    return float(stop)


def evaluate_exit(
    *,
    position: PaperNetPosition,
    mark_price: float | None,
    generated_utc: str,
    config: PaperExitConfig,
    alpha_context: dict[str, Any] | None = None,
    model_context: dict[str, Any] | None = None,
    account_context: dict[str, Any] | None = None,
    atr_bps: float | None = None,
    ob_spread_bps: float | None = None,
    regime: str | None = None,
) -> dict[str, Any]:
    if mark_price is None or mark_price <= 0:
        return {"should_close": False, "close_reason": None, "tier": None, "blocker": "MARK_PRICE_MISSING"}
    position.update_mark(mark_price=mark_price, mark_time=generated_utc)
    hold_seconds = seconds_between(position.opened_est, generated_utc)
    if hold_seconds < config.min_hold_seconds:
        return {"should_close": False, "close_reason": None, "tier": None, "blocker": "MIN_HOLD_ACTIVE"}
    pnl_bps_value = position.unrealized_pnl_bps()
    if ob_spread_bps is None:
        ob_spread_bps = coerce_float(
            (alpha_context or {}).get("bid_ask_spread_bps")
            if (alpha_context or {}).get("bid_ask_spread_bps") is not None
            else (alpha_context or {}).get("spread_bps")
        )
    liquidation_distance_bps = _current_liquidation_distance_bps(
        position,
        mark_price=mark_price,
    )
    if (
        liquidation_distance_bps is not None
        and liquidation_distance_bps <= config.emergency_liquidation_distance_bps
    ):
        return {
            "should_close": True,
            "close_reason": "TIER_0_EMERGENCY_LIQUIDATION_DISTANCE",
            "tier": 0,
            "pnl_bps": pnl_bps_value,
            "liquidation_price_estimate": position.liquidation_price_estimate,
            "current_liquidation_distance_bps": liquidation_distance_bps,
        }
    account_drawdown_bps = coerce_float((account_context or {}).get("drawdown_bps"))
    if account_drawdown_bps is not None and account_drawdown_bps >= abs(config.drawdown_emergency_bps):
        return {
            "should_close": True,
            "close_reason": "TIER_0_DRAWDOWN_EMERGENCY_EXIT",
            "tier": 0,
            "pnl_bps": pnl_bps_value,
            "drawdown_bps": account_drawdown_bps,
        }
    micro_reversal = coerce_float((alpha_context or {}).get("microstructure_reversal_score"))
    if micro_reversal is not None and micro_reversal >= abs(config.microstructure_reversal_score):
        return {
            "should_close": True,
            "close_reason": "TIER_1_MICROSTRUCTURE_REVERSAL_EXIT",
            "tier": 1,
            "pnl_bps": pnl_bps_value,
            "microstructure_reversal_score": micro_reversal,
        }
    if (model_context or {}).get("model_reversal") is True:
        return {
            "should_close": True,
            "close_reason": "TIER_1_MODEL_REVERSAL_EXIT",
            "tier": 1,
            "pnl_bps": pnl_bps_value,
        }
    confidence = coerce_float((model_context or {}).get("confidence"))
    if confidence is not None and confidence <= config.confidence_decay_min:
        return {
            "should_close": True,
            "close_reason": "TIER_1_CONFIDENCE_DECAY_EXIT",
            "tier": 1,
            "pnl_bps": pnl_bps_value,
            "confidence": confidence,
        }
    advanced_exit_context = _advanced_exit_context(
        position,
        alpha_context=alpha_context,
        model_context=model_context,
    )
    advanced_exit = _advanced_exit_signal(position, advanced_exit_context)
    if advanced_exit is not None:
        advanced_exit["pnl_bps"] = pnl_bps_value
        return advanced_exit
    # A+ goal Phase 7: MFE breakeven protection fires before the ATR stop so a
    # trade that already paid for itself exits near breakeven instead of riding
    # the full retracement into a TIER_1_ATR_VOLATILITY_STOP loss.
    if config.mfe_breakeven_protection_enabled:
        _trailing_already_armed = (
            bool(position.trailing_stop_history) or position.trailing_activation_price is not None
        )
        # Only fire near breakeven as designed: a decay band of 3x the cost
        # buffer. Deeper losses must fall through to real stops (LITUSDT
        # regression: this tier mislabelled a -286bps close as "breakeven
        # protection" because it was the only check that ever fired).
        #
        # 2026-07-10 loss-cluster root cause: an ARMED trailing stop can sit
        # below entry (early activation x ATR-scaled distance), so a trade
        # with MFE far above cost could still round-trip into a TIER_2
        # trailing LOSS (KITEUSDT: MFE 92bps -> negative close). The guard
        # therefore also fires when trailing is armed BUT the armed stop level
        # does not lock at least ~breakeven — a profit-locking trail (stop at
        # or above entry+buffer) keeps priority because its gap-close fills at
        # the stop PRICE, which is strictly better than a breakeven close.
        _trailing_stop_locks_profit = False
        _armed_stop_price = getattr(position, "trailing_stop_price", None)
        try:
            _armed_stop = float(_armed_stop_price) if _armed_stop_price else None
        except (TypeError, ValueError):
            _armed_stop = None
        if _armed_stop and _armed_stop > 0 and position.avg_entry_price:
            if position.side == "long":
                _locked_bps = (
                    (_armed_stop - position.avg_entry_price)
                    / position.avg_entry_price
                    * 10000.0
                )
            else:
                _locked_bps = (
                    (position.avg_entry_price - _armed_stop)
                    / position.avg_entry_price
                    * 10000.0
                )
            _trailing_stop_locks_profit = _locked_bps >= -abs(
                config.mfe_breakeven_cost_buffer_bps
            )
        _mfe_breakeven_lower_bound = -abs(config.mfe_breakeven_cost_buffer_bps) * 3.0
        _entry = position.avg_entry_price
        _best = position.best_favorable_price
        _mfe_bps: float | None = None
        if _best is not None and _best > 0 and _entry and _entry > 0:
            if position.side == "long" and _best > _entry:
                _mfe_bps = (_best - _entry) / _entry * 10000.0
            elif position.side == "short" and _best < _entry:
                _mfe_bps = (_entry - _best) / _entry * 10000.0
        _arm_threshold_bps = abs(config.mfe_breakeven_min_mfe_bps)
        if atr_bps is not None and atr_bps > 0:
            _arm_threshold_bps = max(_arm_threshold_bps, atr_bps * config.mfe_breakeven_atr_multiple)
        _mfe_qualified = _mfe_bps is not None and _mfe_bps >= _arm_threshold_bps
        if (
            (not _trailing_already_armed or not _trailing_stop_locks_profit)
            and pnl_bps_value <= config.mfe_breakeven_cost_buffer_bps
            and pnl_bps_value >= _mfe_breakeven_lower_bound
        ):
            if _mfe_qualified:
                return {
                    "should_close": True,
                    "close_reason": "TIER_2_MFE_BREAKEVEN_PROTECTION",
                    "tier": 2,
                    "pnl_bps": pnl_bps_value,
                    "mfe_bps": _mfe_bps,
                    "mfe_breakeven_arm_threshold_bps": _arm_threshold_bps,
                    "mfe_breakeven_cost_buffer_bps": config.mfe_breakeven_cost_buffer_bps,
                    "trailing_already_armed": _trailing_already_armed,
                    "atr_bps": atr_bps,
                }
        # Band-gap giveback stop (2026-07-17): the breakeven band is a
        # point-in-time check per 60s cycle, so a fast adverse move can jump
        # STRAIGHT PAST it (observed: AGLDUSDT, MFE 129.7bps with the armed
        # trail sitting below entry, gapped from inside the band to -90bps in
        # one cycle — no protection left between the missed band and the far
        # ATR stop). When the trade HAD paid for itself (MFE >= the same arm
        # threshold), the trail locks nothing, and price has gapped below the
        # band but is still shallower than one ATR (the volatility stop's
        # domain, honestly labelled there), cut the giveback now instead of
        # riding a former winner into a full stop-out.
        # Priority note: if the armed trail would fire at THIS mark, its
        # close fills at the stop PRICE (strictly better than a mark-price
        # giveback close) — defer to it.
        _trailing_would_fire_now = bool(
            _armed_stop
            and _armed_stop > 0
            and mark_price is not None
            and (
                mark_price <= _armed_stop
                if position.side == "long"
                else mark_price >= _armed_stop
            )
        )
        elif_giveback = (
            _mfe_qualified
            and (not _trailing_already_armed or not _trailing_stop_locks_profit)
            and not _trailing_would_fire_now
            and pnl_bps_value < _mfe_breakeven_lower_bound
            and (
                atr_bps is None
                or atr_bps <= 0
                or pnl_bps_value > -abs(atr_bps)
            )
        )
        if elif_giveback:
            return {
                "should_close": True,
                "close_reason": "TIER_2_MFE_GIVEBACK_STOP",
                "tier": 2,
                "pnl_bps": pnl_bps_value,
                "mfe_bps": _mfe_bps,
                "mfe_breakeven_arm_threshold_bps": _arm_threshold_bps,
                "mfe_breakeven_band_gapped": True,
                "mfe_breakeven_cost_buffer_bps": config.mfe_breakeven_cost_buffer_bps,
                "trailing_already_armed": _trailing_already_armed,
                "atr_bps": atr_bps,
            }
    # A+ goal Phase 8: when ATR is unavailable the volatility stop can never
    # arm; with static stops disabled in the active runtime that left NO
    # working stop (LITUSDT regression). Fall back to the compressed-vol floor
    # as a fixed stop distance for missing-ATR positions.
    if (atr_bps is None or atr_bps <= 0) and not config.static_stop_loss_enabled and config.atr_stop_floor_bps > 0:
        if pnl_bps_value <= -abs(config.atr_stop_floor_bps):
            return {
                "should_close": True,
                "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
                "tier": 1,
                "pnl_bps": pnl_bps_value,
                "atr_bps": atr_bps,
                "atr_stop_bps": float(config.atr_stop_floor_bps),
                "atr_stop_multiplier_used": None,
                "atr_stop_regime": None,
                "atr_stop_regime_scale_used": None,
                "atr_stop_floor_applied": True,
                "atr_stop_floor_bps": config.atr_stop_floor_bps,
                "atr_missing_floor_fallback": True,
            }
    # Phase 7: volatility-adjusted stop — ATR-derived stop overrides when tighter.
    if atr_bps is not None and atr_bps > 0:
        # R29-D4: Use wider multiplier for trend_mode to give model reversal netting runway.
        _is_trend = (position.strategy_selected_mode or "").lower() == "trend_mode"
        _atr_mult = (
            config.atr_stop_multiplier_trend_mode
            if (_is_trend and config.atr_stop_multiplier_trend_mode is not None)
            else config.atr_stop_multiplier
        )
        # 2026-07-16: confidence-adaptive runway. The floor-dominated static
        # stop shook out 7/8 reverting high-confidence positions while the
        # allocator had up-sized exactly those trades. Higher calibrated
        # confidence now earns proportionally more ATR runway; conf <= 0.5 or
        # missing confidence keeps the base multiplier unchanged.
        _exit_confidence = coerce_float(
            (model_context or {}).get("confidence_calibrated")
            if (model_context or {}).get("confidence_calibrated") is not None
            else getattr(position, "confidence_calibrated", None)
        )
        _conf_gain_used = 1.0
        if _exit_confidence is not None and _exit_confidence > 0.5 and config.atr_stop_confidence_gain > 0:
            _conf_gain_used = 1.0 + config.atr_stop_confidence_gain * min(1.0, (_exit_confidence - 0.5) / 0.5)
        _atr_mult_eff = _atr_mult * _conf_gain_used
        # A+ goal Phase 7: regime-aware scale on top of the mode multiplier.
        # Runtime regime strings are comma-joined token lists; tokenize and
        # take the max scale across matched tokens (previously the joined
        # string never matched any map key, silently pinning scale to 1.0).
        _regime_scale = 1.0
        _regime_key = str(regime or position.market_regime_at_entry or "").upper()
        _regime_scale_map = config.atr_stop_regime_scale or {}
        if _regime_key and _regime_scale_map:
            _matched_scales = []
            for _token in (t.strip() for t in _regime_key.split(",")):
                if not _token:
                    continue
                try:
                    _scale_val = _regime_scale_map.get(_token)
                    if _scale_val is not None:
                        _matched_scales.append(float(_scale_val))
                except (TypeError, ValueError):
                    continue
            if _matched_scales:
                _regime_scale = max(_matched_scales)
        atr_stop = atr_bps * _atr_mult_eff * _regime_scale
        _atr_floor_applied = False
        if config.atr_stop_floor_bps > 0 and atr_stop < config.atr_stop_floor_bps:
            atr_stop = float(config.atr_stop_floor_bps)
            _atr_floor_applied = True
        # Rolling exit-overshoot premium: the 60s cycle overshoots the nominal
        # stop by an observed 1.5-46bps, so the enforced distance carries the
        # runtime's rolling estimate to keep sized risk equal to realized risk.
        _overshoot_premium = coerce_float(config.atr_stop_overshoot_premium_bps)
        if _overshoot_premium is not None and _overshoot_premium > 0:
            atr_stop += _overshoot_premium
        if pnl_bps_value <= -abs(atr_stop):
            return {
                "should_close": True,
                "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
                "tier": 1,
                "pnl_bps": pnl_bps_value,
                "atr_bps": atr_bps,
                "atr_stop_bps": atr_stop,
                "atr_stop_multiplier_used": _atr_mult_eff,
                "atr_stop_confidence_used": _exit_confidence,
                "atr_stop_confidence_gain_used": _conf_gain_used,
                "atr_stop_regime": _regime_key or None,
                "atr_stop_regime_scale_used": _regime_scale,
                "atr_stop_floor_applied": _atr_floor_applied,
                "atr_stop_floor_bps": config.atr_stop_floor_bps,
                "atr_stop_overshoot_premium_bps": _overshoot_premium,
            }
    if config.static_stop_loss_enabled and pnl_bps_value <= -abs(config.stop_loss_bps):
        return {
            "should_close": True,
            "close_reason": "TIER_1_STOP_LOSS",
            "tier": 1,
            "pnl_bps": pnl_bps_value,
        }
    # 2026-07-17 (CG-F052): adaptive ATR-stop CEILING. Cuts a loser at a sane
    # maximum distance before it runs to the -150bps catastrophic floor, closing
    # the gap left by effective_atr_stop_bps having a floor but no ceiling (high-
    # ATR symbols computed 1000-2300bps stops that never fired). Fires only for
    # losers whose tighter TIER_1 ATR stop above did not already trigger, so
    # low-ATR positions still exit at their own (tighter) stop. Disabled (0) by
    # default; operator-activated via PAPER_ATR_STOP_CEILING_BPS.
    if config.atr_stop_ceiling_bps > 0 and pnl_bps_value <= -abs(config.atr_stop_ceiling_bps):
        return {
            "should_close": True,
            "close_reason": "TIER_1_ATR_CEILING_STOP",
            "tier": 1,
            "pnl_bps": pnl_bps_value,
            "atr_stop_ceiling_bps": config.atr_stop_ceiling_bps,
            "atr_bps": atr_bps,
        }
    # A+ goal Phase 8: unconditional catastrophic floor — the backstop when no
    # tighter stop fired above (LITUSDT regression: entry_atr_bps=None with
    # static stops disabled left no working stop; MAE reached 610bps).
    if config.catastrophic_floor_stop_bps > 0 and pnl_bps_value <= -abs(config.catastrophic_floor_stop_bps):
        return {
            "should_close": True,
            "close_reason": "TIER_0_CATASTROPHIC_FLOOR_STOP",
            "tier": 0,
            "pnl_bps": pnl_bps_value,
            "catastrophic_floor_stop_bps": config.catastrophic_floor_stop_bps,
        }
    profit_lock_result: dict[str, Any] | None = None
    profit_lock_deferred_result: dict[str, Any] | None = None
    profit_bank_deferred_result: dict[str, Any] | None = None
    take_profit_deferred_result: dict[str, Any] | None = None
    armed_trailing_context: dict[str, Any] | None = None
    best = position.best_favorable_price
    if best is not None and best > 0:
        trailing_was_armed_before_eval = (
            bool(position.trailing_stop_history)
            or position.trailing_activation_price is not None
        )
        trailing_stop_bps_effective = abs(config.trailing_stop_bps)
        if atr_bps is not None and atr_bps > 0:
            trailing_stop_bps_effective = max(
                trailing_stop_bps_effective,
                abs(atr_bps * config.atr_trailing_stop_multiplier),
            )
        trailing_after_cost_buffer_bps = max(
            0.0,
            float(config.trailing_stop_min_after_cost_buffer_bps),
            float(ob_spread_bps or 0.0),
        )
        trailing_profit_floor_bps = (
            float(config.min_profit_before_trailing_bps)
            + trailing_after_cost_buffer_bps
        )
        if config.trailing_stop_enabled and position.side == "long" and best > position.avg_entry_price:
            best_excursion_bps = ((best - position.avg_entry_price) / position.avg_entry_price) * 10000.0
            drawdown_from_best_bps = ((best - mark_price) / best) * 10000.0
            stop_price: float | None = None
            trailing_stop_price_context: dict[str, Any] = {}
            if best_excursion_bps >= trailing_profit_floor_bps:
                activation_price = position.avg_entry_price * (
                    1.0 + trailing_profit_floor_bps / 10000.0
                )
                raw_stop_price = best * (1.0 - trailing_stop_bps_effective / 10000.0)
                # CG-F015 fix: clamp stop_price to at-cost floor so it never falls
                # below entry + profit_floor. Without this, a 50bps trailing distance
                # at a 30bps excursion sets stop_price below entry (loss territory).
                at_cost_floor = position.avg_entry_price * (
                    1.0 + trailing_profit_floor_bps / 10000.0
                )
                stop_price = max(raw_stop_price, at_cost_floor)
                position.record_trailing_state(
                    activation_price=activation_price,
                    activation_time=generated_utc,
                    stop_price=stop_price,
                    reason="ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                )
                if trailing_was_armed_before_eval:
                    armed_trailing_context = {
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "atr_bps": atr_bps,
                    }
                trailing_stop_price_context = _trailing_stop_price_context(
                    side=position.side,
                    entry_price=position.avg_entry_price,
                    mark_price=mark_price,
                    stop_price=stop_price,
                    exit_floor_bps=config.min_profit_before_trailing_bps,
                )
            if (
                drawdown_from_best_bps >= trailing_stop_bps_effective
                and pnl_bps_value < trailing_profit_floor_bps
            ):
                paper_exit_pnl_bps = coerce_float(trailing_stop_price_context.get("paper_exit_pnl_bps"))
                trailing_stop_exit_floor_bps = coerce_float(
                    trailing_stop_price_context.get("trailing_stop_exit_floor_bps")
                )
                if (
                    trailing_was_armed_before_eval
                    and paper_exit_pnl_bps is not None
                    and trailing_stop_exit_floor_bps is not None
                    and paper_exit_pnl_bps >= trailing_stop_exit_floor_bps - 0.001
                ):
                    return {
                        "should_close": True,
                        "close_reason": "TIER_2_TRAILING_STOP",
                        "tier": 2,
                        "pnl_bps": pnl_bps_value,
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "trailing_profit_floor_gap_bps": trailing_profit_floor_bps - pnl_bps_value,
                        "trailing_profit_floor_gap_exit": True,
                        "trailing_profit_floor_gap_exit_reason": "PRIOR_ARMED_TRAILING_STOP_BREACHED_WITH_POSITIVE_PNL",
                        "ob_spread_bps": ob_spread_bps,
                        "atr_bps": atr_bps,
                        **trailing_stop_price_context,
                    }
                return {
                    "should_close": False,
                    "close_reason": None,
                    "tier": None,
                    "pnl_bps": pnl_bps_value,
                    "blocker": "TRAILING_AFTER_COST_PROFIT_FLOOR_NOT_MET",
                    "drawdown_from_best_bps": drawdown_from_best_bps,
                    "best_excursion_bps": best_excursion_bps,
                    "trailing_stop_bps_effective": trailing_stop_bps_effective,
                    "trailing_profit_floor_bps": trailing_profit_floor_bps,
                    "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                    "trailing_stop_exit_after_cost_floor_not_met": (
                        trailing_was_armed_before_eval
                        and paper_exit_pnl_bps is not None
                        and trailing_stop_exit_floor_bps is not None
                        and paper_exit_pnl_bps < trailing_stop_exit_floor_bps
                    ),
                    "ob_spread_bps": ob_spread_bps,
                    "atr_bps": atr_bps,
                    **trailing_stop_price_context,
                }
            if (
                drawdown_from_best_bps >= trailing_stop_bps_effective
                and pnl_bps_value >= trailing_profit_floor_bps
            ):
                # HedgeLock: if enabled and position had sufficient excursion,
                # defer close — caller opens a counter-position instead.
                if (
                    config.hedge_lock_enabled
                    and best_excursion_bps >= config.hedge_lock_min_excursion_bps
                ):
                    return {
                        "should_close": False,
                        "hedge_lock_trigger": True,
                        "close_reason": "TIER_2_HEDGE_LOCK_TRIGGER",
                        "tier": 2,
                        "pnl_bps": pnl_bps_value,
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "atr_bps": atr_bps,
                    }
                return {
                    "should_close": True,
                    "close_reason": "TIER_2_TRAILING_STOP",
                    "tier": 2,
                    "pnl_bps": pnl_bps_value,
                    "drawdown_from_best_bps": drawdown_from_best_bps,
                    "trailing_stop_bps_effective": trailing_stop_bps_effective,
                    "trailing_profit_floor_bps": trailing_profit_floor_bps,
                    "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                    "atr_bps": atr_bps,
                    **trailing_stop_price_context,
                }
            if (
                config.static_profit_lock_enabled
                and pnl_bps_value > 0
                and drawdown_from_best_bps >= abs(config.profit_lock_bps)
            ):
                if (
                    config.defer_profit_lock_to_active_trailing_stop
                    and config.trailing_stop_enabled
                    and best_excursion_bps >= trailing_profit_floor_bps
                ):
                    profit_lock_deferred_result = {
                        "should_close": False,
                        "close_reason": None,
                        "tier": None,
                        "pnl_bps": pnl_bps_value,
                        "blocker": "PROFIT_LOCK_DEFERRED_TO_ACTIVE_TRAILING_STOP",
                        "would_close_reason": "TIER_2_PROFIT_LOCK",
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "profit_lock_bps": abs(config.profit_lock_bps),
                        "atr_bps": atr_bps,
                    }
                else:
                    profit_lock_result = {
                        "should_close": True,
                        "close_reason": "TIER_2_PROFIT_LOCK",
                        "tier": 2,
                        "pnl_bps": pnl_bps_value,
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                    }
        if config.trailing_stop_enabled and position.side == "short" and best < position.avg_entry_price:
            best_excursion_bps = ((position.avg_entry_price - best) / position.avg_entry_price) * 10000.0
            drawdown_from_best_bps = ((mark_price - best) / best) * 10000.0
            stop_price: float | None = None
            trailing_stop_price_context: dict[str, Any] = {}
            if best_excursion_bps >= trailing_profit_floor_bps:
                activation_price = position.avg_entry_price * (
                    1.0 - trailing_profit_floor_bps / 10000.0
                )
                raw_stop_price = best * (1.0 + trailing_stop_bps_effective / 10000.0)
                # CG-F015 fix: clamp stop_price to at-cost ceiling for SHORT —
                # stop must not exceed entry - profit_floor (loss territory above entry).
                at_cost_ceiling = position.avg_entry_price * (
                    1.0 - trailing_profit_floor_bps / 10000.0
                )
                stop_price = min(raw_stop_price, at_cost_ceiling)
                position.record_trailing_state(
                    activation_price=activation_price,
                    activation_time=generated_utc,
                    stop_price=stop_price,
                    reason="ADAPTIVE_TRAIL_ARMED_AFTER_NET_PROFIT_FLOOR",
                )
                if trailing_was_armed_before_eval:
                    armed_trailing_context = {
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "atr_bps": atr_bps,
                    }
                trailing_stop_price_context = _trailing_stop_price_context(
                    side=position.side,
                    entry_price=position.avg_entry_price,
                    mark_price=mark_price,
                    stop_price=stop_price,
                    exit_floor_bps=config.min_profit_before_trailing_bps,
                )
            if (
                drawdown_from_best_bps >= trailing_stop_bps_effective
                and pnl_bps_value < trailing_profit_floor_bps
            ):
                paper_exit_pnl_bps = coerce_float(trailing_stop_price_context.get("paper_exit_pnl_bps"))
                trailing_stop_exit_floor_bps = coerce_float(
                    trailing_stop_price_context.get("trailing_stop_exit_floor_bps")
                )
                if (
                    trailing_was_armed_before_eval
                    and paper_exit_pnl_bps is not None
                    and trailing_stop_exit_floor_bps is not None
                    and paper_exit_pnl_bps >= trailing_stop_exit_floor_bps - 0.001
                ):
                    return {
                        "should_close": True,
                        "close_reason": "TIER_2_TRAILING_STOP",
                        "tier": 2,
                        "pnl_bps": pnl_bps_value,
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "trailing_profit_floor_gap_bps": trailing_profit_floor_bps - pnl_bps_value,
                        "trailing_profit_floor_gap_exit": True,
                        "trailing_profit_floor_gap_exit_reason": "PRIOR_ARMED_TRAILING_STOP_BREACHED_WITH_POSITIVE_PNL",
                        "ob_spread_bps": ob_spread_bps,
                        "atr_bps": atr_bps,
                        **trailing_stop_price_context,
                    }
                return {
                    "should_close": False,
                    "close_reason": None,
                    "tier": None,
                    "pnl_bps": pnl_bps_value,
                    "blocker": "TRAILING_AFTER_COST_PROFIT_FLOOR_NOT_MET",
                    "drawdown_from_best_bps": drawdown_from_best_bps,
                    "best_excursion_bps": best_excursion_bps,
                    "trailing_stop_bps_effective": trailing_stop_bps_effective,
                    "trailing_profit_floor_bps": trailing_profit_floor_bps,
                    "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                    "trailing_stop_exit_after_cost_floor_not_met": (
                        trailing_was_armed_before_eval
                        and paper_exit_pnl_bps is not None
                        and trailing_stop_exit_floor_bps is not None
                        and paper_exit_pnl_bps < trailing_stop_exit_floor_bps
                    ),
                    "ob_spread_bps": ob_spread_bps,
                    "atr_bps": atr_bps,
                    **trailing_stop_price_context,
                }
            if (
                drawdown_from_best_bps >= trailing_stop_bps_effective
                and pnl_bps_value >= trailing_profit_floor_bps
            ):
                # HedgeLock: if enabled and position had sufficient excursion,
                # defer close — caller opens a counter-position instead.
                if (
                    config.hedge_lock_enabled
                    and best_excursion_bps >= config.hedge_lock_min_excursion_bps
                ):
                    return {
                        "should_close": False,
                        "hedge_lock_trigger": True,
                        "close_reason": "TIER_2_HEDGE_LOCK_TRIGGER",
                        "tier": 2,
                        "pnl_bps": pnl_bps_value,
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "atr_bps": atr_bps,
                    }
                return {
                    "should_close": True,
                    "close_reason": "TIER_2_TRAILING_STOP",
                    "tier": 2,
                    "pnl_bps": pnl_bps_value,
                    "drawdown_from_best_bps": drawdown_from_best_bps,
                    "trailing_stop_bps_effective": trailing_stop_bps_effective,
                    "trailing_profit_floor_bps": trailing_profit_floor_bps,
                    "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                    "atr_bps": atr_bps,
                    **trailing_stop_price_context,
                }
            if (
                config.static_profit_lock_enabled
                and pnl_bps_value > 0
                and drawdown_from_best_bps >= abs(config.profit_lock_bps)
            ):
                if (
                    config.defer_profit_lock_to_active_trailing_stop
                    and config.trailing_stop_enabled
                    and best_excursion_bps >= trailing_profit_floor_bps
                ):
                    profit_lock_deferred_result = {
                        "should_close": False,
                        "close_reason": None,
                        "tier": None,
                        "pnl_bps": pnl_bps_value,
                        "blocker": "PROFIT_LOCK_DEFERRED_TO_ACTIVE_TRAILING_STOP",
                        "would_close_reason": "TIER_2_PROFIT_LOCK",
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                        "best_excursion_bps": best_excursion_bps,
                        "trailing_stop_bps_effective": trailing_stop_bps_effective,
                        "trailing_profit_floor_bps": trailing_profit_floor_bps,
                        "trailing_after_cost_buffer_bps": trailing_after_cost_buffer_bps,
                        "profit_lock_bps": abs(config.profit_lock_bps),
                        "atr_bps": atr_bps,
                    }
                else:
                    profit_lock_result = {
                        "should_close": True,
                        "close_reason": "TIER_2_PROFIT_LOCK",
                        "tier": 2,
                        "pnl_bps": pnl_bps_value,
                        "drawdown_from_best_bps": drawdown_from_best_bps,
                    }
    if config.static_profit_bank_enabled and pnl_bps_value >= abs(config.profit_bank_bps):
        if (
            config.defer_profit_bank_to_active_trailing_stop
            and armed_trailing_context is not None
        ):
            profit_bank_deferred_result = {
                "should_close": False,
                "close_reason": None,
                "tier": None,
                "pnl_bps": pnl_bps_value,
                "blocker": "PROFIT_BANK_DEFERRED_TO_ACTIVE_TRAILING_STOP",
                "would_close_reason": "TIER_2_PROFIT_BANK",
                "profit_bank_bps": abs(config.profit_bank_bps),
                **armed_trailing_context,
            }
        else:
            return {
                "should_close": True,
                "close_reason": "TIER_2_PROFIT_BANK",
                "tier": 2,
                "pnl_bps": pnl_bps_value,
            }
    # Phase 7: liquidity-aware TP — skip TP when spread is too wide (poor fill).
    if ob_spread_bps is not None and ob_spread_bps > config.max_ob_spread_bps_for_tp:
        pass  # skip TP tiers — spread too wide, hold for better liquidity
    elif config.static_take_profit_enabled and pnl_bps_value >= abs(config.take_profit_bps):
        if (
            config.defer_take_profit_to_active_trailing_stop
            and armed_trailing_context is not None
        ):
            take_profit_deferred_result = {
                "should_close": False,
                "close_reason": None,
                "tier": None,
                "pnl_bps": pnl_bps_value,
                "blocker": "TAKE_PROFIT_DEFERRED_TO_ACTIVE_TRAILING_STOP",
                "would_close_reason": "TIER_2_TAKE_PROFIT",
                "take_profit_bps": abs(config.take_profit_bps),
                **armed_trailing_context,
            }
        else:
            return {
                "should_close": True,
                "close_reason": "TIER_2_TAKE_PROFIT",
                "tier": 2,
                "pnl_bps": pnl_bps_value,
            }
    cascade = coerce_float((alpha_context or {}).get("liquidation_cascade_risk"))
    if pnl_bps_value >= abs(config.dynamic_take_profit_bps) and cascade is not None and cascade >= 0.60:
        return {
            "should_close": True,
            "close_reason": "TIER_2_DYNAMIC_TAKE_PROFIT",
            "tier": 2,
            "pnl_bps": pnl_bps_value,
            "liquidation_cascade_risk": cascade,
        }
    if profit_lock_result is not None:
        return profit_lock_result
    if config.static_max_hold_enabled and hold_seconds >= config.max_hold_seconds:
        return {
            "should_close": True,
            "close_reason": "TIER_4_MAX_HOLD_TIME",
            "tier": 4,
            "pnl_bps": pnl_bps_value,
            "hold_time_seconds": hold_seconds,
        }
    if profit_bank_deferred_result is not None:
        return profit_bank_deferred_result
    if take_profit_deferred_result is not None:
        return take_profit_deferred_result
    if profit_lock_deferred_result is not None:
        return profit_lock_deferred_result
    return {"should_close": False, "close_reason": None, "tier": None, "pnl_bps": pnl_bps_value}
