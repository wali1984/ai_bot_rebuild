"""P0 paper entry gate — symbol/timeframe/mode filter + dynamic outcome-memory.

Phase 3 remediation (2026-06-17):
    Static hard-coded symbol/timeframe exclusion frozensets are replaced with
    dynamic outcome-memory controls backed by Redis.

    The static soak-test evidence is preserved in outcome_memory.py as the
    initial fallback when no Redis data exists for a bucket. As paper trades
    accumulate, Redis data overrides the static defaults.

    Every block reason is recorded with:
        - block_reason_code (machine-parseable)
        - evidence_source (REDIS_OUTCOME_MEMORY | NO_CURRENT_OUTCOME_MEMORY_ADVISORY_BASELINE)
        - metric values that triggered the block

This gate runs BEFORE the local pre-trade, fee, and churn gates. Any intent that
fails here is added to blocked[] with a clear reason and never becomes a fill or
shadow observation. It does not interact with exchange APIs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from v2.backend.app.services.microstructure_trust.cascade_context import (
    context_allows_short_trend_paper_entry,
)

from .outcome_memory import (
    OutcomeMemoryBucket,
    OutcomeMemoryThresholds,
    evaluate_outcome_memory_bucket,
    load_outcome_memory_bucket,
)
from .side_performance import (
    SIDE_PERFORMANCE_REDIS_KEY,
    SideGateConfig,
    evaluate_side_gate,
)


def load_side_performance(redis_client: Any | None) -> dict[str, Any] | None:
    """Read the published LONG/SHORT performance buckets from Redis."""
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(SIDE_PERFORMANCE_REDIS_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class PaperEntryGateConfig:
    """Operator-configurable entry filter set.

    symbol_exclusion_list: explicit operator overrides (e.g. de-listing risk).
                           Dynamic outcome-memory blocks are separate and automatic.
    allowed_entry_timeframes: TFs permitted for new entries (default: all native TFs).
    blocked_strategy_modes: operator-configured modes blocked from new entries
                            (may still exit). Empty by default; router
                            no-trade and risk gates decide automatic blocks.
    outcome_thresholds: thresholds for dynamic outcome-memory degradation.
    """
    # Explicit operator-level symbol blocks (de-listing, regulatory, etc.)
    # Dynamic outcome-memory blocks are layered on top of these.
    symbol_exclusion_list: frozenset[str] = field(
        default_factory=lambda: frozenset(),
    )
    # Allowed timeframes for new entries
    allowed_entry_timeframes: frozenset[str] = field(
        default_factory=lambda: frozenset({"1m", "5m", "15m", "1h", "4h"}),
    )
    # Strategy modes blocked from new entries. ``reduce_size_mode`` is a
    # risk-reduced trade, not a hard no-trade condition, so it must remain
    # eligible unless an operator explicitly blocks it.
    blocked_strategy_modes: frozenset[str] = field(
        default_factory=lambda: frozenset(),
    )
    # Side+mode combinations blocked from new entries. Each element is a
    # colon-separated "side:mode" string, e.g. "long:mean_reversion_mode".
    # CG-F009: LONG mean_reversion_mode WR=21%, PF=0.25 → block LONG entries.
    # CG-F038: SHORT trend_mode was added here (2026-07-01) as an emergency hard
    #   block. Upgraded to cascade-risk regime gate (R29-D2, 2026-07-02) —
    #   see short_trend_mode_regime_gate_enabled below. Hard block removed so
    #   regime gate controls SHORT trend entries adaptively.
    blocked_side_mode_combinations: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "long:mean_reversion_mode",
        }),
    )
    # R29-D2: Regime gate for short:trend_mode entries.
    # Blocks SHORT trend entries when liquidation cascade risk is below the floor
    # (indicating a bullish/neutral market where SHORT trend has persistent losses).
    # Evidence: 743-trade B_GRADE session (Jun19-Jul1): trend SHORT WR=33%,
    # TIER_1_ATR_VOLATILITY_STOP WR=0% on 148 trades, -$247 losses.
    # During that period ETH cascade_risk was consistently < 0.05 (bullish market).
    # When True: SHORT trend entries require cascade_risk >= short_trend_cascade_risk_min
    # (or liquidation pressure_direction < short_trend_pressure_direction_max).
    # Falls back to BLOCK when liquidation data is missing or stale.
    short_trend_mode_regime_gate_enabled: bool = True
    # Minimum cascade risk required for a SHORT trend entry.
    # 0.30 = 30% of tracked longs are at liquidation risk → downward cascade likely.
    short_trend_cascade_risk_min: float = 0.30
    # R30-D1: Symbols known to produce extreme gap losses on trend_mode entries.
    # These tokens have low liquidity relative to their ATR — a sudden pump or dump
    # can move 10-100x ATR between evaluation cycles, causing catastrophic gap fills.
    # Evidence: 743-trade B_GRADE session (Jun19-Jul1):
    #   SYNUSDT: 4 trades, max loss -1150 bps (price 3x ATR in a single cycle)
    #   RAVEUSDT: -929 bps (13x ATR gap)
    #   LITUSDT: -481 bps (44x ATR, lowest liquidity)
    #   CAPUSDT: -383 bps (7.6x ATR)
    #   EPICUSDT: -294 bps (pattern: micro-cap with thin order book)
    # Only applies to trend_mode — their mean_reversion performance is tracked separately.
    trend_mode_micro_cap_exclusion: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "SYNUSDT",
            "RAVEUSDT",
            "LITUSDT",
            "CAPUSDT",
            "EPICUSDT",
        }),
    )
    # Outcome-memory degradation thresholds
    outcome_thresholds: OutcomeMemoryThresholds = field(
        default_factory=OutcomeMemoryThresholds,
    )
    # Minimum confidence required at entry (above confidence gate threshold).
    min_confidence_calibrated: float = 0.0
    # Expected move must be favorable for the requested side after all costs.
    require_positive_expected_move: bool = True
    # When True, a major-move override permits 1m/5m entries if the
    # major-move detector confirms a squeeze or breakout.
    major_move_override_enabled: bool = True


def _load_liq_regime_data(sym: str, tf: str, redis_client: Any) -> dict[str, Any] | None:
    """Load liquidation level data for regime gate; returns None if missing or stale."""
    if redis_client is None:
        return None
    try:
        key = f"v2:liquidations:levels:{sym}:{tf}"
        raw = redis_client.get(key)
        if not raw:
            return None
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else None
        if not isinstance(data, dict):
            return None
        if data.get("liquidation_is_stale"):
            return None
        return data
    except Exception:
        return None


def _load_cascade_context(sym: str, tf: str, redis_client: Any) -> dict[str, Any] | None:
    """Load structured cascade context; returns None if key is missing/invalid."""
    if redis_client is None:
        return None
    try:
        key = f"v2:microstructure:cascade_context:{sym}:{tf}"
        raw = redis_client.get(key)
        if not raw:
            return None
        data = json.loads(raw) if isinstance(raw, (str, bytes)) else None
        if not isinstance(data, dict):
            return None
        if not data.get("cascade_context_status"):
            return None
        return data
    except Exception:
        return None


def _expected_move_block_reason(
    *,
    side: str | None,
    expected_move_after_cost_bps: float,
) -> str | None:
    normalized_side = (side or "").strip().lower()
    if normalized_side == "short":
        if expected_move_after_cost_bps >= 0:
            return (
                "EXPECTED_MOVE_NOT_FAVORABLE_FOR_SIDE:"
                f"short:{expected_move_after_cost_bps:.1f}bps"
            )
        return None
    if expected_move_after_cost_bps <= 0:
        if normalized_side == "long":
            return (
                "EXPECTED_MOVE_NOT_FAVORABLE_FOR_SIDE:"
                f"long:{expected_move_after_cost_bps:.1f}bps"
            )
        return f"EXPECTED_MOVE_NON_POSITIVE:{expected_move_after_cost_bps:.1f}bps"
    return None


def expected_move_after_cost_favorable_for_side(
    *,
    side: str | None,
    expected_move_after_cost_bps: float | None,
) -> bool:
    """Return True when the signed after-cost move favors the requested side."""
    if expected_move_after_cost_bps is None:
        return False
    return _expected_move_block_reason(
        side=side,
        expected_move_after_cost_bps=expected_move_after_cost_bps,
    ) is None


def evaluate_entry_gate(
    *,
    symbol: str,
    timeframe: str | None,
    side: str | None = None,
    strategy_mode: str | None,
    confidence_calibrated: float | None,
    expected_move_after_cost_bps: float | None,
    major_move_detected: bool = False,
    outcome_memory_bucket: OutcomeMemoryBucket | None = None,
    redis_client: Any | None = None,
    config: PaperEntryGateConfig | None = None,
    side_performance: dict[str, Any] | None = None,
    side_gate_config: SideGateConfig | None = None,
) -> dict[str, Any]:
    """Return allowed=True/False with reasons list.

    Checks (in order):
        1. Explicit operator symbol exclusion
        2. Operator-configured timeframe filter
        3. Strategy mode block
        4. Minimum confidence
        5. Expected move is favorable for the requested side
        6. Dynamic outcome-memory degradation (Phase 3)
        7. Side-level performance gate (LONG/SHORT expectancy + calibration floor)

    Never raises; returns allowed=False with reasons on any unexpected input.
    Does not call external services beyond Redis. Read-only — places no orders.
    """
    cfg = config if config is not None else PaperEntryGateConfig()
    reasons: list[str] = []
    sym = (symbol or "").upper().strip()
    tf = (timeframe or "").strip().lower()
    mode = (strategy_mode or "").strip().lower()

    # 1. Explicit operator symbol exclusion
    if sym in cfg.symbol_exclusion_list:
        reasons.append(f"SYMBOL_EXPLICITLY_EXCLUDED_BY_OPERATOR:{sym}")

    # 2. Operator timeframe filter. The default allows all native paper
    # timeframes; outcome-memory quarantine handles dynamic degradation.
    _noisy_tfs = frozenset()
    if tf and tf not in cfg.allowed_entry_timeframes:
        if tf in _noisy_tfs and cfg.major_move_override_enabled and major_move_detected:
            pass  # major-move override permits noisy TF entry
        else:
            reasons.append(f"TIMEFRAME_BLOCKED:{tf}")

    # 3. Strategy mode block (mode-level) and side+mode combination block (CG-F009)
    if mode in cfg.blocked_strategy_modes:
        reasons.append(f"STRATEGY_MODE_BLOCKED:{mode}")
    normalized_side = (side or "").strip().lower()
    side_mode_key = f"{normalized_side}:{mode}"
    if side_mode_key in cfg.blocked_side_mode_combinations:
        reasons.append(f"SIDE_MODE_COMBINATION_BLOCKED:{side_mode_key}")

    # 3a. R29-D2: Regime gate for short:trend_mode.
    # CG-F038 was an emergency hard block. This adaptive gate replaces it by checking
    # the liquidation cascade risk before allowing SHORT trend entries. Block when:
    #   - no liq data (missing or stale) → conservative default is BLOCK
    #   - cascade_risk < floor → bullish/neutral market, SHORT trend loses to ATR gaps
    # Allow when cascade_risk >= floor → longs are at liquidation risk, downward cascade
    # pressure gives SHORT trend entries a structural tailwind.
    if (
        normalized_side == "short"
        and mode == "trend_mode"
        and cfg.short_trend_mode_regime_gate_enabled
        and side_mode_key not in cfg.blocked_side_mode_combinations
    ):
        cascade_context = _load_cascade_context(sym, tf, redis_client)
        if cascade_context is not None:
            context_allowed, context_reason = context_allows_short_trend_paper_entry(
                cascade_context,
                threshold=cfg.short_trend_cascade_risk_min,
            )
            if not context_allowed:
                reason = context_reason or "REGIME_GATE_NO_CASCADE_DATA"
                reasons.append(f"{reason}:short:trend_mode:{sym}:{tf}")
        else:
            liq_data = _load_liq_regime_data(sym, tf, redis_client)
            if liq_data is None:
                reasons.append(
                    f"REGIME_GATE_NO_CASCADE_DATA:short:trend_mode:{sym}:{tf}"
                )
            else:
                cascade_risk = float(liq_data.get("liquidation_cascade_risk") or 0.0)
                if cascade_risk < cfg.short_trend_cascade_risk_min:
                    reasons.append(
                        f"REGIME_GATE_INSUFFICIENT_CASCADE_RISK:"
                        f"{cascade_risk:.4f}<{cfg.short_trend_cascade_risk_min:.2f}:{sym}:{tf}"
                    )

    # 3b. R30-D1: Micro-cap gap-risk token filter for trend_mode.
    # Blocks known gap-risk tokens from trend_mode entries regardless of side.
    # These tokens produce 10-100x ATR losses due to sudden low-liquidity price gaps.
    # Mean-reversion mode is NOT blocked here — its shorter hold duration has
    # different gap exposure (tracked separately via outcome-memory).
    if mode == "trend_mode" and sym in cfg.trend_mode_micro_cap_exclusion:
        reasons.append(f"TREND_MODE_MICRO_CAP_GAP_RISK:{sym}")

    # 4. Minimum confidence
    if cfg.min_confidence_calibrated > 0 and confidence_calibrated is not None:
        if confidence_calibrated < cfg.min_confidence_calibrated:
            reasons.append(
                f"CONFIDENCE_BELOW_ENTRY_GATE:{confidence_calibrated:.3f}<{cfg.min_confidence_calibrated:.3f}"
            )

    # 5. Expected move directionality
    if cfg.require_positive_expected_move and expected_move_after_cost_bps is not None:
        move_block = _expected_move_block_reason(
            side=side,
            expected_move_after_cost_bps=expected_move_after_cost_bps,
        )
        if move_block is not None:
            reasons.append(move_block)

    # 6. Dynamic outcome-memory degradation (Phase 3)
    # Load from Redis if not pre-loaded; falls back to static soak-test defaults
    if outcome_memory_bucket is None and tf:
        outcome_memory_bucket = load_outcome_memory_bucket(sym, tf, redis_client)

    outcome_result: dict[str, Any] = {}
    if outcome_memory_bucket is not None:
        outcome_result = evaluate_outcome_memory_bucket(
            outcome_memory_bucket, cfg.outcome_thresholds
        )
        if outcome_result.get("blocked"):
            for block_reason in outcome_result.get("reasons", []):
                reasons.append(
                    f"OUTCOME_MEMORY_BLOCK:{block_reason}:"
                    f"source={outcome_result.get('source', 'UNKNOWN')}"
                )

    # 7. Side-level performance gate (Phase 2 directional-balance repair).
    # A side with non-positive expectancy over enough closed trades cannot
    # open new entries; each side has its own calibration-aware confidence floor.
    side_gate_result: dict[str, Any] = {}
    if normalized_side in {"long", "short"}:
        if side_performance is None:
            side_performance = load_side_performance(redis_client)
        side_gate_result = evaluate_side_gate(
            side_performance,
            side=normalized_side,
            confidence_calibrated=confidence_calibrated,
            config=side_gate_config,
        )
        if not side_gate_result.get("allowed", True):
            for side_reason in side_gate_result.get("reasons", []):
                reasons.append(f"SIDE_GATE_BLOCK:{side_reason}")

    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "symbol": sym,
        "timeframe": tf,
        "side": (side or "").strip().lower(),
        "side_gate_result": side_gate_result,
        "strategy_mode": mode,
        "major_move_override_applied": (
            major_move_detected and tf in _noisy_tfs and tf not in cfg.allowed_entry_timeframes
        ),
        "outcome_memory_result": outcome_result,
        "outcome_memory_source": (
            outcome_memory_bucket.data_source if outcome_memory_bucket else "NOT_LOADED"
        ),
        "places_real_order": False,
    }


def entry_gate_config_from_dict(raw: dict[str, Any]) -> PaperEntryGateConfig:
    """Build a PaperEntryGateConfig from an operator JSON config dict."""
    exclusion = frozenset(str(s).upper() for s in (raw.get("symbol_exclusion_list") or []))
    allowed_tf = frozenset(str(t).lower() for t in (raw.get("allowed_entry_timeframes") or []))
    if not allowed_tf:
        allowed_tf = frozenset({"1m", "5m", "15m", "1h", "4h"})
    blocked_modes = frozenset(str(m).lower() for m in (raw.get("blocked_strategy_modes") or []))
    if not blocked_modes:
        blocked_modes = frozenset()
    thresholds = OutcomeMemoryThresholds(
        min_win_rate=float(raw.get("min_win_rate") or 0.35),
        max_drawdown_usd=float(raw.get("max_drawdown_usd") or -10.0),
        min_rolling_ev_bps=float(raw.get("min_rolling_ev_bps") or -5.0),
        max_slippage_failure_rate=float(raw.get("max_slippage_failure_rate") or 0.40),
        max_reversal_after_entry_rate=float(raw.get("max_reversal_after_entry_rate") or 0.50),
        max_missed_tp_then_stop_rate=float(raw.get("max_missed_tp_then_stop_rate") or 0.40),
        min_trade_count_for_dynamic=int(raw.get("min_trade_count_for_dynamic") or 20),
    )
    return PaperEntryGateConfig(
        symbol_exclusion_list=exclusion,
        allowed_entry_timeframes=allowed_tf,
        blocked_strategy_modes=blocked_modes,
        outcome_thresholds=thresholds,
        min_confidence_calibrated=float(raw.get("min_confidence_calibrated") or 0.0),
        require_positive_expected_move=bool(raw.get("require_positive_expected_move", True)),
        major_move_override_enabled=bool(raw.get("major_move_override_enabled", True)),
    )
