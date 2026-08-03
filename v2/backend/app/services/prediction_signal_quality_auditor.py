"""Prediction signal quality auditor.

Audits each (symbol, timeframe) prediction row produced by
``all_timeframe_prediction_signal_price_target_publisher`` and answers:

  1. Is the prediction fresh enough to be a paper candidate?
  2. Are all required feature families covered?
  3. Is there any point-in-time (PIT) leakage?
  4. What is the actionability reason code and explanation?
  5. Is the row operator-reviewable (all explanation fields present)?

Point-in-time leakage rule
~~~~~~~~~~~~~~~~~~~~~~~~~~
A prediction row is PIT-safe if every feature used to produce it was
*available* at or before ``decision_cutoff_time_est``. The audit derives
this from fields the publisher already computes:

  market_state_reject_reasons
      ``feature_timestamp_after_decision_cutoff`` → FUTURE_LEAKAGE
      ``source_available_after_decision_cutoff``  → FUTURE_LEAKAGE
      ``BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME`` → BACKFILLED

  decision_cutoff_time_est
      Must be present; absence flagged as MISSING_DECISION_CUTOFF.

  market_state_source_lineage.source_event_time_est
      Must be <= decision_cutoff_time_est (validated independently of
      the market-state scorer so the check is self-contained).

If any PIT violation is detected, the row is excluded from paper
candidates regardless of freshness or confidence.

Stale exclusion rule
~~~~~~~~~~~~~~~~~~~~
Rows with ``freshness_seconds`` > ``stale_seconds`` OR with a status
outside CURRENT_PREDICTION_STATUSES are excluded from paper candidates.
Rows excluded by staleness retain their PIT audit result so root-cause
analysis can distinguish "stale but clean" from "stale AND leaking".
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

SERVICE_ID = "v2_prediction_signal_quality_auditor"
SCHEMA_VERSION = "v2_prediction_signal_quality_auditor_v1"
LIVE_GATE = "blocked_human_only"

# Statuses from the publisher that represent a current, consumable prediction.
CURRENT_PREDICTION_STATUSES = frozenset(
    {
        "PRESENT_CURRENT",
        "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY",
    }
)

# reason-code tokens in market_state_reject_reasons that indicate PIT leakage.
PIT_LEAKAGE_REASON_TOKENS = frozenset(
    {
        "feature_timestamp_after_decision_cutoff",
        "source_available_after_decision_cutoff",
        "FUTURE_LEAKAGE",
    }
)

BACKFILL_REASON_TOKENS = frozenset(
    {
        "BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME",
        "backfilled_not_available_at_decision_time",
    }
)

# Confidence floor below which a directional action is not paper-actionable.
DEFAULT_CONFIDENCE_FLOOR = 0.58


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _to_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    import math

    return result if math.isfinite(result) else None


# ---------------------------------------------------------------------------
# PIT safety
# ---------------------------------------------------------------------------


def validate_pit_safety(row: Mapping[str, Any]) -> dict[str, Any]:
    """Check point-in-time safety for a single prediction row.

    Returns a dict with:
      status         CLEAN | FUTURE_LEAKAGE | BACKFILLED | MISSING_DECISION_CUTOFF
      violations     list of violation token strings
      explanation    human-readable single sentence
      fields         raw extracted timestamp strings for auditability
    """
    reject_reasons = _as_list(row.get("market_state_reject_reasons"))
    source_lineage = _as_dict(row.get("market_state_source_lineage"))

    leakage_violations = [r for r in reject_reasons if r in PIT_LEAKAGE_REASON_TOKENS]
    backfill_violations = [r for r in reject_reasons if r in BACKFILL_REASON_TOKENS]

    decision_cutoff_raw = (
        row.get("decision_cutoff_time_est")
        or source_lineage.get("decision_cutoff_time_est")
        or _as_dict(row.get("source_lineage")).get("prediction_generated_est")
    )
    source_event_raw = (
        source_lineage.get("source_event_time_est")
        or source_lineage.get("source_event_time_utc")
    )
    source_available_raw = source_lineage.get("source_available_at_decision_time")

    # Independent timestamp check (redundant with scorer but self-contained for audit).
    extra_violations: list[str] = []
    decision_dt = _parse_ts(decision_cutoff_raw)
    source_event_dt = _parse_ts(source_event_raw)
    source_available_dt = _parse_ts(source_available_raw)

    if source_event_dt and decision_dt and source_event_dt > decision_dt:
        if "feature_timestamp_after_decision_cutoff" not in leakage_violations:
            extra_violations.append("feature_timestamp_after_decision_cutoff")
    if source_available_dt and decision_dt and source_available_dt > decision_dt:
        if "source_available_after_decision_cutoff" not in leakage_violations:
            extra_violations.append("source_available_after_decision_cutoff")

    all_leakage = leakage_violations + extra_violations
    all_backfill = backfill_violations

    if all_leakage:
        status = "FUTURE_LEAKAGE"
        explanation = (
            f"PIT violation: features arrived after decision cutoff "
            f"({', '.join(all_leakage)}). Row excluded from paper candidates."
        )
    elif all_backfill:
        status = "BACKFILLED"
        explanation = (
            "Feature data was backfilled after the decision point. "
            "Row excluded from paper candidates."
        )
    elif not decision_cutoff_raw:
        status = "MISSING_DECISION_CUTOFF"
        explanation = (
            "decision_cutoff_time_est is absent — cannot prove PIT safety. "
            "Row excluded from paper candidates."
        )
    else:
        status = "CLEAN"
        explanation = (
            f"All feature timestamps <= decision_cutoff_time_est "
            f"({decision_cutoff_raw}). No PIT leakage detected."
        )

    return {
        "status": status,
        "violations": all_leakage + all_backfill,
        "explanation": explanation,
        "fields": {
            "decision_cutoff_time_est": decision_cutoff_raw,
            "source_event_time_est": source_event_raw,
            "source_available_at_decision_time": source_available_raw,
        },
    }


# ---------------------------------------------------------------------------
# Actionability
# ---------------------------------------------------------------------------


def compute_actionability(
    row: Mapping[str, Any],
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> dict[str, Any]:
    """Derive actionability reason code and explanation for a prediction row.

    Returns:
      actionable         bool
      reason_code        string token
      explanation        human sentence
      confidence         float | None
      action             string
    """
    status = str(row.get("status") or "")
    action = str(row.get("selected_action") or "hold").lower()
    confidence = _to_float(row.get("confidence_calibrated"))
    freshness = _to_float(row.get("freshness_seconds"))
    valid_for_prediction = row.get("valid_for_prediction")
    valid_for_paper = row.get("valid_for_paper")

    if status not in CURRENT_PREDICTION_STATUSES:
        return {
            "actionable": False,
            "reason_code": "prediction_not_current",
            "explanation": (
                f"Prediction status is {status!r}, not in current statuses. "
                "Cannot assess actionability."
            ),
            "confidence": confidence,
            "action": action,
        }

    if action not in ("long", "short"):
        return {
            "actionable": False,
            "reason_code": "non_directional_action",
            "explanation": (
                f"Action is {action!r} (not long or short). No directional trade intent."
            ),
            "confidence": confidence,
            "action": action,
        }

    if confidence is None:
        return {
            "actionable": False,
            "reason_code": "confidence_missing",
            "explanation": "confidence_calibrated is absent — cannot evaluate against floor.",
            "confidence": None,
            "action": action,
        }

    if confidence < confidence_floor:
        return {
            "actionable": False,
            "reason_code": "below_confidence_floor",
            "explanation": (
                f"Calibrated confidence {confidence:.4f} < floor {confidence_floor}. "
                "Signal below quality threshold."
            ),
            "confidence": confidence,
            "action": action,
        }

    if valid_for_prediction is False:
        return {
            "actionable": False,
            "reason_code": "market_state_invalid_for_prediction",
            "explanation": (
                "Market state integrity check failed (valid_for_prediction=False). "
                "Feature snapshot rejected by scorer."
            ),
            "confidence": confidence,
            "action": action,
        }

    if valid_for_paper is False:
        return {
            "actionable": False,
            "reason_code": "market_state_invalid_for_paper",
            "explanation": (
                "Market state integrity check failed (valid_for_paper=False). "
                "Paper fill gate rejected the snapshot."
            ),
            "confidence": confidence,
            "action": action,
        }

    return {
        "actionable": True,
        "reason_code": "actionable",
        "explanation": (
            f"Action {action!r} with confidence {confidence:.4f} >= floor "
            f"{confidence_floor}, prediction is current, market state valid."
        ),
        "confidence": confidence,
        "action": action,
    }


# ---------------------------------------------------------------------------
# Feature family coverage
# ---------------------------------------------------------------------------

_KNOWN_FAMILIES = ("market", "ohlcv", "orderbook", "ta", "liquidation", "microstructure", "altdata")


def summarize_feature_coverage(row: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize feature family coverage from a prediction row.

    Uses ``data_coverage_percent``, ``missing_feature_count``,
    ``stale_feature_count``, ``missing_feature_names``, and
    ``stale_feature_names`` already embedded in the prediction row by
    the publisher.
    """
    coverage_pct = _to_float(row.get("data_coverage_percent"))
    missing_count = row.get("missing_feature_count")
    stale_count = row.get("stale_feature_count")
    missing_names = _as_list(row.get("missing_feature_names"))
    stale_names = _as_list(row.get("stale_feature_names"))
    paper_gate_block_reasons = _as_list(row.get("paper_fill_gate_block_reasons"))

    # Derive family presence from missing field names.
    missing_families: list[str] = []
    for name in missing_names:
        lname = str(name).lower()
        for fam in _KNOWN_FAMILIES:
            if fam in lname and fam not in missing_families:
                missing_families.append(fam)

    coverage_status = "UNKNOWN"
    if coverage_pct is not None:
        if coverage_pct >= 95.0:
            coverage_status = "HIGH"
        elif coverage_pct >= 70.0:
            coverage_status = "PARTIAL"
        else:
            coverage_status = "LOW"

    missing_critical = "MISSING_CRITICAL_FEATURE_FAMILY" in _as_list(
        row.get("market_state_reject_reasons")
    )

    return {
        "data_coverage_percent": coverage_pct,
        "coverage_status": coverage_status,
        "missing_feature_count": missing_count,
        "stale_feature_count": stale_count,
        "missing_feature_names_sample": missing_names[:10],
        "stale_feature_names_sample": stale_names[:10],
        "missing_families_inferred": missing_families,
        "missing_critical_feature_family": missing_critical,
        "paper_gate_block_reasons": paper_gate_block_reasons,
    }


# ---------------------------------------------------------------------------
# Per-row audit
# ---------------------------------------------------------------------------


def audit_prediction_row(
    row: Mapping[str, Any],
    *,
    stale_seconds: int = 900,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> dict[str, Any]:
    """Return a quality audit record for a single (symbol, timeframe) row.

    The returned dict contains all required fields for operator review:
      - freshness/staleness explanation
      - actionability explanation with reason_code
      - PIT safety audit
      - feature coverage summary
      - excluded_from_paper_candidates (bool) with reason
    """
    symbol = str(row.get("symbol") or "UNKNOWN").upper()
    timeframe = str(row.get("timeframe") or "unknown")
    status = str(row.get("status") or "UNKNOWN")
    freshness = _to_float(row.get("freshness_seconds"))

    # Freshness assessment.
    if status not in CURRENT_PREDICTION_STATUSES:
        fresh = False
        freshness_explanation = (
            f"Prediction status is {status!r} — not in accepted current statuses. "
            f"Row is not a paper candidate."
        )
    elif freshness is None:
        fresh = False
        freshness_explanation = (
            "freshness_seconds is absent — cannot verify prediction age. "
            "Treating as stale."
        )
    elif freshness > stale_seconds:
        fresh = False
        freshness_explanation = (
            f"Prediction age {freshness:.0f}s > threshold {stale_seconds}s. "
            "Stale — excluded from paper candidates."
        )
    else:
        fresh = True
        freshness_explanation = (
            f"Prediction age {freshness:.0f}s <= threshold {stale_seconds}s. "
            "Fresh — eligible for paper review."
        )

    if status == "MISSING_TF_PREDICTION":
        # No prediction row exists — PIT check is not applicable.
        # Absence of data is not a PIT safety violation; it is an absence of a
        # candidate. The row is already excluded as NOT_FRESH. Do not treat it
        # as MISSING_DECISION_CUTOFF (which would imply a real row had no lineage).
        pit = {
            "status": "CLEAN",
            "violations": [],
            "explanation": "No prediction row exists for this symbol/timeframe — PIT check not applicable.",
            "fields": {
                "decision_cutoff_time_est": None,
                "source_event_time_est": None,
                "source_available_at_decision_time": None,
            },
        }
        pit_safe = True
    else:
        pit = validate_pit_safety(row)
        pit_safe = pit["status"] == "CLEAN"

    actionability = compute_actionability(row, confidence_floor=confidence_floor)
    coverage = summarize_feature_coverage(row)

    # Exclusion logic: stale OR PIT violation OR missing critical family.
    exclusion_reasons: list[str] = []
    if not fresh:
        exclusion_reasons.append(f"NOT_FRESH:{status}")
    if not pit_safe:
        exclusion_reasons.append(f"PIT_VIOLATION:{pit['status']}")
    if coverage.get("missing_critical_feature_family"):
        exclusion_reasons.append("MISSING_CRITICAL_FEATURE_FAMILY")

    excluded_from_paper = bool(exclusion_reasons)

    operator_explanation = _build_operator_explanation(
        symbol=symbol,
        timeframe=timeframe,
        fresh=fresh,
        freshness_explanation=freshness_explanation,
        pit=pit,
        actionability=actionability,
        coverage=coverage,
        excluded=excluded_from_paper,
        exclusion_reasons=exclusion_reasons,
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "prediction_id": row.get("prediction_id"),
        "prediction_status": status,
        "freshness_seconds": freshness,
        "is_fresh": fresh,
        "freshness_explanation": freshness_explanation,
        "pit_safety": pit,
        "actionability": actionability,
        "feature_coverage": coverage,
        "excluded_from_paper_candidates": excluded_from_paper,
        "exclusion_reasons": exclusion_reasons,
        "operator_explanation": operator_explanation,
        "market_state_integrity_score": _to_float(row.get("market_state_integrity_score")),
        "market_state_reject_reasons": _as_list(row.get("market_state_reject_reasons")),
        "valid_for_prediction": row.get("valid_for_prediction"),
        "valid_for_paper": row.get("valid_for_paper"),
        "source_lineage_summary": {
            "prediction_redis_key": _as_dict(row.get("source_lineage")).get("prediction_redis_key"),
            "trainer_source": row.get("trainer_source"),
            "model_source": row.get("model_source"),
            "decision_cutoff_time_est": pit["fields"]["decision_cutoff_time_est"],
        },
    }


def _build_operator_explanation(
    *,
    symbol: str,
    timeframe: str,
    fresh: bool,
    freshness_explanation: str,
    pit: dict[str, Any],
    actionability: dict[str, Any],
    coverage: dict[str, Any],
    excluded: bool,
    exclusion_reasons: list[str],
) -> str:
    parts = [f"[{symbol}/{timeframe}]"]
    if excluded:
        parts.append(f"EXCLUDED: {', '.join(exclusion_reasons)}.")
    else:
        parts.append("ELIGIBLE for paper review.")
    parts.append(freshness_explanation)
    parts.append(f"PIT: {pit['status']} — {pit['explanation']}")
    parts.append(
        f"Actionability: {actionability['reason_code']} — {actionability['explanation']}"
    )
    cov_pct = coverage.get("data_coverage_percent")
    cov_str = f"{cov_pct:.1f}%" if cov_pct is not None else "unknown"
    parts.append(
        f"Coverage: {coverage['coverage_status']} ({cov_str}), "
        f"missing={coverage.get('missing_feature_count') or 0}, "
        f"stale={coverage.get('stale_feature_count') or 0}."
    )
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Full quality status document
# ---------------------------------------------------------------------------


def build_quality_status(
    rows: list[dict[str, Any]],
    *,
    symbols: list[str],
    timeframes: tuple[str, ...],
    stale_seconds: int = 900,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> dict[str, Any]:
    """Build the full prediction signal quality status document.

    ``rows`` are the raw prediction rows from the all-timeframe publisher.
    Returns a dict suitable for writing to
    ``operator_runtime/prediction_quality/latest/prediction_signal_quality_status.json``.
    """
    import datetime as dt

    generated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    audit_rows = [
        audit_prediction_row(row, stale_seconds=stale_seconds, confidence_floor=confidence_floor)
        for row in rows
    ]

    total = len(audit_rows)
    fresh_count = sum(1 for r in audit_rows if r["is_fresh"])
    stale_count = total - fresh_count
    pit_clean = sum(1 for r in audit_rows if r["pit_safety"]["status"] == "CLEAN")
    pit_violations = [r for r in audit_rows if r["pit_safety"]["status"] != "CLEAN"]
    excluded = [r for r in audit_rows if r["excluded_from_paper_candidates"]]
    paper_candidates = [r for r in audit_rows if not r["excluded_from_paper_candidates"]]
    actionable = [r for r in paper_candidates if r["actionability"]["actionable"]]

    status = _overall_status(
        total=total,
        symbols=symbols,
        timeframes=timeframes,
        pit_violations=pit_violations,
        stale_count=stale_count,
    )

    symbol_grid = _build_symbol_grid(audit_rows, symbols, list(timeframes))

    return {
        "schema_version": SCHEMA_VERSION,
        "service_id": SERVICE_ID,
        "generated_at": generated_at,
        "live_gate": LIVE_GATE,
        "symbols_covered": symbols,
        "timeframes_covered": list(timeframes),
        "prediction_grid_count_expected": len(symbols) * len(timeframes),
        "prediction_grid_count_actual": total,
        "fresh_count": fresh_count,
        "stale_count": stale_count,
        "stale_threshold_seconds": stale_seconds,
        "pit_clean_count": pit_clean,
        "pit_violation_count": len(pit_violations),
        "pit_violations": [
            {
                "symbol": r["symbol"],
                "timeframe": r["timeframe"],
                "pit_status": r["pit_safety"]["status"],
                "violations": r["pit_safety"]["violations"],
                "explanation": r["pit_safety"]["explanation"],
            }
            for r in pit_violations
        ],
        "paper_candidate_count": len(paper_candidates),
        "excluded_from_paper_count": len(excluded),
        "actionable_candidate_count": len(actionable),
        "status": status,
        "symbol_grid": symbol_grid,
        "audit_rows": audit_rows,
    }


def _overall_status(
    *,
    total: int,
    symbols: list[str],
    timeframes: tuple[str, ...],
    pit_violations: list[dict[str, Any]],
    stale_count: int,
) -> str:
    expected = len(symbols) * len(timeframes)
    if not total:
        return "NO_PREDICTION_ROWS"
    if pit_violations:
        return "BLOCKED_PIT_VIOLATIONS_DETECTED"
    if total < expected:
        return "INCOMPLETE_PREDICTION_GRID"
    if stale_count > 0:
        return "PARTIAL_STALE_PREDICTIONS"
    return "PREDICTION_GRID_QUALITY_PASS"


def _build_symbol_grid(
    audit_rows: list[dict[str, Any]],
    symbols: list[str],
    timeframes: list[str],
) -> dict[str, Any]:
    """Build a per-symbol quality summary keyed by symbol."""
    grid: dict[str, Any] = {}
    for symbol in symbols:
        sym_rows = [r for r in audit_rows if r["symbol"] == symbol]
        tf_states: dict[str, str] = {}
        for row in sym_rows:
            tf = row["timeframe"]
            pit_status = row["pit_safety"]["status"]
            is_fresh = row["is_fresh"]
            actionable = row["actionability"]["actionable"]
            excluded = row["excluded_from_paper_candidates"]
            if pit_status != "CLEAN":
                tf_states[tf] = f"PIT_VIOLATION:{pit_status}"
            elif not is_fresh:
                tf_states[tf] = "STALE"
            elif excluded:
                tf_states[tf] = "EXCLUDED"
            elif actionable:
                tf_states[tf] = "ACTIONABLE"
            else:
                tf_states[tf] = "CURRENT_NON_ACTIONABLE"
        missing_tfs = sorted(set(timeframes) - set(tf_states.keys()))
        for tf in missing_tfs:
            tf_states[tf] = "MISSING"
        all_states = list(tf_states.values())
        if all(s == "ACTIONABLE" for s in all_states):
            grid_status = "ALL_ACTIONABLE"
        elif any("PIT_VIOLATION" in s for s in all_states):
            grid_status = "HAS_PIT_VIOLATIONS"
        elif all(s in ("STALE", "MISSING") for s in all_states):
            grid_status = "ALL_STALE_OR_MISSING"
        elif any(s not in ("ACTIONABLE", "CURRENT_NON_ACTIONABLE") for s in all_states):
            grid_status = "PARTIAL_ISSUES"
        else:
            grid_status = "CURRENT_MIXED_ACTIONABILITY"
        grid[symbol] = {
            "symbol": symbol,
            "grid_status": grid_status,
            "timeframe_states": tf_states,
            "missing_timeframes": missing_tfs,
        }
    return grid
