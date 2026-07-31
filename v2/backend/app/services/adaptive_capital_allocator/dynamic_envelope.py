"""Derive paper operating limits from point-in-time performance evidence.

The supplied envelope is an immutable configured safety boundary. Operating
risk can shrink below it when realized evidence is adverse. Paper leverage
starts from the conservative default operating baseline and can earn toward,
but never exceed, the configured and per-symbol ceilings. Favorable growth also
requires a positive after-cost edge lower bound whose magnitude is evaluated
continuously against a caller-supplied data-derived scale bound to the
cohort/estimator's numeric resolution.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import UTC, datetime
from typing import Any

from ..paper_trade_management.leverage_recommendation import (
    PAPER_MAX_LEVERAGE,
    symbol_leverage_ceiling,
)
from .contracts import RiskEnvelope

_PAPER_USDM_SYMBOL_RE = re.compile(r"^[A-Z0-9]{1,26}(?:USDT|USDC)$")


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp value to range [low, high]."""
    return max(low, min(high, value))


def _finite_float(value: Any) -> float | None:
    """Return a finite number without accepting booleans as numeric evidence."""
    if type(value) is bool or value is None:
        return None
    try:
        if type(value) is str and not value.strip():
            return None
        number = float(value)
    except Exception:  # noqa: BLE001 - total untrusted scalar boundary
        return None
    return number if math.isfinite(number) else None


def _nonempty_text(value: Any) -> str | None:
    # Subclasses can override ``strip`` and return attacker-chosen text (or a
    # non-string), so only an exact built-in string is provenance evidence.
    if type(value) is not str:
        return None
    try:
        normalized = value.strip()
    except Exception:  # noqa: BLE001 - total untrusted text boundary
        return None
    return normalized or None


def _aware_utc_timestamp(value: Any) -> datetime | None:
    """Parse a timezone-aware ISO timestamp; naive timestamps are not PIT proof."""
    # Do not invoke overridable string methods on provenance timestamps. A str
    # subclass could otherwise replace invalid contents with a valid ISO value.
    if type(value) is not str:
        return None
    try:
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        parsed = datetime.fromisoformat(normalized)
    except Exception:  # noqa: BLE001 - total untrusted timestamp boundary
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(UTC)
    except Exception:  # noqa: BLE001 - total untrusted tzinfo boundary
        return None


def _paper_symbol_ceiling(value: Any) -> tuple[float, bool]:
    """Return the paper symbol ceiling without coercing hostile identities.

    ``None`` is the sole portfolio-global identity. Any populated symbol must
    be a structurally valid USD-M futures symbol before a symbol tier can be
    consumed; malformed values fail closed to 1x.
    """

    if value is None:
        return float(PAPER_MAX_LEVERAGE), True
    # Symbol identity must be the exact caller-supplied built-in string. A str
    # subclass can spoof ``strip``/``upper`` while retaining different bytes.
    if type(value) is not str:
        return 1.0, False
    try:
        normalized = value.strip().upper()
        if not normalized or _PAPER_USDM_SYMBOL_RE.fullmatch(normalized) is None:
            return 1.0, False
        raw_ceiling = symbol_leverage_ceiling(normalized)
    except Exception:  # noqa: BLE001 - total regex/tier-lookup boundary
        return 1.0, False
    ceiling = _finite_float(raw_ceiling)
    if ceiling is None or ceiling < 1.0:
        return 1.0, False
    return ceiling, True


def _edge_scale_representation_valid(
    scale: float | None,
    resolution: float | None,
) -> bool:
    """Validate a data-derived scale against its reported numeric resolution.

    The resolution is evidence about the cohort/estimator representation, not
    a market-selection threshold. Requiring a normal finite resolution, a
    scale no smaller than that resolution, and a representable finite ratio
    prevents subnormal or under-resolved scales from turning ordinary LCBs
    into near-maximal quality.
    """

    if (
        scale is None
        or resolution is None
        or scale < sys.float_info.min
        or resolution < sys.float_info.min
        or scale < resolution
        or resolution < math.ulp(scale)
    ):
        return False
    ratio = scale / resolution
    return math.isfinite(ratio) and ratio >= 1.0


def _positive_magnitude_quality(value: float, scale: float) -> float:
    """Return ``value / (value + scale)`` without overflowing the sum."""

    if value >= scale:
        return 1.0 / (1.0 + (scale / value))
    ratio = value / scale
    return ratio / (1.0 + ratio)


