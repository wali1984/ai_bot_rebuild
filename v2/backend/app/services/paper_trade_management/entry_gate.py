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

from dataclasses import dataclass, field
from typing import Any

from .outcome_memory import (
    OutcomeMemoryBucket,
    OutcomeMemoryThresholds,
    evaluate_outcome_memory_bucket,
    load_outcome_memory_bucket,
)


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
    blocked_side_mode_combinations: frozenset[str] = field(
        default_factory=lambda: frozenset({"long:mean_reversion_mode"}),
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
) -> dict[str, Any]:
    """Return allowed=True/False with reasons list.

    Checks (in order):
        1. Explicit operator symbol exclusion
        2. Operator-configured timeframe filter
        3. Strategy mode block
        4. Minimum confidence
        5. Expected move is favorable for the requested side
        6. Dynamic outcome-memory degradation (Phase 3)

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

    return {
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "symbol": sym,
        "timeframe": tf,
        "side": (side or "").strip().lower(),
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
