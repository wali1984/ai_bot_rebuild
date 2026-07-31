"""Phase 8: Per-trade paper-only leverage and margin recommendations.

Produces a recommendation dict for each individual trade signal.
NEVER mutates exchange leverage or margin settings.
NEVER produces ALL_SYMBOLS aggregate recommendations for trade decisions.
All recommendations are paper-only and require human approval before live use.

Fields produced per recommendation:
    recommended_leverage: float — per-symbol ADAPTIVE within [1, ceiling]; ceiling is
        75x (BTC/ETH) / 50x (SOL/LTC/XRP) / 20x (alts), further clamped by a
        volatility-scaled liquidation-safety cap. Earned continuously through
        confidence and direction-aligned positive after-cost edge relative to
        current ATR; non-positive aligned edge -> 1x. The
        dynamic risk envelope remains the binding per-cycle cap downstream.
    recommended_margin_mode: str ("isolated" — CROSS is never recommended in paper mode)
    liquidation_distance_bps: float (estimated distance to liquidation in bps)
    volatility_budget_bps: float (max acceptable position loss per period in bps)
    confidence_budget_pct: float (max position size as fraction of equity, 0–1)
    max_loss_budget_usd: float (absolute maximum loss cap per trade)
    reason: str (human-readable explanation)
    live_gate: str ("blocked_human_only" — invariant)
    mutates_exchange: bool (always False — invariant)
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any

LIVE_GATE = "blocked_human_only"
MUTATES_EXCHANGE = False


def _clamp01(value: float) -> float:
    if value != value:  # NaN
        return 0.0
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name, "")
        return float(raw.strip()) if raw.strip() else default
    except (TypeError, ValueError):
        return default


# Per-symbol leverage CEILINGS = the MAX of a fully market-driven adaptive
# range, NEVER a static grant. Operator directive 2026-07-31: the pipeline
# decides leverage/margin from market conditions; top-tier majors may reach up
# to 100x, alts up to 25x.
#   Top-tier majors  BTC/ETH/SOL/LTC/XRP -> up to 100x
#   All other alts                        -> up to 25x
# This ceiling is only the OUTER operator-safety bound. The BINDING per-symbol
# max is the smaller of: the authenticated Binance venue leverage bracket for
# the symbol (read at decision time from maintenance-bracket evidence) and the
# ADAPTIVE liquidation-safe ceiling (_liquidation_safe_max_leverage, a
# continuous function of ATR — tight ranges permit more, choppy markets force
# it down). Every point in the range is still EARNED through the realized
# evidence envelope; a non-positive after-cost edge collapses to 1x. No static
# strategy threshold selects a leverage; only these data-derived safety bounds
# cap it.
_TOP_TIER_MAJOR_SYMBOLS = frozenset(
    {"BTCUSDT", "ETHUSDT", "SOLUSDT", "LTCUSDT", "XRPUSDT"}
)


def symbol_leverage_ceiling(symbol: str) -> int:
    """Return the operator-authorized PAPER outer leverage ceiling.

    Top-tier majors are capped at 100x, all other symbols at 25x. The
    authenticated venue bracket and the adaptive liquidation-safe ceiling
    constrain the actual usable leverage per symbol below this bound.
    """
    s = (symbol or "").upper().strip()
    if s in _TOP_TIER_MAJOR_SYMBOLS:
        return 100
    return 25


def _liquidation_safe_max_leverage(
    atr_bps: float | None, fee_buffer_bps: float, safety_atr_multiple: float
) -> float:
    """Highest leverage whose ISOLATED liquidation distance stays beyond
    safety_atr_multiple x ATR, so a normal adverse candle cannot liquidate.

    liq_distance_bps ~= (1/lev)*1e4 - fee_buffer; require >= safety*ATR:
        lev <= 1e4 / (safety*ATR + fee_buffer)
    This makes the usable ceiling ADAPTIVE to volatility — tight ranges permit
    more leverage, choppy markets force it down — without any static threshold.
    """
    atr = _finite_float(atr_bps)
    fee_buffer = _finite_float(fee_buffer_bps)
    safety_multiple = _finite_float(safety_atr_multiple)
    if (
        atr is None
        or atr <= 0.0
        or fee_buffer is None
        or fee_buffer < 0.0
        or safety_multiple is None
        or safety_multiple <= 0.0
    ):
        return 1.0
    denominator = (safety_multiple * atr) + fee_buffer
    if not math.isfinite(denominator) or denominator <= 0.0:
        return 1.0
    # Do not floor this value. Integer flooring created an ATR-dependent step
    # even though PAPER effective leverage supports a continuous value.
    return max(1.0, 10000.0 / denominator)


SCHEMA_VERSION = "v2_leverage_recommendation_v2"

# Absolute paper safety ceiling = the highest symbol tier (top-tier majors,
# 100x). 2026-07-31 operator directive: leverage is fully market-driven and
# per-symbol adaptive (top-tier majors <=100x, alts <=25x) — see
# symbol_leverage_ceiling(). The recommendation is a continuous point in an
# adaptive range; the dynamic risk envelope (scaled by REALIZED win rate /
# profit factor / confidence / drawdown) plus the authenticated venue bracket
# and the ATR-adaptive liquidation-safe ceiling remain the BINDING caps, so
# higher leverage is EARNED by market/realized evidence, never granted
# statically, and a non-positive after-cost edge -> 1x.
PAPER_MAX_LEVERAGE = 100
PAPER_MAX_CONFIDENCE_BUDGET_PCT = 0.05  # 5% of equity max per trade
PAPER_MAX_LOSS_BUDGET_USD = 50.0


@dataclass(frozen=True)
class LeverageRecommendationConfig:
    max_leverage: int = PAPER_MAX_LEVERAGE
    max_confidence_budget_pct: float = PAPER_MAX_CONFIDENCE_BUDGET_PCT
    max_loss_budget_usd: float = PAPER_MAX_LOSS_BUDGET_USD
    # Fee + slippage buffer for liquidation distance estimate
    liquidation_fee_buffer_bps: float = 25.0
    # Liquidation-safety: keep liq distance >= this multiple of ATR at all times
    # (operator-tunable). Higher = safer/less leverage; adaptive to volatility.
    liquidation_safety_atr_multiple: float = field(
        default_factory=lambda: _env_float("PAPER_LEVERAGE_LIQ_SAFETY_ATR_MULT", 5.0)
    )


def _estimate_liquidation_distance_bps(
    leverage: float, fee_buffer_bps: float
) -> float:
    """Estimate distance to liquidation as bps move against position.

    For ISOLATED margin: liquidation ≈ entry * (1/leverage) minus fees.
    Returns the bps move required to hit liquidation.
    """
    if leverage <= 0:
        return 0.0
    raw_distance_bps = (1.0 / leverage) * 10000.0
    return max(0.0, raw_distance_bps - fee_buffer_bps)


def _compute_confidence_budget(confidence: float, max_pct: float) -> float:
    """Map confidence to a position size budget as fraction of equity.

    Higher confidence → larger budget (up to max_pct).
    """
    bounded_confidence = _clamp01(_finite_float(confidence) or 0.0)
    configured_cap = _finite_float(max_pct)
    if configured_cap is None or configured_cap <= 0.0:
        return 0.0
    return round(configured_cap * bounded_confidence, 8)


def _compute_volatility_budget(
    atr_bps: float | None, leverage: float
) -> float | None:
    """Volatility budget in bps: how much of the move is 'expected' per period.

    Used to set soft stop awareness. Higher ATR → wider expected move.
    """
    atr = _finite_float(atr_bps)
    leverage_value = _finite_float(leverage)
    if atr is None or atr <= 0.0 or leverage_value is None:
        return None
    # Budget = ATR * leverage (scaled risk per unit notional)
    return round(min(300.0, atr * leverage_value), 2)


def recommend_leverage_for_signal(
    *,
    symbol: str,
    timeframe: str,
    signal_id: str,
    direction: str,
    confidence_calibrated: float,
    expected_move_after_cost_bps: float | None,
    atr_bps: float | None = None,
    equity_usd: float | None = None,
    config: LeverageRecommendationConfig | None = None,
) -> dict[str, Any]:
    """Produce a per-trade paper leverage and margin recommendation.

    Args:
        symbol: Trading symbol (e.g., BTCUSDT)
        timeframe: Signal timeframe
        signal_id: Unique signal identifier for audit linkage
        direction: long | short | flat
        confidence_calibrated: Model confidence [0, 1]
        expected_move_after_cost_bps: Signed expected value after fees (may be None)
        atr_bps: ATR in bps (optional — for volatility budgeting)
        equity_usd: Current equity in USD (optional — for max_loss_budget_usd)
        config: Override defaults

    Returns:
        dict with all required Phase 8 fields. Never mutates exchange state.
        Contains live_gate="blocked_human_only" and mutates_exchange=False invariants.
    """
    cfg = config or LeverageRecommendationConfig()
    sym = str(symbol or "").upper().strip()
    tf = str(timeframe or "").lower().strip()
    direction_normalized = str(direction or "").lower().strip()
    confidence_quality = _clamp01(
        _finite_float(confidence_calibrated) or 0.0
    )
    edge = _finite_float(expected_move_after_cost_bps)
    atr = _finite_float(atr_bps)

    # The authorized symbol tier, the configured absolute cap, and the
    # liquidation-distance constraint are safety ceilings. None is a market
    # selection tier. Inside their intersection, confidence and after-cost edge
    # relative to *current ATR* interpolate leverage continuously from 1x.
    # There is no fixed confidence, ATR, or edge reference in this selection.
    symbol_ceiling = symbol_leverage_ceiling(sym)
    liquidation_safe_ceiling = _liquidation_safe_max_leverage(
        atr, cfg.liquidation_fee_buffer_bps, cfg.liquidation_safety_atr_multiple
    )
    configured_cap = _finite_float(cfg.max_leverage)
    if configured_cap is None or configured_cap < 1.0:
        configured_cap = 1.0
    adaptive_ceiling = max(
        1.0,
        min(configured_cap, float(symbol_ceiling), liquidation_safe_ceiling),
    )
    if direction_normalized == "long" and edge is not None:
        direction_aligned_edge = edge
        direction_aligned_edge_source = "SIGNED_EDGE_ALIGNED_TO_LONG"
    elif direction_normalized == "short" and edge is not None:
        direction_aligned_edge = -edge
        direction_aligned_edge_source = "SIGNED_EDGE_ALIGNED_TO_SHORT"
    elif direction_normalized == "flat":
        direction_aligned_edge = 0.0
        direction_aligned_edge_source = "FLAT_DIRECTION_NO_EDGE"
    else:
        direction_aligned_edge = None
        direction_aligned_edge_source = "DIRECTION_OR_EDGE_INVALID"
    positive_aligned_edge = (
        max(0.0, direction_aligned_edge)
        if direction_aligned_edge is not None
        else 0.0
    )
    if direction_normalized == "flat":
        edge_volatility_quality = 0.0
        continuous_market_quality = 0.0
        recommended_leverage = 1.0
        reason_tier = "FLAT_DIRECTION_1X"
    elif direction_normalized not in {"long", "short"}:
        edge_volatility_quality = 0.0
        continuous_market_quality = 0.0
        recommended_leverage = 1.0
        reason_tier = "DIRECTION_INVALID_FAIL_CLOSED_1X"
    elif atr is None or atr <= 0.0:
        edge_volatility_quality = 0.0
        continuous_market_quality = 0.0
        recommended_leverage = 1.0
        reason_tier = "ATR_EVIDENCE_INVALID_FAIL_CLOSED_1X"
    elif edge is None:
        edge_volatility_quality = 0.0
        continuous_market_quality = 0.0
        recommended_leverage = 1.0
        reason_tier = "AFTER_COST_EDGE_INVALID_FAIL_CLOSED_1X"
    else:
        normalization_scale = max(positive_aligned_edge, atr)
        scaled_edge = positive_aligned_edge / normalization_scale
        scaled_atr = atr / normalization_scale
        edge_energy = scaled_edge * scaled_edge
        atr_energy = scaled_atr * scaled_atr
        denominator = edge_energy + atr_energy
        edge_volatility_quality = (
            edge_energy / denominator if denominator > 0.0 else 0.0
        )
        continuous_market_quality = _clamp01(
            confidence_quality * edge_volatility_quality
        )
        recommended_leverage = 1.0 + (
            continuous_market_quality * (adaptive_ceiling - 1.0)
        )
        recommended_leverage = max(
            1.0,
            min(adaptive_ceiling, recommended_leverage),
        )
        # The allocator's durable payload contract uses eight decimal places.
        # This is serialization precision, not a market-selection rung.
        recommended_leverage = min(
            adaptive_ceiling,
            round(recommended_leverage, 8),
        )
        if positive_aligned_edge <= 0.0:
            reason_tier = (
                "CONTINUOUS_NON_POSITIVE_DIRECTION_ALIGNED_EDGE_1X"
            )
        else:
            reason_tier = "CONTINUOUS_CONFIDENCE_EDGE_ATR_SCALED"

    liquidation_distance_bps = _estimate_liquidation_distance_bps(
        recommended_leverage, cfg.liquidation_fee_buffer_bps
    )
    confidence_budget_pct = _compute_confidence_budget(
        confidence_calibrated, cfg.max_confidence_budget_pct
    )
    volatility_budget_bps = _compute_volatility_budget(atr, recommended_leverage)
    volatility_budget_source = (
        "CURRENT_ATR_TIMES_CONTINUOUS_PAPER_LEVERAGE"
        if volatility_budget_bps is not None
        else "ATR_EVIDENCE_INVALID_FAIL_CLOSED"
    )

    # Max loss budget: lesser of config cap and confidence-scaled equity fraction
    equity = _finite_float(equity_usd)
    configured_max_loss = _finite_float(cfg.max_loss_budget_usd)
    if configured_max_loss is None or configured_max_loss < 0.0:
        configured_max_loss = 0.0
    if equity is not None and equity > 0.0:
        max_loss_from_equity = (
            equity * confidence_budget_pct * recommended_leverage * 0.1
        )
        max_loss_budget_usd = round(
            min(configured_max_loss, max_loss_from_equity), 2
        )
    else:
        max_loss_budget_usd = configured_max_loss

    reason = (
        f"{reason_tier}|symbol={sym}|tf={tf}|"
        f"confidence={confidence_quality:.8f}|"
        f"atr_bps={atr}|"
        f"expected_move={edge}|"
        f"lev={recommended_leverage:.8f}x|margin=isolated|"
        f"liq_dist={liquidation_distance_bps:.0f}bps"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": sym,
        "timeframe": tf,
        "signal_id": signal_id,
        "direction": direction_normalized,
        "recommended_leverage": recommended_leverage,
        "symbol_leverage_ceiling": symbol_ceiling,
        "adaptive_leverage_ceiling": adaptive_ceiling,
        "liquidation_safe_leverage_ceiling": liquidation_safe_ceiling,
        "confidence_quality": confidence_quality,
        "direction_aligned_after_cost_edge_bps": direction_aligned_edge,
        "positive_direction_aligned_edge_bps": positive_aligned_edge,
        "direction_aligned_edge_source": direction_aligned_edge_source,
        "edge_volatility_quality": edge_volatility_quality,
        "continuous_market_quality": continuous_market_quality,
        "market_selection_formula": (
            "1 + (adaptive_ceiling - 1) * confidence * "
            "positive_direction_aligned_after_cost_edge_bps^2 / "
            "(positive_direction_aligned_after_cost_edge_bps^2 + "
            "current_atr_bps^2)"
        ),
        "recommended_margin_mode": "isolated",
        "liquidation_distance_bps": liquidation_distance_bps,
        "volatility_budget_bps": volatility_budget_bps,
        "volatility_budget_source": volatility_budget_source,
        "confidence_budget_pct": confidence_budget_pct,
        "max_loss_budget_usd": max_loss_budget_usd,
        "reason": reason,
        "reason_tier": reason_tier,
        "live_gate": LIVE_GATE,
        "mutates_exchange": MUTATES_EXCHANGE,
        "paper_only": True,
        "all_symbols_aggregate": False,
    }


def validate_leverage_recommendation(rec: dict) -> list[str]:
    """Return list of invariant violations. Empty = safe to use."""
    violations: list[str] = []
    if rec.get("live_gate") != LIVE_GATE:
        violations.append(f"INVARIANT_VIOLATED:live_gate must be {LIVE_GATE!r}")
    if rec.get("mutates_exchange") is not False:
        violations.append("INVARIANT_VIOLATED:mutates_exchange must be False")
    if rec.get("paper_only") is not True:
        violations.append("INVARIANT_VIOLATED:paper_only must be True")
    if rec.get("all_symbols_aggregate") is not False:
        violations.append("INVARIANT_VIOLATED:all_symbols_aggregate must be False")
    leverage = _finite_float(rec.get("recommended_leverage"))
    symbol_ceiling = symbol_leverage_ceiling(str(rec.get("symbol") or ""))
    if (
        leverage is None
        or leverage < 1.0
        or leverage > PAPER_MAX_LEVERAGE
    ):
        violations.append(
            "INVARIANT_VIOLATED:recommended_leverage must be finite in "
            f"[1,{PAPER_MAX_LEVERAGE}]"
        )
    elif leverage > symbol_ceiling:
        violations.append(
            "INVARIANT_VIOLATED:recommended_leverage "
            f"{leverage}x exceeds symbol ceiling {symbol_ceiling}x"
        )
    reported_symbol_ceiling = _finite_float(rec.get("symbol_leverage_ceiling"))
    if reported_symbol_ceiling != float(symbol_ceiling):
        violations.append(
            "INVARIANT_VIOLATED:symbol_leverage_ceiling does not match "
            "the authorized envelope"
        )
    adaptive_ceiling = _finite_float(rec.get("adaptive_leverage_ceiling"))
    liquidation_ceiling = _finite_float(
        rec.get("liquidation_safe_leverage_ceiling")
    )
    if (
        adaptive_ceiling is None
        or adaptive_ceiling < 1.0
        or adaptive_ceiling > symbol_ceiling
        or liquidation_ceiling is None
        or liquidation_ceiling < 1.0
        or adaptive_ceiling > liquidation_ceiling
    ):
        violations.append(
            "INVARIANT_VIOLATED:adaptive_leverage_ceiling exceeds a binding "
            "safety ceiling"
        )
    if leverage is not None and adaptive_ceiling is not None:
        if leverage > adaptive_ceiling:
            violations.append(
                "INVARIANT_VIOLATED:recommended_leverage exceeds "
                "adaptive_leverage_ceiling"
            )
    if rec.get("recommended_margin_mode") != "isolated":
        violations.append(
            "INVARIANT_VIOLATED:recommended_margin_mode must be isolated "
            "(never CROSS in paper mode)"
        )
    if not rec.get("symbol"):
        violations.append("MISSING_FIELD:symbol")
    return violations
