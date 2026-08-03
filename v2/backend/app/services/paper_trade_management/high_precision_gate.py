"""High-precision paper-only abstention gate.

This gate is production-equivalent: the same thresholds would apply to live
execution if the live adapter were enabled. It selects a high-confidence subset
of signals for paper fills, preferring fewer trades with stronger multi-source
evidence over forcing coverage on every prediction.

Architecture principle:
    Paper trading is production shadow execution. The only difference from live
    is the execution adapter. This gate must not use simplified thresholds or
    paper-only shortcuts that would not transfer to live.

Abstention semantics:
    When the gate abstains, no paper fill is issued. The signal is still a
    SHADOW_OBSERVATION_ONLY and its features are still recorded for trainer
    learning. Abstention is not suppression — it is a deliberate no-trade
    decision that the trainer can learn from.

Hard rules (same as live gate):
    - No real orders, no test-order, no leverage/margin mutation.
    - Live execution remains blocked.
    - No exchange SDK import.
    - No old Redis keys written.

Phase 4 thresholds (2026-06-17):
    Evidence: 23-30% paper win rate with min_confidence=0.60, min_edge_bps=8.0.
    Stricter thresholds reduce trade count while improving selection quality.
    min_confidence raised to 0.75 (was 0.60).
    min_edge_bps raised to 15.0 (was 8.0) — covers 2x typical slippage.
    min_data_coverage_pct raised to 85.0 (was 70.0).
    require_multi_tf_agreement added (was absent).
    require_orderbook_confirmation added (was absent).
    required_feature_families expanded from 3 to 12 critical families.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .feature_family_classifier import (
    CRITICAL_FEATURE_FAMILIES,
    classify_feature_families,
    feature_family_coverage_summary,
)


@dataclass(frozen=True)
class HighPrecisionGateConfig:
    # ── Phase 4: stricter thresholds ──────────────────────────────────────────
    # Minimum calibrated confidence for a paper fill (0-1 scale)
    # Raised from 0.60 → 0.75 (evidence: 23-30% WR at 0.60)
    min_confidence: float = 0.75
    # Minimum signed expected edge after cost (bps). For shorts this is
    # |expected_move_after_cost_bps| (already sign-normalized by caller).
    # Raised from 8.0 → 15.0 (covers 2x typical slippage + fee margin)
    min_edge_bps: float = 15.0
    # Minimum evidence score from major-move or breakout detector (0-1)
    min_evidence_score: float = 0.0  # 0 = gate is open unless other checks fail
    # Minimum data coverage percentage (0-100)
    # Raised from 70.0 → 85.0 (evidence: current rows at 77% still have 20 missing features)
    min_data_coverage_pct: float = 85.0
    # Minimum market state integrity score (0-100)
    min_market_integrity_score: float = 70.0
    # ── Phase 2: full feature family coverage ─────────────────────────────────
    # When True, abstain if any required feature family is missing
    require_full_feature_coverage: bool = True
    # Required feature families for gate to pass when require_full_feature_coverage=True.
    # Expanded from 3 → 12 critical families (Phase 2 remediation).
    required_feature_families: tuple[str, ...] = field(
        default_factory=lambda: CRITICAL_FEATURE_FAMILIES,
    )
    # ── Phase 4: multi-timeframe agreement ────────────────────────────────────
    # Require that at least min_multi_tf_agree_count timeframes agree on direction.
    require_multi_tf_agreement: bool = True
    # Minimum number of TFs that must agree (of those with valid predictions).
    min_multi_tf_agree_count: int = 2
    # ── Phase 4: orderbook/liquidity confirmation ─────────────────────────────
    # Require positive orderbook imbalance aligned with trade direction.
    require_orderbook_confirmation: bool = True
    # Minimum orderbook imbalance aligned with direction (positive = buy-side pressure).
    # 0.0 = any non-zero positive imbalance accepted.
    min_orderbook_imbalance_aligned: float = 0.0
    # ── Phase 4: outcome bucket health ───────────────────────────────────────
    # Require that the recent outcome bucket for this (symbol, timeframe) is not degraded.
    require_outcome_bucket_healthy: bool = True
    # Set to True to hard-block paper fills from this gate (manual override)
    gate_blocked: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(f"min_confidence must be 0-1, got {self.min_confidence}")
        if self.min_edge_bps < 0:
            raise ValueError(f"min_edge_bps must be >= 0, got {self.min_edge_bps}")


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return v


def _signed_edge_after_cost(action: str, raw_bps: float | None) -> float | None:
    """Return the trade-perspective edge in bps (always positive when in-favour).

    For longs: raw_bps > 0 is positive edge.
    For shorts: raw_bps < 0 means price expected to fall — positive edge for short.
                We return abs(raw_bps) so callers can compare against a positive threshold.
    """
    if raw_bps is None:
        return None
    if str(action).lower() == "short":
        return abs(raw_bps)
    return raw_bps


def evaluate_high_precision_gate(
    *,
    action: str,
    confidence_calibrated: float | None,
    expected_move_after_cost_bps: float | None,
    data_coverage_pct: float | None,
    market_state_integrity_score: float | None,
    evidence_score: float | None = None,
    present_feature_families: set[str] | None = None,
    # Phase 4: new parameters
    agreeing_timeframe_count: int | None = None,
    orderbook_imbalance_aligned: float | None = None,
    outcome_bucket_degraded: bool = False,
    # Prediction dict for inline family classification (alternative to present_feature_families)
    prediction: Mapping[str, Any] | None = None,
    config: HighPrecisionGateConfig | None = None,
) -> dict[str, Any]:
    """Evaluate whether this candidate clears the high-precision gate.

    Returns a dict with:
        allow: bool  — True means the gate approves a paper fill.
        abstain: bool — True means deliberate no-trade (weak evidence).
        reasons: list[str] — why the gate blocked/abstained.
        diagnostics: dict — values used for the decision.
        feature_coverage: dict — family-level coverage summary.

    The gate never sets paper_fill_allowed=True for live or any exchange action.
    """
    cfg = config or HighPrecisionGateConfig()
    reasons: list[str] = []

    if cfg.gate_blocked:
        return {
            "allow": False,
            "abstain": True,
            "reasons": ["GATE_MANUALLY_BLOCKED"],
            "diagnostics": {},
            "feature_coverage": {},
            "paper_only": True,
            "places_real_order": False,
            "live_gate": "blocked_human_only",
        }

    conf = _coerce_float(confidence_calibrated)
    signed_edge = _signed_edge_after_cost(action, _coerce_float(expected_move_after_cost_bps))
    coverage = _coerce_float(data_coverage_pct)
    integrity = _coerce_float(market_state_integrity_score)
    ev_score = _coerce_float(evidence_score)

    # ── Condition 1: confidence ───────────────────────────────────────────────
    if conf is None:
        reasons.append("CONFIDENCE_MISSING")
    elif conf < cfg.min_confidence:
        reasons.append(f"CONFIDENCE_BELOW_THRESHOLD:{conf:.4f}<{cfg.min_confidence:.4f}")

    # ── Condition 2: edge after cost ──────────────────────────────────────────
    if signed_edge is None:
        reasons.append("EXPECTED_EDGE_MISSING")
    elif signed_edge < cfg.min_edge_bps:
        reasons.append(f"EDGE_BELOW_THRESHOLD:{signed_edge:.2f}<{cfg.min_edge_bps:.2f}bps")

    # ── Condition 3: data coverage ────────────────────────────────────────────
    if coverage is None:
        reasons.append("DATA_COVERAGE_MISSING")
    elif coverage < cfg.min_data_coverage_pct:
        reasons.append(f"COVERAGE_BELOW_THRESHOLD:{coverage:.1f}%<{cfg.min_data_coverage_pct:.1f}%")

    # ── Condition 4: market integrity ─────────────────────────────────────────
    if integrity is None:
        reasons.append("MARKET_INTEGRITY_SCORE_MISSING")
    elif integrity < cfg.min_market_integrity_score:
        reasons.append(f"MARKET_INTEGRITY_BELOW_THRESHOLD:{integrity:.1f}<{cfg.min_market_integrity_score:.1f}")

    if ev_score is not None and ev_score < cfg.min_evidence_score:
        reasons.append(f"EVIDENCE_SCORE_BELOW_THRESHOLD:{ev_score:.4f}<{cfg.min_evidence_score:.4f}")

    # ── Condition 5: feature family coverage (Phase 2) ────────────────────────
    # Derive present families from prediction dict if not explicitly passed.
    # When feature_names is absent (common in production rows), the classifier
    # automatically uses inference mode: a family is MISSING_CONFIRMED only when
    # ALL its canonical members appear in missing_feature_names.
    _classification_mode = "normal"
    if present_feature_families is None and prediction is not None:
        _fn = list(prediction.get("feature_names") or [])
        _mfn = list(prediction.get("missing_feature_names") or [])
        if not _fn and _mfn:
            _classification_mode = "inference_missing_names_only"
        present_feature_families, _ = classify_feature_families(
            feature_names=_fn,
            missing_feature_names=_mfn,
        )

    coverage_summary: dict[str, Any] = {}
    if cfg.require_full_feature_coverage and cfg.required_feature_families:
        present = present_feature_families or set()
        missing = sorted(f for f in cfg.required_feature_families if f not in present)
        if missing:
            reasons.append(f"MISSING_FEATURE_FAMILIES:{','.join(missing)}")
        if present_feature_families is not None:
            coverage_summary = feature_family_coverage_summary(
                present, set(missing), classification_mode=_classification_mode
            )

    # ── Condition 6: multi-TF agreement (Phase 4) ─────────────────────────────
    if cfg.require_multi_tf_agreement:
        if agreeing_timeframe_count is None:
            # Not provided — cannot verify; block with explanation
            reasons.append("MULTI_TF_AGREEMENT_NOT_PROVIDED")
        elif agreeing_timeframe_count < cfg.min_multi_tf_agree_count:
            reasons.append(
                f"MULTI_TF_AGREEMENT_INSUFFICIENT:{agreeing_timeframe_count}<{cfg.min_multi_tf_agree_count}"
            )

    # ── Condition 7: orderbook confirmation (Phase 4) ─────────────────────────
    if cfg.require_orderbook_confirmation:
        if orderbook_imbalance_aligned is None:
            reasons.append("ORDERBOOK_IMBALANCE_NOT_PROVIDED")
        elif orderbook_imbalance_aligned <= cfg.min_orderbook_imbalance_aligned:
            reasons.append(
                f"ORDERBOOK_IMBALANCE_UNALIGNED:{orderbook_imbalance_aligned:.4f}<={cfg.min_orderbook_imbalance_aligned:.4f}"
            )

    # ── Condition 8: outcome bucket health (Phase 4) ──────────────────────────
    if cfg.require_outcome_bucket_healthy and outcome_bucket_degraded:
        reasons.append("OUTCOME_BUCKET_DEGRADED")

    allow = len(reasons) == 0
    return {
        "allow": allow,
        "abstain": not allow,
        "reasons": reasons,
        "diagnostics": {
            "confidence_calibrated": conf,
            "signed_edge_after_cost_bps": signed_edge,
            "data_coverage_pct": coverage,
            "market_state_integrity_score": integrity,
            "evidence_score": ev_score,
            "action": action,
            "agreeing_timeframe_count": agreeing_timeframe_count,
            "orderbook_imbalance_aligned": orderbook_imbalance_aligned,
            "outcome_bucket_degraded": outcome_bucket_degraded,
            "min_confidence_threshold": cfg.min_confidence,
            "min_edge_bps_threshold": cfg.min_edge_bps,
            "min_data_coverage_pct_threshold": cfg.min_data_coverage_pct,
            "min_market_integrity_score_threshold": cfg.min_market_integrity_score,
            "min_multi_tf_agree_count": cfg.min_multi_tf_agree_count,
        },
        "feature_coverage": coverage_summary,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }
