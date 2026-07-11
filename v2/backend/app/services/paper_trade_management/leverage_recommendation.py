"""Phase 8: Per-trade paper-only leverage and margin recommendations.

Produces a recommendation dict for each individual trade signal.
NEVER mutates exchange leverage or margin settings.
NEVER produces ALL_SYMBOLS aggregate recommendations for trade decisions.
All recommendations are paper-only and require human approval before live use.

Fields produced per recommendation:
    recommended_leverage: int (1–3 in paper mode)
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

from dataclasses import dataclass
from typing import Any

LIVE_GATE = "blocked_human_only"
MUTATES_EXCHANGE = False
SCHEMA_VERSION = "v2_leverage_recommendation_v1"

# Hard caps for paper mode — never recommend above these.
PAPER_MAX_LEVERAGE = 3
PAPER_MAX_CONFIDENCE_BUDGET_PCT = 0.05  # 5% of equity max per trade
PAPER_MAX_LOSS_BUDGET_USD = 50.0


@dataclass(frozen=True)
class LeverageRecommendationConfig:
    max_leverage: int = PAPER_MAX_LEVERAGE
    max_confidence_budget_pct: float = PAPER_MAX_CONFIDENCE_BUDGET_PCT
    max_loss_budget_usd: float = PAPER_MAX_LOSS_BUDGET_USD
    # Confidence thresholds for leverage tiers
    high_confidence_threshold: float = 0.75
    low_confidence_threshold: float = 0.55
    # Volatility thresholds (ATR in bps) for leverage tiers
    low_volatility_threshold_bps: float = 30.0
    high_volatility_threshold_bps: float = 80.0
    # Fee + slippage buffer for liquidation distance estimate
    liquidation_fee_buffer_bps: float = 25.0


def _estimate_liquidation_distance_bps(leverage: int, fee_buffer_bps: float) -> float:
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
    if confidence <= 0:
        return 0.01
    return round(min(max_pct, max_pct * confidence), 4)


def _compute_volatility_budget(atr_bps: float | None, leverage: int) -> float:
    """Volatility budget in bps: how much of the move is 'expected' per period.

    Used to set soft stop awareness. Higher ATR → wider expected move.
    """
    if atr_bps is None or atr_bps <= 0:
        return 30.0  # default: 30 bps uncertainty
    # Budget = ATR * leverage (scaled risk per unit notional)
    return round(min(300.0, atr_bps * leverage), 2)


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
    sym = symbol.upper().strip()
    tf = timeframe.lower().strip()

    # Determine recommended leverage from confidence + volatility profile.
    # A non-positive after-cost expectation must never be levered: leverage is a
    # derived value from *positive* risk-adjusted edge, so a negative/zero edge
    # caps at 1x before confidence/volatility are even considered. (The composite
    # allocator also caps small/negative edge to 1x; this keeps the standalone
    # recommendation self-consistent for external verifiers.)
    if (
        expected_move_after_cost_bps is not None
        and expected_move_after_cost_bps <= 0.0
    ):
        recommended_leverage = 1
        reason_tier = "NON_POSITIVE_AFTER_COST_EDGE_1X"
    elif direction == "flat" or confidence_calibrated < cfg.low_confidence_threshold:
        recommended_leverage = 1
        reason_tier = "FLAT_OR_LOW_CONFIDENCE_1X"
    elif (
        atr_bps is not None
        and atr_bps >= cfg.high_volatility_threshold_bps
    ):
        recommended_leverage = 1
        reason_tier = "HIGH_VOLATILITY_1X"
    elif (
        confidence_calibrated >= cfg.high_confidence_threshold
        and (atr_bps is None or atr_bps <= cfg.low_volatility_threshold_bps)
    ):
        recommended_leverage = min(cfg.max_leverage, 3)
        reason_tier = "HIGH_CONFIDENCE_LOW_VOLATILITY_3X"
    else:
        recommended_leverage = min(cfg.max_leverage, 2)
        reason_tier = "MODERATE_CONFIDENCE_OR_VOLATILITY_2X"

    liquidation_distance_bps = _estimate_liquidation_distance_bps(
        recommended_leverage, cfg.liquidation_fee_buffer_bps
    )
    confidence_budget_pct = _compute_confidence_budget(
        confidence_calibrated, cfg.max_confidence_budget_pct
    )
    volatility_budget_bps = _compute_volatility_budget(atr_bps, recommended_leverage)

    # Max loss budget: lesser of config cap and confidence-scaled equity fraction
    if equity_usd and equity_usd > 0:
        max_loss_from_equity = equity_usd * confidence_budget_pct * recommended_leverage * 0.1
        max_loss_budget_usd = round(min(cfg.max_loss_budget_usd, max_loss_from_equity), 2)
    else:
        max_loss_budget_usd = cfg.max_loss_budget_usd

    reason = (
        f"{reason_tier}|symbol={sym}|tf={tf}|"
        f"confidence={confidence_calibrated:.3f}|"
        f"atr_bps={atr_bps}|"
        f"expected_move={expected_move_after_cost_bps}|"
        f"lev={recommended_leverage}x|margin=isolated|"
        f"liq_dist={liquidation_distance_bps:.0f}bps"
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "symbol": sym,
        "timeframe": tf,
        "signal_id": signal_id,
        "direction": direction,
        "recommended_leverage": recommended_leverage,
        "recommended_margin_mode": "isolated",
        "liquidation_distance_bps": liquidation_distance_bps,
        "volatility_budget_bps": volatility_budget_bps,
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
    lev = rec.get("recommended_leverage")
    if not isinstance(lev, int) or lev < 1 or lev > PAPER_MAX_LEVERAGE:
        violations.append(f"INVARIANT_VIOLATED:recommended_leverage must be int in [1,{PAPER_MAX_LEVERAGE}]")
    if rec.get("recommended_margin_mode") != "isolated":
        violations.append("INVARIANT_VIOLATED:recommended_margin_mode must be isolated (never CROSS in paper mode)")
    if not rec.get("symbol"):
        violations.append("MISSING_FIELD:symbol")
    return violations