def _finite_defensive_product(left: float, right: float) -> float:
    """Keep a derived defensive minimum finite at the numeric boundary."""

    try:
        product = left * right
    except OverflowError:
        return sys.float_info.max
    return product if math.isfinite(product) else sys.float_info.max


def _most_restrictive_finite_envelope() -> RiskEnvelope:
    """Return the deterministic fail-closed boundary for invalid control data."""

    return RiskEnvelope(
        max_total_portfolio_risk_pct=0.0,
        max_single_symbol_exposure_pct=0.0,
        max_daily_drawdown_pct=0.0,
        max_loss_per_trade_pct=0.0,
        min_available_margin_buffer_pct=1.0,
        max_correlation_exposure_pct=0.0,
        min_liquidation_buffer_bps=10_000.0,
        max_effective_leverage=1.0,
        tail_loss_multiplier=RiskEnvelope().tail_loss_multiplier,
        emergency_absolute_cap_usdt=0.0,
    )


def _paper_safe_base(
    base: RiskEnvelope,
    *,
    operating_leverage: float,
) -> RiskEnvelope:
    """Prevent invalid paper configuration values from propagating NaN/Inf.

    Invalid maxima collapse to their most restrictive finite value. Invalid
    minimum buffers become defensive. Live mode deliberately bypasses this
    helper and continues to return the operator-supplied envelope unchanged.
    """
    defaults = RiskEnvelope()

    def maximum(value: Any) -> float:
        number = _finite_float(value)
        return number if number is not None and number >= 0.0 else 0.0

    margin_buffer = _finite_float(base.min_available_margin_buffer_pct)
    if margin_buffer is None or margin_buffer < 0.0:
        margin_buffer = 1.0
    else:
        margin_buffer = _clamp(margin_buffer, 0.0, 1.0)

    liquidation_buffer = _finite_float(base.min_liquidation_buffer_bps)
    if liquidation_buffer is None or liquidation_buffer < 0.0:
        liquidation_buffer = 10_000.0

    tail_loss_multiplier = _finite_float(base.tail_loss_multiplier)
    if tail_loss_multiplier is None or tail_loss_multiplier <= 0.0:
        tail_loss_multiplier = defaults.tail_loss_multiplier

    emergency_cap = base.emergency_absolute_cap_usdt
    if emergency_cap is not None:
        parsed_emergency_cap = _finite_float(emergency_cap)
        emergency_cap = (
            parsed_emergency_cap
            if parsed_emergency_cap is not None and parsed_emergency_cap >= 0.0
            else 0.0
        )

    return RiskEnvelope(
        max_total_portfolio_risk_pct=maximum(base.max_total_portfolio_risk_pct),
        max_single_symbol_exposure_pct=maximum(base.max_single_symbol_exposure_pct),
        max_daily_drawdown_pct=maximum(base.max_daily_drawdown_pct),
        max_loss_per_trade_pct=maximum(base.max_loss_per_trade_pct),
        min_available_margin_buffer_pct=margin_buffer,
        max_correlation_exposure_pct=maximum(base.max_correlation_exposure_pct),
        min_liquidation_buffer_bps=liquidation_buffer,
        max_effective_leverage=operating_leverage,
        tail_loss_multiplier=tail_loss_multiplier,
        emergency_absolute_cap_usdt=emergency_cap,
    )


def calculate_dynamic_risk_envelope(
    *,
    base_envelope: RiskEnvelope | None = None,
    win_rate: float | None = None,
    profit_factor: float | None = None,
    closed_trade_count: int = 0,
    current_drawdown_pct: float = 0.0,
    model_avg_confidence: float = 0.5,
    paper_mode: bool = True,
    after_cost_edge_lower_bound_bps: float | None = None,
    after_cost_edge_scale_bps: float | None = None,
    after_cost_edge_resolution_bps: float | None = None,
    after_cost_edge_evidence_count: int | float | None = None,
    after_cost_edge_evidence_source: str | None = None,
    edge_available_at: str | None = None,
    liquidity_score: float | None = None,
    regime_quality_score: float | None = None,
    market_context_source: str | None = None,
    market_context_available_at: str | None = None,
    decision_time: str | None = None,
    symbol: str | None = None,
) -> RiskEnvelope:
    """Calculate a smooth, evidence-weighted paper operating envelope.

    Live mode deliberately returns the immutable supplied envelope. Paper mode
    uses continuous shrink/growth factors, so there is no sample-count cliff.
    Source fields and timestamps are structural point-in-time checks only; this
    pure function does not authenticate provenance or authorize a live route.

    Args:
        base_envelope: Configured hard envelope (defaults to conservative cap)
        win_rate: Realized win rate [0, 1] from closed trades
        profit_factor: Realized profit factor from closed trades
        closed_trade_count: Number of closed trades (for statistical confidence)
        current_drawdown_pct: Current drawdown from peak [0, 1]
        model_avg_confidence: Average model confidence across signals [0, 1]
        paper_mode: Exact True for paper adaptation; exact False for live bypass
        after_cost_edge_lower_bound_bps: Conservative after-cost edge estimate
        after_cost_edge_scale_bps: Positive data-derived scale for edge magnitude
        after_cost_edge_resolution_bps: Positive cohort/estimator resolution
        after_cost_edge_evidence_count: Samples used for the edge lower bound
        after_cost_edge_evidence_source: Provenance for LCB, scale, and resolution
        edge_available_at: When the edge evidence became usable
        liquidity_score: Point-in-time liquidity quality [0, 1]
        regime_quality_score: Point-in-time regime compatibility [0, 1]
        market_context_source: Non-empty provenance for liquidity/regime context
        market_context_available_at: When market context became usable
        decision_time: Envelope decision timestamp; must be timezone-aware

    Returns:
        RiskEnvelope with dynamically scaled limits based on performance
    """
    # These two values are control-plane identities, not truthy/falsy inputs.
    # Exact type/identity checks avoid invoking attacker-controlled ``__bool__``
    # or envelope attributes. A RiskEnvelope subclass may override either.
    if base_envelope is None:
        supplied_base = RiskEnvelope()
    elif type(base_envelope) is RiskEnvelope:
        supplied_base = base_envelope
    else:
        return _most_restrictive_finite_envelope()

    if paper_mode is False:
        return supplied_base
    if paper_mode is not True:
        return _most_restrictive_finite_envelope()

    # Operator tiers and the supplied envelope are absolute ceilings, never
    # evidence or initial grants. Leverage operates from the conservative
    # default baseline, clamped down when the configured cap is narrower.
    symbol_ceiling, symbol_input_valid = _paper_symbol_ceiling(symbol)
    global_ceiling = _finite_float(PAPER_MAX_LEVERAGE)
    configured_ceiling = _finite_float(supplied_base.max_effective_leverage)
    if global_ceiling is None or global_ceiling < 1.0:
        global_ceiling = 1.0
    if configured_ceiling is None or configured_ceiling < 1.0:
        configured_ceiling = 1.0
    leverage_ceiling = min(
        global_ceiling,
        symbol_ceiling,
        configured_ceiling,
    )
    default_operating_leverage = _finite_float(RiskEnvelope().max_effective_leverage)
    if default_operating_leverage is None or default_operating_leverage < 1.0:
        default_operating_leverage = 1.0
    operating_leverage = min(default_operating_leverage, leverage_ceiling)
    base = _paper_safe_base(
        supplied_base,
        operating_leverage=operating_leverage,
    )

    raw_sample_count = _finite_float(closed_trade_count)
    sample_count_valid = (
        raw_sample_count is not None and raw_sample_count >= 1.0 and raw_sample_count.is_integer()
    )
    sample_count = (
        int(raw_sample_count) if raw_sample_count is not None and sample_count_valid else 0
    )

    raw_win_rate = _finite_float(win_rate)
    win_rate_valid = raw_win_rate is not None and 0.0 <= raw_win_rate <= 1.0
    bounded_win_rate = raw_win_rate if raw_win_rate is not None and win_rate_valid else 0.5

    raw_profit_factor = _finite_float(profit_factor)
    profit_factor_valid = raw_profit_factor is not None and raw_profit_factor >= 0.0
    bounded_profit_factor = (
        max(1e-6, raw_profit_factor)
        if raw_profit_factor is not None and profit_factor_valid
        else 1.0
    )

    raw_confidence = _finite_float(model_avg_confidence)
    confidence_valid = raw_confidence is not None and 0.0 <= raw_confidence <= 1.0
    bounded_confidence = raw_confidence if raw_confidence is not None and confidence_valid else 0.0

    raw_drawdown = _finite_float(current_drawdown_pct)
    drawdown_valid = raw_drawdown is not None and raw_drawdown >= 0.0
    # Unknown drawdown is not evidence for risk growth. Treat it as one full
    # base drawdown unit so paper leverage/risk contracts without raising.
    bounded_drawdown = (
        raw_drawdown
        if raw_drawdown is not None and drawdown_valid
        else max(base.max_daily_drawdown_pct, 1e-9)
    )

    # Continuous effective-evidence weight: no pass/fail sample-count cliff.
    evidence_weight = sample_count / (sample_count + 25.0)

    win_rate_evidence = 2.0 * (bounded_win_rate - 0.5)
    profit_factor_evidence = math.tanh(math.log(bounded_profit_factor))
    realized_edge_evidence = 0.5 * (win_rate_evidence + profit_factor_evidence)
    confidence_quality = 0.5 + (0.5 * bounded_confidence)
    drawdown_scale = max(base.max_daily_drawdown_pct, 1e-9)
    drawdown_pressure = bounded_drawdown / drawdown_scale

    edge_lower_bound = _finite_float(after_cost_edge_lower_bound_bps)
    edge_scale = _finite_float(after_cost_edge_scale_bps)
    edge_resolution = _finite_float(after_cost_edge_resolution_bps)
    edge_scale_representation_valid = _edge_scale_representation_valid(
        edge_scale,
        edge_resolution,
    )
    raw_edge_evidence_count = _finite_float(after_cost_edge_evidence_count)
    edge_evidence_count_valid = (
        raw_edge_evidence_count is not None
        and raw_edge_evidence_count >= 1.0
        and raw_edge_evidence_count.is_integer()
    )
    edge_evidence_count = (
        int(raw_edge_evidence_count)
        if raw_edge_evidence_count is not None and edge_evidence_count_valid
        else 0
    )

    liquidity = _finite_float(liquidity_score)
    liquidity_valid = liquidity is not None and 0.0 <= liquidity <= 1.0
    regime_quality = _finite_float(regime_quality_score)
    regime_valid = regime_quality is not None and 0.0 <= regime_quality <= 1.0

    edge_available = _aware_utc_timestamp(edge_available_at)
    context_available = _aware_utc_timestamp(market_context_available_at)
    decision = _aware_utc_timestamp(decision_time)
    point_in_time_valid = (
        edge_available is not None
        and context_available is not None
        and decision is not None
        and edge_available <= decision
        and context_available <= decision
    )

    performance_inputs_valid = (
        sample_count_valid
        and win_rate_valid
        and profit_factor_valid
        and confidence_valid
        and drawdown_valid
    )
    growth_evidence_valid = (
        performance_inputs_valid
        and symbol_input_valid
        and edge_lower_bound is not None
        and edge_lower_bound > 0.0
        and edge_scale_representation_valid
        and edge_evidence_count_valid
        and _nonempty_text(after_cost_edge_evidence_source) is not None
        and liquidity_valid
        and regime_valid
        and _nonempty_text(market_context_source) is not None
        and point_in_time_valid
    )

    # Use the smaller independently reported count, so one evidence stream
    # cannot overstate the strength of the other. Weighting remains smooth.
    if growth_evidence_valid:
        joint_evidence_count = min(sample_count, edge_evidence_count)
        growth_evidence_weight = joint_evidence_count / (joint_evidence_count + 25.0)
        assert liquidity is not None
        assert regime_quality is not None
        assert edge_lower_bound is not None
        assert edge_scale is not None
        context_quality = math.sqrt(liquidity * regime_quality)
        edge_magnitude_quality = _positive_magnitude_quality(
            edge_lower_bound,
            edge_scale,
        )
    else:
        growth_evidence_weight = 0.0
        context_quality = 0.0
        edge_magnitude_quality = 0.0

    # Operating risk never grows beyond the immutable base envelope. It
    # contracts smoothly under losing evidence or drawdown.
    risk_log_factor = (
        min(0.0, realized_edge_evidence) * evidence_weight * confidence_quality
        - 0.75 * drawdown_pressure
    )
    risk_factor = _clamp(math.exp(risk_log_factor), 0.20, 1.0)

    # Leverage may exceed the base only on positive realized evidence. Losing
    # evidence and drawdown reduce it toward 1x; confidence cannot override
    # the sign of realized evidence.
    losing_evidence_pressure = (
        min(0.0, realized_edge_evidence) * evidence_weight * confidence_quality
    )
    favorable_growth = (
        max(0.0, realized_edge_evidence)
        * growth_evidence_weight
        * confidence_quality
        * context_quality
        * edge_magnitude_quality
    )
    # Poor-but-valid liquidity/regime evidence continuously consumes only the
    # edge-supported growth. Both terms vanish with edge magnitude, avoiding a
    # downward discontinuity when the LCB moves from zero to a tiny positive
    # value. Context can withhold growth but cannot manufacture contraction.
    context_pressure = (
        (1.0 - context_quality) * growth_evidence_weight * edge_magnitude_quality * 0.5
        if growth_evidence_valid
        else 0.0
    )
    context_adjusted_favorable_growth = max(
        0.0,
        favorable_growth - context_pressure,
    )
    net_favorable_growth = context_adjusted_favorable_growth - drawdown_pressure
    if growth_evidence_valid and net_favorable_growth > 0.0:
        # Positive PIT-safe realized evidence interpolates continuously from
        # the conservative base toward the configured/symbol/global ceiling.
        # Candidate evidence and liquidation math apply additional downstream
        # contraction; the ceiling itself never grants leverage.
        growth_quality = _clamp(
            net_favorable_growth,
            0.0,
            1.0,
        )
        leverage = (
            base.max_effective_leverage
            + (leverage_ceiling - base.max_effective_leverage) * growth_quality
        )
    else:
        leverage = base.max_effective_leverage * math.exp(
            losing_evidence_pressure + min(0.0, net_favorable_growth)
        )
    leverage = _clamp(leverage, 1.0, leverage_ceiling)

    # PAPER LEARNING EXPLORATION (operator directive 2026-07-31): the paper
    # trader is a learning instrument — margin/leverage behaviour must be
    # explored (bounded) to generate the realized-outcome evidence the
    # evidence-earned growth path above requires.  Pinning the ceiling at the
    # base until positive realized edge exists is the same cold-start
    # circularity as the confidence floor: the envelope could never learn
    # sizing because it never varied sizing.  Exploration capacity
    #   - grows smoothly with observed lifecycle count (same 25-sample
    #     half-life as the evidence weight — no sample-count cliff),
    #   - is scaled by model confidence quality,
    #   - contracts exponentially under adverse realized evidence
    #     (losing_evidence_pressure <= 0) and linearly under drawdown
    #     pressure — the system pulls its own exploration back when it is
    #     losing, which IS the learning-from-mistakes contract,
    #   - is capped at HALF the distance to the hard ceiling — full ceiling
    #     access stays reserved for positive realized evidence via the
    #     growth path above,
    #   - never overrides any hard rail: symbol tiers, bracket ladders, ATR
    #     liquidation buffers, bounded-loss, margin and catastrophic
    #     validators all still bind downstream.
    exploration_progress = sample_count / (sample_count + 25.0)
    exploration_capacity = (
        exploration_progress
        * confidence_quality
        * math.exp(losing_evidence_pressure)
        * max(0.0, 1.0 - drawdown_pressure)
    )
    exploration_leverage = 1.0 + (
        0.5 * exploration_capacity * (leverage_ceiling - 1.0)
    )
    leverage = _clamp(max(leverage, exploration_leverage), 1.0, leverage_ceiling)

    defensive_factor = max(1.0, 1.0 / risk_factor)
    return RiskEnvelope(
        max_total_portfolio_risk_pct=base.max_total_portfolio_risk_pct * risk_factor,
        max_single_symbol_exposure_pct=base.max_single_symbol_exposure_pct * risk_factor,
        max_daily_drawdown_pct=base.max_daily_drawdown_pct * risk_factor,
        max_loss_per_trade_pct=base.max_loss_per_trade_pct * risk_factor,
        max_correlation_exposure_pct=base.max_correlation_exposure_pct * risk_factor,
        max_effective_leverage=leverage,
        min_available_margin_buffer_pct=_clamp(
            base.min_available_margin_buffer_pct * defensive_factor,
            base.min_available_margin_buffer_pct,
            1.0,
        ),
        min_liquidation_buffer_bps=_finite_defensive_product(
            base.min_liquidation_buffer_bps,
            defensive_factor,
        ),
        tail_loss_multiplier=base.tail_loss_multiplier,
        emergency_absolute_cap_usdt=base.emergency_absolute_cap_usdt,
    )
